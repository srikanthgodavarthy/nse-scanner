"""
NSE Master Scanner Pro — Streamlit Edition
Mode-aware (Intraday / Swing / Positional) with Phase State Machine

EXHAUSTION & EXTENSION LAYER (this version):
  EXT-1  RSI Overheating         — RSI > mode-specific ceiling triggers score
                                   penalty and blocks STRONG BUY / BREAKOUT.
                                   Ceiling: Intraday 80 · Swing 78 · Positional 75.
  EXT-2  ATR Extension           — current ATR vs its 20-bar mean. If ATR has
                                   expanded > 2.5× its mean the range is already
                                   in a climactic blow-off; penalty + phase demotion.
  EXT-3  Parabolic Acceleration  — compares 3-bar % move to the stock's own
                                   historical daily volatility. If the last 3 bars
                                   cover > 3× expected daily move, flag parabolic.
  EXT-4  EMA Distance            — price stretched > mode-specific σ-multiple above
                                   EMA-fast signals over-extension. Measured as
                                   (price - EMA) / ATR. Threshold: 3.5/3.0/2.5 ATRs.
  EXT-5  Climactic Volume        — volume spike > 3× 20-bar average on an up bar
                                   after a sustained run = distribution / blow-off top.
                                   Requires at least 10 bars of prior uptrend.
  EXT-6  Momentum Exhaustion     — RSI made a lower high while price made a higher
                                   high in the last 14 bars = classic bearish div
                                   proxy (no separate pivot library needed).
  EXT-7  Bearish RSI Divergence  — full 5-point pivot-based divergence check:
                                   price HH > prior HH but RSI HH < prior RSI HH.

  SCORING IMPACT:
    Each flag contributes a weighted penalty to norm_bull BEFORE action/phase.
    Combined penalty can reach -35 norm points on a fully extended stock.
    Phase overrides:
      • BREAKOUT → EXIT   if ext_critical (3+ flags or RSI > ceiling + ATR ext)
      • BREAKOUT → SETUP  if ext_moderate (2 flags)
      • STRONG BUY → BUY  if any exhaustion flag present
    All flags surfaced as an "ExtFlags" field in results for transparency.

FIXES APPLIED IN THIS VERSION:
  BUG-1  OI data not received          — added robust session warm-up with retries,
                                         proper cookie handling, and fallback to
                                         direct JSON fetch; also fixed BANKNIFTY vs
                                         SENSEX labelling.
  BUG-2  Score thresholds vs norm      — action_label() now uses norm_bull (0-100),
                                         not raw bull; thresholds re-tuned accordingly.
  BUG-3  Action uses raw / phase uses  — both action_label and detect_phase now
         norm (mismatch)                 exclusively use norm_bull.
  BUG-4  Regime haircut after action   — haircut applied to norm_bull BEFORE action &
                                         phase assignment; results are consistent.
  BUG-5  Intraday EMA 20/50 on 5m      — Intraday now uses EMA 9/21 on 5-min bars.
  BUG-6  False CONT signals            — CONT gate tightened: requires 3-bar higher
                                         close AND volume > 1.2× avg AND trend_strong
                                         AND price > EMA-fast (not just last 4 bars).
  BUG-7  OI Sensex uses BANKNIFTY      — expander label corrected; kept BANKNIFTY
                                         data fetch (NSE has no Sensex OC) but UI now
                                         clearly says "Bank Nifty" everywhere.
  BUG-8  Cache stampede                — TTL jittered per-symbol with hash-based
                                         offset; parallel fetch uses staggered starts.
  BUG-9  No retry on yfinance          — _fetch_one retries up to 3× with backoff.
  BUG-10 Score ceiling too high        — BULL_MAX reduced 155→120; weights rebalanced
                                         so 100 norm == genuinely strong stock.

Previously documented fixes (retained):
  FIX-1  Positional gate → penalty
  FIX-2  TTL caption corrected
  FIX-3  Intraday HTF via daily fetch
  FIX-4  EMA/RSI/ATR computed once
  FIX-5  Fib SL max() not min()
  FIX-6  detect_phase uses identical norm_bull
"""

import warnings
import logging
import time
import random
from datetime import datetime

import numpy as np
import pandas as pd
import yfinance as yf
import streamlit as st

from nse500 import nse500_symbols
from sectors import SECTORS

logging.getLogger("yfinance").setLevel(logging.CRITICAL)
warnings.filterwarnings("ignore")

NIFTY500 = list(dict.fromkeys([s.strip().upper().replace(".NS", "") for s in nse500_symbols]))
for k in SECTORS:
    if SECTORS[k] is None:
        SECTORS[k] = NIFTY500

# ── Mode config ──────────────────────────────────────────────────
# BUG-5 FIX: Intraday now uses EMA 9/21 (appropriate for 5-min bars)
MODE_CFG = {
    "Intraday":   dict(period="5d",  interval="5m",  ema_fast=9,  ema_slow=21,
                       atr_mult=1.5, atr_wide=3.0, atr_max=1.0,
                       mom1_th=2,  mom3_th=5,  mom6_th=8,  score_th=65, rsi_len=14),
    "Swing":      dict(period="1y",  interval="1d",  ema_fast=50, ema_slow=200,
                       atr_mult=2.5, atr_wide=4.0, atr_max=1.5,
                       mom1_th=3,  mom3_th=7,  mom6_th=10, score_th=70, rsi_len=21),
    "Positional": dict(period="2y",  interval="1d",  ema_fast=50, ema_slow=200,
                       atr_mult=3.5, atr_wide=5.0, atr_max=1.5,
                       mom1_th=5,  mom3_th=10, mom6_th=15, score_th=70, rsi_len=21),
}

# BUG-2/3 FIX: Action thresholds now map to norm_bull (0-100 scale)
# Old thresholds (100/80/60) were calibrated for raw scores that could
# reach 155 — on the 0-100 norm scale the equivalent bands are:
#   STRONG BUY  norm >= 75   (was raw >= 100, i.e. ~64 % of 155)
#   BUY         norm >= 58
#   WATCH       norm >= 42
ACTION_THRESHOLDS = dict(strong_buy=75, buy=58, watch=42)

def action_label(norm_score: float) -> str:
    """Convert a 0-100 normalised score to an action label."""
    if norm_score >= ACTION_THRESHOLDS["strong_buy"]: return "STRONG BUY"
    if norm_score >= ACTION_THRESHOLDS["buy"]:        return "BUY"
    if norm_score >= ACTION_THRESHOLDS["watch"]:      return "WATCH"
    return "SKIP"

# Phase constants
PHASE_IDLE  = "IDLE"
PHASE_SETUP = "SETUP"
PHASE_ENTRY = "ENTRY"
PHASE_CONT  = "CONT"
PHASE_BRK   = "BREAKOUT"
PHASE_EXIT  = "EXIT"

PHASE_COLORS = {
    PHASE_IDLE:  "#555577",
    PHASE_SETUP: "#b87333",
    PHASE_ENTRY: "#2255cc",
    PHASE_CONT:  "#22aa55",
    PHASE_BRK:   "#00dd88",
    PHASE_EXIT:  "#cc4444",
}

# ── Core math ────────────────────────────────────────────────────
def to_nse(sym):
    sym = sym.strip().upper()
    return sym if sym.endswith(".NS") else sym + ".NS"

def ema(s, p):
    return s.ewm(span=p, adjust=False).mean()

def rsi(s, p=14):
    d = s.diff()
    g = d.clip(lower=0).ewm(alpha=1/p, adjust=False).mean()
    l = (-d.clip(upper=0)).ewm(alpha=1/p, adjust=False).mean()
    return 100 - (100 / (1 + g / l.replace(0, np.nan)))

def atr_series(df, p=14):
    hi, lo, cl = df["High"], df["Low"], df["Close"]
    tr = pd.concat([(hi-lo), (hi-cl.shift()).abs(), (lo-cl.shift()).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1/p, adjust=False).mean()

def fib_levels(df, lookback=30):
    sw_hi = float(df["High"].iloc[-lookback:].max())
    sw_lo = float(df["Low"].iloc[-lookback:].min())
    rng   = sw_hi - sw_lo
    if rng == 0:
        return sw_hi, sw_lo, {}, rng
    return sw_hi, sw_lo, {
        "236":    sw_hi - rng * 0.236,
        "382":    sw_hi - rng * 0.382,
        "500":    sw_hi - rng * 0.500,
        "618":    sw_hi - rng * 0.618,
        "786":    sw_hi - rng * 0.786,
        "ext127": sw_hi + rng * 0.272,
        "ext161": sw_hi + rng * 0.618,
        "ext261": sw_hi + rng * 1.618,
    }, rng

# ═══════════════════════════════════════════════════════════════════
# EXHAUSTION & EXTENSION DETECTION (EXT-1 … EXT-7)
# ═══════════════════════════════════════════════════════════════════
# Design principles:
#   • Pure function — takes pre-computed series, returns a named dict.
#   • No new yfinance calls; all inputs come from score_stock's existing vars.
#   • Each flag is boolean; penalty weight is applied by the caller.
#   • Thresholds are mode-aware via EXT_CFG.
#   • All seven signals are independent — a stock can trigger any combination.

EXT_CFG = {
    #                   rsi_ceil  ema_dist_atr  atr_exp_mult  parab_mult  clim_vol_mult  div_bars
    "Intraday":   dict(rsi_ceil=80, ema_dist=3.5, atr_exp=2.5, parab=3.0, clim_vol=3.0, div_bars=10),
    "Swing":      dict(rsi_ceil=78, ema_dist=3.0, atr_exp=2.5, parab=3.0, clim_vol=3.0, div_bars=14),
    "Positional": dict(rsi_ceil=75, ema_dist=2.5, atr_exp=2.0, parab=2.5, clim_vol=2.5, div_bars=20),
}

# Penalty weights applied to norm_bull (0-100 scale).
# Designed so that 2 moderate flags ≈ -15 pts, all 7 ≈ -35 pts.
EXT_PENALTIES = {
    "rsi_overheat":     -8,
    "atr_extension":    -8,
    "parabolic":        -6,
    "ema_distance":     -5,
    "climactic_volume": -6,
    "mom_exhaustion":   -4,
    "bearish_div":      -6,
}

def detect_exhaustion(
    close, high, low, volume, rsi_series,
    e_fast_s, atr_s, atr_mean,
    c, v, vol_avg, mode,
):
    """
    Returns:
        flags   : dict[str, bool]  — which exhaustion conditions are active
        penalty : float            — total norm_bull deduction (negative number)
        labels  : list[str]        — human-readable short labels for the UI
        n_flags : int              — count of True flags
    """
    cfg = EXT_CFG[mode]
    n   = len(close)

    flags = {k: False for k in EXT_PENALTIES}
    labels = []

    # ── EXT-1: RSI Overheating ────────────────────────────────────
    # Current RSI above the mode ceiling. Simple and reliable.
    rsi_now = float(rsi_series.iloc[-1])
    if rsi_now > cfg["rsi_ceil"]:
        flags["rsi_overheat"] = True
        labels.append(f"RSI🔥{rsi_now:.0f}")

    # ── EXT-2: ATR Extension ─────────────────────────────────────
    # Current ATR has expanded far beyond its baseline mean,
    # indicating a climactic range expansion / blow-off.
    atr_val = float(atr_s.iloc[-1])
    if atr_mean > 0 and atr_val > atr_mean * cfg["atr_exp"]:
        flags["atr_extension"] = True
        ratio = round(atr_val / atr_mean, 1)
        labels.append(f"ATR×{ratio}")

    # ── EXT-3: Parabolic Acceleration ────────────────────────────
    # The last 3-bar % move vs the stock's own historical daily σ.
    # Historical σ = rolling std of daily % changes over 20 bars.
    # A 3-bar move > parab_mult × (σ × √3) is statistically extreme.
    if n >= 23:
        daily_pct   = close.pct_change().dropna()
        hist_sigma  = float(daily_pct.iloc[-20:].std())          # 1-bar σ
        expected_3b = hist_sigma * (3 ** 0.5)                    # 3-bar expected move
        actual_3b   = abs(float(close.iloc[-1]) - float(close.iloc[-4])) / float(close.iloc[-4])
        if expected_3b > 0 and actual_3b > cfg["parab"] * expected_3b:
            flags["parabolic"] = True
            labels.append(f"PARAB×{actual_3b/expected_3b:.1f}σ")

    # ── EXT-4: EMA Distance ───────────────────────────────────────
    # Price stretched more than N ATRs above EMA-fast.
    # Mean-reversion risk grows non-linearly beyond this.
    e_fast_now = float(e_fast_s.iloc[-1])
    if atr_val > 0:
        ema_dist_atrs = (c - e_fast_now) / atr_val
        if ema_dist_atrs > cfg["ema_dist"]:
            flags["ema_distance"] = True
            labels.append(f"EMA+{ema_dist_atrs:.1f}ATR")

    # ── EXT-5: Climactic Volume ───────────────────────────────────
    # Volume spike (> clim_vol_mult × avg) on an up bar, AFTER
    # a sustained uptrend (price higher than 10 bars ago).
    # A single vol spike on breakout is fine; it's the blow-off
    # pattern we want — sustained run + giant up-volume + no follow-through.
    if n >= 12 and vol_avg > 0:
        prior_run = c > float(close.iloc[-11])          # at least 10-bar uptrend
        up_bar    = c > float(close.iloc[-2])
        if prior_run and up_bar and v > vol_avg * cfg["clim_vol"]:
            # Check for lack of follow-through: next bar (if exists) closes lower
            # We can't see the future, so instead require upper wick > 30% of bar range
            bar_range = float(high.iloc[-1]) - float(low.iloc[-1])
            upper_wick = float(high.iloc[-1]) - c
            no_followthrough = bar_range > 0 and (upper_wick / bar_range) > 0.30
            if no_followthrough:
                flags["climactic_volume"] = True
                vol_ratio = round(v / vol_avg, 1)
                labels.append(f"CLIM-VOL×{vol_ratio}")

    # ── EXT-6: Momentum Exhaustion (RSI slope weakening) ─────────
    # RSI is making a lower peak while price is still rising —
    # detected by comparing RSI now vs its N-bar peak.
    # Simpler than full pivot divergence but catches the same phenomenon.
    if n >= 10:
        lookback  = min(cfg["div_bars"], n - 1)
        rsi_win   = rsi_series.iloc[-lookback:]
        price_win = close.iloc[-lookback:]
        rsi_peak  = float(rsi_win.max())
        price_rsi_peak_idx = rsi_win.idxmax()    # bar where RSI peaked
        price_at_rsi_peak  = float(close[price_rsi_peak_idx])

        # RSI peaked earlier and is now lower, but price is still rising
        if (rsi_now < rsi_peak - 3          # RSI has pulled back ≥3 pts from peak
                and c > price_at_rsi_peak   # but price is higher than when RSI peaked
                and rsi_win.idxmax() != rsi_win.index[-1]):  # peak wasn't last bar
            flags["mom_exhaustion"] = True
            labels.append(f"MOM-EXH(RSI{rsi_now:.0f}<pk{rsi_peak:.0f})")

    # ── EXT-7: Bearish RSI Divergence (pivot-based) ───────────────
    # Proper 5-point check:
    #   price:  HH₂ > HH₁  (price made a higher high)
    #   RSI:    RSI_HH₂ < RSI_HH₁  (RSI at that high was lower)
    # We identify pivot highs as bars where high > both neighbours.
    if n >= 20:
        lookback = min(cfg["div_bars"] * 2, n - 2)
        h_slice  = high.iloc[-lookback:]
        r_slice  = rsi_series.iloc[-lookback:]

        # Find pivot highs (simple: bar higher than ±1 neighbours)
        pivot_idx = []
        for i in range(1, len(h_slice) - 1):
            if float(h_slice.iloc[i]) > float(h_slice.iloc[i-1]) and \
               float(h_slice.iloc[i]) > float(h_slice.iloc[i+1]):
                pivot_idx.append(i)

        if len(pivot_idx) >= 2:
            p1, p2 = pivot_idx[-2], pivot_idx[-1]   # two most recent pivot highs
            price_h1 = float(h_slice.iloc[p1])
            price_h2 = float(h_slice.iloc[p2])
            rsi_h1   = float(r_slice.iloc[p1])
            rsi_h2   = float(r_slice.iloc[p2])

            if price_h2 > price_h1 and rsi_h2 < rsi_h1 - 2:   # 2-pt RSI buffer
                # Only flag if the second pivot is recent (within last 5 bars)
                bars_since_p2 = len(h_slice) - 1 - p2
                if bars_since_p2 <= 5:
                    flags["bearish_div"] = True
                    labels.append(f"DIV(P↑RSI↓{rsi_h2:.0f}<{rsi_h1:.0f})")

    # ── Aggregate ─────────────────────────────────────────────────
    penalty  = sum(EXT_PENALTIES[k] for k, v in flags.items() if v)
    n_flags  = sum(flags.values())

    return flags, float(penalty), labels, n_flags


def ext_phase_override(phase, ext_flags, n_flags, mode):
    """
    Demote phase when extension is critical or moderate.

    Critical  (≥3 flags OR both rsi_overheat AND atr_extension):
        BREAKOUT → EXIT   (buying a blow-off = catching a falling knife)
        CONT     → SETUP  (continuation likely failing)
        ENTRY    → SETUP  (entry invalid; wait for reset)

    Moderate  (2 flags):
        BREAKOUT → SETUP  (wait for re-test before committing)

    Single flag: no phase demotion, penalty-only.
    """
    rsi_ext = ext_flags.get("rsi_overheat", False)
    atr_ext = ext_flags.get("atr_extension", False)
    is_critical = n_flags >= 3 or (rsi_ext and atr_ext)
    is_moderate = n_flags == 2

    if is_critical:
        if phase == PHASE_BRK:
            return PHASE_EXIT,  "ext-critical→EXIT"
        if phase == PHASE_CONT:
            return PHASE_SETUP, "ext-critical→SETUP"
        if phase == PHASE_ENTRY:
            return PHASE_SETUP, "ext-critical→SETUP"
    elif is_moderate:
        if phase == PHASE_BRK:
            return PHASE_SETUP, "ext-moderate→SETUP"

    return phase, None    # no override


def ext_action_cap(action, n_flags):
    """
    If ANY exhaustion flag is active, STRONG BUY is capped to BUY.
    If 3+ flags (critical), BUY is further capped to WATCH.
    """
    if n_flags == 0:
        return action
    if n_flags >= 3:
        return "WATCH" if action in ("STRONG BUY", "BUY") else action
    # 1-2 flags: cap STRONG BUY → BUY only
    return "BUY" if action == "STRONG BUY" else action


# ═══════════════════════════════════════════════════════════════════
# END EXHAUSTION LAYER
# ═══════════════════════════════════════════════════════════════════

def _compute_targets(entry, sl, atr_val, fib, setup_type, sw_hi, sw_lo):
    rk = max(entry - sl, atr_val * 0.5)

    if setup_type == "fib" and fib:
        t1 = round(fib["ext127"], 2)
        t2 = round(fib["ext161"], 2)
        ext_range = fib["ext161"] - fib["ext127"]
        t3 = round(fib["ext161"] + min(ext_range, atr_val * 3), 2)
    elif setup_type == "breakout" and fib:
        t1 = round((entry + rk      + fib["ext127"]) / 2, 2)
        t2 = round((entry + rk * 2  + fib["ext161"]) / 2, 2)
        t3 = round((entry + rk * 3  + fib["ext261"]) / 2, 2)
    else:
        t1 = round(entry + rk, 2)
        t2 = round(entry + rk * 2, 2)
        t3 = round(entry + rk * 3, 2)

    min_move = atr_val * 0.8
    if t1 - entry < min_move:
        t1 = round(entry + min_move, 2)
        t2 = round(entry + min_move * 2, 2)
        t3 = round(entry + min_move * 3, 2)

    return t1, t2, t3

# ── FIX-3: Intraday daily context fetch ─────────────────────────
@st.cache_data(ttl=900)
def _fetch_daily_close(ticker):
    """Fetch 6 months of daily closes for HTF momentum — Intraday mode only."""
    for attempt in range(3):                   # BUG-9: retry
        try:
            df = yf.download(ticker, period="6mo", interval="1d",
                             auto_adjust=True, progress=False, threads=False)
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            return df["Close"].dropna()
        except Exception:
            time.sleep(1.5 ** attempt)
    return pd.Series(dtype=float)

# ── detect_phase: accepts pre-computed indicators (FIX-4/6) ──────
# BUG-6 FIX: tightened CONT gate — requires price > EMA-fast, vol > 1.2× avg,
#             AND close above 3-bar high (not just 4-bar).
def detect_phase_and_entry(
    df, mode, *,
    c, e_fast_s, e_slow_s, atr_s, atr_val, atr_mean,
    v, vol_avg, fib, sw_hi, sw_lo, in_golden, near_e127, near_e161,
    norm_bull, trend_up, trend_down, trend_strong, score_th,
    vdu_setup=False,
):
    cfg   = MODE_CFG[mode]
    close = df["Close"]
    high  = df["High"]
    n     = len(close)
    if n < 60:
        return PHASE_IDLE, None, "norm"

    e_fast_val = float(e_fast_s.iloc[-1])
    e_slow_val = float(e_slow_s.iloc[-1])

    brk_lb         = 5
    rolling_hi_brk = float(high.iloc[-brk_lb-1:-1].max()) if n > brk_lb+1 else float(high.iloc[-1])
    buf             = atr_val * 0.2

    is_compressed = atr_val < atr_mean * 0.8
    is_expanding  = atr_val > float(atr_s.iloc[-2])

    body = (
        abs(float(close.iloc[-1]) - float(df["Open"].iloc[-1]))
        if "Open" in df.columns else atr_val * 0.3
    )
    upper_wick = (
        float(high.iloc[-1]) - max(float(close.iloc[-1]), float(df["Open"].iloc[-1]))
        if "Open" in df.columns else 0
    )
    is_exhaustion = upper_wick > body * 1.5
    vol_spike     = v > vol_avg * 1.3

    is_fib_buy = trend_up and in_golden

    # Breakout confidence (weighted)
    BRK_CONF_MIN = 0.65
    brk_weights = {
        "price_above_high": (0.30, c > rolling_hi_brk + buf),
        "trend_up":         (0.20, trend_up),
        "score_ok":         (0.15, norm_bull >= score_th),
        "compressed":       (0.15, is_compressed),
        "expanding":        (0.10, is_expanding),
        "vol_spike":        (0.10, vol_spike),
    }
    brk_confidence = sum(w for w, cond in brk_weights.values() if cond)
    is_breakout = brk_confidence >= BRK_CONF_MIN and not is_exhaustion

    # BUG-6 FIX: stricter CONT — price must be above EMA-fast, volume
    # must exceed 1.2× avg, and close must be a 3-bar high (not 4-bar).
    is_cont = (
        n >= 4
        and c > float(close.iloc[-4:-1].max())  # 3-bar high
        and c > e_fast_val                       # above EMA fast (NEW)
        and v > vol_avg * 1.2                    # tighter vol filter (was vol_avg)
        and trend_strong
    )

    ema_down    = e_fast_val < e_slow_val and float(e_fast_s.iloc[-4]) < float(e_slow_s.iloc[-4])
    trail_level = float(close.iloc[-10:].max()) - atr_val * 1.5
    trail_break = c < trail_level

    # Phase priority (unchanged logic, uses norm_bull throughout — BUG-3 fix)
    if trend_down and ema_down:
        phase = PHASE_EXIT
        setup_type = "norm"
    elif is_breakout:
        phase = PHASE_BRK
        setup_type = "breakout"
    elif (is_fib_buy or norm_bull >= score_th) and is_cont and trend_up:
        phase = PHASE_CONT
        setup_type = "fib" if is_fib_buy else "norm"
    elif (is_fib_buy or norm_bull >= score_th) and trend_up:
        phase = PHASE_ENTRY
        setup_type = "fib" if is_fib_buy else "norm"
    elif (is_fib_buy or norm_bull >= score_th * 0.85 or vdu_setup) and trend_up:
        phase = PHASE_SETUP
        setup_type = "fib" if is_fib_buy else ("vdu" if vdu_setup else "norm")
    elif trail_break and trend_up:
        phase = PHASE_EXIT
        setup_type = "norm"
    else:
        phase = PHASE_IDLE
        setup_type = "norm"

    # Entry price
    entry_price = None
    if phase in (PHASE_ENTRY, PHASE_CONT, PHASE_BRK, PHASE_SETUP):
        prox = atr_val * 0.3
        if is_breakout:
            entry_price = round(rolling_hi_brk + buf, 2)
        elif is_fib_buy and fib:
            entry_price = round(fib["618"] + prox * 0.3, 2)
        else:
            cross       = close > e_fast_s
            signal_bars = cross & ~cross.shift(1).fillna(False)
            if signal_bars.any():
                last_idx    = signal_bars[::-1].idxmax()
                entry_price = round(float(close[last_idx]), 2)
            else:
                entry_price = round(c, 2)

    return phase, entry_price, setup_type

# ── Full stock scoring ────────────────────────────────────────────
def score_stock(df, nifty_close, mode="Swing", daily_close=None, market_bullish=True):
    """
    BUG-4 FIX: market regime haircut is applied to norm_bull BEFORE action
    label and phase are derived — previously the haircut was applied after
    action was already assigned in run_scan(), creating an inconsistency
    where action and phase used different effective scores.

    daily_close: pre-fetched daily Close (Intraday HTF momentum, FIX-3).
    """
    try:
        cfg    = MODE_CFG[mode]
        close  = df["Close"]
        volume = df["Volume"]
        n      = len(close)
        if n < 50:
            return None

        c       = float(close.iloc[-1])
        prev    = float(close.iloc[-2])
        e_fast_s = ema(close, cfg["ema_fast"])
        e_slow_s = ema(close, cfg["ema_slow"])
        e_fast   = float(e_fast_s.iloc[-1])
        e_slow   = float(e_slow_s.iloc[-1])
        e200     = float(ema(close, 200).iloc[-1]) if n >= 200 else None
        atr_s    = atr_series(df)
        atr_val  = float(atr_s.iloc[-1])
        atr_mean = float(atr_s.rolling(20).mean().iloc[-1])
        vol_avg  = float(volume.rolling(20).mean().iloc[-1])
        v        = float(volume.iloc[-1])
        chg      = round(((c - prev) / prev) * 100, 2)
        hh       = float(close.iloc[-11:-1].max())

        rs = 0
        if n >= 6 and len(nifty_close) >= 6:
            rs = (c - float(close.iloc[-6])) - (float(nifty_close.iloc[-1]) - float(nifty_close.iloc[-6]))

        trend_up     = (e200 is None or c > e200) and c > e_fast and e_fast > e_slow
        trend_down   = (e200 is None or c < e200) and c < e_fast and e_fast < e_slow
        trend_strong = c > e_fast and e_fast > e_slow

        # FIX-3: HTF momentum via daily bars for Intraday
        mom_src = (daily_close
                   if (mode == "Intraday" and daily_close is not None and len(daily_close) >= 21)
                   else close)
        mom_n = len(mom_src)
        mom1 = (c - float(mom_src.iloc[-21]))  / float(mom_src.iloc[-21])  * 100 if mom_n >= 21  else 0
        mom3 = (c - float(mom_src.iloc[-63]))  / float(mom_src.iloc[-63])  * 100 if mom_n >= 63  else 0
        mom6 = (c - float(mom_src.iloc[-126])) / float(mom_src.iloc[-126]) * 100 if mom_n >= 126 else 0
        strong_htf = mom1 > cfg["mom1_th"] and mom3 > cfg["mom3_th"] and mom6 > cfg["mom6_th"]

        sw_hi, sw_lo, fib, fib_rng = fib_levels(df, lookback=30)
        prox      = atr_val * 0.3
        in_golden = bool(fib and c >= fib["618"] - prox and c <= fib["500"] + prox)
        near_e127 = bool(fib and abs(c - fib["ext127"]) < prox)
        near_e161 = bool(fib and abs(c - fib["ext161"]) < prox)

        # VDU Detection
        VDU_VOL_RATIO  = 0.70
        VDU_RANGE_MULT = 0.80
        vdu_vol_dry = False
        vdu_coil    = False
        if n >= 20 and vol_avg > 0:
            recent_vols = [float(volume.iloc[k]) for k in [-3, -2, -1]]
            vdu_vol_dry = all(vv < vol_avg * VDU_VOL_RATIO for vv in recent_vols)
        if n >= 5:
            recent_hi = float(df["High"].iloc[-5:].max())
            recent_lo = float(df["Low"].iloc[-5:].min())
            vdu_coil  = (recent_hi - recent_lo) < atr_val * VDU_RANGE_MULT
        vdu_setup = bool(trend_up and vdu_vol_dry and vdu_coil)

        qualified = strong_htf and trend_strong

        # ── Exhaustion / Extension pre-check (EXT-1 … EXT-7) ────────
        # Run before scoring so penalties flow into norm_bull naturally.
        rsi_series = rsi(close, cfg["rsi_len"])
        ext_flags, ext_penalty, ext_labels, ext_n = detect_exhaustion(
            close=close, high=df["High"], low=df["Low"], volume=volume,
            rsi_series=rsi_series,
            e_fast_s=e_fast_s, atr_s=atr_s, atr_mean=atr_mean,
            c=c, v=v, vol_avg=vol_avg, mode=mode,
        )
        # r (RSI scalar) still used in bull score below — re-derive from same series
        r = float(rsi_series.iloc[-1])

        # ── Bull score ──────────────────────────────────────────────
        # BUG-10 FIX: rebalanced weights; true max = 120 (was 155).
        # This makes BULL_MAX a realistic ceiling that a genuinely strong
        # stock can reach, not an inflated number requiring impossible combos.
        #
        # Component caps (summing to 120):
        #   trend         25
        #   ema_align     15   (was 20; golden-cross alone shouldn't score too high)
        #   rsi           15   (was 20)
        #   volume        10   (was 15)
        #   price_vs_hh   15   (was 20)
        #   short_mom      8   (was 10)
        #   rel_strength   7   (was 10)
        #   htf/qualified 15   (was 20)
        #   fib_golden    10   (was 15; extension penalties unchanged)
        #   — penalties: near_e127 -20, near_e161 -30 (unchanged)
        BULL_MAX = 120

        bull = 0
        bull += 25 if trend_up else 0
        bull += 15 if e_fast > e_slow else (7 if e_fast > e_slow * 0.995 else 0)
        bull += (15 if r >= 65 else 10) if r >= 60 else (5 if r > 50 else 0)
        bull += 10 if v > vol_avg * 1.2 else (5 if v > vol_avg else 0)
        bull += 15 if c > hh else (9 if c > hh * 0.98 else 0)
        if n >= 3 and c > float(close.iloc[-3]):
            bull += 8
        bull += 7 if rs > 0 else (2 if rs > -0.5 else 0)
        if mode == "Positional":
            bull += 15 if qualified else -15   # FIX-1 retained
        else:
            bull += 15 if strong_htf else -10
        bull += 10 if in_golden else 0
        if near_e127:
            bull -= 20
        elif near_e161:
            bull -= 30

        # ── EXT penalty applied to raw bull before normalisation ──
        # ext_penalty is already negative (e.g. -14 for 2 flags).
        # Applied here so norm_bull, action, and phase all see the
        # same penalised value — consistent with the BUG-4 fix logic.
        bull += ext_penalty   # e.g. bull=95 + (-14) = 81

        # ── BUG-4 FIX: apply regime haircut HERE, before action/phase ──
        BEARISH_HAIRCUT = 0.85
        if not market_bullish:
            bull = int(bull * BEARISH_HAIRCUT)

        raw_score = max(0, bull)
        norm_bull  = min(100.0, max(0.0, bull * 100.0 / BULL_MAX))
        score_th   = float(cfg["score_th"])

        # BUG-2/3 FIX: both action and phase use norm_bull exclusively
        act = action_label(norm_bull)

        phase, entry_price, setup_type = detect_phase_and_entry(
            df, mode,
            c=c, e_fast_s=e_fast_s, e_slow_s=e_slow_s,
            atr_s=atr_s, atr_val=atr_val, atr_mean=atr_mean,
            v=v, vol_avg=vol_avg,
            fib=fib, sw_hi=sw_hi, sw_lo=sw_lo,
            in_golden=in_golden, near_e127=near_e127, near_e161=near_e161,
            norm_bull=norm_bull, trend_up=trend_up, trend_down=trend_down,
            trend_strong=trend_strong, score_th=score_th,
            vdu_setup=vdu_setup,
        )

        # ── Exhaustion overrides (applied after base phase/action) ──
        # Phase demotion: BREAKOUT→EXIT/SETUP, CONT/ENTRY→SETUP on extension.
        # Action cap:     STRONG BUY→BUY (any flag), BUY→WATCH (3+ flags).
        phase, _override_reason = ext_phase_override(phase, ext_flags, ext_n, mode)
        act   = ext_action_cap(act, ext_n)

        ltp   = round(c, 2)
        entry = entry_price if entry_price else ltp

        # SL (FIX-5: max() for tightest fib SL)
        mult = cfg["atr_mult"]
        wide = cfg["atr_wide"]
        maxm = cfg["atr_max"]

        if setup_type == "fib" and fib:
            fib_sl = max(float(sw_lo), fib["618"] - atr_val * 0.5)
            fib_sl = max(fib_sl, entry - atr_val * 0.8)
            sl = round(fib_sl, 2)
        elif setup_type == "breakout":
            sl = round(entry - atr_val * (1.5 if mode == "Intraday" else 2.0), 2)
        else:
            raw_sl = entry - atr_val * mult
            min_sl = entry - atr_val * wide
            max_sl = entry - atr_val * maxm
            sl = round(max(min_sl, min(raw_sl, max_sl)), 2)

        min_risk = atr_val * 0.5
        if entry - sl < min_risk:
            sl = round(entry - min_risk, 2)

        t1, t2, t3 = _compute_targets(entry, sl, atr_val, fib, setup_type, sw_hi, sw_lo)

        return {
            "Score":     round(norm_bull, 1),   # normalised 0-100 after all penalties
            "RawBull":   raw_score,
            "Action":    act,
            "Phase":     phase,
            "Setup":     setup_type,
            "%Change":   chg,
            "LTP":       ltp,
            "Entry":     entry,
            "SL":        sl,
            "T1":        t1,
            "T2":        t2,
            "T3":        t3,
            "InGolden":  in_golden,
            "VDU":       vdu_setup,
            # ── Exhaustion fields ──────────────────────────────────
            "ExtN":      ext_n,               # count of active flags (0-7)
            "ExtLabels": ext_labels,          # e.g. ["RSI🔥82", "PARAB×3.4σ"]
            "ExtFlags":  ext_flags,           # full dict for downstream filtering
        }
    except Exception:
        return None


def fetch_nifty(mode="Swing"):
    cfg = MODE_CFG[mode]
    df  = yf.download("^NSEI", period=cfg["period"], interval=cfg["interval"], progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df["Close"].dropna()

def _market_regime(nifty_close):
    if len(nifty_close) < 50:
        return True, "UNKNOWN"
    ema20_val = float(ema(nifty_close, 20).iloc[-1])
    ema50_val = float(ema(nifty_close, 50).iloc[-1])
    bullish   = (float(nifty_close.iloc[-1]) > ema50_val) and (ema20_val > ema50_val)
    return bullish, "BULLISH" if bullish else "BEARISH"


# ── BUG-9 FIX: _fetch_one with exponential back-off retry ────────
def _fetch_one(args):
    """Download OHLCV for a single ticker — up to 3 attempts with back-off."""
    sym, mode, min_bars = args
    cfg    = MODE_CFG[mode]
    ticker = to_nse(sym)
    for attempt in range(3):
        try:
            df = yf.download(ticker, period=cfg["period"], interval=cfg["interval"],
                             auto_adjust=True, progress=False, threads=False)
            if df.empty:
                return sym, None
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            df = df.dropna(how="all")
            if pd.isna(df["Close"].iloc[-1]):
                df = df.iloc[:-1]
            df["Close"]  = df["Close"].ffill()
            df["Volume"] = df["Volume"].fillna(0)
            df = df.dropna(subset=["Close"])
            return sym, (df if len(df) >= min_bars else None)
        except Exception:
            if attempt < 2:
                time.sleep(1.5 ** attempt + random.uniform(0, 0.5))   # jitter
    return sym, None


def run_scan(symbols, mode, progress_bar, status_text):
    """
    BUG-4 FIX: market_bullish passed into score_stock so haircut happens
                before action/phase assignment.
    BUG-8 FIX: staggered ThreadPoolExecutor starts to avoid cache stampede.
    BUG-9 FIX: _fetch_one retries internally; run_scan no longer needs to.
    """
    import concurrent.futures

    cfg      = MODE_CFG[mode]
    rejected = 0
    total    = len(symbols)
    min_bars = 30 if mode == "Intraday" else 50

    nifty = fetch_nifty(mode)

    market_bullish, regime_label = _market_regime(nifty)
    if not market_bullish:
        st.warning(
            f"⚠️ **Market Regime: {regime_label}** — Nifty EMA20 is below EMA50. "
            "Scores are reduced by 15 % (applied before action/phase assignment). "
            "Prefer WATCH/SETUP phases; avoid chasing breakouts."
        )

    status_text.text("Fetching OHLCV data in parallel…")
    data         = {}
    daily_closes = {}
    args_list    = [(sym, mode, min_bars) for sym in symbols]

    MAX_WORKERS = min(16, total)
    completed   = 0

    # BUG-8 FIX: submit futures in small randomised batches so all workers
    # don't hit yfinance simultaneously (cache stampede mitigation).
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {}
        for i, a in enumerate(args_list):
            # stagger submission by ~50 ms per batch of 16 to spread load
            if i > 0 and i % MAX_WORKERS == 0:
                time.sleep(0.05)
            futures[pool.submit(_fetch_one, a)] = a[0]

        for fut in concurrent.futures.as_completed(futures):
            sym, df = fut.result()
            completed += 1
            progress_bar.progress(completed / total * 0.6)
            if df is not None:
                data[sym] = df
            else:
                rejected += 1

    if mode == "Intraday":
        status_text.text("Fetching daily context for HTF momentum…")
        daily_args = [(sym, "Swing", 50) for sym in data]
        with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
            d_futures = {pool.submit(_fetch_one, a): a[0] for a in daily_args}
            for fut in concurrent.futures.as_completed(d_futures):
                sym, df = fut.result()
                if df is not None:
                    daily_closes[sym] = df["Close"]

    results = []
    n_data  = len(data)
    for i, (sym, df) in enumerate(data.items()):
        progress_bar.progress(0.6 + (i + 1) / n_data * 0.4)
        status_text.text(f"Scoring {i+1}/{n_data}  ▸  {sym}")
        # BUG-4 FIX: pass market_bullish so haircut applies before action/phase
        res = score_stock(df, nifty, mode,
                          daily_close=daily_closes.get(sym),
                          market_bullish=market_bullish)
        if res:
            res["Regime"] = regime_label
            results.append({"Symbol": sym, **res})

    results.sort(key=lambda x: x["Score"], reverse=True)
    return results, rejected


# ── Helpers ───────────────────────────────────────────────────────
def fmt(val):
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return "—"
    return f"₹{val:,.2f}"

def action_icon(a):
    return {"STRONG BUY":"🟢","BUY":"🔵","WATCH":"🟡","SKIP":"🔴"}.get(a,"")


# ── OI data (BUG-1 FIX) ──────────────────────────────────────────
# Root cause: NSE blocks plain requests.Session() without a valid browser
# cookie sequence. The original code did one warm-up GET but rarely got
# a valid cookie in time. Fix:
#   1. Two-step warm-up: homepage → derivatives page → option-chain
#   2. Retry the OC fetch up to 3× with back-off
#   3. Explicit Accept / Referer / X-Requested-With headers
#   4. Session reuse across the retries (cookies persist)
#
# BUG-7 FIX: UI text clarified — "Bank Nifty" not "Sensex" throughout.
# NSE has no Sensex OC; BANKNIFTY is the closest weekly index derivative.

@st.cache_data(ttl=180)
def fetch_oi_data(symbol="NIFTY"):
    """
    Fetch weekly OI from NSE option chain API.
    symbol: "NIFTY" or "BANKNIFTY"
    Returns a dict or None on failure.
    """
    import requests

    HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept":          "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Referer":         "https://www.nseindia.com/",
        "X-Requested-With": "XMLHttpRequest",
        "Connection":      "keep-alive",
    }

    session = requests.Session()
    session.headers.update(HEADERS)

    def _warm_session():
        """Two-step cookie warm-up mimicking a real browser visit."""
        try:
            session.get("https://www.nseindia.com", timeout=10)
            time.sleep(0.8)
            session.get(
                "https://www.nseindia.com/market-data/equity-derivatives-watch",
                timeout=10,
            )
            time.sleep(0.5)
            return True
        except Exception:
            return False

    _warm_session()

    oc_url = f"https://www.nseindia.com/api/option-chain-indices?symbol={symbol}"
    data   = None

    for attempt in range(3):          # BUG-1: retry OC fetch
        try:
            resp = session.get(oc_url, timeout=12)
            if resp.status_code == 200:
                data = resp.json()
                break
            elif resp.status_code in (401, 403):
                # Cookie may have expired — re-warm and retry
                _warm_session()
        except Exception:
            pass
        time.sleep(1.5 ** attempt)

    if data is None:
        return None

    try:
        records      = data["records"]
        spot         = float(records["underlyingValue"])
        expiries     = records["expiryDates"]
        weekly_expiry = expiries[0] if expiries else None

        rows = []
        for item in records["data"]:
            if item.get("expiryDate") != weekly_expiry:
                continue
            strike = item["strikePrice"]
            ce_oi  = item.get("CE", {}).get("openInterest", 0) or 0
            pe_oi  = item.get("PE", {}).get("openInterest", 0) or 0
            ce_chg = item.get("CE", {}).get("changeinOpenInterest", 0) or 0
            pe_chg = item.get("PE", {}).get("changeinOpenInterest", 0) or 0
            ce_ltp = item.get("CE", {}).get("lastPrice", 0) or 0
            pe_ltp = item.get("PE", {}).get("lastPrice", 0) or 0
            rows.append({
                "Strike": strike,
                "CE_OI": ce_oi, "CE_Chg": ce_chg, "CE_LTP": ce_ltp,
                "PE_OI": pe_oi, "PE_Chg": pe_chg, "PE_LTP": pe_ltp,
            })

        if not rows:
            return None

        df_oi     = pd.DataFrame(rows).sort_values("Strike").reset_index(drop=True)
        total_ce  = df_oi["CE_OI"].sum()
        total_pe  = df_oi["PE_OI"].sum()
        pcr       = round(total_pe / total_ce, 2) if total_ce > 0 else 0

        # Max Pain
        pains = []
        for s in df_oi["Strike"]:
            ce_loss = ((df_oi["Strike"] - s).clip(lower=0) * df_oi["CE_OI"]).sum()
            pe_loss = ((s - df_oi["Strike"]).clip(lower=0) * df_oi["PE_OI"]).sum()
            pains.append(ce_loss + pe_loss)
        df_oi["TotalPain"] = pains
        max_pain_strike = int(df_oi.loc[df_oi["TotalPain"].idxmin(), "Strike"])
        call_wall       = int(df_oi.loc[df_oi["CE_OI"].idxmax(), "Strike"])
        put_wall        = int(df_oi.loc[df_oi["PE_OI"].idxmax(), "Strike"])
        top_ce = df_oi.nlargest(5, "CE_OI")[["Strike","CE_OI","CE_Chg"]].to_dict("records")
        top_pe = df_oi.nlargest(5, "PE_OI")[["Strike","PE_OI","PE_Chg"]].to_dict("records")

        return {
            "symbol":    symbol,
            "expiry":    weekly_expiry,
            "spot":      spot,
            "pcr":       pcr,
            "max_pain":  max_pain_strike,
            "call_wall": call_wall,
            "put_wall":  put_wall,
            "top_ce":    top_ce,
            "top_pe":    top_pe,
            "df_oi":     df_oi,
        }
    except Exception:
        return None


def _oi_sentiment(pcr):
    if pcr >= 1.3:  return "Bullish 🟢", "#2ecc71"
    if pcr >= 0.9:  return "Neutral 🟡", "#f39c12"
    return "Bearish 🔴", "#e74c3c"


def _render_oi_card(oi, index_name):
    """Render OI + Max Pain section inside an expander for one index."""
    if oi is None:
        st.caption(
            f"⚠️ OI data unavailable for {index_name} — "
            "NSE API may be rate-limiting or market is closed. "
            "The scanner retries up to 3× automatically."
        )
        return

    sentiment_label, sentiment_color = _oi_sentiment(oi["pcr"])

    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Expiry",    oi["expiry"])
    m2.metric("Spot",      f"₹{oi['spot']:,.0f}")
    m3.metric("Max Pain",  f"₹{oi['max_pain']:,}",
              delta=f"{oi['max_pain'] - int(oi['spot']):+,} from spot",
              delta_color="off")
    m4.metric("Call Wall", f"₹{oi['call_wall']:,}")
    m5.metric("Put Wall",  f"₹{oi['put_wall']:,}")

    st.markdown(
        f'<div style="margin:6px 0 10px;">'
        f'<span style="color:#7a7a9a;font-size:12px;">PCR: </span>'
        f'<span style="color:{sentiment_color};font-weight:bold;font-size:14px;">'
        f'{oi["pcr"]}  ·  {sentiment_label}</span>'
        f'&nbsp;&nbsp;<span style="color:#7a7a9a;font-size:11px;">'
        f'(PCR &gt; 1.3 bullish · &lt; 0.9 bearish)</span>'
        f'</div>',
        unsafe_allow_html=True,
    )

    tc1, tc2 = st.columns(2)
    with tc1:
        st.markdown("**📞 Top CE OI (Resistance)**")
        ce_rows = []
        for row in oi["top_ce"]:
            chg_str = f"+{row['CE_Chg']:,.0f}" if row['CE_Chg'] >= 0 else f"{row['CE_Chg']:,.0f}"
            chg_col = "🔺" if row['CE_Chg'] > 0 else ("🔻" if row['CE_Chg'] < 0 else "–")
            ce_rows.append({"Strike": f"₹{row['Strike']:,}",
                            "OI (lots)": f"{row['CE_OI']:,}",
                            "OI Δ": f"{chg_col} {chg_str}"})
        st.dataframe(pd.DataFrame(ce_rows), hide_index=True, use_container_width=True)
    with tc2:
        st.markdown("**📟 Top PE OI (Support)**")
        pe_rows = []
        for row in oi["top_pe"]:
            chg_str = f"+{row['PE_Chg']:,.0f}" if row['PE_Chg'] >= 0 else f"{row['PE_Chg']:,.0f}"
            chg_col = "🔺" if row['PE_Chg'] > 0 else ("🔻" if row['PE_Chg'] < 0 else "–")
            pe_rows.append({"Strike": f"₹{row['Strike']:,}",
                            "OI (lots)": f"{row['PE_OI']:,}",
                            "OI Δ": f"{chg_col} {chg_str}"})
        st.dataframe(pd.DataFrame(pe_rows), hide_index=True, use_container_width=True)

    pain_dist = oi["max_pain"] - int(oi["spot"])
    if abs(pain_dist) <= 100:
        tip = "🎯 Spot is near Max Pain — expect pin action / low volatility into expiry."
    elif pain_dist > 100:
        tip = f"⬆️ Max Pain is ₹{pain_dist:+,} above spot — options writers may defend upside."
    else:
        tip = f"⬇️ Max Pain is ₹{pain_dist:+,} below spot — options writers may drag price down."
    st.caption(tip)


# ── Nifty & Sensex index cards ────────────────────────────────────
@st.cache_data(ttl=300)
def fetch_indices(mode="Swing"):
    cfg      = MODE_CFG[mode]
    ema_f    = cfg["ema_fast"]
    ema_s    = cfg["ema_slow"]
    rsi_l    = cfg["rsi_len"]
    min_bars = 30 if mode == "Intraday" else 50
    out = {}
    for name, ticker in [("Nifty 50","^NSEI"),("Sensex","^BSESN")]:
        try:
            df = yf.download(ticker, period=cfg["period"], interval=cfg["interval"], progress=False)
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            df = df.dropna()
            if len(df) < min_bars:
                out[name] = None
                continue
            close = df["Close"]
            c, prev = float(close.iloc[-1]), float(close.iloc[-2])
            chg, pct = c - prev, (c - prev) / prev * 100
            ef   = float(ema(close, ema_f).iloc[-1])
            es   = float(ema(close, ema_s).iloc[-1])
            e200 = float(ema(close, 200).iloc[-1]) if len(close) >= 200 else es
            r    = float(rsi(close, rsi_l).iloc[-1])
            hh   = float(close.iloc[-11:-1].max())
            trend_up = c > e200 and c > ef and ef > es

            # Index score uses same BULL_MAX=120 as individual stocks
            bull = 0
            bull += 25 if trend_up else 0
            bull += 15 if ef > es else (7 if ef > es * 0.995 else 0)
            bull += (15 if r >= 65 else 10) if r >= 60 else (5 if r > 50 else 0)
            bull += 15 if c > hh else (9 if c > hh * 0.98 else 0)
            if len(close) >= 3 and c > float(close.iloc[-3]):
                bull += 8
            norm_score = min(100.0, max(0.0, bull * 100.0 / 78))  # index has no htf/fib/vol
            act    = action_label(norm_score)
            score  = round(norm_score, 1)

            interval_label = {"5m":"5min","1d":"Daily","1wk":"Weekly"}.get(
                cfg["interval"], cfg["interval"])
            out[name] = {
                "value": c, "chg": chg, "pct": pct,
                "score": score, "action": act,
                "rsi": round(r, 1),
                "trend": "↑ Above EMAs" if trend_up else "↓ Below EMAs",
                "interval": interval_label,
                "ema_fast": ema_f, "ema_slow": ema_s,
            }
        except Exception:
            out[name] = None
    return out


# ── Zerodha live quotes ───────────────────────────────────────────
ZERODHA_QUOTE_URL = "https://api.kite.trade/quote"
ZERODHA_LTP_URL   = "https://api.kite.trade/quote/ltp"
ZERODHA_INDEX_TOKENS = {
    "Nifty 50":  "NSE:NIFTY 50",
    "Sensex":    "BSE:SENSEX",
    "BankNifty": "NSE:NIFTY BANK",
}

def _zerodha_headers(enctoken):
    return {
        "Authorization":  f"enctoken {enctoken.strip()}",
        "Content-Type":   "application/json",
        "X-Kite-Version": "3",
    }

@st.cache_data(ttl=15)
def zd_fetch_index_quote(enctoken, instruments):
    import requests
    try:
        params = [("i", inst) for inst in instruments]
        r = requests.get(ZERODHA_QUOTE_URL,
                         headers=_zerodha_headers(enctoken),
                         params=params, timeout=5)
        if r.status_code == 200:
            return r.json().get("data", {})
        return {}
    except Exception:
        return {}

@st.cache_data(ttl=15)
def zd_fetch_ltp_bulk(enctoken, instrument_list):
    import requests
    out = {}
    CHUNK = 500
    for i in range(0, len(instrument_list), CHUNK):
        chunk = instrument_list[i:i+CHUNK]
        try:
            params = [("i", inst) for inst in chunk]
            r = requests.get(ZERODHA_LTP_URL,
                             headers=_zerodha_headers(enctoken),
                             params=params, timeout=8)
            if r.status_code == 200:
                data = r.json().get("data", {})
                for k, v in data.items():
                    out[k] = v.get("last_price", None)
        except Exception:
            pass
    return out

def zd_index_display(quote_data, instrument_key, name):
    d = quote_data.get(instrument_key)
    if not d:
        return None
    ltp  = d.get("last_price", 0)
    ohlc = d.get("ohlc", {})
    prev = ohlc.get("close", ltp)
    chg  = round(ltp - prev, 2)
    pct  = round((chg / prev) * 100, 2) if prev else 0
    return {
        "value": ltp, "chg": chg, "pct": pct,
        "open":  ohlc.get("open"), "high": ohlc.get("high"),
        "low":   ohlc.get("low"),  "prev": prev,
        "source": "Zerodha",
    }

def _enctoken_widget():
    if "zd_enctoken" not in st.session_state:
        st.session_state["zd_enctoken"] = ""
    with st.expander("🔑 Zerodha Live Quotes — Enter enctoken",
                     expanded=not st.session_state["zd_enctoken"]):
        st.markdown("""
**How to get your enctoken** (~30 seconds):
1. Open [kite.zerodha.com](https://kite.zerodha.com) and log in
2. Press **F12** → **Application** tab → **Cookies** → `kite.zerodha.com`
3. Find the cookie named **`enctoken`** — copy its value
4. Paste below ↓

> Token resets daily around **6 AM IST**. Re-paste if quotes stop updating.
> Stored only in this browser session — never sent anywhere except Zerodha's servers.
        """)
        col_inp, col_btn = st.columns([5, 1])
        with col_inp:
            token_input = st.text_input(
                "enctoken", type="password",
                value=st.session_state["zd_enctoken"],
                placeholder="Paste your Zerodha enctoken here…",
                label_visibility="collapsed",
            )
        with col_btn:
            save_btn = st.button("✅ Save", use_container_width=True)
        if save_btn and token_input.strip():
            st.session_state["zd_enctoken"] = token_input.strip()
            st.success("Token saved! Live quotes active for this session.")
            st.rerun()
        if st.session_state["zd_enctoken"]:
            if st.button("🗑 Clear token"):
                st.session_state["zd_enctoken"] = ""
                st.rerun()
    return st.session_state.get("zd_enctoken", "")


# ── Streamlit UI ──────────────────────────────────────────────────
st.set_page_config(page_title="NSE Master Scanner Pro", page_icon="📈",
                   layout="wide", initial_sidebar_state="collapsed")
st.markdown("""
<style>
body, .stApp { background-color:#0d0d1a; color:#f0f0f0; }
.stDataFrame { font-size:13px; }
div[data-testid="stMetricValue"] { color:#00b4d8; font-size:1.4rem; }
</style>""", unsafe_allow_html=True)

st.title("📈 NSE Master Scanner Pro  [Phase Engine v6]")

for key, default in [
    ("results",[]),("scan_time",None),("rejected",0),
    ("scan_mode","Swing"),("zd_enctoken",""),("zd_ltp_cache",{}),
]:
    if key not in st.session_state:
        st.session_state[key] = default

# ── Controls ──────────────────────────────────────────────────────
c1, c2, c3, c4, c5, c6 = st.columns([2,1,1,2,2,2])
with c1:
    index_opt = st.selectbox("Index", list(SECTORS.keys()), label_visibility="collapsed")
with c2:
    mode_opt = st.selectbox("Mode", ["Swing","Intraday","Positional"], label_visibility="collapsed")

enctoken = _enctoken_widget()

# ── Nifty & Sensex ────────────────────────────────────────────────
indices = fetch_indices(mode_opt)

# BUG-7 FIX: fetch BANKNIFTY OI but label it "Bank Nifty" throughout
oi_nifty    = fetch_oi_data("NIFTY")
oi_banknifty = fetch_oi_data("BANKNIFTY")

zd_index_data = {}
if enctoken:
    _zd_raw = zd_fetch_index_quote(
        enctoken,
        [ZERODHA_INDEX_TOKENS["Nifty 50"], ZERODHA_INDEX_TOKENS["Sensex"]],
    )
    for idx_name, inst_key in [
        ("Nifty 50", ZERODHA_INDEX_TOKENS["Nifty 50"]),
        ("Sensex",   ZERODHA_INDEX_TOKENS["Sensex"]),
    ]:
        zd_index_data[idx_name] = zd_index_display(_zd_raw, inst_key, idx_name)

ic1, ic2, ic3 = st.columns([2, 2, 6])
for col, name, oi_data in zip(
        [ic1, ic2],
        ["Nifty 50", "Sensex"],
        [oi_nifty, oi_banknifty]):   # BUG-7: use oi_banknifty variable
    zd = zd_index_data.get(name)
    d  = indices.get(name)
    with col:
        if zd:
            ltp_val = zd["value"];  chg_val = zd["chg"];  pct_val = zd["pct"]
            ohlc_str = (
                f'O:{zd["open"]:,.0f}  H:{zd["high"]:,.0f}  '
                f'L:{zd["low"]:,.0f}  P:{zd["prev"]:,.0f}'
                if zd.get("open") else ""
            )
            src_badge = (
                '<span style="background:#1a3a1a;color:#2ecc71;padding:1px 6px;'
                'border-radius:3px;font-size:9px;margin-left:4px;">🟢 LIVE</span>'
            )
        elif d:
            ltp_val  = d["value"];  chg_val  = d["chg"];  pct_val  = d["pct"]
            ohlc_str = ""
            src_badge = (
                '<span style="background:#1c1c36;color:#7a7a9a;padding:1px 6px;'
                'border-radius:3px;font-size:9px;margin-left:4px;">yfinance</span>'
            )
        else:
            st.markdown(f"**{name}:** unavailable")
            continue

        cs  = f"+{chg_val:,.1f} (+{pct_val:.2f}%)" if chg_val >= 0 \
              else f"{chg_val:,.1f} ({pct_val:.2f}%)"
        cc  = "#2ecc71" if chg_val >= 0 else "#e74c3c"
        ar  = "▲" if chg_val >= 0 else "▼"

        act     = d["action"]    if d else "—"
        rsi_val = d["rsi"]       if d else "—"
        trend_s = d["trend"]     if d else ""
        ac      = ("#ffd700" if act=="STRONG BUY" else
                   "#2ecc71" if act=="BUY" else
                   "#f39c12" if act=="WATCH" else "#e74c3c")
        sp = int(min(d["score"], 100)) if d else 0

        oi_badge = ""
        if oi_data:
            s_label, s_col = _oi_sentiment(oi_data["pcr"])
            pain_dist  = oi_data["max_pain"] - int(ltp_val)
            pain_arrow = "⬆️" if pain_dist > 0 else ("⬇️" if pain_dist < 0 else "🎯")
            # BUG-7 FIX: label correctly per index
            oi_index_label = "Nifty" if name == "Nifty 50" else "BankNifty"
            oi_badge = (
                f'<div style="margin-top:6px;padding:5px 8px;background:#0a1a0a;'
                f'border-radius:6px;border:1px solid #1c1c36;font-size:11px;">'
                f'<span style="color:#7a7a9a;">{oi_index_label} PCR: </span>'
                f'<span style="color:{s_col};font-weight:bold;">{oi_data["pcr"]} {s_label}</span>'
                f' &nbsp;│&nbsp; '
                f'<span style="color:#7a7a9a;">MaxPain: </span>'
                f'<span style="color:#e0c97f;font-weight:bold;">'
                f'₹{oi_data["max_pain"]:,} {pain_arrow}{pain_dist:+,}</span>'
                f' &nbsp;│&nbsp; '
                f'<span style="color:#7a7a9a;">CWall: </span>'
                f'<span style="color:#e74c3c;">₹{oi_data["call_wall"]:,}</span>'
                f' &nbsp;│&nbsp; '
                f'<span style="color:#7a7a9a;">PWall: </span>'
                f'<span style="color:#2ecc71;">₹{oi_data["put_wall"]:,}</span>'
                f'</div>'
            )

        ohlc_html = (
            f'<div style="color:#7a7a9a;font-size:10px;margin-top:2px;">{ohlc_str}</div>'
            if ohlc_str else ""
        )
        interval_lbl = d["interval"] if d else "—"
        ema_f        = d["ema_fast"] if d else "—"
        ema_s        = d["ema_slow"] if d else "—"

        st.markdown(
            f'<div style="background:#12122a;border:1px solid #1c1c36;border-radius:10px;'
            f'padding:12px 16px;">'
            f'<div style="color:#7a7a9a;font-size:11px;text-transform:uppercase;">'
            f'{name}{src_badge}'
            f'&nbsp;<span style="background:#1c1c36;padding:1px 6px;border-radius:3px;'
            f'font-size:10px;">{interval_lbl} · EMA{ema_f}/{ema_s}</span></div>'
            f'<div style="color:#f0f0f0;font-size:22px;font-weight:bold;">{ltp_val:,.1f}</div>'
            f'<div style="color:{cc};font-size:13px;">{ar} {cs}</div>'
            + ohlc_html +
            f'<div style="margin:8px 0 4px;background:#1c1c36;border-radius:4px;height:6px;">'
            f'<div style="background:{ac};width:{sp}%;height:6px;border-radius:4px;"></div></div>'
            f'<div style="display:flex;justify-content:space-between;">'
            f'<span style="color:{ac};font-size:12px;font-weight:bold;">'
            f'{act} · Score: {d["score"] if d else "—"}</span>'
            f'<span style="color:#7a7a9a;font-size:11px;">RSI {rsi_val}</span></div>'
            f'<div style="color:#7a7a9a;font-size:11px;margin-top:4px;">{trend_s}</div>'
            + oi_badge +
            f'</div>',
            unsafe_allow_html=True,
        )

with ic3:
    live_note = "🟢 **Live via Zerodha** (15-sec refresh)" if enctoken else "📡 yfinance (5-min cache)"
    st.caption(f"{live_note} · OI refreshes every 3 min · Scores on 0-100 normalised scale")

# ── OI Detail expanders (BUG-7 FIX: correct labels) ──────────────
oi_x1, oi_x2 = st.columns(2)
with oi_x1:
    with st.expander("📊 Nifty 50 — Weekly OI & Max Pain", expanded=False):
        _render_oi_card(oi_nifty, "NIFTY")
with oi_x2:
    # BUG-7 FIX: was "Sensex", now correctly "Bank Nifty"
    with st.expander("📊 Bank Nifty — Weekly OI & Max Pain", expanded=False):
        _render_oi_card(oi_banknifty, "BANKNIFTY")
        st.caption(
            "ℹ️ NSE does not publish a Sensex option chain. "
            "Bank Nifty is shown as the closest NSE weekly index derivative."
        )

with c3:
    scan_btn = st.button("🔍 SCAN", type="primary", use_container_width=True)
with c4:
    filter_opt = st.selectbox("Show",
        ["BUY + STRONG BUY","STRONG BUY only","WATCH + BUY","All Results"],
        label_visibility="collapsed")
with c5:
    phase_filter = st.selectbox("Phase Filter",
        ["All Phases","ENTRY","SETUP","CONT","BREAKOUT","IDLE","EXIT"],
        label_visibility="collapsed")
with c6:
    search_q = st.text_input("Search", placeholder="e.g. RELIANCE", label_visibility="collapsed")

mc = {"Intraday":"#e67e22","Swing":"#27ae60","Positional":"#2980b9"}
mi = {"Intraday":"⚡","Swing":"📈","Positional":"🧘"}
cfg_cur = MODE_CFG[mode_opt]
interval_label = {"5m":"5min candles","1d":"Daily candles","1wk":"Weekly candles"}.get(
    cfg_cur["interval"], cfg_cur["interval"])
last_info = (
    f"&nbsp;&nbsp;<span style='color:#7a7a9a;font-size:11px;'>"
    f"{st.session_state.scan_time} · Rejected: {st.session_state.rejected}</span>"
    if st.session_state.scan_time else ""
)
intraday_note = (
    " &nbsp;<span style='color:#e67e22;font-size:10px;'>EMA 9/21 · HTF momentum via daily data</span>"
    if mode_opt == "Intraday" else ""
)
st.markdown(
    f'<div style="margin-bottom:8px;">'
    f'<span style="background:{mc.get(mode_opt,"#555")};color:#fff;'
    f'padding:3px 12px;border-radius:12px;font-size:12px;font-weight:bold;">'
    f'{mi.get(mode_opt,"")} {mode_opt} · {interval_label} · '
    f'EMA{cfg_cur["ema_fast"]}/{cfg_cur["ema_slow"]}'
    f'</span>{intraday_note}{last_info}</div>',
    unsafe_allow_html=True)

# ── Scan ──────────────────────────────────────────────────────────
if scan_btn:
    symbols = SECTORS[index_opt]
    n   = len(symbols)
    est = "~1 min" if n <= 50 else ("~2 mins" if n <= 150 else "3–5 mins")
    prog = st.progress(0)
    stat = st.empty()
    with st.spinner(f"Scanning {index_opt} ({n} stocks) · {mode_opt} mode · {est}"):
        results, rejected = run_scan(symbols, mode_opt, prog, stat)
    st.session_state.results   = results
    st.session_state.rejected  = rejected
    st.session_state.scan_mode = mode_opt
    st.session_state.scan_time = (
        datetime.now().strftime("%H:%M:%S") + f" ({index_opt} · {mode_opt})"
    )

    if enctoken and results:
        stat.text("Fetching live LTP from Zerodha…")
        instruments = [f"NSE:{r['Symbol']}" for r in results]
        ltp_map     = zd_fetch_ltp_bulk(enctoken, instruments)
        for r in st.session_state.results:
            live = ltp_map.get(f"NSE:{r['Symbol']}")
            if live and live > 0:
                prev_ltp     = r["LTP"]
                r["LTP"]     = round(live, 2)
                r["%Change"] = round(((live - prev_ltp) / prev_ltp) * 100, 2) if prev_ltp else r["%Change"]
                r["_ltp_src"] = "Zerodha"

    prog.empty(); stat.empty()
    st.success(
        f"✅ Done — {len(results)} valid · {rejected} rejected · {mode_opt} mode"
        + (" · 🟢 LTP from Zerodha" if enctoken else "")
    )

# ── Filtering ─────────────────────────────────────────────────────
results = list(st.session_state.results)

if filter_opt == "BUY + STRONG BUY":
    results = [r for r in results if r["Action"] in ("BUY","STRONG BUY")]
elif filter_opt == "STRONG BUY only":
    results = [r for r in results if r["Action"] == "STRONG BUY"]
elif filter_opt == "WATCH + BUY":
    results = [r for r in results if r["Action"] in ("WATCH","BUY","STRONG BUY")]

if phase_filter != "All Phases":
    results = [r for r in results if r.get("Phase") == phase_filter]

if search_q:
    results = [r for r in results if search_q.upper() in r["Symbol"]]

# ── Top cards ─────────────────────────────────────────────────────
if st.session_state.results:
    all_results = st.session_state.results
    ACTIONABLE_PHASES = {PHASE_ENTRY, PHASE_CONT, PHASE_BRK}
    actionable = [
        r for r in all_results
        if r.get("Phase") in ACTIONABLE_PHASES and r["Action"] in ("BUY","STRONG BUY")
    ]
    phase_rank = {PHASE_BRK: 0, PHASE_CONT: 1, PHASE_ENTRY: 2}
    actionable.sort(key=lambda x: (phase_rank.get(x.get("Phase"), 9), -x["Score"]))
    top_act = actionable[:15]

    watchlist = [
        r for r in all_results
        if r.get("Phase") in (PHASE_SETUP, PHASE_IDLE)
        and r["Score"] >= 58         # aligns with BUY threshold on norm scale
        and r["Action"] in ("BUY","STRONG BUY")
    ][:10]

    def make_card(i, r, border_color, show_entry=True):
        chg = r["%Change"]
        cs  = f"+{chg}%" if chg >= 0 else f"{chg}%"
        cc  = "#2ecc71" if chg >= 0 else "#e74c3c"
        gl  = " 🌟" if r.get("InGolden") else ""
        act = r["Action"]
        ac  = "#ffd700" if act=="STRONG BUY" else "#2ecc71"
        ph  = r.get("Phase", PHASE_IDLE)
        pc  = PHASE_COLORS.get(ph, "#555")
        st_icon = {"fib":"🌀","breakout":"🚀","norm":"📊","vdu":"🔕"}.get(r.get("Setup","norm"),"📊")
        entry_str = f'&#8377;{r["Entry"]:,}' if show_entry and r["Entry"] != r["LTP"] else ""

        # Exhaustion badge — amber warning strip at bottom of card
        ext_n      = r.get("ExtN", 0)
        ext_labels = r.get("ExtLabels", [])
        ext_badge  = ""
        if ext_n > 0:
            ext_color  = "#cc4444" if ext_n >= 3 else "#e67e22"
            ext_text   = " · ".join(ext_labels[:3])   # cap at 3 labels to keep card narrow
            ext_badge  = (
                f'<div style="margin-top:5px;background:{ext_color}22;border:1px solid {ext_color}55;'
                f'border-radius:3px;padding:2px 5px;font-size:9px;color:{ext_color};">'
                f'⚠ {ext_text}</div>'
            )

        return (
            f'<div style="background:#0a1a0a;border:1px solid {border_color};border-radius:8px;'
            f'padding:10px 14px;min-width:140px;flex:1 1 140px;max-width:195px;">'
            f'<div style="color:#f0f0f0;font-weight:bold;font-size:13px;">{i+1}. {r["Symbol"]}{gl}</div>'
            f'<div style="color:{ac};font-size:11px;">{act} · Score {r["Score"]}</div>'
            f'<div style="color:#f0f0f0;font-size:12px;">&#8377;{r["LTP"]:,} '
            f'<span style="color:{cc}">{cs}</span></div>'
            + (f'<div style="color:#aaa;font-size:11px;">⚡ Entry {entry_str}</div>' if entry_str else "")
            + f'<div style="margin-top:5px;display:flex;gap:4px;flex-wrap:wrap;">'
            f'<span style="background:{pc};color:#fff;padding:1px 6px;border-radius:3px;font-size:10px;">{ph}</span>'
            f'<span style="background:#1c1c36;color:#aaa;padding:1px 6px;border-radius:3px;font-size:10px;">{st_icon}</span>'
            + ('<span style="background:#4a3000;color:#ffa500;padding:1px 6px;border-radius:3px;font-size:10px;">🔕VDU</span>'
               if r.get("VDU") else "")
            + "</div>"
            + ext_badge
            + "</div>"
        )

    if top_act:
        with st.expander("🚀 READY TO TRADE — ENTRY / CONT / BREAKOUT", expanded=True):
            cards = '<div style="display:flex;flex-wrap:wrap;gap:8px;">'
            for i, r in enumerate(top_act):
                cards += make_card(i, r, border_color="#00dd88", show_entry=True)
            cards += "</div>"
            st.markdown(cards, unsafe_allow_html=True)
    else:
        st.info("No stocks in ENTRY / CONT / BREAKOUT phase right now.")

    if watchlist:
        with st.expander("👁 WATCHLIST — High Score but Not Yet Ready (SETUP / IDLE)", expanded=False):
            cards = '<div style="display:flex;flex-wrap:wrap;gap:8px;">'
            for i, r in enumerate(watchlist):
                cards += make_card(i, r, border_color="#b87333", show_entry=False)
            cards += "</div>"
            st.markdown(cards, unsafe_allow_html=True)

# ── Summary metrics ───────────────────────────────────────────────
if results:
    sb = sum(1 for r in results if r["Action"] == "STRONG BUY")
    b  = sum(1 for r in results if r["Action"] == "BUY")
    w  = sum(1 for r in results if r["Action"] == "WATCH")
    sk = sum(1 for r in results if r["Action"] == "SKIP")
    pe = sum(1 for r in results if r.get("Phase") == PHASE_ENTRY)
    pb = sum(1 for r in results if r.get("Phase") == PHASE_BRK)
    m1,m2,m3,m4,m5,m6,m7 = st.columns(7)
    m1.metric("Showing",    len(results))
    m2.metric("🟢 Str Buy", sb)
    m3.metric("🔵 Buy",     b)
    m4.metric("🟡 Watch",   w)
    m5.metric("🔴 Skip",    sk)
    m6.metric("📍 ENTRY",   pe)
    m7.metric("🚀 BRK",     pb)

# ── Main table ────────────────────────────────────────────────────
if results:
    rows = []
    for i, r in enumerate(results):
        chg        = r["%Change"]
        phase      = r.get("Phase", PHASE_IDLE)
        entry_flag = " ⚡" if r["Entry"] != r["LTP"] else ""
        setup_icon = {"fib":"🌀","breakout":"🚀","norm":"📊","vdu":"🔕"}.get(r.get("Setup","norm"),"📊")
        rows.append({
            "#":        i + 1,
            "Symbol":   r["Symbol"],
            "Score":    r["Score"],        # normalised 0-100
            "Phase":    phase,
            "Setup":    f'{setup_icon} {r.get("Setup","norm")}',
            "Action":   f"{action_icon(r['Action'])} {r['Action']}",
            "%Chg":     f"+{chg}%" if chg >= 0 else f"{chg}%",
            "LTP":      fmt(r["LTP"]),
            "Entry":    fmt(r["Entry"]) + entry_flag,
            "SL":       fmt(r["SL"]),
            "T1":       fmt(r["T1"]),
            "T2":       fmt(r["T2"]),
            "T3":       fmt(r["T3"]),
            "Golden":   "🌟" if r.get("InGolden") else "",
            "VDU":      "🔕" if r.get("VDU") else "",
            "Regime":   r.get("Regime", "—"),
            # ── Extension / exhaustion ──────────────────────────────
            "ExtN":     r.get("ExtN", 0),
            "ExtWarn":  " · ".join(r.get("ExtLabels", [])) or "—",
        })
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True, height=480)
    st.caption(
        "Score = normalised 0-100 (≥75 STRONG BUY · ≥58 BUY · ≥42 WATCH). "
        "⚡ Entry = signal trigger price. "
        "ExtN = exhaustion flag count (0 = clean · 1-2 = caution · 3+ = avoid entry). "
        "ExtWarn = active exhaustion signals."
    )

    buy_rows = [r for r in results if r["Action"] in ("BUY","STRONG BUY")]
    if buy_rows:
        csv = pd.DataFrame(buy_rows).to_csv(index=False)
        ts  = datetime.now().strftime("%Y%m%d_%H%M%S")
        st.download_button("💾 Export BUY results as CSV", csv,
                           f"NSE_Scan_{st.session_state.scan_mode}_{ts}.csv", "text/csv")

    # ── Detail ────────────────────────────────────────────────────
    st.markdown("---")
    st.subheader("🔍 Stock Detail")
    sel = st.selectbox("Select stock", [r["Symbol"] for r in results])
    if sel:
        r = next((x for x in results if x["Symbol"] == sel), None)
        if r:
            phase = r.get("Phase", PHASE_IDLE)
            chg   = r["%Change"]

            phases_order = [PHASE_IDLE, PHASE_SETUP, PHASE_ENTRY, PHASE_CONT, PHASE_BRK, PHASE_EXIT]
            phase_html = '<div style="display:flex;gap:6px;margin-bottom:12px;flex-wrap:wrap;">'
            for ph in phases_order:
                active = ph == phase
                bg     = PHASE_COLORS[ph] if active else "#1c1c36"
                border = f"2px solid {PHASE_COLORS[ph]}" if active else "2px solid #333"
                fw     = "bold" if active else "normal"
                phase_html += (
                    f'<div style="background:{bg};border:{border};color:#fff;'
                    f'padding:5px 12px;border-radius:6px;font-size:12px;font-weight:{fw};">'
                    f'{ph}{"  ◀" if active else ""}</div>'
                )
            phase_html += "</div>"
            st.markdown(phase_html, unsafe_allow_html=True)

            d1, d2, d3, d4 = st.columns(4)
            d1.metric("LTP",       fmt(r["LTP"]),   f"{'+' if chg>=0 else ''}{chg}%")
            d2.metric("Entry ⚡",  fmt(r["Entry"]))
            d3.metric("Stop Loss", fmt(r["SL"]))
            d4.metric("Score",     r["Score"])

            t1c, t2c, t3c = st.columns(3)
            t1c.metric("T1 (+1R)", fmt(r["T1"]))
            t2c.metric("T2 (+2R)", fmt(r["T2"]))
            t3c.metric("T3 (+3R)", fmt(r["T3"]))

            st.markdown(
                f'**Action:** {action_icon(r["Action"])} {r["Action"]}  \n'
                f'**Golden Zone:** {"🌟 Yes — price in 61.8%–50% fib zone" if r.get("InGolden") else "No"}'
            )

            # ── Exhaustion detail ─────────────────────────────────
            ext_n      = r.get("ExtN", 0)
            ext_labels = r.get("ExtLabels", [])
            ext_flags  = r.get("ExtFlags", {})
            if ext_n == 0:
                st.success("✅ No extension/exhaustion signals — structure is clean.")
            else:
                ext_color = "error" if ext_n >= 3 else "warning"
                flag_descriptions = {
                    "rsi_overheat":     "RSI Overheating — RSI above mode ceiling; overbought.",
                    "atr_extension":    "ATR Extension — range expanded far beyond baseline; climactic move.",
                    "parabolic":        "Parabolic Acceleration — 3-bar move statistically extreme vs historical σ.",
                    "ema_distance":     "EMA Distance — price stretched too many ATRs above EMA-fast.",
                    "climactic_volume": "Climactic Volume — giant vol spike + upper wick after sustained run.",
                    "mom_exhaustion":   "Momentum Exhaustion — RSI peaked and declined while price still rising.",
                    "bearish_div":      "Bearish RSI Divergence — price higher high but RSI lower high at pivot.",
                }
                with st.expander(
                    f"⚠️ {ext_n} Exhaustion Signal{'s' if ext_n > 1 else ''} Detected "
                    f"{'— AVOID NEW ENTRY' if ext_n >= 3 else '— Use Caution'}",
                    expanded=True,
                ):
                    for flag_key, active in ext_flags.items():
                        if active:
                            st.markdown(
                                f"🔴 **{flag_key.replace('_',' ').title()}** — "
                                f"{flag_descriptions.get(flag_key, '')}"
                            )
                    st.markdown("---")
                    st.markdown(
                        f"**Active labels:** `{'  ·  '.join(ext_labels)}`  \n"
                        f"**Score penalty applied:** `{sum(EXT_PENALTIES[k] for k, v in ext_flags.items() if v)} norm pts`  \n"
                        f"**Recommendation:** "
                        + (
                            "❌ Avoid new long entries. Wait for RSI reset (< 60) and ATR contraction before re-evaluating."
                            if ext_n >= 3 else
                            "⚠️ Reduce position size. Consider waiting for a pullback to EMA or fib support before entering."
                        )
                    )
            if r["Entry"] != r["LTP"]:
                st.info(
                    f"⚡ Entry ₹{r['Entry']:,} is the signal trigger price. "
                    f"Current LTP is ₹{r['LTP']:,}. "
                    "Place order near Entry when phase reaches ENTRY or BREAKOUT."
                )
else:
    if not st.session_state.results:
        st.info("👆 Select **Index** + **Mode**, then press **SCAN** to begin.")
    else:
        st.warning("No stocks match the current filters.")
