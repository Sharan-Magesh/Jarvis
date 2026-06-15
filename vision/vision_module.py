# vision/vision_module.py
import cv2
import threading
import time
import logging

log = logging.getLogger(__name__)


class VisionModule:
    """
    Captures frames from a webcam in a background thread.
    Thread-safe: latest_frame() always returns a copy.
    """

    def __init__(self, camera_index: int = 0):
        self.camera_index = camera_index
        self._cap:     cv2.VideoCapture | None = None
        self._lock     = threading.Lock()
        self._last     = None
        self._running  = False
        self._thread:  threading.Thread | None = None

    # ── Public API ──────────────────────────────────────────────────────────────

    def start(self) -> bool:
        """Open the camera and start the capture loop. Returns True on success."""
        if self._running:
            return True

        cap = cv2.VideoCapture(self.camera_index, cv2.CAP_DSHOW)
        if not cap.isOpened():
            log.error("[vision] Cannot open camera index %d", self.camera_index)
            cap.release()
            return False

        with self._lock:
            self._cap     = cap
            self._last    = None
            self._running = True

        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="vision-capture"
        )
        self._thread.start()
        log.debug("[vision] Camera %d started.", self.camera_index)
        return True

    def stop(self):
        """Signal the capture loop to stop and release the camera."""
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
        # Camera is released inside _loop's finally block

    def latest_frame(self):
        """Return a copy of the most recent frame, or None if none yet."""
        with self._lock:
            return None if self._last is None else self._last.copy()

    # ── Capture loop ───────────────────────────────────────────────────────────

    def _loop(self):
        try:
            while self._running:
                ok, frame = self._cap.read()
                if ok:
                    with self._lock:
                        self._last = frame
                else:
                    # Camera read failed — brief pause before retry
                    log.warning("[vision] Frame read failed, retrying…")
                    time.sleep(0.1)
                time.sleep(0.033)   # ~30 FPS cap
        except Exception as exc:
            log.error("[vision] Capture loop error: %s", exc)
        finally:
            with self._lock:
                if self._cap is not None:
                    self._cap.release()
                    self._cap = None
            log.debug("[vision] Camera released.")
