"""BULL SUTRA Pro — v11 + EXIT LAYER  (single file app.py)
═══════════════════════════════════════════════════════════════════
All v11 fixes preserved + new Exit/Sell layer fully integrated.

Tabs:  📊 Scan  |  👁 Watchlist  |  🟢 Entry  |  🔴 Exit / Sell

Run:  streamlit run app.py
"""

import warnings
import logging
import time
import threading
import concurrent.futures
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

import numpy as np
import pandas as pd
import yfinance as yf
import streamlit as st

logging.getLogger("yfinance").setLevel(logging.CRITICAL)
warnings.filterwarnings("ignore")

st.set_page_config(
    page_title="BULL SUTRA Pro",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ══════════════════════════════════════════════════════════════════
# UNIVERSES
# ══════════════════════════════════════════════════════════════════

try:
    from nse500 import nse500_symbols
    NSE500 = list(dict.fromkeys([s.strip().upper().replace(".NS","") for s in nse500_symbols]))
except ImportError:
    NSE500 = [
        "RELIANCE","TCS","HDFCBANK","INFY","ICICIBANK","HINDUNILVR","ITC","SBIN",
        "BHARTIARTL","KOTAKBANK","LT","AXISBANK","ASIANPAINT","MARUTI","TITAN",
        "NESTLEIND","WIPRO","ULTRACEMCO","POWERGRID","NTPC","BAJFINANCE","HCLTECH",
        "SUNPHARMA","TECHM","INDUSINDBK","ONGC","COALINDIA","TATASTEEL","JSWSTEEL",
        "HINDALCO","TATAMOTORS","M&M","BAJAJFINSV","DIVISLAB","DRREDDY","CIPLA",
        "EICHERMOT","ADANIENT","ADANIPORTS","BPCL","TATACONSUM","BRITANNIA",
        "HEROMOTOCO","APOLLOHOSP","GRASIM","SBILIFE","HDFCLIFE","ICICIPRULI","VEDL","NMDC",
    ]

NIFTY50 = [
    "RELIANCE","TCS","HDFCBANK","INFY","ICICIBANK","HINDUNILVR","ITC","SBIN",
    "BHARTIARTL","KOTAKBANK","LT","AXISBANK","ASIANPAINT","MARUTI","TITAN",
    "NESTLEIND","WIPRO","ULTRACEMCO","POWERGRID","NTPC","BAJFINANCE","HCLTECH",
    "SUNPHARMA","TECHM","INDUSINDBK","ONGC","COALINDIA","TATASTEEL","JSWSTEEL",
    "HINDALCO","TATAMOTORS","M&M","BAJAJFINSV","DIVISLAB","DRREDDY","CIPLA",
    "EICHERMOT","ADANIENT","ADANIPORTS","BPCL","TATACONSUM","BRITANNIA",
    "HEROMOTOCO","APOLLOHOSP","GRASIM","SBILIFE","HDFCLIFE","ICICIPRULI","BAJAJ-AUTO","UPL",
]

SECTOR_MAP = {
    "RELIANCE":"Energy","ONGC":"Energy","BPCL":"Energy","COALINDIA":"Energy",
    "NTPC":"Utilities","POWERGRID":"Utilities","ADANIENT":"Utilities",
    "ADANIPORTS":"Industrials","LT":"Industrials","BHEL":"Industrials",
    "HDFCBANK":"Financials","ICICIBANK":"Financials","SBIN":"Financials",
    "KOTAKBANK":"Financials","AXISBANK":"Financials","BAJFINANCE":"Financials",
    "BAJAJFINSV":"Financials","SBILIFE":"Financials","HDFCLIFE":"Financials",
    "ICICIPRULI":"Financials","INDUSINDBK":"Financials",
    "TCS":"IT","INFY":"IT","WIPRO":"IT","HCLTECH":"IT","TECHM":"IT",
    "SUNPHARMA":"Healthcare","DRREDDY":"Healthcare","CIPLA":"Healthcare",
    "DIVISLAB":"Healthcare","APOLLOHOSP":"Healthcare",
    "HINDUNILVR":"FMCG","ITC":"FMCG","NESTLEIND":"FMCG","BRITANNIA":"FMCG","TATACONSUM":"FMCG",
    "ASIANPAINT":"Chemicals","ULTRACEMCO":"Materials","GRASIM":"Materials",
    "TATASTEEL":"Metals","JSWSTEEL":"Metals","HINDALCO":"Metals","VEDL":"Metals","NMDC":"Metals",
    "MARUTI":"Auto","TATAMOTORS":"Auto","M&M":"Auto","EICHERMOT":"Auto",
    "HEROMOTOCO":"Auto","BAJAJ-AUTO":"Auto",
    "TITAN":"Consumer","BHARTIARTL":"Telecom",
}

MODE_CFG = {
    "Intraday":   dict(period="5d",  interval="5m",  ema_fast=9,  ema_slow=21,
                       atr_mult=1.5, atr_wide=3.0, atr_max=1.0,
                       mom1_th=2,  mom3_th=5,  mom6_th=8,  score_th=65, rsi_len=14,
                       htf_period="3mo", htf_interval="15m", validity_hours=4),
    "Swing":      dict(period="1y",  interval="1d",  ema_fast=50, ema_slow=200,
                       atr_mult=2.5, atr_wide=4.0, atr_max=1.5,
                       mom1_th=3,  mom3_th=7,  mom6_th=10, score_th=70, rsi_len=21,
                       htf_period="2y", htf_interval="1wk", validity_hours=72),
    "Positional": dict(period="2y",  interval="1d",  ema_fast=50, ema_slow=200,
                       atr_mult=3.5, atr_wide=5.0, atr_max=1.5,
                       mom1_th=5,  mom3_th=10, mom6_th=15, score_th=70, rsi_len=21,
                       htf_period="5y", htf_interval="1wk", validity_hours=240),
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

PHASE_ORDER = {
    PHASE_IDLE:0, PHASE_SETUP:1, PHASE_ENTRY:2,
    PHASE_CONT:3, PHASE_BRK:4, PHASE_EXIT:-1,
}

VIX_CALM    = 15
VIX_CAUTION = 20
VIX_STRESS  = 25
LIQUIDITY_MIN_CR = 5.0

NSE_OPEN_HOUR,  NSE_OPEN_MIN  = 9,  15
NSE_CLOSE_HOUR, NSE_CLOSE_MIN = 15, 30
NSE_SESSION_MINUTES = (NSE_CLOSE_HOUR*60 + NSE_CLOSE_MIN) - (NSE_OPEN_HOUR*60 + NSE_OPEN_MIN)

# Exit phase constants
EXIT_HOLD      = "HOLD"
EXIT_WATCH     = "EXIT WATCH"
EXIT_SIGNAL    = "EXIT SIGNAL"
EXIT_CONFIRMED = "EXIT NOW"

EXIT_COLORS = {
    EXIT_HOLD:      "#22aa55",
    EXIT_WATCH:     "#e8a838",
    EXIT_SIGNAL:    "#ff8800",
    EXIT_CONFIRMED: "#cc2222",
}

EXIT_SCORE_WATCH     = 20
EXIT_SCORE_SIGNAL    = 40
EXIT_SCORE_CONFIRMED = 65
HARD_WEIGHT = 25
SOFT_WEIGHT = 10

_phase_lock = threading.Lock()


# ══════════════════════════════════════════════════════════════════
# MATH HELPERS
# ══════════════════════════════════════════════════════════════════

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
    tr = pd.concat([
        (hi - lo),
        (hi - cl.shift()).abs(),
        (lo - cl.shift()).abs(),
    ], axis=1).max(axis=1)
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


# ══════════════════════════════════════════════════════════════════
# FIX-4: INTRADAY TIME-NORMALISED VOLUME
# ══════════════════════════════════════════════════════════════════

def _session_elapsed_fraction() -> float:
    now_utc  = datetime.utcnow()
    now_ist  = now_utc + timedelta(hours=5, minutes=30)
    minutes_since_open = (now_ist.hour*60 + now_ist.minute) - (NSE_OPEN_HOUR*60 + NSE_OPEN_MIN)
    return float(np.clip(minutes_since_open / NSE_SESSION_MINUTES, 0.05, 1.0))

def _intraday_vol_avg(volume: pd.Series, bars_per_day: int) -> float:
    elapsed_frac = _session_elapsed_fraction()
    today_bars   = int(min(bars_per_day * elapsed_frac + 1, len(volume)))
    today_vol    = float(volume.iloc[-today_bars:].sum())
    today_proj   = today_vol / elapsed_frac
    if len(volume) > bars_per_day + today_bars:
        prior       = volume.iloc[:-(today_bars)].rolling(bars_per_day).sum().dropna()
        prior_daily = prior.iloc[-5:].values.tolist()
    else:
        prior_daily = []
    all_days = prior_daily + [today_proj]
    return float(np.mean(all_days)) if all_days else float(volume.mean() * bars_per_day)


# ══════════════════════════════════════════════════════════════════
# SIGNAL VALIDITY
# ══════════════════════════════════════════════════════════════════

def signal_is_stale(logged_at_iso: str, mode: str) -> bool:
    try:
        validity_h = MODE_CFG[mode].get("validity_hours", 72)
        logged_at  = datetime.fromisoformat(logged_at_iso)
        return (datetime.now() - logged_at) > timedelta(hours=validity_h)
    except Exception:
        return False

def signal_age_label(logged_at_iso: str, mode: str):
    try:
        validity_h = MODE_CFG[mode].get("validity_hours", 72)
        logged_at  = datetime.fromisoformat(logged_at_iso)
        delta      = datetime.now() - logged_at
        hours      = delta.total_seconds() / 3600
        stale      = hours > validity_h
        if hours < 1:
            age_str = f"{int(delta.total_seconds()/60)}m ago"
        elif hours < 24:
            age_str = f"{hours:.1f}h ago"
        else:
            age_str = f"{hours/24:.1f}d ago"
        return age_str, stale
    except Exception:
        return "unknown", False


# ══════════════════════════════════════════════════════════════════
# VIX
# ══════════════════════════════════════════════════════════════════

@st.cache_data(ttl=300)
def fetch_vix():
    try:
        df = yf.download("^INDIAVIX", period="5d", interval="1d",
                         auto_adjust=True, progress=False, threads=False)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df = df.dropna()
        if df.empty:
            return None, "UNKNOWN"
        v     = float(df["Close"].iloc[-1])
        label = "CALM" if v < VIX_CALM else ("CAUTION" if v < VIX_STRESS else "STRESS")
        return round(v, 2), label
    except Exception:
        return None, "UNKNOWN"

def vix_target_mult(vix_val):
    if vix_val is None or vix_val < VIX_CAUTION:
        return 1.0, 2.0, 3.0, 1.0
    if vix_val < VIX_STRESS:
        return 0.75, 1.4, 2.0, 1.2
    return 0.6, 1.1, 1.6, 1.35


# ══════════════════════════════════════════════════════════════════
# LIQUIDITY FILTER
# ══════════════════════════════════════════════════════════════════

def liquidity_ok(df, min_cr=LIQUIDITY_MIN_CR, mode="Swing"):
    try:
        traded  = df["Close"] * df["Volume"]
        n_rows  = len(df)
        if n_rows >= 2:
            idx = df.index
            try:
                delta_min = (idx[1] - idx[0]).total_seconds() / 60
            except Exception:
                delta_min = 1440
        else:
            delta_min = 1440

        if delta_min <= 5:    bars_per_day = 75
        elif delta_min <= 15: bars_per_day = 25
        elif delta_min <= 30: bars_per_day = 13
        elif delta_min < 240: bars_per_day = 7
        else:                 bars_per_day = 1

        if mode == "Intraday" and bars_per_day > 1:
            avg_daily_vol = _intraday_vol_avg(df["Volume"], bars_per_day)
            avg_cr        = float(avg_daily_vol * float(df["Close"].iloc[-1])) / 1e7
        else:
            daily_traded = traded.rolling(bars_per_day).sum()
            avg_cr       = float(daily_traded.rolling(20).mean().iloc[-1]) / 1e7

        return avg_cr >= min_cr, round(avg_cr, 1)
    except Exception:
        return True, 0.0


# ══════════════════════════════════════════════════════════════════
# HTF — FIX-1: CLOSED-CANDLE ONLY
# ══════════════════════════════════════════════════════════════════

@st.cache_data(ttl=900)
def _fetch_htf_cached(ticker: str, period: str, interval: str) -> pd.DataFrame:
    for attempt in range(3):
        try:
            df = yf.download(ticker, period=period, interval=interval,
                             auto_adjust=True, progress=False, threads=False)
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            return df.dropna()
        except Exception:
            time.sleep(min(0.5*(attempt+1), 1.0))
    return pd.DataFrame()

def _htf_trend_from_df(df: pd.DataFrame, mode: str):
    if df is None or df.empty:
        return True, "HTF-UNKNOWN"
    if mode == "Intraday" and len(df) > 2:
        df = df.iloc[:-1].copy()
    min_bars = 55 if mode == "Intraday" else 26
    if len(df) < min_bars:
        return True, "HTF-UNKNOWN"
    cl = df["Close"]
    ef = float(ema(cl, 21 if mode == "Intraday" else 13).iloc[-1])
    es = float(ema(cl, 55 if mode == "Intraday" else 26).iloc[-1])
    c  = float(cl.iloc[-1])
    up = c > ef > es
    return up, ("HTF↑" if up else "HTF↓")

def prefetch_htf_parallel(symbols: list, mode: str, status_text, progress_bar) -> dict:
    cfg     = MODE_CFG[mode]
    results = {}
    total   = len(symbols)

    def _fetch_one_htf(sym):
        ticker = to_nse(sym)
        df     = _fetch_htf_cached(ticker, cfg["htf_period"], cfg["htf_interval"])
        return sym, _htf_trend_from_df(df, mode)

    completed = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(32, total)) as pool:
        futures = {pool.submit(_fetch_one_htf, sym): sym for sym in symbols}
        for fut in concurrent.futures.as_completed(futures):
            sym, result = fut.result()
            results[sym] = result
            completed   += 1
            # Update progress from the main thread (safe for Streamlit)
            progress_bar.progress(0.15 + completed / max(total, 1) * 0.25)
            if completed % 20 == 0:
                status_text.text(f"HTF pre-fetch {completed}/{total}…")
    return results


# ══════════════════════════════════════════════════════════════════
# RELATIVE STRENGTH — PERF-4: VECTORIZED
# ══════════════════════════════════════════════════════════════════

def compute_rs_ranks(sym_returns: dict) -> dict:
    if not sym_returns:
        return {}
    syms  = list(sym_returns.keys())
    vals  = np.array([sym_returns[s] for s in syms], dtype=np.float64)
    order = np.argsort(vals)
    ranks = np.empty_like(order)
    ranks[order] = np.arange(len(vals))
    normalized   = np.round(ranks / max(len(vals)-1, 1) * 100).astype(int)
    return dict(zip(syms, normalized.tolist()))

def _52w_return(close_series: pd.Series) -> float:
    if len(close_series) < 10:
        return 0.0
    lookback = min(252, len(close_series)-1)
    c_now    = float(close_series.iloc[-1])
    c_base   = float(close_series.iloc[-lookback])
    if c_base == 0:
        return 0.0
    return round((c_now - c_base) / c_base * 100, 2)


# ══════════════════════════════════════════════════════════════════
# PHASE TRANSITION MEMORY — PERF-7: THREAD-SAFE
# ══════════════════════════════════════════════════════════════════

def record_phase_transition(sym: str, new_phase: str, phase_history: dict = None):
    """Update phase history dict in-place. Thread-safe when called with an explicit dict."""
    if phase_history is None:
        # Only access session_state from the main thread (UI context)
        try:
            if "phase_history" not in st.session_state:
                st.session_state["phase_history"] = {}
            phase_history = st.session_state["phase_history"]
        except Exception:
            phase_history = {}
    if sym not in phase_history:
        phase_history[sym] = []
    prev_phase = phase_history[sym][-1][1] if phase_history[sym] else None
    changed    = prev_phase != new_phase
    is_prog = is_regr = False
    arrow   = ""
    if changed:
        ts = datetime.now().isoformat()
        phase_history[sym].append((ts, new_phase))
        phase_history[sym] = phase_history[sym][-10:]
        if prev_phase is not None:
            prev_ord = PHASE_ORDER.get(prev_phase, 0)
            new_ord  = PHASE_ORDER.get(new_phase, 0)
            if new_phase == PHASE_EXIT:
                arrow = "→EXIT"; is_regr = True
            elif new_ord > prev_ord:
                arrow = f"↗{new_phase}"; is_prog = True
            elif new_ord < prev_ord and new_phase != PHASE_EXIT:
                arrow = f"↘{new_phase}"; is_regr = True
    return changed, arrow, is_prog, is_regr

def phase_transition_conf_bonus(sym: str, phase_history: dict = None) -> int:
    if phase_history is None:
        try:
            phase_history = st.session_state.get("phase_history", {})
        except Exception:
            phase_history = {}
    history = phase_history
    if sym not in history or len(history[sym]) < 3:
        return 0
    last3 = [h[1] for h in history[sym][-3:]]
    progressions = [
        [PHASE_SETUP, PHASE_ENTRY, PHASE_CONT],
        [PHASE_ENTRY, PHASE_CONT, PHASE_BRK],
        [PHASE_SETUP, PHASE_ENTRY, PHASE_BRK],
    ]
    return 5 if last3 in progressions else 0

def get_phase_arrow(sym: str) -> str:
    history = st.session_state.get("phase_history", {})
    if sym not in history or len(history[sym]) < 2:
        return ""
    last2 = [h[1] for h in history[sym][-2:]]
    prev_ord = PHASE_ORDER.get(last2[0], 0)
    new_ord  = PHASE_ORDER.get(last2[1], 0)
    if last2[1] == PHASE_EXIT:
        return "→EXIT"
    if new_ord > prev_ord:
        return f"↗{last2[1]}"
    if new_ord < prev_ord:
        return f"↘{last2[1]}"
    return ""


# ══════════════════════════════════════════════════════════════════
# POSITION SIZING — FIX-5: CAPITAL CAP
# ══════════════════════════════════════════════════════════════════

def position_size(account_size: float, risk_pct: float, entry: float,
                  stop: float, max_capital_pct: float = 0.20) -> dict:
    risk_amount = account_size * (risk_pct / 100)
    stop_dist   = abs(entry - stop)
    if stop_dist == 0:
        return dict(qty=0, capital=0, risk_amount=risk_amount)
    raw_qty     = int(risk_amount / stop_dist)
    max_qty     = int(account_size * max_capital_pct / entry)
    final_qty   = min(raw_qty, max_qty)
    return dict(qty=final_qty, capital=round(final_qty*entry,2), risk_amount=round(risk_amount,2))


# ══════════════════════════════════════════════════════════════════
# PHASE DETECTION — FIX-3: STRUCTURAL BREAKOUT FILTERING
# ══════════════════════════════════════════════════════════════════

def detect_phase_and_entry(df, atr_val, atr_mean, vol_avg, cfg):
    if len(df) < 30:
        return PHASE_IDLE, None, None, None
    cl   = df["Close"]
    hi   = df["High"]
    lo   = df["Low"]
    e_f  = ema(cl, cfg["ema_fast"])
    e_s  = ema(cl, cfg["ema_slow"])
    price     = float(cl.iloc[-1])
    fast_now  = float(e_f.iloc[-1])
    slow_now  = float(e_s.iloc[-1])
    roll_hi   = float(hi.rolling(20).max().iloc[-1])
    roll_lo   = float(lo.rolling(20).min().iloc[-1])
    vol_now   = float(df["Volume"].iloc[-1])

    entry = stop = target = None

    # BREAKOUT
    is_breakout = (
        price > roll_hi * 1.001 and
        price > roll_hi + 0.15 * atr_val and
        vol_now > vol_avg * 1.5 and
        atr_val <= atr_mean * 1.4
    )
    if is_breakout:
        entry  = price
        stop   = price - cfg["atr_mult"] * atr_val
        target = price + 2.0 * cfg["atr_mult"] * atr_val
        return PHASE_BRK, entry, stop, target

    trend_up = fast_now > slow_now and price > fast_now

    if trend_up:
        near_ema   = abs(price - fast_now) < atr_val * 0.5
        prior_base = hi.iloc[-20:-5].max() if len(hi) >= 20 else hi.max()
        tightening = atr_val < atr_mean * 0.85
        if near_ema or tightening:
            phase  = PHASE_ENTRY if near_ema else PHASE_SETUP
            entry  = price
            stop   = float(lo.rolling(10).min().iloc[-1])
            target = price + cfg["atr_mult"] * atr_val * 2
            return phase, entry, stop, target
        return PHASE_CONT, None, None, None

    if fast_now > slow_now * 0.98:
        return PHASE_SETUP, None, None, None

    return PHASE_IDLE, None, None, None


# ══════════════════════════════════════════════════════════════════
# BULL SCORER — FIX-6: EMA DOUBLE-COUNT REMOVED
# ══════════════════════════════════════════════════════════════════

def score_stock(df, sym, mode, vix_val, htf_up, rs_rank, phase_history_sym=None, phase_history_dict=None):
    cfg     = MODE_CFG[mode]
    cl      = df["Close"]
    hi      = df["High"]
    lo      = df["Low"]
    vol     = df["Volume"]
    price   = float(cl.iloc[-1])

    e_fast  = ema(cl, cfg["ema_fast"])
    e_slow  = ema(cl, cfg["ema_slow"])
    ef      = float(e_fast.iloc[-1])
    es      = float(e_slow.iloc[-1])
    rsi_s   = rsi(cl, cfg["rsi_len"])
    rsi_val = float(rsi_s.iloc[-1]) if len(rsi_s) > 0 else 50
    atr_s   = atr_series(df)
    atr_val = float(atr_s.iloc[-1])
    atr_mean= float(atr_s.rolling(20).mean().iloc[-1])

    n_rows  = len(df)
    if n_rows >= 2:
        try:
            delta_min = (df.index[1] - df.index[0]).total_seconds() / 60
        except Exception:
            delta_min = 1440
    else:
        delta_min = 1440

    if delta_min <= 5:    bars_per_day = 75
    elif delta_min <= 15: bars_per_day = 25
    elif delta_min <= 30: bars_per_day = 13
    elif delta_min < 240: bars_per_day = 7
    else:                 bars_per_day = 1

    if mode == "Intraday" and bars_per_day > 1:
        vol_avg = _intraday_vol_avg(vol, bars_per_day)
    else:
        vol_avg = float(vol.rolling(max(bars_per_day, 20)).mean().iloc[-1])

    bull = 0

    # Trend
    trend_up     = ef > es and price > ef
    trend_strong = ef > es * 1.02 and price > ef * 1.01
    if trend_strong: bull += 25
    elif trend_up:   bull += 15

    # EMA stack (FIX-6: non-overlapping bonus)
    ema_stack = ef > es
    if ema_stack:
        bull += 15
        # Fresh golden cross bonus
        cross_bars = min(5, len(e_fast)-1)
        fresh_cross = any(
            float(e_fast.iloc[-(i+1)]) > float(e_slow.iloc[-(i+1)]) and
            float(e_fast.iloc[-(i+2)]) <= float(e_slow.iloc[-(i+2)])
            for i in range(cross_bars) if len(e_fast) > i+2
        )
        bull += 8 if fresh_cross else 4

    # RSI
    if 55 <= rsi_val <= 75:   bull += 15
    elif 45 <= rsi_val < 55:  bull += 8
    elif rsi_val > 75:        bull += 5

    # Momentum
    if len(cl) >= 2:
        mom1 = (float(cl.iloc[-1]) - float(cl.iloc[-2])) / float(cl.iloc[-2]) * 100
        if mom1 > cfg["mom1_th"]: bull += 10
        elif mom1 > 0:            bull += 4
    if len(cl) >= 4:
        mom3 = (float(cl.iloc[-1]) - float(cl.iloc[-4])) / float(cl.iloc[-4]) * 100
        if mom3 > cfg["mom3_th"]: bull += 8
        elif mom3 > 0:            bull += 3
    if len(cl) >= 7:
        mom6 = (float(cl.iloc[-1]) - float(cl.iloc[-7])) / float(cl.iloc[-7]) * 100
        if mom6 > cfg["mom6_th"]: bull += 7
        elif mom6 > 0:            bull += 2

    # Volume
    if vol_avg > 0:
        vol_ratio = float(vol.iloc[-1]) / vol_avg
        if vol_ratio > 2.0:   bull += 12
        elif vol_ratio > 1.5: bull += 8
        elif vol_ratio > 1.0: bull += 4

    # HTF alignment
    if htf_up: bull += 10

    # RS rank
    if rs_rank >= 80:   bull += 10
    elif rs_rank >= 60: bull += 6
    elif rs_rank >= 40: bull += 2

    # Phase transition confidence
    bull += phase_transition_conf_bonus(sym, phase_history=phase_history_dict)

    # ATR vs wide-stop gate
    if atr_val > cfg.get("atr_max", 1.5) * atr_mean:
        bull = int(bull * 0.8)

    norm_score = round(min(bull / BULL_MAX * 100, 100), 1)

    phase, entry, stop, target = detect_phase_and_entry(df, atr_val, atr_mean, vol_avg, cfg)
    _, _, _, _ = record_phase_transition(sym, phase, phase_history=phase_history_dict)

    return dict(
        sym=sym, price=price, score=norm_score,
        action=action_label(norm_score),
        phase=phase, entry=entry, stop=stop, target=target,
        rsi=round(rsi_val, 1), atr_val=round(atr_val, 2),
        ef=round(ef, 2), es=round(es, 2),
        htf_up=htf_up, rs_rank=rs_rank,
        sector=SECTOR_MAP.get(sym, "Other"),
        scanned_at=datetime.now().isoformat(),
    )


# ══════════════════════════════════════════════════════════════════
# DATA FETCH
# ══════════════════════════════════════════════════════════════════

def fetch_stock_data(sym: str, mode: str) -> pd.DataFrame:
    cfg    = MODE_CFG[mode]
    ticker = to_nse(sym)
    for attempt in range(3):
        try:
            df = yf.download(ticker, period=cfg["period"], interval=cfg["interval"],
                             auto_adjust=True, progress=False, threads=False)
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            df = df.dropna()
            if len(df) >= 30:
                return df
        except Exception:
            time.sleep(min(0.5*(attempt+1), 1.0))
    return pd.DataFrame()


# ══════════════════════════════════════════════════════════════════
# MAIN SCAN — FIX-2: BREADTH GATING + PERF-1 PARALLEL
# ══════════════════════════════════════════════════════════════════

def run_scan(symbols: list, mode: str, vix_val, htf_cache: dict,
             status_text, progress_bar) -> list:
    results = []
    sym_returns = {}
    lock = threading.Lock()
    total = len(symbols)
    completed = [0]

    # Snapshot session state BEFORE spawning threads — workers must NOT access st.session_state
    try:
        phase_history_snapshot = dict(st.session_state.get("phase_history", {}))
    except Exception:
        phase_history_snapshot = {}
    # Shared mutable dict updated from threads (protected by lock)
    phase_history_updates = {}

    def _process_one(sym):
        df = fetch_stock_data(sym, mode)
        if df is None or df.empty:
            return None
        ok, _ = liquidity_ok(df, mode=mode)
        if not ok:
            return None
        htf_up, _ = htf_cache.get(sym, (True, "HTF-UNKNOWN"))
        r52 = _52w_return(df["Close"])
        with lock:
            sym_returns[sym] = r52
        ph = phase_history_snapshot.get(sym, [])
        rs_rank = 50
        # Pass the phase_history snapshot/updates dict; record_phase_transition writes into it
        result = score_stock(df, sym, mode, vix_val, htf_up, rs_rank, ph,
                             phase_history_dict=phase_history_updates)
        with lock:
            completed[0] += 1
        return result

    with concurrent.futures.ThreadPoolExecutor(max_workers=32) as pool:
        futures = {pool.submit(_process_one, sym): sym for sym in symbols}
        for fut in concurrent.futures.as_completed(futures):
            r = fut.result()
            if r:
                results.append(r)
            # Update progress from the main thread (safe for Streamlit)
            done = len(results)
            prog = 0.40 + done / max(total, 1) * 0.55
            progress_bar.progress(min(prog, 0.95))
            if done % 20 == 0:
                status_text.text(f"Scoring {done}/{total}…")

    # Merge phase history updates back into session state (main thread, safe)
    try:
        if "phase_history" not in st.session_state:
            st.session_state["phase_history"] = {}
        for sym, entries in phase_history_updates.items():
            st.session_state["phase_history"][sym] = entries
    except Exception:
        pass

    # Apply RS ranks (vectorized)
    rs_ranks = compute_rs_ranks(sym_returns)
    for r in results:
        r["rs_rank"] = rs_ranks.get(r["sym"], 50)

    # FIX-2: breadth gate
    n_total = len(results)
    if n_total > 0:
        n_above = sum(1 for r in results if r["ef"] > r["es"])
        pct_above = n_above / n_total * 100
        ad_ratio  = n_above / max(n_total - n_above, 1)
        breadth_weak = pct_above < 40 and ad_ratio < 0.8
        if breadth_weak:
            for r in results:
                if r["phase"] in (PHASE_BRK, PHASE_CONT) and r["action"] != "SKIP":
                    r["action"] = "WATCH"
                    r["breadth_gated"] = True

    results.sort(key=lambda r: r["score"], reverse=True)
    return results


# ══════════════════════════════════════════════════════════════════
# EXIT LAYER — TRAILING STOP
# ══════════════════════════════════════════════════════════════════

def compute_trailing_stop(df, entry_price, mode, vix_val):
    cfg       = MODE_CFG[mode]
    base_mult = cfg.get("atr_mult", 2.5)
    atr_val   = float(atr_series(df).iloc[-1])
    vix_adj   = 1.0
    if vix_val is not None:
        if vix_val >= VIX_STRESS:   vix_adj = 1.35
        elif vix_val >= VIX_CAUTION: vix_adj = 1.20
    price          = float(df["Close"].iloc[-1])
    pnl_pct        = (price - entry_price) / entry_price * 100 if entry_price else 0
    profit_tighten = max(0.0, pnl_pct / 5.0) * 0.10
    adj_mult       = max(base_mult * 0.50, (base_mult * vix_adj) - profit_tighten)
    swing_low      = float(df["Low"].rolling(20).min().iloc[-1])
    return round(max(swing_low, price - adj_mult * atr_val), 2)


# ══════════════════════════════════════════════════════════════════
# EXIT LAYER — SIGNAL SCORER
# ══════════════════════════════════════════════════════════════════

@dataclass
class ExitResult:
    sym: str
    exit_phase: str       = EXIT_HOLD
    exit_score: float     = 0.0
    hard_triggers: list   = field(default_factory=list)
    soft_triggers: list   = field(default_factory=list)
    price: float          = 0.0
    entry_price: float    = 0.0
    pnl_pct: float        = 0.0
    trailing_stop: float  = 0.0
    partial_exit_pct: int = 0
    urgency_note: str     = ""
    rs_rank: int          = 50
    htf_up: bool          = True
    scanned_at: str       = ""
    error: Optional[str]  = None


def score_exit(df, sym, entry_price, mode, vix_val, htf_up, rs_rank, phase_history=None):
    result = ExitResult(sym=sym, entry_price=entry_price, rs_rank=rs_rank,
                        htf_up=htf_up, scanned_at=datetime.now().isoformat())

    if df is None or len(df) < 30:
        result.error = "Insufficient data"
        return result

    cfg        = MODE_CFG[mode]
    cl         = df["Close"]
    hi         = df["High"]
    lo         = df["Low"]
    vol        = df["Volume"]
    price      = float(cl.iloc[-1])
    atr_val    = float(atr_series(df).iloc[-1])
    atr_mean   = float(atr_series(df).rolling(20).mean().iloc[-1])
    e_fast     = ema(cl, cfg["ema_fast"])
    e_slow     = ema(cl, cfg["ema_slow"])
    rsi_s      = rsi(cl, cfg["rsi_len"])

    result.price        = round(price, 2)
    result.pnl_pct      = round((price - entry_price) / entry_price * 100, 2) if entry_price else 0
    result.trailing_stop= compute_trailing_stop(df, entry_price, mode, vix_val)

    hard_triggers = []
    soft_triggers = []
    exit_score    = 0.0

    # H1: Trailing stop breach
    if price < result.trailing_stop:
        hard_triggers.append("H1:TrailStop"); exit_score += HARD_WEIGHT

    # H2: EMA crossdown (last 3 bars)
    cross_bars = min(3, len(e_fast)-1)
    ema_cross_down = any(
        float(e_fast.iloc[-(i+1)]) < float(e_slow.iloc[-(i+1)]) and
        float(e_fast.iloc[-(i+2)]) >= float(e_slow.iloc[-(i+2)])
        for i in range(cross_bars) if len(e_fast) > i+2
    )
    if ema_cross_down:
        hard_triggers.append("H2:EMAxDown"); exit_score += HARD_WEIGHT

    # H3: HTF flip
    if not htf_up:
        hard_triggers.append("H3:HTFBearish"); exit_score += HARD_WEIGHT

    # H4: Volume climax (3× avg, red candle)
    if len(vol) >= 20:
        vol_avg  = float(vol.rolling(20).mean().iloc[-1])
        last_red = float(cl.iloc[-1]) < float(cl.iloc[-2])
        if last_red and float(vol.iloc[-1]) > vol_avg * 3.0:
            hard_triggers.append("H4:VolClimax"); exit_score += HARD_WEIGHT

    # S1: RSI overbought reversal
    if len(rsi_s) >= 4:
        rsi_now  = float(rsi_s.iloc[-1])
        rsi_peak = float(rsi_s.iloc[-4:-1].max())
        if rsi_peak > 70 and rsi_now < rsi_peak - 5:
            soft_triggers.append("S1:RSIrev"); exit_score += SOFT_WEIGHT

    # S2: Bearish engulfing
    if len(df) >= 3 and "Open" in df.columns:
        o          = df["Open"]
        prev_bull  = float(cl.iloc[-2]) > float(o.iloc[-2])
        prev_body  = abs(float(cl.iloc[-2]) - float(o.iloc[-2]))
        curr_bear  = float(cl.iloc[-1]) < float(o.iloc[-1])
        curr_body  = abs(float(cl.iloc[-1]) - float(o.iloc[-1]))
        if prev_bull and curr_bear and curr_body > prev_body * 1.2:
            soft_triggers.append("S2:BearEngulf"); exit_score += SOFT_WEIGHT

    # S3: Fib extension target
    _, _, fibs, _ = fib_levels(df, lookback=min(60, len(df)))
    for key in ("ext127", "ext161"):
        fib_val = fibs.get(key)
        if fib_val and abs(price - fib_val) / fib_val < 0.003:
            soft_triggers.append(f"S3:Fib{key}"); exit_score += SOFT_WEIGHT; break

    # S4: Phase regression
    if phase_history and len(phase_history) >= 2:
        last_two = [h[1] for h in phase_history[-2:]]
        ord_a    = PHASE_ORDER.get(last_two[0], 0)
        ord_b    = PHASE_ORDER.get(last_two[1], 0)
        if ord_b < ord_a and last_two[1] not in (PHASE_EXIT, PHASE_IDLE):
            soft_triggers.append("S4:PhaseRegr"); exit_score += SOFT_WEIGHT

    # S5: Momentum decay
    if len(cl) >= 4:
        mom1 = float(cl.iloc[-1]) - float(cl.iloc[-2])
        mom3 = float(cl.iloc[-1]) - float(cl.iloc[-4])
        if mom1 < 0 < mom3:
            soft_triggers.append("S5:MomDecay"); exit_score += SOFT_WEIGHT

    # S6: RS rank declining
    if rs_rank < 40:
        soft_triggers.append(f"S6:RS{rs_rank}"); exit_score += SOFT_WEIGHT

    # S7: Gap-up exhaustion
    if len(df) >= 2 and "Open" in df.columns:
        prior_close = float(cl.iloc[-2])
        open_today  = float(df["Open"].iloc[-1])
        close_today = float(cl.iloc[-1])
        if open_today > prior_close * 1.015 and close_today < open_today:
            soft_triggers.append("S7:GapExhaust"); exit_score += SOFT_WEIGHT

    # VIX stress amplifier
    if vix_val is not None and vix_val >= VIX_STRESS and exit_score > 0:
        exit_score = min(100, exit_score * 1.2)

    score  = round(min(exit_score, 100), 1)
    n_hard = len(hard_triggers)
    n_soft = len(soft_triggers)

    if n_hard >= 2 or score >= EXIT_SCORE_CONFIRMED:
        phase = EXIT_CONFIRMED
    elif n_hard >= 1 or score >= EXIT_SCORE_SIGNAL:
        phase = EXIT_SIGNAL
    elif n_soft >= 1 or score >= EXIT_SCORE_WATCH:
        phase = EXIT_WATCH
    else:
        phase = EXIT_HOLD

    partial_pct = 0
    if result.pnl_pct > 0:
        if phase == EXIT_SIGNAL:    partial_pct = 50
        elif phase == EXIT_WATCH and result.pnl_pct > 5: partial_pct = 25

    notes = []
    if phase == EXIT_CONFIRMED: notes.append("EXIT IMMEDIATELY — multiple hard triggers fired.")
    elif phase == EXIT_SIGNAL:  notes.append("Prepare to exit. Consider partial sell.")
    elif phase == EXIT_WATCH:   notes.append("Monitor closely. Tighten mental stop.")
    else:                       notes.append("Position healthy — hold.")
    if result.pnl_pct > 0:     notes.append(f"Open P&L: +{result.pnl_pct:.1f}%.")
    elif result.pnl_pct < 0:   notes.append(f"Open P&L: {result.pnl_pct:.1f}% — review stop.")
    if not htf_up:              notes.append("HTF bearish — reduce exposure.")

    result.exit_phase      = phase
    result.exit_score      = score
    result.hard_triggers   = hard_triggers
    result.soft_triggers   = soft_triggers
    result.partial_exit_pct= partial_pct
    result.urgency_note    = " ".join(notes)
    return result


def run_exit_scan(positions: list, mode: str, vix_val, htf_cache: dict) -> list:
    results = []
    lock    = threading.Lock()
    # Snapshot phase history BEFORE spawning threads
    try:
        phase_history_all = dict(st.session_state.get("phase_history", {}))
    except Exception:
        phase_history_all = {}

    def _one(pos):
        sym         = pos.get("sym", "")
        entry_price = float(pos.get("entry_price", 0))
        rs_rank     = int(pos.get("rs_rank", 50))
        ph          = phase_history_all.get(sym, [])
        df          = fetch_stock_data(sym, mode)
        if df is None or df.empty:
            return ExitResult(sym=sym, error="Fetch failed", entry_price=entry_price,
                              scanned_at=datetime.now().isoformat())
        htf_up, _ = htf_cache.get(sym, (True, "HTF-UNKNOWN"))
        return score_exit(df, sym, entry_price, mode, vix_val, htf_up, rs_rank, ph)

    with concurrent.futures.ThreadPoolExecutor(max_workers=min(32, max(1, len(positions)))) as pool:
        futures = {pool.submit(_one, pos): pos for pos in positions}
        for fut in concurrent.futures.as_completed(futures):
            try:
                with lock:
                    results.append(fut.result())
            except Exception as e:
                pos = futures[fut]
                results.append(ExitResult(sym=pos.get("sym","?"), error=str(e),
                                          scanned_at=datetime.now().isoformat()))

    results.sort(key=lambda r: r.exit_score, reverse=True)
    return results


# ══════════════════════════════════════════════════════════════════
# POSITION MANAGER (session state)
# ══════════════════════════════════════════════════════════════════

def add_position(sym, entry_price, qty=1, rs_rank=50):
    if "open_positions" not in st.session_state:
        st.session_state["open_positions"] = []
    existing = [p["sym"] for p in st.session_state["open_positions"]]
    if sym not in existing:
        st.session_state["open_positions"].append({
            "sym": sym, "entry_price": entry_price,
            "qty": qty, "rs_rank": rs_rank,
            "entry_date": datetime.now().isoformat(),
        })

def remove_position(sym):
    if "open_positions" in st.session_state:
        st.session_state["open_positions"] = [
            p for p in st.session_state["open_positions"] if p["sym"] != sym
        ]


# ══════════════════════════════════════════════════════════════════
# CSS
# ══════════════════════════════════════════════════════════════════

def inject_css():
    st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600;700&family=Syne:wght@400;600;700;800&display=swap');

    html, body, [class*="css"] { font-family: 'Syne', sans-serif; }
    code, .mono { font-family: 'JetBrains Mono', monospace; }

    .stApp { background: #0d0f14; }

    /* Header */
    .bs-header {
        background: linear-gradient(135deg, #0d0f14 0%, #131824 100%);
        border-bottom: 1px solid #1e2535;
        padding: 18px 0 14px 0;
        margin-bottom: 18px;
    }
    .bs-title {
        font-family: 'Syne', sans-serif; font-weight: 800;
        font-size: 1.7rem; color: #e8eaf0;
        letter-spacing: -0.02em; margin: 0;
    }
    .bs-title span { color: #00d4aa; }
    .bs-subtitle { color: #5a6580; font-size: 0.78rem; margin-top: 2px; }

    /* Cards */
    .card {
        background: #131824; border: 1px solid #1e2535;
        border-radius: 10px; padding: 14px 16px 10px 16px;
        margin-bottom: 10px; transition: border-color 0.2s;
    }
    .card:hover { border-color: #2d3a55; }

    /* Action badges */
    .badge {
        display: inline-block; border-radius: 5px;
        padding: 3px 10px; font-size: 0.72rem;
        font-weight: 700; letter-spacing: 0.08em;
    }
    .badge-sb  { background: #003d28; color: #00d4aa; border: 1px solid #00d4aa55; }
    .badge-buy { background: #002d50; color: #4488ff; border: 1px solid #4488ff55; }
    .badge-w   { background: #3d2800; color: #e8a838; border: 1px solid #e8a83855; }
    .badge-sk  { background: #1e2535; color: #5a6580; border: 1px solid #2d3a55; }

    /* Phase badge */
    .phase-badge {
        display: inline-block; border-radius: 4px;
        padding: 2px 8px; font-size: 0.70rem;
        font-weight: 600; letter-spacing: 0.06em;
    }

    /* Exit cards */
    .exit-card {
        background: #131824; border-radius: 10px;
        padding: 14px 16px 10px 16px; margin-bottom: 10px;
        border-left: 4px solid;
    }
    .trigger-pill {
        display: inline-block; border-radius: 10px;
        padding: 2px 8px; margin: 2px 2px 2px 0;
        font-size: 0.70rem; font-family: 'JetBrains Mono', monospace;
    }
    .pill-hard { background: #3d1010; color: #ff8888; }
    .pill-soft { background: #2a2910; color: #ffcc88; }

    /* Metric rows */
    .mrow { display: flex; gap: 24px; flex-wrap: wrap; font-size: 0.84rem; color: #7a8aa0; margin: 6px 0; }
    .mrow b { color: #c8d0e0; }

    /* Dividers */
    hr { border-color: #1e2535 !important; }

    /* Streamlit overrides */
    .stButton > button {
        background: #1e2535; border: 1px solid #2d3a55;
        color: #c8d0e0; border-radius: 6px; font-family: 'Syne', sans-serif;
    }
    .stButton > button:hover { background: #2d3a55; border-color: #4488ff; }

    div[data-testid="metric-container"] {
        background: #131824; border: 1px solid #1e2535;
        border-radius: 8px; padding: 10px 14px;
    }

    .stTabs [data-baseweb="tab-list"] { gap: 4px; background: transparent; }
    .stTabs [data-baseweb="tab"] {
        background: #131824; border: 1px solid #1e2535;
        border-radius: 6px; color: #7a8aa0;
        font-family: 'Syne', sans-serif; font-weight: 600;
        padding: 8px 18px;
    }
    .stTabs [aria-selected="true"] {
        background: #1e2a44 !important; color: #4488ff !important;
        border-color: #4488ff55 !important;
    }
    </style>
    """, unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════
# UI HELPERS
# ══════════════════════════════════════════════════════════════════

def action_badge_html(action: str) -> str:
    cls = {"STRONG BUY": "badge-sb", "BUY": "badge-buy",
           "WATCH": "badge-w", "SKIP": "badge-sk"}.get(action, "badge-sk")
    return f'<span class="badge {cls}">{action}</span>'

def phase_badge_html(phase: str) -> str:
    color = PHASE_COLORS.get(phase, "#555577")
    return (f'<span class="phase-badge" '
            f'style="background:{color}22;color:{color};border:1px solid {color}55;">'
            f'{phase}</span>')

def exit_badge_html(phase: str) -> str:
    color = EXIT_COLORS.get(phase, "#555577")
    return (f'<span class="badge" '
            f'style="background:{color}22;color:{color};border:1px solid {color}55;">'
            f'{phase}</span>')

def render_scan_card(r: dict, mode: str, account_size: float, risk_pct: float):
    action   = r.get("action", "SKIP")
    phase    = r.get("phase", PHASE_IDLE)
    gated    = r.get("breadth_gated", False)
    arrow    = get_phase_arrow(r["sym"])
    entry    = r.get("entry")
    stop_p   = r.get("stop")
    target   = r.get("target")
    psize    = {}
    if entry and stop_p:
        psize = position_size(account_size, risk_pct, entry, stop_p)

    age_str, stale = signal_age_label(r.get("scanned_at",""), mode)
    stale_flag = ' <span style="color:#cc4444;font-size:0.70rem;">⏱ STALE</span>' if stale else ""
    gated_flag = ' <span style="color:#e8a838;font-size:0.70rem;">📊 BREADTH GATED</span>' if gated else ""
    arrow_html = f' <span style="color:#00d4aa;font-size:0.78rem;">{arrow}</span>' if arrow else ""

    card_border = PHASE_COLORS.get(phase, "#1e2535")

    st.markdown(f"""
    <div class="card" style="border-left:4px solid {card_border};">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">
        <div>
          <span style="font-size:1.05rem;font-weight:700;color:#e8eaf0;">{r['sym']}</span>
          {arrow_html}
          <span style="color:#5a6580;font-size:0.75rem;margin-left:8px;">{r.get('sector','')}</span>
        </div>
        <div style="display:flex;gap:8px;align-items:center;">
          {action_badge_html(action)}
          {phase_badge_html(phase)}
        </div>
      </div>
      <div class="mrow">
        <span>LTP <b>{fmt(r['price'])}</b></span>
        <span>Score <b style="color:#00d4aa;">{r['score']:.0f}</b></span>
        <span>RSI <b>{r['rsi']}</b></span>
        <span>ATR <b>{r['atr_val']}</b></span>
        <span>RS <b>{r['rs_rank']}</b></span>
        <span>HTF <b style="color:{'#22aa55' if r['htf_up'] else '#cc4444'};">{'↑' if r['htf_up'] else '↓'}</b></span>
        <span style="color:#3d4a60;font-size:0.75rem;">{age_str}{stale_flag}{gated_flag}</span>
      </div>
      {f'<div class="mrow" style="margin-top:4px;"><span>Entry <b style="color:#4488ff;">{fmt(entry)}</b></span><span>Stop <b style="color:#cc4444;">{fmt(stop_p)}</b></span><span>Target <b style="color:#00d4aa;">{fmt(target)}</b></span>{"<span>Qty <b>" + str(psize.get("qty",0)) + "</b></span><span>Capital <b>" + fmt(psize.get("capital",0)) + "</b></span>" if psize else ""}</div>' if entry else ''}
    </div>
    """, unsafe_allow_html=True)


def render_exit_card(r: ExitResult):
    color      = EXIT_COLORS.get(r.exit_phase, "#555577")
    pnl_color  = "#22cc66" if r.pnl_pct >= 0 else "#cc4444"
    hard_pills = "".join(f'<span class="trigger-pill pill-hard">{t}</span>' for t in r.hard_triggers)
    soft_pills = "".join(f'<span class="trigger-pill pill-soft">{t}</span>' for t in r.soft_triggers)
    all_pills  = hard_pills + soft_pills or '<span class="trigger-pill" style="background:#1e2535;color:#5a6580;">No triggers</span>'
    partial    = f'&nbsp;·&nbsp;Partial exit: <b style="color:#e8a838;">{r.partial_exit_pct}%</b>' if r.partial_exit_pct else ""
    htf_icon   = '<b style="color:#22aa55;">↑ HTF</b>' if r.htf_up else '<b style="color:#cc4444;">↓ HTF</b>'

    st.markdown(f"""
    <div class="exit-card" style="border-color:{color};">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">
        <span style="font-size:1.05rem;font-weight:700;color:#e8eaf0;">{r.sym}</span>
        {exit_badge_html(r.exit_phase)}
      </div>
      <div class="mrow">
        <span>LTP <b>{fmt(r.price)}</b></span>
        <span>Entry <b>{fmt(r.entry_price)}</b></span>
        <span>P&L <b style="color:{pnl_color};">{r.pnl_pct:+.1f}%</b></span>
        <span>Trail Stop <b style="color:#e8a838;">{fmt(r.trailing_stop)}</b></span>
        <span>Exit Score <b style="color:{color};">{r.exit_score:.0f}/100</b></span>
        <span>RS {r.rs_rank}</span>
        {htf_icon}
      </div>
      <div style="margin:6px 0 5px 0;">{all_pills}</div>
      <div style="font-size:0.79rem;color:#5a6580;font-style:italic;">
        {r.urgency_note}{partial}
      </div>
    </div>
    """, unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════
# MAIN APP
# ══════════════════════════════════════════════════════════════════

def main():
    inject_css()

    # ── Header ────────────────────────────────────────────────────
    st.markdown("""
    <div class="bs-header">
      <p class="bs-title">BULL SUTRA <span>Pro</span></p>
      <p class="bs-subtitle">NSE Scanner · v11 · Entry + Exit Intelligence</p>
    </div>
    """, unsafe_allow_html=True)

    # ── Sidebar ───────────────────────────────────────────────────
    with st.sidebar:
        st.markdown("### ⚙️ Settings")

        mode = st.selectbox("Mode", list(MODE_CFG.keys()), index=1)

        universe_choice = st.selectbox("Universe", ["NIFTY 50", "NSE 500", "Custom"])
        if universe_choice == "NIFTY 50":
            universe = NIFTY50
        elif universe_choice == "NSE 500":
            universe = NSE500
        else:
            raw = st.text_area("Custom symbols (comma-separated)", "RELIANCE,TCS,INFY")
            universe = [s.strip().upper() for s in raw.split(",") if s.strip()]

        st.divider()
        st.markdown("### 💰 Position Sizing")
        account_size = st.number_input("Account Size (₹)", value=500000, step=10000)
        risk_pct     = st.slider("Risk per Trade (%)", 0.5, 3.0, 1.0, 0.25)

        st.divider()
        vix_val, vix_label = fetch_vix()
        vix_color = {"CALM":"#22aa55","CAUTION":"#e8a838","STRESS":"#cc4444","UNKNOWN":"#5a6580"}.get(vix_label,"#5a6580")
        st.markdown(f"**India VIX:** <span style='color:{vix_color};font-weight:700;'>{vix_val or '—'} ({vix_label})</span>", unsafe_allow_html=True)

        st.divider()
        run_btn = st.button("🔍 Run Scan", use_container_width=True, type="primary")

    # ── Tabs ──────────────────────────────────────────────────────
    tab_scan, tab_watch, tab_entry, tab_exit = st.tabs([
        "📊 Scan Results", "👁 Watchlist", "🟢 Entry Signals", "🔴 Exit / Sell"
    ])

    # ── Session state init ────────────────────────────────────────
    if "scan_results"    not in st.session_state: st.session_state["scan_results"]    = []
    if "watchlist"       not in st.session_state: st.session_state["watchlist"]       = []
    if "open_positions"  not in st.session_state: st.session_state["open_positions"]  = []
    if "phase_history"   not in st.session_state: st.session_state["phase_history"]   = {}
    if "htf_cache"       not in st.session_state: st.session_state["htf_cache"]       = {}
    if "last_mode"       not in st.session_state: st.session_state["last_mode"]       = mode

    # ── RUN SCAN ──────────────────────────────────────────────────
    if run_btn:
        st.session_state["last_mode"] = mode
        status_text  = st.empty()
        progress_bar = st.progress(0)

        status_text.text("Pre-warming VIX…")
        progress_bar.progress(0.05)

        status_text.text("Fetching HTF data…")
        progress_bar.progress(0.10)
        htf_cache = prefetch_htf_parallel(universe, mode, status_text, progress_bar)
        st.session_state["htf_cache"] = htf_cache

        status_text.text("Scoring stocks…")
        results = run_scan(universe, mode, vix_val, htf_cache, status_text, progress_bar)
        st.session_state["scan_results"] = results

        progress_bar.progress(1.0)
        status_text.text(f"✅ Scan complete — {len(results)} stocks evaluated")
        time.sleep(0.8)
        status_text.empty()
        progress_bar.empty()

    results  = st.session_state["scan_results"]
    htf_cache= st.session_state.get("htf_cache", {})
    cur_mode = st.session_state.get("last_mode", mode)

    # ══════════════════════════════════════════════════════════════
    # TAB 1: SCAN RESULTS
    # ══════════════════════════════════════════════════════════════
    with tab_scan:
        if not results:
            st.info("Run a scan to see results.")
        else:
            n_sb  = sum(1 for r in results if r["action"] == "STRONG BUY")
            n_buy = sum(1 for r in results if r["action"] == "BUY")
            n_w   = sum(1 for r in results if r["action"] == "WATCH")
            n_sk  = sum(1 for r in results if r["action"] == "SKIP")

            c1,c2,c3,c4 = st.columns(4)
            c1.metric("🟢 Strong Buy", n_sb)
            c2.metric("🔵 Buy",        n_buy)
            c3.metric("🟡 Watch",      n_w)
            c4.metric("⚫ Skip",       n_sk)
            st.divider()

            # Filters
            fc1, fc2, fc3 = st.columns([2,2,1])
            with fc1:
                act_filter = st.multiselect("Action", ["STRONG BUY","BUY","WATCH","SKIP"],
                                            default=["STRONG BUY","BUY","WATCH"], key="scan_af")
            with fc2:
                phase_filter = st.multiselect("Phase",
                    [PHASE_BRK,PHASE_CONT,PHASE_ENTRY,PHASE_SETUP,PHASE_IDLE,PHASE_EXIT],
                    default=[PHASE_BRK,PHASE_CONT,PHASE_ENTRY,PHASE_SETUP], key="scan_pf")
            with fc3:
                sec_filter = st.selectbox("Sector", ["All"] + sorted(set(SECTOR_MAP.values())), key="scan_sf")

            filtered = [r for r in results
                        if r["action"] in act_filter
                        and r["phase"] in phase_filter
                        and (sec_filter == "All" or r.get("sector") == sec_filter)]

            st.caption(f"Showing {len(filtered)} of {len(results)} stocks")

            for r in filtered:
                render_scan_card(r, cur_mode, account_size, risk_pct)
                col_a, col_b = st.columns([1,1])
                with col_a:
                    if st.button(f"+ Watchlist", key=f"wl_{r['sym']}"):
                        wl_syms = [w["sym"] for w in st.session_state["watchlist"]]
                        if r["sym"] not in wl_syms:
                            st.session_state["watchlist"].append(r)
                            st.success(f"Added {r['sym']} to Watchlist")
                with col_b:
                    if r.get("entry") and st.button(f"+ Log Entry", key=f"en_{r['sym']}"):
                        add_position(r["sym"], r["entry"], rs_rank=r.get("rs_rank",50))
                        st.success(f"Position logged: {r['sym']} @ {fmt(r['entry'])}")

    # ══════════════════════════════════════════════════════════════
    # TAB 2: WATCHLIST
    # ══════════════════════════════════════════════════════════════
    with tab_watch:
        watchlist = st.session_state["watchlist"]
        if not watchlist:
            st.info("No stocks on watchlist. Add from Scan Results.")
        else:
            st.markdown(f"**{len(watchlist)} stock(s) on watchlist**")
            st.divider()
            for i, r in enumerate(watchlist):
                render_scan_card(r, cur_mode, account_size, risk_pct)
                col_a, col_b = st.columns([1,1])
                with col_a:
                    if r.get("entry") and st.button(f"+ Log Entry", key=f"wen_{r['sym']}"):
                        add_position(r["sym"], r["entry"], rs_rank=r.get("rs_rank",50))
                        st.success(f"Position logged: {r['sym']} @ {fmt(r['entry'])}")
                with col_b:
                    if st.button(f"Remove", key=f"wrm_{r['sym']}"):
                        st.session_state["watchlist"].pop(i)
                        st.rerun()

    # ══════════════════════════════════════════════════════════════
    # TAB 3: ENTRY SIGNALS
    # ══════════════════════════════════════════════════════════════
    with tab_entry:
        entry_results = [r for r in results
                         if r["phase"] in (PHASE_ENTRY, PHASE_BRK)
                         and r["action"] in ("STRONG BUY","BUY")]
        if not entry_results:
            st.info("No active entry signals. Run a scan first.")
        else:
            st.markdown(f"**{len(entry_results)} active entry signal(s)**")
            st.divider()
            for r in entry_results:
                render_scan_card(r, cur_mode, account_size, risk_pct)
                if r.get("entry") and st.button(f"✅ Log Entry — {r['sym']}", key=f"ep_{r['sym']}"):
                    add_position(r["sym"], r["entry"], rs_rank=r.get("rs_rank",50))
                    st.success(f"Position logged: {r['sym']} @ {fmt(r['entry'])}")

    # ══════════════════════════════════════════════════════════════
    # TAB 4: EXIT / SELL
    # ══════════════════════════════════════════════════════════════
    with tab_exit:
        st.markdown("### 🔴 Exit / Sell Monitor")

        # ── Position manager ──────────────────────────────────────
        with st.expander("➕ Manage Open Positions", expanded=len(st.session_state["open_positions"]) == 0):
            cols = st.columns([2,2,1,1])
            sym_in   = cols[0].text_input("Symbol", key="pm_sym", placeholder="RELIANCE")
            price_in = cols[1].number_input("Entry Price (₹)", min_value=0.01,
                                             value=100.0, key="pm_price")
            qty_in   = cols[2].number_input("Qty", min_value=1, value=1, key="pm_qty")
            add_btn  = cols[3].button("Add", key="pm_add", use_container_width=True)

            if add_btn and sym_in.strip():
                add_position(sym_in.strip().upper(), float(price_in),
                             int(qty_in), rs_rank=50)
                st.success(f"Added {sym_in.strip().upper()}")
                st.rerun()

            positions = st.session_state["open_positions"]
            if positions:
                st.markdown("**Open positions:**")
                for pos in positions:
                    pc1, pc2 = st.columns([5,1])
                    pc1.markdown(
                        f"`{pos['sym']}` — Entry ₹{pos['entry_price']:,.2f} × {pos.get('qty',1)} | "
                        f"Added {pos.get('entry_date','')[:10]}"
                    )
                    if pc2.button("Remove", key=f"xrm_{pos['sym']}"):
                        remove_position(pos["sym"])
                        st.rerun()
            else:
                st.caption("No positions yet. Add above or log from Entry tab.")

        st.divider()

        positions = st.session_state["open_positions"]
        if not positions:
            st.info("No open positions tracked.")
        else:
            # ── Summary metrics ───────────────────────────────────
            with st.spinner("Scanning exit signals…"):
                exit_results = run_exit_scan(positions, cur_mode, vix_val, htf_cache)

            n_exit_now = sum(1 for r in exit_results if r.exit_phase == EXIT_CONFIRMED)
            n_signal   = sum(1 for r in exit_results if r.exit_phase == EXIT_SIGNAL)
            n_watch    = sum(1 for r in exit_results if r.exit_phase == EXIT_WATCH)
            n_hold     = sum(1 for r in exit_results if r.exit_phase == EXIT_HOLD)
            valid_pnl  = [r.pnl_pct for r in exit_results if r.error is None]
            avg_pnl    = np.mean(valid_pnl) if valid_pnl else 0.0

            e1,e2,e3,e4,e5 = st.columns(5)
            e1.metric("🔴 EXIT NOW",    n_exit_now)
            e2.metric("🟠 EXIT SIGNAL", n_signal)
            e3.metric("🟡 EXIT WATCH",  n_watch)
            e4.metric("🟢 HOLD",        n_hold)
            e5.metric("Avg P&L",        f"{avg_pnl:+.1f}%")

            st.divider()

            # ── Filters ───────────────────────────────────────────
            xf1, xf2 = st.columns([3,1])
            with xf1:
                phase_filter_x = st.multiselect(
                    "Show phases",
                    [EXIT_CONFIRMED, EXIT_SIGNAL, EXIT_WATCH, EXIT_HOLD],
                    default=[EXIT_CONFIRMED, EXIT_SIGNAL, EXIT_WATCH, EXIT_HOLD],
                    key="exit_pf"
                )
            with xf2:
                sort_x = st.selectbox("Sort", ["Exit Score","P&L % ↓","P&L % ↑","Symbol"], key="exit_sort")

            filtered_x = [r for r in exit_results if r.exit_phase in phase_filter_x]
            if sort_x == "P&L % ↓":  filtered_x.sort(key=lambda r: r.pnl_pct, reverse=True)
            elif sort_x == "P&L % ↑": filtered_x.sort(key=lambda r: r.pnl_pct)
            elif sort_x == "Symbol":   filtered_x.sort(key=lambda r: r.sym)

            # ── Exit cards ────────────────────────────────────────
            for r in filtered_x:
                render_exit_card(r)
                if r.error:
                    st.warning(f"{r.sym}: {r.error}", icon="⚠️")
                # Quick-remove button
                if st.button(f"Mark Exited — {r.sym}", key=f"exit_rm_{r.sym}"):
                    remove_position(r.sym)
                    st.success(f"{r.sym} removed from open positions.")
                    st.rerun()

            if not filtered_x:
                st.info("No positions match the selected filters.")

            st.caption(f"Last updated: {datetime.now().strftime('%H:%M:%S')}  ·  {len(exit_results)} position(s)")

    # ── Legend sidebar ─────────────────────────────────────────────
    with st.sidebar:
        st.divider()
        st.markdown("#### Exit Trigger Legend")
        for label, desc in [
            ("H1:TrailStop",   "Price below trailing stop"),
            ("H2:EMAxDown",    "EMA fast crossed below slow"),
            ("H3:HTFBearish",  "Higher-TF trend bearish"),
            ("H4:VolClimax",   "3× vol on red candle"),
            ("S1:RSIrev",      "RSI overbought reversal"),
            ("S2:BearEngulf",  "Bearish engulfing candle"),
            ("S3:FibExt",      "At fib extension 1.27/1.61"),
            ("S4:PhaseRegr",   "Phase stepped backwards"),
            ("S5:MomDecay",    "1-bar mom turned negative"),
            ("S6:RS<40",       "RS rank below 40"),
            ("S7:GapExhaust",  "Gap-up but closed weak"),
        ]:
            prefix = "🔴" if label.startswith("H") else "🟡"
            st.markdown(
                f"{prefix} `{label}` <span style='color:#5a6580;font-size:0.75rem;'>{desc}</span>",
                unsafe_allow_html=True
            )


if __name__ == "__main__":
    main()
