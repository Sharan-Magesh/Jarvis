# wake.py
import os
import sounddevice as sd
import pvporcupine


# ── Load .env (dependency-free) so secrets stay out of source ───────────────────
def _load_dotenv(path: str | None = None) -> None:
    """Minimal .env loader for KEY=VALUE lines.

    Does NOT overwrite variables already present in the environment, and never
    raises during import. Avoids a python-dotenv dependency.
    """
    if path is None:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    try:
        with open(path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, val = line.partition("=")
                key, val = key.strip(), val.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = val
    except FileNotFoundError:
        pass
    except Exception as exc:  # never let config loading crash startup
        print(f"[wake] .env load skipped: {exc}")


_load_dotenv()

# ── Config (read from environment / .env — no secrets hard-coded) ───────────────
ACCESS_KEY = os.environ.get("PICOVOICE_ACCESS_KEY", "").strip()

_BASE_DIR  = os.path.dirname(os.path.abspath(__file__))
MODEL_PATH = os.environ.get(
    "PORCUPINE_MODEL_PATH",
    os.path.join(
        _BASE_DIR, "models",
        "Jarvis_en_windows_v3_0_0",
        "Jarvis_en_windows_v3_0_0.ppn"
    )
)
SENSITIVITY  = float(os.environ.get("PORCUPINE_SENSITIVITY", "1.0"))
DEVICE_INDEX = int(os.environ.get("MIC_INDEX", "2"))
# ────────────────────────────────────────────────────────────────────────────────

# Module-level handle — created lazily so import never crashes
_porcupine   = None
_init_failed = False   # stays True after first failure; skips all future retries


def _get_porcupine():
    """
    Return (and cache) the Porcupine instance, raising on any failure.
    After the first failure _init_failed is set so subsequent calls raise
    immediately (a cheap RuntimeError) without hitting the Picovoice SDK again.
    """
    global _porcupine, _init_failed
    if _init_failed:
        raise RuntimeError("Porcupine previously failed to initialize.")
    if _porcupine is None:
        if not ACCESS_KEY:
            _init_failed = True
            raise RuntimeError(
                "PICOVOICE_ACCESS_KEY is not set. Add it to the .env file."
            )
        if not os.path.isfile(MODEL_PATH):
            _init_failed = True
            raise FileNotFoundError(
                f"Porcupine model not found: {MODEL_PATH}\n"
                "Set PORCUPINE_MODEL_PATH env var to fix this."
            )
        try:
            _porcupine = pvporcupine.create(
                access_key=ACCESS_KEY,
                keyword_paths=[MODEL_PATH],
                sensitivities=[SENSITIVITY],
            )
        except Exception:
            _init_failed = True
            raise   # propagate — caller decides whether to fall back
    return _porcupine


def list_devices():
    """Print available audio input devices for debugging."""
    print("Available audio devices:")
    print(sd.query_devices())


def listen_for_wake(timeout: float | None = None) -> bool:
    """
    Block until the 'Jarvis' wake word is detected (or timeout expires).

    Args:
        timeout: seconds to wait; None = wait forever.

    Returns:
        True  — wake word heard
        False — timed out without detection

    Raises:
        Any exception from _get_porcupine() (key error, model missing, etc.)
        so that the caller can decide to fall back gracefully.
    """
    porc = _get_porcupine()   # raises on failure — do NOT catch here

    print("Listening for wake word…")
    elapsed = 0.0
    chunk_sec = porc.frame_length / porc.sample_rate  # seconds per frame

    try:
        with sd.InputStream(
            device=DEVICE_INDEX,
            channels=1,
            samplerate=porc.sample_rate,
            dtype="int16",
        ) as stream:
            while True:
                pcm, _ = stream.read(porc.frame_length)
                if porc.process(pcm.flatten()) >= 0:
                    print("Wake word detected!")
                    return True
                if timeout is not None:
                    elapsed += chunk_sec
                    if elapsed >= timeout:
                        return False
    except Exception as exc:
        print(f"[wake] InputStream error: {exc}")
        return False


def cleanup():
    """Release Porcupine resources."""
    global _porcupine
    if _porcupine is not None:
        try:
            _porcupine.delete()
        except Exception:
            pass
        _porcupine = None
