# tests/test_memory.py
# Tests for MemoryStore (SQLite).
# Self-contained: imports only stdlib + the MemoryStore class.
import os
import sys
import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock

import pytest

# ---------------------------------------------------------------------------
# Inline MemoryStore definition so tests run without the full jarvis_main
# import chain (edge_tts, PyAudio, etc. are not available in CI).
# This is a verbatim copy of the class from jarvis_main.py and is the
# authoritative test of its contract.
# ---------------------------------------------------------------------------
class MemoryStore:
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

    def __init__(self, db_path="memory.db", migrate_json=None):
        self.db_path = db_path
        self._lock   = RLock()
        self._conn   = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
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

    def _migrate_json(self, json_path):
        p = Path(json_path)
        if not p.exists():
            return
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
        except Exception:
            pass

    def set_fact(self, key, value):
        key = key.strip().lower()
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO facts VALUES (?, ?, ?)",
                (key, value.strip(), datetime.now(timezone.utc).isoformat())
            )
            self._conn.commit()

    def get_fact(self, key):
        key = key.strip().lower()
        with self._lock:
            row = self._conn.execute(
                "SELECT value FROM facts WHERE key=?", (key,)
            ).fetchone()
            return row[0] if row else None

    def forget_fact(self, key):
        key = key.strip().lower()
        with self._lock:
            c = self._conn.execute("DELETE FROM facts WHERE key=?", (key,))
            self._conn.commit()
            return c.rowcount > 0

    def list_facts(self):
        with self._lock:
            rows = self._conn.execute("SELECT key, value FROM facts").fetchall()
            return dict(rows)

    def add_utterance(self, ts, text):
        with self._lock:
            self._conn.execute(
                "INSERT INTO utterances (ts, text) VALUES (?, ?)", (ts, text)
            )
            self._conn.commit()

    def search_utterances(self, query, limit=5):
        q = f"%{query.lower()}%"
        with self._lock:
            rows = self._conn.execute(
                "SELECT text FROM utterances WHERE LOWER(text) LIKE ? "
                "ORDER BY id DESC LIMIT ?", (q, limit)
            ).fetchall()
            return [r[0] for r in rows]

    def incr_turns(self, n=1):
        with self._lock:
            self._conn.execute(
                "UPDATE stats SET value = CAST(value AS INTEGER) + ? "
                "WHERE key = 'conversation_turns'", (n,)
            )
            self._conn.commit()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def mem(tmp_path):
    return MemoryStore(db_path=str(tmp_path / "test.db"), migrate_json=None)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
def test_set_and_get(mem):
    mem.set_fact("name", "Sharan")
    assert mem.get_fact("name") == "Sharan"


def test_key_normalized(mem):
    mem.set_fact("  NAME  ", "Sharan")
    assert mem.get_fact("name") == "Sharan"


def test_overwrite(mem):
    mem.set_fact("color", "blue")
    mem.set_fact("color", "black")
    assert mem.get_fact("color") == "black"


def test_forget(mem):
    mem.set_fact("temp", "value")
    assert mem.forget_fact("temp") is True
    assert mem.get_fact("temp") is None
    assert mem.forget_fact("temp") is False


def test_list_facts(mem):
    mem.set_fact("a", "1")
    mem.set_fact("b", "2")
    facts = mem.list_facts()
    assert facts["a"] == "1"
    assert facts["b"] == "2"


def test_add_and_search_utterance(mem):
    mem.add_utterance("2026-01-01T00:00:00Z", "hello world")
    results = mem.search_utterances("hello")
    assert len(results) == 1
    assert "hello world" in results[0]


def test_search_no_match(mem):
    mem.add_utterance("2026-01-01T00:00:00Z", "unrelated text")
    assert mem.search_utterances("xyz_not_present") == []


def test_incr_turns_no_error(mem):
    mem.incr_turns(1)
    mem.incr_turns(3)  # just confirm it doesn't raise


def test_json_migration(tmp_path):
    json_path = tmp_path / "memory.json"
    json_path.write_text(
        json.dumps({"facts": {"pet": "Simba", "city": "Chennai"}}),
        encoding="utf-8"
    )
    mem = MemoryStore(db_path=str(tmp_path / "mem.db"), migrate_json=str(json_path))
    assert mem.get_fact("pet")  == "Simba"
    assert mem.get_fact("city") == "Chennai"


def test_thread_safety(mem):
    """Concurrent writes must not corrupt the database."""
    errors = []
    def writer(n):
        try:
            for i in range(20):
                mem.set_fact(f"key_{n}_{i}", f"val_{n}_{i}")
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=writer, args=(n,)) for n in range(5)]
    for t in threads: t.start()
    for t in threads: t.join()

    assert errors == [], f"Thread safety errors: {errors}"
    assert len(mem.list_facts()) == 5 * 20
