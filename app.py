"""
NSE Master Scanner Pro — Streamlit Edition
Mode-aware (Intraday / Swing / Positional) with Phase State Machine

Fixes applied:
  FIX-1: Positional qualified gate — demoted from hard block to score penalty
  FIX-2: TTL comment was stale (already 300s, caption corrected)
  FIX-3: Intraday momentum now uses a separate daily fetch; 5m bars excluded
  FIX-4: EMA/RSI/ATR computed once in score_stock, passed into detect_phase
  FIX-5: Fib SL uses max() not min() — was giving absurdly wide stops
  FIX-6: detect_phase receives pre-computed norm_bull so phase & action use identical inputs
  FIX-7: _enctoken_widget defined before it is called (NameError fix)
"""

import warnings
import logging
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
MODE_CFG = {
    "Intraday":   dict(period="5d",  interval="5m",  ema_fast=20, ema_slow=50,
                       atr_mult=1.5, atr_wide=3.0, atr_max=1.0,
                       mom1_th=2,  mom3_th=5,  mom6_th=8,  score_th=65, rsi_len=14),
    "Swing":      dict(period="1y",  interval="1d",  ema_fast=50, ema_slow=200,
                       atr_mult=2.5, atr_wide=4.0, atr_max=1.5,
                       mom1_th=3,  mom3_th=7,  mom6_th=10, score_th=70, rsi_len=21),
    "Positional": dict(period="2y",  interval="1d",  ema_fast=50, ema_slow=200,
                       atr_mult=3.5, atr_wide=5.0, atr_max=1.5,
                       mom1_th=5,  mom3_th=10, mom6_th=15, score_th=70, rsi_len=21),
}

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
    """Fetch 6 months of daily closes for HTF momentum — used by Intraday mode only."""
    try:
        df = yf.download(ticker, period="6mo", interval="1d",
                         auto_adjust=True, progress=False, threads=False)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        return df["Close"].dropna()
    except Exception:
        return pd.Series(dtype=float)

# ── FIX-4/6: detect_phase accepts pre-computed indicators ────────
def detect_phase_and_entry(
    df, mode, *,
    c, e_fast_s, e_slow_s, atr_s, atr_val, atr_mean,
    v, vol_avg, fib, sw_hi, sw_lo, in_golden, near_e127, near_e161,
    norm_bull, trend_up, trend_down, trend_strong, score_th,
    vdu_setup=False,
):
    cfg  = MODE_CFG[mode]
    close = df["Close"]
    high  = df["High"]
    n     = len(close)
    if n < 60:
        return PHASE_IDLE, None, "norm"

    e20v = float(e_fast_s.iloc[-1])
    e50v = float(e_slow_s.iloc[-1])

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

    is_cont = (
        c > float(close.iloc[-4:-1].max()) and
        v > vol_avg and
        trend_strong
    )

    ema_down    = e20v < e50v and float(e_fast_s.iloc[-4]) < float(e_slow_s.iloc[-4])
    trail_level = float(close.iloc[-10:].max()) - atr_val * 1.5
    trail_break = c < trail_level

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

    entry_price = None
    if phase in (PHASE_ENTRY, PHASE_CONT, PHASE_BRK, PHASE_SETUP):
        prox = atr_val * 0.3
        if is_breakout:
            entry_price = round(rolling_hi_brk + buf, 2)
        elif is_fib_buy and fib:
            entry_price = round(fib["618"] + prox * 0.3, 2)
        else:
            e_fast_ser = e_fast_s
            cross       = close > e_fast_ser
            signal_bars = cross & ~cross.shift(1).fillna(False)
            if signal_bars.any():
                last_idx    = signal_bars[::-1].idxmax()
                entry_price = round(float(close[last_idx]), 2)
            else:
                entry_price = round(c, 2)

    return phase, entry_price, setup_type

# ── Full stock scoring ────────────────────────────────────────────
def score_stock(df, nifty_close, mode="Swing", daily_close=None):
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
        e20      = float(e_fast_s.iloc[-1])
        e50      = float(e_slow_s.iloc[-1])
        e200     = float(ema(close, 200).iloc[-1]) if n >= 200 else None
        r        = float(rsi(close, cfg["rsi_len"]).iloc[-1])
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

        trend_up     = (e200 is None or c > e200) and c > e20 and e20 > e50
        trend_down   = (e200 is None or c < e200) and c < e20 and e20 < e50
        trend_strong = c > e20 and e20 > e50

        mom_src = daily_close if (mode == "Intraday" and daily_close is not None and len(daily_close) >= 21) else close
        mom_n   = len(mom_src)
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
        vdu_setup = bool(trend_up and vdu_vol_dry and vdu_coil)

        qualified = strong_htf and trend_strong

        bull = 0
        bull += 25 if trend_up else 0
        bull += 20 if e20 > e50 else (10 if e20 > e50 * 0.995 else 0)
        bull += (20 if r >= 65 else 15) if r >= 60 else (8 if r > 50 else 0)
        bull += 15 if v > vol_avg * 1.2 else (8 if v > vol_avg else 0)
        bull += 20 if c > hh else (12 if c > hh * 0.98 else 0)
        if n >= 3 and c > float(close.iloc[-3]):
            bull += 10
        bull += 10 if rs > 0 else (3 if rs > -0.5 else 0)
        if mode == "Positional":
            bull += 20 if qualified else -15
        else:
            bull += 20 if strong_htf else -10
        bull += 15 if in_golden else 0
        if near_e127:
            bull -= 20
        elif near_e161:
            bull -= 30

        BULL_MAX  = 155
        score     = max(0, bull)
        norm_bull = min(100.0, max(0.0, bull * 100 / BULL_MAX))
        score_th  = cfg["score_th"]

        def action_label(s):
            if s >= 100: return "STRONG BUY"
            if s >= 80:  return "BUY"
            if s >= 60:  return "WATCH"
            return "SKIP"

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

        ltp   = round(c, 2)
        entry = entry_price if entry_price else ltp

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
            "Score":    score,
            "Action":   action_label(score),
            "Phase":    phase,
            "Setup":    setup_type,
            "%Change":  chg,
            "LTP":      ltp,
            "Entry":    entry,
            "SL":       sl,
            "T1":       t1,
            "T2":       t2,
            "T3":       t3,
            "InGolden": in_golden,
            "VDU":      vdu_setup,
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

def _fetch_one(args):
    sym, mode, min_bars = args
    cfg    = MODE_CFG[mode]
    ticker = to_nse(sym)
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
        return sym, None

def run_scan(symbols, mode, progress_bar, status_text):
    import concurrent.futures

    cfg      = MODE_CFG[mode]
    rejected = 0
    total    = len(symbols)
    min_bars = 30 if mode == "Intraday" else 50

    nifty = fetch_nifty(mode)

    market_bullish, regime_label = _market_regime(nifty)
    BEARISH_HAIRCUT = 0.85
    if not market_bullish:
        st.warning(
            f"⚠️ **Market Regime: {regime_label}** — Nifty EMA20 is below EMA50. "
            "Scores are reduced by 15 % and higher conviction is required. "
            "Prefer WATCH/SETUP phases; avoid chasing breakouts."
        )

    status_text.text("Fetching OHLCV data in parallel…")
    data         = {}
    daily_closes = {}
    args_list    = [(sym, mode, min_bars) for sym in symbols]

    MAX_WORKERS = min(16, total)
    completed   = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {pool.submit(_fetch_one, a): a[0] for a in args_list}
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
        res = score_stock(df, nifty, mode, daily_close=daily_closes.get(sym))
        if res:
            if not market_bullish:
                res["Score"] = int(res["Score"] * BEARISH_HAIRCUT)
                res["Action"] = action_label_fn(res["Score"])
            res["Regime"] = regime_label
            results.append({"Symbol": sym, **res})

    results.sort(key=lambda x: x["Score"], reverse=True)
    return results, rejected

def action_label_fn(s):
    if s >= 100: return "STRONG BUY"
    if s >= 80:  return "BUY"
    if s >= 60:  return "WATCH"
    return "SKIP"

def fmt(val):
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return "—"
    return f"₹{val:,.2f}"

def action_icon(a):
    return {"STRONG BUY":"🟢","BUY":"🔵","WATCH":"🟡","SKIP":"🔴"}.get(a,"")

# ── Zerodha helpers ──────────────────────────────────────────────
ZERODHA_QUOTE_URL = "https://api.kite.trade/quote"
ZERODHA_LTP_URL   = "https://api.kite.trade/quote/ltp"

ZERODHA_INDEX_TOKENS = {
    "Nifty 50":  "NSE:NIFTY 50",
    "Sensex":    "BSE:SENSEX",
    "BankNifty": "NSE:NIFTY BANK",
}

def _zerodha_headers(enctoken):
    return {
        "Authorization": f"enctoken {enctoken.strip()}",
        "Content-Type":  "application/json",
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
    ltp    = d.get("last_price", 0)
    ohlc   = d.get("ohlc", {})
    prev   = ohlc.get("close", ltp)
    chg    = round(ltp - prev, 2)
    pct    = round((chg / prev) * 100, 2) if prev else 0
    return {
        "value":    ltp,
        "chg":      chg,
        "pct":      pct,
        "open":     ohlc.get("open"),
        "high":     ohlc.get("high"),
        "low":      ohlc.get("low"),
        "prev":     prev,
        "source":   "Zerodha",
    }

# ── FIX-7: _enctoken_widget defined HERE, before it is called ────
def _enctoken_widget():
    """
    Renders the one-time enctoken input box.
    Shows step-by-step instructions on how to get the token.
    Returns the token string or ''.
    """
    if "zd_enctoken" not in st.session_state:
        st.session_state["zd_enctoken"] = ""

    with st.expander("🔑 Zerodha Live Quotes — Enter enctoken", expanded=not st.session_state["zd_enctoken"]):
        st.markdown("""
**How to get your enctoken** (takes ~30 seconds):
1. Open [kite.zerodha.com](https://kite.zerodha.com) and log in
2. Press **F12** → **Application** tab → **Cookies** → `kite.zerodha.com`
3. Find the cookie named **`enctoken`** — copy its value
4. Paste below ↓

> Token resets daily around **6 AM IST**. Re-paste if quotes stop updating.
> Your token is stored only in this browser session — never sent anywhere except Zerodha's own servers.
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

# ── Options OI + Max Pain (NSE public API) ───────────────────────
@st.cache_data(ttl=180)
def fetch_oi_data(symbol="NIFTY"):
    import requests, json

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Referer": "https://www.nseindia.com/",
    }

    session = requests.Session()
    try:
        session.get("https://www.nseindia.com", headers=headers, timeout=8)
        session.get("https://www.nseindia.com/market-data/equity-derivatives-watch",
                    headers=headers, timeout=8)
        url = f"https://www.nseindia.com/api/option-chain-indices?symbol={symbol}"
        resp = session.get(url, headers=headers, timeout=10)
        if resp.status_code != 200:
            return None
        data = resp.json()
    except Exception:
        return None

    try:
        records = data["records"]
        spot    = float(records["underlyingValue"])
        expiries = records["expiryDates"]
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

        df_oi = pd.DataFrame(rows).sort_values("Strike").reset_index(drop=True)
        total_ce = df_oi["CE_OI"].sum()
        total_pe = df_oi["PE_OI"].sum()
        pcr = round(total_pe / total_ce, 2) if total_ce > 0 else 0

        pains = []
        for s in df_oi["Strike"]:
            ce_loss = ((df_oi["Strike"] - s).clip(lower=0) * df_oi["CE_OI"]).sum()
            pe_loss = ((s - df_oi["Strike"]).clip(lower=0) * df_oi["PE_OI"]).sum()
            pains.append(ce_loss + pe_loss)
        df_oi["TotalPain"] = pains
        max_pain_strike = int(df_oi.loc[df_oi["TotalPain"].idxmin(), "Strike"])

        call_wall = int(df_oi.loc[df_oi["CE_OI"].idxmax(), "Strike"])
        put_wall  = int(df_oi.loc[df_oi["PE_OI"].idxmax(), "Strike"])

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
    if oi is None:
        st.caption(f"⚠️ OI data unavailable for {index_name} — NSE API may be closed or rate-limited.")
        return

    sentiment_label, sentiment_color = _oi_sentiment(oi["pcr"])

    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Expiry",     oi["expiry"])
    m2.metric("Spot",       f"₹{oi['spot']:,.0f}")
    m3.metric("Max Pain",   f"₹{oi['max_pain']:,}",
              delta=f"{oi['max_pain'] - int(oi['spot']):+,} from spot",
              delta_color="off")
    m4.metric("Call Wall",  f"₹{oi['call_wall']:,}")
    m5.metric("Put Wall",   f"₹{oi['put_wall']:,}")

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
        for r in oi["top_ce"]:
            chg_str = f"+{r['CE_Chg']:,.0f}" if r['CE_Chg'] >= 0 else f"{r['CE_Chg']:,.0f}"
            chg_col = "🔺" if r['CE_Chg'] > 0 else ("🔻" if r['CE_Chg'] < 0 else "–")
            ce_rows.append({
                "Strike": f"₹{r['Strike']:,}",
                "OI (lots)": f"{r['CE_OI']:,}",
                "OI Δ": f"{chg_col} {chg_str}",
            })
        st.dataframe(pd.DataFrame(ce_rows), hide_index=True, use_container_width=True)
    with tc2:
        st.markdown("**📟 Top PE OI (Support)**")
        pe_rows = []
        for r in oi["top_pe"]:
            chg_str = f"+{r['PE_Chg']:,.0f}" if r['PE_Chg'] >= 0 else f"{r['PE_Chg']:,.0f}"
            chg_col = "🔺" if r['PE_Chg'] > 0 else ("🔻" if r['PE_Chg'] < 0 else "–")
            pe_rows.append({
                "Strike": f"₹{r['Strike']:,}",
                "OI (lots)": f"{r['PE_OI']:,}",
                "OI Δ": f"{chg_col} {chg_str}",
            })
        st.dataframe(pd.DataFrame(pe_rows), hide_index=True, use_container_width=True)

    pain_dist = oi["max_pain"] - int(oi["spot"])
    tip = ""
    if abs(pain_dist) <= 100:
        tip = "🎯 Spot is near Max Pain — expect pin action / low volatility into expiry."
    elif pain_dist > 100:
        tip = f"⬆️ Max Pain is ₹{pain_dist:+,} above spot — options writers may defend upside."
    else:
        tip = f"⬇️ Max Pain is ₹{pain_dist:+,} below spot — options writers may drag price down."
    st.caption(tip)

# ── Index fetch (mode-aware) ─────────────────────────────────────
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
            if len(df) < min_bars: out[name]=None; continue
            close = df["Close"]
            c, prev = float(close.iloc[-1]), float(close.iloc[-2])
            chg, pct = c-prev, (c-prev)/prev*100
            ef   = float(ema(close, ema_f).iloc[-1])
            es   = float(ema(close, ema_s).iloc[-1])
            e200 = float(ema(close, 200).iloc[-1]) if len(close)>=200 else es
            r    = float(rsi(close, rsi_l).iloc[-1])
            hh   = float(close.iloc[-11:-1].max())
            trend_up = c > e200 and c > ef and ef > es
            bull  = 0
            bull += 25 if trend_up else 0
            bull += 30 if ef > es else (20 if ef > es*0.995 else 0)
            bull += (25 if r>=65 else 20) if r>=60 else (10 if r>50 else 0)
            bull += 25 if c>hh else (15 if c>hh*0.98 else 0)
            if len(close)>=3 and c>float(close.iloc[-3]): bull+=10
            score  = bull
            action = "STRONG BUY" if score>=100 else ("BUY" if score>=80 else ("WATCH" if score>=60 else "SKIP"))
            interval_label = {"5m":"5min","1d":"Daily","1wk":"Weekly"}.get(cfg["interval"], cfg["interval"])
            out[name] = {"value":c,"chg":chg,"pct":pct,"score":score,"action":action,
                         "rsi":round(r,1),
                         "trend":"↑ Above EMAs" if trend_up else "↓ Below EMAs",
                         "interval": interval_label,
                         "ema_fast": ema_f, "ema_slow": ema_s}
        except Exception:
            out[name] = None
    return out

# ════════════════════════════════════════════════════════════════
# ── Streamlit UI  (all definitions above this line) ─────────────
# ════════════════════════════════════════════════════════════════
st.set_page_config(page_title="NSE Master Scanner Pro", page_icon="📈",
                   layout="wide", initial_sidebar_state="collapsed")
st.markdown("""
<style>
body, .stApp { background-color:#0d0d1a; color:#f0f0f0; }
.stDataFrame { font-size:13px; }
div[data-testid="stMetricValue"] { color:#00b4d8; font-size:1.4rem; }
</style>""", unsafe_allow_html=True)

st.title("📈 NSE Master Scanner Pro  [Phase Engine v5]")

for key, default in [("results",[]),("scan_time",None),("rejected",0),("scan_mode","Swing"),("zd_enctoken",""),("zd_ltp_cache",{})]:
    if key not in st.session_state:
        st.session_state[key] = default

# ── Zerodha enctoken widget — FIX-7: now defined above, safe to call ──
enctoken = _enctoken_widget()

# ── Controls ─────────────────────────────────────────────────────
c1, c2, c3, c4, c5, c6 = st.columns([2,1,1,2,2,2])
with c1:
    index_opt = st.selectbox("Index", list(SECTORS.keys()), label_visibility="collapsed")
with c2:
    mode_opt = st.selectbox("Mode", ["Swing","Intraday","Positional"], label_visibility="collapsed")

indices = fetch_indices(mode_opt)

# ── OI data ───────────────────────────────────────────────────────
oi_nifty  = fetch_oi_data("NIFTY")
oi_sensex = fetch_oi_data("BANKNIFTY")

# ── Live index quotes (Zerodha if token present, else yfinance) ───
zd_index_data = {}
if enctoken:
    _zd_raw = zd_fetch_index_quote(
        enctoken,
        [ZERODHA_INDEX_TOKENS["Nifty 50"], ZERODHA_INDEX_TOKENS["Sensex"]]
    )
    for idx_name, inst_key in [("Nifty 50", ZERODHA_INDEX_TOKENS["Nifty 50"]),
                                ("Sensex",   ZERODHA_INDEX_TOKENS["Sensex"])]:
        zd_index_data[idx_name] = zd_index_display(_zd_raw, inst_key, idx_name)

ic1, ic2, ic3 = st.columns([2,2,6])
for col, name, oi_sym in zip(
        [ic1, ic2],
        ["Nifty 50", "Sensex"],
        [oi_nifty, oi_sensex]):
    zd = zd_index_data.get(name)
    d  = indices.get(name)
    with col:
        if zd:
            ltp_val = zd["value"]
            chg_val = zd["chg"]
            pct_val = zd["pct"]
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
            ltp_val  = d["value"]
            chg_val  = d["chg"]
            pct_val  = d["pct"]
            ohlc_str = ""
            src_badge = (
                '<span style="background:#1c1c36;color:#7a7a9a;padding:1px 6px;'
                'border-radius:3px;font-size:9px;margin-left:4px;">yfinance</span>'
            )
        else:
            st.markdown(f"**{name}:** unavailable"); continue

        cs  = f"{'+ ' if chg_val>=0 else ''}{chg_val:,.1f} ({'+ ' if pct_val>=0 else ''}{pct_val:.2f}%)"
        cs  = cs.replace("+ ", "+")
        cc  = "#2ecc71" if chg_val >= 0 else "#e74c3c"
        ar  = "▲" if chg_val >= 0 else "▼"

        act = d["action"] if d else "—"
        rsi_val = d["rsi"]  if d else "—"
        trend_s = d["trend"] if d else ""
        ac  = "#ffd700" if act=="STRONG BUY" else ("#2ecc71" if act=="BUY" else ("#f39c12" if act=="WATCH" else "#e74c3c"))
        sp  = min(int(d["score"]/150*100), 100) if d else 0

        oi_badge = ""
        if oi_sym:
            s_label, s_col = _oi_sentiment(oi_sym["pcr"])
            pain_dist  = oi_sym["max_pain"] - int(ltp_val)
            pain_arrow = "⬆️" if pain_dist > 0 else ("⬇️" if pain_dist < 0 else "🎯")
            oi_badge = (
                f'<div style="margin-top:6px;padding:5px 8px;background:#0a1a0a;'
                f'border-radius:6px;border:1px solid #1c1c36;font-size:11px;">'
                f'<span style="color:#7a7a9a;">PCR: </span>'
                f'<span style="color:{s_col};font-weight:bold;">{oi_sym["pcr"]} {s_label}</span>'
                f' &nbsp;│&nbsp; '
                f'<span style="color:#7a7a9a;">MaxPain: </span>'
                f'<span style="color:#e0c97f;font-weight:bold;">'
                f'₹{oi_sym["max_pain"]:,} {pain_arrow}{pain_dist:+,}</span>'
                f' &nbsp;│&nbsp; '
                f'<span style="color:#7a7a9a;">CWall: </span>'
                f'<span style="color:#e74c3c;">₹{oi_sym["call_wall"]:,}</span>'
                f' &nbsp;│&nbsp; '
                f'<span style="color:#7a7a9a;">PWall: </span>'
                f'<span style="color:#2ecc71;">₹{oi_sym["put_wall"]:,}</span>'
                f'</div>'
            )

        ohlc_html = f'<div style="color:#7a7a9a;font-size:10px;margin-top:2px;">{ohlc_str}</div>' if ohlc_str else ""

        interval_lbl = d["interval"] if d else "—"
        ema_f = d["ema_fast"] if d else "—"
        ema_s = d["ema_slow"] if d else "—"

        st.markdown(
            f'<div style="background:#12122a;border:1px solid #1c1c36;border-radius:10px;padding:12px 16px;">'
            f'<div style="color:#7a7a9a;font-size:11px;text-transform:uppercase;">'
            f'{name}{src_badge}'
            f'&nbsp;<span style="background:#1c1c36;padding:1px 6px;border-radius:3px;font-size:10px;">'
            f'{interval_lbl} · EMA{ema_f}/{ema_s}</span></div>'
            f'<div style="color:#f0f0f0;font-size:22px;font-weight:bold;">{ltp_val:,.1f}</div>'
            f'<div style="color:{cc};font-size:13px;">{ar} {cs}</div>'
            + ohlc_html +
            f'<div style="margin:8px 0 4px;background:#1c1c36;border-radius:4px;height:6px;">'
            f'<div style="background:{ac};width:{sp}%;height:6px;border-radius:4px;"></div></div>'
            f'<div style="display:flex;justify-content:space-between;">'
            f'<span style="color:{ac};font-size:12px;font-weight:bold;">{act} · Score: {d["score"] if d else "—"}</span>'
            f'<span style="color:#7a7a9a;font-size:11px;">RSI {rsi_val}</span></div>'
            f'<div style="color:#7a7a9a;font-size:11px;margin-top:4px;">{trend_s}</div>'
            + oi_badge +
            f'</div>', unsafe_allow_html=True)

# FIX-2: corrected caption
with ic3:
    live_note = "🟢 **Live via Zerodha** (15-sec refresh)" if enctoken else "📡 yfinance (5-min cache)"
    st.caption(f"{live_note} · OI refreshes every 3 min · Technical scores via yfinance")

# ── OI Detail expanders ───────────────────────────────────────────
oi_x1, oi_x2 = st.columns(2)
with oi_x1:
    with st.expander("📊 Nifty 50 — Weekly OI & Max Pain", expanded=False):
        _render_oi_card(oi_nifty, "NIFTY")
with oi_x2:
    with st.expander("📊 Bank Nifty — Weekly OI & Max Pain (NSE proxy for Sensex)", expanded=False):
        _render_oi_card(oi_sensex, "BANKNIFTY")

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

# Mode badge
mc = {"Intraday":"#e67e22","Swing":"#27ae60","Positional":"#2980b9"}
mi = {"Intraday":"⚡","Swing":"📈","Positional":"🧘"}
cfg_cur = MODE_CFG[mode_opt]
interval_label = {"5m":"5min candles","1d":"Daily candles","1wk":"Weekly candles"}.get(cfg_cur["interval"], cfg_cur["interval"])
last_info = (
    f"&nbsp;&nbsp;<span style='color:#7a7a9a;font-size:11px;'>"
    f"{st.session_state.scan_time} · Rejected: {st.session_state.rejected}</span>"
    if st.session_state.scan_time else ""
)
intraday_note = (
    " &nbsp;<span style='color:#e67e22;font-size:10px;'>HTF momentum via daily data</span>"
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

# ── Scan ─────────────────────────────────────────────────────────
if scan_btn:
    symbols = SECTORS[index_opt]
    n   = len(symbols)
    est = "~1 min" if n<=50 else ("~2 mins" if n<=150 else "3–5 mins")
    prog = st.progress(0)
    stat = st.empty()
    with st.spinner(f"Scanning {index_opt} ({n} stocks) · {mode_opt} mode · {est}"):
        results, rejected = run_scan(symbols, mode_opt, prog, stat)
    st.session_state.results   = results
    st.session_state.rejected  = rejected
    st.session_state.scan_mode = mode_opt
    st.session_state.scan_time = datetime.now().strftime("%H:%M:%S") + f" ({index_opt} · {mode_opt})"

    if enctoken and results:
        stat.text("Fetching live LTP from Zerodha…")
        instruments = [f"NSE:{r['Symbol']}" for r in results]
        ltp_map = zd_fetch_ltp_bulk(enctoken, instruments)
        for r in st.session_state.results:
            live = ltp_map.get(f"NSE:{r['Symbol']}")
            if live and live > 0:
                prev_ltp = r["LTP"]
                r["LTP"]     = round(live, 2)
                r["%Change"] = round(((live - prev_ltp) / prev_ltp) * 100, 2) if prev_ltp else r["%Change"]
                r["_ltp_src"] = "Zerodha"

    prog.empty(); stat.empty()
    st.success(f"✅ Done — {len(results)} valid · {rejected} rejected · {mode_opt} mode"
               + (" · 🟢 LTP from Zerodha" if enctoken else ""))

# ── Filtering ────────────────────────────────────────────────────
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

# ── Top cards ────────────────────────────────────────────────────
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
        and r["Score"] >= 70
        and r["Action"] in ("BUY","STRONG BUY")
    ][:10]

    def make_card(i, r, border_color, show_entry=True):
        chg = r["%Change"]
        cs  = f"+{chg}%" if chg>=0 else f"{chg}%"
        cc  = "#2ecc71" if chg>=0 else "#e74c3c"
        gl  = " 🌟" if r.get("InGolden") else ""
        act = r["Action"]
        ac  = "#ffd700" if act=="STRONG BUY" else "#2ecc71"
        ph  = r.get("Phase", PHASE_IDLE)
        pc  = PHASE_COLORS.get(ph, "#555")
        st_icon = {"fib":"🌀","breakout":"🚀","norm":"📊","vdu":"🔕"}.get(r.get("Setup","norm"),"📊")
        entry_str = f'&#8377;{r["Entry"]:,}' if show_entry and r["Entry"] != r["LTP"] else ""
        return (
            f'<div style="background:#0a1a0a;border:1px solid {border_color};border-radius:8px;'
            f'padding:10px 14px;min-width:140px;flex:1 1 140px;max-width:185px;">'
            f'<div style="color:#f0f0f0;font-weight:bold;font-size:13px;">{i+1}. {r["Symbol"]}{gl}</div>'
            f'<div style="color:{ac};font-size:11px;">{act} · Score {r["Score"]}</div>'
            f'<div style="color:#f0f0f0;font-size:12px;">&#8377;{r["LTP"]:,} '
            f'<span style="color:{cc}">{cs}</span></div>'
            f'{"<div style=color:#aaa;font-size:11px;>⚡ Entry " + entry_str + "</div>" if entry_str else ""}'
            f'<div style="margin-top:5px;display:flex;gap:4px;flex-wrap:wrap;">'
            f'<span style="background:{pc};color:#fff;padding:1px 6px;border-radius:3px;font-size:10px;">{ph}</span>'
            f'<span style="background:#1c1c36;color:#aaa;padding:1px 6px;border-radius:3px;font-size:10px;">{st_icon}</span>'
            + ('<span style="background:#4a3000;color:#ffa500;padding:1px 6px;border-radius:3px;font-size:10px;">🔕VDU</span>' if r.get("VDU") else '')
            + '</div></div>'
        )

    if top_act:
        with st.expander("🚀 READY TO TRADE — ENTRY / CONT / BREAKOUT", expanded=True):
            cards = '<div style="display:flex;flex-wrap:wrap;gap:8px;">'
            for i, r in enumerate(top_act):
                cards += make_card(i, r, border_color="#00dd88", show_entry=True)
            cards += '</div>'
            st.markdown(cards, unsafe_allow_html=True)
    else:
        st.info("No stocks in ENTRY / CONT / BREAKOUT phase right now.")

    if watchlist:
        with st.expander("👁 WATCHLIST — High Score but Not Yet Ready (SETUP / IDLE)", expanded=False):
            cards = '<div style="display:flex;flex-wrap:wrap;gap:8px;">'
            for i, r in enumerate(watchlist):
                cards += make_card(i, r, border_color="#b87333", show_entry=False)
            cards += '</div>'
            st.markdown(cards, unsafe_allow_html=True)

# ── Summary metrics ───────────────────────────────────────────────
if results:
    sb = sum(1 for r in results if r["Action"]=="STRONG BUY")
    b  = sum(1 for r in results if r["Action"]=="BUY")
    w  = sum(1 for r in results if r["Action"]=="WATCH")
    sk = sum(1 for r in results if r["Action"]=="SKIP")
    pe = sum(1 for r in results if r.get("Phase")==PHASE_ENTRY)
    pb = sum(1 for r in results if r.get("Phase")==PHASE_BRK)
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
        chg   = r["%Change"]
        phase = r.get("Phase", PHASE_IDLE)
        entry_flag = " ⚡" if r["Entry"] != r["LTP"] else ""
        setup_icon = {"fib":"🌀","breakout":"🚀","norm":"📊","vdu":"🔕"}.get(r.get("Setup","norm"),"📊")
        rows.append({
            "#":       i+1,
            "Symbol":  r["Symbol"],
            "Score":   r["Score"],
            "Phase":   phase,
            "Setup":   f'{setup_icon} {r.get("Setup","norm")}',
            "Action":  f"{action_icon(r['Action'])} {r['Action']}",
            "%Chg":    f"+{chg}%" if chg>=0 else f"{chg}%",
            "LTP":     fmt(r["LTP"]),
            "Entry":   fmt(r["Entry"]) + entry_flag,
            "SL":      fmt(r["SL"]),
            "T1":      fmt(r["T1"]),
            "T2":      fmt(r["T2"]),
            "T3":      fmt(r["T3"]),
            "Golden":  "🌟" if r.get("InGolden") else "",
            "VDU":     "🔕" if r.get("VDU") else "",
            "Regime":  r.get("Regime", "—"),
        })
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True, height=480)
    st.caption("⚡ Entry = signal trigger price (fib zone / breakout / EMA cross). LTP = current price.")

    buy_rows = [r for r in results if r["Action"] in ("BUY","STRONG BUY")]
    if buy_rows:
        csv = pd.DataFrame(buy_rows).to_csv(index=False)
        ts  = datetime.now().strftime("%Y%m%d_%H%M%S")
        st.download_button("💾 Export BUY results as CSV", csv,
                           f"NSE_Scan_{st.session_state.scan_mode}_{ts}.csv", "text/csv")

    # ── Detail ───────────────────────────────────────────────────
    st.markdown("---")
    st.subheader("🔍 Stock Detail")
    sel = st.selectbox("Select stock", [r["Symbol"] for r in results])
    if sel:
        r = next((x for x in results if x["Symbol"]==sel), None)
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
            phase_html += '</div>'
            st.markdown(phase_html, unsafe_allow_html=True)

            d1,d2,d3,d4 = st.columns(4)
            d1.metric("LTP",       fmt(r["LTP"]),  f"{'+' if chg>=0 else ''}{chg}%")
            d2.metric("Entry ⚡",  fmt(r["Entry"]))
            d3.metric("Stop Loss", fmt(r["SL"]))
            d4.metric("Score",     r["Score"])

            t1c,t2c,t3c = st.columns(3)
            t1c.metric("T1 (+1R)", fmt(r["T1"]))
            t2c.metric("T2 (+2R)", fmt(r["T2"]))
            t3c.metric("T3 (+3R)", fmt(r["T3"]))

            st.markdown(
                f'**Action:** {action_icon(r["Action"])} {r["Action"]}  \n'
                f'**Golden Zone:** {"🌟 Yes — price in 61.8%–50% fib zone" if r.get("InGolden") else "No"}'
            )
            if r["Entry"] != r["LTP"]:
                st.info(
                    f"⚡ Entry ₹{r['Entry']:,} is the signal trigger price. "
                    f"Current LTP is ₹{r['LTP']:,}. "
                    f"Place order near Entry when phase reaches ENTRY or BREAKOUT."
                )
else:
    if not st.session_state.results:
        st.info("👆 Select **Index** + **Mode**, then press **SCAN** to begin.")
    else:
        st.warning("No stocks match the current filters.")
