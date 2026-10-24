"""Whisper on CTranslate2 (faster-whisper 1.2.x building blocks), batched, with per-chunk English/Hindi routing.

Why not `BatchedInferencePipeline.transcribe` as is: its per-chunk language detection picks the top language among
all 99, so Hindi often comes out in Urdu script, and it does not report which language each chunk got. Here the
same single encoder pass is used to score only English vs Hindi (+Urdu, the same spoken language), the language
token is set per chunk, and the chosen language is returned with every segment.
"""
from __future__ import annotations

import logging
import zlib
from math import ceil
from typing import Callable, Sequence

import numpy as np

from .base import ASROptions, ASRSegment, AudioReader, Chunk, OutOfMemory, Word

log = logging.getLogger("sabhalekh.asr")

PREPEND_PUNCT = "\"'“¿([{-"
APPEND_PUNCT = "\"'.。,，!！?？:：”)]}、।"


# Whisper copies the writing style of its prompt. Without one, the English words of Hinglish speech come out as
# phonetic Devanagari ("कोश्चिन", "पॉसिटिव"), inconsistently; with a mixed-script prompt they stay in English
# ("question", "positive"). Used for Hindi chunks only; English chunks would be pushed into Devanagari.
STYLE_PROMPTS = {
    "as_spoken": "ठीक है, तो आज की meeting में हम project का status और next steps discuss करेंगे।",
    "roman": "ठीक है, तो आज की meeting में हम project का status और next steps discuss करेंगे।",
    "devanagari": "ठीक है, तो आज की मीटिंग में हम प्रोजेक्ट का स्टेटस और नेक्स्ट स्टेप्स डिस्कस करेंगे।",
}


def _compression_ratio(text: str) -> float:
    b = text.encode("utf-8")
    return len(b) / max(1, len(zlib.compress(b)))


def _words(text: str) -> list[str]:
    return [w for w in (t.strip(".,!?।|\"'()") for t in text.lower().split()) if w]


def echoes_prompt(text: str, prompt: str, n: int = 4) -> bool:
    """True if the output repeats a run of n prompt words: on unclear audio Whisper sometimes writes the prompt
    instead of the speech."""
    p = _words(prompt)
    grams = {tuple(p[i:i + n]) for i in range(len(p) - n + 1)}
    t = _words(text)
    return any(tuple(t[i:i + n]) in grams for i in range(len(t) - n + 1))


class WhisperCT2Engine:
    name = "faster-whisper"

    def __init__(self, model_path: str, model_id: str, device: str = "cpu", compute_type: str = "int8",
                 threads: int = 4):
        self.model_path, self.model_id = model_path, model_id
        self.device, self.compute_type, self.threads = device, compute_type, threads
        self.model = None
        self._last_lang: str | None = None

    # ------------------------------------------------------------------ lifecycle
    def load(self) -> None:
        if self.model is not None:
            return
        from faster_whisper import WhisperModel

        try:
            self.model = WhisperModel(self.model_path, device=self.device, compute_type=self.compute_type,
                                      cpu_threads=self.threads, num_workers=1, local_files_only=True)
        except Exception as e:  # noqa: BLE001
            from ..hardware import is_oom_error

            if is_oom_error(e):
                raise OutOfMemory(str(e)) from e
            raise
        log.info("loaded %s on %s (%s)", self.model_id, self.device, self.compute_type)

    def unload(self) -> None:
        if self.model is not None:
            try:
                self.model.model.unload_model()
            except Exception:  # noqa: BLE001
                pass
            self.model = None
        from ..hardware import free_gpu_memory

        free_gpu_memory()

    @property
    def translate_ok(self) -> bool:
        return "turbo" not in self.model_id  # large-v3-turbo was not trained for translation

    # ------------------------------------------------------------------ helpers
    def _tokenizer(self, task: str, language: str):
        from faster_whisper.tokenizer import Tokenizer

        return Tokenizer(self.model.hf_tokenizer, True, task=task, language=language)

    def detect_languages(self, read: AudioReader, chunks: Sequence[Chunk], batch_size: int = 4
                         ) -> list[tuple[float, float]]:
        """(p_english, p_hindi incl. Urdu) for each chunk: one encoder pass per chunk, no decoding."""
        from faster_whisper.audio import pad_or_trim

        from ..hardware import is_oom_error

        self.load()
        m = self.model
        out: list[tuple[float, float]] = []
        try:
            for b0 in range(0, len(chunks), batch_size):
                feats = np.stack([pad_or_trim(m.feature_extractor(read(s, e))[..., :-1])
                                  for s, e in chunks[b0:b0 + batch_size]])
                for langs in m.model.detect_language(m.encode(feats)):
                    p = {tok[2:-2]: prob for tok, prob in langs}
                    out.append((p.get("en", 0.0), p.get("hi", 0.0) + p.get("ur", 0.0)))
        except Exception as e:  # noqa: BLE001
            if is_oom_error(e):
                raise OutOfMemory(f"{type(e).__name__}: {e}") from e
            raise
        return out

    def _choose_languages(self, encoder_output, options: ASROptions) -> list[str]:
        """English or Hindi per chunk. Unclear chunks (short, noisy) follow a confident neighbour, else Hindi:
        decoding English speech with the Hindi token still yields the English words, whereas decoding Hindi speech
        with the English token silently translates it."""
        out: list[str | None] = []
        for langs in self.model.model.detect_language(encoder_output):
            p = {tok[2:-2]: prob for tok, prob in langs}
            p_en, p_hi = p.get("en", 0.0), p.get("hi", 0.0) + p.get("ur", 0.0)  # Urdu = spoken Hindi
            if p_en + p_hi < 0.15:
                out.append(None)
            else:
                # Hinglish often scores as English; decoded as English its Hindi words are dropped or translated.
                # Decoded as Hindi (with the style prompt) its English words stay English, so only confidently
                # English chunks get the English token.
                out.append("en" if p_en > 0.85 and p_en > 4 * p_hi else "hi")
        for i, lang in enumerate(out):
            if lang is None:
                near = [out[j] for j in sorted(range(len(out)), key=lambda j: abs(j - i)) if out[j]]
                out[i] = self._last_lang or (near[0] if near else "hi")
            self._last_lang = out[i]
        return out  # type: ignore[return-value]

    def _generate(self, enc, prompts: list[list[int]], **kw) -> list:
        """CTranslate2 needs every prompt in one generate call to have the same length; chunks with different
        prompts (Hindi with the style prompt, English without) are generated per group from a slice of the same
        encoder output, so no audio is encoded twice."""
        groups: dict[tuple, list[int]] = {}
        for i, p in enumerate(prompts):
            groups.setdefault(tuple(p), []).append(i)
        if len(groups) == 1:
            return self.model.model.generate(enc, prompts, **kw)
        import ctranslate2

        host = np.array(enc.to_device(ctranslate2.Device.cpu))
        out: list = [None] * len(prompts)
        for p, idx in groups.items():
            sub = ctranslate2.StorageView.from_array(np.ascontiguousarray(host[idx]))
            for i, r in zip(idx, self.model.model.generate(sub, [list(p)] * len(idx), **kw)):
                out[i] = r
        return out

    # ------------------------------------------------------------------ transcription
    def _decode(self, feats: np.ndarray, batch: list[Chunk], langs: list[str], task: str,
                options: ASROptions, enc=None) -> list[list[dict]]:
        """Decode one batch (encoder pass unless given, generation, word alignment) with a language per chunk."""
        from faster_whisper.transcribe import get_suppressed_tokens

        m = self.model
        enc = enc if enc is not None else m.encode(feats)
        tok_by_lang = {lang: self._tokenizer(task, lang) for lang in set(langs)}
        user = options.initial_prompt.strip()
        style = STYLE_PROMPTS.get(options.script_mode, "") if task == "transcribe" else ""

        def prompt(lang: str, with_style: bool) -> list[int]:
            text = " ".join(p for p in (style if with_style and lang == "hi" else "", user) if p)
            prev = tok_by_lang[lang].encode(" " + text) if text else []
            return m.get_prompt(tok_by_lang[lang], prev[-223:], without_timestamps=True)

        prompts = [prompt(lang, True) for lang in langs]
        suppress = get_suppressed_tokens(tok_by_lang[langs[0]], [-1])
        gen = self._generate(enc, prompts, beam_size=options.beam_size, patience=1.0, length_penalty=1.0,
                               max_length=m.max_length, suppress_blank=True, suppress_tokens=suppress,
                               return_scores=True, return_no_speech_prob=True, sampling_temperature=1.0,
                               repetition_penalty=1.0, no_repeat_ngram_size=0)
        # outputs that repeat the style prompt are re-decoded without it
        text_of = [tok_by_lang[langs[i]].decode(r.sequences_ids[0]) for i, r in enumerate(gen)]
        echo = [i for i, t in enumerate(text_of) if style and langs[i] == "hi" and echoes_prompt(t, style)]
        if echo:
            prompts = [prompt(lang, i not in echo) for i, lang in enumerate(langs)]
            regen = self._generate(enc, prompts, beam_size=options.beam_size, patience=1.0, length_penalty=1.0,
                                     max_length=m.max_length, suppress_blank=True, suppress_tokens=suppress,
                                     return_scores=True, return_no_speech_prob=True)
            for i in echo:
                gen[i] = regen[i]
                text_of[i] = tok_by_lang[langs[i]].decode(regen[i].sequences_ids[0])
            log.info("re-decoded %d chunk(s) that repeated the style prompt", len(echo))
        # repetitive (hallucinating) outputs get one stricter re-decode
        retry = [i for i, t in enumerate(text_of) if _compression_ratio(t) > 2.4]
        if retry:
            regen = self._generate(enc, prompts, beam_size=options.beam_size, max_length=m.max_length,
                                     suppress_blank=True, suppress_tokens=suppress, return_scores=True,
                                     return_no_speech_prob=True, repetition_penalty=1.15, no_repeat_ngram_size=4)
            for i in retry:
                gen[i] = regen[i]
        seg_lists, sizes = [], []
        for i, r in enumerate(gen):
            tok = tok_by_lang[langs[i]]
            start, end = batch[i]
            duration = end - start
            size = int(ceil(duration) * m.frames_per_second)
            tokens = r.sequences_ids[0]
            avg_lp = r.scores[0] * len(tokens) / (len(tokens) + 1)
            subs, _, _ = m._split_segments_by_timestamps(tokenizer=tok, tokens=tokens, time_offset=start,
                                                         segment_size=size, segment_duration=duration, seek=0)
            if not subs:
                subs = [dict(tokens=[], start=start, end=end)]
            seg_lists.append([dict(text=tok.decode(s["tokens"]), tokens=s["tokens"], start=s["start"], end=s["end"],
                                   avg_logprob=avg_lp, no_speech_prob=r.no_speech_prob, language=langs[i],
                                   seek=int(round(start * m.frames_per_second))) for s in subs])
            sizes.append(size)
        # English and Hindi are both space-delimited, so one alignment pass serves the whole batch
        majority = max(set(langs), key=langs.count)
        self._last_speech = m.add_word_timestamps(seg_lists, tok_by_lang[majority], enc, sizes, PREPEND_PUNCT,
                                                  APPEND_PUNCT, self._last_speech) or self._last_speech
        return seg_lists

    @staticmethod
    def _coverage(segs: list[dict], chunk: Chunk) -> float:
        """Share of the chunk covered by aligned words (a chunk whose speech was skipped scores low)."""
        dur = max(1e-3, chunk[1] - chunk[0])
        words = [w for s in segs for w in (s.get("words") or [])]
        if not words:
            return 0.0 if not any(s["text"].strip() for s in segs) else 0.5
        covered = sum(max(0.0, w["end"] - w["start"]) for w in words)
        return min(1.0, covered / dur)

    def transcribe(self, read: AudioReader, chunks: Sequence[Chunk], options: ASROptions,
                   progress: Callable[[float], None] | None = None,
                   cancelled: Callable[[], bool] | None = None) -> list[ASRSegment]:
        from faster_whisper.audio import pad_or_trim

        from ..hardware import is_oom_error

        self.load()
        m = self.model
        task = "translate" if options.language_mode == "translate" else "transcribe"
        fixed = {"en": "en", "hi": "hi"}.get(options.language_mode)
        results: list[ASRSegment] = []
        self._last_speech = 0.0
        self._last_lang = None
        bs = max(1, options.batch_size)
        total = len(chunks)
        for b0 in range(0, total, bs):
            if cancelled and cancelled():
                raise InterruptedError("cancelled")
            batch = list(chunks[b0:b0 + bs])
            try:
                feats = np.stack([pad_or_trim(m.feature_extractor(read(s, e))[..., :-1]) for s, e in batch])
                enc = m.encode(feats)
                langs = [fixed] * len(batch) if fixed else self._choose_languages(enc, options)
                seg_lists = self._decode(feats, batch, langs, task, options, enc=enc)
                if not fixed and task == "transcribe":
                    # safety net: a chunk whose speech was mostly skipped is re-decoded in the other language
                    weak = [i for i, segs in enumerate(seg_lists)
                            if batch[i][1] - batch[i][0] >= 1.5 and self._coverage(segs, batch[i]) < 0.35]
                    if weak:
                        alt = self._decode(feats[weak], [batch[i] for i in weak],
                                           ["hi" if langs[i] == "en" else "en" for i in weak], task, options)
                        for i, segs in zip(weak, alt):
                            if self._coverage(segs, batch[i]) > self._coverage(seg_lists[i], batch[i]) + 0.15:
                                seg_lists[i] = segs
                for segs in seg_lists:
                    for s in segs:
                        words = [Word(float(w["start"]), float(w["end"]), w["word"], float(w["probability"]))
                                 for w in s.get("words") or []]
                        text = "".join(w.text for w in words).strip() if words else s["text"].strip()
                        if not text:
                            continue
                        results.append(ASRSegment(start=float(s["start"]), end=float(s["end"]), text=text,
                                                  language="en" if task == "translate" else s["language"],
                                                  words=words, avg_logprob=float(s["avg_logprob"]),
                                                  no_speech_prob=float(s["no_speech_prob"]),
                                                  compression_ratio=_compression_ratio(text)))
            except InterruptedError:
                raise
            except Exception as e:  # noqa: BLE001
                if is_oom_error(e):
                    raise OutOfMemory(f"{type(e).__name__}: {e}") from e
                raise
            if progress:
                progress(min(1.0, (b0 + len(batch)) / max(1, total)))
        return results
