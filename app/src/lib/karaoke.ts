/** Playback sync: which segment and word are being spoken at time t (binary search, O(log n)). */
import type { Segment } from "./types";

export function activeSegmentIndex(segments: Segment[], t: number): number {
  let lo = 0;
  let hi = segments.length - 1;
  let best = -1;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    if (segments[mid].start_sec <= t) {
      best = mid;
      lo = mid + 1;
    } else hi = mid - 1;
  }
  if (best < 0) return -1;
  // within the segment, or in a short pause right after it
  return t <= segments[best].end_sec + 0.35 ? best : -1;
}

export function activeWordIndex(seg: Segment | undefined, t: number): number {
  if (!seg || !seg.words.length || seg.edited_text !== null) return -1;
  const w = seg.words;
  let lo = 0;
  let hi = w.length - 1;
  let best = -1;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    if (w[mid].start <= t) {
      best = mid;
      lo = mid + 1;
    } else hi = mid - 1;
  }
  return best;
}

/** Map a caret offset in a segment's text to the word index it falls before (for word-exact splits). */
export function wordIndexAtChar(seg: Segment, charOffset: number): number | null {
  if (seg.edited_text !== null || !seg.words.length) return null;
  let pos = 0;
  const text = seg.display_text;
  for (let i = 0; i < seg.words.length; i++) {
    const w = seg.words[i].text.trim();
    const at = text.indexOf(w, pos);
    if (at < 0) return null;
    if (charOffset <= at && i > 0) return i;
    pos = at + w.length;
  }
  return null;
}
