# TTS-by-me — Discord TTS Bot (accent fix)

Free Discord TTS bot (py-cord + edge-tts, no paid API). Joins a voice
channel only on `/join`, reads the voice-channel chat aloud in Hindi and
English, leaves on `/leave`.

## Accent fix (this version)

Roman Hindi is converted to Devanagari before edge-tts, so the Hindi
voice pronounces it correctly: "kaise ho tum" -> "कैसे हो तुम".
See `roman_hindi.py` (dictionary first, phonetic fallback second) and
`speak_text()` in `bot.py`. It runs only when the detected language is
Hindi and the text has no Devanagari already — English is never touched.
Tested 25/25 (`python3 test_roman_hindi.py`).

## Critical pins — do not change

- `davey>=0.1.7,<0.2` — **never davey 0.2.0**. It makes the bot join
  voice but stay silent (DAVE `can_encrypt=False`).
- `py-cord[voice]>=2.8.0` — discord.py 2.7.x has the same silent-voice
  DAVE problem for this bot.

## Run on Render (free, 24x7)

- Web Service, Free plan, Region Singapore.
- Build Command: `pip install -r requirements.txt` (no apt-get — Render
  fails the build on apt).
- Start Command: `python bot.py`
- Environment Variables: `DISCORD_TOKEN`, `DISCORD_GUILD_ID`.
- `bot.py` runs a small keep-alive HTTP server on `$PORT` that answers
  both GET and HEAD with 200, so UptimeRobot (ping every 5 minutes)
  keeps the free service awake and does not get a 501.

## Run locally

```
pip install -r requirements.txt
cp .env.example .env   # paste your real bot token in .env, never commit it
python bot.py
```

## Commands

`/join` `/leave` `/say` `/voice` `/voicestyle` `/stop` `/skip` `/status`
`/diag` `/testtone`, plus `!testtone` and `!say` as text fallbacks.
