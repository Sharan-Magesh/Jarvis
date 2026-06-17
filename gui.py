# gui.py — J.A.R.V.I.S. Cinematic HUD
# Full PyQt6 rebuild: hex grid background, arc reactor, waveform,
# boot overlay, system metrics, corner brackets, Iron Man palette.
import math
import random
import threading
import time
import sys

from jarvis_main import EnhancedJarvis

from PyQt6.QtWidgets import (
    QApplication, QWidget, QLabel, QVBoxLayout, QHBoxLayout, QFrame,
    QSizePolicy, QTextEdit, QPushButton, QGraphicsOpacityEffect,
)
from PyQt6.QtGui import (
    QPainter, QColor, QBrush, QPen, QLinearGradient, QRadialGradient,
    QPainterPath, QFont, QFontMetrics,
)
from PyQt6.QtCore import Qt, QTimer, QRectF, QPointF, QPropertyAnimation, QEasingCurve

from ui.vision_panel import VisionPanel
from integrations.vision_wiring import build_vision_on_request

# ─────────────────────────────────────────────────────────────────────────────
# PALETTE
# ─────────────────────────────────────────────────────────────────────────────
_BG        = "#050810"
_CARD      = "#080d14"
_BORDER    = "rgba(0,212,255,0.08)"
_TEXT      = "#b8d8e8"
_MUTED     = "#1e3a46"
_ACCENT    = QColor(0, 212, 255)
_ACCENT2   = QColor(0, 180, 255)

_BADGE_STATES = {
    "IDLE":      ("#00d4ff", "rgba(0,212,255,0.08)"),
    "LISTENING": ("#00ff9d", "rgba(0,255,157,0.08)"),
    "THINKING":  ("#ffd700", "rgba(255,215,0,0.08)"),
    "SPEAKING":  ("#e879f9", "rgba(232,121,249,0.08)"),
    "BOOT":      ("#ff6b35", "rgba(255,107,53,0.08)"),
}
_REACTOR_COLORS = {
    "IDLE":      QColor(0,  212, 255),
    "LISTENING": QColor(0,  255, 157),
    "THINKING":  QColor(255,215,   0),
    "SPEAKING":  QColor(232,121, 249),
    "BOOT":      QColor(255,107,  53),
}

_STYLE = f"""
QWidget {{
    background-color: {_BG};
    color: {_TEXT};
    font-family: 'Segoe UI', 'Inter', Arial, sans-serif;
    font-size: 13px;
}}
QFrame#Card {{
    background: {_CARD};
    border: 1px solid {_BORDER};
    border-radius: 12px;
}}
QTextEdit#ChatLog {{
    background: transparent;
    border: none;
    color: {_TEXT};
    font-size: 13px;
    padding: 2px 4px;
    selection-background-color: rgba(0,212,255,0.15);
}}
QScrollBar:vertical {{
    background: transparent; width: 3px; margin: 0; border: none;
}}
QScrollBar::handle:vertical {{
    background: rgba(0,212,255,0.18);
    border-radius: 2px; min-height: 28px;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
"""


# ─────────────────────────────────────────────────────────────────────────────
# HEX GRID BACKGROUND
# ─────────────────────────────────────────────────────────────────────────────
class HexGridWidget(QWidget):
    """Animated honeycomb background — subtle pulse, no CPU hog."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAutoFillBackground(False)
        self._phase   = 0.0
        self._timer   = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(60)   # ~16 FPS — plenty for a subtle grid

    def _tick(self):
        self._phase = (self._phase + 0.018) % (2 * math.pi)
        self.update()

    def paintEvent(self, event):
        w, h = self.width(), self.height()
        if w <= 0 or h <= 0:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        size   = 28          # hex "radius" (center to vertex)
        col_w  = size * 1.732
        row_h  = size * 1.5
        cols   = int(w / col_w) + 3
        rows   = int(h / row_h) + 3

        for row in range(-1, rows + 1):
            for col in range(-1, cols + 1):
                cx = col * col_w + (size * 0.866 if row % 2 else 0)
                cy = row * row_h

                dist   = math.sqrt((cx - w * 0.5) ** 2 + (cy - h * 0.5) ** 2)
                wave   = math.sin(self._phase - dist * 0.012) * 0.5 + 0.5
                alpha  = int(8 + wave * 12)   # 8–20 — very subtle

                pen = QPen(QColor(0, 212, 255, alpha), 0.8)
                p.setPen(pen)
                p.setBrush(Qt.BrushStyle.NoBrush)

                path = QPainterPath()
                for i in range(6):
                    ang = math.radians(60 * i - 30)
                    px  = cx + size * math.cos(ang)
                    py  = cy + size * math.sin(ang)
                    path.moveTo(px, py) if i == 0 else path.lineTo(px, py)
                path.closeSubpath()
                p.drawPath(path)

        p.end()


# ─────────────────────────────────────────────────────────────────────────────
# SCANLINE OVERLAY
# ─────────────────────────────────────────────────────────────────────────────
class ScanlineWidget(QWidget):
    """Subtle moving horizontal scanline — classic sci-fi HUD effect."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAutoFillBackground(False)
        self._y = 0.0
        t = QTimer(self)
        t.timeout.connect(self._tick)
        t.start(16)

    def _tick(self):
        self._y = (self._y + 1.4) % (self.height() + 60)
        self.update()

    def paintEvent(self, event):
        w, h = self.width(), self.height()
        if w <= 0 or h <= 0:
            return
        p = QPainter(self)
        # Horizontal scan band
        grad = QLinearGradient(0, self._y - 40, 0, self._y + 40)
        grad.setColorAt(0.0, QColor(0, 212, 255, 0))
        grad.setColorAt(0.45, QColor(0, 212, 255, 7))
        grad.setColorAt(0.5,  QColor(0, 212, 255, 12))
        grad.setColorAt(0.55, QColor(0, 212, 255, 7))
        grad.setColorAt(1.0, QColor(0, 212, 255, 0))
        p.fillRect(0, int(self._y) - 40, w, 80, QBrush(grad))
        # Fine horizontal lines for CRT texture
        p.setPen(QPen(QColor(0, 212, 255, 3), 1))
        for y in range(0, h, 3):
            p.drawLine(0, y, w, y)
        p.end()


# ─────────────────────────────────────────────────────────────────────────────
# CORNER BRACKET DECORATION
# ─────────────────────────────────────────────────────────────────────────────
class CornerBracketsWidget(QWidget):
    """Draws Iron Man HUD-style corner brackets over the window."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAutoFillBackground(False)
        self._phase = 0.0
        t = QTimer(self)
        t.timeout.connect(self._tick)
        t.start(40)

    def _tick(self):
        self._phase = (self._phase + 0.04) % (2 * math.pi)
        self.update()

    def paintEvent(self, event):
        w, h = self.width(), self.height()
        if w <= 0 or h <= 0:
            return
        p   = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        alpha = int(160 + math.sin(self._phase) * 60)
        pen   = QPen(QColor(0, 212, 255, alpha), 2)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        sz, gap = 28, 8
        corners = [
            (gap, gap),           # top-left
            (w - gap - sz, gap),  # top-right
            (gap, h - gap - sz),  # bottom-left
            (w - gap - sz, h - gap - sz),  # bottom-right
        ]
        for cx, cy in corners:
            # horizontal stroke
            p.drawLine(QPointF(cx, cy + sz * 0.4), QPointF(cx, cy))
            p.drawLine(QPointF(cx, cy), QPointF(cx + sz * 0.4, cy))
            # second corner (opposite direction)
            p.drawLine(QPointF(cx + sz, cy + sz * 0.6), QPointF(cx + sz, cy + sz))
            p.drawLine(QPointF(cx + sz, cy + sz), QPointF(cx + sz * 0.6, cy + sz))
        p.end()


# ─────────────────────────────────────────────────────────────────────────────
# BOOT OVERLAY
# ─────────────────────────────────────────────────────────────────────────────
class BootOverlayWidget(QWidget):
    """
    Full-window cinematic boot sequence overlay.
    Displays diagnostic lines one by one, then fades out.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAutoFillBackground(False)
        self._lines: list[str] = []
        self._alpha  = 255
        self._fading = False
        self._visible = True

        self._fade_timer = QTimer(self)
        self._fade_timer.timeout.connect(self._fade_tick)

    def add_line(self, text: str):
        self._lines.append(text)
        self._visible = True
        self._alpha   = 255
        self._fading  = False
        self._fade_timer.stop()
        self.update()

    def start_fade(self):
        self._fading = True
        self._fade_timer.start(20)

    def _fade_tick(self):
        self._alpha = max(0, self._alpha - 6)
        self.update()
        if self._alpha <= 0:
            self._fade_timer.stop()
            self._visible = False
            self.hide()

    def paintEvent(self, event):
        if not self._visible or not self._lines:
            return
        w, h = self.width(), self.height()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Dark semi-transparent background
        p.fillRect(self.rect(), QColor(6, 10, 14, min(220, self._alpha)))

        # JARVIS title
        title_font = QFont("Segoe UI", 28, QFont.Weight.Bold)
        p.setFont(title_font)
        p.setPen(QColor(0, 212, 255, self._alpha))
        p.drawText(
            QRectF(0, h * 0.22, w, 60),
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
            "J.A.R.V.I.S."
        )

        sub_font = QFont("Segoe UI", 10)
        p.setFont(sub_font)
        p.setPen(QColor(46, 74, 85, self._alpha))
        p.drawText(
            QRectF(0, h * 0.22 + 50, w, 24),
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
            "JUST A RATHER VERY INTELLIGENT SYSTEM"
        )

        # Diagnostic lines
        line_font = QFont("Consolas", 11)
        p.setFont(line_font)
        start_y  = h * 0.42
        line_h   = 22
        for i, line in enumerate(self._lines[-12:]):
            is_last = (i == len(self._lines[-12:]) - 1)
            color   = QColor(0, 212, 255, self._alpha) if is_last else \
                      QColor(46, 120, 100, self._alpha)
            p.setPen(color)
            prefix = "▶  " if is_last else "✓  "
            p.drawText(
                QRectF(w * 0.18, start_y + i * line_h, w * 0.65, line_h),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                prefix + line
            )

        # Progress bar
        bar_y   = h * 0.78
        bar_w   = w * 0.55
        bar_x   = (w - bar_w) / 2
        prog    = min(1.0, len(self._lines) / 6.0)
        p.setPen(QPen(QColor(0, 212, 255, self._alpha // 2), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(QRectF(bar_x, bar_y, bar_w, 4), 2, 2)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(QColor(0, 212, 255, self._alpha)))
        p.drawRoundedRect(QRectF(bar_x, bar_y, bar_w * prog, 4), 2, 2)

        p.end()


# ─────────────────────────────────────────────────────────────────────────────
# SYSTEM METRICS WIDGET
# ─────────────────────────────────────────────────────────────────────────────
class SystemMetricsWidget(QWidget):
    """Displays live clock, CPU%, RAM% — updates every 2 s."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(44)
        self._cpu   = 0.0
        self._ram   = 0.0
        self._clock = "--:--:--"
        self._uptime_start = time.time()

        t = QTimer(self)
        t.timeout.connect(self._refresh)
        t.start(2000)
        self._refresh()

    def _refresh(self):
        from datetime import datetime
        self._clock = datetime.now().strftime("%H:%M:%S")

        try:
            import psutil
            self._cpu = psutil.cpu_percent(interval=None)
            self._ram = psutil.virtual_memory().percent
        except ImportError:
            self._cpu = self._ram = 0.0
        self.update()

    def paintEvent(self, event):
        w, h = self.width(), self.height()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        elapsed = int(time.time() - self._uptime_start)
        hh, rem = divmod(elapsed, 3600)
        mm, ss  = divmod(rem, 60)
        uptime  = f"{hh:02d}:{mm:02d}:{ss:02d}"

        font = QFont("Consolas", 10)
        p.setFont(font)

        segments = [
            (f"⏱  {self._clock}",        QColor(0, 212, 255, 200)),
            (f"CPU  {self._cpu:4.1f}%",   QColor(0, 255, 157, 200)),
            (f"RAM  {self._ram:4.1f}%",   QColor(255, 215, 0, 200)),
            (f"UP   {uptime}",            QColor(200, 180, 255, 180)),
        ]

        seg_w = w / len(segments)
        for i, (text, color) in enumerate(segments):
            p.setPen(color)
            p.drawText(
                QRectF(i * seg_w, 0, seg_w, h),
                Qt.AlignmentFlag.AlignCenter,
                text
            )

        # Separator line
        p.setPen(QPen(QColor(0, 212, 255, 18), 1))
        p.drawLine(QPointF(0, h - 1), QPointF(w, h - 1))
        p.end()


# ─────────────────────────────────────────────────────────────────────────────
# ARC REACTOR (kept + enhanced)
# ─────────────────────────────────────────────────────────────────────────────
class ArcReactorWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._state_color = QColor(0, 212, 255)
        self._radius  = 42.0
        self._growing = True
        self._angle   = 0.0
        self._phase   = 0.0
        self._active  = False
        self._timer   = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(50)

    def set_state_color(self, color: QColor):
        self._state_color = color

    def set_active(self, active: bool):
        active = bool(active)
        if active == self._active:
            return
        self._active = active
        self._timer.start(16 if active else 50)

    def _tick(self):
        self._radius += 0.4 if self._growing else -0.4
        if   self._radius >= 54: self._growing = False
        elif self._radius <= 42: self._growing = True
        self._angle = (self._angle + 2.0) % 360
        self._phase = (self._phase + 0.04) % (2 * math.pi)
        self.update()

    def paintEvent(self, event):
        w, h = self.width(), self.height()
        cx, cy = w / 2, h / 2
        r  = self._radius
        sc = self._state_color

        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Outer glow
        glow = QRadialGradient(QPointF(cx, cy), r * 2.4)
        glow.setColorAt(0.0, QColor(sc.red(), sc.green(), sc.blue(), 100))
        glow.setColorAt(0.5, QColor(sc.red(), sc.green(), sc.blue(), 30))
        glow.setColorAt(1.0, QColor(0, 0, 0, 0))
        p.setBrush(QBrush(glow))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QRectF(cx - r*2.4, cy - r*2.4, r*4.8, r*4.8))

        # Concentric rings
        for rad_mult, width, alpha in [(1.55, 5, 190), (1.30, 2.5, 150), (0.95, 1.5, 90)]:
            p.setPen(QPen(QColor(sc.red(), sc.green(), sc.blue(), alpha), width))
            p.setBrush(Qt.BrushStyle.NoBrush)
            pr = r * rad_mult
            p.drawEllipse(QRectF(cx - pr, cy - pr, pr * 2, pr * 2))

        # Rotating arc dashes
        p.save()
        p.translate(cx, cy)
        p.rotate(self._angle)
        p.setPen(QPen(QColor(sc.red(), sc.green(), sc.blue(), 200), 4))
        for i in range(5):
            p.drawArc(QRectF(-r*1.42, -r*1.42, r*2.84, r*2.84), i * 72 * 16, 16 * 16)
        p.restore()

        # Segmented outer ring
        segs = 36
        sweep = 360 / segs
        p.setPen(Qt.PenStyle.NoPen)
        s_outer = r * 1.15
        s_inner = s_outer - 12
        for i in range(segs):
            if i % 3 == 0:
                continue
            start_deg = i * sweep + self._angle * 0.18
            sg = QLinearGradient(0, cy - s_outer, 0, cy + s_outer)
            sg.setColorAt(0.0, QColor(sc.red(), sc.green(), sc.blue(), 200))
            sg.setColorAt(1.0, QColor(sc.red()//2, sc.green()//2, sc.blue()//2, 160))
            p.setBrush(QBrush(sg))
            path = QPainterPath()
            path.moveTo(cx + s_inner, cy)
            path.arcTo(QRectF(cx-s_inner, cy-s_inner, s_inner*2, s_inner*2),
                       -start_deg, -sweep*0.70)
            path.lineTo(cx + s_outer, cy)
            path.arcTo(QRectF(cx-s_outer, cy-s_outer, s_outer*2, s_outer*2),
                       -(start_deg+sweep*0.70), sweep*0.70)
            path.closeSubpath()
            p.drawPath(path)

        # Tick marks
        p.setPen(QPen(QColor(sc.red(), sc.green(), sc.blue(), 120), 1.5))
        for i in range(48):
            a  = (i / 48) * 2 * math.pi + self._phase * 0.5
            r1 = r * 1.35
            r2 = r * (1.50 if i % 4 == 0 else 1.43)
            p.drawLine(
                QPointF(cx + r1*math.cos(a), cy + r1*math.sin(a)),
                QPointF(cx + r2*math.cos(a), cy + r2*math.sin(a)),
            )

        # Orbit dots
        p.save()
        p.translate(cx, cy)
        p.rotate(-self._angle * 0.75)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(QColor(255, 215, 0, 210)))
        for i in range(6):
            a  = math.radians(i * 60)
            px = r * 0.96 * math.cos(a)
            py = r * 0.96 * math.sin(a)
            p.drawEllipse(QRectF(px-2.5, py-2.5, 5, 5))
        p.restore()

        # Hexagon
        p.setPen(QPen(QColor(sc.red(), sc.green(), sc.blue(), 130), 1.5))
        p.setBrush(Qt.BrushStyle.NoBrush)
        path = QPainterPath()
        for i in range(6):
            ang = math.radians(60*i - 30)
            x = cx + r*0.68*math.cos(ang)
            y = cy + r*0.68*math.sin(ang)
            path.moveTo(x, y) if i == 0 else path.lineTo(x, y)
        path.closeSubpath()
        p.drawPath(path)

        # Core glow
        core_r = r * (0.28 + 0.06 * abs(math.sin(self._phase)))
        core_r = max(core_r, 1.0)
        cg = QRadialGradient(QPointF(cx, cy), core_r)
        cg.setColorAt(0.0, QColor(255, 255, 255, 255))
        cg.setColorAt(0.55, QColor(sc.red(), sc.green(), sc.blue(), 220))
        cg.setColorAt(1.0,  QColor(0, 0, 0, 0))
        p.setBrush(QBrush(cg))
        p.setPen(QPen(QColor(sc.red(), sc.green(), sc.blue(), 110), 1.5))
        p.drawEllipse(QRectF(cx - core_r, cy - core_r, core_r*2, core_r*2))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(QColor(245, 255, 255, 255)))
        p.drawEllipse(QRectF(cx - core_r*0.30, cy - core_r*0.30, core_r*0.60, core_r*0.60))

        p.end()


# ─────────────────────────────────────────────────────────────────────────────
# VOICE WAVEFORM
# ─────────────────────────────────────────────────────────────────────────────
class VoiceWaveformWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAutoFillBackground(False)
        self.setStyleSheet("background: transparent;")
        self.amplitude  = 0.0
        self.phase      = 0.0
        self.is_speaking = False
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._animate)
        self._timer.start(16)

    def start_animation(self):
        self.is_speaking = True
        if not self._timer.isActive():
            self._timer.start(16)

    def stop_animation(self):
        self.is_speaking = False

    def _animate(self):
        if self.is_speaking:
            self.amplitude = min(1.0, self.amplitude + 0.06)
            self.phase    += 0.24
        else:
            self.amplitude = max(0.0, self.amplitude - 0.05)
            self.phase    += 0.07
        self.update()
        if not self.is_speaking and self.amplitude <= 0.001:
            self._timer.stop()

    def paintEvent(self, event):
        w, h = self.width(), self.height()
        if w <= 0 or h <= 0:
            return
        p   = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        mid = h / 2
        if self.amplitude < 0.01:
            p.setPen(QPen(QColor(0, 180, 220, 40), 1.5))
            p.drawLine(QPointF(10, mid), QPointF(w-10, mid))
            p.end()
            return
        bars  = 52
        bar_w = w / bars
        max_a = h * 0.44
        for i in range(bars):
            a = (
                math.sin(self.phase + i * 0.42) * 0.65
                + math.sin(self.phase * 1.5 + i * 0.85) * 0.25
                + math.sin(self.phase * 0.7 + i * 1.20) * 0.10
            ) * max_a * self.amplitude
            bar_h = max(abs(a), 2.0)
            x     = i * bar_w + bar_w / 2
            alpha = int(130 + 120 * self.amplitude)
            grad  = QLinearGradient(x, mid - bar_h, x, mid + bar_h)
            grad.setColorAt(0.0, QColor(0, 255, 200, alpha))
            grad.setColorAt(0.5, QColor(0, 180, 255, int(alpha*0.80)))
            grad.setColorAt(1.0, QColor(0, 255, 200, alpha))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(grad))
            p.drawRoundedRect(
                QRectF(x - bar_w*0.30, mid - bar_h, bar_w*0.60, bar_h*2), 2.0, 2.0
            )
        p.end()


# ─────────────────────────────────────────────────────────────────────────────
# MAIN WINDOW
# ─────────────────────────────────────────────────────────────────────────────
class JarvisUI(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("J.A.R.V.I.S — Just A Rather Very Intelligent System")
        self.resize(1200, 800)
        self.setMinimumSize(900, 600)
        self.setStyleSheet(_STYLE)

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(10)

        root.addWidget(self._build_header())
        root.addWidget(self._build_metrics())
        root.addLayout(self._build_main_row(), stretch=1)
        self._build_vision_section(root)

        # Hex grid sits behind everything
        self._hex = HexGridWidget(self)
        self._hex.lower()
        self._hex.setGeometry(self.rect())

        # Scanline overlay — above hex, below content
        self._scanline = ScanlineWidget(self)
        self._scanline.setGeometry(self.rect())
        self._scanline.raise_()

        # Corner brackets float on top
        self._brackets = CornerBracketsWidget(self)
        self._brackets.raise_()
        self._brackets.setGeometry(self.rect())

        # Boot overlay — full window, shown during startup
        self._boot_overlay = BootOverlayWidget(self)
        self._boot_overlay.raise_()
        self._boot_overlay.setGeometry(self.rect())
        self._boot_overlay.show()

        self._wire_backend()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        for w in (self._hex, self._scanline, self._brackets, self._boot_overlay):
            w.setGeometry(self.rect())

    # ── Header ────────────────────────────────────────────────────────────────
    def _build_header(self) -> QFrame:
        frame = QFrame(); frame.setObjectName("Card")
        frame.setFixedHeight(58)
        lay = QHBoxLayout(frame)
        lay.setContentsMargins(24, 0, 24, 0)
        lay.setSpacing(0)

        # Left: identity block
        title = QLabel("J.A.R.V.I.S")
        title.setStyleSheet(
            "font-size: 20px; font-weight: 700; letter-spacing: 6px; color: #00d4ff;"
            "font-family: 'Segoe UI', 'Courier New', monospace;"
        )
        title.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        sep = QLabel("  |  ")
        sep.setStyleSheet(f"color: {_MUTED}; font-size: 14px;")
        sep.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        subtitle = QLabel("JUST A RATHER VERY INTELLIGENT SYSTEM")
        subtitle.setStyleSheet(
            f"color: {_MUTED}; font-size: 9px; letter-spacing: 2px;"
        )
        subtitle.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        lay.addWidget(title)
        lay.addWidget(sep)
        lay.addWidget(subtitle)
        lay.addStretch()

        # Right: version tag + status badge
        ver = QLabel("v3.0")
        ver.setStyleSheet(f"color: {_MUTED}; font-size: 9px; letter-spacing: 1px; margin-right: 16px;")
        ver.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        self.status_badge = QLabel("BOOT")
        self.status_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_badge.setFixedSize(90, 24)
        self._apply_badge("BOOT")

        lay.addWidget(ver)
        lay.addWidget(self.status_badge)
        return frame

    def _apply_badge(self, state: str):
        color, bg = _BADGE_STATES.get(state, _BADGE_STATES["IDLE"])
        self.status_badge.setText(state)
        self.status_badge.setStyleSheet(f"""
            QLabel {{
                background: {bg};
                border: 1px solid {color};
                color: {color};
                border-radius: 4px;
                font-size: 9px; font-weight: 700; letter-spacing: 2.5px;
                font-family: 'Consolas', monospace;
            }}
        """)

    # ── System metrics bar ────────────────────────────────────────────────────
    def _build_metrics(self) -> QWidget:
        self.metrics = SystemMetricsWidget()
        return self.metrics

    # ── Main two-column row ───────────────────────────────────────────────────
    def _build_main_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(10)

        # Left panel: arc reactor + waveform
        left = QFrame(); left.setObjectName("Card")
        left.setFixedWidth(290)
        ll = QVBoxLayout(left)
        ll.setContentsMargins(20, 20, 20, 20)
        ll.setSpacing(14)

        self.arc_reactor = ArcReactorWidget()
        self.arc_reactor.setFixedSize(230, 230)
        ll.addWidget(self.arc_reactor, alignment=Qt.AlignmentFlag.AlignHCenter)

        self.state_label = QLabel("BOOT")
        self.state_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.state_label.setStyleSheet(
            "color: #ff6b35; font-size: 10px; letter-spacing: 3px; font-weight: 600;"
        )
        ll.addWidget(self.state_label)

        self.waveform = VoiceWaveformWidget()
        self.waveform.setFixedHeight(68)
        self.waveform.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        ll.addWidget(self.waveform)
        ll.addStretch()

        # Divider
        div = QFrame()
        div.setFrameShape(QFrame.Shape.HLine)
        div.setStyleSheet(f"border: none; border-top: 1px solid rgba(0,212,255,0.08);")
        ll.addWidget(div)

        # System status grid — two columns, tight
        status_data = [
            ("LLM",     "llama3.2:3b"),
            ("TTS",     "Edge Neural"),
            ("MEMORY",  "SQLite WAL"),
            ("VISION",  "LLaVA 13B"),
        ]
        for label, value in status_data:
            row_w = QHBoxLayout()
            row_w.setContentsMargins(0, 1, 0, 1)
            lbl = QLabel(label)
            lbl.setStyleSheet(
                "color: rgba(46,74,85,0.85); font-size: 8px; letter-spacing: 1.5px;"
                "font-family: 'Consolas', monospace;"
            )
            val = QLabel(value)
            val.setStyleSheet(
                "color: rgba(0,212,255,0.75); font-size: 8px; font-weight: 600;"
                "font-family: 'Consolas', monospace;"
            )
            row_w.addWidget(lbl)
            row_w.addStretch()
            row_w.addWidget(val)
            ll.addLayout(row_w)

        row.addWidget(left)

        # Right panel: conversation log
        right = QFrame(); right.setObjectName("Card")
        rl = QVBoxLayout(right)
        rl.setContentsMargins(22, 18, 22, 18)
        rl.setSpacing(10)

        conv_header = QHBoxLayout()
        self.conv_label = QLabel("CONVERSATION LOG")
        self.conv_label.setStyleSheet(
            "color: rgba(46,74,85,0.9); font-size: 9px; font-weight: 700;"
            "letter-spacing: 2.5px; font-family: 'Consolas', monospace;"
        )
        conv_header.addWidget(self.conv_label)
        conv_header.addStretch()
        dot_live = QLabel("● LIVE")
        dot_live.setStyleSheet(
            "color: rgba(0,255,157,0.6); font-size: 8px; letter-spacing: 1px;"
        )
        conv_header.addWidget(dot_live)
        rl.addLayout(conv_header)

        div = QFrame()
        div.setFrameShape(QFrame.Shape.HLine)
        div.setStyleSheet("border: none; border-top: 1px solid rgba(0,212,255,0.06);")
        rl.addWidget(div)

        self.chat_log = QTextEdit()
        self.chat_log.setObjectName("ChatLog")
        self.chat_log.setReadOnly(True)
        self.chat_log.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.chat_log.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        rl.addWidget(self.chat_log)

        row.addWidget(right, stretch=1)
        return row

    # ── Vision section ────────────────────────────────────────────────────────
    def _build_vision_section(self, root: QVBoxLayout):
        frame = QFrame(); frame.setObjectName("Card")
        fl    = QVBoxLayout(frame)
        fl.setContentsMargins(20, 16, 20, 16)
        fl.setSpacing(10)
        try:
            on_request, vcfg    = build_vision_on_request()
            self._vision_on_request = on_request
            self.vision_panel       = VisionPanel(
                on_request=on_request,
                camera_index=vcfg.get("camera_index", 0)
            )
            fl.addWidget(self.vision_panel)
        except Exception as exc:
            lbl = QLabel(f"Vision unavailable: {exc}")
            lbl.setStyleSheet(f"color: {_MUTED}; font-size: 12px;")
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            fl.addWidget(lbl)
            self.vision_panel = None
        root.addWidget(frame, stretch=0)

    # ── Backend wiring ────────────────────────────────────────────────────────
    def _wire_backend(self):
        try:
            self.jarvis = EnhancedJarvis(greet_on_start=True)
        except Exception as exc:
            self._append_message("System", f"Backend failed: {exc}", is_jarvis=False)
            self.jarvis = None
            return

        # Boot overlay line feed
        def on_boot_line(line: str):
            QTimer.singleShot(0, lambda l=line: self._boot_overlay.add_line(l))

        self.jarvis.set_boot_line_callback(on_boot_line)

        # Fade boot overlay out once IDLE
        def _maybe_dismiss_boot(state: str):
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
                QTimer.singleShot(0, lambda s=state: _maybe_dismiss_boot(s))
            if event == "speaking_start":
                QTimer.singleShot(0, self.waveform.start_animation)
            elif event == "speaking_end":
                QTimer.singleShot(0, self.waveform.stop_animation)

        self.jarvis.set_ui_notifier(ui_notifier)
        self.jarvis.set_user_message_callback(
            lambda text: self._append_message("You", text, is_jarvis=False)
        )

        orig_speak = self.jarvis.speak

        def speak_with_ui(text: str):
            self._append_message("Jarvis", text, is_jarvis=True)
            orig_speak(text)

        self.jarvis.speak = speak_with_ui

        if self.vision_panel is not None:
            try:
                self.jarvis.vision_request = self._vision_on_request
                self.jarvis.attach_vision(self.vision_panel)
            except Exception as exc:
                print(f"[gui] Vision attachment failed: {exc}")

        threading.Thread(target=self.jarvis.run, daemon=True, name="jarvis-main").start()

    # ── State / UI helpers ────────────────────────────────────────────────────
    def _set_state(self, state: str):
        self._apply_badge(state)
        color, _ = _BADGE_STATES.get(state, _BADGE_STATES["IDLE"])
        self.state_label.setText(state)
        self.state_label.setStyleSheet(
            f"color: {color}; font-size: 10px; letter-spacing: 3px; font-weight: 600;"
        )
        self.arc_reactor.set_state_color(_REACTOR_COLORS.get(state, _ACCENT))
        self.arc_reactor.set_active(state in ("LISTENING", "THINKING", "SPEAKING"))

    def _append_message(self, sender: str, text: str, is_jarvis: bool = True):
        from datetime import datetime
        ts         = datetime.now().strftime("%H:%M:%S")
        accent     = "#00d4ff" if is_jarvis else "#00ff9d"
        align      = "left"   if is_jarvis else "right"
        bar_color  = "rgba(0,212,255,0.35)" if is_jarvis else "rgba(0,255,157,0.35)"
        text_color = "#b8d8e8" if is_jarvis else "#d8f0d8"
        border_l   = f'border-left: 2px solid {bar_color};' if is_jarvis else ''
        border_r   = f'border-right: 2px solid {bar_color};' if not is_jarvis else ''
        pad_l      = "padding-left: 10px;" if is_jarvis else "padding-right: 10px;"
        html = (
            f'<div style="margin-bottom:16px;text-align:{align};">'
            f'<span style="color:{accent};font-weight:600;font-size:9px;letter-spacing:2px;'
            f'font-family:\'Consolas\',monospace;">{sender.upper()}</span>'
            f'<span style="color:rgba(46,74,85,0.7);font-size:8px;margin-left:8px;'
            f'font-family:\'Consolas\',monospace;">{ts}</span><br>'
            f'<span style="{border_l}{border_r}{pad_l}'
            f'color:{text_color};font-size:12.5px;line-height:1.8;display:inline-block;'
            f'margin-top:3px;max-width:92%;">'
            f'{text}</span></div>'
        )

        def _do():
            self.chat_log.append(html)
            sb = self.chat_log.verticalScrollBar()
            sb.setValue(sb.maximum())

        QTimer.singleShot(0, _do)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = JarvisUI()
    window.show()
    sys.exit(app.exec())
