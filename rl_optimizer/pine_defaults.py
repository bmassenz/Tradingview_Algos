"""Parse default inputs from the Pine script so the replica runs exactly what TradingView will run."""
import os
import re

PINE = os.path.join(os.path.dirname(__file__), "..", "trend_core_wae_professional.pine")
LABEL_TO_KEY = {
    "Core Allocation % of Equity": "coreAllocationPct", "EMA Trend Length": "emaLen",
    "Require EMA Slope Up for New Overlay": "useEMASlopeFilter", "Core Trailing Stop %": "coreTrailPct",
    "Core Re-entry Cooldown (bars)": "coreReentryCooldown", "Enable WAE Overlay": "enableOverlay",
    "WAE Fast EMA Length": "fastLen", "WAE Slow EMA Length": "slowLen", "WAE Explosion Length": "waeBBLen",
    "WAE Explosion Threshold (Up/StDev)": "waeBBMult", "WAE Dead-Zone Threshold (Up/StDev)": "deadMult",
    "Use RSI Momentum Filter": "useRSIFilter", "RSI Length": "rsiLen",
    "Minimum RSI for Overlay Entry": "rsiEntryThreshold", "RSI Hard-Exit Threshold": "rsiHardExitThreshold",
    "Use Confirmed Higher-Timeframe WAE Filter": "useHTFWAE", "ATR Length": "atrLen",
    "Initial Overlay Stop: ATR Multiplier": "atrStopMult", "Overlay Initial Risk % of Equity": "overlayRiskPct",
    "Maximum Overlay Risk $": "maxOverlayRiskCash", "Maximum Overlay Notional % of Equity": "maxOverlayNotionalPct",
    "Maximum Combined Gross Exposure % of Equity": "maxGrossExposurePct",
    "Minimum Overlay Quantity": "minOverlayQty", "Tier 1 Target (R)": "tier1R", "Tier 2 Target (R)": "tier2R",
    "Tier 3 Maximum Target (R)": "tier3R", "Enable Tier 3 Breakeven Rule": "useBreakEven",
    "Breakeven Trigger (R)": "breakEvenTriggerR", "Tier 3 ATR Trail Begins at (R)": "trailStartR",
    "Tier 3 ATR Trail Multiplier": "atrTrailMult", "Exit Remaining Overlay on Momentum Loss": "hardExitOnMomentumLoss",
    "Exit Remaining Overlay Below EMA": "hardExitOnTrendLoss", "Exit Overlay When Core Is Flat": "flattenOverlayWithoutCore",
    "Block Overlay Entry on Volatility Shock": "useVolShockFilter", "Shock ATR Fast Length": "volFastLen",
    "Shock ATR Slow Length": "volSlowLen", "Max Fast/Slow ATR Ratio": "volSpikeMax",
    "Block Overlay Entry After Large Gap": "useGapFilter", "Max Signal-Bar Gap (ATR)": "gapAtrMax",
}


def load_defaults(path=PINE):
    src = open(path).read()
    out = {}
    for m in re.finditer(r'input\.(?:int|float|bool)\(\s*([^,]+?),\s*"([^"]+)"', src):
        val, label = m.group(1).strip(), m.group(2)
        key = LABEL_TO_KEY.get(label)
        if key is None:
            continue
        out[key] = 1 if val == "true" else 0 if val == "false" else float(val)
    missing = set(LABEL_TO_KEY.values()) - set(out)
    assert not missing, f"labels not found in Pine: {missing}"
    return out


if __name__ == "__main__":
    import json
    print(json.dumps(load_defaults(), indent=1))
