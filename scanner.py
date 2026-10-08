"""Market Scanner and Coexistence Filter for Memecoin Perpetual Swaps."""

from typing import List, Dict, Any, Set, Optional
from pydantic import BaseModel
from client import BingXClient
from config import AppConfig

# Common memecoin symbols and patterns
MEMECOIN_TAGS = {
    "PEPE", "1000PEPE", "DOGE", "SHIB", "1000SHIB", "BONK", "1000BONK",
    "WIF", "FLOKI", "1000FLOKI", "MEME", "BOME", "POPCAT", "BRETT",
    "NEIRO", "MOODENG", "GOAT", "PNUT", "ACT", "MEW", "TURBO",
    "BABYDOGE", "1000000BABYDOGE", "MYRO", "SLERF", "CAT", "1000CAT"
}

class CandidatePair(BaseModel):
    symbol: str
    last_price: float
    price_change_percent: float
    volume_24h_usdt: float
    bid1: float
    ask1: float
    spread_percent: float
    contract_info: Dict[str, Any]

class MarketScanner:
    def __init__(self, client: BingXClient, config: AppConfig):
        self.client = client
        self.config = config

    def get_occupied_symbols(self) -> Set[str]:
        """
        Retrieves all symbols that currently have active positions or pending orders.
        Guarantees coexistence: Agent will NEVER select an occupied pair.
        """
        occupied: Set[str] = set()

        # Check positions
        try:
            positions = self.client.get_positions()
            for p in positions:
                # BingX position has positionAmt or net quantity
                amt = float(p.get("positionAmt", p.get("initialMargin", 0)))
                if amt != 0:
                    occupied.add(p.get("symbol", ""))
        except Exception:
            pass

        # Check open orders
        try:
            orders = self.client.get_open_orders()
            for o in orders:
                occupied.add(o.get("symbol", ""))
        except Exception:
            pass

        return {s for s in occupied if s}

    def scan_universe(
        self,
        mode: Optional[str] = None,
        min_pump_pct: Optional[float] = None,
        limit_candidates: int = 5,
        direction: str = "SHORT"
    ) -> List[CandidatePair]:
        """
        Scans perpetual contracts based on selected universe mode:
        - PUMP_GAINERS: Scans all altcoin perpetuals (excluding majors and non-crypto NC symbols),
          filtering for positive gainers above min_pump_pct, high volume, tight spread.
        - MEME_ONLY: Restricts universe to memecoin tags.
        """
        active_mode = (mode or self.config.universe_mode).upper()
        dir_norm = (direction or "SHORT").upper()
        min_pump = min_pump_pct if min_pump_pct is not None else self.config.min_pump_percent
        blacklist = set(self.config.majors_blacklist)

        occupied_symbols = self.get_occupied_symbols()
        contracts = self.client.get_contracts()
        tickers = self.client.get_tickers()

        ticker_map = {t.get("symbol"): t for t in tickers if "symbol" in t}
        candidates: List[CandidatePair] = []

        for c in contracts:
            symbol = c.get("symbol", "")
            if not symbol.endswith("-USDT"):
                continue

            # Exclude traditional non-crypto FX/commodities/indices (prefixed with NC)
            if symbol.startswith("NC"):
                continue

            if str(c.get("apiStateOpen", "")).lower() != "true":
                continue

            # Check coexistence rule
            if symbol in occupied_symbols:
                continue

            # Mode-specific filtering
            base_asset = symbol.split("-")[0].upper()
            if active_mode == "MEME_ONLY":
                is_meme = any(tag in base_asset for tag in MEMECOIN_TAGS)
                if not is_meme:
                    continue
            elif active_mode == "PUMP_GAINERS":
                if symbol in blacklist or base_asset in {"BTC", "ETH", "SOL", "BNB"}:
                    continue

            t = ticker_map.get(symbol)
            if not t:
                continue

            try:
                last_price = float(t.get("lastPrice", 0))
                price_change = float(t.get("priceChangePercent", 0))
                volume_usdt = float(t.get("volume", t.get("quoteVolume", 0))) * last_price if "volume" in t else float(t.get("quoteVolume", 0))
                bid1 = float(t.get("bidPrice", t.get("bid1Price", last_price)))
                ask1 = float(t.get("askPrice", t.get("ask1Price", last_price)))
            except (ValueError, TypeError):
                continue

            if last_price <= 0 or bid1 <= 0:
                continue

            # Filter out crazy launch anomalies (>500% usually indicates new pair re-denomination in demo)
            dir_norm = direction.upper()
            if dir_norm == "LONG":
                # Healthy pullbacks can occur between -20.0% and +40.0%
                if price_change > 40.0 or price_change < -20.0:
                    continue
            elif dir_norm == "BOTH":
                # Multi-strategy supports both exhaustion (+gainers) and breakdown/pullback (-losers)
                if price_change > 500.0 or price_change < -30.0:
                    continue
            else:  # SHORT
                # If explicit positive min_pump is requested, enforce it; otherwise allow breakdown setups down to -25.0%
                cutoff = min_pump if (min_pump is not None and min_pump > 0.0) else -25.0
                if price_change > 500.0 or price_change < cutoff:
                    continue

            if volume_usdt < self.config.min_volume_24h_usdt:
                continue

            spread_pct = ((ask1 - bid1) / bid1) * 100.0 if bid1 > 0 else 999.0
            if spread_pct > self.config.max_spread_pct:
                continue

            candidates.append(CandidatePair(
                symbol=symbol,
                last_price=last_price,
                price_change_percent=price_change,
                volume_24h_usdt=volume_usdt,
                bid1=bid1,
                ask1=ask1,
                spread_percent=round(spread_pct, 4),
                contract_info=c
            ))

        # Direction-aware ranking and balanced discovery
        if dir_norm == "LONG":
            # Favor healthy pullbacks (small absolute distance to mild baseline), not unconditional biggest losers
            candidates.sort(key=lambda x: (abs(x.price_change_percent), -x.volume_24h_usdt))
            return candidates[:limit_candidates]
        elif dir_norm == "BOTH":
            # Balanced discovery for BOTH mode: interleave top short candidates and top long pullbacks, deduped
            cutoff = min_pump if (min_pump is not None and min_pump > 0.0) else -25.0
            short_pool = [c for c in candidates if c.price_change_percent >= cutoff]
            short_pool.sort(key=lambda x: (-x.price_change_percent, -x.volume_24h_usdt))

            long_pool = [c for c in candidates if -20.0 <= c.price_change_percent <= 40.0]
            long_pool.sort(key=lambda x: (abs(x.price_change_percent), -x.volume_24h_usdt))

            seen_symbols: Set[str] = set()
            balanced: List[CandidatePair] = []
            max_len = max(len(short_pool), len(long_pool))
            for i in range(max_len):
                if i < len(short_pool):
                    s_cand = short_pool[i]
                    if s_cand.symbol not in seen_symbols:
                        seen_symbols.add(s_cand.symbol)
                        balanced.append(s_cand)
                        if len(balanced) == limit_candidates:
                            break
                if i < len(long_pool):
                    l_cand = long_pool[i]
                    if l_cand.symbol not in seen_symbols:
                        seen_symbols.add(l_cand.symbol)
                        balanced.append(l_cand)
                        if len(balanced) == limit_candidates:
                            break
            return balanced
        else:  # SHORT
            # Sort by price change descending (highest pumpers first for short exhaustion)
            candidates.sort(key=lambda x: (-x.price_change_percent, -x.volume_24h_usdt))
            return candidates[:limit_candidates]

    def scan_memecoins(self, limit_candidates: int = 5) -> List[CandidatePair]:
        """Convenience alias for MEME_ONLY scan mode."""
        return self.scan_universe(mode="MEME_ONLY", limit_candidates=limit_candidates)
