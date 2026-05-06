"""Corrupted sci-fi terminal -- Kumo Crew / Archon Delaine palette."""

# Phosphor green (body) + blood crimson (danger/title) + Agency FB / Consolas
DARK_STYLESHEET = """
QMainWindow, QWidget {
    background-color: rgba(5, 8, 7, 120);
    color: #1ab848;
    font-family: "Segoe UI", "Calibri", sans-serif;
    font-size: 13px;
}

QGroupBox {
    background-color: rgba(3, 6, 4, 160);
    border: 1px solid #1e2a1a;
    border-top: 1px solid #5a0800;
    border-radius: 2px;
    margin-top: 14px;
    padding-top: 10px;
}

QWidget#central, QGroupBox, QTextEdit, QTableWidget, QTableWidget::item {
    background-color: rgba(5, 8, 7, 120);
}

QLabel {
    color: #1ab848;
    background: transparent;
}

QLabel#deco {
    font-family: "Segoe UI", sans-serif;
    font-size: 28px;
    color: #5a1200;
}

QLabel#subtitle {
    font-family: "Segoe UI", sans-serif;
    font-size: 9px;
    color: #0e6830;
    letter-spacing: 5px;
}

QLabel#status_label {
    font-family: "Segoe UI", sans-serif;
    color: #0e6030;
    font-size: 11px;
    letter-spacing: 1px;
    background: transparent;
}

QLabel#live_badge {
    font-family: "Segoe UI", sans-serif;
    color: #22ee55;
    font-weight: bold;
    font-size: 12px;
    background: transparent;
}

QLabel#offline_badge {
    font-family: "Segoe UI", sans-serif;
    color: #bb1500;
    font-weight: bold;
    font-size: 12px;
    background: transparent;
}

QPushButton {
    background-color: #080e0a;
    color: #1ab848;
    border: 1px solid #5a1200;
    border-radius: 2px;
    padding: 6px 16px;
    font-family: "Consolas", monospace;
    font-size: 11px;
    font-weight: bold;
    letter-spacing: 3px;
}

QPushButton:hover {
    background-color: #0e160f;
    border-color: #aa1800;
    color: #22ee55;
}

QPushButton:pressed {
    background-color: #180500;
}

QPushButton:disabled {
    color: #1a3020;
    border-color: #1c1c1c;
}

QPushButton#stop_btn {
    border-color: #440e00;
    color: #6a3020;
}

QPushButton#stop_btn:hover {
    border-color: #992200;
    color: #c03010;
}

QTableWidget {
    background-color: rgba(4, 6, 5, 120);
    gridline-color: #0c140e;
    selection-background-color: #180300;
    selection-color: #ff4d20;
    border: 1px solid #0e160e;
    border-radius: 2px;
    alternate-background-color: #060a07;
}

QTableWidget::item {
    padding: 4px 8px;
    border-bottom: 1px solid #0a100a;
}

QTableWidget::item:selected {
    background-color: #180300;
    color: #ff4d20;
}

QHeaderView::section {
    background-color: #070b08;
    color: #c01500;
    border: none;
    border-bottom: 1px solid #280e00;
    border-right: 1px solid #0c140e;
    padding: 6px 8px;
    font-family: "Segoe UI", sans-serif;
    font-weight: bold;
    letter-spacing: 1px;
    text-transform: uppercase;
    font-size: 11px;
}

QTextEdit {
    background-color: rgba(4, 6, 5, 120);
    color: #18a840;
    border: 1px solid #0c140e;
    border-radius: 2px;
    font-family: "Segoe UI", sans-serif;
    font-size: 11px;
}

QLineEdit, QSpinBox, QDoubleSpinBox {
    background-color: #060c08;
    color: #1ec850;
    border: 1px solid #1a2a1a;
    border-radius: 1px;
    padding: 4px 8px;
    font-family: "Consolas", monospace;
    font-size: 12px;
    letter-spacing: 1px;
}

QSpinBox::up-button, QDoubleSpinBox::up-button {
    subcontrol-origin: border;
    subcontrol-position: top right;
    width: 18px;
    border-left: 1px solid #1a2a1a;
    border-bottom: 1px solid #1a2a1a;
    background-color: #0a1008;
    border-top-right-radius: 2px;
}

QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover,
QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover {
    background-color: #161e12;
}

QSpinBox::up-button:pressed, QDoubleSpinBox::up-button:pressed,
QSpinBox::down-button:pressed, QDoubleSpinBox::down-button:pressed {
    background-color: #6a1200;
}

QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {
    image: none;
    width: 0;
    height: 0;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-bottom: 5px solid #1ab848;
}

QSpinBox::down-button, QDoubleSpinBox::down-button {
    subcontrol-origin: border;
    subcontrol-position: bottom right;
    width: 18px;
    border-left: 1px solid #1a2a1a;
    border-top: 1px solid #1a2a1a;
    background-color: #0a1008;
    border-bottom-right-radius: 2px;
}

QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {
    image: none;
    width: 0;
    height: 0;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 5px solid #1ab848;
}

QLineEdit:focus, QSpinBox:focus {
    border-color: #7a1800;
}

QCheckBox {
    color: #1ec850;
    font-family: "Consolas", monospace;
    font-size: 12px;
    letter-spacing: 1px;
    spacing: 8px;
}

QCheckBox::indicator {
    width: 12px;
    height: 12px;
    border: 1px solid #2a3a28;
    border-radius: 1px;
    background-color: #060c08;
}

QCheckBox::indicator:checked {
    background-color: #6a1200;
    border-color: #cc2000;
}

QCheckBox::indicator:checked:hover {
    background-color: #881800;
}

QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 8px;
    top: 2px;
    padding: 0 4px;
    color: #c81800;
    font-family: "Consolas", monospace;
    font-size: 11px;
    font-weight: bold;
    letter-spacing: 2px;
    text-transform: uppercase;
}

QScrollBar:vertical {
    background: #040605;
    width: 8px;
}

QScrollBar::handle:vertical {
    background: #162016;
    border-radius: 4px;
    min-height: 20px;
}

QScrollBar::handle:vertical:hover {
    background: #6a1200;
}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
}

QSplitter::handle {
    background: #0c140e;
    width: 2px;
}
"""
