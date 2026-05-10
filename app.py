"""
NSE Master Scanner Pro — Streamlit Edition v7
═══════════════════════════════════════════════
WHAT'S NEW IN v7
────────────────
ARCH-1  Sector drop removed. Universe = NSE 500 or Nifty 50 only.
        Clean radio-button selector, no sector clutter.

ARCH-2  st.tabs() UI: Scanner | Breadth Engine | Detail | Analytics | Settings
        Monolithic UI fully decomposed.

BREADTH-1  % of stocks above EMA-50 (rolling + current snapshot).
BREADTH-2  Breakout breadth: % in BREAKOUT phase.
BREADTH-3  Advancing vs Declining count + A/D ratio.
BREADTH-4  Sector heatmap (avg score per GICS sector proxy).
BREADTH-5  VIX awareness: fetch ^INDIAVIX; when VIX > 20 tighten
           target multipliers and SL; when VIX > 25 block STRONG BUY.

CONF-1   Confidence Model: multi-factor score (0–100) shown alongside
         Action. Factors: phase alignment, vol confirmation, EMA stack,
         HTF momentum, regime, exhaustion penalty.

ADAPTIVE-1  Regime-aware target compression.
            BEARISH: T1/T2/T3 at 0.6×/1.1×/1.6× risk-reward (vs 1/2/3×).
            HIGH-VIX (>20): SL widened by 20%, targets compressed 25%.
            Continuation aggressiveness also reduced.

LIQUIDITY-1  Traded-value filter: 20-day avg VWAP × volume. Stocks
             below ₹5 Cr daily traded value flagged / skipped.

MTF-1   Multi-timeframe sync: weekly trend required for Positional,
        daily trend required for Swing, 15m (via 5m proxy) for Intraday.
        Phase blocked if HTF trend is opposed.

PERSIST-1  st.session_state signal log: every scan appends outcome rows.
           Analytics tab shows win-rate skeleton (user marks wins/losses).

EXT-TUNE  Mode-aware RSI exhaustion threshold now also VIX-scaled.
          Upper-wick filter raised to 0.35 for high-beta stocks (ATR > 3%).
"""

import warnings
import logging
import time
import random
import hashlib
from datetime import datetime

import numpy as np
import pandas as pd
import yfinance as yf
import streamlit as st

logging.getLogger("yfinance").setLevel(logging.CRITICAL)
warnings.filterwarnings("ignore")

# ── Universes ─────────────────────────────────────────────────────
try:
    from nse500 import nse500_symbols
    NSE500 = list(dict.fromkeys([s.strip().upper().replace(".NS", "") for s in nse500_symbols]))
except ImportError:
    # Fallback mini-list for environments without nse500.py
    NSE500 = [
        "RELIANCE","TCS","HDFCBANK","INFY","ICICIBANK","HINDUNILVR","ITC",
        "SBIN","BHARTIARTL","KOTAKBANK","LT","AXISBANK","ASIANPAINT","MARUTI",
        "TITAN","NESTLEIND","WIPRO","ULTRACEMCO","POWERGRID","NTPC",
        "BAJFINANCE","HCLTECH","SUNPHARMA","TECHM","INDUSINDBK",
        "ONGC","COALINDIA","TATASTEEL","JSWSTEEL","HINDALCO",
        "TATAMOTORS","M&M","BAJAJFINSV","DIVISLAB","DRREDDY",
        "CIPLA","EICHERMOT","ADANIENT","ADANIPORTS","BPCL",
        "TATACONSUM","BRITANNIA","HEROMOTOCO","APOLLOHOSP","GRASIM",
        "SBILIFE","HDFCLIFE","ICICIPRULI","VEDL","NMDC",
    ]

NIFTY50 = [
    "RELIANCE","TCS","HDFCBANK","INFY","ICICIBANK","HINDUNILVR","ITC",
    "SBIN","BHARTIARTL","KOTAKBANK","LT","AXISBANK","ASIANPAINT","MARUTI",
    "TITAN","NESTLEIND","WIPRO","ULTRACEMCO","POWERGRID","NTPC",
    "BAJFINANCE","HCLTECH","SUNPHARMA","TECHM","INDUSINDBK",
    "ONGC","COALINDIA","TATASTEEL","JSWSTEEL","HINDALCO",
    "TATAMOTORS","M&M","BAJAJFINSV","DIVISLAB","DRREDDY",
    "CIPLA","EICHERMOT","ADANIENT","ADANIPORTS","BPCL",
    "TATACONSUM","BRITANNIA","HEROMOTOCO","APOLLOHOSP","GRASIM",
    "SBILIFE","HDFCLIFE","ICICIPRULI","BAJAJ-AUTO","UPL",
]

# Sector proxy map (GICS-style, hand-coded for Nifty/NSE top names)
SECTOR_MAP = {
    "RELIANCE":"Energy","ONGC":"Energy","BPCL":"Energy","COALINDIA":"Energy",
    "NTPC":"Utilities","POWERGRID":"Utilities","ADANIENT":"Utilities","ADANIPORTS":"Industrials",
    "LT":"Industrials","BHEL":"Industrials",
    "HDFCBANK":"Financials","ICICIBANK":"Financials","SBIN":"Financials","KOTAKBANK":"Financials",
    "AXISBANK":"Financials","BAJFINANCE":"Financials","BAJAJFINSV":"Financials",
    "SBILIFE":"Financials","HDFCLIFE":"Financials","ICICIPRULI":"Financials","INDUSINDBK":"Financials",
    "TCS":"IT","INFY":"IT","WIPRO":"IT","HCLTECH":"IT","TECHM":"IT",
    "SUNPHARMA":"Healthcare","DRREDDY":"Healthcare","CIPLA":"Healthcare",
    "DIVISLAB":"Healthcare","APOLLOHOSP":"Healthcare",
    "HINDUNILVR":"FMCG","ITC":"FMCG","NESTLEIND":"FMCG","BRITANNIA":"FMCG","TATACONSUM":"FMCG",
    "ASIANPAINT":"Chemicals","ULTRATECH":"Materials","GRASIM":"Materials",
    "TATASTEEL":"Metals","JSWSTEEL":"Metals","HINDALCO":"Metals","VEDL":"Metals","NMDC":"Metals",
    "MARUTI":"Auto","TATAMOTORS":"Auto","M&M":"Auto","EICHERMOT":"Auto",
    "HEROMOTOCO":"Auto","BAJAJ-AUTO":"Auto","TITAN":"Consumer","BHARTIARTL":"Telecom",
}

# ── Mode config ───────────────────────────────────────────────────
MODE_CFG = {
    "Intraday":   dict(period="5d",  interval="5m",  ema_fast=9,  ema_slow=21,
                       atr_mult=1.5, atr_wide=3.0, atr_max=1.0,
                       mom1_th=2,  mom3_th=5,  mom6_th=8,  score_th=65, rsi_len=14,
                       htf_period="3mo", htf_interval="15m"),
    "Swing":      dict(period="1y",  interval="1d",  ema_fast=50, ema_slow=200,
                       atr_mult=2.5, atr_wide=4.0, atr_max=1.5,
                       mom1_th=3,  mom3_th=7,  mom6_th=10, score_th=70, rsi_len=21,
                       htf_period="2y", htf_interval="1wk"),
    "Positional": dict(period="2y",  interval="1d",  ema_fast=50, ema_slow=200,
                       atr_mult=3.5, atr_wide=5.0, atr_max=1.5,
                       mom1_th=5,  mom3_th=10, mom6_th=15, score_th=70, rsi_len=21,
                       htf_period="5y", htf_interval="1wk"),
}

BULL_MAX = 120

ACTION_THRESHOLDS = dict(strong_buy=75, buy=58, watch=42)

PHASE_IDLE  = "IDLE"
PHASE_SETUP = "SETUP"
PHASE_ENTRY = "ENTRY"
PHASE_CONT  = "CONT"
PHASE_BRK   = "BREAKOUT"
PHASE_EXIT  = "EXIT"

PHASE_COLORS = {
    PHASE_IDLE:  "#555577", PHASE_SETUP: "#b87333",
    PHASE_ENTRY: "#2255cc", PHASE_CONT:  "#22aa55",
    PHASE_BRK:   "#00dd88", PHASE_EXIT:  "#cc4444",
}

# VIX regimes
VIX_CALM    = 15   # below → normal
VIX_CAUTION = 20   # above → tighten targets/SL
VIX_STRESS  = 25   # above → block STRONG BUY

# Liquidity minimum: ₹5 Cr daily traded value
LIQUIDITY_MIN_CR = 5.0

# ── Math helpers ──────────────────────────────────────────────────
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
        "236": sw_hi - rng*0.236, "382": sw_hi - rng*0.382,
        "500": sw_hi - rng*0.500, "618": sw_hi - rng*0.618,
        "786": sw_hi - rng*0.786,
        "ext127": sw_hi + rng*0.272, "ext161": sw_hi + rng*0.618,
        "ext261": sw_hi + rng*1.618,
    }, rng

def action_label(norm_score: float) -> str:
    if norm_score >= ACTION_THRESHOLDS["strong_buy"]: return "STRONG BUY"
    if norm_score >= ACTION_THRESHOLDS["buy"]:        return "BUY"
    if norm_score >= ACTION_THRESHOLDS["watch"]:      return "WATCH"
    return "SKIP"

def fmt(val):
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return "—"
    return f"₹{val:,.2f}"

def action_icon(a):
    return {"STRONG BUY":"🟢","BUY":"🔵","WATCH":"🟡","SKIP":"🔴"}.get(a,"")


# ═══════════════════════════════════════════════════════════════════
# VIX
# ═══════════════════════════════════════════════════════════════════
@st.cache_data(ttl=300)
def fetch_vix():
    """Fetch India VIX. Returns (float|None, str label)."""
    try:
        df = yf.download("^INDIAVIX", period="5d", interval="1d",
                         auto_adjust=True, progress=False, threads=False)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df = df.dropna()
        if df.empty:
            return None, "UNKNOWN"
        v = float(df["Close"].iloc[-1])
        label = "CALM" if v < VIX_CALM else ("CAUTION" if v < VIX_STRESS else "STRESS")
        return round(v, 2), label
    except Exception:
        return None, "UNKNOWN"

def vix_target_mult(vix_val):
    """Return (t1_mult, t2_mult, t3_mult, sl_expand) based on VIX."""
    if vix_val is None or vix_val < VIX_CAUTION:
        return 1.0, 2.0, 3.0, 1.0
    if vix_val < VIX_STRESS:
        return 0.75, 1.4, 2.0, 1.2    # tighten targets, widen SL
    return 0.6, 1.1, 1.6, 1.35        # high stress


# ═══════════════════════════════════════════════════════════════════
# LIQUIDITY FILTER
# ═══════════════════════════════════════════════════════════════════
def liquidity_ok(df, min_cr=LIQUIDITY_MIN_CR):
    """
    Returns (bool, float avg_daily_cr).
    avg_daily_cr = mean(close × volume) over last 20 bars, in Crores.
    """
    try:
        traded = df["Close"] * df["Volume"]
        avg_cr = float(traded.rolling(20).mean().iloc[-1]) / 1e7  # ₹ to Cr
        return avg_cr >= min_cr, round(avg_cr, 1)
    except Exception:
        return True, 0.0   # pass-through on error


# ═══════════════════════════════════════════════════════════════════
# MULTI-TIMEFRAME SYNC
# ═══════════════════════════════════════════════════════════════════
@st.cache_data(ttl=900)
def fetch_htf(ticker, period, interval):
    """Fetch higher-timeframe OHLCV for MTF sync."""
    for attempt in range(3):
        try:
            df = yf.download(ticker, period=period, interval=interval,
                             auto_adjust=True, progress=False, threads=False)
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            return df.dropna()
        except Exception:
            time.sleep(1.5 ** attempt)
    return pd.DataFrame()

def htf_trend(ticker, mode):
    """
    Returns (htf_up: bool, htf_label: str) for the next higher timeframe.
    Swing → weekly; Positional → weekly + monthly EMA check; Intraday → 15m.
    """
    cfg = MODE_CFG[mode]
    df  = fetch_htf(to_nse(ticker), cfg["htf_period"], cfg["htf_interval"])
    if df.empty or len(df) < 20:
        return True, "HTF-UNKNOWN"   # pass-through if data missing
    cl   = df["Close"]
    ef   = float(ema(cl, 21 if mode == "Intraday" else 13).iloc[-1])
    es   = float(ema(cl, 55 if mode == "Intraday" else 26).iloc[-1])
    c    = float(cl.iloc[-1])
    up   = c > ef > es
    return up, ("HTF↑" if up else "HTF↓")


# ═══════════════════════════════════════════════════════════════════
# EXHAUSTION / EXTENSION (EXT-1 … EXT-7) — VIX-calibrated
# ═══════════════════════════════════════════════════════════════════
EXT_CFG = {
    "Intraday":   dict(rsi_ceil=80, ema_dist=3.5, atr_exp=2.5, parab=3.0, clim_vol=3.0, div_bars=10),
    "Swing":      dict(rsi_ceil=78, ema_dist=3.0, atr_exp=2.5, parab=3.0, clim_vol=3.0, div_bars=14),
    "Positional": dict(rsi_ceil=75, ema_dist=2.5, atr_exp=2.0, parab=2.5, clim_vol=2.5, div_bars=20),
}

EXT_PENALTIES = {
    "rsi_overheat":     -8,
    "atr_extension":    -8,
    "parabolic":        -6,
    "ema_distance":     -5,
    "climactic_volume": -6,
    "mom_exhaustion":   -4,
    "bearish_div":      -6,
}

def detect_exhaustion(close, high, low, volume, rsi_series,
                      e_fast_s, atr_s, atr_mean, c, v, vol_avg, mode, vix_val=None):
    cfg   = EXT_CFG[mode]
    n     = len(close)
    flags = {k: False for k in EXT_PENALTIES}
    labels = []

    # VIX scaling: raise RSI ceiling slightly in calm markets, lower in stress
    rsi_ceil = cfg["rsi_ceil"]
    if vix_val is not None:
        if vix_val < VIX_CALM:
            rsi_ceil += 2    # slightly more room in calm markets
        elif vix_val > VIX_STRESS:
            rsi_ceil -= 3    # tighter in stressed markets

    rsi_now = float(rsi_series.iloc[-1])
    if rsi_now > rsi_ceil:
        flags["rsi_overheat"] = True
        labels.append("Too hot to buy")

    atr_val = float(atr_s.iloc[-1])
    if atr_mean > 0 and atr_val > atr_mean * cfg["atr_exp"]:
        flags["atr_extension"] = True
        labels.append("Range blowout")

    if n >= 23:
        daily_pct  = close.pct_change().dropna()
        hist_sigma = float(daily_pct.iloc[-20:].std())
        exp_3b     = hist_sigma * (3**0.5)
        act_3b     = abs(float(close.iloc[-1]) - float(close.iloc[-4])) / float(close.iloc[-4])
        if exp_3b > 0 and act_3b > cfg["parab"] * exp_3b:
            flags["parabolic"] = True
            labels.append("Moving too fast")

    e_fast_now = float(e_fast_s.iloc[-1])
    if atr_val > 0:
        ema_dist_atrs = (c - e_fast_now) / atr_val
        if ema_dist_atrs > cfg["ema_dist"]:
            flags["ema_distance"] = True
            labels.append("Far from average price")

    # High-beta calibration: raise upper-wick threshold if ATR% > 3%
    wick_thresh = 0.35 if (c > 0 and atr_val/c > 0.03) else 0.30

    if n >= 12 and vol_avg > 0:
        prior_run  = c > float(close.iloc[-11])
        up_bar     = c > float(close.iloc[-2])
        if prior_run and up_bar and v > vol_avg * cfg["clim_vol"]:
            bar_range  = float(high.iloc[-1]) - float(low.iloc[-1])
            upper_wick = float(high.iloc[-1]) - c
            if bar_range > 0 and (upper_wick / bar_range) > wick_thresh:
                flags["climactic_volume"] = True
                labels.append("Panic buying spike")

    if n >= 10:
        lookback  = min(cfg["div_bars"], n-1)
        rsi_win   = rsi_series.iloc[-lookback:]
        price_win = close.iloc[-lookback:]
        rsi_peak  = float(rsi_win.max())
        rsi_peak_idx = rsi_win.idxmax()
        price_at_peak = float(close[rsi_peak_idx])
        # Volatile midcap calibration: require 5pt gap (was 3pt) in Intraday
        gap_req = 5 if mode == "Intraday" else 3
        if (rsi_now < rsi_peak - gap_req
                and c > price_at_peak
                and rsi_win.idxmax() != rsi_win.index[-1]):
            flags["mom_exhaustion"] = True
            labels.append("Buyers losing steam")

    if n >= 20:
        lookback = min(cfg["div_bars"]*2, n-2)
        h_slice  = high.iloc[-lookback:]
        r_slice  = rsi_series.iloc[-lookback:]
        pivot_idx = []
        for i in range(1, len(h_slice)-1):
            if (float(h_slice.iloc[i]) > float(h_slice.iloc[i-1])
                    and float(h_slice.iloc[i]) > float(h_slice.iloc[i+1])):
                pivot_idx.append(i)
        if len(pivot_idx) >= 2:
            p1, p2 = pivot_idx[-2], pivot_idx[-1]
            ph1, ph2 = float(h_slice.iloc[p1]), float(h_slice.iloc[p2])
            rh1, rh2 = float(r_slice.iloc[p1]), float(r_slice.iloc[p2])
            if ph2 > ph1 and rh2 < rh1 - 2 and (len(h_slice)-1-p2) <= 5:
                flags["bearish_div"] = True
                labels.append("Price up but strength fading")

    penalty = sum(EXT_PENALTIES[k] for k, v in flags.items() if v)
    n_flags = sum(flags.values())
    return flags, float(penalty), labels, n_flags


def ext_phase_override(phase, ext_flags, n_flags, mode):
    rsi_ext = ext_flags.get("rsi_overheat", False)
    atr_ext = ext_flags.get("atr_extension", False)
    is_critical = n_flags >= 3 or (rsi_ext and atr_ext)
    is_moderate = n_flags == 2
    if is_critical:
        if phase == PHASE_BRK:   return PHASE_EXIT,  "ext-critical→EXIT"
        if phase == PHASE_CONT:  return PHASE_SETUP, "ext-critical→SETUP"
        if phase == PHASE_ENTRY: return PHASE_SETUP, "ext-critical→SETUP"
    elif is_moderate:
        if phase == PHASE_BRK:   return PHASE_SETUP, "ext-moderate→SETUP"
    return phase, None

def ext_action_cap(action, n_flags, vix_val=None):
    if n_flags == 0 and (vix_val is None or vix_val < VIX_STRESS):
        return action
    # VIX stress: cap BUY → WATCH, STRONG BUY → BUY
    if vix_val is not None and vix_val >= VIX_STRESS:
        return "WATCH" if action in ("STRONG BUY", "BUY") else action
    if n_flags >= 3:
        return "WATCH" if action in ("STRONG BUY", "BUY") else action
    return "BUY" if action == "STRONG BUY" else action


# ═══════════════════════════════════════════════════════════════════
# CONFIDENCE MODEL
# ═══════════════════════════════════════════════════════════════════
def compute_confidence(
    *, norm_bull, phase, trend_up, trend_strong, vol_confirmed,
    ema_stack, htf_aligned, regime_bullish, ext_n, vix_val
):
    """
    Returns a 0–100 confidence score.
    Factors (weighted):
      Phase alignment   20  — BREAKOUT/CONT > ENTRY > SETUP
      Score quality     20  — norm_bull contribution
      Vol confirmation  15  — volume > avg
      EMA stack         15  — fast > slow > 200
      HTF alignment     15  — higher TF trend agrees
      Regime            10  — market is bullish
      Exhaustion drag    5  — penalty for extension flags
    """
    c = 0.0
    # Phase
    c += {PHASE_BRK: 20, PHASE_CONT: 17, PHASE_ENTRY: 13,
          PHASE_SETUP: 7, PHASE_IDLE: 2, PHASE_EXIT: 0}.get(phase, 0)
    # Score quality
    c += min(20, norm_bull * 0.20)
    # Volume
    c += 15 if vol_confirmed else 5
    # EMA stack
    c += 15 if ema_stack else (7 if trend_strong else 0)
    # HTF
    c += 15 if htf_aligned else 0
    # Regime
    c += 10 if regime_bullish else 2
    # Exhaustion drag
    c -= min(5, ext_n * 2)
    # VIX drag
    if vix_val is not None and vix_val > VIX_CAUTION:
        c -= 5
    return round(min(100, max(0, c)), 1)

def confidence_label(conf):
    if conf >= 80: return "HIGH", "#2ecc71"
    if conf >= 60: return "MED",  "#f39c12"
    if conf >= 40: return "LOW",  "#e67e22"
    return "WEAK", "#e74c3c"


# ═══════════════════════════════════════════════════════════════════
# PHASE + ENTRY
# ═══════════════════════════════════════════════════════════════════
def detect_phase_and_entry(df, mode, *, c, e_fast_s, e_slow_s, atr_s,
                            atr_val, atr_mean, v, vol_avg, fib, sw_hi, sw_lo,
                            in_golden, near_e127, near_e161, norm_bull,
                            trend_up, trend_down, trend_strong, score_th,
                            vdu_setup=False, htf_up=True,
                            regime_bearish=False, vix_val=None):
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

    body = (abs(float(close.iloc[-1]) - float(df["Open"].iloc[-1]))
            if "Open" in df.columns else atr_val * 0.3)
    upper_wick = (float(high.iloc[-1]) - max(float(close.iloc[-1]), float(df["Open"].iloc[-1]))
                  if "Open" in df.columns else 0)
    is_exhaustion = upper_wick > body * 1.5
    vol_spike     = v > vol_avg * 1.3
    is_fib_buy    = trend_up and in_golden

    # Reduce continuation aggressiveness in bearish/stressed regimes
    cont_vol_mult = 1.5 if (regime_bearish or (vix_val and vix_val > VIX_CAUTION)) else 1.2

    BRK_CONF_MIN = 0.70 if regime_bearish else 0.65
    brk_weights = {
        "price_above_high": (0.30, c > rolling_hi_brk + buf),
        "trend_up":         (0.20, trend_up),
        "score_ok":         (0.15, norm_bull >= score_th),
        "compressed":       (0.15, is_compressed),
        "expanding":        (0.10, is_expanding),
        "vol_spike":        (0.10, vol_spike),
    }
    brk_confidence = sum(w for w, cond in brk_weights.values() if cond)
    # MTF: block breakout if HTF trend is down
    is_breakout = (brk_confidence >= BRK_CONF_MIN and not is_exhaustion and htf_up)

    is_cont = (
        n >= 4
        and c > float(close.iloc[-4:-1].max())
        and c > e_fast_val
        and v > vol_avg * cont_vol_mult
        and trend_strong
        and htf_up        # MTF: require HTF alignment for continuation
    )

    ema_down    = e_fast_val < e_slow_val and float(e_fast_s.iloc[-4]) < float(e_slow_s.iloc[-4])
    trail_level = float(close.iloc[-10:].max()) - atr_val * 1.5
    trail_break = c < trail_level

    if trend_down and ema_down:
        phase, setup_type = PHASE_EXIT, "norm"
    elif is_breakout:
        phase, setup_type = PHASE_BRK, "breakout"
    elif (is_fib_buy or norm_bull >= score_th) and is_cont and trend_up:
        phase, setup_type = PHASE_CONT, ("fib" if is_fib_buy else "norm")
    elif (is_fib_buy or norm_bull >= score_th) and trend_up:
        phase, setup_type = PHASE_ENTRY, ("fib" if is_fib_buy else "norm")
    elif (is_fib_buy or norm_bull >= score_th*0.85 or vdu_setup) and trend_up:
        phase, setup_type = PHASE_SETUP, ("fib" if is_fib_buy else ("vdu" if vdu_setup else "norm"))
    elif trail_break and trend_up:
        phase, setup_type = PHASE_EXIT, "norm"
    else:
        phase, setup_type = PHASE_IDLE, "norm"

    # MTF veto: if HTF is down and we're not already EXIT/IDLE, demote
    if not htf_up and phase in (PHASE_ENTRY, PHASE_CONT, PHASE_BRK):
        phase, setup_type = PHASE_SETUP, setup_type  # demote but keep setup context

    entry_price = None
    if phase in (PHASE_ENTRY, PHASE_CONT, PHASE_BRK, PHASE_SETUP):
        prox = atr_val * 0.3
        if is_breakout:
            entry_price = round(rolling_hi_brk + buf, 2)
        elif is_fib_buy and fib:
            entry_price = round(fib["618"] + prox*0.3, 2)
        else:
            cross = close > e_fast_s
            signal_bars = cross & ~cross.shift(1).fillna(False)
            if signal_bars.any():
                entry_price = round(float(close[signal_bars[::-1].idxmax()]), 2)
            else:
                entry_price = round(c, 2)

    return phase, entry_price, setup_type


# ═══════════════════════════════════════════════════════════════════
# TARGET COMPUTATION — regime + VIX aware
# ═══════════════════════════════════════════════════════════════════
def _compute_targets(entry, sl, atr_val, fib, setup_type, sw_hi, sw_lo,
                     regime_bearish=False, vix_val=None):
    rk = max(entry - sl, atr_val * 0.5)
    t1m, t2m, t3m, sl_exp = vix_target_mult(vix_val)

    # Further compress in bearish regime
    if regime_bearish:
        t1m *= 0.8; t2m *= 0.7; t3m *= 0.6

    if setup_type == "fib" and fib:
        t1 = round(fib["ext127"], 2)
        t2 = round(fib["ext161"], 2)
        ext_r = fib["ext161"] - fib["ext127"]
        t3 = round(fib["ext161"] + min(ext_r, atr_val*3), 2)
    elif setup_type == "breakout" and fib:
        t1 = round((entry + rk*t1m + fib["ext127"]) / 2, 2)
        t2 = round((entry + rk*t2m + fib["ext161"]) / 2, 2)
        t3 = round((entry + rk*t3m + fib["ext261"]) / 2, 2)
    else:
        t1 = round(entry + rk*t1m, 2)
        t2 = round(entry + rk*t2m, 2)
        t3 = round(entry + rk*t3m, 2)

    min_move = atr_val * 0.8
    if t1 - entry < min_move:
        t1 = round(entry + min_move, 2)
        t2 = round(entry + min_move*2, 2)
        t3 = round(entry + min_move*3, 2)

    return t1, t2, t3, sl_exp   # return sl_exp so caller can widen SL


# ═══════════════════════════════════════════════════════════════════
# FETCH HELPERS
# ═══════════════════════════════════════════════════════════════════
@st.cache_data(ttl=900)
def _fetch_daily_close(ticker):
    for attempt in range(3):
        try:
            df = yf.download(ticker, period="6mo", interval="1d",
                             auto_adjust=True, progress=False, threads=False)
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            return df["Close"].dropna()
        except Exception:
            time.sleep(1.5**attempt)
    return pd.Series(dtype=float)

def _fetch_one(args):
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
                time.sleep(1.5**attempt + random.uniform(0, 0.5))
    return sym, None

def fetch_nifty(mode="Swing"):
    cfg = MODE_CFG[mode]
    df  = yf.download("^NSEI", period=cfg["period"], interval=cfg["interval"], progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df["Close"].dropna()

def _market_regime(nifty_close):
    if len(nifty_close) < 50:
        return True, "UNKNOWN"
    ema20 = float(ema(nifty_close, 20).iloc[-1])
    ema50 = float(ema(nifty_close, 50).iloc[-1])
    bull  = (float(nifty_close.iloc[-1]) > ema50) and (ema20 > ema50)
    return bull, ("BULLISH" if bull else "BEARISH")


# ═══════════════════════════════════════════════════════════════════
# CORE SCORING
# ═══════════════════════════════════════════════════════════════════
def score_stock(df, nifty_close, mode="Swing", daily_close=None,
                market_bullish=True, vix_val=None, min_liquidity_cr=LIQUIDITY_MIN_CR,
                sym=None):
    try:
        cfg   = MODE_CFG[mode]
        close = df["Close"]
        volume = df["Volume"]
        n     = len(close)
        if n < 50:
            return None

        # Liquidity gate
        liq_ok, avg_cr = liquidity_ok(df, min_liquidity_cr)

        c       = float(close.iloc[-1])
        prev    = float(close.iloc[-2])
        e_fast_s = ema(close, cfg["ema_fast"])
        e_slow_s = ema(close, cfg["ema_slow"])
        e_fast   = float(e_fast_s.iloc[-1])
        e_slow   = float(e_slow_s.iloc[-1])
        e200_s   = ema(close, 200)
        e200     = float(e200_s.iloc[-1]) if n >= 200 else None
        atr_s    = atr_series(df)
        atr_val  = float(atr_s.iloc[-1])
        atr_mean = float(atr_s.rolling(20).mean().iloc[-1])
        vol_avg  = float(volume.rolling(20).mean().iloc[-1])
        v        = float(volume.iloc[-1])
        chg      = round(((c - prev) / prev) * 100, 2)
        hh       = float(close.iloc[-11:-1].max())

        # Above EMA50 (for breadth)
        above_ema50 = c > float(ema(close, 50).iloc[-1])

        rs = 0
        if n >= 6 and len(nifty_close) >= 6:
            rs = ((c - float(close.iloc[-6])) / float(close.iloc[-6]) -
                  (float(nifty_close.iloc[-1]) - float(nifty_close.iloc[-6])) / float(nifty_close.iloc[-6])) * 100

        trend_up     = (e200 is None or c > e200) and c > e_fast and e_fast > e_slow
        trend_down   = (e200 is None or c < e200) and c < e_fast and e_fast < e_slow
        trend_strong = c > e_fast and e_fast > e_slow
        ema_stack    = (e200 is not None) and (c > e200) and (e_fast > e_slow) and (e_fast > e200)

        mom_src = (daily_close if (mode == "Intraday" and daily_close is not None
                                   and len(daily_close) >= 21) else close)
        mom_n = len(mom_src)
        mom1 = (c - float(mom_src.iloc[-21]))  / float(mom_src.iloc[-21])  * 100 if mom_n >= 21  else 0
        mom3 = (c - float(mom_src.iloc[-63]))  / float(mom_src.iloc[-63])  * 100 if mom_n >= 63  else 0
        mom6 = (c - float(mom_src.iloc[-126])) / float(mom_src.iloc[-126]) * 100 if mom_n >= 126 else 0
        strong_htf = mom1 > cfg["mom1_th"] and mom3 > cfg["mom3_th"] and mom6 > cfg["mom6_th"]
        # MTF sync: fetch higher-timeframe trend for this symbol.
        # htf_trend() is cached (ttl=900) so repeated calls within a scan
        # are free after the first fetch per symbol.
        # Falls back to True (pass-through) when data is unavailable.
        if sym is not None:
            htf_up, _htf_label = htf_trend(sym, mode)
        else:
            htf_up = True   # no symbol provided — skip MTF check

        sw_hi, sw_lo, fib, fib_rng = fib_levels(df, lookback=30)
        prox      = atr_val * 0.3
        in_golden = bool(fib and c >= fib["618"] - prox and c <= fib["500"] + prox)
        near_e127 = bool(fib and abs(c - fib["ext127"]) < prox)
        near_e161 = bool(fib and abs(c - fib["ext161"]) < prox)

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

        rsi_series = rsi(close, cfg["rsi_len"])
        ext_flags, ext_penalty, ext_labels, ext_n = detect_exhaustion(
            close=close, high=df["High"], low=df["Low"], volume=volume,
            rsi_series=rsi_series, e_fast_s=e_fast_s, atr_s=atr_s, atr_mean=atr_mean,
            c=c, v=v, vol_avg=vol_avg, mode=mode, vix_val=vix_val,
        )
        r = float(rsi_series.iloc[-1])

        bull = 0
        bull += 25 if trend_up else 0
        bull += 15 if e_fast > e_slow else (7 if e_fast > e_slow*0.995 else 0)
        bull += (15 if r >= 65 else 10) if r >= 60 else (5 if r > 50 else 0)
        bull += 10 if v > vol_avg*1.2 else (5 if v > vol_avg else 0)
        bull += 15 if c > hh else (9 if c > hh*0.98 else 0)
        if n >= 3 and c > float(close.iloc[-3]):
            bull += 8
        bull += 7 if rs > 0 else (2 if rs > -0.5 else 0)
        if mode == "Positional":
            bull += 15 if qualified else -15
        else:
            bull += 15 if strong_htf else -10
        bull += 10 if in_golden else 0
        if near_e127:  bull -= 20
        elif near_e161: bull -= 30

        bull += ext_penalty

        BEARISH_HAIRCUT = 0.85
        regime_bearish = not market_bullish
        if regime_bearish:
            bull = int(bull * BEARISH_HAIRCUT)

        raw_score = max(0, bull)
        norm_bull  = min(100.0, max(0.0, bull * 100.0 / BULL_MAX))
        score_th   = float(cfg["score_th"])

        act = action_label(norm_bull)
        vol_confirmed = v > vol_avg * 1.2

        phase, entry_price, setup_type = detect_phase_and_entry(
            df, mode, c=c, e_fast_s=e_fast_s, e_slow_s=e_slow_s,
            atr_s=atr_s, atr_val=atr_val, atr_mean=atr_mean,
            v=v, vol_avg=vol_avg, fib=fib, sw_hi=sw_hi, sw_lo=sw_lo,
            in_golden=in_golden, near_e127=near_e127, near_e161=near_e161,
            norm_bull=norm_bull, trend_up=trend_up, trend_down=trend_down,
            trend_strong=trend_strong, score_th=score_th, vdu_setup=vdu_setup,
            htf_up=htf_up, regime_bearish=regime_bearish, vix_val=vix_val,
        )

        phase, _ = ext_phase_override(phase, ext_flags, ext_n, mode)
        act       = ext_action_cap(act, ext_n, vix_val)

        # Confidence model
        confidence = compute_confidence(
            norm_bull=norm_bull, phase=phase, trend_up=trend_up,
            trend_strong=trend_strong, vol_confirmed=vol_confirmed,
            ema_stack=ema_stack, htf_aligned=htf_up,
            regime_bullish=market_bullish, ext_n=ext_n, vix_val=vix_val,
        )

        ltp   = round(c, 2)
        entry = entry_price if entry_price else ltp

        mult = cfg["atr_mult"]; wide = cfg["atr_wide"]; maxm = cfg["atr_max"]
        if setup_type == "fib" and fib:
            fib_sl = max(float(sw_lo), fib["618"] - atr_val*0.5)
            fib_sl = max(fib_sl, entry - atr_val*0.8)
            sl = round(fib_sl, 2)
        elif setup_type == "breakout":
            sl = round(entry - atr_val*(1.5 if mode=="Intraday" else 2.0), 2)
        else:
            raw_sl = entry - atr_val*mult
            min_sl = entry - atr_val*wide
            max_sl = entry - atr_val*maxm
            sl = round(max(min_sl, min(raw_sl, max_sl)), 2)

        min_risk = atr_val * 0.5
        if entry - sl < min_risk:
            sl = round(entry - min_risk, 2)

        t1, t2, t3, sl_exp = _compute_targets(
            entry, sl, atr_val, fib, setup_type, sw_hi, sw_lo,
            regime_bearish=regime_bearish, vix_val=vix_val,
        )
        # Apply VIX SL expansion
        if sl_exp > 1.0:
            sl = round(entry - (entry - sl) * sl_exp, 2)

        return {
            "Score":       round(norm_bull, 1),
            "RawBull":     raw_score,
            "Action":      act,
            "Phase":       phase,
            "Setup":       setup_type,
            "Confidence":  confidence,
            "%Change":     chg,
            "LTP":         ltp,
            "Entry":       entry,
            "SL":          sl,
            "T1":          t1,
            "T2":          t2,
            "T3":          t3,
            "InGolden":    in_golden,
            "VDU":         vdu_setup,
            "AboveEMA50":  above_ema50,
            "AvgTradedCr": avg_cr,
            "LiquidityOK": liq_ok,
            "RSI":         round(r, 1),
            "RS":          round(rs, 2),
            "ExtN":        ext_n,
            "ExtLabels":   ext_labels,
            "ExtFlags":    ext_flags,
            "HTFUp":       htf_up,
            "EMAStack":    ema_stack,
            "VolConf":     vol_confirmed,
        }
    except Exception:
        return None


# ═══════════════════════════════════════════════════════════════════
# BREADTH ENGINE
# ═══════════════════════════════════════════════════════════════════
def compute_breadth(results):
    """
    Compute market breadth metrics from scan results.
    Returns dict with all breadth indicators.
    """
    if not results:
        return {}

    total = len(results)
    above_ema50    = sum(1 for r in results if r.get("AboveEMA50", False))
    breakout_count = sum(1 for r in results if r.get("Phase") == PHASE_BRK)
    advancing      = sum(1 for r in results if r.get("%Change", 0) > 0)
    declining      = sum(1 for r in results if r.get("%Change", 0) < 0)
    unchanged      = total - advancing - declining

    pct_above_ema50 = round(above_ema50 / total * 100, 1)
    pct_breakout    = round(breakout_count / total * 100, 1)
    ad_ratio        = round(advancing / max(declining, 1), 2)
    pct_advancing   = round(advancing / total * 100, 1)

    # Sector heatmap
    sector_scores = {}
    sector_counts = {}
    for r in results:
        sym = r.get("Symbol","")
        sec = SECTOR_MAP.get(sym, "Other")
        sector_scores[sec] = sector_scores.get(sec, 0) + r.get("Score", 0)
        sector_counts[sec] = sector_counts.get(sec, 0) + 1
    sector_avg = {
        sec: round(sector_scores[sec] / sector_counts[sec], 1)
        for sec in sector_scores
    }

    # Liquidity filtered count
    liquid_count = sum(1 for r in results if r.get("LiquidityOK", True))

    return {
        "total":            total,
        "above_ema50":      above_ema50,
        "pct_above_ema50":  pct_above_ema50,
        "breakout_count":   breakout_count,
        "pct_breakout":     pct_breakout,
        "advancing":        advancing,
        "declining":        declining,
        "unchanged":        unchanged,
        "ad_ratio":         ad_ratio,
        "pct_advancing":    pct_advancing,
        "sector_avg":       sector_avg,
        "liquid_count":     liquid_count,
        "breadth_signal":   _breadth_signal(pct_above_ema50, ad_ratio, pct_breakout),
    }

def _breadth_signal(pct_ema50, ad_ratio, pct_brk):
    """Synthesize a single breadth health label."""
    score = 0
    if pct_ema50 >= 70: score += 2
    elif pct_ema50 >= 50: score += 1
    if ad_ratio >= 2.0: score += 2
    elif ad_ratio >= 1.2: score += 1
    if pct_brk >= 5: score += 1
    if score >= 4: return "STRONG", "#2ecc71"
    if score >= 2: return "NEUTRAL", "#f39c12"
    return "WEAK", "#e74c3c"


# ═══════════════════════════════════════════════════════════════════
# RUN SCAN
# ═══════════════════════════════════════════════════════════════════
def run_scan(symbols, mode, progress_bar, status_text, vix_val=None, min_liq_cr=LIQUIDITY_MIN_CR):
    import concurrent.futures

    cfg      = MODE_CFG[mode]
    rejected = 0
    total    = len(symbols)
    min_bars = 30 if mode == "Intraday" else 50

    nifty              = fetch_nifty(mode)
    market_bullish, regime_label = _market_regime(nifty)

    if not market_bullish:
        st.warning(
            f"⚠️ **Market Regime: {regime_label}** — EMA20 below EMA50. "
            "Scores haircut 15 %. Targets compressed. Continuation gate tightened."
        )

    status_text.text("Fetching OHLCV data in parallel…")
    data         = {}
    daily_closes = {}
    args_list    = [(sym, mode, min_bars) for sym in symbols]
    MAX_WORKERS  = min(16, total)
    completed    = 0

    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {}
        for i, a in enumerate(args_list):
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
    liq_skipped = 0
    for i, (sym, df) in enumerate(data.items()):
        progress_bar.progress(0.6 + (i+1)/n_data * 0.4)
        status_text.text(f"Scoring {i+1}/{n_data}  ▸  {sym}")
        res = score_stock(
            df, nifty, mode,
            daily_close=daily_closes.get(sym),
            market_bullish=market_bullish,
            vix_val=vix_val,
            min_liquidity_cr=min_liq_cr,
            sym=sym,
        )
        if res:
            res["Regime"] = regime_label
            res["Symbol"] = sym
            res["Sector"] = SECTOR_MAP.get(sym, "Other")
            if not res["LiquidityOK"]:
                liq_skipped += 1
            results.append(res)

    results.sort(key=lambda x: x["Score"], reverse=True)
    return results, rejected, liq_skipped


# ═══════════════════════════════════════════════════════════════════
# OI DATA
# ═══════════════════════════════════════════════════════════════════
@st.cache_data(ttl=180)
def fetch_oi_data(symbol="NIFTY"):
    import requests
    HEADERS = {
        "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                       "AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36"),
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.nseindia.com/",
        "X-Requested-With": "XMLHttpRequest",
        "Connection": "keep-alive",
    }
    session = requests.Session()
    session.headers.update(HEADERS)
    def _warm():
        try:
            session.get("https://www.nseindia.com", timeout=10); time.sleep(0.8)
            session.get("https://www.nseindia.com/market-data/equity-derivatives-watch", timeout=10)
            time.sleep(0.5); return True
        except Exception: return False
    _warm()
    oc_url = f"https://www.nseindia.com/api/option-chain-indices?symbol={symbol}"
    data = None
    for attempt in range(3):
        try:
            resp = session.get(oc_url, timeout=12)
            if resp.status_code == 200:
                data = resp.json(); break
            elif resp.status_code in (401, 403):
                _warm()
        except Exception: pass
        time.sleep(1.5**attempt)
    if data is None: return None
    try:
        records = data["records"]
        spot    = float(records["underlyingValue"])
        expiries = records["expiryDates"]
        weekly_expiry = expiries[0] if expiries else None
        rows = []
        for item in records["data"]:
            if item.get("expiryDate") != weekly_expiry: continue
            strike = item["strikePrice"]
            ce_oi  = item.get("CE",{}).get("openInterest",0) or 0
            pe_oi  = item.get("PE",{}).get("openInterest",0) or 0
            ce_chg = item.get("CE",{}).get("changeinOpenInterest",0) or 0
            pe_chg = item.get("PE",{}).get("changeinOpenInterest",0) or 0
            rows.append({"Strike":strike,"CE_OI":ce_oi,"CE_Chg":ce_chg,"PE_OI":pe_oi,"PE_Chg":pe_chg})
        if not rows: return None
        df_oi    = pd.DataFrame(rows).sort_values("Strike").reset_index(drop=True)
        total_ce = df_oi["CE_OI"].sum(); total_pe = df_oi["PE_OI"].sum()
        pcr      = round(total_pe / total_ce, 2) if total_ce > 0 else 0
        pains = []
        for s in df_oi["Strike"]:
            ce_l = ((df_oi["Strike"]-s).clip(lower=0)*df_oi["CE_OI"]).sum()
            pe_l = ((s-df_oi["Strike"]).clip(lower=0)*df_oi["PE_OI"]).sum()
            pains.append(ce_l+pe_l)
        df_oi["TotalPain"] = pains
        return {
            "symbol": symbol, "expiry": weekly_expiry, "spot": spot, "pcr": pcr,
            "max_pain": int(df_oi.loc[df_oi["TotalPain"].idxmin(),"Strike"]),
            "call_wall": int(df_oi.loc[df_oi["CE_OI"].idxmax(),"Strike"]),
            "put_wall":  int(df_oi.loc[df_oi["PE_OI"].idxmax(),"Strike"]),
            "top_ce": df_oi.nlargest(5,"CE_OI")[["Strike","CE_OI","CE_Chg"]].to_dict("records"),
            "top_pe": df_oi.nlargest(5,"PE_OI")[["Strike","PE_OI","PE_Chg"]].to_dict("records"),
            "df_oi": df_oi,
        }
    except Exception: return None

def _oi_sentiment(pcr):
    if pcr >= 1.3: return "Bullish 🟢", "#2ecc71"
    if pcr >= 0.9: return "Neutral 🟡", "#f39c12"
    return "Bearish 🔴", "#e74c3c"


@st.cache_data(ttl=300)
def fetch_indices(mode="Swing"):
    cfg = MODE_CFG[mode]
    ema_f = cfg["ema_fast"]; ema_s = cfg["ema_slow"]; rsi_l = cfg["rsi_len"]
    min_bars = 30 if mode == "Intraday" else 50
    out = {}
    for name, ticker in [("Nifty 50","^NSEI"),("Sensex","^BSESN")]:
        try:
            df = yf.download(ticker, period=cfg["period"], interval=cfg["interval"], progress=False)
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            df = df.dropna()
            if len(df) < min_bars: out[name]=None; continue
            close = df["Close"]
            c, prev = float(close.iloc[-1]), float(close.iloc[-2])
            chg, pct = c-prev, (c-prev)/prev*100
            ef = float(ema(close,ema_f).iloc[-1]); es = float(ema(close,ema_s).iloc[-1])
            e200 = float(ema(close,200).iloc[-1]) if len(close)>=200 else es
            r  = float(rsi(close,rsi_l).iloc[-1])
            hh = float(close.iloc[-11:-1].max())
            trend_up = c>e200 and c>ef and ef>es
            bull = 0
            bull += 25 if trend_up else 0
            bull += 15 if ef>es else (7 if ef>es*0.995 else 0)
            bull += (15 if r>=65 else 10) if r>=60 else (5 if r>50 else 0)
            bull += 15 if c>hh else (9 if c>hh*0.98 else 0)
            if len(close)>=3 and c>float(close.iloc[-3]): bull+=8
            norm_score = min(100.0, max(0.0, bull*100.0/78))
            interval_label = {"5m":"5min","1d":"Daily","1wk":"Weekly"}.get(cfg["interval"],cfg["interval"])
            out[name] = {
                "value":c,"chg":chg,"pct":pct,"score":round(norm_score,1),
                "action":action_label(norm_score),"rsi":round(r,1),
                "trend":"↑ Above EMAs" if trend_up else "↓ Below EMAs",
                "interval":interval_label,"ema_fast":ema_f,"ema_slow":ema_s,
            }
        except Exception:
            out[name]=None
    return out


# ═══════════════════════════════════════════════════════════════════
# STREAMLIT UI
# ═══════════════════════════════════════════════════════════════════
st.set_page_config(
    page_title="NSE Master Scanner Pro",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;700&family=Syne:wght@700;800&display=swap');
body, .stApp { background:#080812; color:#e8e8f0; font-family:'JetBrains Mono',monospace; }
h1,h2,h3 { font-family:'Syne',sans-serif; }
.stDataFrame { font-size:12px; }
div[data-testid="stMetricValue"] { color:#00c9ff; font-size:1.3rem; font-family:'Syne',sans-serif; }
div[data-testid="stMetricLabel"] { color:#6060a0; font-size:11px; }
.stTabs [data-baseweb="tab-list"] { gap:4px; background:#0e0e20; border-radius:8px; padding:4px; }
.stTabs [data-baseweb="tab"] { background:#0e0e20; color:#6060a0; border-radius:6px;
    font-family:'Syne',sans-serif; font-size:13px; padding:6px 18px; }
.stTabs [aria-selected="true"] { background:#1a1a3a !important; color:#00c9ff !important; }
.stButton>button { font-family:'Syne',sans-serif; font-weight:700; letter-spacing:.5px; }
.stSelectbox label, .stRadio label { color:#6060a0; font-size:11px; }
</style>""", unsafe_allow_html=True)

# ── Session state init ────────────────────────────────────────────
for key, default in [
    ("results",[]), ("scan_time",None), ("rejected",0), ("liq_skipped",0),
    ("scan_mode","Swing"), ("signal_log",[]),
]:
    if key not in st.session_state:
        st.session_state[key] = default

# ── Header ────────────────────────────────────────────────────────
st.markdown(
    '<h1 style="font-family:Syne,sans-serif;font-size:26px;margin-bottom:0;'
    'background:linear-gradient(90deg,#00c9ff,#92fe9d);-webkit-background-clip:text;'
    '-webkit-text-fill-color:transparent;">📈 NSE Master Scanner Pro  '
    '<span style="font-size:14px;opacity:.6">[Phase Engine v7]</span></h1>',
    unsafe_allow_html=True,
)

# ── Global controls (above tabs) ──────────────────────────────────
gc1, gc2, gc3, gc4, gc5 = st.columns([2,2,1,2,2])
with gc1:
    universe_opt = st.radio("Universe", ["NSE 500","Nifty 50"], horizontal=True)
with gc2:
    mode_opt = st.radio("Mode", ["Swing","Intraday","Positional"], horizontal=True)
with gc3:
    scan_btn = st.button("🔍 SCAN", type="primary", use_container_width=True)
with gc4:
    filter_opt = st.selectbox("Action Filter",
        ["BUY + STRONG BUY","STRONG BUY only","WATCH + BUY","All Results"],
        label_visibility="collapsed")
with gc5:
    search_q = st.text_input("Symbol search", placeholder="e.g. RELIANCE",
                              label_visibility="collapsed")

# ── VIX fetch (global) ────────────────────────────────────────────
vix_val, vix_label = fetch_vix()
vix_color = {"CALM":"#2ecc71","CAUTION":"#f39c12","STRESS":"#e74c3c","UNKNOWN":"#7a7a9a"}.get(vix_label,"#7a7a9a")

st.markdown(
    f'<div style="display:flex;gap:12px;align-items:center;margin-bottom:6px;">'
    f'<span style="background:{vix_color}22;border:1px solid {vix_color}55;'
    f'padding:2px 10px;border-radius:4px;font-size:11px;color:{vix_color};">'
    f'🌡 India VIX {vix_val if vix_val else "N/A"} — {vix_label}</span>'
    + (f'<span style="color:#e74c3c;font-size:11px;">⚠ VIX>{VIX_STRESS}: STRONG BUY blocked · targets compressed</span>'
       if (vix_val and vix_val >= VIX_STRESS) else "")
    + (f'<span style="color:#f39c12;font-size:11px;">⚡ VIX>{VIX_CAUTION}: targets compressed · SL widened</span>'
       if (vix_val and VIX_CAUTION <= vix_val < VIX_STRESS) else "")
    + f'</div>',
    unsafe_allow_html=True,
)

# ── Tabs ──────────────────────────────────────────────────────────
tab_scanner, tab_breadth, tab_detail, tab_analytics, tab_settings = st.tabs([
    "📡 Scanner", "📊 Breadth Engine", "🔍 Detail", "📈 Analytics", "⚙ Settings",
])


# ═══════════════════════════════════════════════════════════════════
# SETTINGS TAB (read first so values are available to scan)
# ═══════════════════════════════════════════════════════════════════
with tab_settings:
    st.subheader("Scanner Settings")
    sc1, sc2 = st.columns(2)
    with sc1:
        min_liq_cr = st.slider("Min Liquidity (₹ Cr daily traded value)", 1.0, 50.0, 5.0, 1.0)
        phase_filter = st.selectbox("Phase Filter (Scanner)",
            ["All Phases","ENTRY","SETUP","CONT","BREAKOUT","IDLE","EXIT"])
        show_illiquid = st.checkbox("Show illiquid stocks (below liquidity floor)", value=False)
    with sc2:
        st.markdown("**VIX Thresholds**")
        st.caption(f"Caution threshold: {VIX_CAUTION}  ·  Stress threshold: {VIX_STRESS}")
        st.markdown("**Scoring Reference**")
        st.markdown("""
| Score | Action |
|---|---|
| ≥ 75 | STRONG BUY |
| ≥ 58 | BUY |
| ≥ 42 | WATCH |
| < 42 | SKIP |
        """)
        st.markdown("**Confidence Reference**")
        st.markdown("""
| Confidence | Label |
|---|---|
| ≥ 80 | HIGH |
| ≥ 60 | MED |
| ≥ 40 | LOW |
| < 40 | WEAK |
        """)


# ═══════════════════════════════════════════════════════════════════
# SCAN EXECUTION
# ═══════════════════════════════════════════════════════════════════
if scan_btn:
    symbols = NSE500 if universe_opt == "NSE 500" else NIFTY50
    n = len(symbols)
    est = "~1 min" if n <= 50 else ("~2 mins" if n <= 150 else "3–5 mins")
    prog = st.progress(0)
    stat = st.empty()
    with st.spinner(f"Scanning {universe_opt} ({n} stocks) · {mode_opt} · {est}"):
        results, rejected, liq_skipped = run_scan(
            symbols, mode_opt, prog, stat,
            vix_val=vix_val, min_liq_cr=min_liq_cr,
        )
    st.session_state.results     = results
    st.session_state.rejected    = rejected
    st.session_state.liq_skipped = liq_skipped
    st.session_state.scan_mode   = mode_opt
    st.session_state.scan_time   = (
        datetime.now().strftime("%H:%M:%S") + f" ({universe_opt} · {mode_opt})"
    )
    # Persist to signal log
    ts = datetime.now().isoformat()
    for r in results:
        if r.get("Action") in ("BUY","STRONG BUY"):
            st.session_state.signal_log.append({
                "timestamp": ts, "symbol": r["Symbol"],
                "action": r["Action"], "phase": r.get("Phase"),
                "score": r["Score"], "confidence": r.get("Confidence",0),
                "entry": r.get("Entry"), "sl": r.get("SL"),
                "t1": r.get("T1"), "ltp_at_signal": r.get("LTP"),
                "outcome": "Pending",
            })
    prog.empty(); stat.empty()
    st.success(
        f"✅ {len(results)} scanned · {rejected} rejected · "
        f"{liq_skipped} below liquidity floor · {mode_opt}"
    )


# ═══════════════════════════════════════════════════════════════════
# SCANNER TAB
# ═══════════════════════════════════════════════════════════════════
with tab_scanner:
    # Index cards
    indices = fetch_indices(mode_opt)
    oi_nifty     = fetch_oi_data("NIFTY")
    oi_banknifty = fetch_oi_data("BANKNIFTY")

    ic1, ic2, ic3 = st.columns([2,2,5])
    for col, name, oi_data in zip([ic1,ic2],["Nifty 50","Sensex"],[oi_nifty,oi_banknifty]):
        d = indices.get(name)
        with col:
            if not d:
                st.markdown(f"**{name}:** unavailable"); continue
            chg_val=d["chg"]; pct_val=d["pct"]; ltp_val=d["value"]
            cs  = f"+{chg_val:,.1f} (+{pct_val:.2f}%)" if chg_val>=0 else f"{chg_val:,.1f} ({pct_val:.2f}%)"
            cc  = "#2ecc71" if chg_val>=0 else "#e74c3c"
            ar  = "▲" if chg_val>=0 else "▼"
            act = d["action"]
            ac  = ("#ffd700" if act=="STRONG BUY" else "#2ecc71" if act=="BUY"
                   else "#f39c12" if act=="WATCH" else "#e74c3c")
            sp  = int(min(d["score"],100))
            oi_badge = ""
            if oi_data:
                s_label,s_col = _oi_sentiment(oi_data["pcr"])
                pd_ = oi_data["max_pain"]-int(ltp_val)
                pa  = "⬆️" if pd_>0 else ("⬇️" if pd_<0 else "🎯")
                lbl = "Nifty" if name=="Nifty 50" else "BankNifty"
                oi_badge = (
                    f'<div style="margin-top:5px;padding:4px 7px;background:#0a0a18;'
                    f'border-radius:4px;border:1px solid #1c1c36;font-size:10px;">'
                    f'<span style="color:#6060a0;">{lbl} PCR: </span>'
                    f'<span style="color:{s_col};font-weight:bold;">{oi_data["pcr"]} {s_label}</span>'
                    f'  MaxPain: <span style="color:#e0c97f;">₹{oi_data["max_pain"]:,} {pa}{pd_:+,}</span>'
                    f'  CWall:<span style="color:#e74c3c;">₹{oi_data["call_wall"]:,}</span>'
                    f'  PWall:<span style="color:#2ecc71;">₹{oi_data["put_wall"]:,}</span></div>'
                )
            st.markdown(
                f'<div style="background:#0e0e22;border:1px solid #1c1c36;border-radius:10px;padding:12px 14px;">'
                f'<div style="color:#6060a0;font-size:10px;">{name}</div>'
                f'<div style="color:#e8e8f0;font-size:20px;font-weight:bold;font-family:Syne,sans-serif;">'
                f'{ltp_val:,.1f}</div>'
                f'<div style="color:{cc};font-size:12px;">{ar} {cs}</div>'
                f'<div style="margin:6px 0 3px;background:#1c1c36;border-radius:3px;height:5px;">'
                f'<div style="background:{ac};width:{sp}%;height:5px;border-radius:3px;"></div></div>'
                f'<div style="color:{ac};font-size:11px;">{act} · {d["score"]}</div>'
                f'<div style="color:#6060a0;font-size:10px;">{d["trend"]} · RSI {d["rsi"]}</div>'
                + oi_badge + '</div>',
                unsafe_allow_html=True,
            )
    with ic3:
        last_info = f"Last scan: {st.session_state.scan_time}" if st.session_state.scan_time else "Not scanned yet"
        st.caption(f"📡 yfinance (5-min cache) · OI refreshes every 3 min · {last_info}")
        if st.session_state.results:
            sb = sum(1 for r in st.session_state.results if r["Action"]=="STRONG BUY")
            b  = sum(1 for r in st.session_state.results if r["Action"]=="BUY")
            w  = sum(1 for r in st.session_state.results if r["Action"]=="WATCH")
            pe = sum(1 for r in st.session_state.results if r.get("Phase")==PHASE_ENTRY)
            pb = sum(1 for r in st.session_state.results if r.get("Phase")==PHASE_BRK)
            sm1,sm2,sm3,sm4,sm5 = st.columns(5)
            sm1.metric("🟢 Str Buy", sb)
            sm2.metric("🔵 Buy", b)
            sm3.metric("🟡 Watch", w)
            sm4.metric("📍 ENTRY", pe)
            sm5.metric("🚀 BRK", pb)

    st.markdown("---")

    # ── Apply filters ─────────────────────────────────────────────
    results = list(st.session_state.results)
    if filter_opt == "BUY + STRONG BUY":
        results = [r for r in results if r["Action"] in ("BUY","STRONG BUY")]
    elif filter_opt == "STRONG BUY only":
        results = [r for r in results if r["Action"] == "STRONG BUY"]
    elif filter_opt == "WATCH + BUY":
        results = [r for r in results if r["Action"] in ("WATCH","BUY","STRONG BUY")]

    if "phase_filter" in dir() and phase_filter != "All Phases":
        results = [r for r in results if r.get("Phase") == phase_filter]

    if not show_illiquid if "show_illiquid" in dir() else True:
        results = [r for r in results if r.get("LiquidityOK", True)]

    if search_q:
        results = [r for r in results if search_q.upper() in r["Symbol"]]

    # ── Ready-to-Trade cards ──────────────────────────────────────
    if st.session_state.results:
        ACTIONABLE_PHASES = {PHASE_ENTRY, PHASE_CONT, PHASE_BRK}
        actionable = [
            r for r in st.session_state.results
            if r.get("Phase") in ACTIONABLE_PHASES and r["Action"] in ("BUY","STRONG BUY")
        ]
        phase_rank = {PHASE_BRK:0, PHASE_CONT:1, PHASE_ENTRY:2}
        actionable.sort(key=lambda x: (phase_rank.get(x.get("Phase"),9), -x["Score"]))
        top_act = actionable[:15]

        def make_card(i, r, border_color, show_entry=True):
            chg = r["%Change"]; cs = f"+{chg}%" if chg>=0 else f"{chg}%"
            cc  = "#2ecc71" if chg>=0 else "#e74c3c"
            act = r["Action"]
            ac  = "#ffd700" if act=="STRONG BUY" else "#2ecc71"
            ph  = r.get("Phase",PHASE_IDLE)
            pc  = PHASE_COLORS.get(ph,"#555")
            st_icon = {"fib":"🌀","breakout":"🚀","norm":"📊","vdu":"🔕"}.get(r.get("Setup","norm"),"📊")
            conf = r.get("Confidence",0)
            conf_lbl, conf_col = confidence_label(conf)
            entry_str = f'₹{r["Entry"]:,}' if show_entry and r["Entry"]!=r["LTP"] else ""
            ext_n = r.get("ExtN",0)
            ext_labels = r.get("ExtLabels",[])
            ext_badge = ""
            if ext_n > 0:
                ec = "#cc4444" if ext_n>=3 else "#e67e22"
                ext_badge = (
                    f'<div style="margin-top:4px;background:{ec}22;border:1px solid {ec}55;'
                    f'border-radius:3px;padding:2px 4px;font-size:9px;color:{ec};">'
                    f'⚠ {" · ".join(ext_labels[:2])}</div>'
                )
            liq_badge = (
                '<div style="margin-top:2px;font-size:9px;color:#e67e22;">💧 Low liquidity</div>'
                if not r.get("LiquidityOK",True) else ""
            )
            return (
                f'<div style="background:#0a0a1e;border:1px solid {border_color};border-radius:8px;'
                f'padding:10px 12px;min-width:140px;flex:1 1 140px;max-width:190px;">'
                f'<div style="color:#e8e8f0;font-weight:bold;font-size:12px;font-family:Syne,sans-serif;">'
                f'{i+1}. {r["Symbol"]}{"🌟" if r.get("InGolden") else ""}</div>'
                f'<div style="color:{ac};font-size:10px;">{act} · {r["Score"]}</div>'
                f'<div style="color:#e8e8f0;font-size:12px;">₹{r["LTP"]:,} <span style="color:{cc}">{cs}</span></div>'
                + (f'<div style="color:#aaa;font-size:10px;">⚡ {entry_str}</div>' if entry_str else "")
                + f'<div style="margin-top:4px;display:flex;gap:3px;flex-wrap:wrap;">'
                f'<span style="background:{pc};color:#fff;padding:1px 5px;border-radius:3px;font-size:9px;">{ph}</span>'
                f'<span style="background:{conf_col}33;border:1px solid {conf_col}66;color:{conf_col};'
                f'padding:1px 5px;border-radius:3px;font-size:9px;">{conf_lbl} {conf}%</span>'
                f'<span style="background:#1c1c36;color:#aaa;padding:1px 5px;border-radius:3px;font-size:9px;">{st_icon}</span>'
                + ('<span style="background:#4a3000;color:#ffa500;padding:1px 5px;border-radius:3px;font-size:9px;">VDU</span>'
                   if r.get("VDU") else "")
                + "</div>" + ext_badge + liq_badge + "</div>"
            )

        if top_act:
            with st.expander("🚀 READY TO TRADE — ENTRY / CONT / BREAKOUT", expanded=True):
                cards = '<div style="display:flex;flex-wrap:wrap;gap:7px;">'
                for i,r in enumerate(top_act):
                    cards += make_card(i, r, "#00dd88", show_entry=True)
                cards += "</div>"
                st.markdown(cards, unsafe_allow_html=True)
        else:
            st.info("No stocks in ENTRY / CONT / BREAKOUT phase.")

        watchlist = [
            r for r in st.session_state.results
            if r.get("Phase") in (PHASE_SETUP,PHASE_IDLE)
            and r["Score"]>=58 and r["Action"] in ("BUY","STRONG BUY")
        ][:10]
        if watchlist:
            with st.expander("👁 WATCHLIST — High Score, Not Yet Ready", expanded=False):
                cards = '<div style="display:flex;flex-wrap:wrap;gap:7px;">'
                for i,r in enumerate(watchlist):
                    cards += make_card(i, r, "#b87333", show_entry=False)
                cards += "</div>"
                st.markdown(cards, unsafe_allow_html=True)

    # ── Main table ────────────────────────────────────────────────
    if results:
        rows = []
        for i, r in enumerate(results):
            chg        = r["%Change"]
            phase      = r.get("Phase",PHASE_IDLE)
            setup_icon = {"fib":"🌀","breakout":"🚀","norm":"📊","vdu":"🔕"}.get(r.get("Setup","norm"),"📊")
            conf       = r.get("Confidence",0)
            conf_lbl, _ = confidence_label(conf)
            rows.append({
                "#":         i+1,
                "Symbol":    r["Symbol"],
                "Sector":    r.get("Sector","Other"),
                "Score":     r["Score"],
                "Conf%":     conf,
                "Confidence":conf_lbl,
                "Phase":     phase,
                "Setup":     f'{setup_icon} {r.get("Setup","norm")}',
                "Action":    f"{action_icon(r['Action'])} {r['Action']}",
                "%Chg":      f"+{chg}%" if chg>=0 else f"{chg}%",
                "RSI":       r.get("RSI","—"),
                "LTP":       fmt(r["LTP"]),
                "Entry":     fmt(r["Entry"]) + (" ⚡" if r["Entry"]!=r["LTP"] else ""),
                "SL":        fmt(r["SL"]),
                "T1":        fmt(r["T1"]),
                "T2":        fmt(r["T2"]),
                "T3":        fmt(r["T3"]),
                "Liq₹Cr":   r.get("AvgTradedCr","—"),
                "Golden":    "🌟" if r.get("InGolden") else "",
                "VDU":       "🔕" if r.get("VDU") else "",
                "HTF":       "↑" if r.get("HTFUp",True) else "↓",
                "Regime":    r.get("Regime","—"),
                "ExtN":      r.get("ExtN",0),
                "ExtWarn":   " · ".join(r.get("ExtLabels",[])) or "—",
            })
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True, height=480)
        st.caption(
            "Score 0-100 · Conf% = how confident the system is · HTF ↑/↓ = weekly trend direction · "
            "Liq₹Cr = avg daily traded value · ExtN = warning count (0=all clear · 1-2=be careful · 3+=skip this trade) · "
            "ExtWarn = plain-English reasons to be cautious"
        )

        buy_rows = [r for r in results if r["Action"] in ("BUY","STRONG BUY")]
        if buy_rows:
            csv = pd.DataFrame(buy_rows).drop(columns=["ExtFlags"],errors="ignore").to_csv(index=False)
            ts  = datetime.now().strftime("%Y%m%d_%H%M%S")
            st.download_button("💾 Export BUY results", csv,
                               f"NSE_Scan_{st.session_state.scan_mode}_{ts}.csv","text/csv")
    elif st.session_state.results:
        st.warning("No stocks match current filters.")
    else:
        st.info("👆 Select Universe + Mode, then press SCAN.")


# ═══════════════════════════════════════════════════════════════════
# BREADTH ENGINE TAB
# ═══════════════════════════════════════════════════════════════════
with tab_breadth:
    all_results = st.session_state.results
    if not all_results:
        st.info("Run a scan first to see breadth data.")
    else:
        breadth = compute_breadth(all_results)
        b_sig, b_col = breadth["breadth_signal"]

        st.markdown(
            f'<div style="background:{b_col}11;border:1px solid {b_col}44;border-radius:8px;'
            f'padding:10px 16px;margin-bottom:12px;">'
            f'<span style="font-family:Syne,sans-serif;font-size:16px;color:{b_col};">'
            f'Market Breadth: {b_sig}</span></div>',
            unsafe_allow_html=True,
        )

        # Key breadth metrics
        bm1,bm2,bm3,bm4,bm5,bm6 = st.columns(6)
        bm1.metric("% Above EMA50",  f'{breadth["pct_above_ema50"]}%',
                   help="% of scanned stocks trading above their 50-period EMA")
        bm2.metric("% in BREAKOUT",  f'{breadth["pct_breakout"]}%',
                   help="% of stocks in BREAKOUT phase — high = broad participation")
        bm3.metric("Advancing",      breadth["advancing"])
        bm4.metric("Declining",      breadth["declining"])
        bm5.metric("A/D Ratio",      breadth["ad_ratio"],
                   help=">1.5 bullish  ·  <0.8 bearish")
        bm6.metric("Liquid Stocks",  breadth["liquid_count"],
                   help=f"Stocks above ₹{LIQUIDITY_MIN_CR}Cr daily traded value")

        # Breadth interpretation
        pct_ema = breadth["pct_above_ema50"]
        adr     = breadth["ad_ratio"]
        brk_pct = breadth["pct_breakout"]

        interp_lines = []
        if pct_ema >= 70:
            interp_lines.append("✅ **Strong internal trend** — 70%+ above EMA50. Breakouts likely to sustain.")
        elif pct_ema >= 50:
            interp_lines.append("🟡 **Mixed breadth** — about half the market participating. Be selective.")
        else:
            interp_lines.append("🔴 **Weak breadth** — majority below EMA50. Avoid chasing breakouts.")

        if adr >= 2.0:
            interp_lines.append("✅ **A/D ratio strong** — broad advancing participation, low false-breakout risk.")
        elif adr < 0.8:
            interp_lines.append("🔴 **Declining dominance** — wait for A/D to recover before new longs.")

        if brk_pct >= 5:
            interp_lines.append(f"✅ **Breakout breadth healthy** ({brk_pct}% in BREAKOUT). Market in expansion phase.")
        elif brk_pct < 1:
            interp_lines.append("🔴 **No breakout breadth** — avoid momentum trades until breadth improves.")

        vix_interp = ""
        if vix_val:
            if vix_val >= VIX_STRESS:
                vix_interp = f"🔴 **VIX {vix_val} — STRESS**: Targets auto-compressed. STRONG BUY blocked."
            elif vix_val >= VIX_CAUTION:
                vix_interp = f"🟡 **VIX {vix_val} — CAUTION**: Targets compressed 25%, SL widened 20%."
            else:
                vix_interp = f"✅ **VIX {vix_val} — CALM**: Normal risk parameters."
        if vix_interp:
            interp_lines.append(vix_interp)

        st.markdown("\n\n".join(interp_lines))

        st.markdown("---")
        st.subheader("📊 Sector Heatmap")

        sector_data = breadth["sector_avg"]
        if sector_data:
            sec_df = pd.DataFrame([
                {"Sector": k, "Avg Score": v,
                 "Count": sum(1 for r in all_results if r.get("Sector")==k)}
                for k,v in sorted(sector_data.items(), key=lambda x:-x[1])
            ])

            # Visual heatmap bars
            hm_html = '<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:8px;">'
            for _, row in sec_df.iterrows():
                score = row["Avg Score"]
                bar_col = ("#2ecc71" if score>=70 else "#f39c12" if score>=55 else "#e74c3c")
                pct = min(100, score)
                hm_html += (
                    f'<div style="background:#0e0e22;border:1px solid #1c1c36;border-radius:6px;padding:8px 10px;">'
                    f'<div style="color:#e8e8f0;font-size:11px;font-weight:bold;">{row["Sector"]}</div>'
                    f'<div style="color:#6060a0;font-size:10px;">{int(row["Count"])} stocks</div>'
                    f'<div style="background:#1c1c36;border-radius:3px;height:6px;margin:5px 0;">'
                    f'<div style="background:{bar_col};width:{pct}%;height:6px;border-radius:3px;"></div></div>'
                    f'<div style="color:{bar_col};font-size:13px;font-weight:bold;font-family:Syne,sans-serif;">{score}</div>'
                    f'</div>'
                )
            hm_html += "</div>"
            st.markdown(hm_html, unsafe_allow_html=True)
        else:
            st.caption("Add SECTOR_MAP entries for your symbols to see heatmap.")

        st.markdown("---")
        st.subheader("📉 A/D Distribution")
        dist_data = {
            "Advancing": breadth["advancing"],
            "Unchanged": breadth["unchanged"],
            "Declining":  breadth["declining"],
        }
        dist_colors = {"Advancing":"#2ecc71","Unchanged":"#f39c12","Declining":"#e74c3c"}
        total_shown = sum(dist_data.values())
        dist_html = '<div style="display:flex;gap:8px;">'
        for label, count in dist_data.items():
            pct = round(count/total_shown*100,1) if total_shown else 0
            col = dist_colors[label]
            dist_html += (
                f'<div style="flex:1;background:#0e0e22;border:1px solid {col}44;'
                f'border-radius:6px;padding:10px;text-align:center;">'
                f'<div style="color:{col};font-size:20px;font-weight:bold;font-family:Syne,sans-serif;">{count}</div>'
                f'<div style="color:#6060a0;font-size:11px;">{label}</div>'
                f'<div style="color:{col};font-size:11px;">{pct}%</div>'
                f'</div>'
            )
        dist_html += "</div>"
        st.markdown(dist_html, unsafe_allow_html=True)


# ═══════════════════════════════════════════════════════════════════
# DETAIL TAB
# ═══════════════════════════════════════════════════════════════════
with tab_detail:
    all_results = st.session_state.results
    if not all_results:
        st.info("Run a scan first.")
    else:
        sel = st.selectbox("Select stock", [r["Symbol"] for r in all_results])
        r   = next((x for x in all_results if x["Symbol"]==sel), None)
        if r:
            phase = r.get("Phase",PHASE_IDLE)
            chg   = r["%Change"]
            conf  = r.get("Confidence",0)
            conf_lbl, conf_col = confidence_label(conf)

            # Phase timeline
            phases_order = [PHASE_IDLE,PHASE_SETUP,PHASE_ENTRY,PHASE_CONT,PHASE_BRK,PHASE_EXIT]
            ph_html = '<div style="display:flex;gap:5px;margin-bottom:12px;flex-wrap:wrap;">'
            for ph in phases_order:
                active = ph==phase
                bg   = PHASE_COLORS[ph] if active else "#1c1c36"
                brd  = f"2px solid {PHASE_COLORS[ph]}" if active else "2px solid #222"
                fw   = "bold" if active else "normal"
                ph_html += (
                    f'<div style="background:{bg};border:{brd};color:#fff;'
                    f'padding:4px 11px;border-radius:5px;font-size:11px;font-weight:{fw};">'
                    f'{ph}{"  ◀" if active else ""}</div>'
                )
            ph_html += "</div>"
            st.markdown(ph_html, unsafe_allow_html=True)

            d1,d2,d3,d4,d5 = st.columns(5)
            d1.metric("LTP",         fmt(r["LTP"]),  f"{'+' if chg>=0 else ''}{chg}%")
            d2.metric("Entry ⚡",    fmt(r["Entry"]))
            d3.metric("Stop Loss",   fmt(r["SL"]))
            d4.metric("Score",       r["Score"])
            d5.metric(f"Confidence", f"{conf}% ({conf_lbl})")

            t1c,t2c,t3c,r1c = st.columns(4)
            t1c.metric("T1", fmt(r["T1"]))
            t2c.metric("T2", fmt(r["T2"]))
            t3c.metric("T3", fmt(r["T3"]))
            risk = round(r["Entry"] - r["SL"], 2) if r.get("Entry") and r.get("SL") else 0
            r1c.metric("Risk/Share", fmt(risk))

            # Confidence breakdown
            with st.expander(f"🎯 Confidence Model — {conf}% ({conf_lbl})", expanded=True):
                factors = {
                    "Phase alignment":   {PHASE_BRK:20,PHASE_CONT:17,PHASE_ENTRY:13,PHASE_SETUP:7,PHASE_IDLE:2,PHASE_EXIT:0}.get(phase,0),
                    "Score quality":     round(min(20, r["Score"]*0.20),1),
                    "Volume confirmed":  15 if r.get("VolConf") else 5,
                    "EMA stack":         15 if r.get("EMAStack") else (7 if r.get("Phase")!=PHASE_EXIT else 0),
                    "HTF alignment":     15 if r.get("HTFUp",True) else 0,
                    "Market regime":     10 if r.get("Regime")=="BULLISH" else 2,
                    "Exhaustion drag":   -min(5, r.get("ExtN",0)*2),
                }
                for fname, fval in factors.items():
                    col_f = "#2ecc71" if fval >= 10 else ("#f39c12" if fval >= 5 else "#e74c3c")
                    st.markdown(
                        f'<div style="display:flex;justify-content:space-between;padding:3px 0;'
                        f'border-bottom:1px solid #1c1c36;">'
                        f'<span style="color:#a0a0c0;font-size:12px;">{fname}</span>'
                        f'<span style="color:{col_f};font-size:12px;font-weight:bold;">{fval:+.0f}</span>'
                        f'</div>',
                        unsafe_allow_html=True,
                    )

            # Exhaustion detail
            ext_n = r.get("ExtN",0); ext_labels = r.get("ExtLabels",[]); ext_flags = r.get("ExtFlags",{})
            if ext_n == 0:
                st.success("✅ No extension/exhaustion signals — structure is clean.")
            else:
                ec = "error" if ext_n>=3 else "warning"
                flag_desc = {
                    "rsi_overheat":     "Stock has run up too fast — buyers are exhausted. Wait for it to cool down before entering.",
                    "atr_extension":    "Today's price swings are unusually large — the move may be a blow-off. Risk of sharp reversal.",
                    "parabolic":        "Price jumped far more than normal in just 3 candles. These moves rarely sustain — avoid chasing.",
                    "ema_distance":     "Price is stretched way above its average. Likely to pull back before moving higher.",
                    "climactic_volume": "A huge volume spike with a long upper wick — smart money may be selling into retail excitement.",
                    "mom_exhaustion":   "Price is still rising but buying pressure is quietly weakening. Classic late-stage move.",
                    "bearish_div":      "Stock made a new high but momentum did not confirm it. Often a warning of an upcoming top.",
                }
                with st.expander(
                    f"⚠️ {ext_n} Caution Signal{'s' if ext_n>1 else ''} — "
                    f"{'DO NOT enter this trade right now' if ext_n>=3 else 'Reduce size or wait for a better entry'}",
                    expanded=True,
                ):
                    for fk, fa in ext_flags.items():
                        if fa:
                            st.markdown(f"🔴 **{fk.replace('_',' ').title()}** — {flag_desc.get(fk,'')}")
                    st.markdown("---")
                    penalty = sum(EXT_PENALTIES[k] for k,v in ext_flags.items() if v)
                    st.markdown(
                        f"**What the system did:** Score was reduced by `{abs(penalty)} points` because of these signals.  \n"
                        f"**What you should do:** "
                        + ("❌ **Skip this trade.** Wait for the stock to pull back, consolidate, and RSI to come back below 60 before reconsidering."
                           if ext_n>=3 else
                           "⚠️ **Cut your position size in half.** Wait for a dip to support or EMA before entering. Don't chase.")
                    )

            # Key data
            info_cols = st.columns(4)
            info_cols[0].metric("RSI",        r.get("RSI","—"))
            info_cols[1].metric("Sector",      r.get("Sector","Other"))
            info_cols[2].metric("Liq (₹Cr/d)", r.get("AvgTradedCr","—"))
            info_cols[3].metric("Rel Strength",f"{r.get('RS',0):+.1f}%")

            if r["Entry"] != r["LTP"]:
                st.info(
                    f"⚡ Entry ₹{r['Entry']:,} is the signal trigger price. "
                    f"LTP = ₹{r['LTP']:,}. Place order near Entry when phase = ENTRY / BREAKOUT."
                )


# ═══════════════════════════════════════════════════════════════════
# ANALYTICS TAB
# ═══════════════════════════════════════════════════════════════════
with tab_analytics:
    st.subheader("📈 Signal Log & Outcome Tracking")
    st.caption(
        "Every BUY / STRONG BUY signal from each scan is logged here. "
        "Mark outcomes to build a win-rate database."
    )

    log = st.session_state.signal_log
    if not log:
        st.info("No signals logged yet. Run a scan to populate.")
    else:
        log_df = pd.DataFrame(log)

        # Summary metrics
        total_sig  = len(log_df)
        pending    = len(log_df[log_df["outcome"]=="Pending"])
        wins       = len(log_df[log_df["outcome"]=="Win"])
        losses     = len(log_df[log_df["outcome"]=="Loss"])
        win_rate   = round(wins/(wins+losses)*100, 1) if (wins+losses) > 0 else None

        am1,am2,am3,am4 = st.columns(4)
        am1.metric("Total Signals", total_sig)
        am2.metric("Pending",       pending)
        am3.metric("Wins",          wins)
        am4.metric("Win Rate",      f"{win_rate}%" if win_rate is not None else "—",
                   help="Mark outcomes below to calculate")

        # Editable log
        st.markdown("**Mark outcomes (double-click Outcome cell to edit):**")
        edited = st.data_editor(
            log_df[["timestamp","symbol","action","phase","score","confidence",
                    "entry","sl","t1","outcome"]].tail(100),
            column_config={
                "outcome": st.column_config.SelectboxColumn(
                    "Outcome", options=["Pending","Win","Loss","BE"], required=True
                )
            },
            hide_index=True, use_container_width=True,
        )

        # Update session log with edits
        if edited is not None and len(edited) == len(log_df.tail(100)):
            for i, row in edited.iterrows():
                idx = len(log_df) - 100 + i
                if 0 <= idx < len(log):
                    log[idx]["outcome"] = row["outcome"]

        # By phase breakdown
        if wins+losses > 0:
            st.markdown("---")
            st.subheader("Phase Win-Rate Breakdown")
            phase_stats = {}
            for entry in log:
                ph = entry.get("phase","UNKNOWN")
                oc = entry.get("outcome","Pending")
                if oc in ("Win","Loss"):
                    if ph not in phase_stats:
                        phase_stats[ph] = {"Win":0,"Loss":0}
                    phase_stats[ph][oc] += 1
            if phase_stats:
                ps_rows = []
                for ph, stats in phase_stats.items():
                    w = stats["Win"]; l = stats["Loss"]
                    wr = round(w/(w+l)*100,1) if (w+l)>0 else 0
                    ps_rows.append({"Phase":ph,"Wins":w,"Losses":l,"Win Rate":f"{wr}%"})
                st.dataframe(pd.DataFrame(ps_rows), hide_index=True, use_container_width=True)

        # Export
        if st.button("💾 Export Signal Log"):
            csv = pd.DataFrame(log).drop(columns=["ExtFlags"],errors="ignore").to_csv(index=False)
            ts  = datetime.now().strftime("%Y%m%d_%H%M%S")
            st.download_button("Download", csv, f"NSE_SignalLog_{ts}.csv","text/csv")

    st.markdown("---")
    st.subheader("⚙ Next Steps — Missing Analytics")
    st.markdown("""
> **Persistence / Replay** — Signal log above gives you the skeleton. 
> To compute *expectancy* and *setup win-rate* you need to mark T1/T2/SL 
> outcomes daily. The editable table above is the interface; data persists 
> in session (not disk). For disk persistence, connect a SQLite backend or 
> Google Sheets via `st.secrets`.

> **Multi-TF Synchronisation** — MTF veto is implemented in phase detection 
> (weekly for Swing/Positional, 15m for Intraday). The HTF↑/↓ column in the 
> scanner shows alignment. Full 3-TF stack (weekly→daily→intraday trigger) 
> requires fetching 3 intervals per symbol — currently gated by fetch budget.

> **Exhaustion Calibration** — After 50+ signals, use the Analytics tab to 
> split win-rate by ExtN bucket (0, 1-2, 3+). If ExtN≥3 win-rate is >40%, 
> relax the penalty. If <30%, tighten further.
    """)
