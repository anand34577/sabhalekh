import { describe, expect, it } from "vitest";
import { clock, searchNorm } from "./format";
import { activeSegmentIndex, activeWordIndex, wordIndexAtChar } from "./karaoke";
import type { Segment } from "./types";

const seg = (id: number, s: number, e: number, words: [number, number, string][] = [], edited: string | null = null):
  Segment => ({
  id, session_id: 1, speaker_id: 1, original_speaker_id: 1, start_sec: s, end_sec: e,
  text: words.map((w) => w[2]).join(" "), edited_text: edited,
  display_text: edited ?? words.map((w) => w[2]).join(" "), language: "en", confidence: 1, overlap_flag: 0,
  words: words.map(([a, b, t]) => ({ start: a, end: b, text: t, confidence: 1 })),
});

const segs = [
  seg(1, 0, 4, [[0, 0.5, "Let's"], [0.5, 1, "start"], [1, 1.4, "with"], [1.4, 1.8, "the"], [1.8, 4, "budget."]]),
  seg(2, 4.5, 9, [[4.5, 5.2, "हम"], [5.3, 6, "अगले"], [6.1, 7, "क्वार्टर"]]),
  seg(3, 12, 15),
];

describe("karaoke sync", () => {
  it("finds the active segment", () => {
    expect(activeSegmentIndex(segs, 0.2)).toBe(0);
    expect(activeSegmentIndex(segs, 4.2)).toBe(0); // short pause after a segment keeps it lit
    expect(activeSegmentIndex(segs, 6)).toBe(1);
    expect(activeSegmentIndex(segs, 10.5)).toBe(-1); // silence
    expect(activeSegmentIndex(segs, -1)).toBe(-1);
  });
  it("finds the active word", () => {
    expect(activeWordIndex(segs[0], 1.5)).toBe(3);
    expect(activeWordIndex(segs[1], 6.5)).toBe(2);
    expect(activeWordIndex(seg(9, 0, 1, [[0, 1, "x"]], "edited"), 0.5)).toBe(-1); // edited text has no word timing
  });
  it("maps a caret to a word boundary for splitting", () => {
    expect(wordIndexAtChar(segs[0], 12)).toBe(2); // before "with"
    expect(wordIndexAtChar(segs[1], segs[1].display_text.indexOf("क्वार्टर"))).toBe(2);
  });
});

describe("format", () => {
  it("formats clocks", () => {
    expect(clock(83)).toBe("01:23");
    expect(clock(3723)).toBe("01:02:03");
  });
  it("normalizes Hindi for search like the backend", () => {
    expect(searchNorm("ज़रूर")).toBe(searchNorm("जरूर"));
    expect(searchNorm("दूँगा".normalize("NFD"))).toBe(searchNorm("दूँगा"));
  });
});
