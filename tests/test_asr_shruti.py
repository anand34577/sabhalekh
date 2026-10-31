"""Shruti (needle engine) result handling, with synthetic results; the real model needs bin/needle and models/asr/shruti."""
import numpy as np

from sabhalekh.asr import ENGINES, ASROptions
from sabhalekh.asr import shruti
from sabhalekh.asr.shruti import ShrutiEngine, chunk_language, keywords_from_prompt


def test_registered_and_cannot_translate():
    assert "needle-whistle" in ENGINES
    eng = ShrutiEngine("unused", "shruti-55m")
    assert not eng.translate_ok
    try:
        eng.transcribe(lambda s, e: np.zeros(16000, np.float32), [(0.0, 1.0)], ASROptions(language_mode="translate"))
    except RuntimeError as e:
        assert "cannot translate" in str(e)
    else:
        raise AssertionError("translate must be refused")


def test_hinglish_segment_keeps_both_scripts_and_orders_times():
    eng = ShrutiEngine("unused", "shruti-55m")
    r = {"text": "ठीक है तो आज की meeting शुरू करते हैं", "language": "hi",
         "words": [{"word": w, "start": a, "end": b, "probability": p} for w, a, b, p in [
             ("ठीक", 0.0, 0.3, 0.9), ("है", 0.3, 0.5, 0.9), ("तो", 0.5, 0.7, 0.8), ("आज", 0.7, 1.0, 0.9),
             ("की", 1.0, 1.1, 0.95), ("meeting", 1.05, 1.6, 0.7), ("शुरू", 1.6, 2.0, 0.9), ("करते", 2.0, 2.3, 0.9),
             ("हैं", 2.3, 2.6, 0.9)]]}
    seg = eng._segment(r, 10.0, 13.0)
    assert seg.language == "hi" and seg.text == "ठीक है तो आज की meeting शुरू करते हैं"
    assert [w.text for w in seg.words][5] == " meeting"
    starts = [w.start for w in seg.words]
    assert starts == sorted(starts) and all(w.start <= w.end <= 13.0 for w in seg.words)
    assert abs(seg.words[0].start - 10.0) < 1e-9 and seg.words[5].start >= seg.words[4].end
    assert 0.8 < seg.confidence < 0.95 and seg.avg_logprob < 0


def test_millisecond_times_are_scaled():
    eng = ShrutiEngine("unused", "x")
    r = {"text": "hello there", "language": "en", "words": [
        {"word": "hello", "start": 0, "end": 400, "probability": 1.0},
        {"word": "there", "start": 400, "end": 900, "probability": 1.0}]}
    seg = eng._segment(r, 5.0, 7.0)
    assert abs(seg.words[1].end - 5.9) < 1e-9


def test_no_word_timings_spreads_words_over_the_chunk():
    eng = ShrutiEngine("unused", "x")
    seg = eng._segment({"text": "one two three four", "language": "en"}, 2.0, 6.0)
    assert [w.text for w in seg.words] == [" one", " two", " three", " four"]
    assert seg.start == 2.0 and abs(seg.end - 6.0) < 1e-9 and abs(seg.words[1].start - 3.0) < 1e-9


def test_empty_result_is_no_segment():
    eng = ShrutiEngine("unused", "x")
    assert eng._segment({"text": "", "language": None, "words": []}, 0.0, 1.0) is None
    assert eng._segment({"text": "   "}, 0.0, 1.0) is None


def test_language_from_engine_then_script():
    assert chunk_language("hi", "hello") == "hi"
    assert chunk_language("en", "नमस्ते") == "en"
    assert chunk_language(None, "यह एक टेस्ट है") == "hi"
    assert chunk_language("de", "यह meeting ठीक है") == "hi"  # mixed counts as Hindi
    assert chunk_language(None, "this is a test") == "en"


def test_forced_language_wins_over_detection():
    eng = ShrutiEngine("unused", "x")
    assert eng._segment({"text": "hello", "language": "hi"}, 0.0, 1.0, "en").language == "en"


def test_custom_vocabulary_becomes_keywords():
    assert keywords_from_prompt("Siobhan, Krzysztof;  Sabhalekh\nSiobhan") == ["Siobhan", "Krzysztof", "Sabhalekh"]
    assert keywords_from_prompt("") == []


def test_transcribe_passes_language_keywords_and_skips_tiny_chunks():
    calls = []

    class Fake:
        def transcribe(self, audio, language=None, keywords=None, word_timestamps=False):
            calls.append((len(audio), language, keywords, word_timestamps))
            return {"text": "ok", "language": "en", "words": []}

    eng = ShrutiEngine("unused", "x")
    eng.model = Fake()
    read = lambda s, e: np.zeros(int((e - s) * 16000), np.float32)  # noqa: E731
    out = eng.transcribe(read, [(0.0, 0.05), (1.0, 3.0)], ASROptions(language_mode="en", initial_prompt="Anand, Kavya"))
    assert len(out) == 1 and out[0].language == "en"
    assert calls == [(32000, "en", ["Anand", "Kavya"], True)]
    calls.clear()
    eng.transcribe(read, [(0.0, 1.0)], ASROptions(language_mode="auto"))
    assert calls == [(16000, None, None, True)]


def test_runtime_check_needs_library(tmp_path, monkeypatch):
    monkeypatch.setenv("NEEDLE3_LIB_PATH", str(tmp_path / "missing.dll"))
    assert not shruti.runtime_installed()


class Scripted:
    """Fake engine: returns the next scripted result and records how much audio each call got."""

    def __init__(self, *results):
        self.results, self.lengths = list(results), []

    def transcribe(self, audio, language=None, keywords=None, word_timestamps=False):
        self.lengths.append(len(audio))
        return self.results.pop(0)


def words(*items):
    return [{"word": w, "start": a, "end": b, "probability": 0.9} for w, a, b in items]


def test_speech_after_a_language_switch_is_decoded_as_a_second_pass():
    first = {"text": "thanks let us start", "language": "hi", "words": words(("thanks", 0.0, 0.5), ("start", 4.5, 5.0))}
    second = {"text": "ईरानी क्रांति", "language": "hi", "words": words(("ईरानी", 0.1, 0.8), ("क्रांति", 0.8, 6.9))}
    eng = ShrutiEngine("unused", "x")
    eng.model = Scripted(first, second)
    loud = np.full(12 * 16000, 0.1, np.float32)
    segs = eng._decode_chunk(loud, 10.0, 22.0, None, None)
    assert [s.text for s in segs] == ["thanks start", "ईरानी क्रांति"]
    assert abs(segs[1].start - 15.1) < 1e-9 and eng.model.lengths == [12 * 16000, 7 * 16000]


def test_silent_remainder_is_not_decoded_again():
    first = {"text": "hello", "language": "en", "words": words(("hello", 0.0, 1.0))}
    eng = ShrutiEngine("unused", "x")
    eng.model = Scripted(first)
    pcm = np.concatenate([np.full(16000, 0.1, np.float32), np.zeros(9 * 16000, np.float32)])
    assert len(eng._decode_chunk(pcm, 0.0, 10.0, None, None)) == 1 and eng.model.lengths == [10 * 16000]


def test_second_pass_that_makes_no_progress_stops():
    stuck = {"text": "a", "language": "en", "words": words(("a", 0.0, 0.1))}
    eng = ShrutiEngine("unused", "x")
    eng.model = Scripted(stuck, stuck, stuck, stuck, stuck)
    segs = eng._decode_chunk(np.full(10 * 16000, 0.1, np.float32), 0.0, 10.0, None, None)
    assert len(segs) <= 2


def test_english_pronoun_i_is_capitalised_but_other_words_are_left_alone():
    eng = ShrutiEngine("unused", "x")
    r = {"text": "i think i will go with india and i'm sure", "language": "en", "words": words(
        ("i", 0.0, 0.2), ("think", 0.2, 0.5), ("i", 0.5, 0.6), ("will", 0.6, 0.8), ("india", 0.8, 1.2), ("i'm", 1.2, 1.5))}
    seg = eng._segment(r, 0.0, 2.0)
    assert [w.text for w in seg.words] == [" I", " think", " I", " will", " india", " I'm"]
    assert seg.text == "I think I will india I'm"
