import pytest

from sabhalekh import text


@pytest.mark.parametrize("dev, roman", [
    ("क्या", "kya"), ("है", "hai"), ("मैं", "main"), ("हैं", "hain"), ("बात", "baat"), ("समझना", "samajhna"),
    ("करना", "karna"), ("आपका", "aapka"), ("ज़रूर", "zarur"), ("लड़का", "ladka"), ("सम्बन्ध", "sambandh"),
    ("हम बजट पर बात करेंगे।", "ham bajat par baat karenge."), ("२०२४", "2024"),
])
def test_devanagari_to_roman(dev, roman):
    assert text.devanagari_to_roman(dev) == roman


def test_mixed_text_keeps_english():
    assert text.devanagari_to_roman("Meeting कल है, ok?") == "Meeting kal hai, ok?"


def test_script_language():
    assert text.script_language("hello there") == "en"
    assert text.script_language("नमस्ते दोस्तों") == "hi"
    assert text.script_language("मैं office जा रहा हूँ") == "mixed"


def test_normalize_for_search():
    assert text.normalize_for_search("  ज़रूर ‍ Budget ") == "जरूर budget"


def test_hallucination_filter():
    assert text.is_hallucination("Thank you.", 1.0)
    assert text.is_hallucination("Thanks for watching!", 2.0, no_speech_prob=0.5)
    assert not text.is_hallucination("Thank you.", 6.0, no_speech_prob=0.0, avg_logprob=-0.2)
    assert not text.is_hallucination("Let's begin", 2.0)


def test_collapse_repetitions():
    assert text.collapse_repetitions("no no no no no no") == "no no no"


def test_youtube_outro_is_hallucination():
    assert text.is_hallucination("सब्सक्राइब करें और सब्सक्राइब करें", 8.0)
    assert text.is_hallucination("Please like and subscribe.", 5.0)
    assert not text.is_hallucination("चैनल को subscribe करने का option settings में है", 5.0)


def test_style_prompt_echo_detection():
    from sabhalekh.asr.whisper_ct2 import STYLE_PROMPTS, echoes_prompt

    p = STYLE_PROMPTS["as_spoken"]
    assert echoes_prompt("इसका वही URL देगा। तो आज की meeting में हम project का status", p)
    assert not echoes_prompt("ठीक है, तो camera configure करेंगे", p)  # common words, no 4-word run
    assert not echoes_prompt("live camera configure, live monitoring, आपको records कहां दिखेंगे", p)
