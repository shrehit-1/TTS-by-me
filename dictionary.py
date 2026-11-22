"""Dictionary — the bot's Roman Hindi words, in ONE place.

This is the single file to edit when you want to add a default word.

  * WORD_MAP: Roman word -> what the bot says, e.g. "kr": "कर".
    Add ONE line here per new word. Accent rule: if the meaning is
    written in Devanagari, the bot says it in a Hindi accent; if it is
    written in English letters, the bot says it in an English accent.
  * HINDI_ROMAN_WORDS: every WORD_MAP word is automatically counted as
    Hindi for language detection (built from WORD_MAP below), plus a few
    extra words that only help detection and have no fixed meaning
    (HINDI_EXTRA_WORDS). So adding one line to WORD_MAP is enough —
    the word is detected as Hindi AND spoken with the right meaning.

bot.py and roman_hindi.py both import from here; neither of them keeps
its own copy of the words any more. Edit this file, commit, and the bot
picks it up on the next Render redeploy.
"""

WORD_MAP = {
    # pronouns / people
    "main": "मैं", "mein": "मैं", "tum": "तुम", "tu": "तू", "aap": "आप",
    "hum": "हम", "mera": "मेरा", "meri": "मेरी", "mere": "मेरे",
    "tumhara": "तुम्हारा", "tumhari": "तुम्हारी", "tumhare": "तुम्हारे",
    "aapka": "आपका", "aapki": "आपकी", "hamara": "हमारा", "hamari": "हमारी",
    "mujhe": "मुझे", "tujhe": "तुझे", "usko": "उसको", "isko": "इसको",
    "unko": "उनको", "inko": "इनको", "use": "उसे", "ise": "इसे",
    "bhai": "भाई", "dost": "दोस्त", "yaar": "यार", "arre": "अरे",
    # question words
    "kya": "क्या", "kyu": "क्यों", "kyun": "क्यों", "kyunki": "क्योंकि",
    "kab": "कब", "kahan": "कहाँ", "kaun": "कौन", "kaise": "कैसे",
    "kaisa": "कैसा", "kaisi": "कैसी", "kitna": "कितना", "kitni": "कितनी",
    "kitne": "कितने",
    # verbs / auxiliaries
    "hai": "है", "hain": "हैं", "ho": "हो", "hun": "हूँ", "hoon": "हूँ",
    "tha": "था", "thi": "थी", "the": "थे", "hoga": "होगा", "hogi": "होगी",
    "honge": "होंगे", "kar": "कर", "karo": "करो", "karna": "करना",
    "karta": "करता", "karti": "करती", "karte": "करते",
    "raha": "रहा", "rahi": "रही", "rahe": "रहे", "gaya": "गया",
    "gayi": "गई", "gaye": "गए", "aaya": "आया", "aayi": "आई", "aaye": "आए",
    "chahiye": "चाहिए", "sakta": "सकता", "sakti": "सकती", "sakte": "सकते",
    "bolo": "बोलो", "suno": "सुनो", "dekho": "देखो", "batao": "बताओ",
    "samajh": "समझ", "bata": "बता", "sun": "सुन", "dekh": "देख",
    "khelo": "खेलो", "khelna": "खेलना",
    "kha": "खा", "khao": "खाओ", "khana": "खाना", "khaana": "खाना",
    "ja": "जा", "jao": "जाओ", "jana": "जाना", "aa": "आ", "aao": "आओ",
    "aana": "आना", "so": "सो", "sona": "सोना",
    "uth": "उठ", "utho": "उठो", "chal": "चल", "chalo": "चलो",
    # adjectives / adverbs
    "accha": "अच्छा", "acha": "अच्छा", "achha": "अच्छा", "bura": "बुरा",
    "theek": "ठीक", "sahi": "सही", "galat": "गलत", "bahut": "बहुत",
    "bohot": "बहुत", "zyada": "ज़्यादा", "kam": "कम", "bada": "बड़ा",
    "badi": "बड़ी", "chota": "छोटा", "choti": "छोटी",
    "abhi": "अभी", "phir": "फिर", "fir": "फिर", "jab": "जब", "tab": "तब",
    "aaj": "आज", "kal": "कल", "subah": "सुबह", "shaam": "शाम",
    "raat": "रात", "baat": "बात", "sab": "सब", "kuch": "कुछ",
    "koi": "कोई", "aur": "और", "lekin": "लेकिन", "magar": "मगर",
    "bhi": "भी", "liye": "लिए", "saath": "साथ", "bina": "बिना",
    "baad": "बाद", "pehle": "पहले", "andar": "अंदर", "bahar": "बाहर",
    "upar": "ऊपर", "neeche": "नीचे", "yeh": "ये", "ye": "ये",
    "woh": "वो", "wo": "वो", "yahan": "यहाँ", "wahan": "वहाँ",
    "nahi": "नहीं", "mat": "मत", "bas": "बस", "ek": "एक", "do": "दो",
    "teen": "तीन", "naam": "नाम", "kaam": "काम", "ghar": "घर",
    "paani": "पानी", "paisa": "पैसा", "time": "टाइम", "game": "गेम",
    "song": "सॉन्ग", "gaana": "गाना", "gana": "गाना",
    "school": "स्कूल", "bacha": "बच्चा", "bachi": "बच्ची",
    "ladka": "लड़का", "ladki": "लड़की",
    "aaina": "आईना", "aaiye": "आइए",

    # User's typing style (short forms, from his chats — 2026-11-19).
    # He drops vowels / shortens endings: kr, kro, btao, smjh, thik, hn.
    "hn": "हाँ", "thik": "ठीक", "kro": "करो", "kr": "कर",
    "krna": "करना", "krta": "करता", "krte": "करते",
    "btao": "बताओ", "bta": "बता", "smjh": "समझ",
    "aabhe": "अभी", "abhe": "अभी", "aab": "अब",
    "ese": "ऐसे", "eese": "ऐसे", "aise": "ऐसे", "hi": "ही",
    "mai": "मैं", "rhe": "रहे", "rha": "रहा", "rhi": "रही",
    "jaise": "जैसे", "vaise": "वैसे", "kese": "कैसे",
    "gya": "गया", "gyi": "गई", "gye": "गए",
    "lga": "लगा", "lg": "लग", "lagana": "लगाना",
    "pata": "पता", "pta": "पता", "kb": "कब",
    "dekhna": "देखना", "krne": "करने", "hoga": "होगा",
    # 2026-11-22: "nhi" fell to the phonetic fallback and came out as
    # "ंहि"; "hu" came out as "हु" instead of "हूँ".
    "nhi": "नहीं", "hu": "हूँ",
    "ooye": "ओए", "namaste": "नमस्ते",

    # added by me
    "bsdk": "भोसडीके", "wdym": "व्हाट डू यू मीन", "bkl": "बहन के लोड़े"
}

# Words that only help detection (no fixed Devanagari meaning needed).
HINDI_EXTRA_WORDS = {
    "apna",
    "apni",
    "humko",
    "iska",
    "kaha",
    "kahaan",
    "matlab",
    "mujhko",
    "nahin",
    "toh",
    "tumhe",
    "unka",
    "uska",
    "wala",
    "wali",
}

# Everything in WORD_MAP counts as Hindi, plus the extras above.
HINDI_ROMAN_WORDS = set(WORD_MAP) | HINDI_EXTRA_WORDS
