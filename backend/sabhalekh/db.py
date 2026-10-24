"""SQLite storage: sessions, speakers, transcript segments, words, jobs, hardware logs, settings, FTS5 search.

One connection per thread (WAL mode). Schema changes are numbered migrations recorded in `schema_version`.
Search uses an FTS5 trigram index over NFC-normalized text (Devanagari-safe: unicode61 splits words inside
conjuncts), with a LIKE fallback for 1-2 character queries that trigrams cannot match, and a Roman transliteration
of Devanagari segments so "kya" also finds "क्या".
"""
from __future__ import annotations

import json
import re
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Iterable

from . import text as textutil

SPEAKER_COLORS = ["#4F8EF7", "#F25F8C", "#2BB673", "#F5A524", "#9B6CF6", "#14B8C4", "#EF6A3A", "#8C9BAB",
                  "#C2D94C", "#E879F9"]
SELF_COLOR = "#60A5FA"

MIGRATIONS: list[str] = [
    # 1: initial schema
    """
    CREATE TABLE sessions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        source_type TEXT NOT NULL CHECK (source_type IN ('recorded', 'imported')),
        original_filename TEXT,
        source_path TEXT,           -- imports: the user's original file (read during extraction, never modified)
        audio_path TEXT,            -- playback copy (Opus/Ogg)
        norm_path TEXT,             -- 16 kHz mono 16-bit WAV used by the pipeline
        mic_track_path TEXT,        -- recordings: 16 kHz mono WAV of the microphone ("You")
        system_track_path TEXT,     -- recordings: 16 kHz mono WAV of system audio (other participants)
        peaks_path TEXT,
        duration_sec REAL DEFAULT 0,
        created_at REAL NOT NULL,
        updated_at REAL NOT NULL,
        status TEXT NOT NULL DEFAULT 'new',
        stage TEXT,
        progress REAL DEFAULT 0,
        language_mode TEXT DEFAULT 'auto',
        script_mode TEXT DEFAULT 'as_spoken',
        detected_languages TEXT,
        asr_model TEXT,
        diarization_engine TEXT,
        profile_used TEXT,
        tags TEXT DEFAULT '[]',
        error_message TEXT,
        warnings TEXT DEFAULT '[]',
        min_speakers INTEGER,
        max_speakers INTEGER,
        original_snapshot TEXT
    );
    CREATE TABLE speakers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
        label TEXT NOT NULL,
        display_name TEXT NOT NULL,
        color TEXT NOT NULL,
        is_self INTEGER DEFAULT 0
    );
    CREATE INDEX idx_speakers_session ON speakers(session_id);
    CREATE TABLE transcript_segments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
        speaker_id INTEGER REFERENCES speakers(id) ON DELETE SET NULL,
        original_speaker_id INTEGER,
        start_sec REAL NOT NULL,
        end_sec REAL NOT NULL,
        text TEXT NOT NULL,
        edited_text TEXT,
        language TEXT,
        confidence REAL,
        overlap_flag INTEGER DEFAULT 0
    );
    CREATE INDEX idx_segments_session ON transcript_segments(session_id, start_sec);
    CREATE TABLE words (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        segment_id INTEGER NOT NULL REFERENCES transcript_segments(id) ON DELETE CASCADE,
        start_sec REAL NOT NULL,
        end_sec REAL NOT NULL,
        text TEXT NOT NULL,
        confidence REAL
    );
    CREATE INDEX idx_words_segment ON words(segment_id);
    CREATE VIRTUAL TABLE segments_fts USING fts5(
        session_id UNINDEXED, segment_id UNINDEXED, field UNINDEXED, body,
        tokenize = 'trigram case_sensitive 0'
    );
    CREATE TABLE jobs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
        kind TEXT NOT NULL DEFAULT 'process',
        params TEXT DEFAULT '{}',
        status TEXT NOT NULL DEFAULT 'queued',
        stage TEXT,
        progress REAL DEFAULT 0,
        eta_sec REAL,
        created_at REAL NOT NULL,
        started_at REAL,
        finished_at REAL,
        error TEXT
    );
    CREATE INDEX idx_jobs_status ON jobs(status);
    CREATE TABLE hardware_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp REAL NOT NULL,
        gpu_name TEXT,
        vram_mb INTEGER,
        cuda_available INTEGER,
        cpu_cores INTEGER,
        cpu_threads INTEGER,
        ram_mb INTEGER,
        free_disk_mb INTEGER,
        profile TEXT
    );
    CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
    """,
]

DEFAULT_SETTINGS: dict[str, Any] = {
    "theme": "system",                 # system | dark | light
    "accent": "#4F8EF7",
    "text_scale": 1.0,
    "language_mode": "auto",           # auto | en | hi | translate
    "script_mode": "as_spoken",        # as_spoken | devanagari | roman
    "asr_model": "auto",               # auto or a model id from the catalog
    "profile_override": "auto",        # auto | gpu_high | gpu_low | cpu | cpu_fast
    "auto_process": True,
    "initial_prompt": "",              # custom vocabulary: names, jargon
    "min_speakers": None,
    "max_speakers": None,
    "mic_device": None,
    "loopback_device": None,
    "playback_kbps": 64,               # Opus bitrate per channel of the playback copy (48 / 64 / 96)
    "hotkey": "CommandOrControl+Shift+R",
    "start_with_windows": False,
    "minimize_to_tray": True,
    "consent_acknowledged": False,
    "onboarding_done": False,
    "auto_delete_audio_days": 0,       # 0 = never
    "export_timestamps": True,
    "export_speakers": True,
    "export_merge": True,
}


def _whole_percents(shares: list[float]) -> list[int]:
    """Round percentages to whole numbers that still add up to 100 (largest remainder), so a report never shows
    75 % + 26 %."""
    floors = [int(x) for x in shares]
    missing = round(sum(shares)) - sum(floors)
    for i in sorted(range(len(shares)), key=lambda i: shares[i] - floors[i], reverse=True)[:max(0, missing)]:
        floors[i] += 1
    return floors


def _now() -> float:
    return time.time()


class Database:
    def __init__(self, path: Path | str):
        self.path = str(path)
        self._local = threading.local()
        self._write_lock = threading.RLock()
        self._migrate()

    # ------------------------------------------------------------------ connection
    @property
    def conn(self) -> sqlite3.Connection:
        c = getattr(self._local, "conn", None)
        if c is None:
            c = sqlite3.connect(self.path, timeout=30, check_same_thread=False, isolation_level=None)
            c.row_factory = sqlite3.Row
            c.execute("PRAGMA journal_mode=WAL")
            c.execute("PRAGMA synchronous=NORMAL")
            c.execute("PRAGMA foreign_keys=ON")
            c.execute("PRAGMA busy_timeout=30000")
            self._local.conn = c
        return c

    def close(self) -> None:
        c = getattr(self._local, "conn", None)
        if c is not None:
            c.close()
            self._local.conn = None

    def _migrate(self) -> None:
        with self._write_lock:
            c = self.conn
            c.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)")
            row = c.execute("SELECT MAX(version) FROM schema_version").fetchone()
            current = row[0] or 0
            for i, sql in enumerate(MIGRATIONS[current:], start=current + 1):
                c.executescript("BEGIN;" + sql + f";INSERT INTO schema_version VALUES ({i});COMMIT;")

    def tx(self):
        return _Tx(self)

    _SESSION_FILE_COLUMNS = ("audio_path", "norm_path", "mic_track_path", "system_track_path", "peaks_path")

    def relocate_session_files(self, sessions_dir: Path) -> int:
        """Point stored session file paths at `sessions_dir` when the data folder has moved.

        Paths are stored absolute (…/sessions/<id>/<file>). After the data folder is renamed or moved, a path that
        no longer exists is rewritten to sessions_dir/<id>/<file> if that file is there. Returns the number of
        sessions updated."""
        cols = self._SESSION_FILE_COLUMNS
        changed = 0
        for r in self.conn.execute(f"SELECT id, {', '.join(cols)} FROM sessions").fetchall():
            fix = {}
            for col in cols:
                old = r[col]
                if not old or Path(old).exists():
                    continue
                cand = sessions_dir / str(r["id"]) / Path(old.replace("\\", "/")).name
                if cand.exists():
                    fix[col] = str(cand)
            if fix:
                with self.tx() as c:
                    c.execute(f"UPDATE sessions SET {', '.join(f'{k} = ?' for k in fix)} WHERE id = ?",
                              [*fix.values(), r["id"]])
                changed += 1
        return changed

    # ------------------------------------------------------------------ settings
    def get_settings(self) -> dict[str, Any]:
        out = dict(DEFAULT_SETTINGS)
        for r in self.conn.execute("SELECT key, value FROM settings"):
            try:
                out[r["key"]] = json.loads(r["value"])
            except json.JSONDecodeError:
                out[r["key"]] = r["value"]
        return out

    def set_settings(self, values: dict[str, Any]) -> dict[str, Any]:
        with self.tx() as c:
            for k, v in values.items():
                c.execute("INSERT INTO settings(key, value) VALUES (?, ?) "
                          "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (k, json.dumps(v)))
        return self.get_settings()

    # ------------------------------------------------------------------ sessions
    def create_session(self, title: str, source_type: str, **fields) -> int:
        now = _now()
        cols = {"title": title, "source_type": source_type, "created_at": now, "updated_at": now, **fields}
        with self.tx() as c:
            cur = c.execute(f"INSERT INTO sessions ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                            [self._encode(v) for v in cols.values()])
            sid = cur.lastrowid
        self.reindex_session(sid)
        return sid

    @staticmethod
    def _encode(v):
        return json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict)) else v

    def update_session(self, session_id: int, **fields) -> None:
        if not fields:
            return
        fields["updated_at"] = _now()
        sets = ", ".join(f"{k} = ?" for k in fields)
        with self.tx() as c:
            c.execute(f"UPDATE sessions SET {sets} WHERE id = ?", [self._encode(v) for v in fields.values()]
                      + [session_id])
        if "title" in fields:
            self.reindex_session(session_id)

    def get_session(self, session_id: int) -> dict | None:
        r = self.conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
        return self._session_row(r) if r else None

    @staticmethod
    def _session_row(r: sqlite3.Row) -> dict:
        d = dict(r)
        for k in ("tags", "warnings", "detected_languages"):
            try:
                d[k] = json.loads(d[k]) if d.get(k) else []
            except (json.JSONDecodeError, TypeError):
                d[k] = []
        d.pop("original_snapshot", None)
        return d

    def list_sessions(self, status: str | None = None, tag: str | None = None, language: str | None = None,
                      source: str | None = None, date_from: float | None = None, date_to: float | None = None,
                      sort: str = "date", order: str = "desc", query: str | None = None) -> list[dict]:
        where, args = [], []
        if status:
            where.append("status = ?")
            args.append(status)
        if source:
            where.append("source_type = ?")
            args.append(source)
        if tag:
            where.append("EXISTS (SELECT 1 FROM json_each(sessions.tags) WHERE value = ?)")
            args.append(tag)
        if language:
            where.append("EXISTS (SELECT 1 FROM json_each(sessions.detected_languages) WHERE value = ?)")
            args.append(language)
        if date_from:
            where.append("created_at >= ?")
            args.append(date_from)
        if date_to:
            where.append("created_at <= ?")
            args.append(date_to)
        if query:
            ids = {h["session_id"] for h in self.search(query, limit=500)}
            if not ids:
                return []
            where.append(f"id IN ({','.join('?' * len(ids))})")
            args.extend(ids)
        col = {"date": "created_at", "duration": "duration_sec", "title": "title COLLATE NOCASE"}.get(sort,
                                                                                                    "created_at")
        sql = "SELECT * FROM sessions" + (" WHERE " + " AND ".join(where) if where else "")
        sql += f" ORDER BY {col} {'ASC' if order == 'asc' else 'DESC'}"
        return [self._session_row(r) for r in self.conn.execute(sql, args)]

    def delete_session(self, session_id: int) -> None:
        with self.tx() as c:
            c.execute("DELETE FROM segments_fts WHERE session_id = ?", (session_id,))
            c.execute("DELETE FROM sessions WHERE id = ?", (session_id,))

    def all_tags(self) -> list[str]:
        rows = self.conn.execute("SELECT DISTINCT value FROM sessions, json_each(sessions.tags) ORDER BY value")
        return [r[0] for r in rows]

    # ------------------------------------------------------------------ transcript
    def replace_transcript(self, session_id: int, speakers: list[dict], segments: list[dict],
                           snapshot: bool = True) -> None:
        """Store a fresh pipeline result. speakers: [{label, display_name?, is_self?}], segments: [{speaker (label),
        start, end, text, language, confidence, overlap, words: [{start, end, text, confidence}]}]."""
        with self.tx() as c:
            old_names = {r["label"]: r["display_name"] for r in
                         c.execute("SELECT label, display_name FROM speakers WHERE session_id = ?", (session_id,))}
            c.execute("DELETE FROM transcript_segments WHERE session_id = ?", (session_id,))
            c.execute("DELETE FROM speakers WHERE session_id = ?", (session_id,))
            ids: dict[str, int] = {}
            color_i = 0
            for sp in speakers:
                if sp.get("is_self"):
                    color = SELF_COLOR
                else:
                    color = SPEAKER_COLORS[color_i % len(SPEAKER_COLORS)]
                    color_i += 1
                name = old_names.get(sp["label"]) or sp.get("display_name") or sp["label"]
                cur = c.execute("INSERT INTO speakers (session_id, label, display_name, color, is_self) "
                                "VALUES (?, ?, ?, ?, ?)", (session_id, sp["label"], name, color,
                                                           int(bool(sp.get("is_self")))))
                ids[sp["label"]] = cur.lastrowid
            for seg in segments:
                spk = ids.get(seg.get("speaker"))
                cur = c.execute(
                    "INSERT INTO transcript_segments (session_id, speaker_id, original_speaker_id, start_sec, "
                    "end_sec, text, language, confidence, overlap_flag) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (session_id, spk, spk, seg["start"], seg["end"], textutil.nfc(seg["text"]), seg.get("language"),
                     seg.get("confidence"), int(bool(seg.get("overlap")))))
                c.executemany("INSERT INTO words (segment_id, start_sec, end_sec, text, confidence) "
                              "VALUES (?, ?, ?, ?, ?)",
                              [(cur.lastrowid, w["start"], w["end"], textutil.nfc(w["text"]), w.get("confidence"))
                               for w in seg.get("words", [])])
        if snapshot:
            self._save_snapshot(session_id)
        self.reindex_session(session_id)

    def _save_snapshot(self, session_id: int) -> None:
        data = self.get_transcript(session_id)
        with self.tx() as c:
            c.execute("UPDATE sessions SET original_snapshot = ? WHERE id = ?",
                      (json.dumps(data, ensure_ascii=False), session_id))

    def get_speakers(self, session_id: int) -> list[dict]:
        return [dict(r) for r in self.conn.execute("SELECT * FROM speakers WHERE session_id = ? ORDER BY is_self "
                                                   "DESC, id", (session_id,))]

    def get_transcript(self, session_id: int) -> dict:
        speakers = self.get_speakers(session_id)
        segs = [dict(r) for r in self.conn.execute(
            "SELECT * FROM transcript_segments WHERE session_id = ? ORDER BY start_sec, id", (session_id,))]
        words: dict[int, list] = {}
        if segs:
            for r in self.conn.execute(
                    "SELECT w.* FROM words w JOIN transcript_segments s ON s.id = w.segment_id "
                    "WHERE s.session_id = ? ORDER BY w.segment_id, w.start_sec, w.id", (session_id,)):
                words.setdefault(r["segment_id"], []).append(
                    {"start": r["start_sec"], "end": r["end_sec"], "text": r["text"], "confidence": r["confidence"]})
        for s in segs:
            s["words"] = words.get(s["id"], [])
            s["display_text"] = s["edited_text"] if s["edited_text"] is not None else s["text"]
        return {"speakers": speakers, "segments": segs}

    def talk_time(self, session_id: int) -> list[dict]:
        rows = self.conn.execute(
            "SELECT sp.id, sp.display_name, sp.color, COALESCE(SUM(s.end_sec - s.start_sec), 0) AS secs "
            "FROM speakers sp LEFT JOIN transcript_segments s ON s.speaker_id = sp.id "
            "WHERE sp.session_id = ? GROUP BY sp.id ORDER BY secs DESC", (session_id,)).fetchall()
        total = sum(r["secs"] for r in rows) or 1.0
        return [{"speaker_id": r["id"], "name": r["display_name"], "color": r["color"], "seconds": r["secs"],
                 "percent": p} for r, p in zip(rows, _whole_percents([100.0 * r["secs"] / total for r in rows]))]

    # ------------------------------------------------------------------ editing
    def rename_speaker(self, speaker_id: int, name: str) -> None:
        name = textutil.nfc(name).strip()
        if not name:
            raise ValueError("speaker name cannot be empty")
        with self.tx() as c:
            c.execute("UPDATE speakers SET display_name = ? WHERE id = ?", (name, speaker_id))
            sid = c.execute("SELECT session_id FROM speakers WHERE id = ?", (speaker_id,)).fetchone()
        if sid:
            self.reindex_session(sid[0])

    def set_speaker_color(self, speaker_id: int, color: str) -> None:
        with self.tx() as c:
            c.execute("UPDATE speakers SET color = ? WHERE id = ?", (color, speaker_id))

    def add_speaker(self, session_id: int, name: str) -> int:
        with self.tx() as c:
            n = c.execute("SELECT COUNT(*) FROM speakers WHERE session_id = ? AND is_self = 0",
                          (session_id,)).fetchone()[0]
            cur = c.execute("INSERT INTO speakers (session_id, label, display_name, color) VALUES (?, ?, ?, ?)",
                            (session_id, f"Speaker {n + 1}", textutil.nfc(name), SPEAKER_COLORS[n % 10]))
            return cur.lastrowid

    def _segment(self, c, segment_id: int) -> sqlite3.Row:
        r = c.execute("SELECT * FROM transcript_segments WHERE id = ?", (segment_id,)).fetchone()
        if r is None:
            raise KeyError(f"segment {segment_id} not found")
        return r

    def edit_segment(self, segment_id: int, text: str | None = None, speaker_id: int | None = None) -> int:
        with self.tx() as c:
            seg = self._segment(c, segment_id)
            if text is not None:
                t = textutil.nfc(text).strip()
                c.execute("UPDATE transcript_segments SET edited_text = ? WHERE id = ?",
                          (None if t == seg["text"] else t, segment_id))
            if speaker_id is not None:
                ok = c.execute("SELECT 1 FROM speakers WHERE id = ? AND session_id = ?",
                               (speaker_id, seg["session_id"])).fetchone()
                if not ok:
                    raise ValueError("speaker does not belong to this session")
                c.execute("UPDATE transcript_segments SET speaker_id = ? WHERE id = ?", (speaker_id, segment_id))
        self.reindex_session(seg["session_id"])
        return seg["session_id"]

    def revert_segment(self, segment_id: int) -> int:
        with self.tx() as c:
            seg = self._segment(c, segment_id)
            c.execute("UPDATE transcript_segments SET edited_text = NULL, speaker_id = original_speaker_id "
                      "WHERE id = ?", (segment_id,))
        self.reindex_session(seg["session_id"])
        return seg["session_id"]

    def merge_segments(self, segment_ids: list[int]) -> int:
        """Merge consecutive segments into the first one (text joined, words moved, time range widened)."""
        if len(segment_ids) < 2:
            raise ValueError("select at least two segments to merge")
        with self.tx() as c:
            segs = [self._segment(c, i) for i in segment_ids]
            if len({s["session_id"] for s in segs}) != 1:
                raise ValueError("segments belong to different sessions")
            segs.sort(key=lambda s: s["start_sec"])
            first, rest = segs[0], segs[1:]
            text = " ".join(s["text"] for s in segs)
            edited = None
            if any(s["edited_text"] is not None for s in segs):
                edited = " ".join(s["edited_text"] if s["edited_text"] is not None else s["text"] for s in segs)
            conf = [s["confidence"] for s in segs if s["confidence"] is not None]
            c.execute("UPDATE transcript_segments SET end_sec = ?, text = ?, edited_text = ?, confidence = ?, "
                      "overlap_flag = ? WHERE id = ?",
                      (max(s["end_sec"] for s in segs), text, edited, sum(conf) / len(conf) if conf else None,
                       int(any(s["overlap_flag"] for s in segs)), first["id"]))
            for s in rest:
                c.execute("UPDATE words SET segment_id = ? WHERE segment_id = ?", (first["id"], s["id"]))
                c.execute("DELETE FROM transcript_segments WHERE id = ?", (s["id"],))
        self.reindex_session(first["session_id"])
        return first["session_id"]

    def split_segment(self, segment_id: int, at_word: int | None = None, at_char: int | None = None) -> int:
        """Split a segment before word index `at_word` (preferred, keeps timing exact) or at a text offset."""
        with self.tx() as c:
            seg = self._segment(c, segment_id)
            words = c.execute("SELECT * FROM words WHERE segment_id = ? ORDER BY start_sec, id",
                              (segment_id,)).fetchall()
            cur_text = seg["edited_text"] if seg["edited_text"] is not None else seg["text"]
            if at_word is not None and 0 < at_word < len(words):
                left_w, right_w = words[:at_word], words[at_word:]
                split_t = right_w[0]["start_sec"]
                left_txt = " ".join(w["text"].strip() for w in left_w)
                right_txt = " ".join(w["text"].strip() for w in right_w)
                if seg["edited_text"] is None:
                    left_orig, right_orig = left_txt, right_txt
                else:
                    left_orig, right_orig = seg["text"], seg["text"]
            elif at_char is not None and 0 < at_char < len(cur_text):
                frac = at_char / len(cur_text)
                split_t = seg["start_sec"] + frac * (seg["end_sec"] - seg["start_sec"])
                left_txt, right_txt = cur_text[:at_char].strip(), cur_text[at_char:].strip()
                left_orig, right_orig = left_txt, right_txt
                right_w = [w for w in words if w["start_sec"] >= split_t]
            else:
                raise ValueError("split position must be inside the segment")
            edited = seg["edited_text"] is not None or at_word is None
            c.execute("UPDATE transcript_segments SET end_sec = ?, text = ?, edited_text = ? WHERE id = ?",
                      (split_t, left_orig, left_txt if edited else None, segment_id))
            cur = c.execute(
                "INSERT INTO transcript_segments (session_id, speaker_id, original_speaker_id, start_sec, end_sec, "
                "text, edited_text, language, confidence, overlap_flag) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (seg["session_id"], seg["speaker_id"], seg["original_speaker_id"], split_t, seg["end_sec"],
                 right_orig, right_txt if edited else None, seg["language"], seg["confidence"],
                 seg["overlap_flag"]))
            for w in right_w:
                c.execute("UPDATE words SET segment_id = ? WHERE id = ?", (cur.lastrowid, w["id"]))
        self.reindex_session(seg["session_id"])
        return seg["session_id"]

    def revert_session(self, session_id: int) -> None:
        r = self.conn.execute("SELECT original_snapshot FROM sessions WHERE id = ?", (session_id,)).fetchone()
        if not r or not r[0]:
            raise ValueError("no original transcript to revert to")
        snap = json.loads(r[0])
        by_id = {s["id"]: s for s in snap["speakers"]}
        speakers = [{"label": s["label"], "display_name": s["label"] if not s["is_self"] else s["display_name"],
                     "is_self": s["is_self"]} for s in snap["speakers"]]
        segments = [{"speaker": by_id[s["original_speaker_id"]]["label"] if s["original_speaker_id"] in by_id
                     else None, "start": s["start_sec"], "end": s["end_sec"], "text": s["text"],
                     "language": s["language"], "confidence": s["confidence"], "overlap": s["overlap_flag"],
                     "words": s["words"]} for s in snap["segments"]]
        with self.tx() as c:
            c.execute("DELETE FROM speakers WHERE session_id = ?", (session_id,))  # forget renames too
        self.replace_transcript(session_id, speakers, segments, snapshot=True)

    # ------------------------------------------------------------------ search
    def reindex_session(self, session_id: int) -> None:
        with self.tx() as c:
            c.execute("DELETE FROM segments_fts WHERE session_id = ?", (session_id,))
            s = c.execute("SELECT title FROM sessions WHERE id = ?", (session_id,)).fetchone()
            if not s:
                return
            rows: list[tuple] = [(session_id, None, "title", textutil.normalize_for_search(s["title"]))]
            for sp in c.execute("SELECT display_name FROM speakers WHERE session_id = ?", (session_id,)):
                rows.append((session_id, None, "speaker", textutil.normalize_for_search(sp["display_name"])))
            for seg in c.execute("SELECT id, COALESCE(edited_text, text) AS t FROM transcript_segments "
                                 "WHERE session_id = ?", (session_id,)):
                rows.append((session_id, seg["id"], "text", textutil.normalize_for_search(seg["t"])))
                if textutil.has_devanagari(seg["t"]):
                    rows.append((session_id, seg["id"], "roman",
                                 textutil.normalize_for_search(textutil.devanagari_to_roman(seg["t"]))))
            c.executemany("INSERT INTO segments_fts (session_id, segment_id, field, body) VALUES (?, ?, ?, ?)", rows)

    def search(self, query: str, session_id: int | None = None, limit: int = 200) -> list[dict]:
        """Matches in titles, speaker names and transcript text. `snippet` marks hits with \\x02 ... \\x03."""
        q = textutil.normalize_for_search(query)
        if not q:
            return []
        terms = [t for t in q.split(" ") if t]
        extra = " AND f.session_id = ?" if session_id else ""
        base = ("SELECT f.session_id, f.segment_id, f.field, f.body, s.title, s.created_at, "
                "seg.start_sec, seg.speaker_id FROM segments_fts f JOIN sessions s ON s.id = f.session_id "
                "LEFT JOIN transcript_segments seg ON seg.id = f.segment_id")
        if all(len(t) >= 3 for t in terms):
            match = " AND ".join('"' + t.replace('"', '""') + '"' for t in terms)
            sql = base + " WHERE segments_fts MATCH ?" + extra + " ORDER BY s.created_at DESC, seg.start_sec LIMIT ?"
            args: list = [match] + ([session_id] if session_id else []) + [limit * 2]
        else:
            likes = " AND ".join("f.body LIKE ? ESCAPE '\\'" for _ in terms)
            sql = base + " WHERE " + likes + extra + " ORDER BY s.created_at DESC, seg.start_sec LIMIT ?"
            args = [f"%{_like_escape(t)}%" for t in terms] + ([session_id] if session_id else []) + [limit * 2]
        out, seen = [], set()
        for r in self.conn.execute(sql, args):
            key = (r["session_id"], r["segment_id"], r["field"] if r["segment_id"] is None else "seg")
            if key in seen:
                continue
            seen.add(key)
            body = r["body"]
            if r["field"] == "roman" and r["segment_id"]:
                orig = self.conn.execute("SELECT COALESCE(edited_text, text) FROM transcript_segments WHERE id = ?",
                                         (r["segment_id"],)).fetchone()
                display = textutil.nfc(orig[0]) if orig else body
                snippet = display  # roman hit: show the original script, no character offsets to mark
            else:
                display = body
                snippet = _highlight(body, terms)
            out.append({"session_id": r["session_id"], "segment_id": r["segment_id"], "field": r["field"],
                        "title": r["title"], "created_at": r["created_at"], "start_sec": r["start_sec"],
                        "speaker_id": r["speaker_id"], "snippet": _trim(snippet)})
            if len(out) >= limit:
                break
        return out

    # ------------------------------------------------------------------ jobs
    def create_job(self, session_id: int, params: dict, kind: str = "process") -> int:
        with self.tx() as c:
            cur = c.execute("INSERT INTO jobs (session_id, kind, params, status, created_at) VALUES (?, ?, ?, "
                            "'queued', ?)", (session_id, kind, json.dumps(params), _now()))
            return cur.lastrowid

    def update_job(self, job_id: int, **fields) -> None:
        sets = ", ".join(f"{k} = ?" for k in fields)
        with self.tx() as c:
            c.execute(f"UPDATE jobs SET {sets} WHERE id = ?", list(fields.values()) + [job_id])

    def get_job(self, job_id: int) -> dict | None:
        r = self.conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return self._job_row(r) if r else None

    @staticmethod
    def _job_row(r) -> dict:
        d = dict(r)
        d["params"] = json.loads(d["params"] or "{}")
        return d

    def list_jobs(self, statuses: Iterable[str] | None = None, limit: int = 100) -> list[dict]:
        sql = "SELECT j.*, s.title FROM jobs j JOIN sessions s ON s.id = j.session_id"
        args: list = []
        if statuses:
            st = list(statuses)
            sql += f" WHERE j.status IN ({','.join('?' * len(st))})"
            args += st
        sql += " ORDER BY CASE j.status WHEN 'running' THEN 0 WHEN 'queued' THEN 1 ELSE 2 END, j.id DESC LIMIT ?"
        return [self._job_row(r) for r in self.conn.execute(sql, args + [limit])]

    def next_queued_job(self) -> dict | None:
        r = self.conn.execute("SELECT * FROM jobs WHERE status = 'queued' ORDER BY id LIMIT 1").fetchone()
        return self._job_row(r) if r else None

    def requeue_interrupted_jobs(self) -> int:
        """Jobs that were running when the app stopped are queued again (resumable after restart)."""
        with self.tx() as c:
            cur = c.execute("UPDATE jobs SET status = 'queued', stage = NULL, progress = 0 WHERE status = 'running'")
            c.execute("UPDATE sessions SET status = 'queued' WHERE status = 'processing'")
            return cur.rowcount

    # ------------------------------------------------------------------ hardware
    def log_hardware(self, info: dict, profile: str) -> None:
        with self.tx() as c:
            c.execute("INSERT INTO hardware_logs (timestamp, gpu_name, vram_mb, cuda_available, cpu_cores, "
                      "cpu_threads, ram_mb, free_disk_mb, profile) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                      (_now(), info.get("gpu_name"), info.get("vram_mb"), int(bool(info.get("cuda_available"))),
                       info.get("cpu_cores"), info.get("cpu_threads"), info.get("ram_mb"), info.get("free_disk_mb"),
                       profile))


def _like_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _highlight(body: str, terms: list[str]) -> str:
    spans = []
    low = body.lower()
    for t in terms:
        for m in re.finditer(re.escape(t), low):
            spans.append((m.start(), m.end()))
    if not spans:
        return body
    spans.sort()
    merged = [list(spans[0])]
    for a, b in spans[1:]:
        if a <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    out, pos = [], 0
    for a, b in merged:
        out += [body[pos:a], "\x02", body[a:b], "\x03"]
        pos = b
    out.append(body[pos:])
    return "".join(out)


def _trim(snippet: str, width: int = 160) -> str:
    if len(snippet) <= width:
        return snippet
    i = snippet.find("\x02")
    start = max(0, i - width // 3) if i >= 0 else 0
    s = snippet[start:start + width]
    if s.count("\x02") > s.count("\x03"):
        s += "\x03"
    return ("…" if start else "") + s + ("…" if start + width < len(snippet) else "")


class _Tx:
    def __init__(self, db: Database):
        self.db = db

    def __enter__(self) -> sqlite3.Connection:
        self.db._write_lock.acquire()
        self.c = self.db.conn
        self.c.execute("BEGIN IMMEDIATE")
        return self.c

    def __exit__(self, exc_type, exc, tb):
        try:
            if exc_type is None:
                self.c.execute("COMMIT")
            else:
                self.c.execute("ROLLBACK")
        finally:
            self.db._write_lock.release()
        return False
