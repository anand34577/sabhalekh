"""Dev tool: build the offline test fixtures in tests/data (run once; the outputs are committed).

    python tools/make_test_fixtures.py FLEURS_DIR

FLEURS_DIR holds google/fleurs `data/hi_in/dev.tsv` and the extracted `dev/*.wav` (CC-BY-4.0).
Creates:
  tests/data/hindi/NN.wav + manifest.jsonl     Hindi read speech with reference transcripts (WER/CER benchmark)
  tests/data/two_speaker_en_hi.wav + .json     two speakers alternating Hindi (one real FLEURS speaker) and
                                               English (Windows SAPI voice), with the expected turns
"""
import json
import os
import subprocess
import sys
import tempfile

import numpy as np
import soundfile as sf

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "tests", "data")
SR = 16000


def read16k(path):
    a, sr = sf.read(path, dtype="float32", always_2d=False)
    if a.ndim > 1:
        a = a.mean(1)
    if sr != SR:
        idx = np.arange(0, len(a), sr / SR)
        a = np.interp(idx, np.arange(len(a)), a).astype(np.float32)
    return a


def sapi(text, voice="Microsoft Zira Desktop"):
    fd, path = tempfile.mkstemp(suffix=".wav")
    os.close(fd)
    ps = (
        "Add-Type -AssemblyName System.Speech;"
        "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer;"
        f"$s.SelectVoice('{voice}');"
        "$f = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(16000, "
        "[System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen, [System.Speech.AudioFormat.AudioChannel]::Mono);"
        f"$s.SetOutputToWaveFile('{path}', $f); $s.Speak('{text}'); $s.Dispose()"
    )
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=True)
    a = read16k(path)
    os.remove(path)
    return a


def quietest_split(a, lo=0.35, hi=0.65, win=0.25):
    """Index of the quietest 250 ms window between 35% and 65% of the clip (a pause between words)."""
    w = int(win * SR)
    best, best_e = None, None
    for s in range(int(len(a) * lo), int(len(a) * hi) - w, SR // 50):
        e = float(np.mean(a[s:s + w] ** 2))
        if best_e is None or e < best_e:
            best, best_e = s + w // 2, e
    return best


def main(fleurs):
    rows = [l.rstrip("\n").split("\t") for l in open(os.path.join(fleurs, "dev.tsv"), encoding="utf-8")]
    seen, picked = set(), []
    for r in rows:
        sid, fname, raw, gender = r[0], r[1], r[2], r[6]
        if sid in seen or not os.path.exists(os.path.join(fleurs, "dev", fname)):
            continue
        seen.add(sid)
        picked.append((fname, raw, gender))
    hindi_dir = os.path.join(OUT, "hindi")
    os.makedirs(hindi_dir, exist_ok=True)
    with open(os.path.join(hindi_dir, "manifest.jsonl"), "w", encoding="utf-8") as m:
        for i, (fname, raw, gender) in enumerate(picked[:12]):
            a = read16k(os.path.join(fleurs, "dev", fname))
            name = f"{i:02d}.wav"
            sf.write(os.path.join(hindi_dir, name), a, SR, subtype="PCM_16")
            m.write(json.dumps({"audio": name, "text": raw, "language": "hi", "source": f"FLEURS hi_in dev {fname}"},
                               ensure_ascii=False) + "\n")

    # two-speaker clip: the longest male Hindi utterance (a single real speaker), split at a pause
    longest = max((p for p in picked if p[2] == "MALE"),
                  key=lambda p: sf.info(os.path.join(fleurs, "dev", p[0])).frames)
    hi = read16k(os.path.join(fleurs, "dev", longest[0]))
    cut = quietest_split(hi)
    hi1, hi2 = hi[:cut], hi[cut:]
    en1_text = "Thanks. Let us start with the budget for the next quarter."
    en2_text = "That sounds good. I will send the final numbers by Friday."
    en1, en2 = sapi(en1_text), sapi(en2_text)
    gap = np.zeros(int(0.8 * SR), np.float32)
    parts = [("hi", "Speaker A", hi1), ("en", "Speaker B", en1), ("hi", "Speaker A", hi2), ("en", "Speaker B", en2)]
    audio, turns, t = [], [], 0.0
    for lang, spk, a in parts:
        a = a / (np.abs(a).max() + 1e-9) * 0.6
        audio += [a, gap]
        turns.append({"speaker": spk, "language": lang, "start": round(t, 2), "end": round(t + len(a) / SR, 2)})
        t += (len(a) + len(gap)) / SR
    sf.write(os.path.join(OUT, "two_speaker_en_hi.wav"), np.concatenate(audio), SR, subtype="PCM_16")
    json.dump({"turns": turns, "english": [en1_text, en2_text], "hindi_reference": longest[1],
               "source": f"FLEURS hi_in dev {longest[0]} (CC-BY-4.0) + Windows SAPI 'Microsoft Zira Desktop'"},
              open(os.path.join(OUT, "two_speaker_en_hi.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("fixtures written to", OUT)


if __name__ == "__main__":
    main(sys.argv[1])
