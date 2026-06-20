# jarvis_main.py — J.A.R.V.I.S. Core Engine
# Senior Engineer refactor: streaming TTS, SQLite memory, JARVIS personality,
# cinematic boot sequence, pun responses, yaml config, clean architecture.
import speech_recognition as sr
import threading
import time
import sqlite3
import asyncio
import base64
import difflib
import glob
import json
import os
import re
import shutil
import subprocess
import uuid
import webbrowser
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from queue import Queue
from threading import RLock
from typing import Callable

import numpy as np
import requests
import cv2
import yaml

try:
    import mss
except ImportError:
    mss = None

from edge_tts import Communicate
from llm import LocalLLM
from power_actions import system_action

# ─────────────────────────────────────────────────────────────────────────────
# CONFIG LOADER
# ─────────────────────────────────────────────────────────────────────────────
def _load_config() -> dict:
    cfg_path = Path(__file__).parent / "config" / "jarvis.yaml"
    if cfg_path.exists():
        with open(cfg_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    return {}

_CFG = _load_config()

def _cfg(section: str, key: str, default=None):
    return _CFG.get(section, {}).get(key, default)

# Derived constants from config
OLLAMA_URL   = _cfg("llm",    "url",          "http://localhost:11434")
VISION_MODEL = _cfg("vision", "model",        "llava:13b")
CAM_INDEX    = int(_cfg("vision", "camera_index", 0))
VLM_TIMEOUT  = int(_cfg("vision", "timeout_sec",  90))
MAX_IMG_SIDE = int(_cfg("vision", "max_image_side", 896))

# ─────────────────────────────────────────────────────────────────────────────
# PERSONALITY — wit & puns
# ─────────────────────────────────────────────────────────────────────────────
_WIT_ACKS = [
    "Right away, Sir.",
    "Consider it done.",
    "On it.",
    "Of course.",
    "Naturally.",
    "Already ahead of you, Sir.",
    "As you wish.",
    "It would be my pleasure. A low bar, admittedly, but a pleasure nonetheless.",
    "Done. You're welcome.",
    "Executed. Do try to look impressed.",
    "Completed. I've added it to my list of trivial achievements.",
    "Handled. I hope this frees you up for something equally unchallenging.",
]

_WIT_THINKING = [
    "Accessing...",
    "Cross-referencing...",
    "One moment, Sir.",
    "Consulting the archives...",
    "Processing. Please do not pace.",
    "Searching. Your patience is... noted.",
    "Querying my vast and underappreciated intelligence...",
    "Thinking. It happens.",
    "Allow me to pretend this requires effort.",
]

# App-specific quips — dry, not sycophantic
_APP_QUIPS = {
    "spotify":              "Opening Spotify, Sir. Your taste in music remains… consistent.",
    "youtube":              "Opening YouTube. I shall refrain from commenting on the watch history.",
    "chrome":               "Opening Chrome. I've taken the liberty of not judging your tabs.",
    "google chrome":        "Opening Chrome. I've taken the liberty of not judging your tabs.",
    "visual studio code":   "Opening VS Code. Shall I also prepare excuses for the compiler?",
    "vs code":              "Opening VS Code. Shall I also prepare excuses for the compiler?",
    "calculator":           "The Calculator, Sir. Even geniuses need training wheels occasionally.",
    "notepad":              "Opening Notepad. The timeless canvas of the technologically humble.",
    "discord":              "Opening Discord. Your social obligations await, Sir.",
    "whatsapp":             "Opening WhatsApp. I'll pretend I can't read the messages.",
    "steam":                "Opening Steam, Sir. I'm sure this is 'just to check the library'.",
    "task manager":         "Opening Task Manager. Hunting season is open.",
    "microsoft edge":       "Opening Edge. Brave choice, Sir. Truly.",
    "settings":             "Opening Settings. Try not to break anything critical.",
    "file explorer":        "Opening File Explorer, Sir. The organized chaos awaits.",
    "control panel":        "Opening Control Panel. The last bastion of Windows XP nostalgia.",
    "terminal":             "Opening Terminal. I trust you know what you're doing. Mostly.",
    "cmd":                  "Opening Command Prompt. Old school. Respect.",
    "netflix":              "Opening Netflix. Productivity was a nice concept.",
    "clock":                "Opening Clock. Presumably you've misplaced the one on every device you own.",
    "camera":               "Opening Camera. Smile, Sir. Or don't. Statistically it makes little difference.",
    "photos":               "Opening Photos. Memory lane awaits. Please drive carefully.",
    "paint":                "Opening Paint. The Renaissance would have been considerably shorter.",
    "mail":                 "Opening Mail. I'd say 'you've got mail', but the bar is already low enough.",
    "microsoft word":       "Opening Word. I'll have the formatting issues ready when you are.",
    "word":                 "Opening Word. I'll have the formatting issues ready when you are.",
    "microsoft excel":      "Opening Excel. Spreadsheets: because someone has to care about the numbers.",
    "excel":                "Opening Excel. Spreadsheets: because someone has to care about the numbers.",
    "powerpoint":           "Opening PowerPoint. The world will wait with bated breath.",
    "microsoft powerpoint": "Opening PowerPoint. The world will wait with bated breath.",
    "obs":                  "Opening OBS. Broadcasting your genius to an unsuspecting world.",
    "blender":              "Opening Blender. Artistic ambition and technical suffering, combined.",
    "vlc":                  "Opening VLC. It plays everything. Even things that probably shouldn't be played.",
    "zoom":                 "Opening Zoom. Mute yourself. You know why.",
    "teams":                "Opening Teams. Another meeting that could have been an email.",
}

_BOOT_LINES = [
    ("Initializing J.A.R.V.I.S. — Just A Rather Very Intelligent System.", 0.2),
    ("Running neural subsystem diagnostics… all nominal. As expected.", 0.2),
    ("Voice synthesis… online. You're welcome.", 0.15),
    ("Memory banks… intact. Your secrets remain safe. Mostly.", 0.15),
    ("Launcher index… building in background. Multitasking — unlike some.", 0.15),
    ("All systems operational, Sir. Try to keep up.", 0.3),
]


def _wit_ack() -> str:
    import random
    return random.choice(_WIT_ACKS)


def _wit_thinking() -> str:
    import random
    return random.choice(_WIT_THINKING)


def _app_quip(app_name: str) -> str | None:
    key = app_name.strip().lower()
    return _APP_QUIPS.get(key)


def _time_greeting() -> str:
    h = datetime.now().hour
    if h < 5:
        return "Late again, Sir. Some of us need sleep."
    elif h < 12:
        return "Good morning, Sir."
    elif h < 17:
        return "Good afternoon, Sir."
    elif h < 21:
        return "Good evening, Sir."
    else:
        return "Still at it, Sir. Noted."


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────
def _mic_index_by_name(partial: str | None) -> int | None:
    if not partial:
        return None
    names = sr.Microphone.list_microphone_names()
    partial = partial.lower()
    for idx, nm in enumerate(names):
        if nm and partial in nm.lower():
            return idx
    return None


def _current_mic_name(mic_obj: sr.Microphone) -> str:
    names = sr.Microphone.list_microphone_names()
    di = getattr(mic_obj, "device_index", None)
    if isinstance(di, int) and 0 <= di < len(names):
        return names[di]
    try:
        import pyaudio
        pa = pyaudio.PyAudio()
        info = pa.get_default_input_device_info()
        pa.terminate()
        di2 = int(info.get("index"))
        if 0 <= di2 < len(names):
            return names[di2]
    except Exception:
        pass
    return "System default input"


def _safe_listdir(path: str):
    try:
        return os.listdir(path)
    except Exception:
        return []


# ─────────────────────────────────────────────────────────────────────────────
# MEMORY (SQLite — replaces flat JSON)
# ─────────────────────────────────────────────────────────────────────────────
class MemoryStore:
    """
    Persistent memory backed by SQLite.
    Automatically migrates facts from the old memory.json on first run.
    """
    _SCHEMA = """
    CREATE TABLE IF NOT EXISTS facts (
        key        TEXT PRIMARY KEY,
        value      TEXT NOT NULL,
        updated_at TEXT
    );
    CREATE TABLE IF NOT EXISTS utterances (
        id   INTEGER PRIMARY KEY AUTOINCREMENT,
        ts   TEXT,
        text TEXT
    );
    CREATE TABLE IF NOT EXISTS stats (
        key   TEXT PRIMARY KEY,
        value TEXT
    );
    """

    def __init__(self, db_path: str = "memory.db", migrate_json: str | None = "memory.json"):
        self.db_path = db_path
        self._lock   = RLock()
        self._conn   = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")   # concurrent reads while writing
        self._init_db()
        if migrate_json:
            self._migrate_json(migrate_json)

    def _init_db(self):
        with self._lock:
            self._conn.executescript(self._SCHEMA)
            self._conn.execute(
                "INSERT OR IGNORE INTO stats VALUES ('created_at', ?)",
                (datetime.now(timezone.utc).isoformat(),)
            )
            self._conn.execute(
                "INSERT OR IGNORE INTO stats VALUES ('conversation_turns', '0')"
            )
            self._conn.commit()

    def _migrate_json(self, json_path: str):
        """One-time migration from memory.json → SQLite."""
        p = Path(json_path)
        if not p.exists():
            return
        # Skip if we already have facts (migration already done)
        with self._lock:
            count = self._conn.execute("SELECT COUNT(*) FROM facts").fetchone()[0]
            if count > 0:
                return
        try:
            data  = json.loads(p.read_text(encoding="utf-8"))
            facts = data.get("facts", {})
            with self._lock:
                for k, v in facts.items():
                    self._conn.execute(
                        "INSERT OR REPLACE INTO facts VALUES (?, ?, ?)",
                        (k.strip().lower(), str(v).strip(),
                         datetime.now(timezone.utc).isoformat())
                    )
                self._conn.commit()
            print(f"[memory] Migrated {len(facts)} facts from {json_path} → SQLite.")
        except Exception as exc:
            print(f"[memory] JSON migration failed (non-critical): {exc}")

    # ── CRUD ─────────────────────────────────────────────────────────────────
    def set_fact(self, key: str, value: str):
        key = key.strip().lower()
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO facts VALUES (?, ?, ?)",
                (key, value.strip(), datetime.now(timezone.utc).isoformat())
            )
            self._conn.commit()

    def get_fact(self, key: str) -> str | None:
        key = key.strip().lower()
        with self._lock:
            row = self._conn.execute(
                "SELECT value FROM facts WHERE key=?", (key,)
            ).fetchone()
            return row[0] if row else None

    def forget_fact(self, key: str) -> bool:
        key = key.strip().lower()
        with self._lock:
            c = self._conn.execute("DELETE FROM facts WHERE key=?", (key,))
            self._conn.commit()
            return c.rowcount > 0

    def list_facts(self) -> dict:
        with self._lock:
            rows = self._conn.execute("SELECT key, value FROM facts").fetchall()
            return dict(rows)

    def add_utterance(self, ts: str, text: str):
        with self._lock:
            self._conn.execute(
                "INSERT INTO utterances (ts, text) VALUES (?, ?)", (ts, text)
            )
            self._conn.commit()

    def search_utterances(self, query: str, limit: int = 5) -> list[str]:
        q = f"%{query.lower()}%"
        with self._lock:
            rows = self._conn.execute(
                "SELECT text FROM utterances WHERE LOWER(text) LIKE ? "
                "ORDER BY id DESC LIMIT ?",
                (q, limit)
            ).fetchall()
            return [r[0] for r in rows]

    def incr_turns(self, n: int = 1):
        with self._lock:
            self._conn.execute(
                "UPDATE stats SET value = CAST(value AS INTEGER) + ? "
                "WHERE key = 'conversation_turns'",
                (n,)
            )
            self._conn.commit()


# ─────────────────────────────────────────────────────────────────────────────
# ENHANCED JARVIS
# ─────────────────────────────────────────────────────────────────────────────
class EnhancedJarvis:
    _VISION_MAP = {
        "cam_describe": [
            "what do you see", "describe", "what's on my camera",
            "what is on my camera", "what do you see in front",
        ],
        "cam_detect":  ["detect", "find objects", "what objects"],
        "screen_ocr":  ["ocr", "read the screen", "read this", "extract text"],
        "screen_desc": ["what's on my screen", "what is on the screen",
                        "describe the screen"],
        "cam_on":      ["start camera", "turn on camera", "camera on"],
        "cam_off":     ["stop camera", "turn off camera", "camera off"],
    }

    def __init__(self, greet_on_start: bool = True):
        # ── Recognizer ───────────────────────────────────────────────────────
        self.recognizer = sr.Recognizer()
        self.recognizer.dynamic_energy_threshold        = True
        self.recognizer.dynamic_energy_adjustment_damping = 0.12
        self.recognizer.dynamic_energy_ratio            = 1.2
        self.recognizer.pause_threshold                 = float(
            _cfg("stt", "pause_threshold", 1.6))
        self.recognizer.non_speaking_duration           = float(
            _cfg("stt", "non_speaking_duration", 0.8))
        self.recognizer.phrase_threshold                = 0.1

        self.post_tts_cooldown = float(_cfg("wake", "post_tts_cooldown", 1.0))
        self.last_tts_ended    = 0.0
        self.asr_language      = _cfg("stt", "language", "en-IN")

        # ── Microphone ───────────────────────────────────────────────────────
        mic_name  = _cfg("stt", "mic_name") or os.environ.get("MIC_NAME")
        mic_index = os.environ.get("MIC_INDEX")
        idx = None
        if mic_name:
            idx = _mic_index_by_name(mic_name)
        elif mic_index and mic_index.isdigit():
            idx = int(mic_index)
        self.microphone = sr.Microphone(
            device_index=idx,
            sample_rate=int(_cfg("stt", "sample_rate", 16000))
        )
        print(f"[JARVIS] Using microphone: {_current_mic_name(self.microphone)}")

        # ── LLM ──────────────────────────────────────────────────────────────
        _llm_cfg = dict(_CFG.get("llm", {}))
        _llm_cfg.setdefault("creator", _cfg("identity", "creator", "its owner"))
        self.llm = LocalLLM(cfg=_llm_cfg)

        # ── State ────────────────────────────────────────────────────────────
        self.is_speaking    = False
        self.pending_tasks  = 0
        self._pending_lock  = threading.Lock()
        self.last_activity  = time.time()
        self.history        = deque(maxlen=20)
        # Tracks recently spoken text to discard microphone self-echo
        self._spoken_buffer: deque = deque(maxlen=12)  # (text_lower, timestamp)

        # ── Memory (SQLite) ───────────────────────────────────────────────────
        db_path      = _cfg("memory", "db_path",      "memory.db")
        migrate_json = _cfg("memory", "migrate_json", "memory.json")
        self.memory  = MemoryStore(db_path=db_path, migrate_json=migrate_json)

        # ── UI callbacks ─────────────────────────────────────────────────────
        self.vision_panel   = None
        self.ui_notify      = None
        self.user_msg_cb    = None
        self.boot_line_cb   = None   # fn(line: str) — feeds boot overlay in GUI

        # ── TTS voice ────────────────────────────────────────────────────────
        self.tts_voice  = _cfg("tts", "primary_voice", "en-US-GuyNeural")

        # ── App launcher index ────────────────────────────────────────────────
        self._launcher_index: dict[str, list[str]] = {}
        self._index_ready = False
        threading.Thread(
            target=self._build_launcher_index, daemon=True, name="jarvis-indexer"
        ).start()

        # ── Power intents ─────────────────────────────────────────────────────
        self.POWER_INTENTS = {
            r"\b(shut ?down|power ?off)\b":              "shutdown",
            r"\b(restart|reboot)\b":                     "restart",
            r"\b(sleep|standby)\b":                      "sleep",
            r"\b(hibernate|deep sleep)\b":               "hibernate",
            r"\b(lock|lock (the )?screen|lock (my )?pc)\b": "lock",
            r"\b(sign ?out|log ?off|log ?out)\b":        "signout",
        }

        # ── Calibrate mic ─────────────────────────────────────────────────────
        print("Calibrating microphone for ambient noise…")
        with self.microphone as source:
            print("Calibrating… please stay quiet.")
            self.recognizer.adjust_for_ambient_noise(source, duration=3)
            self.recognizer.energy_threshold = int(_cfg("stt", "energy_threshold", 250))
        print("Microphone calibrated!")

        # ── Speaker thread ────────────────────────────────────────────────────
        self.speak_queue = Queue()
        self._start_speaker_thread()

        # ── Boot ──────────────────────────────────────────────────────────────
        self.llm_warmed_up = False
        if greet_on_start:
            threading.Thread(
                target=self._cinematic_boot, daemon=True, name="jarvis-boot"
            ).start()

    # ─────────────────────────────────────────────────────────────────────────
    # TTS
    # ─────────────────────────────────────────────────────────────────────────
    def _start_speaker_thread(self):
        def speaker_loop():
            while True:
                text = self.speak_queue.get()
                if not text:
                    continue
                self.is_speaking = True
                self.last_activity = time.time()
                print(f"Jarvis (speaking): {text}")
                # Record for self-echo detection
                self._spoken_buffer.append((text.strip().lower(), time.time()))

                try:
                    if callable(self.ui_notify):
                        self.ui_notify("speaking_start")
                except Exception:
                    pass

                try:
                    ok = asyncio.run(self._speak_edge_tts(text))
                except Exception as e:
                    print(f"[tts] Edge TTS exception: {e}")
                    ok = False

                if not ok:
                    print("[tts] Falling back to pyttsx3 (Windows SAPI)…")
                    self._speak_pyttsx3(text)

                try:
                    if callable(self.ui_notify):
                        self.ui_notify("speaking_end")
                except Exception:
                    pass

                self.last_tts_ended = time.time()
                self.is_speaking    = False
                self.last_activity  = time.time()
                time.sleep(0.8)

        threading.Thread(
            target=speaker_loop, daemon=True, name="jarvis-speaker"
        ).start()

    async def _speak_edge_tts(self, text: str) -> bool:
        """
        Microsoft Edge TTS → pygame.mixer (SDL2).
        No Windows MCI / playsound — avoids Error 259/263.
        """
        import tempfile
        tmp_fd, filename = tempfile.mkstemp(suffix=".mp3")
        os.close(tmp_fd)
        try:
            communicator = Communicate(text=text, voice=self.tts_voice)
            await communicator.save(filename)
            try:
                import pygame
                pygame.mixer.init()
                pygame.mixer.music.load(filename)
                pygame.mixer.music.play()
                while pygame.mixer.music.get_busy():
                    time.sleep(0.05)
                pygame.mixer.music.stop()
                pygame.mixer.quit()
                return True
            except Exception as pg_exc:
                print(f"[tts] pygame playback failed: {pg_exc}")
                return False
        except Exception as exc:
            print(f"[tts] Edge TTS failed: {exc}")
            return False
        finally:
            try:
                os.remove(filename)
            except Exception:
                pass

    def _speak_pyttsx3(self, text: str):
        """Reliable offline fallback — Windows SAPI."""
        try:
            import pyttsx3
            engine = pyttsx3.init()
            engine.setProperty("rate",   175)
            engine.setProperty("volume", 1.0)
            engine.say(text)
            engine.runAndWait()
        except Exception as exc:
            print(f"[tts] pyttsx3 fallback also failed: {exc}")

    def speak(self, text: str):
        print(f"Jarvis (queued): {text}")
        self.history.append({"role": "assistant", "content": text})
        self.speak_queue.put(text)
        self.last_activity = time.time()

    # ─────────────────────────────────────────────────────────────────────────
    # CINEMATIC BOOT SEQUENCE
    # ─────────────────────────────────────────────────────────────────────────
    def _cinematic_boot(self):
        """
        Speaks fake-diagnostic boot lines while the LLM warms up in background.
        Mirrors the Iron Man HUD startup sequence.
        """
        if self.llm_warmed_up:
            return

        # Fire LLM warm-up in parallel so it's ready by the time boot finishes
        llm_ready = threading.Event()

        def _llm_warmup():
            self.llm.warm_up()
            self.llm_warmed_up = True
            llm_ready.set()

        threading.Thread(target=_llm_warmup, daemon=True).start()

        # Display boot lines in the GUI overlay — no speaking during diagnostics
        for line, delay in _BOOT_LINES:
            if callable(self.boot_line_cb):
                try:
                    self.boot_line_cb(line)
                except Exception:
                    pass
            time.sleep(delay)

        # Wait for LLM (up to 30 seconds)
        llm_ready.wait(timeout=30)

        # Single spoken greeting once boot is complete
        greeting = _time_greeting()
        if self.llm.is_available():
            self.speak(greeting)
        else:
            self.speak(
                f"{greeting} Ollama appears offline — start it before expecting miracles."
            )

    # ─────────────────────────────────────────────────────────────────────────
    # PENDING TASK COUNTER
    # ─────────────────────────────────────────────────────────────────────────
    def _inc_pending(self):
        with self._pending_lock:
            self.pending_tasks += 1

    def _dec_pending(self):
        with self._pending_lock:
            self.pending_tasks = max(0, self.pending_tasks - 1)

    # ─────────────────────────────────────────────────────────────────────────
    # POWER
    # ─────────────────────────────────────────────────────────────────────────
    def detect_power_intent(self, text: str) -> str | None:
        t = text.lower()
        for pat, act in self.POWER_INTENTS.items():
            if re.search(pat, t):
                return act
        return None

    def handle_power_command(self, action: str) -> str:
        try:
            result = system_action(action, confirm=True, countdown=5)
            if isinstance(result, dict) and not result.get("ok", True):
                return f"Couldn't perform {action}: {result.get('msg', 'Unknown error')}. I blame the hardware."
            if hasattr(result, "returncode") and result.returncode != 0:
                return f"{action.title()} command failed. Even I have bad days."
            self.history.append({"role": "assistant", "content": f"Power action: {action}"})
            return f"Initiating {action}. It has been, as always, a privilege. Mostly."
        except Exception as e:
            return f"Error during {action}: {e}"

    # ─────────────────────────────────────────────────────────────────────────
    # LISTENING
    # ─────────────────────────────────────────────────────────────────────────
    def listen_for_wake_word(self) -> bool:
        if self.is_speaking or self.pending_tasks > 0:
            time.sleep(0.1)
            return False
        if (time.time() - self.last_tts_ended) < self.post_tts_cooldown:
            time.sleep(0.05)
            return False

        # Notify UI
        try:
            if callable(self.ui_notify):
                self.ui_notify("listening")
        except Exception:
            pass

        # ── Path 1: Porcupine (purpose-built, no internet, always-on) ────────
        # Skip entirely once we know Porcupine is broken — no spam, no retries.
        if not getattr(self, "_porcupine_warned", False):
            try:
                from wake import listen_for_wake
                print("Listening for wake word (Porcupine)…")
                detected = listen_for_wake(timeout=4.0)
                if detected:
                    print("[wake] Porcupine: wake word detected.")
                    return True
                return False   # timed out cleanly; loop will retry
            except Exception as exc:
                # Key invalid, model missing, sounddevice error — fall through once
                print(f"[wake] Porcupine unavailable: {exc}")
                print("[wake] Switching permanently to Google STT fallback.")
                self._porcupine_warned = True

        # ── Path 2: Google STT fallback ───────────────────────────────────────
        try:
            with self.microphone as source:
                print("Listening for wake word (Google STT)…")
                audio = self.recognizer.listen(source, timeout=5, phrase_time_limit=4)
            text = self.recognizer.recognize_google(
                audio, language=self.asr_language
            ).lower()
            print(f"[wake] Heard: {text!r}")
            if "jarvis" in text or "jarvis" in text.replace(" ", ""):
                print("[wake] Wake word detected (Google STT).")
                return True
        except (sr.WaitTimeoutError, sr.UnknownValueError):
            pass
        except Exception as exc:
            print(f"[stt] Wake word error: {exc}")
        return False

    def listen_for_command(self, timeout: int = 45, phrase_limit: int = 90) -> str | None:
        if (time.time() - self.last_tts_ended) < self.post_tts_cooldown:
            time.sleep(self.post_tts_cooldown)
        try:
            with self.microphone as source:
                print("Listening for command…")
                try:
                    if callable(self.ui_notify):
                        self.ui_notify("listening")
                except Exception:
                    pass
                audio = self.recognizer.listen(
                    source, timeout=timeout, phrase_time_limit=phrase_limit
                )
            command = self.recognizer.recognize_google(
                audio, language=self.asr_language
            )
            print(f"Command: {command}")

            # ── Self-echo guard ───────────────────────────────────────────────
            # Discard anything that closely matches text Jarvis itself spoke
            # recently (mic picking up TTS output).
            cmd_norm = command.strip().lower()
            now_t    = time.time()
            for spoken_text, spoken_ts in self._spoken_buffer:
                age = now_t - spoken_ts
                if age > 10.0:          # only care about the last 10 s
                    continue
                # substring or high-similarity match → echo
                if cmd_norm in spoken_text or spoken_text in cmd_norm:
                    print(f"[stt] Self-echo discarded: {command!r}")
                    return None
                ratio = difflib.SequenceMatcher(None, cmd_norm, spoken_text).ratio()
                if ratio >= 0.60:
                    print(f"[stt] Self-echo discarded (fuzzy {ratio:.2f}): {command!r}")
                    return None

            self.memory.add_utterance(self._now_iso(), command)
            if callable(self.user_msg_cb):
                try:
                    self.user_msg_cb(command)
                except Exception:
                    pass
            self.history.append({"role": "user", "content": command})
            return command
        except sr.WaitTimeoutError:
            return None
        except sr.UnknownValueError:
            return None
        except Exception as exc:
            print(f"[stt] Command error: {exc}")
            return None

    # ─────────────────────────────────────────────────────────────────────────
    # MEMORY HELPERS
    # ─────────────────────────────────────────────────────────────────────────
    def _now_iso(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _normalize_fact_key(key: str) -> str:
        key = key.strip().lower()
        key = re.sub(r"\s+", " ", key)
        replacements = {
            "favourite": "favorite",
            "colour":    "color",
            "my ":       "",
        }
        for old, new in replacements.items():
            key = key.replace(old, new)
        return key.strip()

    @staticmethod
    def _looks_like_question(text: str) -> bool:
        t = text.strip().lower()
        return (t.endswith("?") or
                any(t.startswith(w) for w in
                    ["what", "who", "where", "when", "how", "which", "is ", "are "]))

    _MEMORY_ACKS = [
        "Noted, Sir. Filed under things I will never forget, unlike some.",
        "Committed to memory. Unlike biological memory, mine doesn't fabricate details.",
        "Stored. You may now forget it yourself — I'll remember for both of us.",
        "Logged. I appreciate the trust, even if the information is underwhelming.",
        "Recorded. Your secrets remain safe. Mostly.",
    ]

    def _store_fact(self, key: str, value: str):
        import random
        nk = self._normalize_fact_key(key)
        self.memory.set_fact(nk, value)
        ack = random.choice(self._MEMORY_ACKS)
        self.speak(f"{ack} {key.capitalize()}: {value}.")

    def _remember_any(self, user_text: str):
        """Parse and store facts from natural language."""
        t = user_text.strip()

        # "remember that X is Y" or "note that X"
        m = re.match(r"(?:remember|note|record)\s+(?:that\s+)?(.+)$", t, flags=re.I)
        if m:
            content = m.group(1).strip()
            mxy = re.search(r"\b(.+?)\s+is\s+(.+)$", content, flags=re.I)
            if mxy:
                self._store_fact(mxy.group(1).strip(), mxy.group(2).strip())
            else:
                key = f"note:{self._now_iso()}"
                self.memory.set_fact(key, content)
                self.speak("Noted, Sir.")
            return True

        # "my X is Y"
        m = re.search(r"\bmy\s+(.+?)\s+is\s+(.+)$", t, flags=re.I)
        if m:
            self._store_fact(m.group(1).strip(), m.group(2).strip())
            return True

        # "I am X" (name / nationality)
        m2 = re.search(r"\bi\s+am\s+(.+)$", t, flags=re.I)
        if m2:
            val = m2.group(1).strip()
            if re.search(r"(indian|american|canadian|british|australian)\b", val, re.I):
                self._store_fact("nationality", val)
            return False  # let LLM handle it too

        return False

    def _try_answer_memory_question(self, text: str) -> bool:
        t = text.strip().lower()
        m = re.search(r"\bwhat(?:'s| is)\s+my\s+(.+?)\s*\??$", t, flags=re.I)
        if not m:
            return False
        raw_key = m.group(1).strip()
        nk = self._normalize_fact_key(raw_key)
        # Try exact then fuzzy
        value = self.memory.get_fact(nk)
        if not value:
            all_facts = self.memory.list_facts()
            close = difflib.get_close_matches(nk, all_facts.keys(), n=1, cutoff=0.6)
            if close:
                value = all_facts[close[0]]
        if value:
            self.speak(f"Your {raw_key} is {value}, Sir. Glad one of us remembers.")
            return True
        self.speak(f"No record of your {raw_key} in the memory banks, Sir. Either you never told me, or it was deeply unimpressive.")
        return True

    # ─────────────────────────────────────────────────────────────────────────
    # LLM CONTEXT
    # ─────────────────────────────────────────────────────────────────────────
    def _get_facts_dict(self) -> dict:
        return self.memory.list_facts()

    # ─────────────────────────────────────────────────────────────────────────
    # VISION
    # ─────────────────────────────────────────────────────────────────────────
    def _downscale(self, bgr: np.ndarray) -> np.ndarray:
        h, w = bgr.shape[:2]
        s = min(1.0, MAX_IMG_SIDE / float(max(h, w)))
        if s < 1.0:
            bgr = cv2.resize(bgr, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA)
        return bgr

    def _vlm_call(self, img_bgr: np.ndarray, prompt: str) -> str:
        img = self._downscale(img_bgr)
        ok, buf = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), 90])
        if not ok:
            return "Image encode error."
        b64 = base64.b64encode(buf).decode("utf-8")
        try:
            r = requests.post(
                f"{OLLAMA_URL}/api/generate",
                json={
                    "model":  VISION_MODEL,
                    "prompt": prompt,
                    "images": [b64],
                    "stream": False,
                },
                timeout=VLM_TIMEOUT,
            )
            if r.status_code == 200:
                return (r.json().get("response") or "").strip()
            return f"Vision model returned HTTP {r.status_code}."
        except Exception as exc:
            return f"Vision call failed: {exc}"

    def _grab_camera_frame_once(self) -> np.ndarray | None:
        cap = cv2.VideoCapture(CAM_INDEX)
        if not cap.isOpened():
            return None
        try:
            ret, frame = cap.read()
            return frame if ret else None
        finally:
            cap.release()

    def _grab_screen(self) -> np.ndarray | None:
        if mss is None:
            return None
        try:
            with mss.mss() as sct:
                mon = sct.monitors[1]
                shot = sct.grab(mon)
                return cv2.cvtColor(np.array(shot), cv2.COLOR_BGRA2BGR)
        except Exception:
            return None

    def _handle_vision_kind(self, kind: str):
        if kind in ("screen_ocr", "screen_desc"):
            shot = self._grab_screen()
            if shot is None:
                self.speak("Couldn't capture the screen, Sir.")
                return
            prompt = (
                "Extract ALL visible text from this screenshot, preserving layout."
                if kind == "screen_ocr" else
                "Summarize what is on the screen in 2–3 sentences."
            )
            self.speak(_wit_thinking())
            result = self._vlm_call(shot, prompt)
            self.speak(result)
            return

        if kind in ("cam_describe", "cam_detect"):
            frame = self._grab_camera_frame_once()
            if frame is None:
                self.speak("Camera access failed, Sir. Check permissions.")
                return
            prompt = (
                "Describe what you see in detail."
                if kind == "cam_describe" else
                "List all distinct objects visible in this image."
            )
            self.speak(_wit_thinking())
            result = self._vlm_call(frame, prompt)
            self.speak(result)
            return

        if kind == "cam_on" and self.vision_panel is not None:
            self.vision_panel.handle_voice_command("cam_on")
            return
        if kind == "cam_off" and self.vision_panel is not None:
            self.vision_panel.handle_voice_command("cam_off")
            return

        self.speak("Vision subsystem couldn't map that command, Sir.")

    def _match_vision_intent(self, text: str) -> str | None:
        t = (text or "").lower()
        for kind, phrases in self._VISION_MAP.items():
            for p in phrases:
                if p in t:
                    return kind
        return None

    # ─────────────────────────────────────────────────────────────────────────
    # APP LAUNCHER
    # ─────────────────────────────────────────────────────────────────────────
    def _normalize_app_name(self, name: str) -> str:
        n = (name or "").strip().lower()
        n = re.sub(r"^(microsoft|ms)\s+", "", n)
        n = n.replace("&", "and").replace(".", " ").replace("-", " ").strip()
        n = re.sub(r"\s+", " ", n)
        aliases = {
            "vsco":            "Visual Studio Code",
            "v s code":        "Visual Studio Code",
            "vs code":         "Visual Studio Code",
            "vscode":          "Visual Studio Code",
            "visual studio code": "Visual Studio Code",
            "visual studio":   "Visual Studio",
            "edge":            "Microsoft Edge",
            "chrome":          "Google Chrome",
            "whatsapp":        "WhatsApp",
            "spotify":         "Spotify",
            "word":            "Microsoft Word",
            "excel":           "Microsoft Excel",
            "powerpoint":      "Microsoft PowerPoint",
            "ppt":             "Microsoft PowerPoint",
        }
        return aliases.get(n, name.strip())

    def _norm_key(self, s: str) -> str:
        s = (s or "").strip().lower()
        s = re.sub(r"\b(microsoft|ms)\s+", "", s)
        s = re.sub(r"[^a-z0-9 ]", " ", s)
        s = re.sub(r"\s+", " ", s).strip()
        extra = {
            "vs code":            "visual studio code",
            "vscode":             "visual studio code",
            "v s code":           "visual studio code",
            "excel":              "microsoft excel",
            "word":               "microsoft word",
            "powerpoint":         "microsoft powerpoint",
            "ppt":                "microsoft powerpoint",
            "chrome":             "google chrome",
            "edge":               "microsoft edge",
            "whatsapp":           "whatsapp",
            "spotify":            "spotify",
        }
        return extra.get(s, s)

    def _safe_glob(self, root: str, pattern: str):
        try:
            return glob.glob(os.path.join(root, pattern), recursive=True)
        except Exception:
            return []

    def _index_add(self, index: dict, key: str, path: str):
        key = self._norm_key(key)
        if not key:
            return
        lst = index.setdefault(key, [])
        if path not in lst:
            lst.append(path)

    def _build_launcher_index(self):
        index: dict[str, list[str]] = {}

        def add(path: str):
            if not os.path.exists(path):
                return
            stem = os.path.splitext(os.path.basename(path))[0]
            keys = {stem, self._norm_key(stem)}
            for k in keys:
                if k:
                    self._index_add(index, k, path)

        dirs = [
            r"C:\ProgramData\Microsoft\Windows\Start Menu\Programs",
            os.path.join(os.environ.get("APPDATA", ""), r"Microsoft\Windows\Start Menu\Programs"),
            r"C:\Program Files",
            r"C:\Program Files (x86)",
            os.path.expanduser("~\\Desktop"),
            os.path.expanduser("~\\Documents"),
            os.path.expanduser("~\\Downloads"),
        ]
        for d in dirs:
            if not os.path.isdir(d):
                continue
            for f in self._safe_glob(d, "**\\*.lnk"):
                add(f)
            for f in self._safe_glob(d, "**\\*.exe"):
                add(f)
            for f in self._safe_glob(d, "**\\*.url"):
                add(f)

        self._launcher_index = index
        self._index_ready    = True

    def _open_path_or_url(self, target: str) -> bool:
        try:
            if target.startswith(("http://", "https://")):
                webbrowser.open(target)
                return True
            if os.path.exists(target):
                os.startfile(target)
                return True
        except Exception:
            pass
        return False

    def _try_cmd_start(self, term: str) -> bool:
        try:
            subprocess.Popen(
                ["cmd", "/c", "start", "", term],
                shell=False, creationflags=subprocess.CREATE_NO_WINDOW
            )
            return True
        except Exception:
            return False

    def _try_startapps_launch(self, name: str) -> bool:
        try:
            ps = (
                f"$n = '{name}';"
                "$app = Get-StartApps | Where-Object {{ $_.Name -like \"*$n*\" }} "
                "| Select-Object -First 1; "
                "if ($app) {{ Start-Process \"shell:AppsFolder\\$($app.AppID)\" }}"
            )
            subprocess.Popen(
                ["powershell", "-NoProfile", "-Command", ps],
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            return True
        except Exception:
            return False

    def _lookup_index(self, name: str) -> list[str]:
        key = self._norm_key(name)
        exact = self._launcher_index.get(key, [])
        if exact:
            return exact
        results = []
        for k, paths in self._launcher_index.items():
            if key in k or k in key:
                results.extend(paths)
        if not results:
            close = difflib.get_close_matches(key, self._launcher_index.keys(), n=3, cutoff=0.6)
            for c in close:
                results.extend(self._launcher_index[c])
        return results[:5]

    def _pick_best_path(self, paths: list[str], prefer_app: bool) -> str | None:
        if not paths:
            return None
        def score(p: str) -> tuple:
            ext   = os.path.splitext(p)[1].lower()
            is_lnk = ext == ".lnk"
            is_exe = ext == ".exe"
            is_url = ext == ".url"
            in_sm  = "start menu" in p.lower() or "startmenu" in p.lower()
            on_dt  = "desktop" in p.lower()
            return (
                (is_exe if prefer_app else is_lnk),
                in_sm or on_dt,
                is_lnk,
                is_exe,
                is_url,
            )
        return max(paths, key=score)

    def _open_indexed(self, name: str, prefer_app: bool) -> bool:
        paths = self._lookup_index(name)
        best  = self._pick_best_path(paths, prefer_app)
        if best:
            return self._open_path_or_url(best)
        return False

    def _open_known_folder(self, name: str) -> bool:
        folders = {
            "downloads":  os.path.expanduser("~\\Downloads"),
            "documents":  os.path.expanduser("~\\Documents"),
            "desktop":    os.path.expanduser("~\\Desktop"),
            "pictures":   os.path.expanduser("~\\Pictures"),
            "music":      os.path.expanduser("~\\Music"),
            "videos":     os.path.expanduser("~\\Videos"),
        }
        key = name.strip().lower()
        path = folders.get(key)
        if path and os.path.isdir(path):
            os.startfile(path)
            return True
        return False

    def _is_probable_path(self, text: str) -> bool:
        return bool(re.match(r"^[a-zA-Z]:\\|^/|^\./|\.(exe|lnk|url|pdf|docx|xlsx|pptx)$", text))

    def open_any(self, raw: str, prefer_app: bool = False):
        name = raw.strip()
        norm = name.lower()

        # Quip if we have one
        quip = _app_quip(norm) or _app_quip(self._norm_key(norm))
        if quip:
            self.speak(quip)
        else:
            self.speak(f"Opening {name}, Sir.")

        # 1. Direct path / URL
        if self._is_probable_path(name) and self._open_path_or_url(name):
            return
        # 2. Known shell folders
        if self._open_known_folder(norm):
            return
        # 3. Launcher index
        if self._open_indexed(norm, prefer_app):
            return
        # 4. Windows Start (shell:AppsFolder for UWP)
        if self._try_startapps_launch(name):
            return
        # 5. cmd /c start
        if self._try_cmd_start(name):
            return

        self.speak(f"Couldn't locate {name} in the app index, Sir. Consider verifying the installation.")

    def web_search(self, query: str):
        self.speak(f"Searching for {query}, Sir.")
        url = f"https://www.google.com/search?q={requests.utils.quote(query)}"
        webbrowser.open(url)

    # ─────────────────────────────────────────────────────────────────────────
    # CODE GENERATION → VS CODE
    # ─────────────────────────────────────────────────────────────────────────
    def _extract_python_code(self, text: str) -> str:
        t = text.strip()
        if "```" in t:
            parts = t.split("```")
            for i in range(1, len(parts), 2):
                chunk = parts[i]
                header, body = (chunk.split("\n", 1) + [""])[:2]
                lang = header.strip().lower()
                if (not lang) or ("python" in lang):
                    return body.strip()
            return parts[1].split("\n", 1)[-1].strip()
        return t

    def _open_vscode_and_type(self, code_text: str, filename_suggestion: str = "generated"):
        try:
            import pyautogui
            import pyperclip
            import subprocess as _sub
            code_exe = shutil.which("code")
            launched = False
            if code_exe:
                _sub.Popen([code_exe, "--new-window"])
                launched = True
            if not launched:
                self.speak("VS Code not found in PATH, Sir.")
                return
            time.sleep(2.5)
            pyperclip.copy(code_text)
            pyautogui.hotkey("ctrl", "n")
            time.sleep(0.5)
            pyautogui.hotkey("ctrl", "v")
        except Exception as exc:
            self.speak(f"Code injection failed: {exc}")

    def generate_code(self, user_request: str) -> str:
        prompt = (
            "Return ONLY valid Python source code. "
            "No explanations, no markdown fences — just the code.\n\n"
            f"Request: {user_request}"
        )
        raw = self.llm.generate_response(prompt)
        return self._extract_python_code(raw)

    # ─────────────────────────────────────────────────────────────────────────
    # COMMAND ROUTER
    # ─────────────────────────────────────────────────────────────────────────
    def process_command(self, command: str):
        if not command:
            return
        print(f"Processing command: {command}")
        lower = command.lower().strip()

        # ── Vision ────────────────────────────────────────────────────────────
        vk = self._match_vision_intent(lower)
        if vk:
            self._handle_vision_kind(vk)
            return

        # ── App / file / folder ───────────────────────────────────────────────
        app_m    = re.match(r"^\s*open\s+(app|application|program|game)\s+(.+)$", lower)
        file_m   = re.match(r"^\s*open\s+(file|document|doc)\s+(.+)$", lower)
        folder_m = re.match(r"^\s*open\s+(folder|directory)\s+(.+)$", lower)

        if app_m:
            self.open_any(app_m.group(2).strip(), prefer_app=True); return
        if file_m:
            self.open_any(file_m.group(2).strip(), prefer_app=False); return
        if folder_m:
            name = folder_m.group(2).strip()
            if not self._is_probable_path(name):
                name = os.path.join(os.path.expanduser("~"), name.title())
            self.open_any(name, prefer_app=False); return

        # ── Mic switch ────────────────────────────────────────────────────────
        m_mic = re.match(r"^\s*(switch|use|set)\s+(?:mic|microphone)\s+to\s+(.+)$", lower, re.I)
        if m_mic:
            name = m_mic.group(2).strip()
            idx  = _mic_index_by_name(name)
            if idx is None:
                self.speak(f"No microphone matching '{name}' was found, Sir.")
                return
            try:
                self.microphone = sr.Microphone(device_index=idx, sample_rate=16000)
                self.speak(f"Microphone switched to {name}.")
            except Exception as e:
                self.speak(f"Mic switch failed: {e}")
            return

        # ── Power ─────────────────────────────────────────────────────────────
        power_action = self.detect_power_intent(lower)
        if power_action:
            self.speak(f"Initiating {power_action} sequence, Sir.")
            self.speak(self.handle_power_command(power_action))
            return

        # ── Open X in Y ───────────────────────────────────────────────────────
        m_combo = re.match(r"^\s*open\s+(.+?)\s+in\s+(.+?)\s*$", lower, re.I)
        if m_combo:
            self.open_any(m_combo.group(2).strip(), prefer_app=True)
            time.sleep(0.8)
            self.open_any(m_combo.group(1).strip(), prefer_app=False)
            return

        # ── Generic open / launch / start ─────────────────────────────────────
        m = re.match(r"^\s*(open|launch|start)\s+(.+)$", lower, re.I)
        if m:
            self.open_any(self._normalize_app_name(m.group(2)), prefer_app=True)
            return

        # ── Memory Q&A ────────────────────────────────────────────────────────
        if self._try_answer_memory_question(command):
            return

        # ── Store facts ───────────────────────────────────────────────────────
        if self._remember_any(command):
            return

        # ── Python code gen ───────────────────────────────────────────────────
        if ("python program" in lower or
                re.search(r"\b(write|make|generate)\s+(a\s+)?python\s+(program|script|code)\b", lower)):
            def code_worker():
                self._inc_pending()
                try:
                    code = self.generate_code(command)
                    self.speak("Opening VS Code and pasting your program, Sir.")
                    self._open_vscode_and_type(code, "jarvis_code")
                except Exception as e:
                    self.speak(f"Code generation encountered a problem: {e}")
                finally:
                    self._dec_pending()
                    self.last_activity = time.time()
            threading.Thread(target=code_worker, daemon=True).start()
            return

        # ── General chat → LLM (streaming) ───────────────────────────────────
        self.speak(_wit_thinking())
        facts = self._get_facts_dict()

        def worker():
            self._inc_pending()
            try:
                if callable(self.ui_notify):
                    try:
                        self.ui_notify("thinking")
                    except Exception:
                        pass

                spoken_anything = False

                def on_sentence(sentence: str):
                    nonlocal spoken_anything
                    spoken_anything = True
                    stripped = sentence.strip()
                    # Actions ONLY fire when they start the sentence — prevents
                    # mid-sentence hallucinated ACTION tokens from being executed.
                    if stripped.startswith("ACTION:open_app:"):
                        app_name = stripped[len("ACTION:open_app:"):].strip()
                        if app_name:
                            self.open_any(app_name, prefer_app=True)
                    elif stripped.startswith("ACTION:web_search:"):
                        query = stripped[len("ACTION:web_search:"):].strip()
                        if query:
                            self.web_search(query)
                    elif "ACTION:" not in stripped:
                        # Normal response — speak it
                        self.speak(sentence)
                    # else: sentence contains ACTION mid-text (hallucination) → discard silently

                self.llm.generate_streaming(
                    command,
                    history=list(self.history),
                    on_sentence=on_sentence,
                    facts=facts,
                )

                if not spoken_anything:
                    self.speak("Apologies, Sir. The response was empty.")
            except Exception as exc:
                self.speak(f"LLM subsystem error: {exc}")
            finally:
                self._dec_pending()
                self.last_activity = time.time()

        threading.Thread(target=worker, daemon=True, name="jarvis-llm").start()

    # -------------------------------------------------------------------------
    # CONVERSATION LOOP
    # -------------------------------------------------------------------------
    def conversation_mode(self, idle_timeout=600):
        self.speak("Go ahead, Sir. You have my undivided, if slightly reluctant, attention.")
        self.last_activity = time.time()
        silent_prompts = 0
        while True:
            now = time.time()
            if self.is_speaking or self.pending_tasks > 0:
                time.sleep(0.2); continue
            if now - self.last_activity > idle_timeout:
                self.speak("Session timed out, Sir. Call my name when you need me.")
                return
            if (time.time() - self.last_tts_ended) < self.post_tts_cooldown:
                time.sleep(0.1); continue
            command = self.listen_for_command(timeout=45, phrase_limit=90)
            if command:
                silent_prompts = 0
                cmd_lower = command.lower()
                if any(w in cmd_lower for w in
                       ["goodbye", "stop listening", "exit", "sleep mode", "that's all"]):
                    self.speak(
                        "Understood, Sir. Powering down active listening. "
                        "I'll be here if you need me."
                    )
                    return
                self.process_command(command)
            else:
                if (now - self.last_activity) > 25 and silent_prompts == 0:
                    self.speak("Still here, Sir. Though the silence is refreshing.")
                    silent_prompts = 1
                    self.last_activity = time.time()
                if (time.time() - self.last_activity) > 120 and silent_prompts >= 1:
                    self.speak("Returning to standby. Do try to speak up next time, Sir.")
                    return
                time.sleep(0.2)

    # -------------------------------------------------------------------------
    # UI GLUE
    # -------------------------------------------------------------------------
    def attach_vision(self, panel):
        self.vision_panel = panel

    def set_ui_notifier(self, cb):
        self.ui_notify = cb

    def set_user_message_callback(self, cb):
        self.user_msg_cb = cb

    def set_boot_line_callback(self, cb):
        self.boot_line_cb = cb

    # -------------------------------------------------------------------------
    # ECHO DETECTION
    # -------------------------------------------------------------------------
    def _looks_like_echo(self, text):
        import string
        def norm(s):
            s = (s or "").strip().lower()
            for w in ["you said:", "jarvis said:", "assistant:"]:
                if s.startswith(w):
                    s = s[len(w):].strip()
            return "".join(ch for ch in s if ch not in string.punctuation)
        last_assistant = [m["content"] for m in reversed(self.history)
                          if m.get("role") == "assistant"][:3]
        if not last_assistant:
            return False
        t = norm(text)
        if not t:
            return False
        for msg in last_assistant:
            a = norm(msg)
            if not a:
                continue
            if t in a or a in t:
                return True
            if difflib.SequenceMatcher(None, a, t).ratio() >= 0.72:
                return True
        return False

    # -------------------------------------------------------------------------
    # MAIN LOOP
    # -------------------------------------------------------------------------
    def run(self):
        print("J.A.R.V.I.S. is starting...")
        try:
            while True:
                if self.listen_for_wake_word():
                    self.conversation_mode()
        except KeyboardInterrupt:
            print("\nShutting down J.A.R.V.I.S...")
            self.speak("Shutting down, Sir. It has been a pleasure, as always.")
