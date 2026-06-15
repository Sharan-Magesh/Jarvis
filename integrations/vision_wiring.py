# integrations/vision_wiring.py
import os
import logging

log = logging.getLogger(__name__)

# Sensible defaults so the vision system works even without a config file
_DEFAULTS = {
    "model":          "llava:13b",
    "endpoint":       "http://localhost:11434/api/generate",
    "timeout_sec":    90,
    "max_image_side": 896,
    "camera_index":   0,
}


def _load_config(config_path: str) -> dict:
    """Load vision.yaml if it exists; otherwise return defaults."""
    if not os.path.isfile(config_path):
        log.warning(
            "[vision_wiring] Config not found at '%s' — using defaults.", config_path
        )
        return dict(_DEFAULTS)

    try:
        import yaml
        with open(config_path, "r", encoding="utf-8") as f:
            loaded = yaml.safe_load(f) or {}
        cfg = {**_DEFAULTS, **loaded}   # defaults filled in for any missing keys
        return cfg
    except Exception as exc:
        log.warning("[vision_wiring] Failed to parse config (%s) — using defaults.", exc)
        return dict(_DEFAULTS)


def build_vision_on_request(config_path: str = "config/vision.yaml"):
    """
    Build and return (on_request_callable, cfg_dict).

    on_request(kind, frame_bgr) → str
    """
    from vision.vision_agent import VisionAgent
    from vision.adapters.ollama_llava import OllamaLLaVA

    cfg = _load_config(config_path)

    adapter = OllamaLLaVA(
        model       = cfg["model"],
        endpoint    = cfg["endpoint"],
        timeout_sec = int(cfg.get("timeout_sec", 90)),
    )
    agent = VisionAgent(
        adapter,
        max_image_side = int(cfg.get("max_image_side", 896)),
    )

    def on_request(kind: str, frame_bgr) -> str:
        try:
            return agent.run(kind, frame_bgr)
        except Exception as exc:
            log.error("[vision_wiring] on_request error: %s", exc)
            return f"[vision] Error: {exc}"

    return on_request, cfg
