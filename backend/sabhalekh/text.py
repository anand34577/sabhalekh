"""Text utilities: Unicode normalization, Devanagari detection, Hinglish-style transliteration, hallucination filter."""
from __future__ import annotations

import re
import unicodedata

ZERO_WIDTH = dict.fromkeys(map(ord, "​‌‍⁠﻿"), None)
NUKTA = "़"
DEVANAGARI_RE = re.compile(r"[ऀ-ॿ]")
LATIN_RE = re.compile(r"[A-Za-z]")


def nfc(s: str) -> str:
    return unicodedata.normalize("NFC", s or "")


def normalize_for_search(s: str) -> str:
    """NFC, no zero-width joiners, no nukta (users rarely type it), lower-case, collapsed spaces."""
    s = nfc(s).translate(ZERO_WIDTH).replace(NUKTA, "")
    return re.sub(r"\s+", " ", s).strip().lower()


def has_devanagari(s: str) -> bool:
    return bool(DEVANAGARI_RE.search(s or ""))


def script_language(s: str) -> str:
    """'hi' if the text is mostly Devanagari, 'en' if mostly Latin, 'mixed' when both are substantial."""
    dev = len(DEVANAGARI_RE.findall(s or ""))
    lat = len(LATIN_RE.findall(s or ""))
    if dev and lat and min(dev, lat) / max(dev, lat) > 0.15:
        return "mixed"
    return "hi" if dev > lat else "en"


# ------------------------------------------------------------------ Devanagari -> Roman (Hinglish style)

_CONS = {
    "क": "k", "ख": "kh", "ग": "g", "घ": "gh", "ङ": "n", "च": "ch", "छ": "chh", "ज": "j", "झ": "jh", "ञ": "n",
    "ट": "t", "ठ": "th", "ड": "d", "ढ": "dh", "ण": "n", "त": "t", "थ": "th", "द": "d", "ध": "dh", "न": "n",
    "प": "p", "फ": "ph", "ब": "b", "भ": "bh", "म": "m", "य": "y", "र": "r", "ल": "l", "ळ": "l", "व": "v",
    "श": "sh", "ष": "sh", "स": "s", "ह": "h",
}
_NUKTA_CONS = {"क": "q", "ख": "kh", "ग": "gh", "ज": "z", "ड": "d", "ढ": "rh", "फ": "f", "य": "y"}
_PRECOMPOSED = {"क़": "क", "ख़": "ख", "ग़": "ग", "ज़": "ज", "ड़": "ड", "ढ़": "ढ",
                "फ़": "फ", "य़": "य"}
_VOWELS = {"अ": "a", "आ": "aa", "इ": "i", "ई": "i", "उ": "u", "ऊ": "u", "ऋ": "ri", "ए": "e", "ऐ": "ai",
           "ओ": "o", "औ": "au", "ऑ": "o", "ऍ": "e"}
_MATRAS = {"ा": "aa", "ि": "i", "ी": "i", "ु": "u", "ू": "u", "ृ": "ri", "े": "e", "ै": "ai", "ो": "o", "ौ": "au",
           "ॉ": "o", "ॅ": "e"}
_HALANT = "्"
_ANUSVARA, _CHANDRABINDU, _VISARGA = "ं", "ँ", "ः"
_DIGITS = {chr(0x0966 + i): str(i) for i in range(10)}
_LABIALS = {"p", "ph", "b", "bh", "m"}


def _translit_word(word: str) -> str:
    # akshara list: [consonant_roman or None, vowel_roman, vowel_is_implicit]
    units: list[list] = []
    chars = [_PRECOMPOSED.get(c, c) for c in word]
    expanded: list[str] = []
    for c, orig in zip(chars, word):
        expanded.append(c)
        if orig in _PRECOMPOSED:
            expanded.append(NUKTA)
    i, n = 0, len(expanded)
    while i < n:
        c = expanded[i]
        if c in _CONS:
            rom = _CONS[c]
            if i + 1 < n and expanded[i + 1] == NUKTA:
                rom = _NUKTA_CONS.get(c, rom)
                i += 1
            unit = [rom, "a", True]
            if i + 1 < n and expanded[i + 1] == _HALANT:
                unit = [rom, "", False]
                i += 1
            elif i + 1 < n and expanded[i + 1] in _MATRAS:
                unit = [rom, _MATRAS[expanded[i + 1]], False]
                i += 1
            units.append(unit)
        elif c in _VOWELS:
            units.append([None, _VOWELS[c], False])
        elif c in (_ANUSVARA, _CHANDRABINDU):
            units.append([None, "~n", False])
        elif c == _VISARGA:
            units.append([None, "h", False])
        elif c in _DIGITS:
            units.append([None, _DIGITS[c], False])
        elif c == NUKTA:
            pass
        else:
            units.append([None, c, False])
        i += 1

    akshara = [k for k, u in enumerate(units) if u[0] is not None]
    # schwa deletion: word-final implicit 'a' (when the word has more than one akshara)
    if len(akshara) > 1:
        last = akshara[-1]
        if units[last][2] and all(units[k][1] == "~n" for k in range(last + 1, len(units))):
            units[last][1] = ""
    # medial: C V . C a . C V  ->  drop the 'a' (right to left, never two in a row)
    for k in range(len(units) - 2, 0, -1):
        prev, cur, nxt = units[k - 1], units[k], units[k + 1]
        if cur[0] and cur[2] and cur[1] == "a" and prev[1] and prev[1] != "~n" and nxt[0] and nxt[1]:
            cur[1] = ""
    out: list[str] = []
    for k, (cons, vowel, _) in enumerate(units):
        if vowel == "~n":
            nxt = units[k + 1][0] if k + 1 < len(units) else None
            out.append("m" if nxt in _LABIALS else "n")
            continue
        if cons:
            out.append(cons)
        out.append(vowel)
    s = "".join(out)
    if s.endswith("aa") and len(akshara) > 1 and units[-1][1] == "aa":
        s = s[:-1]  # क्या -> kya, था -> tha
    return s


_WORD_RE = re.compile(r"[ऀ-ॣ०-ॿ]+")


def devanagari_to_roman(text: str) -> str:
    text = nfc(text).translate(ZERO_WIDTH)
    text = text.replace("।", ".").replace("॥", ".")
    return _WORD_RE.sub(lambda m: _translit_word(m.group(0)), text)


# ------------------------------------------------------------------ hallucination / repetition filter

_HALLUCINATIONS = {
    "thank you.", "thanks for watching!", "thank you for watching.", "thanks for watching.",
    "please subscribe.", "subscribe to my channel.", "you", "bye.", "bye!", "so", ".",
    "धन्यवाद।", "धन्यवाद", "सब्सक्राइब करें", "शुक्रिया", "subtitles by the amara.org community",
}


_OUTRO_WORDS = {"सब्सक्राइब", "करें", "करे", "और", "चैनल", "को", "लाइक", "शेयर", "please", "like", "and",
                "subscribe", "share", "to", "my", "the", "channel"}


def collapse_repetitions(text: str, max_repeats: int = 3) -> str:
    """'ok ok ok ok ok ok' -> 'ok ok ok'; also repeated phrases of up to 6 words."""
    words = text.split()
    if len(words) <= max_repeats:
        return text
    for size in range(1, 7):
        out, i = [], 0
        while i < len(words):
            unit = words[i:i + size]
            reps, j = 1, i + size
            while len(unit) == size and words[j:j + size] == unit:
                reps += 1
                j += size
            if reps > max_repeats:
                out.extend(unit * max_repeats)
                i = j
            else:
                out.append(words[i])
                i += 1
        words = out
    return " ".join(words)


def is_hallucination(text: str, duration: float, no_speech_prob: float = 0.0, avg_logprob: float = 0.0) -> bool:
    t = (text or "").strip().lower()
    if not t:
        return True
    if t in _HALLUCINATIONS and (duration < 3.0 or no_speech_prob > 0.3 or avg_logprob < -0.8):
        return True
    # YouTube outro learned from training data ("सब्सक्राइब करें और सब्सक्राइब करें", "like and subscribe")
    words = {w.strip(".,!?।") for w in t.split()} - {""}
    if words and words <= _OUTRO_WORDS and ("सब्सक्राइब" in words or "subscribe" in words):
        return True
    if no_speech_prob > 0.8 and avg_logprob < -1.0:
        return True
    return False
