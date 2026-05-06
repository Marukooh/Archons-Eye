"""Application configuration — edit this file to customize behavior."""

import os
import sys
from dataclasses import dataclass, field


def get_app_data_dir() -> str:
    """Return the platform-specific application data directory."""
    if sys.platform == "win32":
        return os.getenv("APPDATA") or os.path.expanduser("~")
    if sys.platform == "darwin":
        return os.path.join(os.path.expanduser("~"), "Library", "Application Support")
    # Linux and other Unix-like
    return os.getenv("XDG_DATA_HOME", os.path.expanduser("~/.local/share"))


APP_NAME = "ArchonsEye"
APP_DATA_DIR = get_app_data_dir()
DB_DIR = os.path.join(APP_DATA_DIR, APP_NAME)
# Ensure the directory exists
os.makedirs(DB_DIR, exist_ok=True)


@dataclass
class Config:
    # EDDN
    eddn_relay: str = "tcp://eddn.edcd.io:9500"
    eddn_timeout_ms: int = 600_000  # 10 min keepalive

    # Scoring thresholds
    alert_score_threshold: int = 60
    max_system_age_minutes: int = 60  # ignore signals older than this

    # Filters
    target_miner: bool = True
    target_trader: bool = True
    allowed_security: list[str] = field(
        default_factory=lambda: ["Anarchy", "Low", "Medium", "High"]
    )

    # CMDR activity window — unique uploaderIDs seen via FSDJump within this period
    cmdr_window_minutes: int = 10

    # SQLite DB path
    db_path: str = os.path.join(DB_DIR, "archons_eye.db")


# Singleton instance
config = Config()