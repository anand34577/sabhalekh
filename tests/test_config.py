r"""The installed app passes its resource dir as a Windows verbatim path (\\?\C:\...), which CTranslate2 cannot use."""
import os
import subprocess
import sys
from pathlib import Path

from sabhalekh.config import plain_path

ROOT = Path(__file__).resolve().parents[1]


def test_plain_path_strips_verbatim_prefix():
    assert str(plain_path("\\\\?\\C:\\Program Files\\Sabhalekh")) == "C:\\Program Files\\Sabhalekh"
    assert str(plain_path("\\\\?\\UNC\\server\\share\\x")) == "\\\\server\\share\\x"
    assert str(plain_path("C:\\x")) == "C:\\x"


def test_verbatim_app_dir_env_gives_plain_models_dir():
    env = dict(os.environ, SABHALEKH_APP_DIR="\\\\?\\" + str(ROOT))
    out = subprocess.run([sys.executable, "-c", "from sabhalekh import config; print(config.MODELS_DIR)"],
                         env=env, cwd=ROOT / "backend", capture_output=True, text=True, check=True).stdout.strip()
    assert not out.startswith("\\\\?\\")
    assert Path(out) == ROOT / "models"


def test_legacy_data_folder_is_moved_once(tmp_path):
    from sabhalekh.config import _adopt_legacy_data

    old, new = tmp_path / "MeetScribe", tmp_path / "Sabhalekh"
    (old / "sessions" / "1").mkdir(parents=True)
    (old / "meetscribe.db").write_bytes(b"db")
    (old / "meetscribe.db-wal").write_bytes(b"wal")
    assert _adopt_legacy_data(old, new) == new
    assert not old.exists() and (new / "sessions" / "1").is_dir()
    assert (new / "sabhalekh.db").read_bytes() == b"db" and (new / "sabhalekh.db-wal").read_bytes() == b"wal"
    # an existing new folder is never touched again
    old.mkdir()
    assert _adopt_legacy_data(old, new) == new and old.exists()


def test_fresh_install_uses_new_folder(tmp_path):
    from sabhalekh.config import _adopt_legacy_data

    assert _adopt_legacy_data(tmp_path / "MeetScribe", tmp_path / "Sabhalekh") == tmp_path / "Sabhalekh"
