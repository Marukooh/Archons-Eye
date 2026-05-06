"""Real-time table widget showing scored star systems."""

import math
import re
from collections import OrderedDict
from datetime import datetime, timezone

from PySide6.QtWidgets import (
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QStyledItemDelegate, QStyleOptionViewItem, QApplication, QStyle,
)
from PySide6.QtCore import Qt, QSettings, QRectF
from PySide6.QtGui import QColor, QBrush, QTextDocument

from archons_eye.models.system import StarSystem

_COLUMNS = ["System", "Score", "Upd/10m", "CMDRs/10m", "Type", "Security", "Allegiance", "State", "Updated", "Dist(Ly)", "Trading", "Mining"]
_COL_STATE   = 7
_COL_DIST    = 9
_COL_TRADING = 10
_COL_MINING  = 11

_DEFAULT_WIDTHS = [180, 60, 70, 70, 60, 80, 110, 90, 80, 70, 200, 220]

# Per-column sort key extractors.  Index must match _COLUMNS order.
_SORT_KEYS = [
    lambda s: s.name.lower(),
    lambda s: s.total_score,        # overridden to compound key when col == 1
    lambda s: s.activity_count,
    lambda s: s.cmdr_count,
    lambda s: s.target_type,
    lambda s: s.security,
    lambda s: s.allegiance,
    lambda s: s.system_state,
    lambda s: s.last_updated,       # datetime — desc = newest first
    None,                           # Distance — handled separately in _sorted()
    lambda s: s.trader_reason,
    lambda s: s.miner_reason,
]

# First-click direction per column: True = ascending, False = descending.
_SORT_ASC_DEFAULT = [
    True,   # System      — A→Z
    False,  # Score       — high first
    False,  # Upd/10m     — high first
    False,  # CMDRs/10m   — high first
    True,   # Type        — A→Z
    True,   # Security    — A→Z
    True,   # Allegiance  — A→Z
    True,   # State       — A→Z
    False,  # Updated     — newest first
    True,   # Dist(Ly)    — nearest first
    True,   # Trading     — A→Z
    True,   # Mining      — A→Z
]

_SECURITY_COLORS: dict[str, QColor] = {
    "Anarchy": QColor("#ff4444"),
    "Low":     QColor("#ff8800"),
    "Medium":  QColor("#f4c840"),
    "High":    QColor("#44aa66"),
}

_ALLEGIANCE_COLORS: dict[str, QColor] = {
    "Alliance":    QColor("#44aa66"),
    "Federation":  QColor("#ff4444"),
    "Empire":      QColor("#aa66ff"),
    "Independent": QColor("#f4c840"),
}

_STATE_COLORS: dict[str, QColor] = {
    "Boom":         QColor("#44cc44"),
    "Bust":         QColor("#888888"),
    "Famine":       QColor("#ff8800"),
    "Outbreak":     QColor("#ff6644"),
    "Civil Unrest": QColor("#ff4444"),
    "Civil War":    QColor("#ff2222"),
    "War":          QColor("#ff2222"),
    "Lockdown":     QColor("#cc4444"),
    "Election":     QColor("#f4c840"),
}

_COLOR_MINER         = QColor("#5bc8ff")
_COLOR_TRADER        = QColor("#ff9955")
_COLOR_DEFAULT       = QColor("#d4b870")
_COLOR_DIM           = QColor("#555555")
_COLOR_HOTSPOT_BADGE = "#cc2200"   # Kumo crimson — hotspot count badge
_COLOR_HOTSPOT_TYPE  = "#ff9966"   # warm amber-red — hotspot type names
_COLOR_HOTSPOT_DIM   = "#664433"   # muted — separators / counts
_ALIGN_CENTER  = Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignHCenter
_ALIGN_LEFT    = Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft

_GRAD_RED   = (255, 68,  68)
_GRAD_GREEN = (68,  204, 68)
_ACT_MAX     = 10   # gradient goes red→green over 0-10 updates
_CMDR_MAX    = 5    # gradient goes red→green over 0-5 unique CMDRs
_SCORE_MAX   = 120  # score at which the gradient reaches full green

# ---------------------------------------------------------------------------
# Per-commodity colors — distinct hues, all legible on a dark background
# ---------------------------------------------------------------------------
_COMMODITY_COLORS: dict[str, str] = {
    # Miners — cool/gem tones
    "Void Opal":               "#b388ff",
    "Low Temperature Diamond": "#80deea",
    "Platinum":                "#e0e0e0",
    "Painite":                 "#f48fb1",
    "Osmium":                  "#90caf9",
    "Tritium":                 "#ce93d8",
    "Alexandrite":             "#a5d6a7",
    "Rhodplumsite":            "#ffcc80",
    "Serendibite":             "#ff8a65",
    "Musgravite":              "#c5e1a5",
    "Benitoite":               "#64b5f6",
    "Grandidierite":           "#aed581",
    "Taaffeite":               "#f06292",
    "Monazite":                "#fff176",
    "Jadeite":                 "#80cbc4",
    # Traders — warm tones
    "Gold":                    "#ffd54f",
    "Palladium":               "#b0bec5",
    "Silver":                  "#eceff1",
    "Bertrandite":             "#ff8a65",
    "Indite":                  "#ba68c8",
    "Gallite":                 "#4dd0e1",
    "Coltan":                  "#bcaaa4",
    "Superconductors":         "#80cbc4",
    "CMM Composite":           "#a5d6a7",
    "Consumer Technology":     "#ffb74d",
    "Computer Components":     "#90caf9",
    "Resonant Separators":     "#ce93d8",
    "Narcotics":               "#ef5350",
    "Tobacco":                 "#a1887f",
    "Performance Enhancers":   "#ffa726",
    "Progenitor Cells":        "#66bb6a",
    "Battle Weapons":          "#f44336",
    "Personal Weapons":        "#ef9a9a",
    "Reactive Armour":         "#ffcdd2",
    "Imperial Slaves":         "#ab47bc",
    "Slaves":                  "#e53935",
}

_COMMODITY_COLORS_LOWER: dict[str, str] = {k.lower(): v for k, v in _COMMODITY_COLORS.items()}

# Regex matches any known commodity name (longest first — avoids partial matches)
_COMMODITY_RE = re.compile(
    r'(' + '|'.join(re.escape(n) for n in sorted(_COMMODITY_COLORS, key=len, reverse=True)) + r')',
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _gradient(t: float) -> QColor:
    """Interpolate between _GRAD_RED and _GRAD_GREEN for t in [0, 1]."""
    r = int(_GRAD_RED[0] + (_GRAD_GREEN[0] - _GRAD_RED[0]) * t)
    g = int(_GRAD_RED[1] + (_GRAD_GREEN[1] - _GRAD_RED[1]) * t)
    b = int(_GRAD_RED[2] + (_GRAD_GREEN[2] - _GRAD_RED[2]) * t)
    return QColor(r, g, b)


def _score_color(score: int) -> QColor:
    if score <= 0:
        return _COLOR_DIM
    return _gradient(min(score / _SCORE_MAX, 1.0))


def _activity_color(count: int) -> QColor:
    if count == 0:
        return _COLOR_DIM
    return _gradient(min(count / _ACT_MAX, 1.0))


def _cmdr_color(count: int) -> QColor:
    if count == 0:
        return _COLOR_DIM
    return _gradient(min(count / _CMDR_MAX, 1.0))


def _hotspot_html(system: StarSystem) -> str:
    """Return prominent HTML block for hotspots: bold orange badge + colored type names."""
    count = system.hotspot_count
    label = "hotspot" if count == 1 else "hotspots"
    badge = (
        f'<b style="color:{_COLOR_HOTSPOT_BADGE}; background-color:#3a1a00;">'
        f'\u25c6 {count} {label}</b>'
    )
    if system.hotspot_summary:
        # colorize individual commodity names using per-commodity palette
        summary = _colorize_reason(system.hotspot_summary, _COLOR_HOTSPOT_TYPE)
        sep = f'<span style="color:{_COLOR_HOTSPOT_DIM}"> — </span>'
        return badge + sep + summary
    return badge


def _colorize_reason(reason: str, base_color: str) -> str:
    """Return HTML: commodity names bold + unique color, surrounding text in base_color."""
    if not reason:
        return ""
    safe = reason.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    def _replace(m: re.Match) -> str:
        name = m.group(1)
        color = _COMMODITY_COLORS_LOWER.get(name.lower(), base_color)
        return f'<b style="color:{color}">{name}</b>'

    colored = _COMMODITY_RE.sub(_replace, safe)
    return f'<span style="color:{base_color}">{colored}</span>'


# ---------------------------------------------------------------------------
# Custom delegate — renders Segnali column as HTML
# ---------------------------------------------------------------------------

class _RichTextDelegate(QStyledItemDelegate):
    _MAX_CACHE = 200

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._doc_cache: OrderedDict[str, QTextDocument] = OrderedDict()

    def _get_doc(self, html: str, font) -> QTextDocument:
        if html in self._doc_cache:
            self._doc_cache.move_to_end(html)
            return self._doc_cache[html]
        doc = QTextDocument()
        doc.setDefaultFont(font)
        doc.setDocumentMargin(0)
        doc.setHtml(html)
        self._doc_cache[html] = doc
        if len(self._doc_cache) > self._MAX_CACHE:
            self._doc_cache.popitem(last=False)
        return doc

    def paint(self, painter, option, index) -> None:
        html = index.data(Qt.ItemDataRole.UserRole)
        if not html:
            super().paint(painter, option, index)
            return

        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        opt.text = ""
        style = opt.widget.style() if opt.widget else QApplication.style()
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, painter, opt.widget)

        doc = self._get_doc(html, opt.font)

        painter.save()
        r = opt.rect
        y_off = max(0.0, (r.height() - doc.size().height()) / 2)
        painter.translate(r.left() + 4, r.top() + y_off)
        doc.drawContents(painter, QRectF(0, 0, r.width() - 8, r.height()))
        painter.restore()


# ---------------------------------------------------------------------------
# Table widget
# ---------------------------------------------------------------------------

class SystemTable(QTableWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(0, len(_COLUMNS), parent)
        self.setHorizontalHeaderLabels(_COLUMNS)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setAlternatingRowColors(False)
        self.verticalHeader().setVisible(False)

        hh = self.horizontalHeader()
        hh.setStretchLastSection(True)
        for col in range(len(_COLUMNS)):
            hh.setSectionResizeMode(col, QHeaderView.ResizeMode.Interactive)

        self.setItemDelegateForColumn(_COL_MINING,  _RichTextDelegate(self))
        self.setItemDelegateForColumn(_COL_TRADING, _RichTextDelegate(self))

        self._player_pos: tuple[float, float, float] | None = None

        self._load_column_widths()
        hh.sectionResized.connect(self._on_section_resized)
        self.setSortingEnabled(False)

        self._sort_col: int = 1
        self._sort_asc: bool = False
        self._all_systems: list[StarSystem] = []

        hh.setSortIndicatorShown(True)
        hh.setSortIndicator(1, Qt.SortOrder.DescendingOrder)
        hh.sectionClicked.connect(self._on_header_clicked)

    def _settings(self) -> QSettings:
        return QSettings("ArchonsEye", "SystemTable")

    def _load_column_widths(self) -> None:
        s = self._settings()
        for col, default in enumerate(_DEFAULT_WIDTHS):
            width = s.value(f"col_{col}", default, type=int)
            self.setColumnWidth(col, width if isinstance(width, int) else default)

    def _on_section_resized(self, col: int, _old: int, new: int) -> None:
        self._settings().setValue(f"col_{col}", new)

    def update_player_pos(self, pos: tuple[float, float, float] | None) -> None:
        """Called by MainWindow whenever the player jumps to a new system."""
        self._player_pos = pos

    def update_systems(self, systems: list[StarSystem]) -> None:
        self._all_systems = systems
        self.setUpdatesEnabled(False)
        try:
            self._sync_rows(self._sorted(systems))
        finally:
            self.setUpdatesEnabled(True)

    def _on_header_clicked(self, col: int) -> None:
        if col == self._sort_col:
            self._sort_asc = not self._sort_asc
        else:
            self._sort_col = col
            self._sort_asc = _SORT_ASC_DEFAULT[col]
        self.horizontalHeader().setSortIndicator(
            self._sort_col,
            Qt.SortOrder.AscendingOrder if self._sort_asc else Qt.SortOrder.DescendingOrder,
        )
        self.setUpdatesEnabled(False)
        try:
            self._sync_rows(self._sorted(self._all_systems))
        finally:
            self.setUpdatesEnabled(True)

    def _sorted(self, systems: list[StarSystem]) -> list[StarSystem]:
        col = self._sort_col
        asc = self._sort_asc
        if col == 1:
            # Compound key: primary score, then break ties by activity
            return sorted(
                systems,
                key=lambda s: (s.total_score, s.activity_count, s.cmdr_count),
                reverse=not asc,
            )
        if col == _COL_DIST:
            pp = self._player_pos
            if pp:
                def _dist_key(s: StarSystem) -> float:
                    dx, dy, dz = s.x - pp[0], s.y - pp[1], s.z - pp[2]
                    return math.sqrt(dx*dx + dy*dy + dz*dz)
                return sorted(systems, key=_dist_key, reverse=not asc)
            return systems  # no position — preserve existing order
        key = _SORT_KEYS[col]
        return sorted(systems, key=key, reverse=not asc)

    def _sync_rows(self, systems: list[StarSystem]) -> None:
        now = datetime.now(timezone.utc)
        if self.rowCount() != len(systems):
            self.setRowCount(len(systems))
        for row, system in enumerate(systems):
            self._sync_row(row, system, now)

    @staticmethod
    def _get_or_create_item(table: "SystemTable", row: int, col: int) -> QTableWidgetItem:
        item = table.item(row, col)
        if item is None:
            item = QTableWidgetItem()
            item.setTextAlignment(_ALIGN_LEFT)
            table.setItem(row, col, item)
        return item

    @staticmethod
    def _render_dist_cell(item: QTableWidgetItem, val: str) -> None:
        item.setTextAlignment(_ALIGN_CENTER)
        try:
            d = float(val.rstrip(" Ly")) if val != "—" else None
        except ValueError:
            d = None
        if d is not None:
            item.setForeground(QBrush(_gradient(max(0.0, 1.0 - d / 500.0))))
        else:
            item.setForeground(QBrush(_COLOR_DIM))

    @staticmethod
    def _render_mining_cell(item: QTableWidgetItem, val: str, system: StarSystem) -> None:
        sep = '<span style="color:#555555"> · </span>'
        parts_html = []
        if system.hotspot_count > 0:
            parts_html.append(_hotspot_html(system))
        if system.miner_sell_reason:
            parts_html.append(_colorize_reason(system.miner_sell_reason, "#5bc8ff"))
        if system.miner_ring_reason:
            parts_html.append(_colorize_reason(system.miner_ring_reason, "#5bc8ff"))
        if not parts_html and val:
            parts_html.append(_colorize_reason(val, "#5bc8ff"))
        html = sep.join(parts_html)
        if item.data(Qt.ItemDataRole.UserRole) != html:
            item.setData(Qt.ItemDataRole.UserRole, html)

    @staticmethod
    def _render_trading_cell(item: QTableWidgetItem, val: str) -> None:
        html = _colorize_reason(val, "#ff9955")
        if item.data(Qt.ItemDataRole.UserRole) != html:
            item.setData(Qt.ItemDataRole.UserRole, html)

    def _sync_row(self, row: int, system: StarSystem, now: datetime) -> None:
        last = system.last_updated
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        age_secs = (now - last).total_seconds()
        age_str  = f"{int(age_secs // 60)}m {int(age_secs % 60)}s"

        values = [
            system.name,
            str(system.total_score),
            str(system.activity_count) if system.activity_count > 0 else "—",
            str(system.cmdr_count)     if system.cmdr_count     > 0 else "—",
            system.target_type,
            system.security,
            system.allegiance,
            system.system_state or "—",   # State column
            age_str,
            self._dist_str(system),       # Dist(Ly)
            system.trader_reason,         # Trading column
            system.miner_reason,          # Mining column (best overall, used as sort key)
        ]

        for col, val in enumerate(values):
            item = SystemTable._get_or_create_item(self, row, col)
            if item.text() != val:
                item.setText(val)
            if col == _COL_DIST:
                self._render_dist_cell(item, val)
            elif col == _COL_MINING:
                self._render_mining_cell(item, val, system)
            elif col == _COL_TRADING:
                self._render_trading_cell(item, val)
            else:
                self._apply_color(item, col, system)

    @staticmethod
    def _target_type_color(target_type: str) -> QColor:
        if "M" in target_type and "T" in target_type:
            return _COLOR_DEFAULT
        return _COLOR_MINER if "M" in target_type else _COLOR_TRADER

    def _dist_str(self, system: StarSystem) -> str:
        pp = self._player_pos
        if pp is None or (not system.x and not system.y and not system.z and system.name != "Sol"):
            return "—"
        dx = system.x - pp[0]
        dy = system.y - pp[1]
        dz = system.z - pp[2]
        dist = math.sqrt(dx*dx + dy*dy + dz*dz)
        if dist < 10:
            return f"{dist:.1f} Ly"
        return f"{dist:.0f} Ly"

    @staticmethod
    def _apply_color(item: QTableWidgetItem, col: int, system: StarSystem) -> None:
        align = _ALIGN_CENTER if col in (1, 2, 3) else _ALIGN_LEFT
        if col == 1:
            color = _score_color(system.total_score)
        elif col == 2:
            color = _activity_color(system.activity_count)
        elif col == 3:
            color = _cmdr_color(system.cmdr_count)
        elif col == 4:
            color = SystemTable._target_type_color(system.target_type)
        elif col == 5:
            color = _SECURITY_COLORS.get(system.security, _COLOR_DEFAULT)
        elif col == 6:
            color = _ALLEGIANCE_COLORS.get(system.allegiance, _COLOR_DEFAULT)
        elif col == _COL_STATE:
            # Multi-state: use color of highest-priority state found in the string
            color = _COLOR_DIM
            for state, sc in _STATE_COLORS.items():
                if state in system.system_state:
                    color = sc
                    break
        else:
            color = _COLOR_DEFAULT
        item.setForeground(QBrush(color))
        item.setTextAlignment(align)
