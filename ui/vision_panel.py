# ui/vision_panel.py
from PyQt6.QtWidgets import (
    QWidget, QLabel, QVBoxLayout, QHBoxLayout, QPushButton,
    QTextEdit, QSizePolicy, QFrame
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QPixmap, QImage
import cv2
from typing import Callable, Optional
from vision.vision_module import VisionModule

_ACCENT  = "#00d4ff"
_MUTED   = "#3d5a66"
_CARD    = "#0d1117"
_BORDER  = "rgba(0, 212, 255, 0.10)"
_TEXT    = "#c9e8f0"

_BTN_BASE = """
    QPushButton {{
        background: {bg};
        color: {fg};
        border: 1px solid {border};
        border-radius: 8px;
        padding: 6px 16px;
        font-size: 11px;
        font-weight: 600;
        letter-spacing: 1px;
    }}
    QPushButton:hover {{
        background: {hover};
        border-color: {fg};
    }}
    QPushButton:pressed {{
        background: {pressed};
    }}
    QPushButton:disabled {{
        color: #2a3d47;
        border-color: #1a2a32;
        background: transparent;
    }}
"""

def _primary_style():
    return _BTN_BASE.format(
        bg="rgba(0,212,255,0.10)", fg=_ACCENT,
        border="rgba(0,212,255,0.30)",
        hover="rgba(0,212,255,0.18)",
        pressed="rgba(0,212,255,0.25)",
    )

def _ghost_style():
    return _BTN_BASE.format(
        bg="transparent", fg="#7da8b8",
        border="rgba(0,212,255,0.15)",
        hover="rgba(0,212,255,0.08)",
        pressed="rgba(0,212,255,0.14)",
    )


class VisionPanel(QWidget):
    def __init__(
        self,
        on_request: Optional[Callable[[str, any], str]] = None,
        camera_index: int = 0,
    ):
        super().__init__()
        self.on_request = on_request
        self.vm = VisionModule(camera_index=camera_index)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)

        # Section header row
        header_row = QHBoxLayout()
        header_row.setSpacing(10)

        section_lbl = QLabel("VISION")
        section_lbl.setStyleSheet(
            f"color: {_MUTED}; font-size: 10px; font-weight: 700; letter-spacing: 2px;"
        )
        header_row.addWidget(section_lbl)

        self.status = QLabel("Ready")
        self.status.setStyleSheet(f"color: {_ACCENT}; font-size: 11px; font-weight: 600;")
        header_row.addWidget(self.status)
        header_row.addStretch()

        lay.addLayout(header_row)

        # Thin divider
        div = QFrame()
        div.setFrameShape(QFrame.Shape.HLine)
        div.setStyleSheet(f"border: none; border-top: 1px solid {_BORDER};")
        lay.addWidget(div)

        # Two-column: preview | controls+output
        body = QHBoxLayout()
        body.setSpacing(14)

        # Camera preview
        self.preview = QLabel("Camera off")
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setFixedSize(320, 220)
        self.preview.setStyleSheet(f"""
            background: #080c10;
            border: 1px solid {_BORDER};
            border-radius: 12px;
            color: {_MUTED};
            font-size: 12px;
            letter-spacing: 1px;
        """)
        body.addWidget(self.preview)

        # Right side: buttons + output
        right = QVBoxLayout()
        right.setSpacing(10)

        # Camera toggle button
        self.btn_cam = QPushButton("▶  Start Camera")
        self.btn_cam.setStyleSheet(_primary_style())
        self.btn_cam.setFixedHeight(34)
        self.btn_cam.clicked.connect(self._toggle_cam)
        right.addWidget(self.btn_cam)

        # Analysis buttons row
        action_row = QHBoxLayout()
        action_row.setSpacing(8)
        self.btn_desc = QPushButton("Describe")
        self.btn_ocr  = QPushButton("OCR")
        self.btn_det  = QPushButton("Detect")
        for btn in (self.btn_desc, self.btn_ocr, self.btn_det):
            btn.setStyleSheet(_ghost_style())
            btn.setFixedHeight(32)
            btn.setEnabled(False)
            action_row.addWidget(btn)
        right.addLayout(action_row)

        self.btn_desc.clicked.connect(lambda: self._do("describe"))
        self.btn_ocr.clicked.connect(lambda:  self._do("ocr"))
        self.btn_det.clicked.connect(lambda:  self._do("detect"))

        # Output text area
        self.out = QTextEdit()
        self.out.setReadOnly(True)
        self.out.setStyleSheet(f"""
            QTextEdit {{
                background: #080c10;
                color: {_TEXT};
                border: 1px solid {_BORDER};
                border-radius: 10px;
                font-size: 12px;
                padding: 8px 10px;
            }}
            QScrollBar:vertical {{
                background: transparent;
                width: 5px;
            }}
            QScrollBar::handle:vertical {{
                background: rgba(0,212,255,0.20);
                border-radius: 3px;
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0;
            }}
        """)
        self.out.setFixedHeight(138)
        right.addWidget(self.out)
        right.addStretch()

        body.addLayout(right)
        lay.addLayout(body)

        self._cam_timer = QTimer(self)
        self._cam_timer.timeout.connect(self._refresh)

    # ── Camera toggle ───────────────────────────────────────────────────────────
    def _toggle_cam(self):
        if self._cam_timer.isActive():
            self._cam_timer.stop()
            self.vm.stop()
            self.preview.setText("Camera off")
            self.btn_cam.setText("▶  Start Camera")
            self.btn_cam.setStyleSheet(_primary_style())
            for btn in (self.btn_desc, self.btn_ocr, self.btn_det):
                btn.setEnabled(False)
            self._set_status("Stopped", _MUTED)
        else:
            self.vm.start()
            self._cam_timer.start(100)
            self.btn_cam.setText("■  Stop Camera")
            self.btn_cam.setStyleSheet(_BTN_BASE.format(
                bg="rgba(232,121,249,0.10)", fg="#e879f9",
                border="rgba(232,121,249,0.30)",
                hover="rgba(232,121,249,0.18)",
                pressed="rgba(232,121,249,0.25)",
            ))
            for btn in (self.btn_desc, self.btn_ocr, self.btn_det):
                btn.setEnabled(True)
            self._set_status("Live", "#00ff9d")

    def _refresh(self):
        f = self.vm.latest_frame()
        if f is None:
            return
        rgb = cv2.cvtColor(f, cv2.COLOR_BGR2RGB)
        h, w, ch = rgb.shape
        qimg = QImage(rgb.data, w, h, ch * w, QImage.Format.Format_RGB888)
        pix = QPixmap.fromImage(qimg).scaled(
            self.preview.width(), self.preview.height(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.preview.setPixmap(pix)

    def _do(self, kind: str):
        f = self.vm.latest_frame()
        if f is None:
            self.out.append('<i style="color:#3d5a66;">No frame — start camera first.</i>')
            return
        self._set_status(f"Running {kind}…", "#ffd700")
        result = "(no backend)" if not callable(self.on_request) else self.on_request(kind, f)
        self.out.append(
            f'<b style="color:{_ACCENT};font-size:10px;letter-spacing:1px;">'
            f'{kind.upper()}</b><br>'
            f'<span style="color:{_TEXT};">{result}</span><br>'
        )
        self._set_status("Ready", _ACCENT)

    def _set_status(self, text: str, color: str):
        self.status.setText(text)
        self.status.setStyleSheet(f"color: {color}; font-size: 11px; font-weight: 600;")

    # ── Voice hook ──────────────────────────────────────────────────────────────
    def handle_voice_command(self, text: str):
        # Accepts BOTH natural phrases ("start camera") and the internal kind
        # codes emitted by jarvis_main (_VISION_MAP): cam_on, cam_off,
        # cam_describe, cam_detect. Substring checks below cover the codes too
        # (e.g. "cam_describe" contains "describe").
        t = (text or "").lower().strip()
        if t == "cam_on" or any(p in t for p in ["start camera", "camera on", "turn on camera"]):
            if not self._cam_timer.isActive():
                self._toggle_cam()
        elif t == "cam_off" or any(p in t for p in ["stop camera", "camera off", "turn off camera"]):
            if self._cam_timer.isActive():
                self._toggle_cam()
        elif "detect" in t or any(p in t for p in ["objects", "find objects"]):
            self._do("detect")
        elif "describe" in t or any(p in t for p in ["what do you see", "what's on my"]):
            self._do("describe")
        elif "ocr" in t or any(p in t for p in ["read this", "read the screen", "extract text"]):
            self._do("ocr")
