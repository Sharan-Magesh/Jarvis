# gui.py — J.A.R.V.I.S. Glassmorphism HUD
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
    QPainter, QColor, QBrush, QPen, QLinearGradient, QRadialGradient,
    QPainterPath, QFont, QPalette,
)
from PyQt6.QtCore import Qt, QTimer, QRectF, QPointF

from ui.vision_panel import VisionPanel
from integrations.vision_wiring import build_vision_on_request

# ─────────────────────────────────────────────────────────────────────────────
# PALETTE
# ─────────────────────────────────────────────────────────────────────────────
_STATE_COLORS = {
    "IDLE":      QColor(0,   175, 215),
    "LISTENING": QColor(0,   210, 120),
    "THINKING":  QColor(210, 160,   0),
    "SPEAKING":  QColor(170,  70, 235),
    "BOOT":      QColor(215,  85,  35),
}
_STATE_HEX = {k: f"#{v.red():02x}{v.green():02x}{v.blue():02x}"
              for k, v in _STATE_COLORS.items()}

_STYLE = """
QLabel {
    background: transparent;
    color: #b0ccd8;
    font-family: 'Segoe UI', 'Inter', Arial, sans-serif;
    font-size: 13px;
}
QTextEdit#ChatLog {
    background: transparent;
    border: none;
    color: #b0ccd8;
    font-size: 13px;
    padding: 0 4px;
    selection-background-color: rgba(0,175,215,30);
}
QScrollBar:vertical {
    background: transparent; width: 2px; margin: 0; border: none;
}
QScrollBar::handle:vertical {
    background: rgba(0,175,215,30);
    border-radius: 1px; min-height: 20px;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
"""


# ─────────────────────────────────────────────────────────────────────────────
# GLASS CARD  — frosted-glass panel (simulated; PyQt6 has no backdrop-filter)
# ─────────────────────────────────────────────────────────────────────────────
class GlassCard(QWidget):
    """
    Semi-transparent dark panel with top-edge highlight and a subtle border.
    The illusion of glass comes from the high-contrast dark fill over the
    nearly-black background and the gradient highlight at the top edge.
    """

    def __init__(self, radius: int = 20, parent=None):
        super().__init__(parent)
        self._radius = radius
        self.setAutoFillBackground(False)

    def paintEvent(self, event):
        w, h = self.width(), self.height()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, w, h), self._radius, self._radius)

        # ── Glass fill ── dark navy, semi-transparent
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(QColor(10, 16, 28, 148)))
        p.drawPath(path)

        # ── Top highlight ── simulates light from above striking the glass
        hi = QLinearGradient(0, 0, 0, min(80, h))
        hi.setColorAt(0.0, QColor(255, 255, 255, 18))
        hi.setColorAt(1.0, QColor(255, 255, 255,  0))
        p.setBrush(QBrush(hi))
        p.drawPath(path)

        # ── Left-edge shimmer ── subtle secondary highlight
        lh = QLinearGradient(0, 0, min(28, w), 0)
        lh.setColorAt(0.0, QColor(255, 255, 255,  9))
        lh.setColorAt(1.0, QColor(255, 255, 255,  0))
        p.setBrush(QBrush(lh))
        p.drawPath(path)

        # ── Border ── 1px white outline, ~9% opacity
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(255, 255, 255, 22), 1.0))
        p.drawRoundedRect(
            QRectF(0.5, 0.5, w - 1.0, h - 1.0),
            max(0.0, self._radius - 0.5),
            max(0.0, self._radius - 0.5),
        )
        p.end()


# ─────────────────────────────────────────────────────────────────────────────
# ARC REACTOR  — central animated widget
# ─────────────────────────────────────────────────────────────────────────────
class ArcReactorWidget(QWidget):
    _SPEEDS = {
        "IDLE":      0.55,
        "LISTENING": 2.0,
        "THINKING":  3.2,
        "SPEAKING":  2.2,
        "BOOT":      1.1,
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAutoFillBackground(False)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self._angle = 0.0
        self._speed = self._SPEEDS["BOOT"]

        c = _STATE_COLORS["BOOT"]
        self._cr = float(c.red())
        self._cg = float(c.green())
        self._cb = float(c.blue())
        self._tr, self._tg, self._tb = self._cr, self._cg, self._cb

        t = QTimer(self)
        t.timeout.connect(self._tick)
        t.start(33)   # 30 fps

    def set_state(self, state: str):
        c = _STATE_COLORS.get(state, _STATE_COLORS["IDLE"])
        self._tr = float(c.red())
        self._tg = float(c.green())
        self._tb = float(c.blue())
        self._speed = self._SPEEDS.get(state, 1.0)

    def _tick(self):
        self._angle = (self._angle + self._speed) % 360.0
        lr = 0.05
        self._cr += (self._tr - self._cr) * lr
        self._cg += (self._tg - self._cg) * lr
        self._cb += (self._tb - self._cb) * lr
        self.update()

    def paintEvent(self, event):
        w, h   = self.width(), self.height()
        cx, cy = w / 2.0, h / 2.0
        R      = min(w, h) * 0.44

        r, g, b = int(self._cr), int(self._cg), int(self._cb)

        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        # 1. Ambient outer glow
        gr = R * 1.45
        glow = QRadialGradient(QPointF(cx, cy), gr)
        glow.setColorAt(0.0, QColor(r, g, b, 40))
        glow.setColorAt(0.5, QColor(r, g, b, 14))
        glow.setColorAt(1.0, QColor(0,  0, 0,  0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(glow))
        p.drawEllipse(QRectF(cx - gr, cy - gr, gr * 2, gr * 2))

        # 2. Concentric rings (4 rings, decreasing opacity inward)
        ring_specs = [
            (1.00, 55, 1.3),
            (0.78, 40, 1.0),
            (0.58, 30, 0.8),
            (0.38, 22, 0.7),
        ]
        for frac, alpha, lw in ring_specs:
            rr = R * frac
            p.setPen(QPen(QColor(r, g, b, alpha), lw))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QRectF(cx - rr, cy - rr, rr * 2, rr * 2))

        # 3. Outer rotating arc dashes (8 dashes, clockwise)
        p.setBrush(Qt.BrushStyle.NoBrush)
        for i in range(8):
            a_deg     = self._angle + i * 45.0
            brightness = math.cos(math.radians(i * 45)) * 0.5 + 0.5
            aa        = int(55 + 110 * brightness)
            p.setPen(QPen(QColor(r, g, b, aa), 1.8))
            p.drawArc(
                QRectF(cx - R, cy - R, R * 2, R * 2),
                int(a_deg * 16),
                int(20 * 16),
            )

        # 4. Inner counter-rotating arcs (6 dashes, 62% R)
        ir = R * 0.62
        for i in range(6):
            a_deg = -self._angle * 1.5 + i * 60.0
            pulse = math.sin(math.radians(i * 60 + self._angle)) * 0.5 + 0.5
            aa    = int(38 + 82 * pulse)
            p.setPen(QPen(QColor(r, g, b, aa), 1.3))
            p.drawArc(
                QRectF(cx - ir, cy - ir, ir * 2, ir * 2),
                int(a_deg * 16),
                int(24 * 16),
            )

        # 5. Hexagon (very slowly co-rotates at 6% speed)
        hex_r = R * 0.30
        path  = QPainterPath()
        pts   = [
            QPointF(
                cx + hex_r * math.cos(math.radians(i * 60 + 30 + self._angle * 0.06)),
                cy + hex_r * math.sin(math.radians(i * 60 + 30 + self._angle * 0.06)),
            )
            for i in range(6)
        ]
        path.moveTo(pts[0])
        for pt in pts[1:]:
            path.lineTo(pt)
        path.closeSubpath()
        p.setPen(QPen(QColor(r, g, b, 42), 1.0))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)

        # 6. Core radial glow
        pulse_v = math.sin(math.radians(self._angle * 0.8)) * 0.5 + 0.5
        core_r  = R * 0.22
        wb      = int(80 + 50 * pulse_v)
        core    = QRadialGradient(QPointF(cx, cy), core_r)
        core.setColorAt(0.0,  QColor(min(r + wb, 255), min(g + wb, 255), min(b + wb, 255),
                                     int(200 + 55 * pulse_v)))
        core.setColorAt(0.35, QColor(r, g, b, 160))
        core.setColorAt(0.75, QColor(r // 2, g // 2, b // 2, 50))
        core.setColorAt(1.0,  QColor(0, 0, 0, 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(core))
        p.drawEllipse(QRectF(cx - core_r * 1.3, cy - core_r * 1.3,
                             core_r * 2.6, core_r * 2.6))

        # 7. White center point
        dot_a = int(200 + 55 * pulse_v)
        p.setBrush(QBrush(QColor(255, 255, 255, dot_a)))
        p.drawEllipse(QRectF(cx - 3.0, cy - 3.0, 6.0, 6.0))

        p.end()


# ─────────────────────────────────────────────────────────────────────────────
# WAVEFORM  — thin bar waveform, visible only when speaking
# ─────────────────────────────────────────────────────────────────────────────
class WaveformWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAutoFillBackground(False)
        self.setFixedHeight(28)
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
        target    = 1.0 if self._live else 0.0
        self._amp  = self._amp + (target - self._amp) * 0.08
        self._phase += 0.30 if self._live else 0.04
        self.update()

    def paintEvent(self, event):
        w, h = self.width(), self.height()
        if w <= 0 or h <= 0:
            return
        p   = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        mid = h / 2.0
        r, g, b = self._color.red(), self._color.green(), self._color.blue()

        if self._amp < 0.01:
            p.setPen(QPen(QColor(r, g, b, 20), 1))
            p.drawLine(QPointF(20, mid), QPointF(w - 20, mid))
            p.end()
            return

        bars = 44
        bw   = (w - 40.0) / bars
        p.setPen(Qt.PenStyle.NoPen)
        for i in range(bars):
            val = (
                math.sin(self._phase + i * 0.40) * 0.60
                + math.sin(self._phase * 1.35 + i * 0.80) * 0.30
                + math.sin(self._phase * 0.65 + i * 1.10) * 0.10
            )
            bh = max(abs(val) * (h * 0.42) * self._amp, 1.0)
            x  = 20 + i * bw + bw / 2
            aa = int(85 + 100 * self._amp)
            p.setBrush(QBrush(QColor(r, g, b, aa)))
            p.drawRoundedRect(
                QRectF(x - bw * 0.28, mid - bh, bw * 0.56, bh * 2), 1.2, 1.2
            )
        p.end()


# ─────────────────────────────────────────────────────────────────────────────
# BOOT OVERLAY  — full-screen loading screen with pulsing rings
# ─────────────────────────────────────────────────────────────────────────────
class BootOverlayWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAutoFillBackground(False)
        self._lines:   list[str] = []
        self._alpha  = 255
        self._visible = True
        self._phase  = 0.0

        # Ring animation timer
        self._anim_t = QTimer(self)
        self._anim_t.timeout.connect(self._anim_tick)
        self._anim_t.start(33)

        # Fade-out timer
        self._fade_t = QTimer(self)
        self._fade_t.timeout.connect(self._fade_tick)

    def _anim_tick(self):
        self._phase = (self._phase + 0.05) % (2 * math.pi)
        if self._visible:
            self.update()

    def add_line(self, text: str):
        self._lines.append(text)
        self._visible = True
        self._alpha   = 255
        self._fade_t.stop()
        self.update()

    def start_fade(self):
        self._fade_t.start(16)

    def _fade_tick(self):
        self._alpha = max(0, self._alpha - 4)
        self.update()
        if self._alpha <= 0:
            self._fade_t.stop()
            self._anim_t.stop()
            self._visible = False
            self.hide()

    def paintEvent(self, event):
        if not self._visible:
            return
        w, h = self.width(), self.height()
        cx   = w / 2.0
        a    = self._alpha

        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        # ── Background ──
        p.fillRect(self.rect(), QColor(3, 5, 8, min(252, a)))

        # ── Pulsing concentric rings at 28% height ──
        ry = h * 0.28
        for i, ring_r in enumerate([46, 68, 90]):
            pulse = math.sin(self._phase + i * 0.95) * 0.5 + 0.5
            ra    = int((28 + 88 * pulse) * a / 255)
            lw    = 1.5 - i * 0.18
            p.setPen(QPen(QColor(0, 175, 215, ra), lw))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QRectF(cx - ring_r, ry - ring_r, ring_r * 2, ring_r * 2))

        # ── Pulsing center dot ──
        cp = math.sin(self._phase * 2.1) * 0.5 + 0.5
        ca = int((150 + 105 * cp) * a / 255)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(QColor(0, 175, 215, ca)))
        p.drawEllipse(QRectF(cx - 4, ry - 4, 8, 8))

        # ── Title ──
        ty = h * 0.46
        p.setFont(QFont("Segoe UI", 30, QFont.Weight.Thin))
        p.setPen(QColor(0, 175, 215, a))
        p.drawText(
            QRectF(0, ty, w, 54),
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
            "J.A.R.V.I.S.",
        )

        # ── Subtitle ──
        p.setFont(QFont("Consolas", 8))
        p.setPen(QColor(26, 50, 60, a))
        p.drawText(
            QRectF(0, ty + 52, w, 18),
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
            "JUST A RATHER VERY INTELLIGENT SYSTEM",
        )

        # ── Boot diagnostic lines ──
        p.setFont(QFont("Consolas", 10))
        ly, lh = h * 0.66, 20
        shown  = self._lines[-6:]
        for i, line in enumerate(shown):
            last   = (i == len(shown) - 1)
            color  = QColor(0, 175, 215, a) if last else QColor(28, 75, 55, a)
            prefix = "▸  " if last else "✓  "
            p.setPen(color)
            p.drawText(
                QRectF(w * 0.14, ly + i * lh, w * 0.72, lh),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                prefix + line,
            )

        # ── Progress bar ──
        py = h * 0.87
        bw = w * 0.46
        bx = (w - bw) / 2.0
        prog = min(1.0, len(self._lines) / 6.0)

        p.setPen(QPen(QColor(0, 175, 215, int(a * 0.15)), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(QRectF(bx, py, bw, 2), 1, 1)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(QColor(0, 175, 215, a)))
        p.drawRoundedRect(QRectF(bx, py, bw * prog, 2), 1, 1)

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
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(10)

        self._build_header(root)
        self._build_main_card(root)
        self._build_vision(root)

        # Boot overlay — raised above all children
        self._boot_overlay = BootOverlayWidget(self)
        self._boot_overlay.raise_()
        self._boot_overlay.setGeometry(self.rect())
        self._boot_overlay.show()

        self._wire_backend()

    # ── Background ────────────────────────────────────────────────────────────
    def paintEvent(self, event):
        w, h = self.width(), self.height()
        p    = QPainter(self)

        # Near-black base
        p.fillRect(self.rect(), QColor(3, 5, 8))

        # Subtle blue-ish radial glow at centre (adds depth behind glass cards)
        glow = QRadialGradient(QPointF(w / 2.0, h / 2.0), max(w, h) * 0.58)
        glow.setColorAt(0.0, QColor(0, 80, 140, 16))
        glow.setColorAt(0.5, QColor(0, 40, 80,   7))
        glow.setColorAt(1.0, QColor(0,  0,  0,   0))
        p.fillRect(self.rect(), QBrush(glow))
        p.end()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._boot_overlay.setGeometry(self.rect())

    # ── Header glass pill ────────────────────────────────────────────────────
    def _build_header(self, root: QVBoxLayout):
        hdr = GlassCard(radius=12)
        hdr.setFixedHeight(46)

        lay = QHBoxLayout(hdr)
        lay.setContentsMargins(18, 0, 18, 0)
        lay.setSpacing(0)

        name_lbl = QLabel("J.A.R.V.I.S.")
        name_lbl.setStyleSheet(
            "color: rgba(0,175,215,220); font-size: 12px; font-weight: 600;"
            "letter-spacing: 5px; font-family: 'Consolas', monospace;"
        )

        self.status_label = QLabel("BOOT")
        self.status_label.setStyleSheet(
            f"color: {_STATE_HEX['BOOT']}; font-size: 9px; letter-spacing: 3px;"
            "font-family: 'Consolas', monospace;"
        )

        lay.addWidget(name_lbl)
        lay.addStretch()
        lay.addWidget(self.status_label)
        root.addWidget(hdr)

    # ── Main glass card ──────────────────────────────────────────────────────
    def _build_main_card(self, root: QVBoxLayout):
        card = GlassCard(radius=20)

        lay = QVBoxLayout(card)
        lay.setContentsMargins(28, 22, 28, 22)
        lay.setSpacing(0)

        # Arc reactor — horizontally centered, fixed size
        self.reactor = ArcReactorWidget()
        self.reactor.setFixedSize(220, 220)
        row = QHBoxLayout()
        row.addStretch()
        row.addWidget(self.reactor)
        row.addStretch()
        lay.addLayout(row)

        lay.addSpacing(12)

        # State label
        self.state_lbl = QLabel("INITIALIZING")
        self.state_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.state_lbl.setStyleSheet(
            f"color: {_STATE_HEX['BOOT']}; font-size: 9px; letter-spacing: 4px;"
            "font-family: 'Consolas', monospace;"
        )
        lay.addWidget(self.state_lbl)

        lay.addSpacing(8)

        # Waveform
        self.waveform = WaveformWidget()
        lay.addWidget(self.waveform)

        lay.addSpacing(18)

        # Divider
        div = QFrame()
        div.setFrameShape(QFrame.Shape.HLine)
        div.setStyleSheet("border: none; border-top: 1px solid rgba(0,175,215,35);")
        lay.addWidget(div)

        lay.addSpacing(12)

        # Chat log
        self.chat_log = QTextEdit()
        self.chat_log.setObjectName("ChatLog")
        self.chat_log.setReadOnly(True)
        self.chat_log.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.chat_log.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        lay.addWidget(self.chat_log, stretch=1)

        root.addWidget(card, stretch=1)

    # ── Vision panel (optional) ───────────────────────────────────────────────
    def _build_vision(self, root: QVBoxLayout):
        try:
            on_request, vcfg        = build_vision_on_request()
            self._vision_on_request = on_request
            self.vision_panel       = VisionPanel(
                on_request=on_request,
                camera_index=vcfg.get("camera_index", 0),
            )
            root.addSpacing(10)
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
                QTimer.singleShot(1200, self._boot_overlay.start_fade)

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

        threading.Thread(
            target=self.jarvis.run, daemon=True, name="jarvis-main"
        ).start()

    # ── State update ──────────────────────────────────────────────────────────
    def _set_state(self, state: str):
        self.reactor.set_state(state)
        self.waveform.set_color(_STATE_COLORS.get(state, _STATE_COLORS["IDLE"]))
        hex_c = _STATE_HEX.get(state, _STATE_HEX["IDLE"])
        self.state_lbl.setText(state)
        self.state_lbl.setStyleSheet(
            f"color: {hex_c}; font-size: 9px; letter-spacing: 4px;"
            "font-family: 'Consolas', monospace;"
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
            f'<span style="color:rgba(26,50,60,0.9); font-size:8px; margin-left:7px;'
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

    # Set dark palette to prevent white flash before the first paintEvent
    pal = app.palette()
    pal.setColor(QPalette.ColorRole.Window,     QColor(3, 5, 8))
    pal.setColor(QPalette.ColorRole.Base,       QColor(3, 5, 8))
    pal.setColor(QPalette.ColorRole.WindowText, QColor(176, 204, 216))
    pal.setColor(QPalette.ColorRole.Text,       QColor(176, 204, 216))
    app.setPalette(pal)

    window = JarvisUI()
    window.show()
    sys.exit(app.exec())
