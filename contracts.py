"""Domain contracts and explicit enums for Phase 1 Long-Short Architecture.

Ensures no implicit string matching (e.g. 'BUY' substring) or ambiguous mode flags.
"""

from enum import Enum


class Environment(str, Enum):
    BINGX_VST = "BINGX_VST"
    BINGX_LIVE = "BINGX_LIVE"


class ExecutionMode(str, Enum):
    LOCAL_PAPER = "LOCAL_PAPER"
    EXCHANGE_DEMO = "EXCHANGE_DEMO"
    EXCHANGE_LIVE = "EXCHANGE_LIVE"


class DirectionMode(str, Enum):
    SHORT = "SHORT"
    LONG = "LONG"
    BOTH = "BOTH"


class ExitPolicy(str, Enum):
    MANUAL_ONLY = "MANUAL_ONLY"
    AUTO_TPSL = "AUTO_TPSL"


class TradeAction(str, Enum):
    OPEN_SHORT = "OPEN_SHORT"
    OPEN_LONG = "OPEN_LONG"
    CLOSE_SHORT = "CLOSE_SHORT"
    CLOSE_LONG = "CLOSE_LONG"
    NO_NEW_RISK = "NO_NEW_RISK"
    NO_CHANGE = "NO_CHANGE"


class PlaybookType(str, Enum):
    PUMP_EXHAUSTION = "PUMP_EXHAUSTION"
    SUPPORT_PULLBACK = "SUPPORT_PULLBACK"
    BREAKDOWN_RETEST = "BREAKDOWN_RETEST"
    FUNDING_SQUEEZE = "FUNDING_SQUEEZE"
    OVERSOLD_REVERSAL = "OVERSOLD_REVERSAL"
    NONE = "NONE"

