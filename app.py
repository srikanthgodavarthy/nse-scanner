import warnings
import logging
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pandas as pd
import yfinance as yf
import streamlit as st

from nse500 import nse500_symbols
from sectors import SECTORS

# ── Setup ──────────────────────────────────────
logging.getLogger("yfinance").setLevel(logging.CRITICAL)
warnings.filterwarnings("ignore")

st.set_page_config(page_title="NSE Scanner PRO", layout="wide")

# ── UI MODE SELECTOR ───────────────────────────
mode_ui = st.selectbox(
    "📊 Select Mode",
    ["⚡ Intraday", "📈 Swing", "🧘 Positional"],
    index=1
)

mode = mode_ui.split(" ")[1]
st.caption(f"⚙️ Current Mode: {mode}")

# ── NSE LIST ───────────────────────────────────
NIFTY500 = list(dict.fromkeys([s.strip().upper().replace(".NS", "") for s in nse500_symbols]))

for k in SECTORS:
    if SECTORS[k] is None:
        SECTORS[k] = NIFTY500

# ── MODE CONFIG ────────────────────────────────
def get_mode_params(mode):
    if mode == "Intraday":
        return {"atr_mult":1.5,"sl_wide":3.0,"sl_max":1.0,"rsi_len":14,"score_boost":0}
    elif mode == "Swing":
        return {"atr_mult":2.5,"sl_wide":4.0,"sl_max":1.5,"rsi_len":14,"score_boost":5}
    else:
        return {"atr_mult":3.5,"sl_wide":5.0,"sl_max":1.5,"rsi_len":21,"score_boost":10}

# ── Indicators ─────────────────────────────────
def ema(s, p):
    return s.ewm(span=p, adjust=False).mean()

def rsi(s, p=14):
    d = s.diff()
    g = d.clip(lower=0).ewm(alpha=1/p, adjust=False).mean()
    l = (-d.clip(upper=0)).ewm(alpha=1/p, adjust=False).mean()
    return 100 - (100 / (1 + g / l.replace(0, np.nan)))

def atr(df, p=14):
    hi, lo, cl = df["High"], df["Low"], df["Close"]
    prev_cl = cl.shift(1)
    tr = pd.concat([
        hi - lo,
        (hi - prev_cl).abs(),
        (lo - prev_cl).abs()
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1/p, adjust=False).mean()

# ── Market Trend ───────────────────────────────
@st.cache_data(ttl=300)
def market_trend():
    df = yf.download("^NSEI", period="6mo", progress=False)
    close = df["Close"]
    return close.iloc[-1] > ema(close, 50).iloc[-1]

# ── SL + TARGETS ──────────────────────────────
def compute_levels(entry, atr_val, mode):
    p = get_mode_params(mode)

    raw_sl = entry - atr_val * p["atr_mult"]
    sl = max(entry - atr_val * p["sl_wide"], min(raw_sl, entry - atr_val * p["sl_max"]))

    # safety
    if entry - sl < atr_val * 0.7:
        sl = entry - atr_val * 0.7

    risk = entry - sl

    return (
        round(sl, 2),
        round(entry + risk, 2),
        round(entry + risk * 2, 2),
        round(entry + risk * 3, 2),
    )

# ── SCORING ENGINE ────────────────────────────
def score_stock(df, mode):
    try:
        close = df["Close"]
        volume = df["Volume"]

        c = close.iloc[-1]
        e20 = ema(close,20).iloc[-1]
        e50 = ema(close,50).iloc[-1]

        p = get_mode_params(mode)
        r = rsi(close, p["rsi_len"]).iloc[-1]
        atr_v = atr(df).iloc[-1]

        vol_avg = volume.rolling(20).mean().iloc[-1]

        # conditions
        trend_up = c > e20 and e20 > e50
        breakout = c > close.iloc[-20:-1].max()
        vol_spike = volume.iloc[-1] > vol_avg * 1.5

        # scoring
        score = 0

        score += 25 if trend_up else -15
        score += (20 if mode=="Intraday" else 25 if mode=="Swing" else 30) if breakout else 0
        score += (15 if mode=="Intraday" else 20 if mode=="Swing" else 25) if vol_spike else 0

        if r > 65:
            score += 25
        elif r > 55:
            score += 15
        elif r < 40:
            score -= 20

        score += 10 if c > e20 else -20

        if not market_trend():
            score -= (10 if mode == "Intraday" else 20)

        score += p["score_boost"]

        entry = round(c,2)
        sl, t1, t2, t3 = compute_levels(entry, atr_v, mode)

        rr = round((t1 - entry) / (entry - sl), 2)

        # action
        if score >= 90:
            action = "STRONG BUY"
        elif score >= 70:
            action = "BUY"
        elif score >= 55:
            action = "WATCH"
        elif c < e20:
            action = "EXIT"
        else:
            action = "AVOID"

        return {
            "Symbol":"",
            "Score":score,
            "Action":action,
            "LTP":entry,
            "SL":sl,
            "T1":t1,
            "T2":t2,
            "T3":t3,
            "RR":rr
        }

    except:
        return None

# ── FETCH ─────────────────────────────────────
def fetch_symbol(sym):
    try:
        df = yf.download(sym + ".NS", period="1y", progress=False)
        if len(df) < 50:
            return None
        return df
    except:
        return None

# ── SCAN ENGINE ───────────────────────────────
def run_scan(symbols, mode):
    data = {}

    with ThreadPoolExecutor(max_workers=10) as exe:
        results = list(exe.map(fetch_symbol, symbols))

    for sym, df in zip(symbols, results):
        if df is not None:
            data[sym] = df

    out = []
    for sym, df in data.items():
        r = score_stock(df, mode)
        if r:
            r["Symbol"] = sym
            out.append(r)

    out.sort(key=lambda x: x["Score"], reverse=True)
    return out

# ── UI ────────────────────────────────────────
st.title("📈 NSE Scanner PRO v7")

if st.button("🚀 Run Scan"):
    with st.spinner(f"Scanning in {mode} mode..."):
        results = run_scan(NIFTY500, mode)

    df = pd.DataFrame(results)

    df["Action"] = df["Action"].apply(
        lambda x: "🟢 STRONG BUY" if x=="STRONG BUY"
        else "🔵 BUY" if x=="BUY"
        else "🟡 WATCH" if x=="WATCH"
        else "🔴 EXIT" if x=="EXIT"
        else "⚫ AVOID"
    )

    st.dataframe(df, use_container_width=True)

    # Summary
    st.subheader("Summary")
    col1,col2,col3,col4 = st.columns(4)

    col1.metric("Strong Buy", len(df[df["Action"].str.contains("STRONG")]))
    col2.metric("Buy", len(df[df["Action"].str.contains("BUY")]))
    col3.metric("Watch", len(df[df["Action"].str.contains("WATCH")]))
    col4.metric("Exit", len(df[df["Action"].str.contains("EXIT")]))

    # Download
    csv = df.to_csv(index=False)
    st.download_button("💾 Export CSV", csv, "scanner.csv")
