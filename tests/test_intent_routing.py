# tests/test_intent_routing.py
# Tests for personality helpers, power intent patterns, and streaming sentence splitter.
# Self-contained: no hardware imports, no edge_tts, no PyAudio.
import re
import random
import pytest
from datetime import datetime

# ---------------------------------------------------------------------------
# Inline personality helpers (verbatim from jarvis_main.py)
# ---------------------------------------------------------------------------
_WIT_ACKS = [
    "Right away, Sir.",
    "Consider it done.",
    "On it.",
    "Of course.",
    "Naturally.",
    "Already ahead of you, Sir.",
    "As you wish.",
    "It would be my pleasure. A low bar, admittedly, but a pleasure nonetheless.",
]

_WIT_THINKING = [
    "Accessing...",
    "Cross-referencing...",
    "One moment, Sir.",
    "Consulting the archives...",
    "Processing. Please do not pace.",
]

_APP_QUIPS = {
    "spotify":            "Opening Spotify, Sir. Your taste in music remains... consistent.",
    "youtube":            "Opening YouTube. I shall refrain from commenting on the watch history.",
    "chrome":             "Opening Chrome. I've taken the liberty of not judging your tabs.",
    "visual studio code": "Opening VS Code. Shall I also prepare excuses for the compiler?",
    "vs code":            "Opening VS Code. Shall I also prepare excuses for the compiler?",
    "calculator":         "The Calculator, Sir. Even geniuses need training wheels occasionally.",
    "notepad":            "Opening Notepad. The timeless canvas of the technologically humble.",
    "discord":            "Opening Discord. Your social obligations await, Sir.",
    "whatsapp":           "Opening WhatsApp. I'll pretend I can't read the messages.",
    "steam":              "Opening Steam, Sir. I'm sure this is 'just to check the library'.",
    "task manager":       "Opening Task Manager. Hunting season is open.",
    "microsoft edge":     "Opening Edge. Brave choice, Sir. Truly.",
    "settings":           "Opening Settings. Try not to break anything critical.",
    "terminal":           "Opening Terminal. I trust you know what you're doing. Mostly.",
    "cmd":                "Opening Command Prompt. Old school. Respect.",
}

_POWER_INTENTS = {
    r"\b(shut ?down|power ?off)\b":                  "shutdown",
    r"\b(restart|reboot)\b":                         "restart",
    r"\b(sleep|standby)\b":                          "sleep",
    r"\b(hibernate|deep sleep)\b":                   "hibernate",
    r"\b(lock|lock (the )?screen|lock (my )?pc)\b":  "lock",
    r"\b(sign ?out|log ?off|log ?out)\b":            "signout",
}


def _wit_ack():
    return random.choice(_WIT_ACKS)

def _wit_thinking():
    return random.choice(_WIT_THINKING)

def _app_quip(app_name):
    return _APP_QUIPS.get(app_name.strip().lower())

def _time_greeting():
    h = datetime.now().hour
    if h < 5:   return "Working at this hour again, Sir. At least one of us never sleeps."
    elif h < 12: return "Good morning, Sir."
    elif h < 17: return "Good afternoon, Sir."
    elif h < 21: return "Good evening, Sir."
    else:        return "Working late again, Sir. Shall I flag this as a recurring concern?"

def _detect_power(text):
    t = text.lower()
    for pat, act in _POWER_INTENTS.items():
        if re.search(pat, t):
            return act
    return None

def _split_sentences(text):
    """Sentence splitter matching the logic in llm.py generate_streaming."""
    results = []
    buf = text
    while True:
        m = re.search(r'([^.!?]*[.!?]+)(?:\s|$)', buf)
        if not m:
            break
        results.append(m.group(1).strip())
        buf = buf[m.end():]
    if buf.strip():
        results.append(buf.strip())
    return results


# ---------------------------------------------------------------------------
# Personality helpers
# ---------------------------------------------------------------------------
def test_wit_ack_in_pool():
    for _ in range(30):
        assert _wit_ack() in _WIT_ACKS

def test_wit_thinking_in_pool():
    for _ in range(30):
        assert _wit_thinking() in _WIT_THINKING

def test_app_quip_known():
    assert _app_quip("spotify") is not None
    assert isinstance(_app_quip("discord"), str)

def test_app_quip_unknown():
    assert _app_quip("nonexistent_app_xyz_123") is None

def test_app_quip_case_insensitive():
    assert _app_quip("SPOTIFY") == _app_quip("spotify")

def test_time_greeting_returns_string():
    g = _time_greeting()
    assert isinstance(g, str) and len(g) > 5

def test_all_acks_are_strings():
    assert all(isinstance(s, str) and len(s) > 0 for s in _WIT_ACKS)

def test_all_thinking_are_strings():
    assert all(isinstance(s, str) and len(s) > 0 for s in _WIT_THINKING)


# ---------------------------------------------------------------------------
# Power intent detection
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("text,expected", [
    ("shut down the computer",    "shutdown"),
    ("poweroff now",              "shutdown"),
    ("please restart",            "restart"),
    ("reboot the machine",        "restart"),
    ("go to sleep",               "sleep"),
    ("standby mode",              "sleep"),
    ("hibernate",                 "hibernate"),
    ("deep sleep please",         "hibernate"),
    ("lock screen",               "lock"),
    ("lock my pc",                "lock"),
    ("sign out",                  "signout"),
    ("log off",                   "signout"),
    ("log out now",               "signout"),
])
def test_power_intents_match(text, expected):
    assert _detect_power(text) == expected, f"'{text}' → expected '{expected}'"


@pytest.mark.parametrize("text", [
    "what time is it",
    "open chrome",
    "tell me a joke",
    "play music",
    "what's on my screen",
    "write a python script",
])
def test_no_false_power_positives(text):
    assert _detect_power(text) is None, f"False positive on: '{text}'"


# ---------------------------------------------------------------------------
# Streaming sentence splitter
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("text,n", [
    ("Hello Sir. How are you?",       2),
    ("One sentence only.",            1),
    ("First! Second. Third?",         3),
    ("No punctuation here at all",    1),
    ("",                              0),
    ("Sir... on it.",                 2),
])
def test_sentence_split(text, n):
    parts = _split_sentences(text)
    assert len(parts) == n, f"Got {parts} for {repr(text)}"


def test_sentence_split_preserves_content():
    parts = _split_sentences("Hello Sir. The weather is fine.")
    assert "Hello Sir" in parts[0]
    assert "weather" in parts[1]
