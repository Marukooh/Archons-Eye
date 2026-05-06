"""Watches the local Elite Dangerous journal folder for player position updates.

Reads the most recent Journal*.log file and tails it in real-time.
Calls ``on_position(x, y, z, system_name)`` whenever the player jumps to
a new system (FSDJump / CarrierJump) or the game loads (Location).
"""

import asyncio
import json
import logging
from pathlib import Path

log = logging.getLogger(__name__)

# Default journal path on Windows
_DEFAULT_JOURNAL_DIR = (
    Path.home() / "Saved Games" / "Frontier Developments" / "Elite Dangerous"
)

_POSITION_EVENTS = {"FSDJump", "CarrierJump", "Location"}
_CMDR_EVENT      = "LoadGame"


def _find_journal_dir() -> Path | None:
    candidate = _DEFAULT_JOURNAL_DIR
    if candidate.is_dir():
        return candidate
    log.warning("Journal directory not found: %s", candidate)
    return None


def _latest_journal(journal_dir: Path) -> Path | None:
    """Return the most recently modified Journal*.log in the directory."""
    files = sorted(
        journal_dir.glob("Journal.*.log"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return files[0] if files else None


class JournalWatcher:
    """Async watcher — call ``start()`` once from the asyncio event loop."""

    def __init__(self, on_position, on_cmdr=None) -> None:
        """
        Parameters
        ----------
        on_position:
            Callable ``(x, y, z, system_name)`` — called when player jumps.
        on_cmdr:
            Optional callable ``(cmdr_name: str)`` — called when LoadGame is seen.
        """
        self._on_position = on_position
        self._on_cmdr = on_cmdr
        self._running = False
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._running = True
        self._task = asyncio.create_task(self._run(), name="journal-watcher")

    def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _run(self) -> None:
        journal_dir = _find_journal_dir()
        if journal_dir is None:
            log.error("JournalWatcher: journal directory not found, position tracking disabled")
            return

        log.info("JournalWatcher: watching %s", journal_dir)

        current_file: Path | None = None
        file_handle = None
        poll_interval = 1.0  # seconds between checks

        try:
            while self._running:
                latest = _latest_journal(journal_dir)

                # Switched to a newer journal file (game restarted / new session)
                if latest != current_file:
                    if file_handle:
                        file_handle.close()
                    current_file = latest
                    if current_file is None:
                        await asyncio.sleep(poll_interval)
                        continue
                    log.info("JournalWatcher: reading %s", current_file.name)
                    file_handle = open(current_file, encoding="utf-8", errors="replace")
                    # Scan existing content to find the last known position
                    self._scan_existing(file_handle)

                # Tail new lines
                if file_handle:
                    while self._running:
                        line = file_handle.readline()
                        if not line:
                            break
                        self._process_line(line)

                await asyncio.sleep(poll_interval)
        except asyncio.CancelledError:
            raise
        finally:
            if file_handle:
                file_handle.close()

    def _scan_existing(self, fh) -> None:
        """Read the whole file to find the most recent position and CMDR name."""
        last_pos  = None
        last_cmdr = None
        for line in fh:
            ev = self._parse_event(line)
            if ev is None:
                continue
            if ev.get("event") in _POSITION_EVENTS:
                result = self._extract_position(ev)
                if result:
                    last_pos = result
            elif ev.get("event") == _CMDR_EVENT:
                name = ev.get("Commander", "")
                if name:
                    last_cmdr = name
        if last_cmdr and self._on_cmdr:
            self._on_cmdr(last_cmdr)
        if last_pos:
            x, y, z, name = last_pos
            log.info("JournalWatcher: initial position — %s (%.1f, %.1f, %.1f)", name, x, y, z)
            self._on_position(x, y, z, name)

    def _process_line(self, line: str) -> None:
        ev = self._parse_event(line)
        if ev is None:
            return
        event = ev.get("event")
        if event in _POSITION_EVENTS:
            result = self._extract_position(ev)
            if result:
                x, y, z, name = result
                log.info("JournalWatcher: jumped to %s (%.1f, %.1f, %.1f)", name, x, y, z)
                self._on_position(x, y, z, name)
        elif event == _CMDR_EVENT:
            cmdr = ev.get("Commander", "")
            if cmdr and self._on_cmdr:
                log.info("JournalWatcher: commander — %s", cmdr)
                self._on_cmdr(cmdr)

    @staticmethod
    def _parse_event(line: str) -> dict | None:
        line = line.strip()
        if not line:
            return None
        try:
            return json.loads(line)
        except json.JSONDecodeError:
            return None

    @staticmethod
    def _extract_position(ev: dict) -> tuple[float, float, float, str] | None:
        star_pos = ev.get("StarPos")
        name     = ev.get("StarSystem", "")
        if not star_pos or len(star_pos) < 3 or not name:
            return None
        return float(star_pos[0]), float(star_pos[1]), float(star_pos[2]), name
