"""
DAILY SIGNAL — "Sinyal Dari Langit" Dashboard v3.0
Premium terminal-style UI untuk BEI Stock Scanner.

Design System:
    - Typography : Manrope (heading) + Inter (body/angka, tabular-nums)
    - Palette    : dark terminal (#0a0e1a base), emerald/amber/red signal colors
    - Components : hero card, metric tile, gauge bar, signal card, chip/badge

9 halaman: Home, Top Signals, Signal Detail ("Why This Signal?"),
Historical Signals, Signal Performance, Sector Rotation, Portfolio,
System Health, (System Logs digabung ke System Health).

TIDAK ADA perubahan ke engine/scoring/database — murni presentasi.
Kolom baru (raw_score, confidence, factor_contribution, sector_bonus,
pct_above_ema20/50/200) dari migration 002 dipakai bila tersedia,
dengan fallback aman bila migration belum dijalankan (semua .get()
dengan default, tidak pernah crash karena kolom belum ada).
"""

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from datetime import date, timedelta, datetime
import pytz

_WIB = pytz.timezone("Asia/Jakarta")

def _now_wib() -> datetime:
    """Waktu sekarang dalam WIB."""
    return datetime.now(_WIB)

import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dotenv import load_dotenv
load_dotenv()

# ══════════════════════════════════════════════════════════════════
#  PAGE CONFIG
# ══════════════════════════════════════════════════════════════════

st.set_page_config(
    page_title="Sinyal Dari Langit — Daily Signal",
    page_icon="✦",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ══════════════════════════════════════════════════════════════════
#  DESIGN SYSTEM — CSS
# ══════════════════════════════════════════════════════════════════

_CSS_BLOCK = """
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Manrope:wght@500;600;700;800&family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>

/* ── Base tokens ─────────────────────────────────────────────── */
:root{
    --bg:            #0a0e1a;
    --surface:       #131824;
    --surface-2:     #171d2c;
    --border:        #1f2937;
    --border-soft:   #1a2233;
    --text:          #e8ebf2;
    --text-dim:      #9aa4b8;
    --text-faint:    #5c6478;
    --accent:        #60a5fa;
    --accent-soft:   rgba(96,165,250,.12);
    --strong-buy:    #00c896;
    --buy:           #4ade80;
    --watchlist:     #fbbf24;
    --avoid:         #f87171;
    --strong-buy-bg: rgba(0,200,150,.12);
    --buy-bg:        rgba(74,222,128,.12);
    --watchlist-bg:  rgba(251,191,36,.12);
    --avoid-bg:      rgba(248,113,113,.12);
}

html, body, [class*="css"]{
    font-family: 'Inter', -apple-system, sans-serif;
}
h1,h2,h3,h4, .ds-heading{
    font-family: 'Manrope', sans-serif !important;
}

.main{ padding: 0 1.4rem; background: var(--bg); }
.block-container{ padding-top: 1rem; padding-bottom: 2rem; max-width: 1400px; }
[data-testid="stAppViewContainer"]{ background: var(--bg); }
[data-testid="stHeader"]{ background: transparent; }

/* Angka selalu tabular (sejajar) */
.ds-num{ font-variant-numeric: tabular-nums; font-feature-settings: "tnum"; }

/* ── Sidebar ──────────────────────────────────────────────────── */
div[data-testid="stSidebarContent"]{
    background: var(--surface);
    border-right: 1px solid var(--border);
}
.ds-brand{
    font-family:'Manrope',sans-serif; font-weight:800; font-size:1.3rem;
    letter-spacing:-.02em; color:var(--text); margin-bottom:0;
    display:flex; align-items:center; gap:8px;
}
.ds-brand-sub{ color:var(--text-faint); font-size:.72rem; letter-spacing:.08em;
    text-transform:uppercase; margin-top:2px; margin-bottom:14px; }

div[data-testid="stSidebarContent"] div[role="radiogroup"] label{
    padding: 9px 12px !important; border-radius: 8px !important;
    margin-bottom: 2px !important; transition: background .15s;
}
div[data-testid="stSidebarContent"] div[role="radiogroup"] label:hover{
    background: var(--surface-2);
}

/* ── Streamlit native metric (dipakai minimal, mostly diganti ds-metric) */
div[data-testid="metric-container"]{
    background: var(--surface); border:1px solid var(--border);
    border-radius: 12px; padding: 14px 16px;
}
div[data-testid="metric-container"] label{ color:var(--text-dim) !important; font-size:.75rem; }
div[data-testid="metric-container"] div[data-testid="stMetricValue"]{
    font-size:1.35rem; font-weight:700; color:var(--text); font-family:'Inter',sans-serif;
}

/* ── Typography helpers ──────────────────────────────────────── */
.ds-page-title{ font-family:'Manrope',sans-serif; font-weight:800; font-size:1.7rem;
    color:var(--text); letter-spacing:-.02em; margin-bottom:2px; }
.ds-page-sub{ color:var(--text-faint); font-size:.85rem; margin-bottom:1.1rem; }
.ds-section{ font-family:'Manrope',sans-serif; font-weight:700; font-size:.95rem;
    color:var(--text); margin: 22px 0 10px; display:flex; align-items:center; gap:8px; }
.ds-section .ds-section-line{ flex:1; height:1px; background:var(--border); }
.ds-caption{ color:var(--text-faint); font-size:.78rem; }

/* ── Cards ────────────────────────────────────────────────────── */
.ds-card{
    background: var(--surface); border:1px solid var(--border);
    border-radius: 14px; padding: 18px 20px; margin-bottom: 12px;
}
.ds-card-flush{ padding:0; overflow:hidden; }
.ds-hero{
    background: linear-gradient(135deg, var(--surface) 0%, var(--surface-2) 100%);
    border:1px solid var(--border); border-radius:16px; padding:22px 26px; margin-bottom:16px;
}

/* ── Metric tile (custom, dipakai di Home & Signal Detail) ──── */
.ds-tile{
    background: var(--surface); border:1px solid var(--border); border-radius:12px;
    padding:13px 16px; height:100%;
}
.ds-tile-label{ color:var(--text-faint); font-size:.7rem; text-transform:uppercase;
    letter-spacing:.06em; margin-bottom:5px; }
.ds-tile-value{ font-family:'Inter',sans-serif; font-weight:700; font-size:1.25rem;
    color:var(--text); font-variant-numeric: tabular-nums; }
.ds-tile-delta{ font-size:.74rem; margin-top:3px; }
.ds-up{ color: var(--buy); } .ds-down{ color: var(--avoid); } .ds-flat{ color:var(--text-faint); }

/* ── Badges / Chips ───────────────────────────────────────────── */
.ds-badge{ display:inline-flex; align-items:center; gap:5px; padding:3px 11px;
    border-radius:20px; font-weight:700; font-size:.71rem; letter-spacing:.02em; }
.ds-badge::before{ content:''; width:6px; height:6px; border-radius:50%; }
.ds-badge-sb{ background:var(--strong-buy-bg); color:var(--strong-buy); }
.ds-badge-sb::before{ background:var(--strong-buy); }
.ds-badge-buy{ background:var(--buy-bg); color:var(--buy); }
.ds-badge-buy::before{ background:var(--buy); }
.ds-badge-wl{ background:var(--watchlist-bg); color:var(--watchlist); }
.ds-badge-wl::before{ background:var(--watchlist); }
.ds-badge-av{ background:var(--avoid-bg); color:var(--avoid); }
.ds-badge-av::before{ background:var(--avoid); }

.ds-chip{ display:inline-block; padding:2px 9px; border-radius:6px; font-size:.71rem;
    background:var(--surface-2); color:var(--text-dim); border:1px solid var(--border); }
.ds-chip-accent{ background:var(--accent-soft); color:var(--accent); border-color:transparent; }

.ds-conf{ display:inline-flex; align-items:center; gap:4px; font-size:.71rem; font-weight:600; }
.ds-conf-dots span{ width:5px; height:5px; border-radius:50%; display:inline-block; margin-right:2px; background:var(--border); }

/* ── Gauge / progress bars ───────────────────────────────────── */
.ds-gauge-row{ display:flex; align-items:center; gap:10px; margin:7px 0; }
.ds-gauge-label{ width:92px; font-size:.78rem; color:var(--text-dim); flex-shrink:0; }
.ds-gauge-track{ flex:1; height:9px; background:var(--surface-2); border-radius:5px; overflow:hidden; }
.ds-gauge-fill{ height:100%; border-radius:5px; }
.ds-gauge-val{ width:52px; text-align:right; font-size:.78rem; font-weight:700; color:var(--text);
    font-variant-numeric: tabular-nums; flex-shrink:0; }

/* ── Signal list row (Top Signals / Home top picks) ──────────── */
.ds-row{
    display:flex; align-items:center; gap:14px; padding:12px 16px;
    border-bottom:1px solid var(--border-soft); transition:background .12s;
}
.ds-row:last-child{ border-bottom:none; }
.ds-row:hover{ background: var(--surface-2); }
.ds-row-ticker{ font-weight:700; font-size:.92rem; color:var(--text); width:64px; flex-shrink:0; }
.ds-row-sector{ color:var(--text-faint); font-size:.72rem; }

/* ── Reason checklist ─────────────────────────────────────────── */
.ds-reason{ display:flex; align-items:flex-start; gap:8px; padding:6px 0; font-size:.87rem; color:var(--text-dim); }
.ds-reason-check{ color:var(--strong-buy); font-weight:800; flex-shrink:0; }

/* ── Health dot ───────────────────────────────────────────────── */
.ds-health{ display:flex; align-items:center; gap:8px; padding:9px 0; }
.ds-health-dot{ width:8px; height:8px; border-radius:50%; flex-shrink:0; }
.ds-health-ok{ background:var(--buy); box-shadow:0 0 6px var(--buy); }
.ds-health-bad{ background:var(--avoid); box-shadow:0 0 6px var(--avoid); }
.ds-health-warn{ background:var(--watchlist); box-shadow:0 0 6px var(--watchlist); }

hr{ border-color: var(--border) !important; }
.ds-hr{ height:1px; background:var(--border); margin:14px 0; border:none; }

/* ── Flow / VSA badges (BARU, v2.5.0) ────────────────────────── */
.ds-flow{ display:inline-flex; align-items:center; gap:5px; padding:3px 10px;
    border-radius:20px; font-weight:700; font-size:.68rem; letter-spacing:.02em; white-space:nowrap; }
.ds-flow::before{ content:''; width:6px; height:6px; border-radius:50%; flex-shrink:0; }
.ds-flow-acc{ background: var(--strong-buy-bg); color: var(--strong-buy); }
.ds-flow-acc::before{ background: var(--strong-buy); }
.ds-flow-dist{ background: var(--avoid-bg); color: var(--avoid); }
.ds-flow-dist::before{ background: var(--avoid); }
.ds-flow-climax{ background: var(--watchlist-bg); color: var(--watchlist); }
.ds-flow-climax::before{ background: var(--watchlist); }
.ds-flow-weak{ background: var(--surface-2); color: var(--text-faint); }
.ds-flow-weak::before{ background: var(--text-faint); }
.ds-flow-neutral{ background: transparent; color: var(--text-faint); border:1px dashed var(--border); }
.ds-flow-neutral::before{ display:none; }

/* ── Trend Structure chip (BARU, v2.5.0) ─────────────────────── */
.ds-struct{ display:inline-block; padding:2px 10px; border-radius:6px; font-size:.71rem; font-weight:600; }
.ds-struct-good{ background: var(--strong-buy-bg); color: var(--strong-buy); }
.ds-struct-neutral{ background: var(--surface-2); color: var(--text-dim); }
.ds-struct-weak{ background: var(--avoid-bg); color: var(--avoid); }

/* ── Flow Radar card (Home, signature widget BARU v2.5.0) ────── */
.ds-radar-item{ display:flex; align-items:center; gap:12px; padding:11px 16px;
    border-bottom:1px solid var(--border-soft); }
.ds-radar-item:last-child{ border-bottom:none; }
.ds-radar-rank{ width:20px; color:var(--text-faint); font-size:.78rem; font-weight:700; flex-shrink:0; }
.ds-radar-bar-track{ flex:1; height:6px; background:var(--surface-2); border-radius:3px; overflow:hidden; }
.ds-radar-bar-fill{ height:100%; border-radius:3px; background:linear-gradient(90deg, var(--strong-buy) 0%, #00e6a8 100%); }

/* Streamlit widget refinement */
.stDataFrame{ border-radius:12px; overflow:hidden; border:1px solid var(--border); }
button[kind="secondary"], button[kind="primary"]{ border-radius:9px !important; }
</style>
"""

# st.html() dipakai (bukan st.markdown unsafe_allow_html) — st.html
# me-render HTML/CSS mentah TANPA lewat markdown parser sama sekali,
# menghindari kelas bug di mana konten CSS (komentar box-drawing,
# selector atribut [attr="value"]) bisa salah ditafsirkan markdown
# parser dan ikut muncul sebagai teks mentah di halaman.
# Fallback ke st.markdown untuk Streamlit versi sangat lama (<1.29).
try:
    st.html(_CSS_BLOCK)
except AttributeError:
    st.markdown(_CSS_BLOCK, unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════
#  SAFE HELPERS
# ══════════════════════════════════════════════════════════════════

def sf(v, d=0.0):
    if v is None: return d
    try: return float(v)
    except: return d

def _styler_apply(styler, func, subset=None):
    """
    Kompatibilitas pandas Styler lintas versi: pandas >= 2.1 memakai
    .map(), versi lebih lama memakai .applymap() (sudah dihapus di
    pandas terbaru). Dicoba .map() dulu, fallback ke .applymap().
    """
    try:
        return styler.map(func, subset=subset)
    except AttributeError:
        return styler.applymap(func, subset=subset)


def si(v, d=0):
    if v is None: return d
    try: return int(float(v))
    except: return d

def ss(v, d=""):
    return str(v) if v is not None else d

def fmt_rp(v):  return f"Rp{sf(v):,.0f}"
def fmt_pct(v, dec=1, dec100=False):
    x = sf(v) * (100 if dec100 else 1)
    return f"{x:+.{dec}f}%"

SIGNAL_COLOR = {"STRONG_BUY":"#00c896","BUY":"#4ade80","WATCHLIST":"#fbbf24","AVOID":"#f87171"}
SIGNAL_BG    = {"STRONG_BUY":"rgba(0,200,150,.12)","BUY":"rgba(74,222,128,.12)",
                "WATCHLIST":"rgba(251,191,36,.12)","AVOID":"rgba(248,113,113,.12)"}
SIGNAL_LABEL = {"STRONG_BUY":"STRONG BUY","BUY":"BUY","WATCHLIST":"WATCHLIST","AVOID":"AVOID"}

def score_color(s):
    s = sf(s)
    if s >= 75: return "#00c896"
    if s >= 60: return "#4ade80"
    if s >= 45: return "#fbbf24"
    return "#f87171"

def signal_badge(t):
    cls = {"STRONG_BUY":"ds-badge-sb","BUY":"ds-badge-buy","WATCHLIST":"ds-badge-wl","AVOID":"ds-badge-av"}.get(t,"ds-badge-av")
    label = SIGNAL_LABEL.get(t, ss(t).replace("_"," "))
    return f'<span class="ds-badge {cls}">{label}</span>'

def confidence_badge(c):
    """Confidence dari migration 002 (compute_confidence) — fallback aman jika belum ada."""
    c = ss(c, "Low")
    dots = {"Very High":4, "High":3, "Medium":2, "Low":1}.get(c, 1)
    colors = {"Very High":"#00c896","High":"#4ade80","Medium":"#fbbf24","Low":"#9aa4b8"}
    color = colors.get(c, "#9aa4b8")
    dot_html = "".join(
        f'<span style="background:{color if i < dots else "#232c3d"}"></span>'
        for i in range(4)
    )
    return f'<span class="ds-conf" style="color:{color}"><span class="ds-conf-dots">{dot_html}</span>{c}</span>'

def gauge_row(label, val, mx, color=None):
    pct = min(sf(val)/mx*100, 100) if mx > 0 else 0
    c = color or score_color(pct)
    return (
        f'<div class="ds-gauge-row">'
        f'<div class="ds-gauge-label">{label}</div>'
        f'<div class="ds-gauge-track"><div class="ds-gauge-fill" style="width:{pct:.0f}%;background:{c}"></div></div>'
        f'<div class="ds-gauge-val">{sf(val):.0f}/{mx:.0f}</div>'
        f'</div>'
    )

def vsa_badge(vsa_signal, compact=False):
    """
    Badge untuk klasifikasi bar VSA (BARU, v2.5.0) -- lihat
    ta_engine.py::calc_vsa_signal. compact=True -- versi ringkas
    (dot + label pendek) untuk baris tabel yang padat.
    """
    v = ss(vsa_signal, "")
    spec = {
        "ACCUMULATION": ("ds-flow-acc",    "Akumulasi",  "ACC"),
        "DISTRIBUTION": ("ds-flow-dist",   "Distribusi", "DIST"),
        "CLIMAX_UP":    ("ds-flow-climax", "Climax ↑",   "CLMX"),
        "CLIMAX_DOWN":  ("ds-flow-climax", "Climax ↓",   "CLMX"),
        "NO_DEMAND":    ("ds-flow-weak",   "No Demand",  "WEAK"),
    }
    if v not in spec:
        return '<span class="ds-flow ds-flow-neutral">Netral</span>' if not compact else ""
    cls, full_label, short_label = spec[v]
    label = short_label if compact else full_label
    return f'<span class="ds-flow {cls}">{label}</span>'

def structure_chip(structure):
    """Chip untuk trend_structure (BARU, v2.5.0) -- warna sesuai bonus di _score_trend."""
    s = ss(structure, "")
    if not s:
        return ""
    good = {"Pullback", "Higher Low"}
    weak = {"Lower High", "Lower Low"}
    cls = "ds-struct-good" if s in good else ("ds-struct-weak" if s in weak else "ds-struct-neutral")
    return f'<span class="ds-struct {cls}">{s}</span>'

def tile(label, value, delta=None, delta_dir="flat"):
    dcls = {"up":"ds-up","down":"ds-down","flat":"ds-flat"}.get(delta_dir,"ds-flat")
    delta_html = f'<div class="ds-tile-delta {dcls}">{delta}</div>' if delta else ""
    return (
        f'<div class="ds-tile"><div class="ds-tile-label">{label}</div>'
        f'<div class="ds-tile-value ds-num">{value}</div>{delta_html}</div>'
    )

def section(title, icon=""):
    st.markdown(
        f'<div class="ds-section">{icon} {title}<div class="ds-section-line"></div></div>',
        unsafe_allow_html=True
    )

def regime_visual(r):
    return {
        "BULL":     ("🟢", "#00c896", "Kondisi pasar mendukung — sinyal beli lebih terpercaya."),
        "SIDEWAYS": ("🟡", "#fbbf24", "Pasar konsolidasi — pilih saham selektif dengan skor tinggi."),
        "BEAR":     ("🔴", "#f87171", "Pasar melemah — kurangi eksposur, perketat stop loss."),
    }.get(r, ("⚪", "#9aa4b8", "Status pasar belum diketahui."))

DARK_BG = "rgba(0,0,0,0)"
PLOT_BG = "rgba(19,24,36,1)"
GRID    = "#1f2937"
LAYOUT  = dict(paper_bgcolor=DARK_BG, plot_bgcolor=PLOT_BG,
               font=dict(family="Inter, sans-serif", color="#9aa4b8", size=11),
               margin=dict(l=0,r=0,t=30,b=0),
               xaxis=dict(gridcolor=GRID), yaxis=dict(gridcolor=GRID))


# ══════════════════════════════════════════════════════════════════
#  DB CONNECTION
# ══════════════════════════════════════════════════════════════════

@st.cache_resource
def get_db():
    try:
        from src.core.database import get_db as _db
        return _db()
    except Exception as e:
        st.error(f"❌ Database: {e}")
        return None


# ══════════════════════════════════════════════════════════════════
#  DATA LOADERS
#  (Query LOGIC tidak diubah dari versi sebelumnya — hanya kolom
#  baru dari migration 002 ditambahkan ke SELECT eksplisit, karena
#  presentasi butuh field itu. Tidak menyentuh engine/scoring/DB.)
# ══════════════════════════════════════════════════════════════════

@st.cache_data(ttl=300)
def load_signals(sig_date=None):
    try:
        db = get_db()
        if not db: return []
        d = sig_date or date.today().isoformat()
        r = db.table("signals").select("*").eq("signal_date", d)\
              .order("raw_score", desc=True).execute()
        return r.data or []
    except: return []

@st.cache_data(ttl=300)
def load_signals_range(days=30):
    try:
        db = get_db()
        if not db: return []
        since = (date.today()-timedelta(days=days)).isoformat()
        cols = ("signal_date,ticker,signal_type,composite_score,close_price,"
                "entry_price,stop_loss,target_1,target_2,risk_reward,rsi,adx,"
                "volume_ratio,rel_strength,sector,ema20,ema50,ema200,"
                "trend_score,momentum_score,volume_score,strength_score,volatility_score,"
                "flow_score,cmf,mfi,vsa_signal,"
                "raw_score,sector_bonus,confidence")
        r = db.table("signals").select(cols).gte("signal_date", since)\
              .order("signal_date", desc=True).order("raw_score", desc=True).execute()
        return r.data or []
    except: return []

@st.cache_data(ttl=300)
def load_regime():
    try:
        db = get_db()
        if not db: return None
        r = db.table("market_regimes").select("*").order("regime_date", desc=True).limit(1).execute()
        return r.data[0] if r.data else None
    except: return None

@st.cache_data(ttl=300)
def load_regime_history(days=30):
    try:
        db = get_db()
        if not db: return []
        r = db.table("market_regimes")\
              .select("regime_date,regime,ihsg_close,ihsg_rsi,change_5d_pct,"
                      "pct_above_ema20,pct_above_ema50,pct_above_ema200")\
              .order("regime_date", desc=True).limit(days).execute()
        return r.data or []
    except: return []

@st.cache_data(ttl=300)
def load_sectors():
    try:
        db = get_db()
        if not db: return []
        r = db.table("sector_rankings").select("*")\
              .order("rank_date", desc=True).order("rank_position").limit(20).execute()
        return r.data or []
    except: return []

@st.cache_data(ttl=60)
def load_open_positions():
    try:
        from src.portfolio.tracker import get_open_positions
        return get_open_positions()
    except: return []

@st.cache_data(ttl=300)
def load_closed_positions(lim=100):
    try:
        from src.portfolio.tracker import get_closed_positions
        return get_closed_positions(lim)
    except: return []

@st.cache_data(ttl=300)
def load_portfolio_stats():
    try:
        from src.portfolio.tracker import get_portfolio_stats
        return get_portfolio_stats()
    except: return None

@st.cache_data(ttl=300)
def load_equity_curve():
    try:
        db = get_db()
        if not db: return []
        r = db.table("portfolio_snapshots")\
              .select("snapshot_date,total_equity,unrealized_pnl,realized_pnl_ytd")\
              .order("snapshot_date").limit(365).execute()
        return r.data or []
    except: return []

@st.cache_data(ttl=300)
def load_backtests():
    try:
        from src.backtest.engine import get_backtest_results
        return get_backtest_results(limit=200)
    except: return []

@st.cache_data(ttl=600)
def load_logs(lim=50):
    try:
        db = get_db()
        if not db: return []
        r = db.table("system_logs").select("log_time,level,module,message")\
              .order("log_time", desc=True).limit(lim).execute()
        return r.data or []
    except: return []

@st.cache_data(ttl=120)
def load_universe_count():
    try:
        db = get_db()
        if not db: return 0
        r = db.table("stocks").select("ticker", count="exact")\
              .eq("is_active", True).eq("is_delisted", False).limit(1).execute()
        return r.count or 0
    except: return 0

@st.cache_data(ttl=120)
def load_last_scan_run():
    try:
        db = get_db()
        if not db: return None
        r = db.table("scan_runs").select("*").eq("run_type", "DAILY_SCAN")\
              .order("started_at", desc=True).limit(1).execute()
        return r.data[0] if r.data else None
    except: return None


# ── Automatic Signal Evaluation loaders (signal_results) ────────────
# Signal Performance TIDAK LAGI pakai load_portfolio_stats/
# load_closed_positions/load_equity_curve di atas — fungsi itu
# dipertahankan (dipakai page_portfolio() legacy yang masih ada di
# backend, cuma disembunyikan dari nav) tapi Signal Performance kini
# 100% berbasis signal_results (evaluasi otomatis, bukan trading manual).

@st.cache_data(ttl=180)
def load_signal_results(days=90, status=None):
    try:
        db = get_db()
        if not db: return []
        since = (date.today() - timedelta(days=days)).isoformat()
        q = db.table("signal_results").select("*").gte("signal_date", since)
        if status:
            q = q.eq("status", status)
        r = q.order("signal_date", desc=True).execute()
        return r.data or []
    except: return []


@st.cache_data(ttl=300)
def load_broker_flow_top(limit=20):
    """Top saham berdasarkan net broker flow hari terakhir yang ada datanya."""
    try:
        from src.signals.broker_engine import get_top_accumulated_tickers
        return get_top_accumulated_tickers(limit=limit)
    except: return []

@st.cache_data(ttl=300)
def load_broker_flow_top_streak(min_streak_days, limit=20):
    try:
        from src.signals.broker_engine import get_top_accumulated_tickers
        return get_top_accumulated_tickers(limit=limit, min_streak_days=min_streak_days)
    except: return []

@st.cache_data(ttl=300)
def load_broker_flow_detail(ticker, days=30):
    try:
        from src.core.database import get_broker_flow_range
        return get_broker_flow_range(ticker, days=days)
    except: return []

@st.cache_data(ttl=300)
def load_full_broker_summary(ticker):
    try:
        from src.signals.broker_engine import get_full_broker_summary
        return get_full_broker_summary(ticker)
    except: return []

@st.cache_data(ttl=600)
def load_known_brokers():
    try:
        from src.signals.broker_engine import get_known_brokers
        return get_known_brokers()
    except: return []

@st.cache_data(ttl=300)
def load_broker_stalker(broker_code, limit=20):
    try:
        from src.signals.broker_engine import get_broker_stalker
        return get_broker_stalker(broker_code, limit=limit)
    except: return []

@st.cache_data(ttl=300)
def load_broker_footprint(ticker, broker_code, days=60):
    try:
        from src.signals.broker_engine import get_broker_footprint
        return get_broker_footprint(ticker, broker_code, days=days)
    except: return []

@st.cache_data(ttl=180)
def load_signal_results_all_closed():
    """Semua sinyal CLOSED/EXPIRED (tanpa batas hari) — untuk statistik jangka panjang."""
    try:
        db = get_db()
        if not db: return []
        r = db.table("signal_results").select("*")\
              .neq("status", "OPEN").order("exit_date", desc=True).limit(1000).execute()
        return r.data or []
    except: return []


# ══════════════════════════════════════════════════════════════════
#  SIDEBAR
# ══════════════════════════════════════════════════════════════════

PAGES = [
    ("home", "🏠", "Home"),
    ("signals", "🚀", "Top Signals"),
    ("detail", "🔍", "Signal Detail"),
    ("history", "📅", "Historical Signals"),
    ("performance", "📊", "Signal Performance"),
    ("sector", "🏭", "Sector Rotation"),
    ("broker", "🕵️", "Broker Flow"),
    # ("portfolio", "💼", "Portfolio"),  # DISEMBUNYIKAN dari UI — Signal
    # Performance sekarang pakai signal_results (Automatic Signal
    # Evaluation), bukan lagi Portfolio manual. Fungsi page_portfolio()
    # TIDAK dihapus (tetap ada di bawah, backend legacy tetap utuh),
    # cuma tidak dirutekan dari sidebar. Baris ini tinggal di-uncomment
    # kapan saja kalau Portfolio manual mau dimunculkan lagi.
    ("health", "⚙️", "System Health"),
]

def render_sidebar():
    with st.sidebar:
        st.markdown('<div class="ds-brand">✦ SINYAL DARI LANGIT</div>', unsafe_allow_html=True)
        st.markdown('<div class="ds-brand-sub">Daily Signal · BEI Scanner</div>', unsafe_allow_html=True)

        labels = [f"{icon}  {name}" for _, icon, name in PAGES]
        keys   = [k for k, _, _ in PAGES]
        choice = st.radio("nav", labels, label_visibility="collapsed")
        page = keys[labels.index(choice)]

        st.markdown("<hr class='ds-hr'>", unsafe_allow_html=True)

        regime = load_regime()
        if regime:
            r = ss(regime.get("regime"), "N/A")
            emoji, color, _ = regime_visual(r)
            st.markdown(
                f'<div style="display:flex;justify-content:space-between;align-items:center">'
                f'<span style="color:#9aa4b8;font-size:.78rem">Market Regime</span>'
                f'<span style="color:{color};font-weight:700;font-size:.85rem">{emoji} {r}</span></div>',
                unsafe_allow_html=True
            )
            ihsg = sf(regime.get("ihsg_close"))
            chg5 = sf(regime.get("change_5d_pct"))
            chg_color = "#4ade80" if chg5 >= 0 else "#f87171"
            st.markdown(
                f'<div style="margin-top:8px;font-size:.82rem;color:#e8ebf2" class="ds-num">'
                f'Rp{ihsg:,.0f} <span style="color:{chg_color}">({chg5:+.1f}%)</span></div>',
                unsafe_allow_html=True
            )
        else:
            st.caption("Belum ada data regime")

        st.markdown("<hr class='ds-hr'>", unsafe_allow_html=True)
        if st.button("🔄 Refresh Data", use_container_width=True):
            st.cache_data.clear(); st.rerun()
        st.caption(f"Update {_now_wib().strftime('%H:%M WIB')}")

    return page


# ══════════════════════════════════════════════════════════════════
#  PAGE — HOME
# ══════════════════════════════════════════════════════════════════

def page_home():
    st.markdown('<div class="ds-page-title">Market Overview</div>', unsafe_allow_html=True)
    st.markdown(f'<div class="ds-page-sub">{_now_wib().strftime("%A, %d %B %Y")}</div>', unsafe_allow_html=True)

    regime  = load_regime()
    signals = load_signals()
    sectors = load_sectors()

    # ── MARKET STATUS hero ──────────────────────────────────────
    section("MARKET STATUS", "🧭")
    if not regime:
        st.info("Belum ada data. Scan pertama berjalan ~17:30 WIB setiap hari bursa.")
    else:
        r = ss(regime.get("regime"), "N/A")
        emoji, color, desc = regime_visual(r)
        ihsg  = sf(regime.get("ihsg_close"))
        chg5  = sf(regime.get("change_5d_pct"))
        rsi   = sf(regime.get("ihsg_rsi"))
        adx   = sf(regime.get("ihsg_adx"))
        adv   = si(regime.get("advance_count")); dec = si(regime.get("decline_count"))
        breadth50 = regime.get("pct_above_ema50")

        st.markdown(
            f'<div class="ds-hero">'
            f'<div style="display:flex;justify-content:space-between;align-items:flex-start;flex-wrap:wrap;gap:16px">'
            f'<div>'
            f'<div style="font-size:.75rem;color:#9aa4b8;text-transform:uppercase;letter-spacing:.06em">Regime Pasar</div>'
            f'<div style="font-family:Manrope,sans-serif;font-weight:800;font-size:1.7rem;color:{color};margin-top:2px">{emoji} {r}</div>'
            f'<div style="color:#9aa4b8;font-size:.85rem;margin-top:4px;max-width:420px">{desc}</div>'
            f'</div>'
            f'<div class="ds-num" style="text-align:right">'
            f'<div style="font-size:.75rem;color:#9aa4b8;text-transform:uppercase;letter-spacing:.06em">IHSG</div>'
            f'<div style="font-weight:700;font-size:1.6rem;color:#e8ebf2">Rp{ihsg:,.0f}</div>'
            f'<div style="color:{"#4ade80" if chg5>=0 else "#f87171"};font-size:.85rem;font-weight:600">{chg5:+.1f}% (5D)</div>'
            f'</div>'
            f'</div></div>',
            unsafe_allow_html=True
        )

        c1, c2, c3, c4 = st.columns(4)
        with c1: st.markdown(tile("Market Strength (ADX)", f"{adx:.1f}"), unsafe_allow_html=True)
        with c2: st.markdown(tile("RSI IHSG", f"{rsi:.1f}"), unsafe_allow_html=True)
        with c3:
            ad_ratio = adv/dec if dec>0 else 0
            st.markdown(tile("Advance/Decline", f"{ad_ratio:.2f}", f"{adv}↑ / {dec}↓"), unsafe_allow_html=True)
        with c4:
            bv = f"{sf(breadth50):.0f}%" if breadth50 is not None else "N/A"
            st.markdown(tile("Breadth (>EMA50)", bv, "% saham di atas EMA50"), unsafe_allow_html=True)

        hist = load_regime_history(30)
        if len(hist) >= 5:
            df_h = pd.DataFrame(hist)
            df_h["regime_date"] = pd.to_datetime(df_h["regime_date"])
            df_h["ihsg_close"]  = df_h["ihsg_close"].apply(sf)
            df_h = df_h.sort_values("regime_date")
            rc = {"BULL":"#00c896","SIDEWAYS":"#fbbf24","BEAR":"#f87171"}
            df_h["mcolor"] = df_h["regime"].map(rc).fillna("#9aa4b8")
            fig = go.Figure(go.Scatter(
                x=df_h["regime_date"], y=df_h["ihsg_close"],
                mode="lines+markers", line=dict(color="#60a5fa", width=2),
                marker=dict(color=df_h["mcolor"].tolist(), size=8),
                hovertemplate="<b>%{x|%d %b}</b><br>IHSG: Rp%{y:,.0f}<extra></extra>",
            ))
            fig.update_layout(height=200, **LAYOUT)
            st.plotly_chart(fig, use_container_width=True)

    # ── SCANNER SUMMARY ──────────────────────────────────────────
    section("SCANNER SUMMARY", "🔍")
    last_run = load_last_scan_run()
    total_scanned = si(last_run.get("stocks_scanned")) if last_run else len(signals)

    sb = sum(1 for s in signals if s.get("signal_type")=="STRONG_BUY")
    bu = sum(1 for s in signals if s.get("signal_type")=="BUY")
    wl = sum(1 for s in signals if s.get("signal_type")=="WATCHLIST")
    av = sum(1 for s in signals if s.get("signal_type")=="AVOID")

    c1,c2,c3,c4,c5 = st.columns(5)
    with c1: st.markdown(tile("Total Discan", f"{total_scanned:,}"), unsafe_allow_html=True)
    with c2: st.markdown(tile("🚀 Strong Buy", sb), unsafe_allow_html=True)
    with c3: st.markdown(tile("🟢 Buy", bu), unsafe_allow_html=True)
    with c4: st.markdown(tile("👀 Watchlist", wl), unsafe_allow_html=True)
    with c5: st.markdown(tile("🔴 Rejected", av), unsafe_allow_html=True)

    # ── TOP SIGNALS ──────────────────────────────────────────────
    section("TOP SIGNALS", "🏆")
    top5 = [s for s in signals if s.get("signal_type") in ("STRONG_BUY","BUY")][:5]
    if not top5:
        st.markdown(
            '<div class="ds-card">'
            '<span style="color:#9aa4b8">Belum ada sinyal berkualitas hari ini. '
            'Menunggu peluang terbaik lebih baik daripada mengambil peluang yang kurang berkualitas.</span>'
            '</div>', unsafe_allow_html=True
        )
    else:
        rows_html = ""
        for s in top5:
            ticker = ss(s.get("ticker")).replace(".JK","")
            stype  = ss(s.get("signal_type"),"AVOID")
            score  = sf(s.get("raw_score"))
            close  = sf(s.get("close_price"))
            sector = ss(s.get("sector"),"—")
            conf   = s.get("confidence")
            rows_html += (
                f'<div class="ds-row">'
                f'<div class="ds-row-ticker">{ticker}</div>'
                f'<div>{signal_badge(stype)}</div>'
                f'<div style="flex:1"><div class="ds-row-sector">{sector}</div></div>'
                + (f'<div>{confidence_badge(conf)}</div>' if conf else '')
                + f'<div class="ds-num" style="font-weight:700;width:70px;text-align:right">{score:.0f}</div>'
                f'<div class="ds-num" style="width:100px;text-align:right;color:#9aa4b8">Rp{close:,.0f}</div>'
                f'</div>'
            )
        st.markdown(f'<div class="ds-card ds-card-flush">{rows_html}</div>', unsafe_allow_html=True)

    # ── FLOW RADAR (BARU, v2.5.0) ────────────────────────────────
    # Leaderboard saham dengan pola VSA Akumulasi + CMF positif terkuat
    # hari ini -- proxy bandarmology gratis (lihat AUDIT flow_score di
    # ta_engine.py, BELUM tervalidasi empiris, sajikan sebagai info
    # tambahan bukan sinyal beli berdiri sendiri).
    section("FLOW RADAR", "🌊")
    acc_signals = [s for s in signals if ss(s.get("vsa_signal")) == "ACCUMULATION"]
    acc_signals.sort(key=lambda s: sf(s.get("cmf")), reverse=True)
    top_flow = acc_signals[:6]

    if not top_flow:
        st.markdown(
            '<div class="ds-card">'
            '<span style="color:#9aa4b8">Belum ada pola akumulasi VSA yang terdeteksi hari ini.</span>'
            '</div>', unsafe_allow_html=True
        )
    else:
        max_cmf = max(sf(s.get("cmf")) for s in top_flow) or 1.0
        items_html = ""
        for i, s in enumerate(top_flow, 1):
            ticker = ss(s.get("ticker")).replace(".JK", "")
            cmf = sf(s.get("cmf"))
            struct = ss(s.get("trend_structure"), "")
            bar_pct = max(min(cmf / max_cmf * 100, 100), 4)
            items_html += (
                f'<div class="ds-radar-item">'
                f'<div class="ds-radar-rank">#{i}</div>'
                f'<div style="width:64px;font-weight:700">{ticker}</div>'
                f'<div class="ds-radar-bar-track"><div class="ds-radar-bar-fill" style="width:{bar_pct:.0f}%"></div></div>'
                f'<div class="ds-num" style="width:56px;text-align:right;color:#00c896;font-weight:600">{cmf:+.2f}</div>'
                f'<div style="width:120px;text-align:right">{structure_chip(struct)}</div>'
                f'</div>'
            )
        st.markdown(f'<div class="ds-card ds-card-flush">{items_html}</div>', unsafe_allow_html=True)
        st.markdown(
            '<div class="ds-caption" style="margin-top:6px">'
            'Diranking dari Chaikin Money Flow (CMF) tertinggi di antara saham berpola VSA Akumulasi hari ini. '
            'Proxy bandarmology gratis dari OHLCV, bukan data transaksi broker asli.</div>',
            unsafe_allow_html=True
        )

    # ── SYSTEM HEALTH (ringkas) ──────────────────────────────────
    section("SYSTEM HEALTH", "🩺")
    c1, c2, c3, c4 = st.columns(4)
    db_ok = load_regime() is not None
    uni_count = load_universe_count()
    with c1:
        dot = "ds-health-ok" if db_ok else "ds-health-bad"
        st.markdown(f'<div class="ds-health"><span class="ds-health-dot {dot}"></span>Database</div>', unsafe_allow_html=True)
    with c2:
        dot = "ds-health-ok" if uni_count > 100 else ("ds-health-warn" if uni_count > 0 else "ds-health-bad")
        st.markdown(f'<div class="ds-health"><span class="ds-health-dot {dot}"></span>Universe · {uni_count} saham</div>', unsafe_allow_html=True)
    with c3:
        ok = last_run and last_run.get("status") == "SUCCESS"
        dot = "ds-health-ok" if ok else "ds-health-warn"
        st.markdown(f'<div class="ds-health"><span class="ds-health-dot {dot}"></span>Scan Terakhir</div>', unsafe_allow_html=True)
    with c4:
        st.markdown('<div class="ds-health"><span class="ds-health-dot ds-health-ok"></span>Telegram</div>', unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════
#  PAGE — TOP SIGNALS
# ══════════════════════════════════════════════════════════════════

def page_top_signals():
    st.markdown('<div class="ds-page-title">Top Signals</div>', unsafe_allow_html=True)
    st.markdown('<div class="ds-page-sub">Sinyal hasil scan, diranking berdasarkan composite score.</div>', unsafe_allow_html=True)

    c1,c2,c3,c4 = st.columns([1.3,1.6,1.3,1.6])
    scan_date  = c1.date_input("Tanggal", value=date.today(), max_value=date.today())
    sig_filter = c2.multiselect("Tipe Sinyal", ["STRONG_BUY","BUY","WATCHLIST","AVOID"],
                                default=["STRONG_BUY","BUY"])
    min_score  = c3.slider("Skor Minimum (raw)", 0, 100, 45, help="Difilter dari raw_score -- skor yang benar-benar dipakai sistem buat klasifikasi sinyal")
    search_tk  = c4.text_input("Cari Ticker", placeholder="BBCA")

    signals = load_signals(scan_date.isoformat())
    if not signals:
        st.info(f"Tidak ada sinyal untuk {scan_date}."); return

    rows = []
    for s in signals:
        stype  = ss(s.get("signal_type"), "AVOID")
        score  = sf(s.get("raw_score"))
        ticker = ss(s.get("ticker")).replace(".JK","")
        if stype not in sig_filter: continue
        if score < min_score: continue
        if search_tk and search_tk.upper() not in ticker.upper(): continue
        entry = sf(s.get("entry_price")) or sf(s.get("close_price"))
        rows.append({
            "raw": s, "ticker": ticker, "stype": stype, "score": score,
            "sector": ss(s.get("sector"),"—"), "close": sf(s.get("close_price")),
            "vol": sf(s.get("volume_ratio"), 1.0), "rs": sf(s.get("rel_strength")),
            "entry": entry, "sl": sf(s.get("stop_loss")), "tp1": sf(s.get("target_1")),
            "rr": sf(s.get("risk_reward")), "conf": s.get("confidence"),
            "vsa": s.get("vsa_signal"),
        })

    if not rows:
        st.warning("Tidak ada sinyal yang memenuhi filter."); return

    st.markdown(f'<div class="ds-caption">{len(rows)} sinyal ditemukan · {scan_date}</div>', unsafe_allow_html=True)
    st.write("")

    hc = st.columns([0.35, 1.0, 1.4, 1.3, 1.15, 1.3, 0.8, 0.8, 1.0, 1.0, 1.0, 0.7, 0.6])
    header_labels = ["", "Ticker", "Sinyal", "Confidence", "Flow", "Sektor",
                      "Volume", "RS", "Entry", "SL", "TP1", "R/R", ""]
    for col, label in zip(hc, header_labels):
        if label:
            col.markdown(f'<span class="ds-tile-label">{label}</span>', unsafe_allow_html=True)
    st.markdown("<hr class='ds-hr' style='margin:2px 0 8px'>", unsafe_allow_html=True)

    for idx, row in enumerate(rows, 1):
        with st.container():
            c = st.columns([0.35, 1.0, 1.4, 1.3, 1.15, 1.3, 0.8, 0.8, 1.0, 1.0, 1.0, 0.7, 0.6])
            c[0].markdown(f'<span style="color:#5c6478;font-size:.8rem">#{idx}</span>', unsafe_allow_html=True)
            c[1].markdown(f'<span style="font-weight:700">{row["ticker"]}</span>', unsafe_allow_html=True)
            c[2].markdown(signal_badge(row["stype"]), unsafe_allow_html=True)
            if row["conf"]:
                c[3].markdown(confidence_badge(row["conf"]), unsafe_allow_html=True)
            else:
                c[3].markdown(f'<span class="ds-chip">score {row["score"]:.0f}</span>', unsafe_allow_html=True)
            c[4].markdown(vsa_badge(row["vsa"], compact=True) or '<span style="color:#5c6478">·</span>', unsafe_allow_html=True)
            c[5].markdown(f'<span class="ds-chip">{row["sector"][:14]}</span>', unsafe_allow_html=True)
            vc = "#4ade80" if row["vol"]>=1.5 else ("#fbbf24" if row["vol"]>=1 else "#f87171")
            c[6].markdown(f'<span class="ds-num" style="color:{vc}">{row["vol"]:.1f}x</span>', unsafe_allow_html=True)
            rc = "#4ade80" if row["rs"]>0 else "#f87171"
            c[7].markdown(f'<span class="ds-num" style="color:{rc}">{row["rs"]:+.1f}%</span>', unsafe_allow_html=True)
            c[8].markdown(f'<span class="ds-num">Rp{row["entry"]:,.0f}</span>', unsafe_allow_html=True)
            c[9].markdown(f'<span class="ds-num" style="color:#f87171">Rp{row["sl"]:,.0f}</span>', unsafe_allow_html=True)
            c[10].markdown(f'<span class="ds-num" style="color:#4ade80">Rp{row["tp1"]:,.0f}</span>', unsafe_allow_html=True)
            c[11].markdown(f'<span class="ds-num">1:{row["rr"]:.1f}</span>', unsafe_allow_html=True)
            if c[12].button("→", key=f"d_{row['ticker']}_{idx}", help="Lihat detail"):
                st.session_state["sel_ticker"] = row["ticker"]
                st.session_state["nav_override"] = "detail"
                st.rerun()
        st.markdown("<hr class='ds-hr' style='margin:4px 0'>", unsafe_allow_html=True)

    export = pd.DataFrame([{
        "Ticker": r["ticker"], "Signal": r["stype"], "Score": r["score"],
        "Sektor": r["sector"], "Harga": r["close"], "Entry": r["entry"],
        "SL": r["sl"], "TP1": r["tp1"], "R/R": r["rr"], "VSA": ss(r["vsa"], ""),
    } for r in rows])
    st.download_button("⬇ Download CSV", export.to_csv(index=False).encode(),
        file_name=f"daily_signal_{scan_date}.csv", mime="text/csv")


# ══════════════════════════════════════════════════════════════════
#  PAGE — SIGNAL DETAIL ("Why This Signal?")
# ══════════════════════════════════════════════════════════════════

def _build_reasons(sig: dict) -> list[str]:
    """
    Susun reason checklist. Prioritas: pakai factor_contribution.highlights
    dari migration 002 jika ada (sudah dihitung engine, lebih akurat) —
    fallback ke heuristik sederhana dari kolom lama jika belum tersedia
    (migration belum jalan), supaya halaman ini tetap berguna.
    """
    fc = sig.get("factor_contribution")
    if isinstance(fc, dict) and fc.get("highlights"):
        return [f"{h}" for h in fc["highlights"]]

    reasons = []
    trend_score = sf(sig.get("trend_score"))
    # Threshold dinamis (TREND_SCORE_CAP × 0.8) -- BUKAN hardcoded lagi.
    # AUDIT (2026-08): sempat basi 2x berturut (24/30 -> 16/20 -> lupa
    # diupdate lagi pas cap naik ke 22 gara-gara structure bonus).
    # Import konstanta langsung, bukan salin angka, biar tidak basi lagi.
    from src.signals.ta_engine import TREND_SCORE_CAP
    if trend_score >= TREND_SCORE_CAP * 0.8: reasons.append("EMA Bullish Alignment kuat")
    vr = sf(sig.get("volume_ratio"), 1.0)
    if vr >= 1.5: reasons.append(f"Volume Spike {vr:.1f}x rata-rata")
    rs = sf(sig.get("rel_strength"))
    if rs > 5: reasons.append("Relative Strength tinggi (outperform IHSG)")
    adx = sf(sig.get("adx"))
    if adx >= 25: reasons.append(f"ADX kuat ({adx:.0f})")
    macd_h = sf(sig.get("macd_hist"))
    if macd_h > 0: reasons.append("MACD momentum positif")
    if not reasons:
        reasons.append("Memenuhi ambang skor minimum sistem")
    return reasons


def page_signal_detail():
    st.markdown('<div class="ds-page-title">Signal Detail</div>', unsafe_allow_html=True)
    st.markdown('<div class="ds-page-sub">Kenapa saham ini terpilih — breakdown lengkap.</div>', unsafe_allow_html=True)

    signals = load_signals()
    actionable = [s for s in signals if s.get("signal_type") in ("STRONG_BUY","BUY","WATCHLIST")]
    if not actionable:
        st.info("Belum ada sinyal hari ini untuk dianalisis."); return

    tickers = [ss(s.get("ticker")).replace(".JK","") for s in actionable]
    def_idx = 0
    if "sel_ticker" in st.session_state and st.session_state["sel_ticker"] in tickers:
        def_idx = tickers.index(st.session_state["sel_ticker"])

    selected = st.selectbox("Pilih Ticker", tickers, index=def_idx)
    sig = next((s for s in actionable if ss(s.get("ticker")).replace(".JK","")==selected), None)
    if not sig:
        st.warning("Data tidak ditemukan."); return

    stype  = ss(sig.get("signal_type"),"AVOID")
    raw    = sf(sig.get("raw_score"))
    disp   = sig.get("composite_score")  # raw_score x regime_weight -- konteks tambahan
    close  = sf(sig.get("close_price"))
    sector = ss(sig.get("sector"),"—")
    conf   = sig.get("confidence")

    # ── Header hero ──────────────────────────────────────────────
    st.markdown(
        f'<div class="ds-hero">'
        f'<div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:16px">'
        f'<div>'
        f'<div style="font-family:Manrope,sans-serif;font-weight:800;font-size:1.8rem;color:#e8ebf2">{selected}</div>'
        f'<div style="margin-top:6px;display:flex;gap:8px;align-items:center">{signal_badge(stype)}'
        + (confidence_badge(conf) if conf else '') +
        f'<span class="ds-chip">{sector}</span></div>'
        f'</div>'
        f'<div class="ds-num" style="text-align:right">'
        f'<div style="font-size:.75rem;color:#9aa4b8;text-transform:uppercase">Harga</div>'
        f'<div style="font-weight:700;font-size:1.5rem;color:#e8ebf2">Rp{close:,.0f}</div>'
        # AUDIT: raw_score dipajang sebagai angka utama -- itu yang benar2
        # dipakai buat klasifikasi signal_type (lihat _determine_signal_type).
        # composite_score cuma konteks (sudah dikali regime_weight).
        f'<div style="font-size:.8rem;color:#9aa4b8">Score {raw:.0f}/100'
        + (f' · display {sf(disp):.0f}' if disp is not None else '') + '</div>'
        f'</div></div></div>',
        unsafe_allow_html=True
    )

    # ── Score Breakdown ──────────────────────────────────────────
    section("SCORE BREAKDOWN", "📊")
    # AUDIT (2026-08): ini tempat KE-4 yang ketemu masih hardcode cap lama
    # (Trend 20 harusnya 22, Volatility 4 harusnya 2) dalam audit menyeluruh
    # yang sama -- pola berulang. Import konstanta langsung, bukan salin
    # angka lagi, supaya tidak basi lagi kalau cap berubah ke depannya.
    from src.signals.ta_engine import (
        TREND_SCORE_CAP, MOMENTUM_SCORE_CAP, VOLUME_SCORE_CAP,
        STRENGTH_SCORE_CAP, VOLATILITY_SCORE_CAP, FLOW_SCORE_CAP,
    )
    comps = [
        ("Trend",      sf(sig.get("trend_score")),      TREND_SCORE_CAP),
        ("Momentum",   sf(sig.get("momentum_score")),   MOMENTUM_SCORE_CAP),
        ("Volume",     sf(sig.get("volume_score")),     VOLUME_SCORE_CAP),
        ("Strength",   sf(sig.get("strength_score")),   STRENGTH_SCORE_CAP),
        ("Volatility", sf(sig.get("volatility_score")), VOLATILITY_SCORE_CAP),
        ("Flow",       sf(sig.get("flow_score")),       FLOW_SCORE_CAP),
    ]
    sector_bonus = sig.get("sector_bonus")

    gauges_html = "".join(gauge_row(name, val, mx) for name, val, mx in comps)
    if sector_bonus is not None:
        sb = sf(sector_bonus)
        sb_color = "#4ade80" if sb > 0 else ("#f87171" if sb < 0 else "#5c6478")
        gauges_html += (
            f'<div class="ds-gauge-row">'
            f'<div class="ds-gauge-label">Sector Bonus</div>'
            f'<div class="ds-gauge-track"></div>'
            f'<div class="ds-gauge-val" style="color:{sb_color}">{sb:+.0f}</div>'
            f'</div>'
        )
    st.markdown(f'<div class="ds-card">{gauges_html}</div>', unsafe_allow_html=True)

    # ── Mengapa saham ini dipilih ────────────────────────────────
    section("MENGAPA SAHAM INI DIPILIH?", "✓")
    reasons = _build_reasons(sig)
    reasons_html = "".join(
        f'<div class="ds-reason"><span class="ds-reason-check">✓</span>{r}</div>' for r in reasons
    )
    st.markdown(f'<div class="ds-card">{reasons_html}</div>', unsafe_allow_html=True)

    # ── Indikator Detail ─────────────────────────────────────────
    section("INDIKATOR TEKNIKAL", "📈")
    ema20  = sf(sig.get("ema20")); ema50  = sf(sig.get("ema50")); ema200 = sf(sig.get("ema200"))
    rsi    = sf(sig.get("rsi"), 50); macd_h = sf(sig.get("macd_hist"))
    adx    = sf(sig.get("adx")); vr = sf(sig.get("volume_ratio"), 1.0); rs = sf(sig.get("rel_strength"))
    atr    = sf(sig.get("atr")); atr_pct = atr/close*100 if close>0 else 0

    c1,c2,c3,c4 = st.columns(4)
    with c1:
        st.markdown(tile("EMA 20", fmt_rp(ema20)), unsafe_allow_html=True)
        st.write("")
        st.markdown(tile("EMA 50", fmt_rp(ema50)), unsafe_allow_html=True)
    with c2:
        st.markdown(tile("RSI (14)", f"{rsi:.1f}"), unsafe_allow_html=True)
        st.write("")
        st.markdown(tile("MACD Hist", f"{macd_h:+.4f}"), unsafe_allow_html=True)
    with c3:
        st.markdown(tile("ADX (14)", f"{adx:.1f}"), unsafe_allow_html=True)
        st.write("")
        st.markdown(tile("Volume Ratio", f"{vr:.2f}x"), unsafe_allow_html=True)
    with c4:
        st.markdown(tile("RS vs IHSG", f"{rs:+.1f}%"), unsafe_allow_html=True)
        st.write("")
        st.markdown(tile("ATR%", f"{atr_pct:.2f}%"), unsafe_allow_html=True)

    # ── Risk Management ──────────────────────────────────────────
    section("RISK MANAGEMENT", "⚖️")
    entry = sf(sig.get("entry_price")) or close
    sl    = sf(sig.get("stop_loss")); tp1 = sf(sig.get("target_1")); tp2 = sf(sig.get("target_2"))
    rr    = sf(sig.get("risk_reward"))
    pos_risk = sig.get("position_risk")
    sl_pct  = (sl/entry-1)*100  if entry>0 else 0
    tp1_pct = (tp1/entry-1)*100 if entry>0 else 0
    tp2_pct = (tp2/entry-1)*100 if entry>0 else 0

    c1,c2,c3,c4,c5 = st.columns(5)
    with c1: st.markdown(tile("Entry", fmt_rp(entry)), unsafe_allow_html=True)
    with c2: st.markdown(tile("Stop Loss", fmt_rp(sl), f"{sl_pct:.1f}%", "down"), unsafe_allow_html=True)
    with c3: st.markdown(tile("Target 1", fmt_rp(tp1), f"+{tp1_pct:.1f}%", "up"), unsafe_allow_html=True)
    with c4: st.markdown(tile("Target 2", fmt_rp(tp2), f"+{tp2_pct:.1f}%", "up"), unsafe_allow_html=True)
    with c5:
        ps = f"{sf(pos_risk):.1f}%" if pos_risk is not None else f"1:{rr:.1f}"
        st.markdown(tile("Risk/Reward", f"1:{rr:.1f}"), unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════
#  PAGE — HISTORICAL SIGNALS
# ══════════════════════════════════════════════════════════════════

def page_historical_signals():
    st.markdown('<div class="ds-page-title">Historical Signals</div>', unsafe_allow_html=True)
    st.markdown('<div class="ds-page-sub">Evaluasi kualitas sinyal dari waktu ke waktu.</div>', unsafe_allow_html=True)

    c1,c2,c3,c4 = st.columns(4)
    days_back = c1.selectbox("Periode", [7,14,30,60,90], index=2)
    tf        = c2.multiselect("Tipe", ["STRONG_BUY","BUY","WATCHLIST"],
                               default=["STRONG_BUY","BUY"])
    search    = c3.text_input("Cari Ticker", placeholder="BBCA")
    min_s     = c4.slider("Skor Minimum (raw)", 0, 100, 45, key="hs", help="Difilter dari raw_score -- skor yang benar-benar dipakai sistem buat klasifikasi sinyal")

    signals = load_signals_range(days_back)
    if not signals:
        st.info(f"Tidak ada sinyal dalam {days_back} hari terakhir."); return

    filtered = [s for s in signals
                if ss(s.get("signal_type")) in tf
                and sf(s.get("raw_score")) >= min_s
                and (not search or search.upper() in ss(s.get("ticker")).upper())]

    st.markdown(f'<div class="ds-caption">{len(filtered)} dari {len(signals)} sinyal · {days_back} hari terakhir</div>', unsafe_allow_html=True)
    if not filtered:
        st.warning("Tidak ada sinyal yang memenuhi filter."); return

    rows = []
    for s in filtered:
        rows.append({
            "Tanggal": ss(s.get("signal_date")),
            "Ticker":  ss(s.get("ticker")).replace(".JK",""),
            "Type":    ss(s.get("signal_type"),"AVOID").replace("_"," "),
            "Score":   sf(s.get("raw_score")),
            "Sektor":  ss(s.get("sector"),"—")[:18],
            "Close":   sf(s.get("close_price")),
            "Entry":   sf(s.get("entry_price")) or sf(s.get("close_price")),
            "SL":      sf(s.get("stop_loss")),
            "TP1":     sf(s.get("target_1")),
            "R/R":     sf(s.get("risk_reward")),
            "RSI":     sf(s.get("rsi")),
            "Vol x":   sf(s.get("volume_ratio"), 1.0),
        })

    df = pd.DataFrame(rows)

    def cs(v):
        if isinstance(v, str):
            return {"STRONG BUY":"color:#00c896;font-weight:700","BUY":"color:#4ade80;font-weight:700",
                    "WATCHLIST":"color:#fbbf24"}.get(v,"")
        if isinstance(v, float):
            if v>=75: return "background-color:rgba(0,200,150,.1);color:#00c896"
            if v>=60: return "background-color:rgba(74,222,128,.1);color:#4ade80"
            if v>=45: return "background-color:rgba(251,191,36,.1);color:#fbbf24"
            return "background-color:rgba(248,113,113,.1);color:#f87171"
        return ""

    styled = _styler_apply(df.style, cs, subset=["Type","Score"])
    styled = styled.format({"Score":"{:.1f}","Close":"Rp{:,.0f}","Entry":"Rp{:,.0f}",
                       "SL":"Rp{:,.0f}","TP1":"Rp{:,.0f}",
                       "R/R":"1:{:.1f}","RSI":"{:.1f}","Vol x":"{:.1f}x"})
    st.dataframe(styled, use_container_width=True, hide_index=True, height=440)

    c1,c2 = st.columns(2)
    with c1:
        tc = df["Type"].value_counts()
        fig = go.Figure(go.Pie(labels=tc.index.tolist(), values=tc.values.tolist(),
                               marker_colors=["#00c896","#4ade80","#fbbf24","#f87171"],
                               hole=0.55))
        fig.update_layout(title="Distribusi Tipe Sinyal", height=260, **LAYOUT)
        st.plotly_chart(fig, use_container_width=True)
    with c2:
        sc = df["Sektor"].value_counts().head(8)
        fig = px.bar(x=sc.values, y=sc.index, orientation="h", title="Sinyal per Sektor",
                     color=sc.values, color_continuous_scale=["#171d2c","#00c896"])
        fig.update_layout(height=260, showlegend=False, coloraxis_showscale=False, **LAYOUT)
        st.plotly_chart(fig, use_container_width=True)

    st.download_button("⬇ Download CSV", df.to_csv(index=False).encode(),
                       file_name=f"hist_signals_{days_back}d.csv", mime="text/csv")


# ══════════════════════════════════════════════════════════════════
#  PAGE — SIGNAL PERFORMANCE
# ══════════════════════════════════════════════════════════════════

def page_signal_performance():
    """
    Signal Performance — 100% berbasis `signal_results` (Automatic
    Signal Evaluation Engine), BUKAN lagi Portfolio manual. Merepresentasikan
    performa SELURUH sinyal yang dikirim sistem (STRONG_BUY/BUY/WATCHLIST),
    bukan performa trading pribadi Anda.
    """
    st.markdown('<div class="ds-page-title">Signal Performance</div>', unsafe_allow_html=True)
    st.markdown('<div class="ds-page-sub">Performa seluruh sinyal sistem — evaluasi otomatis, bukan trading manual.</div>', unsafe_allow_html=True)

    c1, c2 = st.columns([1.3, 3])
    days_back = c1.selectbox("Periode", [30, 60, 90, 180, 365], index=2, key="perf_days")

    rows = load_signal_results(days=days_back)
    bt   = load_backtests()

    if not rows:
        st.info(
            "Belum ada data signal_results. Data akan terisi otomatis setiap kali "
            "daily scan berjalan (lihat src/signals/signal_evaluator.py) — pastikan "
            "migration 003_signal_evaluation.sql sudah dijalankan di Supabase."
        )
        return

    df = pd.DataFrame(rows)
    for col in ["net_return_pct", "gross_return_pct", "holding_days"]:
        if col in df.columns:
            df[col] = df[col].apply(sf)

    total_signals   = len(df)
    open_df         = df[df["status"] == "OPEN"]
    closed_df       = df[df["status"].isin(["CLOSED", "EXPIRED"])]
    expired_df      = df[df["status"] == "EXPIRED"]

    section("RINGKASAN", "📊")
    c1, c2, c3, c4, c5 = st.columns(5)
    with c1: st.markdown(tile("Total Sinyal", total_signals), unsafe_allow_html=True)
    with c2: st.markdown(tile("Open", len(open_df)), unsafe_allow_html=True)
    with c3: st.markdown(tile("Closed", len(df[df["status"]=="CLOSED"])), unsafe_allow_html=True)
    with c4: st.markdown(tile("Expired", len(expired_df)), unsafe_allow_html=True)
    with c5:
        pct_resolved = len(closed_df)/total_signals*100 if total_signals>0 else 0
        st.markdown(tile("% Terselesaikan", f"{pct_resolved:.0f}%"), unsafe_allow_html=True)

    section("KPI UTAMA", "📈")
    if len(closed_df) > 0:
        wins   = closed_df[closed_df["net_return_pct"] > 0]
        losses = closed_df[closed_df["net_return_pct"] <= 0]
        win_rate = len(wins) / len(closed_df)
        avg_return = closed_df["net_return_pct"].mean()
        avg_win  = wins["net_return_pct"].mean() if len(wins) > 0 else 0
        avg_loss = losses["net_return_pct"].mean() if len(losses) > 0 else 0
        avg_holding = closed_df["holding_days"].mean()

        gross_win  = wins["net_return_pct"].sum() if len(wins) > 0 else 0
        gross_loss = abs(losses["net_return_pct"].sum()) if len(losses) > 0 else 0
        profit_factor = gross_win / gross_loss if gross_loss > 0 else float("inf")

        loss_rate = 1 - win_rate
        expectancy = (win_rate * avg_win) + (loss_rate * avg_loss)

        c1,c2,c3,c4,c5,c6 = st.columns(6)
        with c1: st.markdown(tile("Winning Signals", len(wins)), unsafe_allow_html=True)
        with c2: st.markdown(tile("Losing Signals", len(losses)), unsafe_allow_html=True)
        with c3:
            wr_ok = win_rate >= 0.5
            st.markdown(tile("Win Rate", f"{win_rate:.1%}", "OK ✓" if wr_ok else "< 50%", "up" if wr_ok else "down"), unsafe_allow_html=True)
        with c4:
            pf_display = f"{profit_factor:.2f}" if profit_factor != float("inf") else "∞"
            st.markdown(tile("Profit Factor", pf_display, "OK ✓" if profit_factor>1 else "< 1.0", "up" if profit_factor>1 else "down"), unsafe_allow_html=True)
        with c5: st.markdown(tile("Avg Return", f"{avg_return:+.2f}%", None, "up" if avg_return>=0 else "down"), unsafe_allow_html=True)
        with c6: st.markdown(tile("Avg Holding", f"{avg_holding:.1f} hari"), unsafe_allow_html=True)

        st.markdown(tile("Expectancy (per sinyal)", f"{expectancy:+.2f}%", None, "up" if expectancy>=0 else "down"), unsafe_allow_html=True)
    else:
        st.info("Belum ada sinyal yang CLOSED/EXPIRED dalam periode ini — statistik akan muncul begitu evaluator menutup sinyal pertama.")

    # ── Equity Curve (dari net_return_pct sinyal yang closed, urut exit_date) ─
    if len(closed_df) > 0 and "exit_date" in closed_df.columns:
        section("EQUITY CURVE", "💹")
        eq = closed_df.dropna(subset=["exit_date"]).sort_values("exit_date").copy()
        if not eq.empty:
            eq["exit_date"] = pd.to_datetime(eq["exit_date"])
            eq["cum_return"] = (1 + eq["net_return_pct"]/100).cumprod()
            fig = go.Figure(go.Scatter(
                x=eq["exit_date"], y=eq["cum_return"],
                mode="lines", line=dict(color="#00c896", width=2),
                fill="tozeroy", fillcolor="rgba(0,200,150,.08)",
                hovertemplate="<b>%{x|%d %b}</b><br>Cum. Return: %{y:.2f}x<extra></extra>"))
            fig.update_layout(height=260, paper_bgcolor=DARK_BG, plot_bgcolor=PLOT_BG,
                              font=LAYOUT["font"], margin=LAYOUT["margin"], xaxis=LAYOUT["xaxis"],
                              yaxis=dict(gridcolor=GRID, title="Cumulative (x)"))
            st.plotly_chart(fig, use_container_width=True)

    # ── Distribusi & Outcome ─────────────────────────────────────────
    if len(closed_df) > 0:
        section("DISTRIBUSI HASIL", "🔬")
        c1, c2, c3 = st.columns(3)
        with c1:
            outcome_counts = df["exit_reason"].value_counts(dropna=True)
            colors_map = {"TP1":"#4ade80","TP2":"#00c896","SL":"#f87171","EXPIRED":"#9aa4b8"}
            fig = go.Figure(go.Pie(
                labels=outcome_counts.index.tolist(), values=outcome_counts.values.tolist(),
                marker_colors=[colors_map.get(x,"#60a5fa") for x in outcome_counts.index],
                hole=0.6, textinfo="label+percent"))
            fig.update_layout(title="Outcome Distribution", height=250, **LAYOUT, showlegend=False)
            st.plotly_chart(fig, use_container_width=True)
        with c2:
            fig = px.histogram(closed_df, x="net_return_pct", nbins=20,
                               title="Distribusi Return (%)",
                               color_discrete_sequence=["#60a5fa"])
            fig.update_layout(height=250, **LAYOUT)
            st.plotly_chart(fig, use_container_width=True)
        with c3:
            eqm = closed_df.dropna(subset=["exit_date"]).copy()
            if not eqm.empty:
                eqm["month"] = pd.to_datetime(eqm["exit_date"]).dt.strftime("%Y-%m")
                mo = eqm.groupby("month")["net_return_pct"].sum().reset_index()
                mo["color"] = mo["net_return_pct"].apply(lambda x: "#00c896" if x>=0 else "#f87171")
                fig = go.Figure(go.Bar(x=mo["month"], y=mo["net_return_pct"], marker_color=mo["color"],
                                       text=mo["net_return_pct"].apply(lambda x: f"{x:+.1f}%"), textposition="outside"))
                fig.update_layout(title="Monthly Performance (%)", height=250, **LAYOUT)
                st.plotly_chart(fig, use_container_width=True)

    # ── Detail Per Saham (BARU) ───────────────────────────────────
    section("DETAIL PER SAHAM", "🏷️")
    if len(closed_df) == 0:
        st.info("Belum ada sinyal CLOSED/EXPIRED untuk periode ini.")
    else:
        min_trades = st.slider(
            "Minimal jumlah sinyal per saham (biar tidak kepancing n=1)",
            1, max(1, int(closed_df.groupby("ticker").size().max())), 1, key="perf_min_trades"
        )
        per_ticker = (
            closed_df.groupby("ticker")
            .agg(
                n=("net_return_pct", "count"),
                win_rate=("net_return_pct", lambda x: (x > 0).mean()),
                avg_return=("net_return_pct", "mean"),
                total_return=("net_return_pct", "sum"),
                best=("net_return_pct", "max"),
                worst=("net_return_pct", "min"),
                avg_holding=("holding_days", "mean"),
            )
            .reset_index()
        )
        # sektor (ambil modus per ticker, kalau kolomnya ada)
        if "sector" in closed_df.columns:
            sector_map = closed_df.groupby("ticker")["sector"].agg(
                lambda s: s.mode().iat[0] if not s.mode().empty else "—"
            )
            per_ticker["sector"] = per_ticker["ticker"].map(sector_map)

        per_ticker = per_ticker[per_ticker["n"] >= min_trades].sort_values("total_return", ascending=False)

        c1, c2, c3 = st.columns(3)
        with c1: st.markdown(tile("Saham Unik (lolos filter)", len(per_ticker)), unsafe_allow_html=True)
        with c2:
            best_ticker = per_ticker.iloc[0]["ticker"] if len(per_ticker) else "—"
            st.markdown(tile("Kontributor Terbaik", best_ticker), unsafe_allow_html=True)
        with c3:
            worst_row = per_ticker.sort_values("total_return").iloc[0] if len(per_ticker) else None
            st.markdown(tile("Kontributor Terburuk", worst_row["ticker"] if worst_row is not None else "—"), unsafe_allow_html=True)

        show = per_ticker.copy()
        show["win_rate"]    = show["win_rate"].apply(lambda x: f"{x:.0%}")
        show["avg_return"]  = show["avg_return"].apply(lambda x: f"{x:+.2f}%")
        show["total_return"] = show["total_return"].apply(lambda x: f"{x:+.2f}%")
        show["best"]        = show["best"].apply(lambda x: f"{x:+.2f}%")
        show["worst"]       = show["worst"].apply(lambda x: f"{x:+.2f}%")
        show["avg_holding"] = show["avg_holding"].apply(lambda x: f"{x:.1f}d")
        cols_order = ["ticker"] + (["sector"] if "sector" in show.columns else []) + \
                     ["n", "win_rate", "avg_return", "total_return", "best", "worst", "avg_holding"]
        st.dataframe(
            show[cols_order].rename(columns={
                "ticker": "Ticker", "sector": "Sektor", "n": "Jml Sinyal",
                "win_rate": "Win Rate", "avg_return": "Avg Return",
                "total_return": "Total Return", "best": "Terbaik", "worst": "Terburuk",
                "avg_holding": "Avg Holding",
            }),
            use_container_width=True, hide_index=True, height=420
        )
        st.caption(
            "Klik header kolom untuk sort. 'Total Return' = jumlah net_return_pct semua sinyal "
            "saham itu (non-compounding) -- proxy kontribusi, bukan hasil investasi riil per saham."
        )

    # ── Snapshot Sinyal Individual (BARU) ──────────────────────────
    section("SNAPSHOT SINYAL", "🔎")
    if len(closed_df) == 0:
        st.info("Belum ada sinyal CLOSED/EXPIRED untuk periode ini.")
    else:
        opts_df = closed_df.sort_values("signal_date", ascending=False)
        opt_labels = [
            f"{r.ticker} · {r.signal_date} · {r.signal_type} · {sf(r.net_return_pct):+.1f}%"
            for r in opts_df.itertuples()
        ]
        picked = st.selectbox("Pilih 1 sinyal buat lihat snapshot lengkapnya", opt_labels, key="snap_pick")
        row = opts_df.iloc[opt_labels.index(picked)]
        row = row.astype(object).where(pd.notna(row), None)  # NaN -> None (biar sf()/ss() konsisten)

        def g(col):
            return row[col] if col in row.index else None

        # -- Identitas & hasil --
        c1, c2, c3, c4 = st.columns(4)
        with c1: st.markdown(tile("Ticker", ss(g("ticker")).replace(".JK", "")), unsafe_allow_html=True)
        with c2: st.markdown(tile("Signal Type", ss(g("signal_type"))), unsafe_allow_html=True)
        with c3: st.markdown(tile("Net Return", f"{sf(g('net_return_pct')):+.2f}%"), unsafe_allow_html=True)
        with c4: st.markdown(tile("Exit Reason", ss(g("exit_reason"), "-")), unsafe_allow_html=True)

        st.markdown(
            f"**{ss(g('ticker'))}** — {ss(g('sector'), '—')} · Regime {ss(g('market_regime'), '—')} · "
            f"Timeframe {ss(g('timeframe'), '1D')} · Sinyal {ss(g('signal_date'))} → Exit {ss(g('exit_date'), '-')} "
            f"({sf(g('holding_days')):.0f} hari)"
        )

        tab_a, tab_b, tab_c, tab_d, tab_e = st.tabs(
            ["📐 Indikator", "🧭 Kondisi & Struktur", "🧩 Pattern", "🎯 Score Breakdown", "✔ Alasan & Trading Plan"]
        )

        with tab_a:
            ic1, ic2, ic3, ic4 = st.columns(4)
            with ic1:
                st.markdown("**Momentum**")
                st.write(f"RSI: {sf(g('rsi')):.1f} (prev {sf(g('rsi_prev')):.1f}, slope {sf(g('rsi_slope')):+.2f})")
                st.write(f"MACD: {sf(g('macd_line')):.2f}")
                st.write(f"MACD Signal: {sf(g('macd_signal')):.2f}")
                st.write(f"MACD Hist: {sf(g('macd_hist')):+.2f}")
            with ic2:
                st.markdown("**Trend (EMA/SMA)**")
                st.write(f"EMA20/50/200: {sf(g('ema20')):,.0f} / {sf(g('ema50')):,.0f} / {sf(g('ema200')):,.0f}")
                st.write(f"SMA20/50/200: {sf(g('sma20')):,.0f} / {sf(g('sma50')):,.0f} / {sf(g('sma200')):,.0f}")
                st.write(f"Dist EMA20/50/200: {sf(g('distance_ema20_pct')):+.1f}% / "
                         f"{sf(g('distance_ema50_pct')):+.1f}% / {sf(g('distance_ema200_pct')):+.1f}%")
            with ic3:
                st.markdown("**Strength**")
                st.write(f"ADX: {sf(g('adx')):.1f}")
                st.write(f"DI+: {sf(g('plus_di')):.1f}")
                st.write(f"DI-: {sf(g('minus_di')):.1f}")
                st.write(f"ATR: {sf(g('atr')):.1f}")
            with ic4:
                st.markdown("**Volume & Volatility**")
                st.write(f"Volume: {sf(g('volume')):,.0f}")
                st.write(f"Avg Vol 20D: {sf(g('avg_volume_20')):,.0f}")
                st.write(f"Relative Volume: {sf(g('relative_volume')):.2f}x")
                st.write(f"Bollinger Position: {sf(g('bollinger_position')):.2f}")

        with tab_b:
            cc1, cc2, cc3 = st.columns(3)
            with cc1: st.markdown(tile("Trend", ss(g("trend_condition"), "—")), unsafe_allow_html=True)
            with cc2: st.markdown(tile("Momentum", ss(g("momentum_condition"), "—")), unsafe_allow_html=True)
            with cc3: st.markdown(tile("Volume", ss(g("volume_condition"), "—")), unsafe_allow_html=True)
            st.markdown("")
            st.markdown(tile("Struktur Trend", ss(g("trend_structure"), "Tidak terdeteksi")), unsafe_allow_html=True)
            st.caption(
                "Struktur trend HEURISTIK dari swing pivot (lihat src/signals/pattern_engine.py) -- "
                "belum divalidasi empiris, belum dipakai scoring."
            )

        with tab_c:
            pats = g("pattern_detected")
            if isinstance(pats, str):
                import json as _json
                try:
                    pats = _json.loads(pats)
                except Exception:
                    pats = [pats]
            elif not isinstance(pats, list):
                pats = []  # None / NaN / tipe lain -> anggap kosong, jangan crash
            if pats:
                for p in pats:
                    st.markdown(f"🧩 {p}")
            else:
                st.info("Tidak ada pattern candlestick/breakout/S-R/divergence yang terdeteksi di sinyal ini.")
            st.caption("Deteksi HEURISTIK, bukan machine learning -- lihat docstring pattern_engine.py.")

        with tab_d:
            # AUDIT (2026-08): tempat KE-5 dengan cap hardcoded yang ketemu
            # basi dalam audit menyeluruh yang sama -- pola berulang cukup
            # sering sampai perlu ditutup permanen di SEMUA lokasi sekaligus.
            # Import konstanta, jangan hardcode angka cap lagi di manapun.
            from src.signals.ta_engine import (
                TREND_SCORE_CAP, MOMENTUM_SCORE_CAP, VOLUME_SCORE_CAP,
                STRENGTH_SCORE_CAP, VOLATILITY_SCORE_CAP, FLOW_SCORE_CAP,
            )
            sc1, sc2, sc3, sc4, sc5, sc6b = st.columns(6)
            with sc1: st.markdown(tile("Trend Score", f"{sf(g('trend_score')):.1f}/{TREND_SCORE_CAP:.0f}"), unsafe_allow_html=True)
            with sc2: st.markdown(tile("Momentum Score", f"{sf(g('momentum_score')):.1f}/{MOMENTUM_SCORE_CAP:.0f}"), unsafe_allow_html=True)
            with sc3: st.markdown(tile("Volume Score", f"{sf(g('volume_score')):.1f}/{VOLUME_SCORE_CAP:.0f}"), unsafe_allow_html=True)
            with sc4: st.markdown(tile("Strength Score", f"{sf(g('strength_score')):.1f}/{STRENGTH_SCORE_CAP:.0f}"), unsafe_allow_html=True)
            with sc5: st.markdown(tile("Volatility Score", f"{sf(g('volatility_score')):.1f}/{VOLATILITY_SCORE_CAP:.0f}"), unsafe_allow_html=True)
            with sc6b: st.markdown(tile("Flow Score", f"{sf(g('flow_score')):.1f}/{FLOW_SCORE_CAP:.0f}"), unsafe_allow_html=True)
            st.caption("Flow Score: proxy bandarmology gratis (OBV/CMF/MFI/VSA) — BARU, belum tervalidasi empiris.")
            st.markdown("")
            sc6, sc7, sc8, sc9, sc10 = st.columns(5)
            with sc6: st.markdown(tile("Sector Bonus", f"{sf(g('sector_bonus')):+.1f}"), unsafe_allow_html=True)
            with sc7: st.markdown(tile("Regime Weight", f"{sf(g('regime_weight')):.2f}x"), unsafe_allow_html=True)
            with sc8: st.markdown(tile("Raw Score", f"{sf(g('raw_score')):.0f}/100"), unsafe_allow_html=True)
            with sc9: st.markdown(tile("Final Score", f"{sf(g('final_score')):.0f}/100"), unsafe_allow_html=True)
            with sc10: st.markdown(tile("Confidence", ss(g("confidence"), "—")), unsafe_allow_html=True)
            st.caption(
                "Raw Score = yang benar-benar dipakai klasifikasi signal_type. Final Score = "
                "raw x regime_weight, nilai tampilan saja -- lihat CHANGELOG v2.2.0."
            )

            # ── Flow & Structure narrative (BARU, v2.5.0) ────────
            cmf_val = g("cmf")
            if cmf_val is not None:
                st.markdown("")
                section("MONEY FLOW & STRUKTUR", "🌊")
                vsa_sig = ss(g("vsa_signal"), "")
                structure = ss(g("trend_structure"), "")
                mfi_val = sf(g("mfi"), 50)
                obv_slope = sf(g("obv_slope_pct"))

                fc1, fc2, fc3, fc4 = st.columns(4)
                with fc1: st.markdown(tile("CMF (Chaikin Money Flow)", f"{sf(cmf_val):+.3f}"), unsafe_allow_html=True)
                with fc2: st.markdown(tile("MFI (Money Flow Index)", f"{mfi_val:.0f}"), unsafe_allow_html=True)
                with fc3: st.markdown(tile("OBV Slope (10D)", f"{obv_slope:+.1f}%"), unsafe_allow_html=True)
                with fc4:
                    st.markdown('<div class="ds-tile"><div class="ds-tile-label">VSA Signal</div>'
                                f'<div style="margin-top:4px">{vsa_badge(vsa_sig)}</div></div>', unsafe_allow_html=True)

                # Interpretasi bahasa natural -- BUKAN rekomendasi beli/jual,
                # murni deskripsi apa yang indikator tunjukkan.
                interp_parts = []
                if vsa_sig == "ACCUMULATION":
                    interp_parts.append("volume besar terserap tanpa melebarkan range harga (indikasi akumulasi)")
                elif vsa_sig == "DISTRIBUTION":
                    interp_parts.append("volume besar terserap dengan close melemah (indikasi distribusi)")
                elif vsa_sig == "NO_DEMAND":
                    interp_parts.append("kenaikan harga TIDAK didukung volume (rally lemah)")
                elif vsa_sig in ("CLIMAX_UP", "CLIMAX_DOWN"):
                    interp_parts.append("volume & range ekstrem (potensi exhaustion, waspada pembalikan)")
                if obv_slope > 5:
                    interp_parts.append(f"OBV naik {obv_slope:.1f}% dalam 10 hari terakhir")
                elif obv_slope < -5:
                    interp_parts.append(f"OBV turun {abs(obv_slope):.1f}% dalam 10 hari terakhir")
                if structure:
                    interp_parts.append(f'struktur trend saat ini: "{structure}"')

                if interp_parts:
                    st.markdown(
                        f'<div class="ds-card" style="border-left:3px solid var(--accent)">'
                        f'<span style="color:#9aa4b8;font-size:.85rem">'
                        f'{"; ".join(interp_parts).capitalize()}.</span></div>',
                        unsafe_allow_html=True
                    )
                st.caption(
                    "Flow & struktur adalah proxy bandarmology gratis dari OHLCV (bukan data broker asli) "
                    "dan trend_structure — keduanya BARU, belum ada validasi empiris jangka panjang."
                )

        with tab_e:
            reasons = g("reasons")
            if isinstance(reasons, str):
                import json as _json
                try:
                    reasons = _json.loads(reasons)
                except Exception:
                    reasons = [reasons]
            elif not isinstance(reasons, list):
                reasons = []  # None / NaN / tipe lain -> anggap kosong, jangan crash
            st.markdown("**Alasan sinyal muncul:**")
            if reasons:
                for r in reasons:
                    st.markdown(f"✔ {r}")
            else:
                st.caption("Tidak ada catatan alasan untuk sinyal ini.")
            st.markdown("")
            st.markdown("**Trading Plan saat sinyal dibuat:**")
            tp1, tp2, tp3, tp4 = st.columns(4)
            with tp1: st.markdown(tile("Entry", f"{sf(g('entry_price')):,.0f}"), unsafe_allow_html=True)
            with tp2: st.markdown(tile("Stop Loss", f"{sf(g('stop_loss')):,.0f}"), unsafe_allow_html=True)
            with tp3: st.markdown(tile("Target 1", f"{sf(g('target_1')):,.0f}"), unsafe_allow_html=True)
            with tp4: st.markdown(tile("Target 2", f"{sf(g('target_2')):,.0f}"), unsafe_allow_html=True)
            st.caption(f"Risk/Reward: {sf(g('risk_reward')):.2f} · Exit @ {sf(g('exit_price')):,.0f} ({ss(g('exit_reason'),'-')})")

    # ── Score Calibration (BARU) ──────────────────────────────────
    section("SCORE CALIBRATION", "🎯")
    st.caption(
        "Apakah skor yang dihasilkan sistem benar-benar memprediksi hasil? Breakdown win rate & "
        "avg return per bucket -- dipakai buat validasi bobot scoring, bukan cuma lihat agregat."
    )
    if len(closed_df) < 10:
        st.info("Butuh minimal ~10 sinyal CLOSED untuk kalibrasi yang bermakna.")
    else:
        # CATATAN (2026-08): bucket trend_score/volatility_score di bawah
        # mengikuti cap TERBARU (22 & 2, lihat AUDIT CompositeScore di
        # ta_engine.py) -- kalau cap berubah lagi nanti, bucket di sini
        # JUGA WAJIB disesuaikan manual (beda modul/bahasa dari Python,
        # belum ada cara auto-sync ke TREND_SCORE_CAP dkk). flow_score
        # BARU, belum ada histori signal_results lama untuk divalidasi --
        # baru mulai terisi dari sinyal setelah deploy perubahan ini.
        calib_specs = [
            ("raw_score",        [0, 45, 60, 75, 100],      ["<45", "45-59", "60-74", "75+"]),
            ("trend_score",      [-1, 8, 14, 18, 22],       ["0-8", "8-14", "14-18", "18-22"]),
            ("volatility_score", [-1, 0.5, 1, 1.5, 2],      ["0-0.5 (rendah)", "0.5-1", "1-1.5", "1.5-2 (tinggi)"]),
            ("flow_score",       [-1, 2, 5, 8, 10],         ["0-2", "2-5", "5-8", "8-10"]),
            ("minus_di",         [0, 10, 15, 20, 100],       ["<10", "10-14", "15-19", "20+"]),
            ("adx",              [0, 20, 25, 30, 40, 100],   ["<20", "20-24", "25-29", "30-39", "40+"]),
        ]
        cc = st.columns(2)
        for i, (feat, bins, labels) in enumerate(calib_specs):
            if feat not in closed_df.columns:
                continue
            tmp = closed_df.copy()
            tmp[feat] = tmp[feat].apply(sf)
            tmp["bucket"] = pd.cut(tmp[feat], bins=bins, labels=labels)
            g = tmp.groupby("bucket", observed=True).agg(
                n=("net_return_pct", "count"),
                win_rate=("net_return_pct", lambda x: (x > 0).mean()),
                avg_return=("net_return_pct", "mean"),
            ).reset_index()
            g = g[g["n"] > 0]
            with cc[i % 2]:
                fig = go.Figure(go.Bar(
                    x=g["bucket"].astype(str), y=g["avg_return"],
                    marker_color=g["avg_return"].apply(lambda x: "#00c896" if x >= 0 else "#f87171"),
                    text=g.apply(lambda r: f"{r['avg_return']:+.1f}%<br>n={r['n']}", axis=1),
                    textposition="outside",
                ))
                fig.update_layout(title=f"Avg Return per bucket: {feat}", height=260, **LAYOUT)
                st.plotly_chart(fig, use_container_width=True)
        st.caption(
            "Idealnya avg return naik monoton seiring bucket 'lebih bagus' (raw_score tinggi, "
            "minus_di rendah, dst). Kalau flat/terbalik, faktor itu belum/tidak prediktif -- "
            "lihat AUDIT note di src/signals/ta_engine.py::_score_strength/_score_volatility."
        )

    # ── Backtest Summary (dipertahankan, sumber terpisah dari signal_results) ─
    if bt:
        section("BACKTEST SUMMARY", "🧪")
        df_bt = pd.DataFrame(bt)
        for col in ["win_rate","profit_factor","sharpe_ratio","max_drawdown","expectancy"]:
            if col in df_bt.columns:
                df_bt[col] = df_bt[col].apply(sf)
        c1,c2,c3 = st.columns(3)
        with c1: st.markdown(tile("Saham Dibacktest", len(df_bt)), unsafe_allow_html=True)
        with c2: st.markdown(tile("Avg Win Rate", f"{df_bt['win_rate'].mean():.1%}"), unsafe_allow_html=True)
        with c3: st.markdown(tile("Avg Sharpe", f"{df_bt['sharpe_ratio'].mean():.2f}"), unsafe_allow_html=True)

        top = df_bt.nlargest(10, "win_rate")[
            ["ticker","total_trades","win_rate","profit_factor",
             "max_drawdown","sharpe_ratio","expectancy"]].copy()
        for col, fmt in [("win_rate","{:.1%}"),("profit_factor","{:.2f}"),
                         ("sharpe_ratio","{:.2f}"),("expectancy","{:.2f}%")]:
            top[col] = top[col].apply(lambda x: fmt.format(sf(x)))
        top["max_drawdown"] = top["max_drawdown"].apply(lambda x: f"{sf(x)*100:.1f}%")
        st.dataframe(top.rename(columns={
            "ticker":"Ticker","total_trades":"Trades","win_rate":"Win Rate",
            "profit_factor":"PF","max_drawdown":"Max DD",
            "sharpe_ratio":"Sharpe","expectancy":"Expectancy"}),
            use_container_width=True, hide_index=True)
    else:
        st.info("Backtest berjalan otomatis setiap Sabtu pagi.")

# ══════════════════════════════════════════════════════════════════
#  PAGE — SECTOR ROTATION
# ══════════════════════════════════════════════════════════════════

def page_sector_rotation():
    st.markdown('<div class="ds-page-title">Sector Rotation</div>', unsafe_allow_html=True)
    st.markdown('<div class="ds-page-sub">Sektor mana yang sedang memimpin momentum pasar.</div>', unsafe_allow_html=True)

    sectors = load_sectors()
    if not sectors:
        st.info("Data sektor belum tersedia. Tersedia setelah scan pertama."); return

    df = pd.DataFrame(sectors)
    for col in ["composite_score","return_1d","return_5d","return_20d",
                "momentum_score","breadth_score","rank_position"]:
        if col in df.columns:
            df[col] = df[col].apply(sf)
    df = df.sort_values("composite_score", ascending=False).reset_index(drop=True)

    section("SECTOR LEADERBOARD", "🏆")
    for i, row in df.iterrows():
        rank   = i+1
        sector = ss(row.get("sector"),"—")
        score  = sf(row.get("composite_score"))
        r5d    = sf(row.get("return_5d")); r1d = sf(row.get("return_1d"))
        trend  = ss(row.get("trend"),"STABLE")
        breadth= sf(row.get("breadth_score"))
        te     = {"RISING":"⬆","STABLE":"→","FALLING":"⬇"}.get(trend,"→")
        medal  = {1:"🥇",2:"🥈",3:"🥉"}.get(rank, f"#{rank}")
        r5c = "#4ade80" if r5d>0 else "#f87171"
        r1c = "#4ade80" if r1d>0 else "#f87171"

        st.markdown(
            f'<div class="ds-card" style="padding:14px 20px;margin-bottom:8px">'
            f'<div style="display:flex;align-items:center;gap:14px">'
            f'<div style="width:32px;font-size:1.1rem">{medal}</div>'
            f'<div style="width:190px;font-weight:700">{sector} <span style="color:#9aa4b8;font-weight:400">{te}</span></div>'
            f'<div style="flex:1">{gauge_row("", score, 100)}</div>'
            f'<div class="ds-num" style="width:80px;text-align:right;color:{r5c}">{r5d:+.1f}% 5D</div>'
            f'<div class="ds-num" style="width:80px;text-align:right;color:{r1c}">{r1d:+.1f}% 1D</div>'
            f'<div class="ds-num" style="width:90px;text-align:right;color:#9aa4b8">Breadth {breadth:.0f}%</div>'
            f'</div></div>',
            unsafe_allow_html=True
        )

    c1,c2 = st.columns(2)
    with c1:
        fig = go.Figure(go.Bar(
            x=df["composite_score"], y=df["sector"], orientation="h",
            marker_color=[score_color(s) for s in df["composite_score"]],
            text=df["composite_score"].apply(lambda x: f"{x:.1f}"), textposition="outside"))
        fig.update_layout(title="Composite Score per Sektor", height=380,
                          margin=dict(l=0,r=60,t=30,b=0), paper_bgcolor=DARK_BG, plot_bgcolor=PLOT_BG,
                          font=LAYOUT["font"],
                          xaxis=dict(range=[0,110], showgrid=False), yaxis=dict(autorange="reversed"))
        st.plotly_chart(fig, use_container_width=True)
    with c2:
        if all(c in df.columns for c in ["return_1d","return_5d","return_20d"]):
            mat = df[["return_1d","return_5d","return_20d"]].values
            fig = go.Figure(go.Heatmap(
                z=mat, x=["1D","5D","20D"], y=df["sector"].tolist(),
                colorscale=[[0,"#f87171"],[0.5,"#171d2c"],[1,"#00c896"]], zmid=0,
                text=[[f"{v:+.1f}%" for v in r] for r in mat],
                texttemplate="%{text}", textfont=dict(size=11)))
            fig.update_layout(title="Return Heatmap", height=380,
                              margin=dict(l=0,r=0,t=30,b=0), paper_bgcolor=DARK_BG, font=LAYOUT["font"])
            st.plotly_chart(fig, use_container_width=True)

    if "momentum_score" in df.columns and "breadth_score" in df.columns:
        section("MOMENTUM VS BREADTH", "📡")
        fig = px.scatter(df, x="momentum_score", y="breadth_score",
                         size="composite_score", color="composite_score",
                         color_continuous_scale=["#f87171","#fbbf24","#00c896"],
                         text="sector")
        fig.update_traces(textposition="top center", textfont_size=10)
        fig.update_layout(height=380, **LAYOUT, coloraxis_showscale=False)
        st.plotly_chart(fig, use_container_width=True)


# ══════════════════════════════════════════════════════════════════
#  PAGE — BROKER FLOW (Bandarmology)
#  BARU — belum ada di composite scoring (raw_score), murni informasional
#  sampai ada validasi empiris memadai (pola sama dgn AUDIT di ta_engine.py).
#  Kosong sampai provider di src/providers/broker_data.py dikonfigurasi.
# ══════════════════════════════════════════════════════════════════

def page_broker_flow():
    st.markdown('<div class="ds-page-title">Broker Flow</div>', unsafe_allow_html=True)
    st.markdown('<div class="ds-page-sub">Akumulasi/distribusi broker per saham (bandarmologi). Belum masuk composite scoring.</div>', unsafe_allow_html=True)

    top = load_broker_flow_top(limit=20)
    if not top:
        st.info(
            "Data broker summary belum tersedia. Provider belum dikonfigurasi — "
            "lihat src/providers/broker_data.py dan set BROKER_DATA_PROVIDER di .env."
        )
        return

    tab_screener, tab_detail, tab_stalker = st.tabs(
        ["🏆 Top Akumulasi", "🔍 Detail Saham", "🕵️ Broker Stalker"]
    )

    # ── TAB 1: TOP AKUMULASI (screener) ──────────────────────────
    with tab_screener:
        min_streak = st.slider(
            "Minimal streak akumulasi berturut (hari)", 0, 10, 0,
            help="0 = tanpa filter. Makin tinggi, makin ketat (saham yang net buy-nya positif N hari berturut-turut)."
        )
        top_filtered = load_broker_flow_top(limit=20) if min_streak == 0 else load_broker_flow_top_streak(min_streak, limit=20)

        if not top_filtered:
            st.caption("Tidak ada saham yang lolos filter streak ini.")
        else:
            df = pd.DataFrame(top_filtered)
            for col in ["total_net_value", "foreign_net_value", "domestic_net_value", "bumn_net_value", "broker_count"]:
                if col in df.columns:
                    df[col] = df[col].apply(sf)

            snap_date = ss(df["trade_date"].iloc[0], "—") if "trade_date" in df.columns and not df.empty else "—"
            section(f"TOP AKUMULASI — {snap_date}", "🏆")

            for i, row in df.iterrows():
                ticker  = ss(row.get("ticker"), "—")
                net     = sf(row.get("total_net_value"))
                fnet    = sf(row.get("foreign_net_value"))
                dnet    = sf(row.get("domestic_net_value"))
                bcount  = si(row.get("broker_count"))
                streak  = row.get("accumulation_streak_days")
                net_c   = "#4ade80" if net > 0 else "#f87171"
                f_c     = "#4ade80" if fnet > 0 else "#f87171"
                streak_html = f'<div class="ds-chip" style="width:70px;text-align:center">🔥 {si(streak)}d</div>' if streak else '<div style="width:70px"></div>'

                st.markdown(
                    f'<div class="ds-card" style="padding:14px 20px;margin-bottom:8px">'
                    f'<div style="display:flex;align-items:center;gap:14px">'
                    f'<div style="width:36px;font-size:1.1rem">#{i+1}</div>'
                    f'<div style="width:100px;font-weight:700">{ticker}</div>'
                    f'<div class="ds-num" style="width:150px;text-align:right;color:{net_c}">Net Rp{net:,.0f}</div>'
                    f'<div class="ds-num" style="width:150px;text-align:right;color:{f_c}">Asing Rp{fnet:,.0f}</div>'
                    f'<div class="ds-num" style="width:140px;text-align:right;color:#9aa4b8">Domestik Rp{dnet:,.0f}</div>'
                    f'<div class="ds-num" style="width:80px;text-align:right;color:#9aa4b8">{bcount} broker</div>'
                    f'{streak_html}'
                    f'</div></div>',
                    unsafe_allow_html=True
                )

    # ── TAB 2: DETAIL SAHAM (chart + tabel broker lengkap + asing/domestik) ──
    with tab_detail:
        all_tickers = [t["ticker"] for t in top]
        ticker_pick = st.selectbox("Pilih saham", all_tickers, key="broker_detail_ticker")
        if ticker_pick:
            detail = load_broker_flow_detail(ticker_pick, days=30)
            if detail:
                ddf = pd.DataFrame(detail).sort_values("trade_date")
                fig = go.Figure()
                fig.add_trace(go.Bar(
                    x=ddf["trade_date"], y=ddf["total_net_value"],
                    marker_color=[("#00c896" if v > 0 else "#f87171") for v in ddf["total_net_value"]],
                    name="Net Value"
                ))
                fig.update_layout(title=f"Net Broker Flow — {ticker_pick} (30 hari)", height=300, **LAYOUT)
                st.plotly_chart(fig, use_container_width=True)

                # Breakdown Asing/Domestik/BUMN (BARU) -- data sudah ada di
                # v_broker_net_flow_daily sejak awal, sekarang baru disurface
                latest_row = ddf.iloc[-1]
                section("BREAKDOWN INVESTOR TYPE (hari terakhir)", "🌏")
                bc1, bc2, bc3 = st.columns(3)
                fnet = sf(latest_row.get("foreign_net_value"))
                dnet = sf(latest_row.get("domestic_net_value"))
                bnet = sf(latest_row.get("bumn_net_value"))
                with bc1: st.markdown(tile("Asing", f"Rp{fnet:+,.0f}"), unsafe_allow_html=True)
                with bc2: st.markdown(tile("Domestik", f"Rp{dnet:+,.0f}"), unsafe_allow_html=True)
                with bc3: st.markdown(tile("BUMN", f"Rp{bnet:+,.0f}"), unsafe_allow_html=True)
            else:
                st.caption("Belum ada histori broker flow untuk saham ini.")

            # Ringkasan Broker Lengkap (BARU, ala NeoBDM) -- semua broker,
            # bukan cuma top-3 seperti Flow Radar/leaderboard.
            section("RINGKASAN BROKER LENGKAP", "📋")
            full_summary = load_full_broker_summary(ticker_pick)
            if full_summary:
                fdf = pd.DataFrame(full_summary)
                show_cols = [c for c in ["broker_code", "broker_name", "buy_value", "sell_value",
                                          "net_value", "net_volume", "buy_frequency", "sell_frequency"]
                             if c in fdf.columns]
                fdf_display = fdf[show_cols].rename(columns={
                    "broker_code": "Kode", "broker_name": "Nama Broker",
                    "buy_value": "Buy Value", "sell_value": "Sell Value",
                    "net_value": "Net Value", "net_volume": "Net Volume",
                    "buy_frequency": "Freq Beli", "sell_frequency": "Freq Jual",
                })
                st.dataframe(fdf_display, use_container_width=True, hide_index=True)
                st.caption(f"{len(fdf)} broker tercatat bertransaksi pada tanggal terakhir yang tersedia.")
            else:
                st.caption("Belum ada data ringkasan broker lengkap untuk saham ini.")

    # ── TAB 3: BROKER STALKER (BARU, ala NeoBDM) ─────────────────
    with tab_stalker:
        st.markdown(
            '<div class="ds-caption">Lacak 1 broker lintas SEMUA saham — lihat saham apa saja '
            'yang paling banyak diakumulasi/didistribusi broker tertentu hari ini.</div>',
            unsafe_allow_html=True
        )
        st.write("")
        brokers = load_known_brokers()
        if not brokers:
            st.info(
                "Daftar broker_classification masih kosong. Tambahkan minimal beberapa kode "
                "broker (lihat migration 004_broker_summary.sql) supaya Broker Stalker bisa dipakai."
            )
        else:
            broker_options = {f"{b['broker_code']} — {ss(b.get('broker_name'), '?')} ({ss(b.get('investor_type'), '?')})": b["broker_code"] for b in brokers}
            picked_label = st.selectbox("Pilih broker", list(broker_options.keys()))
            broker_code = broker_options[picked_label]

            stalker_rows = load_broker_stalker(broker_code, limit=20)
            if not stalker_rows:
                st.caption(f"Belum ada aktivitas tercatat untuk broker {broker_code}.")
            else:
                sdf = pd.DataFrame(stalker_rows)
                snap_date = ss(sdf["trade_date"].iloc[0], "—") if "trade_date" in sdf.columns else "—"
                section(f"AKTIVITAS {broker_code} — {snap_date}", "🕵️")

                for i, row in sdf.iterrows():
                    ticker = ss(row.get("ticker"), "—")
                    net = sf(row.get("net_value"))
                    buy_v = sf(row.get("buy_value"))
                    sell_v = sf(row.get("sell_value"))
                    net_c = "#4ade80" if net > 0 else "#f87171"
                    action = "AKUMULASI" if net > 0 else "DISTRIBUSI"

                    st.markdown(
                        f'<div class="ds-card" style="padding:12px 20px;margin-bottom:6px">'
                        f'<div style="display:flex;align-items:center;gap:14px">'
                        f'<div style="width:32px;color:#5c6478">#{i+1}</div>'
                        f'<div style="width:100px;font-weight:700">{ticker}</div>'
                        f'<div style="width:110px"><span class="ds-flow {"ds-flow-acc" if net>0 else "ds-flow-dist"}">{action}</span></div>'
                        f'<div class="ds-num" style="width:150px;text-align:right;color:{net_c}">Net Rp{net:,.0f}</div>'
                        f'<div class="ds-num" style="width:130px;text-align:right;color:#9aa4b8">Buy Rp{buy_v:,.0f}</div>'
                        f'<div class="ds-num" style="width:130px;text-align:right;color:#9aa4b8">Sell Rp{sell_v:,.0f}</div>'
                        f'</div></div>',
                        unsafe_allow_html=True
                    )

                # ── Jejak Broker (BARU) -- histori 1 broker di 1 saham ──
                section("JEJAK BROKER (histori per saham)", "📈")
                footprint_tickers = sdf["ticker"].tolist()
                footprint_ticker = st.selectbox(
                    f"Lihat jejak {broker_code} di saham mana?", footprint_tickers,
                    key="broker_footprint_ticker"
                )
                footprint_days = st.slider("Rentang hari", 10, 180, 60, key="broker_footprint_days")
                if footprint_ticker:
                    footprint = load_broker_footprint(footprint_ticker, broker_code, days=footprint_days)
                    if footprint and len(footprint) >= 2:
                        fpdf = pd.DataFrame(footprint).sort_values("trade_date")
                        fpdf["cum_net_value"] = fpdf["net_value"].apply(sf).cumsum()

                        fig_fp = go.Figure()
                        fig_fp.add_trace(go.Bar(
                            x=fpdf["trade_date"], y=fpdf["net_value"],
                            marker_color=[("#00c896" if v > 0 else "#f87171") for v in fpdf["net_value"]],
                            name="Net Value Harian", yaxis="y1"
                        ))
                        fig_fp.add_trace(go.Scatter(
                            x=fpdf["trade_date"], y=fpdf["cum_net_value"],
                            mode="lines", name="Kumulatif", line=dict(color="#fbbf24", width=2),
                            yaxis="y1"
                        ))
                        fig_fp.update_layout(
                            title=f"Jejak {broker_code} di {footprint_ticker} ({footprint_days} hari)",
                            height=340, **LAYOUT,
                            legend=dict(orientation="h", y=1.1)
                        )
                        st.plotly_chart(fig_fp, use_container_width=True)
                        st.caption(
                            "Batang = net value harian broker ini di saham ini. Garis kuning = "
                            "akumulasi kumulatif sepanjang rentang waktu yang dipilih."
                        )
                    else:
                        st.caption(f"Belum cukup histori {broker_code} di {footprint_ticker} untuk digambar (minimal 2 hari data).")


# ══════════════════════════════════════════════════════════════════
#  PAGE — PORTFOLIO
# ══════════════════════════════════════════════════════════════════

def page_portfolio():
    st.markdown('<div class="ds-page-title">Portfolio</div>', unsafe_allow_html=True)
    st.markdown('<div class="ds-page-sub">Ringkasan posisi dan performa trading Anda.</div>', unsafe_allow_html=True)

    stats   = load_portfolio_stats()
    open_pos = load_open_positions()
    closed   = load_closed_positions(500)

    section("PORTFOLIO SUMMARY", "💼")
    if stats:
        c1,c2,c3,c4,c5 = st.columns(5)
        with c1: st.markdown(tile("Posisi Aktif", si(stats.num_open_positions)), unsafe_allow_html=True)
        with c2: st.markdown(tile("Total Invested", fmt_rp(stats.total_invested)), unsafe_allow_html=True)
        inv  = sf(stats.total_invested); upnl = sf(stats.total_unrealized_pnl)
        dpct = f"{upnl/inv*100:.1f}%" if inv>0 else "0%"
        with c3: st.markdown(tile("Unrealized PnL", fmt_rp(upnl), dpct, "up" if upnl>=0 else "down"), unsafe_allow_html=True)
        with c4: st.markdown(tile("Realized PnL", fmt_rp(stats.total_realized_pnl)), unsafe_allow_html=True)
        with c5:
            wr_txt = f"{sf(stats.win_rate):.1%}" if stats.total_trades>0 else "N/A"
            st.markdown(tile("Win Rate", wr_txt), unsafe_allow_html=True)

    if closed:
        avg_hold = None
        try:
            df_hold = pd.DataFrame(closed)
            if "holding_days" in df_hold.columns:
                avg_hold = df_hold["holding_days"].apply(sf).mean()
        except Exception:
            pass
        if avg_hold is not None:
            st.markdown(tile("Avg Holding Time", f"{avg_hold:.0f} hari"), unsafe_allow_html=True)

    section("OPEN POSITIONS", "📂")
    if not open_pos:
        st.info("Belum ada posisi aktif.")
    else:
        rows = []
        for p in open_pos:
            rows.append({
                "Ticker":      ss(p.get("ticker")).replace(".JK",""),
                "Masuk":       ss(p.get("entry_date")),
                "Entry":       sf(p.get("entry_price")),
                "Harga Kini":  sf(p.get("current_price")),
                "Lot":         si(p.get("shares")),
                "Unrealized":  sf(p.get("unrealized_pnl")),
                "Return %":    sf(p.get("unrealized_pct"))*100,
            })
        df = pd.DataFrame(rows)
        def cpnl(v):
            if isinstance(v, float):
                return "color:#00c896;font-weight:700" if v>=0 else "color:#f87171;font-weight:700"
            return ""
        styled = _styler_apply(df.style, cpnl, subset=["Unrealized","Return %"])
        styled = styled.format({"Entry":"Rp{:,.0f}","Harga Kini":"Rp{:,.0f}",
                                  "Unrealized":"Rp{:,.0f}","Return %":"{:+.2f}%"})
        st.dataframe(styled, use_container_width=True, hide_index=True)

    if closed:
        section("CLOSED POSITIONS", "📁")
        df_c = pd.DataFrame(closed[:50])
        show_cols = [c for c in ["ticker","entry_date","exit_date","entry_price","exit_price",
                                  "net_pnl","return_pct","exit_reason"] if c in df_c.columns]
        if show_cols:
            df_show = df_c[show_cols].copy()
            if "return_pct" in df_show.columns:
                df_show["return_pct"] = df_show["return_pct"].apply(lambda x: sf(x)*100)
            st.dataframe(df_show, use_container_width=True, hide_index=True, height=300)

    st.markdown("<hr class='ds-hr'>", unsafe_allow_html=True)
    with st.expander("➕ Buka Posisi Baru"):
        with st.form("pos_form"):
            c1,c2,c3 = st.columns(3)
            tk = c1.text_input("Ticker (contoh: BBCA)")
            ep = c2.number_input("Entry (Rp)", min_value=1, value=1000)
            sh = c3.number_input("Saham", min_value=100, step=100, value=100)
            c4,c5,c6 = st.columns(3)
            sl_ = c4.number_input("Stop Loss", min_value=1, value=900)
            t1  = c5.number_input("Target 1",  min_value=1, value=1100)
            t2  = c6.number_input("Target 2",  min_value=1, value=1200)
            nt  = st.text_area("Catatan")
            if st.form_submit_button("Buka Posisi", type="primary"):
                if tk:
                    from src.portfolio.tracker import open_position
                    pid = open_position(ticker=tk.upper().strip()+".JK",
                                       entry_price=ep, shares=sh,
                                       stop_loss=sl_, target_1=t1, target_2=t2, notes=nt)
                    if pid:
                        st.success(f"✓ Posisi {tk.upper()} dibuka!"); st.cache_data.clear()
                    else:
                        st.error("Gagal membuka posisi.")
                else:
                    st.warning("Isi ticker terlebih dahulu.")


# ══════════════════════════════════════════════════════════════════
#  PAGE — SYSTEM HEALTH (gabungan System Health + Logs)
# ══════════════════════════════════════════════════════════════════

def page_system_health():
    st.markdown('<div class="ds-page-title">System Health</div>', unsafe_allow_html=True)
    st.markdown('<div class="ds-page-sub">Status komponen sistem dan log terbaru.</div>', unsafe_allow_html=True)

    last_run = load_last_scan_run()
    uni_count = load_universe_count()
    regime = load_regime()

    section("KOMPONEN", "🩺")
    c1,c2,c3,c4 = st.columns(4)
    with c1:
        ok = regime is not None
        st.markdown(tile("Database", "Online" if ok else "Offline"), unsafe_allow_html=True)
    with c2:
        st.markdown(tile("Universe", f"{uni_count:,} saham"), unsafe_allow_html=True)
    with c3:
        status = ss(last_run.get("status"), "N/A") if last_run else "N/A"
        st.markdown(tile("Scan Terakhir", status), unsafe_allow_html=True)
    with c4:
        dur = si(last_run.get("duration_seconds")) if last_run else 0
        st.markdown(tile("Durasi Scan", f"{dur}s" if dur else "N/A"), unsafe_allow_html=True)

    if last_run:
        section("DETAIL SCAN TERAKHIR", "🔬")
        c1,c2,c3 = st.columns(3)
        with c1: st.markdown(tile("Saham Discan", si(last_run.get("stocks_scanned"))), unsafe_allow_html=True)
        with c2: st.markdown(tile("Sinyal Dihasilkan", si(last_run.get("signals_generated"))), unsafe_allow_html=True)
        with c3: st.markdown(tile("Waktu Mulai", ss(last_run.get("started_at"))[:16].replace("T"," ")), unsafe_allow_html=True)

    section("SYSTEM LOGS", "📜")
    c1,c2 = st.columns(2)
    lim   = c1.slider("Jumlah", 20, 200, 50)
    lvl   = c2.multiselect("Level", ["DEBUG","INFO","WARNING","ERROR","CRITICAL"],
                           default=["WARNING","ERROR","CRITICAL"])
    logs = load_logs(lim)
    filtered = [l for l in logs if ss(l.get("level")) in lvl]
    if not filtered:
        st.info("Tidak ada log pada level yang dipilih.")
    else:
        icons  = {"DEBUG":"○","INFO":"●","WARNING":"▲","ERROR":"✕","CRITICAL":"⛔"}
        colors = {"DEBUG":"#5c6478","INFO":"#9aa4b8","WARNING":"#fbbf24",
                  "ERROR":"#f87171","CRITICAL":"#f87171"}
        log_html = ""
        for e in filtered:
            lv  = ss(e.get("level"), "INFO")
            lvc = colors.get(lv, "#9aa4b8")
            lvi = icons.get(lv, "●")
            lt  = ss(e.get("log_time"))[:19]
            mod = ss(e.get("module"))
            msg = ss(e.get("message"))
            log_html += (
                f'<div style="padding:6px 0;border-bottom:1px solid #1a2233;font-size:.82rem">'
                f'<span style="color:{lvc}">{lvi}</span> '
                f'<span class="ds-num" style="color:#5c6478">{lt}</span> '
                f'<span style="color:#60a5fa">[{mod}]</span> '
                f'<span style="color:{lvc if lv in ("ERROR","CRITICAL") else "#e8ebf2"}">{msg}</span>'
                f'</div>'
            )
        st.markdown(f'<div class="ds-card">{log_html}</div>', unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════════

def main():
    page = render_sidebar()

    if "nav_override" in st.session_state:
        page = st.session_state.pop("nav_override")

    page_map = {
        "home":        page_home,
        "signals":     page_top_signals,
        "detail":      page_signal_detail,
        "history":     page_historical_signals,
        "performance": page_signal_performance,
        "sector":      page_sector_rotation,
        "broker":      page_broker_flow,
        "portfolio":   page_portfolio,
        "health":      page_system_health,
    }
    page_map.get(page, page_home)()


if __name__ == "__main__":
    main()
