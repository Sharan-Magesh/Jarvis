# vision/adapters/ollama_llava.py
import base64
import logging

import cv2
import numpy as np
import requests

from vision.vlm_adapter import VLMAdapter

log = logging.getLogger(__name__)


class OllamaLLaVA(VLMAdapter):
    """Send frames to Ollama's LLaVA vision model via HTTP."""

    def __init__(self, model: str, endpoint: str, timeout_sec: int = 90):
        self.model   = model
        self.url     = endpoint
        self.timeout = timeout_sec
        self.sess    = requests.Session()

    def infer(self, frame_bgr: np.ndarray, prompt: str) -> str:
        # ── Encode frame ────────────────────────────────────────────────────────
        if frame_bgr is None or frame_bgr.size == 0:
            return "[encode error] Empty frame."

        ok, buf = cv2.imencode(".jpg", frame_bgr, [cv2.IMWRITE_JPEG_QUALITY, 85])
        if not ok or buf is None:
            return "[encode error] JPEG encoding failed."

        img_b64 = base64.b64encode(buf).decode("utf-8")

        payload = {
            "model":  self.model,
            "prompt": prompt,
            "images": [img_b64],
            "stream": False,
        }

        # ── HTTP request ────────────────────────────────────────────────────────
        try:
            r = self.sess.post(self.url, json=payload, timeout=self.timeout)
        except requests.exceptions.Timeout:
            log.warning("[llava] Request timed out after %ds.", self.timeout)
            return "[vision] Request timed out."
        except requests.exceptions.RequestException as exc:
            log.error("[llava] Network error: %s", exc)
            return f"[vision] Network error: {exc}"

        # ── Parse response ──────────────────────────────────────────────────────
        try:
            r.raise_for_status()
        except requests.HTTPError as exc:
            log.error("[llava] HTTP error: %s", exc)
            return f"[vision] HTTP {r.status_code}: {exc}"

        try:
            data = r.json()
        except ValueError:
            return "[vision] Invalid JSON response from model."

        result = (data or {}).get("response", "").strip()
        if not result:
            return "[vision] Empty response from model."
        return result
