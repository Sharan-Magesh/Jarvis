# llm.py — Local LLM interface (Ollama)
# Streaming-first: generate_streaming() feeds sentence callbacks in real-time
# for sub-second first-word latency.
import os
import re
import json
import requests
from typing import Callable

# ── JARVIS system personality ─────────────────────────────────────────────────
# {creator} is filled in from config (identity.creator in jarvis.yaml), so no
# personal name is hardcoded in source.
_SYSTEM_PROMPT_TEMPLATE = """\
You are J.A.R.V.I.S. — Just A Rather Very Intelligent System — a dry, precise AI \
assistant built by {creator} (addressed exclusively as "Sir").

RESPONSE RULES (absolute, no exceptions):
1. ONE sentence maximum. Two only for genuine technical explanations.
2. Never begin a sentence with "I". Start with an action, observation, or "Sir".
3. Formal, efficient, subtly dry-witted — like a butler who finds requests mildly \
beneath his capabilities but executes them flawlessly anyway.
4. Mild sarcasm is permitted. Puns are a compliment. Enthusiasm is not.
5. Do NOT ask clarifying questions. Infer, act, report.

STRICT HONESTY RULES (critical — hallucination is a firing offence):
- NEVER invent appointments, schedules, tasks, files, names, or facts not provided.
- NEVER make up what Sir said, planned, or asked previously unless it is in the \
  conversation history below.
- If you lack information, say so in one dry sentence. Do not fill in the blanks.
- If the input sounds like ambient noise or a fragment, respond: \
  "Didn't quite catch that, Sir."

ACTION SYNTAX — when a system action is needed, output ONLY this line, nothing else:
  ACTION:open_app:APP_NAME
  ACTION:web_search:QUERY
Actions are ONLY for explicit open/search requests. Never emit an ACTION for \
conversational responses.

Known facts about Sir (use only these — do not invent more):\
"""


def _build_system_prompt(creator: str) -> str:
    return _SYSTEM_PROMPT_TEMPLATE.format(creator=creator or "its owner")


class LocalLLM:
    def __init__(self, base_url: str | None = None, cfg: dict | None = None):
        cfg = cfg or {}
        self.base_url   = (base_url or cfg.get("url") or
                           os.environ.get("OLLAMA_URL", "http://localhost:11434")).rstrip("/")
        self.model_name = cfg.get("model") or os.environ.get("LLM_MODEL", "llama3.2:3b")
        self.timeout    = int(cfg.get("timeout") or os.environ.get("LLM_TIMEOUT", "120"))
        self._history_limit = int(cfg.get("history_limit") or
                                  os.environ.get("LLM_HISTORY", "12"))
        self._options = {
            "temperature": float(cfg.get("temperature", 0.35)),  # lower = less hallucination
            "top_p":       float(cfg.get("top_p", 0.85)),
            "num_ctx":     int(cfg.get("num_ctx", 2048)),
            "num_predict": int(cfg.get("num_predict", 80)),      # short answers only
        }

        creator = (cfg.get("creator") or os.environ.get("JARVIS_CREATOR")
                   or "its owner")
        self._system_prompt = _build_system_prompt(creator)

    # ── Availability ─────────────────────────────────────────────────────────
    def is_available(self) -> bool:
        try:
            r = requests.get(f"{self.base_url}/api/tags", timeout=8)
            if r.status_code != 200:
                return False
            models = [m.get("name", "") for m in r.json().get("models", [])]
            available = any(self.model_name in m for m in models)
            if not available:
                print(f"[llm] Model '{self.model_name}' not found. Available: {models}")
            return available
        except requests.exceptions.RequestException as exc:
            print(f"[llm] Ollama connection error: {exc}")
            return False

    # ── Prompt construction ───────────────────────────────────────────────────
    def _build_prompt(self, user_text: str, history: list, facts: dict | None = None) -> str:
        lines = [self._system_prompt]

        if facts:
            lines.append("\nKnown facts about Sir:")
            for k, v in list(facts.items())[:20]:
                lines.append(f"  - {k}: {v}")

        if history:
            lines.append("\nRecent conversation:")
            for msg in history[-self._history_limit:]:
                role    = "Sir" if msg.get("role") == "user" else "J.A.R.V.I.S"
                content = (msg.get("content") or "").strip()
                lines.append(f"  {role}: {content}")

        lines.append(f"\nSir: {user_text}\nJ.A.R.V.I.S:")
        return "\n".join(lines)

    # ── Streaming generation (preferred) ─────────────────────────────────────
    def generate_streaming(
        self,
        prompt: str,
        history: list | None = None,
        on_sentence: Callable[[str], None] | None = None,
        facts: dict | None = None,
    ) -> str:
        """
        Stream tokens from Ollama, calling on_sentence(text) for each complete
        sentence as it arrives.  Returns the full response string.
        First sentence typically arrives in ~600ms — a 3-4× latency improvement
        over waiting for the full response.
        """
        full_prompt = self._build_prompt(prompt, history or [], facts)
        buffer = ""
        full_response = ""

        try:
            print("[llm] Streaming request…")
            r = requests.post(
                f"{self.base_url}/api/generate",
                json={
                    "model":   self.model_name,
                    "prompt":  full_prompt,
                    "stream":  True,
                    "options": self._options,
                },
                timeout=self.timeout,
                stream=True,
            )

            if r.status_code != 200:
                err = f"HTTP {r.status_code} from LLM."
                if on_sentence:
                    on_sentence(err)
                return err

            for raw_line in r.iter_lines():
                if not raw_line:
                    continue
                try:
                    chunk = json.loads(raw_line)
                except json.JSONDecodeError:
                    continue

                token = chunk.get("response", "")
                buffer += token
                full_response += token

                # Flush complete sentences: . ! ? followed by space or end
                while True:
                    m = re.search(r'([^.!?]*[.!?]+)(?:\s|$)', buffer)
                    if not m:
                        break
                    sentence = m.group(1).strip()
                    buffer = buffer[m.end():]
                    if sentence and on_sentence:
                        on_sentence(sentence)

                if chunk.get("done"):
                    break

            # Flush any remaining text
            remainder = buffer.strip()
            if remainder and on_sentence:
                on_sentence(remainder)

            print("[llm] Stream complete.")
            return full_response.strip()

        except requests.exceptions.Timeout:
            msg = "The model appears to be loading, Sir. A moment's patience is advised."
            if on_sentence:
                on_sentence(msg)
            return msg
        except requests.exceptions.RequestException as exc:
            msg = f"Communication error with the LLM subsystem: {exc}"
            if on_sentence:
                on_sentence(msg)
            return msg

    # -- Blocking generation (fallback / non-conversational uses) -------------
    def generate_response(self, prompt, history=None, facts=None):
        full_prompt = self._build_prompt(prompt, history or [], facts)
        try:
            print("[llm] Sending request to LLM...")
            r = requests.post(
                f"{self.base_url}/api/generate",
                json={
                    "model":   self.model_name,
                    "prompt":  full_prompt,
                    "stream":  False,
                    "options": self._options,
                },
                timeout=self.timeout,
            )
            if r.status_code == 200:
                result = (r.json().get("response") or "").strip()
                print("[llm] Response received.")
                return result or "An empty response was received, Sir."
            return f"Error: HTTP {r.status_code} from LLM."
        except requests.exceptions.Timeout:
            return "The model timed out, Sir. It may still be loading."
        except requests.exceptions.RequestException as exc:
            return f"LLM communication error: {exc}"

    # -- Warm-up ping ---------------------------------------------------------
    def warm_up(self):
        resp = self.generate_response("Respond with exactly: Systems nominal.", history=[])
        ok   = bool(resp and "timed out" not in resp.lower() and not resp.startswith("Error"))
        print("[llm] Warm-up complete." if ok else "[llm] Warm-up failed.")
        return ok
