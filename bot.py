"""
Discord Hindi/English TTS bot (free: edge-tts, no paid API).

- Joins a voice channel only on /join, leaves only on /leave.
- Reads text chat (voice channel chat + the channel where /join was used)
  from users who are in the same voice channel as the bot.
- Works on Windows, Python 3.11+, needs ffmpeg installed.
"""

import asyncio
import ctypes.util
import importlib.metadata
import os
import re
import shutil
import sys
import traceback
from pathlib import Path

import discord
import edge_tts
from discord import option
from discord.ext import commands
from dotenv import load_dotenv

import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

def _keep_alive():
    port = int(os.environ.get("PORT", "10000"))
    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"OK")
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
LAST_TTS = BASE_DIR / "last_tts.mp3"

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

HINDI_ROMAN_WORDS = {
    "kaise", "kaisa", "kaisi", "ho", "tum", "tumhe", "tumhara", "tumhari",
    "mera", "meri", "mere", "hai", "hain", "nahi", "nahin", "kya", "aaj",
    "bahut", "accha", "acha", "achha", "raha", "rahi", "rahe", "gaya",
    "gayi", "gaye", "mujhe", "mujhko", "aap", "kaun", "kyun", "kyu", "kab",
    "kahan", "kahaan", "mein", "hum", "humko", "yaar", "bhai", "theek",
    "thik", "karo", "karna", "kar", "abhi", "chalo", "bolo", "sab", "kuch",
    "koi", "lekin", "toh", "tha", "thi", "hoga", "hogi", "wala", "wali",
    "aur", "bhi", "apna", "apni", "unka", "uska", "iska", "kitna", "kitni",
    "kaha", "khana", "paani", "ghar", "dost", "samajh", "pata", "matlab",
}


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
                await wait_for_dave(vc, state)
                if gen != state.generation or not vc.is_connected():
                    continue
                async with state.play_lock:
                    make_opus, make_pcm = file_sources(str(LAST_TTS))
                    ok = await play_with_fallback(vc, make_opus, make_pcm)
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
        vc = guild.voice_client

        if vc is not None and vc.is_connected():
            if vc.channel and vc.channel.id == channel.id:
                ensure_worker(guild.id)
                return f"✅ I'm already in {channel.mention}."
            try:
                await vc.move_to(channel)
                await guild.change_voice_state(
                    channel=channel, self_deaf=True, self_mute=False
                )
            except Exception as e:
                return f"❌ Could not move to {channel.mention}: {e}"
            ensure_worker(guild.id)
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
        ensure_worker(guild.id)
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
    await wait_for_dave(vc, state)
    async with state.play_lock:
        make_opus, make_pcm = tone_sources()
        return await play_with_fallback(vc, make_opus, make_pcm)


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
    await ctx.respond(f"```\n{text}\n```")


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
        if state:
            state.generation += 1
            state.clear_queue()
            if state.worker is not None and not state.worker.done():
                state.worker.cancel()
            state.worker = None


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
