"""Application entry point."""

import asyncio
import logging
from logging.handlers import RotatingFileHandler
import sys
from pathlib import Path

# When run directly (python archons_eye/main.py), the project root is not on
# sys.path. Insert it so the archons_eye package is importable either way.
_project_root = Path(__file__).parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from PySide6.QtWidgets import QApplication
import qasync

from archons_eye.config import config, DB_DIR
from archons_eye.core.controller import Controller
from archons_eye.gui.main_window import MainWindow
from archons_eye.gui.styles import DARK_STYLESHEET

# DB path is already set to AppData in config.py — nothing to override here.
# Log file goes to the same AppData folder so everything is in one place.
_log_file = Path(DB_DIR) / "archons_eye_debug.log"
_fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s", datefmt="%H:%M:%S")

_file_handler = RotatingFileHandler(
    _log_file, maxBytes=10 * 1024 * 1024, backupCount=4, encoding="utf-8"
)
_file_handler.setFormatter(_fmt)

_console_handler = logging.StreamHandler()
_console_handler.setFormatter(_fmt)

logging.root.setLevel(logging.INFO)
logging.root.addHandler(_file_handler)
logging.root.addHandler(_console_handler)


def main() -> None:
    app = QApplication(sys.argv)
    app.setStyleSheet(DARK_STYLESHEET)
    app.setApplicationName("Archon's Eye")
    app.setApplicationVersion("0.1.0")

    loop = qasync.QEventLoop(app)
    asyncio.set_event_loop(loop)

    controller = Controller()
    window = MainWindow(controller)
    window.show()

    with loop:
        loop.run_forever()


if __name__ == "__main__":
    main()
