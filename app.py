"""
NSE Master Scanner Pro — Streamlit Edition
Mode-aware (Intraday / Swing / Positional) with Phase State Machine
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

# ── Mode config (mirrors Pine Script dynamic params) ─────────────
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
    """Fib retracement + extensions from swing hi/lo over lookback bars (uses High/Low like Pine)."""
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
        "ext127": sw_hi + rng * 0.272,   # 127.2% extension
        "ext161": sw_hi + rng * 0.618,   # 161.8% extension
        "ext261": sw_hi + rng * 1.618,   # 261.8% extension
    }, rng

def _compute_targets(entry, sl, atr_val, fib, setup_type, sw_hi, sw_lo):
    """
    Pine Script target engine — mode-aware by setup type.
    setup_type: 'fib' | 'breakout' | 'norm'
    """
    rk = max(entry - sl, atr_val * 0.5)  # minimum 0.5×ATR risk

    if setup_type == "fib" and fib:
        # Pine STYPE_FIB: T1=ext127, T2=ext161, T3=ext161 + min(range, 3×ATR)
        t1 = round(fib["ext127"], 2)
        t2 = round(fib["ext161"], 2)
        ext_range = fib["ext161"] - fib["ext127"]
        t3 = round(fib["ext161"] + min(ext_range, atr_val * 3), 2)

    elif setup_type == "breakout" and fib:
        # Breakout: blended — avg of ATR-based and Fib extensions
        t1 = round((entry + rk      + fib["ext127"]) / 2, 2)
        t2 = round((entry + rk * 2  + fib["ext161"]) / 2, 2)
        t3 = round((entry + rk * 3  + fib["ext261"]) / 2, 2)

    else:
        # Pure ATR (norm / no fib available)
        t1 = round(entry + rk, 2)
        t2 = round(entry + rk * 2, 2)
        t3 = round(entry + rk * 3, 2)

    # Safety: ensure targets never collapse below entry
    min_move = atr_val * 0.8
    if t1 - entry < min_move:
        t1 = round(entry + min_move, 2)
        t2 = round(entry + min_move * 2, 2)
        t3 = round(entry + min_move * 3, 2)

    return t1, t2, t3

# ── Phase detection (Pine-accurate) ──────────────────────────────
def detect_phase_and_entry(df, mode="Swing"):
    cfg    = MODE_CFG[mode]
    close  = df["Close"]
    high   = df["High"]
    low    = df["Low"]
    volume = df["Volume"]
    n      = len(close)
    if n < 60:
        return PHASE_IDLE, None, "norm"

    c       = float(close.iloc[-1])
    atr_s   = atr_series(df)
    atr_val = float(atr_s.iloc[-1])
    atr_mean= float(atr_s.rolling(20).mean().iloc[-1])
    e_fast  = ema(close, cfg["ema_fast"])
    e_slow  = ema(close, cfg["ema_slow"])
    e20v    = float(e_fast.iloc[-1])
    e50v    = float(e_slow.iloc[-1])
    e200v   = float(ema(close, 200).iloc[-1]) if n >= 200 else e50v
    r       = float(rsi(close, cfg["rsi_len"]).iloc[-1])
    vol_avg = float(volume.rolling(20).mean().iloc[-1])
    v       = float(volume.iloc[-1])
    hh      = float(close.iloc[-11:-1].max())

    trend_up     = c > e200v and c > e20v and e20v > e50v
    trend_down   = c < e200v and c < e20v and e20v < e50v
    trend_strong = c > e20v and e20v > e50v

    # Pine uses i_brkLB=5 for lookback on highs (not closes)
    brk_lb   = 5
    rolling_hi_brk = float(high.iloc[-brk_lb-1:-1].max()) if n > brk_lb+1 else hh
    buf      = atr_val * 0.2

    # Pine compression + expansion checks
    is_compressed = atr_val < atr_mean * 0.8          # ATR < 80% of 20-bar mean
    is_expanding  = atr_val > float(atr_s.iloc[-2])   # ATR growing

    # Wick exhaustion filter (Pine: upperWick > body × 1.5 and close < high)
    body       = abs(float(close.iloc[-1]) - float(df["Open"].iloc[-1])) if "Open" in df.columns else atr_val * 0.3
    upper_wick = float(high.iloc[-1]) - max(float(close.iloc[-1]), float(df["Open"].iloc[-1])) if "Open" in df.columns else 0
    is_exhaustion = upper_wick > body * 1.5

    # Volume spike
    vol_spike = v > vol_avg * 1.3

    sw_hi, sw_lo, fib, fib_rng = fib_levels(df, lookback=30)
    prox      = atr_val * 0.3
    in_golden = bool(fib and c >= fib["618"] - prox and c <= fib["500"] + prox)
    near_e127 = bool(fib and abs(c - fib["ext127"]) < prox)
    near_e161 = bool(fib and abs(c - fib["ext161"]) < prox)

    mom1 = (c - float(close.iloc[-21])) / float(close.iloc[-21]) * 100 if n >= 21 else 0
    mom3 = (c - float(close.iloc[-63])) / float(close.iloc[-63]) * 100 if n >= 63 else 0
    mom6 = (c - float(close.iloc[-126])) / float(close.iloc[-126]) * 100 if n >= 126 else 0
    strong_htf = mom1 > cfg["mom1_th"] and mom3 > cfg["mom3_th"] and mom6 > cfg["mom6_th"]
    qualified  = (strong_htf and trend_strong) if mode == "Positional" else True

    # Bull score
    bull = 0
    bull += 25 if trend_up else 0
    bull += 30 if e20v > e50v else (20 if e20v > e50v*0.995 else 0)
    bull += (25 if r >= 65 else 20) if r >= 60 else (10 if r > 50 else 0)
    bull += 20 if v > vol_avg*1.2 else (10 if v > vol_avg else 0)
    bull += 25 if c > hh else (15 if c > hh*0.98 else 0)
    if n >= 3 and c > float(close.iloc[-3]): bull += 10
    bull += 30 if in_golden else 0
    if near_e127: bull -= 20
    elif near_e161: bull -= 30
    norm_bull = min(100, bull * 100 / 155)

    score_th   = cfg["score_th"]
    is_fib_buy = trend_up and in_golden

    # ── Pine-accurate breakout (smartBreakout) ────────────────────
    # qualifiedStock AND isBreakout AND trendUp AND normBull>=th
    # AND isCompressed[1] AND isExpanding AND volSpike AND NOT isExhaustion
    is_breakout = (
        qualified and
        c > rolling_hi_brk + buf and     # close breaks above 5-bar high+buffer
        trend_up and
        norm_bull >= score_th and
        is_compressed and                  # was in consolidation
        is_expanding and                   # ATR now expanding
        vol_spike and                      # volume confirmation
        not is_exhaustion                  # no wick exhaustion
    )

    # Continuation: close > 3-bar high, volume > avg, trend intact
    is_cont = (
        c > float(close.iloc[-4:-1].max()) and
        v > vol_avg and
        trend_strong
    )

    # Exit conditions
    ema_down    = e20v < e50v and float(e_fast.iloc[-4]) < float(e_slow.iloc[-4])
    trail_level = float(close.iloc[-10:].max()) - atr_val * 1.5
    trail_break = c < trail_level

    if not qualified:
        return PHASE_IDLE, None, "norm"

    # ── Phase priority (mirrors Pine state machine) ───────────────
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
    elif (is_fib_buy or norm_bull >= score_th * 0.85) and trend_up:
        phase = PHASE_SETUP
        setup_type = "fib" if is_fib_buy else "norm"
    elif trail_break and trend_up:
        phase = PHASE_EXIT
        setup_type = "norm"
    else:
        phase = PHASE_IDLE
        setup_type = "norm"

    # ── Entry price = actual signal trigger level ─────────────────
    entry_price = None
    if phase in (PHASE_ENTRY, PHASE_CONT, PHASE_BRK, PHASE_SETUP):
        if is_breakout:
            # Pine: entry at close of breakout bar (which already broke rolling_hi + buf)
            entry_price = round(rolling_hi_brk + buf, 2)
        elif is_fib_buy and fib:
            # Pine: entry at top of golden zone (61.8% level + tiny buffer)
            entry_price = round(fib["618"] + prox * 0.3, 2)
        else:
            # Entry at last EMA fast crossover bar
            cross       = close > e_fast
            signal_bars = cross & ~cross.shift(1).fillna(False)
            if signal_bars.any():
                last_idx    = signal_bars[::-1].idxmax()
                entry_price = round(float(close[last_idx]), 2)
            else:
                entry_price = round(c, 2)

    return phase, entry_price, setup_type

# ── Full stock scoring ────────────────────────────────────────────
def score_stock(df, nifty_close, mode="Swing"):
    try:
        cfg    = MODE_CFG[mode]
        close  = df["Close"]
        volume = df["Volume"]
        n      = len(close)
        if n < 50:
            return None

        c       = float(close.iloc[-1])
        prev    = float(close.iloc[-2])
        e20     = float(ema(close, cfg["ema_fast"]).iloc[-1])
        e50     = float(ema(close, cfg["ema_slow"]).iloc[-1])
        e200    = float(ema(close, 200).iloc[-1]) if n >= 200 else None
        r       = float(rsi(close, cfg["rsi_len"]).iloc[-1])
        atr_val = float(atr_series(df).iloc[-1])
        vol_avg = float(volume.rolling(20).mean().iloc[-1])
        v       = float(volume.iloc[-1])
        chg     = round(((c - prev) / prev) * 100, 2)
        hh      = float(close.iloc[-11:-1].max())

        rs = 0
        if n >= 6 and len(nifty_close) >= 6:
            rs = (c - float(close.iloc[-6])) - (float(nifty_close.iloc[-1]) - float(nifty_close.iloc[-6]))

        trend_up     = (e200 is None or c > e200) and c > e20 and e20 > e50
        trend_strong = c > e20 and e20 > e50

        mom1 = (c - float(close.iloc[-21])) / float(close.iloc[-21]) * 100 if n >= 21 else 0
        mom3 = (c - float(close.iloc[-63])) / float(close.iloc[-63]) * 100 if n >= 63 else 0
        mom6 = (c - float(close.iloc[-126])) / float(close.iloc[-126]) * 100 if n >= 126 else 0
        strong_htf = mom1 > cfg["mom1_th"] and mom3 > cfg["mom3_th"] and mom6 > cfg["mom6_th"]

        sw_hi, sw_lo, fib, fib_rng = fib_levels(df, lookback=30)
        prox      = atr_val * 0.3
        in_golden = bool(fib and c >= fib["618"] - prox and c <= fib["500"] + prox)
        near_e127 = bool(fib and abs(c - fib["ext127"]) < prox)
        near_e161 = bool(fib and abs(c - fib["ext161"]) < prox)

        bull = 0
        bull += 25 if trend_up else 0
        bull += 30 if e20 > e50 else (20 if e20 > e50*0.995 else 0)
        bull += (25 if r >= 65 else 20) if r >= 60 else (10 if r > 50 else 0)
        bull += 20 if v > vol_avg*1.2 else (10 if v > vol_avg else 0)
        bull += 25 if c > hh else (15 if c > hh*0.98 else 0)
        if n >= 3 and c > float(close.iloc[-3]): bull += 10
        bull += 15 if rs > 0 else (5 if rs > -0.5 else 0)
        bull += 25 if strong_htf else -10
        bull += 30 if in_golden else 0
        if near_e127: bull -= 20
        elif near_e161: bull -= 30

        score = bull

        def action_label(s):
            if s >= 100: return "STRONG BUY"
            if s >= 80:  return "BUY"
            if s >= 60:  return "WATCH"
            return "SKIP"

        phase, entry_price, setup_type = detect_phase_and_entry(df, mode)
        ltp   = round(c, 2)
        entry = entry_price if entry_price else ltp

        # ── SL (Pine-accurate, mode-aware) ────────────────────────
        mult   = cfg["atr_mult"]
        wide   = cfg["atr_wide"]
        maxm   = cfg["atr_max"]

        if setup_type == "fib" and fib:
            # Pine STYPE_FIB: SL below swing low or 61.8% - 0.5×ATR
            fib_sl = min(float(sw_lo), fib["618"] - atr_val * 0.5)
            fib_sl = min(fib_sl, entry - atr_val * 0.8)
            sl = round(fib_sl, 2)
        elif setup_type == "breakout":
            # Breakout SL: tighter — entry - 1.5×ATR (Pine breakout SL)
            sl = round(entry - atr_val * (1.5 if mode == "Intraday" else 2.0), 2)
        else:
            raw_sl = entry - atr_val * mult
            min_sl = entry - atr_val * wide
            max_sl = entry - atr_val * maxm
            sl = round(max(min_sl, min(raw_sl, max_sl)), 2)

        # Minimum risk floor
        min_risk = atr_val * 0.5
        if entry - sl < min_risk:
            sl = round(entry - min_risk, 2)

        # ── Targets (Pine-accurate, setup-aware) ──────────────────
        t1, t2, t3 = _compute_targets(entry, sl, atr_val, fib, setup_type, sw_hi, sw_lo)

        return {
            "Score":     score,
            "Action":    action_label(score),
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
        }
    except Exception:
        return None

def fetch_nifty(mode="Swing"):
    cfg = MODE_CFG[mode]
    df  = yf.download("^NSEI", period=cfg["period"], interval=cfg["interval"], progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df["Close"].dropna()

def run_scan(symbols, mode, progress_bar, status_text):
    cfg      = MODE_CFG[mode]
    data     = {}
    rejected = 0
    total    = len(symbols)
    nifty    = fetch_nifty(mode)

    for i, sym in enumerate(symbols):
        ticker = to_nse(sym)
        progress_bar.progress((i+1)/total)
        status_text.text(f"Scanning {i+1}/{total}  ▸  {ticker}  [{mode}]")
        try:
            df = yf.download(ticker, period=cfg["period"], interval=cfg["interval"],
                             auto_adjust=True, progress=False, threads=False)
            if df.empty:
                rejected += 1; continue
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            df = df.dropna(how="all")
            if pd.isna(df["Close"].iloc[-1]):
                df = df.iloc[:-1]
            df["Close"]  = df["Close"].ffill()
            df["Volume"] = df["Volume"].fillna(0)
            df = df.dropna(subset=["Close"])
            min_bars = 30 if mode == "Intraday" else 50
            if len(df) >= min_bars:
                data[sym] = df
            else:
                rejected += 1
        except Exception:
            rejected += 1

    results = []
    for sym, df in data.items():
        res = score_stock(df, nifty, mode)
        if res:
            results.append({"Symbol": sym, **res})

    results.sort(key=lambda x: x["Score"], reverse=True)
    return results, rejected

def fmt(val):
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return "—"
    return f"₹{val:,.2f}"

def action_icon(a):
    return {"STRONG BUY":"🟢","BUY":"🔵","WATCH":"🟡","SKIP":"🔴"}.get(a,"")

# ── Streamlit UI ─────────────────────────────────────────────────
st.set_page_config(page_title="NSE Master Scanner Pro", page_icon="📈",
                   layout="wide", initial_sidebar_state="collapsed")
st.markdown("""
<style>
body, .stApp { background-color:#0d0d1a; color:#f0f0f0; }
.stDataFrame { font-size:13px; }
div[data-testid="stMetricValue"] { color:#00b4d8; font-size:1.4rem; }
</style>""", unsafe_allow_html=True)

st.title("📈 NSE Master Scanner Pro  [Phase Engine v5]")

# ── Session state ────────────────────────────────────────────────
for key, default in [("results",[]),("scan_time",None),("rejected",0),("scan_mode","Swing")]:
    if key not in st.session_state:
        st.session_state[key] = default

# ── Controls (mode must be selected BEFORE fetching indices) ─────
c1, c2, c3, c4, c5, c6 = st.columns([2,1,1,2,2,2])
with c1:
    index_opt = st.selectbox("Index", list(SECTORS.keys()), label_visibility="collapsed")
with c2:
    mode_opt = st.selectbox("Mode", ["Swing","Intraday","Positional"], label_visibility="collapsed")

# ── Nifty & Sensex (mode-aware) ───────────────────────────────────
@st.cache_data(ttl=300)
def fetch_indices(mode="Swing"):
    cfg    = MODE_CFG[mode]
    ema_f  = cfg["ema_fast"]
    ema_s  = cfg["ema_slow"]
    rsi_l  = cfg["rsi_len"]
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
        except:
            out[name] = None
    return out

indices = fetch_indices(mode_opt)
ic1, ic2, ic3 = st.columns([2,2,6])
for col, name in zip([ic1,ic2],["Nifty 50","Sensex"]):
    d = indices.get(name)
    with col:
        if d:
            cs = f"{'+' if d['chg']>=0 else ''}{d['chg']:,.1f} ({'+' if d['pct']>=0 else ''}{d['pct']:.2f}%)"
            cc = "#2ecc71" if d["chg"]>=0 else "#e74c3c"
            ar = "▲" if d["chg"]>=0 else "▼"
            act= d["action"]
            ac = "#ffd700" if act=="STRONG BUY" else ("#2ecc71" if act=="BUY" else ("#f39c12" if act=="WATCH" else "#e74c3c"))
            sp = min(int(d["score"]/150*100),100)
            st.markdown(
                f'<div style="background:#12122a;border:1px solid #1c1c36;border-radius:10px;padding:12px 16px;">'
                f'<div style="color:#7a7a9a;font-size:11px;text-transform:uppercase;">'
                f'{name} &nbsp;<span style="background:#1c1c36;padding:1px 6px;border-radius:3px;font-size:10px;">'
                f'{d["interval"]} · EMA{d["ema_fast"]}/{d["ema_slow"]}</span></div>'
                f'<div style="color:#f0f0f0;font-size:22px;font-weight:bold;">{d["value"]:,.1f}</div>'
                f'<div style="color:{cc};font-size:13px;">{ar} {cs}</div>'
                f'<div style="margin:8px 0 4px;background:#1c1c36;border-radius:4px;height:6px;">'
                f'<div style="background:{ac};width:{sp}%;height:6px;border-radius:4px;"></div></div>'
                f'<div style="display:flex;justify-content:space-between;">'
                f'<span style="color:{ac};font-size:12px;font-weight:bold;">{act} · Score: {d["score"]}</span>'
                f'<span style="color:#7a7a9a;font-size:11px;">RSI {d["rsi"]}</span></div>'
                f'<div style="color:#7a7a9a;font-size:11px;margin-top:4px;">{d["trend"]}</div>'
                f'</div>', unsafe_allow_html=True)
        else:
            st.markdown(f"**{name}:** unavailable")
with ic3:
    st.caption(f"📡 Index data matches selected mode ({mode_opt}). Auto-refreshes every 5 min.")
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

# Mode badge row
mc = {"Intraday":"#e67e22","Swing":"#27ae60","Positional":"#2980b9"}
mi = {"Intraday":"⚡","Swing":"📈","Positional":"🧘"}
cfg_cur = MODE_CFG[mode_opt]
interval_label = {"5m":"5min candles","1d":"Daily candles","1wk":"Weekly candles"}.get(cfg_cur["interval"], cfg_cur["interval"])
last_info = (f"&nbsp;&nbsp;<span style='color:#7a7a9a;font-size:11px;'>"
             f"{st.session_state.scan_time} · Rejected: {st.session_state.rejected}</span>"
             if st.session_state.scan_time else "")
st.markdown(
    f'<div style="margin-bottom:8px;">'
    f'<span style="background:{mc.get(mode_opt,"#555")};color:#fff;'
    f'padding:3px 12px;border-radius:12px;font-size:12px;font-weight:bold;">'
    f'{mi.get(mode_opt,"")} {mode_opt} · {interval_label} · '
    f'EMA{cfg_cur["ema_fast"]}/{cfg_cur["ema_slow"]}'
    f'</span>{last_info}</div>',
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
    prog.empty(); stat.empty()
    st.success(f"✅ Done — {len(results)} valid · {rejected} rejected · {mode_opt} mode")

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

# ── Top 15 ───────────────────────────────────────────────────────
if st.session_state.results:
    all_results = st.session_state.results

    # Actionable = phase is ENTRY, CONT, or BREAKOUT + BUY/STRONG BUY action
    ACTIONABLE_PHASES = {PHASE_ENTRY, PHASE_CONT, PHASE_BRK}
    actionable = [
        r for r in all_results
        if r.get("Phase") in ACTIONABLE_PHASES
        and r["Action"] in ("BUY", "STRONG BUY")
    ]
    # Sort actionable: BREAKOUT first, then by score
    phase_rank = {PHASE_BRK: 0, PHASE_CONT: 1, PHASE_ENTRY: 2}
    actionable.sort(key=lambda x: (phase_rank.get(x.get("Phase"), 9), -x["Score"]))
    top_act = actionable[:15]

    # Watch list = high score but SETUP or IDLE — not ready yet
    watchlist = [
        r for r in all_results
        if r.get("Phase") in (PHASE_SETUP, PHASE_IDLE)
        and r["Score"] >= 70
        and r["Action"] in ("BUY", "STRONG BUY")
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
        st_icon = {"fib":"🌀","breakout":"🚀","norm":"📊"}.get(r.get("Setup","norm"),"📊")
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
            f'</div></div>'
        )

    if top_act:
        with st.expander("🚀 READY TO TRADE — ENTRY / CONT / BREAKOUT", expanded=True):
            cards = '<div style="display:flex;flex-wrap:wrap;gap:8px;">'
            for i, r in enumerate(top_act):
                cards += make_card(i, r, border_color="#00dd88", show_entry=True)
            cards += '</div>'
            st.markdown(cards, unsafe_allow_html=True)
    else:
        st.info("No stocks in ENTRY / CONT / BREAKOUT phase right now. Check SETUP watchlist below.")

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
        setup_icon = {"fib":"🌀","breakout":"🚀","norm":"📊"}.get(r.get("Setup","norm"),"📊")
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
            pc    = PHASE_COLORS.get(phase,"#555")
            chg   = r["%Change"]

            # Phase state machine display
            phases_order = [PHASE_IDLE, PHASE_SETUP, PHASE_ENTRY, PHASE_CONT, PHASE_BRK, PHASE_EXIT]
            phase_html = '<div style="display:flex;gap:6px;margin-bottom:12px;flex-wrap:wrap;">'
            for ph in phases_order:
                active = ph == phase
                bg = PHASE_COLORS[ph] if active else "#1c1c36"
                border = f"2px solid {PHASE_COLORS[ph]}" if active else "2px solid #333"
                fw = "bold" if active else "normal"
                phase_html += (
                    f'<div style="background:{bg};border:{border};color:#fff;'
                    f'padding:5px 12px;border-radius:6px;font-size:12px;font-weight:{fw};">'
                    f'{ph}{"  ◀" if active else ""}</div>'
                )
            phase_html += '</div>'
            st.markdown(phase_html, unsafe_allow_html=True)

            d1,d2,d3,d4 = st.columns(4)
            d1.metric("LTP",        fmt(r["LTP"]),  f"{'+' if chg>=0 else ''}{chg}%")
            d2.metric("Entry ⚡",   fmt(r["Entry"]))
            d3.metric("Stop Loss",  fmt(r["SL"]))
            d4.metric("Score",      r["Score"])

            t1c,t2c,t3c = st.columns(3)
            t1c.metric("T1 (+1R)", fmt(r["T1"]))
            t2c.metric("T2 (+2R)", fmt(r["T2"]))
            t3c.metric("T3 (+3R)", fmt(r["T3"]))

            st.markdown(
                f'**Action:** {action_icon(r["Action"])} {r["Action"]}  \n'
                f'**Golden Zone:** {"🌟 Yes — price in 61.8%–50% fib zone" if r.get("InGolden") else "No"}'
            )
            if r["Entry"] != r["LTP"]:
                st.info(f"⚡ Entry ₹{r['Entry']:,} is the signal trigger price. "
                        f"Current LTP is ₹{r['LTP']:,}. "
                        f"Place order near Entry when phase reaches ENTRY or BREAKOUT.")

else:
    if not st.session_state.results:
        st.info("👆 Select **Index** + **Mode**, then press **SCAN** to begin.")
    else:
        st.warning("No stocks match the current filters.")
