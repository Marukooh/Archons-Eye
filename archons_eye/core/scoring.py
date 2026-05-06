"""Scoring engine — assigns piracy-opportunity scores to star systems."""

import logging
import re
from datetime import datetime, timezone
from archons_eye.config import config
from archons_eye.models.system import StarSystem, CommoditySignal

_CAMEL_RE = re.compile(r'(?<=[a-z])(?=[A-Z])')

# Lowercase EDDN internal name → in-game display name.
# Covers both all-lowercase and PascalCase EDDN variants via .lower() lookup.
_DISPLAY_NAMES: dict[str, str] = {
    # Special overrides — in-game name differs from EDDN internal name
    "opal":                  "Void Opal",
    "basicnarcotics":        "Narcotics",
    # Multi-word (EDDN lowercase, camelCase regex can't split)
    "lowtemperaturediamond": "Low Temperature Diamond",
    "progenitorcells":       "Progenitor Cells",
    "performanceenhancers":  "Performance Enhancers",
    "battleweapons":         "Battle Weapons",
    "personalweapons":       "Personal Weapons",
    "reactivearmour":        "Reactive Armour",
    "imperialslaves":        "Imperial Slaves",
    # Industrial / tech (EDDN PascalCase — camelCase split gives wrong result)
    "cmmcomposite":          "CMM Composite",
    "consumertechnology":    "Consumer Technology",
    "computercomponents":    "Computer Components",
    "resonantseparators":    "Resonant Separators",
    "microbialfurnaces":     "Microbial Furnaces",
    "hnshockmount":          "HN Shock Mount",
    "superconductors":       "Superconductors",
    "cryolite":              "Cryolite",
    # Single-word (EDDN sends all-lowercase — capitalise explicitly)
    "painite":       "Painite",
    "platinum":      "Platinum",
    "osmium":        "Osmium",
    "tritium":       "Tritium",
    "gold":          "Gold",
    "palladium":     "Palladium",
    "silver":        "Silver",
    "bertrandite":   "Bertrandite",
    "indite":        "Indite",
    "gallite":       "Gallite",
    "coltan":        "Coltan",
    "tobacco":       "Tobacco",
    "slaves":        "Slaves",
    "rhodplumsite":  "Rhodplumsite",
    "serendibite":   "Serendibite",
    "musgravite":    "Musgravite",
    "benitoite":     "Benitoite",
    "grandidierite": "Grandidierite",
    "alexandrite":   "Alexandrite",
    "taaffeite":     "Taaffeite",
    "monazite":      "Monazite",
    "jadeite":       "Jadeite",
}

def _fmt(name: str) -> str:
    """Return in-game display name. Dict lookup first (handles lowercase EDDN names),
    then camelCase split as fallback for PascalCase variants."""
    return _DISPLAY_NAMES.get(name.lower()) or _CAMEL_RE.sub(' ', name)

log = logging.getLogger(__name__)

# Raw ED security strings → human-readable (matched after .lower())
# Normal security levels use $SYSTEM_SECURITY_* format (from FDevIDs/security.csv)
# Anarchy/Lawless use the $GALAXY_MAP_INFO_state_* format (different ED subsystem)
_SECURITY_MAP: dict[str, str] = {
    "$system_security_high;":            "High",
    "$system_security_medium;":          "Medium",
    "$system_security_low;":             "Low",
    "$galaxy_map_info_state_anarchy;":   "Anarchy",
    "$galaxy_map_info_state_lawless;":   "Anarchy",
}

# Security → bonus points added on top of signal score
_SECURITY_BONUS: dict[str, int] = {
    "Anarchy": 25,
    "Low":     15,
    "Medium":   5,
    "High":     0,
}

# Commodity reference sets — use exact EDDN internal names (PascalCase); stored lowercase.
# EDDN sends commodity names in PascalCase (e.g. "LowTemperatureDiamond", "ProgenitorCells").
# We call sig.commodity.lower() before lookup, so keys here must be lowercase of those names.
_MINER_COMMODITIES: frozenset[str] = frozenset(c.lower() for c in {
    # High-value mineable minerals (EDDN internal names from FDevIDs/commodity.csv)
    "Painite", "Platinum", "Osmium", "Tritium",
    "LowTemperatureDiamond", "Rhodplumsite", "Serendibite",
    "Monazite", "Musgravite", "Benitoite", "Grandidierite",
    "Alexandrite",
    "Opal",          # display name: "Void Opal"
    "Taaffeite",     # rare gem
    "Jadeite",       # rare gem
})

_TRADER_COMMODITIES: frozenset[str] = frozenset(c.lower() for c in {
    # Precious metals — high unit value, classic piracy targets
    "Gold", "Silver", "Palladium", "Tritium",
    # Industrial / tech goods (EDDN names: lowercase, no spaces/symbols)
    "Superconductors", "CMMComposite", "ConsumerTechnology",
    "ComputerComponents", "ResonantSeparators", "MicrobialFurnaces",
    "HNShockMount", "Cryolite",
    # Minerals hauled from markets (not exclusively mined)
    "Bertrandite", "Indite", "Gallite", "Coltan", "Cobalt",
    # Medicines / drugs
    "ProgenitorCells", "PerformanceEnhancers",
    "BasicNarcotics", "Tobacco",
    # Weapons
    "BattleWeapons", "PersonalWeapons", "ReactiveArmour",
    # Slavery
    "ImperialSlaves", "Slaves",
})


def normalise_security(raw: str) -> str:
    """Map raw ED security string to human-readable label."""
    return _SECURITY_MAP.get(raw.lower(), raw) if raw else "Unknown"


def security_bonus(security: str) -> int:
    return _SECURITY_BONUS.get(security, 0)


_MAX_SIGNALS = 3  # max entries per category in miner_signals / trader_signals


def _upsert_signal(sigs: list[tuple[int, str]], score: int, reason: str) -> None:
    """Insert or update a signal in the sorted list (max _MAX_SIGNALS entries).
    Deduplication: entries sharing the same station name are treated as the same slot.
    The list is kept sorted descending by score.
    """
    station = reason.rsplit(" · ", 1)[-1] if " · " in reason else reason
    for i, (s, r) in enumerate(sigs):
        r_station = r.rsplit(" · ", 1)[-1] if " · " in r else r
        if r_station == station:
            if score > s:
                sigs[i] = (score, reason)
                sigs.sort(key=lambda x: x[0], reverse=True)
            return
    sigs.append((score, reason))
    sigs.sort(key=lambda x: x[0], reverse=True)
    if len(sigs) > _MAX_SIGNALS:
        del sigs[_MAX_SIGNALS:]


def score_from_commodity_signal(system: StarSystem, sig: CommoditySignal) -> None:
    commodity = sig.commodity.lower()
    _score_miner(system, sig, commodity)
    _score_trader(system, sig, commodity)


# Per-commodity weight for sell-price scoring.
# Genuine mined minerals score proportionally higher than generic commodities
# that happen to have a sell price. Mirrors the tier structure in HOTSPOT_SCORES.
# Weight W means the commodity hits max score (40 pts) at: 600_000 / W credits.
_MINER_COMMODITY_WEIGHTS: dict[str, float] = {
    "opal":                  2.5,   # Void Opal       — hits max at ~240k
    "lowtemperaturediamond": 2.5,   # LTD             — hits max at ~240k
    "painite":               2.2,   # Painite         — hits max at ~273k
    "platinum":              2.0,   # Platinum        — hits max at ~300k
    "monazite":              2.0,   # Monazite        — hits max at ~300k
    "musgravite":            2.0,   # Musgravite      — hits max at ~300k
    "benitoite":             1.8,   # Benitoite       — hits max at ~333k
    "grandidierite":         1.8,   # Grandidierite   — hits max at ~333k
    "rhodplumsite":          1.8,   # Rhodplumsite    — hits max at ~333k
    "serendibite":           1.8,   # Serendibite     — hits max at ~333k
    "alexandrite":           1.8,   # Alexandrite     — hits max at ~333k
    "taaffeite":             1.8,   # Taaffeite       — hits max at ~333k
    "jadeite":               1.8,   # Jadeite         — hits max at ~333k
    "osmium":                1.4,   # Osmium          — hits max at ~429k
    "tritium":               1.2,   # Tritium         — hits max at ~500k
}


def _score_miner(system: StarSystem, sig: CommoditySignal, commodity: str) -> None:
    if commodity not in _MINER_COMMODITIES or sig.sell_price < 50_000:
        return
    weight = _MINER_COMMODITY_WEIGHTS.get(commodity, 1.0)
    points = min(40, int(sig.sell_price * weight) // 15_000)
    if points <= 0:
        return
    stars = f" {'★' * sig.demand_bracket}" if sig.demand_bracket >= 1 else ""
    reason = f"{_fmt(sig.commodity)} @{sig.sell_price // 1_000}k{stars} · {sig.station_name}"
    _upsert_signal(system.miner_signals, points, reason)
    if points > system.miner_raw:
        system.miner_raw    = points
        system.miner_reason = reason
        log.debug("[Miner %+d] %s — %s sell=%d", points, system.name, commodity, sig.sell_price)
    # Track best sell-price signal separately so the GUI can show it alongside hotspot badges
    if sig.sell_price > system.miner_sell_price:
        system.miner_sell_price  = sig.sell_price
        system.miner_sell_reason = reason


def _score_trader(system: StarSystem, sig: CommoditySignal, commodity: str) -> None:
    if commodity not in _TRADER_COMMODITIES:
        return
    demand_bracket = sig.demand_bracket
    if demand_bracket >= 2 and sig.demand > 0 and sig.sell_price >= 15_000:
        points = 15 + demand_bracket * 10  # bracket 2→35, 3→45
        price_str = f" @{sig.sell_price // 1_000}k" if sig.sell_price > 0 else ""
        reason = f"{_fmt(sig.commodity)}{price_str} {'★' * demand_bracket} · {sig.station_name}"
        _upsert_signal(system.trader_signals, points, reason)
        if points > system.trader_raw:
            system.trader_raw    = points
            system.trader_reason = reason
            log.debug("[Trader %+d] %s — %s demand_bracket=%d", points, system.name, commodity, demand_bracket)


_GOVERNMENT_MAP: dict[str, str] = {
    "$government_anarchy;":     "Anarchy",
    "$government_corporate;":   "Corporate",
    "$government_democracy;":   "Democracy",
    "$government_dictatorship;":"Dictatorship",
    "$government_feudal;":      "Feudal",
    "$government_imperial;":    "Imperial",
    "$government_patronage;":   "Patronage",
    "$government_theocracy;":   "Theocracy",
    "$government_cooperative;": "Cooperative",
    "$government_prison;":      "Prison",
    "$government_engineer;":    "Engineer",
}

# Anarchy government = no courts, no bounty tracking, zero legal consequences for piracy
_GOVERNMENT_BONUS: dict[str, int] = {
    "Anarchy": 15,
}


def normalise_government(raw: str) -> str:
    return _GOVERNMENT_MAP.get(raw.lower(), raw) if raw else "Unknown"


def government_bonus(government: str) -> int:
    return _GOVERNMENT_BONUS.get(government, 0)


def apply_security_bonus(system: StarSystem) -> None:
    """Compute miner/trader/security scores. Idempotent — safe to call every message.

    Security bonus is applied ONCE to security_score (not per signal type) to avoid
    double-counting in systems with both miner and trader signals.
    Government bonus stacks: Anarchy government + Anarchy security = optimal piracy zone.
    """
    has_signal = (system.miner_raw + system.trader_raw) > 0
    system.miner_score  = system.miner_raw + hotspot_density_bonus(system.hotspot_count)
    system.trader_score = system.trader_raw
    if has_signal:
        boom_bonus = 15 if "Boom" in system.system_state else 0
        system.security_score = security_bonus(system.security) + government_bonus(system.government) + boom_bonus
    else:
        system.security_score = 0


def hotspot_density_bonus(count: int) -> int:
    """Bonus for systems with multiple hotspot instances — more hotspots attract more miners.
    +2 pts per hotspot, capped at 14 (reached at 7+ hotspots).
    This stacks on top of the best individual hotspot score already in miner_raw.
    """
    return min(count * 2, 14)


# Ring class (substring of eRingClass_* values, lowercased) → base score.
# Metallic and MetalRich carry the most valuable minerals; Rocky is common but lower value.
_RING_SCORES: dict[str, int] = {
    "metallic":  35,
    "metalrich": 30,
    "icy":       25,
    "rocky":     15,
}

# EDDN hotspot type (lowercased commodity name from SAASignalsFound Signals[].Type) → (score, display name).
# These are the primary miner signal: a CMDR has already probed the body and found a deposit.
# Note: EDDN journal/1 sends plain commodity names (e.g. "Alexandrite"), NOT "$Hotspot_*;" format.
# Public so the controller can use it for hotspot aggregation display.
HOTSPOT_SCORES: dict[str, tuple[int, str]] = {
    "opal":                  (40, "Void Opal"),
    "lowtemperaturediamond": (40, "Low Temp Diamond"),
    "painite":               (38, "Painite"),
    "platinum":              (38, "Platinum"),
    "musgravite":            (36, "Musgravite"),
    "monazite":              (36, "Monazite"),
    "benitoite":             (34, "Benitoite"),
    "grandidierite":         (34, "Grandidierite"),
    "rhodplumsite":          (34, "Rhodplumsite"),
    "serendibite":           (34, "Serendibite"),
    "alexandrite":           (34, "Alexandrite"),
    "taaffeite":             (34, "Taaffeite"),
    "jadeite":               (34, "Jadeite"),
    "osmium":                (30, "Osmium"),
    "tritium":               (28, "Tritium"),
}


def score_from_journal(system: StarSystem, event: str, body: dict) -> None:
    """Update system scores from journal events."""
    if event == "Scan":
        _score_scan(system, body)
    elif event == "SAASignalsFound":
        _score_saa_signals(system, body)
    elif event in ("CargoTransfer", "EjectCargo"):
        # Strong piracy-activity signal: someone is actively being pirated in this system.
        # Boost BOTH miner and trader raw to surface the system regardless of cargo type.
        label = "Cargo ejected" if event == "EjectCargo" else "Cargo transfer"
        reason = f"{label} · piracy active"
        if 20 > system.miner_raw:
            system.miner_raw    = 20
            system.miner_reason = reason
        _upsert_signal(system.miner_signals, 20, reason)
        if 20 > system.trader_raw:
            system.trader_raw    = 20
            system.trader_reason = reason
        _upsert_signal(system.trader_signals, 20, reason)


def _score_scan(system: StarSystem, body: dict) -> None:
    """Score ring types from a Scan event (primary miner signal).
    RingClass values: eRingClass_Metallic, eRingClass_MetalRich, eRingClass_Icy, eRingClass_Rocky.
    Takes the highest-value ring found on the body.
    """
    body_name = body.get("BodyName", "?")
    for ring in body.get("Rings", []):
        ring_class = ring.get("RingClass", "").lower()
        for key, pts in _RING_SCORES.items():
            if key in ring_class:
                ring_name = ring.get("Name", body_name)
                reason    = f"{key.capitalize()} ring · {ring_name}"
                _upsert_signal(system.miner_signals, pts, reason)
                if pts > system.miner_raw:
                    system.miner_raw    = pts
                    system.miner_reason = reason
                    log.debug("[Miner ring %d] %s — %s", pts, system.name, ring_class)
                if pts > system.miner_ring_score:
                    system.miner_ring_score  = pts
                    system.miner_ring_reason = reason
                break  # one ring type matched, move to next ring


def _score_saa_signals(system: StarSystem, body: dict) -> None:
    """Score hotspots from SAASignalsFound (strongest miner signal — body has been probed).
    Signal types arrive as plain commodity names (e.g. "Alexandrite") — lowercased for lookup.
    Multiple hotspots of the same type add a small bonus.
    _ring_names injected by the controller when Scan data for the body is known.
    """
    body_name  = body.get("BodyName", "?")
    ring_names = body.get("_ring_names", [])
    if len(ring_names) == 1:
        location = ring_names[0]
    elif ring_names:
        location = f"{body_name} ({len(ring_names)} rings)"
    else:
        location = body_name

    for sig in body.get("Signals", []):
        t = sig.get("Type", "").lower()
        entry = HOTSPOT_SCORES.get(t)
        if not entry:
            continue
        base_pts, display = entry
        count = int(sig.get("Count", 1))
        pts   = min(base_pts + (count - 1) * 3, base_pts + 9)
        label  = f"×{count}" if count > 1 else "hotspot"
        reason = f"{display} {label} · {location}"
        _upsert_signal(system.miner_signals, pts, reason)
        if pts > system.miner_raw:
            system.miner_raw    = pts
            system.miner_reason = reason
            log.debug("[Miner hotspot %d] %s — %s ×%d", pts, system.name, display, count)


def cmdr_bonus(cmdr_count: int) -> int:
    """Bonus based on unique CMDRs (FSDJump uploaderIDs) seen in the window.
    10 pts per CMDR, capped at 30 (reached at 3+ CMDRs).
    Stacks on top of activity_bonus in the Score column.
    """
    return min(30, cmdr_count * 10)


def _recency_multiplier(system: StarSystem) -> float:
    """Rank fresh systems higher. Applied to sort key only — does not change stored score."""
    age_min = (datetime.now(timezone.utc) - system.last_updated).total_seconds() / 60
    if age_min < 2:   return 1.00
    if age_min < 10:  return 0.90
    if age_min < 20:  return 0.75
    if age_min < 40:  return 0.55
    if age_min < 60:  return 0.35
    return 0.15


def _cmdr_factor(system: StarSystem) -> float:
    """Multiplicative weight for sort key based on unique CMDR count.
    Systems with more commanders present rank higher even at equal scores.
    """
    count = system.cmdr_count
    if count == 0: return 0.60
    if count < 2:  return 0.85
    if count < 4:  return 1.00
    if count < 7:  return 1.25
    return 1.50


def _passes_filters(s: StarSystem, now_dt: datetime, max_age: int, min_score: int) -> bool:
    """Return True if the system passes all active config filters."""
    if s.miner_raw + s.trader_raw == 0:
        return False  # no actual commodity/journal signal — skip pure-activity entries
    if s.security not in config.allowed_security and s.security != "Unknown":
        return False
    if not config.target_miner and s.miner_raw > 0 and s.trader_raw == 0:
        return False
    if not config.target_trader and s.trader_raw > 0 and s.miner_raw == 0:
        return False
    lu = s.last_updated if s.last_updated.tzinfo else s.last_updated.replace(tzinfo=timezone.utc)
    if (now_dt - lu).total_seconds() / 60 > max_age:
        return False
    return s.total_score >= min_score


def filter_systems(systems: list[StarSystem]) -> list[StarSystem]:
    """Apply config filters and return list sorted by recency- and activity-weighted score."""
    now_dt    = datetime.now(timezone.utc)
    max_age   = config.max_system_age_minutes
    min_score = config.alert_score_threshold
    result = [s for s in systems if _passes_filters(s, now_dt, max_age, min_score)]
    return sorted(
        result,
        key=lambda s: s.total_score * _recency_multiplier(s) * _cmdr_factor(s),
        reverse=True,
    )
