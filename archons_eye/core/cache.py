"""SQLite-backed local cache for systems and signals."""

import sqlite3
from datetime import datetime

from archons_eye.config import config
from archons_eye.models.system import StarSystem


class Cache:
    def __init__(self) -> None:
        self._conn = sqlite3.connect(config.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._setup()

    def _setup(self) -> None:
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS systems (
                name         TEXT PRIMARY KEY,
                x            REAL DEFAULT 0,
                y            REAL DEFAULT 0,
                z            REAL DEFAULT 0,
                security     TEXT DEFAULT 'Unknown',
                allegiance   TEXT DEFAULT 'Unknown',
                population   INTEGER DEFAULT 0,
                miner_score  INTEGER DEFAULT 0,
                trader_score INTEGER DEFAULT 0,
                last_updated TEXT,
                edsm_checked INTEGER DEFAULT 0
            );
        """)
        self._conn.commit()
        # Migration: add edsm_checked to existing DBs that pre-date this column
        try:
            self._conn.execute("ALTER TABLE systems ADD COLUMN edsm_checked INTEGER DEFAULT 0")
            self._conn.commit()
        except sqlite3.OperationalError:
            pass  # column already exists

    def upsert_systems(self, systems: list[StarSystem]) -> None:
        """Write multiple systems in a single transaction — avoids per-row disk sync."""
        rows = [
            (s.name, s.x, s.y, s.z, s.security, s.allegiance, s.population,
             s.miner_score, s.trader_score, s.last_updated.isoformat(),
             int(s.edsm_checked))
            for s in systems
        ]
        with self._conn:
            self._conn.executemany("""
                INSERT INTO systems
                    (name, x, y, z, security, allegiance, population,
                     miner_score, trader_score, last_updated, edsm_checked)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET
                    x = excluded.x,
                    y = excluded.y,
                    z = excluded.z,
                    security = excluded.security,
                    allegiance = excluded.allegiance,
                    population = excluded.population,
                    miner_score = excluded.miner_score,
                    trader_score = excluded.trader_score,
                    last_updated = excluded.last_updated,
                    edsm_checked = excluded.edsm_checked
            """, rows)

    def get_system(self, name: str) -> "StarSystem | None":
        row = self._conn.execute(
            "SELECT * FROM systems WHERE name = ?", (name,)
        ).fetchone()
        return self._row_to_system(row) if row else None

    @staticmethod
    def _row_to_system(row: sqlite3.Row) -> StarSystem:
        s = StarSystem(name=row["name"])
        s.x, s.y, s.z = row["x"], row["y"], row["z"]
        s.security   = row["security"]
        s.allegiance = row["allegiance"]
        s.population = row["population"]
        # Scores are NOT loaded — they rebuild from live EDDN data each session.
        # This avoids stale/inflated values persisting across restarts.
        s.last_updated  = datetime.fromisoformat(row["last_updated"])
        s.edsm_checked  = bool(row["edsm_checked"])
        return s

    def close(self) -> None:
        self._conn.close()
