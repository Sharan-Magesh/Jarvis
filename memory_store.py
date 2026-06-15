# memory_store.py
import json
import os
import logging
import threading
from datetime import datetime, timezone

log = logging.getLogger(__name__)


class MemoryStore:
    """
    Thread-safe, lightweight persistent memory for Jarvis.
    Stores facts, preferences, and simple stats in a JSON file.
    Uses atomic write (tmp → rename) to prevent corruption.
    """

    _DEFAULTS: dict = {
        "facts":       {},
        "preferences": {},
        "stats": {
            "created_at":        None,
            "updated_at":        None,
            "conversation_turns": 0,
        },
    }

    def __init__(self, path: str = "memory.json"):
        self.path  = path
        self._lock = threading.RLock()
        self._data = {k: v.copy() if isinstance(v, dict) else v
                      for k, v in self._DEFAULTS.items()}
        self._data["stats"] = dict(self._DEFAULTS["stats"])  # deep copy stats
        self._load()

    # ── Persistence ────────────────────────────────────────────────────────────

    def _load(self):
        with self._lock:
            if not os.path.exists(self.path):
                self._data["stats"]["created_at"] = datetime.now(timezone.utc).isoformat()
                return
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                # Merge loaded data, keeping defaults for missing keys
                for section in ("facts", "preferences", "stats"):
                    if isinstance(loaded.get(section), dict):
                        self._data[section].update(loaded[section])
            except json.JSONDecodeError as exc:
                log.warning("[memory] Corrupt memory.json (%s) — starting fresh.", exc)
            except OSError as exc:
                log.warning("[memory] Cannot read memory.json: %s", exc)

            if not self._data["stats"].get("created_at"):
                self._data["stats"]["created_at"] = datetime.now(timezone.utc).isoformat()

    def _save(self):
        """Atomic write: write to .tmp then rename, so the file is never half-written."""
        with self._lock:
            self._data["stats"]["updated_at"] = datetime.now(timezone.utc).isoformat()
            tmp = self.path + ".tmp"
            try:
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(self._data, f, ensure_ascii=False, indent=2)
                os.replace(tmp, self.path)
            except OSError as exc:
                log.error("[memory] Failed to save memory: %s", exc)
                try:
                    os.remove(tmp)
                except OSError:
                    pass

    # ── Facts API ──────────────────────────────────────────────────────────────

    def set_fact(self, key: str, value: str):
        key = key.strip().lower()
        with self._lock:
            self._data["facts"][key] = value.strip()
            self._save()

    def get_fact(self, key: str) -> str | None:
        with self._lock:
            return self._data["facts"].get(key.strip().lower())

    def forget_fact(self, key: str) -> bool:
        key = key.strip().lower()
        with self._lock:
            existed = self._data["facts"].pop(key, None) is not None
            if existed:
                self._save()
            return existed

    def list_facts(self) -> dict:
        with self._lock:
            return dict(self._data["facts"])

    # ── Preferences API ────────────────────────────────────────────────────────

    def set_pref(self, key: str, value: str):
        key = key.strip().lower()
        with self._lock:
            self._data["preferences"][key] = value.strip()
            self._save()

    def get_pref(self, key: str) -> str | None:
        with self._lock:
            return self._data["preferences"].get(key.strip().lower())

    # ── Stats API ──────────────────────────────────────────────────────────────

    def incr_turns(self, n: int = 1):
        with self._lock:
            self._data["stats"]["conversation_turns"] = (
                self._data["stats"].get("conversation_turns", 0) + n
            )
            self._save()

    def get_stats(self) -> dict:
        with self._lock:
            return dict(self._data["stats"])
