"""BULL SUTRA Pro — v15.7
═══════════════════════════════════════════════════════════════════
BASE: v15.6-preconfirm — all prior fixes 100% preserved.

NEW: v15.7 — FIVE INTELLIGENCE GAPS CLOSED
─────────────────────────────────────────────────────────────────

GAP-1  RELATIVE LEADERSHIP INTELLIGENCE (compute_rs_leadership)
       RS Line trend analysis — not just rank, but whether the RS Line
       itself is in an uptrend, making new highs, and accelerating.
       Sector-relative leadership: stock vs sector, not just vs Nifty.
       Leadership rotation detector: sector momentum shifts.
       New output keys per stock: RSLineSlope, RSLineHigh, RSLeaderSector,
       RSLeaderScore, RSLeaderLabel (LEADER · IMPROVING · NEUTRAL · LAGGARD)

GAP-2  SMART MONEY BEHAVIOR MODEL (compute_smart_money_model)
       Unifies scattered PCA signals into a behavioral phase narrative:
       synthesizes CMF, hidden accumulation, effort/result, block volume,
       OBV trend, failed breakdowns into a composite SmartMoneyScore (0–100)
       with a behavioral verdict: DISTRIBUTING · NEUTRAL · ABSORBING ·
       ACCUMULATING · MARKUP_READY.
       New keys: SmartMoneyScore, SmartMoneyVerdict, SMBehaviorPhase,
       SMConfidence, SMCMFScore, SMBlockScore, SMOBVScore, SMAbsorptionScore.

GAP-3  ACCUMULATION SEQUENCING (compute_accumulation_sequence)
       Detects WHERE in the Wyckoff/Weinstein sequence a stock sits:
       Stage 1A (base building), 1B (testing), 1C (spring/test),
       2A (early markup), 2B (continuation). Uses PCA+EmScore+Phase+
       RS trajectory together to infer sequence position.
       New keys: AccumStage, AccumStageLabel, AccumSequenceScore,
       AccumConfidence, AccumBarsInBase.

GAP-4  MICROSTRUCTURE LOGIC (compute_microstructure)
       Intrabar order-flow proxies from OHLCV: Close Location Value,
       intrabar delta proxy (up-fraction of range used), bar-by-bar
       absorption ratio, tick imbalance proxy, VWAP micro-deviation,
       wicking asymmetry (buying vs selling pressure per bar).
       New keys: MicroScore, MicroDelta, MicroCLV, MicroAbsorption,
       MicroWickAsym, MicroVWAPDev, MicroLabel.

GAP-5  PRE-CONFIRMATION ACTION TIER (PRE-CONFIRM)
       Removes confirmation dependency bias. Stocks with:
         • PCAScore ≥ 55 AND EmScore ≥ 40
         • Phase in SETUP/IDLE (not yet confirmed)
         • SmartMoneyVerdict in (ABSORBING, ACCUMULATING, MARKUP_READY)
         • AccumStage in (1B, 1C, 2A) — inside the base, not after breakout
       receive Action = "PRE-CONFIRM" — a first-class alert tier that surfaces
       BEFORE price confirmation, distinct from both WATCH (score-based)
       and BUY (price-confirmed). Breadth gate does not suppress PRE-CONFIRM.
       PRE-CONFIRM stocks sort above WATCH in Emerging tab.
─────────────────────────────────────────────────────────────────
Integration points:
  • score_stock() — all 4 new compute_* functions appended to result dict
  • run_scan() — sector-relative RS enrichment pass (like EmSectorMom)
  • action_label() — extended with PRE-CONFIRM tier
  • run_scan() breadth gate — exempt PRE-CONFIRM from capping
  • Emerging tab UI — PRE-CONFIRM badge + AccumStage + SmartMoney verdict
  • Main table — RSLeaderLabel, SmartMoneyVerdict, AccumStage columns
═══════════════════════════════════════════════════════════════════
All v15.6 / v15.5 / v15.4 / v15.3 / v14.3 fixes unchanged.
"""


import warnings
import logging
import time
import os
import threading
import concurrent.futures
import asyncio
import json
import hashlib
import struct
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
import streamlit as st

# ── Optional fast-path imports ─────────────────────────────────────────────────
try:
    import polars as pl
    _POLARS_OK = True
except ImportError:
    _POLARS_OK = False

try:
    import aiohttp
    _AIOHTTP_OK = True
except ImportError:
    _AIOHTTP_OK = False
    import yfinance as yf          # fallback

try:
    import pyarrow                 # needed for parquet cache
    _PARQUET_OK = True
except ImportError:
    _PARQUET_OK = False

try:
    import psycopg2 as _psycopg2
    _DB_OK = True
except ImportError:
    _DB_OK = False

logging.getLogger("yfinance").setLevel(logging.CRITICAL)
warnings.filterwarnings("ignore")

# ── Cache directory ────────────────────────────────────────────────────────────
_CACHE_DIR = Path(os.environ.get("BS_CACHE_DIR", "/tmp/bull_sutra_cache"))
_CACHE_DIR.mkdir(parents=True, exist_ok=True)

# ── Universes ──────────────────────────────────────────────────────────────────
try:
    from sectors import SECTORS as _SECTORS
except ImportError:
    _SECTORS = None
    try:
        import urllib.request, types as _types, hashlib as _hashlib
        _GH_SECTORS_URL = (
            "https://raw.githubusercontent.com/srikanthgodavarthy/nse-scan/main/sectors.py"
        )
        # SECURITY NOTE: exec() on remote code is a risk. Pin to a known SHA-256 or
        # bundle sectors.py locally. The hash check below should be updated whenever
        # sectors.py changes on the remote. Set _SECTORS_EXPECTED_SHA = None to skip.
        _SECTORS_EXPECTED_SHA = None   # e.g. "abc123..." — set to your known hash
        with urllib.request.urlopen(_GH_SECTORS_URL, timeout=10) as _resp:
            _src_bytes = _resp.read()
        if _SECTORS_EXPECTED_SHA is not None:
            _actual_sha = _hashlib.sha256(_src_bytes).hexdigest()
            if _actual_sha != _SECTORS_EXPECTED_SHA:
                raise RuntimeError(
                    f"sectors.py integrity check failed: got {_actual_sha[:16]}…"
                )
        _src = _src_bytes.decode("utf-8")
        _mod = _types.ModuleType("sectors_remote")
        exec(compile(_src, "<sectors_gh>", "exec"), _mod.__dict__)
        _SECTORS = getattr(_mod, "SECTORS", None)
    except Exception:
        _SECTORS = None

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

# ── SECTOR_MAP ─────────────────────────────────────────────────────────────────
SECTOR_MAP: dict[str, str] = {}

_CSV_GH_URL = (
    "https://raw.githubusercontent.com/srikanthgodavarthy/nse-scan/main/nse500_clean_sample.csv"
)

def _load_sector_csv(source) -> dict:
    _df = pd.read_csv(source)
    _df["Symbol"] = _df["Symbol"].astype(str).str.replace(".NS","",regex=False).str.strip()
    _sector_col = "Sector" if "Sector" in _df.columns else "Industry"
    _df[_sector_col] = _df[_sector_col].astype(str).str.strip().str.title()
    return dict(zip(_df["Symbol"], _df[_sector_col]))

try:
    SECTOR_MAP = _load_sector_csv(_CSV_GH_URL)
except Exception:
    try:
        SECTOR_MAP = _load_sector_csv("nse500_clean_sample.csv")
    except Exception:
        pass

if not SECTOR_MAP:
    if _SECTORS:
        for _sector_name, _syms in _SECTORS.items():
            if _syms is None:
                continue
            for _sym in _syms:
                if _sym not in SECTOR_MAP:
                    SECTOR_MAP[_sym] = _sector_name
    if not SECTOR_MAP:
        SECTOR_MAP = {
            "RELIANCE":"Energy & Power","ONGC":"Energy & Power","BPCL":"Energy & Power",
            "COALINDIA":"Energy & Power","NTPC":"Energy & Power","POWERGRID":"Energy & Power",
            "ADANIENT":"Energy & Power","ADANIPORTS":"Infrastructure","LT":"Infrastructure",
            "HDFCBANK":"Banking & Finance","ICICIBANK":"Banking & Finance",
            "SBIN":"Banking & Finance","KOTAKBANK":"Banking & Finance",
            "AXISBANK":"Banking & Finance","BAJFINANCE":"Banking & Finance",
            "TCS":"IT & Technology","INFY":"IT & Technology","WIPRO":"IT & Technology",
            "HCLTECH":"IT & Technology","TECHM":"IT & Technology",
            "SUNPHARMA":"Pharma & Healthcare","DRREDDY":"Pharma & Healthcare",
            "CIPLA":"Pharma & Healthcare","HINDUNILVR":"FMCG & Consumer",
            "ITC":"FMCG & Consumer","NESTLEIND":"FMCG & Consumer",
            "TATASTEEL":"Metals & Mining","JSWSTEEL":"Metals & Mining",
            "MARUTI":"Auto & Auto Ancillaries","TATAMOTORS":"Auto & Auto Ancillaries",
        }

# ── Mode config ────────────────────────────────────────────────────────────────
MODE_CFG = {
    "Intraday":   dict(period="5d",  interval="5m",  ema_fast=9,  ema_slow=21,
                       atr_mult=1.5, atr_wide=3.0, atr_max=1.0,
                       mom1_th=2, mom3_th=5, mom6_th=8, score_th=65, rsi_len=14,
                       htf_period="3mo", htf_interval="15m", validity_hours=4,
                       yf_period="5d",  yf_interval="5m",
                       live_interval="1m", hist_min_bars=60),
    "Swing":      dict(period="1y",  interval="1d",  ema_fast=50, ema_slow=200,
                       atr_mult=2.5, atr_wide=4.0, atr_max=1.5,
                       mom1_th=3, mom3_th=7, mom6_th=10, score_th=70, rsi_len=21,
                       htf_period="2y", htf_interval="1wk", validity_hours=72,
                       yf_period="1y",  yf_interval="1d",
                       live_interval="1d", hist_min_bars=50),
    "Positional": dict(period="2y",  interval="1d",  ema_fast=50, ema_slow=200,
                       atr_mult=3.5, atr_wide=5.0, atr_max=1.5,
                       mom1_th=5, mom3_th=10, mom6_th=15, score_th=70, rsi_len=21,
                       htf_period="5y", htf_interval="1wk", validity_hours=240,
                       yf_period="2y",  yf_interval="1d",
                       live_interval="1d", hist_min_bars=50),
}

BULL_MAX        = 120
ACTION_THRESHOLDS = dict(strong_buy=75, buy=58, watch=42)

PHASE_IDLE  = "IDLE";  PHASE_SETUP = "SETUP"; PHASE_ENTRY = "ENTRY"
PHASE_CONT  = "CONT";  PHASE_BRK   = "BREAKOUT"; PHASE_EXIT = "EXIT"

PHASE_COLORS = {
    PHASE_IDLE:"#555577", PHASE_SETUP:"#b87333",
    PHASE_ENTRY:"#2255cc", PHASE_CONT:"#22aa55",
    PHASE_BRK:"#00dd88",  PHASE_EXIT:"#cc4444",
}
PHASE_ORDER = {
    PHASE_IDLE:0, PHASE_SETUP:1, PHASE_ENTRY:2,
    PHASE_CONT:3, PHASE_BRK:4, PHASE_EXIT:-1,
}

VIX_CALM=15; VIX_CAUTION=20; VIX_STRESS=20  # v15.8-FIX: was 25 — UI said STRESS at 20 but math used 25
LIQUIDITY_MIN_CR = 5.0

EXIT_HOLD="HOLD"; EXIT_WATCH_LBL="EXIT WATCH"
EXIT_SIGNAL_LBL="EXIT SIGNAL"; EXIT_CONFIRM_LBL="EXIT NOW"
EXIT_COLORS = {
    EXIT_HOLD:"#22aa55", EXIT_WATCH_LBL:"#f59e0b",
    EXIT_SIGNAL_LBL:"#ff8800", EXIT_CONFIRM_LBL:"#cc4444",
}

SHORT_SKIP="SKIP"; SHORT_WATCH="SHORT WATCH"
SHORT_SIGNAL="SHORT SIGNAL"; SHORT_CONFIRMED="SHORT NOW"
SHORT_COLORS = {
    SHORT_SKIP:"#555577", SHORT_WATCH:"#f59e0b",
    SHORT_SIGNAL:"#ff6b35", SHORT_CONFIRMED:"#cc2244",
}
SHORT_SCORE_WATCH=25; SHORT_SCORE_SIGNAL=45
SHORT_SCORE_CONFIRMED=68; SHORT_HARD_WEIGHT=22; SHORT_SOFT_WEIGHT=9

NSE_OPEN_HOUR=9;  NSE_OPEN_MIN=15
NSE_CLOSE_HOUR=15; NSE_CLOSE_MIN=30
NSE_SESSION_MINUTES = (NSE_CLOSE_HOUR*60+NSE_CLOSE_MIN)-(NSE_OPEN_HOUR*60+NSE_OPEN_MIN)

_phase_lock = threading.Lock()

# ══════════════════════════════════════════════════════════════════════════════
# SPEED-3: PARQUET CACHE  — Historical bars cached; only live tail fetched
# ══════════════════════════════════════════════════════════════════════════════

def _cache_path(sym: str, interval: str) -> Path:
    return _CACHE_DIR / f"{sym.replace('.NS','').upper()}_{interval}.parquet"

# ══════════════════════════════════════════════════════════════════════════════
# Key change: call _normalize_index so the returned DataFrame always has a
# tz-aware DatetimeIndex regardless of how pyarrow or Polars reconstructed it.
# ══════════════════════════════════════════════════════════════════════════════

def _load_cached(sym: str, interval: str) -> Optional[pd.DataFrame]:
    """Load cached historical bars; always returns a tz-aware DatetimeIndex."""
    p = _cache_path(sym, interval)
    if not p.exists():
        return None
    try:
        if _POLARS_OK:
            # Polars may strip tz info on round-trip; _normalize_index fixes it
            df = pl.read_parquet(p).to_pandas()
        else:
            df = pd.read_parquet(p)
        return _normalize_index(df)
    except Exception:
        return None

# ══════════════════════════════════════════════════════════════════════════════
# NEW HELPER — insert once, just above _save_cached
# ══════════════════════════════════════════════════════════════════════════════
_IST = "Asia/Kolkata"

def _normalize_index(df: pd.DataFrame) -> pd.DataFrame:
    """
    Guarantee that df has a tz-aware DatetimeIndex in Asia/Kolkata.

    Handles three situations that arise at the cache/fetch boundary:
      1. Index is already a tz-aware DatetimeIndex (live fetch path) → convert tz.
      2. Index is a tz-naive DatetimeIndex (Polars round-trip strips tz) → localize.
      3. Index is RangeIndex and a datetime column exists (save/load mismatch) → promote.
    """
    if df is None or df.empty:
        return df

    # ── Case 3: index column was saved as a data column ──────────────────────
    if not isinstance(df.index, pd.DatetimeIndex):
        for col in ("ts", "Datetime", "datetime", "index", "Date", "date"):
            if col in df.columns:
                df = df.copy()
                series = pd.to_datetime(df[col], errors="coerce")
                if series.dt.tz is None:
                    series = series.dt.tz_localize("UTC").dt.tz_convert(_IST)
                else:
                    series = series.dt.tz_convert(_IST)
                df.index = series
                df = df.drop(columns=[col])
                break

    # ── Cases 1 & 2: fix timezone on existing DatetimeIndex ──────────────────
    if isinstance(df.index, pd.DatetimeIndex):
        if df.index.tz is None:
            df.index = df.index.tz_localize("UTC").tz_convert(_IST)
        elif str(df.index.tz) != _IST:
            df.index = df.index.tz_convert(_IST)

    return df
# ══════════════════════════════════════════════════════════════════════════════
# Key change: save the timestamp column as "ts" (predictable name) instead of
# relying on the default "index" name that reset_index() produces.
# ══════════════════════════════════════════════════════════════════════════════
def _save_cached(sym: str, interval: str, df: pd.DataFrame):
    """Save historical bars to parquet with a reliable 'ts' timestamp column."""
    if not _PARQUET_OK:
        return
    try:
        p       = _cache_path(sym, interval)
        df_save = df.copy()
        if isinstance(df_save.index, pd.DatetimeIndex):
            df_save.index.name = "ts"          # always 'ts', never unnamed "index"
            df_save = df_save.reset_index()
        df_save.to_parquet(p, index=False, compression="snappy")
    except Exception:
        pass


def _cache_is_fresh(sym: str, interval: str, max_age_hours: float) -> bool:
    p = _cache_path(sym, interval)
    if not p.exists():
        return False
    age = (time.time() - p.stat().st_mtime) / 3600
    return age < max_age_hours

def _is_market_open() -> bool:
    now_ist = datetime.utcnow() + timedelta(hours=5, minutes=30)
    if now_ist.weekday() >= 5:
        return False
    minutes = now_ist.hour * 60 + now_ist.minute
    open_m  = NSE_OPEN_HOUR * 60 + NSE_OPEN_MIN
    close_m = NSE_CLOSE_HOUR * 60 + NSE_CLOSE_MIN
    return open_m <= minutes <= close_m

def _cold_start_needed(mode: str) -> bool:
    """True if we haven't done a full historical fetch today."""
    flag = _CACHE_DIR / f"cold_start_{mode}_{datetime.utcnow().date()}.flag"
    return not flag.exists()

def _mark_cold_start_done(mode: str):
    flag = _CACHE_DIR / f"cold_start_{mode}_{datetime.utcnow().date()}.flag"
    flag.touch()

# ══════════════════════════════════════════════════════════════════════════════
# SPEED-1: ASYNC HTTP  — Direct Yahoo Finance v8 API
# ══════════════════════════════════════════════════════════════════════════════

_YF_BASE = "https://query1.finance.yahoo.com/v8/finance/chart"
_YF_HDR  = {
    "User-Agent": "Mozilla/5.0 (compatible; BullSutra/15)",
    "Accept":     "application/json",
}

def _yf_period_to_range(period: str):
    """Map yfinance period string → (range1, range2) for Yahoo v8 API."""
    _map = {
        "5d":"5d","1mo":"1mo","3mo":"3mo","6mo":"6mo",
        "1y":"1y","2y":"2y","5y":"5y","ytd":"ytd","max":"max",
    }
    return _map.get(period, "1y")

def _parse_yahoo_v8(data: dict, sym: str) -> pd.DataFrame:
    """Parse Yahoo v8 JSON response → OHLCV DataFrame."""
    try:
        res    = data["chart"]["result"][0]
        ts     = res["timestamp"]
        ohlcv  = res["indicators"]["quote"][0]
        adj    = res["indicators"].get("adjclose", [{}])[0].get("adjclose", ohlcv["close"])
        idx    = pd.to_datetime(ts, unit="s", utc=True).tz_convert("Asia/Kolkata")
        df     = pd.DataFrame({
            "Open":   ohlcv["open"],
            "High":   ohlcv["high"],
            "Low":    ohlcv["low"],
            "Close":  adj if adj else ohlcv["close"],
            "Volume": ohlcv["volume"],
        }, index=idx)
        df["Volume"] = df["Volume"].fillna(0)
        return df.dropna(subset=["Close"])
    except Exception:
        return pd.DataFrame()

async def _fetch_one_async(session: "aiohttp.ClientSession",
                           sym: str, period: str, interval: str) -> tuple[str, pd.DataFrame]:
    ticker = sym if sym.endswith(".NS") else sym + ".NS"
    url    = f"{_YF_BASE}/{ticker}"
    params = {"range": _yf_period_to_range(period), "interval": interval,
               "includeAdjustedClose": "true", "events": ""}
    for attempt in range(3):
        try:
            async with session.get(url, params=params, headers=_YF_HDR,
                                   timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status == 200:
                    data = await resp.json(content_type=None)
                    return sym, _parse_yahoo_v8(data, sym)
        except Exception:
            pass
        await asyncio.sleep(0.3 * (attempt + 1))
    return sym, pd.DataFrame()

async def _fetch_live_tail_async(session: "aiohttp.ClientSession",
                                 sym: str, interval: str,
                                 n_bars: int = 3) -> tuple[str, pd.DataFrame]:
    """Fetch only the last n_bars (for live refresh during session)."""
    ticker = sym if sym.endswith(".NS") else sym + ".NS"
    url    = f"{_YF_BASE}/{ticker}"
    period = "1d" if interval in ("1m","5m","15m","30m") else "5d"
    params = {"range": period, "interval": interval,
               "includeAdjustedClose": "true", "events": ""}
    for attempt in range(2):
        try:
            async with session.get(url, params=params, headers=_YF_HDR,
                                   timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    data = await resp.json(content_type=None)
                    df   = _parse_yahoo_v8(data, sym)
                    if not df.empty:
                        return sym, df.iloc[-n_bars:]
        except Exception:
            pass
        await asyncio.sleep(0.3)
    return sym, pd.DataFrame()

async def _batch_fetch_async(symbols: list, period: str, interval: str,
                              concurrency: int = 64) -> dict[str, pd.DataFrame]:
    """Fetch all symbols concurrently using a shared aiohttp session."""
    results: dict[str, pd.DataFrame] = {}
    sem = asyncio.Semaphore(concurrency)

    async def _bounded(sym):
        async with sem:
            return await _fetch_one_async(session, sym, period, interval)

    connector = aiohttp.TCPConnector(limit=concurrency, ttl_dns_cache=300,
                                     enable_cleanup_closed=True)
    async with aiohttp.ClientSession(connector=connector) as session:
        tasks = [asyncio.create_task(_bounded(s)) for s in symbols]
        for coro in asyncio.as_completed(tasks):
            sym, df = await coro
            results[sym] = df
    return results

def fetch_async(symbols: list, period: str, interval: str,
                concurrency: int = 64) -> dict[str, pd.DataFrame]:
    """Sync wrapper: run async fetch in a new event loop (thread-safe)."""
    if not _AIOHTTP_OK:
        return _yf_fallback_batch(symbols, period, interval)
    try:
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(
                _batch_fetch_async(symbols, period, interval, concurrency)
            )
        finally:
            loop.close()
    except Exception:
        return _yf_fallback_batch(symbols, period, interval)

def _yf_fallback_batch(symbols: list, period: str, interval: str) -> dict[str, pd.DataFrame]:
    """Fallback: use yfinance batch download if aiohttp unavailable."""
    import yfinance as yf
    tickers = [s if s.endswith(".NS") else s+".NS" for s in symbols]
    out: dict[str, pd.DataFrame] = {}
    for i in range(0, len(tickers), 50):
        batch = tickers[i:i+50]
        try:
            raw = yf.download(batch, period=period, interval=interval,
                              auto_adjust=True, progress=False, threads=False,
                              group_by="ticker")
            for sym, tkr in zip(symbols[i:i+50], batch):
                try:
                    if isinstance(raw.columns, pd.MultiIndex):
                        if tkr in raw.columns.get_level_values(0):
                            df = raw[tkr].copy()
                        elif tkr in raw.columns.get_level_values(1):
                            df = raw.xs(tkr, axis=1, level=1).copy()
                        else:
                            df = pd.DataFrame()
                    else:
                        df = raw.copy()
                    df["Volume"] = df["Volume"].fillna(0) if not df.empty else df
                    out[sym] = df.dropna(subset=["Close"]) if not df.empty else pd.DataFrame()
                except Exception:
                    out[sym] = pd.DataFrame()
        except Exception:
            for sym in symbols[i:i+50]:
                out[sym] = pd.DataFrame()
    return out

# ══════════════════════════════════════════════════════════════════════════════
# SPEED-3: INCREMENTAL FETCH  — cache + live-tail merge
# ══════════════════════════════════════════════════════════════════════════════




def batch_incremental_fetch(
    symbols: list,
    mode: str,
    force_full: bool = False,
    progress_cb=None,
) -> dict:
    cfg      = MODE_CFG[mode]
    interval = cfg["interval"]
    period   = cfg["yf_period"]
    min_bars = cfg["hist_min_bars"]

    need_full  = []
    can_append = []
    results    = {}

    for sym in symbols:
        c = _load_cached(sym, interval)
        if force_full or c is None or len(c) < min_bars:
            need_full.append(sym)
        else:
            can_append.append(sym)

    total = len(symbols)

    if need_full:
        fresh = fetch_async(need_full, period, interval, concurrency=64)
        for sym, df in fresh.items():
            if not df.empty:
                _save_cached(sym, interval, df)
                results[sym] = df
            else:
                results[sym] = pd.DataFrame()
        if progress_cb:
            progress_cb(len(need_full) / total)

    # Cache staleness thresholds (seconds) — market-closed path also enforces these
    _STALE_SECS = {"Intraday": 900, "Swing": 43200, "Positional": 86400}
    _stale_secs = _STALE_SECS.get(mode, 43200)

    if can_append and _is_market_open():
        live_int = cfg.get("live_interval", interval)
        tails    = fetch_async(can_append, "1d", live_int, concurrency=64)
        done     = len(need_full)
        for sym in can_append:
            cached = _load_cached(sym, interval)
            tail   = tails.get(sym, pd.DataFrame())
            if cached is not None and not tail.empty:
                cached = _normalize_index(cached)
                tail   = _normalize_index(tail)
                merged = pd.concat([cached, tail])
                merged = merged[~merged.index.duplicated(keep="last")].sort_index()
                _save_cached(sym, interval, merged)
                results[sym] = merged
            elif cached is not None:
                results[sym] = cached
            else:
                results[sym] = pd.DataFrame()
            done += 1
            if progress_cb:
                progress_cb(done / total)
    else:
        # FIX-2: enforce staleness even when market is closed; re-fetch stale caches
        stale_syms = [
            sym for sym in can_append
            if not _cache_is_fresh(sym, interval, _stale_secs / 3600)
        ]
        fresh_syms = [sym for sym in can_append if sym not in stale_syms]

        if stale_syms:
            refreshed = fetch_async(stale_syms, period, interval, concurrency=64)
            for sym, df in refreshed.items():
                if not df.empty:
                    _save_cached(sym, interval, df)
                results[sym] = df if not df.empty else pd.DataFrame()

        for sym in fresh_syms:
            cached = _load_cached(sym, interval)
            results[sym] = cached if cached is not None else pd.DataFrame()
        if progress_cb:
            progress_cb(1.0)

    return results

# ══════════════════════════════════════════════════════════════════════════════
# SPEED-4 + SPEED-5: VECTORIZED BATCH INDICATORS (numpy)
# ══════════════════════════════════════════════════════════════════════════════

def _ema_np(arr: np.ndarray, span: int) -> np.ndarray:
    """EMA on 1-D array."""
    alpha  = 2.0 / (span + 1)
    result = np.empty_like(arr)
    result[0] = arr[0]
    for i in range(1, len(arr)):
        result[i] = alpha * arr[i] + (1 - alpha) * result[i-1]
    return result

def _rma_np(arr: np.ndarray, period: int) -> np.ndarray:
    """Wilder's Moving Average (RMA) on 1-D array — alpha = 1/period.
    Used for ADX/DI smoothing to match charting platform values."""
    alpha  = 1.0 / period
    result = np.empty_like(arr)
    result[0] = arr[0]
    for i in range(1, len(arr)):
        result[i] = alpha * arr[i] + (1 - alpha) * result[i-1]
    return result

def _rma_batch(matrix: np.ndarray, period: int) -> np.ndarray:
    """Wilder's Moving Average on (N, T) matrix — alpha = 1/period."""
    alpha  = 1.0 / period
    result = np.empty_like(matrix)
    result[:, 0] = matrix[:, 0]
    beta = 1 - alpha
    for t in range(1, matrix.shape[1]):
        result[:, t] = alpha * matrix[:, t] + beta * result[:, t - 1]
    return result

def _ema_batch(matrix: np.ndarray, span: int) -> np.ndarray:
    """EMA on (N, T) matrix → (N, T). Uses numba if available, else loops."""
    N, T   = matrix.shape
    alpha  = 2.0 / (span + 1)
    result = np.empty_like(matrix)
    result[:, 0] = matrix[:, 0]
    beta = 1 - alpha
    for t in range(1, T):
        result[:, t] = alpha * matrix[:, t] + beta * result[:, t-1]
    return result

def _rsi_batch(close_matrix: np.ndarray, period: int = 14) -> np.ndarray:
    """RSI on (N, T) matrix → (N, T)."""
    N, T   = close_matrix.shape
    diff   = np.diff(close_matrix, axis=1, prepend=close_matrix[:, :1])
    gain   = np.where(diff > 0, diff, 0.0)
    loss   = np.where(diff < 0, -diff, 0.0)
    avg_g  = _ema_batch(gain, period)
    avg_l  = _ema_batch(loss, period)
    rs     = np.where(avg_l == 0, 100.0, avg_g / (avg_l + 1e-10))
    return 100 - (100 / (1 + rs))

def _atr_batch(high: np.ndarray, low: np.ndarray,
               close: np.ndarray, period: int = 14) -> np.ndarray:
    """ATR on (N, T) matrices → (N, T)."""
    prev_close = np.roll(close, 1, axis=1)
    prev_close[:, 0] = close[:, 0]
    tr = np.maximum(high - low,
         np.maximum(np.abs(high - prev_close), np.abs(low - prev_close)))
    return _ema_batch(tr, period)

def _adx_batch(high: np.ndarray, low: np.ndarray,
               close: np.ndarray, period: int = 14) -> np.ndarray:
    """ADX on (N, T) → returns ADX values (N, T).
    Uses Wilder's RMA (alpha=1/period) to match standard charting platform values."""
    prev_high  = np.roll(high,  1, axis=1); prev_high[:,  0] = high[:,  0]
    prev_low   = np.roll(low,   1, axis=1); prev_low[:,   0] = low[:,   0]
    prev_close = np.roll(close, 1, axis=1); prev_close[:, 0] = close[:, 0]

    up_move   = high  - prev_high
    down_move = prev_low - low
    plus_dm   = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm  = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

    tr = np.maximum(high - low,
         np.maximum(np.abs(high - prev_close), np.abs(low - prev_close)))

    atr_s     = _rma_batch(tr,        period)
    plus_di   = 100 * _rma_batch(plus_dm,  period) / (atr_s + 1e-10)
    minus_di  = 100 * _rma_batch(minus_dm, period) / (atr_s + 1e-10)
    dx        = 100 * np.abs(plus_di - minus_di) / (plus_di + minus_di + 1e-10)
    adx       = _rma_batch(dx, period)
    return adx

def _bb_squeeze_batch(close: np.ndarray, high: np.ndarray, low: np.ndarray,
                      period: int = 20, bb_mult: float = 2.0,
                      kc_mult: float = 1.5) -> np.ndarray:
    """
    Keltner/BB Squeeze detector.
    Returns boolean (N, T) — True = squeeze (BB inside KC).
    """
    N, T = close.shape
    # Rolling mean + std (approx with EMA for speed)
    mid    = _ema_batch(close, period)
    # Approximate rolling std via EMA of squared deviations
    dev2   = _ema_batch((close - mid) ** 2, period)
    std    = np.sqrt(np.maximum(dev2, 0))
    bb_up  = mid + bb_mult * std
    bb_lo  = mid - bb_mult * std
    # Keltner channels via ATR
    atr_k  = _atr_batch(high, low, close, period)
    kc_up  = mid + kc_mult * atr_k
    kc_lo  = mid - kc_mult * atr_k
    # Squeeze = BB inside KC
    squeeze = (bb_up <= kc_up) & (bb_lo >= kc_lo)
    return squeeze

def _vol_contraction_batch(atr_matrix: np.ndarray) -> np.ndarray:
    """
    Volatility contraction ratio: ATR_5 / ATR_20.
    Values < 0.75 indicate compression.
    Returns (N,) array of latest ratios.
    """
    atr_short = _ema_batch(atr_matrix, 5)
    atr_long  = _ema_batch(atr_matrix, 20)
    ratio = atr_short[:, -1] / (atr_long[:, -1] + 1e-10)
    return ratio

# ══════════════════════════════════════════════════════════════════════════════
# SPEED-2: TWO-STAGE SCAN
#  Stage-A: fast pre-filter (price, volume, EMA) — eliminates ~65% of symbols
#  Stage-B: full engine on survivors
# ══════════════════════════════════════════════════════════════════════════════

def stage_a_prefilter(data: dict[str, pd.DataFrame],
                       mode: str, min_bars: int = 30) -> list[str]:
    """
    Vectorized pre-filter: build (N × T) matrices, compute EMA alignment
    and basic volume check for all symbols in one pass.
    Returns list of symbols that PASS the pre-filter.
    """
    cfg      = MODE_CFG[mode]
    ef_span  = cfg["ema_fast"]
    es_span  = cfg["ema_slow"]

    symbols  = [s for s, df in data.items()
                if df is not None and not df.empty and len(df) >= min_bars]
    if not symbols:
        return []

    # Align all close series to same length (pad left with first value)
    max_len = max(len(data[s]) for s in symbols)
    closes  = np.zeros((len(symbols), max_len), dtype=np.float32)
    vols    = np.zeros((len(symbols), max_len), dtype=np.float32)

    for i, sym in enumerate(symbols):
        cl = data[sym]["Close"].values.astype(np.float32)
        n  = len(cl)
        closes[i, max_len - n:] = cl
        vols[i,   max_len - n:] = data[sym]["Volume"].values.astype(np.float32)
        # left-pad with first real value
        if n < max_len:
            closes[i, :max_len - n] = cl[0]
            vols[i,   :max_len - n] = vols[i, max_len - n]

    ef = _ema_batch(closes, ef_span)
    es = _ema_batch(closes, es_span)

    c_last  = closes[:, -1]
    ef_last = ef[:, -1]
    es_last = es[:, -1]

    # EMA alignment gate: price above fast EMA OR fast > slow (either is enough for watchlist)
    ema_ok  = (c_last > ef_last) | (ef_last > es_last)

    # Volume gate: latest volume > 0
    vol_ok  = vols[:, -1] > 0

    # Price gate: > 10 (penny stock filter)
    price_ok = c_last > 10.0

    # Combined filter
    passed = ema_ok & vol_ok & price_ok
    survivors = [sym for sym, ok in zip(symbols, passed.tolist()) if ok]
    return survivors

# ══════════════════════════════════════════════════════════════════════════════
# MATH HELPERS (unchanged from v14)
# ══════════════════════════════════════════════════════════════════════════════

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
        "236": sw_hi-rng*0.236,"382":sw_hi-rng*0.382,
        "500":sw_hi-rng*0.500, "618":sw_hi-rng*0.618,
        "786":sw_hi-rng*0.786,
        "ext127":sw_hi+rng*0.272,"ext161":sw_hi+rng*0.618,
        "ext261":sw_hi+rng*1.618,
    }, rng

def action_label(norm_score: float) -> str:
    if norm_score >= ACTION_THRESHOLDS["strong_buy"]: return "STRONG BUY"
    if norm_score >= ACTION_THRESHOLDS["buy"]:        return "BUY"
    if norm_score >= ACTION_THRESHOLDS["watch"]:      return "WATCH"
    return "SKIP"

def action_label_with_preconfirm(
    norm_score: float,
    pca_score: float = 0.0,
    em_score: float = 0.0,
    phase: str = "IDLE",
    smart_money_verdict: str = "NEUTRAL",
    accum_stage: str = "NONE",
) -> str:
    """
    GAP-5 — Extended action label with PRE-CONFIRM tier.

    PRE-CONFIRM fires when:
      • Phase is SETUP or IDLE (price hasn't confirmed yet)
      • PCAScore ≥ 55 (strong buying pressure evidence)
      • EmScore ≥ 40 (coiling mechanics present)
      • SmartMoneyVerdict in (ABSORBING, ACCUMULATING, MARKUP_READY)
      • AccumStage in (1B, 1C, 2A) — inside the base or just leaving it

    PRE-CONFIRM sits between WATCH and BUY in the action hierarchy.
    It cannot be suppressed by the breadth gate (pre-confirmation stocks
    are precisely those that haven't run yet).
    """
    base = action_label(norm_score)
    # Only consider upgrade to PRE-CONFIRM for unconfirmed phases
    if phase not in (PHASE_SETUP, PHASE_IDLE):
        return base
    # Must already pass WATCH threshold (some signal quality required)
    if norm_score < ACTION_THRESHOLDS["watch"]:
        return base
    # Gate: strong buying pressure evidence required
    if pca_score < 55:
        return base
    # Gate: coiling mechanics required
    if em_score < 40:
        return base
    # Gate: smart money must show at least absorption
    if smart_money_verdict not in ("ABSORBING", "ACCUMULATING", "MARKUP_READY"):
        return base
    # Gate: must be inside an identified accumulation base (not random)
    if accum_stage not in ("1B", "1C", "2A"):
        return base
    return "PRE-CONFIRM"

def fmt(val):
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return "—"
    return f"₹{val:,.2f}"

def _session_elapsed_fraction() -> float:
    now_ist  = datetime.utcnow() + timedelta(hours=5, minutes=30)
    minutes_since_open = (now_ist.hour*60+now_ist.minute)-(NSE_OPEN_HOUR*60+NSE_OPEN_MIN)
    fraction = minutes_since_open / NSE_SESSION_MINUTES
    return float(np.clip(fraction, 0.05, 1.0))

def _intraday_vol_avg(volume: pd.Series, bars_per_day: int) -> float:
    elapsed_frac = _session_elapsed_fraction()
    today_bars   = int(min(bars_per_day*elapsed_frac+1, len(volume)))
    today_vol    = float(volume.iloc[-today_bars:].sum())
    today_proj   = today_vol / elapsed_frac
    if len(volume) > bars_per_day + today_bars:
        prior = volume.iloc[:-(today_bars)].rolling(bars_per_day).sum().dropna()
        prior_daily = prior.iloc[-5:].values.tolist()
    else:
        prior_daily = []
    all_days = prior_daily + [today_proj]
    return float(np.mean(all_days)) if all_days else float(volume.mean()*bars_per_day)

# ══════════════════════════════════════════════════════════════════════════════
# SIGNAL VALIDITY
# ══════════════════════════════════════════════════════════════════════════════

def signal_is_stale(logged_at_iso: str, mode: str) -> bool:
    try:
        validity_h = MODE_CFG[mode].get("validity_hours", 72)
        logged_at  = datetime.fromisoformat(logged_at_iso)
        return (datetime.now()-logged_at) > timedelta(hours=validity_h)
    except Exception:
        return False

def signal_age_label(logged_at_iso: str, mode: str) -> str:
    try:
        validity_h = MODE_CFG[mode].get("validity_hours", 72)
        logged_at  = datetime.fromisoformat(logged_at_iso)
        delta      = datetime.now()-logged_at
        hours      = delta.total_seconds()/3600
        stale      = hours > validity_h
        if hours < 1:   age_str = f"{int(delta.total_seconds()/60)}m ago"
        elif hours < 24: age_str = f"{hours:.1f}h ago"
        else:            age_str = f"{hours/24:.1f}d ago"
        return age_str, stale
    except Exception:
        return "unknown", False

# ══════════════════════════════════════════════════════════════════════════════
# VIX
# ══════════════════════════════════════════════════════════════════════════════

@st.cache_data(ttl=300)
def fetch_vix():
    try:
        raw = fetch_async(["^INDIAVIX"], "5d", "1d", concurrency=1)
        df  = raw.get("^INDIAVIX", pd.DataFrame())
        if df.empty:
            import yfinance as yf
            df = yf.download("^INDIAVIX", period="5d", interval="1d",
                             auto_adjust=True, progress=False, threads=False)
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            df = df.dropna()
        if df.empty:
            return None, "UNKNOWN"
        v = float(df["Close"].iloc[-1])
        label = "CALM" if v < VIX_CALM else ("CAUTION" if v < VIX_CAUTION else "STRESS")
        return round(v, 2), label
    except Exception:
        return None, "UNKNOWN"

def vix_target_mult(vix_val):
    if vix_val is None or vix_val < VIX_CAUTION: return 1.0, 2.0, 3.0, 1.0
    if vix_val < VIX_STRESS:                      return 0.75, 1.4, 2.0, 1.2
    return 0.6, 1.1, 1.6, 1.35

# ══════════════════════════════════════════════════════════════════════════════
# LIQUIDITY FILTER
# ══════════════════════════════════════════════════════════════════════════════

def liquidity_ok(df, min_cr=LIQUIDITY_MIN_CR, mode="Swing"):
    try:
        traded   = df["Close"] * df["Volume"]
        n_rows   = len(df)
        if n_rows >= 2:
            try:
                delta_min = (df.index[1]-df.index[0]).total_seconds()/60
            except Exception:
                delta_min = 1440
        else:
            delta_min = 1440
        if delta_min <= 5:     bars_per_day = 75
        elif delta_min <= 15:  bars_per_day = 25
        elif delta_min <= 30:  bars_per_day = 13
        elif delta_min < 240:  bars_per_day = 7
        else:                  bars_per_day = 1
        if mode == "Intraday" and bars_per_day > 1:
            avg_daily_vol = _intraday_vol_avg(df["Volume"], bars_per_day)
            avg_cr        = float(avg_daily_vol*float(df["Close"].iloc[-1]))/1e7
        else:
            daily_traded = traded.rolling(bars_per_day).sum()
            avg_cr       = float(daily_traded.rolling(20).mean().iloc[-1])/1e7
        return avg_cr >= min_cr, round(avg_cr, 1)
    except Exception:
        return True, 0.0

# ══════════════════════════════════════════════════════════════════════════════
# SPEED-6: HTF — single shared cache, parallel pre-fetch
# ══════════════════════════════════════════════════════════════════════════════

@st.cache_data(ttl=900)
def _fetch_htf_cached(ticker: str, period: str, interval: str) -> pd.DataFrame:
    raw = fetch_async([ticker.replace(".NS","")], period, interval, concurrency=1)
    df  = raw.get(ticker.replace(".NS",""), pd.DataFrame())
    if df.empty:
        # fallback
        try:
            import yfinance as yf
            df = yf.download(ticker, period=period, interval=interval,
                             auto_adjust=True, progress=False, threads=False)
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            df = df.dropna()
        except Exception:
            pass
    return df

def _htf_trend_from_df(df: pd.DataFrame, mode: str):
    if df is None or df.empty: return True, "HTF-UNKNOWN"
    if mode == "Intraday" and len(df) > 2: df = df.iloc[:-1].copy()
    min_bars = 55 if mode == "Intraday" else 26
    if len(df) < min_bars: return True, "HTF-UNKNOWN"
    cl = df["Close"]
    ef = float(ema(cl, 21 if mode == "Intraday" else 13).iloc[-1])
    es = float(ema(cl, 55 if mode == "Intraday" else 26).iloc[-1])
    c  = float(cl.iloc[-1])
    up = c > ef > es
    return up, ("HTF↑" if up else "HTF↓")

def prefetch_htf_parallel(symbols: list, mode: str, status_text, progress_bar) -> dict:
    cfg    = MODE_CFG[mode]
    total  = len(symbols)
    # Batch async HTF fetch
    raw    = fetch_async(symbols, cfg["htf_period"], cfg["htf_interval"], concurrency=64)
    results = {}
    for i, sym in enumerate(symbols):
        df = raw.get(sym, pd.DataFrame())
        results[sym] = _htf_trend_from_df(df, mode)
        if i % 20 == 0:
            progress_bar.progress(0.15 + i/total*0.25)
    return results

# ══════════════════════════════════════════════════════════════════════════════
# RS RANKS (vectorized, unchanged)
# ══════════════════════════════════════════════════════════════════════════════

def compute_rs_ranks(sym_returns: dict) -> dict:
    if not sym_returns: return {}
    syms  = list(sym_returns.keys())
    vals  = np.array([sym_returns[s] for s in syms], dtype=np.float64)
    order = np.argsort(vals)
    ranks = np.empty_like(order)
    ranks[order] = np.arange(len(vals))
    normalized = np.round(ranks/max(len(vals)-1,1)*100).astype(int)
    return dict(zip(syms, normalized.tolist()))

def _52w_return(close_series: pd.Series) -> float:
    if len(close_series) < 10: return 0.0
    lookback = min(252, len(close_series)-1)
    c_now  = float(close_series.iloc[-1])
    c_base = float(close_series.iloc[-lookback])
    if c_base == 0: return 0.0
    return round((c_now-c_base)/c_base*100, 2)

# ══════════════════════════════════════════════════════════════════════════════
# GAP-1 — RELATIVE LEADERSHIP INTELLIGENCE
# Analyses the RS Line (stock/index ratio) as a price series in its own right.
# Captures RS-line trend, new-highs, acceleration, and sector-relative rank.
# ══════════════════════════════════════════════════════════════════════════════

def compute_rs_leadership(
    close: pd.Series,
    nifty_close: pd.Series,
    rs_rank: int = 50,
    sector_avg_score: float = 50.0,
    stock_score: float = 50.0,
) -> dict:
    """
    Relative Leadership Intelligence (0–100 RSLeaderScore).

    Components:
    1. RS Line Slope         (25 pts) — RS line EMA slope: rising vs falling
    2. RS Line New High      (20 pts) — RS line at multi-week high vs prior peak
    3. RS Acceleration       (20 pts) — recent RS outperformance accelerating
    4. Sector-Relative Lead  (20 pts) — stock score vs sector average score
    5. RS Rank Tier          (15 pts) — percentile rank bonus

    Labels: LEADER ≥75 · IMPROVING ≥55 · NEUTRAL ≥35 · LAGGARD <35
    """
    out = dict(
        RSLeaderScore=0, RSLeaderLabel="NEUTRAL",
        RSLineSlope=0.0, RSLineHigh=False,
        RSLineSlopeRaw=0.0, RSLeaderSector=0.0,
    )
    try:
        n_stock = len(close)
        n_nifty = len(nifty_close)
        if n_stock < 30 or n_nifty < 30:
            return out

        # Align lengths
        min_len = min(n_stock, n_nifty)
        cl  = close.values[-min_len:].astype(np.float64)
        nif = nifty_close.values[-min_len:].astype(np.float64)
        n   = len(cl)

        # RS Line = stock / nifty (ratio series)
        rs_line = cl / (nif + 1e-10)

        # ── 1. RS Line Slope (0–25 pts) ─────────────────────────────────────
        slope_pts = 0.0
        rs_slope_raw = 0.0
        try:
            lb = min(20, n - 1)
            rs_ema10 = _ema_np(rs_line, 10)
            rs_ema20 = _ema_np(rs_line, 20)
            # Slope = % change in RS EMA10 over lb bars
            rs_slope_raw = (rs_ema10[-1] - rs_ema10[-lb]) / (rs_ema10[-lb] + 1e-10) * 100
            # EMA alignment on RS line itself
            rs_ema_bull = rs_ema10[-1] > rs_ema20[-1]
            if   rs_slope_raw > 5  and rs_ema_bull: slope_pts = 25.0
            elif rs_slope_raw > 2  and rs_ema_bull: slope_pts = 20.0
            elif rs_slope_raw > 0  and rs_ema_bull: slope_pts = 14.0
            elif rs_slope_raw > 0:                  slope_pts = 8.0
            elif rs_slope_raw > -2:                 slope_pts = 3.0
        except Exception:
            pass

        # ── 2. RS Line New High (0–20 pts) ──────────────────────────────────
        rslh_pts = 0.0
        rs_line_high = False
        try:
            # Compare current RS line vs 10-week (50-bar) and 6-week (30-bar) highs
            lb_rslh = min(50, n - 1)
            rs_prior_high_50 = float(np.max(rs_line[-lb_rslh:-1]))
            rs_prior_high_30 = float(np.max(rs_line[-min(30, n-1):-1]))
            rs_now = float(rs_line[-1])
            if rs_now > rs_prior_high_50:
                rslh_pts = 20.0; rs_line_high = True
            elif rs_now > rs_prior_high_30:
                rslh_pts = 13.0; rs_line_high = True
            elif rs_now > rs_prior_high_50 * 0.97:
                rslh_pts = 7.0   # within 3% of 50-bar RS high
        except Exception:
            pass

        # ── 3. RS Acceleration (0–20 pts) ───────────────────────────────────
        rsaccel_pts = 0.0
        try:
            def _rs_delta(bars):
                if n < bars + 1: return 0.0
                s = (cl[-1] - cl[-bars]) / (cl[-bars] + 1e-10) * 100
                m = (nif[-1] - nif[-bars]) / (nif[-bars] + 1e-10) * 100
                return s - m
            rs5, rs10, rs20 = _rs_delta(5), _rs_delta(10), _rs_delta(20)
            if rs5 > rs10 > rs20 > 0:        rsaccel_pts = 20.0   # triple acceleration
            elif rs5 > rs10 > 0:             rsaccel_pts = 15.0   # double acceleration
            elif rs5 > 0 and rs5 > rs20:     rsaccel_pts = 9.0    # recent vs long
            elif rs5 > 0:                    rsaccel_pts = 4.0
        except Exception:
            pass

        # ── 4. Sector-Relative Leadership (0–20 pts) ────────────────────────
        sec_pts = 0.0
        try:
            diff = stock_score - sector_avg_score
            if   diff >= 20: sec_pts = 20.0
            elif diff >= 10: sec_pts = 15.0
            elif diff >= 5:  sec_pts = 10.0
            elif diff >= 0:  sec_pts = 5.0
            elif diff >= -5: sec_pts = 2.0
        except Exception:
            pass

        # ── 5. RS Rank Tier (0–15 pts) ───────────────────────────────────────
        rank_pts = 0.0
        if   rs_rank >= 90: rank_pts = 15.0
        elif rs_rank >= 80: rank_pts = 12.0
        elif rs_rank >= 70: rank_pts = 8.0
        elif rs_rank >= 60: rank_pts = 5.0
        elif rs_rank >= 40: rank_pts = 2.0

        total = round(float(np.clip(
            slope_pts + rslh_pts + rsaccel_pts + sec_pts + rank_pts,
            0, 100
        )), 1)
        label = (
            "LEADER"   if total >= 75 else
            "IMPROVING" if total >= 55 else
            "NEUTRAL"   if total >= 35 else
            "LAGGARD"
        )
        out.update(
            RSLeaderScore   = total,
            RSLeaderLabel   = label,
            RSLineSlope     = round(slope_pts, 1),
            RSLineHigh      = rs_line_high,
            RSLineSlopeRaw  = round(rs_slope_raw, 2),
            RSLeaderSector  = round(sec_pts, 1),
        )
    except Exception:
        pass
    return out

# ══════════════════════════════════════════════════════════════════════════════
# PHASE TRANSITION MEMORY (unchanged)
# ══════════════════════════════════════════════════════════════════════════════

def record_phase_transition(sym: str, new_phase: str):
    if "phase_history" not in st.session_state:
        st.session_state["phase_history"] = {}
    history = st.session_state["phase_history"]
    if sym not in history: history[sym] = []
    prev_phase = history[sym][-1][1] if history[sym] else None
    changed = prev_phase != new_phase
    is_prog = is_regr = False
    arrow   = ""
    if changed:
        ts = datetime.now().isoformat()
        history[sym].append((ts, new_phase))
        history[sym] = history[sym][-10:]
        if prev_phase is not None:
            prev_ord = PHASE_ORDER.get(prev_phase, 0)
            new_ord  = PHASE_ORDER.get(new_phase, 0)
            if new_phase == PHASE_EXIT:             arrow="→EXIT"; is_regr=True
            elif new_ord > prev_ord:                arrow=f"↗{new_phase}"; is_prog=True
            elif new_ord < prev_ord and new_phase!=PHASE_EXIT: arrow=f"↘{new_phase}"; is_regr=True
    return changed, arrow, is_prog, is_regr

def phase_transition_conf_bonus(sym: str) -> int:
    history = st.session_state.get("phase_history", {})
    if sym not in history or len(history[sym]) < 3: return 0
    last3 = [h[1] for h in history[sym][-3:]]
    progressions = [
        [PHASE_SETUP,PHASE_ENTRY,PHASE_CONT],
        [PHASE_ENTRY,PHASE_CONT,PHASE_BRK],
        [PHASE_SETUP,PHASE_ENTRY,PHASE_BRK],
    ]
    return 5 if last3 in progressions else 0

def get_phase_arrow(sym: str) -> str:
    history = st.session_state.get("phase_history", {})
    if sym not in history or len(history[sym]) < 2: return ""
    prev = history[sym][-2][1]; curr = history[sym][-1][1]
    if curr == PHASE_EXIT:                                   return "→EXIT"
    if PHASE_ORDER.get(curr,0) > PHASE_ORDER.get(prev,0):  return "↗"
    if PHASE_ORDER.get(curr,0) < PHASE_ORDER.get(prev,0):  return "↘"
    return ""

# ══════════════════════════════════════════════════════════════════════════════
# POSITION SIZING (FIX-5, unchanged)
# ══════════════════════════════════════════════════════════════════════════════

def position_size(account_size, entry, sl, atr_val, atr_mean, vix_val,
                  risk_pct=0.02, max_capital_pct=0.20):
    risk_per_share = max(entry-sl, 0.01)
    base_qty       = int((account_size*risk_pct)/risk_per_share)
    vix_adj        = float(np.clip(20.0/vix_val, 0.5, 1.5)) if vix_val and vix_val > 0 else 1.0
    atr_adj        = float(np.clip(atr_mean/atr_val, 0.6, 1.4)) if atr_mean > 0 else 1.0
    vol_adj_qty    = max(1, int(base_qty*vix_adj*atr_adj))
    max_qty_by_cap = max(1, int((account_size*max_capital_pct)/entry))
    final_qty      = min(vol_adj_qty, max_qty_by_cap)
    return {
        "base_qty":base_qty,"vix_adj":round(vix_adj,2),"atr_adj":round(atr_adj,2),
        "vol_adj_qty":vol_adj_qty,"final_qty":final_qty,
        "capital_used":round(final_qty*entry,2),"max_loss":round(final_qty*risk_per_share,2),
        "risk_pct":risk_pct,"max_capital_pct":max_capital_pct,
        "capital_capped":final_qty < vol_adj_qty,
    }

# ══════════════════════════════════════════════════════════════════════════════
# EXHAUSTION DETECTION (unchanged)
# ══════════════════════════════════════════════════════════════════════════════

EXT_CFG = {
    "Intraday":   dict(rsi_ceil=80,ema_dist=3.5,atr_exp=2.5,parab=3.0,clim_vol=3.0,div_bars=10),
    "Swing":      dict(rsi_ceil=78,ema_dist=3.0,atr_exp=2.5,parab=3.0,clim_vol=3.0,div_bars=14),
    "Positional": dict(rsi_ceil=75,ema_dist=2.5,atr_exp=2.0,parab=2.5,clim_vol=2.5,div_bars=20),
}
EXT_PENALTIES = {
    "rsi_overheat":-8,"atr_extension":-8,"parabolic":-6,
    "ema_distance":-5,"climactic_volume":-6,"mom_exhaustion":-4,"bearish_div":-6,
}

def detect_exhaustion(close, high, low, volume, rsi_series, e_fast_s, atr_s, atr_mean,
                      c, v, vol_avg, mode, vix_val=None):
    cfg    = EXT_CFG[mode]
    n      = len(close)
    flags  = {k:False for k in EXT_PENALTIES}
    labels = []
    rsi_ceil = cfg["rsi_ceil"]
    if vix_val is not None:
        if vix_val < VIX_CALM:     rsi_ceil += 2
        elif vix_val > VIX_STRESS: rsi_ceil -= 3
    rsi_now = float(rsi_series.iloc[-1])
    if rsi_now > rsi_ceil:
        flags["rsi_overheat"] = True; labels.append("Too hot")
    atr_val = float(atr_s.iloc[-1])
    if atr_mean > 0 and atr_val > atr_mean*cfg["atr_exp"]:
        flags["atr_extension"] = True; labels.append("Range blowout")
    if n >= 23:
        daily_pct  = close.pct_change().dropna()
        hist_sigma = float(daily_pct.iloc[-20:].std())
        exp_3b     = hist_sigma*(3**0.5)
        act_3b     = abs(float(close.iloc[-1])-float(close.iloc[-4]))/float(close.iloc[-4])
        if exp_3b > 0 and act_3b > cfg["parab"]*exp_3b:
            flags["parabolic"] = True; labels.append("Parabolic")
    e_fast_now = float(e_fast_s.iloc[-1])
    if atr_val > 0:
        ema_dist_atrs = (c-e_fast_now)/atr_val
        if ema_dist_atrs > cfg["ema_dist"]:
            flags["ema_distance"] = True; labels.append("EMA overext")
    wick_thresh = 0.35 if (c > 0 and atr_val/c > 0.03) else 0.30
    if n >= 12 and vol_avg > 0:
        prior_run = c > float(close.iloc[-11])
        up_bar    = c > float(close.iloc[-2])
        if prior_run and up_bar and v > vol_avg*cfg["clim_vol"]:
            bar_range  = float(high.iloc[-1])-float(low.iloc[-1])
            upper_wick = float(high.iloc[-1])-c
            if bar_range > 0 and (upper_wick/bar_range) > wick_thresh:
                flags["climactic_volume"] = True; labels.append("Vol climax")
    if n >= 10:
        lookback     = min(cfg["div_bars"], n-1)
        rsi_win      = rsi_series.iloc[-lookback:]
        rsi_peak     = float(rsi_win.max())
        rsi_peak_idx = rsi_win.idxmax()
        price_at_pk  = float(close[rsi_peak_idx])
        gap_req = 5 if mode == "Intraday" else 3
        if (rsi_now < rsi_peak-gap_req
                and c > price_at_pk
                and rsi_win.idxmax() != rsi_win.index[-1]):
            flags["mom_exhaustion"] = True; labels.append("Mom fade")
    if n >= 20:
        lookback  = min(cfg["div_bars"]*2, n-2)
        h_slice   = high.iloc[-lookback:]
        r_slice   = rsi_series.iloc[-lookback:]
        pivot_idx = []
        for i in range(1, len(h_slice)-1):
            if float(h_slice.iloc[i]) > float(h_slice.iloc[i-1]) and float(h_slice.iloc[i]) > float(h_slice.iloc[i+1]):
                pivot_idx.append(i)
        if len(pivot_idx) >= 2:
            p1, p2   = pivot_idx[-2], pivot_idx[-1]
            ph1, ph2 = float(h_slice.iloc[p1]), float(h_slice.iloc[p2])
            rh1, rh2 = float(r_slice.iloc[p1]), float(r_slice.iloc[p2])
            if ph2 > ph1 and rh2 < rh1-2 and (len(h_slice)-1-p2) <= 5:
                flags["bearish_div"] = True; labels.append("Bear div")
    penalty = sum(EXT_PENALTIES[k] for k,v2 in flags.items() if v2)
    n_flags = sum(flags.values())
    return flags, float(penalty), labels, n_flags

def ext_phase_override(phase, ext_flags, n_flags, mode):
    rsi_ext  = ext_flags.get("rsi_overheat", False)
    atr_ext  = ext_flags.get("atr_extension", False)
    is_crit  = n_flags >= 3 or (rsi_ext and atr_ext)
    is_mod   = n_flags == 2
    if is_crit:
        if phase == PHASE_BRK:  return PHASE_EXIT, "ext-critical→EXIT"
        if phase == PHASE_CONT: return PHASE_SETUP,"ext-critical→SETUP"
        if phase == PHASE_ENTRY:return PHASE_SETUP,"ext-critical→SETUP"
    elif is_mod:
        if phase == PHASE_BRK:  return PHASE_SETUP,"ext-moderate→SETUP"
    return phase, None

def ext_action_cap(action, n_flags, vix_val=None):
    if n_flags == 0 and (vix_val is None or vix_val < VIX_STRESS): return action
    if vix_val is not None and vix_val >= VIX_STRESS:
        return "WATCH" if action in ("STRONG BUY","BUY") else action
    if n_flags >= 3:
        return "WATCH" if action in ("STRONG BUY","BUY") else action
    return "BUY" if action == "STRONG BUY" else action

# ══════════════════════════════════════════════════════════════════════════════
# CONFIDENCE MODEL (unchanged)
# ══════════════════════════════════════════════════════════════════════════════

def compute_confidence(*, norm_bull, phase, trend_up, trend_strong, vol_confirmed,
                       ema_stack, htf_aligned, regime_bullish, ext_n, vix_val,
                       phase_bonus=0, rs_rank=50):
    c  = 0.0
    c += {PHASE_BRK:20,PHASE_CONT:17,PHASE_ENTRY:13,
          PHASE_SETUP:7,PHASE_IDLE:2,PHASE_EXIT:0}.get(phase, 0)
    c += min(20, norm_bull*0.20)
    c += 15 if vol_confirmed else 5
    c += 15 if ema_stack else (7 if trend_strong else 0)
    c += 15 if htf_aligned else 0
    c += 10 if regime_bullish else 2
    c -= min(5, ext_n*2)
    if vix_val is not None and vix_val > VIX_CAUTION: c -= 5
    if rs_rank >= 90:   c += 5
    elif rs_rank >= 80: c += 3
    elif rs_rank <= 20: c -= 3
    c += phase_bonus
    return round(min(100, max(0,c)), 1)

def confidence_label(conf):
    if conf >= 80: return "HIGH","#2ecc71"
    if conf >= 60: return "MED", "#f39c12"
    if conf >= 40: return "LOW", "#e67e22"
    return "WEAK","#e74c3c"

# ══════════════════════════════════════════════════════════════════════════════
# PHASE + ENTRY (unchanged from v14)
# ══════════════════════════════════════════════════════════════════════════════

def detect_phase_and_entry(df, mode, *, c, e_fast_s, e_slow_s, atr_s,
                            atr_val, atr_mean, v, vol_avg, fib, sw_hi, sw_lo,
                            in_golden, near_e127, near_e161, norm_bull,
                            trend_up, trend_down, trend_strong, score_th,
                            vdu_setup=False, htf_up=True,
                            regime_bearish=False, vix_val=None):
    cfg   = MODE_CFG[mode]
    close = df["Close"]; high = df["High"]; n = len(close)
    if n < 60: return PHASE_IDLE, None, "norm"
    e_fast_val = float(e_fast_s.iloc[-1])
    e_slow_val = float(e_slow_s.iloc[-1])
    brk_lb     = 5
    rolling_hi_brk = float(high.iloc[-brk_lb-1:-1].max()) if n > brk_lb+1 else float(high.iloc[-1])
    buf = atr_val*0.15
    is_compressed = atr_val < atr_mean*0.8
    is_expanding  = atr_val > float(atr_s.iloc[-2])
    prior_3bar_atr_expanded = atr_val > atr_mean*1.4
    body = (abs(float(close.iloc[-1])-float(df["Open"].iloc[-1]))
            if "Open" in df.columns else atr_val*0.3)
    upper_wick = (float(high.iloc[-1])-max(float(close.iloc[-1]),float(df["Open"].iloc[-1]))
                  if "Open" in df.columns else 0)
    is_exhaustion = upper_wick > body*1.5
    brk_vol_ok = (v > vol_avg*1.5) if vol_avg > 0 else False
    vol_spike  = v > vol_avg*1.3
    is_fib_buy = trend_up and in_golden
    cont_vol_mult = 1.5 if (regime_bearish or (vix_val and vix_val>VIX_CAUTION)) else 1.2
    BRK_CONF_MIN  = 0.70 if regime_bearish else 0.65
    brk_weights = {
        "price_above_high":(0.35, c > rolling_hi_brk+buf),
        "score_ok":        (0.20, norm_bull >= score_th),
        "compressed":      (0.20, is_compressed),
        "expanding":       (0.15, is_expanding),
        "vol_spike":       (0.10, vol_spike),
    }
    brk_confidence = sum(w for w,cond in brk_weights.values() if cond)
    is_breakout = (brk_confidence >= BRK_CONF_MIN and not is_exhaustion
                   and brk_vol_ok and not prior_3bar_atr_expanded and htf_up)
    was_recent_brk = False; recent_brk_bar = None
    if not is_breakout and n > brk_lb*2+2:
        for k in range(1, brk_lb+1):
            look_start = -(brk_lb+1+k); look_end = -(1+k)
            if abs(look_start) > n or abs(look_end) > n: break
            prev_rolling_hi = float(high.iloc[look_start:look_end].max())
            prev_hi_k       = float(high.iloc[-k])
            prev_close_k    = float(close.iloc[-k])
            prev_vol_k      = float(df["Volume"].iloc[-k])
            close_above_brk = prev_close_k > prev_rolling_hi
            prev_open_k     = (float(df["Open"].iloc[-k]) if "Open" in df.columns else prev_close_k)
            body_non_red    = prev_close_k >= prev_open_k
            hist_vol        = df["Volume"].iloc[:-k]
            hist_avg_k      = (float(hist_vol.rolling(20).mean().iloc[-1])
                               if len(hist_vol) >= 20 else vol_avg)
            vol_gate        = (hist_avg_k == 0 or prev_vol_k > hist_avg_k*1.5)
            if (prev_hi_k > prev_rolling_hi+buf and close_above_brk
                    and body_non_red and vol_gate):
                was_recent_brk = True; recent_brk_bar = k; break
    is_cont = (n >= 4 and c > float(close.iloc[-4:-1].max())
               and c > e_fast_val and v > vol_avg*cont_vol_mult
               and trend_strong and htf_up)
    ema_down    = e_fast_val < e_slow_val and float(e_fast_s.iloc[-4]) < float(e_slow_s.iloc[-4])
    trail_level = float(close.iloc[-10:].max())-atr_val*1.5
    trail_break = c < trail_level
    if trend_down and ema_down:     phase, setup_type = PHASE_EXIT, "norm"
    elif is_breakout:               phase, setup_type = PHASE_BRK, "breakout"
    elif was_recent_brk and trend_strong:
        phase, setup_type = (PHASE_CONT,"breakout") if trend_up else (PHASE_SETUP,"breakout")
    elif (is_fib_buy or norm_bull >= score_th) and is_cont and trend_up:
        phase, setup_type = PHASE_CONT, ("fib" if is_fib_buy else "norm")
    elif (is_fib_buy or norm_bull >= score_th) and trend_up:
        phase, setup_type = PHASE_ENTRY, ("fib" if is_fib_buy else "norm")
    elif (is_fib_buy or norm_bull >= score_th*0.85 or vdu_setup) and trend_up:
        phase, setup_type = PHASE_SETUP, ("fib" if is_fib_buy else ("vdu" if vdu_setup else "norm"))
    elif trail_break and trend_up:  phase, setup_type = PHASE_EXIT, "norm"
    else:                           phase, setup_type = PHASE_IDLE, "norm"
    if not htf_up and phase in (PHASE_ENTRY,PHASE_CONT,PHASE_BRK):
        phase, setup_type = PHASE_SETUP, setup_type
    entry_price = None
    if phase in (PHASE_ENTRY,PHASE_CONT,PHASE_BRK,PHASE_SETUP):
        prox = atr_val*0.3
        if is_breakout:         entry_price = round(rolling_hi_brk+buf, 2)
        elif was_recent_brk:    entry_price = round(c, 2)
        elif is_fib_buy and fib: entry_price = round(fib["618"]+prox*0.3, 2)
        else:
            cross       = close > e_fast_s
            signal_bars = cross & ~cross.shift(1).fillna(False)
            if signal_bars.any():
                last_cross_idx = signal_bars[::-1].idxmax()
                cross_pos      = close.index.get_loc(last_cross_idx)
                bars_ago       = (n-1)-cross_pos
                cross_px       = float(close[last_cross_idx])
                entry_price = round(cross_px,2) if (bars_ago<=10 and cross_px>=c*0.97) else round(c,2)
            else:
                entry_price = round(c, 2)
    return phase, entry_price, setup_type

# ══════════════════════════════════════════════════════════════════════════════
# TARGET COMPUTATION (unchanged)
# ══════════════════════════════════════════════════════════════════════════════

def _compute_targets(entry, sl, atr_val, fib, setup_type, sw_hi, sw_lo,
                     regime_bearish=False, vix_val=None):
    rk = max(entry-sl, atr_val*0.5)
    t1m,t2m,t3m,sl_exp = vix_target_mult(vix_val)
    if regime_bearish: t1m*=0.8; t2m*=0.7; t3m*=0.6
    if setup_type == "fib" and fib:
        t1=round(fib["ext127"],2); t2=round(fib["ext161"],2)
        ext_r=fib["ext161"]-fib["ext127"]
        t3=round(fib["ext161"]+min(ext_r,atr_val*3),2)
    elif setup_type == "breakout" and fib:
        t1=round((entry+rk*t1m+fib["ext127"])/2,2)
        t2=round((entry+rk*t2m+fib["ext161"])/2,2)
        t3=round((entry+rk*t3m+fib["ext261"])/2,2)
    else:
        t1=round(entry+rk*t1m,2); t2=round(entry+rk*t2m,2); t3=round(entry+rk*t3m,2)
    min_move = atr_val*0.8
    if t1-entry < min_move:
        t1=round(entry+min_move,2); t2=round(entry+min_move*2,2); t3=round(entry+min_move*3,2)
    return t1, t2, t3, sl_exp

# ══════════════════════════════════════════════════════════════════════════════
# NIFTY FETCH
# ══════════════════════════════════════════════════════════════════════════════

@st.cache_data(ttl=300)
def fetch_nifty(mode="Swing"):
    cfg = MODE_CFG[mode]
    raw = fetch_async(["^NSEI"], cfg["period"], cfg["interval"], concurrency=1)
    df  = raw.get("^NSEI", pd.DataFrame())
    if df.empty:
        try:
            import yfinance as yf
            df = yf.download("^NSEI", period=cfg["period"], interval=cfg["interval"], progress=False)
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
        except Exception:
            return pd.Series(dtype=float)
    return df["Close"].dropna()

def _market_regime(nifty_close):
    if len(nifty_close) < 50: return True, "UNKNOWN"
    ema20 = float(ema(nifty_close, 20).iloc[-1])
    ema50 = float(ema(nifty_close, 50).iloc[-1])
    bull  = (float(nifty_close.iloc[-1]) > ema50) and (ema20 > ema50)
    return bull, ("BULLISH" if bull else "BEARISH")

# ══════════════════════════════════════════════════════════════════════════════
# SPEED-10: ADX + SQUEEZE helpers per-symbol (Stage-B enrichment)
# ══════════════════════════════════════════════════════════════════════════════

def _compute_adx(df: pd.DataFrame, period: int = 14) -> float:
    """Single-symbol ADX using Wilder's RMA — matches standard charting platform values."""
    if len(df) < period * 3:
        return 20.0
    hi  = df["High"].values.astype(np.float32)
    lo  = df["Low"].values.astype(np.float32)
    cl  = df["Close"].values.astype(np.float32)
    prev_hi = np.roll(hi, 1); prev_hi[0] = hi[0]
    prev_lo = np.roll(lo, 1); prev_lo[0] = lo[0]
    prev_cl = np.roll(cl, 1); prev_cl[0] = cl[0]
    up_m  = hi - prev_hi; dn_m = prev_lo - lo
    pdm   = np.where((up_m > dn_m) & (up_m > 0), up_m, 0.0)
    ndm   = np.where((dn_m > up_m) & (dn_m > 0), dn_m, 0.0)
    tr    = np.maximum(hi-lo, np.maximum(np.abs(hi-prev_cl), np.abs(lo-prev_cl)))
    atr_v = _rma_np(tr, period)
    pdi   = 100*_rma_np(pdm, period)/(atr_v+1e-10)
    ndi   = 100*_rma_np(ndm, period)/(atr_v+1e-10)
    dx    = 100*np.abs(pdi-ndi)/(pdi+ndi+1e-10)
    adx_v = _rma_np(dx, period)
    return float(adx_v[-1])

def _compute_squeeze(df: pd.DataFrame, period: int = 20) -> bool:
    """Returns True if BB inside KC (squeeze on)."""
    if len(df) < period:
        return False
    cl = df["Close"].values.astype(np.float32)
    hi = df["High"].values.astype(np.float32)
    lo = df["Low"].values.astype(np.float32)
    mid   = _ema_np(cl, period)
    dev2  = _ema_np((cl-mid)**2, period)
    std   = np.sqrt(np.maximum(dev2, 0))
    bb_hi = mid + 2.0*std; bb_lo = mid - 2.0*std
    atr_k = _ema_np(np.maximum(hi-lo,
             np.maximum(np.abs(hi-np.roll(cl,1)),
                        np.abs(lo-np.roll(cl,1)))), period)
    kc_hi = mid + 1.5*atr_k; kc_lo = mid - 1.5*atr_k
    return bool(bb_hi[-1] <= kc_hi[-1] and bb_lo[-1] >= kc_lo[-1])

def _compute_vol_contraction(df: pd.DataFrame) -> float:
    """ATR_5 / ATR_20 ratio — <0.75 = compressed."""
    if len(df) < 25:
        return 1.0
    cl = df["Close"].values.astype(np.float32)
    hi = df["High"].values.astype(np.float32)
    lo = df["Low"].values.astype(np.float32)
    prev_cl = np.roll(cl,1); prev_cl[0] = cl[0]
    tr      = np.maximum(hi-lo, np.maximum(np.abs(hi-prev_cl), np.abs(lo-prev_cl)))
    atr5    = float(_ema_np(tr, 5)[-1])
    atr20   = float(_ema_np(tr,20)[-1])
    return atr5/(atr20+1e-10)

# ══════════════════════════════════════════════════════════════════════════════
# v15.5 — EMERGING MOMENTUM ENGINE
# Surfaces stocks BEFORE they become obvious, using 7 leading indicators.
# ══════════════════════════════════════════════════════════════════════════════

def _count_squeeze_bars(df: pd.DataFrame, period: int = 20,
                         max_lookback: int = 40) -> int:
    """Count consecutive bars currently in Keltner/BB squeeze (from most recent bar back)."""
    n = len(df)
    if n < period + 2:
        return 0
    cl = df["Close"].values.astype(np.float64)
    hi = df["High"].values.astype(np.float64)
    lo = df["Low"].values.astype(np.float64)
    count = 0
    for offset in range(min(max_lookback, n - period)):
        end = n - offset
        if end < period:
            break
        cl_w = cl[end - period:end]
        hi_w = hi[end - period:end]
        lo_w = lo[end - period:end]
        mid   = _ema_np(cl_w, period)[-1]
        dev2  = _ema_np((cl_w - _ema_np(cl_w, period)) ** 2, period)[-1]
        std   = float(np.sqrt(max(dev2, 0)))
        bb_hi = mid + 2.0 * std;  bb_lo = mid - 2.0 * std
        prev_cl_w = np.roll(cl_w, 1); prev_cl_w[0] = cl_w[0]
        tr_w   = np.maximum(hi_w - lo_w,
                 np.maximum(np.abs(hi_w - prev_cl_w), np.abs(lo_w - prev_cl_w)))
        atr_k  = float(_ema_np(tr_w, period)[-1])
        kc_hi  = mid + 1.5 * atr_k;  kc_lo = mid - 1.5 * atr_k
        if bb_hi <= kc_hi and bb_lo >= kc_lo:
            count += 1
        else:
            break
    return count


def compute_emerging_score(
    df: pd.DataFrame,
    mode: str,
    nifty_close: pd.Series,
    rs_rank: int = 50,
) -> dict:
    """
    Emerging Momentum Score (0–100) — surfaces stocks BEFORE they become obvious.

    Components (max pts):
    1. RS Acceleration      15 — relative strength gaining speed vs index
    2. ATR Compression      15 — volatility coiling toward a breakout
    3. RVOL Acceleration    15 — volume building quietly (smart-money fingerprint)
    4. EMA Convergence      15 — fast/slow EMAs tightening = decision approaching
    5. Squeeze Pressure     15 — consecutive BB-inside-KC bars = stored energy
    6. Sector Momentum      10 — sector tailwind (enriched post-scan in run_scan)
    7. Opening Range Exp.   15 — price expanding beyond recent consolidation

    Labels: IGNITING ≥65 · BUILDING ≥50 · COILING ≥35 · LATENT ≥20 · QUIET <20
    """
    out = dict(
        EmScore=0.0, EmLabel="QUIET",
        EmRSAccel=0.0, EmATRCompress=0.0, EmRVolAccel=0.0,
        EmEMAConv=0.0, EmSqzPressure=0.0, EmSectorMom=0.0, EmORExpansion=0.0,
    )
    try:
        if df is None or len(df) < 40:
            return out
        cl  = df["Close"].values.astype(np.float64)
        hi  = df["High"].values.astype(np.float64)
        lo  = df["Low"].values.astype(np.float64)
        vol = df["Volume"].values.astype(np.float64)
        n   = len(cl)
        cfg = MODE_CFG[mode]
        ef_span = cfg["ema_fast"]
        es_span = cfg["ema_slow"]

        # ── 1. RS ACCELERATION (0–15 pts) ────────────────────────────────────
        # RS is accelerating when recent outperformance > medium > long window
        rs_pts = 0.0
        try:
            nifty = (nifty_close.values.astype(np.float64)
                     if nifty_close is not None and len(nifty_close) >= 20
                     else None)
            if nifty is not None:
                def _rs(bars):
                    if n < bars + 1 or len(nifty) < bars + 1:
                        return 0.0
                    s = (cl[-1] - cl[-bars]) / (cl[-bars] + 1e-10) * 100
                    m = (nifty[-1] - nifty[-bars]) / (nifty[-bars] + 1e-10) * 100
                    return s - m
                rs5, rs10, rs20 = _rs(5), _rs(10), _rs(20)
                if rs5 > rs10 > 0:          # Accelerating outperformance
                    rs_pts = min(15.0, (rs5 - rs10) * 2.5 + 5)
                elif rs5 > 0 and rs5 > rs20 * 0.5:
                    rs_pts = min(8.0, rs5 * 0.6)
                if rs_rank >= 70 and rs5 > 0:  # High rank + still accelerating
                    rs_pts = min(15.0, rs_pts + 3)
        except Exception:
            pass

        # ── 2. ATR COMPRESSION (0–15 pts) ────────────────────────────────────
        # Volatility contracting → coiling energy before expansion
        atr_pts = 0.0
        try:
            if n >= 25:
                prev_cl = np.roll(cl, 1); prev_cl[0] = cl[0]
                tr_arr  = np.maximum(hi - lo, np.maximum(
                          np.abs(hi - prev_cl), np.abs(lo - prev_cl)))
                atr5_now  = float(_ema_np(tr_arr, 5)[-1])
                atr20_now = float(_ema_np(tr_arr, 20)[-1])
                ratio_now = atr5_now / (atr20_now + 1e-10)
                if   ratio_now < 0.65: atr_pts = 15.0
                elif ratio_now < 0.75: atr_pts = 12.0
                elif ratio_now < 0.85: atr_pts = 8.0
                elif ratio_now < 0.95: atr_pts = 4.0
                # Bonus: actively compressing (trend in ratio)
                if n > 15:
                    atr5_5  = float(_ema_np(tr_arr[:-5], 5)[-1])
                    atr20_5 = float(_ema_np(tr_arr[:-5], 20)[-1])
                    if ratio_now < atr5_5 / (atr20_5 + 1e-10) - 0.05:
                        atr_pts = min(15.0, atr_pts + 4.0)
        except Exception:
            pass

        # ── 3. RVOL ACCELERATION (0–15 pts) ──────────────────────────────────
        # Volume building quietly across successive windows → smart money
        rvol_pts = 0.0
        try:
            if n >= 20:
                avg_vol = float(np.mean(vol[-21:-1])) if n >= 22 else float(np.mean(vol[:-1]))
                if avg_vol > 0:
                    v_now   = float(np.mean(vol[-3:]))
                    v_5ago  = float(np.mean(vol[-8:-5]))   if n >= 8  else avg_vol
                    v_10ago = float(np.mean(vol[-13:-10])) if n >= 13 else avg_vol
                    r_now   = v_now   / avg_vol
                    r_5ago  = v_5ago  / avg_vol
                    r_10ago = v_10ago / avg_vol
                    if r_now > r_5ago > r_10ago and r_now > 0.8:  # Sequential build
                        rvol_pts = min(15.0, (r_now - r_10ago) * 15)
                    elif r_now > r_5ago and r_now > 0.9:
                        rvol_pts = min(9.0, (r_now - r_5ago) * 12)
                    elif 0.4 < r_now < 0.75:                       # Quiet dryup = stealth accumulation
                        rvol_pts = 5.0
        except Exception:
            pass

        # ── 4. EMA CONVERGENCE (0–15 pts) ────────────────────────────────────
        # Fast + slow EMAs tightening → coiling, decision point approaching
        conv_pts = 0.0
        try:
            if n >= es_span + 5:
                ef_arr = _ema_np(cl, ef_span)
                es_arr = _ema_np(cl, es_span)
                dist_now   = abs(ef_arr[-1]  - es_arr[-1])
                dist_5ago  = abs(ef_arr[-6]  - es_arr[-6])  if n >= 6  else dist_now
                dist_10ago = abs(ef_arr[-11] - es_arr[-11]) if n >= 11 else dist_now
                c_last     = cl[-1] + 1e-10
                dpct_now   = dist_now   / c_last * 100
                dpct_5ago  = dist_5ago  / c_last * 100
                dpct_10ago = dist_10ago / c_last * 100
                converging = dpct_now < dpct_5ago
                if   converging and dpct_now < 0.5:  conv_pts = 15.0
                elif converging and dpct_now < 1.0:  conv_pts = 11.0
                elif converging and dpct_now < 2.0:  conv_pts = 7.0
                elif converging:                     conv_pts = 4.0
                elif dpct_now < dpct_10ago * 0.65:   conv_pts = 6.0  # 35% tighter in 10 bars
                # Bonus: bullish convergence (fast still > slow)
                if ef_arr[-1] > es_arr[-1] and converging:
                    conv_pts = min(15.0, conv_pts + 4.0)
        except Exception:
            pass

        # ── 5. SQUEEZE PRESSURE (0–15 pts) ───────────────────────────────────
        # Consecutive bars in BB/KC squeeze → more bars = more stored kinetic energy
        sqz_pts = 0.0
        try:
            csq = _count_squeeze_bars(df, period=20, max_lookback=40)
            if   csq >= 20: sqz_pts = 15.0
            elif csq >= 15: sqz_pts = 12.0
            elif csq >= 10: sqz_pts = 9.0
            elif csq >= 5:  sqz_pts = 6.0
            elif csq >= 2:  sqz_pts = 3.0
        except Exception:
            pass

        # ── 6. SECTOR MOMENTUM (0–10 pts) — placeholder enriched in run_scan ─
        sec_pts = 0.0

        # ── 7. OPENING RANGE EXPANSION (0–15 pts) ────────────────────────────
        # Price moving beyond recent consolidation zone = first activation signal
        or_pts = 0.0
        try:
            if mode == "Intraday" and n >= 8:
                # First 6 bars (~30 min at 5m) = opening range
                or_hi = float(np.max(hi[:6]))
                or_lo = float(np.min(lo[:6]))
                or_rng = or_hi - or_lo
                cur = cl[-1]
                if or_rng > 0:
                    exp_pct = (cur - or_hi) / or_rng
                    if   exp_pct > 0.20:  or_pts = 15.0
                    elif exp_pct > 0.05:  or_pts = 10.0
                    elif exp_pct >= 0:    or_pts = 6.0
                    elif exp_pct > -0.15: or_pts = 3.0
            else:
                lb = min(10 if mode == "Swing" else 20, n - 2)
                rng_hi = float(np.max(hi[-lb - 1:-1]))
                rng_lo = float(np.min(lo[-lb - 1:-1]))
                rng_w  = rng_hi - rng_lo
                cur    = cl[-1]
                if rng_w > 0:
                    exp_pct = (cur - rng_hi) / rng_w
                    if   exp_pct > 0.15:  or_pts = 15.0
                    elif exp_pct > 0.02:  or_pts = 10.0
                    elif exp_pct >= 0:    or_pts = 6.0
                    elif cur > rng_lo + rng_w * 0.65: or_pts = 3.0
        except Exception:
            pass

        # ── TOTAL ─────────────────────────────────────────────────────────────
        total = round(float(np.clip(
            rs_pts + atr_pts + rvol_pts + conv_pts + sqz_pts + sec_pts + or_pts,
            0, 100)), 1)
        label = ("IGNITING" if total >= 65 else "BUILDING" if total >= 50
                 else "COILING" if total >= 35 else "LATENT" if total >= 20 else "QUIET")
        out.update(
            EmScore       = total,
            EmLabel       = label,
            EmRSAccel     = round(rs_pts,   1),
            EmATRCompress = round(atr_pts,  1),
            EmRVolAccel   = round(rvol_pts, 1),
            EmEMAConv     = round(conv_pts, 1),
            EmSqzPressure = round(sqz_pts,  1),
            EmSectorMom   = 0.0,   # filled by enrich_sector_momentum() in run_scan
            EmORExpansion = round(or_pts,   1),
        )
    except Exception:
        pass
    return out

# ══════════════════════════════════════════════════════════════════════════════
# v15.6 — PRE-CONFIRMATION ACCUMULATION (PCA) ENGINE
# Detects institutional buying BEFORE price confirms — 7 signal components.
# This layer completes the early-accumulation intelligence stack that
# EmScore starts but doesn't finish (EmScore targets coiling mechanics;
# PCA targets the buying-pressure fingerprint beneath the coil).
# ══════════════════════════════════════════════════════════════════════════════

_PCA_COMPONENTS = [
    ("Rel CMF",       "PCACMFRel",       15, "💧"),
    ("Vol Cmp Seq",   "PCAVolCmpSeq",    15, "🗜"),
    ("Hidden Accum",  "PCAHiddenAccum",  15, "👻"),
    ("Effort/Result", "PCAEffortResult", 15, "⚖"),
    ("Range Persist", "PCARangeCont",    10, "📏"),
    ("Failed BRK",    "PCAFailedBrkdn",  15, "🛡"),
    ("Vol Asymmetry", "PCAVolAsym",      15, "⚖"),
]

def compute_preconfirmation_accumulation(
    df: pd.DataFrame,
    mode: str,
) -> dict:
    """
    Pre-Confirmation Accumulation Score (0–100).

    Components (max pts):
    1. Relative CMF          15 — CMF improving vs its own rolling baseline
    2. Vol Compression Seq   15 — sequence of tightening ATR/range contractions
    3. Hidden Accumulation   15 — down-days low-vol, up-days high-vol (absorption)
    4. Effort vs Result      15 — big volume that barely moves price = supply absorbed
    5. Range Contraction     10 — persistent NR bars below historical avg range
    6. Failed Breakdown      15 — wicks below support closed back above = buying
    7. Volume Asymmetry      15 — up-day volume persistently > down-day volume

    Labels: ACCUMULATING ≥65 · BUILDING ≥50 · FORMING ≥35 · WEAK ≥20 · NONE <20
    """
    out = dict(
        PCAScore=0.0, PCALabel="NONE",
        PCACMFRel=0.0, PCAVolCmpSeq=0.0, PCAHiddenAccum=0.0,
        PCAEffortResult=0.0, PCARangeCont=0.0, PCAFailedBrkdn=0.0, PCAVolAsym=0.0,
    )
    try:
        if df is None or len(df) < 30:
            return out

        cl  = df["Close"].values.astype(np.float64)
        hi  = df["High"].values.astype(np.float64)
        lo  = df["Low"].values.astype(np.float64)
        vol = df["Volume"].values.astype(np.float64)
        n   = len(cl)
        op  = (df["Open"].values.astype(np.float64)
               if "Open" in df.columns else cl.copy())

        # ── 1. RELATIVE CMF (0–15 pts) ────────────────────────────────────────
        # CMF improving vs its own 40-bar prior baseline = fresh buying pressure
        cmf_pts = 0.0
        try:
            win = min(20, n)
            hlr = np.where((hi[-win:] - lo[-win:]) == 0, 1e-10, hi[-win:] - lo[-win:])
            mfm = ((cl[-win:] - lo[-win:]) - (hi[-win:] - cl[-win:])) / hlr
            cmf_now = float(np.sum(mfm * vol[-win:]) / (np.sum(vol[-win:]) + 1e-10))

            if n >= 40:
                hlr_old = np.where(
                    (hi[-40:-20] - lo[-40:-20]) == 0, 1e-10,
                    hi[-40:-20] - lo[-40:-20]
                )
                mfm_old = ((cl[-40:-20] - lo[-40:-20]) -
                           (hi[-40:-20] - cl[-40:-20])) / hlr_old
                cmf_old = float(
                    np.sum(mfm_old * vol[-40:-20]) / (np.sum(vol[-40:-20]) + 1e-10)
                )
                delta = cmf_now - cmf_old
                if   cmf_now > 0.15 and delta > 0:        cmf_pts = 15.0
                elif cmf_now > 0.05 and delta > 0:         cmf_pts = 11.0
                elif cmf_now > 0    and delta > 0.05:      cmf_pts = 8.0
                elif cmf_now > 0:                          cmf_pts = 4.0
                elif cmf_now > -0.05 and delta > 0.10:    cmf_pts = 3.0
            else:
                if   cmf_now > 0.15: cmf_pts = 10.0
                elif cmf_now > 0.05: cmf_pts = 6.0
                elif cmf_now > 0:    cmf_pts = 3.0
        except Exception:
            pass

        # ── 2. VOLATILITY COMPRESSION SEQUENCING (0–15 pts) ──────────────────
        # Consecutive narrowing ranges AND multi-window avg sequence tightening
        vc_pts = 0.0
        try:
            if n >= 10:
                ranges = hi - lo
                consec = 0
                for k in range(1, min(15, n - 1)):
                    if ranges[-k] < ranges[-(k + 1)]:
                        consec += 1
                    else:
                        break
                avg5  = float(np.mean(ranges[-5:]))  if n >= 5  else float(np.mean(ranges))
                avg10 = float(np.mean(ranges[-10:])) if n >= 10 else avg5
                avg20 = float(np.mean(ranges[-20:])) if n >= 20 else avg10
                sequenced = avg5 < avg10 < avg20

                if   consec >= 8 and sequenced: vc_pts = 15.0
                elif consec >= 5 and sequenced: vc_pts = 12.0
                elif consec >= 3:               vc_pts = 8.0
                elif consec >= 2 and sequenced: vc_pts = 5.0
                elif sequenced:                 vc_pts = 3.0
        except Exception:
            pass

        # ── 3. HIDDEN ACCUMULATION (0–15 pts) ────────────────────────────────
        # Up-day vol >> down-day vol even while price is flat/slightly negative
        ha_pts = 0.0
        try:
            lb = min(20, n - 1)
            up_vols   = [float(vol[i]) for i in range(-lb, 0) if cl[i] > cl[i - 1]]
            down_vols = [float(vol[i]) for i in range(-lb, 0) if cl[i] <= cl[i - 1]]
            if up_vols and down_vols:
                avg_up   = float(np.mean(up_vols))
                avg_down = float(np.mean(down_vols))
                ratio    = avg_up / (avg_down + 1e-10)
                price_chg = (float(cl[-1]) - float(cl[-lb])) / (float(cl[-lb]) + 1e-10) * 100

                if   ratio >= 2.5:                          ha_pts = 15.0
                elif ratio >= 2.0:                          ha_pts = 12.0
                elif ratio >= 1.5:                          ha_pts = 9.0
                elif ratio >= 1.2:                          ha_pts = 6.0
                elif ratio >= 1.05 and price_chg < 2.0:   ha_pts = 3.0
        except Exception:
            pass

        # ── 4. EFFORT VS RESULT ANOMALIES (0–15 pts) ─────────────────────────
        # High volume + tiny body = supply absorbed (Wyckoff spring fingerprint)
        evr_pts = 0.0
        try:
            lb_evr   = min(10, n - 1)
            avg_vol_ = float(np.mean(vol[-21:-1])) if n >= 22 else float(np.mean(vol[:-1]))
            avg_rng_ = (float(np.mean(hi[-21:-1] - lo[-21:-1]))
                        if n >= 22 else float(np.mean(hi - lo)))
            if avg_vol_ > 0 and avg_rng_ > 0:
                anomalies = 0
                for k in range(1, lb_evr + 1):
                    v_k    = float(vol[-k])
                    body_k = abs(float(cl[-k]) - float(op[-k]))
                    cl_k   = float(cl[-k])
                    op_k   = float(op[-k])
                    hi_k   = float(hi[-k])
                    lo_k   = float(lo[-k])
                    mid_k  = (hi_k + lo_k) / 2
                    # High-vol tiny-body (absorption bar)
                    if v_k > avg_vol_ * 1.3 and body_k < avg_rng_ * 0.30:
                        anomalies += 1
                    # High-vol red day that closed upper half (buyers absorbed selling)
                    elif (v_k > avg_vol_ * 1.5 and cl_k < op_k
                          and cl_k > mid_k):
                        anomalies += 1

                if   anomalies >= 5: evr_pts = 15.0
                elif anomalies >= 3: evr_pts = 11.0
                elif anomalies >= 2: evr_pts = 7.0
                elif anomalies >= 1: evr_pts = 4.0
        except Exception:
            pass

        # ── 5. RANGE CONTRACTION PERSISTENCE (0–10 pts) ──────────────────────
        # How many of last 10 bars have range below 85% of 20-bar historical avg
        rc_pts = 0.0
        try:
            if n >= 12:
                ranges_ = hi - lo
                avg_rng20 = float(np.mean(ranges_[-21:-1])) if n >= 22 else float(np.mean(ranges_[:-1]))
                if avg_rng20 > 0:
                    nr_count = int(np.sum(ranges_[-10:] < avg_rng20 * 0.85))
                    if   nr_count >= 9: rc_pts = 10.0
                    elif nr_count >= 7: rc_pts = 8.0
                    elif nr_count >= 5: rc_pts = 6.0
                    elif nr_count >= 3: rc_pts = 4.0
                    elif nr_count >= 2: rc_pts = 2.0
        except Exception:
            pass

        # ── 6. FAILED BREAKDOWN ABSORPTION (0–15 pts) ────────────────────────
        # Bars where lows pierced recent support but closed back above = buying
        fba_pts = 0.0
        try:
            if n >= 15:
                lb_fba  = min(10, n - 5)
                support = float(np.min(lo[-lb_fba - 5:-5]))   # recent swing support
                fba_cnt = 0
                for k in range(1, lb_fba + 1):
                    lo_k = float(lo[-k]); cl_k = float(cl[-k])
                    if lo_k < support * 0.997 and cl_k >= support * 0.999:
                        fba_cnt += 1

                if   fba_cnt >= 4: fba_pts = 15.0
                elif fba_cnt >= 3: fba_pts = 12.0
                elif fba_cnt >= 2: fba_pts = 8.0
                elif fba_cnt >= 1: fba_pts = 5.0

                # Bonus: if holding above support on tight range (coil above base)
                if fba_cnt >= 1 and float(cl[-1]) > support:
                    rng_now = float(hi[-1] - lo[-1])
                    avg_rng_b = float(np.mean(hi[-20:] - lo[-20:])) if n >= 20 else rng_now
                    if avg_rng_b > 0 and rng_now < avg_rng_b * 0.70:
                        fba_pts = min(15.0, fba_pts + 3.0)
        except Exception:
            pass

        # ── 7. VOLUME ASYMMETRY (0–15 pts) ────────────────────────────────────
        # Up-day vol is consistently AND significantly > down-day vol
        va_pts = 0.0
        try:
            lb_va       = min(30, n - 1)
            up_vols_a   = [float(vol[i]) for i in range(-lb_va, 0) if cl[i] > cl[i - 1]]
            down_vols_a = [float(vol[i]) for i in range(-lb_va, 0) if cl[i] < cl[i - 1]]
            if len(up_vols_a) >= 3 and len(down_vols_a) >= 3:
                median_down  = float(np.median(down_vols_a))
                pct_above    = (sum(1 for v in up_vols_a if v > median_down)
                                / len(up_vols_a))
                mag_ratio    = (float(np.mean(up_vols_a))
                                / (float(np.mean(down_vols_a)) + 1e-10))

                if   pct_above >= 0.80 and mag_ratio >= 1.8: va_pts = 15.0
                elif pct_above >= 0.70 and mag_ratio >= 1.5: va_pts = 12.0
                elif pct_above >= 0.65 and mag_ratio >= 1.3: va_pts = 9.0
                elif pct_above >= 0.55 and mag_ratio >= 1.2: va_pts = 6.0
                elif pct_above >= 0.50 and mag_ratio >= 1.1: va_pts = 3.0
        except Exception:
            pass

        # ── TOTAL ──────────────────────────────────────────────────────────────
        total = round(float(np.clip(
            cmf_pts + vc_pts + ha_pts + evr_pts + rc_pts + fba_pts + va_pts,
            0, 100
        )), 1)
        label = (
            "ACCUMULATING" if total >= 65 else
            "BUILDING"     if total >= 50 else
            "FORMING"      if total >= 35 else
            "WEAK"         if total >= 20 else
            "NONE"
        )
        out.update(
            PCAScore        = total,
            PCALabel        = label,
            PCACMFRel       = round(cmf_pts,  1),
            PCAVolCmpSeq    = round(vc_pts,   1),
            PCAHiddenAccum  = round(ha_pts,   1),
            PCAEffortResult = round(evr_pts,  1),
            PCARangeCont    = round(rc_pts,   1),
            PCAFailedBrkdn  = round(fba_pts,  1),
            PCAVolAsym      = round(va_pts,   1),
        )
    except Exception:
        pass
    return out

# ══════════════════════════════════════════════════════════════════════════════
# GAP-2 — SMART MONEY BEHAVIOR MODEL
# Synthesizes all buying-pressure signals into one behavioral verdict.
# Goes beyond PCA (snapshot score) to classify the behaviour type.
# ══════════════════════════════════════════════════════════════════════════════

_SM_VERDICTS = ["DISTRIBUTING", "NEUTRAL", "ABSORBING", "ACCUMULATING", "MARKUP_READY"]

def compute_smart_money_model(
    df: pd.DataFrame,
    mode: str,
    pca_score: float = 0.0,
    inst_score: float = 50.0,
    obv_trend: bool = True,
) -> dict:
    """
    Smart Money Behavior Model (0–100 SmartMoneyScore).

    Components:
    1. CMF Regime          (20 pts) — current CMF + trend direction
    2. Block Volume        (20 pts) — large-lot days (>2× avg vol) net bias
    3. OBV Trend           (15 pts) — OBV slope and EMA alignment
    4. Absorption Quality  (25 pts) — high-vol days that barely moved price
    5. Pressure Asymmetry  (20 pts) — net buying pressure over last N bars

    Verdicts: MARKUP_READY ≥80 · ACCUMULATING ≥65 · ABSORBING ≥50 ·
              NEUTRAL ≥35 · DISTRIBUTING <35
    """
    out = dict(
        SmartMoneyScore=0.0, SmartMoneyVerdict="NEUTRAL",
        SMBehaviorPhase="UNKNOWN", SMConfidence=0,
        SMCMFScore=0.0, SMBlockScore=0.0,
        SMOBVScore=0.0, SMAbsorptionScore=0.0, SMPressureScore=0.0,
    )
    try:
        if df is None or len(df) < 30:
            return out
        cl  = df["Close"].values.astype(np.float64)
        hi  = df["High"].values.astype(np.float64)
        lo  = df["Low"].values.astype(np.float64)
        vol = df["Volume"].values.astype(np.float64)
        op  = (df["Open"].values.astype(np.float64)
               if "Open" in df.columns else cl.copy())
        n = len(cl)

        # ── 1. CMF Regime (0–20 pts) ─────────────────────────────────────────
        cmf_pts = 0.0
        try:
            win = min(20, n)
            hlr = np.where((hi[-win:] - lo[-win:]) == 0, 1e-10, hi[-win:] - lo[-win:])
            mfm = ((cl[-win:] - lo[-win:]) - (hi[-win:] - cl[-win:])) / hlr
            cmf_now = float(np.sum(mfm * vol[-win:]) / (np.sum(vol[-win:]) + 1e-10))
            # CMF trend: compare two halves of the window
            half = win // 2
            if half > 2:
                hlr1 = np.where((hi[-win:-half]-lo[-win:-half])==0, 1e-10, hi[-win:-half]-lo[-win:-half])
                mfm1 = ((cl[-win:-half]-lo[-win:-half])-(hi[-win:-half]-cl[-win:-half]))/hlr1
                cmf_old = float(np.sum(mfm1*vol[-win:-half])/(np.sum(vol[-win:-half])+1e-10))
                cmf_rising = cmf_now > cmf_old
            else:
                cmf_rising = cmf_now > 0
            if   cmf_now > 0.20 and cmf_rising: cmf_pts = 20.0
            elif cmf_now > 0.10 and cmf_rising: cmf_pts = 16.0
            elif cmf_now > 0.05 and cmf_rising: cmf_pts = 12.0
            elif cmf_now > 0    and cmf_rising: cmf_pts = 8.0
            elif cmf_now > 0:                   cmf_pts = 5.0
            elif cmf_now > -0.05 and cmf_rising:cmf_pts = 3.0
        except Exception:
            pass

        # ── 2. Block Volume Net Bias (0–20 pts) ──────────────────────────────
        block_pts = 0.0
        try:
            avg_vol = float(np.mean(vol[-21:-1])) if n >= 22 else float(np.mean(vol))
            if avg_vol > 0:
                threshold = avg_vol * 2.0
                bull_blocks = sum(
                    1 for i in range(-min(20, n-1), 0)
                    if vol[i] >= threshold and cl[i] >= op[i]
                )
                bear_blocks = sum(
                    1 for i in range(-min(20, n-1), 0)
                    if vol[i] >= threshold and cl[i] < op[i]
                )
                net = bull_blocks - bear_blocks
                if   net >= 5: block_pts = 20.0
                elif net >= 3: block_pts = 15.0
                elif net >= 2: block_pts = 10.0
                elif net >= 1: block_pts = 6.0
                elif net == 0: block_pts = 3.0
        except Exception:
            pass

        # ── 3. OBV Trend (0–15 pts) ──────────────────────────────────────────
        obv_pts = 0.0
        try:
            obv = np.zeros(n)
            for i in range(1, n):
                if cl[i] > cl[i-1]:   obv[i] = obv[i-1] + vol[i]
                elif cl[i] < cl[i-1]: obv[i] = obv[i-1] - vol[i]
                else:                 obv[i] = obv[i-1]
            obv_ema10 = _ema_np(obv, 10)
            obv_ema20 = _ema_np(obv, 20)
            obv_slope = (obv_ema10[-1] - obv_ema10[-min(10, n-1)]) / (abs(obv_ema10[-min(10, n-1)]) + 1e-10)
            obv_bull  = obv_ema10[-1] > obv_ema20[-1]
            if   obv_slope > 0.10 and obv_bull: obv_pts = 15.0
            elif obv_slope > 0.03 and obv_bull: obv_pts = 11.0
            elif obv_slope > 0    and obv_bull: obv_pts = 7.0
            elif obv_slope > 0:                 obv_pts = 4.0
            elif obv_trend:                     obv_pts = 5.0  # fallback from inst engine
        except Exception:
            if obv_trend: obv_pts = 5.0

        # ── 4. Absorption Quality (0–25 pts) ─────────────────────────────────
        # High-vol bars where price barely moved = supply being absorbed by buyers
        abs_pts = 0.0
        try:
            avg_vol_ = float(np.mean(vol[-21:-1])) if n >= 22 else float(np.mean(vol))
            avg_rng_ = float(np.mean(hi[-21:-1] - lo[-21:-1])) if n >= 22 else float(np.mean(hi - lo))
            if avg_vol_ > 0 and avg_rng_ > 0:
                quality_abs = 0
                strong_abs  = 0
                for k in range(1, min(15, n)):
                    v_k    = float(vol[-k])
                    body_k = abs(float(cl[-k]) - float(op[-k]))
                    hi_k   = float(hi[-k]); lo_k = float(lo[-k])
                    cl_k   = float(cl[-k]); op_k = float(op[-k])
                    mid_k  = (hi_k + lo_k) / 2
                    # High-vol tiny-body = absorption
                    if v_k > avg_vol_ * 1.5 and body_k < avg_rng_ * 0.25:
                        quality_abs += 1
                        if cl_k > mid_k:  # closed upper half = buyers won
                            strong_abs += 1
                    # High-vol red close in upper half = sellers tried, buyers held
                    elif (v_k > avg_vol_ * 1.8 and cl_k < op_k
                          and cl_k > mid_k and body_k < avg_rng_ * 0.40):
                        quality_abs += 1
                if   strong_abs >= 3: abs_pts = 25.0
                elif strong_abs >= 2: abs_pts = 20.0
                elif quality_abs >= 4:abs_pts = 18.0
                elif quality_abs >= 3:abs_pts = 14.0
                elif quality_abs >= 2:abs_pts = 9.0
                elif quality_abs >= 1:abs_pts = 5.0
        except Exception:
            pass

        # ── 5. Pressure Asymmetry (0–20 pts) ─────────────────────────────────
        # Net directional pressure per bar: (close - open) / range × volume
        pres_pts = 0.0
        try:
            lb_p = min(20, n - 1)
            rng_arr = hi[-lb_p:] - lo[-lb_p:]
            # Buying pressure fraction per bar (0=full selling, 1=full buying)
            bpf = np.where(rng_arr > 0,
                           (cl[-lb_p:] - lo[-lb_p:]) / rng_arr,
                           0.5)
            # Weighted by volume
            total_vol = float(np.sum(vol[-lb_p:]))
            if total_vol > 0:
                net_bp = float(np.sum((bpf - 0.5) * vol[-lb_p:])) / total_vol  # -0.5 to +0.5
                if   net_bp > 0.20: pres_pts = 20.0
                elif net_bp > 0.12: pres_pts = 15.0
                elif net_bp > 0.06: pres_pts = 10.0
                elif net_bp > 0.02: pres_pts = 6.0
                elif net_bp > 0:    pres_pts = 3.0
        except Exception:
            pass

        # Blend with PCA and inst_score
        pca_boost = round(float(np.clip((pca_score - 35.0) / 65.0 * 10.0, 0, 10)), 1)
        inst_boost = round(float(np.clip((inst_score - 50.0) / 50.0 * 5.0, 0, 5)), 1)

        raw_total = cmf_pts + block_pts + obv_pts + abs_pts + pres_pts + pca_boost + inst_boost
        total = round(float(np.clip(raw_total, 0, 100)), 1)

        if   total >= 80: verdict = "MARKUP_READY"
        elif total >= 65: verdict = "ACCUMULATING"
        elif total >= 50: verdict = "ABSORBING"
        elif total >= 35: verdict = "NEUTRAL"
        else:             verdict = "DISTRIBUTING"

        # Behavioral phase narrative
        if verdict in ("MARKUP_READY", "ACCUMULATING"):
            phase = "INSTITUTIONAL_BUY"
        elif verdict == "ABSORBING":
            phase = "SUPPLY_ABSORPTION"
        elif verdict == "NEUTRAL":
            phase = "EQUILIBRIUM"
        else:
            phase = "SUPPLY_PRESSURE"

        confidence = min(100, int(
            (1 if cmf_pts > 8 else 0) +
            (1 if block_pts > 6 else 0) +
            (1 if obv_pts > 7 else 0) +
            (1 if abs_pts > 9 else 0) +
            (1 if pres_pts > 6 else 0)
        ) * 20)

        out.update(
            SmartMoneyScore    = total,
            SmartMoneyVerdict  = verdict,
            SMBehaviorPhase    = phase,
            SMConfidence       = confidence,
            SMCMFScore         = round(cmf_pts,   1),
            SMBlockScore       = round(block_pts,  1),
            SMOBVScore         = round(obv_pts,    1),
            SMAbsorptionScore  = round(abs_pts,    1),
            SMPressureScore    = round(pres_pts,   1),
        )
    except Exception:
        pass
    return out

# ══════════════════════════════════════════════════════════════════════════════
# GAP-3 — ACCUMULATION SEQUENCING
# Infers WHERE in the Wyckoff / Weinstein base-building sequence a stock is.
# Uses PCA + EmScore + Phase + price structure to determine sequence position.
# ══════════════════════════════════════════════════════════════════════════════

_ACCUM_STAGES = {
    "NONE":  (0,  "No base detected"),
    "1A":    (20, "Base building — early contraction"),
    "1B":    (40, "Base testing — support holding"),
    "1C":    (60, "Spring / re-test — buyers absorbing supply"),
    "2A":    (80, "Early markup — first leg out of base"),
    "2B":    (95, "Markup continuation — trend established"),
}

def compute_accumulation_sequence(
    df: pd.DataFrame,
    mode: str,
    pca_score: float = 0.0,
    em_score: float = 0.0,
    phase: str = "IDLE",
    smart_money_verdict: str = "NEUTRAL",
    rs_line_high: bool = False,
) -> dict:
    """
    Accumulation Sequence Detector.

    Infers Wyckoff/Weinstein stage from the combination of:
    - Price structure (base width, depth, tightening)
    - PCA score (buying pressure evidence)
    - EmScore (coiling mechanics)
    - Phase classification
    - Smart money verdict

    Returns AccumStage (NONE/1A/1B/1C/2A/2B), AccumStageLabel,
    AccumSequenceScore (0–100), AccumConfidence, AccumBarsInBase.
    """
    out = dict(
        AccumStage="NONE", AccumStageLabel="No base detected",
        AccumSequenceScore=0, AccumConfidence=0, AccumBarsInBase=0,
    )
    try:
        if df is None or len(df) < 30:
            return out
        cl  = df["Close"].values.astype(np.float64)
        hi  = df["High"].values.astype(np.float64)
        lo  = df["Low"].values.astype(np.float64)
        vol = df["Volume"].values.astype(np.float64)
        n   = len(cl)

        # ── Base detection ────────────────────────────────────────────────────
        # Find the longest recent stretch where price stayed within a range ≤ 25%
        # of price (Weinstein Stage 1 base = sideways consolidation)
        base_bars = 0
        base_depth_pct = 0.0
        base_range_tightening = False
        try:
            lb = min(120, n)
            cl_lb = cl[-lb:]
            hi_lb = hi[-lb:]
            lo_lb = lo[-lb:]
            # Scan backwards for base: find max contiguous stretch within 20% range
            for start in range(lb - 1, 0, -1):
                sub_hi  = float(np.max(hi_lb[start:]))
                sub_lo  = float(np.min(lo_lb[start:]))
                mid_px  = (sub_hi + sub_lo) / 2
                if mid_px > 0:
                    depth = (sub_hi - sub_lo) / mid_px * 100
                    if depth <= 25.0:
                        base_bars = lb - start
                        base_depth_pct = round(depth, 1)
                        # Tightening: first half range > second half range
                        mid = start + (lb - start) // 2
                        h1 = float(np.max(hi_lb[start:mid])) - float(np.min(lo_lb[start:mid]))
                        h2 = float(np.max(hi_lb[mid:])) - float(np.min(lo_lb[mid:]))
                        base_range_tightening = (h2 < h1 * 0.80)
                    else:
                        break
        except Exception:
            pass

        # ── Spring / failed breakdown detection ───────────────────────────────
        spring_detected = False
        try:
            if base_bars >= 10 and n >= 15:
                lb_spring = min(base_bars, n - 5)
                base_lo_support = float(np.min(lo[-lb_spring - 5:-5]))
                spring_cnt = sum(
                    1 for k in range(1, min(10, n))
                    if float(lo[-k]) < base_lo_support * 0.997
                    and float(cl[-k]) >= base_lo_support * 0.999
                )
                spring_detected = spring_cnt >= 1
        except Exception:
            pass

        # ── Price breakout from base ──────────────────────────────────────────
        early_markup = phase in (PHASE_BRK, PHASE_CONT, PHASE_ENTRY)
        continued_markup = phase in (PHASE_CONT, PHASE_BRK) and rs_line_high

        # ── Sequence scoring ──────────────────────────────────────────────────
        # Combine structural evidence with PCA + Em signals
        seq_score = 0
        confidence_signals = 0

        if base_bars >= 20:   seq_score += 25; confidence_signals += 1
        elif base_bars >= 10: seq_score += 15
        elif base_bars >= 5:  seq_score += 8

        if base_range_tightening: seq_score += 15; confidence_signals += 1
        if spring_detected:        seq_score += 20; confidence_signals += 1
        if pca_score >= 50:        seq_score += 15; confidence_signals += 1
        elif pca_score >= 35:      seq_score += 8
        if em_score >= 45:         seq_score += 10; confidence_signals += 1
        elif em_score >= 30:       seq_score += 5
        if smart_money_verdict in ("ACCUMULATING", "MARKUP_READY"):
            seq_score += 15; confidence_signals += 1
        elif smart_money_verdict == "ABSORBING":
            seq_score += 8

        seq_score = int(np.clip(seq_score, 0, 100))
        confidence = min(100, confidence_signals * 17)

        # ── Stage assignment ──────────────────────────────────────────────────
        if continued_markup and rs_line_high:
            stage = "2B"
        elif early_markup and (pca_score >= 45 or seq_score >= 60):
            stage = "2A"
        elif spring_detected and pca_score >= 40:
            stage = "1C"
        elif base_bars >= 15 and base_range_tightening and pca_score >= 30:
            stage = "1B"
        elif base_bars >= 8 and seq_score >= 25:
            stage = "1A"
        else:
            stage = "NONE"

        label = _ACCUM_STAGES.get(stage, (0, "Unknown"))[1]

        out.update(
            AccumStage          = stage,
            AccumStageLabel     = label,
            AccumSequenceScore  = seq_score,
            AccumConfidence     = confidence,
            AccumBarsInBase     = base_bars,
        )
    except Exception:
        pass
    return out

# ══════════════════════════════════════════════════════════════════════════════
# GAP-4 — MICROSTRUCTURE LOGIC
# Reconstructs intrabar order-flow proxies from OHLCV. Works for all modes.
# ══════════════════════════════════════════════════════════════════════════════

def compute_microstructure(df: pd.DataFrame, mode: str) -> dict:
    """
    Microstructure Score (0–100 MicroScore).

    Intrabar order-flow proxies reconstructed from OHLCV:
    1. Close Location Value  (20 pts) — where close sits in bar range (=buying pressure)
    2. Delta Proxy           (20 pts) — fraction of bar range used upward (up-close bias)
    3. Absorption Ratio      (20 pts) — high-vol bars with small net move (=supply absorbed)
    4. Wick Asymmetry        (20 pts) — lower wicks > upper wicks = buyers defending
    5. VWAP Micro-Deviation  (20 pts) — price hugging VWAP from above = strong demand

    Labels: STRONG_BUY_FLOW ≥75 · BUY_FLOW ≥55 · NEUTRAL_FLOW ≥35 ·
            SELL_FLOW ≥20 · STRONG_SELL_FLOW <20
    """
    out = dict(
        MicroScore=0.0, MicroLabel="NEUTRAL_FLOW",
        MicroDelta=0.0, MicroCLV=0.0,
        MicroAbsorption=0.0, MicroWickAsym=0.0, MicroVWAPDev=0.0,
    )
    try:
        if df is None or len(df) < 20:
            return out
        cl  = df["Close"].values.astype(np.float64)
        hi  = df["High"].values.astype(np.float64)
        lo  = df["Low"].values.astype(np.float64)
        vol = df["Volume"].values.astype(np.float64)
        op  = (df["Open"].values.astype(np.float64)
               if "Open" in df.columns else cl.copy())
        n   = len(cl)

        # ── 1. Close Location Value (0–20 pts) ────────────────────────────────
        # CLV = (close - low) / (high - low); averaged = where buyers left price
        clv_pts = 0.0
        try:
            lb_clv = min(20, n)
            rng    = hi[-lb_clv:] - lo[-lb_clv:]
            clv    = np.where(rng > 0, (cl[-lb_clv:] - lo[-lb_clv:]) / rng, 0.5)
            # Volume-weighted CLV
            vw_clv = float(np.sum(clv * vol[-lb_clv:]) / (np.sum(vol[-lb_clv:]) + 1e-10))
            if   vw_clv > 0.70: clv_pts = 20.0
            elif vw_clv > 0.60: clv_pts = 15.0
            elif vw_clv > 0.50: clv_pts = 10.0
            elif vw_clv > 0.40: clv_pts = 5.0
            elif vw_clv > 0.30: clv_pts = 2.0
        except Exception:
            pass

        # ── 2. Delta Proxy (0–20 pts) ─────────────────────────────────────────
        # Measures how much of the bar's range was used on the upside
        # Approximation: (close - open) / range = net directional usage
        delta_pts = 0.0
        try:
            lb_d  = min(20, n)
            rng_d = hi[-lb_d:] - lo[-lb_d:]
            delta = np.where(rng_d > 0, (cl[-lb_d:] - op[-lb_d:]) / rng_d, 0.0)
            # Volume-weighted mean delta
            vw_delta = float(np.sum(delta * vol[-lb_d:]) / (np.sum(vol[-lb_d:]) + 1e-10))
            if   vw_delta > 0.25: delta_pts = 20.0
            elif vw_delta > 0.15: delta_pts = 15.0
            elif vw_delta > 0.05: delta_pts = 10.0
            elif vw_delta > 0:    delta_pts = 5.0
            elif vw_delta > -0.05:delta_pts = 2.0
        except Exception:
            pass

        # ── 3. Absorption Ratio (0–20 pts) ────────────────────────────────────
        # High-vol bars with small price move relative to vol = supply being absorbed
        abs_pts = 0.0
        try:
            avg_vol_ = float(np.mean(vol[-21:-1])) if n >= 22 else float(np.mean(vol))
            avg_rng_ = float(np.mean(hi[-21:-1] - lo[-21:-1])) if n >= 22 else float(np.mean(hi - lo))
            if avg_vol_ > 0 and avg_rng_ > 0:
                lb_a = min(15, n - 1)
                absorption_score = 0.0
                for k in range(1, lb_a + 1):
                    v_k   = float(vol[-k])
                    rng_k = float(hi[-k] - lo[-k])
                    # Volume efficiency ratio: vol per unit of range
                    if rng_k > 0:
                        eff = v_k / rng_k
                        avg_eff = avg_vol_ / (avg_rng_ + 1e-10)
                        # High efficiency + close in upper half = absorption
                        clv_k = (float(cl[-k]) - float(lo[-k])) / rng_k
                        if eff > avg_eff * 1.5 and clv_k > 0.50:
                            absorption_score += 2.0
                        elif eff > avg_eff * 1.2 and clv_k > 0.45:
                            absorption_score += 1.0
                abs_pts = min(20.0, absorption_score)
        except Exception:
            pass

        # ── 4. Wick Asymmetry (0–20 pts) ─────────────────────────────────────
        # Lower wicks > upper wicks = sellers tried to push down, buyers recovered
        wick_pts = 0.0
        try:
            lb_w   = min(20, n)
            upper_wicks = hi[-lb_w:] - np.maximum(cl[-lb_w:], op[-lb_w:])
            lower_wicks = np.minimum(cl[-lb_w:], op[-lb_w:]) - lo[-lb_w:]
            # Volume-weight each wick
            vw_upper = float(np.sum(upper_wicks * vol[-lb_w:]) / (np.sum(vol[-lb_w:]) + 1e-10))
            vw_lower = float(np.sum(lower_wicks * vol[-lb_w:]) / (np.sum(vol[-lb_w:]) + 1e-10))
            ratio = vw_lower / (vw_upper + 1e-10)
            if   ratio > 2.5: wick_pts = 20.0
            elif ratio > 1.8: wick_pts = 15.0
            elif ratio > 1.3: wick_pts = 10.0
            elif ratio > 1.0: wick_pts = 6.0
            elif ratio > 0.7: wick_pts = 2.0
        except Exception:
            pass

        # ── 5. VWAP Micro-Deviation (0–20 pts) ────────────────────────────────
        # How consistently price closes above rolling VWAP over recent bars
        vwap_pts = 0.0
        try:
            lb_v = min(20, n)
            typ  = (hi[-lb_v:] + lo[-lb_v:] + cl[-lb_v:]) / 3.0
            cum_vol  = np.cumsum(vol[-lb_v:])
            cum_tpv  = np.cumsum(typ * vol[-lb_v:])
            vwap_arr = cum_tpv / (cum_vol + 1e-10)
            # Count bars where close > rolling VWAP
            above_vwap = np.sum(cl[-lb_v:] > vwap_arr)
            pct_above  = above_vwap / lb_v
            # Also check: is close currently above VWAP?
            above_now  = float(cl[-1]) > float(vwap_arr[-1])
            if   pct_above > 0.80 and above_now: vwap_pts = 20.0
            elif pct_above > 0.65 and above_now: vwap_pts = 15.0
            elif pct_above > 0.55 and above_now: vwap_pts = 10.0
            elif pct_above > 0.45 and above_now: vwap_pts = 5.0
            elif above_now:                       vwap_pts = 3.0
        except Exception:
            pass

        total = round(float(np.clip(
            clv_pts + delta_pts + abs_pts + wick_pts + vwap_pts,
            0, 100
        )), 1)

        if   total >= 75: label = "STRONG_BUY_FLOW"
        elif total >= 55: label = "BUY_FLOW"
        elif total >= 35: label = "NEUTRAL_FLOW"
        elif total >= 20: label = "SELL_FLOW"
        else:             label = "STRONG_SELL_FLOW"

        out.update(
            MicroScore      = total,
            MicroLabel      = label,
            MicroCLV        = round(clv_pts,   1),
            MicroDelta      = round(delta_pts,  1),
            MicroAbsorption = round(abs_pts,    1),
            MicroWickAsym   = round(wick_pts,   1),
            MicroVWAPDev    = round(vwap_pts,   1),
        )
    except Exception:
        pass
    return out

# ══════════════════════════════════════════════════════════════════════════════
# v15.1 PATTERN HELPERS + v15.2 FIXES (closed-candle, pivot tolerance)
# ══════════════════════════════════════════════════════════════════════════════

# FIX-A: pivot tolerance multipliers per mode
_PIVOT_TOL = {"Intraday": 0.25, "Swing": 0.15, "Positional": 0.10}

def _tol(atr_val: float, mode: str) -> float:
    """Absolute price tolerance for pivot comparisons."""
    return atr_val * _PIVOT_TOL.get(mode, 0.15)

def _closed_candle_df(df: pd.DataFrame, mode: str, market_open: bool) -> pd.DataFrame:
    """Strip the live forming bar for Intraday when market is open."""
    if mode == "Intraday" and market_open and len(df) > 1:
        return df.iloc[:-1]
    return df

def detect_vcp(df: pd.DataFrame, atr_val: float = 0.0, mode: str = "Swing",
               min_contractions: int = 2, lookback: int = 60) -> dict:
    result = dict(detected=False, n_contractions=0, tightest_pct=0.0, vcp_grade="NONE")
    if len(df) < max(lookback, 20): return result
    sl = df.iloc[-lookback:]
    hi = sl["High"].values.astype(np.float64); lo = sl["Low"].values.astype(np.float64)
    vol = sl["Volume"].values.astype(np.float64); n = len(sl)
    tol_price = _tol(atr_val, mode) if atr_val > 0 else 0.0
    wing = 3
    phi = [i for i in range(wing, n-wing) if hi[i] >= np.max(hi[i-wing:i+wing+1]) - tol_price]
    plo = [i for i in range(wing, n-wing) if lo[i] <= np.min(lo[i-wing:i+wing+1]) + tol_price]
    if len(phi) < 2 or len(plo) < 2: return result
    segments = []
    for ph in phi:
        sub = [pl for pl in plo if pl > ph]
        if not sub: continue
        pl = sub[0]
        depth_abs = hi[ph] - lo[pl]; depth_pct = depth_abs / hi[ph] * 100
        seg_vol = float(np.mean(vol[ph:pl+1])) if pl > ph else float(vol[ph])
        segments.append((ph, pl, depth_pct, seg_vol, depth_abs))
    if len(segments) < 2: return result
    n_cont = 0
    for i in range(len(segments)-1, 0, -1):
        cur = segments[i]; prev = segments[i-1]
        if (cur[2] < prev[2]*0.95 and cur[3] < prev[3]*0.95
                and (prev[4]-cur[4]) > tol_price):
            n_cont += 1
        else: break
    detected = n_cont >= min_contractions
    tightest_pct = float(segments[-1][2]) if segments else 0.0
    grade = "PERFECT" if n_cont>=4 else "GOOD" if n_cont>=3 else "FORMING" if n_cont>=2 else "NONE"
    result.update(detected=detected, n_contractions=n_cont,
                  tightest_pct=round(tightest_pct,2), vcp_grade=grade)
    return result

def compute_anchored_vwap(df: pd.DataFrame, atr_val: float = 0.0,
                           mode: str = "Swing", lookback: int = 60) -> dict:
    result = dict(avwap=None, anchor_idx=None, pct_above=0.0,
                  price_above=False, near_support=False)
    if not {"High","Low","Close","Volume"}.issubset(df.columns) or len(df) < 10:
        return result
    sl = df.iloc[-lookback:]
    closes = sl["Close"].values.astype(np.float64); highs = sl["High"].values.astype(np.float64)
    lows = sl["Low"].values.astype(np.float64); volumes = sl["Volume"].values.astype(np.float64)
    n = len(sl); avg_vol = float(np.mean(volumes)) or 1.0
    best_idx = None; best_cl = float("inf")
    for i in range(n-1):
        if closes[i] < best_cl and volumes[i] >= avg_vol*0.8:
            best_cl = closes[i]; best_idx = i
    if best_idx is None: best_idx = int(np.argmin(closes[:-1]))
    typical = (highs[best_idx:]+lows[best_idx:]+closes[best_idx:])/3.0
    vols_s = volumes[best_idx:]
    avwap = float(np.cumsum(typical*vols_s)[-1] / (np.cumsum(vols_s)[-1]+1e-10))
    current = float(closes[-1])
    tol_abs = _tol(atr_val, mode) if atr_val > 0 else avwap*0.01
    pct_above = (current-avwap)/avwap*100 if avwap > 0 else 0.0
    price_above = current > avwap-tol_abs
    near_support = price_above and (current-avwap) < tol_abs
    result.update(avwap=round(avwap,2), anchor_idx=n-1-best_idx,
                  pct_above=round(pct_above,2), price_above=price_above,
                  near_support=near_support)
    return result

def score_fib_pullback(df: pd.DataFrame, atr_val: float,
                        mode: str = "Swing", lookback: int = 60) -> dict:
    result = dict(quality=0, grade="POOR", depth_ok=False, vol_ok=False,
                  recovery_ok=False, fib_level="—")
    if len(df) < 20 or atr_val <= 0: return result
    sl = df.iloc[-lookback:]
    hi_a = sl["High"].values.astype(np.float64); lo_a = sl["Low"].values.astype(np.float64)
    cl_a = sl["Close"].values.astype(np.float64); vo_a = sl["Volume"].values.astype(np.float64)
    n = len(sl); tol_abs = _tol(atr_val, mode); wing = 3
    phi = [i for i in range(wing, n-wing) if hi_a[i] >= np.max(hi_a[i-wing:i+wing+1])-tol_abs]
    plo = [i for i in range(wing, n-wing) if lo_a[i] <= np.min(lo_a[i-wing:i+wing+1])+tol_abs]
    if not phi or not plo: return result
    sw_hi_i = phi[-1]
    prior_lo = [i for i in plo if i < sw_hi_i]
    if not prior_lo: return result
    sw_lo_i = prior_lo[-1]
    sw_hi = float(hi_a[sw_hi_i]); sw_lo = float(lo_a[sw_lo_i]); rng = sw_hi-sw_lo
    if rng < atr_val*0.5: return result
    post_lo = float(np.min(lo_a[sw_hi_i:])); post_cl = float(cl_a[-1])
    depth_pct = (sw_hi-post_lo)/rng*100; tol_pct = tol_abs/rng*100
    def _in_zone(lo_p, hi_p): return (lo_p-tol_pct) <= depth_pct <= (hi_p+tol_pct)
    if _in_zone(38.2,50.0):   ds=40; dok=True; fl="38.2–50"
    elif _in_zone(50.0,61.8): ds=30; dok=True; fl="50–61.8"
    elif _in_zone(23.6,38.2): ds=15; dok=False; fl="23.6–38.2"
    elif _in_zone(61.8,78.6): ds=10; dok=False; fl="61.8–78.6"
    else:                     ds=0;  dok=False; fl="Outside"
    adv_v=float(np.mean(vo_a[sw_lo_i:sw_hi_i+1])) if sw_hi_i>sw_lo_i else 1.0
    pb_v=float(np.mean(vo_a[sw_hi_i:])) if len(vo_a[sw_hi_i:])>0 else 1.0
    vr=pb_v/(adv_v+1e-10)
    vs=30 if vr<=0.60 else (20 if vr<=0.75 else (10 if vr<=0.90 else 0))
    vok=vr<=0.75
    f500=sw_hi-rng*0.500; f618=sw_hi-rng*0.618; overshoot=max(0.0,f500-post_lo)
    if post_cl>f500-tol_abs and overshoot<=tol_abs*2: rs=30; rok=True
    elif post_cl>f618-tol_abs: rs=15; rok=False
    else: rs=0; rok=False
    quality=ds+vs+rs
    grade="EXCELLENT" if quality>=80 else "GOOD" if quality>=60 else "FAIR" if quality>=40 else "POOR"
    result.update(quality=quality, grade=grade, depth_ok=dok, vol_ok=vok,
                  recovery_ok=rok, fib_level=fl)
    return result

def detect_volume_dryup(df: pd.DataFrame, atr_val: float,
                         mode: str = "Swing", window: int = 5) -> dict:
    result = dict(dry_up=False, intensity=0, bars=0, vol_pct=100.0)
    if len(df) < max(window+5, 25) or atr_val <= 0: return result
    vols = df["Volume"].values.astype(np.float64)
    highs = df["High"].values.astype(np.float64); lows = df["Low"].values.astype(np.float64)
    n = len(vols)
    avg_vol_20 = float(np.mean(vols[-21:-1])) if n>=22 else float(np.mean(vols[:-1]))
    if avg_vol_20 <= 0: return result
    consec = 0
    for i in range(1, min(window+1, n)):
        if vols[-i] < vols[-(i+1)]: consec += 1
        else: break
    tight = False
    if consec >= 2:
        tight = (float(np.max(highs[-consec:]))-float(np.min(lows[-consec:]))) < atr_val*1.2
    latest_vol_pct = float(vols[-1])/avg_vol_20*100
    dry_up = consec>=2 and tight and latest_vol_pct<80.0
    if dry_up:
        intensity = 3 if (latest_vol_pct<40 and consec>=4) else (2 if (latest_vol_pct<60 and consec>=3) else 1)
    else: intensity = 0
    result.update(dry_up=dry_up, intensity=intensity, bars=consec, vol_pct=round(latest_vol_pct,1))
    return result

def compute_relative_volume(df: pd.DataFrame, lookback: int = 60) -> dict:
    result = dict(rel_vol_pct=50.0, label="NORMAL", ratio=1.0)
    if len(df) < 10: return result
    vols = df["Volume"].values.astype(np.float64)
    window = vols[-lookback-1:-1] if len(vols)>lookback+1 else vols[:-1]
    cur_vol = float(vols[-1])
    if len(window)==0 or float(np.max(window))==0: return result
    pct_rank = float(np.sum(window<cur_vol))/len(window)*100
    ratio = cur_vol/(float(np.mean(window))+1e-10)
    label = "SURGE" if pct_rank>=85 else "HIGH" if pct_rank>=65 else "NORMAL" if pct_rank>=30 else "DRY"
    result.update(rel_vol_pct=round(pct_rank,1), label=label, ratio=round(ratio,2))
    return result

def detect_darvas_box(df: pd.DataFrame, atr_val: float,
                       mode: str = "Swing", lookback: int = 60) -> dict:
    result = dict(in_box=False, breakout=False, box_top=0.0, box_bottom=0.0,
                  box_width_pct=0.0, bars_in_box=0)
    if len(df) < 20 or atr_val <= 0: return result
    sl = df.iloc[-lookback:]
    hi_a = sl["High"].values.astype(np.float64); lo_a = sl["Low"].values.astype(np.float64)
    cl_a = sl["Close"].values.astype(np.float64); n = len(sl)
    tol = _tol(atr_val, mode)
    peak_i = int(np.argmax(hi_a)); box_top = float(hi_a[peak_i])
    if peak_i >= n-3: peak_i = max(0, peak_i-3)
    top_confirmed = False; top_i = peak_i; consec_below = 0
    for i in range(peak_i+1, min(peak_i+10, n)):
        if hi_a[i] < box_top+tol: consec_below += 1
        else: box_top = float(hi_a[i]); consec_below = 0
        if consec_below >= 3: top_confirmed = True; top_i = i; break
    if not top_confirmed: return result
    sub_lo = lo_a[top_i:]
    if len(sub_lo) < 4: return result
    trough_i = int(np.argmin(sub_lo))+top_i; box_bottom = float(lo_a[trough_i])
    btm_confirmed = False; consec_above = 0
    for i in range(trough_i+1, min(trough_i+10, n)):
        if lo_a[i] > box_bottom-tol: consec_above += 1
        else: box_bottom = float(lo_a[i]); consec_above = 0
        if consec_above >= 3: btm_confirmed = True; break
    if not btm_confirmed: return result
    cur = float(cl_a[-1])
    in_box = (box_bottom-tol) <= cur <= (box_top+tol)
    breakout = cur > box_top+tol
    box_width_pct = (box_top-box_bottom)/box_bottom*100 if box_bottom>0 else 0.0
    result.update(in_box=in_box, breakout=breakout, box_top=round(box_top,2),
                  box_bottom=round(box_bottom,2), box_width_pct=round(box_width_pct,2),
                  bars_in_box=n-trough_i)
    return result

def score_all_patterns(df: pd.DataFrame, atr_val: float,
                        mode: str = "Swing", market_open: bool = False) -> tuple:
    """FIX-A+B: runs on closed candles only; called externally via enrich_with_patterns."""
    closed = _closed_candle_df(df, mode, market_open)
    if len(closed) < 20: return 0, {}
    vcp    = detect_vcp(closed,            atr_val=atr_val, mode=mode)
    avwap  = compute_anchored_vwap(closed, atr_val=atr_val, mode=mode)
    fibq   = score_fib_pullback(closed,    atr_val=atr_val, mode=mode)
    vdu    = detect_volume_dryup(closed,   atr_val=atr_val, mode=mode)
    rvol   = compute_relative_volume(closed)
    darvas = detect_darvas_box(closed,     atr_val=atr_val, mode=mode)
    pts = 0
    if vcp["n_contractions"] >= 3:    pts += 14
    elif vcp["n_contractions"] >= 2:  pts += 7
    if avwap["price_above"]:          pts += 8
    if avwap["near_support"]:         pts += 4
    fq = fibq["quality"]
    if fq >= 75:                      pts += 10
    elif fq >= 50:                    pts += 5
    if vdu["intensity"] >= 2:         pts += 8
    elif vdu["intensity"] == 1:       pts += 4
    rvp = rvol["rel_vol_pct"]
    if rvp >= 85:                     pts += 10
    elif rvp >= 65:                   pts += 5
    if darvas["breakout"]:            pts += 12
    elif darvas["in_box"]:            pts += 6
    patterns = dict(vcp=vcp, avwap=avwap, fib_quality=fibq,
                    vol_dryup=vdu, rel_vol=rvol, darvas=darvas,
                    total_pattern_pts=pts)
    return pts, patterns

# ══════════════════════════════════════════════════════════════════════════════
# ENGINE 1 — MULTI-TIMEFRAME MOMENTUM SYNCHRONIZATION
# ══════════════════════════════════════════════════════════════════════════════

_MTF_CFG = {
    "Intraday":   (("5m",  "15m", "1h"),  (0.25, 0.40, 0.35)),
    "Swing":      (("1d",  "1wk", "1mo"), (0.30, 0.40, 0.30)),
    "Positional": (("1d",  "1wk", "1mo"), (0.20, 0.40, 0.40)),
}

def _mtf_tf_score(close_s: pd.Series, ema_fast: int, ema_slow: int) -> float:
    """Score a single timeframe: -1.0 (full bear) to +1.0 (full bull)."""
    n = len(close_s)
    if n < ema_slow + 5:
        return 0.0
    c   = float(close_s.iloc[-1])
    ef  = float(close_s.ewm(span=ema_fast, adjust=False).mean().iloc[-1])
    es  = float(close_s.ewm(span=ema_slow, adjust=False).mean().iloc[-1])
    rv  = float(rsi(close_s, 14).iloc[-1])
    lb  = max(1, min(21, n - 1))
    mom = (c - float(close_s.iloc[-lb])) / float(close_s.iloc[-lb]) * 100
    s   = 0.0
    s  += 0.30 if c  > ef  else -0.30
    s  += 0.30 if ef > es  else -0.30
    s  += 0.20 if rv > 50  else -0.20
    s  += 0.20 if mom > 0  else -0.20
    return float(np.clip(s, -1.0, 1.0))

def compute_mtf_sync(sym: str, mode: str,
                     prefetched: dict | None = None) -> dict:
    """
    Multi-Timeframe Momentum Synchronization.
    Returns sync_score (0–100), alignment flag, per-TF scores, divergence flag.
    """
    out = dict(sync_score=50.0, aligned=False, bull_count=0, bear_count=0,
               tf_scores={}, divergence=False, mtf_label="NEUTRAL")
    try:
        intervals, weights = _MTF_CFG[mode]
        cfg      = MODE_CFG[mode]
        ef_span  = cfg["ema_fast"]
        es_span  = cfg["ema_slow"]
        data     = prefetched or {}
        tf_scores: dict = {}

        for tf in intervals:
            df = data.get(tf)
            if df is None or df.empty or len(df) < 30:
                tf_scores[tf] = 0.0
                continue
            tf_scores[tf] = _mtf_tf_score(df["Close"], ef_span, es_span)

        weighted  = sum(tf_scores.get(tf, 0.0) * w
                        for tf, w in zip(intervals, weights))
        sync_score = round((weighted + 1.0) / 2.0 * 100.0, 1)

        scores    = [tf_scores.get(tf, 0.0) for tf in intervals]
        bull_cnt  = sum(1 for s in scores if s >  0.2)
        bear_cnt  = sum(1 for s in scores if s < -0.2)
        aligned   = (bull_cnt == len(intervals)) or (bear_cnt == len(intervals))
        diverge   = (len(scores) >= 2
                     and ((scores[0] > 0.3 and scores[-1] < -0.3)
                          or (scores[0] < -0.3 and scores[-1] > 0.3)))

        if   sync_score >= 70 and aligned: lbl = "BULL SYNC"
        elif sync_score >= 60:             lbl = "BULL LEAN"
        elif sync_score <= 30 and aligned: lbl = "BEAR SYNC"
        elif sync_score <= 40:             lbl = "BEAR LEAN"
        elif diverge:                      lbl = "DIVERGE"
        else:                              lbl = "NEUTRAL"

        out.update(sync_score=sync_score, aligned=aligned,
                   bull_count=bull_cnt, bear_count=bear_cnt,
                   tf_scores=tf_scores, divergence=diverge, mtf_label=lbl)
    except Exception:
        pass
    return out

def prefetch_mtf_parallel(symbols: list, mode: str) -> dict:
    """Batch-fetch secondary/tertiary TF data for all survivors (async)."""
    intervals, _ = _MTF_CFG[mode]
    result: dict = {sym: {} for sym in symbols}
    if len(intervals) < 2 or not symbols:
        return result
    for tf in intervals[1:]:
        period = "1y" if tf in ("15m", "1h") else "3y"
        raw    = fetch_async(symbols, period, tf, concurrency=64)
        for sym, df in raw.items():
            result[sym][tf] = df
    return result

# ══════════════════════════════════════════════════════════════════════════════
# ENGINE 2 — INSTITUTIONAL VOLUME ANALYSIS
# ══════════════════════════════════════════════════════════════════════════════

def analyze_institutional_volume(df: pd.DataFrame,
                                  mode: str = "Swing") -> dict:
    """
    Detect institutional accumulation / distribution via OBV, CMF,
    Acc/Dist line, block-volume fingerprint, and Wyckoff Effort-vs-Result.
    Returns inst_score (0–100), verdict, and component values.
    """
    out = dict(inst_score=50.0, verdict="NEUTRAL", obv_trend=0.0,
               cmf=0.0, acc_dist=0.0, block_days=0,
               effort_vs_result="NEUTRAL", inst_label="INST~")
    try:
        if len(df) < 30:
            return out
        cl  = df["Close"].values.astype(np.float64)
        hi  = df["High"].values.astype(np.float64)
        lo  = df["Low"].values.astype(np.float64)
        vol = df["Volume"].values.astype(np.float64)
        n   = len(cl)

        # OBV trend — EMA(10) vs EMA(30)
        direction  = np.sign(np.diff(cl, prepend=cl[0]))
        obv        = np.cumsum(direction * vol)
        obv_trend  = 1.0 if float(_ema_np(obv, 10)[-1]) > float(_ema_np(obv, 30)[-1]) else -1.0

        # Chaikin Money Flow (20-bar)
        win   = min(20, n)
        hlr   = np.where((hi[-win:] - lo[-win:]) == 0, 1e-10,
                          hi[-win:] - lo[-win:])
        mfm   = ((cl[-win:] - lo[-win:]) - (hi[-win:] - cl[-win:])) / hlr
        cmf   = float(np.sum(mfm * vol[-win:]) / (np.sum(vol[-win:]) + 1e-10))

        # Accumulation / Distribution
        hlr_full = np.where((hi - lo) == 0, 1e-10, hi - lo)
        ad_mfm   = ((cl - lo) - (hi - cl)) / hlr_full
        ad_line  = np.cumsum(ad_mfm * vol)
        ad_trend = 1.0 if ad_line[-1] > ad_line[-min(10, n)] else -1.0

        # Block volume (institutional fingerprint) — days > 2.5× avg
        avg_vol    = float(np.mean(vol[-min(60, n):])) or 1.0
        block_days = int(np.sum(vol[-min(20, n):] > avg_vol * 2.5))

        # Wyckoff Effort-vs-Result (last 5 bars)
        recent     = min(5, n)
        avg_rng    = float(np.mean(hi[-min(20,n):] - lo[-min(20,n):])) or 1e-10
        last_rng   = float(np.mean(hi[-recent:] - lo[-recent:]))
        last_vr    = float(np.mean(vol[-recent:])) / avg_vol
        if   last_vr > 1.3 and last_rng > avg_rng * 0.8: evr = "THRUST"
        elif last_vr > 1.3 and last_rng < avg_rng * 0.6: evr = "ABSORPTION"
        elif last_vr < 0.7:                               evr = "DRY"
        else:                                             evr = "NEUTRAL"

        # Composite score (centre 50)
        score  = 50.0
        score += obv_trend * 12.0
        score += float(np.clip(cmf * 100, -15, 15))
        score += ad_trend  * 8.0
        score += min(block_days * 3, 12)
        if evr == "THRUST":        score += 10.0
        elif evr == "ABSORPTION":  score -=  8.0
        elif evr == "DRY":         score -=  5.0
        score = float(np.clip(score, 0, 100))

        if   score >= 70: verdict = "ACCUMULATION"
        elif score >= 58: verdict = "MILD ACCUM"
        elif score <= 30: verdict = "DISTRIBUTION"
        elif score <= 42: verdict = "MILD DIST"
        else:             verdict = "NEUTRAL"

        inst_label = "INST↑" if score >= 65 else ("INST↓" if score <= 35 else "INST~")

        out.update(inst_score=round(score, 1), verdict=verdict,
                   obv_trend=round(obv_trend, 2), cmf=round(cmf, 4),
                   acc_dist=round(ad_trend, 2), block_days=block_days,
                   effort_vs_result=evr, inst_label=inst_label)
    except Exception:
        pass
    return out

# ══════════════════════════════════════════════════════════════════════════════
# ENGINE 3 — HARMONIC / ABCD PATTERN ENGINE
# ══════════════════════════════════════════════════════════════════════════════

_HARMONIC_DEF = {
    "Gartley":   dict(AB_XA=(0.618,0.618), BC_AB=(0.382,0.886),
                      CD_BC=(1.272,1.618), AD_XA=(0.786,0.786), tol=0.05),
    "Bat":       dict(AB_XA=(0.382,0.500), BC_AB=(0.382,0.886),
                      CD_BC=(1.618,2.618), AD_XA=(0.886,0.886), tol=0.05),
    "Butterfly": dict(AB_XA=(0.786,0.786), BC_AB=(0.382,0.886),
                      CD_BC=(1.618,2.618), AD_XA=(1.272,1.272), tol=0.06),
    "Crab":      dict(AB_XA=(0.382,0.618), BC_AB=(0.382,0.886),
                      CD_BC=(2.618,3.618), AD_XA=(1.618,1.618), tol=0.06),
    "Cypher":    dict(AB_XA=(0.382,0.618), BC_AB=(1.272,1.414),
                      CD_BC=(0.382,0.786), AD_XA=(0.786,0.786), tol=0.07),
}

def _fib_ok(val: float, lo: float, hi: float, tol: float) -> bool:
    mn, mx = min(lo, hi), max(lo, hi)
    return mn * (1 - tol) <= val <= mx * (1 + tol)

def _find_swing_pivots(arr: np.ndarray, wing: int = 4) -> list:
    """Return alternating (idx, price, 'H'/'L') swing pivots."""
    n = len(arr); pivots = []
    for i in range(wing, n - wing):
        w = arr[i - wing: i + wing + 1]
        if arr[i] == np.max(w):   pivots.append((i, float(arr[i]), "H"))
        elif arr[i] == np.min(w): pivots.append((i, float(arr[i]), "L"))
    # Keep only alternating, prefer stronger pivot on same type run
    deduped: list = []
    for p in pivots:
        if deduped and deduped[-1][2] == p[2]:
            if (p[2] == "H" and p[1] > deduped[-1][1]) or \
               (p[2] == "L" and p[1] < deduped[-1][1]):
                deduped[-1] = p
        else:
            deduped.append(p)
    return deduped

def detect_harmonic_patterns(df: pd.DataFrame,
                              mode: str = "Swing") -> dict:
    """
    Detect ABCD and named harmonic patterns (Gartley, Bat, Butterfly, Crab, Cypher).
    Returns best match: pattern name, direction, quality (0–100),
    completion zone, and harmonic_score contribution.
    """
    out = dict(pattern=None, direction=None, quality=0,
               completion_zone=(0.0, 0.0), harmonic_score=0,
               d_level=0.0, detected=False)
    try:
        if len(df) < 60:
            return out
        hi  = df["High"].values.astype(np.float64)
        lo  = df["Low"].values.astype(np.float64)
        mid = (hi + lo) / 2.0

        pivots = _find_swing_pivots(mid, wing=4)
        if len(pivots) < 5:
            return out

        best: dict | None = None
        best_q = 0

        for start in range(max(0, len(pivots) - 5), -1, -1):
            pts = pivots[start: start + 5]
            if len(pts) < 5:
                continue
            X, A, B, C, D = pts
            types = [p[2] for p in pts]
            # Strict alternation required
            if any(types[i] == types[i+1] for i in range(4)):
                continue

            px, pa, pb, pc, pd_ = [p[1] for p in pts]
            bull = types[0] == "L"   # bullish: X=low, completion at D=low

            XA  = abs(pa - px)
            AB  = abs(pa - pb)
            BC  = abs(pc - pb)
            CD  = abs(pc - pd_)
            if any(v <= 0 for v in (XA, AB, BC, CD)):
                continue

            ab_xa = AB / XA
            bc_ab = BC / AB
            cd_bc = CD / BC
            ad_xa = abs(pa - pd_) / XA

            # ABCD (simple)
            abcd_q = 0
            if _fib_ok(ab_xa, 0.382, 0.786, 0.07) and \
               _fib_ok(cd_bc, 1.13,  1.618, 0.08):
                abcd_q = 60

            # Named harmonics
            for name, r in _HARMONIC_DEF.items():
                tol = r["tol"]
                hits = sum([_fib_ok(ab_xa, *r["AB_XA"], tol),
                            _fib_ok(bc_ab, *r["BC_AB"], tol),
                            _fib_ok(cd_bc, *r["CD_BC"], tol),
                            _fib_ok(ad_xa, *r["AD_XA"], tol)])
                q = int(hits / 4 * 100)
                if hits >= 3 and q > best_q:
                    d_lo = (pc - XA * r["AD_XA"][0] if bull
                            else pc + XA * r["AD_XA"][0])
                    d_hi = (pc - XA * r["AD_XA"][1] if bull
                            else pc + XA * r["AD_XA"][1])
                    best_q = q
                    best   = dict(pattern=name,
                                  direction="BULL" if bull else "BEAR",
                                  quality=q,
                                  completion_zone=(round(min(d_lo,d_hi),2),
                                                   round(max(d_lo,d_hi),2)),
                                  d_level=round(pd_, 2), detected=True)

            if abcd_q > best_q and best is None:
                best_q = abcd_q
                best   = dict(pattern="ABCD",
                              direction="BULL" if bull else "BEAR",
                              quality=abcd_q,
                              completion_zone=(round(pd_*0.995,2),
                                               round(pd_*1.005,2)),
                              d_level=round(pd_,2), detected=True)

        if best:
            best["harmonic_score"] = int(best["quality"] * 0.8)
            out.update(best)
    except Exception:
        pass
    return out

# ══════════════════════════════════════════════════════════════════════════════
# ENGINE 4 — ADAPTIVE REGIME SCORING
# ══════════════════════════════════════════════════════════════════════════════

_REGIME_WEIGHTS = {
    "TREND_BULL":   dict(TREND=35, MOMENTUM=22, STRUCTURE=18, VOLUME=13, QUALITY=12),
    "TREND_BEAR":   dict(TREND=28, MOMENTUM=15, STRUCTURE=22, VOLUME=18, QUALITY=17),
    "RANGE_BULL":   dict(TREND=22, MOMENTUM=18, STRUCTURE=28, VOLUME=15, QUALITY=17),
    "RANGE_BEAR":   dict(TREND=18, MOMENTUM=12, STRUCTURE=30, VOLUME=18, QUALITY=22),
    "HIGHVOL_BULL": dict(TREND=25, MOMENTUM=18, STRUCTURE=20, VOLUME=17, QUALITY=20),
    "HIGHVOL_BEAR": dict(TREND=15, MOMENTUM=10, STRUCTURE=20, VOLUME=20, QUALITY=35),
    "DEFAULT":      dict(TREND=30, MOMENTUM=20, STRUCTURE=20, VOLUME=15, QUALITY=15),
}
_REGIME_LABELS = {
    "TREND_BULL": "Trending Bull",   "TREND_BEAR": "Trending Bear",
    "RANGE_BULL": "Ranging Bull",    "RANGE_BEAR": "Ranging Bear",
    "HIGHVOL_BULL":"High-Vol Bull",  "HIGHVOL_BEAR":"High-Vol Bear",
    "DEFAULT":    "Default",
}

def classify_regime(market_bullish: bool,
                    adx_val: float,
                    vix_val: float | None = None) -> tuple:
    """
    Classify the market regime into one of 6 buckets.
    Returns (regime_key, regime_label, weights_dict).
    """
    trending = adx_val >= 22
    high_vol  = vix_val is not None and vix_val >= VIX_CAUTION

    if   high_vol  and     market_bullish: key = "HIGHVOL_BULL"
    elif high_vol  and not market_bullish: key = "HIGHVOL_BEAR"
    elif trending  and     market_bullish: key = "TREND_BULL"
    elif trending  and not market_bullish: key = "TREND_BEAR"
    elif market_bullish:                   key = "RANGE_BULL"
    else:                                  key = "RANGE_BEAR"

    return key, _REGIME_LABELS[key], _REGIME_WEIGHTS[key]

# ══════════════════════════════════════════════════════════════════════════════
# ENGINE 5 — CANDLE STRUCTURE INTELLIGENCE
# ══════════════════════════════════════════════════════════════════════════════

def detect_candle_structure(df: pd.DataFrame,
                             atr_val: float,
                             mode: str = "Swing") -> dict:
    """
    Identify single, two, and three-candle patterns on the last 1–5 bars.
    Returns candle_score (−10 to +10), list of pattern names, and signal.
    """
    out = dict(candle_score=0, patterns=[], candle_signal="NEUTRAL",
               nr7=False, inside_bar=False)
    try:
        if len(df) < 10 or atr_val <= 0:
            return out
        op  = (df["Open"].values.astype(np.float64)
               if "Open" in df.columns else df["Close"].values.astype(np.float64))
        hi  = df["High"].values.astype(np.float64)
        lo  = df["Low"].values.astype(np.float64)
        cl  = df["Close"].values.astype(np.float64)
        n   = len(cl)

        score    = 0
        patterns: list = []

        c0,o0,h0,l0 = cl[-1],op[-1],hi[-1],lo[-1]
        c1,o1,h1,l1 = cl[-2],op[-2],hi[-2],lo[-2]
        body0       = abs(c0 - o0)
        body1       = abs(c1 - o1)
        rng0        = h0 - l0
        bull0       = c0 > o0
        bull1       = c1 > o1
        uw0         = h0 - max(c0, o0)   # upper wick
        lw0         = min(c0, o0) - l0   # lower wick

        # ── Single-candle ──────────────────────────────────────────────────────
        if rng0 > atr_val * 0.5:
            if lw0 > body0 * 2.0 and uw0 < body0 * 0.5:
                patterns.append("Hammer"); score += 4
            if uw0 > body0 * 2.0 and lw0 < body0 * 0.5:
                if bull0: patterns.append("Inverted Hammer"); score += 2
                else:     patterns.append("Shooting Star");  score -= 5

        if rng0 > 0 and body0 / rng0 < 0.10:
            if   lw0 > rng0 * 0.60: patterns.append("Dragonfly Doji");  score += 3
            elif uw0 > rng0 * 0.60: patterns.append("Gravestone Doji"); score -= 3
            else:                   patterns.append("Doji")

        if body0 > atr_val * 0.7:
            if bull0: patterns.append("Bull Marubozu"); score += 3
            else:     patterns.append("Bear Marubozu"); score -= 3

        # ── Two-candle ────────────────────────────────────────────────────────
        if n >= 2:
            if not bull1 and bull0 and body0 > body1*1.2 and c0>o1 and o0<c1:
                patterns.append("Bullish Engulfing"); score += 6
            if bull1 and not bull0 and body0 > body1*1.2 and c0<o1 and o0>c1:
                patterns.append("Bearish Engulfing"); score -= 6
            if h0 < h1 and l0 > l1:
                patterns.append("Inside Bar"); out["inside_bar"] = True; score += 1
            if not bull1 and bull0 and o0 < l1 and c0 > (o1+c1)/2:
                patterns.append("Piercing Line"); score += 4
            if bull1 and not bull0 and o0 > h1 and c0 < (o1+c1)/2:
                patterns.append("Dark Cloud Cover"); score -= 4

        # ── Three-candle ──────────────────────────────────────────────────────
        if n >= 3:
            c2,o2 = cl[-3],op[-3]
            bull2 = c2 > o2
            if not bull2 and abs(c1-o1)<atr_val*0.3 and bull0 and c0>(c2+o2)/2:
                patterns.append("Morning Star"); score += 7
            if bull2 and abs(c1-o1)<atr_val*0.3 and not bull0 and c0<(c2+o2)/2:
                patterns.append("Evening Star"); score -= 7
            if bull0 and bull1 and bull2 and c0>c1>c2 and o0>o1>o2:
                patterns.append("3 White Soldiers"); score += 5
            if not bull0 and not bull1 and not bull2 and c0<c1<c2 and o0<o1<o2:
                patterns.append("3 Black Crows"); score -= 5

        # ── NR7 ───────────────────────────────────────────────────────────────
        if n >= 7:
            ranges = hi[-7:] - lo[-7:]
            if rng0 == float(np.min(ranges)):
                patterns.append("NR7"); out["nr7"] = True; score += 2

        score = int(np.clip(score, -10, 10))
        if   score >=  4: sig = "BULL"
        elif score >=  1: sig = "BULL LEAN"
        elif score <= -4: sig = "BEAR"
        elif score <= -1: sig = "BEAR LEAN"
        else:             sig = "NEUTRAL"

        out.update(candle_score=score, patterns=patterns, candle_signal=sig)
    except Exception:
        pass
    return out

# FIX-B: gate constants
PATTERN_ENRICH_SCORE_MIN = 45
PATTERN_ENRICH_PHASES    = {"ENTRY", "CONT", "BREAKOUT", "SETUP"}

_EMPTY_PAT = dict(
    vcp=dict(detected=False,n_contractions=0,tightest_pct=0.0,vcp_grade="NONE"),
    avwap=dict(avwap=None,price_above=False,near_support=False,pct_above=0.0),
    fib_quality=dict(quality=0,grade="POOR",depth_ok=False,vol_ok=False,recovery_ok=False,fib_level="—"),
    vol_dryup=dict(dry_up=False,intensity=0,bars=0,vol_pct=100.0),
    rel_vol=dict(rel_vol_pct=50.0,label="NORMAL",ratio=1.0),
    darvas=dict(in_box=False,breakout=False,box_top=0.0,box_bottom=0.0,box_width_pct=0.0,bars_in_box=0),
    total_pattern_pts=0)

def _apply_pattern_keys(r: dict, patterns: dict) -> dict:
    r["Patterns"]     = patterns
    r["VCP"]          = patterns.get("vcp",{}).get("detected",False)
    r["VCPGrade"]     = patterns.get("vcp",{}).get("vcp_grade","NONE")
    r["AVWAP"]        = patterns.get("avwap",{}).get("avwap")
    r["AVWAPAbove"]   = patterns.get("avwap",{}).get("price_above",False)
    r["FibQuality"]   = patterns.get("fib_quality",{}).get("quality",0)
    r["FibGrade"]     = patterns.get("fib_quality",{}).get("grade","POOR")
    r["VolDryup"]     = patterns.get("vol_dryup",{}).get("dry_up",False)
    r["VDUIntensity"] = patterns.get("vol_dryup",{}).get("intensity",0)
    r["RVolPct"]      = patterns.get("rel_vol",{}).get("rel_vol_pct",50.0)
    r["RVolLabel"]    = patterns.get("rel_vol",{}).get("label","NORMAL")
    r["DarvasIn"]     = patterns.get("darvas",{}).get("in_box",False)
    r["DarvasBrk"]    = patterns.get("darvas",{}).get("breakout",False)
    r["DarvasTop"]    = patterns.get("darvas",{}).get("box_top",0.0)
    return r

def enrich_with_patterns(results: list, data: dict, mode: str, market_open: bool) -> list:
    """FIX-B: pattern engine runs ONLY on shortlisted stocks after Stage-B."""
    to_enrich = [r for r in results
                 if r.get("Score",0) >= PATTERN_ENRICH_SCORE_MIN
                 and r.get("Phase","") in PATTERN_ENRICH_PHASES
                 and r.get("Symbol","") in data
                 and data.get(r.get("Symbol","")) is not None
                 and not data.get(r.get("Symbol",""),pd.DataFrame()).empty]
    passthrough = [r for r in results if r not in to_enrich]
    for r in passthrough:
        _apply_pattern_keys(r, dict(_EMPTY_PAT))

    def _enrich_one(r):
        sym = r["Symbol"]; df = data[sym]; atr_val = r.get("ATR", 0.0)
        try:
            pts, patterns = score_all_patterns(df, atr_val=atr_val, mode=mode,
                                               market_open=market_open)
        except Exception:
            pts, patterns = 0, dict(_EMPTY_PAT)
        _apply_pattern_keys(r, patterns)
        if pts > 0:
            # FIX-5: scale down pattern bonus when exhaustion flags have fired
            # so patterns cannot leapfrog a stock past the exhaustion gate
            ext_n = r.get("ExtN", 0)
            if ext_n >= 3:
                bonus = 0.0                     # critical exhaustion — block bonus entirely
            elif ext_n == 2:
                bonus = round(pts * 0.25, 1)    # moderate exhaustion — halved bonus
            else:
                bonus = round(pts * 0.5, 1)     # clean stock — full 50% bonus
            r["Score"] = round(min(100.0, r.get("Score", 0) + bonus), 1)
            ns = r["Score"]
            r["Action"] = ("STRONG BUY" if ns>=75 else "BUY" if ns>=58
                           else "WATCH" if ns>=42 else "SKIP")
        return r

    if to_enrich:
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(16,len(to_enrich))) as pool:
            enriched = list(pool.map(_enrich_one, to_enrich))
    else:
        enriched = []
    all_out = enriched + passthrough
    all_out.sort(key=lambda x: x.get("Score",0), reverse=True)
    return all_out

# ══════════════════════════════════════════════════════════════════════════════
# FIX-C: CATEGORY-BASED WEIGHTED SCORING (v15.3 calibrated)
# ══════════════════════════════════════════════════════════════════════════════

_CAT_W = dict(TREND=30, MOMENTUM=20, STRUCTURE=20, VOLUME=15, QUALITY=15)
_PHASE_RAW = {"BREAKOUT":100,"CONT":85,"ENTRY":65,"SETUP":40,"IDLE":10,"EXIT":0}

def category_score(*,
                   trend_up, ema_stack, fresh_cross, htf_up, market_bullish, e_fast_gt_slow,
                   rsi, mom1, mom3, mom6, mom1_th, mom3_th, mom6_th,
                   phase, in_golden, near_e127, near_e161, norm_bull_raw,
                   rs_rank, c_gt_hh, c_near_hh,
                   vol_ratio, vol_avg_gt_zero, adx_val,
                   squeeze, vc_ratio, ext_penalty,
                   regime_bearish,
                   # Engine 1 — MTF sync (optional, safe default = neutral)
                   mtf_sync_score: float = 50.0,
                   # Engine 2 — Institutional volume (optional, safe default = neutral)
                   inst_score: float = 50.0,
                   # Engine 3 — Harmonics (optional)
                   harmonic_score: int = 0,
                   # Engine 5 — Candle structure (optional)
                   candle_score: int = 0,
                   # Engine 4 — Adaptive regime weights (None → use static _CAT_W)
                   regime_weights: dict | None = None) -> dict:

    W = regime_weights if regime_weights is not None else _CAT_W

    # TREND — MTF sync adds ±10 raw points (centred at 50)
    t = (40 if trend_up else 0) \
      + (20 if ema_stack else (10 if e_fast_gt_slow else 0)) \
      + (15 if htf_up else 0) \
      + (15 if market_bullish else 0) \
      + (10 if fresh_cross else 0)
    t = max(0.0, t + (mtf_sync_score - 50.0) / 50.0 * 10.0)
    cat_T = min(W["TREND"], t / 100 * W["TREND"])

    # MOMENTUM
    m = (40 if rsi>=70 else 35 if rsi>=65 else 25 if rsi>=60 else 18 if rsi>=55
         else 10 if rsi>=50 else 0 if rsi>=40 else -10)
    m += (25 if mom1>mom1_th else 12 if mom1>0 else -5)
    m += (20 if mom3>mom3_th else 10 if mom3>0 else 0)
    m += (15 if mom6>mom6_th else 5 if mom6>0 else 0)
    cat_M = min(W["MOMENTUM"], max(0.0, m) / 100 * W["MOMENTUM"])

    # STRUCTURE — harmonic patterns add up to +12 raw
    s = float(_PHASE_RAW.get(phase, 10))
    s += (20 if c_gt_hh else (10 if c_near_hh else 0))
    s += (20 if in_golden else 0)
    s += (-25 if near_e127 else (-35 if near_e161 else 0))
    s += (15 if rs_rank>=80 else (5 if rs_rank>=60 else (-10 if rs_rank<30 else 0)))
    s += harmonic_score * 0.15   # quality*0.8 → max ~64; ×0.15 → ≤9.6 raw pts
    cat_S = min(W["STRUCTURE"], max(0.0, s) / 120 * W["STRUCTURE"])

    # VOLUME — institutional score replaces static ADX-only centre
    v = 0.0
    if vol_avg_gt_zero:
        v += (50 if vol_ratio>=1.5 else 35 if vol_ratio>=1.2 else 20 if vol_ratio>=1.0 else -5)
    v += (35 if adx_val>=30 else 20 if adx_val>=20 else 8 if adx_val>=15 else -8)
    v += (inst_score - 50.0) / 50.0 * 15.0   # institutional: ±15 raw
    cat_V = min(W["VOLUME"], max(0.0, v) / 100 * W["VOLUME"])

    # QUALITY — candle structure adds ±10 raw points
    q = (25 if squeeze else 0) + (25 if vc_ratio<0.75 else (12 if vc_ratio<0.90 else 0))
    q += max(0.0, 40.0 + ext_penalty)
    q += candle_score   # −10 to +10
    cat_Q = min(W["QUALITY"], q / 100 * W["QUALITY"])

    raw = cat_T + cat_M + cat_S + cat_V + cat_Q
    if regime_bearish:
        raw *= 0.85
    return dict(norm_bull=round(min(100.0, max(0.0, raw)), 1),
                cat_T=round(cat_T,2), cat_M=round(cat_M,2),
                cat_S=round(cat_S,2), cat_V=round(cat_V,2), cat_Q=round(cat_Q,2))

# ══════════════════════════════════════════════════════════════════════════════
# CORE SCORING — v14 logic + SPEED-10 new indicators
# ══════════════════════════════════════════════════════════════════════════════

def score_stock(df, nifty_close, mode="Swing", daily_close=None,
                market_bullish=True, vix_val=None, min_liquidity_cr=LIQUIDITY_MIN_CR,
                sym=None, htf_up=True, rs_rank=50,
                phase_history_snapshot=None, mtf_prefetched=None):
    try:
        cfg   = MODE_CFG[mode]
        close = df["Close"]; volume = df["Volume"]; n = len(close)
        if n < 50: return None

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
        chg      = round(((c-prev)/prev)*100, 2)
        hh       = float(close.iloc[-11:-1].max())

        if len(df) >= 2:
            try:    delta_min = (df.index[1]-df.index[0]).total_seconds()/60
            except: delta_min = 1440
        else:
            delta_min = 1440

        if delta_min <= 5:     bars_per_day = 75
        elif delta_min <= 15:  bars_per_day = 25
        elif delta_min <= 30:  bars_per_day = 13
        elif delta_min < 240:  bars_per_day = 7
        else:                  bars_per_day = 1

        if mode == "Intraday" and bars_per_day > 1:
            vol_avg = _intraday_vol_avg(volume, bars_per_day)
        else:
            vol_avg = float(volume.rolling(20).mean().iloc[-1])

        v           = float(volume.iloc[-1])
        above_ema50 = c > float(ema(close, 50).iloc[-1])

        rs_raw = 0.0
        if n >= 6 and len(nifty_close) >= 6:
            rs_raw = ((c-float(close.iloc[-6]))/float(close.iloc[-6]) -
                      (float(nifty_close.iloc[-1])-float(nifty_close.iloc[-6]))/
                      float(nifty_close.iloc[-6]))*100

        trend_up     = (e200 is None or c > e200) and c > e_fast and e_fast > e_slow
        trend_down   = (e200 is None or c < e200) and c < e_fast and e_fast < e_slow
        trend_strong = c > e_fast and e_fast > e_slow
        ema_stack    = (e200 is not None) and (c > e200) and (e_fast > e_slow) and (e_fast > e200)

        fresh_cross = False
        if n >= 6 and e_fast > e_slow:
            lookback_cross = min(5, n-1)
            for k in range(1, lookback_cross+1):
                ef_curr = float(e_fast_s.iloc[-k]); es_curr = float(e_slow_s.iloc[-k])
                ef_prev = float(e_fast_s.iloc[-(k+1)]); es_prev = float(e_slow_s.iloc[-(k+1)])
                if ef_curr > es_curr and ef_prev <= es_prev:
                    fresh_cross = True; break

        ema_cross_bonus = 8 if fresh_cross else (4 if e_fast > e_slow else 0)

        mom_src = (daily_close if (mode=="Intraday" and daily_close is not None
                                    and len(daily_close)>=21) else close)
        mom_n   = len(mom_src)
        mom1 = (c-float(mom_src.iloc[-21]))  /float(mom_src.iloc[-21])*100  if mom_n>=21  else 0
        mom3 = (c-float(mom_src.iloc[-63]))  /float(mom_src.iloc[-63])*100  if mom_n>=63  else 0
        mom6 = (c-float(mom_src.iloc[-126])) /float(mom_src.iloc[-126])*100 if mom_n>=126 else 0
        strong_htf = mom1>cfg["mom1_th"] and mom3>cfg["mom3_th"] and mom6>cfg["mom6_th"]

        sw_hi, sw_lo, fib, fib_rng = fib_levels(df, lookback=30)
        prox      = atr_val*0.3
        in_golden = bool(fib and c>=fib["618"]-prox and c<=fib["500"]+prox)
        near_e127 = bool(fib and abs(c-fib["ext127"]) < prox)
        near_e161 = bool(fib and abs(c-fib["ext161"]) < prox)

        VDU_VOL_RATIO=0.70; VDU_RANGE_MULT=0.80
        vdu_vol_dry=False; vdu_coil=False
        if n >= 20 and vol_avg > 0:
            recent_vols = [float(volume.iloc[k]) for k in [-3,-2,-1]]
            vdu_vol_dry = all(vv < vol_avg*VDU_VOL_RATIO for vv in recent_vols)
        if n >= 5:
            recent_hi = float(df["High"].iloc[-5:].max())
            recent_lo = float(df["Low"].iloc[-5:].min())
            vdu_coil  = (recent_hi-recent_lo) < atr_val*VDU_RANGE_MULT
        vdu_setup  = bool(trend_up and vdu_vol_dry and vdu_coil)
        qualified  = strong_htf and trend_strong

        rsi_series = rsi(close, cfg["rsi_len"])
        ext_flags, ext_penalty, ext_labels, ext_n = detect_exhaustion(
            close=close, high=df["High"], low=df["Low"], volume=volume,
            rsi_series=rsi_series, e_fast_s=e_fast_s, atr_s=atr_s, atr_mean=atr_mean,
            c=c, v=v, vol_avg=vol_avg, mode=mode, vix_val=vix_val,
        )
        r = float(rsi_series.iloc[-1])

        # ── SPEED-10: NEW STAGE-B INDICATORS ──────────────────────────────
        adx_val   = _compute_adx(df)
        squeeze   = _compute_squeeze(df)
        vol_ratio = _compute_vol_contraction(df)

        # ── NEW ENGINES (v15.4) ────────────────────────────────────────────
        # Engine 4 first — its weights feed both category_score calls below
        regime_bearish = not market_bullish
        _regime_key, _regime_label, _regime_w = classify_regime(
            market_bullish, adx_val, vix_val)

        # Engine 2: institutional volume
        _inst = analyze_institutional_volume(df, mode)

        # Engine 3: harmonic / ABCD patterns
        _harm = detect_harmonic_patterns(df, mode)

        # Engine 5: candle structure
        _candle = detect_candle_structure(df, atr_val, mode)

        # Engine 1: MTF sync — inject base TF df so all three TFs are present
        _mtf_data = dict(mtf_prefetched or {})
        _base_tf   = MODE_CFG[mode]["interval"]
        if _base_tf not in _mtf_data:
            _mtf_data[_base_tf] = df
        _mtf = compute_mtf_sync(sym or "", mode, prefetched=_mtf_data)
        # ── FIX-C: category-based scoring — placeholder phase ──────────────
        _cat = category_score(
            trend_up       = trend_up,
            ema_stack      = ema_stack,
            fresh_cross    = fresh_cross,
            htf_up         = htf_up,
            market_bullish = market_bullish,
            e_fast_gt_slow = (e_fast > e_slow),
            rsi            = r,
            mom1=mom1, mom3=mom3, mom6=mom6,
            mom1_th=cfg["mom1_th"], mom3_th=cfg["mom3_th"], mom6_th=cfg["mom6_th"],
            phase          = PHASE_IDLE,        # placeholder; overwritten after detect_phase
            in_golden      = in_golden,
            near_e127      = near_e127,
            near_e161      = near_e161,
            norm_bull_raw  = 50.0,
            rs_rank        = rs_rank,
            c_gt_hh        = (c > hh),
            c_near_hh      = (c > hh*0.98),
            vol_ratio      = (v/vol_avg) if vol_avg > 0 else 1.0,
            vol_avg_gt_zero= vol_avg > 0,
            adx_val        = adx_val,
            squeeze        = squeeze,
            vc_ratio       = vol_ratio,
            ext_penalty    = ext_penalty,
            regime_bearish = regime_bearish,
            mtf_sync_score = _mtf["sync_score"],
            inst_score     = _inst["inst_score"],
            harmonic_score = _harm["harmonic_score"],
            candle_score   = _candle["candle_score"],
            regime_weights = _regime_w,
        )
        norm_bull = _cat["norm_bull"]
        raw_score = int(norm_bull)
        score_th  = float(cfg["score_th"])

        act           = action_label(norm_bull)
        vol_confirmed = v > vol_avg*1.2

        phase, entry_price, setup_type = detect_phase_and_entry(
            df, mode, c=c, e_fast_s=e_fast_s, e_slow_s=e_slow_s,
            atr_s=atr_s, atr_val=atr_val, atr_mean=atr_mean,
            v=v, vol_avg=vol_avg, fib=fib, sw_hi=sw_hi, sw_lo=sw_lo,
            in_golden=in_golden, near_e127=near_e127, near_e161=near_e161,
            norm_bull=norm_bull, trend_up=trend_up, trend_down=trend_down,
            trend_strong=trend_strong, score_th=score_th, vdu_setup=vdu_setup,
            htf_up=htf_up, regime_bearish=regime_bearish, vix_val=vix_val,
        )

        # Re-score with the real phase now known
        _cat2 = category_score(
            trend_up=trend_up, ema_stack=ema_stack, fresh_cross=fresh_cross,
            htf_up=htf_up, market_bullish=market_bullish, e_fast_gt_slow=(e_fast>e_slow),
            rsi=r, mom1=mom1, mom3=mom3, mom6=mom6,
            mom1_th=cfg["mom1_th"], mom3_th=cfg["mom3_th"], mom6_th=cfg["mom6_th"],
            phase=phase, in_golden=in_golden, near_e127=near_e127, near_e161=near_e161,
            norm_bull_raw=norm_bull, rs_rank=rs_rank,
            c_gt_hh=(c>hh), c_near_hh=(c>hh*0.98),
            vol_ratio=(v/vol_avg) if vol_avg>0 else 1.0,
            vol_avg_gt_zero=vol_avg>0, adx_val=adx_val, squeeze=squeeze,
            vc_ratio=vol_ratio, ext_penalty=ext_penalty, regime_bearish=regime_bearish,
            mtf_sync_score=_mtf["sync_score"],
            inst_score=_inst["inst_score"],
            harmonic_score=_harm["harmonic_score"],
            candle_score=_candle["candle_score"],
            regime_weights=_regime_w,
        )
        norm_bull = _cat2["norm_bull"]
        raw_score = int(norm_bull)

        # ADX gate: don't declare BREAKOUT if ADX weak (no trend strength)
        if phase == PHASE_BRK and adx_val < 18:
            phase = PHASE_ENTRY

        phase, _ = ext_phase_override(phase, ext_flags, ext_n, mode)
        act       = ext_action_cap(act, ext_n, vix_val)

        phase_bonus = 0
        if sym and phase_history_snapshot:
            history = phase_history_snapshot.get(sym, [])
            if len(history) >= 3:
                last3 = [h[1] for h in history[-3:]]
                progressions = [
                    [PHASE_SETUP,PHASE_ENTRY,PHASE_CONT],
                    [PHASE_ENTRY,PHASE_CONT,PHASE_BRK],
                    [PHASE_SETUP,PHASE_ENTRY,PHASE_BRK],
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

        mult=cfg["atr_mult"]; wide=cfg["atr_wide"]; closest=cfg["atr_max"]
        if setup_type == "fib" and fib:
            fib_sl = max(float(sw_lo), fib["618"]-atr_val*0.5)
            fib_sl = max(fib_sl, entry-atr_val*0.8)
            sl     = round(fib_sl, 2)
        elif setup_type == "breakout":
            sl = round(entry-atr_val*(1.5 if mode=="Intraday" else 2.0), 2)
        else:
            raw_sl     = entry-atr_val*mult
            furthest_sl= entry-atr_val*wide
            closest_sl = entry-atr_val*closest
            sl = round(max(furthest_sl, min(raw_sl,closest_sl)), 2)

        min_risk = atr_val*0.5
        if entry-sl < min_risk: sl = round(entry-min_risk, 2)

        t1,t2,t3,sl_exp = _compute_targets(entry,sl,atr_val,fib,setup_type,sw_hi,sw_lo,
                                            regime_bearish=regime_bearish, vix_val=vix_val)
        if sl_exp > 1.0: sl = round(entry-(entry-sl)*sl_exp, 2)

        return {
            "Score":       round(norm_bull,1), "RawBull":raw_score,
            "Action":      act, "Phase":phase, "Setup":setup_type,
            "Confidence":  confidence, "%Change":chg,
            "LTP":         ltp, "Entry":entry, "SL":sl,
            "T1":t1,"T2":t2,"T3":t3,
            "InGolden":    in_golden, "VDU":vdu_setup,
            "AboveEMA50":  above_ema50, "AvgTradedCr":avg_cr,
            "LiquidityOK": liq_ok, "RSI":round(r,1),
            "RS":          round(rs_raw,2), "RS_Rank":rs_rank,
            "ExtN":        ext_n, "ExtLabels":ext_labels,
            "ExtFlags":    ext_flags, "HTFUp":htf_up,
            "EMAStack":    ema_stack, "VolConf":vol_confirmed,
            "FreshCross":  fresh_cross, "ATR":round(atr_val,2),
            "ATR_Mean":    round(atr_mean,2), "PhaseBonus":phase_bonus,
            "BreadthGated":False, "Mom1":round(mom1,2), "Mom3":round(mom3,2),
            "TrendUp":     trend_up, "TrendDown":trend_down,
            # v15 speed-10
            "ADX":         round(adx_val,1), "Squeeze":squeeze,
            "VolRatio":    round(vol_ratio,2),
            # v15.3 category scores
            "CatT":_cat2["cat_T"],"CatM":_cat2["cat_M"],"CatS":_cat2["cat_S"],
            "CatV":_cat2["cat_V"],"CatQ":_cat2["cat_Q"],
            # v15.1/15.2 pattern keys — populated by enrich_with_patterns after Stage-B
            "Patterns":{},"VCP":False,"VCPGrade":"NONE","AVWAP":None,
            "AVWAPAbove":False,"FibQuality":0,"FibGrade":"POOR",
            "VolDryup":False,"VDUIntensity":0,"RVolPct":50.0,"RVolLabel":"NORMAL",
            "DarvasIn":False,"DarvasBrk":False,"DarvasTop":0.0,
            "_detected_phase": phase,
            # ── v15.4: Five new engines ───────────────────────────────────────
            # Engine 1 — MTF sync
            "MTFScore":   _mtf["sync_score"],
            "MTFLabel":   _mtf["mtf_label"],
            "MTFAligned": _mtf["aligned"],
            "MTFDiverge": _mtf["divergence"],
            "MTFTFScores":_mtf["tf_scores"],
            # Engine 2 — Institutional volume
            "InstScore":  _inst["inst_score"],
            "InstVerdict":_inst["verdict"],
            "InstLabel":  _inst["inst_label"],
            "InstEVR":    _inst["effort_vs_result"],
            "InstCMF":    _inst["cmf"],
            "InstOBV":    _inst["obv_trend"],
            "InstBlocks": _inst["block_days"],
            # Engine 3 — Harmonic / ABCD
            "HarmonicDetected": _harm["detected"],
            "HarmonicPattern":  _harm["pattern"],
            "HarmonicDir":      _harm["direction"],
            "HarmonicQuality":  _harm["quality"],
            "HarmonicZone":     _harm["completion_zone"],
            "HarmonicScore":    _harm["harmonic_score"],
            # Engine 4 — Adaptive regime
            "RegimeKey":    _regime_key,
            "RegimeLabel":  _regime_label,
            "RegimeWeights":_regime_w,
            # Engine 5 — Candle structure
            "CandleScore":  _candle["candle_score"],
            "CandleSignal": _candle["candle_signal"],
            "CandlePatterns":_candle["patterns"],
            "NR7":          _candle["nr7"],
            "InsideBar":    _candle["inside_bar"],
            # ── v15.5: Emerging Momentum Score (7-component leading indicator) ──
            **compute_emerging_score(df, mode, nifty_close, rs_rank),
            # ── v15.6: Pre-Confirmation Accumulation (7-signal buying-pressure layer) ──
            **compute_preconfirmation_accumulation(df, mode),
            # ── v15.7: Smart Money Behavior Model ────────────────────────────
            **compute_smart_money_model(
                df, mode,
                pca_score  = 0.0,     # filled post-hoc below
                inst_score = _inst["inst_score"],
                obv_trend  = _inst["obv_trend"],
            ),
            # ── v15.7: Accumulation Sequencing ───────────────────────────────
            **compute_accumulation_sequence(
                df, mode,
                pca_score            = 0.0,   # filled post-hoc below
                em_score             = 0.0,   # filled post-hoc below
                phase                = phase,
                smart_money_verdict  = "NEUTRAL",  # filled post-hoc below
                rs_line_high         = False,       # filled post-hoc below
            ),
            # ── v15.7: Microstructure Logic ───────────────────────────────────
            **compute_microstructure(df, mode),
            # ── v15.7: Relative Leadership Intelligence ───────────────────────
            **compute_rs_leadership(
                close            = close,
                nifty_close      = nifty_close,
                rs_rank          = rs_rank,
                sector_avg_score = 50.0,  # enriched in run_scan (like EmSectorMom)
                stock_score      = norm_bull,
            ),
        }
    except Exception:
        return None

# ══════════════════════════════════════════════════════════════════════════════
# BREADTH ENGINE (unchanged from v14)
# ══════════════════════════════════════════════════════════════════════════════

def compute_breadth(results):
    if not results: return {}
    total          = len(results)
    above_ema50    = sum(1 for r in results if r.get("AboveEMA50", False))
    breakout_count = sum(1 for r in results if r.get("Phase") == PHASE_BRK)
    advancing      = sum(1 for r in results if r.get("%Change", 0) > 0)
    declining      = sum(1 for r in results if r.get("%Change", 0) < 0)
    unchanged      = total-advancing-declining
    pct_above_ema50= round(above_ema50/total*100, 1)
    pct_breakout   = round(breakout_count/total*100, 1)
    ad_ratio       = round(advancing/max(declining,1), 2)
    pct_advancing  = round(advancing/total*100, 1)
    sector_scores  = {}; sector_counts = {}
    for r in results:
        sec = r.get("Sector", "Other")
        sector_scores[sec] = sector_scores.get(sec,0)+r.get("Score",0)
        sector_counts[sec] = sector_counts.get(sec,0)+1
    sector_avg = {sec:round(sector_scores[sec]/sector_counts[sec],1) for sec in sector_scores}
    liquid_count = sum(1 for r in results if r.get("LiquidityOK", True))
    return {
        "total":total,"above_ema50":above_ema50,"pct_above_ema50":pct_above_ema50,
        "breakout_count":breakout_count,"pct_breakout":pct_breakout,
        "advancing":advancing,"declining":declining,"unchanged":unchanged,
        "ad_ratio":ad_ratio,"pct_advancing":pct_advancing,
        "sector_avg":sector_avg,"liquid_count":liquid_count,
        "breadth_signal":_breadth_signal(pct_above_ema50,ad_ratio,pct_breakout),
    }

def _breadth_signal(pct_ema50, ad_ratio, pct_brk):
    score = 0
    if pct_ema50 >= 70: score += 2
    elif pct_ema50 >= 50: score += 1
    if ad_ratio >= 2.0: score += 2
    elif ad_ratio >= 1.2: score += 1
    if pct_brk >= 5: score += 1
    if score >= 4: return "STRONG","#2ecc71"
    if score >= 2: return "NEUTRAL","#f39c12"
    return "WEAK","#e74c3c"

# ══════════════════════════════════════════════════════════════════════════════
# DB / SUPABASE (unchanged)
# ══════════════════════════════════════════════════════════════════════════════

def _db_conn():
    if not _DB_OK: raise RuntimeError("psycopg2 not installed")
    url = st.secrets.get("SUPABASE_URL","")
    if not url or not url.startswith(("postgres://","postgresql://")):
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
        # FIX-6: atomic save — insert first, then trim old rows in one transaction
        # This prevents data loss if the process crashes between a DELETE and INSERT.
        cur.execute(
            f"INSERT INTO {table} (data) VALUES (%s)",
            [json.dumps(payload)]
        )
        cur.execute(
            f"""DELETE FROM {table}
                WHERE id NOT IN (
                    SELECT id FROM {table} ORDER BY ts DESC LIMIT 1
                )"""
        )
        conn.commit(); cur.close(); conn.close()
        st.session_state["_db_error"] = None
    except Exception as e:
        st.session_state["_db_error"] = str(e)

def _db_load(table):
    try:
        conn=_db_conn(); cur=conn.cursor()
        _db_ensure(cur); conn.commit()
        cur.execute(f"SELECT data FROM {table} ORDER BY ts DESC LIMIT 1")
        row=cur.fetchone(); cur.close(); conn.close()
        if row and row[0]:
            return row[0] if isinstance(row[0],list) else json.loads(row[0])
    except Exception:
        pass
    return []

# ══════════════════════════════════════════════════════════════════════════════
# RUN SCAN — v15: two-stage + incremental + async HTTP
# ══════════════════════════════════════════════════════════════════════════════

def run_scan(symbols, mode, progress_bar, status_text,
             vix_val=None, min_liq_cr=LIQUIDITY_MIN_CR):

    cfg      = MODE_CFG[mode]
    min_bars = cfg["hist_min_bars"]
    total    = len(symbols)

    nifty          = fetch_nifty(mode)
    market_bullish, regime_label = _market_regime(nifty)

    if not market_bullish:
        st.warning(
            f"⚠️ **Market Regime: {regime_label}** — EMA20 below EMA50. "
            "Scores haircut 15%. Targets compressed."
        )

    # ── SPEED-3: incremental batch fetch ──────────────────────────────────
    cold  = _cold_start_needed(mode)
    status_text.text(
        f"{'🌅 Cold-start: full fetch' if cold else '⚡ Incremental: live tail'} "
        f"for {total} symbols…"
    )
    progress_bar.progress(0.05)

    data = batch_incremental_fetch(
        symbols, mode, force_full=cold,
        progress_cb=lambda p: progress_bar.progress(0.05 + p*0.30),
    )

    if cold:
        _mark_cold_start_done(mode)

    progress_bar.progress(0.35)

    # ── SPEED-2: Stage-A pre-filter ────────────────────────────────────────
    status_text.text("⚡ Stage-A: fast EMA pre-filter…")
    valid_data  = {s: df for s,df in data.items()
                   if df is not None and not df.empty and len(df) >= min_bars}
    survivors   = stage_a_prefilter(valid_data, mode, min_bars=min_bars)
    rejected    = total - len(survivors)

    progress_bar.progress(0.40)
    status_text.text(f"Stage-A: {len(survivors)}/{total} survive "
                     f"({rejected} filtered) → Stage-B…")

    # ── HTF pre-fetch (survivors only — much smaller set) ─────────────────
    htf_map = prefetch_htf_parallel(survivors, mode, status_text, progress_bar)
    progress_bar.progress(0.55)

    # ── MTF pre-fetch (Engine 1 — secondary/tertiary TFs for survivors) ───
    status_text.text("📊 Multi-timeframe data for survivors…")
    mtf_prefetched = prefetch_mtf_parallel(survivors, mode)
    progress_bar.progress(0.57)

    # ── RS ranks ──────────────────────────────────────────────────────────
    sym_52w_returns = {sym: _52w_return(valid_data[sym]["Close"])
                       for sym in survivors if sym in valid_data}
    rs_rank_map     = compute_rs_ranks(sym_52w_returns)

    phase_history_snapshot = dict(st.session_state.get("phase_history", {}))

    # ── SPEED-2: Stage-B full scoring ─────────────────────────────────────
    status_text.text(f"🔬 Stage-B: full scoring {len(survivors)} survivors…")
    results     = []
    liq_skipped = 0
    n_surv      = len(survivors)
    scored      = 0

    # Fetch daily context for Intraday survivors
    daily_closes: dict = {}
    if mode == "Intraday" and survivors:
        daily_cfg = MODE_CFG["Swing"]
        d_raw     = fetch_async(survivors, daily_cfg["yf_period"],
                                daily_cfg["interval"], concurrency=64)
        for sym, df in d_raw.items():
            if df is not None and not df.empty:
                daily_closes[sym] = df["Close"]

    def _score_one(sym):
        df        = valid_data[sym]
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
            mtf_prefetched         = mtf_prefetched.get(sym, {}),
        )

    with concurrent.futures.ThreadPoolExecutor(max_workers=min(32, n_surv)) as pool:
        futures = {pool.submit(_score_one, sym): sym for sym in survivors}
        for fut in concurrent.futures.as_completed(futures):
            sym, res = fut.result()
            scored  += 1
            progress_bar.progress(0.55 + scored/max(n_surv,1)*0.40)
            if scored % 20 == 0:
                status_text.text(f"Stage-B: scored {scored}/{n_surv}…")
            if res:
                res["Regime"] = regime_label
                res["Symbol"] = sym
                res["Sector"] = SECTOR_MAP.get(sym, "Other")
                if not res["LiquidityOK"]:
                    liq_skipped += 1
                results.append(res)

    for res in results:
        sym   = res["Symbol"]
        phase = res["_detected_phase"]
        record_phase_transition(sym, phase)
        res["PhaseBonus"] = phase_transition_conf_bonus(sym)

    # FIX-B: pattern enrichment — runs only on shortlisted stocks
    status_text.text("🔬 Pattern enrichment on shortlisted stocks…")
    results = enrich_with_patterns(
        results, data=valid_data, mode=mode, market_open=_is_market_open()
    )

    breadth_pulse = compute_breadth(results)
    pct_ema50_now = breadth_pulse.get("pct_above_ema50", 100)
    ad_ratio_now  = breadth_pulse.get("ad_ratio", 2.0)

    # ── v15.5: Enrich Emerging Scores with sector momentum ────────────────
    _sec_avg   = breadth_pulse.get("sector_avg", {})
    _ovl_avg   = float(np.mean(list(_sec_avg.values()))) if _sec_avg else 50.0
    for _res in results:
        _sb = 0.0
        if _sec_avg:
            _sa = _sec_avg.get(_res.get("Sector", "Other"), _ovl_avg)
            if   _sa >= _ovl_avg + 10: _sb = 10.0
            elif _sa >= _ovl_avg + 5:  _sb = 7.0
            elif _sa >= _ovl_avg:      _sb = 4.0
            elif _sa >= _ovl_avg - 5:  _sb = 2.0
        _res["EmSectorMom"] = round(_sb, 1)
        _em_total = round(min(100.0, _res.get("EmScore", 0) + _sb), 1)
        _res["EmScore"] = _em_total
        _res["EmLabel"] = ("IGNITING" if _em_total >= 65 else "BUILDING" if _em_total >= 50
                           else "COILING" if _em_total >= 35 else "LATENT" if _em_total >= 20
                           else "QUIET")
    # ─────────────────────────────────────────────────────────────────────────

    # ── v15.7: Post-hoc cross-field enrichment ────────────────────────────
    # Now that PCA, Em, AccumSeq, SmartMoney are all computed, fill the
    # fields that depend on each other (circular dependencies resolved here).
    _sec_avg_2 = breadth_pulse.get("sector_avg", {})
    _ovl_avg_2 = float(np.mean(list(_sec_avg_2.values()))) if _sec_avg_2 else 50.0

    for _res in results:
        _pca  = _res.get("PCAScore", 0.0)
        _em   = _res.get("EmScore",  0.0)
        _ph   = _res.get("Phase",    PHASE_IDLE)
        _sec  = _res.get("Sector",   "Other")
        _sec_score = _sec_avg_2.get(_sec, _ovl_avg_2)

        # ── Re-compute SmartMoney with real PCA score ──────────────────────
        _sm = compute_smart_money_model(
            valid_data.get(_res.get("Symbol",""), pd.DataFrame()),
            mode,
            pca_score  = _pca,
            inst_score = _res.get("InstScore", 50.0),
            obv_trend  = _res.get("InstOBV",   True),
        )
        _res.update(_sm)

        # ── Re-compute AccumSequence with real PCA + Em + SmartMoney ──────
        _rl_high = _res.get("RSLineHigh", False)
        _as = compute_accumulation_sequence(
            valid_data.get(_res.get("Symbol",""), pd.DataFrame()),
            mode,
            pca_score           = _pca,
            em_score            = _em,
            phase               = _ph,
            smart_money_verdict = _res.get("SmartMoneyVerdict", "NEUTRAL"),
            rs_line_high        = _rl_high,
        )
        _res.update(_as)

        # ── Re-compute RSLeadership with real sector avg ───────────────────
        _close_ser = (valid_data[_res["Symbol"]]["Close"]
                      if _res.get("Symbol") in valid_data else pd.Series(dtype=float))
        _rl = compute_rs_leadership(
            close            = _close_ser,
            nifty_close      = nifty,
            rs_rank          = _res.get("RS_Rank", 50),
            sector_avg_score = _sec_score,
            stock_score      = _res.get("Score", 50.0),
        )
        _res.update(_rl)

        # ── GAP-5: Apply PRE-CONFIRM action tier ──────────────────────────
        _cur_action = _res.get("Action", "SKIP")
        if _cur_action not in ("STRONG BUY", "BUY"):   # don't downgrade confirmed signals
            _pc_action = action_label_with_preconfirm(
                norm_score           = _res.get("Score", 0.0),
                pca_score            = _pca,
                em_score             = _em,
                phase                = _ph,
                smart_money_verdict  = _res.get("SmartMoneyVerdict", "NEUTRAL"),
                accum_stage          = _res.get("AccumStage", "NONE"),
            )
            _res["Action"] = _pc_action

    breadth_weak  = (pct_ema50_now < 40) and (ad_ratio_now < 0.8)

    if breadth_weak:
        gated_count = 0
        for res in results:
            if res.get("Phase") in (PHASE_BRK, PHASE_CONT):
                if res["Action"] in ("STRONG BUY","BUY"):
                    res["Action"]       = "WATCH"
                    res["BreadthGated"] = True
                    gated_count        += 1
            # v15.7: PRE-CONFIRM is never breadth-gated — these stocks haven't
            # confirmed yet, so breadth doesn't apply to them.
            # (PRE-CONFIRM only fires on SETUP/IDLE phase anyway)
        if gated_count:
            st.warning(
                f"⚠️ **Breadth Gate active** — only {pct_ema50_now}% above EMA50, "
                f"A/D ratio {ad_ratio_now:.2f}. "
                f"{gated_count} BREAKOUT/CONT signals capped to WATCH."
            )

    progress_bar.progress(1.0)
    results.sort(key=lambda x: x["Score"], reverse=True)
    return results, rejected, liq_skipped

# ══════════════════════════════════════════════════════════════════════════════
# SHORT SELL ENGINE (unchanged logic, uses new fetch path)
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class ShortResult:
    symbol:str; verdict:str=SHORT_SKIP; short_score:int=0
    hard_triggers:list=field(default_factory=list)
    soft_triggers:list=field(default_factory=list)
    entry_zone_lo:float=0.0; entry_zone_hi:float=0.0
    stop_loss:float=0.0; target1:float=0.0; target2:float=0.0; target3:float=0.0
    risk_reward:float=0.0; current_price:float=0.0; atr:float=0.0
    rsi_val:float=50.0; volume_ratio:float=1.0; rs_rank:int=50
    htf_trend:str="HTF-UNKNOWN"; phase:str=PHASE_IDLE; ext_n:int=0
    sector:str="—"; mode:str="Swing"
    scanned_at:str=field(default_factory=lambda: datetime.now().isoformat())
    error:str=""; day_change:float=0.0

def score_short(sym:str, mode:str="Swing", htf_cache:dict=None,
                rs_ranks:dict=None, vix_val:float=None,
                prefetched_df:pd.DataFrame=None) -> "ShortResult":
    result = ShortResult(symbol=sym, mode=mode, sector=SECTOR_MAP.get(sym,"—"))
    cfg    = MODE_CFG[mode]
    try:
        df = prefetched_df.copy() if (prefetched_df is not None and not prefetched_df.empty) else pd.DataFrame()
        if df.empty:
            raw = fetch_async([sym], cfg["yf_period"], cfg["interval"], concurrency=1)
            df  = raw.get(sym, pd.DataFrame())
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df = df.dropna(subset=["Close"])
        if len(df) < 60: result.error="insufficient data"; return result

        cl=df["Close"]; hi=df["High"]; lo=df["Low"]; vol=df["Volume"]
        close=float(cl.iloc[-1]); result.current_price=close
        ef_ser=ema(cl,cfg["ema_fast"]); es_ser=ema(cl,cfg["ema_slow"])
        ef=float(ef_ser.iloc[-1]); es=float(es_ser.iloc[-1])
        atr_s=atr_series(df); atr_v=float(atr_s.iloc[-1])
        atr_mean=float(atr_s.rolling(20).mean().iloc[-1]); result.atr=atr_v
        rsi_ser=rsi(cl,cfg["rsi_len"]); rsi_v=float(rsi_ser.iloc[-1])
        result.rsi_val=round(rsi_v,1)
        avg_vol=float(vol.rolling(20).mean().iloc[-1]) or 1
        result.volume_ratio=round(float(vol.iloc[-1])/avg_vol,2)
        def _ret(n):
            if len(cl)<=n: return 0.0
            return float((cl.iloc[-1]-cl.iloc[-n])/cl.iloc[-n]*100)
        mom1=_ret(22); mom3=_ret(66)
        w52_lo=float(lo.iloc[-252:].min()) if len(lo)>=252 else float(lo.min())
        prior_swing_lo=float(lo.iloc[-21:-1].min()) if len(lo)>21 else float(lo.min())
        rsi_5_ago=float(rsi_ser.iloc[-6]) if len(rsi_ser)>=6 else rsi_v
        ticker=to_nse(sym)
        if htf_cache and sym in htf_cache:
            htf_up,htf_label=htf_cache[sym]
        else:
            htf_df=_fetch_htf_cached(ticker,cfg["htf_period"],cfg["htf_interval"])
            htf_up,htf_label=_htf_trend_from_df(htf_df,mode)
        result.htf_trend=htf_label
        rs_rank=rs_ranks.get(sym,50) if rs_ranks else 50; result.rs_rank=rs_rank
        trend_down=close<ef and ef<es; trend_up=close>ef and ef>es
        if trend_down:          phase=PHASE_EXIT
        elif trend_up:          phase=PHASE_CONT if mom1>0 else PHASE_ENTRY
        elif close>ef and ef<es: phase=PHASE_SETUP
        else:                   phase=PHASE_IDLE
        result.phase=phase
        ext_flags,_,_,ext_n=detect_exhaustion(
            close=cl,high=hi,low=lo,volume=vol,rsi_series=rsi_ser,
            e_fast_s=ef_ser,atr_s=atr_s,atr_mean=atr_mean,
            c=close,v=float(vol.iloc[-1]),vol_avg=avg_vol,mode=mode,vix_val=vix_val)
        result.ext_n=ext_n
        score=0; hard_t=[]; soft_t=[]
        if close<ef and ef<es: score+=SHORT_HARD_WEIGHT; hard_t.append("Bearish EMA Stack")
        for i in range(1,min(5,len(ef_ser)-1)+1):
            if (float(ef_ser.iloc[-i])<float(es_ser.iloc[-i]) and
                    float(ef_ser.iloc[-(i+1)])>=float(es_ser.iloc[-(i+1)])):
                score+=SHORT_HARD_WEIGHT; hard_t.append("Death Cross (EMA ×)"); break
        if not htf_up: score+=SHORT_HARD_WEIGHT; hard_t.append(f"HTF Downtrend ({htf_label})")
        near_52w_lo=(close-w52_lo)/w52_lo<0.03 if w52_lo>0 else False
        below_swing=close<prior_swing_lo
        if near_52w_lo or below_swing:
            score+=SHORT_HARD_WEIGHT
            hard_t.append("Near 52W Low" if near_52w_lo else "Below Swing Low")
        if rsi_5_ago>68 and rsi_v<rsi_5_ago-5:
            score+=SHORT_SOFT_WEIGHT; soft_t.append(f"RSI Rollover ({rsi_5_ago:.0f}→{rsi_v:.0f})")
        if rsi_v<42 and not htf_up: score+=SHORT_SOFT_WEIGHT; soft_t.append(f"RSI Bearish Zone ({rsi_v:.0f})")
        if mom1<-cfg["mom1_th"]: score+=SHORT_SOFT_WEIGHT; soft_t.append(f"Neg 1M Mom ({mom1:.1f}%)")
        if mom3<-cfg["mom3_th"]: score+=SHORT_SOFT_WEIGHT; soft_t.append(f"Neg 3M Mom ({mom3:.1f}%)")
        if float(df["Close"].iloc[-1])<float(df["Open"].iloc[-1]) and result.volume_ratio>1.5:
            score+=SHORT_SOFT_WEIGHT; soft_t.append(f"High-Vol Red Day ({result.volume_ratio:.1f}×)")
        _,_,fibs,_=fib_levels(df)
        if fibs:
            if close<fibs.get("618",float("inf")): score+=SHORT_SOFT_WEIGHT; soft_t.append("Below 61.8% Fib")
            elif close<fibs.get("500",float("inf")): score+=SHORT_SOFT_WEIGHT; soft_t.append("Below 50% Fib")
        if rs_rank<30: score+=SHORT_SOFT_WEIGHT; soft_t.append(f"RS Rank Weak ({rs_rank})")
        if vix_val and vix_val>=VIX_STRESS: score+=5
        if ext_n>=2: score+=min(ext_n*4,12)
        result.short_score=min(score,100); result.hard_triggers=hard_t; result.soft_triggers=soft_t
        if score>=SHORT_SCORE_CONFIRMED: result.verdict=SHORT_CONFIRMED
        elif score>=SHORT_SCORE_SIGNAL:  result.verdict=SHORT_SIGNAL
        elif score>=SHORT_SCORE_WATCH:   result.verdict=SHORT_WATCH
        else:                            result.verdict=SHORT_SKIP
        atr_sl_mult=cfg["atr_mult"]*(0.85 if vix_val and vix_val>=VIX_STRESS else 1.0)
        result.entry_zone_lo=round(close,2); result.entry_zone_hi=round(close+atr_v*0.4,2)
        result.stop_loss=round(close+atr_v*atr_sl_mult,2)
        result.target1=round(close-atr_v*cfg["atr_mult"]*1.0,2)
        result.target2=round(close-atr_v*cfg["atr_mult"]*2.0,2)
        result.target3=round(close-atr_v*cfg["atr_mult"]*3.0,2)
        risk=result.stop_loss-close
        result.risk_reward=round((close-result.target2)/risk,2) if risk>0 else 0.0
    except Exception as e:
        result.error=str(e)
    return result

def run_short_scan(symbols,mode,htf_cache=None,rs_ranks=None,
                   vix_val=None,status_text=None,progress_bar=None) -> list:
    total=len(symbols); results=[]; done=0; cfg=MODE_CFG[mode]
    if status_text: status_text.text("Short scan 1/2: Async OHLCV fetch…")
    prefetched = fetch_async(symbols, cfg["yf_period"], cfg["interval"], concurrency=64)
    if progress_bar: progress_bar.progress(0.50)
    if status_text: status_text.text("Short scan 2/2: Scoring…")
    def _one(sym):
        return score_short(sym,mode,htf_cache=htf_cache,rs_ranks=rs_ranks,
                           vix_val=vix_val,prefetched_df=prefetched.get(sym))
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(32,total)) as pool:
        futures={pool.submit(_one,sym):sym for sym in symbols}
        for fut in concurrent.futures.as_completed(futures):
            results.append(fut.result()); done+=1
            if progress_bar: progress_bar.progress(0.50+done/total*0.50)
            if status_text and done%20==0: status_text.text(f"Short scan {done}/{total}…")
    results.sort(key=lambda r:r.short_score,reverse=True)
    return [r for r in results if r.verdict!=SHORT_SKIP and not r.error]

def score_short_from_result(r:dict, mode:str, vix_val:float=None) -> ShortResult:
    sym=r.get("Symbol","")
    result=ShortResult(symbol=sym,mode=mode,sector=r.get("Sector",SECTOR_MAP.get(sym,"—")))
    cfg=MODE_CFG[mode]
    try:
        close=float(r.get("LTP",0))
        if close<=0: result.error="no price"; return result
        atr_v=float(r.get("ATR",0)); rsi_v=float(r.get("RSI",50))
        rs_rank=int(r.get("RS_Rank",50)); ext_n=int(r.get("ExtN",0))
        ext_flags=r.get("ExtFlags",{}); htf_up=bool(r.get("HTFUp",True))
        htf_label="HTF↑" if htf_up else "HTF↓"
        ema_stack=bool(r.get("EMAStack",False)); trend_down=bool(r.get("TrendDown",False))
        trend_up=bool(r.get("TrendUp",False)); fresh_cross=bool(r.get("FreshCross",False))
        mom1=float(r.get("Mom1",0)); mom3=float(r.get("Mom3",0))
        vol_conf=bool(r.get("VolConf",False)); phase=r.get("Phase",PHASE_IDLE)
        chg=float(r.get("%Change",0))
        result.current_price=close; result.atr=atr_v; result.rsi_val=round(rsi_v,1)
        result.rs_rank=rs_rank; result.htf_trend=htf_label; result.phase=phase
        result.ext_n=ext_n; result.day_change=chg
        result.volume_ratio=1.3 if vol_conf else 0.9
        score=0; hard_t=[]; soft_t=[]
        if trend_down: score+=SHORT_HARD_WEIGHT; hard_t.append("Bearish EMA Stack")
        if not ema_stack and not htf_up and not fresh_cross and not trend_up:
            score+=SHORT_HARD_WEIGHT; hard_t.append("Bearish EMA Alignment (no golden cross)")
        if not htf_up: score+=SHORT_HARD_WEIGHT; hard_t.append(f"HTF Downtrend ({htf_label})")
        if phase==PHASE_EXIT: score+=SHORT_HARD_WEIGHT; hard_t.append("Phase EXIT (structural downtrend)")
        if ext_flags.get("rsi_overheat") or ext_flags.get("mom_exhaustion"):
            score+=SHORT_SOFT_WEIGHT; soft_t.append("RSI/Mom Exhaustion (ExtFlag)")
        if rsi_v<42 and not htf_up: score+=SHORT_SOFT_WEIGHT; soft_t.append(f"RSI Bearish Zone ({rsi_v:.0f})")
        if mom1<-cfg["mom1_th"]: score+=SHORT_SOFT_WEIGHT; soft_t.append(f"Neg 1M Mom ({mom1:.1f}%)")
        if mom3<-cfg["mom3_th"]: score+=SHORT_SOFT_WEIGHT; soft_t.append(f"Neg 3M Mom ({mom3:.1f}%)")
        if chg<-0.5 and vol_conf: score+=SHORT_SOFT_WEIGHT; soft_t.append(f"High-Vol Red Day ({chg:+.1f}%)")
        if ext_flags.get("bearish_div"): score+=SHORT_SOFT_WEIGHT; soft_t.append("Bearish Divergence (ExtFlag)")
        if rs_rank<30: score+=SHORT_SOFT_WEIGHT; soft_t.append(f"RS Rank Weak ({rs_rank})")
        if vix_val and vix_val>=VIX_STRESS: score+=5
        if ext_n>=2: score+=min(ext_n*4,12)
        result.short_score=min(score,100); result.hard_triggers=hard_t; result.soft_triggers=soft_t
        if score>=SHORT_SCORE_CONFIRMED: result.verdict=SHORT_CONFIRMED
        elif score>=SHORT_SCORE_SIGNAL:  result.verdict=SHORT_SIGNAL
        elif score>=SHORT_SCORE_WATCH:   result.verdict=SHORT_WATCH
        else:                            result.verdict=SHORT_SKIP
        if atr_v>0:
            atr_sl_mult=cfg["atr_mult"]*(0.85 if vix_val and vix_val>=VIX_STRESS else 1.0)
            result.entry_zone_lo=round(close,2); result.entry_zone_hi=round(close+atr_v*0.4,2)
            result.stop_loss=round(close+atr_v*atr_sl_mult,2)
            result.target1=round(close-atr_v*cfg["atr_mult"]*1.0,2)
            result.target2=round(close-atr_v*cfg["atr_mult"]*2.0,2)
            result.target3=round(close-atr_v*cfg["atr_mult"]*3.0,2)
            risk=result.stop_loss-close
            result.risk_reward=round((close-result.target2)/risk,2) if risk>0 else 0.0
    except Exception as e:
        result.error=str(e)
    return result

def derive_short_candidates(scan_results:list, mode:str, vix_val:float=None) -> list:
    out=[]
    for r in scan_results:
        if not r: continue
        sr=score_short_from_result(r,mode,vix_val)
        if sr.verdict!=SHORT_SKIP and not sr.error: out.append(sr)
    out.sort(key=lambda s:s.short_score,reverse=True)
    return out

# ══════════════════════════════════════════════════════════════════════════════
# EXIT ENGINE (unchanged)
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class ExitResult:
    symbol:str; verdict:str=EXIT_HOLD; exit_score:int=0
    triggers:list=field(default_factory=list)
    trailing_stop:float=None; current_price:float=0.0
    atr:float=0.0; day_pct:float=0.0; error:str=""

def score_exit(sym:str, entry_price:float, mode:str="Swing", vix_val:float=None) -> ExitResult:
    result=ExitResult(symbol=sym); cfg=MODE_CFG[mode]
    try:
        raw=fetch_async([sym],cfg["yf_period"],cfg["interval"],concurrency=1)
        df=raw.get(sym,pd.DataFrame())
        if df.empty:
            import yfinance as yf
            df=yf.download(to_nse(sym),period=cfg["period"],interval=cfg["interval"],
                           auto_adjust=True,progress=False,threads=False)
            if isinstance(df.columns,pd.MultiIndex): df.columns=df.columns.get_level_values(0)
            df=df.dropna()
        if len(df)<30: result.error="insufficient data"; return result
        cl=df["Close"]; close=float(cl.iloc[-1]); result.current_price=close
        atr_v=float(atr_series(df).iloc[-1]); result.atr=atr_v
        if len(cl)>=2:
            result.day_pct=round((close-float(cl.iloc[-2]))/float(cl.iloc[-2])*100,2)
        ef=float(ema(cl,cfg["ema_fast"]).iloc[-1]); es=float(ema(cl,cfg["ema_slow"]).iloc[-1])
        rsi_v=float(rsi(cl,cfg["rsi_len"]).iloc[-1])
        avg_vol=float(df["Volume"].rolling(20).mean().iloc[-1]) or 1
        vol_ratio=float(df["Volume"].iloc[-1])/avg_vol
        pnl_pct=(close-entry_price)/entry_price*100 if entry_price else 0
        base_mult=2.0
        if vix_val and vix_val>=VIX_STRESS:    base_mult=1.5
        elif vix_val and vix_val>=VIX_CAUTION: base_mult=1.75
        if pnl_pct>=20: base_mult*=0.7
        elif pnl_pct>=10: base_mult*=0.85
        result.trailing_stop=round(close-atr_v*base_mult,2)
        score=0; triggers=[]
        if close<ef:  score+=25; triggers.append("Price < Fast EMA")
        if close<es:  score+=25; triggers.append("Price < Slow EMA")
        if rsi_v>78:  score+=25; triggers.append(f"RSI Overbought {rsi_v:.0f}")
        if pnl_pct<-8: score+=25; triggers.append(f"SL Hit {pnl_pct:.1f}%")
        if ef<es:     score+=10; triggers.append("EMA Bear Cross")
        if rsi_v>70:  score+=10; triggers.append(f"RSI High {rsi_v:.0f}")
        if vol_ratio>2.0 and float(df["Close"].iloc[-1])<float(df["Open"].iloc[-1]):
            score+=10; triggers.append("High-Vol Down Day")
        if pnl_pct>30: score+=10; triggers.append(f"Big Profit {pnl_pct:.1f}% — Lock In")
        if vix_val and vix_val>=VIX_STRESS: score+=10; triggers.append(f"VIX Stress {vix_val}")
        _,_,fibs,_=fib_levels(df)
        if fibs and close<fibs.get("618",0): score+=10; triggers.append("Below 61.8% Fib")
        htf_df=_fetch_htf_cached(to_nse(sym),cfg["htf_period"],cfg["htf_interval"])
        htf_up,_=_htf_trend_from_df(htf_df,mode)
        if not htf_up: score+=10; triggers.append("HTF Downtrend")
        result.exit_score=min(score,100); result.triggers=triggers
        if score>=65:   result.verdict=EXIT_CONFIRM_LBL
        elif score>=40: result.verdict=EXIT_SIGNAL_LBL
        elif score>=20: result.verdict=EXIT_WATCH_LBL
        else:           result.verdict=EXIT_HOLD
    except Exception as e:
        result.error=str(e)
    return result

def run_exit_scan(positions:list, vix_val:float=None) -> dict:
    out={}
    valid=[p for p in positions if isinstance(p,dict) and p.get("symbol")]
    if not valid: return out
    def _one(pos):
        sym=pos["symbol"]
        return sym,score_exit(sym,pos.get("entry_price",0),pos.get("mode","Swing"),vix_val)
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(16,len(valid))) as pool:
        futures={pool.submit(_one,pos):pos for pos in valid}
        for fut in concurrent.futures.as_completed(futures):
            try:
                sym,er=fut.result(); out[sym]=er
            except Exception as e:
                pos=futures[fut]; sym=pos.get("symbol","?")
                out[sym]=ExitResult(symbol=sym,error=str(e))
    return out

def add_position(sym:str, entry_price:float, qty:int, mode:str, entry_date:str=None):
    pos=dict(symbol=sym.upper(),entry_price=entry_price,qty=qty,mode=mode,
             entry_date=entry_date or datetime.now().date().isoformat(),current_price=entry_price)
    # FIX-7: deduplicate on (symbol, entry_date, entry_price) so different-price
    # lots entered on the same day are preserved separately.
    existing=[p for p in st.session_state.get("open_positions",[])
              if not (p["symbol"]==sym.upper()
                      and p["entry_date"]==pos["entry_date"]
                      and p["entry_price"]==entry_price)]
    st.session_state["open_positions"]=existing+[pos]
    _db_save("bs_positions",st.session_state["open_positions"])

# ══════════════════════════════════════════════════════════════════════════════
# CARD STYLE HELPERS (unchanged from v14.3)
# ══════════════════════════════════════════════════════════════════════════════

def _action_colors(act):
    if act=="STRONG BUY": return "#f59e0b22","#f59e0b88","#f59e0b"
    if act=="BUY":        return "#22c55e1a","#22c55e66","#22c55e"
    if act=="PRE-CONFIRM":return "#8b5cf622","#8b5cf688","#a78bfa"   # v15.7
    if act=="WATCH":      return "#3b82f611","#3b82f644","#60a5fa"
    return "#cbd5e111","#cbd5e133","#cbd5e1"

def _phase_color(ph):
    return {"BREAKOUT":"#00dd88","CONT":"#22aa55","ENTRY":"#2255cc",
            "SETUP":"#b87333","IDLE":"#555577","EXIT":"#cc4444"}.get(ph,"#555577")

def _trend_color(up:bool): return "#22c55e" if up else "#ef4444"

def _rs_color(rank:int):
    if rank>=80: return "#22c55e"
    if rank>=60: return "#d97706"
    return "#94a3b8"

def _conf_color(conf:int):
    if conf>=80: return "#2ecc71"
    if conf>=60: return "#f39c12"
    if conf>=40: return "#e67e22"
    return "#e74c3c"

# ══════════════════════════════════════════════════════════════════════════════
# SPEED-8: CARD HASH for render guard
# ══════════════════════════════════════════════════════════════════════════════

def _result_hash(r: dict) -> str:
    """Stable short hash of a result dict for Streamlit key uniqueness."""
    key_fields = (r.get("Symbol",""), r.get("Score",0), r.get("Phase",""),
                  r.get("Action",""), r.get("LTP",0), r.get("Confidence",0))
    return hashlib.md5(str(key_fields).encode()).hexdigest()[:8]

# ══════════════════════════════════════════════════════════════════════════════
# v15.8-FIX: EARNINGS DATE WARNING
# ══════════════════════════════════════════════════════════════════════════════

@st.cache_data(ttl=3600, show_spinner=False)
def get_earnings_dates(symbols: list) -> dict:
    """
    Returns {symbol: "DD Mon"} for stocks with earnings in the next 14 days.
    Best-effort — silent on any failure. Uses yfinance calendar.
    """
    import yfinance as yf
    from datetime import date as _date, timedelta as _td
    upcoming: dict = {}
    today   = _date.today()
    horizon = today + _td(days=14)
    for sym in symbols:
        try:
            cal = yf.Ticker(sym + ".NS").calendar
            if cal is None:
                continue
            if isinstance(cal, pd.DataFrame) and not cal.empty:
                if "Earnings Date" in cal.columns:
                    ed = pd.to_datetime(cal["Earnings Date"].iloc[0]).date()
                    if today <= ed <= horizon:
                        upcoming[sym] = ed.strftime("%d %b")
            elif isinstance(cal, dict):
                ed_raw = cal.get("Earnings Date")
                if ed_raw:
                    ed = (pd.to_datetime(ed_raw[0]).date()
                          if isinstance(ed_raw, list)
                          else pd.to_datetime(ed_raw).date())
                    if today <= ed <= horizon:
                        upcoming[sym] = ed.strftime("%d %b")
        except Exception:
            pass
    return upcoming

# ══════════════════════════════════════════════════════════════════════════════
# OI DATA — improved NSE session warm-up (v15.8-FIX)
# ══════════════════════════════════════════════════════════════════════════════

@st.cache_data(ttl=180)
def fetch_oi_data(symbol="NIFTY"):
    import requests
    HEADERS={
        "User-Agent":("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36"),
        "Accept":"application/json, text/plain, */*",
        "Accept-Language":"en-US,en;q=0.9",
        "Accept-Encoding":"gzip, deflate, br",
        "Referer":"https://www.nseindia.com/",
        "X-Requested-With":"XMLHttpRequest","Connection":"keep-alive",
        "Cache-Control":"no-cache",
        "Sec-Fetch-Site":"same-origin","Sec-Fetch-Mode":"cors","Sec-Fetch-Dest":"empty",
    }
    session=requests.Session(); session.headers.update(HEADERS)
    def _warm():
        # v15.8-FIX: proper NSE session warming — needs gap between requests for cookie setup
        try:
            session.get("https://www.nseindia.com", timeout=8,
                        headers={**HEADERS,
                                  "Accept":"text/html,application/xhtml+xml,*/*;q=0.8",
                                  "Sec-Fetch-Mode":"navigate","Sec-Fetch-Dest":"document"})
            time.sleep(1.5)   # NSE needs this gap to set session cookies
            session.get("https://www.nseindia.com/market-data/equity-derivatives-watch", timeout=8)
            time.sleep(1.0)
            return "nsit" in session.cookies or "nseappid" in session.cookies
        except Exception:
            return False
    _warm()
    oc_url=f"https://www.nseindia.com/api/option-chain-indices?symbol={symbol}"
    data=None
    for attempt in range(3):
        try:
            resp=session.get(oc_url,timeout=12)
            if resp.status_code==200: data=resp.json(); break
            elif resp.status_code in (401,403): _warm()
        except Exception: pass
        time.sleep(1.5**attempt)
    if data is None: return None
    try:
        records=data["records"]; spot=float(records["underlyingValue"])
        expiries=records["expiryDates"]; weekly_expiry=expiries[0] if expiries else None
        rows=[]
        for item in records["data"]:
            if item.get("expiryDate")!=weekly_expiry: continue
            strike=item["strikePrice"]
            ce_oi=item.get("CE",{}).get("openInterest",0) or 0
            pe_oi=item.get("PE",{}).get("openInterest",0) or 0
            ce_chg=item.get("CE",{}).get("changeinOpenInterest",0) or 0
            pe_chg=item.get("PE",{}).get("changeinOpenInterest",0) or 0
            rows.append({"Strike":strike,"CE_OI":ce_oi,"CE_Chg":ce_chg,"PE_OI":pe_oi,"PE_Chg":pe_chg})
        if not rows: return None
        df_oi=pd.DataFrame(rows).sort_values("Strike").reset_index(drop=True)
        total_ce=df_oi["CE_OI"].sum(); total_pe=df_oi["PE_OI"].sum()
        pcr=round(total_pe/total_ce,2) if total_ce>0 else 0
        pains=[]
        for s in df_oi["Strike"]:
            ce_l=((df_oi["Strike"]-s).clip(lower=0)*df_oi["CE_OI"]).sum()
            pe_l=((s-df_oi["Strike"]).clip(lower=0)*df_oi["PE_OI"]).sum()
            pains.append(ce_l+pe_l)
        df_oi["TotalPain"]=pains
        return {
            "symbol":symbol,"expiry":weekly_expiry,"spot":spot,"pcr":pcr,
            "max_pain":int(df_oi.loc[df_oi["TotalPain"].idxmin(),"Strike"]),
            "call_wall":int(df_oi.loc[df_oi["CE_OI"].idxmax(),"Strike"]),
            "put_wall":int(df_oi.loc[df_oi["PE_OI"].idxmax(),"Strike"]),
            "top_ce":df_oi.nlargest(5,"CE_OI")[["Strike","CE_OI","CE_Chg"]].to_dict("records"),
            "top_pe":df_oi.nlargest(5,"PE_OI")[["Strike","PE_OI","PE_Chg"]].to_dict("records"),
            "df_oi":df_oi,
        }
    except Exception: return None

def _oi_sentiment(pcr):
    if pcr>=1.3: return "Bullish","#16a34a"
    if pcr>=0.9: return "Neutral","#d97706"
    return "Bearish","#dc2626"

@st.cache_data(ttl=300)
def fetch_indices(mode="Swing"):
    cfg=MODE_CFG[mode]; ema_f=cfg["ema_fast"]; ema_s=cfg["ema_slow"]; rsi_l=cfg["rsi_len"]
    min_bars=60 if mode=="Intraday" else 50; out={}
    index_syms=[("Nifty 50","^NSEI"),("BankNifty","^NSEBANK"),("Sensex","^BSESN")]
    raw=fetch_async(["^NSEI","^NSEBANK","^BSESN"],cfg["yf_period"],cfg["interval"],concurrency=3)
    for name,ticker in index_syms:
        sym_key=ticker
        df=raw.get(sym_key,pd.DataFrame())
        if df.empty:
            out[name]=None; continue
        try:
            if len(df)<min_bars: out[name]=None; continue
            close=df["Close"]; c,prev=float(close.iloc[-1]),float(close.iloc[-2])
            chg,pct=c-prev,(c-prev)/prev*100
            ef=float(ema(close,ema_f).iloc[-1]); es=float(ema(close,ema_s).iloc[-1])
            e200=float(ema(close,200).iloc[-1]) if len(close)>=200 else es
            r=float(rsi(close,rsi_l).iloc[-1]); hh=float(close.iloc[-11:-1].max())
            trend_up=c>e200 and c>ef and ef>es
            bull=0
            bull+=25 if trend_up else 0
            bull+=15 if ef>es else (7 if ef>es*0.995 else 0)
            bull+=(15 if r>=65 else 10) if r>=60 else (5 if r>50 else 0)
            bull+=15 if c>hh else (9 if c>hh*0.98 else 0)
            if len(close)>=3 and c>float(close.iloc[-3]): bull+=8
            norm_score=min(100.0,max(0.0,bull*100.0/78))
            interval_label={"5m":"5min","1d":"Daily","1wk":"Weekly"}.get(cfg["interval"],cfg["interval"])
            out[name]={"value":round(c,1),"chg":round(chg,2),"pct":round(pct,2),
                       "score":round(norm_score,1),"action":action_label(norm_score),
                       "rsi":round(r,1),"trend":"↑ Above EMAs" if trend_up else "↓ Below EMAs",
                       "interval":interval_label,"ema_fast":ema_f,"ema_slow":ema_s}
        except Exception:
            out[name]=None
    return out

# ══════════════════════════════════════════════════════════════════════════════
# STREAMLIT APP
# ══════════════════════════════════════════════════════════════════════════════

st.set_page_config(
    page_title="🐂 BULL SUTRA Pro v15.8",
    page_icon="🐂", layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600;700&family=DM+Sans:wght@400;500;600&family=Syne:wght@600;700&display=swap');
html,body,[class*="css"]{background:#07070f;color:#e8e8f4;}
.stApp{background:#07070f;}
.stDataFrame{background:#111120;}
.stButton>button{background:#1a1a35;border:1px solid #2a2a55;color:#e8e8f4;border-radius:8px;}
.stButton>button[kind="primary"]{background:#f59e0b;color:#1a0a00;font-weight:700;}
[data-testid="metric-container"]{background:#111120;border:1px solid #1e1e40;border-radius:8px;padding:10px;}
</style>
""", unsafe_allow_html=True)

# ── Session state ──────────────────────────────────────────────────────────────
for key,default in [
    ("results",[]),("scan_time",None),("rejected",0),("liq_skipped",0),
    ("scan_mode","Swing"),("signal_log",[]),("phase_history",{}),
    ("account_size",500000),("risk_pct",0.02),("max_capital_pct",0.20),
    ("phase_filter","All Phases"),("show_illiquid",False),("min_liq_cr",5.0),
    ("open_positions",None),("short_results",[]),("short_watchlist",None),
    ("exit_results",{}),("_db_error",None),
    # v15 additions
    ("last_scan_stage_a_survivors",0),("live_refresh_enabled",False),
    ("earnings_map",{}),  # v15.8-FIX: earnings date cache
]:
    if key not in st.session_state:
        st.session_state[key]=default

if st.session_state["open_positions"] is None:
    st.session_state["open_positions"]=_db_load("bs_positions")
if st.session_state["short_watchlist"] is None:
    st.session_state["short_watchlist"]=_db_load("bs_short_wl")

@st.cache_data(ttl=300, show_spinner=False)
def _prewarm():
    fetch_vix()
    fetch_nifty("Swing")
_prewarm()

# ══════════════════════════════════════════════════════════════════════════════
# v15.8-FIX: PRE-ENTRY CHECKLIST SIDEBAR
# ══════════════════════════════════════════════════════════════════════════════
with st.sidebar:
    st.markdown(
        '<div style="font-family:Syne,sans-serif;font-size:13px;font-weight:700;'
        'color:#f59e0b;margin-bottom:10px;letter-spacing:.05em;'
        'text-transform:uppercase;">Pre-Entry Checklist</div>',
        unsafe_allow_html=True,
    )
    _checks = [
        ("ltp_near_entry",    "LTP within 0.5% of Entry price"),
        ("nifty_flat_rising", "Nifty flat or rising right now"),
        ("htf_bullish",       "HTFUp = True (check Detail tab)"),
        ("ext_n_ok",          "ExtN is 0 or 1 (no exhaustion)"),
        ("no_earnings",       "No earnings in next 7 days"),
        ("no_resistance",     "No major resistance within 2%"),
        ("size_checked",      "Position size reviewed"),
    ]
    _all_ok = True
    for _ck, _cl in _checks:
        _v = st.checkbox(_cl, key=f"chk_{_ck}")
        if not _v: _all_ok = False
    if _all_ok:
        st.success("✅ All clear — proceed")
    else:
        _rem = sum(1 for _ck,_ in _checks if not st.session_state.get(f"chk_{_ck}",False))
        st.warning(f"⚠ {_rem} item{'s' if _rem>1 else ''} unchecked")
    if st.button("Reset", key="chk_reset", use_container_width=True):
        for _ck,_ in _checks:
            st.session_state[f"chk_{_ck}"] = False
        st.rerun()
    st.markdown("---")
    # Show any active earnings alerts from last scan
    _em = st.session_state.get("earnings_map", {})
    if _em:
        st.markdown(
            '<div style="font-size:11px;font-weight:600;color:#fca5a5;margin-bottom:4px;">'
            '⚠ Results upcoming (14d)</div>', unsafe_allow_html=True
        )
        for _s, _d in list(_em.items())[:8]:
            st.markdown(
                f'<div style="font-size:10px;font-family:JetBrains Mono,monospace;'
                f'color:#f87171;">{_s} · {_d}</div>', unsafe_allow_html=True
            )
st.markdown(
    '''<div style="font-family:Syne,sans-serif;font-size:28px;font-weight:700;
    letter-spacing:-1px;color:#e8e8f4;padding:8px 0 4px;">
    <span style="color:#f59e0b;">&#x1F402;</span> BULL SUTRA
    <span style="font-size:13px;color:#cbd5e1;font-family:JetBrains Mono,monospace;
    font-weight:400;">PRO · v15.7 ⚡</span></div>''',
    unsafe_allow_html=True,
)

_UNIVERSE_OPTIONS = (
    ["NSE 500"]+[k for k in _SECTORS.keys() if k!="Nifty 500"]
    if _SECTORS else ["NSE 500","Nifty 50"]
)

gc1,gc2,gc3,gc4,gc5,gc6 = st.columns([2,2,1,1,2,2])
with gc1:
    universe_opt=st.selectbox("Universe",_UNIVERSE_OPTIONS,index=0,label_visibility="visible")
with gc2:
    mode_opt=st.radio("Mode",["Swing","Intraday","Positional"],horizontal=True)
with gc3:
    scan_btn=st.button("SCAN",type="primary",use_container_width=True)
with gc4:
    # SPEED-8: live refresh toggle
    live_refresh=st.toggle("⚡ Live",value=st.session_state.get("live_refresh_enabled",False),
                            help="Auto-refresh live tail every 60s during market hours")
    st.session_state["live_refresh_enabled"]=live_refresh
with gc5:
    filter_opt=st.selectbox("Filter",
        ["BUY + STRONG BUY","STRONG BUY only","WATCH + BUY","PRE-CONFIRM","All Results"],
        label_visibility="collapsed")
with gc6:
    search_q=st.text_input("Search symbol",placeholder="e.g. RELIANCE",
                            label_visibility="collapsed")

# ── v15.5: Selection type row ──────────────────────────────────────────────────
_sc1, _sc2, _sc3 = st.columns([3, 3, 6])
with _sc1:
    selection_type = st.radio(
        "Selection Mode",
        ["🎯 Confirmation", "🌱 Emerging"],
        horizontal=True,
        key="sel_type",
        help=(
            "Confirmation — stocks already in ENTRY/CONT/BREAKOUT phase.\n"
            "Emerging — stocks BEFORE they become obvious (coiling, building momentum)."
        ),
    )
with _sc2:
    if selection_type == "🌱 Emerging":
        em_min_score = st.slider(
            "Min Emerging Score", 20, 80,
            st.session_state.get("em_min_score", 35), 5,
            key="em_min_score_slider",
        )
        st.session_state["em_min_score"] = em_min_score
    else:
        em_min_score = st.session_state.get("em_min_score", 35)

vix_val,vix_label=fetch_vix()
vix_color={"CALM":"#22c55e","CAUTION":"#f59e0b","STRESS":"#ef4444","UNKNOWN":"#cbd5e1"}.get(vix_label,"#cbd5e1")
vix_text_color={"CALM":"#14532d","CAUTION":"#78350f","STRESS":"#7f1d1d","UNKNOWN":"#374151"}.get(vix_label,"#374151")

# Speed indicators
aiohttp_badge  = ("⚡ async HTTP" if _AIOHTTP_OK   else "yfinance fallback")
polars_badge   = ("🔷 Polars"     if _POLARS_OK    else "")
parquet_badge  = ("📦 Parquet cache" if _PARQUET_OK else "")
cold_flag_info = "🌅 cold-start" if _cold_start_needed(mode_opt) else "♻️ incremental"
speed_badges   = " · ".join(filter(None,[aiohttp_badge,polars_badge,parquet_badge,cold_flag_info]))

st.markdown(
    f'<div style="background:{vix_color}18;border:1px solid {vix_color}44;'
    f'border-radius:7px;padding:7px 14px;margin:6px 0;display:flex;'
    f'align-items:center;gap:12px;font-family:JetBrains Mono,monospace;flex-wrap:wrap;">'
    f'<span style="background:{vix_color};color:{vix_text_color};padding:2px 8px;'
    f'border-radius:4px;font-size:11px;font-weight:700;">VIX '
    f'{vix_val if vix_val else "—"} · {vix_label}</span>'
    f'<span style="color:#475569;font-size:10px;">{speed_badges}</span>'
    +(f'<span style="color:#ef4444;font-size:11px;">⚠ High VIX: STRONG BUY blocked · targets compressed</span>'
      if (vix_val and vix_val>=VIX_STRESS) else "")
    +(f'<span style="color:#f59e0b;font-size:11px;">⚡ Elevated VIX: targets compressed · SL widened</span>'
      if (vix_val and VIX_CAUTION<=vix_val<VIX_STRESS) else "")
    +'</div>',
    unsafe_allow_html=True,
)

# ── Tabs ───────────────────────────────────────────────────────────────────────
tab_scanner,tab_breadth,tab_detail,tab_portfolio,tab_analytics,tab_settings = st.tabs(
    ["Scanner","Breadth Engine","Detail","💼 Portfolio","Analytics","Settings"]
)

# ══════════════════════════════════════════════════════════════════════════════
# SETTINGS TAB
# ══════════════════════════════════════════════════════════════════════════════

with tab_settings:
    st.subheader("Scanner Settings")
    sc1,sc2=st.columns(2)
    with sc1:
        st.session_state.min_liq_cr=st.slider(
            "Min Liquidity (₹ Cr daily traded value)",1.0,50.0,
            float(st.session_state.min_liq_cr),1.0)
        st.session_state.phase_filter=st.selectbox(
            "Phase Filter (Scanner)",
            ["All Phases","ENTRY","SETUP","CONT","BREAKOUT","IDLE","EXIT"],
            index=["All Phases","ENTRY","SETUP","CONT","BREAKOUT","IDLE","EXIT"].index(
                st.session_state.get("phase_filter","All Phases")))
        st.session_state.show_illiquid=st.checkbox(
            "Show illiquid stocks (below liquidity floor)",value=st.session_state.show_illiquid)
        st.markdown("---"); st.markdown("**Position Sizing**")
        st.session_state.account_size=st.number_input(
            "Account Size (₹)",min_value=10000,max_value=10_000_000,
            value=int(st.session_state.account_size),step=10000)
        st.session_state.risk_pct=st.slider(
            "Risk per trade (%)",0.5,5.0,float(st.session_state.risk_pct*100),0.5)/100.0
        st.session_state.max_capital_pct=st.slider(
            "Max capital per trade (% of account)",5,50,
            int(st.session_state.max_capital_pct*100),5)/100.0
        st.caption(
            f"Current cap: ₹{st.session_state.account_size*st.session_state.max_capital_pct:,.0f} "
            f"per position ({int(st.session_state.max_capital_pct*100)}% of account)"
        )
        st.markdown("---"); st.markdown("**v15 Cache**")
        col_c1,col_c2=st.columns(2)
        with col_c1:
            cache_size=sum(f.stat().st_size for f in _CACHE_DIR.glob("*.parquet"))
            st.metric("Cache size",f"{cache_size/1e6:.1f} MB")
            st.metric("Cached files",len(list(_CACHE_DIR.glob("*.parquet"))))
        with col_c2:
            if st.button("🗑 Clear cache",use_container_width=True):
                for f in _CACHE_DIR.glob("*.parquet"): f.unlink(missing_ok=True)
                for f in _CACHE_DIR.glob("cold_start_*.flag"): f.unlink(missing_ok=True)
                st.success("Cache cleared — next scan will do a full fetch.")
    with sc2:
        st.markdown("**v15 Speed Architecture**")
        st.markdown("""
| Component | v14 | v15 |
|-----------|-----|-----|
| HTTP | yfinance | aiohttp direct |
| Fetch | Sequential batches | 64 concurrent |
| History | Re-download every scan | Parquet cache + live tail |
| Pre-filter | None | Stage-A EMA vectorized |
| Indicators | Per-symbol Pandas | Batch numpy (N×T) |
| ADX | ✗ | ✓ |
| Squeeze | ✗ | ✓ |
| Vol contraction | ✗ | ✓ |
""")
        st.markdown("**Action Thresholds**")
        st.markdown("""
| Score | Action |
|-------|--------|
| ≥ 75 | STRONG BUY |
| ≥ 58 | BUY |
| ≥ 42 | WATCH |
| < 42 | SKIP |
""")

# ══════════════════════════════════════════════════════════════════════════════
# SCAN EXECUTION
# ══════════════════════════════════════════════════════════════════════════════

if scan_btn:
    if universe_opt=="NSE 500":
        symbols=NSE500
    elif _SECTORS and universe_opt in _SECTORS:
        _sec_syms=_SECTORS[universe_opt]
        symbols=NSE500 if _sec_syms is None else list(_sec_syms)
    else:
        symbols=NIFTY50

    n=len(symbols)
    prog=st.progress(0); stat=st.empty()
    t0=time.time()
    with st.spinner(f"Scanning {universe_opt} ({n} stocks) · {mode_opt}…"):
        results,rejected,liq_skipped=run_scan(
            symbols,mode_opt,prog,stat,
            vix_val=vix_val,min_liq_cr=st.session_state.min_liq_cr,
        )
    elapsed=time.time()-t0
    st.session_state.results=results
    st.session_state.rejected=rejected
    st.session_state.liq_skipped=liq_skipped
    st.session_state.scan_mode=mode_opt
    st.session_state.scan_time=(
        datetime.now().strftime("%H:%M:%S")+
        f" ({universe_opt} · {mode_opt} · {elapsed:.0f}s)"
    )
    ts=datetime.now().isoformat(); validity_h=MODE_CFG[mode_opt]["validity_hours"]
    for r in results:
        if r.get("Action") in ("BUY","STRONG BUY"):
            st.session_state.signal_log.append({
                "timestamp":ts,"symbol":r["Symbol"],"action":r["Action"],
                "phase":r.get("Phase"),"score":r["Score"],
                "confidence":r.get("Confidence",0),"rs_rank":r.get("RS_Rank",50),
                "entry":r.get("Entry"),"sl":r.get("SL"),"t1":r.get("T1"),
                "ltp_at_signal":r.get("LTP"),"mode":mode_opt,
                "validity_hours":validity_h,"outcome":"Pending",
                "breadth_gated":r.get("BreadthGated",False),
            })
    prog.empty(); stat.empty()
    survivors_count=n-rejected
    st.success(
        f"✅ {len(results)} scored · {survivors_count} survived Stage-A · "
        f"{rejected} Stage-A filtered · {liq_skipped} illiquid · "
        f"⏱ {elapsed:.1f}s"
    )
    # v15.8-FIX: fetch earnings dates for all scanned symbols (background, cached 1h)
    with st.spinner("Checking earnings calendar…"):
        st.session_state["earnings_map"] = get_earnings_dates(
            [r["Symbol"] for r in results]
        )

# ── SPEED-8: Live refresh during market hours ──────────────────────────────────
if (live_refresh and _is_market_open()
        and st.session_state.results
        and st.session_state.scan_mode):
    import streamlit as _st
    # Auto-rerun every 60 seconds via st.rerun inside a time check
    if "last_live_refresh" not in st.session_state:
        st.session_state["last_live_refresh"] = time.time()
    elapsed_since = time.time() - st.session_state.get("last_live_refresh", 0)
    if elapsed_since >= 60:
        st.session_state["last_live_refresh"] = time.time()
        st.info("⚡ Live: refreshing latest candle…")
        # Refresh only LTP for existing results (lightweight)
        syms = [r["Symbol"] for r in st.session_state.results[:30]]
        cfg  = MODE_CFG[st.session_state.scan_mode]
        live = fetch_async(syms,"1d",cfg["interval"],concurrency=32)
        for r in st.session_state.results:
            sym = r["Symbol"]
            df  = live.get(sym)
            if df is not None and not df.empty:
                ltp = float(df["Close"].iloc[-1])
                prev = r["LTP"]
                r["LTP"] = round(ltp, 2)
                r["%Change"] = round((ltp-prev)/prev*100, 2) if prev else r["%Change"]
        st.rerun()

# ══════════════════════════════════════════════════════════════════════════════
# SCANNER TAB
# ══════════════════════════════════════════════════════════════════════════════

with tab_scanner:
    indices=fetch_indices(mode_opt)
    oi_nifty=fetch_oi_data("NIFTY")
    oi_banknifty=fetch_oi_data("BANKNIFTY")

    ic1,ic2,ic3=st.columns(3)
    for (name,col,oi_data) in [("Nifty 50",ic1,oi_nifty),("BankNifty",ic2,oi_banknifty),("Sensex",ic3,None)]:
        d=indices.get(name)
        with col:
            if not d:
                st.markdown(f"<div style='color:#cbd5e1;font-size:12px;'>{name}: unavailable</div>",unsafe_allow_html=True)
                continue
            chg_val=d["chg"]; pct_val=d["pct"]; ltp_val=d["value"]
            cs=f"+{pct_val:.2f}%" if chg_val>=0 else f"{pct_val:.2f}%"
            cc="#22c55e" if chg_val>=0 else "#ef4444"
            ar="▲" if chg_val>=0 else "▼"
            act=d["action"]
            score_bar_color=("#f59e0b" if act=="STRONG BUY" else "#22c55e" if act=="BUY"
                             else "#f59e0b" if act=="WATCH" else "#cbd5e1")
            sp=int(min(d["score"],100))
            oi_badge=""
            if oi_data:
                s_label,s_col=_oi_sentiment(oi_data["pcr"])
                pd_=oi_data["max_pain"]-int(ltp_val)
                pa="↑" if pd_>0 else ("↓" if pd_<0 else "=")
                oi_badge=(f'<div style="margin-top:6px;padding:5px 8px;background:#09090f;'
                          f'border-radius:5px;border:1px solid #1e1e40;font-family:JetBrains Mono,monospace;">'
                          f'<span style="color:#cbd5e1;font-size:9px;">PCR </span>'
                          f'<span style="background:{s_col}22;border:1px solid {s_col}44;'
                          f'color:{s_col};padding:1px 5px;border-radius:3px;font-size:9px;font-weight:600;">'
                          f'{oi_data["pcr"]} {s_label}</span>'
                          f'<span style="color:#cbd5e1;font-size:9px;margin-left:6px;">Pain </span>'
                          f'<span style="color:#f59e0b;font-size:9px;font-weight:600;">'
                          f'₹{oi_data["max_pain"]:,} {pa}{abs(pd_):,}</span>'
                          f'<br><span style="color:#ef4444;font-size:9px;">C▶₹{oi_data["call_wall"]:,}  </span>'
                          f'<span style="color:#22c55e;font-size:9px;">P▶₹{oi_data["put_wall"]:,}</span></div>')
            st.markdown(
                f'<div style="background:#111120;border:1px solid #1e1e40;border-radius:10px;padding:14px 16px;">'
                f'<div style="font-family:DM Sans,sans-serif;color:#cbd5e1;font-size:10px;text-transform:uppercase;letter-spacing:1px;">{name}</div>'
                f'<div style="font-family:JetBrains Mono,monospace;color:#e8e8f4;font-size:22px;font-weight:600;margin:4px 0 2px;">{ltp_val:,.1f}</div>'
                f'<div style="font-family:JetBrains Mono,monospace;color:{cc};font-size:12px;">{ar} {cs}</div>'
                f'<div style="margin:8px 0 4px;background:#1e1e40;border-radius:3px;height:3px;">'
                f'<div style="background:{score_bar_color};width:{sp}%;height:3px;border-radius:3px;"></div></div>'
                f'<div style="display:flex;align-items:center;gap:6px;margin-top:4px;">'
                f'<span style="background:{score_bar_color}22;border:1px solid {score_bar_color}44;'
                f'color:{score_bar_color};padding:2px 7px;border-radius:3px;font-size:10px;font-weight:600;">{act}</span>'
                f'<span style="font-family:JetBrains Mono,monospace;color:#3a3a60;font-size:10px;">RSI {d["rsi"]} · {d["trend"]}</span>'
                f'</div>'+oi_badge+'</div>',
                unsafe_allow_html=True,
            )

    st.markdown('<div style="border-top:1px solid #1e1e40;margin:16px 0;"></div>',unsafe_allow_html=True)

    # ── Apply filters ──────────────────────────────────────────────────────────
    results=list(st.session_state.results)
    if filter_opt=="BUY + STRONG BUY": results=[r for r in results if r["Action"] in ("BUY","STRONG BUY")]
    elif filter_opt=="STRONG BUY only": results=[r for r in results if r["Action"]=="STRONG BUY"]
    elif filter_opt=="WATCH + BUY": results=[r for r in results if r["Action"] in ("WATCH","BUY","STRONG BUY")]
    elif filter_opt=="PRE-CONFIRM": results=[r for r in results if r["Action"]=="PRE-CONFIRM"]
    _phase_filter=st.session_state.get("phase_filter","All Phases")
    if _phase_filter!="All Phases": results=[r for r in results if r.get("Phase")==_phase_filter]
    if not st.session_state.get("show_illiquid",False): results=[r for r in results if r.get("LiquidityOK",True)]
    if search_q: results=[r for r in results if search_q.upper() in r["Symbol"]]

    # ── make_card (v14.3 card UI preserved, v15 adds ADX/Squeeze badges) ──────
    if st.session_state.results:
        scan_mode_now=st.session_state.scan_mode
        stale_syms=set()
        for entry in st.session_state.signal_log:
            if signal_is_stale(entry["timestamp"],entry.get("mode",scan_mode_now)):
                stale_syms.add(entry["symbol"])

        # ── v15.8-FIX: helpers for unique signal extraction ──────────────────────
        def _unique_signals(r):
            """Extract top-4 most differentiated, stock-specific signals with actual values."""
            sigs = []
            # Squeeze depth + duration
            if r.get("Squeeze"):
                sb = r.get("SqzBars", 0); sd = r.get("SqzDepth", 1.0)
                sigs.append({"label":f"Squeeze {sb}d","value":f"{int((1-sd)*100)}% tight","color":"#c084fc","rank":90+sb})
            # Volume dry-up
            vdu = r.get("Patterns",{}).get("vol_dryup",{})
            if vdu.get("dry_up") and vdu.get("intensity",0)>=1:
                sigs.append({"label":f"Vol Dry {vdu.get('bars',0)}b","value":f"{vdu.get('vol_pct',0):.0f}% avg","color":"#38bdf8","rank":80+vdu.get("intensity",0)*5})
            # ADX
            adx = r.get("ADX",0)
            if adx >= 20:
                ac = "#22c55e" if adx>=30 else "#f59e0b"
                al = "Very strong" if adx>=40 else "Strong" if adx>=30 else "Building"
                sigs.append({"label":f"ADX {adx:.0f}","value":al,"color":ac,"rank":55+adx})
            # MTF sync
            ms = r.get("MTFScore",50); ml = r.get("MTFLabel","NEUTRAL")
            if ms>=62 or ms<=38:
                mc = "#22c55e" if ms>=62 else "#ef4444"
                sigs.append({"label":f"MTF {ms:.0f}","value":ml,"color":mc,"rank":ms if ms>=50 else 100-ms})
            # Institutional
            iv = r.get("InstVerdict","NEUTRAL"); ic = r.get("InstCMF",0); ins = r.get("InstScore",50)
            if ins>=65 or ins<=35:
                ic2 = "#22c55e" if ins>=65 else "#ef4444"
                sigs.append({"label":f"Inst {ins:.0f}","value":f"CMF {ic:+.3f}","color":ic2,"rank":abs(ins-50)+50})
            # VCP
            vcp = r.get("Patterns",{}).get("vcp",{})
            if vcp.get("detected") and vcp.get("n_contractions",0)>=2:
                nc=vcp.get("n_contractions",0); tp=vcp.get("tightest_pct",0)
                sigs.append({"label":f"VCP {nc}×","value":f"{tp:.1f}% tight","color":"#a78bfa","rank":70+nc*5})
            # AVWAP
            av_d = r.get("Patterns",{}).get("avwap",{}); av=av_d.get("avwap"); pa=av_d.get("pct_above",0)
            if av and av_d.get("price_above"):
                avc = "#38bdf8" if av_d.get("near_support") else "#64748b"
                sigs.append({"label":f"AVWAP ₹{av:,.0f}","value":f"+{pa:.1f}% above","color":avc,"rank":60+(5 if av_d.get("near_support") else 0)})
            # RS rank
            rsr=r.get("RS_Rank",50); rsv=r.get("RS",0)
            if rsr>=75 or rsr<=25:
                rsc="#22c55e" if rsr>=75 else "#ef4444"
                arr="↑" if rsv>=0 else "↓"
                sigs.append({"label":f"RS Rank {rsr}","value":f"{arr} {abs(rsv):.1f}% vs Nifty","color":rsc,"rank":rsr if rsr>=50 else 100-rsr})
            # Harmonic
            if r.get("HarmonicDetected"):
                hp=r.get("HarmonicPattern",""); hd=r.get("HarmonicDir",""); hq=r.get("HarmonicQuality",0)
                hc="#22c55e" if hd=="BULL" else "#ef4444"
                sigs.append({"label":f"{hp}","value":f"{hq}% · {hd}","color":hc,"rank":hq})
            # Candle pattern
            cp=r.get("CandlePatterns",[]); cs_=r.get("CandleScore",0)
            if r.get("CandleSignal") in ("BULL","BULL LEAN") and cp:
                sigs.append({"label":cp[0],"value":f"Score +{cs_}","color":"#86efac","rank":50+cs_*3})
            # Darvas breakout
            dv=r.get("Patterns",{}).get("darvas",{})
            if dv.get("breakout"):
                sigs.append({"label":"Darvas Break","value":f"Box {dv.get('box_width_pct',0):.1f}%","color":"#f87171","rank":88})
            # Fib quality
            fq=r.get("Patterns",{}).get("fib_quality",{})
            if fq.get("quality",0)>=60:
                sigs.append({"label":f"Fib {fq.get('fib_level','—')}","value":f"{fq.get('grade','—')} retracement","color":"#fb923c","rank":fq.get("quality",0)})
            # 1M momentum (specific %)
            m1=r.get("Mom1",0)
            if abs(m1)>=5:
                mc2="#22c55e" if m1>0 else "#ef4444"
                sigs.append({"label":"1M Mom","value":f"{m1:+.1f}%","color":mc2,"rank":40+abs(m1)})
            # Fresh EMA cross
            if r.get("FreshCross"):
                sigs.append({"label":"Golden Cross","value":"EMA cross <5 bars","color":"#fbbf24","rank":82})
            # NR7
            if r.get("NR7"):
                sigs.append({"label":"NR7","value":"Narrowest range 7d","color":"#c084fc","rank":72})
            # Smart money (v15.7)
            smv=r.get("SmartMoneyVerdict",""); sms=r.get("SmartMoneyScore",50)
            if smv in ("ACCUMULATING","MARKUP_READY","ABSORBING"):
                smc="#22c55e" if smv in ("ACCUMULATING","MARKUP_READY") else "#38bdf8"
                sigs.append({"label":f"SM {smv[:6]}","value":f"Score {sms:.0f}","color":smc,"rank":85})
            # Accum stage (v15.7)
            ast=r.get("AccumStage","")
            if ast in ("1C","2A","2B"):
                sigs.append({"label":f"Stage {ast}","value":r.get("AccumStageLabel","")[:18],"color":"#22c55e","rank":88 if ast=="2A" else 78})
            sigs.sort(key=lambda x:x["rank"], reverse=True)
            return sigs[:4]

        def _caution_line(r):
            ext_n=r.get("ExtN",0); ext_lb=r.get("ExtLabels",[])
            if r.get("BreadthGated"): return "Breadth weak — size down"
            if ext_n>=3: return f"{'/ '.join(ext_lb[:2]) or 'Exhaustion'} — avoid entry"
            if ext_n==2: return f"{ext_lb[0] if ext_lb else 'Ext'} — halve size"
            if r.get("MTFDiverge"): return "TF divergence — confirm HTF first"
            if r.get("RSI",50)>=73: return f"RSI {r.get('RSI',50):.0f} — extended, wait"
            if not r.get("HTFUp",True): return "HTF bearish — reduce size"
            ed = st.session_state.get("earnings_map",{}).get(r.get("Symbol",""))
            if ed: return f"Results {ed} — binary risk"
            return None

        def make_card(i, r, border_color, show_entry=True):
            sym   = r["Symbol"]; act = r["Action"]; ltp = r["LTP"]; chg = r["%Change"]
            score = r["Score"];  phase = r.get("Phase", PHASE_IDLE); conf = r.get("Confidence", 0)
            entry = r.get("Entry"); sl = r.get("SL"); t1 = r.get("T1"); t2 = r.get("T2"); t3 = r.get("T3")
            ext_n = r.get("ExtN", 0); ext_labels = r.get("ExtLabels", [])
            sector = r.get("Sector", SECTOR_MAP.get(sym, "—"))
            is_stale = sym in stale_syms

            # ── Derived values ────────────────────────────────────────────────
            chg_str = f"+{chg:.2f}%" if chg >= 0 else f"{chg:.2f}%"
            chg_col = "#22c55e" if chg >= 0 else "#ef4444"
            chg_arr = "▲" if chg >= 0 else "▼"
            act_bg, act_brd, act_txt = _action_colors(act)
            phase_col = _phase_color(phase)
            conf_col  = _conf_color(conf)
            phase_icon = {"BREAKOUT":"🚀","CONT":"↗","ENTRY":"⚡","SETUP":"◎","IDLE":"–","EXIT":"↘"}.get(phase,"")
            ph_arrow   = get_phase_arrow(sym)
            score_col  = "#f59e0b" if act == "STRONG BUY" else "#22c55e" if act in ("BUY","PRE-CONFIRM") else "#3b82f6"

            def _p(v):
                if v is None: return "—"
                try: return f"₹{int(round(v)):,}"
                except: return "—"

            ref = entry if (show_entry and entry and entry != ltp) else ltp
            risk_pct = reward_pct = rr = None
            if ref and sl:
                risk = ref - sl
                if risk > 0:
                    risk_pct = risk / ref * 100
                    tgt = t2 or t1
                    if tgt:
                        reward_pct = (tgt - ref) / ref * 100
                        rr = reward_pct / risk_pct
            rr_col = "#22c55e" if (rr and rr >= 2) else "#f59e0b" if (rr and rr >= 1.5) else "#64748b"
            rr_str = f"{rr:.1f}×" if rr else "—"
            entry_disp = f"₹{entry:,.0f}" if (show_entry and entry and entry != ltp) else f"₹{ltp:,.2f}"

            stale_dot = ' <span style="color:#475569;font-size:9px;">⏱</span>' if is_stale else ""
            ed = st.session_state.get("earnings_map", {}).get(sym)
            earn_html = (f'<span style="background:#7f1d1d;border:1px solid #ef4444;color:#fca5a5;'
                         f'padding:1px 5px;border-radius:3px;font-size:9px;font-weight:700;margin-left:4px;">'
                         f'⚠ RESULTS {ed}</span>') if ed else ""

            # ── Why Now signals ───────────────────────────────────────────────
            sigs = _unique_signals(r)
            sig_rows = "".join(
                f'<div style="display:flex;align-items:center;justify-content:space-between;'
                f'padding:4px 0;border-bottom:1px solid #12182a;">'
                f'<span style="color:#94a3b8;font-family:JetBrains Mono,monospace;font-size:9px;'
                f'width:90px;flex-shrink:0;">{s["label"]}</span>'
                f'<div style="flex:1;margin:0 6px;background:#12182a;border-radius:2px;height:3px;">'
                f'<div style="background:{s["color"]};width:{min(s["rank"],100)}%;height:3px;border-radius:2px;"></div></div>'
                f'<span style="color:{s["color"]};font-family:JetBrains Mono,monospace;font-size:9px;'
                f'font-weight:600;text-align:right;min-width:70px;">{s["value"]}</span>'
                f'</div>'
                for s in sigs
            ) if sigs else '<div style="color:#334155;font-size:9px;padding:4px 0;">No dominant signals</div>'

            caution = _caution_line(r)
            caution_html = (
                f'<div style="display:flex;gap:4px;align-items:flex-start;'
                f'padding:4px 6px;margin-top:4px;background:#1c0700;border-left:2px solid #f59e0b;border-radius:2px;">'
                f'<span style="color:#f59e0b;font-size:9px;flex-shrink:0;">⚠</span>'
                f'<span style="color:#fbbf24;font-size:9px;">{caution}</span></div>'
            ) if caution else ""

            # ── Exhaustion warning ────────────────────────────────────────────
            ext_html = ""
            if ext_n > 0:
                ec = "#fca5a5" if ext_n >= 3 else "#fbbf24"
                eb = "#3b1a0a" if ext_n >= 3 else "#2a1e00"
                skip_warn = " — SKIP ENTRY" if ext_n >= 3 else " — reduce size"
                pills = "  ".join(f'⚠ {lb}' for lb in ext_labels[:2])
                ext_html = (f'<div style="padding:4px 12px;background:{eb};border-top:1px solid #1e293b;">'
                            f'<span style="color:{ec};font-size:9px;">{pills}{skip_warn}</span></div>')

            # ── Intelligence grid (same 3×2 as emerging cards) ────────────────
            sm_verdict = r.get("SmartMoneyVerdict","NEUTRAL")
            sm_c_map   = {"MARKUP_READY":"#f59e0b","ACCUMULATING":"#22c55e",
                          "ABSORBING":"#38bdf8","NEUTRAL":"#64748b","DISTRIBUTING":"#ef4444"}
            sm_c     = sm_c_map.get(sm_verdict,"#64748b")
            sm_short = {"MARKUP_READY":"MKUP▲","ACCUMULATING":"ACCUM","ABSORBING":"ABSO",
                        "NEUTRAL":"NEUT","DISTRIBUTING":"DIST▼"}.get(sm_verdict, sm_verdict[:5])

            accum_stage = r.get("AccumStage","NONE")
            as_c_map = {"NONE":"#374151","1A":"#64748b","1B":"#38bdf8","1C":"#a78bfa","2A":"#22c55e","2B":"#f59e0b"}
            as_c    = as_c_map.get(accum_stage,"#374151")
            as_disp = "—" if accum_stage == "NONE" else f"Stage {accum_stage}"

            rl_label = r.get("RSLeaderLabel","NEUTRAL")
            rl_c_map = {"LEADER":"#f59e0b","IMPROVING":"#22c55e","NEUTRAL":"#64748b","LAGGARD":"#ef4444"}
            rl_c     = rl_c_map.get(rl_label,"#64748b")
            rl_short = {"LEADER":"LEADER","IMPROVING":"IMPRV↑","NEUTRAL":"NEUT","LAGGARD":"LAGGARD"}.get(rl_label, rl_label)

            micro_lbl = r.get("MicroLabel","NEUTRAL_FLOW")
            mf_c_map  = {"STRONG_BUY_FLOW":"#22c55e","BUY_FLOW":"#86efac",
                         "NEUTRAL_FLOW":"#64748b","SELL_FLOW":"#fca5a5","STRONG_SELL_FLOW":"#ef4444"}
            mf_c     = mf_c_map.get(micro_lbl,"#64748b")
            mf_short = {"STRONG_BUY_FLOW":"↑↑ BUY","BUY_FLOW":"↑ BUY",
                        "NEUTRAL_FLOW":"~ NEUT","SELL_FLOW":"↓ SELL",
                        "STRONG_SELL_FLOW":"↓↓ SELL"}.get(micro_lbl,"~")

            mtf_lbl   = r.get("MTFLabel","NEUTRAL")
            mtf_c_map = {"BULL SYNC":"#22c55e","BULL LEAN":"#86efac","BEAR SYNC":"#ef4444",
                         "BEAR LEAN":"#fca5a5","DIVERGE":"#f59e0b"}
            mtf_c     = mtf_c_map.get(mtf_lbl,"#475569")
            mtf_short = {"BULL SYNC":"BULL⚡","BULL LEAN":"BULL~","BEAR SYNC":"BEAR⚡",
                         "BEAR LEAN":"BEAR~","DIVERGE":"DIVG"}.get(mtf_lbl,"NEUT")

            inst_lbl   = r.get("InstLabel","INST~")
            inst_c_map = {"INST↑":"#22c55e","INST↓":"#ef4444","INST~":"#475569"}
            inst_c     = inst_c_map.get(inst_lbl,"#475569")
            inst_short = {"INST↑":"↑ BUY","INST↓":"↓ SELL","INST~":"~ NEUT"}.get(inst_lbl,"~")

            def _icell(label, value, color, dim=False):
                bg  = f"{color}18" if not dim else "#37415118"
                brd = f"{color}40" if not dim else "#37415130"
                vc  = f"{color}cc" if not dim else "#47556955"
                return (
                    f'<div style="background:{bg};border:1px solid {brd};border-radius:6px;padding:4px 6px;min-width:0;">'
                    f'<div style="color:#475569;font-size:7.5px;letter-spacing:.05em;text-transform:uppercase;margin-bottom:2px;">{label}</div>'
                    f'<div style="color:{vc};font-family:JetBrains Mono,monospace;font-size:10px;font-weight:700;'
                    f'white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">{value}</div>'
                    f'</div>'
                )

            intel_grid = (
                f'<div style="padding:6px 10px 7px;border-top:1px solid #1e2a3a;">'
                f'<div style="color:#334155;font-size:7.5px;letter-spacing:.08em;text-transform:uppercase;margin-bottom:5px;">Intelligence</div>'
                f'<div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:4px;">'
                + _icell("Smart $", sm_short,  sm_c,   dim=(sm_verdict=="NEUTRAL"))
                + _icell("Stage",   as_disp,   as_c,   dim=(accum_stage=="NONE"))
                + _icell("RS Lead", rl_short,  rl_c,   dim=(rl_label=="NEUTRAL"))
                + _icell("Flow",    mf_short,  mf_c,   dim=(micro_lbl=="NEUTRAL_FLOW"))
                + _icell("MTF",     mtf_short, mtf_c,  dim=(mtf_lbl not in mtf_c_map))
                + _icell("Inst",    inst_short, inst_c, dim=(inst_lbl=="INST~"))
                + f'</div></div>'
            )

            # ── R:R visual bar ────────────────────────────────────────────────
            rr_bar_pct = min(int((rr / 4) * 100), 100) if rr else 0

            # ── Compact metrics strip (RSI · RS RNK · ATR · ADX) ─────────────
            c_rsi_val = r.get("RSI", "—")
            c_rs_rank = r.get("RS_Rank", 50)
            c_atr_val = r.get("ATR", "—")
            c_adx_val = r.get("ADX", "—")
            conf_metrics_grid = (
                f'<div style="display:grid;grid-template-columns:1fr 1fr 1fr 1fr;'
                f'gap:0;padding:6px 12px;border-top:1px solid #1e2a3a;">'
                f'<div><div style="color:#475569;font-size:8px;">RSI</div>'
                f'<div style="font-family:JetBrains Mono,monospace;color:#94a3b8;font-size:11px;font-weight:600;">{c_rsi_val}</div></div>'
                f'<div><div style="color:#475569;font-size:8px;">RS RNK</div>'
                f'<div style="font-family:JetBrains Mono,monospace;color:#94a3b8;font-size:11px;font-weight:600;">{c_rs_rank}</div></div>'
                f'<div><div style="color:#475569;font-size:8px;">ATR</div>'
                f'<div style="font-family:JetBrains Mono,monospace;color:#94a3b8;font-size:11px;font-weight:600;">{c_atr_val}</div></div>'
                f'<div><div style="color:#475569;font-size:8px;">ADX</div>'
                f'<div style="font-family:JetBrains Mono,monospace;color:#94a3b8;font-size:11px;font-weight:600;">{c_adx_val}</div></div>'
                f'</div>'
            )

            return (
                f'<div style="background:#07101e;border:1px solid {border_color};'
                f'border-top:3px solid {border_color};border-radius:10px;'
                f'overflow:hidden;min-width:210px;max-width:300px;flex:1 1 210px;">'

                # ── Header: symbol · phase · action ──────────────────────────
                f'<div style="display:flex;align-items:center;padding:9px 12px 8px;'
                f'gap:7px;background:#0b1422;border-bottom:1px solid #1e2a3a;">'
                f'<div style="flex:1;min-width:0;">'
                f'<div style="display:flex;align-items:center;gap:5px;">'
                f'<span style="font-family:Syne,sans-serif;color:#f1f5f9;font-size:15px;font-weight:700;">{sym}</span>'
                f'{stale_dot}{earn_html}</div>'
                f'<div style="display:flex;align-items:center;gap:4px;margin-top:3px;">'
                f'<span style="background:{phase_col}20;color:{phase_col};font-size:9px;font-weight:600;'
                f'padding:1px 6px;border-radius:3px;border:1px solid {phase_col}40;">'
                f'{phase_icon} {phase}{(" "+ph_arrow) if ph_arrow else ""}</span>'
                f'<span style="color:#475569;font-size:9px;">{sector}</span>'
                f'</div></div>'
                f'<span style="background:{act_bg};border:1px solid {act_brd};color:{act_txt};'
                f'padding:3px 9px;border-radius:5px;font-size:10px;font-weight:700;">{act}</span>'
                f'</div>'

                # ── Price row + score ─────────────────────────────────────────
                f'<div style="display:flex;align-items:center;justify-content:space-between;'
                f'padding:8px 12px;border-bottom:1px solid #1e2a3a;">'
                f'<div>'
                f'<div style="font-family:JetBrains Mono,monospace;color:#f8fafc;font-size:20px;font-weight:700;line-height:1;">₹{ltp:,.2f}</div>'
                f'<div style="font-family:JetBrains Mono,monospace;color:{chg_col};font-size:10px;margin-top:3px;">{chg_arr} {chg_str}</div>'
                f'</div>'
                f'<div style="text-align:right;">'
                f'<div style="color:{score_col};font-family:JetBrains Mono,monospace;font-size:22px;font-weight:700;line-height:1;">{score:.0f}</div>'
                f'<div style="color:#475569;font-size:8px;margin-top:2px;">score / 100</div>'
                f'<div style="background:#1e2a3a;border-radius:2px;width:60px;height:3px;margin-top:4px;margin-left:auto;">'
                f'<div style="background:{score_col};width:{min(int(score),100)}%;height:3px;border-radius:2px;"></div></div>'
                f'<div style="color:{conf_col};font-size:8px;margin-top:2px;">{conf}% confidence</div>'
                f'</div></div>'

                # ── Trade plan: entry → stop → target ────────────────────────
                f'<div style="background:#050d18;border-bottom:1px solid #1e2a3a;">'
                f'<div style="padding:5px 12px 3px;">'
                f'<div style="color:#334155;font-size:7.5px;letter-spacing:.08em;text-transform:uppercase;margin-bottom:4px;">Trade plan</div>'
                f'<div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:1px;">'

                # Entry cell
                f'<div style="background:#0f1e30;border-radius:6px 0 0 6px;padding:6px 8px;">'
                f'<div style="color:#64748b;font-size:7.5px;text-transform:uppercase;letter-spacing:.05em;">Buy around</div>'
                f'<div style="color:#e2e8f0;font-family:JetBrains Mono,monospace;font-size:11px;font-weight:700;margin-top:1px;">{entry_disp}</div>'
                f'<div style="color:#334155;font-size:8px;margin-top:1px;">entry zone</div>'
                f'</div>'

                # Stop cell
                f'<div style="background:#1a0f0f;border-radius:0;padding:6px 8px;">'
                f'<div style="color:#64748b;font-size:7.5px;text-transform:uppercase;letter-spacing:.05em;">Exit if wrong</div>'
                f'<div style="color:#f87171;font-family:JetBrains Mono,monospace;font-size:11px;font-weight:700;margin-top:1px;">{_p(sl)}</div>'
                f'<div style="color:#7f1d1d;font-size:8px;margin-top:1px;">{"−"+str(round(risk_pct,1))+"% risk" if risk_pct else "stop loss"}</div>'
                f'</div>'

                # Target cell
                f'<div style="background:#0a1a10;border-radius:0 6px 6px 0;padding:6px 8px;">'
                f'<div style="color:#64748b;font-size:7.5px;text-transform:uppercase;letter-spacing:.05em;">Take profit</div>'
                f'<div style="color:#4ade80;font-family:JetBrains Mono,monospace;font-size:11px;font-weight:700;margin-top:1px;">{_p(t2 or t1)}</div>'
                f'<div style="color:{rr_col};font-size:8px;font-weight:600;margin-top:1px;">R:R = {rr_str}</div>'
                f'</div></div>'

                # All targets row
                f'<div style="display:flex;gap:8px;padding:4px 8px 6px;align-items:center;">'
                f'<span style="color:#334155;font-size:8px;flex-shrink:0;">All targets →</span>'
                f'<span style="color:#86efac;font-family:JetBrains Mono,monospace;font-size:9px;">{_p(t1)}</span>'
                f'<span style="color:#4ade80;font-family:JetBrains Mono,monospace;font-size:9px;font-weight:600;">{_p(t2)}</span>'
                f'<span style="color:#22c55e;font-family:JetBrains Mono,monospace;font-size:9px;">{_p(t3)}</span>'
                f'<div style="flex:1;background:#1e2a3a;border-radius:2px;height:3px;margin-left:4px;">'
                f'<div style="background:{rr_col};width:{rr_bar_pct}%;height:3px;border-radius:2px;"></div></div>'
                f'</div></div></div>'

                # ── Caution alert only (RSI extended, etc.) ──────────────────
                + (f'<div style="padding:3px 12px 2px;border-top:1px solid #1e2a3a;">'
                   + caution_html
                   + f'</div>' if caution else '')

                # ── Intelligence grid ─────────────────────────────────────────
                + intel_grid

                # ── Compact metrics strip (RSI · RS RNK · ATR · ADX) ─────────
                + conf_metrics_grid

                # ── Exhaustion warning ────────────────────────────────────────
                + ext_html +

                f'</div>'
            )

        ACTIONABLE_PHASES={PHASE_ENTRY,PHASE_CONT,PHASE_BRK}
        actionable=[r for r in st.session_state.results
                    if r.get("Phase") in ACTIONABLE_PHASES and r["Action"] in ("BUY","STRONG BUY","PRE-CONFIRM")]
        phase_rank={PHASE_BRK:0,PHASE_CONT:1,PHASE_ENTRY:2}
        actionable.sort(key=lambda x:(phase_rank.get(x.get("Phase"),9),-x["Score"]))
        top_act=actionable[:15]

        # ── v15.5: EMERGING MOMENTUM CARD ─────────────────────────────────────
        _EM_COLORS = {
            "IGNITING": ("#f59e0b","#f59e0b22"),
            "BUILDING": ("#22c55e","#22c55e22"),
            "COILING":  ("#8b5cf6","#8b5cf622"),
            "LATENT":   ("#38bdf8","#38bdf822"),
            "QUIET":    ("#475569","#47556922"),
        }
        _EM_COMPONENTS = [
            ("RS Accel",    "EmRSAccel",     15, "📈"),
            ("ATR Cmprss",  "EmATRCompress", 15, "🗜"),
            ("RVOL Accel",  "EmRVolAccel",   15, "📊"),
            ("EMA Conv",    "EmEMAConv",     15, "🔀"),
            ("Sqz Press",   "EmSqzPressure", 15, "🔄"),
            ("Sector Mom",  "EmSectorMom",   10, "🏭"),
            ("Range Exp",   "EmORExpansion", 15, "🚀"),
        ]

        def make_emerging_card(i, r):
            sym   = r["Symbol"]; ltp = r["LTP"]; chg = r["%Change"]
            em    = r.get("EmScore", 0); lbl = r.get("EmLabel","QUIET")
            pca   = r.get("PCAScore", 0); pca_lbl = r.get("PCALabel","NONE")
            phase = r.get("Phase", PHASE_IDLE)
            act   = r.get("Action","SKIP"); sector = r.get("Sector","—")
            # Combined readiness: EmScore × 0.55 + PCA × 0.45
            readiness = round(em * 0.55 + pca * 0.45, 1)
            em_c, em_bg = _EM_COLORS.get(lbl, ("#475569","#47556922"))
            _PCA_COLORS = {
                "ACCUMULATING": ("#22c55e","#22c55e22"),
                "BUILDING":     ("#38bdf8","#38bdf822"),
                "FORMING":      ("#a78bfa","#a78bfa22"),
                "WEAK":         ("#64748b","#64748b22"),
                "NONE":         ("#374151","#37415122"),
            }
            pca_c, pca_bg = _PCA_COLORS.get(pca_lbl, ("#374151","#37415122"))
            chg_col = "#22c55e" if chg >= 0 else "#ef4444"
            chg_arr = "▲" if chg >= 0 else "▼"
            chg_str = f"+{chg:.2f}%" if chg >= 0 else f"{chg:.2f}%"
            phase_col = _phase_color(phase)
            act_bg, act_brd, act_txt = _action_colors(act)

            # ── Squeeze / Vol-Contraction strip (price-area only) ─────────────
            sqz_badge = ('<span style="background:#8b5cf622;border:1px solid #8b5cf655;color:#a78bfa;'
                         'padding:1px 5px;border-radius:3px;font-size:9px;margin-right:3px;">🔄 SQZ</span>'
                         if r.get("Squeeze") else "")
            vc_badge  = ('<span style="background:#0ea5e922;border:1px solid #0ea5e955;color:#38bdf8;'
                         'padding:1px 5px;border-radius:3px;font-size:9px;margin-right:3px;">VC</span>'
                         if r.get("VolRatio", 1.0) < 0.75 else "")

            # ── Resolve all 6 intelligence signal values + colors ─────────────
            # Smart Money
            sm_verdict = r.get("SmartMoneyVerdict","NEUTRAL")
            sm_c_map   = {"MARKUP_READY":"#f59e0b","ACCUMULATING":"#22c55e",
                          "ABSORBING":"#38bdf8","NEUTRAL":"#64748b","DISTRIBUTING":"#ef4444"}
            sm_c       = sm_c_map.get(sm_verdict,"#64748b")
            sm_short   = {"MARKUP_READY":"MKUP▲","ACCUMULATING":"ACCUM","ABSORBING":"ABSO",
                          "NEUTRAL":"NEUT","DISTRIBUTING":"DIST▼"}.get(sm_verdict, sm_verdict[:5])

            # Accumulation Stage
            accum_stage = r.get("AccumStage","NONE")
            as_c_map    = {"NONE":"#374151","1A":"#64748b","1B":"#38bdf8",
                           "1C":"#a78bfa","2A":"#22c55e","2B":"#f59e0b"}
            as_c        = as_c_map.get(accum_stage,"#374151")
            as_disp     = "—" if accum_stage == "NONE" else f"Stage {accum_stage}"

            # RS Leadership
            rl_label = r.get("RSLeaderLabel","NEUTRAL")
            rl_c_map = {"LEADER":"#f59e0b","IMPROVING":"#22c55e","NEUTRAL":"#64748b","LAGGARD":"#ef4444"}
            rl_c     = rl_c_map.get(rl_label,"#64748b")
            rl_short = {"LEADER":"LEADER","IMPROVING":"IMPRV↑","NEUTRAL":"NEUT","LAGGARD":"LAGGARD"}.get(rl_label,rl_label)

            # Microstructure Flow
            micro_lbl = r.get("MicroLabel","NEUTRAL_FLOW")
            mf_c_map  = {"STRONG_BUY_FLOW":"#22c55e","BUY_FLOW":"#86efac",
                         "NEUTRAL_FLOW":"#64748b","SELL_FLOW":"#fca5a5","STRONG_SELL_FLOW":"#ef4444"}
            mf_c      = mf_c_map.get(micro_lbl,"#64748b")
            mf_short  = {"STRONG_BUY_FLOW":"↑↑ BUY","BUY_FLOW":"↑ BUY",
                         "NEUTRAL_FLOW":"~ NEUT","SELL_FLOW":"↓ SELL",
                         "STRONG_SELL_FLOW":"↓↓ SELL"}.get(micro_lbl,"~")

            # MTF Alignment
            mtf_lbl   = r.get("MTFLabel","NEUTRAL")
            mtf_c_map = {"BULL SYNC":"#22c55e","BULL LEAN":"#86efac","BEAR SYNC":"#ef4444",
                         "BEAR LEAN":"#fca5a5","DIVERGE":"#f59e0b"}
            mtf_c     = mtf_c_map.get(mtf_lbl,"#475569")
            mtf_short = {"BULL SYNC":"BULL⚡","BULL LEAN":"BULL~","BEAR SYNC":"BEAR⚡",
                         "BEAR LEAN":"BEAR~","DIVERGE":"DIVG"}.get(mtf_lbl,"NEUT")

            # Institutional Activity
            inst_lbl   = r.get("InstLabel","INST~")
            inst_c_map = {"INST↑":"#22c55e","INST↓":"#ef4444","INST~":"#475569"}
            inst_c     = inst_c_map.get(inst_lbl,"#475569")
            inst_short = {"INST↑":"↑ BUY","INST↓":"↓ SELL","INST~":"~ NEUT"}.get(inst_lbl,"~")

            # ── Unified 3×2 intelligence grid ─────────────────────────────────
            def _intel_cell(label, value, color, dim=False):
                val_opacity = "55" if dim else "cc"
                bg = f"{color}18" if not dim else "#37415118"
                brd = f"{color}40" if not dim else "#37415130"
                return (
                    f'<div style="background:{bg};border:1px solid {brd};border-radius:6px;'
                    f'padding:4px 6px;min-width:0;">'
                    f'<div style="color:#475569;font-size:7.5px;letter-spacing:.05em;'
                    f'text-transform:uppercase;margin-bottom:2px;">{label}</div>'
                    f'<div style="color:{color}{val_opacity};font-family:JetBrains Mono,monospace;'
                    f'font-size:10px;font-weight:700;white-space:nowrap;overflow:hidden;'
                    f'text-overflow:ellipsis;">{value}</div>'
                    f'</div>'
                )

            intel_grid = (
                f'<div style="padding:6px 10px 7px;border-top:1px solid #1e1e40;">'
                f'<div style="color:#334155;font-size:7.5px;letter-spacing:.08em;'
                f'text-transform:uppercase;margin-bottom:5px;">Intelligence</div>'
                f'<div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:4px;">'
                + _intel_cell("Smart $", sm_short, sm_c, dim=(sm_verdict=="NEUTRAL"))
                + _intel_cell("Stage",   as_disp,  as_c, dim=(accum_stage=="NONE"))
                + _intel_cell("RS Lead", rl_short,  rl_c, dim=(rl_label=="NEUTRAL"))
                + _intel_cell("Flow",    mf_short,  mf_c, dim=(micro_lbl=="NEUTRAL_FLOW"))
                + _intel_cell("MTF",     mtf_short, mtf_c, dim=(mtf_lbl not in mtf_c_map))
                + _intel_cell("Inst",    inst_short, inst_c, dim=(inst_lbl=="INST~"))
                + f'</div></div>'
            )

            # ── Compact 4-cell metrics grid (RSI · RS Rank · ATR · ADX) ───────
            rsi_val = r.get("RSI","—"); rs_rank = r.get("RS_Rank", 50)
            atr_val = r.get("ATR","—"); adx_val = r.get("ADX","—")
            metrics_grid = (
                f'<div style="display:grid;grid-template-columns:1fr 1fr 1fr 1fr;'
                f'gap:0;padding:6px 12px;border-top:1px solid #1e1e40;">'
                f'<div><div style="color:#475569;font-size:8px;">RSI</div>'
                f'<div style="font-family:JetBrains Mono,monospace;color:#94a3b8;font-size:11px;font-weight:600;">{rsi_val}</div></div>'
                f'<div><div style="color:#475569;font-size:8px;">RS RNK</div>'
                f'<div style="font-family:JetBrains Mono,monospace;color:#94a3b8;font-size:11px;font-weight:600;">{rs_rank}</div></div>'
                f'<div><div style="color:#475569;font-size:8px;">ATR</div>'
                f'<div style="font-family:JetBrains Mono,monospace;color:#94a3b8;font-size:11px;font-weight:600;">{atr_val}</div></div>'
                f'<div><div style="color:#475569;font-size:8px;">ADX</div>'
                f'<div style="font-family:JetBrains Mono,monospace;color:#94a3b8;font-size:11px;font-weight:600;">{adx_val}</div></div>'
                f'</div>'
            )

            return (
                f'<div style="background:#0e0e1c;border:1.5px solid {em_c}55;border-radius:12px;'
                f'overflow:hidden;min-width:210px;max-width:300px;flex:1 1 210px;">'
                # ── Header: symbol + dual score chips + phase/action ──────────
                f'<div style="background:{em_bg};border-bottom:1px solid {em_c}33;padding:8px 12px 7px;'
                f'display:flex;align-items:center;gap:8px;">'
                f'<div style="flex:1;">'
                f'<div style="font-family:Syne,sans-serif;color:#e8e8f4;font-size:15px;font-weight:700;">{sym}</div>'
                f'<div style="font-size:9px;color:#94a3b8;">{sector}</div>'
                f'</div>'
                f'<div style="text-align:right;">'
                f'<div style="display:flex;gap:3px;justify-content:flex-end;flex-wrap:wrap;">'
                f'<span style="background:{em_c};color:#0a0a0f;font-family:JetBrains Mono,monospace;'
                f'font-size:10px;font-weight:700;padding:2px 6px;border-radius:4px;">EM {em:.0f}</span>'
                f'<span style="background:{pca_c};color:#0a0a0f;font-family:JetBrains Mono,monospace;'
                f'font-size:10px;font-weight:700;padding:2px 6px;border-radius:4px;">PCA {pca:.0f}</span>'
                f'</div>'
                f'<div style="margin-top:4px;display:flex;gap:3px;justify-content:flex-end;">'
                f'<span style="background:{phase_col}22;border:1px solid {phase_col}55;color:{phase_col};'
                f'padding:1px 5px;border-radius:3px;font-size:9px;">{phase}</span>'
                f'<span style="background:{act_bg};border:1px solid {act_brd};color:{act_txt};'
                f'padding:1px 5px;border-radius:3px;font-size:9px;font-weight:600;">{act}</span>'
                f'</div></div></div>'
                # ── Price row + SQZ/VC strip ───────────────────────────────────
                f'<div style="padding:8px 12px 5px;display:flex;justify-content:space-between;align-items:center;">'
                f'<div>'
                f'<div style="font-family:JetBrains Mono,monospace;color:#e8e8f4;font-size:18px;font-weight:600;">₹{ltp:,.2f}</div>'
                f'<div style="font-family:JetBrains Mono,monospace;color:{chg_col};font-size:10px;">{chg_arr} {chg_str}</div>'
                f'</div>'
                f'<div style="text-align:right;">{sqz_badge}{vc_badge}</div>'
                f'</div>'
                # ── Readiness bar ──────────────────────────────────────────────
                f'<div style="padding:2px 12px 6px;">'
                f'<div style="display:flex;justify-content:space-between;margin-bottom:2px;">'
                f'<span style="color:#475569;font-size:8px;letter-spacing:.06em;">READINESS</span>'
                f'<span style="color:#e8e8f4;font-family:JetBrains Mono,monospace;font-size:9px;font-weight:600;">{readiness:.0f}/100</span>'
                f'</div>'
                f'<div style="background:#1e1e40;border-radius:3px;height:5px;">'
                f'<div style="background:linear-gradient(90deg,{em_c},{pca_c});'
                f'width:{min(readiness,100):.0f}%;height:5px;border-radius:3px;"></div></div></div>'
                # ── Compact metrics grid ───────────────────────────────────────
                + metrics_grid
                # ── 3×2 Intelligence grid ─────────────────────────────────────
                + intel_grid +
                # ── Footer: SL + stage label ───────────────────────────────────
                f'<div style="background:#07070f;border-top:1px solid #1e1e40;padding:5px 12px;'
                f'display:flex;justify-content:space-between;align-items:center;">'
                f'<div>'
                f'<div style="color:#334155;font-size:7.5px;text-transform:uppercase;letter-spacing:.05em;">If it breaks down, exit at</div>'
                f'<div style="color:#f87171;font-family:JetBrains Mono,monospace;font-size:10px;font-weight:600;">SL ₹{r.get("SL",0):,.0f}</div>'
                f'</div>'
                f'<span style="color:{em_c};font-size:9px;font-weight:600;">'
                f'{lbl} · {pca_lbl}</span>'
                f'</div>'
                f'</div>'
            )

        # ── Render section based on Selection Mode ─────────────────────────────
        if selection_type == "🌱 Emerging":
            # ── EMERGING: stocks coiling BEFORE becoming obvious ───────────────
            em_candidates = [
                r for r in st.session_state.results
                if (r.get("EmScore", 0) >= em_min_score
                    or r.get("Action") == "PRE-CONFIRM")   # v15.7: always include PRE-CONFIRM
                and r.get("Phase") in (PHASE_SETUP, PHASE_IDLE, PHASE_ENTRY)
            ]
            # Sort: PRE-CONFIRM first, then by combined readiness
            def _em_sort_key(x):
                pc_boost = 20 if x.get("Action") == "PRE-CONFIRM" else 0
                return x.get("EmScore", 0) * 0.55 + x.get("PCAScore", 0) * 0.45 + pc_boost
            em_candidates.sort(key=_em_sort_key, reverse=True)
            top_em = em_candidates[:20]

            # Label distribution
            _em_dist = {"IGNITING":0,"BUILDING":0,"COILING":0,"LATENT":0}
            for r in em_candidates:
                lbl = r.get("EmLabel","QUIET")
                if lbl in _em_dist: _em_dist[lbl] += 1

            if top_em:
                _em_header_cols = st.columns(7)
                _em_header_cols[0].metric("🌱 Emerging Total", len(em_candidates))
                for idx,(lbl,col) in enumerate([("IGNITING","#f59e0b"),("BUILDING","#22c55e"),
                                                ("COILING","#8b5cf6"),("LATENT","#38bdf8")]):
                    _em_header_cols[idx+1].metric(lbl, _em_dist.get(lbl,0))
                _pca_accum = sum(1 for r in em_candidates if r.get("PCALabel") == "ACCUMULATING")
                _pre_confirm_cnt = sum(1 for r in em_candidates if r.get("Action") == "PRE-CONFIRM")
                _em_header_cols[5].metric("🛡 Accumulating", _pca_accum)
                _em_header_cols[6].metric("🔮 PRE-CONFIRM", _pre_confirm_cnt)

                with st.expander(
                    f"🌱 EMERGING + 🛡 PRE-CONFIRM — {len(top_em)} stocks building before breakout",
                    expanded=True,
                ):
                    st.markdown(
                        '<div style="color:#94a3b8;font-size:11px;font-family:JetBrains Mono,monospace;'
                        'margin-bottom:10px;">Each card shows two layers: <b>EmScore</b> (coil mechanics — '
                        'RS accel, ATR compress, squeeze) and <b>PCAScore</b> (buying pressure — '
                        'CMF trend, hidden accumulation, failed-breakdown absorption, volume asymmetry). '
                        'Combined Readiness = Em×0.55 + PCA×0.45. '
                        'Wait for phase upgrade to ENTRY/CONT/BREAKOUT before acting.</div>',
                        unsafe_allow_html=True,
                    )
                    em_cards_html = '<div style="display:flex;flex-wrap:wrap;gap:12px;align-items:stretch;">'
                    for i, r in enumerate(top_em):
                        em_cards_html += make_emerging_card(i, r)
                    em_cards_html += "</div>"
                    st.markdown(em_cards_html, unsafe_allow_html=True)
                    st.markdown(
                        '<div style="text-align:center;color:#3a3a60;font-size:10px;'
                        'font-family:JetBrains Mono,monospace;padding:6px 0 2px;">'
                        'ⓘ Emerging score identifies setups in formation — NOT entry signals. '
                        'Wait for phase upgrade to ENTRY/CONT/BREAKOUT before acting.</div>',
                        unsafe_allow_html=True,
                    )
            else:
                st.info(f"No emerging stocks found with score ≥ {em_min_score}. "
                        "Try lowering the minimum score or run a scan first.")

        else:
            # ── CONFIRMATION: stocks already in actionable phases ──────────────
            if top_act:
                with st.expander(
                    f"READY TO TRADE — {len(top_act)} stocks in ENTRY / CONT / BREAKOUT",
                    expanded=True
                ):
                    cards_html='<div style="display:flex;flex-wrap:wrap;gap:12px;align-items:stretch;">'
                    for i,r in enumerate(top_act):
                        cards_html+=make_card(i,r,"#22c55e55",show_entry=True)
                    cards_html+="</div>"
                    st.markdown(cards_html,unsafe_allow_html=True)
                    st.markdown(
                        '<div style="text-align:center;color:#3a3a60;font-size:10px;'
                        'font-family:JetBrains Mono,monospace;padding:4px 0 2px;">'
                        'ⓘ Data is indicator based. Confirm with price action.</div>',
                        unsafe_allow_html=True,
                    )
            else:
                st.info("No stocks in ENTRY / CONT / BREAKOUT phase.")

            # FIX-5: include WATCH action; lower threshold so SETUP stocks (45-57) appear
            watchlist=[r for r in st.session_state.results
                       if r.get("Phase") in (PHASE_SETUP,PHASE_IDLE)
                       and r["Score"]>=45
                       and r["Action"] in ("BUY","STRONG BUY","WATCH")][:10]
            if watchlist:
                with st.expander(f"WATCHLIST — {len(watchlist)} high-score, not yet ready",expanded=False):
                    cards_html='<div style="display:flex;flex-wrap:wrap;gap:12px;align-items:stretch;">'
                    for i,r in enumerate(watchlist):
                        cards_html+=make_card(i,r,"#f59e0b55",show_entry=False)
                    cards_html+="</div>"
                    st.markdown(cards_html,unsafe_allow_html=True)

        # ── Short list (derived from scan, shown in both modes) ────────────────
        short_candidates=derive_short_candidates(st.session_state.results,scan_mode_now,vix_val)
        if short_candidates:
            sh_now=sum(1 for s in short_candidates if s.verdict==SHORT_CONFIRMED)
            sh_sig=sum(1 for s in short_candidates if s.verdict==SHORT_SIGNAL)
            sh_watch=sum(1 for s in short_candidates if s.verdict==SHORT_WATCH)
            top_shorts=[s for s in short_candidates if s.verdict in (SHORT_CONFIRMED,SHORT_SIGNAL)][:12]
            with st.expander(f"🔻 SHORT LIST — {sh_now} SHORT NOW · {sh_sig} SIGNAL · {sh_watch} WATCH",
                             expanded=(sh_now>0)):
                if top_shorts:
                    sh_cards='<div style="display:flex;flex-wrap:wrap;gap:12px;align-items:stretch;">'
                    for i,sr in enumerate(top_shorts):
                        vc=SHORT_COLORS.get(sr.verdict,"#555577")
                        rr_c="#22c55e" if sr.risk_reward>=2 else ("#f59e0b" if sr.risk_reward>=1.5 else "#ef4444")
                        rsi_c="#ef4444" if sr.rsi_val>70 else ("#f59e0b" if sr.rsi_val>60 else "#cbd5e1")
                        bar=min(sr.short_score,100)
                        dchg=sr.day_change; dchg_s=f"+{dchg:.2f}%" if dchg>=0 else f"{dchg:.2f}%"
                        dchg_c="#22c55e" if dchg>=0 else "#ef4444"; dchg_arr="▲" if dchg>=0 else "▼"
                        hard_pills="".join(
                            f'<span style="background:#0b0b0f;border:1px solid rgba(239,68,68,0.20);'
                            f'color:#e2e8f0;padding:3px 8px;border-radius:6px;font-size:10px;'
                            f'font-weight:500;font-family:Inter,sans-serif;margin:2px;">{t}</span>'
                            for t in sr.hard_triggers)
                        soft_pills="".join(
                            f'<span style="background:#0b0b0f;border:1px solid rgba(239,68,68,0.14);'
                            f'color:#e2e8f0;padding:3px 8px;border-radius:6px;font-size:10px;'
                            f'font-weight:500;font-family:Inter,sans-serif;margin:2px;">{t}</span>'
                            for t in sr.soft_triggers)
                        ext_badge=(f'<span style="background:#0b0b0f;border:1px solid rgba(239,68,68,0.18);'
                                   f'color:#e2e8f0;padding:3px 8px;border-radius:6px;font-size:10px;'
                                   f'font-weight:500;font-family:Inter,sans-serif;margin:2px;">'
                                   f'EXT {sr.ext_n} — short fuel</span>') if sr.ext_n>=2 else ""
                        sh_cards+=(
                            f'<div style="background:#1b1113;border:1px solid {vc}55;border-radius:12px;'
                            f'overflow:hidden;min-width:240px;max-width:340px;flex:1 1 240px;">'
                            f'<div style="display:flex;align-items:center;padding:12px 16px 10px;'
                            f'border-bottom:1px solid rgba(255,255,255,0.08);gap:10px;">'
                            f'<div style="background:{vc}22;color:{vc};font-family:JetBrains Mono,monospace;'
                            f'font-size:12px;font-weight:700;padding:4px 8px;border-radius:6px;min-width:32px;text-align:center;">{i+1:02d}</div>'
                            f'<div style="font-family:Syne,sans-serif;color:#f0e8e8;font-size:16px;font-weight:700;flex:1;">{sr.symbol}</div>'
                            f'<span style="background:{vc}22;border:1px solid {vc};color:{vc};'
                            f'padding:4px 10px;border-radius:5px;font-size:11px;font-weight:700;">▼ {sr.verdict}</span>'
                            f'<span style="background:#1e1e40;color:#cbd5e1;font-family:JetBrains Mono,monospace;'
                            f'font-size:11px;padding:4px 8px;border-radius:5px;">{sr.short_score}</span>'
                            f'</div>'
                            f'<div style="display:flex;padding:12px 16px;gap:0;">'
                            f'<div style="flex:0 0 45%;padding-right:16px;border-right:1px solid #1e1e40;">'
                            f'<div style="font-family:JetBrains Mono,monospace;color:#f0e8e8;font-size:22px;font-weight:600;line-height:1;">₹{sr.current_price:,.1f}</div>'
                            f'<div style="font-family:JetBrains Mono,monospace;color:{dchg_c};font-size:13px;margin-top:4px;font-weight:500;">{dchg_s} {dchg_arr}</div>'
                            f'<div style="color:#f8fafc;font-size:11px;margin-top:3px;font-family:JetBrains Mono,monospace;">Short zone</div>'
                            f'<div style="color:#f8fafc;font-size:12px;font-weight:600;font-family:JetBrains Mono,monospace;">₹{sr.entry_zone_lo:,.1f}–₹{sr.entry_zone_hi:,.1f}</div>'
                            f'</div>'
                            f'<div style="flex:1;padding-left:16px;">'
                            f'<div style="display:flex;gap:6px;flex-wrap:wrap;">'
                            f'<span style="background:#1e1e40;padding:5px 8px;border-radius:5px;"><span style="color:#cbd5e1;font-size:9px;display:block;">SL ▲</span>'
                            f'<span style="color:#ef4444;font-family:JetBrains Mono,monospace;font-size:11px;font-weight:600;">₹{sr.stop_loss:,.1f}</span></span>'
                            f'<span style="background:#1e1e40;padding:5px 8px;border-radius:5px;"><span style="color:#cbd5e1;font-size:9px;display:block;">R:R</span>'
                            f'<span style="color:{rr_c};font-weight:700;font-size:12px;">1:{sr.risk_reward:.1f}</span></span>'
                            f'<span style="background:#1e1e40;padding:5px 8px;border-radius:5px;"><span style="color:#cbd5e1;font-size:9px;display:block;">RSI</span>'
                            f'<span style="color:{rsi_c};font-family:JetBrains Mono,monospace;font-size:11px;">{sr.rsi_val:.0f}</span></span>'
                            f'</div></div></div>'
                            f'<div style="padding:6px 16px 8px;background:#0a0808;display:flex;gap:16px;">'
                            f'<div><span style="color:#cbd5e1;font-size:9px;">T1 ▼</span>'
                            f'<div style="font-family:JetBrains Mono,monospace;color:#22aa88;font-size:11px;">₹{sr.target1:,.1f}</div></div>'
                            f'<div><span style="color:#cbd5e1;font-size:9px;">T2 ▼</span>'
                            f'<div style="font-family:JetBrains Mono,monospace;color:#22aa88;font-size:12px;font-weight:600;">₹{sr.target2:,.1f}</div></div>'
                            f'<div><span style="color:#cbd5e1;font-size:9px;">T3 ▼</span>'
                            f'<div style="font-family:JetBrains Mono,monospace;color:#22aa88;font-size:11px;">₹{sr.target3:,.1f}</div></div>'
                            f'<div style="margin-left:auto;text-align:right;">'
                            f'<span style="color:#cbd5e1;font-size:9px;">RS · {sr.sector}</span>'
                            f'<div style="color:#aaa;font-family:JetBrains Mono,monospace;font-size:11px;">RS{sr.rs_rank}</div></div>'
                            f'</div>'
                            f'<div style="padding:0 16px 6px;"><div style="background:#1e1e40;border-radius:2px;height:3px;">'
                            f'<div style="background:{vc};width:{bar}%;height:3px;border-radius:2px;"></div></div></div>'
                            f'<div style="padding:4px 16px 10px;">{hard_pills}{soft_pills}{ext_badge}</div>'
                            f'</div>'
                        )
                    sh_cards+="</div>"
                    st.markdown(sh_cards,unsafe_allow_html=True)
                    st.markdown(
                        '<div style="text-align:center;color:#94a3b8;font-size:11px;'
                        'font-family:JetBrains Mono,monospace;padding:10px 0 4px;line-height:1.6;">'
                        'ⓘ Short candidates derived from scan engine — confirm with price action.<br>'
                        '<span style="color:#fca5a5;font-weight:600;">Short selling carries elevated risk — always use disciplined SL management.</span>'
                        '</div>',unsafe_allow_html=True)

        # ── Export BUY results ──────────────────────────────────────────────
        if results:
            buy_rows=[r for r in results if r["Action"] in ("BUY","STRONG BUY")]
            if buy_rows:
                csv=pd.DataFrame(buy_rows).drop(columns=["ExtFlags"],errors="ignore").to_csv(index=False)
                ts=datetime.now().strftime("%Y%m%d_%H%M%S")
                st.download_button("Export BUY results",csv,
                                   f"NSE_Scan_{st.session_state.scan_mode}_{ts}.csv","text/csv")
        elif st.session_state.results:
            st.warning("No stocks match current filters.")
        else:
            st.info("Select Universe + Mode, then press SCAN.")

# ══════════════════════════════════════════════════════════════════════════════
# BREADTH ENGINE TAB (unchanged)
# ══════════════════════════════════════════════════════════════════════════════

with tab_breadth:
    all_results=st.session_state.results
    if not all_results:
        st.info("Run a scan first to see breadth data.")
    else:
        breadth=compute_breadth(all_results)
        b_sig,b_col=breadth["breadth_signal"]
        st.markdown(
            f'<div style="background:{b_col}11;border:1px solid {b_col}33;border-radius:8px;'
            f'padding:10px 16px;margin-bottom:14px;">'
            f'<span style="font-family:Syne,sans-serif;font-size:15px;color:{b_col};">'
            f'Market Breadth: <strong>{b_sig}</strong></span></div>',
            unsafe_allow_html=True,
        )
        bm1,bm2,bm3,bm4,bm5,bm6=st.columns(6)
        bm1.metric("% Above EMA50",f'{breadth["pct_above_ema50"]}%')
        bm2.metric("% in BREAKOUT",f'{breadth["pct_breakout"]}%')
        bm3.metric("Advancing",breadth["advancing"])
        bm4.metric("Declining",breadth["declining"])
        bm5.metric("A/D Ratio",breadth["ad_ratio"])
        bm6.metric("Liquid Stocks",breadth["liquid_count"])
        gated_n=sum(1 for r in all_results if r.get("BreadthGated"))
        if gated_n:
            st.warning(f"🔵 **Breadth Gate** — {gated_n} BREAKOUT/CONT signals capped to WATCH")
        sector_data=breadth["sector_avg"]
        if sector_data:
            sec_df=pd.DataFrame([
                {"Sector":k,"Avg Score":v,"Count":sum(1 for r in all_results if r.get("Sector")==k)}
                for k,v in sorted(sector_data.items(),key=lambda x:-x[1])
            ])
            hm_html='<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(170px,1fr));gap:8px;">'
            for _,row in sec_df.iterrows():
                score=row["Avg Score"]
                bar_col="#22c55e" if score>=70 else ("#d97706" if score>=55 else "#ef4444")
                pct=min(100,score)
                hm_html+=(
                    f'<div style="background:#111120;border:1px solid #1e1e40;border-radius:7px;padding:10px 12px;">'
                    f'<div style="color:#e8e8f4;font-size:11px;font-weight:600;font-family:DM Sans,sans-serif;">{row["Sector"]}</div>'
                    f'<div style="color:#cbd5e1;font-size:10px;font-family:JetBrains Mono,monospace;">{int(row["Count"])} stocks</div>'
                    f'<div style="background:#1e1e40;border-radius:2px;height:4px;margin:6px 0;">'
                    f'<div style="background:{bar_col};width:{pct}%;height:4px;border-radius:2px;"></div></div>'
                    f'<div style="color:{bar_col};font-size:15px;font-weight:600;font-family:JetBrains Mono,monospace;">{score}</div></div>'
                )
            hm_html+="</div>"
            st.markdown(hm_html,unsafe_allow_html=True)
        st.markdown("---")
        dist_data={"Advancing":breadth["advancing"],"Unchanged":breadth["unchanged"],"Declining":breadth["declining"]}
        dist_colors={"Advancing":"#22c55e","Unchanged":"#d97706","Declining":"#ef4444"}
        total_shown=sum(dist_data.values())
        dist_html='<div style="display:flex;gap:8px;">'
        for label,count in dist_data.items():
            pct2=round(count/total_shown*100,1) if total_shown else 0
            col=dist_colors[label]
            dist_html+=(
                f'<div style="flex:1;background:#111120;border:1px solid {col}33;border-radius:7px;padding:12px;text-align:center;">'
                f'<div style="color:{col};font-size:22px;font-weight:600;font-family:JetBrains Mono,monospace;">{count}</div>'
                f'<div style="color:#cbd5e1;font-size:11px;font-family:DM Sans,sans-serif;">{label}</div>'
                f'<div style="color:{col};font-size:11px;font-family:JetBrains Mono,monospace;">{pct2}%</div></div>'
            )
        dist_html+="</div>"
        st.markdown(dist_html,unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════════════════════
# DETAIL TAB (unchanged structure, adds ADX/Squeeze metrics)
# ══════════════════════════════════════════════════════════════════════════════

with tab_detail:
    all_results=st.session_state.results
    if not all_results:
        st.info("Run a scan first.")
    else:
        sel=st.selectbox("Select stock",[r["Symbol"] for r in all_results])
        r=next((x for x in all_results if x["Symbol"]==sel),None)
        if r:
            phase=r.get("Phase",PHASE_IDLE); chg=r["%Change"]
            conf=r.get("Confidence",0); conf_lbl,conf_col=confidence_label(conf)
            phases_order=[PHASE_IDLE,PHASE_SETUP,PHASE_ENTRY,PHASE_CONT,PHASE_BRK,PHASE_EXIT]
            ph_html='<div style="display:flex;gap:5px;margin-bottom:12px;flex-wrap:wrap;">'
            for ph in phases_order:
                active=ph==phase
                bg=PHASE_COLORS[ph] if active else "#1e1e40"
                brd=f"1px solid {PHASE_COLORS[ph]}" if active else "1px solid #1e1e40"
                ph_html+=(
                    f'<div style="background:{bg};border:{brd};color:{"#e8e8f4" if active else "#cbd5e1"};'
                    f'padding:4px 12px;border-radius:5px;font-size:11px;'
                    f'font-weight:{"600" if active else "400"};font-family:DM Sans,sans-serif;">'
                    f'{ph}{"  ◀" if active else ""}</div>'
                )
            ph_html+="</div>"
            st.markdown(ph_html,unsafe_allow_html=True)
            if r.get("BreadthGated"):
                st.warning("🔵 **Breadth Gated** — action capped to WATCH due to weak market breadth.")
            d1,d2,d3,d4,d5=st.columns(5)
            d1.metric("LTP",fmt(r["LTP"]),f"{'+' if chg>=0 else ''}{chg}%")
            d2.metric("Entry ⚡",fmt(r["Entry"]))
            d3.metric("Stop Loss",fmt(r["SL"]))
            d4.metric("Score",r["Score"])
            d5.metric("Confidence",f"{conf}% ({conf_lbl})")
            t1c,t2c,t3c,r1c=st.columns(4)
            t1c.metric("T1",fmt(r["T1"])); t2c.metric("T2",fmt(r["T2"]))
            t3c.metric("T3",fmt(r["T3"]))
            risk=round(r["Entry"]-r["SL"],2) if r.get("Entry") and r.get("SL") else 0
            r1c.metric("Risk/Share",fmt(risk))
            # v15 new indicator row
            adx_c,sq_c,vc_c=st.columns(3)
            adx_c.metric("ADX",f'{r.get("ADX","—")}',
                         delta="Strong" if (r.get("ADX") or 0)>=30 else "Weak",
                         delta_color="normal" if (r.get("ADX") or 0)>=30 else "inverse")
            sq_c.metric("BB/KC Squeeze","ON 🔄" if r.get("Squeeze") else "OFF")
            vc_c.metric("Vol Contraction",f'{r.get("VolRatio","—")}',
                        delta="Compressed" if (r.get("VolRatio") or 1)<0.75 else "Normal",
                        delta_color="normal" if (r.get("VolRatio") or 1)<0.75 else "off")
            # v15.3 category score breakdown
            st.markdown("**Score Breakdown (Category Weights)**")
            _cT=r.get("CatT",0); _cM=r.get("CatM",0); _cS=r.get("CatS",0)
            _cV=r.get("CatV",0); _cQ=r.get("CatQ",0)
            _cat_cols=st.columns(5)
            for _col,_lbl,_val,_mx,_tip in [
                (_cat_cols[0],"TREND",    _cT,30,"EMA stack · HTF · regime · cross"),
                (_cat_cols[1],"MOMENTUM", _cM,20,"RSI · 1M/3M/6M mom"),
                (_cat_cols[2],"STRUCTURE",_cS,20,"Phase · Fib zone · HH · RS rank"),
                (_cat_cols[3],"VOLUME",   _cV,15,"Vol ratio · ADX strength"),
                (_cat_cols[4],"QUALITY",  _cQ,15,"Squeeze · Vol contraction · Clean"),
            ]:
                _pct=int(_val/_mx*100) if _mx>0 else 0
                _col.metric(_lbl,f"{_val:.1f}/{_mx}",f"{_pct}%",
                            delta_color="normal" if _pct>=60 else ("off" if _pct>=30 else "inverse"))
            # v15.6 Pre-Confirmation Accumulation breakdown
            st.markdown("**Pre-Confirmation Accumulation (PCA)** — buying-pressure layer")
            _pca_score = r.get("PCAScore", 0); _pca_lbl = r.get("PCALabel", "NONE")
            _pca_col = {"ACCUMULATING":"#22c55e","BUILDING":"#38bdf8",
                        "FORMING":"#a78bfa","WEAK":"#64748b","NONE":"#374151"}.get(_pca_lbl,"#374151")
            st.markdown(
                f'<div style="background:{_pca_col}11;border:1px solid {_pca_col}33;border-radius:7px;'
                f'padding:7px 14px;margin-bottom:8px;display:flex;align-items:center;gap:12px;">'
                f'<span style="background:{_pca_col};color:#0a0a0f;padding:2px 10px;border-radius:4px;'
                f'font-family:JetBrains Mono,monospace;font-size:12px;font-weight:700;">'
                f'{_pca_lbl} · {_pca_score}</span>'
                f'<span style="color:#94a3b8;font-size:10px;">Detects institutional buying BEFORE price confirms</span>'
                f'</div>',
                unsafe_allow_html=True,
            )
            pca_c1,pca_c2,pca_c3,pca_c4=st.columns(4)
            pca_c1.metric("Relative CMF",    f'{r.get("PCACMFRel",0):.0f}/15',
                          delta="Active" if r.get("PCACMFRel",0)>=8 else None,
                          delta_color="normal" if r.get("PCACMFRel",0)>=8 else "off")
            pca_c2.metric("Vol Cmp Seq",     f'{r.get("PCAVolCmpSeq",0):.0f}/15',
                          delta="Active" if r.get("PCAVolCmpSeq",0)>=8 else None,
                          delta_color="normal" if r.get("PCAVolCmpSeq",0)>=8 else "off")
            pca_c3.metric("Hidden Accum",    f'{r.get("PCAHiddenAccum",0):.0f}/15',
                          delta="Active" if r.get("PCAHiddenAccum",0)>=8 else None,
                          delta_color="normal" if r.get("PCAHiddenAccum",0)>=8 else "off")
            pca_c4.metric("Effort/Result",   f'{r.get("PCAEffortResult",0):.0f}/15',
                          delta="Active" if r.get("PCAEffortResult",0)>=8 else None,
                          delta_color="normal" if r.get("PCAEffortResult",0)>=8 else "off")
            pca_c5,pca_c6,pca_c7,_ = st.columns(4)
            pca_c5.metric("NR Persistence",  f'{r.get("PCARangeCont",0):.0f}/10',
                          delta="Active" if r.get("PCARangeCont",0)>=6 else None,
                          delta_color="normal" if r.get("PCARangeCont",0)>=6 else "off")
            pca_c6.metric("Failed Breakdown", f'{r.get("PCAFailedBrkdn",0):.0f}/15',
                          delta="Active" if r.get("PCAFailedBrkdn",0)>=8 else None,
                          delta_color="normal" if r.get("PCAFailedBrkdn",0)>=8 else "off")
            pca_c7.metric("Vol Asymmetry",   f'{r.get("PCAVolAsym",0):.0f}/15',
                          delta="Active" if r.get("PCAVolAsym",0)>=8 else None,
                          delta_color="normal" if r.get("PCAVolAsym",0)>=8 else "off")
            # v15.1/15.2 pattern signals
            st.markdown("**Pattern Signals** *(enriched post-scan)*")
            _pat=r.get("Patterns",{})
            _vcp_d=_pat.get("vcp",{}); _avwap_d=_pat.get("avwap",{})
            _fibq_d=_pat.get("fib_quality",{}); _vdu_d=_pat.get("vol_dryup",{})
            _rvol_d=_pat.get("rel_vol",{}); _darv_d=_pat.get("darvas",{})
            pc1,pc2,pc3,pc4,pc5,pc6=st.columns(6)
            pc1.metric("VCP",f'{_vcp_d.get("vcp_grade","—")} ({_vcp_d.get("n_contractions",0)}×)',
                       delta="Confirmed" if _vcp_d.get("detected") else None,
                       delta_color="normal" if _vcp_d.get("detected") else "off")
            _av=_avwap_d.get("avwap"); _avp=_avwap_d.get("pct_above",0)
            pc2.metric("Anch.VWAP",f'₹{_av:,.1f}' if _av else "—",
                       delta=f'{_avp:+.1f}%',
                       delta_color="normal" if _avwap_d.get("price_above") else "inverse")
            pc3.metric("Fib Pullback",_fibq_d.get("grade","—"),
                       delta=f'Q:{_fibq_d.get("quality",0)}',
                       delta_color="normal" if _fibq_d.get("quality",0)>=60 else "off")
            pc4.metric("Vol Dry-up",f'{"×"*int(_vdu_d.get("intensity",0)) or "—"} ({_vdu_d.get("bars",0)}b)',
                       delta="Active" if _vdu_d.get("dry_up") else None,
                       delta_color="normal" if _vdu_d.get("dry_up") else "off")
            pc5.metric("Rel.Volume",_rvol_d.get("label","—"),
                       delta=f'{_rvol_d.get("rel_vol_pct",50):.0f}th · {_rvol_d.get("ratio",1):.1f}×',
                       delta_color="normal" if _rvol_d.get("rel_vol_pct",50)>=65 else "off")
            _dbrk=_darv_d.get("breakout"); _din=_darv_d.get("in_box")
            _dtop=_darv_d.get("box_top",0); _dbot=_darv_d.get("box_bottom",0)
            pc6.metric("Darvas","BREAKOUT" if _dbrk else ("IN BOX" if _din else "—"),
                       delta=f'₹{_dbot:,.0f}–₹{_dtop:,.0f}' if _dtop else None,
                       delta_color="normal" if _dbrk else "off")
            st.markdown("---")
            with st.expander("Position Sizing",expanded=True):
                _acct_size=st.session_state.get("account_size",500000)
                _risk_pct=st.session_state.get("risk_pct",0.02)
                _max_cap_pct=st.session_state.get("max_capital_pct",0.20)
                ps=position_size(account_size=_acct_size,entry=r["Entry"],sl=r["SL"],
                                 atr_val=r.get("ATR",risk),atr_mean=r.get("ATR_Mean",risk),
                                 vix_val=vix_val,risk_pct=_risk_pct,max_capital_pct=_max_cap_pct)
                ps1,ps2,ps3,ps4=st.columns(4)
                ps1.metric("Suggested Qty",ps["final_qty"])
                ps2.metric("Capital Used",fmt(ps["capital_used"]))
                ps3.metric("Max Loss",fmt(ps["max_loss"]))
                ps4.metric("Risk per Share",fmt(risk))
            ext_n=r.get("ExtN",0); ext_labels=r.get("ExtLabels",[]); ext_flags=r.get("ExtFlags",{})
            if ext_n==0:
                st.success("✅ No extension/exhaustion signals — structure is clean.")
            else:
                flag_desc={
                    "rsi_overheat":"Stock ran up too fast — buyers exhausted. Wait for cooldown.",
                    "atr_extension":"Today's range unusually large — possible blow-off.",
                    "parabolic":"Price jumped far more than normal in 3 bars. Hard to sustain.",
                    "ema_distance":"Price stretched way above its average. Pullback likely.",
                    "climactic_volume":"Huge volume spike with long upper wick — potential distribution.",
                    "mom_exhaustion":"Price rising but buying pressure quietly weakening.",
                    "bearish_div":"New high, but momentum didn't confirm it.",
                }
                with st.expander(f"⚠ {ext_n} Caution Signal{'s' if ext_n>1 else ''} — "
                                  f"{'DO NOT enter' if ext_n>=3 else 'Reduce size'}",expanded=True):
                    for fk,fa in ext_flags.items():
                        if fa:
                            ec="#ef4444" if ext_n>=3 else "#f59e0b"
                            st.markdown(f'<div style="color:{ec};font-size:12px;padding:3px 0;">'
                                        f'▸ <strong>{fk.replace("_"," ").title()}</strong> — '
                                        f'{flag_desc.get(fk,"")}</div>',unsafe_allow_html=True)
            info_cols=st.columns(4)
            info_cols[0].metric("RSI",r.get("RSI","—"))
            info_cols[1].metric("RS Rank",f'{r.get("RS_Rank",50)}/100')
            info_cols[2].metric("Liq (₹Cr/d)",r.get("AvgTradedCr","—"))
            info_cols[3].metric("Raw RS Diff",f"{r.get('RS',0):+.1f}%")

# ══════════════════════════════════════════════════════════════════════════════
# ANALYTICS TAB (unchanged)
# ══════════════════════════════════════════════════════════════════════════════

with tab_analytics:
    st.subheader("Signal Log & Outcome Tracking")
    log=st.session_state.signal_log
    if not log:
        st.info("No signals logged yet. Run a scan to populate.")
    else:
        log_df=pd.DataFrame(log); scan_mode_now=st.session_state.scan_mode
        log_df["stale"]=log_df.apply(
            lambda row:signal_is_stale(row["timestamp"],row.get("mode",scan_mode_now)),axis=1)
        log_df["age"]=log_df.apply(
            lambda row:signal_age_label(row["timestamp"],row.get("mode",scan_mode_now))[0],axis=1)
        total_sig=len(log_df); pending=len(log_df[log_df["outcome"]=="Pending"])
        stale_cnt=int(log_df["stale"].sum())
        wins=len(log_df[log_df["outcome"]=="Win"]); losses=len(log_df[log_df["outcome"]=="Loss"])
        win_rate=round(wins/(wins+losses)*100,1) if (wins+losses)>0 else None
        am1,am2,am3,am4=st.columns(4)
        am1.metric("Total Signals",total_sig); am2.metric("Pending",pending)
        am3.metric("Expired",stale_cnt); am4.metric("Win%",f"{win_rate}%" if win_rate else "—")
        display_cols=["timestamp","symbol","action","phase","score","confidence",
                      "rs_rank","entry","sl","t1","age","outcome","breadth_gated"]
        display_cols=[c for c in display_cols if c in log_df.columns]
        edited=st.data_editor(
            log_df[display_cols].tail(100),
            column_config={"outcome":st.column_config.SelectboxColumn("Outcome",
                            options=["Pending","Win","Loss","BE"],required=True),
                           "age":st.column_config.TextColumn("Age",disabled=True)},
            hide_index=True,use_container_width=True,
        )
        if edited is not None and len(edited)==len(log_df.tail(100)):
            for i,row in edited.iterrows():
                idx=len(log_df)-100+i
                if 0<=idx<len(log): log[idx]["outcome"]=row["outcome"]

# ══════════════════════════════════════════════════════════════════════════════
# PORTFOLIO TAB (unchanged)
# ══════════════════════════════════════════════════════════════════════════════

with tab_portfolio:
    st.markdown(
        '<div style="font-family:Syne,sans-serif;font-size:18px;font-weight:700;'
        'color:#e8e8f4;margin-bottom:12px;">💼 Open Positions & Exit Signals</div>',
        unsafe_allow_html=True,
    )
    with st.expander("➕ Add Position",expanded=False):
        pf1,pf2,pf3,pf4=st.columns([2,2,1,1])
        ap_sym=pf1.text_input("Symbol",key="pf_sym").upper()
        ap_entry=pf2.number_input("Entry Price ₹",min_value=0.01,value=100.0,step=0.5,key="pf_ep")
        ap_qty=pf3.number_input("Qty",min_value=1,value=100,step=1,key="pf_qty")
        ap_mode=pf4.selectbox("Mode",list(MODE_CFG.keys()),index=1,key="pf_mode")
        if st.button("Add",type="primary",key="pf_add_btn"):
            if ap_sym:
                add_position(ap_sym,ap_entry,int(ap_qty),ap_mode)
                st.success(f"Added {ap_sym}")
    positions=st.session_state.get("open_positions") or []
    if not positions:
        st.info("No open positions.")
    else:
        col_refresh,_=st.columns([1,5])
        with col_refresh:
            if st.button("🔄 Refresh Exit Signals",use_container_width=True,key="pf_refresh"):
                vix_pf,_=fetch_vix()
                with st.spinner("Scanning exits…"):
                    st.session_state["exit_results"]=run_exit_scan(positions,vix_pf)
        exit_res=st.session_state.get("exit_results",{})
        counts={EXIT_HOLD:0,EXIT_WATCH_LBL:0,EXIT_SIGNAL_LBL:0,EXIT_CONFIRM_LBL:0}
        for p in positions:
            if not isinstance(p,dict): continue
            sym=p.get("symbol")
            if not sym: continue
            er=exit_res.get(sym); lbl=er.verdict if er else EXIT_HOLD
            counts[lbl]=counts.get(lbl,0)+1
        p1,p2,p3,p4=st.columns(4)
        p1.metric("🟢 Hold",counts[EXIT_HOLD]); p2.metric("🟡 Watch",counts[EXIT_WATCH_LBL])
        p3.metric("🟠 Exit Signal",counts[EXIT_SIGNAL_LBL]); p4.metric("🔴 Exit Now",counts[EXIT_CONFIRM_LBL])
        valid_pos=[p for p in positions if isinstance(p,dict) and p.get("symbol")]

        # ── Build card HTML for a single position ─────────────────────────────
        def _pf_card_html(pos):
            sym=pos["symbol"]; er=exit_res.get(sym)
            verdict=er.verdict if er else EXIT_HOLD; ex_score=er.exit_score if er else 0
            triggers=er.triggers if er else []; trail_sl=er.trailing_stop if er else None
            entry_px=pos.get("entry_price",0); curr_px=(er.current_price if (er and er.current_price) else entry_px)
            qty=pos.get("qty",0); mode_p=pos.get("mode","Swing")
            day_pct=er.day_pct if er else 0.0
            pnl_pct=(curr_px-entry_px)/entry_px*100 if entry_px else 0
            pnl_col="#22c55e" if pnl_pct>=0 else "#ef4444"
            day_col="#22c55e" if day_pct>=0 else "#ef4444"
            day_str=f"+{day_pct:.2f}%" if day_pct>=0 else f"{day_pct:.2f}%"
            vc=EXIT_COLORS.get(verdict,"#22aa55"); bar=min(int(ex_score),100)
            sector=SECTOR_MAP.get(sym,"—")
            trig_rows="".join(
                f'<div style="padding:3px 0;border-bottom:1px solid #15152a;color:#c8d0e0;font-size:9.5px;">{t}</div>'
                for t in triggers) or '<div style="color:#3a3a60;font-size:9px;padding:4px 0;">No triggers</div>'
            trail_row=(
                f'<div style="display:flex;justify-content:space-between;padding:2px 12px;">'
                f'<span style="color:#cbd5e1;font-size:9px;">🎯 TRAIL SL</span>'
                f'<span style="font-family:JetBrains Mono,monospace;color:#f59e0b;font-size:12px;font-weight:600;">₹{trail_sl:,.2f}</span></div>'
            ) if trail_sl else ""
            return (
                f'<div style="background:#111120;border:1.5px solid {vc};border-radius:12px;'
                f'overflow:hidden;min-width:210px;max-width:300px;flex:1 1 210px;">'
                f'<div style="display:flex;justify-content:space-between;align-items:center;'
                f'padding:10px 12px 8px;border-bottom:1px solid #1e1e40;background:#0e0e1c;">'
                f'<div><span style="font-family:Syne,sans-serif;color:#e8e8f4;font-size:15px;font-weight:700;">{sym}</span>'
                f'<div style="color:#6b7280;font-size:9px;">{sector} · {mode_p}</div></div>'
                f'<span style="background:{vc}22;border:1px solid {vc};color:{vc};padding:2px 8px;'
                f'border-radius:5px;font-size:10px;font-weight:700;">{verdict}</span>'
                f'</div>'
                f'<div style="display:grid;grid-template-columns:1fr 1fr 1fr 1fr;gap:0;padding:8px 12px;">'
                f'<div><div style="color:#64748b;font-size:8px;">ENTRY</div>'
                f'<div style="font-family:JetBrains Mono,monospace;color:#94a3b8;font-size:11px;">₹{entry_px:,.2f}</div></div>'
                f'<div><div style="color:#64748b;font-size:8px;">CMP</div>'
                f'<div style="font-family:JetBrains Mono,monospace;color:#e2e8f0;font-size:11px;">₹{curr_px:,.2f}</div></div>'
                f'<div><div style="color:#64748b;font-size:8px;">DAY</div>'
                f'<div style="font-family:JetBrains Mono,monospace;color:{day_col};font-size:11px;font-weight:600;">{day_str}</div></div>'
                f'<div><div style="color:#64748b;font-size:8px;">P&L</div>'
                f'<div style="font-family:JetBrains Mono,monospace;color:{pnl_col};font-size:11px;font-weight:700;">{pnl_pct:+.1f}%</div></div>'
                f'</div>'
                + trail_row +
                f'<div style="padding:5px 12px 6px;background:#0e0e1c;border-top:1px solid #1a1a30;">'
                f'<div style="color:#475569;font-size:8px;margin-bottom:3px;">SIGNALS</div>'
                + trig_rows +
                f'</div>'
                f'<div style="padding:5px 12px 6px;border-top:1px solid #1a1a30;">'
                f'<div style="background:#1e1e40;border-radius:2px;height:3px;">'
                f'<div style="background:{vc};width:{bar}%;height:3px;border-radius:2px;"></div></div></div>'
                f'</div>'
            )

        # ── Group positions by verdict priority then render each group ─────────
        _group_order=[EXIT_CONFIRM_LBL, EXIT_SIGNAL_LBL, EXIT_WATCH_LBL, EXIT_HOLD]
        _group_labels={
            EXIT_CONFIRM_LBL:"🔴 Exit Now",
            EXIT_SIGNAL_LBL: "🟠 Exit Signal",
            EXIT_WATCH_LBL:  "🟡 Watch",
            EXIT_HOLD:       "🟢 Hold",
        }
        for _grp in _group_order:
            _grp_pos=[p for p in valid_pos
                      if (exit_res.get(p["symbol"]).verdict if exit_res.get(p["symbol"]) else EXIT_HOLD)==_grp]
            if not _grp_pos: continue
            vc_grp=EXIT_COLORS.get(_grp,"#22aa55")
            st.markdown(
                f'<div style="color:{vc_grp};font-family:Syne,sans-serif;font-size:12px;'
                f'font-weight:700;letter-spacing:.06em;margin:14px 0 6px;">'
                f'{_group_labels[_grp]} · {len(_grp_pos)}</div>',
                unsafe_allow_html=True,
            )
            grp_html='<div style="display:flex;flex-wrap:wrap;gap:10px;align-items:stretch;">'
            for p in _grp_pos:
                grp_html+=_pf_card_html(p)
            grp_html+="</div>"
            st.markdown(grp_html, unsafe_allow_html=True)

        # ── Remove positions ───────────────────────────────────────────────────
        st.markdown("<div style='margin-top:18px;'></div>", unsafe_allow_html=True)
        sym_options=[f"{p['symbol']} ({p.get('mode','—')})" for p in valid_pos]
        to_remove=st.multiselect("🗑 Remove positions", sym_options, key="pf_remove_sel")
        if to_remove and st.button("Remove selected", key="pf_remove_btn", type="primary"):
            remove_syms={s.split(" (")[0] for s in to_remove}
            st.session_state["open_positions"]=[
                p for p in st.session_state["open_positions"]
                if p.get("symbol") not in remove_syms
            ]
            _db_save("bs_positions", st.session_state["open_positions"])
            st.rerun()
