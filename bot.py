"""
Discord Hindi/English TTS bot (free: edge-tts, no paid API).

- Joins a voice channel only on /join, leaves only on /leave.
- Reads text chat (voice channel chat + the channel where /join was used)
  from users who are in the same voice channel as the bot.
- Works on Windows, Python 3.11+, needs ffmpeg installed.
"""

import asyncio
import ctypes.util
import base64
import importlib.metadata
import json
import urllib.error
import urllib.request
import os
import re
import shutil
import sys
import time
import traceback
from pathlib import Path

import discord
import edge_tts
from discord import option
from discord.ext import commands
from dotenv import load_dotenv

import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from roman_hindi import WORD_MAP, to_devanagari  # accent fix: Roman Hindi -> Devanagari

def _keep_alive():
    port = int(os.environ.get("PORT", "10000"))
    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"OK")
        def do_HEAD(self):
            self.send_response(200)
            self.end_headers()
        def log_message(self, *a):
            pass
    server = HTTPServer(("0.0.0.0", port), H)
    threading.Thread(target=server.serve_forever, daemon=True).start()

_keep_alive()



# --------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

TOKEN = os.getenv("DISCORD_TOKEN", "").strip().strip('"').strip("'")
_gid = os.getenv("DISCORD_GUILD_ID", "").strip().strip('"').strip("'")
GUILD_ID = int(_gid) if _gid.isdigit() else None

PREFIX = "!"
MAX_CHARS = 280
MAX_QUEUE = 20
DAVE_WAIT_SECONDS = 15.0
# Idle fix: Discord/Render can drop the UDP media path after a few
# minutes of silence even though the websocket stays connected and
# /diag still shows can_encrypt=True. A 1s silent Opus packet every
# 90s keeps that path alive. If the client is gone, reconnect instead.
KEEPALIVE_INTERVAL_SECONDS = 20.0
KEEPALIVE_SILENCE_SECONDS = 1
LAST_TTS = BASE_DIR / "last_tts.mp3"
USER_WORDS_FILE = BASE_DIR / "user_words.json"
# Words added from Discord with /dictionary add. They work immediately,
# and are saved to user_words.json so a bot restart on the same Render
# instance keeps them. They are NOT permanent until they are also added
# to roman_hindi.py WORD_MAP and deployed — use /dictionary list to
# collect them for that commit.
USER_WORDS: dict = {}


def load_user_words() -> None:
    try:
        data = json.loads(USER_WORDS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return
    if isinstance(data, dict):
        for k, v in data.items():
            if isinstance(k, str) and isinstance(v, str):
                USER_WORDS[k.lower()] = v
                WORD_MAP[k.lower()] = v


def save_user_words() -> None:
    try:
        USER_WORDS_FILE.write_text(
            json.dumps(USER_WORDS, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
    except Exception as e:
        print(f"[dictionary] save failed: {e!r}")


load_user_words()

# ---------------------------------------------------------------------------
# GitHub sync for /dictionary words.
# Words added in Discord are pushed to user_words.json in the fork repo
# gplayaaru/TTS-by-me (public), so they survive a Render restart/redeploy.
# Needs a GitHub token with contents:write on that repo, set in Render as
# env var GITHUB_TOKEN. Without it, words still work in this session and
# in user_words.json on disk, but are not backed up to GitHub.
# The live bot also loads user_words.json from GitHub raw on startup,
# so a word pushed from Discord comes back after a restart.
# ---------------------------------------------------------------------------
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "").strip()
GITHUB_WORDS_REPO = os.environ.get("GITHUB_WORDS_REPO", "gplayaaru/TTS-by-me")
GITHUB_WORDS_BRANCH = os.environ.get("GITHUB_WORDS_BRANCH", "main")
GITHUB_WORDS_PATH = "user_words.json"


def _github_request(method, url, body=None):
    req = urllib.request.Request(url, method=method)
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("User-Agent", "tts-by-me-dictionary-bot")
    if GITHUB_TOKEN:
        req.add_header("Authorization", f"Bearer {GITHUB_TOKEN}")
    data = json.dumps(body).encode("utf-8") if body is not None else None
    if data:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, data=data, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


def load_user_words_from_github() -> int:
    """Fetch user_words.json from GitHub raw, merge into WORD_MAP. Returns count, 0 on any failure."""
    url = f"https://raw.githubusercontent.com/{GITHUB_WORDS_REPO}/{GITHUB_WORDS_BRANCH}/{GITHUB_WORDS_PATH}"
    try:
        with urllib.request.urlopen(url, timeout=8) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return 0
    if not isinstance(data, dict):
        return 0
    n = 0
    for k, v in data.items():
        if isinstance(k, str) and isinstance(v, str):
            USER_WORDS[k.lower()] = v
            WORD_MAP[k.lower()] = v
            n += 1
    return n


def sync_user_words_to_github(action: str) -> str:
    """Push the current USER_WORDS to user_words.json in the fork repo.
    Returns 'ok', 'no_token' or 'failed: ...' — never raises."""
    if not GITHUB_TOKEN:
        return "no_token"
    try:
        content = json.dumps(USER_WORDS, ensure_ascii=False, indent=2, sort_keys=True)
        b64 = base64.b64encode(content.encode("utf-8")).decode("ascii")
        api = f"https://api.github.com/repos/{GITHUB_WORDS_REPO}/contents/{GITHUB_WORDS_PATH}"
        sha = None
        try:
            existing = _github_request("GET", api + f"?ref={GITHUB_WORDS_BRANCH}")
            sha = existing.get("sha")
        except urllib.error.HTTPError as e:
            if e.code != 404:
                raise
        body = {
            "message": f"Dictionary: {action}",
            "content": b64,
            "branch": GITHUB_WORDS_BRANCH,
        }
        if sha:
            body["sha"] = sha
        _github_request("PUT", api, body)
        return "ok"
    except Exception as e:
        print(f"[dictionary] github sync failed: {e!r}")
        return f"failed: {e}"


_gh_count = load_user_words_from_github()
if _gh_count:
    print(f"[dictionary] loaded {_gh_count} words from GitHub")

_local_ffmpeg = BASE_DIR / ("ffmpeg.exe" if os.name == "nt" else "ffmpeg")
FFMPEG = os.getenv("FFMPEG_PATH", "").strip() or (
    str(_local_ffmpeg) if _local_ffmpeg.exists() else "ffmpeg"
)

VOICES = {
    "default": {"hi": "hi-IN-SwaraNeural", "en": "en-US-AriaNeural"},
    "male": {"hi": "hi-IN-MadhurNeural", "en": "en-US-GuyNeural"},
    "indian": {"hi": "hi-IN-SwaraNeural", "en": "en-IN-NeerjaNeural"},
    "indian_male": {"hi": "hi-IN-MadhurNeural", "en": "en-IN-PrabhatNeural"},
}
VOICE_MODES = ("auto", "hindi", "english")
VOICE_STYLES = tuple(VOICES.keys())

MISSING = object()


# --------------------------------------------------------------------------
# Opus loading (Windows often has no opus.dll)
# --------------------------------------------------------------------------
def load_opus_library() -> bool:
    if discord.opus.is_loaded():
        print("[opus] Already loaded.")
        return True

    if hasattr(os, "add_dll_directory"):
        try:
            os.add_dll_directory(str(BASE_DIR))
        except Exception:
            pass

    candidates = []
    # 1) Files next to bot.py, by full path
    for name in ("opus.dll", "libopus-0.x64.dll"):
        p = BASE_DIR / name
        if p.exists():
            candidates.append(str(p))
    # 2) System names
    candidates.extend(["opus", "libopus.so.0", "libopus.so", "libopus-0.dll"])
    found = ctypes.util.find_library("opus")
    if found:
        candidates.append(found)
    # 3) DLL bundled inside the discord package (if any)
    bundled_dir = Path(discord.__file__).resolve().parent / "bin"
    for name in ("libopus-0.x64.dll", "libopus-0.x86.dll"):
        p = bundled_dir / name
        if p.exists():
            candidates.append(str(p))

    for cand in candidates:
        try:
            discord.opus.load_opus(cand)
        except Exception:
            continue
        if discord.opus.is_loaded():
            print(f"[opus] Loaded: {cand}")
            return True

    try:
        default_loader = getattr(discord.opus, "_load_default", None)
        if default_loader and default_loader() and discord.opus.is_loaded():
            print("[opus] Loaded: discord default loader")
            return True
    except Exception:
        pass

    print("=" * 70)
    print("[opus] WARNING: Opus is NOT loaded. Nobody will hear anything!")
    print("[opus] Put opus.dll (or libopus-0.x64.dll, 64-bit) in this folder:")
    print(f"[opus]   {BASE_DIR}")
    print("[opus] then restart the bot.")
    print("=" * 70)
    return False


# --------------------------------------------------------------------------
# Text cleaning and language detection
# --------------------------------------------------------------------------
CODEBLOCK_RE = re.compile(r"```.*?```", re.S)
MD_LINK_RE = re.compile(r"\[([^\]]+)\]\(\s*https?://[^)]*\)")
MENTION_RE = re.compile(r"<@[!&]?\d+>|<#\d+>|<@&\d+>|@everyone|@here")
CUSTOM_EMOJI_RE = re.compile(r"<a?:\w+:\d+>")
TIMESTAMP_RE = re.compile(r"<t:\d+(?::[a-zA-Z])?>")
URL_RE = re.compile(r"(?:https?://|www\.)\S+", re.I)
EMOJI_RE = re.compile(
    "["
    "\U0001F000-\U0001FAFF"
    "\u2190-\u21FF"
    "\u2300-\u23FF"
    "\u2460-\u24FF"
    "\u25A0-\u27BF"
    "\u2900-\u297F"
    "\u2B00-\u2BFF"
    "\u3030\u303D\u3297\u3299"
    "\uFE0F\u20E3"
    "]+",
    flags=re.UNICODE,
)
DEVANAGARI_RE = re.compile(r"[\u0900-\u097F]")
LANG_PREFIX_RE = re.compile(r"^\s*(hi|en)\s*:\s*", re.I)

from dictionary import HINDI_ROMAN_WORDS  # single source of truth: see dictionary.py


def split_lang_prefix(text: str):
    m = LANG_PREFIX_RE.match(text)
    if not m:
        return None, text
    lang = "hi" if m.group(1).lower() == "hi" else "en"
    return lang, text[m.end():]


def clean_text(text: str) -> str:
    text = CODEBLOCK_RE.sub(" ", text)
    text = MD_LINK_RE.sub(r"\1", text)
    text = MENTION_RE.sub(" ", text)
    text = CUSTOM_EMOJI_RE.sub(" ", text)
    text = TIMESTAMP_RE.sub(" ", text)
    text = URL_RE.sub(" link ", text)
    text = re.sub(r"`([^`]*)`", r"\1", text)
    for pat in (
        r"\*\*\*(.+?)\*\*\*",
        r"\*\*(.+?)\*\*",
        r"\*(.+?)\*",
        r"__(.+?)__",
        r"~~(.+?)~~",
        r"\|\|(.+?)\|\|",
    ):
        text = re.sub(pat, r"\1", text, flags=re.S)
    text = re.sub(r"(?<!\w)_(.+?)_(?!\w)", r"\1", text)
    text = re.sub(r"^\s{0,3}(?:#{1,6}|>{1,3}|-#)\s+", "", text, flags=re.M)
    text = re.sub(r"[*_~`|]+", " ", text)
    text = EMOJI_RE.sub(" ", text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > MAX_CHARS:
        text = text[:MAX_CHARS].rstrip()
    return text


def detect_language(text: str) -> str:
    if DEVANAGARI_RE.search(text):
        return "hi"
    words = re.findall(r"[a-zA-Z]+", text.lower())
    if not words:
        return "en"
    hits = sum(1 for w in words if w in HINDI_ROMAN_WORDS)
    if hits >= 2 or (hits >= 1 and hits / len(words) >= 0.3):
        return "hi"
    return "en"


# --------------------------------------------------------------------------
# Per-guild state
# --------------------------------------------------------------------------
class GuildState:
    def __init__(self):
        self.queue: asyncio.Queue = asyncio.Queue(maxsize=MAX_QUEUE)
        self.worker = None
        self.text_channel_id = None
        self.voice_channel_id = None
        self.last_spoke = 0.0
        self.last_real_spoke = 0.0
        self.reconnecting = False  # v3: our own keepalive reconnect, not a kick/leave
        self.keepalive_task = None
        self.keepalive_count = 0
        self.mode = "auto"
        self.style = "default"
        self.play_lock = asyncio.Lock()
        self.join_lock = asyncio.Lock()
        self.generation = 0
        self.busy = False
        self.skip_pending = False
        self.dave_timed_out = False

    def clear_queue(self) -> int:
        n = 0
        while True:
            try:
                self.queue.get_nowait()
                n += 1
            except asyncio.QueueEmpty:
                break
        return n


states: dict = {}


def get_state(guild_id: int) -> GuildState:
    st = states.get(guild_id)
    if st is None:
        st = GuildState()
        states[guild_id] = st
    return st


# --------------------------------------------------------------------------
# Bot
# --------------------------------------------------------------------------
intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True
intents.guilds = True

bot_kwargs = dict(
    command_prefix=PREFIX,
    intents=intents,
    help_command=None,
    auto_sync_commands=False,
)
if GUILD_ID:
    bot_kwargs["debug_guilds"] = [GUILD_ID]
bot = commands.Bot(**bot_kwargs)

_startup_done = False


# --------------------------------------------------------------------------
# DAVE helpers
# --------------------------------------------------------------------------
def _candidate_objects(vc):
    objs = [vc]
    for name in ("_connection", "_voice_state", "voice_state"):
        o = getattr(vc, name, None)
        if o is not None and o is not vc:
            objs.append(o)
    return objs


def _probe(vc, names, call=True):
    """Return the first non-None attribute value, else None if it exists
    but is None, else MISSING if no object has the attribute."""
    found_none = False
    for obj in _candidate_objects(vc):
        for name in names:
            try:
                val = getattr(obj, name)
            except Exception:
                continue
            if call and callable(val):
                try:
                    val = val()
                except Exception:
                    continue
            if val is not None:
                return val
            found_none = True
    return None if found_none else MISSING


def dave_status(vc) -> dict:
    if vc is None:
        return {
            "can_encrypt": False, "ready": False, "dave_version": "n/a",
            "max_dave": "n/a", "has_dave_session": False,
        }
    session = _probe(vc, ("dave_session",), call=False)
    version = _probe(vc, ("dave_protocol_version", "dave_version"))
    max_version = _probe(vc, ("max_dave_protocol_version", "max_dave_version"))
    ce = _probe(vc, ("can_encrypt",))

    has_session = session is not MISSING and session is not None
    ready = False
    if has_session:
        r = getattr(session, "ready", MISSING)
        if callable(r):
            try:
                r = r()
            except Exception:
                r = False
        ready = bool(r) if r is not MISSING else False

    if ce is MISSING:
        if session is MISSING:
            can_encrypt = None  # this library build exposes no DAVE info
        else:
            ver_ok = version in (MISSING, None) or version != 0
            can_encrypt = bool(has_session and ready and ver_ok)
    else:
        can_encrypt = bool(ce)

    def show(v):
        return "unknown" if v is MISSING or v is None else v

    return {
        "can_encrypt": can_encrypt,
        "ready": ready,
        "dave_version": show(version),
        "max_dave": show(max_version),
        "has_dave_session": has_session,
    }


def format_dave(vc) -> str:
    d = dave_status(vc)
    return (
        f"can_encrypt={d['can_encrypt']} ready={d['ready']} "
        f"dave_version={d['dave_version']} max_dave={d['max_dave']} "
        f"has_dave_session={d['has_dave_session']}"
    )


async def wait_for_dave(vc, state: GuildState) -> bool:
    """Wait (only before playing audio) until can_encrypt is True."""
    status = dave_status(vc)
    if status["can_encrypt"] is None:
        print("[dave] This py-cord build exposes no DAVE status; continuing.")
        return True
    if status["can_encrypt"]:
        return True

    timeout = 3.0 if state.dave_timed_out else DAVE_WAIT_SECONDS
    print(f"[dave] Waiting up to {timeout:.0f}s for DAVE handshake: {format_dave(vc)}")
    loop = asyncio.get_running_loop()
    start = loop.time()
    while loop.time() - start < timeout:
        await asyncio.sleep(0.25)
        if not vc.is_connected():
            return False
        if dave_status(vc)["can_encrypt"]:
            print(f"[dave] Handshake done: {format_dave(vc)}")
            state.dave_timed_out = False
            return True
    state.dave_timed_out = True
    print(f"[dave] WARNING: can_encrypt still False after {timeout:.0f}s. "
          f"Discord may drop the audio. {format_dave(vc)}")
    return False


async def log_dave_progress(vc):
    """Background task after /join: prints DAVE status, never blocks /join."""
    try:
        loop = asyncio.get_running_loop()
        start = loop.time()
        last = None
        while loop.time() - start < DAVE_WAIT_SECONDS:
            if not vc.is_connected():
                return
            cur = format_dave(vc)
            if cur != last:
                print(f"[dave] {cur}")
                last = cur
            if dave_status(vc)["can_encrypt"] in (True, None):
                return
            await asyncio.sleep(0.5)
        print(f"[dave] WARNING: DAVE not ready 15s after join: {format_dave(vc)}")
    except Exception as e:
        print(f"[dave] progress logger error: {e!r}")


# --------------------------------------------------------------------------
# Audio playback
# --------------------------------------------------------------------------
async def play_with_fallback(vc, make_opus, make_pcm) -> bool:
    loop = asyncio.get_running_loop()
    for kind, make in (("FFmpegOpusAudio", make_opus), ("FFmpegPCMAudio", make_pcm)):
        if not vc.is_connected():
            return False
        try:
            source = make()
        except Exception as e:
            print(f"[audio] {kind} could not start: {e!r}")
            continue

        fut = loop.create_future()

        def after(error, fut=fut):
            def _set():
                if not fut.done():
                    fut.set_result(error)
            loop.call_soon_threadsafe(_set)

        try:
            if vc.is_playing():
                vc.stop()
            vc.play(source, after=after)
        except Exception as e:
            print(f"[audio] {kind} play() failed: {e!r}")
            try:
                source.cleanup()
            except Exception:
                pass
            continue

        print(f"[audio] Playing with {kind}")
        error = await fut
        if error is None:
            return True
        print(f"[audio] {kind} error: {error!r}")
    return False


def file_sources(path: str):
    def make_opus():
        return discord.FFmpegOpusAudio(path, executable=FFMPEG, options="-vn")

    def make_pcm():
        return discord.FFmpegPCMAudio(path, executable=FFMPEG, options="-vn")

    return make_opus, make_pcm


def tone_sources():
    spec = "sine=frequency=880:duration=3"

    def make_opus():
        return discord.FFmpegOpusAudio(
            spec, executable=FFMPEG, before_options="-f lavfi",
            options="-af volume=0.5",
        )

    def make_pcm():
        return discord.FFmpegPCMAudio(
            spec, executable=FFMPEG, before_options="-f lavfi",
            options="-af volume=0.5",
        )

    return make_opus, make_pcm


def silence_sources():
    """1s of silent audio, only to keep the voice UDP path alive."""
    spec = "anullsrc=r=48000:cl=stereo"

    def make_opus():
        return discord.FFmpegOpusAudio(
            spec, executable=FFMPEG,
            before_options=f"-f lavfi -t {KEEPALIVE_SILENCE_SECONDS}",
            options="-af volume=0",
        )

    def make_pcm():
        return discord.FFmpegPCMAudio(
            spec, executable=FFMPEG,
            before_options=f"-f lavfi -t {KEEPALIVE_SILENCE_SECONDS}",
            options="-af volume=0",
        )

    return make_opus, make_pcm


async def reconnect_voice(guild, state) -> bool:
    """Reconnect to the stored voice channel. Returns True if connected.

    v3: the disconnect fires on_voice_state_update for the bot itself,
    which used to tear down the TTS worker + keepalive and clear the
    queue — that is why v2's testtone worked (direct play) but queued
    text never spoke. The reconnecting flag tells that handler to
    leave the worker/queue alone, and we restart both here as a net.
    """
    if state.voice_channel_id is None:
        return False
    channel = guild.get_channel(state.voice_channel_id)
    if channel is None:
        return False
    state.reconnecting = True
    try:
        vc = guild.voice_client
        if vc is not None:
            try:
                await vc.disconnect(force=True)
            except Exception:
                pass
        try:
            await connect_self_deaf(channel)
        except Exception as e:
            print(f"[keepalive] reconnect failed: {e!r}")
            return False
        state.dave_timed_out = False
        print(f"[keepalive] reconnected to {channel}")
        ensure_worker(guild.id)
        ensure_keepalive(guild.id)
        return True
    finally:
        state.reconnecting = False


# v5: reconnect only when speech is actually needed after idle.
# The 5-min timer reconnect is gone (v4 — it made the rejoin sound), but
# silent packets alone do NOT keep the media path alive, so a message
# after minutes of silence would play into a dead connection. Fix: before
# playing, if nothing real was spoken for 2 min, do ONE fresh reconnect.
# No sound while idle — the reconnect happens only when someone speaks.
RECONNECT_ON_DEMAND_IDLE_SECONDS = 120.0


async def maybe_reconnect_if_idle(guild, state) -> None:
    idle_for = time.time() - (state.last_real_spoke or state.last_spoke or time.time())
    if idle_for < RECONNECT_ON_DEMAND_IDLE_SECONDS:
        return
    print(f"[keepalive] idle {idle_for:.0f}s, reconnecting before play")
    async with state.play_lock:
        if await reconnect_voice(guild, state):
            state.last_real_spoke = time.time()
            state.last_spoke = time.time()


async def voice_keepalive_loop(guild_id: int):
    """While in VC, send 1s silence every 20s so the media path survives idle."""
    state = get_state(guild_id)
    print(f"[keepalive] started for guild {guild_id}")
    try:
        while True:
            await asyncio.sleep(KEEPALIVE_INTERVAL_SECONDS)
            guild = bot.get_guild(guild_id)
            if guild is None:
                return
            vc = guild.voice_client
            if vc is None or not vc.is_connected():
                print("[keepalive] voice client gone, trying reconnect")
                if await reconnect_voice(guild, state):
                    continue
                return
            if vc.is_playing():
                continue
            # v4: NO timer-based reconnect any more. The 5-min full
            # reconnect was the rejoin sound the user hears every 5-10
            # min — Discord plays its join sound on every reconnect.
            # The 20s silent packets keep the media path alive instead;
            # reconnect_voice is kept only for when the voice client is
            # actually gone (see the check above).
            async with state.play_lock:
                if vc.is_playing():
                    continue
                ok = await play_with_fallback(vc, *silence_sources())
                state.keepalive_count += 1
                print(f"[keepalive] silent packet sent, ok={ok}, "
                      f"latency={getattr(vc, 'latency', None)}")
    except asyncio.CancelledError:
        print(f"[keepalive] stopped for guild {guild_id}")
        raise


def ensure_keepalive(guild_id: int):
    state = get_state(guild_id)
    if state.keepalive_task is None or state.keepalive_task.done():
        state.keepalive_task = asyncio.create_task(voice_keepalive_loop(guild_id))


def stop_keepalive(state):
    if state.keepalive_task is not None and not state.keepalive_task.done():
        state.keepalive_task.cancel()
    state.keepalive_task = None


async def synthesize(text: str, voice: str) -> bool:
    for attempt in (1, 2):
        try:
            comm = edge_tts.Communicate(text, voice)
            await asyncio.wait_for(comm.save(str(LAST_TTS)), timeout=30)
            if LAST_TTS.exists() and LAST_TTS.stat().st_size > 0:
                return True
        except asyncio.CancelledError:
            raise
        except Exception as e:
            print(f"[tts] attempt {attempt} failed ({voice}): {e!r}")
            await asyncio.sleep(0.5)
    return False


async def tts_worker(guild_id: int):
    state = get_state(guild_id)
    print(f"[worker] started for guild {guild_id}")
    try:
        while True:
            text, lang = await state.queue.get()
            state.busy = True
            gen = state.generation
            try:
                guild = bot.get_guild(guild_id)
                vc = guild.voice_client if guild else None
                if vc is None or not vc.is_connected():
                    continue
                voice = VOICES[state.style][lang]
                print(f"[tts] ({lang}/{voice}) {text!r}")
                if not await synthesize(text, voice):
                    print("[tts] synthesis failed, skipping message")
                    continue
                if gen != state.generation:
                    continue
                if state.skip_pending:
                    state.skip_pending = False
                    continue
                # v5: fresh connection if the media path went stale in idle.
                await maybe_reconnect_if_idle(guild, state)
                vc = guild.voice_client
                if vc is None or not vc.is_connected():
                    continue
                await wait_for_dave(vc, state)
                if gen != state.generation or not vc.is_connected():
                    continue
                async with state.play_lock:
                    make_opus, make_pcm = file_sources(str(LAST_TTS))
                    ok = await play_with_fallback(vc, make_opus, make_pcm)
                    if not ok:
                        # Play failed into a stale path: one reconnect + retry.
                        print("[audio] play failed, reconnecting and retrying once")
                        if await reconnect_voice(guild, state):
                            vc = guild.voice_client
                            if vc is not None and vc.is_connected():
                                await wait_for_dave(vc, state)
                                make_opus, make_pcm = file_sources(str(LAST_TTS))
                                ok = await play_with_fallback(vc, make_opus, make_pcm)
                    if ok:
                        state.last_spoke = time.time()
                        state.last_real_spoke = time.time()
                    if not ok:
                        print("[audio] Could not play this message.")
            except asyncio.CancelledError:
                raise
            except Exception:
                print("[worker] error:")
                traceback.print_exc()
            finally:
                state.busy = False
    except asyncio.CancelledError:
        print(f"[worker] stopped for guild {guild_id}")
        raise


def ensure_worker(guild_id: int):
    state = get_state(guild_id)
    if state.worker is None or state.worker.done():
        state.worker = asyncio.create_task(tts_worker(guild_id))


async def teardown(guild: discord.Guild, disconnect: bool = True) -> int:
    """Stop worker, clear queue, stop audio, optionally disconnect."""
    state = get_state(guild.id)
    state.generation += 1
    state.skip_pending = False
    cleared = state.clear_queue()
    vc = guild.voice_client
    if vc is not None:
        try:
            vc.stop()
        except Exception:
            pass
    if state.worker is not None and not state.worker.done():
        state.worker.cancel()
    state.worker = None
    stop_keepalive(state)
    if disconnect and vc is not None:
        try:
            await vc.disconnect(force=True)
        except Exception as e:
            print(f"[voice] disconnect error: {e!r}")
    return cleared


# --------------------------------------------------------------------------
# Shared command logic
# --------------------------------------------------------------------------
async def connect_self_deaf(channel):
    try:
        return await channel.connect(
            timeout=15.0, reconnect=True, self_deaf=True, self_mute=False
        )
    except TypeError:
        vc = await channel.connect(timeout=15.0, reconnect=True)
        try:
            await channel.guild.change_voice_state(
                channel=channel, self_deaf=True, self_mute=False
            )
        except Exception as e:
            print(f"[voice] could not self-deafen: {e!r}")
        return vc


async def do_join(guild: discord.Guild, member, text_channel) -> str:
    voice = getattr(member, "voice", None)
    if not voice or not voice.channel:
        return "❌ Join a voice channel first, then use /join."
    channel = voice.channel
    perms = channel.permissions_for(guild.me)
    if not (perms.connect and perms.speak):
        return f"❌ I need Connect and Speak permission in {channel.mention}."

    state = get_state(guild.id)
    async with state.join_lock:
        state.text_channel_id = text_channel.id
        state.voice_channel_id = channel.id
        vc = guild.voice_client

        if vc is not None and vc.is_connected():
            if vc.channel and vc.channel.id == channel.id:
                ensure_worker(guild.id)
                ensure_keepalive(guild.id)
                return f"✅ I'm already in {channel.mention}."
            try:
                await vc.move_to(channel)
                await guild.change_voice_state(
                    channel=channel, self_deaf=True, self_mute=False
                )
            except Exception as e:
                return f"❌ Could not move to {channel.mention}: {e}"
            ensure_worker(guild.id)
            ensure_keepalive(guild.id)
            return f"✅ Moved to {channel.mention}."

        if vc is not None:  # stale, half-open client
            try:
                await vc.disconnect(force=True)
            except Exception:
                pass

        try:
            vc = await connect_self_deaf(channel)
        except asyncio.TimeoutError:
            if guild.voice_client:
                try:
                    await guild.voice_client.disconnect(force=True)
                except Exception:
                    pass
            return "❌ Timed out connecting to voice. Try /join again."
        except Exception as e:
            print(f"[voice] join error: {e!r}")
            traceback.print_exc()
            return f"❌ Could not join voice: {e}"

        state.dave_timed_out = False
        state.last_spoke = time.time()
        state.last_real_spoke = time.time()
        ensure_worker(guild.id)
        ensure_keepalive(guild.id)
        asyncio.create_task(log_dave_progress(vc))
        return (
            f"✅ Joined {channel.mention}. I'll read messages from people in this "
            f"voice channel (voice chat + {text_channel.mention})."
        )


def check_can_speak(guild, member):
    """Returns (state, vc, error_message)."""
    if guild is None:
        return None, None, "❌ This only works in a server."
    vc = guild.voice_client
    if vc is None or not vc.is_connected():
        return None, None, "❌ I'm not in a voice channel. Use /join first."
    voice = getattr(member, "voice", None)
    if not voice or not voice.channel or voice.channel.id != vc.channel.id:
        return None, None, "❌ You must be in my voice channel to do that."
    return get_state(guild.id), vc, None


def speak_text(text: str, lang: str) -> str:
    """Accent fix: Roman Hindi ko Devanagari me badlo, taaki Hindi voice sahi bole.

    Sirf tab jab lang hindi ho aur text me Devanagari pehle se na ho.
    English messages ko kabhi convert nahi karta.
    """
    if lang == "hi" and not DEVANAGARI_RE.search(text):
        return to_devanagari(text)
    return text


def build_item(raw: str, state: GuildState):
    prefix_lang, body = split_lang_prefix(raw)
    text = clean_text(body)
    if not text or not re.search(r"\w", text):
        return None
    if prefix_lang:
        lang = prefix_lang
    elif state.mode == "hindi":
        lang = "hi"
    elif state.mode == "english":
        lang = "en"
    else:
        lang = detect_language(text)
        # Accent fix: single entry point — /say, !say and VC chat all go
        # through build_item -> enqueue_text, so converting here covers all.
        text = speak_text(text, lang)
    return text, lang


def enqueue_text(state: GuildState, raw: str) -> str:
    item = build_item(raw, state)
    if item is None:
        return "empty"
    try:
        state.queue.put_nowait(item)
    except asyncio.QueueFull:
        return "full"
    return "ok"


async def run_tone(guild, state, vc) -> bool:
    await maybe_reconnect_if_idle(guild, state)
    vc = guild.voice_client
    if vc is None or not vc.is_connected():
        return False
    await wait_for_dave(vc, state)
    async with state.play_lock:
        make_opus, make_pcm = tone_sources()
        ok = await play_with_fallback(vc, make_opus, make_pcm)
        if ok:
            state.last_spoke = time.time()
            state.last_real_spoke = time.time()
        return ok


def pkg_version(*names) -> str:
    for n in names:
        try:
            return importlib.metadata.version(n)
        except importlib.metadata.PackageNotFoundError:
            continue
    return "not installed"


def build_diag(guild) -> str:
    vc = guild.voice_client if guild else None
    connected = bool(vc and vc.is_connected())
    state = get_state(guild.id) if guild else GuildState()
    lib = "py-cord" if pkg_version("py-cord") != "not installed" else "discord.py"
    d = dave_status(vc if connected else None)
    try:
        import davey
        davey_ver = getattr(davey, "__version__", None) or pkg_version("davey")
    except Exception:
        davey_ver = "not installed"
    try:
        import nacl
        nacl_ver = getattr(nacl, "__version__", None) or pkg_version("PyNaCl")
    except Exception:
        nacl_ver = "not installed"
    lines = [
        f"library: {lib} {discord.__version__}",
        f"davey: {davey_ver}",
        f"PyNaCl: {nacl_ver}",
        f"opus loaded: {discord.opus.is_loaded()}",
        f"VC connected: {connected}",
        f"DAVE can_encrypt: {d['can_encrypt']}",
        f"ready: {d['ready']}",
        f"dave_version: {d['dave_version']}",
        f"max_dave: {d['max_dave']}",
        f"has_dave_session: {d['has_dave_session']}",
        f"voice latency: {getattr(vc, 'latency', None) if connected else None}",
        f"keepalives sent: {state.keepalive_count}",
        f"voice mode: {state.mode}",
        f"voice style: {state.style}",
        f"queue size: {state.queue.qsize()}",
    ]
    return "\n".join(lines)


# --------------------------------------------------------------------------
# Slash commands
# --------------------------------------------------------------------------
@bot.slash_command(name="join", description="Join your voice channel and read chat aloud")
async def slash_join(ctx: discord.ApplicationContext):
    if ctx.guild is None:
        return await ctx.respond("❌ This only works in a server.")
    await ctx.defer()
    msg = await do_join(ctx.guild, ctx.author, ctx.channel)
    await ctx.respond(msg)


@bot.slash_command(name="leave", description="Leave the voice channel and clear the queue")
async def slash_leave(ctx: discord.ApplicationContext):
    if ctx.guild is None:
        return await ctx.respond("❌ This only works in a server.")
    await ctx.defer()
    vc = ctx.guild.voice_client
    if vc is None:
        state = get_state(ctx.guild.id)
        state.clear_queue()
        return await ctx.respond("I'm not in a voice channel.")
    cleared = await teardown(ctx.guild, disconnect=True)
    await ctx.respond(f"👋 Left the voice channel. Cleared {cleared} queued message(s).")


@bot.slash_command(name="say", description="Speak the given text in the voice channel")
@option("text", description="What should I say?")
async def slash_say(ctx: discord.ApplicationContext, text: str):
    state, vc, err = check_can_speak(ctx.guild, ctx.author)
    if err:
        return await ctx.respond(err)
    result = enqueue_text(state, text)
    if result == "ok":
        await ctx.respond("🔊 Queued.")
    elif result == "full":
        await ctx.respond(f"⚠️ Queue is full ({MAX_QUEUE}). Try again in a moment.")
    else:
        await ctx.respond("❌ Nothing speakable in that text.")


@bot.slash_command(name="voice", description="Change voice mode")
@option("mode", description="auto, hindi or english", choices=list(VOICE_MODES))
async def slash_voice(ctx: discord.ApplicationContext, mode: str):
    if ctx.guild is None:
        return await ctx.respond("❌ This only works in a server.")
    get_state(ctx.guild.id).mode = mode
    await ctx.respond(f"✅ Voice mode: **{mode}**")


@bot.slash_command(name="voicestyle", description="Change voice style")
@option("style", description="default, male, indian or indian_male", choices=list(VOICE_STYLES))
async def slash_voicestyle(ctx: discord.ApplicationContext, style: str):
    if ctx.guild is None:
        return await ctx.respond("❌ This only works in a server.")
    get_state(ctx.guild.id).style = style
    v = VOICES[style]
    await ctx.respond(f"✅ Voice style: **{style}** (Hindi: {v['hi']}, English: {v['en']})")


@bot.slash_command(name="stop", description="Stop speaking now and clear the queue")
async def slash_stop(ctx: discord.ApplicationContext):
    if ctx.guild is None:
        return await ctx.respond("❌ This only works in a server.")
    state = get_state(ctx.guild.id)
    state.generation += 1
    state.skip_pending = False
    cleared = state.clear_queue()
    vc = ctx.guild.voice_client
    if vc is not None:
        try:
            vc.stop()
        except Exception:
            pass
    await ctx.respond(f"⏹️ Stopped. Cleared {cleared} queued message(s).")


@bot.slash_command(name="skip", description="Skip the current message")
async def slash_skip(ctx: discord.ApplicationContext):
    if ctx.guild is None:
        return await ctx.respond("❌ This only works in a server.")
    state = get_state(ctx.guild.id)
    vc = ctx.guild.voice_client
    if vc is not None and (vc.is_playing() or vc.is_paused()):
        vc.stop()
        return await ctx.respond("⏭️ Skipped.")
    if state.busy:
        state.skip_pending = True
        return await ctx.respond("⏭️ Skipping the message that's being prepared.")
    await ctx.respond("Nothing to skip.")


@bot.slash_command(name="status", description="Show bot status")
async def slash_status(ctx: discord.ApplicationContext):
    if ctx.guild is None:
        return await ctx.respond("❌ This only works in a server.")
    state = get_state(ctx.guild.id)
    vc = ctx.guild.voice_client
    if vc is not None and vc.is_connected() and vc.channel:
        where = vc.channel.mention
    else:
        where = "not connected"
    await ctx.respond(
        f"**Voice channel:** {where}\n"
        f"**Voice mode:** {state.mode}\n"
        f"**Voice style:** {state.style}\n"
        f"**Queue size:** {state.queue.qsize()}/{MAX_QUEUE}"
    )


@bot.slash_command(name="diag", description="Show diagnostics for voice and DAVE")
async def slash_diag(ctx: discord.ApplicationContext):
    text = build_diag(ctx.guild)
    print("[diag]\n" + text)
    # Ephemeral: /diag sirf usko dikhe jisne command chalaya, sabko nahi.
    await ctx.respond(f"```\n{text}\n```", ephemeral=True)


@bot.slash_command(name="testtone", description="Play a 3 second 880 Hz test tone")
async def slash_testtone(ctx: discord.ApplicationContext):
    state, vc, err = check_can_speak(ctx.guild, ctx.author)
    if err:
        return await ctx.respond(err)
    await ctx.respond("🔔 Playing a 3 second 880 Hz tone...")
    ok = await run_tone(ctx.guild, state, vc)
    if not ok:
        try:
            await ctx.followup.send("⚠️ Tone failed. Check /diag and the console.")
        except Exception:
            pass


# --------------------------------------------------------------------------
# /dictionary — add words from Discord (no GitHub needed for the session)
# --------------------------------------------------------------------------
dict_group = bot.create_group(
    "dictionary", "Roman Hindi dictionary: add/list/remove words the bot should say right"
)


@dict_group.command(name="add", description="Add a Roman Hindi word: /dictionary add word: krna meaning: करना")
async def dict_add(ctx: discord.ApplicationContext, word: str, meaning: str):
    if ctx.guild is None:
        return await ctx.respond("❌ This only works in a server.")
    perms = getattr(ctx.author, "guild_permissions", None)
    is_owner = ctx.author.id == ctx.guild.owner_id
    if not is_owner and not (perms and perms.manage_guild):
        return await ctx.respond("❌ Only the server owner / admins can add dictionary words.")
    word = word.strip().lower()
    meaning = meaning.strip()
    if not word or not re.fullmatch(r"[a-z]+", word):
        return await ctx.respond("❌ Word ek hi Roman Hindi word hona chahiye, sirf a-z, jaise `krna`.")
    if not meaning:
        return await ctx.respond("❌ Meaning bhi do, jaise `करना`.")
    # Meaning Devanagari me ho to waisa hi rakho; Roman me likha ho to convert karo.
    if not DEVANAGARI_RE.search(meaning):
        meaning = to_devanagari(meaning.lower())
    WORD_MAP[word] = meaning
    USER_WORDS[word] = meaning
    HINDI_ROMAN_WORDS.add(word)  # so the word is detected as Hindi too
    save_user_words()
    sync = sync_user_words_to_github(f"add {word}")
    if sync == "ok":
        note = "GitHub pe bhi save ho gaya, restart ke baad bhi rahega."
    elif sync == "no_token":
        note = "⚠️ GitHub sync abhi off hai (Render me GITHUB_TOKEN nahi hai) — word abhi chalega, par restart pe chala jayega."
    else:
        note = f"⚠️ GitHub sync fail ho gaya ({sync}) — word abhi chalega, `/dictionary list` se list mujhe bhej dena."
    await ctx.respond(
        f"✅ Added: **{word}** → **{meaning}**\n"
        f"Ab se bot `{word}` ko `{meaning}` bolega. {note}"
    )


@dict_group.command(name="list", description="Show words added from Discord with /dictionary add")
async def dict_list(ctx: discord.ApplicationContext):
    if not USER_WORDS:
        return await ctx.respond("Dictionary me abhi koi naya word add nahi hua hai. `/dictionary add` se add karo.")
    lines = [f"{k} → {v}" for k, v in sorted(USER_WORDS.items())]
    text = "\n".join(lines)
    if len(text) > 1800:
        text = text[:1800] + "\n… (aur bhi hain)"
    await ctx.respond(f"**Discord se add kiye gaye words ({len(USER_WORDS)}):**\n```\n{text}\n```")


@dict_group.command(name="remove", description="Remove a word added with /dictionary add")
async def dict_remove(ctx: discord.ApplicationContext, word: str):
    if ctx.guild is None:
        return await ctx.respond("❌ This only works in a server.")
    perms = getattr(ctx.author, "guild_permissions", None)
    is_owner = ctx.author.id == ctx.guild.owner_id
    if not is_owner and not (perms and perms.manage_guild):
        return await ctx.respond("❌ Only the server owner / admins can remove dictionary words.")
    word = word.strip().lower()
    if word not in USER_WORDS:
        return await ctx.respond(f"❌ `{word}` Discord se add nahi hua tha (built-in word hai to remove nahi hota).")
    del USER_WORDS[word]
    save_user_words()
    sync_user_words_to_github(f"remove {word}")
    await ctx.respond(f"✅ Removed: **{word}**. Ab wo phonetic fallback se bolega.")


@dict_group.command(name="sync", description="Push Discord words to GitHub / pull words from GitHub")
async def dict_sync(ctx: discord.ApplicationContext):
    perms = getattr(ctx.author, "guild_permissions", None)
    is_owner = ctx.guild is not None and ctx.author.id == ctx.guild.owner_id
    if ctx.guild is not None and not is_owner and not (perms and perms.manage_guild):
        return await ctx.respond("❌ Only the server owner / admins can sync.")
    pulled = load_user_words_from_github()
    save_user_words()
    pushed = sync_user_words_to_github("sync")
    await ctx.respond(
        f"GitHub se {pulled} words liye, "
        f"GitHub pe push: {'✅ ho gaya' if pushed == 'ok' else '⚠️ ' + pushed}. "
        f"Total user words: {len(USER_WORDS)}."
    )


# --------------------------------------------------------------------------
# Text (prefix) commands as backup
# --------------------------------------------------------------------------
@bot.command(name="testtone")
async def prefix_testtone(ctx: commands.Context):
    state, vc, err = check_can_speak(ctx.guild, ctx.author)
    if err:
        return await ctx.send(err)
    try:
        await ctx.message.add_reaction("🔔")
    except Exception:
        pass
    ok = await run_tone(ctx.guild, state, vc)
    if not ok:
        await ctx.send("⚠️ Tone failed. Check /diag and the console.")


@bot.command(name="say")
async def prefix_say(ctx: commands.Context, *, text: str):
    state, vc, err = check_can_speak(ctx.guild, ctx.author)
    if err:
        return await ctx.send(err)
    result = enqueue_text(state, text)
    if result == "ok":
        try:
            await ctx.message.add_reaction("🔊")
        except Exception:
            pass
    elif result == "full":
        await ctx.send(f"⚠️ Queue is full ({MAX_QUEUE}).")
    else:
        await ctx.send("❌ Nothing speakable in that text.")


@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        return
    if isinstance(error, commands.MissingRequiredArgument):
        try:
            await ctx.send(f"Usage: `{PREFIX}say <text>`")
        except Exception:
            pass
        return
    print(f"[command error] {error!r}")


@bot.event
async def on_application_command_error(ctx, error):
    print(f"[slash error] /{getattr(ctx.command, 'name', '?')}: {error!r}")
    traceback.print_exception(type(error), error, error.__traceback__)
    try:
        await ctx.respond(f"❌ Error: {error}")
    except Exception:
        pass


# --------------------------------------------------------------------------
# Reading chat aloud
# --------------------------------------------------------------------------
@bot.listen("on_message")
async def speak_chat_messages(message: discord.Message):
    if message.author.bot or message.guild is None:
        return
    if message.type not in (discord.MessageType.default, discord.MessageType.reply):
        return
    if not message.content or message.content.startswith(PREFIX):
        return

    state = states.get(message.guild.id)
    if state is None:
        return
    vc = message.guild.voice_client
    if vc is None or not vc.is_connected() or vc.channel is None:
        return

    in_vc_chat = message.channel.id == vc.channel.id
    in_join_channel = state.text_channel_id is not None and message.channel.id == state.text_channel_id
    if not (in_vc_chat or in_join_channel):
        return

    voice = getattr(message.author, "voice", None)
    if not voice or not voice.channel or voice.channel.id != vc.channel.id:
        return

    result = enqueue_text(state, message.content)
    if result == "full":
        print("[queue] full, dropped a message")


@bot.event
async def on_voice_state_update(member, before, after):
    if bot.user is None or member.id != bot.user.id:
        return
    if before.channel is not None and after.channel is None:
        # The bot left voice (kicked, moved out, or /leave). Clean up quietly.
        state = states.get(member.guild.id)
        if state and state.reconnecting:
            # v3: this disconnect is our own keepalive reconnect — the
            # worker, queue and keepalive must survive it.
            return
        if state:
            state.generation += 1
            state.clear_queue()
            if state.worker is not None and not state.worker.done():
                state.worker.cancel()
            state.worker = None
            stop_keepalive(state)


# --------------------------------------------------------------------------
# Startup / slash sync
# --------------------------------------------------------------------------
async def sync_slash_commands():
    app_id = bot.user.id
    try:
        if GUILD_ID:
            print(f"[sync] Clearing old commands in guild {GUILD_ID} ...")
            await bot.http.bulk_upsert_guild_commands(app_id, GUILD_ID, [])
        await bot.sync_commands()
        if GUILD_ID:
            cmds = await bot.http.get_guild_commands(app_id, GUILD_ID)
            names = sorted(c["name"] for c in cmds)
            print(f"[sync] Synced {len(names)} command(s) to guild {GUILD_ID}: {', '.join('/' + n for n in names)}")
        else:
            cmds = await bot.http.get_global_commands(app_id)
            names = sorted(c["name"] for c in cmds)
            print(f"[sync] Synced {len(names)} global command(s): {', '.join('/' + n for n in names)}")
            print("[sync] Tip: set DISCORD_GUILD_ID in .env for instant sync (global can take a while).")
    except discord.Forbidden:
        print("[sync] ERROR: Missing Access. Re-invite the bot with the "
              "'applications.commands' scope, and check DISCORD_GUILD_ID.")
    except Exception as e:
        print(f"[sync] ERROR syncing commands: {e!r}")
        traceback.print_exc()


@bot.event
async def on_ready():
    global _startup_done
    print(f"[bot] Logged in as {bot.user} (id {bot.user.id})")
    if _startup_done:
        return
    _startup_done = True

    load_opus_library()
    if shutil.which(FFMPEG) is None and not Path(FFMPEG).exists():
        print("[ffmpeg] WARNING: ffmpeg not found. Install it and add it to PATH "
              "(or put ffmpeg.exe next to bot.py).")
    else:
        print(f"[ffmpeg] Using: {FFMPEG}")
    print("[bot] Version info:")
    for line in build_diag(None).splitlines()[:4]:
        print(f"[bot]   {line}")

    dv = pkg_version("davey")
    m = re.match(r"(\d+)\.(\d+)", dv)
    if m and (int(m.group(1)), int(m.group(2))) >= (0, 2):
        print("=" * 70)
        print(f"[dave] WARNING: davey {dv} is installed. davey 0.2+ makes bots join")
        print("[dave] voice but stay SILENT. Fix:")
        print('[dave]   pip uninstall -y davey')
        print('[dave]   pip install "davey>=0.1.7,<0.2"')
        print("=" * 70)

    await sync_slash_commands()
    print("[bot] Ready. Use /join in a server (or !say / !testtone after joining).")


def main():
    if not TOKEN or TOKEN == "PASTE_YOUR_BOT_TOKEN_HERE":
        print("ERROR: DISCORD_TOKEN is missing. Copy .env.example to .env and paste your bot token.")
        sys.exit(1)
    load_opus_library()
    bot.run(TOKEN)


if __name__ == "__main__":
    main()
