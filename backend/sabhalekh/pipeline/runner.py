"""The processing pipeline, identical for recorded and imported sessions.

    1 extract     media -> 16 kHz mono 16-bit WAV (+ Opus playback copy, waveform peaks)
    2 vad         Silero VAD: speech regions -> <= 28 s chunks (silence is never sent to Whisper)
    3 diarize     Nemotron-3-Diarization on the CPU (system track only when a mic track exists)
    4 transcribe  Nemotron 3.5 ASR (transcribe.cpp: Vulkan GPU / iGPU / CPU) or Whisper, per-chunk language, word times
    5 align       words -> speakers by maximum overlap, overlap flags, flip smoothing, sentence segments
    6 save        SQLite (+ FTS index), status, notification

Two-track recordings: the microphone track is transcribed as "You" and never diarized; the system track holds the
other participants and is diarized. Mic segments that merely repeat what the speakers played (echo without a
headset) are dropped.
"""
from __future__ import annotations

import logging
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

import numpy as np

from .. import config
from .. import text as textutil
from ..asr import ENGINES, ASROptions, ASRSegment, OutOfMemory
from ..audio import media
from ..diarization.base import NemotronEngine, SingleSpeakerFallback
from ..hardware import HardwareManager, Profile
from . import align
from .vad import language_cuts, make_chunks, speaker_turns, speech_regions, uncovered_regions

log = logging.getLogger("sabhalekh.pipeline")

STAGES = ["extract", "vad", "diarize", "transcribe", "align", "save"]
WEIGHTS = {"extract": 0.08, "vad": 0.04, "diarize": 0.18, "transcribe": 0.65, "align": 0.03, "save": 0.02}
SUPER_BATCH = 24  # chunks per engine call: progress granularity, and what an OOM retry has to redo


class Cancelled(Exception):
    pass


@dataclass
class JobParams:
    language_mode: str = "auto"
    script_mode: str = "as_spoken"
    asr_model: str = "auto"
    profile_override: str = "auto"
    initial_prompt: str = ""
    min_speakers: int | None = None
    max_speakers: int | None = None
    playback_kbps: int = 64  # Opus bitrate per channel of the playback copy


class Context:
    """What a pipeline run needs from the app: storage, hardware, models, events and cancellation."""

    def __init__(self, db, hw: HardwareManager, registry, emit: Callable[..., None],
                 cancelled: Callable[[], bool], asr_cache: dict):
        self.db, self.hw, self.registry, self.emit, self.cancelled = db, hw, registry, emit, cancelled
        self.asr_cache = asr_cache  # {"key": (model_id, device, compute), "engine": ...} kept between jobs


class Run:
    def __init__(self, ctx: Context, session_id: int, job_id: int, params: JobParams):
        self.ctx, self.sid, self.job_id, self.p = ctx, session_id, job_id, params
        self.warnings: list[str] = []
        self.stage = STAGES[0]
        self.t0 = time.time()
        self._last_emit = 0.0

    # ------------------------------------------------------------------ progress
    def _check(self):
        if self.ctx.cancelled():
            raise Cancelled()

    def progress(self, stage: str, frac: float, detail: str | None = None, force: bool = False):
        self.stage = stage
        done = sum(WEIGHTS[s] for s in STAGES[:STAGES.index(stage)])
        total = min(0.999, done + WEIGHTS[stage] * max(0.0, min(1.0, frac)))
        now = time.time()
        if not force and now - self._last_emit < 0.4:
            return
        self._last_emit = now
        elapsed = now - self.t0
        eta = elapsed / total * (1 - total) if total > 0.03 else None
        self.ctx.db.update_job(self.job_id, stage=stage, progress=total, eta_sec=eta)
        self.ctx.db.update_session(self.sid, stage=stage, progress=total)
        self.ctx.emit("job_progress", job_id=self.job_id, session_id=self.sid, stage=stage, progress=total,
                      eta_sec=eta, detail=detail)

    def warn(self, msg: str):
        log.warning("session %s: %s", self.sid, msg)
        self.warnings.append(msg)
        self.ctx.emit("job_warning", job_id=self.job_id, session_id=self.sid, message=msg)

    # ------------------------------------------------------------------ stages
    def run(self) -> None:
        db = self.ctx.db
        s = db.get_session(self.sid)
        if s is None:
            raise RuntimeError("session no longer exists")
        sdir = config.session_dir(self.sid)
        db.update_session(self.sid, status="processing", error_message=None, language_mode=self.p.language_mode,
                          script_mode=self.p.script_mode)
        self.ctx.emit("session_updated", session_id=self.sid)

        # 1 extract
        self.progress("extract", 0, force=True)
        two_track = bool(s.get("mic_track_path") and s.get("system_track_path")
                         and Path(s["mic_track_path"]).exists() and Path(s["system_track_path"]).exists())
        norm = Path(s["norm_path"]) if s.get("norm_path") else sdir / "audio_16k.wav"
        if not norm.exists():
            if s["source_type"] == "imported":
                original = Path(s["source_path"] or "")
                if not original.is_file():
                    raise RuntimeError(f"the original file was moved or deleted: {s['source_path']}")
                media.to_wav16k(original, norm, progress=lambda f: self.progress("extract", 0.7 * f),
                                cancelled=self.ctx.cancelled)
            elif two_track:
                media.mix_wavs([s["mic_track_path"], s["system_track_path"]], norm)
            else:
                raise RuntimeError("the recording's audio file is missing")
            db.update_session(self.sid, norm_path=str(norm))
        wav = media.Wav16k(norm)
        db.update_session(self.sid, duration_sec=wav.duration)
        if not (sdir / "playback.ogg").exists():
            kbps = int(self.p.playback_kbps or 64)
            try:
                if two_track:
                    stereo = sdir / "stereo_16k.wav"
                    media.write_stereo_wav(s["mic_track_path"], s["system_track_path"], stereo)
                    media.make_playback(stereo, sdir / "playback.ogg", bitrate=kbps * 1500, stereo=True,
                                        cancelled=self.ctx.cancelled)
                    stereo.unlink(missing_ok=True)
                else:
                    src = Path(s["source_path"]) if s.get("source_path") and Path(s["source_path"]).is_file() \
                        else norm
                    media.make_playback(src, sdir / "playback.ogg", bitrate=kbps * 1000,
                                        cancelled=self.ctx.cancelled)
            except InterruptedError:
                raise Cancelled()
            except Exception as e:  # noqa: BLE001 - the player falls back to the WAV
                self.warn(f"could not create the compressed playback copy ({e}); playing the WAV instead")
            pb = sdir / "playback.ogg"
            db.update_session(self.sid, audio_path=str(pb if pb.exists() else norm))
        if not (sdir / "peaks.json").exists():
            media.compute_peaks(norm, sdir / "peaks.json")
            db.update_session(self.sid, peaks_path=str(sdir / "peaks.json"))
        self.progress("extract", 1, force=True)
        self.ctx.emit("session_updated", session_id=self.sid)
        self._check()

        tracks = ([("mic", media.Wav16k(s["mic_track_path"])), ("system", media.Wav16k(s["system_track_path"]))]
                  if two_track else [("main", wav)])

        # 2 vad
        regions = {}
        total_dur = sum(t.duration for _, t in tracks) or 1
        done = 0.0
        for name, t in tracks:
            regions[name] = speech_regions(
                t.read, t.duration, progress=lambda f, d=done, td=t.duration: self.progress(
                    "vad", (d + f * td) / total_dur), cancelled=self.ctx.cancelled)
            done += t.duration
        speech_sec = sum(e - s_ for r in regions.values() for s_, e in r)
        log.info("session %s: %.0f s of speech in %.0f s of audio", self.sid, speech_sec, wav.duration)
        if two_track:
            secs = {k: sum(e - s_ for s_, e in r) for k, r in regions.items()}
            if secs["system"] < 3.0 or secs["mic"] < 1.0:
                # in-person meeting (nothing played by the PC) or muted mic: one real source, diarize it
                main = "mic" if secs["system"] < 3.0 else "system"
                log.info("session %s: only the %s track has speech, diarizing it as a single track", self.sid, main)
                tracks = [("main", dict(tracks)[main])]
                regions = {"main": regions[main]}
                two_track = False
        self.progress("vad", 1, force=True)
        self._check()

        # 3 diarize (CPU)
        profile = self.ctx.hw.profile(self.p.profile_override)
        diar_track = dict(tracks)["system" if two_track else "main"]
        act, diar_engine = self._diarize(diar_track, profile)
        self._check()

        # 4 transcribe (GPU when available)
        asr_segments: dict[str, list[ASRSegment]] = {}
        diarized_track = "system" if two_track else "main"
        cuts, profile = self._language_cuts(dict(tracks)[diarized_track], act, profile)
        chunks = {name: make_chunks(regions[name], split_at=cuts if name == diarized_track else None)
                  for name, _ in tracks}
        log.info("session %s: %d chunks (%d language cuts)", self.sid, sum(len(c) for c in chunks.values()),
                 len(cuts))
        n_total = sum(len(c) for c in chunks.values()) or 1
        n_done = 0
        model_used = None
        for name, t in tracks:
            span = len(chunks[name]) / n_total
            segs, profile, model_used = self._transcribe(t, chunks[name], profile, base=n_done / n_total,
                                                         span=span * 0.9)
            # gap fill: speech the decoder skipped (e.g. the other-language part of a chunk) is re-transcribed
            # region by region, each with its own language detection
            gaps = uncovered_regions(regions[name], [(w.start, w.end) for s in segs for w in s.words])
            if gaps:
                log.info("session %s: re-transcribing %d skipped region(s) (%.0f s) on %s", self.sid, len(gaps),
                         sum(e - s_ for s_, e in gaps), name)
                extra, profile, _ = self._transcribe(t, make_chunks(gaps, max_gap=0), profile,
                                                     base=n_done / n_total + span * 0.9, span=span * 0.1)
                segs = _replace_in_regions(segs, extra, gaps)
            asr_segments[name] = segs
            n_done += len(chunks[name])
        # Nemotron reloads in ~1 s: never hold its VRAM / shared memory while idle
        if profile.free_between_stages or getattr(self.ctx.asr_cache.get("engine"), "release_after_job", False):
            self._release_asr()
        self.progress("transcribe", 1, force=True)
        self._check()

        # 5 align
        self.progress("align", 0, force=True)
        speakers, segments, langs = self._align(asr_segments, act, two_track)
        self.progress("align", 1, force=True)

        # 6 save
        db.replace_transcript(self.sid, speakers, segments)
        db.update_session(self.sid, status="done", stage="save", progress=1.0, asr_model=model_used,
                          diarization_engine=diar_engine, profile_used=profile.label,
                          detected_languages=sorted(langs), warnings=self.warnings, error_message=None)
        self.progress("save", 1, force=True)

    # ------------------------------------------------------------------ diarization
    def _diarize(self, track: media.Wav16k, profile: Profile):
        self.progress("diarize", 0, force=True)
        m = self.ctx.registry.get("nemotron3-diarization")
        try:
            if not m or not m["available"]:
                raise RuntimeError(m["problem"] if m else "Nemotron model not installed")
            eng = NemotronEngine(m["path"], threads=profile.threads)
        except Exception as e:  # noqa: BLE001
            eng = SingleSpeakerFallback(str(e))
            self.warn(f"Speaker diarization is unavailable ({e}). All speech was attributed to one speaker.")
        try:
            probs = eng.probabilities(track.mm, progress=lambda f: self.progress("diarize", f),
                                      cancelled=self.ctx.cancelled)
        except InterruptedError:
            raise Cancelled()
        except Exception as e:  # noqa: BLE001
            log.exception("diarization failed")
            self.warn(f"Speaker diarization failed ({e}). All speech was attributed to one speaker.")
            eng = SingleSpeakerFallback(str(e))
            probs = eng.probabilities(track.mm)
        act = self._activity(probs, eng.frame_sec)
        self.progress("diarize", 1, force=True)
        return act, eng.name

    def _activity(self, probs: np.ndarray, frame_sec: float) -> align.Activity:
        act = align.activity_from_probs(probs, frame_sec)
        if self.p.min_speakers and len(act.speakers_present()) < self.p.min_speakers:
            for th in (0.4, 0.3):  # quieter speakers: accept lower activity probabilities
                trial = align.activity_from_probs(probs, frame_sec, threshold=th)
                act = trial
                if len(trial.speakers_present()) >= self.p.min_speakers:
                    break
            if len(act.speakers_present()) < self.p.min_speakers:
                self.warn(f"Found {len(act.speakers_present())} speaker(s), fewer than the minimum of "
                          f"{self.p.min_speakers} you set.")
        if self.p.max_speakers:
            act = align.limit_speakers(act, self.p.max_speakers)
        return act

    # ------------------------------------------------------------------ chunking
    def _language_cuts(self, track: media.Wav16k, act: align.Activity, profile: Profile):
        """Where chunks must be cut so one chunk never mixes languages (one language token per chunk).

        Fixed English/Hindi modes: nowhere. Auto: a short language profile per speaker (their <= 3 longest turns,
        one encoder pass each) decides; changes between two speakers of the same single language need no cut,
        speakers who mix languages (or could not be profiled) always get one. Fewer cuts = longer chunks = fewer
        30 s encoder passes (measured: 186 vs 459 chunks on an hour of alternating speakers)."""
        if self.p.language_mode in ("en", "hi"):
            return [], profile
        turns = speaker_turns(act.active, act.frame_sec)
        speakers = {t[2] for t in turns}
        if len(speakers) < 2:
            return [], profile
        samples, owners = [], []
        for spk in speakers:
            longest = sorted((t for t in turns if t[2] == spk and t[1] - t[0] >= 2.0), key=lambda t: t[0] - t[1])[:3]
            for a, b, _ in longest:
                samples.append((a, min(b, a + 28.0)))
                owners.append(spk)
        all_cuts = [s for (_, _, a), (s, _, b) in zip(turns, turns[1:]) if a != b]
        try:
            eng, _ = self._engine(profile)
            if not samples or not hasattr(eng, "detect_languages"):
                return all_cuts, profile
            probs = eng.detect_languages(track.read, samples, batch_size=profile.batch_size)
        except InterruptedError:
            raise Cancelled()
        except Exception as e:  # noqa: BLE001 - profiling is an optimization: fall back to cutting everywhere
            log.warning("speaker language profiling failed (%s); cutting at every speaker change", e)
            self._release_asr()
            return all_cuts, profile
        votes: dict[int, list[str]] = {}
        for spk, (p_en, p_hi) in zip(owners, probs):
            votes.setdefault(spk, []).append(
                "en" if p_en > 0.7 and p_en > 3 * p_hi else "hi" if p_hi > 0.7 and p_hi > 3 * p_en else "mixed")
        lang = {spk: v[0] if len(set(v)) == 1 else "mixed" for spk, v in votes.items()}
        log.info("session %s: speaker languages %s", self.sid, lang)
        return language_cuts(turns, lang), profile

    # ------------------------------------------------------------------ transcription
    def _engine(self, profile: Profile):
        translate = self.p.language_mode == "translate"
        m = self.ctx.registry.choose_asr(self.p.asr_model, translate, profile.prefer_light_model, profile.device)
        if self.p.asr_model not in ("auto", None, m["id"]):
            self.warn(f"{self.p.asr_model} is not usable for this job; using {m['label']} instead.")
        key = (m["id"], profile.device, profile.compute_type, profile.accel)
        cache = self.ctx.asr_cache
        if cache.get("key") != key:
            self._release_asr()
            cache["engine"] = ENGINES[m["engine"]](m["path"], m["id"], profile)
            cache["key"] = key
        return cache["engine"], m

    def _release_asr(self):
        eng = self.ctx.asr_cache.pop("engine", None)
        self.ctx.asr_cache.pop("key", None)
        if eng is not None:
            eng.unload()

    def _transcribe(self, track: media.Wav16k, chunks, profile: Profile, base: float, span: float):
        out: list[ASRSegment] = []
        batch = profile.batch_size
        i = 0
        model = None
        while i < len(chunks):
            self._check()
            part = chunks[i:i + SUPER_BATCH]
            try:
                eng, model = self._engine(profile)
                if profile.name == "gpu_low" and model["id"] == "whisper-large-v3-int8":
                    batch = min(batch, 2)  # measured: 3.3 GB peak at batch 2, OOM at batch 8 on a 4 GB GPU
                opts = ASROptions(language_mode=self.p.language_mode, script_mode=self.p.script_mode,
                                  initial_prompt=self.p.initial_prompt, beam_size=profile.beam_size,
                                  batch_size=batch)
                done_before = i
                segs = eng.transcribe(track.read, part, opts, cancelled=self.ctx.cancelled,
                                      progress=lambda f, d=done_before, n=len(part): self.progress(
                                          "transcribe", base + span * (d + f * n) / max(1, len(chunks)),
                                          detail=f"{model['label']} · {profile.label}"))
                out.extend(segs)
                i += len(part)
            except InterruptedError:
                raise Cancelled()
            except OutOfMemory as e:
                log.warning("OOM on %s (batch %d): %s", profile.name, batch, e)
                self._release_asr()
                if profile.device == "cuda" and batch > 1 and (model or {}).get("engine") != "transcribe-cpp":
                    batch = max(1, batch // 2)
                    self.warn(f"GPU memory is full; continuing with a smaller batch ({batch}).")
                    continue
                lighter = self.ctx.hw.downgrade(profile)
                if lighter is None:
                    raise RuntimeError("Out of memory even in the lightest CPU profile. Close other apps and "
                                       "retry.") from e
                self.warn(f"Out of memory in {profile.label} mode; switched to {lighter.label} mode.")
                profile, batch = lighter, lighter.batch_size
            except Exception as e:  # noqa: BLE001
                from ..hardware import is_cuda_error

                gpu_engine = model and model["engine"] == "transcribe-cpp" and profile.accel != "cpu"
                if (profile.device == "cuda" and is_cuda_error(e)) or (
                        gpu_engine and type(e).__name__ in ("BackendError", "ModelLoadError", "TranscribeError")):
                    log.exception("GPU failure, falling back")
                    self._release_asr()
                    lighter = self.ctx.hw.downgrade(profile)
                    while lighter and (lighter.device == "cuda" or (gpu_engine and lighter.accel != "cpu")):
                        lighter = self.ctx.hw.downgrade(lighter)
                    if lighter is None:
                        raise
                    self.warn(f"The GPU failed ({type(e).__name__}); continuing on the CPU.")
                    profile, batch = lighter, lighter.batch_size
                    continue
                raise
        return out, profile, (model["id"] if model else None)

    # ------------------------------------------------------------------ alignment
    def _words(self, segs: list[ASRSegment]) -> list[align.AWord]:
        words: list[align.AWord] = []
        roman = self.p.script_mode == "roman"
        for s in segs:
            if textutil.is_hallucination(s.text, s.end - s.start, s.no_speech_prob, s.avg_logprob):
                continue
            ws = s.words or [align.AWord(s.start, s.end, s.text, s.confidence, s.language)]
            toks = [w.text for w in ws]
            kept = _collapse_word_runs(toks)
            for idx in kept:
                w = ws[idx]
                t = w.text
                if roman and textutil.has_devanagari(t):
                    lead = " " if t.startswith(" ") else ""
                    t = lead + textutil.devanagari_to_roman(t.strip())
                words.append(align.AWord(float(w.start), float(w.end), t, float(getattr(w, "confidence", 1.0)),
                                         s.language))
        return words

    def _align(self, asr_segments: dict[str, list[ASRSegment]], act: align.Activity, two_track: bool):
        words = self._words(asr_segments.get("system" if two_track else "main", []))
        present = act.speakers_present()
        tmp_labels = {k: f"__spk{k}" for k in present}
        align.assign_speakers(words, act, tmp_labels)
        align.smooth_flips(words)
        # final labels in order of first spoken word (Speaker 1 talks first)
        order: list[str] = []
        for w in sorted(words, key=lambda x: x.start):
            if w.speaker and w.speaker not in order:
                order.append(w.speaker)
        final = {lab: f"Speaker {i + 1}" for i, lab in enumerate(order)}
        for w in words:
            w.speaker = final.get(w.speaker, "Speaker 1")
        others = align.group_segments(words)
        speakers = [{"label": final[lab]} for lab in order] or ([{"label": "Speaker 1"}] if words else [])
        segments = others
        if two_track:
            mine_words = self._words(asr_segments.get("mic", []))
            for w in mine_words:
                w.speaker = "You"
            mine = _drop_echo(align.group_segments(mine_words), others)
            align.flag_cross_track_overlaps(mine, others)
            segments = sorted(mine + others, key=lambda g: g.start)
            if mine:
                speakers = [{"label": "You", "display_name": "You", "is_self": True}] + speakers
        out = [g.as_dict() for g in segments if g.text]
        return speakers, out, {g["language"] for g in out if g["language"]}


def _replace_in_regions(segs: list[ASRSegment], extra: list[ASRSegment],
                        regions: list[tuple[float, float]]) -> list[ASRSegment]:
    """Gap fill merge: inside each region where the re-transcription found words, its words replace the few the
    first pass had there; elsewhere the first pass is kept."""
    filled = [(s, e) for s, e in regions
              if any(w.start < e and w.end > s for x in extra for w in x.words)]
    if not filled:
        return segs

    def inside(t: float) -> bool:
        return any(s <= t <= e for s, e in filled)

    def norm(t: str) -> str:
        return textutil.normalize_for_search(t).strip(".,!?।;:\"'")

    # first-pass words just outside a filled region that repeat a re-transcribed word are the same speech,
    # aligned a little late or early: drop them too
    near: list[tuple[float, float, set[str]]] = []
    for s, e in filled:
        texts = {norm(w.text) for x in extra for w in x.words if s <= (w.start + w.end) / 2 <= e}
        near.append((s - 1.0, e + 1.0, texts - {""}))

    def duplicate(w) -> bool:
        mid = (w.start + w.end) / 2
        return any(a <= mid <= b and norm(w.text) in texts for a, b, texts in near)

    out: list[ASRSegment] = []
    for seg in segs:
        if not seg.words:
            if not inside((seg.start + seg.end) / 2):
                out.append(seg)
            continue
        kept = [w for w in seg.words if not inside((w.start + w.end) / 2) and not duplicate(w)]
        if len(kept) == len(seg.words):
            out.append(seg)
        elif kept:
            out.append(ASRSegment(kept[0].start, kept[-1].end, "".join(w.text for w in kept).strip(), seg.language,
                                  kept, seg.avg_logprob, seg.no_speech_prob, seg.compression_ratio))
    out.extend(x for x in extra if any(inside((w.start + w.end) / 2) for w in x.words) or not x.words)
    return sorted(out, key=lambda s: s.start)


def _collapse_word_runs(tokens: list[str], max_repeats: int = 3) -> list[int]:
    """Indices of words to keep after collapsing a word or phrase repeated more than `max_repeats` times."""
    norm = [t.strip().lower() for t in tokens]
    keep = list(range(len(tokens)))
    for size in range(1, 7):
        out, i = [], 0
        seq = [norm[k] for k in keep]
        while i < len(keep):
            unit = seq[i:i + size]
            reps, j = 1, i + size
            while len(unit) == size and seq[j:j + size] == unit:
                reps += 1
                j += size
            if reps > max_repeats:
                out.extend(keep[i:i + size * max_repeats])
                i = j
            else:
                out.append(keep[i])
                i += 1
        keep = out
    return keep


def _drop_echo(mine: list[align.Segment], others: list[align.Segment], sim: float = 0.6) -> list[align.Segment]:
    """Without a headset the mic hears the meeting: drop 'You' segments that repeat overlapping system speech."""
    def toks(seg):
        return {textutil.normalize_for_search(w.text) for w in seg.words if len(w.text.strip()) > 1}

    kept = []
    for m in mine:
        mt = toks(m)
        echo = False
        for o in others:
            if o.end < m.start - 1 or o.start > m.end + 1 or not mt:
                continue
            ot = toks(o)
            if ot and len(mt & ot) / len(mt) >= sim:
                echo = True
                break
        if not echo:
            kept.append(m)
    return kept


def params_from(settings: dict, overrides: dict | None = None) -> JobParams:
    p = JobParams(language_mode=settings.get("language_mode", "auto"),
                  script_mode=settings.get("script_mode", "as_spoken"),
                  asr_model=settings.get("asr_model", "auto"),
                  profile_override=settings.get("profile_override", "auto"),
                  initial_prompt=settings.get("initial_prompt", "") or "",
                  min_speakers=settings.get("min_speakers"), max_speakers=settings.get("max_speakers"),
                  playback_kbps=int(settings.get("playback_kbps") or 64))
    for k, v in (overrides or {}).items():
        if hasattr(p, k) and v is not None:
            setattr(p, k, v)
    return p


def params_dict(p: JobParams) -> dict:
    return asdict(p)
