import os
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
# isolate every test run from the real %APPDATA%/Sabhalekh
os.environ.setdefault("SABHALEKH_DATA_DIR", tempfile.mkdtemp(prefix="sabhalekh_test_"))
os.environ.setdefault("SABHALEKH_APP_DIR", str(ROOT))

DATA = ROOT / "tests" / "data"


@pytest.fixture
def db(tmp_path):
    from sabhalekh.db import Database

    d = Database(tmp_path / "test.db")
    yield d
    d.close()


def models_available() -> bool:
    return any((ROOT / "models" / "asr" / "nemotron-3.5-asr-0.6b").glob("*.gguf")) and \
        (ROOT / "bin" / "transcribe" / "transcribe.dll").exists() and \
        (ROOT / "models" / "diarization" / "nemotron3" / "frontend.npz").exists()


def sample_transcript(db, title="Budget review"):
    sid = db.create_session(title, "imported", duration_sec=30.0, status="done")
    speakers = [{"label": "Speaker 1"}, {"label": "Speaker 2"}]
    segments = [
        {"speaker": "Speaker 1", "start": 0.0, "end": 4.0, "text": "Let's start with the budget.", "language": "en",
         "confidence": 0.9, "words": [{"start": 0.0, "end": 0.5, "text": "Let's"}, {"start": 0.5, "end": 1.0,
                                                                                    "text": "start"},
                                      {"start": 1.0, "end": 1.4, "text": "with"}, {"start": 1.4, "end": 1.8,
                                                                                  "text": "the"},
                                      {"start": 1.8, "end": 4.0, "text": "budget."}]},
        {"speaker": "Speaker 2", "start": 4.5, "end": 9.0, "text": "हम अगले क्वार्टर का बजट तय करेंगे।",
         "language": "hi", "confidence": 0.8, "words": []},
        {"speaker": "Speaker 1", "start": 9.5, "end": 12.0, "text": "क्या यह सही है? Yes, I think so.",
         "language": "hi", "confidence": 0.7, "words": []},
        {"speaker": "Speaker 2", "start": 12.2, "end": 15.0, "text": "पक्का, कल तक भेज दूँगा।", "language": "hi",
         "confidence": 0.85, "words": []},
    ]
    db.replace_transcript(sid, speakers, segments)
    return sid
