"""Hima-ASR (ONNX) engine: front end, text handling, word placement and option mapping with synthetic data.
The real model (models/asr/hima-asr) is exercised by the last test when it is installed."""
import json

import numpy as np
import pytest

from conftest import DATA, ROOT
from sabhalekh.asr import ENGINES, ASROptions
from sabhalekh.asr import hima
from sabhalekh.asr.hima import (HimaEngine, clean_text, find_variants, log_mel, missing_files, place_words,
                                providers_for, text_language, _cut_loop, _encoder_frames, _loop_length)

MODEL_DIR = ROOT / "models" / "asr" / "hima-asr"


def test_registered_and_cannot_translate():
    assert "hima-onnx" in ENGINES
    eng = HimaEngine("unused", "hima-asr-0.46b")
    assert not eng.translate_ok
    with pytest.raises(RuntimeError, match="cannot translate"):
        eng.transcribe(lambda s, e: np.zeros(16000, np.float32), [(0.0, 1.0)], ASROptions(language_mode="translate"))


def test_clean_text_lowercases_strips_symbols_and_keeps_scripts():
    assert clean_text("Hello,  World!  <hindi native> [noise]") == "hello world"
    assert clean_text("नमस्ते, दुनिया।") == "नमस्ते दुनिया"
    assert clean_text("Don’t stop") == "don't stop"
    assert clean_text("3.5 million") == "3 5 million"
    assert clean_text(None) == ""


def test_malayalam_final_consonants_become_chillus():
    assert clean_text("അവൻ") == "അവൻ"
    assert clean_text("അവന്‍") == "അവൻ"


def test_text_language_from_script():
    assert text_language("यह एक टेस्ट है") == "hi"
    assert text_language("आज की meeting शुरू करते हैं") == "hi"  # Hinglish is Hindi
    assert text_language("this is a test") == "en"
    assert text_language("இது ஒரு சோதனை") == "ta"
    assert text_language("ఇది ఒక పరీక్ష") == "te"
    assert text_language("") == "en"
    assert text_language("ok సరే") == "te"


def test_stuck_decoder_loops_are_cut():
    assert _loop_length([5, 5, 5, 5, 5, 5]) == 1
    assert _loop_length([1, 2, 3, 4, 5]) == 0
    assert _cut_loop([9, 1, 2, 1, 2, 1, 2, 1, 2]) == [9, 1, 2]
    assert _cut_loop([7, 8, 9]) == [7, 8, 9]


def test_mel_shape_is_padded_to_blocks_and_short_clips_are_extended():
    filters = np.random.default_rng(0).random((201, 128)).astype(np.float32)
    mel, n = log_mel(np.zeros(100, np.float32) + 0.01, filters)  # < 0.5 s
    assert mel.shape == (128, 100) and n == 50
    mel, n = log_mel(np.random.default_rng(1).normal(0, 0.1, 3 * 16000).astype(np.float32), filters)
    assert n == 300 and mel.shape == (128, 300) and mel.dtype == np.float32
    assert np.isfinite(mel).all()


def test_encoder_frames_follow_the_three_stride_two_convolutions():
    assert _encoder_frames(100) == 13
    assert _encoder_frames(300) == 39
    assert _encoder_frames(150) == 13 + 7  # a block of 100 and a block of 50
    assert _encoder_frames(0) == 0


def speech_with_pause():
    """1 s silence, 1 s of speech-level noise, 1 s silence, 1 s speech, 1 s silence (16 kHz)."""
    rng = np.random.default_rng(2)
    loud = lambda: rng.normal(0, 0.1, 16000).astype(np.float32)  # noqa: E731
    quiet = lambda: np.zeros(16000, np.float32)  # noqa: E731
    return np.concatenate([quiet(), loud(), quiet(), loud(), quiet()])


def test_words_are_placed_on_the_speech_not_on_silence():
    pcm = speech_with_pause()
    words = place_words(["ek", "do", "teen", "char"], pcm, 10.0, 15.0)
    assert [w.text for w in words] == [" ek", " do", " teen", " char"]
    starts = [w.start for w in words]
    assert starts == sorted(starts)
    assert all(10.0 <= w.start <= w.end <= 15.0 for w in words)
    assert words[0].start >= 10.95  # nothing in the leading second of silence
    assert words[-1].end <= 14.05  # nothing in the trailing silence
    assert words[0].end <= 12.0 and words[-1].start >= 13.0  # words at the two ends sit in their own burst
    assert not any(w.start >= 12.0 and w.end <= 13.0 for w in words)  # the silent gap holds no whole word


def test_all_silent_chunk_still_spreads_words_inside_the_chunk():
    words = place_words(["a", "b"], np.zeros(32000, np.float32), 4.0, 6.0)
    assert 4.0 <= words[0].start <= words[-1].end <= 6.0


def test_segment_carries_confidence_language_and_pronoun_i():
    eng = HimaEngine("unused", "x")
    pcm = np.full(32000, 0.1, np.float32)
    seg = eng._segment("i think i'm fine", float(np.log(0.8)), pcm, 5.0, 7.0, None)
    assert seg.text == "I think I'm fine" and seg.language == "en"
    assert abs(seg.confidence - 0.8) < 1e-6 and seg.avg_logprob < 0
    assert seg.start >= 5.0 and seg.end <= 7.0
    assert eng._segment("   ", 0.0, pcm, 0.0, 2.0, None) is None
    assert eng._segment("hello", 0.0, pcm, 0.0, 2.0, "hi").language == "hi"  # a forced language wins


class Fake(HimaEngine):
    """Skips the models: records what the engine asked of them."""

    def __init__(self):
        super().__init__("unused", "x")
        self.calls = []
        self.enc = object()  # "loaded"

    def _listen(self, pcm):
        return np.zeros((3, 640), np.float32)

    def _write(self, sound, language, style, max_pieces=512):
        self.calls.append((language, style))
        return "hello there", -0.1


def loud(_seconds):
    return lambda s, e: np.full(int((e - s) * 16000), 0.1, np.float32)


def test_language_and_script_options_reach_the_model():
    eng = Fake()
    cases = [(ASROptions(language_mode="auto"), (None, "mixed")),
             (ASROptions(language_mode="hi", script_mode="devanagari"), ("hi", "native")),
             (ASROptions(language_mode="en", script_mode="roman"), ("en", "mixed")),
             (ASROptions(language_mode="auto", script_mode="as_spoken"), (None, "mixed"))]
    for opts, expect in cases:
        eng.calls.clear()
        out = eng.transcribe(loud(2), [(0.0, 2.0)], opts)
        assert eng.calls == [expect] and out[0].text == "hello there"


def test_silent_and_tiny_chunks_are_skipped_and_progress_reported():
    eng, seen = Fake(), []
    read = lambda s, e: np.zeros(int((e - s) * 16000), np.float32) if s == 0 else np.full(800, 0.1, np.float32)  # noqa: E731
    out = eng.transcribe(read, [(0.0, 2.0), (3.0, 3.05)], ASROptions(), progress=seen.append)
    assert out == [] and eng.calls == [] and seen == [0.5, 1.0]


def test_long_chunk_is_cut_to_thirty_seconds_with_correct_offsets():
    eng = Fake()
    out = eng.transcribe(loud(70), [(100.0, 170.0)], ASROptions())
    assert len(out) == 3 and eng.calls == [(None, "mixed")] * 3
    assert abs(out[1].start - 130.0) < 1.0 and out[2].end <= 170.0


def test_cancel_stops_transcription():
    eng = Fake()
    with pytest.raises(InterruptedError):
        eng.transcribe(loud(1), [(0.0, 1.0)], ASROptions(), cancelled=lambda: True)


def test_gpu_providers_only_when_the_profile_can_use_them():
    dml = ["DmlExecutionProvider", "CPUExecutionProvider"]
    assert providers_for("gpu", dml) == [("DmlExecutionProvider", {"performance_preference": "high_performance"}),
                                         "CPUExecutionProvider"]
    assert providers_for("igpu", dml)[0][1] == {"performance_preference": "minimum_power"}
    assert providers_for("cpu", dml) == []
    assert providers_for("gpu", ["CPUExecutionProvider"]) == []  # the CPU-only onnxruntime


def test_gpu_failure_midway_continues_on_the_cpu(monkeypatch):
    eng = Fake()
    eng.used = "GPU"
    reloaded = []
    monkeypatch.setattr(eng, "_encoder_on_cpu", lambda: (reloaded.append(1), setattr(eng, "used", "CPU")))
    n = {"calls": 0}

    def write(sound, language, style, max_pieces=512):
        n["calls"] += 1
        if n["calls"] == 1:
            raise RuntimeError("DXGI_ERROR_DEVICE_REMOVED")
        return "hello there", -0.1

    eng._write = write
    out = eng.transcribe(loud(2), [(0.0, 2.0)], ASROptions())
    assert out[0].text == "hello there" and reloaded == [1] and eng.used == "CPU"


def fake_model(tmp_path, *files):
    tmp_path.mkdir(parents=True, exist_ok=True)
    for f in ("tokenizer.json", "embed.npy", "keep_ids.json", "start_of_text.npy", "mel_filters.npy"):
        (tmp_path / f).write_bytes(b"x")
    (tmp_path / "onnx").mkdir(exist_ok=True)
    for f in files:
        (tmp_path / "onnx" / f).write_bytes(b"x")
    return tmp_path


def graphs(*names):
    return [f for n in names for f in (n + ".onnx", n + ".onnx_data")]


def test_installed_variants_need_both_graphs_and_their_weights(tmp_path):
    m = fake_model(tmp_path / "a", "encoder_model_q4.onnx", "decoder_model_int8.onnx")
    assert find_variants(m) == []  # the *_data weights are missing
    m = fake_model(tmp_path / "b", *graphs("encoder_model_q4", "decoder_model_int8"))
    assert find_variants(m) == ["q4"] and missing_files(m) == []
    m = fake_model(tmp_path / "c", *graphs("encoder_model_q4", "encoder_model_int8", "decoder_model_int8"))
    assert find_variants(m) == ["q4", "int8"]  # q4 first: as accurate, smaller and faster
    m = fake_model(tmp_path / "d", *graphs("encoder_model_q4"))
    assert find_variants(m) == []  # no decoder


def test_fp32_export_is_not_a_variant(tmp_path):
    m = fake_model(tmp_path, "encoder_model.onnx", "decoder_model.onnx")
    assert find_variants(m) == [] and missing_files(m)


def test_missing_shared_files_are_named(tmp_path):
    missing = missing_files(tmp_path)
    assert "tokenizer.json" in missing and any("encoder_model_q4" in f for f in missing)


class Sessions:
    """Records the sessions HimaEngine.load opens instead of opening them."""

    def __init__(self, fail_gpu=False):
        self.opened, self.fail_gpu = [], fail_gpu

    def __call__(self, name, providers):
        on = "gpu" if any(isinstance(p, tuple) for p in providers) else "cpu"
        if on == "gpu" and self.fail_gpu:
            raise RuntimeError("no DirectX 12 device")
        self.opened.append((name, on))
        return object()


def real_shared_files(m):
    np.save(m / "embed.npy", np.zeros((3, 640), np.float32))
    (m / "keep_ids.json").write_text("[0, 1, 2]")
    np.save(m / "start_of_text.npy", np.zeros(640, np.float32))
    np.save(m / "mel_filters.npy", np.zeros((201, 128), np.float32))


@pytest.mark.parametrize("accel,fail,expect", [
    ("gpu", False, ("gpu", "GPU")), ("igpu", False, ("gpu", "iGPU")), ("cpu", False, ("cpu", "CPU")),
    ("gpu", True, ("cpu", "CPU"))])
def test_encoder_goes_to_the_gpu_and_the_decoder_stays_on_the_cpu(tmp_path, monkeypatch, accel, fail, expect):
    import onnxruntime
    import tokenizers

    m = fake_model(tmp_path, *graphs("encoder_model_q4", "decoder_model_int8"))
    real_shared_files(m)
    monkeypatch.setattr(onnxruntime, "get_available_providers",
                        lambda: ["DmlExecutionProvider", "CPUExecutionProvider"])
    monkeypatch.setattr(tokenizers.Tokenizer, "from_file", staticmethod(lambda path: object()))
    eng = HimaEngine(str(m), "x", accel=accel)
    rec = Sessions(fail_gpu=fail)
    monkeypatch.setattr(eng, "_session", rec)
    eng.load()
    assert ("decoder_model_int8.onnx", "cpu") in rec.opened
    assert ("encoder_model_q4.onnx", expect[0]) in rec.opened and eng.used == expect[1] and eng.precision == "q4"


def test_catalog_lists_hima_and_reports_why_it_is_unavailable(monkeypatch, tmp_path):
    from sabhalekh import config
    from sabhalekh.models import ModelRegistry

    monkeypatch.setattr(config, "model_search_dirs", lambda: [tmp_path])
    m = next(x for x in ModelRegistry().catalog() if x["id"] == "hima-asr-0.46b")
    assert m["engine"] == "hima-onnx" and not m["translate"] and not m["available"]
    fake_model(tmp_path / "asr" / "hima-asr", "encoder_model_q4.onnx")
    m = next(x for x in ModelRegistry().catalog() if x["id"] == "hima-asr-0.46b")
    assert not m["available"] and "missing files" in m["problem"]


@pytest.mark.skipif(not (MODEL_DIR / "tokenizer.json").exists() or not find_variants(MODEL_DIR),
                    reason="models/asr/hima-asr is not installed")
def test_real_model_transcribes_hindi_clips():
    import soundfile as sf

    rows = [json.loads(line) for line in (DATA / "hindi" / "manifest.jsonl").read_text(encoding="utf-8").splitlines()]
    eng = HimaEngine(str(MODEL_DIR), "hima-asr-0.46b", threads=4)
    try:
        errs = words = 0
        for r in rows[:3]:
            x, sr = sf.read(DATA / "hindi" / r["audio"], dtype="float32")
            segs = eng.transcribe(lambda s, e: x[int(s * sr):int(e * sr)], [(0.0, len(x) / sr)],
                                  ASROptions(language_mode="hi"))
            assert segs and segs[0].language == "hi" and segs[0].words
            ref = r["text"].replace(",", "").replace("।", "").split()
            hyp = " ".join(s.text for s in segs).split()
            words += len(ref)
            errs += _edit(ref, hyp)
        assert errs / words < 0.25
    finally:
        eng.unload()


def _edit(a, b):
    d = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        prev, d[0] = d[0], i
        for j, y in enumerate(b, 1):
            prev, d[j] = d[j], min(d[j] + 1, d[j - 1] + 1, prev + (x != y))
    return d[-1]
