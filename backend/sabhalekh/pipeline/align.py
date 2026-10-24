"""Speaker activity -> word speakers -> transcript segments.

1. `activity_from_probs`: threshold the diarizer's per-frame speaker probabilities, close short gaps, drop blips.
2. `assign_speakers`: each ASR word gets the speaker whose activity overlaps it most (ties: higher mean
   probability); words in diarizer silence take the nearest active speaker; words covered by two or more speakers
   for most of their duration are flagged as overlapping speech.
3. `smooth_flips`: runs of words shorter than ~0.3 s between two runs of the same other speaker are reassigned.
4. `group_segments`: words become sentence/paragraph segments {speaker, start, end, text, language, confidence,
   overlap, words}, split on speaker or language change, long pauses and sentence ends of long paragraphs.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

SENTENCE_END = (".", "?", "!", "।", "॥", "。", "？", "！")


@dataclass
class AWord:
    start: float
    end: float
    text: str
    confidence: float = 1.0
    language: str = "en"
    speaker: str | None = None
    overlap: bool = False


@dataclass
class Activity:
    """Binary per-frame activity (frames, speakers) after smoothing, at `frame_sec` resolution."""
    active: np.ndarray
    probs: np.ndarray
    frame_sec: float

    @property
    def num_speakers(self) -> int:
        return int(self.active.shape[1]) if self.active.ndim == 2 else 0

    def speakers_present(self) -> list[int]:
        return [k for k in range(self.num_speakers) if self.active[:, k].any()]


def _runs(mask: np.ndarray) -> list[tuple[int, int]]:
    d = np.diff(np.concatenate([[0], mask.astype(np.int8), [0]]))
    return list(zip(np.flatnonzero(d == 1), np.flatnonzero(d == -1)))


def activity_from_probs(probs: np.ndarray, frame_sec: float = 0.01, threshold: float = 0.5,
                        merge_gap: float = 0.3, min_dur: float = 0.1) -> Activity:
    active = probs > threshold
    gap, mind = int(round(merge_gap / frame_sec)), int(round(min_dur / frame_sec))
    for k in range(active.shape[1]):
        col = active[:, k]
        runs = _runs(col)
        for (s0, e0), (s1, _) in zip(runs, runs[1:]):
            if s1 - e0 <= gap:
                col[e0:s1] = True
        for s, e in _runs(col):
            if e - s < mind:
                col[s:e] = False
    return Activity(active, probs, frame_sec)


def limit_speakers(act: Activity, max_speakers: int | None) -> Activity:
    """Keep the `max_speakers` most active speakers; frames of the others go to the most probable kept one."""
    present = act.speakers_present()
    if not max_speakers or len(present) <= max_speakers:
        return act
    talk = {k: act.active[:, k].sum() for k in present}
    keep = sorted(sorted(present, key=lambda k: -talk[k])[:max_speakers])
    drop = [k for k in present if k not in keep]
    active = act.active.copy()
    for k in drop:
        frames = np.flatnonzero(active[:, k])
        if len(frames):
            best = np.array(keep)[np.argmax(act.probs[np.ix_(frames, keep)], axis=1)]
            active[frames, best] = True
        active[:, k] = False
    return Activity(active, act.probs, act.frame_sec)


def assign_speakers(words: list[AWord], act: Activity, label_of: dict[int, str],
                    nearest_within: float = 2.0) -> list[AWord]:
    n_frames = act.active.shape[0]
    present = act.speakers_present()
    if not present:
        return words
    centers = {k: np.flatnonzero(act.active[:, k]) for k in present}
    for w in words:
        f0 = max(0, min(n_frames - 1, int(np.floor(w.start / act.frame_sec))))
        f1 = max(f0 + 1, min(n_frames, int(np.ceil(w.end / act.frame_sec))))
        block = act.active[f0:f1]
        overlap = block.sum(axis=0)
        if overlap.max() > 0:
            best = np.flatnonzero(overlap == overlap.max())
            if len(best) > 1:
                best = best[np.argmax(act.probs[f0:f1, best].mean(axis=0))]
            else:
                best = best[0]
            w.speaker = label_of[int(best)]
            multi = (block.sum(axis=1) >= 2).mean()
            w.overlap = bool(multi > 0.5)
        else:
            mid = (f0 + f1) // 2
            dist = {k: np.abs(c - mid).min() for k, c in centers.items() if len(c)}
            k = min(dist, key=dist.get)
            if dist[k] * act.frame_sec <= nearest_within:
                w.speaker = label_of[k]
    # words still without a speaker inherit from their neighbours
    last = None
    for w in words:
        if w.speaker is None:
            w.speaker = last
        last = w.speaker
    nxt = None
    for w in reversed(words):
        if w.speaker is None:
            w.speaker = nxt
        nxt = w.speaker
    return words


def smooth_flips(words: list[AWord], min_run: float = 0.3) -> list[AWord]:
    """A short run of one speaker sandwiched between runs of another speaker is a flip: reassign it."""
    if len(words) < 3:
        return words
    changed = True
    while changed:
        changed = False
        runs: list[list[int]] = []
        for i, w in enumerate(words):
            if runs and words[runs[-1][0]].speaker == w.speaker:
                runs[-1].append(i)
            else:
                runs.append([i])
        for j in range(1, len(runs) - 1):
            r = runs[j]
            dur = words[r[-1]].end - words[r[0]].start
            before, after = words[runs[j - 1][0]].speaker, words[runs[j + 1][0]].speaker
            if before == after and dur < min_run and not any(words[i].overlap for i in r):
                for i in r:
                    words[i].speaker = before
                changed = True
                break
    return words


@dataclass
class Segment:
    speaker: str | None
    start: float
    end: float
    words: list[AWord] = field(default_factory=list)

    @property
    def text(self) -> str:
        return "".join(w.text if w.text.startswith(" ") or i == 0 else " " + w.text
                       for i, w in enumerate(self.words)).strip()

    def as_dict(self) -> dict:
        langs = [w.language for w in self.words]
        return {"speaker": self.speaker, "start": round(self.start, 3), "end": round(self.end, 3),
                "text": self.text, "language": max(set(langs), key=langs.count) if langs else None,
                "confidence": round(float(np.mean([w.confidence for w in self.words])), 4) if self.words else None,
                "overlap": any(w.overlap for w in self.words),
                "words": [{"start": round(w.start, 3), "end": round(w.end, 3), "text": w.text.strip(),
                           "confidence": round(w.confidence, 4)} for w in self.words]}


def group_segments(words: list[AWord], max_gap: float = 1.5, soft_max: float = 12.0,
                   hard_max: float = 30.0) -> list[Segment]:
    segs: list[Segment] = []
    for w in sorted(words, key=lambda x: x.start):
        cur = segs[-1] if segs else None
        new = (
            cur is None
            or w.speaker != cur.speaker
            or w.language != cur.words[-1].language
            or w.start - cur.end > max_gap
            or w.end - cur.start > hard_max
            or (cur.end - cur.start > soft_max and cur.words[-1].text.strip().endswith(SENTENCE_END))
        )
        if new:
            segs.append(Segment(w.speaker, w.start, w.end, [w]))
        else:
            cur.words.append(w)
            cur.end = max(cur.end, w.end)
    return segs


def flag_cross_track_overlaps(a: list[Segment], b: list[Segment], min_overlap: float = 0.5) -> None:
    """Two-track recordings: mark segments of 'You' and of the others that are spoken at the same time."""
    j = 0
    for s in a:
        while j < len(b) and b[j].end <= s.start:
            j += 1
        k = j
        while k < len(b) and b[k].start < s.end:
            if min(s.end, b[k].end) - max(s.start, b[k].start) >= min_overlap:
                for w in s.words:
                    if any(min(w.end, x.end) > max(w.start, x.start) for x in b[k].words):
                        w.overlap = True
                for w in b[k].words:
                    if any(min(w.end, x.end) > max(w.start, x.start) for x in s.words):
                        w.overlap = True
            k += 1


def label_speakers(act: Activity, used: list[int]) -> dict[int, str]:
    """Speakers in arrival order (Nemotron already orders them by first appearance): Speaker 1, Speaker 2, ..."""
    first = {k: int(np.flatnonzero(act.active[:, k])[0]) if act.active[:, k].any() else 1 << 30 for k in used}
    return {k: f"Speaker {i + 1}" for i, k in enumerate(sorted(used, key=lambda k: first[k]))}
