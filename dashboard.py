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
<link href="https://fonts.googleapis.com/css2?family=Manrope:wght@500;600;700;800&family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@500;700;800&display=swap" rel="stylesheet">
<style>

/* ── Base tokens (Neon Cyber Theme) ──────────────────────────── */
:root{
    --bg:            #050505;
    --surface:       rgba(18, 18, 18, 0.65);
    --surface-2:     rgba(35, 35, 35, 0.8);
    --border:        rgba(255, 255, 255, 0.08);
    --border-soft:   rgba(255, 255, 255, 0.03);
    --text:          #f4f4f5;
    --text-dim:      #a1a1aa;
    --text-faint:    #52525b;
    --accent:        #00f0ff;
    --accent-soft:   rgba(0, 240, 255, 0.15);
    --strong-buy:    #00ffa3;
    --buy:           #b4ff00;
    --watchlist:     #ffb800;
    --avoid:         #ff3366;
    --strong-buy-bg: rgba(0, 255, 163, 0.12);
    --buy-bg:        rgba(180, 255, 0, 0.12);
    --watchlist-bg:  rgba(255, 184, 0, 0.12);
    --avoid-bg:      rgba(255, 51, 102, 0.12);
}

html, body, [class*="css"]{ font-family: 'Inter', sans-serif; background: var(--bg); }
h1,h2,h3,h4, .ds-heading{ font-family: 'Manrope', sans-serif !important; }

/* ── Background & Layouts ────────────────────────────────────── */
.main{ padding: 0 1.4rem; background: radial-gradient(circle at top right, #131824 0%, var(--bg) 60%); }
.block-container{ padding-top: 1rem; padding-bottom: 2rem; max-width: 1400px; }
[data-testid="stAppViewContainer"]{ background: transparent; }
[data-testid="stHeader"]{ background: transparent; }

/* Angka pakai font ala coding/terminal biar rapi & pro */
.ds-num{ font-family: 'JetBrains Mono', monospace; font-variant-numeric: tabular-nums; letter-spacing: -0.02em; }

/* ── Sidebar Glass Effect ─────────────────────────────────────── */
div[data-testid="stSidebarContent"]{
    background: rgba(10, 10, 12, 0.85);
    backdrop-filter: blur(20px);
    border-right: 1px solid var(--border);
}
.ds-brand{
    font-family:'Manrope',sans-serif; font-weight:800; font-size:1.35rem;
    letter-spacing:-.02em; color:var(--text); margin-bottom:0;
    display:flex; align-items:center; gap:8px;
    text-shadow: 0 0 15px var(--accent-soft);
}
.ds-brand-sub{ color:var(--accent); font-size:.72rem; letter-spacing:.1em;
    text-transform:uppercase; margin-top:2px; margin-bottom:14px; font-weight: 700; }

div[data-testid="stSidebarContent"] div[role="radiogroup"] label{
    padding: 9px 12px !important; border-radius: 8px !important;
    margin-bottom: 2px !important; transition: all .2s ease; border: 1px solid transparent;
}
div[data-testid="stSidebarContent"] div[role="radiogroup"] label:hover{
    background: var(--surface-2); border: 1px solid var(--border);
}

/* ── Cards & Glassmorphism ────────────────────────────────────── */
.ds-card, .ds-hero, .ds-tile, div[data-testid="metric-container"] {
    background: var(--surface);
    backdrop-filter: blur(16px);
    -webkit-backdrop-filter: blur(16px);
    border: 1px solid var(--border);
    border-radius: 14px;
    box-shadow: 0 8px 32px rgba(0, 0, 0, 0.4);
    transition: transform 0.2s ease, box-shadow 0.2s ease;
}
.ds-card:hover, .ds-tile:hover {
    box-shadow: 0 12px 40px rgba(0, 0, 0, 0.6);
    border-color: rgba(255, 255, 255, 0.15);
}
.ds-card{ padding: 18px 20px; margin-bottom: 12px; }
.ds-card-flush{ padding:0; overflow:hidden; }
.ds-hero{ padding:22px 26px; margin-bottom:16px; background: linear-gradient(135deg, rgba(18,18,18,0.8) 0%, rgba(18,18,18,0.2) 100%); border-top: 1px solid rgba(255,255,255,0.12);}

/* ── Metric tile ─────────────────────────────────────────────── */
.ds-tile{ padding:15px 18px; height:100%; border-top: 1px solid rgba(255,255,255,0.1); }
.ds-tile-label{ color:var(--text-dim); font-size:.7rem; text-transform:uppercase;
    letter-spacing:.08em; margin-bottom:5px; font-weight:600;}
.ds-tile-value{ font-weight:800; font-size:1.35rem; color:var(--text); text-shadow: 0 0 10px rgba(255,255,255,0.1); }
.ds-tile-delta{ font-size:.74rem; margin-top:4px; font-weight:600;}
.ds-up{ color: var(--buy); text-shadow: 0 0 8px var(--buy-bg); } 
.ds-down{ color: var(--avoid); text-shadow: 0 0 8px var(--avoid-bg); } 
.ds-flat{ color:var(--text-faint); }

/* ── Typography helpers ──────────────────────────────────────── */
.ds-page-title{ font-family:'Manrope',sans-serif; font-weight:800; font-size:1.8rem;
    color:var(--text); letter-spacing:-.02em; margin-bottom:2px; }
.ds-page-sub{ color:var(--accent); font-size:.85rem; margin-bottom:1.2rem; font-weight:500; }
.ds-section{ font-family:'Manrope',sans-serif; font-weight:700; font-size:.95rem;
    color:var(--text); margin: 24px 0 12px; display:flex; align-items:center; gap:10px; letter-spacing:0.03em;}
.ds-section .ds-section-line{ flex:1; height:1px; background: linear-gradient(90deg, var(--border) 0%, transparent 100%); }
.ds-caption{ color:var(--text-faint); font-size:.78rem; font-family:'JetBrains Mono', monospace;}

/* ── Badges / Chips (Neon Glow) ──────────────────────────────── */
.ds-badge{ display:inline-flex; align-items:center; gap:6px; padding:4px 12px;
    border-radius:20px; font-weight:700; font-size:.71rem; letter-spacing:.04em; border: 1px solid transparent; }
.ds-badge::before{ content:''; width:6px; height:6px; border-radius:50%; box-shadow: 0 0 8px currentColor; }
.ds-badge-sb{ background:var(--strong-buy-bg); color:var(--strong-buy); border-color:rgba(0,255,163,0.3); text-shadow: 0 0 8px rgba(0,255,163,0.4); }
.ds-badge-sb::before{ background:var(--strong-buy); }
.ds-badge-buy{ background:var(--buy-bg); color:var(--buy); border-color:rgba(180,255,0,0.3); }
.ds-badge-buy::before{ background:var(--buy); }
.ds-badge-wl{ background:var(--watchlist-bg); color:var(--watchlist); border-color:rgba(255,184,0,0.3); }
.ds-badge-wl::before{ background:var(--watchlist); }
.ds-badge-av{ background:var(--avoid-bg); color:var(--avoid); border-color:rgba(255,51,102,0.3); }
.ds-badge-av::before{ background:var(--avoid); }

.ds-chip{ display:inline-block; padding:3px 10px; border-radius:6px; font-size:.71rem;
    background:rgba(255,255,255,0.03); color:var(--text-dim); border:1px solid var(--border); font-weight:600;}
.ds-chip-accent{ background:var(--accent-soft); color:var(--accent); border-color:var(--accent); text-shadow: 0 0 8px var(--accent-soft);}

.ds-conf{ display:inline-flex; align-items:center; gap:4px; font-size:.71rem; font-weight:700; letter-spacing:0.02em;}
.ds-conf-dots span{ width:6px; height:6px; border-radius:50%; display:inline-block; margin-right:2px; background:var(--border); }

/* ── Gauge / progress bars ───────────────────────────────────── */
.ds-gauge-row{ display:flex; align-items:center; gap:12px; margin:8px 0; }
.ds-gauge-label{ width:92px; font-size:.78rem; color:var(--text-dim); flex-shrink:0; font-weight:500;}
.ds-gauge-track{ flex:1; height:6px; background:rgba(255,255,255,0.05); border-radius:10px; overflow:hidden; }
.ds-gauge-fill{ height:100%; border-radius:10px; box-shadow: 0 0 10px currentColor; }
.ds-gauge-val{ width:52px; text-align:right; font-size:.78rem; font-weight:700; color:var(--text); flex-shrink:0; }

/* ── Signal list row ─────────────────────────────────────────── */
.ds-row{ display:flex; align-items:center; gap:14px; padding:14px 18px;
    border-bottom:1px solid var(--border-soft); transition:all .15s ease; }
.ds-row:last-child{ border-bottom:none; }
.ds-row:hover{ background: rgba(255,255,255,0.02); padding-left: 22px; }
.ds-row-ticker{ font-weight:800; font-size:.95rem; color:var(--text); width:64px; flex-shrink:0; letter-spacing:0.02em;}
.ds-row-sector{ color:var(--text-faint); font-size:.72rem; font-weight:600; text-transform:uppercase; letter-spacing:0.05em;}

/* ── Reason checklist ─────────────────────────────────────────── */
.ds-reason{ display:flex; align-items:flex-start; gap:10px; padding:8px 0; font-size:.87rem; color:var(--text-dim); }
.ds-reason-check{ color:var(--accent); font-weight:800; flex-shrink:0; text-shadow: 0 0 8px var(--accent-soft);}

/* ── Health dot ───────────────────────────────────────────────── */
.ds-health{ display:flex; align-items:center; gap:8px; padding:9px 0; font-weight:600; font-size:0.85rem;}
.ds-health-dot{ width:10px; height:10px; border-radius:50%; flex-shrink:0; }
.ds-health-ok{ background:var(--strong-buy); box-shadow:0 0 10px var(--strong-buy); }
.ds-health-bad{ background:var(--avoid); box-shadow:0 0 10px var(--avoid); }
.ds-health-warn{ background:var(--watchlist); box-shadow:0 0 10px var(--watchlist); }

hr{ border-color: var(--border) !important; }
.ds-hr{ height:1px; background:var(--border-soft); margin:16px 0; border:none; }

/* ── Streamlit native tweaks ─────────────────────────────────── */
.stDataFrame{ border-radius:12px; overflow:hidden; border:1px solid var(--border); box-shadow: 0 8px 32px rgba(0,0,0,0.4); }
button[kind="secondary"]{ background: var(--surface) !important; border: 1px solid var(--border) !important; color: var(--text) !important; border-radius: 8px !important; }
button[kind="secondary"]:hover{ border-color: var(--accent) !important; color: var(--accent) !important; box-shadow: 0 0 15px var(--accent-soft) !important; }
button[kind="primary"]{ background: var(--accent) !important; color: #000 !important; font-weight: 800 !important; border-radius: 8px !important; box-shadow: 0 0 15px var(--accent-soft) !important; border: none !important;}
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

SIGNAL_COLOR = {"STRONG_BUY":"#00ffa3","BUY":"#b4ff00","WATCHLIST":"#ffb800","AVOID":"#ff3366"}
SIGNAL_BG    = {"STRONG_BUY":"rgba(0,255,163,.12)","BUY":"rgba(180,255,0,.12)",
                "WATCHLIST":"rgba(255,184,0,.12)","AVOID":"rgba(255,51,102,.12)"}
SIGNAL_LABEL = {"STRONG_BUY":"STRONG BUY","BUY":"BUY","WATCHLIST":"WATCHLIST","AVOID":"AVOID"}

def score_color(s):
    s = sf(s)
    if s >= 75: return "#00ffa3" # Neon Emerald
    if s >= 60: return "#b4ff00" # Neon Lime
    if s >= 45: return "#ffb800" # Neon Amber
    return "#ff3366"             # Neon Red

def signal_badge(t):
    cls = {"STRONG_BUY":"ds-badge-sb","BUY":"ds-badge-buy","WATCHLIST":"ds-badge-wl","AVOID":"ds-badge-av"}.get(t,"ds-badge-av")
    label = SIGNAL_LABEL.get(t, ss(t).replace("_"," "))
    return f'<span class="ds-badge {cls}">{label}</span>'

def confidence_badge(c):
    """Confidence dari migration 002 (compute_confidence) — fallback aman jika belum ada."""
    c = ss(c, "Low")
    dots = {"Very High":4, "High":3, "Medium":2, "Low":1}.get(c, 1)
    colors = {"Very High":"#00ffa3","High":"#b4ff00","Medium":"#ffb800","Low":"#52525b"}
    color = colors.get(c, "#a1a1aa")
    dot_html = "".join(
        f'<span style="background:{color if i < dots else "rgba(255,255,255,0.08)"}; box-shadow: {"0 0 8px "+color if i < dots else "none"};"></span>'
        for i in range(4)
    )
    return f'<span class="ds-conf" style="color:{color}"><span class="ds-conf-dots">{dot_html}</span>{c}</span>'

def gauge_row(label, val, mx, color=None):
    pct = min(sf(val)/mx*100, 100) if mx > 0 else 0
    c = color or score_color(pct)
    return (
        f'<div class="ds-gauge-row">'
        f'<div class="ds-gauge-label">{label}</div>'
        f'<div class="ds-gauge-track"><div class="ds-gauge-fill" style="width:{pct:.0f}%;background:{c};color:{c}"></div></div>'
        f'<div class="ds-gauge-val ds-num">{sf(val):.0f}/{mx:.0f}</div>'
        f'</div>'
    )

def tile(label, value, delta=None, delta_dir="flat"):
    dcls = {"up":"ds-up","down":"ds-down","flat":"ds-flat"}.get(delta_dir,"ds-flat")
    delta_html = f'<div class="ds-tile-delta {dcls}">{delta}</div>' if delta else ""
    return (
        f'<div class="ds-tile"><div class="ds-tile-label">{label}</div>'
        f'<div class="ds-tile-value ds-num">{value}</div>{delta_html}</div>'
    )

def section(title, icon=""):
    st.markdown(
        f'<div class="ds-section"><span style="color:var(--accent);text-shadow:0 0 10px var(--accent-soft)">{icon}</span> {title}<div class="ds-section-line"></div></div>',
        unsafe_allow_html=True
    )

def regime_visual(r):
    return {
        "BULL":     ("🚀", "#00ffa3", "Kondisi pasar mendukung — sinyal beli lebih terpercaya."),
        "SIDEWAYS": ("⚖️", "#ffb800", "Pasar konsolidasi — pilih saham selektif dengan skor tinggi."),
        "BEAR":     ("🩸", "#ff3366", "Pasar melemah — kurangi eksposur, perketat stop loss."),
    }.get(r, ("⚪", "#52525b", "Status pasar belum diketahui."))

DARK_BG = "rgba(0,0,0,0)"
PLOT_BG = "rgba(10,10,12,0.3)"
GRID    = "rgba(255,255,255,0.05)"
LAYOUT  = dict(paper_bgcolor=DARK_BG, plot_bgcolor=PLOT_BG,
               font=dict(family="Inter, sans-serif", color="#a1a1aa", size=11),
               margin=dict(l=0,r=0,t=30,b=0),
               xaxis=dict(gridcolor=GRID, zerolinecolor=GRID), yaxis=dict(gridcolor=GRID, zerolinecolor=GRID))


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
              .order("composite_score", desc=True).execute()
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
                "raw_score,sector_bonus,confidence")
        r = db.table("signals").select(cols).gte("signal_date", since)\
              .order("signal_date", desc=True).order("composite_score", desc=True).execute()
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
    ("portfolio", "💼", "Portfolio"),
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
            score  = sf(s.get("composite_score"))
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
    min_score  = c3.slider("Skor Minimum", 0, 100, 45)
    search_tk  = c4.text_input("Cari Ticker", placeholder="BBCA")

    signals = load_signals(scan_date.isoformat())
    if not signals:
        st.info(f"Tidak ada sinyal untuk {scan_date}."); return

    rows = []
    for s in signals:
        stype  = ss(s.get("signal_type"), "AVOID")
        score  = sf(s.get("composite_score"))
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
        })

    if not rows:
        st.warning("Tidak ada sinyal yang memenuhi filter."); return

    st.markdown(f'<div class="ds-caption">{len(rows)} sinyal ditemukan · {scan_date}</div>', unsafe_allow_html=True)
    st.write("")

    for idx, row in enumerate(rows, 1):
        with st.container():
            c = st.columns([0.4, 1.1, 1.6, 1.6, 1.5, 0.9, 0.9, 1.1, 1.1, 1.1, 0.8, 0.8])
            c[0].markdown(f'<span style="color:#5c6478;font-size:.8rem">#{idx}</span>', unsafe_allow_html=True)
            c[1].markdown(f'<span style="font-weight:700">{row["ticker"]}</span>', unsafe_allow_html=True)
            c[2].markdown(signal_badge(row["stype"]), unsafe_allow_html=True)
            if row["conf"]:
                c[3].markdown(confidence_badge(row["conf"]), unsafe_allow_html=True)
            else:
                c[3].markdown(f'<span class="ds-chip">score {row["score"]:.0f}</span>', unsafe_allow_html=True)
            c[4].markdown(f'<span class="ds-chip">{row["sector"][:16]}</span>', unsafe_allow_html=True)
            vc = "#4ade80" if row["vol"]>=1.5 else ("#fbbf24" if row["vol"]>=1 else "#f87171")
            c[5].markdown(f'<span class="ds-num" style="color:{vc}">{row["vol"]:.1f}x</span>', unsafe_allow_html=True)
            rc = "#4ade80" if row["rs"]>0 else "#f87171"
            c[6].markdown(f'<span class="ds-num" style="color:{rc}">{row["rs"]:+.1f}%</span>', unsafe_allow_html=True)
            c[7].markdown(f'<span class="ds-num">Rp{row["entry"]:,.0f}</span>', unsafe_allow_html=True)
            c[8].markdown(f'<span class="ds-num" style="color:#f87171">Rp{row["sl"]:,.0f}</span>', unsafe_allow_html=True)
            c[9].markdown(f'<span class="ds-num" style="color:#4ade80">Rp{row["tp1"]:,.0f}</span>', unsafe_allow_html=True)
            c[10].markdown(f'<span class="ds-num">1:{row["rr"]:.1f}</span>', unsafe_allow_html=True)
            if c[11].button("→", key=f"d_{row['ticker']}_{idx}", help="Lihat detail"):
                st.session_state["sel_ticker"] = row["ticker"]
                st.session_state["nav_override"] = "detail"
                st.rerun()
        st.markdown("<hr class='ds-hr' style='margin:4px 0'>", unsafe_allow_html=True)

    export = pd.DataFrame([{
        "Ticker": r["ticker"], "Signal": r["stype"], "Score": r["score"],
        "Sektor": r["sector"], "Harga": r["close"], "Entry": r["entry"],
        "SL": r["sl"], "TP1": r["tp1"], "R/R": r["rr"],
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
    if trend_score >= 24: reasons.append("EMA Bullish Alignment kuat")
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
    score  = sf(sig.get("composite_score"))
    raw    = sig.get("raw_score")
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
        f'<div style="font-size:.8rem;color:#9aa4b8">Score {score:.0f}/100'
        + (f' · raw {sf(raw):.0f}' if raw is not None else '') + '</div>'
        f'</div></div></div>',
        unsafe_allow_html=True
    )

    # ── Score Breakdown ──────────────────────────────────────────
    section("SCORE BREAKDOWN", "📊")
    comps = [
        ("Trend",      sf(sig.get("trend_score")),      30),
        ("Momentum",   sf(sig.get("momentum_score")),   25),
        ("Volume",     sf(sig.get("volume_score")),     20),
        ("Strength",   sf(sig.get("strength_score")),   15),
        ("Volatility", sf(sig.get("volatility_score")), 10),
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
    min_s     = c4.slider("Skor Minimum", 0, 100, 45, key="hs")

    signals = load_signals_range(days_back)
    if not signals:
        st.info(f"Tidak ada sinyal dalam {days_back} hari terakhir."); return

    filtered = [s for s in signals
                if ss(s.get("signal_type")) in tf
                and sf(s.get("composite_score")) >= min_s
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
            "Score":   sf(s.get("composite_score")),
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
    st.markdown('<div class="ds-page-title">Signal Performance</div>', unsafe_allow_html=True)
    st.markdown('<div class="ds-page-sub">Apakah sistem ini benar-benar bekerja?</div>', unsafe_allow_html=True)

    stats   = load_portfolio_stats()
    closed  = load_closed_positions(200)
    equity  = load_equity_curve()
    bt      = load_backtests()

    section("KPI UTAMA", "📈")
    if stats and stats.total_trades > 0:
        wr = sf(stats.win_rate)
        pf = sf(stats.profit_factor)
        c1,c2,c3,c4,c5,c6 = st.columns(6)
        with c1: st.markdown(tile("Total Trades", si(stats.total_trades)), unsafe_allow_html=True)
        with c2: st.markdown(tile("Win Rate", f"{wr:.1%}", "OK ✓" if wr>=0.55 else "< 55%", "up" if wr>=0.55 else "down"), unsafe_allow_html=True)
        with c3: st.markdown(tile("Profit Factor", f"{pf:.2f}", "OK ✓" if pf>1 else "< 1.0", "up" if pf>1 else "down"), unsafe_allow_html=True)
        with c4: st.markdown(tile("Expectancy", f"{sf(stats.expectancy):+.2f}%"), unsafe_allow_html=True)
        with c5: st.markdown(tile("Avg Gain", f"{sf(stats.avg_gain_pct):+.2f}%"), unsafe_allow_html=True)
        with c6: st.markdown(tile("Max Drawdown", f"{sf(stats.max_drawdown_pct):.1f}%"), unsafe_allow_html=True)
    else:
        st.info("Belum ada trade selesai — statistik akan muncul setelah posisi ditutup.")

    if equity:
        section("EQUITY CURVE", "💹")
        df_e = pd.DataFrame(equity)
        df_e["snapshot_date"] = pd.to_datetime(df_e["snapshot_date"])
        df_e["total_equity"]  = df_e["total_equity"].apply(sf)
        fig = go.Figure(go.Scatter(
            x=df_e["snapshot_date"], y=df_e["total_equity"],
            mode="lines", line=dict(color="#00c896", width=2),
            fill="tozeroy", fillcolor="rgba(0,200,150,.08)",
            hovertemplate="<b>%{x|%d %b}</b><br>Rp%{y:,.0f}<extra></extra>"))
        fig.update_layout(height=280, paper_bgcolor=DARK_BG, plot_bgcolor=PLOT_BG,
                          font=LAYOUT["font"], margin=LAYOUT["margin"], xaxis=LAYOUT["xaxis"],
                          yaxis=dict(gridcolor=GRID, tickformat=",.0f"))
        st.plotly_chart(fig, use_container_width=True)

    if closed:
        section("ANALISIS TRADE", "🔬")
        df_c = pd.DataFrame(closed)
        df_c["return_pct"] = df_c["return_pct"].apply(lambda x: sf(x)*100)
        df_c["net_pnl"]    = df_c["net_pnl"].apply(sf)

        c1,c2,c3 = st.columns(3)
        with c1:
            wins = len(df_c[df_c["net_pnl"]>0]); losses = len(df_c[df_c["net_pnl"]<=0])
            fig = go.Figure(go.Pie(labels=["Win","Loss"], values=[wins,losses],
                                  marker_colors=["#00c896","#f87171"], hole=0.6,
                                  textinfo="label+percent"))
            fig.update_layout(title="Win / Loss", height=250, **LAYOUT, showlegend=False)
            st.plotly_chart(fig, use_container_width=True)
        with c2:
            fig = px.histogram(df_c, x="return_pct", nbins=20,
                               title="Distribusi Return (%)",
                               color_discrete_sequence=["#60a5fa"])
            fig.update_layout(height=250, **LAYOUT)
            st.plotly_chart(fig, use_container_width=True)
        with c3:
            if "exit_date" in df_c.columns:
                df_c["month"] = pd.to_datetime(df_c["exit_date"], errors="coerce").dt.strftime("%Y-%m")
                mo = df_c.groupby("month")["net_pnl"].sum().reset_index()
                mo["color"] = mo["net_pnl"].apply(lambda x: "#00c896" if x>=0 else "#f87171")
                fig = go.Figure(go.Bar(x=mo["month"], y=mo["net_pnl"], marker_color=mo["color"],
                                       text=mo["net_pnl"].apply(lambda x: f"Rp{x:,.0f}"), textposition="outside"))
                fig.update_layout(title="PnL per Bulan", height=250, **LAYOUT)
                st.plotly_chart(fig, use_container_width=True)

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
        "portfolio":   page_portfolio,
        "health":      page_system_health,
    }
    page_map.get(page, page_home)()


if __name__ == "__main__":
    main()
