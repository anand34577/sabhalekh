"""FTS5 search must work for English, Devanagari Hindi and Hinglish (mixed script and romanized queries)."""
import unicodedata

from conftest import sample_transcript


def hits(db, q, **kw):
    return db.search(q, **kw)


def test_english_word(db):
    sid = sample_transcript(db)
    r = hits(db, "budget")
    assert any(h["session_id"] == sid and h["field"] == "text" for h in r)
    assert "\x02budget\x03" in r[0]["snippet"].lower()


def test_hindi_word(db):
    sample_transcript(db)
    r = hits(db, "क्वार्टर")
    assert len(r) == 1 and "\x02क्वार्टर\x03" in r[0]["snippet"]


def test_hindi_conjunct_inside_word(db):
    sample_transcript(db)
    assert hits(db, "पक्का"), "a word with a conjunct (क्क) must be found"


def test_two_letter_hindi_word_uses_fallback(db):
    sample_transcript(db)
    r = hits(db, "कल")  # 2 code points: shorter than a trigram
    assert len(r) == 1 and r[0]["start_sec"] == 12.2


def test_nfd_query_matches_nfc_text(db):
    sample_transcript(db)
    q = unicodedata.normalize("NFD", "दूँगा")
    assert hits(db, q)


def test_query_without_nukta(db):
    sid = db.create_session("Notes", "imported")
    db.replace_transcript(sid, [{"label": "Speaker 1"}],
                          [{"speaker": "Speaker 1", "start": 0, "end": 2, "text": "ज़रूर, मैं फ़ाइल भेजूँगा"}])
    assert hits(db, "जरूर") and hits(db, "फाइल")


def test_hinglish_mixed_query(db):
    sample_transcript(db)
    r = hits(db, "क्या think")
    assert len(r) == 1 and r[0]["start_sec"] == 9.5


def test_romanized_query_finds_devanagari(db):
    sample_transcript(db)
    r = hits(db, "kya")
    assert any(h["start_sec"] == 9.5 for h in r), "Roman 'kya' should find क्या"
    r = hits(db, "bajat")
    assert [h["start_sec"] for h in r] == [4.5], "Roman 'bajat' should find बजट"
    assert "बजट" in r[0]["snippet"], "a romanized hit shows the original Devanagari"


def test_title_and_speaker_name(db):
    sid = sample_transcript(db, "Quarterly planning")
    spk = db.get_speakers(sid)[0]
    db.rename_speaker(spk["id"], "Rahul Sharma")
    assert any(h["field"] == "title" for h in hits(db, "quarterly"))
    assert any(h["field"] == "speaker" for h in hits(db, "rahul"))
    assert db.list_sessions(query="rahul")[0]["id"] == sid


def test_edits_are_searchable(db):
    sid = sample_transcript(db)
    seg = db.get_transcript(sid)["segments"][0]
    db.edit_segment(seg["id"], text="Let's start with the marketing plan.")
    assert hits(db, "marketing")
    assert not any(h["segment_id"] == seg["id"] for h in hits(db, "budget"))


def test_scope_to_one_session(db):
    a = sample_transcript(db, "A")
    b = sample_transcript(db, "B")
    assert {h["session_id"] for h in hits(db, "बजट")} == {a, b}
    assert {h["session_id"] for h in hits(db, "बजट", session_id=b)} == {b}


def test_special_characters_are_safe(db):
    sample_transcript(db)
    for q in ['"', "budget OR", "50%", "a_b", "NEAR(", "*", "'"]:
        hits(db, q)  # must not raise
