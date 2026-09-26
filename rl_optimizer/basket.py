"""The traded basket and its per-symbol Core settings (decided 2026-09-26, see tv_verify/BASKET.md).

Everything not listed keeps the defaults parsed from trend_core_professional.pine (Core only).
In TradingView, set the same inputs on each symbol's chart: SPY keeps the defaults; QQQ sets
"Tighten Trail After Gain %" = 30 and "Tightened Trailing Stop %" = 10; SMH additionally sets
"Core Allocation % of Equity" = 80.
"""
BASKET = {
    "SPY": {},
    "QQQ": {"trailTightenTriggerPct": 30.0, "trailTightPct": 10.0},
    "SMH": {"coreAllocationPct": 80.0, "trailTightenTriggerPct": 30.0, "trailTightPct": 10.0},
}
