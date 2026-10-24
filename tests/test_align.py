import numpy as np

from sabhalekh.pipeline import align
from sabhalekh.pipeline.runner import _collapse_word_runs, _drop_echo


def probs_from(turns, n_spk=8, dur=20.0, fs=0.01, p=0.9):
    n = int(dur / fs)
    pr = np.full((n, n_spk), 0.02, np.float32)
    for spk, s, e in turns:
        pr[int(s / fs):int(e / fs), spk] = p
    return pr


def W(s, e, t, lang="en"):
    return align.AWord(s, e, t, 0.9, lang)


def test_activity_merges_short_gaps_and_drops_blips():
    pr = probs_from([(0, 0.0, 2.0), (0, 2.2, 4.0), (1, 6.0, 6.05)])
    act = align.activity_from_probs(pr)
    assert act.active[int(2.1 / 0.01), 0]  # 0.2 s gap closed
    assert not act.active[:, 1].any()  # 50 ms blip removed
    assert act.speakers_present() == [0]


def test_assign_by_maximum_overlap():
    act = align.activity_from_probs(probs_from([(0, 0.0, 3.0), (1, 3.0, 6.0)]))
    words = [W(0.5, 1.0, " hello"), W(2.8, 3.6, " there"), W(4.0, 4.5, " friend")]
    align.assign_speakers(words, act, {0: "A", 1: "B"})
    assert [w.speaker for w in words] == ["A", "B", "B"]  # 'there' overlaps B for 0.6 s vs A 0.2 s


def test_words_in_silence_take_nearest_speaker():
    act = align.activity_from_probs(probs_from([(0, 0.0, 2.0), (1, 10.0, 12.0)]))
    words = [W(2.3, 2.6, " uh"), W(9.5, 9.8, " so")]
    align.assign_speakers(words, act, {0: "A", 1: "B"})
    assert [w.speaker for w in words] == ["A", "B"]


def test_overlap_flag():
    act = align.activity_from_probs(probs_from([(0, 0.0, 5.0), (1, 2.0, 5.0)]))
    words = [W(0.5, 1.0, " a"), W(3.0, 3.5, " b")]
    align.assign_speakers(words, act, {0: "A", 1: "B"})
    assert not words[0].overlap and words[1].overlap


def test_smooth_tiny_flips():
    words = [W(0, 0.5, " one"), W(0.5, 1.0, " two"), W(1.0, 1.2, " x"), W(1.2, 1.7, " three"), W(1.7, 2.0, " four")]
    for w, s in zip(words, "AABAA"):
        w.speaker = s
    align.smooth_flips(words)
    assert [w.speaker for w in words] == list("AAAAA")


def test_long_runs_are_not_smoothed():
    words = [W(0, 0.5, " one"), W(0.5, 1.5, " two"), W(1.5, 2.5, " three")]
    for w, s in zip(words, "ABA"):
        w.speaker = s
    align.smooth_flips(words)
    assert [w.speaker for w in words] == list("ABA")


def test_group_segments_splits_on_speaker_language_and_pause():
    words = [W(0, 0.4, " Hello"), W(0.4, 0.8, " all."), W(1.0, 1.4, " नमस्ते", "hi"), W(1.5, 2.0, " दोस्तों", "hi"),
             W(5.0, 5.5, " ok")]
    for w, s in zip(words, "AAAAB"):
        w.speaker = s
    words[4].speaker = "A"  # same speaker after a 3 s pause
    segs = align.group_segments(words)
    assert [(g.speaker, g.text) for g in segs] == [("A", "Hello all."), ("A", "नमस्ते दोस्तों"), ("A", "ok")]
    d = segs[1].as_dict()
    assert d["language"] == "hi" and d["start"] == 1.0 and d["end"] == 2.0 and len(d["words"]) == 2


def test_long_paragraph_breaks_at_sentence_end():
    words, t = [], 0.0
    for i in range(40):
        words.append(W(t, t + 0.4, " word." if i == 35 else " word"))
        t += 0.45
    for w in words:
        w.speaker = "A"
    segs = align.group_segments(words, soft_max=12.0)
    assert len(segs) == 2 and segs[0].text.endswith("word.")


def test_limit_speakers_merges_least_active():
    act = align.activity_from_probs(probs_from([(0, 0.0, 8.0), (1, 8.0, 16.0), (2, 16.0, 16.5)]))
    lim = align.limit_speakers(act, 2)
    assert lim.speakers_present() == [0, 1]
    assert lim.active[int(16.2 / 0.01)].any()  # speaker 2's speech went to a kept speaker


def test_cross_track_overlap_and_echo_removal():
    me = align.group_segments([align.AWord(1.0, 1.5, " the", 0.9, "en", "You"),
                               align.AWord(1.5, 2.5, " budget", 0.9, "en", "You")])
    them = align.group_segments([align.AWord(1.1, 1.6, " the", 0.9, "en", "S1"),
                                 align.AWord(1.6, 2.4, " budget", 0.9, "en", "S1")])
    assert _drop_echo(me, them) == []  # the mic only heard the loudspeaker
    mine = align.group_segments([align.AWord(1.8, 2.5, " agreed", 0.9, "en", "You")])  # 0.6 s over S1
    align.flag_cross_track_overlaps(mine, them)
    assert mine[0].words[0].overlap
    brief = align.group_segments([align.AWord(2.2, 2.8, " ok", 0.9, "en", "You")])  # only 0.2 s: not an overlap
    align.flag_cross_track_overlaps(brief, them)
    assert not brief[0].words[0].overlap


def test_collapse_word_runs():
    toks = [" ok"] * 7 + [" fine"] + [" thank", " you"] * 5
    kept = [toks[i] for i in _collapse_word_runs(toks)]
    assert kept == [" ok"] * 3 + [" fine"] + [" thank", " you"] * 3


# ------------------------------------------------------------------ chunking and gap fill
from sabhalekh.asr.base import ASRSegment, Word  # noqa: E402
from sabhalekh.pipeline.runner import _replace_in_regions  # noqa: E402
from sabhalekh.pipeline.vad import make_chunks, speaker_changes, uncovered_regions  # noqa: E402


def test_chunks_merge_same_speaker_but_split_at_speaker_change():
    regions = [(0.0, 5.0), (5.6, 9.0), (9.8, 14.0)]
    assert make_chunks(regions) == [(0.0, 14.0)]  # one speaker: merged across short pauses
    assert make_chunks(regions, split_at=[9.4]) == [(0.0, 9.0), (9.8, 14.0)]  # a new speaker starts a new chunk
    assert make_chunks([(0.0, 10.0)], split_at=[4.0]) == [(0.0, 4.0), (4.0, 10.0)]  # change inside a region


def test_chunks_respect_max_length_and_gaps():
    regions = [(0.0, 20.0), (20.5, 35.0), (40.0, 41.0)]
    assert make_chunks(regions) == [(0.0, 20.0), (20.5, 35.0), (40.0, 41.0)]
    assert all(e - s <= 28.0 for s, e in make_chunks([(0.0, 70.0)]))


def test_speaker_changes_from_activity():
    act = align.activity_from_probs(probs_from([(0, 0.0, 3.0), (1, 3.5, 6.0), (0, 6.5, 8.0)]))
    assert speaker_changes(act.active, act.frame_sec) == [3.5, 6.5]


def test_uncovered_regions_finds_skipped_speech():
    regions = [(0.0, 5.0), (6.0, 10.0), (11.0, 11.5)]
    words = [(0.2, 0.8), (1.0, 2.0), (2.1, 4.5), (6.1, 6.4)]
    assert uncovered_regions(regions, words) == [(6.0, 10.0)]  # short (0.5 s) regions are ignored


def test_gap_fill_replaces_only_inside_filled_regions():
    first = [ASRSegment(0.0, 10.0, "hello there um", "en",
                        [Word(0.1, 0.6, " hello", 0.9), Word(0.7, 1.2, " there", 0.9), Word(6.2, 6.5, " um", 0.3)])]
    extra = [ASRSegment(6.0, 9.8, "नमस्ते सब लोग", "hi",
                        [Word(6.1, 7.0, " नमस्ते", 0.9), Word(7.2, 8.0, " सब", 0.9), Word(8.1, 9.5, " लोग", 0.9)])]
    out = _replace_in_regions(first, extra, [(6.0, 10.0)])
    assert [s.text for s in out] == ["hello there", "नमस्ते सब लोग"]
    assert [s.language for s in out] == ["en", "hi"]
    assert _replace_in_regions(first, [], [(6.0, 10.0)]) == first  # nothing new found: keep the first pass


def test_gap_fill_drops_late_aligned_duplicates():
    """First pass aligned 'Thanks' just after the region it was spoken in; the re-transcription must not repeat it."""
    first = [ASRSegment(17.6, 21.0, "Thanks Let us start", "en",
                        [Word(17.9, 18.4, " Thanks", 0.4), Word(18.5, 18.8, " Let", 0.4), Word(18.8, 19.0, " us", 0.9),
                         Word(19.0, 19.5, " start", 0.9)])]
    extra = [ASRSegment(16.8, 17.8, "Thanks.", "en", [Word(16.9, 17.6, " Thanks.", 0.9)])]
    out = _replace_in_regions(first, extra, [(16.8, 17.8)])
    assert " ".join(s.text for s in out) == "Thanks. Let us start"


def test_coverage_margin_tolerates_slightly_late_words():
    assert uncovered_regions([(16.8, 17.8)], [(17.6, 18.3)]) == []  # 0.5 s of word inside region +-0.3 s
    assert uncovered_regions([(16.8, 17.8)], [(18.5, 19.0)]) == [(16.8, 17.8)]


def test_language_cuts_only_between_different_or_mixed_speakers():
    from sabhalekh.pipeline.vad import language_cuts, speaker_turns

    act = align.activity_from_probs(probs_from([(0, 0.0, 3.0), (1, 3.5, 6.0), (2, 6.5, 9.0), (0, 9.5, 12.0)], dur=13))
    turns = speaker_turns(act.active, act.frame_sec)
    assert [t[2] for t in turns] == [0, 1, 2, 0]
    # speakers 0 and 1 both English, 2 Hindi: 0->1 needs no cut, 1->2 and 2->0 do
    assert language_cuts(turns, {0: "en", 1: "en", 2: "hi"}) == [6.5, 9.5]
    # someone who mixes languages always gets cuts
    assert language_cuts(turns, {0: "en", 1: "mixed", 2: "en"}) == [3.5, 6.5]
    # unknown speakers are treated as mixed
    assert language_cuts(turns, {}) == [3.5, 6.5, 9.5]
