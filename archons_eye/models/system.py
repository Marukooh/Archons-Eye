"""Data models for star systems and piracy signals."""

from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class StarSystem:
    name: str
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    security: str = "Unknown"
    allegiance: str = "Unknown"
    population: int = 0
    last_updated: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    government: str = "Unknown"

    # Raw signal scores — commodity/journal only, no bonuses baked in
    miner_raw:  int = 0
    trader_raw: int = 0

    # Display scores — raw signal only (security bonus is tracked separately)
    miner_score:    int = 0
    trader_score:   int = 0
    security_score: int = 0   # applied once regardless of how many signal types are present
    activity_score: int = 0   # session-only, computed from update frequency, not persisted
    activity_count: int = 0   # commodity update count in last 10 min — displayed in table
    cmdr_count: int = 0       # unique uploaderIDs (FSDJump) in last cmdr_window_minutes

    miner_reason:      str = ""  # best miner signal overall (journal or market)
    miner_sell_reason: str = ""  # best commodity sell-price signal (market only)
    miner_sell_price:  int = 0   # raw sell price that produced miner_sell_reason
    miner_ring_reason: str = ""  # best ring scan signal — tracked separately so commodities can't crowd it out
    miner_ring_score:  int = 0
    trader_reason:     str = ""  # best trader signal — used for GUI log
    edsm_checked:  bool = False  # True once EDSM has been queried (even if no data returned)

    # Active states of the controlling faction — session-only, not persisted.
    # Populated from FSDJump Factions data. May contain multiple comma-separated states.
    system_state: str = ""

    # Hotspot aggregation — accumulated across all scanned bodies in the system
    hotspot_count:   int = 0   # total hotspot instances (sum of all Counts across all bodies)
    hotspot_summary: str = ""  # top types, e.g. "Void Opal×3 · Painite×1"

    # All relevant signals — ordered by score descending, max 3 per category.
    # Session-only (not persisted): rebuilt from live EDDN data each session.
    miner_signals: list[tuple[int, str]] = field(default_factory=list, repr=False)
    trader_signals: list[tuple[int, str]] = field(default_factory=list, repr=False)

    @property
    def total_score(self) -> int:
        return self.miner_score + self.trader_score + self.security_score + self.activity_score

    @property
    def reason(self) -> str:
        parts = []
        if self.miner_signals:
            parts.append(self.miner_signals[0][1])
        if self.trader_signals:
            parts.append(self.trader_signals[0][1])
        return " • ".join(parts)

    @property
    def target_type(self) -> str:
        """Based on raw signal scores so security bonus doesn't affect the label."""
        if self.miner_raw > 0 and self.trader_raw > 0:
            return "M+T"
        if self.miner_raw > 0:
            return "Miner"
        if self.trader_raw > 0:
            return "Trader"
        return "—"



@dataclass
class CommoditySignal:
    """A commodity price report received from EDDN commodity/3."""
    system_name: str
    station_name: str
    commodity: str
    sell_price: int      # credits per unit the station pays to players (miners sell here)
    buy_price: int       # credits per unit players pay the station
    stock: int           # units currently in stock at the station
    demand: int          # units the station wants to buy
    demand_bracket: int = 0   # 0=none, 1=low, 2=med, 3=high — key signal for traders
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
