# vision/vision_agent.py
from typing import Literal
import cv2
import numpy as np
from vision.vlm_adapter import VLMAdapter

Kind = Literal["describe", "ocr", "detect"]

_PROMPTS: dict[str, str] = {
    "describe": "Describe the scene briefly. Mention key objects and any visible text.",
    "ocr":      "Extract all legible text from the image. Preserve line breaks.",
    "detect":   "List the main objects you can identify in this image, comma-separated.",
}


class VisionAgent:
    def __init__(self, adapter: VLMAdapter, max_image_side: int = 896):
        self.adapter  = adapter
        self.max_side = max(1, max_image_side)

    def _downscale(self, img: np.ndarray) -> np.ndarray:
        """Resize so the longer edge is at most max_side (no upscaling)."""
        if img is None or img.size == 0:
            raise ValueError("Empty or None frame passed to VisionAgent.")
        h, w = img.shape[:2]
        if h == 0 or w == 0:
            raise ValueError(f"Invalid frame dimensions: {w}×{h}")
        s = self.max_side / max(h, w)
        if s < 1.0:
            new_w, new_h = max(1, int(w * s)), max(1, int(h * s))
            img = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_AREA)
        return img

    def run(self, kind: str, frame_bgr: np.ndarray) -> str:
        """Run the requested vision task on *frame_bgr* and return the result."""
        try:
            frame_bgr = self._downscale(frame_bgr)
        except ValueError as exc:
            return f"[vision] Invalid frame: {exc}"

        prompt = _PROMPTS.get(kind, "Give a concise description of this image.")

        try:
            result = self.adapter.infer(frame_bgr, prompt)
            return result or "[vision] No response from model."
        except Exception as exc:
            return f"[vision] Inference error: {exc}"
