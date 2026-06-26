"""
DAILY SIGNAL — Streamlit Dashboard v2.0
8 halaman: Market Overview, Top Signals, Why This Signal,
Historical Signals, Signal Performance, Sector Rotation,
Portfolio, System Logs. Semua null-safe.
"""

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from datetime import date, timedelta, datetime
import os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dotenv import load_dotenv
load_dotenv()

# ── Page Config ─────────────────────────────────────────────────────
st.set_page_config(
    page_title="DAILY SIGNAL — BEI Scanner",
    page_icon="📈", layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
.main{padding:0 1.2rem}.block-container{padding-top:.8rem}
div[data-testid="stSidebarContent"]{background:#0d1b2a}
div[data-testid="metric-container"]{background:#1a2744;border:1px solid #1e3a5f;border-radius:10px;padding:14px 18px}
div[data-testid="metric-container"] label{color:#8899bb!important;font-size:.78rem}
div[data-testid="metric-container"] div[data-testid="stMetricValue"]{font-size:1.4rem;font-weight:700;color:#e8f0ff}
.badge-sb{background:#00c853;color:#000;padding:2px 10px;border-radius:12px;font-weight:700;font-size:.75rem}
.badge-buy{background:#69f0ae;color:#000;padding:2px 10px;border-radius:12px;font-weight:700;font-size:.75rem}
.badge-wl{background:#ffd740;color:#000;padding:2px 10px;border-radius:12px;font-weight:700;font-size:.75rem}
.badge-av{background:#ff5252;color:#fff;padding:2px 10px;border-radius:12px;font-weight:700;font-size:.75rem}
.section-title{font-size:1.1rem;font-weight:700;color:#aaccff;border-left:4px solid #4488ff;padding-left:10px;margin:16px 0 8px}
.info-box{background:#0d2137;border:1px solid #1e3a5f;border-radius:8px;padding:12px 16px;margin:6px 0;font-size:.9rem;color:#c8d8f0}
.info-box b{color:#7ab8ff}
.interp{color:#aaccee;font-size:.88rem;line-height:1.6}
.interp .good{color:#00ff88;font-weight:600}
.interp .warn{color:#ffd700;font-weight:600}
.interp .bad{color:#ff6b6b;font-weight:600}
.sbar-wrap{background:#1a2744;border-radius:6px;height:8px;margin-top:4px}
.sbar-fill{height:8px;border-radius:6px}
</style>
""", unsafe_allow_html=True)


# ════════ SAFE HELPERS ═══════════════════════════════════════════════

def sf(v, d=0.0):
    if v is None: return d
    try: return float(v)
    except: return d

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

def score_color(s):
    s = sf(s)
    if s >= 75: return "#00c853"
    if s >= 60: return "#69f0ae"
    if s >= 45: return "#ffd740"
    return "#ff5252"

def signal_badge(t):
    cls = {"STRONG_BUY":"badge-sb","BUY":"badge-buy","WATCHLIST":"badge-wl","AVOID":"badge-av"}.get(t,"badge-av")
    return f'<span class="{cls}">{t.replace("_"," ")}</span>'

def score_bar(s, mx=100):
    pct = min(sf(s)/mx*100, 100)
    c = score_color(sf(s) if mx==100 else sf(s)/mx*100)
    return f'<div class="sbar-wrap"><div class="sbar-fill" style="width:{pct:.0f}%;background:{c}"></div></div>'

def regime_emoji(r):
    return {"BULL":"🟢","SIDEWAYS":"🟡","BEAR":"🔴"}.get(r,"⚪")

def regime_color(r):
    return {"BULL":"#00ff88","SIDEWAYS":"#ffd700","BEAR":"#ff4757"}.get(r,"#aaa")

DARK_BG = "rgba(0,0,0,0)"
PLOT_BG = "rgba(13,17,23,1)"
GRID    = "#1a2744"
LAYOUT  = dict(paper_bgcolor=DARK_BG, plot_bgcolor=PLOT_BG,
               margin=dict(l=0,r=0,t=30,b=0),
               xaxis=dict(gridcolor=GRID), yaxis=dict(gridcolor=GRID))


# ════════ DB CONNECTION ══════════════════════════════════════════════

@st.cache_resource
def get_db():
    try:
        from src.core.database import get_db as _db
        return _db()
    except Exception as e:
        st.error(f"❌ Database: {e}")
        return None


# ════════ DATA LOADERS ═══════════════════════════════════════════════

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
                "trend_score,momentum_score,volume_score,strength_score,volatility_score")
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
              .select("regime_date,regime,ihsg_close,ihsg_rsi,change_5d_pct")\
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


# ════════ SIDEBAR ════════════════════════════════════════════════════

def render_sidebar():
    with st.sidebar:
        st.markdown("## 📈 DAILY SIGNAL")
        st.markdown("*SINYAL DARI LANGIT*")
        st.divider()
        page = st.radio("nav", [
            "🏠  Market Overview",
            "🚀  Top Signals",
            "🔍  Why This Signal?",
            "📅  Historical Signals",
            "📊  Signal Performance",
            "🏭  Sector Rotation",
            "💼  Portfolio",
            "⚙️  System Logs",
        ], label_visibility="collapsed")
        st.divider()
        regime = load_regime()
        if regime:
            r  = ss(regime.get("regime"), "N/A")
            e  = regime_emoji(r)
            c  = regime_color(r)
            st.markdown(f"**Regime** {e} <span style='color:{c};font-weight:700'>{r}</span>",
                        unsafe_allow_html=True)
            ihsg = sf(regime.get("ihsg_close"))
            chg5 = sf(regime.get("change_5d_pct"))
            st.markdown(f"**IHSG** Rp{ihsg:,.0f} `{chg5:+.1f}%`")
            st.markdown(f"**RSI** {sf(regime.get('ihsg_rsi')):.1f}")
        else:
            st.markdown("*Belum ada data*")
        st.divider()
        if st.button("🔄 Refresh", use_container_width=True):
            st.cache_data.clear(); st.rerun()
        st.caption(f"Update: {datetime.now().strftime('%H:%M WIB')}")
    return page


# ════════ PAGE 1 — MARKET OVERVIEW ══════════════════════════════════

def page_market_overview():
    st.title("🏠 Market Overview")
    st.caption(date.today().strftime("%A, %d %B %Y"))

    regime  = load_regime()
    signals = load_signals()
    sectors = load_sectors()

    if not regime:
        st.info("🕐 Belum ada data. Scan pertama berjalan ~17:30 WIB setiap hari bursa.")
    else:
        r    = ss(regime.get("regime"), "N/A")
        e    = regime_emoji(r)
        c    = regime_color(r)
        desc = {"BULL":  "Kondisi pasar mendukung — sinyal beli lebih terpercaya.",
                "SIDEWAYS": "Pasar konsolidasi — pilih saham selektif score tinggi.",
                "BEAR":  "Pasar melemah — kurangi eksposur, perketat stop loss."}.get(r, "")
        st.markdown(
            f"<div class='info-box'><b style='font-size:1.3rem'>{e} Market Regime: "
            f"<span style='color:{c}'>{r}</span></b><br>"
            f"<span class='interp'>{desc}</span></div>", unsafe_allow_html=True)

        c1,c2,c3,c4,c5,c6 = st.columns(6)
        ihsg = sf(regime.get("ihsg_close"))
        chg5 = sf(regime.get("change_5d_pct"))
        c1.metric("IHSG", f"Rp{ihsg:,.0f}", delta=f"{chg5:+.1f}% (5D)")
        c2.metric("RSI IHSG", f"{sf(regime.get('ihsg_rsi')):.1f}")
        c3.metric("ADX IHSG", f"{sf(regime.get('ihsg_adx')):.1f}")
        adv = si(regime.get("advance_count")); dec = si(regime.get("decline_count"))
        ad  = adv/dec if dec > 0 else 0
        c4.metric("A/D Ratio", f"{ad:.2f}", delta=f"{adv}↑ {dec}↓")
        if sectors:
            ts = ss(sectors[0].get("sector"),  "-")[:16]
            bs = ss(sectors[-1].get("sector"), "-")[:16]
            c5.metric("Sektor Terkuat",  ts, delta=f"{sf(sectors[0].get('return_5d')):+.1f}% 5D")
            c6.metric("Sektor Terlemah", bs, delta=f"{sf(sectors[-1].get('return_5d')):+.1f}% 5D")
        else:
            c5.metric("Sektor Terkuat",  "N/A"); c6.metric("Sektor Terlemah", "N/A")

        hist = load_regime_history(30)
        if len(hist) >= 5:
            df_h = pd.DataFrame(hist)
            df_h["regime_date"] = pd.to_datetime(df_h["regime_date"])
            df_h["ihsg_close"]  = df_h["ihsg_close"].apply(sf)
            df_h = df_h.sort_values("regime_date")
            rc = {"BULL":"#00c853","SIDEWAYS":"#ffd740","BEAR":"#ff5252"}
            df_h["mcolor"] = df_h["regime"].map(rc).fillna("#888")
            fig = go.Figure(go.Scatter(
                x=df_h["regime_date"], y=df_h["ihsg_close"],
                mode="lines+markers",
                line=dict(color="#4488ff", width=2),
                marker=dict(color=df_h["mcolor"].tolist(), size=9),
                hovertemplate="<b>%{x|%d %b}</b><br>IHSG: Rp%{y:,.0f}<extra></extra>",
            ))
            fig.update_layout(title="IHSG 30 Hari (🟢 Bull · 🟡 Sideways · 🔴 Bear)",
                              height=220, **LAYOUT)
            st.plotly_chart(fig, use_container_width=True)

    st.markdown("<div class='section-title'>📊 Ringkasan Sinyal Hari Ini</div>", unsafe_allow_html=True)
    sb = sum(1 for s in signals if s.get("signal_type")=="STRONG_BUY")
    bu = sum(1 for s in signals if s.get("signal_type")=="BUY")
    wl = sum(1 for s in signals if s.get("signal_type")=="WATCHLIST")
    av = sum(1 for s in signals if s.get("signal_type")=="AVOID")
    c1,c2,c3,c4 = st.columns(4)
    c1.metric("🚀 Strong Buy", sb); c2.metric("🟢 Buy", bu)
    c3.metric("👀 Watchlist", wl); c4.metric("🔴 Avoid", av)

    top3 = [s for s in signals if s.get("signal_type") in ("STRONG_BUY","BUY")][:3]
    if top3:
        st.markdown("<div class='section-title'>🏆 Top 3 Sinyal</div>", unsafe_allow_html=True)
        for sig in top3:
            ticker = ss(sig.get("ticker")).replace(".JK","")
            score  = sf(sig.get("composite_score"))
            stype  = ss(sig.get("signal_type"),"AVOID")
            col = st.columns([1.5,2.5,1.5,2,2])
            col[0].markdown(f"**{ticker}**")
            col[1].markdown(signal_badge(stype), unsafe_allow_html=True)
            col[2].markdown(f"Score **{score:.0f}**")
            col[3].markdown(fmt_rp(sig.get("close_price")))
            col[4].markdown(ss(sig.get("sector"),"—")[:18])
    elif not signals:
        st.info("Belum ada sinyal hari ini. Scan berjalan ~17:30 WIB setiap hari bursa.")


# ════════ PAGE 2 — TOP SIGNALS ══════════════════════════════════════

def page_top_signals():
    st.title("🚀 Top Signals")

    c1,c2,c3,c4 = st.columns([2,2,2,2])
    scan_date  = c1.date_input("Tanggal", value=date.today(), max_value=date.today())
    sig_filter = c2.multiselect("Type", ["STRONG_BUY","BUY","WATCHLIST","AVOID"],
                                default=["STRONG_BUY","BUY"])
    min_score  = c3.slider("Min Score", 0, 100, 45)
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
            "_st": stype, "_sc": score, "_tk": ticker,
            "Ticker": ticker,
            "Signal": stype.replace("_"," "),
            "Score":  score,
            "Sektor": ss(s.get("sector"),"—")[:18],
            "Harga":  sf(s.get("close_price")),
            "Vol x":  sf(s.get("volume_ratio"), 1.0),
            "RS%":    sf(s.get("rel_strength")),
            "Entry":  entry,
            "SL":     sf(s.get("stop_loss")),
            "TP1":    sf(s.get("target_1")),
            "R/R":    sf(s.get("risk_reward")),
        })

    if not rows:
        st.warning("Tidak ada sinyal yang memenuhi filter."); return

    st.caption(f"**{len(rows)}** sinyal · {scan_date}")

    # Header
    hdr = st.columns([0.4,1.2,2.5,1.8,1.1,0.9,0.9,1.2,1.2,1.2,0.8,0.7])
    for h,col in zip(["#","Ticker","Signal / Score","Sektor","Harga",
                       "Vol","RS%","Entry","SL","TP1","R/R",""],hdr):
        col.markdown(f"<span style='color:#8899bb;font-size:.75rem;font-weight:600'>{h}</span>",
                     unsafe_allow_html=True)
    st.markdown("<hr style='margin:3px 0;border-color:#1e3a5f'>", unsafe_allow_html=True)

    for idx, row in enumerate(rows, 1):
        score = row["_sc"]; stype = row["_st"]; ticker = row["_tk"]
        c = st.columns([0.4,1.2,2.5,1.8,1.1,0.9,0.9,1.2,1.2,1.2,0.8,0.7])
        c[0].markdown(f"<span style='color:#444;font-size:.82rem'>#{idx}</span>",
                      unsafe_allow_html=True)
        c[1].markdown(f"**{ticker}**")
        c[2].markdown(
            f"{signal_badge(stype)} "
            f"<b style='color:{score_color(score)}'>&nbsp;{score:.0f}</b><br>"
            f"{score_bar(score)}",
            unsafe_allow_html=True)
        c[3].markdown(f"<span style='font-size:.8rem;color:#8899bb'>{row['Sektor']}</span>",
                      unsafe_allow_html=True)
        c[4].markdown(f"Rp{row['Harga']:,.0f}")
        vr = row["Vol x"]; vc = "#00ff88" if vr>=1.5 else ("#ffd700" if vr>=1 else "#ff6b6b")
        c[5].markdown(f"<span style='color:{vc}'>{vr:.1f}x</span>", unsafe_allow_html=True)
        rs = row["RS%"]; rc = "#00ff88" if rs>0 else "#ff6b6b"
        c[6].markdown(f"<span style='color:{rc}'>{rs:+.1f}%</span>", unsafe_allow_html=True)
        c[7].markdown(f"Rp{row['Entry']:,.0f}")
        c[8].markdown(f"<span style='color:#ff6b6b'>Rp{row['SL']:,.0f}</span>",
                      unsafe_allow_html=True)
        c[9].markdown(f"<span style='color:#00ff88'>Rp{row['TP1']:,.0f}</span>",
                      unsafe_allow_html=True)
        c[10].markdown(f"1:{row['R/R']:.1f}")
        if c[11].button("Detail", key=f"d_{ticker}_{idx}"):
            st.session_state["sel_ticker"] = ticker
            st.session_state["sel_sig"]    = row
            st.rerun()
        st.markdown("<hr style='margin:2px 0;border-color:#0d1b2a'>", unsafe_allow_html=True)

    export = pd.DataFrame(rows).drop(columns=["_st","_sc","_tk"])
    st.download_button("⬇️ Download CSV",
        export.to_csv(index=False).encode(),
        file_name=f"daily_signal_{scan_date}.csv", mime="text/csv")


# ════════ PAGE 3 — WHY THIS SIGNAL? ═════════════════════════════════

def _interp_trend(score, close, ema20, ema50, ema200):
    if close > ema20 > ema50 > ema200 > 0:
        return '<span class="good">Full EMA alignment (close > EMA20 > EMA50 > EMA200)</span> — trend naik sangat kuat.'
    if close > ema20 > ema50 > 0:
        return '<span class="good">Harga di atas EMA20 & EMA50</span> — uptrend menengah, belum dikonfirmasi EMA200.'
    if close > ema20 > 0:
        return '<span class="warn">Hanya di atas EMA20</span> — trend awal, belum terkonfirmasi jangka menengah.'
    return '<span class="bad">Harga di bawah EMA20</span> — tidak dalam uptrend.'

def _interp_momentum(rsi, macd_hist):
    rsi_txt = (f'<span class="good">RSI {rsi:.0f} (sweet spot 40–65)</span>' if 40<=rsi<=65
               else f'<span class="warn">RSI {rsi:.0f} (oversold)</span>' if rsi<30
               else f'<span class="bad">RSI {rsi:.0f} (overbought)</span>')
    macd_txt = ('<span class="good">MACD Histogram positif</span> — momentum bullish.' if macd_hist>0
                else '<span class="bad">MACD Histogram negatif</span> — momentum belum bullish.')
    return f"{rsi_txt}. {macd_txt}"

def _interp_volume(vr):
    if vr >= 2.0: return f'<span class="good">Volume {vr:.1f}x rata-rata</span> — surge volume, akumulasi kuat.'
    if vr >= 1.5: return f'<span class="good">Volume {vr:.1f}x rata-rata</span> — di atas normal, konfirmasi valid.'
    if vr >= 1.0: return f'Volume {vr:.1f}x rata-rata — normal.'
    return f'<span class="bad">Volume {vr:.1f}x rata-rata</span> — di bawah normal, kurang terpercaya.'

def _interp_strength(adx, rs):
    adx_txt = (f'<span class="good">ADX {adx:.0f} — trend kuat</span>' if adx>=25
               else f'<span class="warn">ADX {adx:.0f} — trend lemah</span>')
    rs_txt  = (f'<span class="good">RS vs IHSG {rs:+.1f}% — outperform</span>' if rs>5
               else f'<span class="bad">RS vs IHSG {rs:+.1f}% — underperform</span>' if rs<0
               else f'RS vs IHSG {rs:+.1f}%')
    return f"{adx_txt}. {rs_txt}."

def _interp_volatility(atr_pct):
    if 1.0 <= atr_pct <= 4.0: return f'<span class="good">ATR {atr_pct:.1f}%</span> — volatilitas ideal untuk swing trading.'
    if atr_pct < 1.0:          return f'<span class="warn">ATR {atr_pct:.1f}%</span> — terlalu stabil, potensi profit terbatas.'
    return                       f'<span class="warn">ATR {atr_pct:.1f}%</span> — volatilitas tinggi, gunakan position size lebih kecil.'

def page_why_this_signal():
    st.title("🔍 Why This Signal?")

    signals = load_signals()
    actionable = [s for s in signals if s.get("signal_type") in ("STRONG_BUY","BUY","WATCHLIST")]
    if not actionable:
        st.info("Belum ada sinyal hari ini untuk dianalisis."); return

    tickers = [ss(s.get("ticker")).replace(".JK","") for s in actionable]
    def_idx = 0
    if "sel_ticker" in st.session_state and st.session_state["sel_ticker"] in tickers:
        def_idx = tickers.index(st.session_state["sel_ticker"])

    selected = st.selectbox("Pilih Ticker:", tickers, index=def_idx)
    sig = next((s for s in actionable if ss(s.get("ticker")).replace(".JK","")==selected), None)
    if not sig:
        st.warning("Data tidak ditemukan."); return

    stype  = ss(sig.get("signal_type"),"AVOID")
    score  = sf(sig.get("composite_score"))
    close  = sf(sig.get("close_price"))
    sector = ss(sig.get("sector"),"—")
    color  = score_color(score)

    c1,c2,c3 = st.columns([2,2,3])
    c1.markdown(f"## {selected}")
    c1.markdown(signal_badge(stype), unsafe_allow_html=True)
    c2.metric("Composite Score", f"{score:.1f}/100")
    c2.metric("Harga", fmt_rp(close))
    c3.metric("Sektor", sector)
    c3.metric("Tanggal", ss(sig.get("signal_date")))
    st.divider()

    # Score breakdown bar chart
    st.markdown("<div class='section-title'>📊 Score Breakdown</div>", unsafe_allow_html=True)
    comps = [
        ("Trend",      sf(sig.get("trend_score")),      30),
        ("Momentum",   sf(sig.get("momentum_score")),   25),
        ("Volume",     sf(sig.get("volume_score")),     20),
        ("Strength",   sf(sig.get("strength_score")),   15),
        ("Volatility", sf(sig.get("volatility_score")), 10),
    ]
    fig_g = go.Figure()
    for name, val, mx in comps:
        pct = val/mx*100 if mx>0 else 0
        fig_g.add_trace(go.Bar(name=name, x=[val], y=[name], orientation="h",
                               marker_color=score_color(pct),
                               text=f"{val:.0f}/{mx}", textposition="outside"))
        fig_g.add_trace(go.Bar(name=f"_{name}", x=[mx-val], y=[name], orientation="h",
                               marker_color="#1a2744", showlegend=False))
    fig_g.update_layout(barmode="stack", height=260,
                        margin=dict(l=0,r=60,t=10,b=0),
                        paper_bgcolor=DARK_BG, plot_bgcolor=DARK_BG, showlegend=False,
                        xaxis=dict(range=[0,36], showgrid=False, showticklabels=False),
                        yaxis=dict(autorange="reversed"))
    st.plotly_chart(fig_g, use_container_width=True)

    # Indicators
    st.markdown("<div class='section-title'>📈 Indikator Detail</div>", unsafe_allow_html=True)
    ema20  = sf(sig.get("ema20")); ema50  = sf(sig.get("ema50")); ema200 = sf(sig.get("ema200"))
    rsi    = sf(sig.get("rsi"), 50); macd_h = sf(sig.get("macd_hist"))
    adx    = sf(sig.get("adx")); vr = sf(sig.get("volume_ratio"), 1.0); rs = sf(sig.get("rel_strength"))
    atr    = sf(sig.get("atr")); atr_pct = atr/close*100 if close>0 else 0

    c1,c2,c3,c4 = st.columns(4)
    c1.metric("EMA 20",  fmt_rp(ema20))
    c1.metric("EMA 50",  fmt_rp(ema50))
    c1.metric("EMA 200", fmt_rp(ema200) if ema200>0 else "N/A")
    c2.metric("RSI (14)", f"{rsi:.1f}")
    c2.metric("MACD Hist", f"{macd_h:+.4f}")
    c2.metric("ADX (14)", f"{adx:.1f}")
    c3.metric("Volume Ratio", f"{vr:.2f}x")
    c3.metric("RS vs IHSG",   f"{rs:+.1f}%")
    c3.metric("ATR%",         f"{atr_pct:.2f}%")
    entry = sf(sig.get("entry_price")) or close
    sl    = sf(sig.get("stop_loss")); tp1 = sf(sig.get("target_1")); tp2 = sf(sig.get("target_2"))
    rr    = sf(sig.get("risk_reward"))
    c4.metric("Entry",   fmt_rp(entry))
    c4.metric("Stop Loss", fmt_rp(sl))
    c4.metric("Target 1",  fmt_rp(tp1))

    # Interpretations
    st.markdown("<div class='section-title'>💡 Interpretasi Otomatis</div>", unsafe_allow_html=True)
    interps = [
        ("📈 Trend",      _interp_trend(sf(sig.get("trend_score")), close, ema20, ema50, ema200)),
        ("⚡ Momentum",   _interp_momentum(rsi, macd_h)),
        ("📊 Volume",     _interp_volume(vr)),
        ("💪 Strength",   _interp_strength(adx, rs)),
        ("🌀 Volatility", _interp_volatility(atr_pct)),
    ]
    for title, text in interps:
        st.markdown(
            f"<div class='info-box'><b>{title}</b><br>"
            f"<span class='interp'>{text}</span></div>",
            unsafe_allow_html=True)

    # Risk
    st.markdown("<div class='section-title'>⚖️ Risk Management</div>", unsafe_allow_html=True)
    sl_pct  = (sl/entry-1)*100  if entry>0 else 0
    tp1_pct = (tp1/entry-1)*100 if entry>0 else 0
    tp2_pct = (tp2/entry-1)*100 if entry>0 else 0
    c1,c2,c3,c4 = st.columns(4)
    c1.metric("Entry",   fmt_rp(entry))
    c2.metric("Stop Loss",fmt_rp(sl),  delta=f"{sl_pct:.1f}%")
    c3.metric("Target 1", fmt_rp(tp1), delta=f"+{tp1_pct:.1f}%")
    c4.metric("Target 2", fmt_rp(tp2), delta=f"+{tp2_pct:.1f}%")
    st.markdown(
        f"<div class='info-box'><b>Risk/Reward: 1:{rr:.1f}</b> | "
        f"Risiko: {abs(sl_pct):.1f}% dari entry</div>",
        unsafe_allow_html=True)


# ════════ PAGE 4 — HISTORICAL SIGNALS ═══════════════════════════════

def page_historical_signals():
    st.title("📅 Historical Signals")

    c1,c2,c3,c4 = st.columns(4)
    days_back = c1.selectbox("Periode", [7,14,30,60,90], index=2)
    tf        = c2.multiselect("Type", ["STRONG_BUY","BUY","WATCHLIST"],
                               default=["STRONG_BUY","BUY"])
    search    = c3.text_input("Cari Ticker", placeholder="BBCA")
    min_s     = c4.slider("Min Score", 0, 100, 45, key="hs")

    signals = load_signals_range(days_back)
    if not signals:
        st.info(f"Tidak ada sinyal dalam {days_back} hari terakhir."); return

    filtered = [s for s in signals
                if ss(s.get("signal_type")) in tf
                and sf(s.get("composite_score")) >= min_s
                and (not search or search.upper() in ss(s.get("ticker")).upper())]

    st.caption(f"**{len(filtered)}** dari {len(signals)} sinyal · {days_back} hari terakhir")
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
            return {"STRONG BUY":"color:#00c853;font-weight:700","BUY":"color:#69f0ae;font-weight:700",
                    "WATCHLIST":"color:#ffd740"}.get(v,"")
        if isinstance(v, float):
            if v>=75: return "background-color:#003820;color:#00ff88"
            if v>=60: return "background-color:#002a1a;color:#69f0ae"
            if v>=45: return "background-color:#2a2000;color:#ffd740"
            return "background-color:#2a0000;color:#ff5252"
        return ""

    styled = (df.style
              .applymap(cs, subset=["Type","Score"])
              .format({"Score":"{:.1f}","Close":"Rp{:,.0f}","Entry":"Rp{:,.0f}",
                       "SL":"Rp{:,.0f}","TP1":"Rp{:,.0f}",
                       "R/R":"1:{:.1f}","RSI":"{:.1f}","Vol x":"{:.1f}x"}))
    st.dataframe(styled, use_container_width=True, hide_index=True, height=480)

    c1,c2 = st.columns(2)
    with c1:
        tc = df["Type"].value_counts()
        fig = go.Figure(go.Pie(labels=tc.index.tolist(), values=tc.values.tolist(),
                               marker_colors=["#00c853","#69f0ae","#ffd740","#ff5252"],
                               hole=0.4))
        fig.update_layout(title="Distribusi Tipe", height=260, paper_bgcolor=DARK_BG)
        st.plotly_chart(fig, use_container_width=True)
    with c2:
        sc = df["Sektor"].value_counts().head(8)
        fig = px.bar(x=sc.values, y=sc.index, orientation="h", title="Sinyal per Sektor",
                     color=sc.values, color_continuous_scale=["#1e3a5f","#00c853"])
        fig.update_layout(height=260, showlegend=False, coloraxis_showscale=False,
                          paper_bgcolor=DARK_BG, plot_bgcolor=PLOT_BG)
        st.plotly_chart(fig, use_container_width=True)

    st.download_button("⬇️ Download CSV", df.to_csv(index=False).encode(),
                       file_name=f"hist_signals_{days_back}d.csv", mime="text/csv")


# ════════ PAGE 5 — SIGNAL PERFORMANCE ═══════════════════════════════

def page_signal_performance():
    st.title("📊 Signal Performance")

    stats   = load_portfolio_stats()
    closed  = load_closed_positions(200)
    equity  = load_equity_curve()
    bt      = load_backtests()

    st.markdown("<div class='section-title'>📈 KPI Utama</div>", unsafe_allow_html=True)
    if stats and stats.total_trades > 0:
        wr = sf(stats.win_rate)
        pf = sf(stats.profit_factor)
        c1,c2,c3,c4,c5,c6 = st.columns(6)
        c1.metric("Total Trades",  si(stats.total_trades))
        c2.metric("Win Rate",      f"{wr:.1%}",  delta="OK ✓" if wr>=0.55 else "⚠ <55%")
        c3.metric("Profit Factor", f"{pf:.2f}",  delta="OK ✓" if pf>1 else "⚠ <1.0")
        c4.metric("Expectancy",    f"{sf(stats.expectancy):+.2f}%")
        c5.metric("Avg Gain",      f"{sf(stats.avg_gain_pct):+.2f}%")
        c6.metric("Max Drawdown",  f"{sf(stats.max_drawdown_pct):.1f}%")
    else:
        st.info("Belum ada trade selesai.")

    if equity:
        st.markdown("<div class='section-title'>📈 Equity Curve</div>", unsafe_allow_html=True)
        df_e = pd.DataFrame(equity)
        df_e["snapshot_date"] = pd.to_datetime(df_e["snapshot_date"])
        df_e["total_equity"]  = df_e["total_equity"].apply(sf)
        fig = go.Figure(go.Scatter(
            x=df_e["snapshot_date"], y=df_e["total_equity"],
            mode="lines", line=dict(color="#00ff88", width=2),
            fill="tozeroy", fillcolor="rgba(0,255,136,0.08)",
            hovertemplate="<b>%{x|%d %b}</b><br>Rp%{y:,.0f}<extra></extra>"))
        fig.update_layout(height=280, **LAYOUT, yaxis=dict(gridcolor=GRID, tickformat=",.0f"))
        st.plotly_chart(fig, use_container_width=True)

    if closed:
        st.markdown("<div class='section-title'>📊 Analisis Trade</div>", unsafe_allow_html=True)
        df_c = pd.DataFrame(closed)
        df_c["return_pct"] = df_c["return_pct"].apply(lambda x: sf(x)*100)
        df_c["net_pnl"]    = df_c["net_pnl"].apply(sf)

        c1,c2,c3 = st.columns(3)
        with c1:
            wins = len(df_c[df_c["net_pnl"]>0]); losses = len(df_c[df_c["net_pnl"]<=0])
            fig = go.Figure(go.Pie(labels=["Win","Loss"], values=[wins,losses],
                                  marker_colors=["#00c853","#ff5252"], hole=0.5,
                                  textinfo="label+percent"))
            fig.update_layout(title="Win / Loss", height=250,
                              paper_bgcolor=DARK_BG, showlegend=False)
            st.plotly_chart(fig, use_container_width=True)
        with c2:
            fig = px.histogram(df_c, x="return_pct", nbins=20,
                               title="Distribusi Return (%)",
                               color_discrete_sequence=["#4488ff"])
            fig.update_layout(height=250, paper_bgcolor=DARK_BG, plot_bgcolor=PLOT_BG)
            st.plotly_chart(fig, use_container_width=True)
        with c3:
            if "exit_date" in df_c.columns:
                df_c["month"] = pd.to_datetime(df_c["exit_date"], errors="coerce")\
                                  .dt.strftime("%Y-%m")
                mo = df_c.groupby("month")["net_pnl"].sum().reset_index()
                mo["color"] = mo["net_pnl"].apply(lambda x: "#00c853" if x>=0 else "#ff5252")
                fig = go.Figure(go.Bar(x=mo["month"], y=mo["net_pnl"],
                                       marker_color=mo["color"],
                                       text=mo["net_pnl"].apply(lambda x: f"Rp{x:,.0f}"),
                                       textposition="outside"))
                fig.update_layout(title="PnL per Bulan", height=250,
                                  paper_bgcolor=DARK_BG, plot_bgcolor=PLOT_BG)
                st.plotly_chart(fig, use_container_width=True)

    if bt:
        st.markdown("<div class='section-title'>🔬 Backtest Summary</div>", unsafe_allow_html=True)
        df_bt = pd.DataFrame(bt)
        for col in ["win_rate","profit_factor","sharpe_ratio","max_drawdown","expectancy"]:
            if col in df_bt.columns:
                df_bt[col] = df_bt[col].apply(sf)
        c1,c2,c3 = st.columns(3)
        c1.metric("Saham Dibacktest", len(df_bt))
        c2.metric("Avg Win Rate",     f"{df_bt['win_rate'].mean():.1%}")
        c3.metric("Avg Sharpe",       f"{df_bt['sharpe_ratio'].mean():.2f}")

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


# ════════ PAGE 6 — SECTOR ROTATION ══════════════════════════════════

def page_sector_rotation():
    st.title("🏭 Sector Rotation")
    sectors = load_sectors()
    if not sectors:
        st.info("Data sektor belum tersedia. Tersedia setelah scan pertama."); return

    df = pd.DataFrame(sectors)
    for col in ["composite_score","return_1d","return_5d","return_20d",
                "momentum_score","breadth_score","rank_position"]:
        if col in df.columns:
            df[col] = df[col].apply(sf)

    df = df.sort_values("composite_score", ascending=False).reset_index(drop=True)

    st.markdown("<div class='section-title'>🏆 Sector Leaderboard</div>", unsafe_allow_html=True)
    for i, row in df.iterrows():
        rank   = i+1
        sector = ss(row.get("sector"),"—")
        score  = sf(row.get("composite_score"))
        r5d    = sf(row.get("return_5d")); r1d = sf(row.get("return_1d"))
        trend  = ss(row.get("trend"),"STABLE")
        breadth= sf(row.get("breadth_score"))
        te     = {"RISING":"⬆️","STABLE":"➡️","FALLING":"⬇️"}.get(trend,"➡️")
        medal  = {1:"🥇",2:"🥈",3:"🥉"}.get(rank,f"#{rank}")
        c1,c2,c3,c4,c5,c6 = st.columns([0.5,2.5,3,1,1,1])
        c1.markdown(f"**{medal}**")
        c2.markdown(f"**{sector}** {te}")
        c3.markdown(
            f'{score_bar(score)}'
            f'<span style="color:{score_color(score)};font-size:.8rem"> {score:.1f}</span>',
            unsafe_allow_html=True)
        r5c = "#00ff88" if r5d>0 else "#ff5252"
        r1c = "#00ff88" if r1d>0 else "#ff5252"
        c4.markdown(f"<span style='color:{r5c}'>{r5d:+.1f}% 5D</span>", unsafe_allow_html=True)
        c5.markdown(f"<span style='color:{r1c}'>{r1d:+.1f}% 1D</span>", unsafe_allow_html=True)
        c6.markdown(f"Breadth {breadth:.0f}%")

    st.markdown("<hr style='border-color:#1e3a5f'>", unsafe_allow_html=True)

    c1,c2 = st.columns(2)
    with c1:
        fig = go.Figure(go.Bar(
            x=df["composite_score"], y=df["sector"], orientation="h",
            marker_color=[score_color(s) for s in df["composite_score"]],
            text=df["composite_score"].apply(lambda x: f"{x:.1f}"),
            textposition="outside"))
        fig.update_layout(title="Composite Score", height=380,
                          margin=dict(l=0,r=60,t=30,b=0),
                          paper_bgcolor=DARK_BG, plot_bgcolor=PLOT_BG,
                          xaxis=dict(range=[0,110], showgrid=False),
                          yaxis=dict(autorange="reversed"))
        st.plotly_chart(fig, use_container_width=True)
    with c2:
        if all(c in df.columns for c in ["return_1d","return_5d","return_20d"]):
            mat = df[["return_1d","return_5d","return_20d"]].values
            fig = go.Figure(go.Heatmap(
                z=mat, x=["1D","5D","20D"], y=df["sector"].tolist(),
                colorscale=[[0,"#ff5252"],[0.5,"#1a2744"],[1,"#00c853"]], zmid=0,
                text=[[f"{v:+.1f}%" for v in row] for row in mat],
                texttemplate="%{text}", textfont=dict(size=11)))
            fig.update_layout(title="Return Heatmap", height=380,
                              margin=dict(l=0,r=0,t=30,b=0),
                              paper_bgcolor=DARK_BG)
            st.plotly_chart(fig, use_container_width=True)

    if "momentum_score" in df.columns and "breadth_score" in df.columns:
        st.markdown("<div class='section-title'>📡 Momentum vs Breadth</div>", unsafe_allow_html=True)
        fig = px.scatter(df, x="momentum_score", y="breadth_score",
                         size="composite_score", color="composite_score",
                         color_continuous_scale=["#ff5252","#ffd740","#00c853"],
                         text="sector",
                         title="Momentum Score vs Breadth Score")
        fig.update_traces(textposition="top center", textfont_size=10)
        fig.update_layout(height=380, paper_bgcolor=DARK_BG, plot_bgcolor=PLOT_BG,
                          coloraxis_showscale=False)
        st.plotly_chart(fig, use_container_width=True)


# ════════ PAGE 7 — PORTFOLIO ═════════════════════════════════════════

def page_portfolio():
    st.title("💼 Portfolio")
    stats   = load_portfolio_stats()
    open_pos = load_open_positions()

    if stats:
        c1,c2,c3,c4,c5 = st.columns(5)
        c1.metric("Posisi Aktif", si(stats.num_open_positions))
        c2.metric("Total Invested", fmt_rp(stats.total_invested))
        inv  = sf(stats.total_invested); upnl = sf(stats.total_unrealized_pnl)
        dpct = f"{upnl/inv*100:.1f}%" if inv>0 else "0%"
        c3.metric("Unrealized PnL", fmt_rp(upnl), delta=dpct)
        c4.metric("Realized PnL",   fmt_rp(stats.total_realized_pnl))
        c5.metric("Win Rate", f"{sf(stats.win_rate):.1%}" if stats.total_trades>0 else "N/A")

    st.divider()
    st.subheader("📂 Posisi Aktif")
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
                return "color:#00c853;font-weight:700" if v>=0 else "color:#ff5252;font-weight:700"
            return ""
        styled = df.style.applymap(cpnl, subset=["Unrealized","Return %"])\
                         .format({"Entry":"Rp{:,.0f}","Harga Kini":"Rp{:,.0f}",
                                  "Unrealized":"Rp{:,.0f}","Return %":"{:+.2f}%"})
        st.dataframe(styled, use_container_width=True, hide_index=True)

    st.divider()
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


# ════════ PAGE 8 — SYSTEM LOGS ══════════════════════════════════════

def page_system_logs():
    st.title("⚙️ System Logs")
    c1,c2 = st.columns(2)
    lim   = c1.slider("Jumlah", 20, 200, 50)
    lvl   = c2.multiselect("Level",
                           ["DEBUG","INFO","WARNING","ERROR","CRITICAL"],
                           default=["WARNING","ERROR","CRITICAL"])
    logs = load_logs(lim)
    filtered = [l for l in logs if ss(l.get("level")) in lvl]
    if not filtered:
        st.info("Tidak ada log."); return
    icons  = {"DEBUG":"🔵","INFO":"⚪","WARNING":"🟡","ERROR":"🔴","CRITICAL":"🚨"}
    colors = {"DEBUG":"#556","INFO":"#8899bb","WARNING":"#ffd740",
              "ERROR":"#ff6b6b","CRITICAL":"#ff5252"}
    for e in filtered:
        lv  = ss(e.get("level"), "INFO")
        lvc = colors.get(lv, "#aaa")
        lvi = icons.get(lv, "⚪")
        lt  = ss(e.get("log_time"))[:19]
        mod = ss(e.get("module"))
        msg = ss(e.get("message"))
        st.markdown(
            f"{lvi} `{lt}` "
            f"<span style='color:#4488ff;font-size:.8rem'>[{mod}]</span> "
            f"<span style='color:{lvc}'>{msg}</span>",
            unsafe_allow_html=True)


# ════════ MAIN ═══════════════════════════════════════════════════════

def main():
    page = render_sidebar()
    {
        "🏠  Market Overview":    page_market_overview,
        "🚀  Top Signals":        page_top_signals,
        "🔍  Why This Signal?":   page_why_this_signal,
        "📅  Historical Signals": page_historical_signals,
        "📊  Signal Performance": page_signal_performance,
        "🏭  Sector Rotation":    page_sector_rotation,
        "💼  Portfolio":          page_portfolio,
        "⚙️  System Logs":        page_system_logs,
    }.get(page, page_market_overview)()

if __name__ == "__main__":
    main()
