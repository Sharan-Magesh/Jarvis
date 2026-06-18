# gui.py — J.A.R.V.I.S. Minimalist Breathing HUD
import math
import threading
import time
import sys

from jarvis_main import EnhancedJarvis

from PyQt6.QtWidgets import (
    QApplication, QWidget, QLabel, QVBoxLayout, QHBoxLayout, QFrame,
    QSizePolicy, QTextEdit,
)
from PyQt6.QtGui import (
    QPainter, QColor, QBrush, QPen, QRadialGradient, QFont,
)
from PyQt6.QtCore import Qt, QTimer, QRectF, QPointF

from ui.vision_panel import VisionPanel
from integrations.vision_wiring import build_vision_on_request

# ─────────────────────────────────────────────────────────────────────────────
# PALETTE & STATE COLORS
# ─────────────────────────────────────────────────────────────────────────────
_BG   = "#03050a"
_TEXT = "#9ab8c8"
_DIM  = "#162430"

_STATE_COLORS = {
    "IDLE":      QColor(0,   175, 215),
    "LISTENING": QColor(0,   210, 120),
    "THINKING":  QColor(210, 160,   0),
    "SPEAKING":  QColor(170,  70, 235),
    "BOOT":      QColor(215,  85,  35),
}
_STATE_HEX = {k: f"#{v.red():02x}{v.green():02x}{v.blue():02x}"
              for k, v in _STATE_COLORS.items()}

_STYLE = f"""
QWidget {{
    background-color: {_BG};
    color: {_TEXT};
    font-family: 'Segoe UI', 'Inter', Arial, sans-serif;
    font-size: 13px;
}}
QTextEdit#ChatLog {{
    background: transparent;
    border: none;
    color: {_TEXT};
    font-size: 13px;
    padding: 0px 4px;
    selection-background-color: rgba(0,175,215,0.12);
}}
QScrollBar:vertical {{
    background: transparent; width: 2px; margin: 0; border: none;
}}
QScrollBar::handle:vertical {{
    background: rgba(0,175,215,0.14);
    border-radius: 1px; min-height: 20px;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
"""


# ─────────────────────────────────────────────────────────────────────────────
# BREATHING ORB  — the only decoration in the UI
# ─────────────────────────────────────────────────────────────────────────────
class BreathingOrbWidget(QWidget):
    """
    A soft radial glow that inhales and exhales.
    Idle: slow 5-second breath cycle, cyan.
    Active: faster pulse, color shifts with state.
    """
    _IDLE_SPEED   = 0.016   # ~5 s per breath
    _ACTIVE_SPEED = 0.036   # ~2.5 s per pulse

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAutoFillBackground(False)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self._phase = 0.0
        self._speed = self._IDLE_SPEED

        c = _STATE_COLORS["BOOT"]
        self._cr, self._cg, self._cb = float(c.red()), float(c.green()), float(c.blue())
        self._tr, self._tg, self._tb = self._cr, self._cg, self._cb

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(33)   # 30 fps

    def set_state(self, state: str):
        c = _STATE_COLORS.get(state, _STATE_COLORS["IDLE"])
        self._tr, self._tg, self._tb = float(c.red()), float(c.green()), float(c.blue())
        self._speed = self._ACTIVE_SPEED if state in ("LISTENING", "THINKING", "SPEAKING") \
                      else self._IDLE_SPEED

    def _tick(self):
        self._phase = (self._phase + self._speed) % (2 * math.pi)
        lr = 0.05   # color lerp rate
        self._cr += (self._tr - self._cr) * lr
        self._cg += (self._tg - self._cg) * lr
        self._cb += (self._tb - self._cb) * lr
        self.update()

    def paintEvent(self, event):
        w, h = self.width(), self.height()
        cx, cy = w / 2, h / 2

        # Breath: 0.78 → 1.0 (sin wave)
        breath = 0.78 + 0.22 * (math.sin(self._phase) * 0.5 + 0.5)

        r = int(self._cr); g = int(self._cg); b = int(self._cb)
        base = min(w, h) * 0.26 * breath

        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)

        # Halo — very diffuse, large
        hr = base * 3.6
        halo = QRadialGradient(QPointF(cx, cy), hr)
        halo.setColorAt(0.0, QColor(r, g, b, 16))
        halo.setColorAt(0.4, QColor(r, g, b, 7))
        halo.setColorAt(1.0, QColor(0, 0, 0, 0))
        p.setBrush(QBrush(halo))
        p.drawEllipse(QRectF(cx - hr, cy - hr, hr * 2, hr * 2))

        # Mid glow
        mr = base * 1.85
        mid = QRadialGradient(QPointF(cx, cy), mr)
        mid.setColorAt(0.0, QColor(r, g, b, 50))
        mid.setColorAt(0.55, QColor(r, g, b, 18))
        mid.setColorAt(1.0,  QColor(0, 0, 0, 0))
        p.setBrush(QBrush(mid))
        p.drawEllipse(QRectF(cx - mr, cy - mr, mr * 2, mr * 2))

        # Core orb
        core = QRadialGradient(QPointF(cx, cy), base)
        core.setColorAt(0.0,  QColor(min(r+90,255), min(g+90,255), min(b+90,255), 255))
        core.setColorAt(0.38, QColor(r, g, b, 230))
        core.setColorAt(0.80, QColor(r//2, g//2, b//2, 100))
        core.setColorAt(1.0,  QColor(0, 0, 0, 0))
        p.setBrush(QBrush(core))
        p.drawEllipse(QRectF(cx - base, cy - base, base * 2, base * 2))

        # Edge ring — pulses with breath
        ring_a = int(45 + 65 * (math.sin(self._phase) * 0.5 + 0.5))
        p.setPen(QPen(QColor(r, g, b, ring_a), 0.8))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QRectF(cx - base, cy - base, base * 2, base * 2))

        p.end()


# ─────────────────────────────────────────────────────────────────────────────
# VOICE WAVEFORM  — thin, minimal, only visible when speaking
# ─────────────────────────────────────────────────────────────────────────────
class WaveformWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAutoFillBackground(False)
        self.setFixedHeight(32)
        self._amp   = 0.0
        self._phase = 0.0
        self._live  = False
        self._color = _STATE_COLORS["IDLE"]
        t = QTimer(self)
        t.timeout.connect(self._tick)
        t.start(25)

    def set_live(self, live: bool):
        self._live = live

    def set_color(self, color: QColor):
        self._color = color

    def _tick(self):
        target = 1.0 if self._live else 0.0
        self._amp = self._amp + (target - self._amp) * 0.08
        self._phase += 0.28 if self._live else 0.05
        self.update()

    def paintEvent(self, event):
        w, h = self.width(), self.height()
        if w <= 0 or h <= 0:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        mid = h / 2
        r, g, b = self._color.red(), self._color.green(), self._color.blue()

        if self._amp < 0.01:
            # Flat rest line
            p.setPen(QPen(QColor(r, g, b, 22), 1))
            p.drawLine(QPointF(0, mid), QPointF(w, mid))
            p.end()
            return

        bars = 48
        bw   = w / bars
        p.setPen(Qt.PenStyle.NoPen)
        for i in range(bars):
            val = (
                math.sin(self._phase + i * 0.38) * 0.6
                + math.sin(self._phase * 1.4 + i * 0.78) * 0.3
                + math.sin(self._phase * 0.6 + i * 1.1)  * 0.1
            )
            bh  = max(abs(val) * (h * 0.44) * self._amp, 1.2)
            x   = i * bw + bw / 2
            a   = int(90 + 100 * self._amp)
            p.setBrush(QBrush(QColor(r, g, b, a)))
            p.drawRoundedRect(
                QRectF(x - bw * 0.28, mid - bh, bw * 0.56, bh * 2), 1.5, 1.5
            )
        p.end()


# ─────────────────────────────────────────────────────────────────────────────
# BOOT OVERLAY
# ─────────────────────────────────────────────────────────────────────────────
class BootOverlayWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAutoFillBackground(False)
        self._lines:   list[str] = []
        self._alpha  = 255
        self._visible = True
        self._fade_t  = QTimer(self)
        self._fade_t.timeout.connect(self._fade_tick)

    def add_line(self, text: str):
        self._lines.append(text)
        self._visible = True
        self._alpha   = 255
        self._fade_t.stop()
        self.update()

    def start_fade(self):
        self._fade_t.start(18)

    def _fade_tick(self):
        self._alpha = max(0, self._alpha - 5)
        self.update()
        if self._alpha <= 0:
            self._fade_t.stop()
            self._visible = False
            self.hide()

    def paintEvent(self, event):
        if not self._visible:
            return
        w, h = self.width(), self.height()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Solid dark backdrop
        p.fillRect(self.rect(), QColor(3, 5, 10, min(240, self._alpha)))

        # Title
        p.setFont(QFont("Segoe UI", 26, QFont.Weight.Light))
        p.setPen(QColor(0, 175, 215, self._alpha))
        p.drawText(
            QRectF(0, h * 0.20, w, 56),
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
            "J.A.R.V.I.S."
        )
        p.setFont(QFont("Consolas", 9))
        p.setPen(QColor(22, 36, 48, self._alpha))
        p.drawText(
            QRectF(0, h * 0.20 + 46, w, 20),
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
            "JUST A RATHER VERY INTELLIGENT SYSTEM"
        )

        # Boot lines
        p.setFont(QFont("Consolas", 10))
        sy, lh = h * 0.42, 21
        for i, line in enumerate(self._lines[-8:]):
            last  = i == len(self._lines[-8:]) - 1
            color = QColor(0, 175, 215, self._alpha) if last else QColor(30, 90, 70, self._alpha)
            p.setPen(color)
            prefix = "▸  " if last else "✓  "
            p.drawText(
                QRectF(w * 0.20, sy + i * lh, w * 0.60, lh),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                prefix + line
            )

        # Progress bar
        by, bw_full = h * 0.76, w * 0.50
        bx  = (w - bw_full) / 2
        prog = min(1.0, len(self._lines) / 6.0)
        p.setPen(QPen(QColor(0, 175, 215, self._alpha // 3), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(QRectF(bx, by, bw_full, 2), 1, 1)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(QColor(0, 175, 215, self._alpha)))
        p.drawRoundedRect(QRectF(bx, by, bw_full * prog, 2), 1, 1)

        p.end()


# ─────────────────────────────────────────────────────────────────────────────
# MAIN WINDOW
# ─────────────────────────────────────────────────────────────────────────────
class JarvisUI(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("J.A.R.V.I.S.")
        self.resize(960, 720)
        self.setMinimumSize(700, 520)
        self.setStyleSheet(_STYLE)

        root = QVBoxLayout(self)
        root.setContentsMargins(32, 24, 32, 24)
        root.setSpacing(0)

        # ── Header ──────────────────────────────────────────────────────────
        hdr = QHBoxLayout()
        hdr.setContentsMargins(0, 0, 0, 0)

        name = QLabel("J.A.R.V.I.S.")
        name.setStyleSheet(
            "color: rgba(0,175,215,0.85); font-size: 13px; font-weight: 600;"
            "letter-spacing: 5px; font-family: 'Consolas', monospace;"
        )
        self.status_label = QLabel("BOOT")
        self.status_label.setStyleSheet(
            f"color: {_STATE_HEX['BOOT']}; font-size: 9px; letter-spacing: 3px;"
            "font-family: 'Consolas', monospace;"
        )
        hdr.addWidget(name)
        hdr.addStretch()
        hdr.addWidget(self.status_label)
        root.addLayout(hdr)

        root.addSpacing(8)

        # ── Breathing orb ────────────────────────────────────────────────────
        self.orb = BreathingOrbWidget()
        root.addWidget(self.orb, stretch=3)

        # ── State label ──────────────────────────────────────────────────────
        self.state_lbl = QLabel("INITIALIZING")
        self.state_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.state_lbl.setStyleSheet(
            f"color: {_STATE_HEX['BOOT']}; font-size: 9px; letter-spacing: 4px;"
            "font-family: 'Consolas', monospace; margin-top: 6px;"
        )
        root.addWidget(self.state_lbl)

        root.addSpacing(10)

        # ── Waveform ─────────────────────────────────────────────────────────
        self.waveform = WaveformWidget()
        root.addWidget(self.waveform)

        root.addSpacing(18)

        # ── Divider ──────────────────────────────────────────────────────────
        div = QFrame()
        div.setFrameShape(QFrame.Shape.HLine)
        div.setStyleSheet("border: none; border-top: 1px solid rgba(0,175,215,0.06);")
        root.addWidget(div)

        root.addSpacing(14)

        # ── Chat log ─────────────────────────────────────────────────────────
        self.chat_log = QTextEdit()
        self.chat_log.setObjectName("ChatLog")
        self.chat_log.setReadOnly(True)
        self.chat_log.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.chat_log.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        root.addWidget(self.chat_log, stretch=4)

        # ── Vision panel (optional) ──────────────────────────────────────────
        self._build_vision(root)

        # ── Boot overlay ─────────────────────────────────────────────────────
        self._boot_overlay = BootOverlayWidget(self)
        self._boot_overlay.raise_()
        self._boot_overlay.setGeometry(self.rect())
        self._boot_overlay.show()

        self._wire_backend()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._boot_overlay.setGeometry(self.rect())

    # ── Vision ───────────────────────────────────────────────────────────────
    def _build_vision(self, root: QVBoxLayout):
        try:
            on_request, vcfg    = build_vision_on_request()
            self._vision_on_request = on_request
            self.vision_panel       = VisionPanel(
                on_request=on_request,
                camera_index=vcfg.get("camera_index", 0)
            )
            root.addSpacing(12)
            root.addWidget(self.vision_panel)
        except Exception:
            self.vision_panel = None

    # ── Backend wiring ────────────────────────────────────────────────────────
    def _wire_backend(self):
        try:
            self.jarvis = EnhancedJarvis(greet_on_start=True)
        except Exception as exc:
            self._append_message("System", f"Backend failed: {exc}", is_jarvis=False)
            self.jarvis = None
            return

        def on_boot_line(line: str):
            QTimer.singleShot(0, lambda l=line: self._boot_overlay.add_line(l))
        self.jarvis.set_boot_line_callback(on_boot_line)

        def _maybe_dismiss(state: str):
            if state == "IDLE" and self._boot_overlay.isVisible():
                QTimer.singleShot(1000, self._boot_overlay.start_fade)

        def ui_notifier(event: str):
            state_map = {
                "speaking_start": "SPEAKING",
                "speaking_end":   "IDLE",
                "listening":      "LISTENING",
                "thinking":       "THINKING",
            }
            state = state_map.get(event)
            if state:
                QTimer.singleShot(0, lambda s=state: self._set_state(s))
                QTimer.singleShot(0, lambda s=state: _maybe_dismiss(s))
            if event == "speaking_start":
                QTimer.singleShot(0, lambda: self.waveform.set_live(True))
            elif event == "speaking_end":
                QTimer.singleShot(0, lambda: self.waveform.set_live(False))

        self.jarvis.set_ui_notifier(ui_notifier)
        self.jarvis.set_user_message_callback(
            lambda text: self._append_message("you", text, is_jarvis=False)
        )

        orig_speak = self.jarvis.speak

        def speak_with_ui(text: str):
            self._append_message("jarvis", text, is_jarvis=True)
            orig_speak(text)

        self.jarvis.speak = speak_with_ui

        if self.vision_panel is not None:
            try:
                self.jarvis.vision_request = self._vision_on_request
                self.jarvis.attach_vision(self.vision_panel)
            except Exception as exc:
                print(f"[gui] Vision attachment failed: {exc}")

        threading.Thread(target=self.jarvis.run, daemon=True, name="jarvis-main").start()

    # ── State update ──────────────────────────────────────────────────────────
    def _set_state(self, state: str):
        self.orb.set_state(state)
        self.waveform.set_color(_STATE_COLORS.get(state, _STATE_COLORS["IDLE"]))
        hex_c = _STATE_HEX.get(state, _STATE_HEX["IDLE"])
        self.state_lbl.setText(state)
        self.state_lbl.setStyleSheet(
            f"color: {hex_c}; font-size: 9px; letter-spacing: 4px;"
            "font-family: 'Consolas', monospace; margin-top: 6px;"
        )
        self.status_label.setText(state)
        self.status_label.setStyleSheet(
            f"color: {hex_c}; font-size: 9px; letter-spacing: 3px;"
            "font-family: 'Consolas', monospace;"
        )

    # ── Chat log ──────────────────────────────────────────────────────────────
    def _append_message(self, sender: str, text: str, is_jarvis: bool = True):
        from datetime import datetime
        ts    = datetime.now().strftime("%H:%M")
        color = "#00afd7" if is_jarvis else "#00d278"
        align = "left"   if is_jarvis else "right"
        html  = (
            f'<div style="margin-bottom:14px; text-align:{align};">'
            f'<span style="color:{color}; font-size:8px; letter-spacing:2px;'
            f' font-family:Consolas,monospace; font-weight:600;">{sender.upper()}</span>'
            f'<span style="color:rgba(22,36,48,0.9); font-size:8px; margin-left:7px;'
            f' font-family:Consolas,monospace;">{ts}</span><br>'
            f'<span style="color:{"#9ab8c8" if is_jarvis else "#88c8a0"};'
            f' font-size:13px; line-height:1.85; display:inline-block; margin-top:3px;">'
            f'{text}</span>'
            f'</div>'
        )

        def _do():
            self.chat_log.append(html)
            self.chat_log.verticalScrollBar().setValue(
                self.chat_log.verticalScrollBar().maximum()
            )
        QTimer.singleShot(0, _do)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = JarvisUI()
    window.show()
    sys.exit(app.exec())
