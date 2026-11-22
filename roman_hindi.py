"""Roman Hindi -> Devanagari conversion (accent fix, PRD Section 13).

Problem it fixes: bot already *detects* Roman Hindi ("kaise ho tum" ->
Hindi voice), but it sends the Latin letters to edge-tts as-is, so the
Hindi voice reads them with an English accent. Converting the text to
Devanagari first ("kaise ho tum" -> "कैसे हो तुम") makes the same Hindi
voice pronounce it correctly.

Design (no new dependency, no network, no training):
  1. Dictionary first: common words from the bot's ROMAN_HINDI_WORDS list
     plus other frequent words, with hand-checked Devanagari spellings.
  2. Phonetic fallback for any other word: ITRANS-style syllable parsing
     (consonant + vowel matra, halant before another consonant, anusvara
     for a pre-consonant / word-final-after-long-vowel n). Approximate,
     but Devanagari read by the Hindi voice still sounds far closer
     than Latin letters do.

Usage in bot.py (proposed, not yet wired in):
    from roman_hindi import to_devanagari
    if lang == "hindi" and not DEVANAGARI.search(text):
        text = to_devanagari(text)
Only call it when detect_lang already said "hindi", so English messages
are never touched.
"""

import re

DEVANAGARI_RE = re.compile(r"[\u0900-\u097F]")

# ---------------------------------------------------------------------------
# 1. Dictionary: hand-checked spellings for the most common words.
#    (Covers the bot's ROMAN_HINDI_WORDS list plus other frequent words.)
# ---------------------------------------------------------------------------
from dictionary import WORD_MAP  # single source of truth: see dictionary.py

# ---------------------------------------------------------------------------
# 2. Phonetic fallback (ITRANS-style). Longest match first.
# ---------------------------------------------------------------------------
# consonant -> Devanagari (inherent 'a' form)
_CONSONANTS = [
    ("ksh", "क्ष"), ("tr", "त्र"), ("gy", "ज्ञ"),
    ("kh", "ख"), ("gh", "घ"), ("chh", "छ"), ("ch", "च"),
    ("jh", "झ"), ("th", "थ"), ("dh", "ध"), ("ph", "फ"),
    ("bh", "भ"), ("sh", "श"), ("ng", "ङ"), ("ny", "ञ"),
    ("k", "क"), ("g", "ग"), ("j", "ज"), ("t", "त"),
    ("d", "द"), ("n", "न"), ("p", "प"), ("b", "ब"),
    ("m", "म"), ("y", "य"), ("r", "र"), ("l", "ल"),
    ("v", "व"), ("w", "व"), ("s", "स"), ("h", "ह"),
    ("f", "फ़"), ("z", "ज़"), ("q", "क़"), ("x", "क्स"),
]

# vowel (after a consonant) -> matra; "" means inherent 'a'
_VOWEL_MATRAS = [
    ("aa", "ा"), ("ee", "ी"), ("ii", "ी"), ("oo", "ू"), ("uu", "ू"),
    ("ai", "ै"), ("au", "ौ"),
    ("a", ""), ("i", "ि"), ("u", "ु"), ("e", "े"), ("o", "ो"),
]
# vowel at word start (or after another vowel) -> independent letter
_VOWEL_INDEPENDENT = {
    "aa": "आ", "ee": "ई", "ii": "ई", "oo": "ऊ", "uu": "ऊ",
    "ai": "ऐ", "au": "औ",
    "a": "अ", "i": "इ", "u": "उ", "e": "ए", "o": "ओ",
}
_LONG_VOWELS = {"aa", "ee", "ii", "oo", "uu", "ai", "au"}

_HALANT = "्"
_ANUSVARA = "ं"

# Consonant pairs that form a real conjunct (halant), e.g. स्त, स्न, च्छ.
# Other clusters (e.g. "lt" in "milte") are two syllables, not a conjunct.
_CONJUNCT_PAIRS = {
    ("s", "t"), ("s", "n"), ("s", "m"), ("s", "p"), ("s", "r"),
    ("s", "v"), ("s", "k"), ("c", "ch"),
    ("k", "r"), ("g", "r"), ("p", "r"), ("b", "r"), ("d", "r"),
    ("t", "r"), ("n", "t"), ("s", "sh"),
}


def _match_at(word, i, table):
    """Longest table key matching word[i:]; returns (key, value) or None."""
    for key, val in table:
        if word.startswith(key, i):
            return key, val
    return None


def _transliterate_word(word: str) -> str:
    """One lowercase a-z word -> Devanagari (phonetic fallback)."""
    if word in WORD_MAP:
        return WORD_MAP[word]
    out = []
    i, n = 0, len(word)
    # True when the last emitted unit ended in a vowel sound, so a vowel
    # here starts a new syllable (independent letter, e.g. "jao" -> जाओ).
    prev_was_vowel = False
    prev_vowel = None
    while i < n:
        # Nasal: 'n'/'m' directly before a consonant is ं ("andar" -> अंदर).
        # Word-final 'n' after a long vowel is also ं ("main" -> मैं,
        # "hoon" -> हूँ). Final 'm' stays म ("naam" -> नाम, "kaam" -> काम).
        if word[i] in ("n", "m"):
            if _match_at(word, i + 1, _CONSONANTS):
                out.append(_ANUSVARA)
                prev_was_vowel = False
                prev_vowel = None
                i += 1
                continue
            if word[i] == "n" and i == n - 1 and prev_vowel in _LONG_VOWELS:
                out.append(_ANUSVARA)
                i += 1
                continue
        # Vowel at word start or after another vowel -> independent letter.
        # Word-final 'a' is long आ in Roman Hindi ("hua" -> हुआ).
        if i == 0 or prev_was_vowel:
            v = _match_at(word, i, _VOWEL_MATRAS)
            if v:
                key, _ = v
                letter = "आ" if key == "a" and i + len(key) == n \
                    else _VOWEL_INDEPENDENT[key]
                out.append(letter)
                prev_was_vowel = True
                prev_vowel = key
                i += len(key)
                continue
        # Consonant (+ optional vowel matra).
        c = _match_at(word, i, _CONSONANTS)
        if c:
            key, deva = c
            j = i + len(key)
            v = _match_at(word, j, _VOWEL_MATRAS)
            if v:
                vkey, matra = v
                # Word-final explicit 'a' is long आ ("laga" -> लगा,
                # "liya" -> लिया, "sneha" -> स्नेहा).
                if vkey == "a" and j + len(vkey) == n:
                    matra = "ा"
                out.append(deva + matra)
                prev_was_vowel = True
                prev_vowel = vkey
                i = j + len(vkey)
            else:
                # No vowel after: halant only for a real conjunct
                # (same consonant twice, y/r as second consonant, or a
                # known pair like स्त/स्न/च्छ); else keep inherent 'a'
                # so the next consonant starts a new syllable
                # ("milte" -> मिलते, not मिल्ते).
                nxt = _match_at(word, j, _CONSONANTS)
                if nxt and (nxt[0] == key or nxt[0] in ("y", "r")
                            or (key, nxt[0]) in _CONJUNCT_PAIRS):
                    out.append(deva + _HALANT)
                else:
                    out.append(deva)
                prev_was_vowel = False
                prev_vowel = None
                i = j
            continue
        # Unknown char (shouldn't happen for a-z words): copy through.
        out.append(word[i])
        prev_was_vowel = False
        prev_vowel = None
        i += 1
    return "".join(out)


_WORD_RE = re.compile(r"[A-Za-z]+")


def segment_text(text: str) -> list:
    """Split a Hindi-detected message into (text, lang) segments.

    A dictionary word whose meaning is written in English letters stays
    English ("en") — the bot speaks it in an English accent. Everything
    else becomes Devanagari ("hi") and is spoken in a Hindi accent.
    Spaces and punctuation ride along with the segment before them.
    """
    segments: list = []

    def push(chunk: str, lang: str) -> None:
        if not chunk:
            return
        if segments and segments[-1][1] == lang:
            segments[-1] = (segments[-1][0] + chunk, lang)
        else:
            segments.append((chunk, lang))

    for m in re.finditer(r"[A-Za-z]+|[^A-Za-z]+", text):
        tok = m.group(0)
        if re.fullmatch(r"[A-Za-z]+", tok):
            word = tok.lower()
            if word in WORD_MAP:
                val = WORD_MAP[word]
                # Devanagari meaning -> Hindi accent; Latin meaning -> English accent.
                lang = "hi" if DEVANAGARI_RE.search(val) else "en"
                push(val, lang)
            else:
                push(_transliterate_word(word), "hi")
        else:
            push(tok, segments[-1][1] if segments else "hi")
    return segments


def to_devanagari(text: str) -> str:
    """Convert Roman-Hindi text to Devanagari, word by word.

    Non-letters (spaces, punctuation, digits, existing Devanagari) pass
    through untouched. Only call when the message is Hindi (see module
    docstring); English text must not reach this function.
    """
    def _sub(m):
        return _transliterate_word(m.group(0).lower())
    return _WORD_RE.sub(_sub, text)
