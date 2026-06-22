# vision/vlm_adapter.py
from abc import ABC, abstractmethod
import numpy as np

class VLMAdapter(ABC):
    @abstractmethod
    def infer(self, frame_bgr: np.ndarray, prompt: str) -> str:
        """Return text response for (image, prompt)."""
        raise NotImplementedError
