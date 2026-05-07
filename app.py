"""
NSE Master Scanner — Streamlit Edition
Converted from Tkinter GUI to Streamlit web app for cloud deployment.
"""

import warnings
import logging
import time
from datetime import datetime

import numpy as np
import pandas as pd
import yfinance as yf
import streamlit as st

from nse500 import nse500_symbols
from sectors import SECTORS

# ── Setup ──────────────────────────────────────
logging.getLogger("yfinance").setLevel(logging.CRITICAL)
warnings.filterwarnings("ignore")

NIFTY500 = list(dict.fromkeys([s.strip().upper().replace(".NS", "") for s in nse500_symbols]))

# Inject full Nifty500 list for the "None" placeholder
for k in SECTORS:
    if SECTORS[k] is None:
        SECTORS[k] = NIFTY500

SCANNER_MODE = "Swing"

_ATR_SL_MULT = {"Intraday": 1.5, "Swing": 2.5, "Positional": 3.5}
_ATR_SL_WIDE = {"Intraday": 3.0, "Swing": 4.0, "Positional": 5.0}
_ATR_SL_MAX  = {"Intraday": 1.0, "Swing": 1.5, "Positional": 1.5}

# ── Engine ─────────────────────────────────────
def to_nse_symbol(sym):
    sym = sym.strip().upper()
    return sym if sym.endswith(".NS") else sym + ".NS"

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

def fib_levels(df, lookback=30):
    sw_hi = df["High"].iloc[-lookback:].max()
    sw_lo = df["Low"].iloc[-lookback:].min()
    fib_rng = sw_hi - sw_lo
    if fib_rng == 0:
        return sw_hi, sw_lo, {}, None, None
    levels = {
        "236":    sw_hi - fib_rng * 0.236,
        "382":    sw_hi - fib_rng * 0.382,
        "500":    sw_hi - fib_rng * 0.500,
        "618":    sw_hi - fib_rng * 0.618,
        "786":    sw_hi - fib_rng * 0.786,
        "ext127": sw_hi + fib_rng * 0.272,
        "ext161": sw_hi + fib_rng * 0.618,
        "ext261": sw_hi + fib_rng * 1.618,
    }
    return sw_hi, sw_lo, levels, fib_rng, None

def compute_sl_targets_v5(entry, atr_val, mode=SCANNER_MODE, fib_ext127=None, fib_ext161=None):
    mult = _ATR_SL_MULT.get(mode, 2.5)
    wide = _ATR_SL_WIDE.get(mode, 4.0)
    maxm = _ATR_SL_MAX.get(mode, 1.5)
    raw_sl = entry - atr_val * mult
    min_sl = entry - atr_val * wide
    max_sl = entry - atr_val * maxm
    sl = round(max(min_sl, min(raw_sl, max_sl)), 2)
    rk = max(entry - sl, atr_val * 0.5)
    t1 = round(entry + rk, 2)
    t2 = round(entry + rk * 2, 2)
    t3 = round(entry + rk * 3, 2)
    tf1 = round(fib_ext127, 2) if fib_ext127 else None
    tf2 = round(fib_ext161, 2) if fib_ext161 else None
    return sl, t1, t2, t3, tf1, tf2

def action_label(score):
    if score >= 100: return "STRONG BUY"
    if score >= 80:  return "BUY"
    if score >= 60:  return "WATCH"
    return "SKIP"

def score_stock(df, nifty_close):
    try:
        close  = df["Close"]
        volume = df["Volume"]
        if len(close) < 50:
            return None
        c     = close.iloc[-1]
        prev  = close.iloc[-2]
        e20   = ema(close, 20).iloc[-1]
        e50   = ema(close, 50).iloc[-1]
        e200  = ema(close, 200).iloc[-1] if len(close) >= 200 else None
        r     = rsi(close).iloc[-1]
        atr_s = atr(df).iloc[-1]
        vol_avg = volume.rolling(20).mean().iloc[-1]
        v     = volume.iloc[-1]
        chg   = round(((c - prev) / prev) * 100, 2)
        hh    = close.iloc[-11:-1].max()

        rs = 0
        if len(close) >= 6 and len(nifty_close) >= 6:
            rs = (c - close.iloc[-6]) - (nifty_close.iloc[-1] - nifty_close.iloc[-6])

        trend_up = (e200 is None or c > e200) and c > e20 and e20 > e50

        if len(close) >= 126:
            mom1 = (c - close.iloc[-21])  / close.iloc[-21]  * 100
            mom3 = (c - close.iloc[-63])  / close.iloc[-63]  * 100
            mom6 = (c - close.iloc[-126]) / close.iloc[-126] * 100
            strongHTF = mom1 > 5 and mom3 > 10 and mom6 > 15
        else:
            strongHTF = False

        trendStrong = c > e20 and e20 > e50
        qualified   = strongHTF and trendStrong

        sw_hi, sw_lo, fib, fib_rng, _ = fib_levels(df, lookback=30)
        in_golden = False
        if fib:
            prox = atr_s * 0.3
            in_golden  = (c >= fib["618"] - prox) and (c <= fib["500"] + prox)
            near_e127  = abs(c - fib["ext127"]) < prox
            near_e161  = abs(c - fib["ext161"]) < prox
        else:
            near_e127 = near_e161 = False

        score = 0
        score += 25 if trend_up else 0
        score += 30 if e20 > e50 else (20 if e20 > e50 * 0.995 else 0)
        score += 25 if r > 60 else (20 if r > 55 else (15 if r > 50 else (5 if r > 45 else 0)))
        score += 20 if v > vol_avg * 1.2 else (10 if v > vol_avg else 0)
        score += 25 if c > hh else (15 if c > hh * 0.98 else 0)
        if len(close) >= 3 and c > close.iloc[-3]:
            score += 10
        score += 15 if rs > 0 else (5 if rs > -0.5 else 0)
        score += 25 if qualified else 0
        score -= 10 if not qualified else 0
        score += 30 if in_golden else 0
        if fib:
            score += -20 if near_e127 else (-30 if near_e161 else 0)

        entry = round(c, 2)
        ext127 = fib["ext127"] if fib else None
        ext161 = fib["ext161"] if fib else None
        sl, t1, t2, t3, tf1, tf2 = compute_sl_targets_v5(
            entry, atr_s, mode=SCANNER_MODE,
            fib_ext127=ext127, fib_ext161=ext161
        )

        return {
            "Score":    score,
            "Qual":     "⭐ STAR" if score >= 85 else ("✔ GOOD" if score >= 70 else "✖ WEAK"),
            "%Change":  chg,
            "LTP":      entry,
            "Entry":    entry,
            "SL":       sl,
            "T1":       t1,
            "T2":       t2,
            "T3":       t3,
            "InGolden": in_golden,
        }
    except Exception:
        return None

def fetch_nifty(period="1y"):
    df = yf.download("^NSEI", period=period, interval="1d", progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df["Close"].dropna()

def run_scan(symbols, progress_bar, status_text):
    data     = {}
    rejected = 0
    total    = len(symbols)
    nifty    = fetch_nifty()

    for i, sym in enumerate(symbols):
        ticker = to_nse_symbol(sym)
        pct = (i + 1) / total
        status_text.text(f"Scanning {i+1}/{total}  ▸  {ticker}")
        progress_bar.progress(pct)
        try:
            df = yf.download(
                ticker, period="1y", interval="1d",
                auto_adjust=True, progress=False, threads=False
            )
            if df.empty:
                rejected += 1
                continue
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            df = df.dropna(how="all")
            if pd.isna(df["Close"].iloc[-1]):
                df = df.iloc[:-1]
            df["Close"]  = df["Close"].ffill()
            df["Volume"] = df["Volume"].fillna(0)
            df = df.dropna(subset=["Close"])
            if len(df) >= 50:
                data[sym] = df
            else:
                rejected += 1
        except Exception:
            rejected += 1

    results = []
    for sym, df in data.items():
        res = score_stock(df, nifty)
        if res:
            results.append({
                "Symbol":   sym,
                "Score":    res["Score"],
                "Qual":     res["Qual"],
                "Action":   action_label(res["Score"]),
                "%Change":  res["%Change"],
                "LTP":      res["LTP"],
                "Entry":    res["Entry"],
                "SL":       res["SL"],
                "T1":       res["T1"],
                "T2":       res["T2"],
                "T3":       res["T3"],
                "InGolden": res["InGolden"],
            })

    results.sort(key=lambda x: x["Score"], reverse=True)
    return results, rejected

def fmt(val):
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return "—"
    return f"₹{val:,.2f}"

def action_color(action):
    return {
        "STRONG BUY": "🟢",
        "BUY":        "🔵",
        "WATCH":      "🟡",
        "SKIP":       "🔴",
    }.get(action, "")

# ── Streamlit UI ───────────────────────────────
st.set_page_config(
    page_title="NSE Master Scanner Pro",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="collapsed"
)

st.markdown("""
<style>
body, .stApp { background-color: #0d0d1a; color: #f0f0f0; }
.stDataFrame { font-size: 13px; }
div[data-testid="stMetricValue"] { color: #00b4d8; font-size: 1.4rem; }
.strong-buy { background-color: #0a3d1a; }
.buy        { background-color: #1a4d0a; }
.watch      { background-color: #4d3300; }
.skip       { background-color: #3d0a0a; }
</style>
""", unsafe_allow_html=True)

st.title("📈 NSE Master Scanner Pro  [v5 Targets]")

# ── Live Nifty & Sensex ──
@st.cache_data(ttl=300)  # refresh every 5 minutes
def fetch_indices():
    results = {}
    for name, ticker in [("Nifty 50", "^NSEI"), ("Sensex", "^BSESN")]:
        try:
            df = yf.download(ticker, period="1y", interval="1d", progress=False)
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            df = df.dropna()
            if len(df) < 50:
                results[name] = None
                continue

            close  = df["Close"]
            curr   = float(close.iloc[-1])
            prev   = float(close.iloc[-2])
            chg    = curr - prev
            pct    = (chg / prev) * 100

            # Score components
            e20  = float(ema(close, 20).iloc[-1])
            e50  = float(ema(close, 50).iloc[-1])
            e200 = float(ema(close, 200).iloc[-1]) if len(close) >= 200 else None
            r    = float(rsi(close).iloc[-1])
            hh   = float(close.iloc[-11:-1].max())
            trend_up = (e200 is None or curr > e200) and curr > e20 and e20 > e50

            if len(close) >= 126:
                mom1 = (curr - float(close.iloc[-21]))  / float(close.iloc[-21])  * 100
                mom3 = (curr - float(close.iloc[-63]))  / float(close.iloc[-63])  * 100
                mom6 = (curr - float(close.iloc[-126])) / float(close.iloc[-126]) * 100
                strongHTF = mom1 > 5 and mom3 > 10 and mom6 > 15
            else:
                strongHTF = False

            trendStrong = curr > e20 and e20 > e50
            qualified   = strongHTF and trendStrong

            score = 0
            score += 25 if trend_up else 0
            score += 30 if e20 > e50 else (20 if e20 > e50 * 0.995 else 0)
            score += 25 if r > 60 else (20 if r > 55 else (15 if r > 50 else (5 if r > 45 else 0)))
            score += 25 if curr > hh else (15 if curr > hh * 0.98 else 0)
            if len(close) >= 3 and curr > float(close.iloc[-3]):
                score += 10
            score += 25 if qualified else 0
            score -= 10 if not qualified else 0

            action = action_label(score)

            results[name] = {
                "value":  curr,
                "chg":    chg,
                "pct":    pct,
                "score":  score,
                "action": action,
                "rsi":    round(r, 1),
                "trend":  "↑ Above EMA20 & EMA50" if trendStrong else "↓ Below EMA",
            }
        except Exception:
            results[name] = None
    return results

indices = fetch_indices()
ic1, ic2, ic3 = st.columns([2, 2, 6])
for col, name in zip([ic1, ic2], ["Nifty 50", "Sensex"]):
    d = indices.get(name)
    with col:
        if d:
            chg_str  = f"{'+' if d['chg'] >= 0 else ''}{d['chg']:,.1f} ({'+' if d['pct'] >= 0 else ''}{d['pct']:.2f}%)"
            chg_color = "#2ecc71" if d["chg"] >= 0 else "#e74c3c"
            arrow     = "▲" if d["chg"] >= 0 else "▼"
            act       = d["action"]
            act_color = "#ffd700" if act == "STRONG BUY" else ("#2ecc71" if act == "BUY" else ("#f39c12" if act == "WATCH" else "#e74c3c"))
            score_pct = min(int(d["score"] / 150 * 100), 100)
            st.markdown(
                f'<div style="background:#12122a;border:1px solid #1c1c36;border-radius:10px;padding:12px 16px;">'
                f'<div style="color:#7a7a9a;font-size:11px;text-transform:uppercase;letter-spacing:1px;">{name}</div>'
                f'<div style="color:#f0f0f0;font-size:22px;font-weight:bold;">{d["value"]:,.1f}</div>'
                f'<div style="color:{chg_color};font-size:13px;">{arrow} {chg_str}</div>'
                f'<div style="margin:8px 0 4px 0;background:#1c1c36;border-radius:4px;height:6px;">'
                f'<div style="background:{act_color};width:{score_pct}%;height:6px;border-radius:4px;"></div></div>'
                f'<div style="display:flex;justify-content:space-between;align-items:center;">'
                f'<span style="color:{act_color};font-size:12px;font-weight:bold;">{act} &nbsp;·&nbsp; Score: {d["score"]}</span>'
                f'<span style="color:#7a7a9a;font-size:11px;">RSI {d["rsi"]}</span>'
                f'</div>'
                f'<div style="color:#7a7a9a;font-size:11px;margin-top:4px;">{d["trend"]}</div>'
                f'</div>',
                unsafe_allow_html=True
            )
        else:
            st.markdown(f"**{name}:** unavailable")
with ic3:
    st.caption("📡 Index data auto-refreshes every 5 min. Score uses same EMA/RSI/momentum logic as stock scanner.")

# ── Session state ──
if "results" not in st.session_state:
    st.session_state.results = []
if "scan_time" not in st.session_state:
    st.session_state.scan_time = None
if "rejected" not in st.session_state:
    st.session_state.rejected = 0

# ── Top controls ──
col1, col2, col3, col4, col5 = st.columns([2, 2, 2, 2, 2])
with col1:
    index_opt = st.selectbox(
        "Index",
        list(SECTORS.keys()),
        label_visibility="collapsed"
    )
with col2:
    scan_btn = st.button(f"🔍 SCAN {index_opt.upper()}", type="primary", use_container_width=True)
with col3:
    filter_opt = st.selectbox(
        "Show",
        ["BUY + STRONG BUY", "STRONG BUY only", "WATCH + BUY", "All Results"],
        label_visibility="collapsed"
    )
with col4:
    search_q = st.text_input("Search symbol", placeholder="e.g. RELIANCE", label_visibility="collapsed")
with col5:
    if st.session_state.scan_time:
        st.markdown(f"**Last scan:** {st.session_state.scan_time}  |  **Rejected:** {st.session_state.rejected}")

# ── Scan ──
if scan_btn:
    symbols = SECTORS[index_opt]
    n = len(symbols)
    est = "~1 min" if n <= 50 else ("~2 mins" if n <= 150 else "3–5 mins")
    prog_bar   = st.progress(0)
    status_txt = st.empty()
    with st.spinner(f"Scanning {index_opt} ({n} stocks)... {est} on cloud ☁️"):
        results, rejected = run_scan(symbols, prog_bar, status_txt)
    st.session_state.results  = results
    st.session_state.rejected = rejected
    st.session_state.scan_time = datetime.now().strftime("%H:%M:%S") + f" ({index_opt})"
    prog_bar.empty()
    status_txt.empty()
    st.success(f"✅ Scan complete!  Valid: {len(results)}  Rejected: {rejected}")

# ── Filter results ──
results = st.session_state.results

if filter_opt == "BUY + STRONG BUY":
    results = [r for r in results if r["Action"] in ("BUY", "STRONG BUY")]
elif filter_opt == "STRONG BUY only":
    results = [r for r in results if r["Action"] == "STRONG BUY"]
elif filter_opt == "WATCH + BUY":
    results = [r for r in results if r["Action"] in ("WATCH", "BUY", "STRONG BUY")]

if search_q:
    results = [r for r in results if search_q.upper() in r["Symbol"]]

# ── Top 15 panel ──
if st.session_state.results:
    top15 = [r for r in st.session_state.results if r["Score"] >= 70][:15]
    if top15:
        with st.expander("⭐ TOP 15 STRONG STOCKS", expanded=True):
            cards_html = '<div style="display:flex;flex-wrap:wrap;gap:8px;">'
            for idx, r in enumerate(top15):
                chg = r["%Change"]
                chg_str = f"+{chg}%" if chg >= 0 else f"{chg}%"
                chg_color = "#2ecc71" if chg >= 0 else "#e74c3c"
                golden = " 🌟" if r.get("InGolden") else ""
                act = r["Action"]
                act_color = "#ffd700" if act == "STRONG BUY" else "#2ecc71"
                bg = "#0a2e14" if r["Score"] >= 100 else "#0d3d10"
                cards_html += (
                    f'<div style="background:{bg};border:1px solid #2ecc71;border-radius:8px;'
                    f'padding:10px 14px;min-width:140px;flex:1 1 140px;max-width:180px;">'
                    f'<div style="color:#f0f0f0;font-weight:bold;font-size:14px;">{idx+1}. {r["Symbol"]}{golden}</div>'
                    f'<div style="color:{act_color};font-size:12px;">{act} &middot; {r["Score"]}</div>'
                    f'<div style="color:#f0f0f0;font-size:12px;">&#8377;{r["LTP"]:,}&nbsp;'
                    f'<span style="color:{chg_color}">{chg_str}</span></div>'
                    f'</div>'
                )
            cards_html += '</div>'
            st.markdown(cards_html, unsafe_allow_html=True)

# ── Summary metrics ──
if results:
    sb  = sum(1 for r in results if r["Action"] == "STRONG BUY")
    b   = sum(1 for r in results if r["Action"] == "BUY")
    w   = sum(1 for r in results if r["Action"] == "WATCH")
    sk  = sum(1 for r in results if r["Action"] == "SKIP")
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Showing", len(results))
    m2.metric("🟢 Strong Buy", sb)
    m3.metric("🔵 Buy", b)
    m4.metric("🟡 Watch", w)
    m5.metric("🔴 Skip", sk)

# ── Main table ──
if results:
    df_display = pd.DataFrame([{
        "#":        i + 1,
        "Symbol":   r["Symbol"],
        "Score":    r["Score"],
        "Action":   f"{action_color(r['Action'])} {r['Action']}",
        "Qual":     r["Qual"],
        "%Change":  f"+{r['%Change']}%" if r["%Change"] >= 0 else f"{r['%Change']}%",
        "LTP":      fmt(r["LTP"]),
        "Entry":    fmt(r["Entry"]),
        "SL":       fmt(r["SL"]),
        "T1 (+1R)": fmt(r["T1"]),
        "T2 (+2R)": fmt(r["T2"]),
        "T3 (+3R)": fmt(r["T3"]),
        "Golden 🌟": "Yes" if r.get("InGolden") else "",
    } for i, r in enumerate(results)])

    st.dataframe(
        df_display,
        use_container_width=True,
        hide_index=True,
        height=500,
    )

    # ── Export ──
    buy_rows = [r for r in results if r["Action"] in ("BUY", "STRONG BUY")]
    if buy_rows:
        csv = pd.DataFrame(buy_rows).to_csv(index=False)
        ts  = datetime.now().strftime("%Y%m%d_%H%M%S")
        st.download_button(
            label="💾 Export BUY results as CSV",
            data=csv,
            file_name=f"NSE_Scan_v5_{ts}.csv",
            mime="text/csv"
        )

    # ── Detail view ──
    st.markdown("---")
    st.subheader("🔍 Stock Detail")
    syms = [r["Symbol"] for r in results]
    selected = st.selectbox("Select a stock for details", syms, label_visibility="visible")
    if selected:
        r = next((x for x in results if x["Symbol"] == selected), None)
        if r:
            chg = r["%Change"]
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("LTP",    fmt(r["LTP"]),   f"{'+' if chg>=0 else ''}{chg}%")
            c2.metric("Entry",  fmt(r["Entry"]))
            c3.metric("Stop Loss", fmt(r["SL"]))
            c4.metric("Score",  r["Score"])

            t1, t2, t3 = st.columns(3)
            t1.metric("T1 (+1R)", fmt(r["T1"]))
            t2.metric("T2 (+2R)", fmt(r["T2"]))
            t3.metric("T3 (+3R)", fmt(r["T3"]))

            st.markdown(f"""
**Action:** {action_color(r['Action'])} {r['Action']}  
**Quality:** {r['Qual']}  
**Golden Zone:** {'🌟 Yes' if r.get('InGolden') else 'No'}
""")
else:
    if not st.session_state.results:
        st.info("👆 Press **SCAN NSE 500** to begin. The scan fetches live data for ~500 stocks and takes 3–5 minutes on cloud.")
    else:
        st.warning("No stocks match the current filter.")
