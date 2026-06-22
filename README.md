# J.A.R.V.I.S
**Just A Rather Very Intelligent System**

A local, privacy-first AI voice assistant with an Iron Man HUD — runs entirely on your machine. No cloud AI, no subscriptions, no data leaving your device.

---

## What it does

Say **"Jarvis"** to wake it up, then speak naturally:

- *"Open Spotify"* → launches the app with a dry quip
- *"What's on my screen?"* → LLaVA vision model describes it
- *"My favorite color is black"* → stores it to persistent memory
- *"Shut down"* → 5-second spoken countdown, then executes
- *"Search for Interstellar showtimes"* → opens a browser search
- *"What do I know about quantum computing?"* → answered by local LLM

Responds in a neural voice. Displays a real-time Iron Man-style HUD with arc reactor, hex grid, waveform, and chat log.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Wake Word | Picovoice Porcupine (custom `Jarvis` model) |
| Speech-to-Text | Google Speech API via `speech_recognition` |
| LLM | Ollama (`llama3.2:3b`) — fully local |
| Vision / VLM | Ollama (`llava:13b`) + OpenCV + mss |
| Text-to-Speech | Edge TTS (neural) + pyttsx3 (offline fallback) |
| GUI | PyQt6 with custom-painted widgets |
| Memory | SQLite (WAL mode) with fuzzy key lookup |
| Config | YAML + `.env` — zero secrets in source |

---

## Features

- **100% local AI inference** — Ollama serves both the LLM and vision model on-device
- **Streaming TTS** — first sentence speaks at ~600ms while the rest generates
- **Self-echo guard** — difflib fuzzy matching prevents Jarvis from hearing itself
- **Persistent memory** — SQLite store; say "my dog's name is Simba" and it remembers forever
- **Vision modes** — describe webcam scene, detect objects, OCR screen text, summarize screen
- **Intent routing** — priority chain: power → memory → vision → app launch → web search → LLM
- **App launcher** — indexes Start Menu, Program Files, Desktop; 3-tier launch fallback
- **Bilingual** — English + Tamil (`ta-IN-ValluvarNeural` voice)
- **Iron Man HUD** — arc reactor changes color by state (cyan → green → gold → magenta)
- **Thread-safe** — 4 concurrent threads, `Queue` for TTS pipeline, `RLock` for SQLite

---

## Prerequisites

- Windows 10/11 (GUI and wake word are Windows-native)
- Python 3.11+
- [Ollama](https://ollama.com) installed and running
- A microphone
- Picovoice access key (free at [console.picovoice.ai](https://console.picovoice.ai))

Pull the required models in Ollama:
```
ollama pull llama3.2:3b
ollama pull llava:13b
```

---

## Setup

**1. Clone and create a virtual environment**
```
git clone https://github.com/sharanmagesh03/jarvis.git
cd jarvis
python -m venv jarvis_env
jarvis_env\Scripts\activate
pip install -r requirements.txt
```

**2. Configure secrets**
```
copy .env.example .env
```
Open `.env` and paste your Picovoice access key:
```
PICOVOICE_ACCESS_KEY=your-key-here
```

**3. Set your microphone index** *(optional)*

Run `python tools/list_devices.py` to see your audio devices, then set `MIC_INDEX` in `.env` if the default isn't correct.

**4. Add the Porcupine wake word model**

Place your `.ppn` model file at:
```
models/Jarvis_en_windows_v3_0_0/Jarvis_en_windows_v3_0_0.ppn
```
Or set `PORCUPINE_MODEL_PATH` in `.env` to a custom path.

---

## Running

```
python gui.py
```

The HUD launches. Say **"Jarvis"** to begin.

To run without the GUI (headless, for testing):
```
python jarvis_main.py
```

---

## Configuration

All tunable parameters live in `config/jarvis.yaml` — no code changes needed:

```yaml
identity:
  creator: "Sharan"        # name used in the LLM persona
  owner: "Sir"             # how Jarvis addresses you

llm:
  model: "llama3.2:3b"
  temperature: 0.35        # low = less hallucination
  num_predict: 80          # keeps responses concise

wake:
  sensitivity: 0.5         # 0.0–1.0 (higher = more sensitive)
  post_tts_cooldown: 2.5   # seconds before wake listener re-arms after speaking
```

Environment variables in `.env` override YAML values.

---

## Voice Commands

| Category | Example |
|---|---|
| App launch | *"Open Chrome"*, *"Launch VS Code"* |
| Memory store | *"My birthday is March 5th"* |
| Memory recall | *"What is my birthday?"* |
| Vision | *"What do you see?"*, *"Read my screen"* |
| Web search | *"Search for Python tutorials"* |
| Power | *"Shut down"*, *"Sleep"*, *"Lock"* |
| Language | *"Switch to Tamil"* |
| Quit | *"Goodbye Jarvis"* |

---

## Architecture

```
Audio → Porcupine (wake) → Google STT → Intent Router
                                              │
              ┌───────────────────────────────┼──────────────────────┐
              ▼               ▼               ▼                      ▼
        Power actions    Memory (SQLite)  Vision (LLaVA)     LLM (Ollama)
                                                                     │
                                         Edge TTS (streaming) ◄──────┘
                                              │
                                         PyQt6 HUD
```

The GUI and core engine are fully decoupled via callback injection — the engine never imports PyQt6, making it independently testable.

---

## Project Structure

```
├── jarvis_main.py          # Core engine, intent routing, main loop
├── gui.py                  # PyQt6 Iron Man HUD
├── llm.py                  # Ollama streaming LLM interface
├── memory_store.py         # SQLite memory (facts, utterances)
├── wake.py                 # Porcupine wake word detection
├── power_actions.py        # Shutdown / sleep / lock
├── config/
│   ├── jarvis.yaml         # Central configuration
│   └── vision.yaml         # Vision model config
├── vision/                 # LLaVA vision subsystem
├── ui/                     # Vision panel widget
├── integrations/           # Vision ↔ engine wiring
├── tools/                  # Dev utilities (mic test, device list)
└── tests/                  # Pytest suite
```

---

## Running Tests

```
pip install pytest
pytest tests/ -v
```

---

## Built by

Sharan Magesh — [github.com/sharanmagesh03](https://github.com/sharanmagesh03)
