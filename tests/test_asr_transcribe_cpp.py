"""Nemotron (transcribe.cpp) result handling, with synthetic results; the real model runs in test_integration."""
from types import SimpleNamespace as NS

from sabhalekh.asr.transcribe_cpp import TranscribeCppEngine, chunk_language


def result(words, raw):
    tokens, out = [], []
    for text, t0, t1, p in words:
        out.append(NS(text=text, t0_ms=t0, t1_ms=t1, first_token=len(tokens), n_tokens=1))
        tokens.append(NS(text=text, p=p))
    return NS(text=" ".join(w[0] for w in words), raw_text=raw, words=out, tokens=tokens)


def test_language_from_tag_then_script():
    assert chunk_language(" That sounds good. <en-US> I will send it. <en-US>", "That sounds good.") == "en"
    assert chunk_language(" ईरानी क्रांति जो ईरान", "ईरानी क्रांति जो ईरान") == "hi"  # Hindi gets no tag
    assert chunk_language(" Thanks let us start", "Thanks let us start") == "en"
    assert chunk_language(" Guten Tag <de-DE>", "Guten Tag") == "de"


def test_segment_drops_tags_orders_times_and_keeps_confidence():
    eng = TranscribeCppEngine("unused", "nemotron-3.5-asr-0.6b")
    r = result([("That", 100, 300, 0.9), ("sounds", 300, 600, 0.8), ("good.", 560, 800, 1.0),
                ("<en-US>", 800, 800, 1.0)], raw=" That sounds good. <en-US>")
    seg = eng._segment(r, 10.0, 11.0)
    assert seg.text == "That sounds good." and seg.language == "en"
    assert [w.text for w in seg.words] == [" That", " sounds", " good."]
    starts = [w.start for w in seg.words]
    assert starts == sorted(starts) and all(w.start <= w.end <= 11.0 for w in seg.words)
    assert abs(seg.words[0].start - 10.1) < 1e-9 and seg.words[2].start >= seg.words[1].end
    assert 0.85 < seg.confidence < 0.95 and seg.avg_logprob < 0


def test_empty_or_tag_only_output_is_no_segment():
    eng = TranscribeCppEngine("unused", "x")
    assert eng._segment(result([("<en-US>", 0, 0, 1.0)], " <en-US>"), 0.0, 1.0) is None
    assert eng._segment(result([], ""), 0.0, 1.0) is None
