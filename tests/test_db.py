import time

from conftest import sample_transcript
from sabhalekh.db import Database


def test_create_and_list(db):
    sid = sample_transcript(db)
    rows = db.list_sessions()
    assert [r["id"] for r in rows] == [sid]
    assert rows[0]["source_type"] == "imported"


def test_rename_speaker_updates_all_segments_and_persists(db, tmp_path):
    sid = sample_transcript(db)
    t = db.get_transcript(sid)
    s1 = next(s for s in t["speakers"] if s["label"] == "Speaker 1")
    db.rename_speaker(s1["id"], "Rahul Sharma")
    t = db.get_transcript(sid)
    names = {s["id"]: s["display_name"] for s in t["speakers"]}
    owned = [g for g in t["segments"] if g["speaker_id"] == s1["id"]]
    assert len(owned) == 2 and all(names[g["speaker_id"]] == "Rahul Sharma" for g in owned)
    # closing and reopening keeps names and edits
    db.edit_segment(t["segments"][1]["id"], text="हम अगले क्वार्टर का बजट कल तय करेंगे।")
    db.close()
    again = Database(db.path)
    t2 = again.get_transcript(sid)
    assert {s["display_name"] for s in t2["speakers"]} == {"Rahul Sharma", "Speaker 2"}
    assert t2["segments"][1]["display_text"] == "हम अगले क्वार्टर का बजट कल तय करेंगे।"
    again.close()


def test_edit_reassign_and_revert_segment(db):
    sid = sample_transcript(db)
    t = db.get_transcript(sid)
    seg, other = t["segments"][0], t["speakers"][1]
    db.edit_segment(seg["id"], text="Let us begin with the budget.", speaker_id=other["id"])
    g = db.get_transcript(sid)["segments"][0]
    assert g["display_text"] == "Let us begin with the budget." and g["speaker_id"] == other["id"]
    db.revert_segment(seg["id"])
    g = db.get_transcript(sid)["segments"][0]
    assert g["edited_text"] is None and g["speaker_id"] == seg["original_speaker_id"]


def test_merge_and_split(db):
    sid = sample_transcript(db)
    segs = db.get_transcript(sid)["segments"]
    db.merge_segments([segs[0]["id"], segs[1]["id"]])
    segs2 = db.get_transcript(sid)["segments"]
    assert len(segs2) == 3
    assert segs2[0]["end_sec"] == 9.0 and "budget." in segs2[0]["text"] and "बजट" in segs2[0]["text"]
    db.split_segment(segs2[0]["id"], at_word=2)  # words of the first original segment moved with the merge
    segs3 = db.get_transcript(sid)["segments"]
    assert len(segs3) == 4 and segs3[0]["display_text"] == "Let's start"
    assert segs3[1]["start_sec"] == 1.0


def test_revert_whole_session(db):
    sid = sample_transcript(db)
    t = db.get_transcript(sid)
    db.rename_speaker(t["speakers"][0]["id"], "Asha")
    db.merge_segments([t["segments"][2]["id"], t["segments"][3]["id"]])
    db.edit_segment(t["segments"][0]["id"], text="changed")
    db.revert_session(sid)
    t2 = db.get_transcript(sid)
    assert len(t2["segments"]) == 4
    assert [g["display_text"] for g in t2["segments"]] == [g["text"] for g in t["segments"]]
    assert {s["display_name"] for s in t2["speakers"]} == {"Speaker 1", "Speaker 2"}


def test_talk_time(db):
    sid = sample_transcript(db)
    tt = db.talk_time(sid)
    assert sum(t["percent"] for t in tt) == 100 and all(isinstance(t["percent"], int) for t in tt)
    assert abs(tt[0]["seconds"] - 7.3) < 1e-9  # speaker 2: 4.5 + 2.8


def test_reprocess_keeps_speaker_names(db):
    sid = sample_transcript(db)
    sp = db.get_speakers(sid)[0]
    db.rename_speaker(sp["id"], "Priya")
    db.replace_transcript(sid, [{"label": "Speaker 1"}],
                          [{"speaker": "Speaker 1", "start": 0, "end": 1, "text": "hi"}])
    assert db.get_speakers(sid)[0]["display_name"] == "Priya"


def test_jobs_resume_after_restart(db):
    sid = sample_transcript(db)
    jid = db.create_job(sid, {"language_mode": "auto"})
    db.update_job(jid, status="running", started_at=time.time())
    db.update_session(sid, status="processing")
    assert db.requeue_interrupted_jobs() == 1
    assert db.get_job(jid)["status"] == "queued"
    assert db.get_session(sid)["status"] == "queued"
    assert db.next_queued_job()["id"] == jid


def test_settings_roundtrip(db):
    assert db.get_settings()["language_mode"] == "auto"
    db.set_settings({"language_mode": "hi", "min_speakers": 2})
    st = db.get_settings()
    assert st["language_mode"] == "hi" and st["min_speakers"] == 2


def test_filters_and_tags(db):
    a = sample_transcript(db, "Alpha")
    b = sample_transcript(db, "Beta")
    db.update_session(a, tags=["finance"], detected_languages=["en", "hi"])
    db.update_session(b, status="error")
    assert [s["id"] for s in db.list_sessions(tag="finance")] == [a]
    assert [s["id"] for s in db.list_sessions(status="error")] == [b]
    assert [s["id"] for s in db.list_sessions(language="hi")] == [a]
    assert [s["title"] for s in db.list_sessions(sort="title", order="asc")] == ["Alpha", "Beta"]
    assert db.all_tags() == ["finance"]


def test_session_files_follow_a_moved_data_folder(db, tmp_path):
    sid = sample_transcript(db)
    old = tmp_path / "Old" / "sessions" / str(sid)
    new_sessions = tmp_path / "New" / "sessions"
    (new_sessions / str(sid)).mkdir(parents=True)
    (new_sessions / str(sid) / "playback.ogg").write_bytes(b"ogg")
    db.update_session(sid, audio_path=str(old / "playback.ogg"), peaks_path=str(old / "peaks.json"))
    assert db.relocate_session_files(new_sessions) == 1
    s = db.get_session(sid)
    assert s["audio_path"] == str(new_sessions / str(sid) / "playback.ogg")
    assert s["peaks_path"] == str(old / "peaks.json")  # missing in both places: left alone
    assert db.relocate_session_files(new_sessions) == 0


def test_whole_percents_add_up_to_100():
    from sabhalekh.db import _whole_percents

    assert _whole_percents([74.6, 25.4]) == [75, 25]
    assert _whole_percents([74.5, 25.5]) in ([75, 25], [74, 26])
    assert sum(_whole_percents([33.33, 33.33, 33.34])) == 100
    assert _whole_percents([100.0]) == [100] and _whole_percents([]) == []


def test_settings_are_validated_before_anything_is_saved(db):
    import pytest

    for bad in ({"text_scale": 0}, {"text_scale": "big"}, {"accent": "blue"}, {"theme": "neon"}, {"nope": 1},
                {"min_speakers": 99}, {"auto_process": "yes"}, {"asr_model": None}):
        with pytest.raises(ValueError):
            db.set_settings(bad)
    with pytest.raises(ValueError):  # one bad value rejects the whole update
        db.set_settings({"theme": "dark", "text_scale": 0})
    assert db.get_settings()["theme"] == "system"
    db.set_settings({"theme": "dark", "text_scale": 1.2, "accent": "#a1B2c3", "min_speakers": None, "playback_kbps": 96,
                     "mic_device": "Microphone (USB)"})
    st = db.get_settings()
    assert st["theme"] == "dark" and st["text_scale"] == 1.2 and st["min_speakers"] is None
