"""Silero VAD (v6, ONNX, bundled with faster-whisper) over long audio in blocks, then speech chunks for ASR."""
from __future__ import annotations

from typing import Callable

import numpy as np

SR = 16000
BLOCK_SEC = 600.0
MAX_CHUNK_SEC = 28.0


def speech_regions(read: Callable[[float, float], np.ndarray], duration: float, threshold: float = 0.5,
                   progress: Callable[[float], None] | None = None,
                   cancelled: Callable[[], bool] | None = None) -> list[tuple[float, float]]:
    """Speech (start, end) in seconds. Processes 10-minute blocks so memory stays flat for 3 h recordings."""
    from faster_whisper.vad import VadOptions, get_speech_timestamps

    opts = VadOptions(threshold=threshold, min_speech_duration_ms=250, max_speech_duration_s=MAX_CHUNK_SEC,
                      min_silence_duration_ms=500, speech_pad_ms=200)
    regions: list[tuple[float, float]] = []
    t = 0.0
    while t < duration:
        if cancelled and cancelled():
            raise InterruptedError("cancelled")
        end = min(duration, t + BLOCK_SEC)
        block = read(t, end)
        for r in get_speech_timestamps(block, opts):
            s, e = t + r["start"] / SR, t + r["end"] / SR
            if regions and s - regions[-1][1] < 0.3 and e - regions[-1][0] <= MAX_CHUNK_SEC:
                regions[-1] = (regions[-1][0], e)  # speech cut by a block boundary
            else:
                regions.append((s, e))
        t = end
        if progress:
            progress(t / duration)
    return regions


def make_chunks(regions: list[tuple[float, float]], max_len: float = MAX_CHUNK_SEC, max_gap: float = 1.5,
                split_at: list[float] | None = None, min_piece: float = 0.6) -> list[tuple[float, float]]:
    """Speech chunks (<= `max_len` s) for batched decoding.

    A chunk is decoded with one language token, and Whisper silently drops the part of a chunk spoken in the other
    language (measured on an English/Hindi turn-taking clip). Language switches mostly come with a change of
    speaker, so chunks are cut at diarization speaker changes (`split_at`) and neighbouring regions are merged
    (gap <= `max_gap`) only while the same speaker continues. Fewer, longer chunks keep decoding fast: every chunk
    costs one 30 s encoder pass. What a merged chunk still misses is re-transcribed by the ASR gap-fill pass.
    """
    cuts = sorted(split_at or [])
    pieces: list[list[float]] = []
    for s, e in regions:
        inner = [c for c in cuts if s + min_piece <= c <= e - min_piece]
        bounds = [s] + inner + [e]
        for a, b in zip(bounds, bounds[1:]):
            while b - a > max_len:  # VAD already caps regions; this is a safety net
                pieces.append([a, a + max_len])
                a += max_len
            pieces.append([a, b])

    def change_between(t0: float, t1: float) -> bool:
        return any(t0 - 0.25 <= c <= t1 + 0.25 for c in cuts)

    chunks: list[list[float]] = []
    for a, b in pieces:
        if (chunks and 0 <= a - chunks[-1][1] <= max_gap and b - chunks[-1][0] <= max_len
                and not change_between(chunks[-1][1], a)):
            chunks[-1][1] = b
        else:
            chunks.append([a, b])
    return [(round(a, 3), round(b, 3)) for a, b in chunks]


def uncovered_regions(regions: list[tuple[float, float]], words: list[tuple[float, float]],
                      min_len: float = 0.8, max_cover: float = 0.25, margin: float = 0.3) -> list[tuple[float, float]]:
    """Speech regions (>= min_len s) that the transcript's words barely cover: skipped speech to re-transcribe.
    Word timestamps can be a few hundred ms off, so words within `margin` of a region count for it."""
    out = []
    ws = sorted(words)
    j = 0
    for s, e in regions:
        if e - s < min_len:
            continue
        a, b = s - margin, e + margin
        while j < len(ws) and ws[j][1] <= a:
            j += 1
        cov, k = 0.0, j
        while k < len(ws) and ws[k][0] < b:
            cov += max(0.0, min(b, ws[k][1]) - max(a, ws[k][0]))
            k += 1
        if cov / (e - s) < max_cover:
            out.append((s, e))
    return out


def speaker_turns(active, frame_sec: float, min_len: float = 0.3) -> list[tuple[float, float, int]]:
    """(start, end, speaker) runs of the dominant active speaker, shorter runs folded into their neighbours."""
    import numpy as np

    if active is None or active.size == 0:
        return []
    any_active = active.any(axis=1)
    dom = np.where(any_active, active.argmax(axis=1), -1)
    turns: list[list] = []
    for i in np.flatnonzero(any_active):
        t = i * frame_sec
        if turns and turns[-1][2] == dom[i] and t - turns[-1][1] <= 1.0:
            turns[-1][1] = t + frame_sec
        else:
            turns.append([t, t + frame_sec, int(dom[i])])
    merged: list[list] = []
    for t in turns:
        if merged and (t[1] - t[0] < min_len or merged[-1][2] == t[2]):
            merged[-1][1] = t[1]
        else:
            merged.append(t)
    return [(round(a, 3), round(b, 3), s) for a, b, s in merged]


def language_cuts(turns: list[tuple[float, float, int]], speaker_lang: dict[int, str]) -> list[float]:
    """Speaker changes where the language may change: between speakers whose language differs or is 'mixed'
    (or unknown). Changes between two speakers of the same single language need no cut."""
    cuts = []
    for (_, _, a), (s, _, b) in zip(turns, turns[1:]):
        la, lb = speaker_lang.get(a, "mixed"), speaker_lang.get(b, "mixed")
        if a != b and (la != lb or la == "mixed"):
            cuts.append(s)
    return cuts


def speaker_changes(active, frame_sec: float) -> list[float]:
    """Times where the dominant active speaker changes (from a diarization activity matrix)."""
    import numpy as np

    if active is None or active.size == 0:
        return []
    any_active = active.any(axis=1)
    dom = np.where(any_active, active.argmax(axis=1), -1)
    out, last = [], -1
    for i in np.flatnonzero(any_active):
        if last not in (-1, dom[i]):
            out.append(round(i * frame_sec, 3))
        last = dom[i]
    return out
