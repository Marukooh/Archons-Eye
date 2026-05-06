"""Central controller — ties together EDDN listener, scoring, cache, and GUI."""

import asyncio
import logging
import time
from collections import deque
from datetime import datetime, timedelta, timezone

import httpx

from archons_eye.config import config
from archons_eye.core.cache import Cache
from archons_eye.core.eddn_listener import (
    EDDNListener, schema_of,
    SCHEMA_COMMODITY, SCHEMA_JOURNAL,
    parse_commodity, parse_journal,
)
from archons_eye.core.edsm_client import fetch_systems
from archons_eye.core.journal_watcher import JournalWatcher
from archons_eye.core.scoring import (
    score_from_commodity_signal, score_from_journal,
    apply_security_bonus,
    normalise_security, normalise_government, cmdr_bonus,
    HOTSPOT_SCORES,
)
from archons_eye.models.system import StarSystem, CommoditySignal

log = logging.getLogger(__name__)

_LOG_INTERVAL = 3.0   # min seconds between GUI log entries per system
_DB_FLUSH_INTERVAL = 60  # seconds between SQLite persistence flushes


def _extract_faction_state(body: dict) -> str:
    """Return the active state string of the controlling faction, or '' if none."""
    controlling = body.get("SystemFaction") or {}
    controlling_name = controlling.get("Name", "")
    for f in body.get("Factions", []):
        if f.get("Name") != controlling_name:
            continue
        active = [s.get("State", "") for s in f.get("ActiveStates", []) if s.get("State")]
        if active:
            return ", ".join(active)
        fs = f.get("FactionState", "")
        if fs and fs != "None":
            return fs
        break
    # Fallback: SystemFaction.FactionState is present even when Factions list is absent
    fs = controlling.get("FactionState", "")
    return fs if fs and fs != "None" else ""


class Controller:
    def __init__(self) -> None:
        self._cache = Cache()
        self._listener = EDDNListener(on_message=self._handle_message)
        self._systems: dict[str, StarSystem] = {}
        self._dirty: set[str] = set()  # systems with unsaved score changes
        self._stopped = False

        self.on_log = None

        self._prune_task: asyncio.Task | None = None
        self._listener_task: asyncio.Task | None = None
        self._lookup_task: asyncio.Task | None = None

        self._last_log_per_system: dict[str, float] = {}

        # EDSM lookup state — all accessed only from the asyncio thread
        self._lookup_queue: asyncio.Queue[str] = asyncio.Queue()
        self._lookup_queued: set[str] = set()   # in queue or being fetched
        self._lookup_done: set[str]   = set()   # fetched (or confirmed not in EDSM)

        # Activity tracking — monotonic timestamps of recent commodity updates per system.
        # Deduplication: we record at most one update per (system, station) per 60s to
        # suppress the 3-5 duplicate uploads that different EDDN clients generate for the
        # same station scan.  maxlen=300 covers 5 updates/min × 60 min with headroom.
        self._update_times: dict[str, deque[float]] = {}

        # CMDR tracking — uploaderID → last FSDJump timestamp per system.
        # Unique uploaderIDs in the last cmdr_window_minutes give the best available
        # estimate of distinct CMDRs active in a system from EDDN data.
        self._cmdr_seen: dict[str, dict[str, float]] = {}

        # Ring name cache — body_name → (system_name, ring_names) from Scan events.
        # Stores system_name so stale entries can be pruned alongside their system.
        self._body_rings: dict[str, tuple[str, list[str]]] = {}

        # Per-body hotspot data — body_name → (system_name, {hotspot_type_key: count}).
        # Keyed by body so re-scanning the same body replaces old data instead of adding to it.
        self._body_hotspot_data: dict[str, tuple[str, dict[str, int]]] = {}

        # Player position — updated by the local journal watcher.
        self.player_pos: tuple[float, float, float] | None = None
        self.player_system: str = ""
        self.player_cmdr: str = ""
        self._journal_watcher = JournalWatcher(
            on_position=self._on_player_position,
            on_cmdr=self._on_cmdr,
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start_journal_watcher(self) -> None:
        """Start the local journal watcher independently of the EDDN connection."""
        self._journal_watcher.start()

    async def start(self) -> None:
        log.info("Controller starting")
        self._listener_task = asyncio.create_task(self._listener.run(), name="eddn-listener")
        self._prune_task    = asyncio.create_task(self._flush_loop(),   name="flush-loop")
        self._lookup_task   = asyncio.create_task(self._lookup_worker(), name="edsm-lookup")
        self._journal_watcher.start()  # no-op if already running
        await asyncio.sleep(0)

    async def stop(self) -> None:
        self._stopped = True
        self._listener.stop()
        # Journal watcher keeps running — CMDR/system display stays live after STOP
        # Cancel background tasks and wait for the listener to fully drain
        for task in (self._listener_task, self._prune_task, self._lookup_task):
            if task:
                task.cancel()
        if self._listener_task:
            await asyncio.gather(self._listener_task, return_exceptions=True)
        self._db_flush()  # persist on exit
        self._cache.close()
        log.info("Controller stopped")

    # ------------------------------------------------------------------
    # EDDN message handler — runs on the asyncio/Qt main thread
    # Keep this as lightweight as possible; no blocking I/O here.
    # ------------------------------------------------------------------

    def _handle_message(self, msg: dict) -> None:
        if self._stopped:
            return
        schema = schema_of(msg)
        if schema == SCHEMA_COMMODITY:
            self._process_commodity(msg)
        elif schema == SCHEMA_JOURNAL:
            self._process_journal(msg)
        # No sleep here — yielding to Qt happens once per batch in EDDNListener.run()

    def _process_commodity(self, msg: dict) -> None:
        parsed = parse_commodity(msg)
        if not parsed:
            return
        system_name, station_name, commodities, uploader_id = parsed
        if uploader_id:
            self._record_cmdr(system_name, uploader_id)

        system = self._get_or_create(system_name)
        before = system.total_score

        for entry in commodities:
            sig = CommoditySignal(
                system_name=system_name,
                station_name=station_name,
                commodity=entry.get("name", ""),
                sell_price=int(entry.get("sellPrice") or 0),
                buy_price=int(entry.get("buyPrice") or 0),
                stock=int(entry.get("stock") or 0),
                demand=int(entry.get("demand") or 0),
                demand_bracket=int(entry.get("demandBracket") or 0),
            )
            score_from_commodity_signal(system, sig)

        system.last_updated = datetime.now(timezone.utc)
        apply_security_bonus(system)
        self._record_update(system_name)

        if system.total_score != before:
            self._dirty.add(system_name)
            if system.total_score > 0:
                self._gui_log(system_name, f"Commodity: {system_name} [{station_name}] — score {system.total_score}")

    def _process_journal(self, msg: dict) -> None:
        parsed = parse_journal(msg)
        if not parsed:
            return
        system_name, event, body, uploader_id = parsed

        system = self._get_or_create(system_name)
        before = system.total_score
        body   = self._preprocess_journal(system, system_name, event, body, uploader_id)

        # FSS events — count uploader as active CMDR in the system
        if event in ("FSSDiscoveryScan", "FSSAllBodiesFound", "FSSSignalFound") and uploader_id:
            self._record_cmdr(system_name, uploader_id)

        score_from_journal(system, event, body)
        if event == "SAASignalsFound":
            self._update_hotspot_data(system, body)
        self._record_update(system_name)
        system.last_updated = datetime.now(timezone.utc)
        apply_security_bonus(system)

        if system.total_score != before:
            self._dirty.add(system_name)
            if system.total_score > 0:
                self._gui_log(system_name, f"Journal [{event}]: {system_name} — score {system.total_score}")

    # ------------------------------------------------------------------
    # Background flush loop — SQLite writes happen here, off the hot path
    # ------------------------------------------------------------------

    async def _flush_loop(self) -> None:
        while True:
            await asyncio.sleep(_DB_FLUSH_INTERVAL)
            self._db_flush()
            self._prune_stale()

    def _db_flush(self) -> None:
        """Persist dirty systems to SQLite. Called periodically, not per-message."""
        if not self._dirty:
            return
        count = len(self._dirty)
        systems = [self._systems[n] for n in self._dirty if n in self._systems]
        self._dirty.clear()
        if systems:
            self._cache.upsert_systems(systems)
        log.debug("DB flush: %d systems persisted", count)

    def _prune_stale(self) -> None:
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=config.max_system_age_minutes)
        stale = [n for n, s in self._systems.items() if s.last_updated < cutoff]
        for name in stale:
            del self._systems[name]
            self._dirty.discard(name)
            self._update_times.pop(name, None)
            self._cmdr_seen.pop(name, None)
        if stale:
            log.info("Pruned %d stale systems", len(stale))
            self._cache.delete_systems(stale)
        # Prune unbounded dicts so memory doesn't grow across long sessions
        stale_set = set(stale)
        self._last_log_per_system = {k: v for k, v in self._last_log_per_system.items() if k not in stale_set}
        self._lookup_done -= stale_set
        stale_bodies = [b for b, (sname, _) in self._body_hotspot_data.items() if sname in stale_set]
        for b in stale_bodies:
            del self._body_hotspot_data[b]
        stale_rings = [b for b, (sname, _) in self._body_rings.items() if sname in stale_set]
        for b in stale_rings:
            del self._body_rings[b]
        # Evict uploader entries older than the window from active systems
        window_s = config.cmdr_window_minutes * 60
        now_m    = time.monotonic()
        for seen in self._cmdr_seen.values():
            stale_uids = [uid for uid, t in seen.items() if now_m - t > window_s]
            for uid in stale_uids:
                del seen[uid]

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_or_create(self, name: str) -> StarSystem:
        if name not in self._systems:
            cached = self._cache.get_system(name)
            self._systems[name] = cached if cached else StarSystem(name=name)
        system = self._systems[name]
        if system.security == "Unknown" and not system.edsm_checked:
            self._enqueue_lookup(name)
        return system

    # ------------------------------------------------------------------
    # EDSM background lookup — resolves security/allegiance for new systems
    # ------------------------------------------------------------------

    def _preprocess_journal(
        self, system: "StarSystem", system_name: str, event: str, body: dict, uploader_id: str
    ) -> dict:
        """Handle per-event side-effects and return (possibly enriched) body dict."""
        if event in ("FSDJump", "Location", "CarrierJump"):
            self._apply_fsd_jump(system, system_name, body, uploader_id)
        elif event == "Scan":
            self._cache_ring_names(system_name, body)
        elif event == "SAASignalsFound":
            body = self._inject_ring_names(body)
        return body

    def _apply_fsd_jump(
        self, system: "StarSystem", system_name: str, body: dict, uploader_id: str
    ) -> None:
        if uploader_id:
            self._record_cmdr(system_name, uploader_id)
        # EDDN strips _Localised fields — map the raw ED security/government strings ourselves
        raw_sec = body.get("SystemSecurity", "")
        raw_gov = body.get("SystemGovernment", "")
        system.security   = normalise_security(raw_sec)   if raw_sec else system.security
        system.government = normalise_government(raw_gov) if raw_gov else system.government
        system.allegiance = body.get("SystemAllegiance") or system.allegiance
        system.population = body.get("Population", system.population)
        x, y, z = body.get("StarPos", [system.x, system.y, system.z])
        system.x, system.y, system.z = x, y, z
        new_state = _extract_faction_state(body)
        if new_state:
            system.system_state = new_state
        log.debug("[State] %s — controlling=%r state=%r factions=%d",
                  system_name,
                  (body.get("SystemFaction") or {}).get("Name", ""),
                  new_state,
                  len(body.get("Factions", [])))

    def _cache_ring_names(self, system_name: str, body: dict) -> None:
        body_name = body.get("BodyName", "")
        rings     = body.get("Rings", [])
        if body_name and rings:
            self._body_rings[body_name] = (system_name, [r["Name"] for r in rings if r.get("Name")])

    def _inject_ring_names(self, body: dict) -> dict:
        body_name = body.get("BodyName", "")
        entry     = self._body_rings.get(body_name)
        if entry:
            return {**body, "_ring_names": entry[1]}
        return body

    def _update_hotspot_data(self, system: StarSystem, body: dict) -> None:
        """Store per-body hotspot counts and recompute system totals.
        Keyed by BodyName so a re-scan of the same body replaces old data.
        """
        body_name = body.get("BodyName", "")
        all_signals = body.get("Signals", [])
        log.debug(
            "SAASignalsFound: %s / %s — %d signal(s): %s",
            system.name,
            body_name or "(no BodyName)",
            len(all_signals),
            [s.get("Type") for s in all_signals],
        )
        if not body_name:
            return
        new_data: dict[str, int] = {}
        for sig in all_signals:
            t = sig.get("Type", "").lower()
            if t in HOTSPOT_SCORES:
                new_data[t] = int(sig.get("Count", 1))
        if not new_data:
            return
        self._body_hotspot_data[body_name] = (system.name, new_data)
        self._recompute_system_hotspots(system)
        self._gui_log(
            system.name,
            f"Hotspot: {system.name} [{body_name}] — {system.hotspot_count} hotspot(s): {system.hotspot_summary}",
        )

    def _recompute_system_hotspots(self, system: StarSystem) -> None:
        """Aggregate hotspot counts across all scanned bodies for this system."""
        totals: dict[str, int] = {}
        for _body, (sname, data) in self._body_hotspot_data.items():
            if sname == system.name:
                for t, count in data.items():
                    totals[t] = totals.get(t, 0) + count
        system.hotspot_count = sum(totals.values())
        if totals:
            sorted_types = sorted(
                totals.items(),
                key=lambda x: (HOTSPOT_SCORES[x[0]][0], x[1]),
                reverse=True,
            )[:3]
            system.hotspot_summary = " · ".join(
                f"{HOTSPOT_SCORES[t][1]}×{c}" for t, c in sorted_types
            )
        else:
            system.hotspot_summary = ""

    def _on_player_position(self, x: float, y: float, z: float, system_name: str) -> None:
        self.player_pos = (x, y, z)
        self.player_system = system_name

    def _on_cmdr(self, name: str) -> None:
        self.player_cmdr = name

    def _record_update(self, system_name: str) -> None:
        self._update_times.setdefault(system_name, deque(maxlen=2000)).append(time.monotonic())

    def _record_cmdr(self, system_name: str, uploader_id: str) -> None:
        """Record a CMDR FSDJump into a system, keyed by EDDN uploaderID."""
        self._cmdr_seen.setdefault(system_name, {})[uploader_id] = time.monotonic()

    def _enqueue_lookup(self, name: str) -> None:
        if name not in self._lookup_queued and name not in self._lookup_done:
            self._lookup_queued.add(name)
            self._lookup_queue.put_nowait(name)

    _BATCH_SIZE    = 50   # max systems per EDSM request
    _BATCH_WINDOW  = 10.0 # seconds to wait accumulating names before firing

    async def _collect_batch(self) -> list[str]:
        """Wait up to _BATCH_WINDOW seconds to accumulate a full batch of _BATCH_SIZE names.
        Returns as soon as the batch is full or the window expires (whichever comes first).
        Always returns at least one name (blocks until one arrives).
        """
        names: list[str] = [await self._lookup_queue.get()]
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self._BATCH_WINDOW
        while len(names) < self._BATCH_SIZE:
            remaining = deadline - loop.time()
            if remaining <= 0:
                break
            try:
                name = await asyncio.wait_for(self._lookup_queue.get(), timeout=remaining)
                names.append(name)
            except asyncio.TimeoutError:
                break
        return names

    async def _lookup_worker(self) -> None:
        async with httpx.AsyncClient(
            headers={"User-Agent": "Elite-Scouterous/1.0"},
            timeout=httpx.Timeout(15.0),
        ) as client:
            while True:
                names = await self._collect_batch()
                await self._fetch_and_apply(client, names)
                await asyncio.sleep(2.0)  # polite delay between requests

    async def _fetch_and_apply(self, client: httpx.AsyncClient, names: list[str]) -> None:
        try:
            results = await fetch_systems(client, names)
        except httpx.HTTPStatusError as exc:
            await self._handle_edsm_http_error(exc, names)
            return
        except Exception as exc:
            # Network error (timeout, connection refused, etc.) — don't mark as edsm_checked,
            # just release from the queued set so they can be re-enqueued on the next EDDN message.
            log.warning("EDSM batch failed: %s — will retry on next activity", exc)
            for n in names:
                self._lookup_queued.discard(n)
            return

        found: set[str] = set()
        for data in results:
            self._apply_edsm(data)
            found.add(data.get("name", ""))
        for n in names:
            if n not in found:
                self._mark_edsm_checked(n)
        log.debug("EDSM: %d/%d systems resolved", len(found), len(names))

    async def _handle_edsm_http_error(self, exc: httpx.HTTPStatusError, names: list[str]) -> None:
        if exc.response.status_code == 429:
            wait = int(exc.response.headers.get("Retry-After", "60"))
            log.warning("EDSM: 429 rate-limited — waiting %ds, will retry %d systems", wait, len(names))
            await asyncio.sleep(wait)
            for n in names:
                self._lookup_queued.discard(n)
                if n not in self._lookup_done:
                    self._lookup_queue.put_nowait(n)
                    self._lookup_queued.add(n)
        else:
            log.warning("EDSM HTTP %d — skipping %d systems", exc.response.status_code, len(names))
            for n in names:
                self._lookup_queued.discard(n)
                self._lookup_done.add(n)

    def _mark_edsm_checked(self, name: str) -> None:
        """Mark a system as EDSM-checked so it isn't re-queried next session."""
        self._lookup_queued.discard(name)
        self._lookup_done.add(name)
        if name in self._systems:
            self._systems[name].edsm_checked = True
            self._dirty.add(name)

    def _apply_edsm(self, data: dict) -> None:
        name   = data.get("name", "")
        system = self._systems.get(name)
        self._lookup_queued.discard(name)
        self._lookup_done.add(name)
        if not system:
            return
        info   = data.get("information", {})
        coords = data.get("coords", {})
        if info.get("security"):
            system.security = info["security"]
        if info.get("allegiance"):
            system.allegiance = info["allegiance"]
        if info.get("population") is not None:
            system.population = info["population"]
        if coords:
            system.x = coords.get("x", system.x)
            system.y = coords.get("y", system.y)
            system.z = coords.get("z", system.z)
        system.edsm_checked = True  # don't re-query this system next session
        self._dirty.add(name)

    def get_top_systems(self, limit: int = 50) -> list[StarSystem]:
        from archons_eye.core.scoring import filter_systems
        now         = time.monotonic()
        upd_cutoff  = now - 600                              # 10-minute window for updates
        cmdr_cutoff = now - config.cmdr_window_minutes * 60  # window for unique CMDRs
        for name, system in self._systems.items():
            q      = self._update_times.get(name)
            recent = sum(1 for t in q if t > upd_cutoff) if q else 0
            system.activity_count = recent
            seen              = self._cmdr_seen.get(name, {})
            system.cmdr_count = sum(1 for t in seen.values() if t > cmdr_cutoff)
            system.activity_score = cmdr_bonus(system.cmdr_count)
        return filter_systems(list(self._systems.values()))[:limit]

    def _gui_log(self, system_name: str, message: str) -> None:
        """Rate-limited GUI log — at most one entry per system per _LOG_INTERVAL."""
        now = time.monotonic()
        if now - self._last_log_per_system.get(system_name, 0.0) < _LOG_INTERVAL:
            return
        self._last_log_per_system[system_name] = now
        log.info(message)
        if self.on_log:
            self.on_log(message)
