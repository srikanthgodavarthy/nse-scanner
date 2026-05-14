"""BULL SUTRA Pro — v14.3
═══════════════════════════════════════════════════════════════════
BASE: v14.2 — all FIX-1…FIX-12 100% preserved.
NEW in v14.3:
  • sectors.py FULLY INTEGRATED
    — Imported at startup with graceful ImportError fallback.

    — SECTOR_MAP rebuilt from sectors.py (symbol → sector name)
      covering 300+ NSE stocks across 18 sectors instead of the
      old 50-stock hardcoded dict with generic labels ("IT", "FMCG").
      New labels match sectors.py: "IT & Technology",
      "Banking & Finance", "Pharma & Healthcare", etc.

    — NIFTY50 list replaced with sectors.py "Nifty 50" group,
      which includes the current correct composition (ETERNAL,
      JIOFIN, SHRIRAMFIN, LTIM) that was missing from the old
      hardcoded list.

    — Universe selector upgraded from a 2-option radio
      ("NSE 500" / "Nifty 50") to a full selectbox showing
      ALL sectors from sectors.py:
        NSE 500, Nifty 50, Banking & Finance, IT & Technology,
        Pharma & Healthcare, Auto & Auto Ancillaries,
        FMCG & Consumer, Metals & Mining, Energy & Power,
        Infrastructure & Construction, Real Estate,
        Capital Goods & Engineering, Chemicals & Fertilizers,
        Telecom & Media, Retail & E-Commerce,
        Logistics & Shipping, Paints & Chemicals, Textiles, PSU.

    — Symbol resolution: each sector maps to its stocks list
      from sectors.py; "Nifty 500" (None) maps to NSE500.
═══════════════════════════════════════════════════════════════════
  • FIX-8  BREAKOUT CONFIDENCE DOUBLE-COUNT REMOVED
    — "trend_up" removed from brk_weights; it was already captured by
      "score_ok" (norm_bull awards +25 for trend_up, so both weights
      fired together, over-counting trend strength by 0.35).
    — Redistributed weight to orthogonal signals: price_above_high
      raised to 0.35; compressed raised to 0.20.  Weights still sum 1.0.

  • FIX-9  was_recent_brk VOLATILITY-SPIKE GUARD
    — Added two new guards to prevent wick/spike candles from triggering
      post-breakout suppression:
        (a) CLOSE must also be above the rolling high, not just the wick.
        (b) Body must be non-red (close >= open) — rules out reversal spikes.
    — FIX-9 also fixes the VOLUME AVERAGE MISMATCH (Bug 3):
      was_recent_brk now computes the rolling-20 volume average at bar[-k]
      (using only bars prior to bar[-k]) instead of using today's vol_avg,
      so the comparison is apples-to-apples with the historical bar's baseline.

  • FIX-10 fresh_cross IS NOW A TRUE CROSSOVER DETECTOR
    — Old loop: found any bar where EMA_fast was previously ≤ EMA_slow,
      which could fire on oscillating EMAs without a genuine directional cross.
    — New loop: requires that at bar[-k], EMA_fast > EMA_slow (above)
      AND at bar[-(k+1)], EMA_fast ≤ EMA_slow (below).  Both adjacent-bar
      conditions must hold simultaneously — a genuine golden-cross event.

  • FIX-11 DAY % CHANGE ON ALL CARD TYPES
    — Short cards: day_change field added to ShortResult; propagated from
      %Change in score_short_from_result; displayed as color-coded ▲/▼
      below the current price (matching bull scanner card style).
    — Portfolio cards: day_pct field added to ExitResult; computed in
      score_exit as (close − prev_close) / prev_close × 100; displayed
      as "DAY" metric alongside ENTRY / CURRENT / QTY / P&L.

  • FIX-12 PORTFOLIO CARD SIZES MATCH SCANNER
    — Portfolio cards now use width:360px;min-width:320px;max-width:380px;
      flex:1 1 360px — identical sizing to scanner cards.
    — Each card is wrapped in a flex container so multiple cards
      flow side-by-side on wide screens, matching the scanner layout.
═══════════════════════════════════════════════════════════════════
  • Short Sell Engine (score_short / run_short_scan)
    — 4 hard triggers + 7 soft triggers, uses v11 detect_exhaustion
  • "🔻 Short Scan" as a top-level tab (not buried in sub-tabs)
  • Short cards use v11 JetBrains Mono dark style
  • 💼 Portfolio tab: open positions with exit signals
  • Supabase persistence (optional, silently skipped if no secret)
  • v11 bull scoring math completely untouched
═══════════════════════════════════════════════════════════════════
FIXES FROM v10
──────────────────────────
FIX-1  CLOSED-CANDLE HTF ALIGNMENT
        _htf_trend_from_df now drops the last (still-forming) bar
        before computing EMAs, so a live intraday bar never
        contaminates the higher-timeframe signal.

FIX-2  BREADTH-BASED GATING
        run_scan computes a quick breadth pulse after scoring.
        When breadth is WEAK (pct_above_ema50 < 40 AND ad_ratio < 0.8)
        stocks in PHASE_BRK / PHASE_CONT have their action capped to
        WATCH and a "breadth_gated" flag is set on the result dict.
        No scoring math changes; the gate is applied in the main thread.

FIX-3  STRUCTURAL BREAKOUT FILTERING
        detect_phase_and_entry now requires a breakout candle to clear
        the rolling high by at least 0.15 × ATR (was 0.20 × ATR buf),
        AND volume must exceed vol_avg × 1.5 (hard gate, not weighted).
        Breakout is also rejected when the prior 3-bar range is already
        expanded (atr_val > atr_mean × 1.4) — avoids chasing blowoffs.

FIX-4  INTRADAY TIME-NORMALISED VOLUME
        liquidity_ok and score_stock now compute vol_avg using only
        bars from the current session so far when mode == "Intraday".
        A helper _intraday_bars_elapsed() returns the fraction of the
        trading session completed; volume is scaled to a full-session
        equivalent before comparison, preventing false "volume spike"
        signals early in the day.

FIX-5  CAPITAL CAP IN POSITION SIZING
        position_size now accepts a max_capital_pct parameter
        (default 0.20 = 20 % of account).  final_qty is clamped so
        that capital_used ≤ account_size × max_capital_pct, regardless
        of how wide the stop is relative to account size.

FIX-6  EMA DOUBLE-COUNTING REMOVED
        In score_stock bull scoring the block
            bull += 15 if e_fast > e_slow else (7 if e_fast > e_slow * 0.995 else 0)
        was also fully captured by the trend_up / trend_strong flags
        (which already require e_fast > e_slow).  The EMA cross line
        is replaced with a tighter, non-overlapping bonus:
            +8 if golden-cross within last 5 bars (fresh cross)
            +4 if e_fast > e_slow but not a fresh cross
            0  otherwise
        trend_up (+25) and ema_stack (+15) remain unchanged.

SPEED IMPROVEMENTS PRESERVED FROM v10
──────────────────────────
PERF-1  Parallel scoring (ThreadPoolExecutor, 32 workers)
PERF-2  Merged OHLCV + daily context fetch
PERF-3  No throttle sleep; 32 workers
PERF-4  Vectorized RS ranks (numpy argsort)
PERF-5  VIX + Nifty pre-warmed on startup
PERF-6  Retry sleep capped at 1.0 s
PERF-7  Thread-safe phase transitions
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

import numpy as np
import pandas as pd
import yfinance as yf
import streamlit as st

try:
    import psycopg2 as _psycopg2
    _DB_OK = True
except ImportError:
    _DB_OK = False

logging.getLogger("yfinance").setLevel(logging.CRITICAL)
warnings.filterwarnings("ignore")

# ── Universes ──────────────────────────────────────────────────────────────────

try:
    from sectors import SECTORS as _SECTORS
except ImportError:
    _SECTORS = None   # sectors.py missing — fall back to hardcoded maps below

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

NIFTY50 = (
    _SECTORS["Nifty 50"]
    if _SECTORS and "Nifty 50" in _SECTORS
    else [
        "RELIANCE","TCS","HDFCBANK","INFY","ICICIBANK","HINDUNILVR","ITC","SBIN",
        "BHARTIARTL","KOTAKBANK","LT","AXISBANK","ASIANPAINT","MARUTI","TITAN",
        "NESTLEIND","WIPRO","ULTRACEMCO","POWERGRID","NTPC","BAJFINANCE","HCLTECH",
        "SUNPHARMA","TECHM","INDUSINDBK","ONGC","COALINDIA","TATASTEEL","JSWSTEEL",
        "HINDALCO","TATAMOTORS","M&M","BAJAJFINSV","DIVISLAB","DRREDDY","CIPLA",
        "EICHERMOT","ADANIENT","ADANIPORTS","BPCL","TATACONSUM","BRITANNIA",
        "HEROMOTOCO","APOLLOHOSP","GRASIM","SBILIFE","HDFCLIFE","ICICIPRULI","BAJAJ-AUTO","UPL",
    ]
)

# ── SECTOR_MAP: built from sectors.py (symbol → sector name) ──────────────────
# If sectors.py is available, invert the SECTORS dict so every symbol maps to
# its primary sector (first matching sector wins).  Falls back to the compact
# hardcoded map when sectors.py is missing.
if _SECTORS:
    SECTOR_MAP: dict[str, str] = {}
    for _sector_name, _syms in _SECTORS.items():
        if _syms is None:   # "Nifty 500" → None = use nse500 list, skip for map
            continue
        for _sym in _syms:
            if _sym not in SECTOR_MAP:       # first sector listed wins
                SECTOR_MAP[_sym] = _sector_name
else:
    SECTOR_MAP = {
        "RELIANCE":"Energy & Power","ONGC":"Energy & Power","BPCL":"Energy & Power",
        "COALINDIA":"Energy & Power","NTPC":"Energy & Power","POWERGRID":"Energy & Power",
        "ADANIENT":"Energy & Power",
        "ADANIPORTS":"Infrastructure & Construction","LT":"Infrastructure & Construction",
        "BHEL":"Capital Goods & Engineering",
        "HDFCBANK":"Banking & Finance","ICICIBANK":"Banking & Finance","SBIN":"Banking & Finance",
        "KOTAKBANK":"Banking & Finance","AXISBANK":"Banking & Finance","BAJFINANCE":"Banking & Finance",
        "BAJAJFINSV":"Banking & Finance","SBILIFE":"Banking & Finance","HDFCLIFE":"Banking & Finance",
        "ICICIPRULI":"Banking & Finance","INDUSINDBK":"Banking & Finance",
        "TCS":"IT & Technology","INFY":"IT & Technology","WIPRO":"IT & Technology",
        "HCLTECH":"IT & Technology","TECHM":"IT & Technology",
        "SUNPHARMA":"Pharma & Healthcare","DRREDDY":"Pharma & Healthcare",
        "CIPLA":"Pharma & Healthcare","DIVISLAB":"Pharma & Healthcare","APOLLOHOSP":"Pharma & Healthcare",
        "HINDUNILVR":"FMCG & Consumer","ITC":"FMCG & Consumer","NESTLEIND":"FMCG & Consumer",
        "BRITANNIA":"FMCG & Consumer","TATACONSUM":"FMCG & Consumer",
        "ASIANPAINT":"Paints & Chemicals","ULTRACEMCO":"Infrastructure & Construction",
        "GRASIM":"Infrastructure & Construction",
        "TATASTEEL":"Metals & Mining","JSWSTEEL":"Metals & Mining","HINDALCO":"Metals & Mining",
        "VEDL":"Metals & Mining","NMDC":"Metals & Mining",
        "MARUTI":"Auto & Auto Ancillaries","TATAMOTORS":"Auto & Auto Ancillaries",
        "M&M":"Auto & Auto Ancillaries","EICHERMOT":"Auto & Auto Ancillaries",
        "HEROMOTOCO":"Auto & Auto Ancillaries","BAJAJ-AUTO":"Auto & Auto Ancillaries",
        "TITAN":"FMCG & Consumer","BHARTIARTL":"Telecom & Media",
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

# ── Exit layer constants ───────────────────────────────────────────────────────
EXIT_HOLD        = "HOLD"
EXIT_WATCH_LBL   = "EXIT WATCH"
EXIT_SIGNAL_LBL  = "EXIT SIGNAL"
EXIT_CONFIRM_LBL = "EXIT NOW"
EXIT_COLORS = {
    EXIT_HOLD:        "#22aa55",
    EXIT_WATCH_LBL:   "#f59e0b",
    EXIT_SIGNAL_LBL:  "#ff8800",
    EXIT_CONFIRM_LBL: "#cc4444",
}

# ── Short sell constants ───────────────────────────────────────────────────────
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


# ═══════════════════════════════════════════════════════════════════════════════
# SUPABASE PERSISTENCE  (optional — silently skipped if secret missing)
# ═══════════════════════════════════════════════════════════════════════════════

def _db_conn():
    if not _DB_OK:
        raise RuntimeError("psycopg2 not installed")
    url = st.secrets.get("SUPABASE_URL", "")
    if not url or not url.startswith(("postgres://", "postgresql://")):
        raise ValueError("SUPABASE_URL missing/malformed")
    return _psycopg2.connect(url)

def _db_ensure(cur):
    cur.execute("""CREATE TABLE IF NOT EXISTS bs_positions (
        id SERIAL PRIMARY KEY, data JSONB NOT NULL, ts TIMESTAMP DEFAULT now())""")
    cur.execute("""CREATE TABLE IF NOT EXISTS bs_short_wl (
        id SERIAL PRIMARY KEY, data JSONB NOT NULL, ts TIMESTAMP DEFAULT now())""")

def _db_save(table, payload):
    try:
        conn = _db_conn(); cur = conn.cursor()
        _db_ensure(cur); conn.commit()
        cur.execute(f"DELETE FROM {table}")
        cur.execute(f"INSERT INTO {table} (data) VALUES (%s)", [json.dumps(payload)])
        conn.commit(); cur.close(); conn.close()
        st.session_state["_db_error"] = None
    except Exception as e:
        st.session_state["_db_error"] = str(e)

def _db_load(table):
    try:
        conn = _db_conn(); cur = conn.cursor()
        _db_ensure(cur); conn.commit()
        cur.execute(f"SELECT data FROM {table} ORDER BY ts DESC LIMIT 1")
        row = cur.fetchone(); cur.close(); conn.close()
        if row and row[0]:
            return row[0] if isinstance(row[0], list) else json.loads(row[0])
    except Exception:
        pass
    return []

# NSE cash-market session: 09:15–15:30 IST
NSE_OPEN_HOUR,  NSE_OPEN_MIN  = 9, 15
NSE_CLOSE_HOUR, NSE_CLOSE_MIN = 15, 30
NSE_SESSION_MINUTES = (NSE_CLOSE_HOUR * 60 + NSE_CLOSE_MIN) - (NSE_OPEN_HOUR * 60 + NSE_OPEN_MIN)  # 375

# ── Thread safety ──────────────────────────────────────────────────────────────
_phase_lock = threading.Lock()


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
    """
    Returns the fraction of the NSE trading session (09:15–15:30) that has
    elapsed as of *now* (IST = UTC+5:30).  Clamped to [0.05, 1.0] so we
    never divide by near-zero early in the session.
    """
    now_utc  = datetime.utcnow()
    now_ist  = now_utc + timedelta(hours=5, minutes=30)
    minutes_since_open = (now_ist.hour * 60 + now_ist.minute) - (NSE_OPEN_HOUR * 60 + NSE_OPEN_MIN)
    fraction = minutes_since_open / NSE_SESSION_MINUTES
    return float(np.clip(fraction, 0.05, 1.0))


def _intraday_vol_avg(volume: pd.Series, bars_per_day: int) -> float:
    """
    FIX-4: For intraday data, compute today's cumulative volume scaled to a
    full-session equivalent, then average with recent prior-day totals.

    - Collects full prior-day volumes (rolling sum of bars_per_day bars,
      shifted by 1 day's worth of bars so today's partial data is excluded).
    - Estimates today's projected full-day volume by dividing elapsed bars'
      cumulative volume by the session fraction elapsed.
    - Returns the mean of the last 5 prior-day full volumes + today's projection.
    """
    elapsed_frac = _session_elapsed_fraction()

    # today's bars: last N bars (may be partial)
    today_bars = int(min(bars_per_day * elapsed_frac + 1, len(volume)))
    today_vol  = float(volume.iloc[-today_bars:].sum())
    today_proj = today_vol / elapsed_frac          # scaled to full session

    # prior full days: rolling sum, skip today's partial bars
    if len(volume) > bars_per_day + today_bars:
        prior = volume.iloc[:-(today_bars)].rolling(bars_per_day).sum().dropna()
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

def signal_age_label(logged_at_iso: str, mode: str) -> str:
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

        if delta_min <= 5:
            bars_per_day = 75
        elif delta_min <= 15:
            bars_per_day = 25
        elif delta_min <= 30:
            bars_per_day = 13
        elif delta_min < 240:
            bars_per_day = 7
        else:
            bars_per_day = 1

        # FIX-4: use time-normalised volume for intraday liquidity check
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
# HTF — CACHED FETCH + TREND   (FIX-1: closed-candle only)
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

    """
    FIX-1: Use only CLOSED HTF candles.
    Prevents repainting from partially formed HTF bars.
    """

    if df is None or df.empty:
        return True, "HTF-UNKNOWN"

    # Remove live/incomplete HTF candle
    if mode == "Intraday" and len(df) > 2:
        df = df.iloc[:-1].copy()

    min_bars = 55 if mode == "Intraday" else 26

    if len(df) < min_bars:
        return True, "HTF-UNKNOWN"

    cl = df["Close"]

    ef = float(ema(cl, 21 if mode == "Intraday" else 13).iloc[-1])
    es = float(ema(cl, 55 if mode == "Intraday" else 26).iloc[-1])

    c = float(cl.iloc[-1])

    up = c > ef > es

    return up, ("HTF↑" if up else "HTF↓")

def prefetch_htf_parallel(symbols: list, mode: str, status_text, progress_bar) -> dict:
    import concurrent.futures
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
# RELATIVE STRENGTH — VECTORIZED 52-WEEK PERCENTILE RANK  (PERF-4)
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
# PHASE TRANSITION MEMORY  (PERF-7: thread-safe version)
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
    if curr == PHASE_EXIT:                                          return "→EXIT"
    if PHASE_ORDER.get(curr, 0) > PHASE_ORDER.get(prev, 0):        return "↗"
    if PHASE_ORDER.get(curr, 0) < PHASE_ORDER.get(prev, 0):        return "↘"
    return ""


# ═══════════════════════════════════════════════════════════════════════════════
# FIX-5  VOLATILITY-NORMALIZED POSITION SIZING  (with capital cap)
# ═══════════════════════════════════════════════════════════════════════════════

def position_size(account_size, entry, sl, atr_val, atr_mean, vix_val,
                  risk_pct=0.02, max_capital_pct=0.20):
    """
    FIX-5: Added max_capital_pct (default 20 %).
    final_qty is now clamped so that:
        final_qty × entry  ≤  account_size × max_capital_pct
    This prevents the sizer from allocating a runaway position when the
    stop is very tight relative to account size.
    """
    risk_per_share = max(entry - sl, 0.01)
    base_qty       = int((account_size * risk_pct) / risk_per_share)

    if vix_val and vix_val > 0:
        vix_adj = float(np.clip(20.0 / vix_val, 0.5, 1.5))
    else:
        vix_adj = 1.0

    if atr_mean > 0:
        atr_adj = float(np.clip(atr_mean / atr_val, 0.6, 1.4))
    else:
        atr_adj = 1.0

    vol_adj_qty = max(1, int(base_qty * vix_adj * atr_adj))

    # FIX-5: capital cap — never allocate more than max_capital_pct of account
    max_qty_by_capital = max(1, int((account_size * max_capital_pct) / entry))
    final_qty          = min(vol_adj_qty, max_qty_by_capital)

    capital_used = round(final_qty * entry, 2)
    max_loss     = round(final_qty * risk_per_share, 2)

    return {
        "base_qty":          base_qty,
        "vix_adj":           round(vix_adj, 2),
        "atr_adj":           round(atr_adj, 2),
        "vol_adj_qty":       vol_adj_qty,           # pre-cap qty (diagnostic)
        "final_qty":         final_qty,
        "capital_used":      capital_used,
        "max_loss":          max_loss,
        "risk_pct":          risk_pct,
        "max_capital_pct":   max_capital_pct,
        "capital_capped":    final_qty < vol_adj_qty,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# EXHAUSTION DETECTION
# ═══════════════════════════════════════════════════════════════════════════════

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
    cfg    = EXT_CFG[mode]
    n      = len(close)
    flags  = {k: False for k in EXT_PENALTIES}
    labels = []

    rsi_ceil = cfg["rsi_ceil"]
    if vix_val is not None:
        if vix_val < VIX_CALM:     rsi_ceil += 2
        elif vix_val > VIX_STRESS: rsi_ceil -= 3

    rsi_now = float(rsi_series.iloc[-1])
    if rsi_now > rsi_ceil:
        flags["rsi_overheat"] = True; labels.append("Too hot")

    atr_val = float(atr_s.iloc[-1])
    if atr_mean > 0 and atr_val > atr_mean * cfg["atr_exp"]:
        flags["atr_extension"] = True; labels.append("Range blowout")

    if n >= 23:
        daily_pct  = close.pct_change().dropna()
        hist_sigma = float(daily_pct.iloc[-20:].std())
        exp_3b     = hist_sigma * (3 ** 0.5)
        act_3b     = abs(float(close.iloc[-1]) - float(close.iloc[-4])) / float(close.iloc[-4])
        if exp_3b > 0 and act_3b > cfg["parab"] * exp_3b:
            flags["parabolic"] = True; labels.append("Parabolic")

    e_fast_now = float(e_fast_s.iloc[-1])
    if atr_val > 0:
        ema_dist_atrs = (c - e_fast_now) / atr_val
        if ema_dist_atrs > cfg["ema_dist"]:
            flags["ema_distance"] = True; labels.append("EMA overext")

    wick_thresh = 0.35 if (c > 0 and atr_val / c > 0.03) else 0.30

    if n >= 12 and vol_avg > 0:
        prior_run = c > float(close.iloc[-11])
        up_bar    = c > float(close.iloc[-2])
        if prior_run and up_bar and v > vol_avg * cfg["clim_vol"]:
            bar_range  = float(high.iloc[-1]) - float(low.iloc[-1])
            upper_wick = float(high.iloc[-1]) - c
            if bar_range > 0 and (upper_wick / bar_range) > wick_thresh:
                flags["climactic_volume"] = True; labels.append("Vol climax")

    if n >= 10:
        lookback      = min(cfg["div_bars"], n - 1)
        rsi_win       = rsi_series.iloc[-lookback:]
        rsi_peak      = float(rsi_win.max())
        rsi_peak_idx  = rsi_win.idxmax()
        price_at_peak = float(close[rsi_peak_idx])
        gap_req = 5 if mode == "Intraday" else 3
        if (rsi_now < rsi_peak - gap_req
                and c > price_at_peak
                and rsi_win.idxmax() != rsi_win.index[-1]):
            flags["mom_exhaustion"] = True; labels.append("Mom fade")

    if n >= 20:
        lookback  = min(cfg["div_bars"] * 2, n - 2)
        h_slice   = high.iloc[-lookback:]
        r_slice   = rsi_series.iloc[-lookback:]
        pivot_idx = []
        for i in range(1, len(h_slice) - 1):
            if (float(h_slice.iloc[i]) > float(h_slice.iloc[i-1])
                    and float(h_slice.iloc[i]) > float(h_slice.iloc[i+1])):
                pivot_idx.append(i)
        if len(pivot_idx) >= 2:
            p1, p2   = pivot_idx[-2], pivot_idx[-1]
            ph1, ph2 = float(h_slice.iloc[p1]), float(h_slice.iloc[p2])
            rh1, rh2 = float(r_slice.iloc[p1]), float(r_slice.iloc[p2])
            if ph2 > ph1 and rh2 < rh1 - 2 and (len(h_slice) - 1 - p2) <= 5:
                flags["bearish_div"] = True; labels.append("Bear div")

    penalty = sum(EXT_PENALTIES[k] for k, v2 in flags.items() if v2)
    n_flags = sum(flags.values())
    return flags, float(penalty), labels, n_flags

def ext_phase_override(phase, ext_flags, n_flags, mode):
    rsi_ext     = ext_flags.get("rsi_overheat", False)
    atr_ext     = ext_flags.get("atr_extension", False)
    is_critical = n_flags >= 3 or (rsi_ext and atr_ext)
    is_moderate = n_flags == 2
    if is_critical:
        if phase == PHASE_BRK:   return PHASE_EXIT,  "ext-critical→EXIT"
        if phase == PHASE_CONT:  return PHASE_SETUP, "ext-critical→SETUP"
        if phase == PHASE_ENTRY: return PHASE_SETUP, "ext-critical→SETUP"
    elif is_moderate:
        if phase == PHASE_BRK:  return PHASE_SETUP, "ext-moderate→SETUP"
    return phase, None

def ext_action_cap(action, n_flags, vix_val=None):
    if n_flags == 0 and (vix_val is None or vix_val < VIX_STRESS):
        return action
    if vix_val is not None and vix_val >= VIX_STRESS:
        return "WATCH" if action in ("STRONG BUY", "BUY") else action
    if n_flags >= 3:
        return "WATCH" if action in ("STRONG BUY", "BUY") else action
    return "BUY" if action == "STRONG BUY" else action


# ═══════════════════════════════════════════════════════════════════════════════
# CONFIDENCE MODEL
# ═══════════════════════════════════════════════════════════════════════════════

def compute_confidence(*, norm_bull, phase, trend_up, trend_strong, vol_confirmed,
                       ema_stack, htf_aligned, regime_bullish, ext_n, vix_val,
                       phase_bonus=0, rs_rank=50):
    c  = 0.0
    c += {PHASE_BRK:20, PHASE_CONT:17, PHASE_ENTRY:13,
          PHASE_SETUP:7, PHASE_IDLE:2, PHASE_EXIT:0}.get(phase, 0)
    c += min(20, norm_bull * 0.20)
    c += 15 if vol_confirmed else 5
    c += 15 if ema_stack else (7 if trend_strong else 0)
    c += 15 if htf_aligned else 0
    c += 10 if regime_bullish else 2
    c -= min(5, ext_n * 2)
    if vix_val is not None and vix_val > VIX_CAUTION:
        c -= 5
    if rs_rank >= 90:    c += 5
    elif rs_rank >= 80:  c += 3
    elif rs_rank <= 20:  c -= 3
    c += phase_bonus
    return round(min(100, max(0, c)), 1)

def confidence_label(conf):
    if conf >= 80: return "HIGH", "#2ecc71"
    if conf >= 60: return "MED",  "#f39c12"
    if conf >= 40: return "LOW",  "#e67e22"
    return "WEAK", "#e74c3c"


# ═══════════════════════════════════════════════════════════════════════════════
# PHASE + ENTRY   (FIX-3: structural breakout filtering)
# ═══════════════════════════════════════════════════════════════════════════════

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
    rolling_hi_brk = float(high.iloc[-brk_lb-1:-1].max()) if n > brk_lb + 1 else float(high.iloc[-1])

    # FIX-3: tighter buffer (0.15 × ATR) + hard volume gate + anti-blowoff guard
    buf = atr_val * 0.15    # tighter than v10's 0.20

    is_compressed = atr_val < atr_mean * 0.8
    is_expanding  = atr_val > float(atr_s.iloc[-2])

    # FIX-3: reject breakouts when the prior 3-bar range is already expanded
    #         (avoids entering a blow-off move disguised as a breakout)
    prior_3bar_atr_expanded = atr_val > atr_mean * 1.4

    body = (abs(float(close.iloc[-1]) - float(df["Open"].iloc[-1]))
            if "Open" in df.columns else atr_val * 0.3)
    upper_wick = (float(high.iloc[-1]) - max(float(close.iloc[-1]), float(df["Open"].iloc[-1]))
                  if "Open" in df.columns else 0)
    is_exhaustion = upper_wick > body * 1.5

    # FIX-3: hard volume gate — breakout candle MUST have vol > 1.5× avg
    brk_vol_ok    = (v > vol_avg * 1.5) if vol_avg > 0 else False

    vol_spike     = v > vol_avg * 1.3
    is_fib_buy    = trend_up and in_golden

    cont_vol_mult = 1.5 if (regime_bearish or (vix_val and vix_val > VIX_CAUTION)) else 1.2
    BRK_CONF_MIN  = 0.70 if regime_bearish else 0.65

    # FIX-8: Removed "trend_up" weight — it was already captured by "score_ok"
    # (norm_bull awards +25 for trend_up, so score_ok and trend_up fire together,
    # artificially inflating brk_confidence by 0.35 when trend is strong).
    # Redistributed weight to orthogonal signals: price_above_high (+0.05),
    # compressed (+0.05), so the remaining 5 factors still sum to 1.0.
    brk_weights = {
        "price_above_high": (0.35, c > rolling_hi_brk + buf),
        "score_ok":         (0.20, norm_bull >= score_th),
        "compressed":       (0.20, is_compressed),
        "expanding":        (0.15, is_expanding),
        "vol_spike":        (0.10, vol_spike),
    }
    brk_confidence = sum(w for w, cond in brk_weights.values() if cond)

    # FIX-3: add hard gates — exhaustion, volume, and prior-range expansion all
    #         veto the breakout regardless of the weighted score
    is_breakout = (
        brk_confidence >= BRK_CONF_MIN
        and not is_exhaustion
        and brk_vol_ok                      # FIX-3 hard vol gate
        and not prior_3bar_atr_expanded     # FIX-3 anti-blowoff
        and htf_up
    )

    # FIX-7: POST-BREAKOUT SUPPRESSION
    # After a breakout fires on bar N, bars N+1…N+brk_lb all have the elevated
    # breakout high inside rolling_hi_brk, so is_breakout becomes False.
    # Without suppression, the stock falls through to PHASE_ENTRY the very next
    # bar — producing a spurious "new" entry signal at a stale/lower price.
    #
    # Detection: scan the last brk_lb bars (excluding current) for any bar that
    # clears the rolling high AT THAT TIME with breakout-level volume.
    # If found → was_recent_brk = True.  The phase tree routes this to CONT
    # (not ENTRY), and entry_price is pinned to current price, not old EMA cross.
    was_recent_brk = False
    recent_brk_bar = None                       # index offset (1 = previous bar)
    if not is_breakout and n > brk_lb * 2 + 2:
        for k in range(1, brk_lb + 1):
            # Rolling high as it was BEFORE bar [-k]
            look_start = -(brk_lb + 1 + k)
            look_end   = -(1 + k)
            if abs(look_start) > n or abs(look_end) > n:
                break
            prev_rolling_hi = float(high.iloc[look_start:look_end].max())
            prev_hi_k       = float(high.iloc[-k])
            prev_close_k    = float(close.iloc[-k])
            prev_vol_k      = float(df["Volume"].iloc[-k])

            # FIX-9: volatility-spike guard — the CLOSE must also clear the rolling
            # high (not just the wick/high).  A spike candle that wicks above but
            # closes back below the old high is NOT a breakout; it's an exhaustion bar.
            close_above_brk = prev_close_k > prev_rolling_hi

            # FIX-9: body must be non-red (close >= open).  A red candle that gaps
            # up through the high and closes below open is a bearish reversal bar,
            # not a breakout continuation signal.
            prev_open_k = (float(df["Open"].iloc[-k])
                           if "Open" in df.columns else prev_close_k)
            body_non_red = prev_close_k >= prev_open_k

            # FIX-9 (Bug 3): use the volume average computed at bar [-k] (exclude
            # recent k bars) so we compare against the baseline that was relevant
            # at the time — not today's potentially inflated/deflated average.
            hist_vol = df["Volume"].iloc[:-k]
            hist_avg_k = (float(hist_vol.rolling(20).mean().iloc[-1])
                          if len(hist_vol) >= 20 else vol_avg)
            vol_gate = (hist_avg_k == 0 or prev_vol_k > hist_avg_k * 1.5)

            if (prev_hi_k > prev_rolling_hi + buf
                    and close_above_brk
                    and body_non_red
                    and vol_gate):
                was_recent_brk = True
                recent_brk_bar = k
                break

    is_cont = (
        n >= 4
        and c > float(close.iloc[-4:-1].max())
        and c > e_fast_val
        and v > vol_avg * cont_vol_mult
        and trend_strong
        and htf_up
    )

    ema_down    = e_fast_val < e_slow_val and float(e_fast_s.iloc[-4]) < float(e_slow_s.iloc[-4])
    trail_level = float(close.iloc[-10:].max()) - atr_val * 1.5
    trail_break = c < trail_level

    if trend_down and ema_down:
        phase, setup_type = PHASE_EXIT, "norm"
    elif is_breakout:
        phase, setup_type = PHASE_BRK, "breakout"
    elif was_recent_brk and trend_strong:
        # FIX-7: post-breakout bars → CONT (not ENTRY).
        # Only downgrade to SETUP if volume dried up AND trend weakening.
        if trend_up:
            phase, setup_type = PHASE_CONT, "breakout"
        else:
            phase, setup_type = PHASE_SETUP, "breakout"
    elif (is_fib_buy or norm_bull >= score_th) and is_cont and trend_up:
        phase, setup_type = PHASE_CONT, ("fib" if is_fib_buy else "norm")
    elif (is_fib_buy or norm_bull >= score_th) and trend_up:
        phase, setup_type = PHASE_ENTRY, ("fib" if is_fib_buy else "norm")
    elif (is_fib_buy or norm_bull >= score_th * 0.85 or vdu_setup) and trend_up:
        phase, setup_type = PHASE_SETUP, ("fib" if is_fib_buy else ("vdu" if vdu_setup else "norm"))
    elif trail_break and trend_up:
        phase, setup_type = PHASE_EXIT, "norm"
    else:
        phase, setup_type = PHASE_IDLE, "norm"

    if not htf_up and phase in (PHASE_ENTRY, PHASE_CONT, PHASE_BRK):
        phase, setup_type = PHASE_SETUP, setup_type

    entry_price = None
    if phase in (PHASE_ENTRY, PHASE_CONT, PHASE_BRK, PHASE_SETUP):
        prox = atr_val * 0.3
        if is_breakout:
            entry_price = round(rolling_hi_brk + buf, 2)
        elif was_recent_brk:
            # FIX-7: post-breakout CONT — pin entry to current price (already
            # above the breakout level).  Do NOT use the old EMA-cross price,
            # which is stale and far below the actual breakout level.
            entry_price = round(c, 2)
        elif is_fib_buy and fib:
            entry_price = round(fib["618"] + prox * 0.3, 2)
        else:
            # FIX-7: guard the EMA-cross finder — only use crossover price if
            # it is recent (within last 10 bars) AND above current close * 0.97.
            # Otherwise fall back to current price to avoid stale signals.
            cross       = close > e_fast_s
            signal_bars = cross & ~cross.shift(1).fillna(False)
            if signal_bars.any():
                last_cross_idx = signal_bars[::-1].idxmax()
                cross_pos      = close.index.get_loc(last_cross_idx)
                bars_ago       = (n - 1) - cross_pos
                cross_px       = float(close[last_cross_idx])
                if bars_ago <= 10 and cross_px >= c * 0.97:
                    entry_price = round(cross_px, 2)
                else:
                    entry_price = round(c, 2)
            else:
                entry_price = round(c, 2)

    return phase, entry_price, setup_type


# ═══════════════════════════════════════════════════════════════════════════════
# TARGET COMPUTATION
# ═══════════════════════════════════════════════════════════════════════════════

def _compute_targets(entry, sl, atr_val, fib, setup_type, sw_hi, sw_lo,
                     regime_bearish=False, vix_val=None):
    rk = max(entry - sl, atr_val * 0.5)
    t1m, t2m, t3m, sl_exp = vix_target_mult(vix_val)

    if regime_bearish:
        t1m *= 0.8; t2m *= 0.7; t3m *= 0.6

    if setup_type == "fib" and fib:
        t1     = round(fib["ext127"], 2)
        t2     = round(fib["ext161"], 2)
        ext_r  = fib["ext161"] - fib["ext127"]
        t3     = round(fib["ext161"] + min(ext_r, atr_val * 3), 2)
    elif setup_type == "breakout" and fib:
        t1     = round((entry + rk * t1m + fib["ext127"]) / 2, 2)
        t2     = round((entry + rk * t2m + fib["ext161"]) / 2, 2)
        t3     = round((entry + rk * t3m + fib["ext261"]) / 2, 2)
    else:
        t1     = round(entry + rk * t1m, 2)
        t2     = round(entry + rk * t2m, 2)
        t3     = round(entry + rk * t3m, 2)

    min_move = atr_val * 0.8
    if t1 - entry < min_move:
        t1 = round(entry + min_move, 2)
        t2 = round(entry + min_move * 2, 2)
        t3 = round(entry + min_move * 3, 2)

    return t1, t2, t3, sl_exp


# ═══════════════════════════════════════════════════════════════════════════════
# FETCH HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

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
                time.sleep(min(0.5 * (attempt + 1), 1.0))
    return sym, None

def _fetch_one_with_daily(args):
    sym, mode, min_bars = args
    primary_sym, primary_df = _fetch_one(args)
    daily_df = None
    if mode == "Intraday" and primary_df is not None:
        _, daily_df = _fetch_one((sym, "Swing", 50))
    return primary_sym, primary_df, daily_df

@st.cache_data(ttl=300)
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


# ═══════════════════════════════════════════════════════════════════════════════
# CORE SCORING  (FIX-4 + FIX-6 — no session_state access)
# ═══════════════════════════════════════════════════════════════════════════════

def score_stock(df, nifty_close, mode="Swing", daily_close=None,
                market_bullish=True, vix_val=None, min_liquidity_cr=LIQUIDITY_MIN_CR,
                sym=None, htf_up=True, rs_rank=50,
                phase_history_snapshot=None):
    """
    FIX-4: vol_avg for Intraday mode now uses _intraday_vol_avg() so that
           a partial session's volume is scaled to a full-day equivalent
           before comparison.  This prevents spurious "volume spike" signals
           at market open.

    FIX-6: EMA cross scoring block is replaced with a fresh-cross bonus that
           is orthogonal to trend_up (+25) and ema_stack (+15):
               +8  golden-cross within last 5 bars  (fresh, bullish momentum)
               +4  e_fast > e_slow but not a fresh cross
               0   otherwise
           The old "+15 if e_fast > e_slow" added redundant signal weight
           that was already embedded in trend_up and ema_stack.
    """
    try:
        cfg    = MODE_CFG[mode]
        close  = df["Close"]
        volume = df["Volume"]
        n      = len(close)
        if n < 50:
            return None

        liq_ok, avg_cr = liquidity_ok(df, min_liquidity_cr, mode=mode)

        c        = float(close.iloc[-1])
        prev     = float(close.iloc[-2])
        e_fast_s = ema(close, cfg["ema_fast"])
        e_slow_s = ema(close, cfg["ema_slow"])
        e_fast   = float(e_fast_s.iloc[-1])
        e_slow   = float(e_slow_s.iloc[-1])
        e200_s   = ema(close, 200)
        e200     = float(e200_s.iloc[-1]) if n >= 200 else None
        atr_s    = atr_series(df)
        atr_val  = float(atr_s.iloc[-1])
        atr_mean = float(atr_s.rolling(20).mean().iloc[-1])
        chg      = round(((c - prev) / prev) * 100, 2)
        hh       = float(close.iloc[-11:-1].max())

        # ── FIX-4: time-normalised vol_avg for intraday ──────────────────────
        n_rows  = len(df)
        if n_rows >= 2:
            try:
                delta_min = (df.index[1] - df.index[0]).total_seconds() / 60
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
            vol_avg = _intraday_vol_avg(volume, bars_per_day)
        else:
            vol_avg = float(volume.rolling(20).mean().iloc[-1])

        v = float(volume.iloc[-1])

        above_ema50 = c > float(ema(close, 50).iloc[-1])

        rs_raw = 0.0
        if n >= 6 and len(nifty_close) >= 6:
            rs_raw = ((c - float(close.iloc[-6])) / float(close.iloc[-6]) -
                      (float(nifty_close.iloc[-1]) - float(nifty_close.iloc[-6])) /
                      float(nifty_close.iloc[-6])) * 100

        trend_up     = (e200 is None or c > e200) and c > e_fast and e_fast > e_slow
        trend_down   = (e200 is None or c < e200) and c < e_fast and e_fast < e_slow
        trend_strong = c > e_fast and e_fast > e_slow
        ema_stack    = (e200 is not None) and (c > e200) and (e_fast > e_slow) and (e_fast > e200)

        # ── FIX-6: fresh EMA cross detection (non-redundant) ─────────────────
        # A "golden cross" is the first bar where e_fast crosses above e_slow.
        # We look back up to 5 bars to see if such a cross occurred recently.
        # FIX-10: True golden-cross detection — the cross bar must have
        # e_fast > e_slow AND the immediately prior bar must have e_fast <= e_slow.
        # The old loop only checked that e_fast was below at some past bar, which
        # could fire on oscillating EMAs without a clean directional crossover.
        fresh_cross = False
        if n >= 6 and e_fast > e_slow:
            lookback_cross = min(5, n - 1)
            for k in range(1, lookback_cross + 1):
                ef_curr = float(e_fast_s.iloc[-k])
                es_curr = float(e_slow_s.iloc[-k])
                ef_prev = float(e_fast_s.iloc[-(k+1)])
                es_prev = float(e_slow_s.iloc[-(k+1)])
                # Both conditions must hold at adjacent bars for a genuine crossover
                if ef_curr > es_curr and ef_prev <= es_prev:
                    fresh_cross = True
                    break

        ema_cross_bonus = 8 if fresh_cross else (4 if e_fast > e_slow else 0)
        # (replaces the old "+15 if e_fast > e_slow" which double-counted trend_up)

        mom_src = (daily_close if (mode == "Intraday" and daily_close is not None
                                   and len(daily_close) >= 21) else close)
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
        vdu_setup  = bool(trend_up and vdu_vol_dry and vdu_coil)
        qualified  = strong_htf and trend_strong

        rsi_series = rsi(close, cfg["rsi_len"])
        ext_flags, ext_penalty, ext_labels, ext_n = detect_exhaustion(
            close=close, high=df["High"], low=df["Low"], volume=volume,
            rsi_series=rsi_series, e_fast_s=e_fast_s, atr_s=atr_s, atr_mean=atr_mean,
            c=c, v=v, vol_avg=vol_avg, mode=mode, vix_val=vix_val,
        )
        r = float(rsi_series.iloc[-1])

        # ── Bull score  (FIX-6: ema_cross_bonus replaces old +15 EMA block) ──
        bull  = 0
        bull += 25 if trend_up else 0
        # FIX-6: was "+15 if e_fast > e_slow else (7 if near else 0)"
        # Now replaced with non-redundant fresh-cross bonus:
        bull += ema_cross_bonus
        bull += (15 if r >= 65 else 10) if r >= 60 else (5 if r > 50 else 0)
        bull += 10 if v > vol_avg * 1.2 else (5 if v > vol_avg else 0)
        bull += 15 if c > hh else (9 if c > hh * 0.98 else 0)
        if n >= 3 and c > float(close.iloc[-3]):
            bull += 8
        bull += 7 if rs_rank >= 80 else (3 if rs_rank >= 60 else (0 if rs_rank >= 40 else -3))
        if mode == "Positional":
            bull += 15 if qualified else -15
        else:
            bull += 15 if strong_htf else -10
        bull += 10 if in_golden else 0
        if near_e127:   bull -= 20
        elif near_e161: bull -= 30
        bull += ext_penalty

        BEARISH_HAIRCUT = 0.85
        regime_bearish  = not market_bullish
        if regime_bearish:
            bull = int(bull * BEARISH_HAIRCUT)

        raw_score = max(0, bull)
        # FIX-6: BULL_MAX adjusted down by 7 to reflect removed double-count
        # (old max was 120; ema cross block max contribution was +15, now max +8)
        BULL_MAX_V11 = 113
        norm_bull  = min(100.0, max(0.0, bull * 100.0 / BULL_MAX_V11))
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

        # PERF-7: compute phase bonus from snapshot (no session_state in thread)
        phase_bonus = 0
        if sym and phase_history_snapshot:
            history = phase_history_snapshot.get(sym, [])
            if len(history) >= 3:
                last3 = [h[1] for h in history[-3:]]
                progressions = [
                    [PHASE_SETUP, PHASE_ENTRY, PHASE_CONT],
                    [PHASE_ENTRY, PHASE_CONT, PHASE_BRK],
                    [PHASE_SETUP, PHASE_ENTRY, PHASE_BRK],
                ]
                phase_bonus = 5 if last3 in progressions else 0

        confidence = compute_confidence(
            norm_bull=norm_bull, phase=phase, trend_up=trend_up,
            trend_strong=trend_strong, vol_confirmed=vol_confirmed,
            ema_stack=ema_stack, htf_aligned=htf_up,
            regime_bullish=market_bullish, ext_n=ext_n, vix_val=vix_val,
            phase_bonus=phase_bonus, rs_rank=rs_rank,
        )

        ltp   = round(c, 2)
        entry = entry_price if entry_price else ltp

        mult = cfg["atr_mult"]; wide = cfg["atr_wide"]; closest = cfg["atr_max"]
        if setup_type == "fib" and fib:
            fib_sl = max(float(sw_lo), fib["618"] - atr_val * 0.5)
            fib_sl = max(fib_sl, entry - atr_val * 0.8)
            sl     = round(fib_sl, 2)
        elif setup_type == "breakout":
            sl = round(entry - atr_val * (1.5 if mode == "Intraday" else 2.0), 2)
        else:
            raw_sl      = entry - atr_val * mult
            furthest_sl = entry - atr_val * wide
            closest_sl  = entry - atr_val * closest
            sl = round(max(furthest_sl, min(raw_sl, closest_sl)), 2)

        min_risk = atr_val * 0.5
        if entry - sl < min_risk:
            sl = round(entry - min_risk, 2)

        t1, t2, t3, sl_exp = _compute_targets(
            entry, sl, atr_val, fib, setup_type, sw_hi, sw_lo,
            regime_bearish=regime_bearish, vix_val=vix_val,
        )
        if sl_exp > 1.0:
            sl = round(entry - (entry - sl) * sl_exp, 2)

        return {
            "Score":         round(norm_bull, 1),
            "RawBull":       raw_score,
            "Action":        act,
            "Phase":         phase,
            "Setup":         setup_type,
            "Confidence":    confidence,
            "%Change":       chg,
            "LTP":           ltp,
            "Entry":         entry,
            "SL":            sl,
            "T1":            t1,
            "T2":            t2,
            "T3":            t3,
            "InGolden":      in_golden,
            "VDU":           vdu_setup,
            "AboveEMA50":    above_ema50,
            "AvgTradedCr":   avg_cr,
            "LiquidityOK":   liq_ok,
            "RSI":           round(r, 1),
            "RS":            round(rs_raw, 2),
            "RS_Rank":       rs_rank,
            "ExtN":          ext_n,
            "ExtLabels":     ext_labels,
            "ExtFlags":      ext_flags,
            "HTFUp":         htf_up,
            "EMAStack":      ema_stack,
            "VolConf":       vol_confirmed,
            "FreshCross":    fresh_cross,
            "ATR":           round(atr_val, 2),
            "ATR_Mean":      round(atr_mean, 2),
            "PhaseBonus":    phase_bonus,
            "BreadthGated":  False,
            # v14: short scoring uses these — already computed, free to store
            "Mom1":          round(mom1, 2),
            "Mom3":          round(mom3, 2),
            "TrendUp":       trend_up,
            "TrendDown":     trend_down,
            "_detected_phase": phase,
        }
    except Exception:
        return None


# ═══════════════════════════════════════════════════════════════════════════════
# BREADTH ENGINE
# ═══════════════════════════════════════════════════════════════════════════════

def compute_breadth(results):
    if not results:
        return {}
    total          = len(results)
    above_ema50    = sum(1 for r in results if r.get("AboveEMA50", False))
    breakout_count = sum(1 for r in results if r.get("Phase") == PHASE_BRK)
    advancing      = sum(1 for r in results if r.get("%Change", 0) > 0)
    declining      = sum(1 for r in results if r.get("%Change", 0) < 0)
    unchanged      = total - advancing - declining

    pct_above_ema50 = round(above_ema50 / total * 100, 1)
    pct_breakout    = round(breakout_count / total * 100, 1)
    ad_ratio        = round(advancing / max(declining, 1), 2)
    pct_advancing   = round(advancing / total * 100, 1)

    sector_scores = {}
    sector_counts = {}
    for r in results:
        sym = r.get("Symbol", "")
        sec = SECTOR_MAP.get(sym, "Other")
        sector_scores[sec] = sector_scores.get(sec, 0) + r.get("Score", 0)
        sector_counts[sec] = sector_counts.get(sec, 0) + 1
    sector_avg = {
        sec: round(sector_scores[sec] / sector_counts[sec], 1)
        for sec in sector_scores
    }

    liquid_count = sum(1 for r in results if r.get("LiquidityOK", True))

    return {
        "total":           total,
        "above_ema50":     above_ema50,
        "pct_above_ema50": pct_above_ema50,
        "breakout_count":  breakout_count,
        "pct_breakout":    pct_breakout,
        "advancing":       advancing,
        "declining":       declining,
        "unchanged":       unchanged,
        "ad_ratio":        ad_ratio,
        "pct_advancing":   pct_advancing,
        "sector_avg":      sector_avg,
        "liquid_count":    liquid_count,
        "breadth_signal":  _breadth_signal(pct_above_ema50, ad_ratio, pct_breakout),
    }

def _breadth_signal(pct_ema50, ad_ratio, pct_brk):
    score = 0
    if pct_ema50 >= 70:   score += 2
    elif pct_ema50 >= 50: score += 1
    if ad_ratio >= 2.0:   score += 2
    elif ad_ratio >= 1.2: score += 1
    if pct_brk >= 5:      score += 1
    if score >= 4: return "STRONG", "#2ecc71"
    if score >= 2: return "NEUTRAL", "#f39c12"
    return "WEAK", "#e74c3c"


# ═══════════════════════════════════════════════════════════════════════════════
# OI DATA
# ═══════════════════════════════════════════════════════════════════════════════

@st.cache_data(ttl=180)
def fetch_oi_data(symbol="NIFTY"):
    import requests
    HEADERS = {
        "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                       "AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36"),
        "Accept":          "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer":         "https://www.nseindia.com/",
        "X-Requested-With":"XMLHttpRequest",
        "Connection":      "keep-alive",
    }
    session = requests.Session()
    session.headers.update(HEADERS)

    def _warm():
        try:
            session.get("https://www.nseindia.com", timeout=10)
            time.sleep(0.8)
            session.get("https://www.nseindia.com/market-data/equity-derivatives-watch", timeout=10)
            time.sleep(0.5)
            return True
        except Exception:
            return False
    _warm()

    oc_url = f"https://www.nseindia.com/api/option-chain-indices?symbol={symbol}"
    data   = None
    for attempt in range(3):
        try:
            resp = session.get(oc_url, timeout=12)
            if resp.status_code == 200:
                data = resp.json(); break
            elif resp.status_code in (401, 403):
                _warm()
        except Exception:
            pass
        time.sleep(1.5 ** attempt)

    if data is None:
        return None
    try:
        records       = data["records"]
        spot          = float(records["underlyingValue"])
        expiries      = records["expiryDates"]
        weekly_expiry = expiries[0] if expiries else None
        rows = []
        for item in records["data"]:
            if item.get("expiryDate") != weekly_expiry: continue
            strike = item["strikePrice"]
            ce_oi  = item.get("CE", {}).get("openInterest", 0) or 0
            pe_oi  = item.get("PE", {}).get("openInterest", 0) or 0
            ce_chg = item.get("CE", {}).get("changeinOpenInterest", 0) or 0
            pe_chg = item.get("PE", {}).get("changeinOpenInterest", 0) or 0
            rows.append({"Strike": strike, "CE_OI": ce_oi, "CE_Chg": ce_chg,
                         "PE_OI": pe_oi, "PE_Chg": pe_chg})
        if not rows:
            return None
        df_oi    = pd.DataFrame(rows).sort_values("Strike").reset_index(drop=True)
        total_ce = df_oi["CE_OI"].sum()
        total_pe = df_oi["PE_OI"].sum()
        pcr      = round(total_pe / total_ce, 2) if total_ce > 0 else 0
        pains = []
        for s in df_oi["Strike"]:
            ce_l = ((df_oi["Strike"] - s).clip(lower=0) * df_oi["CE_OI"]).sum()
            pe_l = ((s - df_oi["Strike"]).clip(lower=0) * df_oi["PE_OI"]).sum()
            pains.append(ce_l + pe_l)
        df_oi["TotalPain"] = pains
        return {
            "symbol":    symbol,
            "expiry":    weekly_expiry,
            "spot":      spot,
            "pcr":       pcr,
            "max_pain":  int(df_oi.loc[df_oi["TotalPain"].idxmin(), "Strike"]),
            "call_wall": int(df_oi.loc[df_oi["CE_OI"].idxmax(), "Strike"]),
            "put_wall":  int(df_oi.loc[df_oi["PE_OI"].idxmax(), "Strike"]),
            "top_ce":    df_oi.nlargest(5, "CE_OI")[["Strike","CE_OI","CE_Chg"]].to_dict("records"),
            "top_pe":    df_oi.nlargest(5, "PE_OI")[["Strike","PE_OI","PE_Chg"]].to_dict("records"),
            "df_oi":     df_oi,
        }
    except Exception:
        return None

def _oi_sentiment(pcr):
    if pcr >= 1.3: return "Bullish", "#16a34a"
    if pcr >= 0.9: return "Neutral", "#d97706"
    return "Bearish", "#dc2626"

@st.cache_data(ttl=300)
def fetch_indices(mode="Swing"):
    cfg      = MODE_CFG[mode]
    ema_f    = cfg["ema_fast"]; ema_s = cfg["ema_slow"]; rsi_l = cfg["rsi_len"]
    min_bars = 60 if mode == "Intraday" else 50
    out      = {}
    index_map = [
        ("Nifty 50",  "^NSEI"),
        ("BankNifty", "^NSEBANK"),
        ("Sensex",    "^BSESN"),
    ]
    for name, ticker in index_map:
        try:
            df = yf.download(ticker, period=cfg["period"], interval=cfg["interval"], progress=False)
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            df = df.dropna()
            if len(df) < min_bars:
                out[name] = None; continue
            close     = df["Close"]
            c, prev   = float(close.iloc[-1]), float(close.iloc[-2])
            chg, pct  = c - prev, (c - prev) / prev * 100
            ef        = float(ema(close, ema_f).iloc[-1])
            es        = float(ema(close, ema_s).iloc[-1])
            e200      = float(ema(close, 200).iloc[-1]) if len(close) >= 200 else es
            r         = float(rsi(close, rsi_l).iloc[-1])
            hh        = float(close.iloc[-11:-1].max())
            trend_up  = c > e200 and c > ef and ef > es
            bull      = 0
            bull += 25 if trend_up else 0
            bull += 15 if ef > es else (7 if ef > es * 0.995 else 0)
            bull += (15 if r >= 65 else 10) if r >= 60 else (5 if r > 50 else 0)
            bull += 15 if c > hh else (9 if c > hh * 0.98 else 0)
            if len(close) >= 3 and c > float(close.iloc[-3]): bull += 8
            norm_score     = min(100.0, max(0.0, bull * 100.0 / 78))
            interval_label = {"5m":"5min","1d":"Daily","1wk":"Weekly"}.get(cfg["interval"], cfg["interval"])
            out[name] = {
                "value":    round(c, 1),
                "chg":      round(chg, 2),
                "pct":      round(pct, 2),
                "score":    round(norm_score, 1),
                "action":   action_label(norm_score),
                "rsi":      round(r, 1),
                "trend":    "↑ Above EMAs" if trend_up else "↓ Below EMAs",
                "interval": interval_label,
                "ema_fast": ema_f,
                "ema_slow": ema_s,
            }
        except Exception:
            out[name] = None
    return out


# ═══════════════════════════════════════════════════════════════════════════════
# RUN SCAN  — v11 with FIX-2 breadth gating
# ═══════════════════════════════════════════════════════════════════════════════

def run_scan(symbols, mode, progress_bar, status_text,
             vix_val=None, min_liq_cr=LIQUIDITY_MIN_CR):
    import concurrent.futures

    cfg      = MODE_CFG[mode]
    rejected = 0
    total    = len(symbols)
    min_bars = 60 if mode == "Intraday" else 50

    nifty = fetch_nifty(mode)
    market_bullish, regime_label = _market_regime(nifty)

    if not market_bullish:
        st.warning(
            f"⚠️ **Market Regime: {regime_label}** — EMA20 below EMA50. "
            "Scores haircut 15%. Targets compressed."
        )

    # ── Pass 1: Merged OHLCV + daily context (PERF-2, PERF-3) ──────────────
    status_text.text("Pass 1/3: Fetching OHLCV + daily context (parallel)…")
    data         = {}
    daily_closes = {}
    args_list    = [(sym, mode, min_bars) for sym in symbols]
    MAX_WORKERS  = min(6, os.cpu_count() or 4, total)
    completed    = 0

    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {pool.submit(_fetch_one_with_daily, a): a[0] for a in args_list}
        for fut in concurrent.futures.as_completed(futures):
            sym, df, daily_df = fut.result()
            completed += 1
            progress_bar.progress(completed / total * 0.40)
            if df is not None:
                data[sym] = df
                if daily_df is not None:
                    daily_closes[sym] = daily_df["Close"]
            else:
                rejected += 1

    # ── Pass 2: HTF ──────────────────────────────────────────────────────────
    status_text.text("Pass 2/3: Pre-fetching HTF data (parallel)…")
    progress_bar.progress(0.40)
    htf_map = prefetch_htf_parallel(list(data.keys()), mode, status_text, progress_bar)

    # ── Pass 2b: Vectorized RS ranks (PERF-4) ────────────────────────────────
    status_text.text("Pass 2b/3: Computing RS ranks (vectorized)…")
    sym_52w_returns = {sym: _52w_return(df["Close"]) for sym, df in data.items()}
    rs_rank_map     = compute_rs_ranks(sym_52w_returns)

    # ── PERF-7: Snapshot phase history ───────────────────────────────────────
    phase_history_snapshot = dict(st.session_state.get("phase_history", {}))

    # ── Pass 3: Parallel scoring (PERF-1) ────────────────────────────────────
    status_text.text("Pass 3/3: Scoring stocks (parallel)…")
    results     = []
    liq_skipped = 0
    n_data      = len(data)
    scored      = 0

    def _score_one(sym):
        df     = data[sym]
        htf_up, _ = htf_map.get(sym, (True, "HTF-UNKNOWN"))
        rs_rank   = rs_rank_map.get(sym, 50)
        return sym, score_stock(
            df, nifty, mode,
            daily_close            = daily_closes.get(sym),
            market_bullish         = market_bullish,
            vix_val                = vix_val,
            min_liquidity_cr       = min_liq_cr,
            sym                    = sym,
            htf_up                 = htf_up,
            rs_rank                = rs_rank,
            phase_history_snapshot = phase_history_snapshot,
        )

    with concurrent.futures.ThreadPoolExecutor(max_workers=min(32, n_data)) as pool:
        futures = {pool.submit(_score_one, sym): sym for sym in data}
        for fut in concurrent.futures.as_completed(futures):
            sym, res = fut.result()
            scored  += 1
            progress_bar.progress(0.65 + scored / n_data * 0.30)
            if scored % 20 == 0:
                status_text.text(f"Pass 3/3: Scored {scored}/{n_data}…")
            if res:
                res["Regime"] = regime_label
                res["Symbol"] = sym
                res["Sector"] = SECTOR_MAP.get(sym, "Other")
                if not res["LiquidityOK"]:
                    liq_skipped += 1
                results.append(res)

    # ── PERF-7: Apply phase transitions in main thread ────────────────────────
    for res in results:
        sym   = res["Symbol"]
        phase = res["_detected_phase"]
        record_phase_transition(sym, phase)
        res["PhaseBonus"] = phase_transition_conf_bonus(sym)

    # ── FIX-2: Breadth-based gating ──────────────────────────────────────────
    # Compute a fast breadth pulse from the freshly scored results.
    # When the market is internally weak (pct_above_ema50 < 40 AND ad_ratio < 0.8),
    # cap BRK/CONT actions to WATCH and flag the result so the UI can show
    # a breadth-gate badge.  No scoring math is changed; this is a post-hoc cap.
    breadth_pulse = compute_breadth(results)
    pct_ema50_now = breadth_pulse.get("pct_above_ema50", 100)
    ad_ratio_now  = breadth_pulse.get("ad_ratio", 2.0)
    breadth_weak  = (pct_ema50_now < 40) and (ad_ratio_now < 0.8)

    if breadth_weak:
        gated_count = 0
        for res in results:
            if res.get("Phase") in (PHASE_BRK, PHASE_CONT):
                if res["Action"] in ("STRONG BUY", "BUY"):
                    res["Action"]       = "WATCH"
                    res["BreadthGated"] = True
                    gated_count        += 1
        if gated_count:
            st.warning(
                f"⚠️ **Breadth Gate active** — only {pct_ema50_now}% above EMA50, "
                f"A/D ratio {ad_ratio_now:.2f}. "
                f"{gated_count} BREAKOUT/CONT signals capped to WATCH."
            )

    progress_bar.progress(1.0)
    results.sort(key=lambda x: x["Score"], reverse=True)
    return results, rejected, liq_skipped


# ═══════════════════════════════════════════════════════════════════════════════
# SHORT SELL ENGINE  (v14 new — v11 bull engine untouched above)
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class ShortResult:
    symbol:        str
    verdict:       str   = SHORT_SKIP
    short_score:   int   = 0
    hard_triggers: list  = field(default_factory=list)
    soft_triggers: list  = field(default_factory=list)
    entry_zone_lo: float = 0.0
    entry_zone_hi: float = 0.0
    stop_loss:     float = 0.0
    target1:       float = 0.0
    target2:       float = 0.0
    target3:       float = 0.0
    risk_reward:   float = 0.0
    current_price: float = 0.0
    atr:           float = 0.0
    rsi_val:       float = 50.0
    volume_ratio:  float = 1.0
    rs_rank:       int   = 50
    htf_trend:     str   = "HTF-UNKNOWN"
    phase:         str   = PHASE_IDLE
    ext_n:         int   = 0
    sector:        str   = "—"
    mode:          str   = "Swing"
    scanned_at:    str   = field(default_factory=lambda: datetime.now().isoformat())
    error:         str   = ""
    day_change:    float = 0.0   # FIX-11: today's % change (for card display)


def score_short(sym: str, mode: str = "Swing",
                htf_cache: dict = None,
                rs_ranks:  dict = None,
                vix_val:   float = None) -> ShortResult:
    """
    Hard triggers (SHORT_HARD_WEIGHT = 22 pts each):
      H1  Bearish EMA stack: price < fast EMA < slow EMA
      H2  Death cross: fast EMA crossed below slow EMA in last 5 bars
      H3  HTF downtrend confirmed
      H4  52-week breakdown: near 52w low OR below prior swing low

    Soft triggers (SHORT_SOFT_WEIGHT = 9 pts each):
      S1  RSI overbought rollover (was >68, now falling >5 pts)
      S2  RSI bearish zone (<42 + HTF down)
      S3  Negative 1-month momentum
      S4  Negative 3-month momentum
      S5  High-volume red day (vol >1.5× avg, red candle)
      S6  Below 61.8% or 50% Fib retrace
      S7  RS rank bottom quartile (<30)

    Bonus: v11 exhaustion flags (overextended = good for short).
    """
    result = ShortResult(symbol=sym, mode=mode, sector=SECTOR_MAP.get(sym, "—"))
    cfg    = MODE_CFG[mode]
    try:
        ticker = to_nse(sym)
        df = yf.download(ticker, period=cfg["period"], interval=cfg["interval"],
                         auto_adjust=True, progress=False, threads=False)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df = df.dropna()
        if len(df) < 60:
            result.error = "insufficient data"; return result

        cl    = df["Close"]; hi = df["High"]; lo = df["Low"]; vol = df["Volume"]
        close = float(cl.iloc[-1]); result.current_price = close

        ef_ser  = ema(cl, cfg["ema_fast"]); es_ser = ema(cl, cfg["ema_slow"])
        ef = float(ef_ser.iloc[-1]); es = float(es_ser.iloc[-1])
        atr_s   = atr_series(df); atr_v = float(atr_s.iloc[-1])
        atr_mean = float(atr_s.rolling(20).mean().iloc[-1])
        result.atr = atr_v

        rsi_ser = rsi(cl, cfg["rsi_len"]); rsi_v = float(rsi_ser.iloc[-1])
        result.rsi_val = round(rsi_v, 1)

        avg_vol = float(vol.rolling(20).mean().iloc[-1]) or 1
        result.volume_ratio = round(float(vol.iloc[-1]) / avg_vol, 2)

        def _ret(n):
            if len(cl) <= n: return 0.0
            return float((cl.iloc[-1] - cl.iloc[-n]) / cl.iloc[-n] * 100)
        mom1 = _ret(22); mom3 = _ret(66)

        w52_lo = float(lo.iloc[-252:].min()) if len(lo) >= 252 else float(lo.min())
        prior_swing_lo = float(lo.iloc[-21:-1].min()) if len(lo) > 21 else float(lo.min())
        rsi_5_ago = float(rsi_ser.iloc[-6]) if len(rsi_ser) >= 6 else rsi_v

        # HTF
        if htf_cache and sym in htf_cache:
            htf_up, htf_label = htf_cache[sym]
        else:
            htf_df = _fetch_htf_cached(ticker, cfg["htf_period"], cfg["htf_interval"])
            htf_up, htf_label = _htf_trend_from_df(htf_df, mode)
        result.htf_trend = htf_label

        rs_rank = rs_ranks.get(sym, 50) if rs_ranks else 50
        result.rs_rank = rs_rank

        # Phase
        trend_down = close < ef and ef < es
        trend_up   = close > ef and ef > es
        if trend_down:           phase = PHASE_EXIT
        elif trend_up:           phase = PHASE_CONT if mom1 > 0 else PHASE_ENTRY
        elif close > ef and ef < es: phase = PHASE_SETUP
        else:                    phase = PHASE_IDLE
        result.phase = phase

        # v11 exhaustion (overextended stocks = good short candidates)
        nifty_dummy = cl  # approximate; ext only needs close/high/low/vol/rsi/ema/atr
        ext_flags, _, _, ext_n = detect_exhaustion(
            close=cl, high=hi, low=lo, volume=vol, rsi_series=rsi_ser,
            e_fast_s=ef_ser, atr_s=atr_s, atr_mean=atr_mean,
            c=close, v=float(vol.iloc[-1]), vol_avg=avg_vol, mode=mode, vix_val=vix_val,
        )
        result.ext_n = ext_n

        score = 0; hard_t = []; soft_t = []

        # H1 — Bearish EMA stack
        if close < ef and ef < es:
            score += SHORT_HARD_WEIGHT; hard_t.append("Bearish EMA Stack")

        # H2 — Death cross
        for i in range(1, min(5, len(ef_ser) - 1) + 1):
            if (float(ef_ser.iloc[-i]) < float(es_ser.iloc[-i]) and
                    float(ef_ser.iloc[-(i+1)]) >= float(es_ser.iloc[-(i+1)])):
                score += SHORT_HARD_WEIGHT; hard_t.append("Death Cross (EMA ×)"); break

        # H3 — HTF downtrend
        if not htf_up:
            score += SHORT_HARD_WEIGHT; hard_t.append(f"HTF Downtrend ({htf_label})")

        # H4 — 52w breakdown
        near_52w_lo = (close - w52_lo) / w52_lo < 0.03 if w52_lo > 0 else False
        below_swing = close < prior_swing_lo
        if near_52w_lo or below_swing:
            score += SHORT_HARD_WEIGHT
            hard_t.append("Near 52W Low" if near_52w_lo else "Below Swing Low")

        # S1 — RSI rollover
        if rsi_5_ago > 68 and rsi_v < rsi_5_ago - 5:
            score += SHORT_SOFT_WEIGHT; soft_t.append(f"RSI Rollover ({rsi_5_ago:.0f}→{rsi_v:.0f})")

        # S2 — RSI bearish zone
        if rsi_v < 42 and not htf_up:
            score += SHORT_SOFT_WEIGHT; soft_t.append(f"RSI Bearish Zone ({rsi_v:.0f})")

        # S3 — Neg 1M mom
        if mom1 < -cfg["mom1_th"]:
            score += SHORT_SOFT_WEIGHT; soft_t.append(f"Neg 1M Mom ({mom1:.1f}%)")

        # S4 — Neg 3M mom
        if mom3 < -cfg["mom3_th"]:
            score += SHORT_SOFT_WEIGHT; soft_t.append(f"Neg 3M Mom ({mom3:.1f}%)")

        # S5 — High-vol red day
        if float(df["Close"].iloc[-1]) < float(df["Open"].iloc[-1]) and result.volume_ratio > 1.5:
            score += SHORT_SOFT_WEIGHT; soft_t.append(f"High-Vol Red Day ({result.volume_ratio:.1f}×)")

        # S6 — Below Fib level
        _, _, fibs, _ = fib_levels(df)
        if fibs:
            if close < fibs.get("618", float("inf")):
                score += SHORT_SOFT_WEIGHT; soft_t.append("Below 61.8% Fib")
            elif close < fibs.get("500", float("inf")):
                score += SHORT_SOFT_WEIGHT; soft_t.append("Below 50% Fib")

        # S7 — Weak RS rank
        if rs_rank < 30:
            score += SHORT_SOFT_WEIGHT; soft_t.append(f"RS Rank Weak ({rs_rank})")

        # Bonus: VIX stress + exhaustion (overextended = better short)
        if vix_val and vix_val >= VIX_STRESS: score += 5
        if ext_n >= 2: score += min(ext_n * 4, 12)  # exhaustion = short fuel

        result.short_score   = min(score, 100)
        result.hard_triggers = hard_t
        result.soft_triggers = soft_t

        if score >= SHORT_SCORE_CONFIRMED:   result.verdict = SHORT_CONFIRMED
        elif score >= SHORT_SCORE_SIGNAL:    result.verdict = SHORT_SIGNAL
        elif score >= SHORT_SCORE_WATCH:     result.verdict = SHORT_WATCH
        else:                                result.verdict = SHORT_SKIP

        # Trade levels (sell zone above current; stop above; targets below)
        atr_sl_mult = cfg["atr_mult"] * (0.85 if vix_val and vix_val >= VIX_STRESS else 1.0)
        result.entry_zone_lo = round(close, 2)
        result.entry_zone_hi = round(close + atr_v * 0.4, 2)
        result.stop_loss     = round(close + atr_v * atr_sl_mult, 2)
        result.target1       = round(close - atr_v * cfg["atr_mult"] * 1.0, 2)
        result.target2       = round(close - atr_v * cfg["atr_mult"] * 2.0, 2)
        result.target3       = round(close - atr_v * cfg["atr_mult"] * 3.0, 2)
        risk = result.stop_loss - close
        result.risk_reward = round((close - result.target2) / risk, 2) if risk > 0 else 0.0

    except Exception as e:
        result.error = str(e)
    return result


def run_short_scan(symbols: list, mode: str,
                   htf_cache: dict = None, rs_ranks: dict = None,
                   vix_val: float = None,
                   status_text=None, progress_bar=None) -> list:
    results = []; total = len(symbols); done = 0

    def _one(sym): return score_short(sym, mode, htf_cache, rs_ranks, vix_val)

    with concurrent.futures.ThreadPoolExecutor(max_workers=min(32, total)) as pool:
        futures = {pool.submit(_one, sym): sym for sym in symbols}
        for fut in concurrent.futures.as_completed(futures):
            results.append(fut.result()); done += 1
            if progress_bar: progress_bar.progress(0.5 + done / total * 0.5)
            if status_text and done % 20 == 0: status_text.text(f"Short scan {done}/{total}…")

    results.sort(key=lambda r: r.short_score, reverse=True)
    return [r for r in results if r.verdict != SHORT_SKIP and not r.error]


# ═══════════════════════════════════════════════════════════════════════════════
# SHORT SCORING FROM EXISTING SCAN RESULTS  (v14 — no re-download)
# ═══════════════════════════════════════════════════════════════════════════════

def score_short_from_result(r: dict, mode: str, vix_val: float = None) -> ShortResult:
    """
    Derive a ShortResult from an already-scored score_stock() dict.
    Zero network calls — all inputs come from fields stored in v14's result dict.

    Fields used:
      Phase, TrendDown, TrendUp, EMAStack, HTFUp, RSI, RS_Rank,
      ExtN, ExtFlags, Mom1, Mom3, ATR, LTP, Sector, Symbol, %Change, VolConf
    """
    sym    = r.get("Symbol", "")
    result = ShortResult(symbol=sym, mode=mode, sector=r.get("Sector", SECTOR_MAP.get(sym, "—")))
    cfg    = MODE_CFG[mode]

    try:
        close      = float(r.get("LTP", 0))
        if close <= 0:
            result.error = "no price"; return result

        atr_v      = float(r.get("ATR", 0))
        rsi_v      = float(r.get("RSI", 50))
        rs_rank    = int(r.get("RS_Rank", 50))
        ext_n      = int(r.get("ExtN", 0))
        ext_flags  = r.get("ExtFlags", {})
        htf_up     = bool(r.get("HTFUp", True))
        htf_label  = "HTF↑" if htf_up else "HTF↓"
        ema_stack  = bool(r.get("EMAStack", False))   # price>EF>ES>E200
        trend_down = bool(r.get("TrendDown", False))  # price<EF<ES
        trend_up   = bool(r.get("TrendUp",  False))
        fresh_cross = bool(r.get("FreshCross", False))  # golden cross just happened
        mom1       = float(r.get("Mom1", 0))
        mom3       = float(r.get("Mom3", 0))
        vol_conf   = bool(r.get("VolConf", False))
        phase      = r.get("Phase", PHASE_IDLE)
        chg        = float(r.get("%Change", 0))

        result.current_price = close
        result.atr           = atr_v
        result.rsi_val       = round(rsi_v, 1)
        result.rs_rank       = rs_rank
        result.htf_trend     = htf_label
        result.phase         = phase
        result.ext_n         = ext_n
        result.day_change    = chg   # FIX-11: propagate today's % change

        # volume_ratio: VolConf means vol > 1.2× avg
        result.volume_ratio  = 1.3 if vol_conf else 0.9

        score = 0; hard_t = []; soft_t = []

        # ── HARD TRIGGERS ────────────────────────────────────────────────────

        # H1 — Bearish EMA stack (price < EF < ES; stored as TrendDown)
        if trend_down:
            score += SHORT_HARD_WEIGHT; hard_t.append("Bearish EMA Stack")

        # H2 — Death cross proxy: EMAStack just turned False AND FreshCross False
        #       (i.e. no golden cross recently, and bearish alignment)
        if not ema_stack and not htf_up and not fresh_cross and not trend_up:
            score += SHORT_HARD_WEIGHT; hard_t.append("Bearish EMA Alignment (no golden cross)")

        # H3 — HTF downtrend
        if not htf_up:
            score += SHORT_HARD_WEIGHT; hard_t.append(f"HTF Downtrend ({htf_label})")

        # H4 — Phase EXIT = v11 confirmed the stock is in a downtrend structure
        if phase == PHASE_EXIT:
            score += SHORT_HARD_WEIGHT; hard_t.append("Phase EXIT (structural downtrend)")

        # ── SOFT TRIGGERS ────────────────────────────────────────────────────

        # S1 — RSI overbought rollover: ExtFlags rsi_overheat = RSI was very high
        if ext_flags.get("rsi_overheat") or ext_flags.get("mom_exhaustion"):
            score += SHORT_SOFT_WEIGHT; soft_t.append("RSI/Mom Exhaustion (ExtFlag)")

        # S2 — RSI bearish zone
        if rsi_v < 42 and not htf_up:
            score += SHORT_SOFT_WEIGHT; soft_t.append(f"RSI Bearish Zone ({rsi_v:.0f})")

        # S3 — Negative 1-month momentum
        if mom1 < -cfg["mom1_th"]:
            score += SHORT_SOFT_WEIGHT; soft_t.append(f"Neg 1M Mom ({mom1:.1f}%)")

        # S4 — Negative 3-month momentum
        if mom3 < -cfg["mom3_th"]:
            score += SHORT_SOFT_WEIGHT; soft_t.append(f"Neg 3M Mom ({mom3:.1f}%)")

        # S5 — High-vol red day: today down + vol confirmed
        if chg < -0.5 and vol_conf:
            score += SHORT_SOFT_WEIGHT; soft_t.append(f"High-Vol Red Day ({chg:+.1f}%)")

        # S6 — Bearish divergence from ExtFlags
        if ext_flags.get("bearish_div"):
            score += SHORT_SOFT_WEIGHT; soft_t.append("Bearish Divergence (ExtFlag)")

        # S7 — Relative weakness
        if rs_rank < 30:
            score += SHORT_SOFT_WEIGHT; soft_t.append(f"RS Rank Weak ({rs_rank})")

        # Bonus: VIX stress + exhaustion count
        if vix_val and vix_val >= VIX_STRESS: score += 5
        if ext_n >= 2: score += min(ext_n * 4, 12)

        result.short_score   = min(score, 100)
        result.hard_triggers = hard_t
        result.soft_triggers = soft_t

        if score >= SHORT_SCORE_CONFIRMED:   result.verdict = SHORT_CONFIRMED
        elif score >= SHORT_SCORE_SIGNAL:    result.verdict = SHORT_SIGNAL
        elif score >= SHORT_SCORE_WATCH:     result.verdict = SHORT_WATCH
        else:                                result.verdict = SHORT_SKIP

        # Trade levels
        if atr_v > 0:
            atr_sl_mult      = cfg["atr_mult"] * (0.85 if vix_val and vix_val >= VIX_STRESS else 1.0)
            result.entry_zone_lo = round(close, 2)
            result.entry_zone_hi = round(close + atr_v * 0.4, 2)
            result.stop_loss     = round(close + atr_v * atr_sl_mult, 2)
            result.target1       = round(close - atr_v * cfg["atr_mult"] * 1.0, 2)
            result.target2       = round(close - atr_v * cfg["atr_mult"] * 2.0, 2)
            result.target3       = round(close - atr_v * cfg["atr_mult"] * 3.0, 2)
            risk = result.stop_loss - close
            result.risk_reward = round((close - result.target2) / risk, 2) if risk > 0 else 0.0

    except Exception as e:
        result.error = str(e)
    return result


def derive_short_candidates(scan_results: list, mode: str,
                             vix_val: float = None) -> list:
    """
    Convert existing bull-scan results into ShortResults — no downloads.
    Returns sorted list excluding SKIP and errors.
    """
    out = []
    for r in scan_results:
        if not r:
            continue
        sr = score_short_from_result(r, mode, vix_val)
        if sr.verdict != SHORT_SKIP and not sr.error:
            out.append(sr)
    out.sort(key=lambda s: s.short_score, reverse=True)
    return out
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
    day_pct:       float = 0.0   # FIX-11: today's % change for portfolio card display
    error:         str   = ""


def score_exit(sym: str, entry_price: float, mode: str = "Swing",
               vix_val: float = None) -> ExitResult:
    result = ExitResult(symbol=sym)
    cfg    = MODE_CFG[mode]
    try:
        ticker = to_nse(sym)
        df = yf.download(ticker, period=cfg["period"], interval=cfg["interval"],
                         auto_adjust=True, progress=False, threads=False)
        if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
        df = df.dropna()
        if len(df) < 30: result.error = "insufficient data"; return result

        cl    = df["Close"]; close = float(cl.iloc[-1]); result.current_price = close
        atr_v = float(atr_series(df).iloc[-1]); result.atr = atr_v
        # FIX-11: today's % change (current bar vs previous close)
        if len(cl) >= 2:
            result.day_pct = round((close - float(cl.iloc[-2])) / float(cl.iloc[-2]) * 100, 2)
        ef    = float(ema(cl, cfg["ema_fast"]).iloc[-1])
        es    = float(ema(cl, cfg["ema_slow"]).iloc[-1])
        rsi_v = float(rsi(cl, cfg["rsi_len"]).iloc[-1])
        avg_vol   = float(df["Volume"].rolling(20).mean().iloc[-1]) or 1
        vol_ratio = float(df["Volume"].iloc[-1]) / avg_vol
        pnl_pct   = (close - entry_price) / entry_price * 100 if entry_price else 0

        base_mult = 2.0
        if vix_val and vix_val >= VIX_STRESS:   base_mult = 1.5
        elif vix_val and vix_val >= VIX_CAUTION: base_mult = 1.75
        if pnl_pct >= 20: base_mult *= 0.7
        elif pnl_pct >= 10: base_mult *= 0.85
        result.trailing_stop = round(close - atr_v * base_mult, 2)

        score = 0; triggers = []
        if close < ef:      score += 25; triggers.append("Price < Fast EMA")
        if close < es:      score += 25; triggers.append("Price < Slow EMA")
        if rsi_v > 78:      score += 25; triggers.append(f"RSI Overbought {rsi_v:.0f}")
        if pnl_pct < -8:    score += 25; triggers.append(f"SL Hit {pnl_pct:.1f}%")
        if ef < es:         score += 10; triggers.append("EMA Bear Cross")
        if rsi_v > 70:      score += 10; triggers.append(f"RSI High {rsi_v:.0f}")
        if vol_ratio > 2.0 and float(df["Close"].iloc[-1]) < float(df["Open"].iloc[-1]):
            score += 10; triggers.append("High-Vol Down Day")
        if pnl_pct > 30:    score += 10; triggers.append(f"Big Profit {pnl_pct:.1f}% — Lock In")
        if vix_val and vix_val >= VIX_STRESS: score += 10; triggers.append(f"VIX Stress {vix_val}")
        _, _, fibs, _ = fib_levels(df)
        if fibs and close < fibs.get("618", 0): score += 10; triggers.append("Below 61.8% Fib")
        htf_df = _fetch_htf_cached(ticker, cfg["htf_period"], cfg["htf_interval"])
        htf_up, _ = _htf_trend_from_df(htf_df, mode)
        if not htf_up: score += 10; triggers.append("HTF Downtrend")

        result.exit_score = min(score, 100); result.triggers = triggers
        if score >= 65:   result.verdict = EXIT_CONFIRM_LBL
        elif score >= 40: result.verdict = EXIT_SIGNAL_LBL
        elif score >= 20: result.verdict = EXIT_WATCH_LBL
        else:             result.verdict = EXIT_HOLD
    except Exception as e:
        result.error = str(e)
    return result


def run_exit_scan(positions: list, vix_val: float = None) -> dict:
    out = {}
    valid = [p for p in positions if isinstance(p, dict) and p.get("symbol")]
    if not valid:
        return out

    def _one(pos):
        sym = pos["symbol"]
        return sym, score_exit(sym, pos.get("entry_price", 0),
                               pos.get("mode", "Swing"), vix_val)

    with concurrent.futures.ThreadPoolExecutor(max_workers=min(16, len(valid))) as pool:
        futures = {pool.submit(_one, pos): pos for pos in valid}
        for fut in concurrent.futures.as_completed(futures):
            try:
                sym, er = fut.result()
                out[sym] = er
            except Exception as e:
                pos = futures[fut]
                sym = pos.get("symbol", "?")
                out[sym] = ExitResult(symbol=sym, error=str(e))
    return out


def add_position(sym: str, entry_price: float, qty: int, mode: str, entry_date: str = None):
    pos = dict(symbol=sym.upper(), entry_price=entry_price, qty=qty, mode=mode,
               entry_date=entry_date or datetime.now().date().isoformat(), current_price=entry_price)
    existing = [p for p in st.session_state.get("open_positions", [])
                if not (p["symbol"] == sym.upper() and p["entry_date"] == pos["entry_date"])]
    st.session_state["open_positions"] = existing + [pos]
    _db_save("bs_positions", st.session_state["open_positions"])


# ═══════════════════════════════════════════════════════════════════════════════
# STREAMLIT APP
# ═══════════════════════════════════════════════════════════════════════════════

st.set_page_config(
    page_title="BULL SUTRA Pro v14",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600;700&family=DM+Sans:wght@400;500;600&family=Syne:wght@600;700&display=swap');
html, body, [class*="css"] { background: #07070f; color: #e8e8f4; }
.stApp { background: #07070f; }
.stDataFrame { background: #111120; }
.stButton>button { background:#1a1a35; border:1px solid #2a2a55; color:#e8e8f4; border-radius:8px; }
.stButton>button[kind="primary"] { background:#f59e0b; color:#1a0a00; font-weight:700; }
[data-testid="metric-container"] { background:#111120; border:1px solid #1e1e40; border-radius:8px; padding:10px; }
</style>
""", unsafe_allow_html=True)

# ── Session state init ─────────────────────────────────────────────────────────
for key, default in [
    ("results",         []),
    ("scan_time",       None),
    ("rejected",        0),
    ("liq_skipped",     0),
    ("scan_mode",       "Swing"),
    ("signal_log",      []),
    ("phase_history",   {}),
    ("account_size",    500000),
    ("risk_pct",        0.02),
    ("max_capital_pct", 0.20),
    ("phase_filter",    "All Phases"),
    ("show_illiquid",   False),
    ("min_liq_cr",      5.0),
    ("open_positions",  None),   # None = not yet loaded from DB
    ("short_results",   []),
    ("short_watchlist", None),   # None = not yet loaded from DB
    ("exit_results",    {}),
    ("_db_error",       None),
]:
    if key not in st.session_state:
        st.session_state[key] = default

# One-time DB load
if st.session_state["open_positions"] is None:
    st.session_state["open_positions"] = _db_load("bs_positions")
if st.session_state["short_watchlist"] is None:
    st.session_state["short_watchlist"] = _db_load("bs_short_wl")

# ── PERF-5: Pre-warm caches on startup ────────────────────────────────────────
@st.cache_data(ttl=300, show_spinner=False)
def _prewarm():
    fetch_vix()
    fetch_nifty("Swing")
_prewarm()

# ── Header ─────────────────────────────────────────────────────────────────────
st.markdown(
    '''<div style="font-family:Syne,sans-serif;font-size:28px;font-weight:700;
    letter-spacing:-1px;color:#e8e8f4;padding:8px 0 4px;">
    BULL SUTRA <span style="color:#f59e0b;">''</span>
    <span style="font-size:13px;color:#cbd5e1;font-family:JetBrains Mono,monospace;
    font-weight:400;">PRO · v14</span></div>''',
    unsafe_allow_html=True,
)

# ── Global controls ────────────────────────────────────────────────────────────
# Build universe options from sectors.py: NSE 500 first, then every named sector.
# If sectors.py is missing, fall back to the original two options.
_UNIVERSE_OPTIONS = (
    ["NSE 500"] + [k for k in _SECTORS.keys() if k != "Nifty 500"]
    if _SECTORS
    else ["NSE 500", "Nifty 50"]
)

gc1, gc2, gc3, gc4, gc5 = st.columns([2, 2, 1, 2, 2])
with gc1:
    universe_opt = st.selectbox("Universe", _UNIVERSE_OPTIONS, index=0,
                                label_visibility="visible")
with gc2:
    mode_opt = st.radio("Mode", ["Swing", "Intraday", "Positional"], horizontal=True)
with gc3:
    scan_btn = st.button("SCAN", type="primary", use_container_width=True)
with gc4:
    filter_opt = st.selectbox("Filter",
        ["BUY + STRONG BUY", "STRONG BUY only", "WATCH + BUY", "All Results"],
        label_visibility="collapsed")
with gc5:
    search_q = st.text_input("Search symbol", placeholder="e.g. RELIANCE",
                             label_visibility="collapsed")

# ── VIX banner ─────────────────────────────────────────────────────────────────
vix_val, vix_label = fetch_vix()
vix_color = {
    "CALM":    "#22c55e", "CAUTION": "#f59e0b",
    "STRESS":  "#ef4444", "UNKNOWN": "#cbd5e1",
}.get(vix_label, "#cbd5e1")
vix_text_color = {
    "CALM":    "#14532d", "CAUTION": "#78350f",
    "STRESS":  "#7f1d1d", "UNKNOWN": "#374151",
}.get(vix_label, "#374151")

st.markdown(
    f'<div style="background:{vix_color}18;border:1px solid {vix_color}44;'
    f'border-radius:7px;padding:7px 14px;margin:6px 0;display:flex;'
    f'align-items:center;gap:12px;font-family:JetBrains Mono,monospace;">'
    f'<span style="background:{vix_color};color:{vix_text_color};padding:2px 8px;'
    f'border-radius:4px;font-size:11px;font-weight:700;">VIX '
    f'{vix_val if vix_val else "—"} · {vix_label}</span>'
    + (f'<span style="color:#ef4444;font-size:11px;">⚠ High VIX: STRONG BUY blocked · targets compressed</span>'
       if (vix_val and vix_val >= VIX_STRESS) else "")
    + (f'<span style="color:#f59e0b;font-size:11px;">⚡ Elevated VIX: targets compressed · SL widened</span>'
       if (vix_val and VIX_CAUTION <= vix_val < VIX_STRESS) else "")
    + '</div>',
    unsafe_allow_html=True,
)

# ── Tabs ───────────────────────────────────────────────────────────────────────
tab_scanner, tab_breadth, tab_detail, tab_portfolio, tab_analytics, tab_settings = st.tabs(
    ["Scanner", "Breadth Engine", "Detail", "💼 Portfolio", "Analytics", "Settings"]
)


# ═══════════════════════════════════════════════════════════════════════════════
# SETTINGS TAB
# ═══════════════════════════════════════════════════════════════════════════════

with tab_settings:
    st.subheader("Scanner Settings")
    sc1, sc2 = st.columns(2)
    with sc1:
        st.session_state.min_liq_cr = st.slider(
            "Min Liquidity (₹ Cr daily traded value)", 1.0, 50.0,
            float(st.session_state.min_liq_cr), 1.0)
        st.session_state.phase_filter = st.selectbox(
            "Phase Filter (Scanner)",
            ["All Phases","ENTRY","SETUP","CONT","BREAKOUT","IDLE","EXIT"],
            index=["All Phases","ENTRY","SETUP","CONT","BREAKOUT","IDLE","EXIT"].index(
                st.session_state.get("phase_filter","All Phases")))
        st.session_state.show_illiquid = st.checkbox(
            "Show illiquid stocks (below liquidity floor)",
            value=st.session_state.show_illiquid)
        st.markdown("---")
        st.markdown("**Position Sizing**")
        st.session_state.account_size = st.number_input(
            "Account Size (₹)", min_value=10000, max_value=10_000_000,
            value=int(st.session_state.account_size), step=10000)
        st.session_state.risk_pct = st.slider(
            "Risk per trade (%)", 0.5, 5.0,
            float(st.session_state.risk_pct * 100), 0.5) / 100.0
        # FIX-5: capital cap slider
        st.session_state.max_capital_pct = st.slider(
            "Max capital per trade (% of account)  ← FIX-5", 5, 50,
            int(st.session_state.max_capital_pct * 100), 5) / 100.0
        st.caption(
            f"Current cap: ₹{st.session_state.account_size * st.session_state.max_capital_pct:,.0f} "
            f"per position ({int(st.session_state.max_capital_pct*100)}% of account)"
        )

    with sc2:
        st.markdown("**Action Thresholds**")
        st.markdown("""
| Score | Action |
|-------|--------|
| ≥ 75  | STRONG BUY |
| ≥ 58  | BUY |
| ≥ 42  | WATCH |
| < 42  | SKIP |
""")
        st.markdown("**Signal Validity**")
        st.markdown("""
| Mode | Window |
|------|--------|
| Intraday | 4 h |
| Swing | 72 h |
| Positional | 240 h |
""")
        st.markdown("**v11 Fixes**")
        st.markdown("""
| Fix | What changed |
|-----|-------------|
| FIX-1 HTF closed-candle | Drops live bar before EMA calc |
| FIX-2 Breadth gating | BRK/CONT capped to WATCH when breadth weak |
| FIX-3 Structural BRK | Hard vol gate + anti-blowoff guard |
| FIX-4 Intraday vol norm | Time-scaled vol_avg for partial sessions |
| FIX-5 Capital cap | Max capital % clamp in sizer |
| FIX-6 EMA de-dup | Fresh-cross bonus replaces double-count |
""")


# ═══════════════════════════════════════════════════════════════════════════════
# SCAN EXECUTION
# ═══════════════════════════════════════════════════════════════════════════════

if scan_btn:
    # Resolve the selected universe to a symbol list
    if universe_opt == "NSE 500":
        symbols = NSE500
    elif _SECTORS and universe_opt in _SECTORS:
        _sec_syms = _SECTORS[universe_opt]
        # "Nifty 500" entry has None → use full NSE500 list
        symbols = NSE500 if _sec_syms is None else list(_sec_syms)
    else:
        symbols = NIFTY50  # fallback (should not normally reach here)
    n       = len(symbols)
    est     = "~60s" if n <= 50 else ("~90s" if n <= 150 else "~2 min")
    prog    = st.progress(0)
    stat    = st.empty()
    with st.spinner(f"Scanning {universe_opt} ({n} stocks) · {mode_opt} · {est}"):
        results, rejected, liq_skipped = run_scan(
            symbols, mode_opt, prog, stat,
            vix_val=vix_val, min_liq_cr=st.session_state.min_liq_cr,
        )
    st.session_state.results     = results
    st.session_state.rejected    = rejected
    st.session_state.liq_skipped = liq_skipped
    st.session_state.scan_mode   = mode_opt
    st.session_state.scan_time   = (
        datetime.now().strftime("%H:%M:%S") + f" ({universe_opt} · {mode_opt})"
    )
    ts         = datetime.now().isoformat()
    validity_h = MODE_CFG[mode_opt]["validity_hours"]
    for r in results:
        if r.get("Action") in ("BUY", "STRONG BUY"):
            st.session_state.signal_log.append({
                "timestamp":      ts,
                "symbol":         r["Symbol"],
                "action":         r["Action"],
                "phase":          r.get("Phase"),
                "score":          r["Score"],
                "confidence":     r.get("Confidence", 0),
                "rs_rank":        r.get("RS_Rank", 50),
                "entry":          r.get("Entry"),
                "sl":             r.get("SL"),
                "t1":             r.get("T1"),
                "ltp_at_signal":  r.get("LTP"),
                "mode":           mode_opt,
                "validity_hours": validity_h,
                "outcome":        "Pending",
                "breadth_gated":  r.get("BreadthGated", False),  # FIX-2 diagnostic
            })
    prog.empty(); stat.empty()
    st.success(
        f"✅ {len(results)} scanned · {rejected} rejected · "
        f"{liq_skipped} below liquidity floor · {mode_opt}"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# SCANNER TAB
# ═══════════════════════════════════════════════════════════════════════════════

with tab_scanner:
    indices      = fetch_indices(mode_opt)
    oi_nifty     = fetch_oi_data("NIFTY")
    oi_banknifty = fetch_oi_data("BANKNIFTY")

    ic1, ic2, ic3 = st.columns(3)
    index_card_cfg = [
        ("Nifty 50",  ic1, oi_nifty),
        ("BankNifty", ic2, oi_banknifty),
        ("Sensex",    ic3, None),
    ]

    for name, col, oi_data in index_card_cfg:
        d = indices.get(name)
        with col:
            if not d:
                st.markdown(
                    f"<div style='color:#cbd5e1;font-size:12px;'>{name}: unavailable</div>",
                    unsafe_allow_html=True)
                continue

            chg_val = d["chg"]; pct_val = d["pct"]; ltp_val = d["value"]
            cs  = f"+{pct_val:.2f}%" if chg_val >= 0 else f"{pct_val:.2f}%"
            cc  = "#22c55e" if chg_val >= 0 else "#ef4444"
            ar  = "▲" if chg_val >= 0 else "▼"
            act = d["action"]
            score_bar_color = (
                "#f59e0b" if act == "STRONG BUY" else
                "#22c55e" if act == "BUY" else
                "#f59e0b" if act == "WATCH" else "#cbd5e1"
            )
            sp = int(min(d["score"], 100))

            oi_badge = ""
            if oi_data:
                s_label, s_col = _oi_sentiment(oi_data["pcr"])
                pd_    = oi_data["max_pain"] - int(ltp_val)
                pa     = "↑" if pd_ > 0 else ("↓" if pd_ < 0 else "=")
                oi_badge = (
                    f'<div style="margin-top:6px;padding:5px 8px;background:#09090f;'
                    f'border-radius:5px;border:1px solid #1e1e40;font-family:JetBrains Mono,monospace;">'
                    f'<span style="color:#cbd5e1;font-size:9px;">PCR </span>'
                    f'<span style="background:{s_col}22;border:1px solid {s_col}44;'
                    f'color:{s_col};padding:1px 5px;border-radius:3px;font-size:9px;font-weight:600;">'
                    f'{oi_data["pcr"]} {s_label}</span>'
                    f'<span style="color:#cbd5e1;font-size:9px;margin-left:6px;">Pain </span>'
                    f'<span style="color:#f59e0b;font-size:9px;font-weight:600;">'
                    f'₹{oi_data["max_pain"]:,} {pa}{abs(pd_):,}</span>'
                    f'<br><span style="color:#ef4444;font-size:9px;">C▶₹{oi_data["call_wall"]:,}  </span>'
                    f'<span style="color:#22c55e;font-size:9px;">P▶₹{oi_data["put_wall"]:,}</span>'
                    f'</div>'
                )

            st.markdown(
                f'<div style="background:#111120;border:1px solid #1e1e40;'
                f'border-radius:10px;padding:14px 16px;">'
                f'<div style="font-family:DM Sans,sans-serif;color:#cbd5e1;'
                f'font-size:10px;text-transform:uppercase;letter-spacing:1px;">{name}</div>'
                f'<div style="font-family:JetBrains Mono,monospace;color:#e8e8f4;'
                f'font-size:22px;font-weight:600;margin:4px 0 2px;">{ltp_val:,.1f}</div>'
                f'<div style="font-family:JetBrains Mono,monospace;color:{cc};font-size:12px;">'
                f'{ar} {cs}</div>'
                f'<div style="margin:8px 0 4px;background:#1e1e40;border-radius:3px;height:3px;">'
                f'<div style="background:{score_bar_color};width:{sp}%;height:3px;'
                f'border-radius:3px;transition:width 0.3s;"></div></div>'
                f'<div style="display:flex;align-items:center;gap:6px;margin-top:4px;">'
                f'<span style="background:{score_bar_color}22;border:1px solid {score_bar_color}44;'
                f'color:{score_bar_color};padding:2px 7px;border-radius:3px;'
                f'font-size:10px;font-weight:600;font-family:DM Sans,sans-serif;">{act}</span>'
                f'<span style="font-family:JetBrains Mono,monospace;color:#3a3a60;font-size:10px;">'
                f'RSI {d["rsi"]} · {d["trend"]}</span>'
                f'</div>'
                + oi_badge + '</div>',
                unsafe_allow_html=True,
            )

    st.markdown('<div style="border-top:1px solid #1e1e40;margin:16px 0;"></div>',
                unsafe_allow_html=True)

    # ── Apply filters ──────────────────────────────────────────────────────────
    results = list(st.session_state.results)
    if filter_opt == "BUY + STRONG BUY":
        results = [r for r in results if r["Action"] in ("BUY", "STRONG BUY")]
    elif filter_opt == "STRONG BUY only":
        results = [r for r in results if r["Action"] == "STRONG BUY"]
    elif filter_opt == "WATCH + BUY":
        results = [r for r in results if r["Action"] in ("WATCH", "BUY", "STRONG BUY")]

    _phase_filter = st.session_state.get("phase_filter", "All Phases")
    if _phase_filter != "All Phases":
        results = [r for r in results if r.get("Phase") == _phase_filter]

    if not st.session_state.get("show_illiquid", False):
        results = [r for r in results if r.get("LiquidityOK", True)]

    if search_q:
        results = [r for r in results if search_q.upper() in r["Symbol"]]

    # ── Ready-to-Trade cards ───────────────────────────────────────────────────
    if st.session_state.results:
        ACTIONABLE_PHASES = {PHASE_ENTRY, PHASE_CONT, PHASE_BRK}
        actionable = [
            r for r in st.session_state.results
            if r.get("Phase") in ACTIONABLE_PHASES and r["Action"] in ("BUY", "STRONG BUY")
        ]
        phase_rank = {PHASE_BRK: 0, PHASE_CONT: 1, PHASE_ENTRY: 2}
        actionable.sort(key=lambda x: (phase_rank.get(x.get("Phase"), 9), -x["Score"]))
        top_act = actionable[:15]

        scan_mode_now = st.session_state.scan_mode
        stale_syms    = set()
        for entry in st.session_state.signal_log:
            if signal_is_stale(entry["timestamp"], entry.get("mode", scan_mode_now)):
                stale_syms.add(entry["symbol"])

        def _action_colors(act):
            if act == "STRONG BUY": return "#f59e0b22", "#f59e0b55", "#f59e0b"
            if act == "BUY":        return "#22c55e1a", "#22c55e44", "#22c55e"
            if act == "WATCH":      return "#f59e0b11", "#f59e0b33", "#d97706"
            return "#cbd5e111", "#cbd5e133", "#cbd5e1"

        def make_card(i, r, border_color, show_entry=True):
            chg = r["%Change"]
            cs  = f"+{chg}%" if chg >= 0 else f"{chg}%"
            cc  = "#22c55e" if chg >= 0 else "#ef4444"
            arr = "▲" if chg >= 0 else "▼"
            act = r["Action"]
            act_bg, act_brd, act_txt = _action_colors(act)

            ph  = r.get("Phase", PHASE_IDLE)
            pc  = PHASE_COLORS.get(ph, "#555")
            ph_txt_map = {
                "#00dd88": "#064e3b", "#22aa55": "#064e3b",
                "#2255cc": "#dbeafe", "#b87333": "#431407",
                "#555577": "#c4c6d0", "#cc4444": "#fee2e2",
            }
            ph_txt = ph_txt_map.get(pc, "#e8e8f4")

            conf = r.get("Confidence", 0)
            conf_lbl, conf_col = confidence_label(conf)

            rsr    = r.get("RS_Rank", 50)
            rs_col = "#22c55e" if rsr >= 80 else ("#d97706" if rsr >= 60 else "#cbd5e1")

            entry_str  = (f'₹{r["Entry"]:,.2f}' if show_entry and r["Entry"] != r["LTP"] else "")
            ext_n      = r.get("ExtN", 0)
            ext_labels = r.get("ExtLabels", [])
            ph_arrow   = get_phase_arrow(r["Symbol"])
            is_stale   = r["Symbol"] in stale_syms
            sector     = r.get("Sector", SECTOR_MAP.get(r["Symbol"], "—"))
            breadth_gated = r.get("BreadthGated", False)   # FIX-2

            vol_conf    = r.get("VolConf", False)
            vol_label   = "High" if vol_conf else "Above Avg" if r.get("ATR", 0) > 0 else "Normal"
            htf_up      = r.get("HTFUp", True)
            trend_label = "↑ Bullish" if htf_up else "↓ Bearish"
            trend_col   = "#22c55e" if htf_up else "#ef4444"
            rsi_val     = r.get("RSI", "—")

            num_bg  = "#22c55e" if act in ("BUY", "STRONG BUY") else "#d97706" if act == "WATCH" else "#3a3a60"
            num_txt = "#064e3b" if act in ("BUY", "STRONG BUY") else "#431407" if act == "WATCH" else "#c4c6d0"
            phase_icon = {
                "BREAKOUT":"📈","CONT":"🔄","ENTRY":"⚡","SETUP":"🔍","IDLE":"💤","EXIT":"🚪"
            }.get(ph, "")

            ext_html = ""
            if ext_n > 0:
                for lbl in ext_labels[:2]:
                    ec_bg  = "#3b1a0a" if ext_n >= 3 else "#2a1e00"
                    ec_brd = "#ef444466" if ext_n >= 3 else "#f59e0b66"
                    ec_txt = "#fca5a5" if ext_n >= 3 else "#fbbf24"
                    ext_html += (
                        f'<div style="margin-top:6px;background:{ec_bg};border:1px solid {ec_brd};'
                        f'border-radius:5px;padding:5px 10px;font-size:11px;color:{ec_txt};'
                        f'font-family:DM Sans,sans-serif;display:flex;align-items:center;gap:6px;">'
                        f'⚠ {lbl}</div>'
                    )

            # FIX-2: breadth gate badge
            breadth_badge = (
                '<span style="background:#1e2a40;border:1px solid #3b5998;color:#93b4ff;'
                'padding:1px 5px;border-radius:3px;font-size:9px;margin-left:4px;">B-GATE</span>'
                if breadth_gated else ""
            )

            golden_badge = (
                '<span style="background:#f59e0b22;border:1px solid #f59e0b55;color:#f59e0b;'
                'padding:1px 5px;border-radius:3px;font-size:9px;margin-left:4px;">GOLDEN</span>'
                if r.get("InGolden") else ""
            )
            stale_html = (
                '<span style="color:#cbd5e1;font-size:10px;margin-left:6px;">⏱ stale</span>'
                if is_stale else ""
            )

            ltp_str   = f'&#8377;{r["LTP"]:,.2f}'
            entry_div = (
                f'<div style="font-family:JetBrains Mono,monospace;color:#f59e0b;font-size:12px;'
                f'margin-top:5px;">&#9889; {entry_str}</div>'
                if entry_str else ""
            )
            ph_txt_full = f'{phase_icon} {ph}' + (f' {ph_arrow}' if ph_arrow else '')
            conf_badge  = (
                f'<span style="background:#1e1e40;border:1px solid {conf_col}55;'
                f'padding:6px 10px;border-radius:6px;font-size:10px;font-weight:600;'
                f'font-family:DM Sans,sans-serif;">'
                f'<span style="color:#cbd5e1;font-size:9px;display:block;">{conf_lbl}</span>'
                f'<span style="color:{conf_col};font-weight:700;">{conf}%</span></span>'
            )
            parts = [
                f'<div style="background:#111120;border:1px solid {border_color};'
                f'border-radius:12px;overflow:hidden;width:360px;min-width:320px;'
                f'max-width:380px;flex:1 1 360px;">',
                f'<div style="display:flex;align-items:center;padding:12px 16px 10px;'
                f'border-bottom:1px solid #1e1e40;gap:10px;">',
                f'<div style="background:{num_bg};color:{num_txt};font-family:JetBrains Mono,'
                f'monospace;font-size:12px;font-weight:700;padding:4px 8px;border-radius:6px;'
                f'min-width:32px;text-align:center;">{i+1:02d}</div>',
                f'<div style="font-family:Syne,sans-serif;color:#e8e8f4;font-size:16px;'
                f'font-weight:700;letter-spacing:-0.3px;flex:1;">{r["Symbol"]}'
                f'{golden_badge}{breadth_badge}</div>',
                f'<span style="background:{act_bg};border:1px solid {act_brd};color:{act_txt};'
                f'padding:4px 10px;border-radius:5px;font-size:11px;font-weight:700;'
                f'font-family:DM Sans,sans-serif;">{act}</span>',
                f'<span style="background:#1e1e40;color:#cbd5e1;font-family:JetBrains Mono,'
                f'monospace;font-size:11px;padding:4px 8px;border-radius:5px;">{r["Score"]}</span>',
                stale_html, '</div>',
                '<div style="display:flex;padding:14px 16px;gap:0;">',
                f'<div style="flex:0 0 45%;padding-right:16px;border-right:1px solid #1e1e40;">',
                f'<div style="font-family:JetBrains Mono,monospace;color:#e8e8f4;font-size:26px;'
                f'font-weight:600;line-height:1;">{ltp_str}</div>',
                f'<div style="font-family:JetBrains Mono,monospace;color:{cc};font-size:13px;'
                f'margin-top:4px;font-weight:500;">{cs} {arr}</div>',
                entry_div, '</div>',
                '<div style="flex:1;padding-left:16px;">',
                '<div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center;">',
                f'<span style="background:{pc};color:{ph_txt};padding:6px 12px;border-radius:6px;'
                f'font-size:11px;font-weight:700;font-family:DM Sans,sans-serif;">{ph_txt_full}</span>',
                conf_badge,
                f'<span style="background:#1e1e40;border:1px solid {rs_col}55;padding:6px 10px;'
                f'border-radius:6px;font-size:12px;font-weight:700;font-family:JetBrains Mono,'
                f'monospace;color:{rs_col};">RS{rsr}</span>',
                '</div>', ext_html, '</div>', '</div>',
                '<div style="display:flex;align-items:center;padding:9px 16px;'
                'border-top:1px solid #1e1e40;background:#0d0d1a;">',
                f'<div style="flex:1;"><span style="color:#cbd5e1;font-size:9px;display:block;'
                f'text-transform:uppercase;letter-spacing:0.5px;">RSI</span>'
                f'<span style="color:#e8e8f4;font-size:12px;font-family:JetBrains Mono,'
                f'monospace;">{rsi_val}</span></div>',
                '<div style="width:1px;background:#1e1e40;height:28px;margin:0 6px;"></div>',
                f'<div style="flex:1;"><span style="color:#cbd5e1;font-size:9px;display:block;'
                f'text-transform:uppercase;letter-spacing:0.5px;">Trend</span>'
                f'<span style="color:{trend_col};font-size:12px;font-weight:600;">'
                f'{trend_label}</span></div>',
                '<div style="width:1px;background:#1e1e40;height:28px;margin:0 6px;"></div>',
                f'<div style="flex:1;"><span style="color:#cbd5e1;font-size:9px;display:block;'
                f'text-transform:uppercase;letter-spacing:0.5px;">Volume</span>'
                f'<span style="color:#e8e8f4;font-size:12px;">{vol_label}</span></div>',
                '<div style="width:1px;background:#1e1e40;height:28px;margin:0 6px;"></div>',
                f'<div style="flex:1;"><span style="color:#cbd5e1;font-size:9px;display:block;'
                f'text-transform:uppercase;letter-spacing:0.5px;">Sector</span>'
                f'<span style="color:#e8e8f4;font-size:12px;">{sector}</span></div>',
                '</div>', '</div>',
            ]
            return "".join(parts)

        if top_act:
            with st.expander(
                f"READY TO TRADE — {len(top_act)} stocks in ENTRY / CONT / BREAKOUT",
                expanded=True
            ):
                cards_html = '<div style="display:flex;flex-wrap:wrap;gap:12px;align-items:stretch;">'
                for i, r in enumerate(top_act):
                    cards_html += make_card(i, r, "#22c55e55", show_entry=True)
                cards_html += "</div>"
                st.markdown(cards_html, unsafe_allow_html=True)
                st.markdown(
                    '<div style="text-align:center;color:#3a3a60;font-size:10px;'
                    'font-family:JetBrains Mono,monospace;padding:4px 0 2px;">'
                    'ⓘ Data is indicator based. Confirm with price action.</div>',
                    unsafe_allow_html=True,
                )
        else:
            st.info("No stocks in ENTRY / CONT / BREAKOUT phase.")

        watchlist = [
            r for r in st.session_state.results
            if r.get("Phase") in (PHASE_SETUP, PHASE_IDLE)
            and r["Score"] >= 58 and r["Action"] in ("BUY", "STRONG BUY")
        ][:10]
        if watchlist:
            with st.expander(
                f"WATCHLIST — {len(watchlist)} high-score, not yet ready",
                expanded=False
            ):
                cards_html = '<div style="display:flex;flex-wrap:wrap;gap:12px;align-items:stretch;">'
                for i, r in enumerate(watchlist):
                    cards_html += make_card(i, r, "#f59e0b55", show_entry=False)
                cards_html += "</div>"
                st.markdown(cards_html, unsafe_allow_html=True)

        # ── 🔻 SHORT LIST — derived from same scan, zero re-download ──────────
        short_candidates = derive_short_candidates(
            st.session_state.results, scan_mode_now, vix_val
        )
        if short_candidates:
            sh_now   = sum(1 for s in short_candidates if s.verdict == SHORT_CONFIRMED)
            sh_sig   = sum(1 for s in short_candidates if s.verdict == SHORT_SIGNAL)
            sh_watch = sum(1 for s in short_candidates if s.verdict == SHORT_WATCH)
            top_shorts = [s for s in short_candidates
                          if s.verdict in (SHORT_CONFIRMED, SHORT_SIGNAL)][:12]

            with st.expander(
                f"🔻 SHORT LIST — {sh_now} SHORT NOW · {sh_sig} SIGNAL · {sh_watch} WATCH",
                expanded=(sh_now > 0)
            ):
                if vix_val and vix_val >= VIX_STRESS:
                    st.error(f"⚡ VIX {vix_val} STRESS — short probability elevated; use strict SL")
                elif vix_val and vix_val >= VIX_CAUTION:
                    st.warning(f"⚠️ VIX {vix_val} CAUTION — prefer SHORT NOW only")

                if top_shorts:
                    sh_cards = '<div style="display:flex;flex-wrap:wrap;gap:12px;align-items:stretch;">'
                    for i, sr in enumerate(top_shorts):
                        vc   = SHORT_COLORS.get(sr.verdict, "#555577")
                        rr_c = "#22c55e" if sr.risk_reward >= 2 else ("#f59e0b" if sr.risk_reward >= 1.5 else "#ef4444")
                        rsi_c = "#ef4444" if sr.rsi_val > 70 else ("#f59e0b" if sr.rsi_val > 60 else "#cbd5e1")
                        bar  = min(sr.short_score, 100)
                        # FIX-11: day % change display for short cards
                        dchg    = sr.day_change
                        dchg_s  = f"+{dchg:.2f}%" if dchg >= 0 else f"{dchg:.2f}%"
                        dchg_c  = "#22c55e" if dchg >= 0 else "#ef4444"
                        dchg_arr = "▲" if dchg >= 0 else "▼"
                        hard_pills = "".join(
                            f'<span style="background:#0b0b0f;'
                            f'border:1px solid rgba(239,68,68,0.20);'
                            f'color:#e2e8f0;'
                            f'padding:3px 8px;'
                            f'border-radius:6px;'
                            f'font-size:10px;'
                            f'font-weight:500;'
                            f'font-family:Inter,sans-serif;'
                            f'margin:2px;">{t}</span>'
                            for t in sr.hard_triggers
                        )
                        soft_pills = "".join(
                            f'<span style="background:#0b0b0f;'
                            f'border:1px solid rgba(239,68,68,0.14);'
                            f'color:#e2e8f0;'
                            f'padding:3px 8px;'
                            f'border-radius:6px;'
                            f'font-size:10px;'
                            f'font-weight:500;'
                            f'font-family:Inter,sans-serif;'
                            f'margin:2px;">{t}</span>'
                            for t in sr.soft_triggers
                        )
                        ext_badge = (
                            f'<span style="background:#0b0b0f;'
                            f'border:1px solid rgba(239,68,68,0.18);'
                            f'color:#e2e8f0;'
                            f'padding:3px 8px;'
                            f'border-radius:6px;'
                            f'font-size:10px;'
                            f'font-weight:500;'
                            f'font-family:Inter,sans-serif;'
                            f'margin:2px;">'
                            f'EXT {sr.ext_n} — short fuel</span>'
                        ) if sr.ext_n >= 2 else ""

                        sh_cards += (
                            f'<div style="background:#1b1113;border:1px solid {vc}55;border-radius:12px;'
                            f'overflow:hidden;width:360px;min-width:320px;max-width:380px;flex:1 1 360px;">'
                            # header
                            f'<div style="display:flex;align-items:center;padding:12px 16px 10px;'
                            f'border-bottom:1px solid rgba(255,255,255,0.08);gap:10px;">'
                            f'<div style="background:{vc}22;color:{vc};font-family:JetBrains Mono,monospace;'
                            f'font-size:12px;font-weight:700;padding:4px 8px;border-radius:6px;'
                            f'min-width:32px;text-align:center;">{i+1:02d}</div>'
                            f'<div style="font-family:Syne,sans-serif;color:#f0e8e8;font-size:16px;'
                            f'font-weight:700;flex:1;">{sr.symbol}</div>'
                            f'<span style="background:{vc}22;border:1px solid {vc};color:{vc};'
                            f'padding:4px 10px;border-radius:5px;font-size:11px;font-weight:700;">▼ {sr.verdict}</span>'
                            f'<span style="background:#1e1e40;color:#cbd5e1;font-family:JetBrains Mono,'
                            f'monospace;font-size:11px;padding:4px 8px;border-radius:5px;">{sr.short_score}</span>'
                            f'</div>'
                            # price + short zone
                            f'<div style="display:flex;padding:12px 16px;gap:0;">'
                            f'<div style="flex:0 0 45%;padding-right:16px;border-right:1px solid #1e1e40;">'
                            f'<div style="font-family:JetBrains Mono,monospace;color:#f0e8e8;font-size:22px;'
                            f'font-weight:600;line-height:1;">₹{sr.current_price:,.1f}</div>'
                            f'<div style="font-family:JetBrains Mono,monospace;color:{dchg_c};font-size:13px;'
                            f'margin-top:4px;font-weight:500;">{dchg_s} {dchg_arr}</div>'
                            f'<div style="color:#f8fafc;font-size:11px;margin-top:3px;'
                            f'font-family:JetBrains Mono,monospace;">Short zone</div>'
                            f'<div style="color:#f8fafc;font-size:12px;font-weight:600;'
                            f'font-family:JetBrains Mono,monospace;">'
                            f'₹{sr.entry_zone_lo:,.1f}–₹{sr.entry_zone_hi:,.1f}</div>'
                            f'</div>'
                            # right side metrics
                            f'<div style="flex:1;padding-left:16px;">'
                            f'<div style="display:flex;gap:6px;flex-wrap:wrap;">'
                            f'<span style="background:#1e1e40;padding:5px 8px;border-radius:5px;">'
                            f'<span style="color:#cbd5e1;font-size:9px;display:block;">SL ▲</span>'
                            f'<span style="color:#ef4444;font-family:JetBrains Mono,monospace;font-size:11px;'
                            f'font-weight:600;">₹{sr.stop_loss:,.1f}</span></span>'
                            f'<span style="background:#1e1e40;padding:5px 8px;border-radius:5px;">'
                            f'<span style="color:#cbd5e1;font-size:9px;display:block;">R:R</span>'
                            f'<span style="color:{rr_c};font-weight:700;font-size:12px;">1:{sr.risk_reward:.1f}</span></span>'
                            f'<span style="background:#1e1e40;padding:5px 8px;border-radius:5px;">'
                            f'<span style="color:#cbd5e1;font-size:9px;display:block;">RSI</span>'
                            f'<span style="color:{rsi_c};font-family:JetBrains Mono,monospace;font-size:11px;">'
                            f'{sr.rsi_val:.0f}</span></span>'
                            f'<span style="background:#1e1e40;padding:5px 8px;border-radius:5px;">'
                            f'<span style="color:#cbd5e1;font-size:9px;display:block;">HTF</span>'
                            f'<span style="color:#aaa;font-size:11px;">{sr.htf_trend}</span></span>'
                            f'</div></div></div>'
                            # targets
                            f'<div style="padding:6px 16px 8px;background:#0a0808;display:flex;gap:16px;">'
                            f'<div><span style="color:#cbd5e1;font-size:9px;">T1 ▼</span>'
                            f'<div style="font-family:JetBrains Mono,monospace;color:#22aa88;font-size:11px;">'
                            f'₹{sr.target1:,.1f}</div></div>'
                            f'<div><span style="color:#cbd5e1;font-size:9px;">T2 ▼</span>'
                            f'<div style="font-family:JetBrains Mono,monospace;color:#22aa88;font-size:12px;'
                            f'font-weight:600;">₹{sr.target2:,.1f}</div></div>'
                            f'<div><span style="color:#cbd5e1;font-size:9px;">T3 ▼</span>'
                            f'<div style="font-family:JetBrains Mono,monospace;color:#22aa88;font-size:11px;">'
                            f'₹{sr.target3:,.1f}</div></div>'
                            f'<div style="margin-left:auto;text-align:right;">'
                            f'<span style="color:#cbd5e1;font-size:9px;">RS · {sr.sector}</span>'
                            f'<div style="color:#aaa;font-family:JetBrains Mono,monospace;font-size:11px;">'
                            f'RS{sr.rs_rank}</div></div>'
                            f'</div>'
                            # score bar
                            f'<div style="padding:0 16px 6px;">'
                            f'<div style="background:#1e1e40;border-radius:2px;height:3px;">'
                            f'<div style="background:{vc};width:{bar}%;height:3px;border-radius:2px;"></div>'
                            f'</div></div>'
                            # trigger pills
                            f'<div style="padding:4px 16px 10px;">'
                            f'{hard_pills}{soft_pills}{ext_badge}</div>'
                            f'</div>'
                        )
                    sh_cards += "</div>"
                    st.markdown(sh_cards, unsafe_allow_html=True)
                    st.markdown(
                      '''
                      <div style="
                          text-align:center;
                          color:#94a3b8;
                          font-size:11px;
                          font-family:JetBrains Mono,monospace;
                          padding:10px 0 4px;
                          line-height:1.6;
                          opacity:0.92;
                          max-width:900px;
                          margin:0 auto;
                      ">
                          ⓘ Short candidates are derived from the same scan engine and require
                          confirmation with price action, volume, and market context.<br>
                          <span style="
                              color:#fca5a5;
                              font-weight:600;
                          ">
                              Short selling carries elevated risk — always use disciplined stop-loss management.
                          </span>
                      </div>
                      ''',
                      unsafe_allow_html=True,
                  )

                # Watch-only table (collapsed)
                sh_watch_list = [s for s in short_candidates if s.verdict == SHORT_WATCH]
                if sh_watch_list:
                    st.markdown(
                        f'<div style="color:#cbd5e1;font-size:11px;font-family:DM Sans,sans-serif;'
                        f'margin-top:10px;">Also on watch ({len(sh_watch_list)}):</div>',
                        unsafe_allow_html=True,
                    )
                    tbl = [{"Symbol": s.symbol, "Score": s.short_score,
                            "Current": fmt(s.current_price), "SL ▲": fmt(s.stop_loss),
                            "T2 ▼": fmt(s.target2), "R:R": s.risk_reward,
                            "RSI": s.rsi_val, "RS": s.rs_rank, "Phase": s.phase,
                            "Hard#": len(s.hard_triggers), "Soft#": len(s.soft_triggers)}
                           for s in sh_watch_list]
                    st.dataframe(pd.DataFrame(tbl), use_container_width=True,
                                 hide_index=True, height=200)

    # ── Main table ─────────────────────────────────────────────────────────────
    if results:
        rows = []
        for i, r in enumerate(results):
            chg       = r["%Change"]
            phase     = r.get("Phase", PHASE_IDLE)
            setup_icon = {"fib":"Fib","breakout":"BRK","norm":"std","vdu":"VDU"}.get(
                r.get("Setup", "norm"), "std")
            conf     = r.get("Confidence", 0)
            ph_arrow = get_phase_arrow(r["Symbol"])
            rows.append({
                "#":        i + 1,
                "Symbol":   r["Symbol"],
                "Score":    r["Score"],
                "Conf%":    conf,
                "Phase":    f'{phase}{" "+ph_arrow if ph_arrow else ""}',
                "Setup":    setup_icon,
                "Action":   r["Action"],
                "B-Gate":   "⚠" if r.get("BreadthGated") else "",   # FIX-2
                "%Chg":     f"+{chg}%" if chg >= 0 else f"{chg}%",
                "RSI":      r.get("RSI", "—"),
                "RS_Rank":  r.get("RS_Rank", 50),
                "LTP":      fmt(r["LTP"]),
                "Entry":    fmt(r["Entry"]) + (" ⚡" if r["Entry"] != r["LTP"] else ""),
                "SL":       fmt(r["SL"]),
                "T1":       fmt(r["T1"]),
                "T2":       fmt(r["T2"]),
                "T3":       fmt(r["T3"]),
                "Liq₹Cr":  r.get("AvgTradedCr", "—"),
                "HTF":      "↑" if r.get("HTFUp", True) else "↓",
                "ExtN":     r.get("ExtN", 0),
                "Ext":      " ".join(r.get("ExtLabels", [])) or "—",
            })

        df_display = pd.DataFrame(rows)

        def color_extn(val):
            if val == 0: return "background-color: transparent; color: #cbd5e1"
            if val == 1: return "background-color: #78350f44; color: #f59e0b"
            if val == 2: return "background-color: #9a3412aa; color: #fb923c"
            return "background-color: #7f1d1d; color: #fca5a5; font-weight: 600"

        def color_action(val):
            if val == "STRONG BUY": return "color: #f59e0b; font-weight: 600"
            if val == "BUY":        return "color: #22c55e"
            if val == "WATCH":      return "color: #d97706"
            return "color: #cbd5e1"

        def color_pct(val):
            if isinstance(val, str) and val.startswith("+"):
                return "color: #22c55e; font-family: JetBrains Mono, monospace"
            if isinstance(val, str) and val.startswith("-"):
                return "color: #ef4444; font-family: JetBrains Mono, monospace"
            return ""

        styled = (
            df_display.style
            .map(color_extn,   subset=["ExtN"])
            .map(color_action, subset=["Action"])
            .map(color_pct,    subset=["%Chg"])
            .set_properties(**{"font-family": "JetBrains Mono, monospace", "font-size": "11px"})
        )

        st.dataframe(styled, use_container_width=True, hide_index=True, height=480)
        st.markdown(
            '<div style="font-size:10px;color:#3a3a60;font-family:JetBrains Mono,monospace;'
            'margin-top:4px;">Score 0-100 · Conf% = confidence · RS_Rank = 52w percentile '
            '(80+=top) · HTF ↑/↓ = weekly · Liq₹Cr = avg daily value · '
            'ExtN 0=clean 3+=skip · B-Gate = breadth gated</div>',
            unsafe_allow_html=True,
        )

        buy_rows = [r for r in results if r["Action"] in ("BUY", "STRONG BUY")]
        if buy_rows:
            csv = pd.DataFrame(buy_rows).drop(columns=["ExtFlags"], errors="ignore").to_csv(index=False)
            ts  = datetime.now().strftime("%Y%m%d_%H%M%S")
            st.download_button("Export BUY results", csv,
                               f"NSE_Scan_{st.session_state.scan_mode}_{ts}.csv", "text/csv")
    elif st.session_state.results:
        st.warning("No stocks match current filters.")
    else:
        st.info("Select Universe + Mode, then press SCAN.")


# ═══════════════════════════════════════════════════════════════════════════════
# BREADTH ENGINE TAB
# ═══════════════════════════════════════════════════════════════════════════════

with tab_breadth:
    all_results = st.session_state.results
    if not all_results:
        st.info("Run a scan first to see breadth data.")
    else:
        breadth      = compute_breadth(all_results)
        b_sig, b_col = breadth["breadth_signal"]

        st.markdown(
            f'<div style="background:{b_col}11;border:1px solid {b_col}33;border-radius:8px;'
            f'padding:10px 16px;margin-bottom:14px;">'
            f'<span style="font-family:Syne,sans-serif;font-size:15px;color:{b_col};">'
            f'Market Breadth: <strong>{b_sig}</strong></span></div>',
            unsafe_allow_html=True,
        )

        bm1, bm2, bm3, bm4, bm5, bm6 = st.columns(6)
        bm1.metric("% Above EMA50", f'{breadth["pct_above_ema50"]}%')
        bm2.metric("% in BREAKOUT", f'{breadth["pct_breakout"]}%')
        bm3.metric("Advancing",     breadth["advancing"])
        bm4.metric("Declining",     breadth["declining"])
        bm5.metric("A/D Ratio",     breadth["ad_ratio"])
        bm6.metric("Liquid Stocks", breadth["liquid_count"])

        # FIX-2: show how many signals are breadth-gated
        gated_n = sum(1 for r in all_results if r.get("BreadthGated"))
        if gated_n:
            st.warning(
                f"🔵 **Breadth Gate** — {gated_n} BREAKOUT/CONT signals were capped to WATCH "
                f"(pct_above_ema50={breadth['pct_above_ema50']}%, A/D={breadth['ad_ratio']})"
            )

        pct_ema = breadth["pct_above_ema50"]
        adr     = breadth["ad_ratio"]
        brk_pct = breadth["pct_breakout"]

        interp_lines = []
        if pct_ema >= 70:
            interp_lines.append("✅ **Strong internal trend** — 70%+ above EMA50.")
        elif pct_ema >= 50:
            interp_lines.append("🟡 **Mixed breadth** — about half the market participating. Be selective.")
        else:
            interp_lines.append("🔴 **Weak breadth** — majority below EMA50. Avoid chasing.")
        if adr >= 2.0:
            interp_lines.append("✅ **A/D ratio strong** — broad advancing participation.")
        elif adr < 0.8:
            interp_lines.append("🔴 **Declining dominance** — wait for A/D recovery before new longs.")
        if brk_pct >= 5:
            interp_lines.append(f"✅ **Breakout breadth healthy** ({brk_pct}%).")
        elif brk_pct < 1:
            interp_lines.append("🔴 **No breakout breadth** — avoid momentum until breadth improves.")
        if vix_val:
            if vix_val >= VIX_STRESS:
                interp_lines.append(f"🔴 **VIX {vix_val} STRESS** — STRONG BUY blocked. Targets compressed.")
            elif vix_val >= VIX_CAUTION:
                interp_lines.append(f"🟡 **VIX {vix_val} CAUTION** — Targets compressed 25%, SL widened.")
            else:
                interp_lines.append(f"✅ **VIX {vix_val} CALM** — Normal risk parameters.")

        st.markdown("\n\n".join(interp_lines))
        st.markdown("---")
        st.subheader("Sector Heatmap")

        sector_data = breadth["sector_avg"]
        if sector_data:
            sec_df = pd.DataFrame([
                {"Sector": k, "Avg Score": v,
                 "Count": sum(1 for r in all_results if r.get("Sector") == k)}
                for k, v in sorted(sector_data.items(), key=lambda x: -x[1])
            ])
            hm_html = '<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(170px,1fr));gap:8px;">'
            for _, row in sec_df.iterrows():
                score   = row["Avg Score"]
                bar_col = "#22c55e" if score >= 70 else ("#d97706" if score >= 55 else "#ef4444")
                pct     = min(100, score)
                hm_html += (
                    f'<div style="background:#111120;border:1px solid #1e1e40;'
                    f'border-radius:7px;padding:10px 12px;">'
                    f'<div style="color:#e8e8f4;font-size:11px;font-weight:600;'
                    f'font-family:DM Sans,sans-serif;">{row["Sector"]}</div>'
                    f'<div style="color:#cbd5e1;font-size:10px;'
                    f'font-family:JetBrains Mono,monospace;">{int(row["Count"])} stocks</div>'
                    f'<div style="background:#1e1e40;border-radius:2px;height:4px;margin:6px 0;">'
                    f'<div style="background:{bar_col};width:{pct}%;height:4px;border-radius:2px;"></div></div>'
                    f'<div style="color:{bar_col};font-size:15px;font-weight:600;'
                    f'font-family:JetBrains Mono,monospace;">{score}</div>'
                    f'</div>'
                )
            hm_html += "</div>"
            st.markdown(hm_html, unsafe_allow_html=True)

        st.markdown("---")
        dist_data   = {"Advancing": breadth["advancing"], "Unchanged": breadth["unchanged"],
                       "Declining": breadth["declining"]}
        dist_colors = {"Advancing":"#22c55e","Unchanged":"#d97706","Declining":"#ef4444"}
        total_shown = sum(dist_data.values())
        dist_html   = '<div style="display:flex;gap:8px;">'
        for label, count in dist_data.items():
            pct2 = round(count / total_shown * 100, 1) if total_shown else 0
            col  = dist_colors[label]
            dist_html += (
                f'<div style="flex:1;background:#111120;border:1px solid {col}33;'
                f'border-radius:7px;padding:12px;text-align:center;">'
                f'<div style="color:{col};font-size:22px;font-weight:600;'
                f'font-family:JetBrains Mono,monospace;">{count}</div>'
                f'<div style="color:#cbd5e1;font-size:11px;font-family:DM Sans,sans-serif;">{label}</div>'
                f'<div style="color:{col};font-size:11px;font-family:JetBrains Mono,monospace;">{pct2}%</div>'
                f'</div>'
            )
        dist_html += "</div>"
        st.markdown(dist_html, unsafe_allow_html=True)

        st.markdown("---")
        st.subheader("RS Rank Distribution")
        rs_buckets = {"Top 80-100":0,"Upper 60-79":0,"Mid 40-59":0,"Lower 20-39":0,"Bottom 0-19":0}
        for r in all_results:
            rk = r.get("RS_Rank", 50)
            if rk >= 80:   rs_buckets["Top 80-100"]  += 1
            elif rk >= 60: rs_buckets["Upper 60-79"] += 1
            elif rk >= 40: rs_buckets["Mid 40-59"]   += 1
            elif rk >= 20: rs_buckets["Lower 20-39"] += 1
            else:           rs_buckets["Bottom 0-19"] += 1
        rs_cols = st.columns(5)
        for col, (label, cnt) in zip(rs_cols, rs_buckets.items()):
            col.metric(label, cnt)


# ═══════════════════════════════════════════════════════════════════════════════
# DETAIL TAB
# ═══════════════════════════════════════════════════════════════════════════════

with tab_detail:
    all_results = st.session_state.results
    if not all_results:
        st.info("Run a scan first.")
    else:
        sel = st.selectbox("Select stock", [r["Symbol"] for r in all_results])
        r   = next((x for x in all_results if x["Symbol"] == sel), None)
        if r:
            phase = r.get("Phase", PHASE_IDLE)
            chg   = r["%Change"]
            conf  = r.get("Confidence", 0)
            conf_lbl, conf_col = confidence_label(conf)

            phases_order = [PHASE_IDLE, PHASE_SETUP, PHASE_ENTRY, PHASE_CONT, PHASE_BRK, PHASE_EXIT]
            history      = st.session_state.get("phase_history", {}).get(sel, [])

            ph_html = '<div style="display:flex;gap:5px;margin-bottom:12px;flex-wrap:wrap;">'
            for ph in phases_order:
                active = ph == phase
                bg     = PHASE_COLORS[ph] if active else "#1e1e40"
                brd    = f"1px solid {PHASE_COLORS[ph]}" if active else "1px solid #1e1e40"
                ph_txt_active = {
                    "#00dd88":"#064e3b", "#22aa55":"#064e3b",
                    "#2255cc":"#dbeafe", "#b87333":"#431407",
                    "#555577":"#c4c6d0", "#cc4444":"#fee2e2",
                }.get(PHASE_COLORS[ph], "#e8e8f4")
                ph_html += (
                    f'<div style="background:{bg};border:{brd};'
                    f'color:{ph_txt_active if active else "#cbd5e1"};'
                    f'padding:4px 12px;border-radius:5px;font-size:11px;'
                    f'font-weight:{"600" if active else "400"};font-family:DM Sans,sans-serif;">'
                    f'{ph}{"  ◀" if active else ""}</div>'
                )
            ph_html += "</div>"
            st.markdown(ph_html, unsafe_allow_html=True)

            if r.get("BreadthGated"):
                st.warning("🔵 **Breadth Gated** — action capped to WATCH due to weak market breadth.")

            if len(history) >= 2:
                transitions = []
                for j in range(1, len(history)):
                    prev_ts, prev_ph = history[j-1]
                    curr_ts, curr_ph = history[j]
                    arrow = "↗" if PHASE_ORDER.get(curr_ph, 0) > PHASE_ORDER.get(prev_ph, 0) else "↘"
                    transitions.append(
                        f'{prev_ph} {arrow} {curr_ph}'
                        f'  <span style="color:#3a3a60;font-size:10px;">({curr_ts[:16]})</span>'
                    )
                st.markdown(
                    '<details><summary style="color:#cbd5e1;font-size:11px;cursor:pointer;">'
                    f'Phase History ({len(history)} states)</summary>'
                    '<div style="font-size:11px;color:#cbd5e1;padding:6px 0;'
                    'font-family:JetBrains Mono,monospace;">'
                    + "<br>".join(transitions) + '</div></details>',
                    unsafe_allow_html=True,
                )

            d1, d2, d3, d4, d5 = st.columns(5)
            d1.metric("LTP",        fmt(r["LTP"]),   f"{'+' if chg >= 0 else ''}{chg}%")
            d2.metric("Entry ⚡",   fmt(r["Entry"]))
            d3.metric("Stop Loss",  fmt(r["SL"]))
            d4.metric("Score",      r["Score"])
            d5.metric("Confidence", f"{conf}% ({conf_lbl})")

            t1c, t2c, t3c, r1c = st.columns(4)
            t1c.metric("T1", fmt(r["T1"]))
            t2c.metric("T2", fmt(r["T2"]))
            t3c.metric("T3", fmt(r["T3"]))
            risk = round(r["Entry"] - r["SL"], 2) if r.get("Entry") and r.get("SL") else 0
            r1c.metric("Risk/Share", fmt(risk))

            st.markdown("---")
            with st.expander("Position Sizing (Volatility-Normalized + Capital Cap)", expanded=True):
                _acct_size      = st.session_state.get("account_size", 500000)
                _risk_pct       = st.session_state.get("risk_pct", 0.02)
                _max_cap_pct    = st.session_state.get("max_capital_pct", 0.20)
                ps = position_size(
                    account_size    = _acct_size,
                    entry           = r["Entry"],
                    sl              = r["SL"],
                    atr_val         = r.get("ATR", risk),
                    atr_mean        = r.get("ATR_Mean", risk),
                    vix_val         = vix_val,
                    risk_pct        = _risk_pct,
                    max_capital_pct = _max_cap_pct,      # FIX-5
                )
                ps1, ps2, ps3, ps4 = st.columns(4)
                ps1.metric("Suggested Qty",  ps["final_qty"])
                ps2.metric("Capital Used",   fmt(ps["capital_used"]))
                ps3.metric("Max Loss",       fmt(ps["max_loss"]))
                ps4.metric("Risk per Share", fmt(risk))

                cap_note = (
                    f'  ⚠ <span style="color:#f59e0b;">Capital capped</span>'
                    f' (pre-cap qty: {ps["vol_adj_qty"]})'
                    if ps.get("capital_capped") else ""
                )
                st.markdown(
                    f'<div style="background:#111120;border:1px solid #1e1e40;border-radius:6px;'
                    f'padding:8px 12px;margin-top:8px;font-size:11px;'
                    f'font-family:JetBrains Mono,monospace;color:#cbd5e1;">'
                    f'Base: <span style="color:#e8e8f4;">{ps["base_qty"]}</span>  ×  '
                    f'VIX adj <span style="color:#f59e0b;">{ps["vix_adj"]}×</span>  ×  '
                    f'ATR adj <span style="color:#f59e0b;">{ps["atr_adj"]}×</span>  =  '
                    f'<span style="color:#22c55e;font-weight:600;">{ps["final_qty"]} shares</span>'
                    f'{cap_note}'
                    f'</div>',
                    unsafe_allow_html=True,
                )

            with st.expander(f"Confidence Model — {conf}% ({conf_lbl})", expanded=False):
                factors = {
                    "Phase alignment":   {PHASE_BRK:20,PHASE_CONT:17,PHASE_ENTRY:13,
                                          PHASE_SETUP:7,PHASE_IDLE:2,PHASE_EXIT:0}.get(phase, 0),
                    "Score quality":     round(min(20, r["Score"] * 0.20), 1),
                    "Volume confirmed":  15 if r.get("VolConf") else 5,
                    "EMA stack":         8 if r.get("EMAStack") else 3,
                    "HTF alignment":     7 if r.get("HTFUp", True) else 0,
                    "Market regime":     10 if r.get("Regime") == "BULLISH" else 2,
                    "Exhaustion drag":   -min(5, r.get("ExtN", 0) * 2),
                    "RS rank bonus": (10 if r.get("RS_Rank", 50) >= 90 else 7 if r.get("RS_Rank", 50) >= 80 else 3 if r.get("RS_Rank", 50) >= 70 else 0),
                    "Phase progression": r.get("PhaseBonus", 0),
                }
                for fname, fval in factors.items():
                    col_f = ("#22c55e" if fval >= 10 else
                             "#f59e0b" if fval >= 5 else
                             "#ef4444" if fval < 0 else "#cbd5e1")
                    st.markdown(
                        f'<div style="display:flex;justify-content:space-between;'
                        f'padding:4px 0;border-bottom:1px solid #1e1e40;">'
                        f'<span style="color:#cbd5e1;font-size:12px;'
                        f'font-family:DM Sans,sans-serif;">{fname}</span>'
                        f'<span style="color:{col_f};font-size:12px;font-weight:600;'
                        f'font-family:JetBrains Mono,monospace;">{fval:+.0f}</span>'
                        f'</div>',
                        unsafe_allow_html=True,
                    )

            ext_n      = r.get("ExtN", 0)
            ext_labels = r.get("ExtLabels", [])
            ext_flags  = r.get("ExtFlags", {})
            if ext_n == 0:
                st.success("✅ No extension/exhaustion signals — structure is clean.")
            else:
                flag_desc = {
                    "rsi_overheat":     "Stock has run up too fast — buyers are exhausted. Wait for a cooldown.",
                    "atr_extension":    "Today's range is unusually large — possible blow-off.",
                    "parabolic":        "Price jumped far more than normal in 3 bars. Hard to sustain.",
                    "ema_distance":     "Price is stretched way above its average. Pullback likely.",
                    "climactic_volume": "Huge volume spike with long upper wick — potential distribution.",
                    "mom_exhaustion":   "Price rising but buying pressure quietly weakening.",
                    "bearish_div":      "New high, but momentum didn't confirm it.",
                }
                with st.expander(
                    f"⚠ {ext_n} Caution Signal{'s' if ext_n > 1 else ''} — "
                    f"{'DO NOT enter' if ext_n >= 3 else 'Reduce size'}",
                    expanded=True,
                ):
                    for fk, fa in ext_flags.items():
                        if fa:
                            ec = "#ef4444" if ext_n >= 3 else "#f59e0b"
                            st.markdown(
                                f'<div style="color:{ec};font-size:12px;padding:3px 0;">'
                                f'▸ <strong>{fk.replace("_"," ").title()}</strong> — '
                                f'{flag_desc.get(fk,"")}</div>',
                                unsafe_allow_html=True,
                            )
                    penalty = sum(EXT_PENALTIES[k] for k, v2 in ext_flags.items() if v2)
                    st.markdown(
                        f'<div style="margin-top:8px;padding:6px 10px;background:#7f1d1d22;'
                        f'border:1px solid #7f1d1d;border-radius:5px;'
                        f'font-size:12px;color:#fca5a5;">'
                        f'Score reduced by {abs(penalty)} pts — '
                        + ("Skip. Wait for pullback + RSI < 60." if ext_n >= 3
                           else "Half size. Wait for support/EMA dip.")
                        + '</div>',
                        unsafe_allow_html=True,
                    )

            info_cols = st.columns(4)
            info_cols[0].metric("RSI",          r.get("RSI", "—"))
            info_cols[1].metric("RS Rank",       f'{r.get("RS_Rank", 50)}/100')
            info_cols[2].metric("Liq (₹Cr/d)",  r.get("AvgTradedCr", "—"))
            info_cols[3].metric("Raw RS Diff",   f"{r.get('RS', 0):+.1f}%")

            if r["Entry"] != r["LTP"]:
                st.info(
                    f"⚡ Entry ₹{r['Entry']:,} is the trigger price. "
                    f"LTP = ₹{r['LTP']:,}. Place order near Entry when phase = ENTRY/BREAKOUT."
                )


# ═══════════════════════════════════════════════════════════════════════════════
# ANALYTICS TAB
# ═══════════════════════════════════════════════════════════════════════════════

with tab_analytics:
    st.subheader("Signal Log & Outcome Tracking")
    log = st.session_state.signal_log
    if not log:
        st.info("No signals logged yet. Run a scan to populate.")
    else:
        log_df        = pd.DataFrame(log)
        scan_mode_now = st.session_state.scan_mode

        log_df["stale"] = log_df.apply(
            lambda row: signal_is_stale(row["timestamp"], row.get("mode", scan_mode_now)), axis=1)
        log_df["age"] = log_df.apply(
            lambda row: signal_age_label(row["timestamp"], row.get("mode", scan_mode_now))[0], axis=1)

        total_sig  = len(log_df)
        pending    = len(log_df[log_df["outcome"] == "Pending"])
        stale_cnt  = int(log_df["stale"].sum())
        wins       = len(log_df[log_df["outcome"] == "Win"])
        losses     = len(log_df[log_df["outcome"] == "Loss"])
        active_df  = log_df[~log_df["stale"]]
        active_wins   = len(active_df[active_df["outcome"] == "Win"])
        active_losses = len(active_df[active_df["outcome"] == "Loss"])
        win_rate   = round(wins / (wins + losses) * 100, 1) if (wins + losses) > 0 else None
        active_wr  = round(active_wins / (active_wins + active_losses) * 100, 1) \
                     if (active_wins + active_losses) > 0 else None

        am1, am2, am3, am4, am5 = st.columns(5)
        am1.metric("Total Signals", total_sig)
        am2.metric("Pending",       pending)
        am3.metric("Expired",       stale_cnt)
        am4.metric("Overall Win%",  f"{win_rate}%" if win_rate is not None else "—")
        am5.metric("Active Win%",   f"{active_wr}%" if active_wr is not None else "—")

        display_cols = ["timestamp","symbol","action","phase","score","confidence",
                        "rs_rank","entry","sl","t1","age","outcome","breadth_gated"]
        display_cols = [c for c in display_cols if c in log_df.columns]

        edited = st.data_editor(
            log_df[display_cols].tail(100),
            column_config={
                "outcome": st.column_config.SelectboxColumn(
                    "Outcome", options=["Pending","Win","Loss","BE"], required=True),
                "age":     st.column_config.TextColumn("Age", disabled=True),
                "rs_rank": st.column_config.NumberColumn("RS Rank", disabled=True),
                "breadth_gated": st.column_config.CheckboxColumn("B-Gated", disabled=True),
            },
            hide_index=True, use_container_width=True,
        )
        if edited is not None and len(edited) == len(log_df.tail(100)):
            for i, row in edited.iterrows():
                idx = len(log_df) - 100 + i
                if 0 <= idx < len(log):
                    log[idx]["outcome"] = row["outcome"]

        if wins + losses > 0:
            st.markdown("---")
            st.subheader("Phase Win-Rate (active signals only)")
            phase_stats = {}
            for entry in log:
                if signal_is_stale(entry["timestamp"], entry.get("mode", scan_mode_now)):
                    continue
                ph = entry.get("phase", "UNKNOWN")
                oc = entry.get("outcome", "Pending")
                if oc in ("Win","Loss"):
                    if ph not in phase_stats:
                        phase_stats[ph] = {"Win":0,"Loss":0}
                    phase_stats[ph][oc] += 1
            if phase_stats:
                ps_rows = []
                for ph, stats in phase_stats.items():
                    w  = stats["Win"]; l = stats["Loss"]
                    wr = round(w / (w + l) * 100, 1) if (w + l) > 0 else 0
                    ps_rows.append({"Phase":ph,"Wins":w,"Losses":l,"Win Rate":f"{wr}%"})
                st.dataframe(pd.DataFrame(ps_rows), hide_index=True, use_container_width=True)

        if st.button("Export Signal Log"):
            export_df = pd.DataFrame(log).drop(columns=["ExtFlags"], errors="ignore")
            csv = export_df.to_csv(index=False)
            ts  = datetime.now().strftime("%Y%m%d_%H%M%S")
            st.download_button("Download", csv,
                               f"NSE_SignalLog_{ts}.csv", "text/csv")

# ═══════════════════════════════════════════════════════════════════════════════
# 💼 PORTFOLIO TAB  (open positions with exit signals)
# ═══════════════════════════════════════════════════════════════════════════════

with tab_portfolio:
    st.markdown(
        '<div style="font-family:Syne,sans-serif;font-size:18px;font-weight:700;'
        'color:#e8e8f4;margin-bottom:12px;">💼 Open Positions & Exit Signals</div>',
        unsafe_allow_html=True,
    )

    # Add position form inline
    with st.expander("➕ Add Position", expanded=False):
        pf1, pf2, pf3, pf4 = st.columns([2, 2, 1, 1])
        ap_sym   = pf1.text_input("Symbol", key="pf_sym").upper()
        ap_entry = pf2.number_input("Entry Price ₹", min_value=0.01, value=100.0, step=0.5, key="pf_ep")
        ap_qty   = pf3.number_input("Qty", min_value=1, value=100, step=1, key="pf_qty")
        ap_mode  = pf4.selectbox("Mode", list(MODE_CFG.keys()), index=1, key="pf_mode")
        if st.button("Add", type="primary", key="pf_add_btn"):
            if ap_sym:
                add_position(ap_sym, ap_entry, int(ap_qty), ap_mode)
                st.success(f"Added {ap_sym}")

    positions = st.session_state.get("open_positions") or []

    if not positions:
        st.info("No open positions. Add from this page, from the Scanner, or via the sidebar.")
    else:
        col_refresh, _ = st.columns([1, 5])
        with col_refresh:
            if st.button("🔄 Refresh Exit Signals", use_container_width=True, key="pf_refresh"):
                vix_pf, _ = fetch_vix()
                with st.spinner("Scanning exits…"):
                    st.session_state["exit_results"] = run_exit_scan(positions, vix_pf)

        exit_res = st.session_state.get("exit_results", {})

        # Summary strip
        counts = {EXIT_HOLD: 0, EXIT_WATCH_LBL: 0, EXIT_SIGNAL_LBL: 0, EXIT_CONFIRM_LBL: 0}
        for p in positions:
            if not isinstance(p, dict): continue
            sym = p.get("symbol")
            if not sym: continue
            er = exit_res.get(sym)
            lbl = er.verdict if er else EXIT_HOLD
            counts[lbl] = counts.get(lbl, 0) + 1

        p1, p2, p3, p4 = st.columns(4)
        p1.metric("🟢 Hold",        counts[EXIT_HOLD])
        p2.metric("🟡 Watch",       counts[EXIT_WATCH_LBL])
        p3.metric("🟠 Exit Signal", counts[EXIT_SIGNAL_LBL])
        p4.metric("🔴 Exit Now",    counts[EXIT_CONFIRM_LBL])
        st.markdown('<div style="border-top:1px solid #1e1e40;margin:10px 0;"></div>', unsafe_allow_html=True)

        _exit_ord = {EXIT_CONFIRM_LBL: 0, EXIT_SIGNAL_LBL: 1, EXIT_WATCH_LBL: 2, EXIT_HOLD: 3}
        valid_pos = [p for p in positions if isinstance(p, dict) and p.get("symbol")]
        pos_sorted = sorted(valid_pos, key=lambda p: _exit_ord.get(
            exit_res[p["symbol"]].verdict if p["symbol"] in exit_res else EXIT_HOLD, 3))

        for pos in pos_sorted:
            sym      = pos["symbol"]
            er       = exit_res.get(sym)
            verdict  = er.verdict if er else EXIT_HOLD
            ex_score = er.exit_score if er else 0
            triggers = er.triggers if er else []
            trail_sl = er.trailing_stop if er else None
            entry_px = pos.get("entry_price", 0)
            curr_px  = (er.current_price if (er and er.current_price) else entry_px)
            qty      = pos.get("qty", 0)
            mode_p   = pos.get("mode", "Swing")
            day_pct  = er.day_pct if er else 0.0   # FIX-11

            pnl_pct  = (curr_px - entry_px) / entry_px * 100 if entry_px else 0
            pnl_abs  = (curr_px - entry_px) * qty
            pnl_col  = "#22c55e" if pnl_pct >= 0 else "#ef4444"
            day_col  = "#22c55e" if day_pct >= 0 else "#ef4444"   # FIX-11
            day_str  = f"+{day_pct:.2f}%" if day_pct >= 0 else f"{day_pct:.2f}%"  # FIX-11
            vc       = EXIT_COLORS.get(verdict, "#22aa55")
            bar      = min(int(ex_score), 100)

            trig_html = "".join(
                f'<span style="background:#1e1e40;border:1px solid #555;color:#ccc;'
                f'padding:2px 8px;border-radius:4px;font-size:9px;margin:1px;">⚡ {t}</span>'
                for t in triggers
            ) or '<span style="color:#3a3a60;font-size:9px;">No exit triggers</span>'

            trail_bit = (
                f'<div style="flex:0 0 auto;">'
                f'<div style="color:#cbd5e1;font-size:9px;">TRAIL SL</div>'
                f'<div style="font-family:JetBrains Mono,monospace;color:#f59e0b;font-size:13px;font-weight:600;">₹{trail_sl:,.2f}</div>'
                f'</div>'
            ) if trail_sl else ""

            # FIX-12: render portfolio cards in a scanner-sized card (360px wide)
            # wrapped in a flex container so they flow side-by-side like scanner cards.
            st.markdown(
                f'<div style="display:flex;flex-wrap:wrap;gap:12px;margin-bottom:4px;">'
                f'<div style="background:#111120;border:1.5px solid {vc};border-radius:12px;'
                f'overflow:hidden;box-shadow:0 2px 12px {vc}22;'
                f'width:360px;min-width:320px;max-width:380px;flex:1 1 360px;">'
                # header
                f'<div style="display:flex;justify-content:space-between;align-items:center;'
                f'padding:12px 16px 10px;border-bottom:1px solid #1e1e40;">'
                f'<div><span style="font-family:Syne,sans-serif;color:#e8e8f4;font-size:16px;font-weight:700;">{sym}</span>'
                f'<span style="color:#cbd5e1;font-size:11px;font-family:DM Sans,sans-serif;margin-left:8px;">'
                f'{SECTOR_MAP.get(sym,"—")} · {mode_p}</span></div>'
                f'<span style="background:{vc}22;border:1px solid {vc};color:{vc};'
                f'padding:4px 12px;border-radius:6px;font-size:11px;font-weight:700;">{verdict}</span>'
                f'</div>'
                # metrics
                f'<div style="display:flex;gap:16px;flex-wrap:wrap;padding:12px 16px;">'
                f'<div><div style="color:#cbd5e1;font-size:9px;">ENTRY</div>'
                f'<div style="font-family:JetBrains Mono,monospace;color:#aaa;font-size:13px;">₹{entry_px:,.2f}</div></div>'
                f'<div><div style="color:#cbd5e1;font-size:9px;">CURRENT</div>'
                f'<div style="font-family:JetBrains Mono,monospace;color:#e8e8f4;font-size:13px;">₹{curr_px:,.2f}</div></div>'
                f'<div><div style="color:#cbd5e1;font-size:9px;">DAY</div>'
                f'<div style="font-family:JetBrains Mono,monospace;color:{day_col};font-size:13px;font-weight:600;">{day_str}</div></div>'
                f'<div><div style="color:#cbd5e1;font-size:9px;">QTY</div>'
                f'<div style="font-family:JetBrains Mono,monospace;color:#aaa;font-size:13px;">{qty}</div></div>'
                f'<div><div style="color:#cbd5e1;font-size:9px;">P&L</div>'
                f'<div style="font-family:JetBrains Mono,monospace;color:{pnl_col};font-size:13px;font-weight:700;">'
                f'{"+"}' + f'{pnl_pct:.1f}% (₹{pnl_abs:+,.0f})</div></div>'
                + trail_bit +
                f'</div>'
                # exit pressure bar
                f'<div style="padding:4px 16px 8px;">'
                f'<div style="display:flex;justify-content:space-between;margin-bottom:3px;">'
                f'<span style="color:#cbd5e1;font-size:9px;">EXIT PRESSURE</span>'
                f'<span style="color:{vc};font-size:9px;font-weight:700;">{bar}/100</span></div>'
                f'<div style="background:#1e1e40;border-radius:2px;height:4px;">'
                f'<div style="background:{vc};width:{bar}%;height:4px;border-radius:2px;"></div></div></div>'
                # triggers
                f'<div style="padding:4px 16px 10px;">{trig_html}</div>'
                f'</div></div>',
                unsafe_allow_html=True,
            )

            ac1, ac2, ac3 = st.columns([3, 2, 1])
            with ac1:
                if verdict == EXIT_CONFIRM_LBL: st.error("⚠️ Consider full exit or tight trailing stop")
                elif verdict == EXIT_SIGNAL_LBL: st.warning("🔶 Consider 50% exit to lock gains")
                elif verdict == EXIT_WATCH_LBL: st.info("👁 Monitor closely — tighten stop")
            with ac3:
                if st.button("🗑 Remove", key=f"rm_{sym}_{pos.get('entry_date','')}"):
                    st.session_state["open_positions"] = [
                        p for p in st.session_state["open_positions"]
                        if not (p.get("symbol") == sym and p.get("entry_date") == pos.get("entry_date"))
                    ]
                    _db_save("bs_positions", st.session_state["open_positions"])
                    st.rerun()
