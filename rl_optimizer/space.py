"""Parameter search space: maps a PPO action in [-1, 1]^d to strategy inputs.

Risk budget inputs (100% Core allocation, the $65 overlay risk cap, 0.25% risk,
25% overlay notional, 125% gross cap, $26k sizing capital) are account constraints,
not tuned. Allocation is excluded on purpose: with a drawdown-weighted reward the
optimizer otherwise just shrinks the Core, which trades return for drawdown 1:1
without improving the signal.
"""
import math
import numpy as np

# name, low, high, kind ("int", "float", "log", "bool")
SPACE = [
    ("emaLen", 50, 300, "int"),
    ("coreTrailPct", 3.0, 20.0, "float"),
    ("coreReentryCooldown", 0, 20, "int"),
    ("fastLen", 5, 60, "int"),
    ("slowGap", 10, 150, "int"),            # slowLen = fastLen + slowGap
    ("waeBBLen", 10, 60, "int"),
    ("waeBBMult", 0.005, 0.40, "log"),
    ("deadFrac", 0.1, 1.0, "float"),        # deadMult = waeBBMult * deadFrac
    ("rsiLen", 7, 28, "int"),
    ("rsiEntryThreshold", 50.0, 75.0, "float"),
    ("rsiHardExitThreshold", 30.0, 50.0, "float"),
    ("atrLen", 7, 50, "int"),
    ("atrStopMult", 0.75, 4.0, "float"),
    ("tier1R", 0.5, 2.0, "float"),
    ("t2Gap", 0.25, 2.0, "float"),          # tier2R = tier1R + t2Gap
    ("t3Gap", 0.5, 5.0, "float"),           # tier3R = tier2R + t3Gap
    ("breakEvenTriggerR", 0.25, 2.0, "float"),
    ("trailStartR", 0.5, 4.0, "float"),
    ("atrTrailMult", 0.5, 4.0, "float"),
    ("volSpikeMax", 1.1, 3.0, "float"),
    ("gapAtrMax", 0.3, 3.0, "float"),
    ("useVolShockFilter", 0, 1, "bool"),
    ("useGapFilter", 0, 1, "bool"),
    ("useHTFWAE", 0, 1, "bool"),
    ("useEMASlopeFilter", 0, 1, "bool"),
    ("hardExitOnMomentumLoss", 0, 1, "bool"),
    ("useRSIFilter", 0, 1, "bool"),
    ("useBreakEven", 0, 1, "bool"),
]
DIM = len(SPACE)


def decode(action):
    a = np.clip(np.asarray(action, dtype=float), -1.0, 1.0)
    raw = {}
    for x, (name, lo, hi, kind) in zip(a, SPACE):
        u = (x + 1.0) / 2.0
        if kind == "int":
            raw[name] = int(round(lo + u * (hi - lo)))
        elif kind == "float":
            raw[name] = round(lo + u * (hi - lo), 2)
        elif kind == "log":
            raw[name] = round(math.exp(math.log(lo) + u * (math.log(hi) - math.log(lo))), 4)
        else:
            raw[name] = 1 if x > 0 else 0
    return to_strategy(raw)


def to_strategy(raw):
    p = {k: v for k, v in raw.items() if k not in ("slowGap", "deadFrac", "t2Gap", "t3Gap")}
    p["slowLen"] = raw["fastLen"] + raw["slowGap"]
    p["deadMult"] = round(raw["waeBBMult"] * raw["deadFrac"], 4)
    p["tier2R"] = round(raw["tier1R"] + raw["t2Gap"], 2)
    p["tier3R"] = round(p["tier2R"] + raw["t3Gap"], 2)
    p["_raw"] = raw
    return p


def encode(raw):
    """Inverse of decode for a raw dict (used to seed / perturb around a point)."""
    out = []
    for name, lo, hi, kind in SPACE:
        v = raw[name]
        if kind == "bool":
            out.append(0.5 if v else -0.5)
        elif kind == "log":
            out.append((math.log(v) - math.log(lo)) / (math.log(hi) - math.log(lo)) * 2 - 1)
        else:
            out.append((v - lo) / (hi - lo) * 2 - 1)
    return np.clip(np.array(out), -1, 1)


# The original script defaults expressed in the search space (PPO's starting mean)
ORIGINAL_RAW = dict(
    emaLen=150, coreTrailPct=5.0, coreReentryCooldown=0, coreAllocationPct=100.0,
    fastLen=30, slowGap=60, waeBBLen=20, waeBBMult=0.05, deadFrac=0.4, rsiLen=14,
    rsiEntryThreshold=60.0, rsiHardExitThreshold=48.0, atrLen=21, atrStopMult=1.5,
    tier1R=1.0, t2Gap=1.0, t3Gap=2.0, breakEvenTriggerR=0.75, trailStartR=2.0,
    atrTrailMult=1.0, volSpikeMax=1.6, gapAtrMax=1.0, useVolShockFilter=0, useGapFilter=0,
    useHTFWAE=1, useEMASlopeFilter=1, hardExitOnMomentumLoss=1, useRSIFilter=1, useBreakEven=1,
)
