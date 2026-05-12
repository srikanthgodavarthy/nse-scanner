"""BULL SUTRA Pro — v13 + SHORT SELL + PORTFOLIO TAB
═══════════════════════════════════════════════════════════════════
BASE: v12 solid — all FIX-1 … FIX-6 preserved, exit layer intact.
NEW:  Short Sell Engine + Portfolio tab overhaul.
  • ShortResult dataclass + score_short() — 4 hard + 7 soft triggers
  • run_short_scan()         — parallel, thread-safe
  • Tab 6: 💼 Portfolio      — open positions cards (exit signals)
                               + Ready to Short cards (same style)
  • Tab renamed from "🔴 Exit/Sell" → "💼 Portfolio"
PERSISTENCE:
  • Positions + Short watchlist saved to Supabase Postgres
  • Set SUPABASE_URL in Streamlit Cloud Secrets
═══════════════════════════════════════════════════════════════════
"""

import warnings
import logging
import time
import os
import threading
import concurrent.futures
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

import numpy as np
import pandas as pd
import psycopg2
import yfinance as yf
import streamlit as st

logging.getLogger("yfinance").setLevel(logging.CRITICAL)
warnings.filterwarnings("ignore")

# ── Universes ──────────────────────────────────────────────────────────────────

try:
    from nse500 import nse500_symbols
    NSE500 = list(dict.fromkeys([s.strip().upper().replace(".NS", "") for s in nse500_symbols]))
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

NSE_OPEN_HOUR,  NSE_OPEN_MIN  = 9, 15
NSE_CLOSE_HOUR, NSE_CLOSE_MIN = 15, 30
NSE_SESSION_MINUTES = (NSE_CLOSE_HOUR * 60 + NSE_CLOSE_MIN) - (NSE_OPEN_HOUR * 60 + NSE_OPEN_MIN)

# ── Exit Layer Constants ───────────────────────────────────────────────────────

EXIT_HOLD      = "HOLD"
EXIT_WATCH     = "EXIT WATCH"
EXIT_SIGNAL    = "EXIT SIGNAL"
EXIT_CONFIRMED = "EXIT NOW"

EXIT_COLORS = {
    EXIT_HOLD:      "#22aa55",
    EXIT_WATCH:     "#f59e0b",
    EXIT_SIGNAL:    "#ff8800",
    EXIT_CONFIRMED: "#cc4444",
}

EXIT_SCORE_WATCH     = 20
EXIT_SCORE_SIGNAL    = 40
EXIT_SCORE_CONFIRMED = 65
EXIT_HARD_WEIGHT     = 25
EXIT_SOFT_WEIGHT     = 10

# ── Short Sell Constants ───────────────────────────────────────────────────────

SHORT_SKIP      = "SKIP"
SHORT_WATCH     = "SHORT WATCH"
SHORT_SIGNAL    = "SHORT SIGNAL"
SHORT_CONFIRMED = "SHORT NOW"

SHORT_COLORS = {
    SHORT_SKIP:      "#555577",
    SHORT_WATCH:     "#f59e0b",
    SHORT_SIGNAL:    "#ff6b35",
    SHORT_CONFIRMED: "#cc2244",
}

SHORT_SCORE_WATCH     = 25
SHORT_SCORE_SIGNAL    = 45
SHORT_SCORE_CONFIRMED = 68
SHORT_HARD_WEIGHT     = 22
SHORT_SOFT_WEIGHT     = 9

# ── Thread safety ──────────────────────────────────────────────────────────────
_phase_lock = threading.Lock()


# ═══════════════════════════════════════════════════════════════════════════════
# SUPABASE PERSISTENCE
# ═══════════════════════════════════════════════════════════════════════════════

def _get_conn():
    try:
        url = st.secrets["SUPABASE_URL"]
    except Exception:
        raise ValueError("SUPABASE_URL secret is missing — check Streamlit Cloud Secrets")
    if not url or not url.startswith(("postgres://", "postgresql://")):
        raise ValueError(f"SUPABASE_URL looks wrong: {url[:30]}...")
    return psycopg2.connect(url)

def _ensure_table(cur):
    cur.execute("""
        CREATE TABLE IF NOT EXISTS positions (
            id         SERIAL PRIMARY KEY,
            data       JSONB NOT NULL,
            updated_at TIMESTAMP DEFAULT now()
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS short_watchlist (
            id         SERIAL PRIMARY KEY,
            data       JSONB NOT NULL,
            updated_at TIMESTAMP DEFAULT now()
        )
    """)

def _save_positions():
    try:
        conn = _get_conn()
        cur  = conn.cursor()
        _ensure_table(cur)
        conn.commit()
        cur.execute("DELETE FROM positions")
        cur.execute(
            "INSERT INTO positions (data) VALUES (%s)",
            [json.dumps(st.session_state.get("open_positions", []))]
        )
        conn.commit()
        cur.close(); conn.close()
        st.session_state["_db_error"] = None
    except Exception as e:
        st.session_state["_db_error"] = str(e)

def _save_short_watchlist():
    try:
        conn = _get_conn()
        cur  = conn.cursor()
        _ensure_table(cur)
        conn.commit()
        cur.execute("DELETE FROM short_watchlist")
        cur.execute(
            "INSERT INTO short_watchlist (data) VALUES (%s)",
            [json.dumps(st.session_state.get("short_watchlist", []))]
        )
        conn.commit()
        cur.close(); conn.close()
    except Exception as e:
        st.session_state["_db_error"] = str(e)

def _load_positions() -> list:
    try:
        conn = _get_conn()
        cur  = conn.cursor()
        _ensure_table(cur); conn.commit()
        cur.execute("SELECT data FROM positions ORDER BY updated_at DESC LIMIT 1")
        row = cur.fetchone()
        cur.close(); conn.close()
        if row and row[0]:
            return row[0] if isinstance(row[0], list) else json.loads(row[0])
        return []
    except Exception:
        return []

def _load_short_watchlist() -> list:
    try:
        conn = _get_conn()
        cur  = conn.cursor()
        _ensure_table(cur); conn.commit()
        cur.execute("SELECT data FROM short_watchlist ORDER BY updated_at DESC LIMIT 1")
        row = cur.fetchone()
        cur.close(); conn.close()
        if row and row[0]:
            return row[0] if isinstance(row[0], list) else json.loads(row[0])
        return []
    except Exception:
        return []


# ═══════════════════════════════════════════════════════════════════════════════
# MATH HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

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
        "236": sw_hi - rng * 0.236, "382": sw_hi - rng * 0.382,
        "500": sw_hi - rng * 0.500, "618": sw_hi - rng * 0.618,
        "786": sw_hi - rng * 0.786,
        "ext127": sw_hi + rng * 0.272, "ext161": sw_hi + rng * 0.618,
        "ext261": sw_hi + rng * 1.618,
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


# ═══════════════════════════════════════════════════════════════════════════════
# FIX-4 HELPER — intraday time-normalised volume
# ═══════════════════════════════════════════════════════════════════════════════

def _session_elapsed_fraction() -> float:
    now_utc  = datetime.utcnow()
    now_ist  = now_utc + timedelta(hours=5, minutes=30)
    minutes_since_open = (now_ist.hour * 60 + now_ist.minute) - (NSE_OPEN_HOUR * 60 + NSE_OPEN_MIN)
    fraction = minutes_since_open / NSE_SESSION_MINUTES
    return float(np.clip(fraction, 0.05, 1.0))

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


# ═══════════════════════════════════════════════════════════════════════════════
# SIGNAL VALIDITY HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

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


# ═══════════════════════════════════════════════════════════════════════════════
# VIX
# ═══════════════════════════════════════════════════════════════════════════════

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


# ═══════════════════════════════════════════════════════════════════════════════
# LIQUIDITY FILTER
# ═══════════════════════════════════════════════════════════════════════════════

def liquidity_ok(df, min_cr=LIQUIDITY_MIN_CR, mode="Swing"):
    try:
        traded    = df["Close"] * df["Volume"]
        n_rows    = len(df)
        if n_rows >= 2:
            idx = df.index
            try:
                delta_min = (idx[1] - idx[0]).total_seconds() / 60
            except Exception:
                delta_min = 1440
        else:
            delta_min = 1440

        if delta_min <= 5:       bars_per_day = 75
        elif delta_min <= 15:    bars_per_day = 25
        elif delta_min <= 30:    bars_per_day = 13
        elif delta_min < 240:    bars_per_day = 7
        else:                    bars_per_day = 1

        if mode == "Intraday" and bars_per_day > 1:
            avg_daily_vol = _intraday_vol_avg(df["Volume"], bars_per_day)
            avg_cr        = float(avg_daily_vol * float(df["Close"].iloc[-1])) / 1e7
        else:
            daily_traded = traded.rolling(bars_per_day).sum()
            avg_cr       = float(daily_traded.rolling(20).mean().iloc[-1]) / 1e7

        return avg_cr >= min_cr, round(avg_cr, 1)
    except Exception:
        return True, 0.0


# ═══════════════════════════════════════════════════════════════════════════════
# HTF — CACHED FETCH + TREND (FIX-1: closed-candle only)
# ═══════════════════════════════════════════════════════════════════════════════

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
            time.sleep(min(0.5 * (attempt + 1), 1.0))
    return pd.DataFrame()

def _htf_trend_from_df(df: pd.DataFrame, mode: str):
    if df is None or df.empty:
        return True, "HTF-UNKNOWN"
    if mode == "Intraday" and len(df) > 2:
        df = df.iloc[:-1].copy()
    min_bars = 55 if mode == "Intraday" else 26
    if len(df) < min_bars:
        return True, "HTF-UNKNOWN"
    cl  = df["Close"]
    ef  = float(ema(cl, 21 if mode == "Intraday" else 13).iloc[-1])
    es  = float(ema(cl, 55 if mode == "Intraday" else 26).iloc[-1])
    c   = float(cl.iloc[-1])
    up  = c > ef > es
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
            progress_bar.progress(0.15 + completed / total * 0.25)
            if completed % 20 == 0:
                status_text.text(f"HTF pre-fetch {completed}/{total}…")
    return results


# ═══════════════════════════════════════════════════════════════════════════════
# RELATIVE STRENGTH — VECTORIZED 52-WEEK PERCENTILE RANK
# ═══════════════════════════════════════════════════════════════════════════════

def compute_rs_ranks(sym_returns: dict) -> dict:
    if not sym_returns:
        return {}
    syms  = list(sym_returns.keys())
    vals  = np.array([sym_returns[s] for s in syms], dtype=np.float64)
    order = np.argsort(vals)
    ranks = np.empty_like(order)
    ranks[order] = np.arange(len(vals))
    normalized = np.round(ranks / max(len(vals) - 1, 1) * 100).astype(int)
    return dict(zip(syms, normalized.tolist()))

def _52w_return(close_series: pd.Series) -> float:
    if len(close_series) < 10:
        return 0.0
    lookback = min(252, len(close_series) - 1)
    c_now    = float(close_series.iloc[-1])
    c_base   = float(close_series.iloc[-lookback])
    if c_base == 0:
        return 0.0
    return round((c_now - c_base) / c_base * 100, 2)


# ═══════════════════════════════════════════════════════════════════════════════
# PHASE TRANSITION MEMORY (PERF-7: thread-safe)
# ═══════════════════════════════════════════════════════════════════════════════

def record_phase_transition(sym: str, new_phase: str):
    if "phase_history" not in st.session_state:
        st.session_state["phase_history"] = {}
    history = st.session_state["phase_history"]
    if sym not in history:
        history[sym] = []

    prev_phase = history[sym][-1][1] if history[sym] else None
    changed    = prev_phase != new_phase
    is_prog    = False
    is_regr    = False
    arrow      = ""

    if changed:
        ts = datetime.now().isoformat()
        history[sym].append((ts, new_phase))
        history[sym] = history[sym][-10:]

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

def phase_transition_conf_bonus(sym: str) -> int:
    history = st.session_state.get("phase_history", {})
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
    prev = history[sym][-2][1]
    curr = history[sym][-1][1]
    if curr == PHASE_EXIT:
        return "→EXIT"
    if PHASE_ORDER.get(curr, 0) > PHASE_ORDER.get(prev, 0):
        return "↗"
    if PHASE_ORDER.get(curr, 0) < PHASE_ORDER.get(prev, 0):
        return "↘"
    return ""


# ═══════════════════════════════════════════════════════════════════════════════
# VOLATILITY-NORMALISED SCORE + BULL SCORE ENGINE
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class BullResult:
    symbol:        str
    raw_score:     int   = 0
    norm_score:    float = 0.0
    action:        str   = "SKIP"
    phase:         str   = PHASE_IDLE
    entry_low:     float = 0.0
    entry_high:    float = 0.0
    stop_loss:     float = 0.0
    target1:       float = 0.0
    target2:       float = 0.0
    target3:       float = 0.0
    risk_reward:   float = 0.0
    atr:           float = 0.0
    rsi_val:       float = 50.0
    volume_ratio:  float = 1.0
    rs_rank:       int   = 50
    htf_trend:     str   = "HTF-UNKNOWN"
    sector:        str   = "—"
    mode:          str   = "Swing"
    liquidity_cr:  float = 0.0
    current_price: float = 0.0
    fib_hi:        float = 0.0
    fib_lo:        float = 0.0
    scored_at:     str   = field(default_factory=lambda: datetime.now().isoformat())
    phase_arrow:   str   = ""
    error:         str   = ""


def score_bull(sym: str, mode: str = "Swing",
               htf_cache: dict = None,
               rs_ranks:  dict = None,
               vix_val:   float = None) -> BullResult:
    result = BullResult(symbol=sym, mode=mode, sector=SECTOR_MAP.get(sym, "—"))
    cfg    = MODE_CFG[mode]

    try:
        ticker = to_nse(sym)
        df = yf.download(
            ticker,
            period=cfg["period"], interval=cfg["interval"],
            auto_adjust=True, progress=False, threads=False,
        )
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df = df.dropna()

        if len(df) < 60:
            result.error = "insufficient data"
            return result

        cl    = df["Close"]
        hi    = df["High"]
        lo    = df["Low"]
        vol   = df["Volume"]
        close = float(cl.iloc[-1])
        result.current_price = close

        liq_ok, liq_cr = liquidity_ok(df, mode=mode)
        result.liquidity_cr = liq_cr
        if not liq_ok:
            result.error = f"low liquidity {liq_cr}Cr"
            return result

        ef_ser = ema(cl, cfg["ema_fast"])
        es_ser = ema(cl, cfg["ema_slow"])
        ef     = float(ef_ser.iloc[-1])
        es     = float(es_ser.iloc[-1])
        atr_v  = float(atr_series(df, cfg["rsi_len"]).iloc[-1])
        result.atr = atr_v

        rsi_v = float(rsi(cl, cfg["rsi_len"]).iloc[-1])
        result.rsi_val = round(rsi_v, 1)

        avg_vol = float(vol.rolling(20).mean().iloc[-1]) or 1
        result.volume_ratio = round(float(vol.iloc[-1]) / avg_vol, 2)

        sw_hi, sw_lo, fibs, fib_rng = fib_levels(df)
        result.fib_hi = sw_hi
        result.fib_lo = sw_lo

        def _ret(n):
            if len(cl) <= n:
                return 0.0
            return float((cl.iloc[-1] - cl.iloc[-n]) / cl.iloc[-n] * 100)

        mom1 = _ret(22)
        mom3 = _ret(66)
        mom6 = _ret(132)

        # ── HTF trend ────────────────────────────────────────────────
        if htf_cache and sym in htf_cache:
            htf_up, htf_label = htf_cache[sym]
        else:
            htf_df = _fetch_htf_cached(ticker, cfg["htf_period"], cfg["htf_interval"])
            htf_up, htf_label = _htf_trend_from_df(htf_df, mode)
        result.htf_trend = htf_label

        # ── RS rank ──────────────────────────────────────────────────
        rs_rank = rs_ranks.get(sym, 50) if rs_ranks else 50
        result.rs_rank = rs_rank

        # ── Phase ────────────────────────────────────────────────────
        above_ef = close > ef
        above_es = close > es
        ef_above_es = ef > es

        if not above_ef and not above_es:
            phase = PHASE_EXIT
        elif above_ef and above_es and ef_above_es:
            if close > sw_hi * 0.98:
                phase = PHASE_BRK
            elif mom1 > cfg["mom1_th"] and mom3 > 0:
                phase = PHASE_CONT
            else:
                phase = PHASE_ENTRY
        elif above_ef and not ef_above_es:
            phase = PHASE_SETUP
        else:
            phase = PHASE_IDLE

        with _phase_lock:
            record_phase_transition(sym, phase)
            result.phase_arrow = get_phase_arrow(sym)
        result.phase = phase

        # ── Scoring ──────────────────────────────────────────────────
        score = 0

        # trend alignment
        if above_ef:              score += 10
        if above_es:              score += 10
        if ef_above_es:           score += 10
        if htf_up:                score += 15

        # momentum
        if mom1 > cfg["mom1_th"]: score += 8
        if mom3 > cfg["mom3_th"]: score += 8
        if mom6 > cfg["mom6_th"]: score += 8

        # RSI zone
        if 45 < rsi_v < 70:      score += 10
        elif 35 < rsi_v <= 45:   score += 5

        # volume
        if result.volume_ratio > 1.5: score += 8
        elif result.volume_ratio > 1.2: score += 4

        # RS rank
        if rs_rank >= 80:         score += 10
        elif rs_rank >= 60:       score += 5

        # phase bonus
        phase_bonus = {PHASE_BRK:15, PHASE_CONT:10, PHASE_ENTRY:5, PHASE_SETUP:2}.get(phase, 0)
        score += phase_bonus
        score += phase_transition_conf_bonus(sym)

        result.raw_score  = score
        result.norm_score = round(min(score / BULL_MAX * 100, 100), 1)
        result.action     = action_label(result.norm_score)

        # ── Levels ───────────────────────────────────────────────────
        t1m, t2m, t3m, sl_m = vix_target_mult(vix_val)
        result.entry_low  = round(close - atr_v * 0.3, 2)
        result.entry_high = round(close + atr_v * 0.3, 2)
        result.stop_loss  = round(close - atr_v * cfg["atr_mult"] * sl_m, 2)
        result.target1    = round(close + atr_v * cfg["atr_mult"] * t1m, 2)
        result.target2    = round(close + atr_v * cfg["atr_mult"] * t2m, 2)
        result.target3    = round(close + atr_v * cfg["atr_mult"] * t3m, 2)
        risk              = close - result.stop_loss
        reward            = result.target2 - close
        result.risk_reward = round(reward / risk, 2) if risk > 0 else 0.0

    except Exception as e:
        result.error = str(e)

    return result


def run_scan(symbols: list, mode: str,
             htf_cache: dict = None,
             rs_ranks:  dict = None,
             vix_val:   float = None,
             status_text=None, progress_bar=None) -> list[BullResult]:
    results  = []
    total    = len(symbols)
    completed = 0

    def _score_one(sym):
        return score_bull(sym, mode, htf_cache, rs_ranks, vix_val)

    with concurrent.futures.ThreadPoolExecutor(max_workers=min(32, total)) as pool:
        futures = {pool.submit(_score_one, sym): sym for sym in symbols}
        for fut in concurrent.futures.as_completed(futures):
            results.append(fut.result())
            completed += 1
            if progress_bar:
                progress_bar.progress(0.5 + completed / total * 0.5)
            if status_text and completed % 20 == 0:
                status_text.text(f"Scored {completed}/{total}…")

    results.sort(key=lambda r: r.norm_score, reverse=True)
    return results


# ═══════════════════════════════════════════════════════════════════════════════
# EXIT LAYER
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class ExitResult:
    symbol:        str
    verdict:       str   = EXIT_HOLD
    exit_score:    int   = 0
    triggers:      list  = field(default_factory=list)
    trailing_stop: float = None
    current_price: float = 0.0
    atr:           float = 0.0
    error:         str   = ""


def compute_trailing_stop(close: float, atr: float, pnl_pct: float, vix_val: float = None) -> float:
    base_mult = 2.0
    if vix_val and vix_val >= VIX_STRESS:
        base_mult = 1.5
    elif vix_val and vix_val >= VIX_CAUTION:
        base_mult = 1.75
    if pnl_pct >= 20:
        base_mult *= 0.7
    elif pnl_pct >= 10:
        base_mult *= 0.85
    return round(close - atr * base_mult, 2)


def score_exit(sym: str, entry_price: float, mode: str = "Swing",
               vix_val: float = None) -> ExitResult:
    result = ExitResult(symbol=sym)
    cfg    = MODE_CFG[mode]

    try:
        ticker = to_nse(sym)
        df = yf.download(
            ticker,
            period=cfg["period"], interval=cfg["interval"],
            auto_adjust=True, progress=False, threads=False,
        )
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df = df.dropna()

        if len(df) < 30:
            result.error = "insufficient data"
            return result

        cl    = df["Close"]
        close = float(cl.iloc[-1])
        result.current_price = close

        atr_v = float(atr_series(df, cfg["rsi_len"]).iloc[-1])
        result.atr = atr_v

        ef = float(ema(cl, cfg["ema_fast"]).iloc[-1])
        es = float(ema(cl, cfg["ema_slow"]).iloc[-1])
        rsi_v = float(rsi(cl, cfg["rsi_len"]).iloc[-1])
        avg_vol = float(df["Volume"].rolling(20).mean().iloc[-1]) or 1
        vol_ratio = float(df["Volume"].iloc[-1]) / avg_vol

        pnl_pct = (close - entry_price) / entry_price * 100 if entry_price else 0
        result.trailing_stop = compute_trailing_stop(close, atr_v, pnl_pct, vix_val)

        score    = 0
        triggers = []

        # Hard triggers (EXIT_HARD_WEIGHT each)
        if close < ef:
            score += EXIT_HARD_WEIGHT; triggers.append("Price < Fast EMA")
        if close < es:
            score += EXIT_HARD_WEIGHT; triggers.append("Price < Slow EMA")
        if rsi_v > 78:
            score += EXIT_HARD_WEIGHT; triggers.append(f"RSI Overbought {rsi_v:.0f}")
        if entry_price and pnl_pct < -8:
            score += EXIT_HARD_WEIGHT; triggers.append(f"Stop-Loss Hit {pnl_pct:.1f}%")

        # Soft triggers (EXIT_SOFT_WEIGHT each)
        if ef < es:
            score += EXIT_SOFT_WEIGHT; triggers.append("EMA Bearish Cross")
        if rsi_v > 70:
            score += EXIT_SOFT_WEIGHT; triggers.append(f"RSI High {rsi_v:.0f}")
        if vol_ratio > 2.0 and float(df["Close"].iloc[-1]) < float(df["Open"].iloc[-1]):
            score += EXIT_SOFT_WEIGHT; triggers.append("High Vol Down Day")
        if entry_price and pnl_pct > 30:
            score += EXIT_SOFT_WEIGHT; triggers.append(f"Large Profit {pnl_pct:.1f}% — Lock In")
        if vix_val and vix_val >= VIX_STRESS:
            score += EXIT_SOFT_WEIGHT; triggers.append(f"VIX Stress {vix_val}")

        _, _, fibs, _ = fib_levels(df)
        if fibs and close < fibs.get("618", 0):
            score += EXIT_SOFT_WEIGHT; triggers.append("Below 61.8% Fib")

        htf_df  = _fetch_htf_cached(ticker, cfg["htf_period"], cfg["htf_interval"])
        htf_up, _ = _htf_trend_from_df(htf_df, mode)
        if not htf_up:
            score += EXIT_SOFT_WEIGHT; triggers.append("HTF Downtrend")

        result.exit_score = min(score, 100)
        result.triggers   = triggers

        if score >= EXIT_SCORE_CONFIRMED:
            result.verdict = EXIT_CONFIRMED
        elif score >= EXIT_SCORE_SIGNAL:
            result.verdict = EXIT_SIGNAL
        elif score >= EXIT_SCORE_WATCH:
            result.verdict = EXIT_WATCH
        else:
            result.verdict = EXIT_HOLD

    except Exception as e:
        result.error = str(e)

    return result


def run_exit_scan(positions: list, vix_val: float = None) -> dict:
    out = {}

    def _scan_one(pos):
        sym   = pos["symbol"]
        entry = pos.get("entry_price", 0)
        mode  = pos.get("mode", "Swing")
        return sym, score_exit(sym, entry, mode, vix_val)

    with concurrent.futures.ThreadPoolExecutor(max_workers=min(16, len(positions) or 1)) as pool:
        for sym, er in pool.map(_scan_one, positions):
            out[sym] = er
    return out


# ═══════════════════════════════════════════════════════════════════════════════
# SHORT SELL ENGINE  ← NEW in v13
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class ShortResult:
    symbol:         str
    verdict:        str   = SHORT_SKIP
    short_score:    int   = 0
    hard_triggers:  list  = field(default_factory=list)
    soft_triggers:  list  = field(default_factory=list)
    entry_zone_hi:  float = 0.0   # short entry — sell into this zone
    entry_zone_lo:  float = 0.0
    stop_loss:      float = 0.0   # stop ABOVE entry (buy to cover)
    target1:        float = 0.0
    target2:        float = 0.0
    target3:        float = 0.0
    risk_reward:    float = 0.0
    current_price:  float = 0.0
    atr:            float = 0.0
    rsi_val:        float = 50.0
    volume_ratio:   float = 1.0
    rs_rank:        int   = 50
    htf_trend:      str   = "HTF-UNKNOWN"
    phase:          str   = PHASE_IDLE
    sector:         str   = "—"
    mode:           str   = "Swing"
    scanned_at:     str   = field(default_factory=lambda: datetime.now().isoformat())
    error:          str   = ""

    @property
    def all_triggers(self):
        return self.hard_triggers + self.soft_triggers


def score_short(sym: str, mode: str = "Swing",
                htf_cache: dict = None,
                rs_ranks:  dict = None,
                vix_val:   float = None) -> ShortResult:
    """
    Score a stock for short-selling potential.

    Hard triggers (SHORT_HARD_WEIGHT = 22 pts each — max 4):
      H1  Bearish EMA alignment: price < fast EMA < slow EMA
      H2  Death cross: fast EMA recently crossed below slow EMA (last 5 bars)
      H3  HTF downtrend confirmed
      H4  52-week breakdown: price within 3% of 52-week low OR below prior swing low

    Soft triggers (SHORT_SOFT_WEIGHT = 9 pts each — max 7):
      S1  RSI overbought rollover: RSI was > 68 and now falling (exhaustion top)
      S2  RSI bearish zone: RSI < 42 in a downtrend
      S3  Negative 1-month momentum
      S4  Negative 3-month momentum
      S5  High-volume red day: today's candle bearish + volume > 1.5× avg
      S6  Below key Fibonacci level (61.8% or 50% retrace of last swing)
      S7  Relative weakness: RS rank < 30 (bottom quartile of universe)
    """
    result = ShortResult(symbol=sym, mode=mode, sector=SECTOR_MAP.get(sym, "—"))
    cfg    = MODE_CFG[mode]

    try:
        ticker = to_nse(sym)
        df = yf.download(
            ticker,
            period=cfg["period"], interval=cfg["interval"],
            auto_adjust=True, progress=False, threads=False,
        )
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df = df.dropna()

        if len(df) < 60:
            result.error = "insufficient data"
            return result

        cl    = df["Close"]
        hi    = df["High"]
        lo    = df["Low"]
        vol   = df["Volume"]
        close = float(cl.iloc[-1])
        result.current_price = close

        ef_ser = ema(cl, cfg["ema_fast"])
        es_ser = ema(cl, cfg["ema_slow"])
        ef     = float(ef_ser.iloc[-1])
        es     = float(es_ser.iloc[-1])
        atr_v  = float(atr_series(df, cfg["rsi_len"]).iloc[-1])
        result.atr = atr_v

        rsi_v = float(rsi(cl, cfg["rsi_len"]).iloc[-1])
        result.rsi_val = round(rsi_v, 1)

        avg_vol   = float(vol.rolling(20).mean().iloc[-1]) or 1
        today_vol = float(vol.iloc[-1])
        result.volume_ratio = round(today_vol / avg_vol, 2)

        # momentum
        def _ret(n):
            if len(cl) <= n:
                return 0.0
            return float((cl.iloc[-1] - cl.iloc[-n]) / cl.iloc[-n] * 100)

        mom1 = _ret(22)
        mom3 = _ret(66)

        # 52-week metrics
        w52_lo = float(lo.iloc[-252:].min()) if len(lo) >= 252 else float(lo.min())
        w52_hi = float(hi.iloc[-252:].max()) if len(hi) >= 252 else float(hi.max())

        # swing low (prior 20 bars)
        prior_swing_lo = float(lo.iloc[-21:-1].min()) if len(lo) > 21 else float(lo.min())

        # RSI lookback (was RSI high?)
        rsi_ser   = rsi(cl, cfg["rsi_len"])
        rsi_5_ago = float(rsi_ser.iloc[-6]) if len(rsi_ser) >= 6 else rsi_v

        # HTF trend
        if htf_cache and sym in htf_cache:
            htf_up, htf_label = htf_cache[sym]
        else:
            htf_df = _fetch_htf_cached(ticker, cfg["htf_period"], cfg["htf_interval"])
            htf_up, htf_label = _htf_trend_from_df(htf_df, mode)
        result.htf_trend = htf_label

        # RS rank
        rs_rank = rs_ranks.get(sym, 50) if rs_ranks else 50
        result.rs_rank = rs_rank

        # Phase from existing phase engine (shorts favour EXIT / IDLE)
        above_ef    = close > ef
        above_es    = close > es
        ef_above_es = ef > es
        if not above_ef and not above_es:
            phase = PHASE_EXIT
        elif above_ef and above_es and ef_above_es:
            phase = PHASE_CONT if mom1 > 0 else PHASE_ENTRY
        elif above_ef and not ef_above_es:
            phase = PHASE_SETUP
        else:
            phase = PHASE_IDLE
        result.phase = phase

        # ── HARD TRIGGERS ────────────────────────────────────────────
        score          = 0
        hard_triggers  = []
        soft_triggers  = []

        # H1 — Bearish EMA alignment
        if close < ef and ef < es:
            score += SHORT_HARD_WEIGHT
            hard_triggers.append("Bearish EMA Stack (price < EF < ES)")

        # H2 — Death cross (fast EMA crossed below slow EMA in last 5 bars)
        cross_window = min(5, len(ef_ser) - 1)
        death_cross = False
        for i in range(1, cross_window + 1):
            if float(ef_ser.iloc[-i]) < float(es_ser.iloc[-i]) and \
               float(ef_ser.iloc[-(i+1)]) >= float(es_ser.iloc[-(i+1)]):
                death_cross = True
                break
        if death_cross:
            score += SHORT_HARD_WEIGHT
            hard_triggers.append("Death Cross (EMA bearish crossover)")

        # H3 — HTF downtrend
        if not htf_up:
            score += SHORT_HARD_WEIGHT
            hard_triggers.append(f"HTF Downtrend ({htf_label})")

        # H4 — 52-week breakdown
        near_52w_lo = (close - w52_lo) / w52_lo < 0.03 if w52_lo > 0 else False
        below_swing = close < prior_swing_lo
        if near_52w_lo or below_swing:
            score += SHORT_HARD_WEIGHT
            lbl = "Near 52-Week Low" if near_52w_lo else "Below Swing Low"
            hard_triggers.append(lbl)

        # ── SOFT TRIGGERS ────────────────────────────────────────────

        # S1 — RSI overbought rollover
        if rsi_5_ago > 68 and rsi_v < rsi_5_ago - 5:
            score += SHORT_SOFT_WEIGHT
            soft_triggers.append(f"RSI Rollover ({rsi_5_ago:.0f}→{rsi_v:.0f})")

        # S2 — RSI bearish zone
        if rsi_v < 42 and not htf_up:
            score += SHORT_SOFT_WEIGHT
            soft_triggers.append(f"RSI Bearish Zone ({rsi_v:.0f})")

        # S3 — Negative 1-month momentum
        if mom1 < -cfg["mom1_th"]:
            score += SHORT_SOFT_WEIGHT
            soft_triggers.append(f"Neg 1M Mom ({mom1:.1f}%)")

        # S4 — Negative 3-month momentum
        if mom3 < -cfg["mom3_th"]:
            score += SHORT_SOFT_WEIGHT
            soft_triggers.append(f"Neg 3M Mom ({mom3:.1f}%)")

        # S5 — High-volume red day
        today_red = float(df["Close"].iloc[-1]) < float(df["Open"].iloc[-1])
        if today_red and result.volume_ratio > 1.5:
            score += SHORT_SOFT_WEIGHT
            soft_triggers.append(f"High-Vol Red Day ({result.volume_ratio:.1f}×)")

        # S6 — Below key Fibonacci level
        _, _, fibs, _ = fib_levels(df)
        if fibs:
            below_618 = close < fibs.get("618", float("inf"))
            below_500 = close < fibs.get("500", float("inf"))
            if below_618:
                score += SHORT_SOFT_WEIGHT
                soft_triggers.append("Below 61.8% Fib")
            elif below_500:
                score += SHORT_SOFT_WEIGHT
                soft_triggers.append("Below 50% Fib")

        # S7 — Relative weakness
        if rs_rank < 30:
            score += SHORT_SOFT_WEIGHT
            soft_triggers.append(f"RS Rank Weak ({rs_rank})")

        # VIX bonus — stress markets favour shorts
        if vix_val and vix_val >= VIX_STRESS:
            score += 5

        result.short_score   = min(score, 100)
        result.hard_triggers = hard_triggers
        result.soft_triggers = soft_triggers

        if score >= SHORT_SCORE_CONFIRMED:
            result.verdict = SHORT_CONFIRMED
        elif score >= SHORT_SCORE_SIGNAL:
            result.verdict = SHORT_SIGNAL
        elif score >= SHORT_SCORE_WATCH:
            result.verdict = SHORT_WATCH
        else:
            result.verdict = SHORT_SKIP

        # ── Short trade levels ────────────────────────────────────────
        # Entry: sell into the dead-cat bounce zone just above current price
        atr_sl_mult = cfg["atr_mult"]
        if vix_val and vix_val >= VIX_STRESS:
            atr_sl_mult *= 0.85      # tighter stops in panic markets

        result.entry_zone_lo = round(close,          2)
        result.entry_zone_hi = round(close + atr_v * 0.4, 2)
        result.stop_loss     = round(close + atr_v * atr_sl_mult, 2)   # BUY-TO-COVER stop

        # Targets are BELOW entry (profit from decline)
        result.target1 = round(close - atr_v * cfg["atr_mult"] * 1.0, 2)
        result.target2 = round(close - atr_v * cfg["atr_mult"] * 2.0, 2)
        result.target3 = round(close - atr_v * cfg["atr_mult"] * 3.0, 2)

        risk   = result.stop_loss - close
        reward = close - result.target2
        result.risk_reward = round(reward / risk, 2) if risk > 0 else 0.0

    except Exception as e:
        result.error = str(e)

    return result


def run_short_scan(symbols: list, mode: str,
                   htf_cache: dict = None,
                   rs_ranks:  dict = None,
                   vix_val:   float = None,
                   status_text=None, progress_bar=None) -> list[ShortResult]:
    results   = []
    total     = len(symbols)
    completed = 0

    def _score_one(sym):
        return score_short(sym, mode, htf_cache, rs_ranks, vix_val)

    with concurrent.futures.ThreadPoolExecutor(max_workers=min(32, total)) as pool:
        futures = {pool.submit(_score_one, sym): sym for sym in symbols}
        for fut in concurrent.futures.as_completed(futures):
            results.append(fut.result())
            completed += 1
            if progress_bar:
                progress_bar.progress(0.5 + completed / total * 0.5)
            if status_text and completed % 20 == 0:
                status_text.text(f"Short scan {completed}/{total}…")

    # sort: best short candidates first (highest score), skip SKIP verdicts
    results.sort(key=lambda r: r.short_score, reverse=True)
    return [r for r in results if r.verdict != SHORT_SKIP and not r.error]


# ═══════════════════════════════════════════════════════════════════════════════
# POSITION MANAGER
# ═══════════════════════════════════════════════════════════════════════════════

def init_session():
    if "open_positions"  not in st.session_state:
        st.session_state["open_positions"]  = _load_positions()
    if "short_watchlist" not in st.session_state:
        st.session_state["short_watchlist"] = _load_short_watchlist()
    if "exit_results"    not in st.session_state:
        st.session_state["exit_results"]    = {}
    if "short_results"   not in st.session_state:
        st.session_state["short_results"]   = []
    if "scan_results"    not in st.session_state:
        st.session_state["scan_results"]    = []
    if "phase_history"   not in st.session_state:
        st.session_state["phase_history"]   = {}
    if "_db_error"       not in st.session_state:
        st.session_state["_db_error"]       = None


def add_position(sym: str, entry_price: float, qty: int,
                 mode: str, entry_date: str = None):
    pos = dict(
        symbol      = sym.upper(),
        entry_price = entry_price,
        qty         = qty,
        mode        = mode,
        entry_date  = entry_date or datetime.now().date().isoformat(),
        current_price = entry_price,
    )
    existing = [p for p in st.session_state["open_positions"]
                if not (p["symbol"] == sym.upper() and p["entry_date"] == pos["entry_date"])]
    st.session_state["open_positions"] = existing + [pos]
    _save_positions()


# ═══════════════════════════════════════════════════════════════════════════════
# SHARED CARD CSS
# ═══════════════════════════════════════════════════════════════════════════════

CARD_CSS = """
<style>
.bull-card, .short-card {
    border-radius: 12px;
    padding: 16px 20px 12px 20px;
    margin-bottom: 14px;
    font-family: 'Segoe UI', sans-serif;
}
.pill {
    display: inline-block;
    border-radius: 14px;
    padding: 2px 10px;
    font-size: 0.68rem;
    margin: 2px 3px 2px 0;
}
.score-bar-bg {
    background: #2d2d40;
    border-radius: 6px;
    height: 7px;
    overflow: hidden;
    margin-top: 3px;
}
</style>
"""


def _render_exit_card(pos: dict, er: ExitResult):
    """Render one open-position card with exit signal overlay."""
    sym       = pos["symbol"]
    verdict   = er.verdict    if er else EXIT_HOLD
    ex_score  = er.exit_score if er else 0
    triggers  = er.triggers   if er else []
    trail_sl  = er.trailing_stop if er else None
    entry_px  = pos.get("entry_price", 0)
    curr_px   = er.current_price if (er and er.current_price) else pos.get("current_price", entry_px)
    qty       = pos.get("qty", 0)
    mode      = pos.get("mode", "Swing")

    pnl_pct   = ((curr_px - entry_px) / entry_px * 100) if entry_px else 0
    pnl_abs   = (curr_px - entry_px) * qty
    pnl_color = "#22aa55" if pnl_pct >= 0 else "#cc4444"
    v_color   = EXIT_COLORS.get(verdict, "#555577")
    bar_pct   = min(int(ex_score), 100)

    trail_html = "" if trail_sl is None else f"""
        <div>
          <div style="font-size:0.68rem;color:#888;margin-bottom:2px;">TRAIL SL</div>
          <div style="font-size:0.95rem;font-weight:600;color:#f59e0b;">₹{trail_sl:,.2f}</div>
        </div>"""

    trigger_html = "".join(
        f'<span class="pill" style="background:#2d2d40;border:1px solid #555;color:#ccc;">⚡ {t}</span>'
        for t in triggers
    ) if triggers else '<span style="font-size:0.72rem;color:#555;">No triggers fired</span>'

    st.markdown(f"""
    <div class="bull-card" style="
        background:#1e1e2e;
        border:1.5px solid {v_color};
        box-shadow:0 2px 12px {v_color}33;">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">
        <div>
          <span style="font-size:1.25rem;font-weight:700;color:#e8e8f0;">{sym}</span>
          <span style="font-size:0.75rem;color:#aaa;margin-left:8px;">
            {SECTOR_MAP.get(sym,'—')} · {mode}
          </span>
        </div>
        <span style="background:{v_color}22;border:1px solid {v_color};
                     border-radius:20px;padding:3px 14px;
                     font-size:0.78rem;font-weight:700;color:{v_color};letter-spacing:.5px;">
          {verdict}
        </span>
      </div>
      <div style="display:flex;gap:28px;flex-wrap:wrap;margin-bottom:10px;">
        <div>
          <div style="font-size:0.68rem;color:#888;margin-bottom:2px;">ENTRY</div>
          <div style="font-size:0.95rem;font-weight:600;color:#ccc;">₹{entry_px:,.2f}</div>
        </div>
        <div>
          <div style="font-size:0.68rem;color:#888;margin-bottom:2px;">CURRENT</div>
          <div style="font-size:0.95rem;font-weight:600;color:#e8e8f0;">₹{curr_px:,.2f}</div>
        </div>
        <div>
          <div style="font-size:0.68rem;color:#888;margin-bottom:2px;">QTY</div>
          <div style="font-size:0.95rem;font-weight:600;color:#ccc;">{qty}</div>
        </div>
        <div>
          <div style="font-size:0.68rem;color:#888;margin-bottom:2px;">P&L</div>
          <div style="font-size:0.95rem;font-weight:700;color:{pnl_color};">
            {'+' if pnl_pct>=0 else ''}{pnl_pct:.1f}% &nbsp;(₹{pnl_abs:+,.0f})
          </div>
        </div>
        {trail_html}
      </div>
      <div style="margin-bottom:8px;">
        <div style="display:flex;justify-content:space-between;margin-bottom:3px;">
          <span style="font-size:0.68rem;color:#888;">EXIT PRESSURE</span>
          <span style="font-size:0.68rem;font-weight:700;color:{v_color};">{bar_pct}/100</span>
        </div>
        <div class="score-bar-bg">
          <div style="width:{bar_pct}%;height:100%;
                      background:linear-gradient(90deg,{v_color}88,{v_color});
                      border-radius:6px;"></div>
        </div>
      </div>
      <div style="margin-top:6px;">{trigger_html}</div>
    </div>
    """, unsafe_allow_html=True)


def _render_short_card(sr: ShortResult):
    """Render one short-sell candidate card — same dark-theme card style."""
    verdict    = sr.verdict
    score      = sr.short_score
    v_color    = SHORT_COLORS.get(verdict, "#555577")
    bar_pct    = min(score, 100)
    rr_color   = "#22aa55" if sr.risk_reward >= 2.0 else ("#f59e0b" if sr.risk_reward >= 1.5 else "#cc4444")

    hard_html = "".join(
        f'<span class="pill" style="background:#3d1a1a;border:1px solid #cc2244;color:#ff8888;">🔴 {t}</span>'
        for t in sr.hard_triggers
    )
    soft_html = "".join(
        f'<span class="pill" style="background:#2d2d1a;border:1px solid #f59e0b;color:#ffd280;">🟡 {t}</span>'
        for t in sr.soft_triggers
    )
    trigger_html = (hard_html + soft_html) or \
        '<span style="font-size:0.72rem;color:#555;">No triggers</span>'

    rsi_color = "#cc4444" if sr.rsi_val > 70 else ("#f59e0b" if sr.rsi_val > 60 else "#888")

    st.markdown(f"""
    <div class="short-card" style="
        background:#1e1a1a;
        border:1.5px solid {v_color};
        box-shadow:0 2px 14px {v_color}44;">

      <!-- Header row -->
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">
        <div>
          <span style="font-size:1.25rem;font-weight:700;color:#f0e8e8;">{sr.symbol}</span>
          <span style="font-size:0.75rem;color:#aaa;margin-left:8px;">
            {sr.sector} · {sr.mode} · RS {sr.rs_rank}
          </span>
        </div>
        <div style="display:flex;gap:8px;align-items:center;">
          <span style="font-size:0.72rem;color:#aaa;">HTF: {sr.htf_trend}</span>
          <span style="background:{v_color}22;border:1px solid {v_color};
                       border-radius:20px;padding:3px 14px;
                       font-size:0.78rem;font-weight:700;color:{v_color};letter-spacing:.5px;">
            ▼ {verdict}
          </span>
        </div>
      </div>

      <!-- Price + levels row -->
      <div style="display:flex;gap:24px;flex-wrap:wrap;margin-bottom:10px;">
        <div>
          <div style="font-size:0.68rem;color:#888;margin-bottom:2px;">CURRENT</div>
          <div style="font-size:0.95rem;font-weight:600;color:#f0e8e8;">₹{sr.current_price:,.2f}</div>
        </div>
        <div>
          <div style="font-size:0.68rem;color:#888;margin-bottom:2px;">SHORT ZONE</div>
          <div style="font-size:0.95rem;font-weight:600;color:#ff8888;">
            ₹{sr.entry_zone_lo:,.2f} – ₹{sr.entry_zone_hi:,.2f}
          </div>
        </div>
        <div>
          <div style="font-size:0.68rem;color:#888;margin-bottom:2px;">STOP LOSS ▲</div>
          <div style="font-size:0.95rem;font-weight:600;color:#ff4466;">₹{sr.stop_loss:,.2f}</div>
        </div>
        <div>
          <div style="font-size:0.68rem;color:#888;margin-bottom:2px;">T1 / T2 / T3 ▼</div>
          <div style="font-size:0.90rem;font-weight:600;color:#22aa88;">
            ₹{sr.target1:,.2f} · ₹{sr.target2:,.2f} · ₹{sr.target3:,.2f}
          </div>
        </div>
        <div>
          <div style="font-size:0.68rem;color:#888;margin-bottom:2px;">R:R</div>
          <div style="font-size:0.95rem;font-weight:700;color:{rr_color};">
            1:{sr.risk_reward:.1f}
          </div>
        </div>
        <div>
          <div style="font-size:0.68rem;color:#888;margin-bottom:2px;">RSI</div>
          <div style="font-size:0.95rem;font-weight:600;color:{rsi_color};">{sr.rsi_val:.0f}</div>
        </div>
        <div>
          <div style="font-size:0.68rem;color:#888;margin-bottom:2px;">VOL ×</div>
          <div style="font-size:0.95rem;font-weight:600;color:#aaa;">{sr.volume_ratio:.1f}×</div>
        </div>
      </div>

      <!-- Short pressure bar -->
      <div style="margin-bottom:8px;">
        <div style="display:flex;justify-content:space-between;margin-bottom:3px;">
          <span style="font-size:0.68rem;color:#888;">SHORT PRESSURE</span>
          <span style="font-size:0.68rem;font-weight:700;color:{v_color};">{bar_pct}/100</span>
        </div>
        <div class="score-bar-bg">
          <div style="width:{bar_pct}%;height:100%;
                      background:linear-gradient(90deg,{v_color}88,{v_color});
                      border-radius:6px;"></div>
        </div>
      </div>

      <!-- Trigger pills -->
      <div style="margin-top:6px;">{trigger_html}</div>
    </div>
    """, unsafe_allow_html=True)


# ═══════════════════════════════════════════════════════════════════════════════
# STREAMLIT APP
# ═══════════════════════════════════════════════════════════════════════════════

st.set_page_config(
    page_title="BULL SUTRA Pro v13",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(CARD_CSS, unsafe_allow_html=True)
init_session()

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## ⚙️ Settings")
    mode = st.selectbox("Mode", list(MODE_CFG.keys()), index=1)
    universe_choice = st.selectbox("Universe", ["NIFTY 50", "NSE 500", "Custom"])
    if universe_choice == "NIFTY 50":
        symbols = NIFTY50
    elif universe_choice == "NSE 500":
        symbols = NSE500
    else:
        custom_raw = st.text_area("Symbols (comma-separated)")
        symbols = [s.strip().upper() for s in custom_raw.split(",") if s.strip()]

    st.markdown("---")
    st.markdown("### ➕ Add Position")
    ap_sym   = st.text_input("Symbol").upper()
    ap_entry = st.number_input("Entry Price", min_value=0.01, value=100.0, step=0.5)
    ap_qty   = st.number_input("Qty", min_value=1, value=100, step=1)
    if st.button("Add to Portfolio", use_container_width=True):
        if ap_sym:
            add_position(ap_sym, ap_entry, int(ap_qty), mode)
            st.success(f"Added {ap_sym}")

    st.markdown("---")
    vix_val, vix_label = fetch_vix()
    vix_color = {"CALM":"#22aa55","CAUTION":"#f59e0b","STRESS":"#cc4444","UNKNOWN":"#888"}.get(vix_label,"#888")
    st.markdown(
        f'<div style="background:#1e1e2e;border:1px solid {vix_color};border-radius:8px;'
        f'padding:8px 14px;text-align:center;">'
        f'<span style="color:#888;font-size:0.75rem;">INDIA VIX</span><br>'
        f'<span style="font-size:1.4rem;font-weight:700;color:{vix_color};">'
        f'{vix_val if vix_val else "—"}</span>&nbsp;'
        f'<span style="font-size:0.78rem;color:{vix_color};">{vix_label}</span></div>',
        unsafe_allow_html=True,
    )

    if st.session_state.get("_db_error"):
        st.error(f"DB: {st.session_state['_db_error']}")

# ── Tabs ──────────────────────────────────────────────────────────────────────
tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
    "🔍 Scan", "⚡ Entry List", "👁 Watch List",
    "📊 Dashboard", "📈 Signals", "💼 Portfolio",
])


# ─────────────────────────────────────────────────────────────────────────────
# TAB 1 — SCAN
# ─────────────────────────────────────────────────────────────────────────────
with tab1:
    st.markdown(f"## 🔍 Bull Scan — {mode} · {len(symbols)} symbols")

    if st.button("▶ Run Scan", use_container_width=True, type="primary"):
        status_txt  = st.empty()
        prog_bar    = st.progress(0.0)

        status_txt.text("Prefetching HTF data…")
        prog_bar.progress(0.05)
        htf_cache = prefetch_htf_parallel(symbols, mode, status_txt, prog_bar)

        status_txt.text("Computing RS ranks…")
        prog_bar.progress(0.45)
        raw_returns = {}
        def _quick_ret(sym):
            try:
                cfg = MODE_CFG[mode]
                df = yf.download(to_nse(sym), period=cfg["period"], interval=cfg["interval"],
                                 auto_adjust=True, progress=False, threads=False)
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.get_level_values(0)
                cl = df["Close"].dropna()
                return sym, _52w_return(cl)
            except Exception:
                return sym, 0.0

        with concurrent.futures.ThreadPoolExecutor(max_workers=32) as pool:
            for sym, ret in pool.map(_quick_ret, symbols):
                raw_returns[sym] = ret

        rs_ranks = compute_rs_ranks(raw_returns)

        status_txt.text("Scoring bulls…")
        results = run_scan(symbols, mode, htf_cache, rs_ranks, vix_val, status_txt, prog_bar)
        st.session_state["scan_results"] = results
        prog_bar.progress(1.0)
        status_txt.text(f"Done — {len(results)} stocks scored.")

    if st.session_state["scan_results"]:
        results = st.session_state["scan_results"]
        df_out = pd.DataFrame([{
            "Symbol":  r.symbol,
            "Score":   r.norm_score,
            "Action":  r.action,
            "Phase":   r.phase,
            "RSI":     r.rsi_val,
            "RS Rank": r.rs_rank,
            "HTF":     r.htf_trend,
            "R:R":     r.risk_reward,
            "Liq Cr":  r.liquidity_cr,
            "Sector":  r.sector,
        } for r in results if not r.error])
        st.dataframe(df_out, use_container_width=True, hide_index=True)


# ─────────────────────────────────────────────────────────────────────────────
# TAB 2 — ENTRY LIST
# ─────────────────────────────────────────────────────────────────────────────
with tab2:
    st.markdown("## ⚡ Entry List")
    results = st.session_state.get("scan_results", [])
    entry_results = [r for r in results if r.action in ("STRONG BUY", "BUY") and not r.error]

    if not entry_results:
        st.info("Run a scan first to populate the entry list.")
    else:
        st.markdown(f"**{len(entry_results)} stocks ready for entry**")
        for r in entry_results:
            action_color = "#00dd88" if r.action == "STRONG BUY" else "#2255cc"
            phase_color  = PHASE_COLORS.get(r.phase, "#555577")
            score_pct    = int(r.norm_score)
            st.markdown(f"""
            <div class="bull-card" style="background:#1e1e2e;border:1.5px solid {action_color};
                                          box-shadow:0 2px 12px {action_color}33;">
              <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">
                <div>
                  <span style="font-size:1.25rem;font-weight:700;color:#e8e8f0;">{r.symbol}</span>
                  <span style="font-size:0.75rem;color:#aaa;margin-left:8px;">{r.sector} · {r.mode}</span>
                </div>
                <div style="display:flex;gap:8px;">
                  <span style="background:{phase_color}22;border:1px solid {phase_color};
                               border-radius:20px;padding:2px 10px;
                               font-size:0.72rem;color:{phase_color};">{r.phase} {r.phase_arrow}</span>
                  <span style="background:{action_color}22;border:1px solid {action_color};
                               border-radius:20px;padding:2px 12px;
                               font-size:0.78rem;font-weight:700;color:{action_color};">{r.action}</span>
                </div>
              </div>
              <div style="display:flex;gap:24px;flex-wrap:wrap;margin-bottom:10px;">
                <div><div style="font-size:0.68rem;color:#888;">CURRENT</div>
                     <div style="font-size:0.95rem;font-weight:600;color:#e8e8f0;">₹{r.current_price:,.2f}</div></div>
                <div><div style="font-size:0.68rem;color:#888;">ENTRY ZONE</div>
                     <div style="font-size:0.95rem;font-weight:600;color:#aef;">₹{r.entry_low:,.2f}–₹{r.entry_high:,.2f}</div></div>
                <div><div style="font-size:0.68rem;color:#888;">STOP</div>
                     <div style="font-size:0.95rem;font-weight:600;color:#f88;">₹{r.stop_loss:,.2f}</div></div>
                <div><div style="font-size:0.68rem;color:#888;">T1 / T2 / T3</div>
                     <div style="font-size:0.90rem;font-weight:600;color:#22aa88;">
                       ₹{r.target1:,.2f} · ₹{r.target2:,.2f} · ₹{r.target3:,.2f}</div></div>
                <div><div style="font-size:0.68rem;color:#888;">R:R</div>
                     <div style="font-size:0.95rem;font-weight:700;color:{'#22aa55' if r.risk_reward>=2 else '#f59e0b'};">
                       1:{r.risk_reward:.1f}</div></div>
                <div><div style="font-size:0.68rem;color:#888;">RSI</div>
                     <div style="font-size:0.95rem;color:#aaa;">{r.rsi_val:.0f}</div></div>
                <div><div style="font-size:0.68rem;color:#888;">RS Rank</div>
                     <div style="font-size:0.95rem;color:#aaa;">{r.rs_rank}</div></div>
                <div><div style="font-size:0.68rem;color:#888;">HTF</div>
                     <div style="font-size:0.95rem;color:#aaa;">{r.htf_trend}</div></div>
              </div>
              <div>
                <div style="display:flex;justify-content:space-between;margin-bottom:3px;">
                  <span style="font-size:0.68rem;color:#888;">BULL SCORE</span>
                  <span style="font-size:0.68rem;font-weight:700;color:{action_color};">{score_pct}/100</span>
                </div>
                <div class="score-bar-bg">
                  <div style="width:{score_pct}%;height:100%;
                              background:linear-gradient(90deg,{action_color}88,{action_color});
                              border-radius:6px;"></div>
                </div>
              </div>
            </div>
            """, unsafe_allow_html=True)

            c1, c2 = st.columns([4, 1])
            with c2:
                if st.button("➕ Add to Portfolio", key=f"add_{r.symbol}"):
                    add_position(r.symbol, r.current_price, 100, mode)
                    st.success(f"Added {r.symbol}")


# ─────────────────────────────────────────────────────────────────────────────
# TAB 3 — WATCH LIST
# ─────────────────────────────────────────────────────────────────────────────
with tab3:
    st.markdown("## 👁 Watch List")
    results = st.session_state.get("scan_results", [])
    watch_results = [r for r in results if r.action == "WATCH" and not r.error]

    if not watch_results:
        st.info("Run a scan first to populate the watch list.")
    else:
        st.markdown(f"**{len(watch_results)} stocks on watch**")
        for r in watch_results:
            phase_color = PHASE_COLORS.get(r.phase, "#555577")
            score_pct   = int(r.norm_score)
            st.markdown(f"""
            <div class="bull-card" style="background:#1a1a28;border:1.5px solid #b87333;
                                          box-shadow:0 2px 10px #b8733333;">
              <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">
                <div>
                  <span style="font-size:1.2rem;font-weight:700;color:#e8e8f0;">{r.symbol}</span>
                  <span style="font-size:0.75rem;color:#aaa;margin-left:8px;">{r.sector} · {r.mode}</span>
                </div>
                <span style="background:{phase_color}22;border:1px solid {phase_color};
                             border-radius:20px;padding:2px 10px;
                             font-size:0.72rem;color:{phase_color};">{r.phase} {r.phase_arrow}</span>
              </div>
              <div style="display:flex;gap:24px;flex-wrap:wrap;margin-bottom:10px;">
                <div><div style="font-size:0.68rem;color:#888;">CURRENT</div>
                     <div style="font-size:0.95rem;font-weight:600;color:#e8e8f0;">₹{r.current_price:,.2f}</div></div>
                <div><div style="font-size:0.68rem;color:#888;">STOP</div>
                     <div style="font-size:0.95rem;color:#f88;">₹{r.stop_loss:,.2f}</div></div>
                <div><div style="font-size:0.68rem;color:#888;">T2 TARGET</div>
                     <div style="font-size:0.95rem;color:#22aa88;">₹{r.target2:,.2f}</div></div>
                <div><div style="font-size:0.68rem;color:#888;">RSI</div>
                     <div style="font-size:0.95rem;color:#aaa;">{r.rsi_val:.0f}</div></div>
                <div><div style="font-size:0.68rem;color:#888;">RS Rank</div>
                     <div style="font-size:0.95rem;color:#aaa;">{r.rs_rank}</div></div>
                <div><div style="font-size:0.68rem;color:#888;">HTF</div>
                     <div style="font-size:0.95rem;color:#aaa;">{r.htf_trend}</div></div>
              </div>
              <div>
                <div style="display:flex;justify-content:space-between;margin-bottom:3px;">
                  <span style="font-size:0.68rem;color:#888;">BULL SCORE</span>
                  <span style="font-size:0.68rem;font-weight:700;color:#b87333;">{score_pct}/100</span>
                </div>
                <div class="score-bar-bg">
                  <div style="width:{score_pct}%;height:100%;
                              background:linear-gradient(90deg,#b8733388,#b87333);
                              border-radius:6px;"></div>
                </div>
              </div>
            </div>
            """, unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────────────────
# TAB 4 — DASHBOARD
# ─────────────────────────────────────────────────────────────────────────────
with tab4:
    st.markdown("## 📊 Dashboard")
    results = st.session_state.get("scan_results", [])
    if not results:
        st.info("Run a scan to see dashboard stats.")
    else:
        valid = [r for r in results if not r.error]
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("Scanned",    len(valid))
        c2.metric("Strong Buy", sum(1 for r in valid if r.action == "STRONG BUY"))
        c3.metric("Buy",        sum(1 for r in valid if r.action == "BUY"))
        c4.metric("Watch",      sum(1 for r in valid if r.action == "WATCH"))
        c5.metric("Skip",       sum(1 for r in valid if r.action == "SKIP"))

        st.divider()

        # phase distribution
        phase_counts = {}
        for r in valid:
            phase_counts[r.phase] = phase_counts.get(r.phase, 0) + 1
        st.markdown("**Phase Distribution**")
        for ph, cnt in sorted(phase_counts.items(), key=lambda x: -x[1]):
            pct = cnt / len(valid) * 100
            col = PHASE_COLORS.get(ph, "#555")
            st.markdown(
                f'<div style="display:flex;align-items:center;gap:10px;margin-bottom:4px;">'
                f'<span style="width:90px;font-size:0.8rem;color:{col};">{ph}</span>'
                f'<div style="flex:1;background:#2d2d40;border-radius:4px;height:12px;">'
                f'<div style="width:{pct:.0f}%;height:100%;background:{col};border-radius:4px;"></div></div>'
                f'<span style="width:40px;text-align:right;font-size:0.8rem;color:#aaa;">{cnt}</span>'
                f'</div>',
                unsafe_allow_html=True,
            )

        st.divider()

        # sector breakdown
        st.markdown("**Top Sectors (avg score)**")
        sector_scores: dict = {}
        for r in valid:
            sector_scores.setdefault(r.sector, []).append(r.norm_score)
        sector_avg = {s: round(sum(v)/len(v), 1) for s, v in sector_scores.items()}
        for sec, avg in sorted(sector_avg.items(), key=lambda x: -x[1])[:8]:
            st.markdown(f"- **{sec}**: {avg}")


# ─────────────────────────────────────────────────────────────────────────────
# TAB 5 — SIGNALS
# ─────────────────────────────────────────────────────────────────────────────
with tab5:
    st.markdown("## 📈 Signals Log")
    results = st.session_state.get("scan_results", [])
    actionable = [r for r in results if r.action in ("STRONG BUY", "BUY") and not r.error]
    if not actionable:
        st.info("No actionable signals yet — run a scan.")
    else:
        for r in actionable:
            age_str, stale = signal_age_label(r.scored_at, mode)
            stale_badge = "🔴 STALE" if stale else "🟢 FRESH"
            st.markdown(
                f"**{r.symbol}** · {r.action} · Score {r.norm_score:.0f} · "
                f"{age_str} · {stale_badge} · Phase {r.phase}"
            )


# ─────────────────────────────────────────────────────────────────────────────
# TAB 6 — 💼 PORTFOLIO  (open positions + ready-to-short)
# ─────────────────────────────────────────────────────────────────────────────
with tab6:
    st.markdown("## 💼 Portfolio")

    # ── Sub-tabs inside Portfolio ──────────────────────────────────────────
    ptab1, ptab2 = st.tabs(["📂 Open Positions", "🔻 Ready to Short"])

    # ══════════════════════════════════════════════════════════════════════
    # PTAB 1 — OPEN POSITIONS
    # ══════════════════════════════════════════════════════════════════════
    with ptab1:
        st.markdown("### 📂 Open Positions & Exit Signals")
        positions = st.session_state.get("open_positions", [])

        if not positions:
            st.info("No open positions. Add a position from the sidebar or Entry List.")
        else:
            col_refresh, col_space = st.columns([1, 4])
            with col_refresh:
                if st.button("🔄 Refresh Exit Signals", use_container_width=True):
                    with st.spinner("Scanning exits…"):
                        st.session_state["exit_results"] = run_exit_scan(positions, vix_val)

            exit_results = st.session_state.get("exit_results", {})

            # ── Summary strip ────────────────────────────────────────────
            counts = {EXIT_HOLD: 0, EXIT_WATCH: 0, EXIT_SIGNAL: 0, EXIT_CONFIRMED: 0}
            for p in positions:
              if not isinstance(p, dict):
                  continue
          
              sym = p.get("symbol")
              if not sym:
                  continue
          
              er  = exit_results.get(sym)
              lbl = er.verdict if er else EXIT_HOLD
              counts[lbl] = counts.get(lbl, 0) + 1

            col_h, col_w, col_s, col_e = st.columns(4)
            col_h.metric("🟢 Hold",        counts[EXIT_HOLD])
            col_w.metric("🟡 Watch",       counts[EXIT_WATCH])
            col_s.metric("🟠 Exit Signal", counts[EXIT_SIGNAL])
            col_e.metric("🔴 Exit Now",    counts[EXIT_CONFIRMED])
            st.divider()

            # sort by urgency
            _exit_order = {
                EXIT_CONFIRMED: 0,
                EXIT_SIGNAL: 1,
                EXIT_WATCH: 2,
                EXIT_HOLD: 3
            }
            
            valid_positions = [
                p for p in positions
                if isinstance(p, dict) and p.get("symbol")
            ]
            
            positions_sorted = sorted(
                valid_positions,
                key=lambda p: _exit_order.get(
                    exit_results[p["symbol"]].verdict
                    if p["symbol"] in exit_results else EXIT_HOLD,
                    3
                )
            )
            
            for pos in positions_sorted:
                sym = pos.get("symbol")
                if not sym:
                    continue
            
                er = exit_results.get(sym)
                _render_exit_card(pos, er)
            
                verdict = er.verdict if er else EXIT_HOLD
            
                c1, c2, c3 = st.columns([2, 2, 1])
            
                with c1:
                    if verdict == EXIT_CONFIRMED:
                        st.error("⚠️ Consider full exit or tight stop")
                    elif verdict == EXIT_SIGNAL:
                        st.warning("🔶 Consider 50% exit to lock gains")
                    elif verdict == EXIT_WATCH:
                        st.info("👁 Monitor closely — tighten stop")
            
                with c3:
                    if st.button("🗑 Remove", key=f"rm_{sym}_{pos.get('entry_date','')}"):
                        st.session_state["open_positions"] = [
                            p for p in st.session_state["open_positions"]
                            if not (
                                p.get("symbol") == sym
                                and p.get("entry_date") == pos.get("entry_date")
                            )
                        ]
                        _save_positions()
                        st.rerun()

    # ══════════════════════════════════════════════════════════════════════
    # PTAB 2 — READY TO SHORT
    # ══════════════════════════════════════════════════════════════════════
    with ptab2:
        st.markdown("### 🔻 Ready to Short — Short-Sell Candidates")

        # ── Controls row ──────────────────────────────────────────────
        c_uni, c_mode, c_run = st.columns([2, 2, 1])
        with c_uni:
            short_universe = st.selectbox(
                "Scan universe",
                ["NIFTY 50", "NSE 500", "Custom", "My Watchlist"],
                key="short_uni",
            )
        with c_mode:
            short_mode = st.selectbox("Mode", list(MODE_CFG.keys()), index=1, key="short_mode")
        with c_run:
            st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
            run_short = st.button("🔻 Scan Shorts", use_container_width=True, type="primary")

        # custom input
        if short_universe == "Custom":
            raw = st.text_area("Symbols (comma-separated)", key="short_custom")
            short_syms = [s.strip().upper() for s in raw.split(",") if s.strip()]
        elif short_universe == "My Watchlist":
            short_syms = list({p["symbol"] for p in st.session_state.get("open_positions", [])})
            if not short_syms:
                st.warning("No positions in portfolio — add some or choose another universe.")
        elif short_universe == "NIFTY 50":
            short_syms = NIFTY50
        else:
            short_syms = NSE500

        # ── Filters ──────────────────────────────────────────────────
        with st.expander("⚙️ Filters", expanded=False):
            fc1, fc2, fc3 = st.columns(3)
            min_score  = fc1.slider("Min Short Score", 0, 100, SHORT_SCORE_WATCH, 5, key="sh_min_score")
            max_rr     = fc2.slider("Min R:R", 0.5, 5.0, 1.5, 0.25, key="sh_min_rr")
            show_verdicts = fc3.multiselect(
                "Show verdicts",
                [SHORT_WATCH, SHORT_SIGNAL, SHORT_CONFIRMED],
                default=[SHORT_SIGNAL, SHORT_CONFIRMED],
                key="sh_verdicts",
            )

        if run_short and short_syms:
            s_status = st.empty()
            s_prog   = st.progress(0.0)
            s_status.text("Prefetching HTF for short scan…")

            htf_cache_s = prefetch_htf_parallel(short_syms, short_mode, s_status, s_prog)

            s_status.text("Computing RS ranks…")
            raw_ret_s = {}
            def _q_ret(sym):
                try:
                    cfg = MODE_CFG[short_mode]
                    df = yf.download(to_nse(sym), period=cfg["period"], interval=cfg["interval"],
                                     auto_adjust=True, progress=False, threads=False)
                    if isinstance(df.columns, pd.MultiIndex):
                        df.columns = df.columns.get_level_values(0)
                    cl = df["Close"].dropna()
                    return sym, _52w_return(cl)
                except Exception:
                    return sym, 0.0
            with concurrent.futures.ThreadPoolExecutor(max_workers=32) as pool:
                for sym, ret in pool.map(_q_ret, short_syms):
                    raw_ret_s[sym] = ret
            rs_ranks_s = compute_rs_ranks(raw_ret_s)

            s_status.text("Scoring short candidates…")
            short_res = run_short_scan(
                short_syms, short_mode, htf_cache_s, rs_ranks_s, vix_val, s_status, s_prog
            )
            st.session_state["short_results"] = short_res
            s_prog.progress(1.0)
            s_status.text(f"Done — {len(short_res)} short candidates found.")

        short_results: list[ShortResult] = st.session_state.get("short_results", [])

        if not short_results:
            st.info("Click **🔻 Scan Shorts** to find short-sell candidates.")
        else:
            # apply filters
            filtered = [
                r for r in short_results
                if r.short_score >= min_score
                and r.risk_reward >= max_rr
                and r.verdict in (show_verdicts or [SHORT_WATCH, SHORT_SIGNAL, SHORT_CONFIRMED])
            ]

            # ── Summary strip ──────────────────────────────────────────
            s_counts = {SHORT_WATCH: 0, SHORT_SIGNAL: 0, SHORT_CONFIRMED: 0}
            for r in short_results:
                s_counts[r.verdict] = s_counts.get(r.verdict, 0) + 1

            sc1, sc2, sc3, sc4 = st.columns(4)
            sc1.metric("Total candidates", len(short_results))
            sc2.metric("🟡 Short Watch",   s_counts[SHORT_WATCH])
            sc3.metric("🟠 Short Signal",  s_counts[SHORT_SIGNAL])
            sc4.metric("🔴 Short Now",     s_counts[SHORT_CONFIRMED])
            st.divider()

            if not filtered:
                st.warning("No candidates match current filters — try lowering the thresholds.")
            else:
                st.markdown(f"**{len(filtered)} candidates after filters** — sorted by short pressure ↓")

                # VIX note for short traders
                if vix_val and vix_val >= VIX_STRESS:
                    st.error(
                        f"⚡ VIX {vix_val} — STRESS market. Shorts have higher success probability "
                        f"but use tight stops; gaps against short can be severe."
                    )
                elif vix_val and vix_val >= VIX_CAUTION:
                    st.warning(f"⚠️ VIX {vix_val} — CAUTION. Short selectively; prefer confirmed signals only.")

                for sr in filtered:
                    _render_short_card(sr)

                    # Action buttons per card
                    bc1, bc2, bc3 = st.columns([3, 2, 1])
                    with bc1:
                        if sr.verdict == SHORT_CONFIRMED:
                            st.error(f"⚠️ High-conviction short. SL strictly at ₹{sr.stop_loss:,.2f}")
                        elif sr.verdict == SHORT_SIGNAL:
                            st.warning(f"🔶 Enter short on bounce to ₹{sr.entry_zone_hi:,.2f}")
                        else:
                            st.info("👁 Wait for entry zone — don't chase breakdown")
                    with bc2:
                        st.caption(
                            f"Hard: {len(sr.hard_triggers)} · Soft: {len(sr.soft_triggers)} · "
                            f"Phase: {sr.phase} · ATR ₹{sr.atr:,.1f}"
                        )
                    with bc3:
                        if st.button("📌 Save", key=f"save_short_{sr.symbol}_{sr.scanned_at}"):
                            wl = st.session_state.get("short_watchlist", [])
                            entry = dict(
                                symbol      = sr.symbol,
                                verdict     = sr.verdict,
                                short_score = sr.short_score,
                                entry_hi    = sr.entry_zone_hi,
                                stop_loss   = sr.stop_loss,
                                target2     = sr.target2,
                                mode        = sr.mode,
                                saved_at    = datetime.now().isoformat(),
                            )
                            wl = [w for w in wl if w["symbol"] != sr.symbol] + [entry]
                            st.session_state["short_watchlist"] = wl
                            _save_short_watchlist()
                            st.success(f"Saved {sr.symbol} to short watchlist")

            # ── Saved short watchlist ──────────────────────────────────
            saved_shorts = st.session_state.get("short_watchlist", [])
            if saved_shorts:
                st.divider()
                st.markdown("#### 📌 Saved Short Watchlist")
                for sw in saved_shorts:
                    age_str, _ = signal_age_label(sw.get("saved_at", datetime.now().isoformat()), sw.get("mode", "Swing"))
                    vc = SHORT_COLORS.get(sw.get("verdict", SHORT_WATCH), "#888")
                    c1, c2, c3 = st.columns([3, 3, 1])
                    c1.markdown(
                        f'<span style="color:{vc};font-weight:700;">{sw["symbol"]}</span>'
                        f' <span style="color:#888;font-size:0.75rem;">· {sw.get("verdict","")} · saved {age_str}</span>',
                        unsafe_allow_html=True,
                    )
                    c2.caption(
                        f'Short zone ~₹{sw.get("entry_hi",0):,.2f} · '
                        f'SL ₹{sw.get("stop_loss",0):,.2f} · '
                        f'T2 ₹{sw.get("target2",0):,.2f}'
                    )
                    with c3:
                        if st.button("🗑", key=f"del_sw_{sw['symbol']}"):
                            st.session_state["short_watchlist"] = [
                                w for w in st.session_state["short_watchlist"]
                                if w["symbol"] != sw["symbol"]
                            ]
                            _save_short_watchlist()
                            st.rerun()
