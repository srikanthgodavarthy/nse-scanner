"""
   ╭──╮
╭──╯  ╰──╮
│  █ █ █ │
╰────────╯
BullSutra Pro — v9
═══════════════════════════════════════════════
UI FIXES FROM v8
────────────────
UI-1  BADGE TEXT CONTRAST
     Green/teal badges now use dark text (deep green/teal) instead of
     white, which was invisible. All colored badge text uses the 800-stop
     of its color ramp for proper contrast.

UI-2  COMPLETE UI REDESIGN
     Dark terminal-inspired aesthetic with amber/gold accents.
     Sharp, data-dense layout with proper visual hierarchy.
     Custom CSS variables, monospace numbers, clear section dividers.

UI-3  SECTOR REMOVED FROM TABLE
     Sector column dropped — redundant with the breadth heatmap view.

UI-4  REDUNDANT CONF COLUMN REMOVED
     Table shows only "Conf%" (numeric). The text label (HIGH/MED/LOW/WEAK)
     is embedded in the card view only, not duplicated in the table.

UI-5  EXTN HEATMAP COLORING
     ExtN column background is heatmapped:
       0  → transparent (clean)
       1  → amber tint
       2  → orange tint
       3+ → red tint
     Applied via st.dataframe column styling callback.
"""

import warnings
import logging
import time
import random
from datetime import datetime, timedelta

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

MODE_CFG = {
"Intraday":   dict(period="5d",  interval="5m",  ema_fast=9,  ema_slow=21,
atr_mult=1.5, atr_wide=3.0, atr_max=1.0,
mom1_th=2,  mom3_th=5,  mom6_th=8,  score_th=65, rsi_len=14,
htf_period="3mo", htf_interval="15m",
validity_hours=4),
"Swing":      dict(period="1y",  interval="1d",  ema_fast=50, ema_slow=200,
atr_mult=2.5, atr_wide=4.0, atr_max=1.5,
mom1_th=3,  mom3_th=7,  mom6_th=10, score_th=70, rsi_len=21,
htf_period="2y", htf_interval="1wk",
validity_hours=72),
"Positional": dict(period="2y",  interval="1d",  ema_fast=50, ema_slow=200,
atr_mult=3.5, atr_wide=5.0, atr_max=1.5,
mom1_th=5,  mom3_th=10, mom6_th=15, score_th=70, rsi_len=21,
htf_period="5y", htf_interval="1wk",
validity_hours=240),
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

PHASE_ORDER = {PHASE_IDLE:0, PHASE_SETUP:1, PHASE_ENTRY:2,
PHASE_CONT:3, PHASE_BRK:4, PHASE_EXIT:-1}

VIX_CALM    = 15
VIX_CAUTION = 20
VIX_STRESS  = 25
LIQUIDITY_MIN_CR = 5.0


# ═══════════════════════════════════════════════════════════════════
# MATH HELPERS
# ═══════════════════════════════════════════════════════════════════
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
# SIGNAL VALIDITY HELPERS
# ═══════════════════════════════════════════════════════════════════
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


# ═══════════════════════════════════════════════════════════════════
# VIX
# ═══════════════════════════════════════════════════════════════════
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
v = float(df["Close"].iloc[-1])
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


# ═══════════════════════════════════════════════════════════════════
# LIQUIDITY FILTER
# ═══════════════════════════════════════════════════════════════════
def liquidity_ok(df, min_cr=LIQUIDITY_MIN_CR):
try:
traded = df["Close"] * df["Volume"]
avg_cr = float(traded.rolling(20).mean().iloc[-1]) / 1e7
return avg_cr >= min_cr, round(avg_cr, 1)
except Exception:
return True, 0.0


# ═══════════════════════════════════════════════════════════════════
# HTF — PARALLEL PRE-FETCH
# ═══════════════════════════════════════════════════════════════════
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
time.sleep(1.5 ** attempt)
return pd.DataFrame()

def _htf_trend_from_df(df: pd.DataFrame, mode: str):
if df.empty or len(df) < 20:
return True, "HTF-UNKNOWN"
cl   = df["Close"]
ef   = float(ema(cl, 21 if mode == "Intraday" else 13).iloc[-1])
es   = float(ema(cl, 55 if mode == "Intraday" else 26).iloc[-1])
c    = float(cl.iloc[-1])
up   = c > ef > es
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
with concurrent.futures.ThreadPoolExecutor(max_workers=min(20, total)) as pool:
futures = {pool.submit(_fetch_one_htf, sym): sym for sym in symbols}
for fut in concurrent.futures.as_completed(futures):
sym, result = fut.result()
results[sym] = result
completed   += 1
progress_bar.progress(0.15 + completed / total * 0.25)
if completed % 20 == 0:
status_text.text(f"HTF pre-fetch {completed}/{total}…")
return results


# ═══════════════════════════════════════════════════════════════════
# RELATIVE STRENGTH — 52-WEEK PERCENTILE RANK
# ═══════════════════════════════════════════════════════════════════
def compute_rs_ranks(sym_returns: dict) -> dict:
if not sym_returns:
return {}
syms    = list(sym_returns.keys())
returns = [sym_returns[s] for s in syms]
sorted_returns = sorted(returns)
n = len(sorted_returns)
ranks = {}
for sym in syms:
r   = sym_returns[sym]
pos = sorted_returns.index(r)
ranks[sym] = round(pos / max(n - 1, 1) * 100)
return ranks

def _52w_return(close_series: pd.Series) -> float:
if len(close_series) < 10:
return 0.0
lookback = min(252, len(close_series) - 1)
c_now  = float(close_series.iloc[-1])
c_base = float(close_series.iloc[-lookback])
if c_base == 0:
return 0.0
return round((c_now - c_base) / c_base * 100, 2)


# ═══════════════════════════════════════════════════════════════════
# PHASE TRANSITION MEMORY
# ═══════════════════════════════════════════════════════════════════
def record_phase_transition(sym: str, new_phase: str):
if "phase_history" not in st.session_state:
st.session_state["phase_history"] = {}
history = st.session_state["phase_history"]
if sym not in history:
history[sym] = []

prev_phase = history[sym][-1][1] if history[sym] else None
changed     = prev_phase != new_phase
is_prog     = False
is_regr     = False
arrow       = ""

if changed:
ts = datetime.now().isoformat()
history[sym].append((ts, new_phase))
history[sym] = history[sym][-10:]

if prev_phase is not None:
prev_ord = PHASE_ORDER.get(prev_phase, 0)
new_ord  = PHASE_ORDER.get(new_phase, 0)
if new_phase == PHASE_EXIT:
arrow = "→EXIT"
is_regr = True
elif new_ord > prev_ord:
arrow = f"↗{new_phase}"
is_prog = True
elif new_ord < prev_ord and new_phase != PHASE_EXIT:
arrow = f"↘{new_phase}"
is_regr = True

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
prev_ord = PHASE_ORDER.get(prev, 0)
curr_ord = PHASE_ORDER.get(curr, 0)
if curr == PHASE_EXIT:
return "→EXIT"
if curr_ord > prev_ord:
return "↗"
if curr_ord < prev_ord:
return "↘"
return ""


# ═══════════════════════════════════════════════════════════════════
# VOLATILITY-NORMALIZED POSITION SIZING
# ═══════════════════════════════════════════════════════════════════
def position_size(account_size, entry, sl, atr_val, atr_mean, vix_val, risk_pct=0.02):
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
final_qty    = max(1, int(base_qty * vix_adj * atr_adj))
capital_used = round(final_qty * entry, 2)
max_loss     = round(final_qty * risk_per_share, 2)
return {
"base_qty":     base_qty,
"vix_adj":      round(vix_adj, 2),
"atr_adj":      round(atr_adj, 2),
"final_qty":    final_qty,
"capital_used": capital_used,
"max_loss":     max_loss,
"risk_pct":     risk_pct,
}


# ═══════════════════════════════════════════════════════════════════
# EXHAUSTION DETECTION
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

rsi_ceil = cfg["rsi_ceil"]
if vix_val is not None:
if vix_val < VIX_CALM:    rsi_ceil += 2
elif vix_val > VIX_STRESS: rsi_ceil -= 3

rsi_now = float(rsi_series.iloc[-1])
if rsi_now > rsi_ceil:
flags["rsi_overheat"] = True
labels.append("Too hot")

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
labels.append("Parabolic")

e_fast_now = float(e_fast_s.iloc[-1])
if atr_val > 0:
ema_dist_atrs = (c - e_fast_now) / atr_val
if ema_dist_atrs > cfg["ema_dist"]:
flags["ema_distance"] = True
labels.append("EMA overext")

wick_thresh = 0.35 if (c > 0 and atr_val/c > 0.03) else 0.30

if n >= 12 and vol_avg > 0:
prior_run  = c > float(close.iloc[-11])
up_bar     = c > float(close.iloc[-2])
if prior_run and up_bar and v > vol_avg * cfg["clim_vol"]:
bar_range  = float(high.iloc[-1]) - float(low.iloc[-1])
upper_wick = float(high.iloc[-1]) - c
if bar_range > 0 and (upper_wick / bar_range) > wick_thresh:
flags["climactic_volume"] = True
labels.append("Vol climax")

if n >= 10:
lookback  = min(cfg["div_bars"], n-1)
rsi_win   = rsi_series.iloc[-lookback:]
price_win = close.iloc[-lookback:]
rsi_peak  = float(rsi_win.max())
rsi_peak_idx = rsi_win.idxmax()
price_at_peak = float(close[rsi_peak_idx])
gap_req = 5 if mode == "Intraday" else 3
if (rsi_now < rsi_peak - gap_req
and c > price_at_peak
and rsi_win.idxmax() != rsi_win.index[-1]):
flags["mom_exhaustion"] = True
labels.append("Mom fade")

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
labels.append("Bear div")

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
if vix_val is not None and vix_val >= VIX_STRESS:
return "WATCH" if action in ("STRONG BUY", "BUY") else action
if n_flags >= 3:
return "WATCH" if action in ("STRONG BUY", "BUY") else action
return "BUY" if action == "STRONG BUY" else action


# ═══════════════════════════════════════════════════════════════════
# CONFIDENCE MODEL
# ═══════════════════════════════════════════════════════════════════
def compute_confidence(*, norm_bull, phase, trend_up, trend_strong, vol_confirmed,
ema_stack, htf_aligned, regime_bullish, ext_n, vix_val,
phase_bonus=0, rs_rank=50):
c = 0.0
c += {PHASE_BRK: 20, PHASE_CONT: 17, PHASE_ENTRY: 13,
PHASE_SETUP: 7, PHASE_IDLE: 2, PHASE_EXIT: 0}.get(phase, 0)
c += min(20, norm_bull * 0.20)
c += 15 if vol_confirmed else 5
c += 15 if ema_stack else (7 if trend_strong else 0)
c += 15 if htf_aligned else 0
c += 10 if regime_bullish else 2
c -= min(5, ext_n * 2)
if vix_val is not None and vix_val > VIX_CAUTION:
c -= 5
if rs_rank >= 90:   c += 5
elif rs_rank >= 80: c += 3
elif rs_rank <= 20: c -= 3
c += phase_bonus
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

cont_vol_mult = 1.5 if (regime_bearish or (vix_val and vix_val > VIX_CAUTION)) else 1.2
BRK_CONF_MIN  = 0.70 if regime_bearish else 0.65

brk_weights = {
"price_above_high": (0.30, c > rolling_hi_brk + buf),
"trend_up":         (0.20, trend_up),
"score_ok":         (0.15, norm_bull >= score_th),
"compressed":       (0.15, is_compressed),
"expanding":        (0.10, is_expanding),
"vol_spike":        (0.10, vol_spike),
}
brk_confidence = sum(w for w, cond in brk_weights.values() if cond)
is_breakout = (brk_confidence >= BRK_CONF_MIN and not is_exhaustion and htf_up)

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

if not htf_up and phase in (PHASE_ENTRY, PHASE_CONT, PHASE_BRK):
phase, setup_type = PHASE_SETUP, setup_type

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
# TARGET COMPUTATION
# ═══════════════════════════════════════════════════════════════════
def _compute_targets(entry, sl, atr_val, fib, setup_type, sw_hi, sw_lo,
regime_bearish=False, vix_val=None):
rk = max(entry - sl, atr_val * 0.5)
t1m, t2m, t3m, sl_exp = vix_target_mult(vix_val)

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

return t1, t2, t3, sl_exp


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
sym=None, htf_up=True, rs_rank=50):
try:
cfg   = MODE_CFG[mode]
close = df["Close"]
volume = df["Volume"]
n     = len(close)
if n < 50:
return None

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
bull += 7 if rs_rank >= 80 else (3 if rs_rank >= 60 else (0 if rs_rank >= 40 else -3))
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

phase_bonus = 0
if sym:
record_phase_transition(sym, phase)
phase_bonus = phase_transition_conf_bonus(sym)

confidence = compute_confidence(
norm_bull=norm_bull, phase=phase, trend_up=trend_up,
trend_strong=trend_strong, vol_confirmed=vol_confirmed,
ema_stack=ema_stack, htf_aligned=htf_up,
regime_bullish=market_bullish, ext_n=ext_n, vix_val=vix_val,
phase_bonus=phase_bonus, rs_rank=rs_rank,
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
"RS":          round(rs_raw, 2),
"RS_Rank":     rs_rank,
"ExtN":        ext_n,
"ExtLabels":   ext_labels,
"ExtFlags":    ext_flags,
"HTFUp":       htf_up,
"EMAStack":    ema_stack,
"VolConf":     vol_confirmed,
"ATR":         round(atr_val, 2),
"ATR_Mean":    round(atr_mean, 2),
"PhaseBonus":  phase_bonus,
}
except Exception:
return None


# ═══════════════════════════════════════════════════════════════════
# BREADTH ENGINE
# ═══════════════════════════════════════════════════════════════════
def compute_breadth(results):
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
def run_scan(symbols, mode, progress_bar, status_text,
vix_val=None, min_liq_cr=LIQUIDITY_MIN_CR):
import concurrent.futures

cfg      = MODE_CFG[mode]
rejected = 0
total    = len(symbols)
min_bars = 30 if mode == "Intraday" else 50

nifty = fetch_nifty(mode)
market_bullish, regime_label = _market_regime(nifty)

if not market_bullish:
st.warning(
f"⚠️ **Market Regime: {regime_label}** — EMA20 below EMA50. "
"Scores haircut 15%. Targets compressed."
)

status_text.text("Pass 1/3: Fetching OHLCV data…")
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
progress_bar.progress(completed / total * 0.40)
if df is not None:
data[sym] = df
else:
rejected += 1

if mode == "Intraday":
status_text.text("Pass 1b: Fetching daily context…")
daily_args = [(sym, "Swing", 50) for sym in data]
with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
d_futures = {pool.submit(_fetch_one, a): a[0] for a in daily_args}
for fut in concurrent.futures.as_completed(d_futures):
sym, df = fut.result()
if df is not None:
daily_closes[sym] = df["Close"]

status_text.text("Pass 2/3: Pre-fetching HTF data (parallel)…")
progress_bar.progress(0.40)
htf_map = prefetch_htf_parallel(list(data.keys()), mode, status_text, progress_bar)

status_text.text("Pass 2b/3: Computing RS ranks…")
sym_52w_returns = {}
for sym, df in data.items():
sym_52w_returns[sym] = _52w_return(df["Close"])
rs_rank_map = compute_rs_ranks(sym_52w_returns)

results     = []
n_data      = len(data)
liq_skipped = 0

for i, (sym, df) in enumerate(data.items()):
progress_bar.progress(0.65 + (i+1)/n_data * 0.35)
status_text.text(f"Pass 3/3: Scoring {i+1}/{n_data}  ▸  {sym}")

htf_up, _ = htf_map.get(sym, (True, "HTF-UNKNOWN"))
rs_rank   = rs_rank_map.get(sym, 50)

res = score_stock(
df, nifty, mode,
daily_close    = daily_closes.get(sym),
market_bullish = market_bullish,
vix_val        = vix_val,
min_liquidity_cr = min_liq_cr,
sym            = sym,
htf_up         = htf_up,
rs_rank        = rs_rank,
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
if pcr >= 1.3: return "Bullish", "#16a34a"
if pcr >= 0.9: return "Neutral", "#d97706"
return "Bearish", "#dc2626"


@st.cache_data(ttl=300)
def fetch_indices(mode="Swing"):
cfg = MODE_CFG[mode]
ema_f = cfg["ema_fast"]; ema_s = cfg["ema_slow"]; rsi_l = cfg["rsi_len"]
min_bars = 30 if mode == "Intraday" else 50
out = {}
index_map = [
("Nifty 50",   "^NSEI"),
("BankNifty",  "^NSEBANK"),
("Sensex",     "^BSESN"),
]
for name, ticker in index_map:
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
# UI-2: REDESIGNED CSS — Dark terminal aesthetic, amber accents
# ═══════════════════════════════════════════════════════════════════
st.set_page_config(
page_title="NSE Master Scanner Pro",
page_icon="📈",
layout="wide",
initial_sidebar_state="collapsed",
)

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;600&family=Syne:wght@600;700;800&family=DM+Sans:wght@400;500;600&display=swap');

/* ── Root palette ── */
:root {
 --bg-base:     #09090f;
 --bg-surface:  #111120;
 --bg-elevated: #171730;
 --bg-border:   #1e1e40;
 --amber:       #f59e0b;
 --amber-dim:   #92600a;
 --amber-glow:  rgba(245,158,11,0.12);
 --green-vivid: #22c55e;
 --green-dark:  #14532d;   /* UI-1: dark text for green badges */
 --green-dim:   rgba(34,197,94,0.12);
 --red-vivid:   #ef4444;
 --red-dark:    #7f1d1d;
 --blue-vivid:  #3b82f6;
 --teal-vivid:  #14b8a6;
 --teal-dark:   #134e4a;   /* UI-1: dark text for teal badges */
 --text-primary: #e8e8f4;
 --text-muted:  #6b7090;
 --text-dim:    #3a3a60;
 --mono: 'JetBrains Mono', monospace;
 --sans: 'DM Sans', sans-serif;
 --display: 'Syne', sans-serif;
}

/* ── Base ── */
body, .stApp { background: var(--bg-base) !important; font-family: var(--sans); }
.main .block-container { padding-top: 1.2rem; padding-bottom: 1rem; max-width: 1400px; }
h1,h2,h3 { font-family: var(--display); }

/* ── Tabs ── */
.stTabs [data-baseweb="tab-list"] {
 gap: 2px;
 background: var(--bg-surface);
 border: 1px solid var(--bg-border);
 border-radius: 8px;
 padding: 4px;
 margin-bottom: 16px;
}
.stTabs [data-baseweb="tab"] {
 background: transparent;
 color: var(--text-muted);
 border-radius: 6px;
 font-family: var(--sans);
 font-size: 12px;
 font-weight: 500;
 padding: 6px 16px;
 border: none;
 letter-spacing: 0.3px;
}
.stTabs [aria-selected="true"] {
 background: var(--amber-glow) !important;
 color: var(--amber) !important;
 border: 1px solid var(--amber-dim) !important;
}

/* ── Buttons ── */
.stButton > button {
 font-family: var(--display);
 font-weight: 700;
 font-size: 13px;
 letter-spacing: 1px;
 background: var(--amber) !important;
 color: #09090f !important;
 border: none !important;
 border-radius: 6px;
 padding: 8px 24px;
 transition: filter 0.15s;
}
.stButton > button:hover { filter: brightness(1.1); }

/* ── Inputs & selects ── */
.stSelectbox > div > div,
.stTextInput > div > div > input,
.stRadio > div { font-family: var(--sans); font-size: 13px; }
.stRadio label { color: var(--text-muted) !important; }
div[data-baseweb="select"] { background: var(--bg-surface) !important; }

/* ── Metrics ── */
div[data-testid="stMetricValue"] {
 color: var(--amber);
 font-family: var(--mono);
 font-size: 1.4rem;
 font-weight: 500;
}
div[data-testid="stMetricLabel"] { color: var(--text-muted); font-size: 11px; }
div[data-testid="stMetricDelta"] { font-family: var(--mono); font-size: 12px; }

/* ── DataFrame ── */
.stDataFrame {
 font-size: 12px;
 font-family: var(--mono);
 border-radius: 8px;
 overflow: hidden;
 border: 1px solid var(--bg-border) !important;
}
.stDataFrame thead th {
 background: var(--bg-elevated) !important;
 color: var(--text-muted) !important;
 font-size: 10px !important;
 text-transform: uppercase;
 letter-spacing: 0.5px;
 border-bottom: 1px solid var(--bg-border) !important;
}
.stDataFrame tbody tr:nth-child(odd)  { background: var(--bg-surface) !important; }
.stDataFrame tbody tr:nth-child(even) { background: var(--bg-base) !important; }
.stDataFrame tbody tr:hover { background: var(--bg-elevated) !important; }

/* ── Expander ── */
.streamlit-expanderHeader {
 background: var(--bg-surface) !important;
 border: 1px solid var(--bg-border) !important;
 border-radius: 6px !important;
 font-family: var(--sans) !important;
 font-size: 13px !important;
 color: var(--text-primary) !important;
}
.streamlit-expanderContent {
 background: var(--bg-base) !important;
 border: 1px solid var(--bg-border) !important;
 border-top: none !important;
}

/* ── Alerts ── */
div[data-testid="stAlert"] { border-radius: 6px; font-size: 13px; font-family: var(--sans); }

/* ── Scrollbar ── */
::-webkit-scrollbar { width: 4px; height: 4px; }
::-webkit-scrollbar-track { background: var(--bg-base); }
::-webkit-scrollbar-thumb { background: var(--bg-border); border-radius: 2px; }
</style>""", unsafe_allow_html=True)

# ── Session state init ────────────────────────────────────────────
for key, default in [
("results",[]), ("scan_time",None), ("rejected",0), ("liq_skipped",0),
("scan_mode","Swing"), ("signal_log",[]), ("phase_history",{}),
]:
if key not in st.session_state:
st.session_state[key] = default

# ── Header ────────────────────────────────────────────────────────
st.markdown(
'<div style="display:flex;align-items:baseline;gap:12px;margin-bottom:4px;">'
'<h1 style="font-family:Syne,sans-serif;font-size:22px;margin:0;'
'color:#f59e0b;letter-spacing:-0.5px;">NSE MASTER SCANNER</h1>'
'<span style="font-family:JetBrains Mono,monospace;font-size:11px;'
'color:#3a3a60;letter-spacing:2px;">PRO · v9</span>'
'</div>',
unsafe_allow_html=True,
)

# ── Global controls ───────────────────────────────────────────────
gc1, gc2, gc3, gc4, gc5 = st.columns([2,2,1,2,2])
with gc1:
universe_opt = st.radio("Universe", ["NSE 500","Nifty 50"], horizontal=True)
with gc2:
mode_opt = st.radio("Mode", ["Swing","Intraday","Positional"], horizontal=True)
with gc3:
scan_btn = st.button("SCAN", type="primary", use_container_width=True)
with gc4:
filter_opt = st.selectbox("Filter",
["BUY + STRONG BUY","STRONG BUY only","WATCH + BUY","All Results"],
label_visibility="collapsed")
with gc5:
search_q = st.text_input("Search symbol", placeholder="e.g. RELIANCE",
label_visibility="collapsed")

# ── VIX banner ───────────────────────────────────────────────────
vix_val, vix_label = fetch_vix()
vix_color = {"CALM":"#22c55e","CAUTION":"#f59e0b","STRESS":"#ef4444","UNKNOWN":"#6b7090"}.get(vix_label,"#6b7090")
# UI-1: dark text on colored badge, not white
vix_text_color = {"CALM":"#14532d","CAUTION":"#78350f","STRESS":"#7f1d1d","UNKNOWN":"#374151"}.get(vix_label,"#374151")

st.markdown(
f'<div style="display:flex;gap:10px;align-items:center;margin-bottom:8px;">'
f'<span style="background:{vix_color}22;border:1px solid {vix_color}44;'
f'padding:3px 10px;border-radius:4px;font-size:11px;color:{vix_color};'
f'font-family:JetBrains Mono,monospace;font-weight:500;">'
f'VIX {vix_val if vix_val else "—"} · {vix_label}</span>'
+ (f'<span style="color:#ef4444;font-size:11px;font-family:DM Sans,sans-serif;">'
f'⚠ High VIX: STRONG BUY blocked · targets compressed</span>'
if (vix_val and vix_val >= VIX_STRESS) else "")
+ (f'<span style="color:#f59e0b;font-size:11px;font-family:DM Sans,sans-serif;">'
f'⚡ Elevated VIX: targets compressed · SL widened</span>'
if (vix_val and VIX_CAUTION <= vix_val < VIX_STRESS) else "")
+ f'</div>',
unsafe_allow_html=True,
)

# ── Tabs ─────────────────────────────────────────────────────────
tab_scanner, tab_breadth, tab_detail, tab_analytics, tab_settings = st.tabs([
"Scanner", "Breadth Engine", "Detail", "Analytics", "Settings",
])


# ═══════════════════════════════════════════════════════════════════
# SETTINGS TAB
# ═══════════════════════════════════════════════════════════════════
with tab_settings:
st.subheader("Scanner Settings")
sc1, sc2 = st.columns(2)
with sc1:
min_liq_cr = st.slider("Min Liquidity (₹ Cr daily traded value)", 1.0, 50.0, 5.0, 1.0)
phase_filter = st.selectbox("Phase Filter (Scanner)",
["All Phases","ENTRY","SETUP","CONT","BREAKOUT","IDLE","EXIT"])
show_illiquid = st.checkbox("Show illiquid stocks (below liquidity floor)", value=False)
st.markdown("---")
st.markdown("**Position Sizing**")
account_size = st.number_input("Account Size (₹)", min_value=10000,
max_value=10_000_000, value=500000, step=10000)
risk_pct_input = st.slider("Risk per trade (%)", 0.5, 5.0, 2.0, 0.5) / 100.0
with sc2:
st.markdown("**Action Thresholds**")
st.markdown("""
| Score | Action |
|---|---|
| ≥ 75 | STRONG BUY |
| ≥ 58 | BUY |
| ≥ 42 | WATCH |
| < 42 | SKIP |
       """)
st.markdown("**Signal Validity**")
st.markdown("""
| Mode | Window |
|---|---|
| Intraday | 4 h |
| Swing | 72 h |
| Positional | 240 h |
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
ts = datetime.now().isoformat()
validity_h = MODE_CFG[mode_opt]["validity_hours"]
for r in results:
if r.get("Action") in ("BUY","STRONG BUY"):
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
st.markdown(f"<div style='color:#6b7090;font-size:12px;'>{name}: unavailable</div>",
unsafe_allow_html=True)
continue

chg_val = d["chg"]; pct_val = d["pct"]; ltp_val = d["value"]
cs = f"+{pct_val:.2f}%" if chg_val >= 0 else f"{pct_val:.2f}%"
cc = "#22c55e" if chg_val >= 0 else "#ef4444"
ar = "▲" if chg_val >= 0 else "▼"
act = d["action"]
# UI-1: score bar color + DISTINCT text color on colored backgrounds
score_bar_color = (
"#f59e0b" if act == "STRONG BUY" else
"#22c55e" if act == "BUY" else
"#f59e0b" if act == "WATCH" else
"#6b7090"
)
act_text_color = (
"#78350f" if act == "STRONG BUY" else  # amber-dark on amber
"#14532d" if act == "BUY" else          # green-dark on green
"#78350f" if act == "WATCH" else
"#e8e8f4"
)
sp = int(min(d["score"], 100))

oi_badge = ""
if oi_data:
s_label, s_col = _oi_sentiment(oi_data["pcr"])
# UI-1: ensure text is dark on the colored sentiment badge
s_text = "#14532d" if "Bullish" in s_label else ("#78350f" if "Neutral" in s_label else "#7f1d1d")
pd_ = oi_data["max_pain"] - int(ltp_val)
pa = "↑" if pd_ > 0 else ("↓" if pd_ < 0 else "=")
oi_badge = (
f'<div style="margin-top:6px;padding:5px 8px;background:#09090f;'
f'border-radius:5px;border:1px solid #1e1e40;font-family:JetBrains Mono,monospace;">'
f'<span style="color:#6b7090;font-size:9px;">PCR </span>'
f'<span style="background:{s_col}22;border:1px solid {s_col}44;'
f'color:{s_col};padding:1px 5px;border-radius:3px;font-size:9px;font-weight:600;">'
f'{oi_data["pcr"]} {s_label}</span>'
f'<span style="color:#6b7090;font-size:9px;margin-left:6px;">Pain </span>'
f'<span style="color:#f59e0b;font-size:9px;font-weight:600;">'
f'₹{oi_data["max_pain"]:,} {pa}{abs(pd_):,}</span>'
f'<br><span style="color:#ef4444;font-size:9px;">C▶₹{oi_data["call_wall"]:,}  </span>'
f'<span style="color:#22c55e;font-size:9px;">P▶₹{oi_data["put_wall"]:,}</span>'
f'</div>'
)

st.markdown(
f'<div style="background:#111120;border:1px solid #1e1e40;'
f'border-radius:10px;padding:14px 16px;">'
f'<div style="font-family:DM Sans,sans-serif;color:#6b7090;'
f'font-size:10px;text-transform:uppercase;letter-spacing:1px;">{name}</div>'
f'<div style="font-family:JetBrains Mono,monospace;color:#e8e8f4;'
f'font-size:22px;font-weight:600;margin:4px 0 2px;">'
f'{ltp_val:,.1f}</div>'
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

# ── Apply filters ─────────────────────────────────────────────
results = list(st.session_state.results)
if filter_opt == "BUY + STRONG BUY":
results = [r for r in results if r["Action"] in ("BUY","STRONG BUY")]
elif filter_opt == "STRONG BUY only":
results = [r for r in results if r["Action"] == "STRONG BUY"]
elif filter_opt == "WATCH + BUY":
results = [r for r in results if r["Action"] in ("WATCH","BUY","STRONG BUY")]

_phase_filter = phase_filter if "phase_filter" in dir() else "All Phases"
if _phase_filter != "All Phases":
results = [r for r in results if r.get("Phase") == _phase_filter]

_show_illiquid = show_illiquid if "show_illiquid" in dir() else False
if not _show_illiquid:
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

scan_mode_now = st.session_state.scan_mode
stale_syms = set()
for entry in st.session_state.signal_log:
if signal_is_stale(entry["timestamp"], entry.get("mode", scan_mode_now)):
stale_syms.add(entry["symbol"])

def _action_colors(act):
"""UI-1: return (bg_color, border_color, text_color) with proper contrast."""
if act == "STRONG BUY":
return "#f59e0b22", "#f59e0b55", "#f59e0b"
if act == "BUY":
return "#22c55e1a", "#22c55e44", "#22c55e"
if act == "WATCH":
return "#f59e0b11", "#f59e0b33", "#d97706"
return "#6b709011", "#6b709033", "#6b7090"

def make_card(i, r, border_color, show_entry=True):
chg = r["%Change"]
cs  = f"+{chg}%" if chg >= 0 else f"{chg}%"
cc  = "#22c55e" if chg >= 0 else "#ef4444"
act = r["Action"]
act_bg, act_brd, act_txt = _action_colors(act)
ph  = r.get("Phase", PHASE_IDLE)
pc  = PHASE_COLORS.get(ph, "#555")
# UI-1: dark text on bright phase backgrounds
ph_txt_map = {
"#00dd88": "#064e3b",  # BREAKOUT green → dark green
"#22aa55": "#064e3b",  # CONT green → dark green
"#2255cc": "#1e1b4b",  # ENTRY blue → dark blue
"#b87333": "#431407",  # SETUP amber → dark
"#555577": "#c4c6d0",  # IDLE → light
"#cc4444": "#7f1d1d",  # EXIT → dark red
}
ph_txt = ph_txt_map.get(pc, "#e8e8f4")
conf = r.get("Confidence", 0)
conf_lbl, conf_col = confidence_label(conf)
# UI-1: dark text for confidence badge
conf_txt_map = {"HIGH":"#14532d","MED":"#78350f","LOW":"#7c2d12","WEAK":"#7f1d1d"}
conf_txt = conf_txt_map.get(conf_lbl, "#e8e8f4")
entry_str = f'₹{r["Entry"]:,}' if show_entry and r["Entry"] != r["LTP"] else ""
ext_n = r.get("ExtN", 0)
ext_labels = r.get("ExtLabels", [])
ext_badge = ""
if ext_n > 0:
ec = "#ef444422" if ext_n >= 3 else "#f59e0b22"
ec_brd = "#ef4444" if ext_n >= 3 else "#f59e0b"
ec_txt = "#ef4444" if ext_n >= 3 else "#d97706"
ext_badge = (
f'<div style="margin-top:4px;background:{ec};border:1px solid {ec_brd}44;'
f'border-radius:3px;padding:2px 5px;font-size:9px;color:{ec_txt};'
f'font-family:JetBrains Mono,monospace;">'
f'⚠ {" · ".join(ext_labels[:2])}</div>'
)
liq_badge = (
'<div style="margin-top:2px;font-size:9px;color:#d97706;">low liq</div>'
if not r.get("LiquidityOK", True) else ""
)
ph_arrow = get_phase_arrow(r["Symbol"])
stale_badge = (
'<div style="margin-top:2px;font-size:9px;color:#6b7090;">⏱ expired</div>'
if r["Symbol"] in stale_syms else ""
)
rsr = r.get("RS_Rank", 50)
rs_col = "#22c55e" if rsr >= 80 else ("#d97706" if rsr >= 60 else "#6b7090")
rs_txt = "#14532d" if rsr >= 80 else ("#78350f" if rsr >= 60 else "#4b5563")  # UI-1

return (
f'<div style="background:#111120;border:1px solid {border_color};'
f'border-radius:8px;padding:10px 12px;min-width:150px;flex:1 1 150px;max-width:210px;">'
# Symbol row
f'<div style="font-family:JetBrains Mono,monospace;color:#e8e8f4;'
f'font-weight:600;font-size:12px;display:flex;align-items:center;gap:4px;">'
f'{i+1}. {r["Symbol"]}'
+ (f'<span style="font-size:9px;color:#22c55e;margin-left:2px;">🌟</span>' if r.get("InGolden") else "")
+ (f'<span style="color:#22c55e;font-size:10px;margin-left:2px;">{ph_arrow}</span>' if ph_arrow else "")
+ f'</div>'
# Action badge
f'<div style="margin:4px 0;">'
f'<span style="background:{act_bg};border:1px solid {act_brd};'
f'color:{act_txt};padding:2px 6px;border-radius:3px;'
f'font-size:9px;font-weight:600;font-family:DM Sans,sans-serif;">{act}</span>'
f'<span style="font-family:JetBrains Mono,monospace;color:#6b7090;'
f'font-size:9px;margin-left:4px;">{r["Score"]}</span>'
f'</div>'
# LTP + change
f'<div style="font-family:JetBrains Mono,monospace;color:#e8e8f4;font-size:13px;">'
f'₹{r["LTP"]:,} <span style="color:{cc};font-size:10px;">{cs}</span></div>'
+ (f'<div style="font-family:JetBrains Mono,monospace;color:#f59e0b;'
f'font-size:10px;margin-top:2px;">⚡ {entry_str}</div>' if entry_str else "")
# Badges row
+ f'<div style="margin-top:5px;display:flex;gap:3px;flex-wrap:wrap;align-items:center;">'
# Phase badge - UI-1: dark text
f'<span style="background:{pc};color:{ph_txt};'
f'padding:2px 6px;border-radius:3px;font-size:9px;'
f'font-weight:600;font-family:DM Sans,sans-serif;">{ph}</span>'
# Confidence badge - UI-1: dark text on colored bg
f'<span style="background:{conf_col}22;border:1px solid {conf_col}44;'
f'color:{conf_col};padding:2px 5px;border-radius:3px;'
f'font-size:9px;font-family:DM Sans,sans-serif;">{conf_lbl} {conf}%</span>'
# RS badge
f'<span style="background:{rs_col}1a;border:1px solid {rs_col}33;'
f'color:{rs_col};padding:2px 5px;border-radius:3px;font-size:9px;'
f'font-family:JetBrains Mono,monospace;">RS{rsr}</span>'
+ ('<span style="background:#f59e0b22;border:1px solid #f59e0b44;'
'color:#d97706;padding:2px 5px;border-radius:3px;'
'font-size:9px;font-family:DM Sans,sans-serif;">VDU</span>'
if r.get("VDU") else "")
+ "</div>" + ext_badge + liq_badge + stale_badge + "</div>"
)

if top_act:
with st.expander(f"READY TO TRADE — {len(top_act)} stocks in ENTRY / CONT / BREAKOUT", expanded=True):
cards = '<div style="display:flex;flex-wrap:wrap;gap:8px;padding:4px 0;">'
for i, r in enumerate(top_act):
cards += make_card(i, r, "#22c55e44", show_entry=True)
cards += "</div>"
st.markdown(cards, unsafe_allow_html=True)
else:
st.info("No stocks in ENTRY / CONT / BREAKOUT phase.")

watchlist = [
r for r in st.session_state.results
if r.get("Phase") in (PHASE_SETUP, PHASE_IDLE)
and r["Score"] >= 58 and r["Action"] in ("BUY","STRONG BUY")
][:10]
if watchlist:
with st.expander(f"WATCHLIST — {len(watchlist)} high-score, not yet ready", expanded=False):
cards = '<div style="display:flex;flex-wrap:wrap;gap:8px;padding:4px 0;">'
for i, r in enumerate(watchlist):
cards += make_card(i, r, "#f59e0b44", show_entry=False)
cards += "</div>"
st.markdown(cards, unsafe_allow_html=True)

# ── Main table ────────────────────────────────────────────────
if results:
rows = []
for i, r in enumerate(results):
chg      = r["%Change"]
phase    = r.get("Phase", PHASE_IDLE)
setup_icon = {"fib":"Fib","breakout":"BRK","norm":"std","vdu":"VDU"}.get(r.get("Setup","norm"),"std")
conf     = r.get("Confidence", 0)
ph_arrow = get_phase_arrow(r["Symbol"])
rows.append({
"#":       i + 1,
"Symbol":  r["Symbol"],
# UI-3: Sector removed
"Score":   r["Score"],
# UI-4: Only Conf% (numeric), no text label column
"Conf%":   conf,
"Phase":   f'{phase}{" "+ph_arrow if ph_arrow else ""}',
"Setup":   setup_icon,
"Action":  r["Action"],
"%Chg":    f"+{chg}%" if chg >= 0 else f"{chg}%",
"RSI":     r.get("RSI", "—"),
"RS_Rank": r.get("RS_Rank", 50),
"LTP":     fmt(r["LTP"]),
"Entry":   fmt(r["Entry"]) + (" ⚡" if r["Entry"] != r["LTP"] else ""),
"SL":      fmt(r["SL"]),
"T1":      fmt(r["T1"]),
"T2":      fmt(r["T2"]),
"T3":      fmt(r["T3"]),
"Liq₹Cr": r.get("AvgTradedCr", "—"),
"HTF":     "↑" if r.get("HTFUp", True) else "↓",
# UI-5: ExtN as integer for heatmap styling
"ExtN":    r.get("ExtN", 0),
"Ext":     " ".join(r.get("ExtLabels", [])) or "—",
})

df_display = pd.DataFrame(rows)

# UI-5: ExtN heatmap via Styler
def color_extn(val):
if val == 0:   return "background-color: transparent; color: #6b7090"
if val == 1:   return "background-color: #78350f44; color: #f59e0b"
if val == 2:   return "background-color: #9a3412aa; color: #fb923c"
return              "background-color: #7f1d1d; color: #fca5a5; font-weight: 600"

def color_action(val):
if val == "STRONG BUY": return "color: #f59e0b; font-weight: 600"
if val == "BUY":        return "color: #22c55e"
if val == "WATCH":      return "color: #d97706"
return "color: #6b7090"

def color_pct(val):
if isinstance(val, str) and val.startswith("+"):
return "color: #22c55e; font-family: JetBrains Mono, monospace"
if isinstance(val, str) and val.startswith("-"):
return "color: #ef4444; font-family: JetBrains Mono, monospace"
return ""

styled = (
df_display.style
            .applymap(color_extn, subset=["ExtN"])
            .applymap(color_action, subset=["Action"])
            .applymap(color_pct, subset=["%Chg"])
            .map(color_extn, subset=["ExtN"])
            .map(color_action, subset=["Action"])
            .map(color_pct, subset=["%Chg"])
.set_properties(**{
"font-family": "JetBrains Mono, monospace",
"font-size": "11px",
})
)

st.dataframe(styled, use_container_width=True, hide_index=True, height=480)

st.markdown(
'<div style="font-size:10px;color:#3a3a60;font-family:JetBrains Mono,monospace;'
'margin-top:4px;">Score 0-100 · Conf% = confidence · RS_Rank = 52w percentile '
'(80+=top) · HTF ↑/↓ = weekly · Liq₹Cr = avg daily value · ExtN 0=clean 3+=skip</div>',
unsafe_allow_html=True,
)

buy_rows = [r for r in results if r["Action"] in ("BUY","STRONG BUY")]
if buy_rows:
csv = pd.DataFrame(buy_rows).drop(columns=["ExtFlags"], errors="ignore").to_csv(index=False)
ts  = datetime.now().strftime("%Y%m%d_%H%M%S")
st.download_button("Export BUY results", csv,
f"NSE_Scan_{st.session_state.scan_mode}_{ts}.csv", "text/csv")
elif st.session_state.results:
st.warning("No stocks match current filters.")
else:
st.info("Select Universe + Mode, then press SCAN.")


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
f'<div style="background:{b_col}11;border:1px solid {b_col}33;border-radius:8px;'
f'padding:10px 16px;margin-bottom:14px;">'
f'<span style="font-family:Syne,sans-serif;font-size:15px;color:{b_col};">'
f'Market Breadth: <strong>{b_sig}</strong></span></div>',
unsafe_allow_html=True,
)

bm1,bm2,bm3,bm4,bm5,bm6 = st.columns(6)
bm1.metric("% Above EMA50",  f'{breadth["pct_above_ema50"]}%')
bm2.metric("% in BREAKOUT",  f'{breadth["pct_breakout"]}%')
bm3.metric("Advancing",      breadth["advancing"])
bm4.metric("Declining",      breadth["declining"])
bm5.metric("A/D Ratio",      breadth["ad_ratio"])
bm6.metric("Liquid Stocks",  breadth["liquid_count"])

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
"Count": sum(1 for r in all_results if r.get("Sector")==k)}
for k, v in sorted(sector_data.items(), key=lambda x: -x[1])
])
hm_html = '<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(170px,1fr));gap:8px;">'
for _, row in sec_df.iterrows():
score = row["Avg Score"]
bar_col = "#22c55e" if score >= 70 else ("#d97706" if score >= 55 else "#ef4444")
pct = min(100, score)
hm_html += (
f'<div style="background:#111120;border:1px solid #1e1e40;'
f'border-radius:7px;padding:10px 12px;">'
f'<div style="color:#e8e8f4;font-size:11px;font-weight:600;'
f'font-family:DM Sans,sans-serif;">{row["Sector"]}</div>'
f'<div style="color:#6b7090;font-size:10px;'
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
dist_data   = {"Advancing": breadth["advancing"], "Unchanged": breadth["unchanged"], "Declining": breadth["declining"]}
dist_colors = {"Advancing":"#22c55e","Unchanged":"#d97706","Declining":"#ef4444"}
total_shown = sum(dist_data.values())
dist_html = '<div style="display:flex;gap:8px;">'
for label, count in dist_data.items():
pct2 = round(count/total_shown*100,1) if total_shown else 0
col  = dist_colors[label]
dist_html += (
f'<div style="flex:1;background:#111120;border:1px solid {col}33;'
f'border-radius:7px;padding:12px;text-align:center;">'
f'<div style="color:{col};font-size:22px;font-weight:600;'
f'font-family:JetBrains Mono,monospace;">{count}</div>'
f'<div style="color:#6b7090;font-size:11px;font-family:DM Sans,sans-serif;">{label}</div>'
f'<div style="color:{col};font-size:11px;'
f'font-family:JetBrains Mono,monospace;">{pct2}%</div>'
f'</div>'
)
dist_html += "</div>"
st.markdown(dist_html, unsafe_allow_html=True)

# RS rank distribution
st.markdown("---")
st.subheader("RS Rank Distribution")
rs_buckets = {"Top 80-100":0, "Upper 60-79":0, "Mid 40-59":0, "Lower 20-39":0, "Bottom 0-19":0}
for r in all_results:
rk = r.get("RS_Rank", 50)
if rk >= 80:   rs_buckets["Top 80-100"]   += 1
elif rk >= 60: rs_buckets["Upper 60-79"]  += 1
elif rk >= 40: rs_buckets["Mid 40-59"]    += 1
elif rk >= 20: rs_buckets["Lower 20-39"]  += 1
else:           rs_buckets["Bottom 0-19"] += 1
rs_cols = st.columns(5)
for col, (label, cnt) in zip(rs_cols, rs_buckets.items()):
col.metric(label, cnt)


# ═══════════════════════════════════════════════════════════════════
# DETAIL TAB
# ═══════════════════════════════════════════════════════════════════
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

# Phase timeline
phases_order = [PHASE_IDLE, PHASE_SETUP, PHASE_ENTRY, PHASE_CONT, PHASE_BRK, PHASE_EXIT]
history = st.session_state.get("phase_history", {}).get(sel, [])

ph_html = '<div style="display:flex;gap:5px;margin-bottom:12px;flex-wrap:wrap;">'
for ph in phases_order:
active = ph == phase
bg   = PHASE_COLORS[ph] if active else "#1e1e40"
brd  = f"1px solid {PHASE_COLORS[ph]}" if active else "1px solid #1e1e40"
# UI-1: dark text on bright active phase bg
txt_active = {
"#00dd88":"#064e3b", "#22aa55":"#064e3b",
"#2255cc":"#dbeafe", "#b87333":"#431407",
"#555577":"#c4c6d0", "#cc4444":"#fee2e2",
}.get(PHASE_COLORS[ph], "#e8e8f4")
ph_html += (
f'<div style="background:{bg};border:{brd};'
f'color:{"" + txt_active if active else "#6b7090"};'
f'padding:4px 12px;border-radius:5px;font-size:11px;'
f'font-weight:{"600" if active else "400"};'
f'font-family:DM Sans,sans-serif;">'
f'{ph}{"  ◀" if active else ""}</div>'
)
ph_html += "</div>"
st.markdown(ph_html, unsafe_allow_html=True)

if len(history) >= 2:
transitions = []
for j in range(1, len(history)):
prev_ts, prev_ph = history[j-1]
curr_ts, curr_ph = history[j]
arrow = "↗" if PHASE_ORDER.get(curr_ph,0) > PHASE_ORDER.get(prev_ph,0) else "↘"
transitions.append(
f'{prev_ph} {arrow} {curr_ph}'
f'  <span style="color:#3a3a60;font-size:10px;">({curr_ts[:16]})</span>'
)
st.markdown(
'<details><summary style="color:#6b7090;font-size:11px;cursor:pointer;">'
f'Phase History ({len(history)} states)</summary>'
'<div style="font-size:11px;color:#6b7090;padding:6px 0;'
'font-family:JetBrains Mono,monospace;">'
+ "<br>".join(transitions) + '</div></details>',
unsafe_allow_html=True,
)

d1,d2,d3,d4,d5 = st.columns(5)
d1.metric("LTP",        fmt(r["LTP"]),  f"{'+' if chg>=0 else ''}{chg}%")
d2.metric("Entry ⚡",   fmt(r["Entry"]))
d3.metric("Stop Loss",  fmt(r["SL"]))
d4.metric("Score",      r["Score"])
d5.metric("Confidence", f"{conf}% ({conf_lbl})")

t1c,t2c,t3c,r1c = st.columns(4)
t1c.metric("T1", fmt(r["T1"]))
t2c.metric("T2", fmt(r["T2"]))
t3c.metric("T3", fmt(r["T3"]))
risk = round(r["Entry"] - r["SL"], 2) if r.get("Entry") and r.get("SL") else 0
r1c.metric("Risk/Share", fmt(risk))

# Position sizing
st.markdown("---")
with st.expander("Position Sizing (Volatility-Normalized)", expanded=True):
_acct_size = account_size if "account_size" in dir() else 500000
_risk_pct  = risk_pct_input if "risk_pct_input" in dir() else 0.02
ps = position_size(
account_size = _acct_size,
entry        = r["Entry"],
sl           = r["SL"],
atr_val      = r.get("ATR", risk),
atr_mean     = r.get("ATR_Mean", risk),
vix_val      = vix_val,
risk_pct     = _risk_pct,
)
ps1,ps2,ps3,ps4 = st.columns(4)
ps1.metric("Suggested Qty",  ps["final_qty"])
ps2.metric("Capital Used",   fmt(ps["capital_used"]))
ps3.metric("Max Loss",       fmt(ps["max_loss"]))
ps4.metric("Risk per Share", fmt(risk))
st.markdown(
f'<div style="background:#111120;border:1px solid #1e1e40;border-radius:6px;'
f'padding:8px 12px;margin-top:8px;font-size:11px;'
f'font-family:JetBrains Mono,monospace;color:#6b7090;">'
f'Base: <span style="color:#e8e8f4;">{ps["base_qty"]}</span>  ×  '
f'VIX adj <span style="color:#f59e0b;">{ps["vix_adj"]}×</span>  ×  '
f'ATR adj <span style="color:#f59e0b;">{ps["atr_adj"]}×</span>  =  '
f'<span style="color:#22c55e;font-weight:600;">{ps["final_qty"]} shares</span>'
f'</div>',
unsafe_allow_html=True,
)

# Confidence breakdown
with st.expander(f"Confidence Model — {conf}% ({conf_lbl})", expanded=False):
factors = {
"Phase alignment":   {PHASE_BRK:20,PHASE_CONT:17,PHASE_ENTRY:13,PHASE_SETUP:7,PHASE_IDLE:2,PHASE_EXIT:0}.get(phase,0),
"Score quality":     round(min(20, r["Score"]*0.20),1),
"Volume confirmed":  15 if r.get("VolConf") else 5,
"EMA stack":         15 if r.get("EMAStack") else 7,
"HTF alignment":     15 if r.get("HTFUp",True) else 0,
"Market regime":     10 if r.get("Regime")=="BULLISH" else 2,
"Exhaustion drag":   -min(5, r.get("ExtN",0)*2),
"RS rank bonus":     5 if r.get("RS_Rank",50)>=90 else (3 if r.get("RS_Rank",50)>=80 else 0),
"Phase progression": r.get("PhaseBonus",0),
}
for fname, fval in factors.items():
col_f = "#22c55e" if fval >= 10 else ("#f59e0b" if fval >= 5 else ("#ef4444" if fval < 0 else "#6b7090"))
st.markdown(
f'<div style="display:flex;justify-content:space-between;'
f'padding:4px 0;border-bottom:1px solid #1e1e40;">'
f'<span style="color:#6b7090;font-size:12px;'
f'font-family:DM Sans,sans-serif;">{fname}</span>'
f'<span style="color:{col_f};font-size:12px;font-weight:600;'
f'font-family:JetBrains Mono,monospace;">{fval:+.0f}</span>'
f'</div>',
unsafe_allow_html=True,
)

# Exhaustion signals
ext_n = r.get("ExtN",0)
ext_labels = r.get("ExtLabels",[])
ext_flags  = r.get("ExtFlags",{})
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
f"⚠ {ext_n} Caution Signal{'s' if ext_n>1 else ''} — "
f"{'DO NOT enter' if ext_n>=3 else 'Reduce size'}",
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
info_cols[0].metric("RSI",         r.get("RSI","—"))
info_cols[1].metric("RS Rank",      f'{r.get("RS_Rank",50)}/100')
info_cols[2].metric("Liq (₹Cr/d)", r.get("AvgTradedCr","—"))
info_cols[3].metric("Raw RS Diff",  f"{r.get('RS',0):+.1f}%")

if r["Entry"] != r["LTP"]:
st.info(
f"⚡ Entry ₹{r['Entry']:,} is the trigger price. "
f"LTP = ₹{r['LTP']:,}. Place order near Entry when phase = ENTRY/BREAKOUT."
)


# ═══════════════════════════════════════════════════════════════════
# ANALYTICS TAB
# ═══════════════════════════════════════════════════════════════════
with tab_analytics:
st.subheader("Signal Log & Outcome Tracking")
log = st.session_state.signal_log
if not log:
st.info("No signals logged yet. Run a scan to populate.")
else:
log_df = pd.DataFrame(log)
scan_mode_now = st.session_state.scan_mode

log_df["stale"] = log_df.apply(
lambda row: signal_is_stale(row["timestamp"], row.get("mode", scan_mode_now)),
axis=1,
)
log_df["age"] = log_df.apply(
lambda row: signal_age_label(row["timestamp"], row.get("mode", scan_mode_now))[0],
axis=1,
)

total_sig  = len(log_df)
pending    = len(log_df[log_df["outcome"]=="Pending"])
stale_cnt  = int(log_df["stale"].sum())
wins       = len(log_df[log_df["outcome"]=="Win"])
losses     = len(log_df[log_df["outcome"]=="Loss"])
active_df  = log_df[~log_df["stale"]]
active_wins   = len(active_df[active_df["outcome"]=="Win"])
active_losses = len(active_df[active_df["outcome"]=="Loss"])
win_rate   = round(wins/(wins+losses)*100, 1) if (wins+losses) > 0 else None
active_wr  = round(active_wins/(active_wins+active_losses)*100, 1) if (active_wins+active_losses)>0 else None

am1,am2,am3,am4,am5 = st.columns(5)
am1.metric("Total Signals", total_sig)
am2.metric("Pending",       pending)
am3.metric("Expired",       stale_cnt)
am4.metric("Overall Win%",  f"{win_rate}%" if win_rate is not None else "—")
am5.metric("Active Win%",   f"{active_wr}%" if active_wr is not None else "—")

display_cols = ["timestamp","symbol","action","phase","score","confidence",
"rs_rank","entry","sl","t1","age","outcome"]
display_cols = [c for c in display_cols if c in log_df.columns]

edited = st.data_editor(
log_df[display_cols].tail(100),
column_config={
"outcome": st.column_config.SelectboxColumn(
"Outcome", options=["Pending","Win","Loss","BE"], required=True
),
"age":     st.column_config.TextColumn("Age", disabled=True),
"rs_rank": st.column_config.NumberColumn("RS Rank", disabled=True),
},
hide_index=True, use_container_width=True,
)
if edited is not None and len(edited) == len(log_df.tail(100)):
for i, row in edited.iterrows():
idx = len(log_df) - 100 + i
if 0 <= idx < len(log):
log[idx]["outcome"] = row["outcome"]

if wins+losses > 0:
st.markdown("---")
st.subheader("Phase Win-Rate (active signals only)")
phase_stats = {}
for entry in log:
if signal_is_stale(entry["timestamp"], entry.get("mode", scan_mode_now)):
continue
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

if st.button("Export Signal Log"):
export_df = pd.DataFrame(log).drop(columns=["ExtFlags"],errors="ignore")
csv = export_df.to_csv(index=False)
ts  = datetime.now().strftime("%Y%m%d_%H%M%S")
st.download_button("Download", csv, f"NSE_SignalLog_{ts}.csv","text/csv")
