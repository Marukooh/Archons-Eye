"""Main application window."""

import asyncio
import logging
import os
import random
import time
from datetime import datetime

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QSplitter,
    QGroupBox, QCheckBox, QSpinBox,
    QFormLayout, QGraphicsDropShadowEffect,
)
from PySide6.QtCore import Qt, QTimer, Signal, QObject, QRect, QSize
from PySide6.QtGui import QPainter, QFont, QFontMetrics, QColor, QPixmap

from archons_eye.config import config
from archons_eye.gui.system_table import SystemTable

log = logging.getLogger(__name__)

_TITLE_FONT = QFont("Agency FB", 28, QFont.Weight.Bold)
_TITLE_FONT.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 5)


class GlitchTitleWidget(QWidget):
    """Animated title: crimson text, chromatic aberration, random glitch slices."""

    def __init__(self, text: str, parent=None) -> None:
        super().__init__(parent)
        self._text = text
        self._slices: list[tuple[int, int, int, int]] = []
        self._rng = random.Random()

        fm = QFontMetrics(_TITLE_FONT)
        self.setFixedHeight(fm.height() + 18)
        self.setMinimumWidth(fm.horizontalAdvance(text) + 8)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        glow = QGraphicsDropShadowEffect(self)
        glow.setColor(QColor(192, 18, 0, 210))
        glow.setBlurRadius(22)
        glow.setOffset(0, 0)
        self.setGraphicsEffect(glow)

        timer = QTimer(self)
        timer.timeout.connect(self._tick)
        timer.start(130)

    def _tick(self) -> None:
        self._slices = []
        if self._rng.random() < 0.28:
            for _ in range(self._rng.randint(1, 3)):
                y   = self._rng.randint(0, max(1, self.height() - 6))
                sh  = self._rng.randint(3, 9)
                dx  = self._rng.choice([-8, -5, -4, 4, 5, 8])
                alp = self._rng.randint(130, 245)
                self._slices.append((y, sh, dx, alp))
        self.update()

    def sizeHint(self) -> QSize:
        fm = QFontMetrics(_TITLE_FONT)
        return QSize(fm.horizontalAdvance(self._text) + 16, fm.height() + 18)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        fm = QFontMetrics(_TITLE_FONT)
        text_w = fm.horizontalAdvance(self._text)
        text_x = max(0, (self.width() - text_w) // 2)
        baseline = fm.ascent() + 6
        painter.setFont(_TITLE_FONT)

        # Chromatic aberration ghost layers
        painter.setPen(QColor(0, 160, 180, 48))
        painter.drawText(text_x - 4, baseline, self._text)
        painter.setPen(QColor(192, 15, 0, 48))
        painter.drawText(text_x + 4, baseline, self._text)

        # Core text
        painter.setPen(QColor("#c41500"))
        painter.drawText(text_x, baseline, self._text)

        # Glitch slices — horizontal bands redrawn at a lateral offset
        for y, sh, dx, alp in self._slices:
            painter.save()
            painter.setClipRect(QRect(0, y, self.width(), sh))
            painter.setPen(QColor(210, 28, 0, alp))
            painter.drawText(text_x + dx, baseline, self._text)
            painter.restore()

        painter.end()


_TABLE_REFRESH_MS  = 500
_STATUS_REFRESH_MS = 500

_BADGE_LIVE    = "● LIVE"
_BADGE_OFFLINE = "● OFFLINE"
_OBJ_LIVE      = "live_badge"
_OBJ_OFFLINE   = "offline_badge"

_CMDR_FONT = QFont("Consolas", 11, QFont.Weight.Bold)
_CMDR_FONT.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 2)
_CMDR_FONT_SMALL = QFont("Consolas", 9)
_CMDR_FONT_SMALL.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1)


class CorruptedCmdrWidget(QWidget):
    """Displays CMDR name and current system with corrupted terminal glitch styling."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._cmdr   = ""
        self._system = ""
        self._rng    = random.Random()
        self._disp_cmdr   = "CMDR ——————"
        self._disp_system = "◈ ——————————"
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMinimumWidth(220)

        glow = QGraphicsDropShadowEffect(self)
        glow.setColor(QColor(20, 200, 80, 160))
        glow.setBlurRadius(18)
        glow.setOffset(0, 0)
        self.setGraphicsEffect(glow)

        timer = QTimer(self)
        timer.timeout.connect(self._tick)
        timer.start(140)

    def set_cmdr(self, name: str) -> None:
        self._cmdr = name.upper() if name else ""
        self.updateGeometry()

    def set_system(self, system: str) -> None:
        self._system = system.upper() if system else ""
        self.updateGeometry()

    def sizeHint(self) -> QSize:
        fm1 = QFontMetrics(_CMDR_FONT)
        fm2 = QFontMetrics(_CMDR_FONT_SMALL)
        w = max(
            fm1.horizontalAdvance(f"CMDR {self._cmdr or '——————'}"),
            fm2.horizontalAdvance(f"◈ {self._system or '——————————'}"),
        ) + 20
        return QSize(w, fm1.height() + fm2.height() + 10)

    def _tick(self) -> None:
        def corrupt(s: str, chance: float) -> str:
            if self._rng.random() > chance:
                return s
            chars = list(s)
            for _ in range(self._rng.randint(1, 2)):
                pos = self._rng.randint(0, max(0, len(chars) - 1))
                chars[pos] = self._rng.choice(_GLITCH_CHARS)
            return "".join(chars)

        cmdr_str   = f"CMDR {self._cmdr}"   if self._cmdr   else "CMDR ——————"
        system_str = f"◈ {self._system}"    if self._system else "◈ ——————————"
        self._disp_cmdr   = corrupt(cmdr_str,   0.20)
        self._disp_system = corrupt(system_str, 0.12)
        self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        fm1 = QFontMetrics(_CMDR_FONT)
        fm2 = QFontMetrics(_CMDR_FONT_SMALL)
        lh1 = fm1.height() + 2
        cx  = self.width() // 2

        # CMDR name line
        painter.setFont(_CMDR_FONT)
        w1 = fm1.horizontalAdvance(self._disp_cmdr)
        painter.setPen(QColor(30, 210, 80, 230))
        painter.drawText(cx - w1 // 2, 4 + fm1.ascent(), self._disp_cmdr)

        # Current system line
        painter.setFont(_CMDR_FONT_SMALL)
        w2 = fm2.horizontalAdvance(self._disp_system)
        painter.setPen(QColor(14, 140, 50, 180))
        painter.drawText(cx - w2 // 2, 4 + lh1 + fm2.ascent(), self._disp_system)

        painter.end()

_DECO_FONT    = QFont("Consolas", 8)
_GLITCH_CHARS = "!@#$%░▒▓▌█?╬═╦╠"

_SENSOR_LABELS = ["MSG_RATE    ", "SYSTEMS     ", "ALERTS      ", "UPLINK      "]
_NET_LABELS    = ["MSG RECEIVED", "SYSTEMS SEEN", "ACTIVE ALRTS", "STATUS      "]

_HUD_TICKS = [0.12, 0.28, 0.50, 0.72, 0.88]

# Shared phase for all HudDividerWidget instances — one timer drives both so
# they are always perfectly synchronised.
_hud_phase: float = 0.0
_hud_timer: QTimer | None = None
_hud_instances: list["HudDividerWidget"] = []


def _hud_tick() -> None:
    global _hud_phase
    _hud_phase = (_hud_phase + 0.008) % 1.0
    for w in _hud_instances:
        w.update()


class HudDividerWidget(QWidget):
    """Animated scan-line bar that fills empty header space.

    Draws a dim crimson targeting line with tick marks and a traveling
    bright scan pulse.  ``flip=True`` mirrors the pulse direction and
    swaps the arrow cap to ◄ (used on the right side of the CMDR widget).
    Both instances share a single phase so their pulses are always in sync.
    """

    def __init__(self, flip: bool = False, parent=None) -> None:
        super().__init__(parent)
        self._flip = flip
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMinimumWidth(60)

        _hud_instances.append(self)

        global _hud_timer
        if _hud_timer is None:
            _hud_timer = QTimer()
            _hud_timer.timeout.connect(_hud_tick)
            _hud_timer.start(30)

    def sizeHint(self) -> QSize:
        return QSize(200, 54)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w  = self.width()
        cy = self.height() // 2

        # --- Base line (dim crimson) ---
        painter.setPen(QColor(90, 12, 0, 100))
        painter.drawLine(0, cy, w, cy)

        # --- Tick marks ---
        for frac in _HUD_TICKS:
            tx = int(w * frac)
            painter.setPen(QColor(140, 20, 0, 130))
            painter.drawLine(tx, cy - 4, tx, cy + 4)

        # --- Travelling scan pulse (soft glow + bright core) ---
        raw = (1.0 - _hud_phase) if self._flip else _hud_phase
        px  = int(w * raw)
        for radius, alpha in ((22, 25), (10, 60), (4, 130)):
            painter.setPen(QColor(200, 40, 0, alpha))
            painter.drawLine(max(0, px - radius), cy, min(w - 1, px + radius), cy)
        painter.setPen(QColor(255, 110, 20, 240))
        painter.drawLine(max(0, px - 1), cy, min(w - 1, px + 1), cy)

        # --- Arrow cap at the CMDR-facing end ---
        fm    = QFontMetrics(_DECO_FONT)
        cap   = "\u25c4" if self._flip else "\u25ba"   # ◄ / ►
        cap_x = (w - fm.horizontalAdvance(cap) - 2) if not self._flip else 2
        text_y = cy + fm.ascent() - fm.height() // 2
        painter.setFont(_DECO_FONT)
        painter.setPen(QColor(180, 25, 0, 190))
        painter.drawText(cap_x, text_y, cap)

        painter.end()


class CorruptedScanWidget(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._rng = random.Random()
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        self._msg_count      = 0
        self._prev_msg_count = 0
        self._system_count   = 0
        self._alert_count    = 0
        self._connected      = False

        self._sensor_base = [0.05, 0.0, 0.0, 0.04]
        self._sensor_disp = [0.05, 0.0, 0.0, 0.04]

        self._intercepts: list[str] = []
        self._glitch: dict[int, list[tuple[int, str]]] = {}

        timer = QTimer(self)
        timer.timeout.connect(self._tick)
        timer.start(200)

    # ------------------------------------------------------------------
    # Public API — called by MainWindow
    # ------------------------------------------------------------------

    def update_stats(self, msg_count: int, system_count: int, alert_count: int, connected: bool) -> None:
        delta = msg_count - self._prev_msg_count
        self._prev_msg_count = msg_count
        self._msg_count    = msg_count
        self._system_count = system_count
        self._alert_count  = alert_count
        self._connected    = connected
        self._sensor_base[0] = min(1.0, delta / 25.0)
        self._sensor_base[1] = min(1.0, system_count / 30.0)
        self._sensor_base[2] = min(1.0, alert_count / max(1, system_count))
        self._sensor_base[3] = 0.90 if connected else 0.04

    def add_intercept(self, text: str) -> None:
        ts = datetime.now().strftime("%H:%M")
        self._intercepts.append(f"{ts} {text[:34]}")
        if len(self._intercepts) > 60:
            self._intercepts.pop(0)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _tick(self) -> None:
        for i in range(4):
            noise = self._rng.uniform(-0.015, 0.015)
            self._sensor_disp[i] = max(0.0, min(1.0,
                self._sensor_disp[i] + (self._sensor_base[i] - self._sensor_disp[i]) * 0.3 + noise))
        self._glitch = {}
        for i in range(len(self._intercepts)):
            if self._rng.random() < 0.10:
                line = self._intercepts[i]
                corruptions = [(self._rng.randint(0, max(0, len(line) - 1)),
                                self._rng.choice(_GLITCH_CHARS))
                               for _ in range(self._rng.randint(1, 2))]
                self._glitch[i] = corruptions
        self.update()

    def _glitched(self, i: int, line: str) -> str:
        if i not in self._glitch:
            return line
        chars = list(line)
        for pos, ch in self._glitch[i]:
            if pos < len(chars):
                chars[pos] = ch
        return "".join(chars)

    def _section_header(self, painter: QPainter, fm: QFontMetrics, x: int, y: int, title: str) -> None:
        used   = fm.horizontalAdvance(f"── {title} ")
        dashes = max(0, (self.width() - x - 4 - used) // fm.horizontalAdvance("─"))
        painter.setPen(QColor(160, 18, 0, 170))
        painter.drawText(x, y + fm.ascent(), f"── {title} {'─' * dashes}")

    def _draw_bar(self, painter: QPainter, fm: QFontMetrics, x: int, y: int, bar_w: int, val: float) -> None:
        cw = fm.horizontalAdvance("█")
        if cw <= 0:
            return
        n      = max(1, bar_w // cw)
        filled = int(n * val)
        painter.setPen(QColor(20, 190, 65, 210))
        painter.drawText(x, y + fm.ascent(), "█" * filled)
        painter.setPen(QColor(10, 55, 20, 100))
        painter.drawText(x + filled * cw, y + fm.ascent(), "░" * (n - filled))

    def _paint_sensors(self, painter: QPainter, fm: QFontMetrics, lh: int,
                       x0: int, y: int, bar_x: int, bar_w: int, pct_w: int) -> int:
        self._section_header(painter, fm, x0, y, "SENSOR ARRAY")
        y += lh + 2
        for i, label in enumerate(_SENSOR_LABELS):
            val = self._sensor_disp[i]
            painter.setPen(QColor(12, 115, 42, 150))
            painter.drawText(x0, y + fm.ascent(), label)
            self._draw_bar(painter, fm, bar_x, y, bar_w, val)
            painter.setPen(QColor(14, 130, 48, 155))
            painter.drawText(self.width() - pct_w - 4, y + fm.ascent(), f"{int(val * 100):3d}%")
            y += lh
        return y + 6

    def _paint_intercepts(self, painter: QPainter, fm: QFontMetrics, lh: int,
                          x0: int, y: int, n_net: int, n_kumo: int) -> int:
        fixed_h   = y + (lh + 2) + 6 + (lh + 2) + n_net * lh + 6 + (lh + 2) + n_kumo * lh
        n_visible = max(1, min(len(self._intercepts), (self.height() - fixed_h) // lh))
        visible   = self._intercepts[-n_visible:]
        offset    = len(self._intercepts) - len(visible)
        self._section_header(painter, fm, x0, y, "LIVE INTERCEPTS")
        y += lh + 2
        if not visible:
            painter.setPen(QColor(10, 80, 30, 100))
            painter.drawText(x0, y + fm.ascent(), "-- AWAITING DATA --")
            return y + n_visible * lh + 6
        for j, line in enumerate(visible):
            gi    = offset + j
            color = QColor(30, 200, 70, 210) if gi in self._glitch else QColor(18, 145, 52, 150)
            painter.setPen(color)
            painter.drawText(x0, y + fm.ascent(), f"> {self._glitched(gi, line)}")
            y += lh
        return y + 6

    def _paint_net(self, painter: QPainter, fm: QFontMetrics, lh: int, x0: int, y: int) -> int:
        status_str = "LIVE" if self._connected else "OFFLINE"
        net_values = [f"{self._msg_count:,}", str(self._system_count),
                      str(self._alert_count), status_str]
        self._section_header(painter, fm, x0, y, "NET STATUS")
        y += lh + 2
        for i, (label, val) in enumerate(zip(_NET_LABELS, net_values)):
            if i == 3:
                color = QColor(20, 180, 60, 160) if self._connected else QColor(160, 18, 0, 160)
            else:
                color = QColor(12, 100, 38, 135)
            painter.setPen(color)
            painter.drawText(x0, y + fm.ascent(), f"{label}  {val}")
            y += lh
        return y + 6

    def _paint_kumo(self, painter: QPainter, fm: QFontMetrics, lh: int, x0: int, y: int) -> None:
        self._section_header(painter, fm, x0, y, "KUMO AUTHORITY")
        y += lh + 2
        for line in [
            f"MINER TARGET  {'YES' if config.target_miner  else 'NO '}",
            f"TRADER TARGET {'YES' if config.target_trader else 'NO '}",
            f"MIN SCORE     {config.alert_score_threshold}",
            f"MAX AGE       {config.max_system_age_minutes}min",
        ]:
            painter.setPen(QColor(130, 15, 0, 135))
            painter.drawText(x0, y + fm.ascent(), line)
            y += lh

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setFont(_DECO_FONT)
        fm  = QFontMetrics(_DECO_FONT)
        lh  = fm.height() + 2
        x0  = 6
        label_w = fm.horizontalAdvance("MSG_RATE     ")
        pct_w   = fm.horizontalAdvance("100%")
        bar_x   = x0 + label_w + 4
        bar_w   = self.width() - bar_x - pct_w - 10
        y = self._paint_sensors(painter, fm, lh, x0, 8, bar_x, bar_w, pct_w)
        y = self._paint_intercepts(painter, fm, lh, x0, y, len(_NET_LABELS), 4)
        y = self._paint_net(painter, fm, lh, x0, y)
        self._paint_kumo(painter, fm, lh, x0, y)
        painter.end()


class _AsyncSignals(QObject):
    """Qt signals used by asyncio callbacks to safely cross thread boundaries."""
    log_message = Signal(str)


class BackgroundWidget(QWidget):
    def __init__(self, pixmap: QPixmap | None, parent=None):
        super().__init__(parent)
        self._pixmap = pixmap

    def paintEvent(self, event):
        super().paintEvent(event)
        if self._pixmap and not self._pixmap.isNull():
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            padded = self.size() * 0.82
            scaled = self._pixmap.scaled(padded, Qt.AspectRatioMode.KeepAspectRatio,
                                         Qt.TransformationMode.SmoothTransformation)
            painter.setOpacity(0.25)
            cx = int(self.width() * 0.72)
            cy = int(self.height() * 0.565)
            painter.translate(cx, cy)
            painter.rotate(30)
            painter.drawPixmap(-scaled.width() // 2, -scaled.height() // 2, scaled)
            painter.end()


class MainWindow(QMainWindow):
    def __init__(self, controller) -> None:
        super().__init__()
        self._controller = controller
        self._signals    = _AsyncSignals()
        self._running    = False
        self._bg_task:   asyncio.Task | None = None
        self._bg_pixmap: QPixmap | None = None

        self._last_system_count = 0
        self._last_alert_count  = 0

        self._load_background()
        self._setup_ui()
        self._wire_callbacks()
        self._setup_timers()

        self.setWindowTitle("Archon's Eye — Kumo Crew")
        self.resize(1200, 750)

    def _setup_ui(self) -> None:
        central = BackgroundWidget(self._bg_pixmap)
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)
        root.addLayout(self._build_header())

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self._build_sidebar())
        splitter.addWidget(self._build_main_panel())
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([260, 900])
        root.addWidget(splitter, stretch=1)

    def _load_background(self) -> None:
        logo_path = os.path.join(os.path.dirname(__file__), "resources", "Archon_Delaine_Green_Vector.webp")
        if os.path.exists(logo_path):
            self._bg_pixmap = QPixmap(logo_path)

    # ------------------------------------------------------------------
    # UI builders
    # ------------------------------------------------------------------

    def _build_header(self) -> QHBoxLayout:
        layout = QHBoxLayout()
        layout.setSpacing(10)
        layout.setContentsMargins(0, 0, 0, 0)

        title_box = QWidget()
        title_box.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        title_box_layout = QVBoxLayout(title_box)
        title_box_layout.setContentsMargins(0, 0, 0, 0)
        title_box_layout.setSpacing(2)
        title = GlitchTitleWidget("ARCHON'S EYE")
        title_box_layout.addWidget(title)
        layout.addWidget(title_box)

        layout.addWidget(HudDividerWidget(flip=False), 1)
        self._cmdr_widget = CorruptedCmdrWidget()
        layout.addWidget(self._cmdr_widget, alignment=Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(HudDividerWidget(flip=True), 1)

        self._badge = QLabel(_BADGE_OFFLINE)
        self._badge.setObjectName(_OBJ_OFFLINE)
        layout.addWidget(self._badge)
        self._msg_label = QLabel("Messages: 0")
        self._msg_label.setObjectName("status_label")
        layout.addWidget(self._msg_label)
        return layout

    def _build_sidebar(self) -> QWidget:
        sidebar = QWidget()
        sidebar.setFixedWidth(260)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(0, 0, 8, 0)
        layout.setSpacing(12)

        ctrl_group = QGroupBox("Connection")
        ctrl_layout = QVBoxLayout(ctrl_group)
        self._start_btn = QPushButton("▶  START")
        self._start_btn.clicked.connect(self._on_start)
        self._stop_btn = QPushButton("■  STOP")
        self._stop_btn.setObjectName("stop_btn")
        self._stop_btn.clicked.connect(self._on_stop)
        self._stop_btn.setEnabled(False)
        ctrl_layout.addWidget(self._start_btn)
        ctrl_layout.addWidget(self._stop_btn)
        layout.addWidget(ctrl_group)

        filter_group = QGroupBox("Filters")
        filter_layout = QFormLayout(filter_group)
        filter_layout.setSpacing(8)

        self._cb_miner = QCheckBox("Miner targets")
        self._cb_miner.setChecked(config.target_miner)
        self._cb_miner.toggled.connect(lambda v: setattr(config, "target_miner", v))

        self._cb_trader = QCheckBox("Trader targets")
        self._cb_trader.setChecked(config.target_trader)
        self._cb_trader.toggled.connect(lambda v: setattr(config, "target_trader", v))

        self._score_spin = QSpinBox()
        self._score_spin.setRange(0, 200)
        self._score_spin.setValue(config.alert_score_threshold)
        self._score_spin.valueChanged.connect(lambda v: setattr(config, "alert_score_threshold", v))

        self._age_spin = QSpinBox()
        self._age_spin.setRange(5, 1440)
        self._age_spin.setSuffix(" min")
        self._age_spin.setValue(config.max_system_age_minutes)
        self._age_spin.valueChanged.connect(lambda v: setattr(config, "max_system_age_minutes", v))

        def _flabel(text: str) -> QLabel:
            lbl = QLabel(text)
            lbl.setStyleSheet(
                "font-family: 'Consolas', monospace; font-size: 11px;"
                "letter-spacing: 1px; color: #1ab848;"
            )
            return lbl

        filter_layout.addRow(self._cb_miner)
        filter_layout.addRow(self._cb_trader)
        filter_layout.addRow(_flabel("MIN SCORE"), self._score_spin)
        filter_layout.addRow(_flabel("MAX AGE  "), self._age_spin)
        layout.addWidget(filter_group)

        self._scan_widget = CorruptedScanWidget()
        layout.addWidget(self._scan_widget, stretch=1)
        return sidebar

    def _build_main_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        lbl = QLabel("  TARGET SYSTEMS")
        lbl.setObjectName("status_label")
        layout.addWidget(lbl)
        self._table = SystemTable()
        layout.addWidget(self._table, stretch=1)
        return panel

    # ------------------------------------------------------------------
    # Timers
    # ------------------------------------------------------------------

    def _setup_timers(self) -> None:
        self._table_timer = QTimer(self)
        self._table_timer.setInterval(_TABLE_REFRESH_MS)
        self._table_timer.timeout.connect(self._tick_table)

        self._status_timer = QTimer(self)
        self._status_timer.setInterval(_STATUS_REFRESH_MS)
        self._status_timer.timeout.connect(self._tick_status)
        self._status_timer.start()

        # Start the journal watcher as soon as the event loop is running
        QTimer.singleShot(0, self._controller.start_journal_watcher)

    def _tick_table(self) -> None:
        t0 = time.monotonic()
        systems = self._controller.get_top_systems()
        t1 = time.monotonic()
        self._table.update_player_pos(self._controller.player_pos)
        self._table.update_systems(systems)
        t2 = time.monotonic()
        self._last_system_count = len(systems)
        self._last_alert_count  = sum(
            1 for s in systems if s.total_score >= config.alert_score_threshold
        )
        total_ms = (t2 - t0) * 1000
        if total_ms > 30:
            log.debug(
                "_tick_table: get_top_systems=%.0fms  update_systems=%.0fms  total=%.0fms",
                (t1 - t0) * 1000, (t2 - t1) * 1000, total_ms,
            )

    def _tick_status(self) -> None:
        listener  = self._controller._listener
        connected = listener.is_running
        count     = listener.messages_received
        self._msg_label.setText(f"Messages: {count:,}")
        name = _OBJ_LIVE  if connected else _OBJ_OFFLINE
        text = _BADGE_LIVE if connected else _BADGE_OFFLINE
        if self._badge.text() != text:
            self._badge.setText(text)
            self._badge.setObjectName(name)
            self._badge.style().unpolish(self._badge)
            self._badge.style().polish(self._badge)
        self._cmdr_widget.set_cmdr(self._controller.player_cmdr)
        self._cmdr_widget.set_system(self._controller.player_system)
        self._scan_widget.update_stats(
            msg_count=count,
            system_count=self._last_system_count,
            alert_count=self._last_alert_count,
            connected=connected,
        )

    # ------------------------------------------------------------------
    # Callbacks
    # ------------------------------------------------------------------

    def _wire_callbacks(self) -> None:
        self._signals.log_message.connect(self._append_log)
        self._controller.on_log = lambda msg: self._signals.log_message.emit(msg)

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _on_start(self) -> None:
        self._start_btn.setEnabled(False)
        self._stop_btn.setEnabled(True)
        self._running = True
        self._bg_task = asyncio.ensure_future(self._controller.start())
        self._table_timer.start()
        self._append_log("Connecting to EDDN...")

    def _on_stop(self) -> None:
        self._stop_btn.setEnabled(False)
        self._start_btn.setEnabled(True)
        self._running = False
        self._table_timer.stop()
        self._status_timer.stop()
        self._bg_task = asyncio.ensure_future(self._controller.stop())
        self._badge.setText(_BADGE_OFFLINE)
        self._badge.setObjectName(_OBJ_OFFLINE)
        self._badge.style().unpolish(self._badge)
        self._badge.style().polish(self._badge)
        self._append_log("Disconnected from EDDN.")

    def _append_log(self, msg: str) -> None:
        self._scan_widget.add_intercept(msg)

    def closeEvent(self, event) -> None:
        self._table_timer.stop()
        self._status_timer.stop()
        if self._running:
            self._bg_task = asyncio.ensure_future(self._controller.stop())
        event.accept()
