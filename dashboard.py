"""
DAILY SIGNAL — Streamlit Dashboard
Dashboard modern untuk monitoring sinyal, portfolio, dan performa.

Jalankan dengan:
    streamlit run dashboard.py
"""

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from datetime import date, timedelta, datetime
import os
import sys

# Tambahkan root directory ke path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Setup environment
from dotenv import load_dotenv
load_dotenv()

# ── Page Config ────────────────────────────────────────────────────
st.set_page_config(
    page_title="DAILY SIGNAL — BEI Scanner",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
    menu_items={
        "Get Help": None,
        "Report a bug": None,
        "About": "DAILY SIGNAL v1.0 — BEI Stock Scanner",
    },
)

# ── Custom CSS ──────────────────────────────────────────────────────
st.markdown("""
<style>
    .main { padding: 0rem 1rem; }
    .stMetric { background: #1a1a2e; border-radius: 8px; padding: 10px; }
    .metric-card {
        background: linear-gradient(135deg, #1a1a2e, #16213e);
        border: 1px solid #0f3460;
        border-radius: 10px;
        padding: 15px;
        margin: 5px;
    }
    .signal-strong-buy { color: #00ff88; font-weight: bold; }
    .signal-buy { color: #4eff91; }
    .signal-watchlist { color: #ffd700; }
    .signal-avoid { color: #ff4757; }
    .regime-bull { color: #00ff88; }
    .regime-sideways { color: #ffd700; }
    .regime-bear { color: #ff4757; }
    div[data-testid="stSidebarContent"] { background: #0f3460; }
    .block-container { padding-top: 1rem; padding-bottom: 1rem; }
</style>
""", unsafe_allow_html=True)


# ── DB Connection (cached) ─────────────────────────────────────────

@st.cache_resource
def get_db_client():
    try:
        from src.core.database import get_db
        return get_db()
    except Exception as e:
        st.error(f"❌ Koneksi database gagal: {e}")
        return None


# ── Data Loaders (cached 5 menit) ─────────────────────────────────

@st.cache_data(ttl=300)
def load_today_signals():
    try:
        db = get_db_client()
        if db is None:
            return []
        result = (
            db.table("signals")
            .select("*")
            .eq("signal_date", date.today().isoformat())
            .order("composite_score", desc=True)
            .execute()
        )
        return result.data or []
    except Exception:
        return []


@st.cache_data(ttl=300)
def load_market_regime():
    try:
        db = get_db_client()
        if db is None:
            return None
        result = (
            db.table("market_regimes")
            .select("*")
            .order("regime_date", desc=True)
            .limit(1)
            .execute()
        )
        return result.data[0] if result.data else None
    except Exception:
        return None


@st.cache_data(ttl=300)
def load_sector_rankings():
    try:
        db = get_db_client()
        if db is None:
            return []
        result = (
            db.table("sector_rankings")
            .select("*")
            .order("rank_date", desc=True)
            .order("rank_position")
            .limit(20)
            .execute()
        )
        return result.data or []
    except Exception:
        return []


@st.cache_data(ttl=300)
def load_portfolio_stats():
    try:
        from src.portfolio.tracker import get_portfolio_stats
        return get_portfolio_stats()
    except Exception:
        return None


@st.cache_data(ttl=60)
def load_open_positions():
    try:
        from src.portfolio.tracker import get_open_positions
        return get_open_positions()
    except Exception:
        return []


@st.cache_data(ttl=300)
def load_closed_positions(limit=50):
    try:
        from src.portfolio.tracker import get_closed_positions
        return get_closed_positions(limit)
    except Exception:
        return []


@st.cache_data(ttl=300)
def load_equity_curve():
    try:
        db = get_db_client()
        if db is None:
            return []
        result = (
            db.table("portfolio_snapshots")
            .select("snapshot_date, total_equity, unrealized_pnl, realized_pnl_ytd")
            .order("snapshot_date")
            .limit(365)
            .execute()
        )
        return result.data or []
    except Exception:
        return []


@st.cache_data(ttl=300)
def load_backtest_results():
    try:
        from src.backtest.engine import get_backtest_results
        return get_backtest_results(limit=100)
    except Exception:
        return []


@st.cache_data(ttl=600)
def load_system_logs(level="ERROR", limit=50):
    try:
        db = get_db_client()
        if db is None:
            return []
        result = (
            db.table("system_logs")
            .select("*")
            .gte("level", level)
            .order("log_time", desc=True)
            .limit(limit)
            .execute()
        )
        return result.data or []
    except Exception:
        return []


# ── Helper Functions ────────────────────────────────────────────────

def _regime_color(regime: str) -> str:
    return {"BULL": "#00ff88", "SIDEWAYS": "#ffd700", "BEAR": "#ff4757"}.get(regime, "#aaa")


def _signal_color(signal: str) -> str:
    return {
        "STRONG_BUY": "#00ff88",
        "BUY": "#4eff91",
        "WATCHLIST": "#ffd700",
        "AVOID": "#ff4757",
    }.get(signal, "#aaa")


def _signal_emoji(signal: str) -> str:
    return {
        "STRONG_BUY": "🚀",
        "BUY": "🟢",
        "WATCHLIST": "👀",
        "AVOID": "🔴",
    }.get(signal, "⚪")


# ── Sidebar ─────────────────────────────────────────────────────────

def render_sidebar():
    with st.sidebar:
        st.markdown("# 📈 DAILY SIGNAL")
        st.markdown("*BEI Stock Scanner*")
        st.divider()

        # Navigation
        page = st.radio(
            "📌 Menu",
            options=[
                "🏠 Overview",
                "🏛️ Market Regime",
                "📊 Top Signals",
                "🔍 All Signals",
                "💼 Portfolio",
                "📈 Performance",
                "🔬 Backtesting",
                "🏭 Sector Analysis",
                "⚙️ System Logs",
            ],
            label_visibility="collapsed",
        )

        st.divider()

        # Quick Stats
        regime = load_market_regime()
        if regime:
            color = _regime_color(regime["regime"])
            st.markdown(f"**Market:** <span style='color:{color}'>{regime['regime']}</span>", unsafe_allow_html=True)
            st.markdown(f"**IHSG:** Rp{regime.get('ihsg_close', 0):,.0f}")
            st.markdown(f"**RSI:** {regime.get('ihsg_rsi', 0):.1f}")

        st.divider()

        # Refresh button
        if st.button("🔄 Refresh Data", use_container_width=True):
            st.cache_data.clear()
            st.rerun()

        st.markdown(f"*Update: {datetime.now().strftime('%H:%M WIB')}*")

    return page


# ── Pages ─────────────────────────────────────────────────────────

def page_overview():
    st.title("🏠 Overview")
    st.markdown(f"*{date.today().strftime('%A, %d %B %Y')}*")

    # Market Regime card
    regime = load_market_regime()
    signals = load_today_signals()
    stats = load_portfolio_stats()

    # Top metrics row
    col1, col2, col3, col4, col5 = st.columns(5)

    with col1:
        if regime:
            color = _regime_color(regime["regime"])
            st.metric("Market Regime", regime["regime"])
        else:
            st.metric("Market Regime", "N/A")

    with col2:
        if regime:
            st.metric("IHSG", f"Rp{regime.get('ihsg_close', 0):,.0f}",
                      delta=f"{regime.get('change_5d_pct', 0):+.1f}% (5D)")
        else:
            st.metric("IHSG", "N/A")

    with col3:
        strong_buy = sum(1 for s in signals if s.get("signal_type") == "STRONG_BUY")
        buy = sum(1 for s in signals if s.get("signal_type") == "BUY")
        st.metric("Sinyal Hari Ini", f"{strong_buy + buy}", delta=f"{strong_buy} STRONG BUY")

    with col4:
        if stats:
            st.metric("Posisi Aktif", stats.num_open_positions,
                      delta=f"PnL: Rp{stats.total_unrealized_pnl:,.0f}")
        else:
            st.metric("Posisi Aktif", 0)

    with col5:
        if stats and stats.total_trades > 0:
            st.metric("Win Rate", f"{stats.win_rate:.1%}",
                      delta=f"{stats.total_trades} trades")
        else:
            st.metric("Win Rate", "N/A")

    st.divider()

    # Signal summary + Sector columns
    col_left, col_right = st.columns([2, 1])

    with col_left:
        st.subheader("🚀 Sinyal Terkuat Hari Ini")

        if not signals:
            st.info("Belum ada sinyal hari ini. Scan akan berjalan post-market.")
        else:
            top_signals = [s for s in signals if s.get("signal_type") in ("STRONG_BUY", "BUY")][:10]

            for sig in top_signals:
                ticker = sig.get("ticker", "").replace(".JK", "")
                signal_type = sig.get("signal_type", "")
                score = sig.get("composite_score", 0)
                close = sig.get("close_price", 0)
                rsi = sig.get("rsi", 0)
                vol_ratio = sig.get("volume_ratio", 1)
                rs = sig.get("rel_strength", 0)
                emoji = _signal_emoji(signal_type)

                with st.container():
                    c1, c2, c3, c4, c5 = st.columns([2, 2, 1, 1, 1])
                    c1.markdown(f"**{ticker}** {emoji}")
                    c2.markdown(f"Rp{close:,.0f}")
                    c3.markdown(f"Score: **{score:.0f}**")
                    c4.markdown(f"RSI: {rsi:.0f}")
                    c5.markdown(f"Vol: {vol_ratio:.1f}x")

    with col_right:
        st.subheader("🏭 Sector Rankings")
        sectors = load_sector_rankings()

        if sectors:
            for sr in sectors[:8]:
                trend_emoji = {"RISING": "⬆️", "STABLE": "➡️", "FALLING": "⬇️"}.get(sr.get("trend", ""), "➡️")
                rank = sr.get("rank_position", 0)
                sector_name = sr.get("sector", "")[:20]
                r5d = sr.get("return_5d", 0)
                color = "#00ff88" if r5d > 0 else "#ff4757"

                st.markdown(
                    f"#{rank} {trend_emoji} **{sector_name}** "
                    f"<span style='color:{color}'>{r5d:+.1f}%</span>",
                    unsafe_allow_html=True
                )
        else:
            st.info("Data sektor belum tersedia")


def page_market_regime():
    st.title("🏛️ Market Regime")

    regime = load_market_regime()
    if not regime:
        st.warning("Data market regime belum tersedia. Jalankan daily scan terlebih dahulu.")
        return

    # Regime badge
    r = regime["regime"]
    color = _regime_color(r)
    emoji = {"BULL": "📈", "SIDEWAYS": "↔️", "BEAR": "📉"}.get(r, "📊")

    st.markdown(
        f"<h2 style='color:{color}'>{emoji} {r} MARKET</h2>",
        unsafe_allow_html=True
    )
    st.markdown(f"*{regime.get('regime_reason', '')}*")

    st.divider()

    col1, col2, col3 = st.columns(3)
    col1.metric("IHSG Close", f"Rp{regime.get('ihsg_close', 0):,.0f}")
    col1.metric("IHSG EMA20", f"Rp{regime.get('ihsg_ema20', 0):,.0f}")
    col2.metric("RSI IHSG", f"{regime.get('ihsg_rsi', 0):.1f}")
    col2.metric("ADX IHSG", f"{regime.get('ihsg_adx', 0):.1f}")
    col3.metric("5D Change", f"{regime.get('change_5d_pct', 0):+.1f}%")

    # Market Breadth
    adv = regime.get("advance_count", 0)
    dec = regime.get("decline_count", 0)
    if adv + dec > 0:
        st.subheader("Market Breadth")
        total = adv + dec
        adv_pct = adv / total * 100 if total else 50

        col1, col2 = st.columns(2)
        col1.metric("Advance", adv, delta=f"{adv_pct:.0f}% saham naik")
        col2.metric("Decline", dec)

        # Breadth bar chart
        fig = go.Figure(go.Bar(
            x=["Advance", "Decline"],
            y=[adv, dec],
            marker_color=["#00ff88", "#ff4757"],
        ))
        fig.update_layout(
            height=200,
            margin=dict(l=0, r=0, t=20, b=0),
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
        )
        st.plotly_chart(fig, use_container_width=True)

    # Regime history
    try:
        db = get_db_client()
        if db:
            hist = (
                db.table("market_regimes")
                .select("regime_date, regime, ihsg_close, ihsg_rsi, change_5d_pct")
                .order("regime_date", desc=True)
                .limit(30)
                .execute()
            )
            if hist.data:
                df_hist = pd.DataFrame(hist.data)
                df_hist["regime_date"] = pd.to_datetime(df_hist["regime_date"])

                # Regime timeline
                st.subheader("Riwayat Regime (30 Hari)")
                regime_colors = {"BULL": "#00ff88", "SIDEWAYS": "#ffd700", "BEAR": "#ff4757"}
                df_hist["color"] = df_hist["regime"].map(regime_colors)

                fig2 = px.scatter(
                    df_hist,
                    x="regime_date",
                    y="ihsg_close",
                    color="regime",
                    color_discrete_map=regime_colors,
                    hover_data=["ihsg_rsi", "change_5d_pct"],
                )
                fig2.update_layout(
                    height=300,
                    paper_bgcolor="rgba(0,0,0,0)",
                    plot_bgcolor="rgba(13,17,23,1)",
                )
                st.plotly_chart(fig2, use_container_width=True)
    except Exception:
        pass


def page_top_signals():
    st.title("📊 Top Signals Hari Ini")

    signals = load_today_signals()

    if not signals:
        st.info("Belum ada sinyal hari ini.")
        return

    # Filter
    col1, col2 = st.columns(2)
    with col1:
        sig_filter = st.multiselect(
            "Filter Signal Type",
            options=["STRONG_BUY", "BUY", "WATCHLIST"],
            default=["STRONG_BUY", "BUY"],
        )
    with col2:
        min_score = st.slider("Minimum Score", 0, 100, 50)

    filtered = [
        s for s in signals
        if s.get("signal_type") in sig_filter and s.get("composite_score", 0) >= min_score
    ]

    st.markdown(f"**{len(filtered)} sinyal** memenuhi kriteria")

    for sig in filtered:
        ticker = sig.get("ticker", "").replace(".JK", "")
        signal_type = sig.get("signal_type", "")
        score = sig.get("composite_score", 0)
        close = sig.get("close_price", 0)
        entry = sig.get("entry_price", 0)
        sl = sig.get("stop_loss", 0)
        tp1 = sig.get("target_1", 0)
        tp2 = sig.get("target_2", 0)
        rr = sig.get("risk_reward", 0)
        rsi = sig.get("rsi", 0)
        adx = sig.get("adx", 0)
        vol_ratio = sig.get("volume_ratio", 1)
        rs = sig.get("rel_strength", 0)
        trend_score = sig.get("trend_score", 0)
        mom_score = sig.get("momentum_score", 0)
        vol_score = sig.get("volume_score", 0)
        str_score = sig.get("strength_score", 0)

        emoji = _signal_emoji(signal_type)
        color = _signal_color(signal_type)

        with st.expander(
            f"{emoji} **{ticker}** | Score: {score:.0f} | {signal_type} | Rp{close:,.0f}",
            expanded=signal_type == "STRONG_BUY",
        ):
            c1, c2, c3 = st.columns(3)

            with c1:
                st.markdown("**📊 Sinyal**")
                st.markdown(f"Type: **{signal_type}**")
                st.markdown(f"Score: **{score:.0f}/100**")
                st.progress(int(score) / 100)

            with c2:
                st.markdown("**💰 Risk Management**")
                sl_pct = (sl / entry - 1) * 100 if entry > 0 else 0
                tp1_pct = (tp1 / entry - 1) * 100 if entry > 0 else 0
                tp2_pct = (tp2 / entry - 1) * 100 if entry > 0 else 0
                st.markdown(f"Entry: Rp{entry:,.0f}")
                st.markdown(f"SL: Rp{sl:,.0f} ({sl_pct:.1f}%)")
                st.markdown(f"TP1: Rp{tp1:,.0f} (+{tp1_pct:.1f}%)")
                st.markdown(f"TP2: Rp{tp2:,.0f} (+{tp2_pct:.1f}%)")
                st.markdown(f"R/R: 1:{rr:.1f}")

            with c3:
                st.markdown("**📈 Indikator**")
                st.markdown(f"RSI: {rsi:.1f}")
                st.markdown(f"ADX: {adx:.1f}")
                st.markdown(f"Vol Ratio: {vol_ratio:.1f}x")
                st.markdown(f"RS vs IHSG: {rs:+.1f}%")

            # Score breakdown
            st.markdown("**Score Breakdown:**")
            score_data = pd.DataFrame({
                "Komponen": ["Trend", "Momentum", "Volume", "Strength"],
                "Score": [trend_score, mom_score, vol_score, str_score],
                "Max": [30, 25, 20, 15],
            })
            score_data["Pct"] = score_data["Score"] / score_data["Max"] * 100

            fig = px.bar(
                score_data, x="Komponen", y="Score",
                color="Pct",
                color_continuous_scale=["#ff4757", "#ffd700", "#00ff88"],
                range_color=[0, 100],
            )
            fig.update_layout(height=200, margin=dict(l=0, r=0, t=0, b=0),
                              paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
            st.plotly_chart(fig, use_container_width=True)


def page_portfolio():
    st.title("💼 Portfolio")

    stats = load_portfolio_stats()
    open_pos = load_open_positions()

    if stats:
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Posisi Aktif", stats.num_open_positions)
        col2.metric("Total Invested", f"Rp{stats.total_invested:,.0f}")
        col3.metric("Unrealized PnL", f"Rp{stats.total_unrealized_pnl:,.0f}",
                    delta=f"{stats.total_unrealized_pnl/stats.total_invested*100:.1f}%" if stats.total_invested > 0 else "0%")
        col4.metric("Realized PnL", f"Rp{stats.total_realized_pnl:,.0f}")

    st.divider()
    st.subheader("📂 Posisi Aktif")

    if not open_pos:
        st.info("Belum ada posisi aktif. Tambahkan posisi melalui form di bawah.")
    else:
        df_open = pd.DataFrame(open_pos)
        df_open["unrealized_pct_display"] = df_open["unrealized_pct"].apply(
            lambda x: f"{float(x)*100:+.2f}%" if x else "0%"
        )
        df_open["unrealized_pnl_display"] = df_open["unrealized_pnl"].apply(
            lambda x: f"Rp{float(x):,.0f}" if x else "Rp0"
        )

        cols_display = ["ticker", "entry_date", "entry_price", "current_price",
                        "shares", "unrealized_pnl_display", "unrealized_pct_display"]
        st.dataframe(
            df_open[[c for c in cols_display if c in df_open.columns]].rename(columns={
                "ticker": "Ticker",
                "entry_date": "Tanggal Masuk",
                "entry_price": "Entry",
                "current_price": "Harga Saat Ini",
                "shares": "Lot × 100",
                "unrealized_pnl_display": "Unrealized PnL",
                "unrealized_pct_display": "Return %",
            }),
            use_container_width=True,
            hide_index=True,
        )

    # Form buka posisi baru
    st.divider()
    st.subheader("➕ Buka Posisi Baru")

    with st.form("open_position_form"):
        c1, c2, c3 = st.columns(3)
        ticker_input = c1.text_input("Ticker (contoh: BBCA)", placeholder="BBCA")
        entry_price = c2.number_input("Harga Entry (Rp)", min_value=1, value=1000)
        shares = c3.number_input("Jumlah Saham (lot × 100)", min_value=100, step=100, value=100)

        c4, c5, c6 = st.columns(3)
        stop_loss = c4.number_input("Stop Loss (Rp)", min_value=1, value=900)
        target_1 = c5.number_input("Target 1 (Rp)", min_value=1, value=1100)
        target_2 = c6.number_input("Target 2 (Rp)", min_value=1, value=1200)

        notes = st.text_area("Catatan / Alasan Entry", placeholder="EMA20 breakout dengan volume spike...")

        submitted = st.form_submit_button("Buka Posisi", type="primary")

        if submitted:
            if ticker_input:
                from src.portfolio.tracker import open_position
                ticker_full = ticker_input.upper().strip() + ".JK"
                pos_id = open_position(
                    ticker=ticker_full,
                    entry_price=entry_price,
                    shares=shares,
                    stop_loss=stop_loss,
                    target_1=target_1,
                    target_2=target_2,
                    notes=notes,
                )
                if pos_id:
                    st.success(f"✓ Posisi {ticker_input.upper()} berhasil dibuka!")
                    st.cache_data.clear()
                else:
                    st.error("Gagal membuka posisi. Cek koneksi database.")
            else:
                st.warning("Isi ticker terlebih dahulu.")


def page_performance():
    st.title("📈 Performance")

    stats = load_portfolio_stats()
    equity_data = load_equity_curve()
    closed = load_closed_positions(100)

    if stats and stats.total_trades > 0:
        # Key metrics
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Total Trades", stats.total_trades)
        col2.metric("Win Rate", f"{stats.win_rate:.1%}")
        col3.metric("Profit Factor", f"{stats.profit_factor:.2f}")
        col4.metric("Expectancy", f"{stats.expectancy:+.2f}%")

        col5, col6, col7, col8 = st.columns(4)
        col5.metric("Avg Gain", f"{stats.avg_gain_pct:+.2f}%")
        col6.metric("Avg Loss", f"{stats.avg_loss_pct:.2f}%")
        col7.metric("Max Drawdown", f"{stats.max_drawdown_pct:.1f}%")
        col8.metric("Total PnL", f"Rp{stats.total_realized_pnl:,.0f}")

    # Equity Curve
    if equity_data:
        st.subheader("📈 Equity Curve")
        df_eq = pd.DataFrame(equity_data)
        df_eq["snapshot_date"] = pd.to_datetime(df_eq["snapshot_date"])

        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=df_eq["snapshot_date"],
            y=df_eq["total_equity"],
            mode="lines",
            name="Total Equity",
            line=dict(color="#00ff88", width=2),
            fill="tozeroy",
            fillcolor="rgba(0,255,136,0.1)",
        ))
        fig.update_layout(
            height=350,
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(13,17,23,1)",
            xaxis=dict(gridcolor="#1a1a2e"),
            yaxis=dict(gridcolor="#1a1a2e", tickformat=",.0f"),
        )
        st.plotly_chart(fig, use_container_width=True)

    # Trade history
    if closed:
        st.subheader("📋 Riwayat Trade")
        df_closed = pd.DataFrame(closed)
        df_closed["return_display"] = df_closed["return_pct"].apply(
            lambda x: f"{float(x)*100:+.2f}%"
        )
        df_closed["pnl_display"] = df_closed["net_pnl"].apply(
            lambda x: f"Rp{float(x):,.0f}"
        )

        show_cols = ["ticker", "entry_date", "exit_date", "entry_price", "exit_price",
                     "shares", "pnl_display", "return_display", "exit_reason", "holding_days"]
        st.dataframe(
            df_closed[[c for c in show_cols if c in df_closed.columns]].rename(columns={
                "ticker": "Ticker", "entry_date": "Entry", "exit_date": "Exit",
                "entry_price": "Harga Masuk", "exit_price": "Harga Keluar",
                "shares": "Saham", "pnl_display": "Net PnL",
                "return_display": "Return", "exit_reason": "Alasan", "holding_days": "Hari",
            }),
            use_container_width=True,
            hide_index=True,
        )


def page_backtesting():
    st.title("🔬 Backtesting")
    st.markdown("*Backtest deterministik menggunakan data historis BEI. Tidak ada AI, tidak ada look-ahead bias.*")

    bt_results = load_backtest_results()

    if not bt_results:
        st.info("Belum ada hasil backtest. Jalankan `python -m src.backtest.runner` untuk menjalankan backtest.")

    else:
        df_bt = pd.DataFrame(bt_results)
        df_bt["win_rate_display"] = df_bt["win_rate"].apply(lambda x: f"{float(x):.1%}")
        df_bt["sharpe_display"] = df_bt["sharpe_ratio"].apply(lambda x: f"{float(x):.2f}")

        # Summary stats
        col1, col2, col3 = st.columns(3)
        col1.metric("Saham di-backtest", len(df_bt))
        col2.metric("Avg Win Rate", f"{df_bt['win_rate'].astype(float).mean():.1%}")
        col3.metric("Avg Sharpe", f"{df_bt['sharpe_ratio'].astype(float).mean():.2f}")

        # Table
        show_cols = ["ticker", "period_start", "period_end", "total_trades",
                     "win_rate_display", "profit_factor", "max_drawdown",
                     "sharpe_display", "expectancy"]
        st.dataframe(
            df_bt[[c for c in show_cols if c in df_bt.columns]].rename(columns={
                "ticker": "Ticker", "period_start": "Mulai", "period_end": "Selesai",
                "total_trades": "Trades", "win_rate_display": "Win Rate",
                "profit_factor": "Profit Factor", "max_drawdown": "Max DD",
                "sharpe_display": "Sharpe", "expectancy": "Expectancy",
            }),
            use_container_width=True,
            hide_index=True,
        )


def page_sector_analysis():
    st.title("🏭 Sector Analysis")

    sectors = load_sector_rankings()

    if not sectors:
        st.info("Data sektor belum tersedia.")
        return

    df_sec = pd.DataFrame(sectors)

    # Bar chart sector performance
    fig = px.bar(
        df_sec.sort_values("composite_score", ascending=True),
        x="composite_score",
        y="sector",
        orientation="h",
        color="composite_score",
        color_continuous_scale=["#ff4757", "#ffd700", "#00ff88"],
        title="Composite Score per Sektor",
    )
    fig.update_layout(height=400, paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(13,17,23,1)")
    st.plotly_chart(fig, use_container_width=True)

    # Return breakdown
    fig2 = go.Figure()
    for period, col, color in [("1D", "return_1d", "#00ff88"), ("5D", "return_5d", "#4488ff"), ("20D", "return_20d", "#ffd700")]:
        if col in df_sec.columns:
            fig2.add_trace(go.Bar(
                name=period,
                x=df_sec["sector"],
                y=df_sec[col].astype(float),
                marker_color=color,
            ))
    fig2.update_layout(
        title="Return per Periode",
        barmode="group",
        height=350,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(13,17,23,1)",
    )
    st.plotly_chart(fig2, use_container_width=True)

    # Table
    st.dataframe(
        df_sec[["rank_position", "sector", "return_1d", "return_5d", "return_20d",
                "momentum_score", "breadth_score", "composite_score", "trend"]].rename(columns={
            "rank_position": "Rank", "sector": "Sektor", "return_1d": "1D%",
            "return_5d": "5D%", "return_20d": "20D%", "momentum_score": "Momentum",
            "breadth_score": "Breadth", "composite_score": "Score", "trend": "Trend",
        }),
        use_container_width=True,
        hide_index=True,
    )


def page_system_logs():
    st.title("⚙️ System Logs")

    col1, col2 = st.columns(2)
    with col1:
        log_level = st.selectbox("Level minimum", ["INFO", "WARNING", "ERROR", "CRITICAL"], index=1)
    with col2:
        log_limit = st.slider("Jumlah log", 10, 200, 50)

    logs = load_system_logs(level=log_level, limit=log_limit)

    if not logs:
        st.info("Tidak ada log yang sesuai filter.")
        return

    for log_entry in logs:
        level = log_entry.get("level", "INFO")
        msg = log_entry.get("message", "")
        module = log_entry.get("module", "")
        log_time = log_entry.get("log_time", "")[:19]

        level_colors = {
            "INFO": "🔵",
            "WARNING": "🟡",
            "ERROR": "🔴",
            "CRITICAL": "🚨",
        }
        emoji = level_colors.get(level, "⚪")

        with st.container():
            st.markdown(f"{emoji} `{log_time}` **[{module}]** {msg}")


# ── Main Router ─────────────────────────────────────────────────────

def main():
    page = render_sidebar()

    page_map = {
        "🏠 Overview": page_overview,
        "🏛️ Market Regime": page_market_regime,
        "📊 Top Signals": page_top_signals,
        "🔍 All Signals": page_top_signals,     # Same page, different filter default
        "💼 Portfolio": page_portfolio,
        "📈 Performance": page_performance,
        "🔬 Backtesting": page_backtesting,
        "🏭 Sector Analysis": page_sector_analysis,
        "⚙️ System Logs": page_system_logs,
    }

    render_fn = page_map.get(page, page_overview)
    render_fn()


if __name__ == "__main__":
    main()
