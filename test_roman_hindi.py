"""Local test for roman_hindi.py — run: python3 test_roman_hindi.py"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from roman_hindi import to_devanagari

CASES = [
    # (roman, expected devanagari)
    ("kaise ho tum", "कैसे हो तुम"),
    ("aaj kya kar rahe ho", "आज क्या कर रहे हो"),
    ("mujhe bahut accha laga", "मुझे बहुत अच्छा लगा"),
    ("tum kahan ho", "तुम कहाँ हो"),
    ("main ghar ja raha hoon", "मैं घर जा रहा हूँ"),
    ("aap kaise hain", "आप कैसे हैं"),
    ("kuch bolo yaar", "कुछ बोलो यार"),
    ("yeh game bahut accha hai", "ये गेम बहुत अच्छा है"),
    ("kal subah milte hain", "कल सुबह मिलते हैं"),
    ("nahi, aaj nahi", "नहीं, आज नहीं"),
    ("batao kya hua", "बताओ क्या हुआ"),
    ("khaana kha liya", "खाना खा लिया"),
    ("suno, ek baat suno", "सुनो, एक बात सुनो"),
    ("theek hai, chalo", "ठीक है, चलो"),
    ("aur batao, sab kaisa hai", "और बताओ, सब कैसा है"),
    ("mujhe samajh nahi aaya", "मुझे समझ नहीं आया"),
    ("aapka naam kya hai", "आपका नाम क्या है"),
    ("bahut zyada accha hai", "बहुत ज़्यादा अच्छा है"),
    ("khel rahe ho?", "खेल रहे हो?"),
    ("raat ho gayi hai", "रात हो गई है"),
    ("aaina", "आईना"),
    ("sneha", "स्नेहा"),
    ("accha", "अच्छा"),
    ("school", "स्कूल"),
    ("namaste", "नमस्ते"),
]

fails = 0
for roman, expected in CASES:
    got = to_devanagari(roman)
    ok = got == expected
    fails += 0 if ok else 1
    print(("OK  " if ok else "FAIL"), repr(roman), "->", got,
          "" if ok else f"(expected {expected})")
print(f"\n{len(CASES) - fails}/{len(CASES)} passed")
