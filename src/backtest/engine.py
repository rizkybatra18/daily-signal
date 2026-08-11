"""
DAILY SIGNAL — Backtesting Framework
Walk-forward backtest: deterministic, reproducible, tanpa look-ahead
bias, dengan transaction cost dan model eksekusi yang realistis.

═══════════════════════════════════════════════════════════════════
AUDIT NOTE (Backtest Audit — lihat AUDIT_REPORT_v2.md untuk detail)
═══════════════════════════════════════════════════════════════════
Tidak ditemukan data leakage / look-ahead bias literal (semua indikator
memakai .ewm()/.rolling()/.shift() yang murni backward-looking).

TAPI ditemukan 3 masalah REALISME EKSEKUSI yang sudah diperbaiki:

  1. ENTRY DI HARI YANG SAMA DENGAN SINYAL — versi sebelumnya "membeli"
     tepat di harga close hari sinyal dihasilkan. Di dunia nyata, sinyal
     baru dikirim ~17:30 WIB SETELAH market tutup; eksekusi paling cepat
     adalah open hari BERIKUTNYA. Diperbaiki: entry kini di open H+1.
  2. RESOLUSI TP/SL OPTIMISTIS — jika dalam satu candle SL dan TP1
     sama-sama tersentuh, versi lama SELALU menganggap TP1 duluan
     (bias optimis, win rate ter-inflate). Diperbaiki: SL diperiksa
     LEBIH DULU (asumsi konservatif standar dalam backtesting).
  3. SCORING BACKTEST BEDA DENGAN SCORING LIVE — versi lama memakai
     skala 0-60 dengan bobot berbeda dari composite scoring live
     (0-100). Akibatnya backtest sebenarnya memvalidasi strategi yang
     BERBEDA dari yang benar-benar dipakai live. Diperbaiki (poin 3,
     LALU disempurnakan lagi di poin 4 di bawah — bobot terkini lihat
     CompositeScore di ta_engine.py, BUKAN angka statis di sini, karena
     sudah 2x berubah sejak poin ini ditulis).

  4. [v2, 2026-08] "MENIRU PERSIS" DI POIN 3 MASIH RAPUH — perbaikan
     poin 3 di atas MASIH berupa duplikat manual (_score_row() menyalin
     ulang formula ta_engine.py sebagai kode terpisah). Terbukti rapuh:
     begitu trend_score dipotong 30->20 & flow_score baru ditambahkan
     di ta_engine.py (lihat AUDIT CompositeScore), _score_row() di sini
     TIDAK ikut berubah kalau tidak disentuh manual -- persis skenario
     yang bikin poin 3 perlu diperbaiki dari awal. Diperbaiki BENAR
     kali ini: _score_row() sekarang membangun StockAnalysis dari row
     lalu MEMANGGIL LANGSUNG _score_trend/_score_momentum/_score_volume/
     _score_strength/_score_volatility/_score_flow dari ta_engine.py --
     bukan menyalin formulanya lagi. Konsekuensinya: kalau ta_engine.py
     berubah lagi nanti, backtest OTOMATIS ikut berubah, tidak perlu
     diingat-ingat untuk disinkronkan manual.

  5. [v2.5.0, 2026-08] TP2 TIDAK PERNAH DISIMULASIKAN — _simulate_trade()
     SEBELUMNYA cuma cek TP1 & SL, padahal settings.atr_tp2_multiplier
     ADA dan DIPAKAI live tracking (signal_evaluator.py::_walk_price_path,
     urutan SL->TP2->TP1). Backtest jadi menguji strategi single-target
     (exit penuh di TP1) yang beda dari yang dilacak live. Diperbaiki:
     tp2 dihitung & urutan cek disamakan persis dengan _walk_price_path.

Metrik output:
    Win Rate, Profit Factor, Expectancy, Sharpe, Sortino,
    Calmar, Max Drawdown, Avg Gain, Avg Loss
"""

import pandas as pd
import numpy as np
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional

from src.core.config import settings
from src.core.logger import get_logger
from src.core.database import get_db
from src.signals.ta_engine import (
    calc_rsi, calc_ema, calc_macd, calc_atr, calc_adx, calc_bollinger,
    calc_mansfield_rs, calc_obv, calc_obv_slope_pct, calc_ad_line, calc_cmf,
    calc_mfi, calc_vsa_signal, _safe_detect_trend_structure,
    StockAnalysis, TrendIndicators, MomentumIndicators, StrengthIndicators,
    VolumeIndicators, VolatilityIndicators, FlowIndicators,
    _score_trend, _score_momentum, _score_volume, _score_strength,
    _score_volatility, _score_flow,
)

log = get_logger("backtest")

# ── Constants ────────────────────────────────────────────────────────
BUY_COMMISSION = 0.0019    # 0.15% broker + 0.04% levy
SELL_COMMISSION = 0.0029   # 0.15% broker + 0.04% levy + 0.10% PPh Final
FORWARD_CANDLES = 10       # Simulasi 10 hari ke depan dari entry
MIN_WARMUP_ROWS = 60       # Minimal rows sebelum mulai simulasi


@dataclass
class TradeResult:
    date: str
    ticker: str
    entry: float
    exit_price: float
    atr: float
    tp1: float
    tp2: float              # BARU -- lihat AUDIT parity TP2 di _simulate_trade
    sl: float
    win: bool
    exit_reason: str       # TP1/TP2/SL/TIMEOUT/INVALID/NO_NEXT_BAR
    exit_candle: int
    gross_pnl_pct: float
    net_pnl_pct: float     # Setelah komisi
    max_gain_pct: float
    conditions_met: int


@dataclass
class BacktestResult:
    ticker: str
    strategy_name: str = "DAILY_SIGNAL_V1"
    period_start: str = ""
    period_end: str = ""
    # Trade Stats
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    win_rate: float = 0.0
    # Return Metrics
    profit_factor: float = 0.0
    expectancy: float = 0.0
    avg_gain_pct: float = 0.0
    avg_loss_pct: float = 0.0
    max_gain_pct: float = 0.0
    max_loss_pct: float = 0.0
    total_return_pct: float = 0.0
    # Risk Metrics
    max_drawdown_pct: float = 0.0
    sharpe_ratio: float = 0.0
    sortino_ratio: float = 0.0
    calmar_ratio: float = 0.0
    # Trade Details
    trades: list = field(default_factory=list)
    # Status
    passed: bool = False
    fail_reason: str = ""


def _add_indicators(df: pd.DataFrame, ihsg_close: Optional[pd.Series] = None) -> pd.DataFrame:
    """
    Hitung semua indikator yang dipakai _score_row(), selaras dengan
    yang dipakai composite scoring live (ta_engine.analyze_stock).
    PENTING: semua backward-looking (.ewm/.rolling/.shift) — tidak ada
    look-ahead bias.
    """
    df = df.copy()
    close = df["close"]
    volume = df["volume"]

    # Trend
    df["ema20"] = calc_ema(close, 20)
    df["ema50"] = calc_ema(close, 50)
    df["ema200"] = calc_ema(close, 200).fillna(0)  # 0 = belum cukup data, netral (sama seperti live)

    # Momentum
    df["rsi"] = calc_rsi(close, settings.rsi_period)
    df["rsi_prev"] = df["rsi"].shift(1).fillna(df["rsi"])
    macd_line, macd_sig, macd_hist = calc_macd(close)
    df["macd_line"] = macd_line
    df["macd_signal"] = macd_sig
    df["macd_hist"] = macd_hist
    df["macd_hist_prev"] = macd_hist.shift(1).fillna(0)
    df["macd_cross"] = np.where(
        (df["macd_hist_prev"] < 0) & (df["macd_hist"] > 0), "GOLDEN",
        np.where((df["macd_hist_prev"] > 0) & (df["macd_hist"] < 0), "DEATH", "NONE"),
    )

    # Strength
    adx, plus_di, minus_di = calc_adx(df, settings.adx_period)
    df["adx"] = adx
    df["plus_di"] = plus_di
    df["minus_di"] = minus_di
    if ihsg_close is not None and not ihsg_close.empty:
        df["rel_strength"] = calc_mansfield_rs(close, ihsg_close, period=20).fillna(0)
    else:
        df["rel_strength"] = 0.0

    # Volume
    df["vol_ma20"] = volume.rolling(20, min_periods=10).mean()
    df["vol_ma5"] = volume.rolling(5, min_periods=3).mean()
    df["volume_trend"] = "NORMAL"
    vol_ratio_5_20 = df["vol_ma5"] / df["vol_ma20"].replace(0, np.nan)
    df.loc[vol_ratio_5_20 > 1.8, "volume_trend"] = "SURGE"
    df.loc[(vol_ratio_5_20 > 1.2) & (vol_ratio_5_20 <= 1.8), "volume_trend"] = "INCREASING"
    df.loc[vol_ratio_5_20 < 0.7, "volume_trend"] = "DECLINING"

    # Volatility
    df["atr"] = calc_atr(df, settings.atr_period)
    df["atr_pct"] = (df["atr"] / close.replace(0, np.nan) * 100).fillna(0)
    bb_up, bb_mid, bb_lo = calc_bollinger(close, 20)
    df["bb_upper"] = bb_up
    df["bb_mid"] = bb_mid
    df["bb_lower"] = bb_lo
    bb_range = (bb_up - bb_lo).replace(0, np.nan)
    df["bb_position"] = ((close - bb_lo) / bb_range).fillna(0.5)
    df["bb_width"] = (bb_range / bb_mid.replace(0, np.nan)).fillna(1.0)
    df["bb_squeeze"] = df["bb_width"] < 0.05

    # Flow (BARU) -- pakai fungsi ASLI dari ta_engine.py (bukan reimplement)
    # supaya definisinya dijamin sama persis dengan live, sama seperti
    # indikator lain di atas.
    df["obv"] = calc_obv(close, volume)
    df["obv_slope_pct"] = calc_obv_slope_pct(df["obv"], period=10)
    df["ad_line"] = calc_ad_line(df)
    df["cmf"] = calc_cmf(df, period=20)
    df["mfi"] = calc_mfi(df, period=14)
    df["vsa_signal"] = calc_vsa_signal(df, period=20)

    # Trend Structure (v2.5.0) -- dari pattern_engine.py, SAMA PERSIS
    # dengan yang dipakai live (_safe_detect_trend_structure). TIDAK
    # bisa divectorize (perlu deteksi swing-pivot ulang tiap titik
    # waktu), jadi dihitung per-baris dengan window 120 bar TERAKHIR
    # s.d. baris itu saja (bukan seluruh df) -- window terbatas supaya
    # PASTI TIDAK ADA LOOKAHEAD (prinsip inti sistem ini, lihat AUDIT
    # no-lookahead di CHANGELOG) sekaligus tetap murah dihitung untuk
    # backtest ribuan baris. 120 = 2x lookback default detect_trend_
    # structure (60) + buffer untuk pivot_window.
    structures = [None] * len(df)
    for i in range(len(df)):
        window = df.iloc[max(0, i - 119):i + 1]
        structures[i] = _safe_detect_trend_structure(window)
    df["trend_structure"] = structures

    return df.dropna(subset=["rsi", "ema20", "atr"])


def _score_row(row: pd.Series) -> tuple[float, int]:
    """
    Hitung composite score untuk satu baris (satu hari) — SKALA 0-100.

    [v2, 2026-08] TIDAK LAGI duplikat formula manual (lihat AUDIT NOTE
    poin 4 di atas modul ini). Fungsi ini membangun StockAnalysis dari
    kolom row (hasil _add_indicators, semua backward-looking) lalu
    MEMANGGIL LANGSUNG _score_trend/_score_momentum/_score_volume/
    _score_strength/_score_volatility/_score_flow dari ta_engine.py --
    sumber tunggal kebenaran (single source of truth) untuk kedua
    live scanner dan backtest.

    Return: (score 0-100, conditions_met) — signature TIDAK berubah
    dari versi sebelumnya (dipakai test_backtest_no_lookahead).
    conditions_met adalah bookkeeping KHUSUS BACKTEST (bukan bagian
    dari scoring live) -- hitung kasar berapa "kondisi kuat" terpenuhi,
    dipakai untuk kolom conditions_met di TradeResult saja.
    """
    close = row.get("close", 0) or 0
    ema20 = row.get("ema20", 0) or 0
    ema50 = row.get("ema50", 0) or 0
    ema200 = row.get("ema200", 0) or 0
    price_vs_ema20 = ((close / ema20) - 1) * 100 if ema20 > 0 else 0

    vol_ma20 = row.get("vol_ma20", 0) or 0
    vol = row.get("volume", 0) or 0
    volume_ratio = (vol / vol_ma20) if vol_ma20 > 0 else 1.0

    plus_di = row.get("plus_di", 0) or 0
    minus_di = row.get("minus_di", 0) or 0
    adx = row.get("adx", 0) or 0

    analysis = StockAnalysis(
        trend=TrendIndicators(
            ema20=ema20, ema50=ema50, ema200=ema200,
            price_vs_ema20=price_vs_ema20,
            structure=row.get("trend_structure"),
        ),
        momentum=MomentumIndicators(
            rsi=row.get("rsi", 50) or 50,
            rsi_prev=row.get("rsi_prev", 50) or 50,
            macd_line=row.get("macd_line", 0) or 0,
            macd_signal=row.get("macd_signal", 0) or 0,
            macd_hist=row.get("macd_hist", 0) or 0,
            macd_hist_prev=row.get("macd_hist_prev", 0) or 0,
            macd_cross=row.get("macd_cross", "NONE"),
        ),
        strength=StrengthIndicators(
            adx=adx, plus_di=plus_di, minus_di=minus_di,
            rel_strength=row.get("rel_strength", 0) or 0,
        ),
        volume=VolumeIndicators(
            volume_ratio=volume_ratio,
            volume_trend=row.get("volume_trend", "NORMAL"),
        ),
        volatility=VolatilityIndicators(
            atr_pct=row.get("atr_pct", 0) or 0,
            bb_position=row.get("bb_position", 0.5),
        ),
        flow=FlowIndicators(
            cmf=row.get("cmf", 0) or 0,
            obv_slope_pct=row.get("obv_slope_pct", 0) or 0,
            mfi=row.get("mfi", 50) or 50,
            vsa_signal=row.get("vsa_signal", "NEUTRAL") or "NEUTRAL",
        ),
    )

    trend_score = _score_trend(analysis, close)
    momentum_score = _score_momentum(analysis)
    volume_score = _score_volume(analysis)
    strength_score = _score_strength(analysis)
    volatility_score = _score_volatility(analysis, close)
    flow_score = _score_flow(analysis)

    total = (trend_score + momentum_score + volume_score +
             strength_score + volatility_score + flow_score)

    # conditions_met -- bookkeeping backtest-only, definisi dipertahankan
    # dari versi sebelumnya (dipakai laporan/analisis backtest, BUKAN
    # bagian dari raw_score/signal_type).
    conditions = 0
    if close > ema20 > ema50 > ema200 > 0 or close > ema20 > ema50 > 0:
        conditions += 1
    if ema50 > ema200 > 0:
        conditions += 1
    rsi_val = analysis.momentum.rsi
    if 30 <= rsi_val <= 60:
        conditions += 1
    if analysis.momentum.macd_hist > 0:
        conditions += 1
    if volume_ratio >= 1.5:
        conditions += 1
    bearish_dominant = minus_di > 20 or minus_di > plus_di
    if adx >= 25 and not bearish_dominant:
        conditions += 1

    return round(total, 2), conditions


def _simulate_trade(
    df: pd.DataFrame,
    signal_idx: int,
    ticker: str = "",
) -> TradeResult:
    """
    Simulasi satu trade dari titik SINYAL (signal_idx), dengan model
    eksekusi realistis (lihat AUDIT NOTE di atas modul):

      - Entry di OPEN hari berikutnya (signal_idx + 1), bukan close
        hari sinyal itu sendiri.
      - ATR/SL/TP dihitung dari informasi yang SUDAH diketahui saat
        sinyal terbentuk (ATR hari sinyal) — tidak ada leakage.
      - Jika SL dan TP1 sama-sama tersentuh dalam satu candle, SL
        diasumsikan terjadi lebih dulu (konservatif, standar industri).
      - Window pencarian TP/SL dimulai dari hari entry itu sendiri
        (gap besar di hari entry pun bisa langsung kena SL/TP).
    """
    signal_row = df.iloc[signal_idx]
    signal_date = str(df.index[signal_idx])[:10]

    atr = signal_row.get("atr", None)
    if atr is None or pd.isna(atr) or atr <= 0:
        try:
            atr = float(signal_row["high"]) - float(signal_row["low"])
        except Exception:
            atr = 0.0

    entry_idx = signal_idx + 1
    if entry_idx >= len(df):
        return TradeResult(
            date=signal_date, ticker=ticker, entry=0, exit_price=0,
            atr=float(atr), tp1=0, tp2=0, sl=0, win=False, exit_reason="NO_NEXT_BAR",
            exit_candle=0, gross_pnl_pct=0, net_pnl_pct=0,
            max_gain_pct=0, conditions_met=0,
        )

    entry_row = df.iloc[entry_idx]
    entry = float(entry_row["open"])

    if atr <= 0 or entry <= 0:
        return TradeResult(
            date=signal_date, ticker=ticker, entry=entry, exit_price=entry,
            atr=float(atr), tp1=0, tp2=0, sl=0, win=False, exit_reason="INVALID",
            exit_candle=0, gross_pnl_pct=0, net_pnl_pct=0,
            max_gain_pct=0, conditions_met=0,
        )

    # AUDIT (2026-08, ditemukan saat audit menyeluruh): SEBELUMNYA cuma
    # TP1 & SL yang disimulasikan di sini -- TP2 (atr_tp2_multiplier,
    # ADA di settings & DIPAKAI live tracking di signal_evaluator.py::
    # _walk_price_path, urutan cek SL->TP2->TP1) TIDAK PERNAH disimulasikan
    # backtest sama sekali. Akibatnya backtest menguji strategi single-
    # target (exit penuh di TP1) yang BEDA dari yang benar-benar dilacak
    # live (bisa exit di TP2 kalau harga gap lewat TP1 & TP2 di hari yang
    # sama). Diperbaiki: tp2 dihitung & urutan cek disamakan persis
    # dengan _walk_price_path (SL -> TP2 -> TP1).
    tp1 = entry + settings.atr_tp1_multiplier * atr
    tp2 = entry + settings.atr_tp2_multiplier * atr
    sl = entry - settings.atr_sl_multiplier * atr

    max_gain = 0.0
    exit_price = entry
    exit_reason = "TIMEOUT"
    exit_candle = FORWARD_CANDLES

    for i in range(0, FORWARD_CANDLES):
        idx = entry_idx + i
        if idx >= len(df):
            exit_candle = i
            break

        bar = df.iloc[idx]
        bar_high = float(bar["high"])
        bar_low = float(bar["low"])
        candle_gain = (bar_high - entry) / entry * 100
        max_gain = max(max_gain, candle_gain)

        # Konservatif, SAMA PERSIS urutan dgn signal_evaluator.py::
        # _walk_price_path -- SL -> TP2 -> TP1 (lihat AUDIT NOTE di atas)
        if bar_low <= sl:
            exit_price = sl
            exit_reason = "SL"
            exit_candle = i + 1
            break

        if bar_high >= tp2:
            exit_price = tp2
            exit_reason = "TP2"
            exit_candle = i + 1
            break

        if bar_high >= tp1:
            exit_price = tp1
            exit_reason = "TP1"
            exit_candle = i + 1
            break

    gross_pnl_pct = (exit_price - entry) / entry * 100
    commission_pct = (BUY_COMMISSION + SELL_COMMISSION) * 100
    net_pnl_pct = gross_pnl_pct - commission_pct

    _, cond_met = _score_row(signal_row)

    return TradeResult(
        date=signal_date,
        ticker=ticker,
        entry=entry,
        exit_price=exit_price,
        atr=float(atr),
        tp1=tp1,
        tp2=tp2,
        sl=sl,
        win=net_pnl_pct > 0,
        exit_reason=exit_reason,
        exit_candle=exit_candle,
        gross_pnl_pct=round(gross_pnl_pct, 4),
        net_pnl_pct=round(net_pnl_pct, 4),
        max_gain_pct=round(max_gain, 4),
        conditions_met=cond_met,
    )


def _run_period_backtest(
    df: pd.DataFrame,
    ticker: str,
    min_score: float = 60.0,
    min_conditions: int = 3,
) -> list[TradeResult]:
    """
    Scan seluruh periode dan simulasi semua trade yang valid.
    min_score kini di skala 0-100 (selaras live), default 60 = sama
    persis dengan threshold BUY di composite scoring live.
    """
    trades = []
    start_idx = MIN_WARMUP_ROWS

    for i in range(start_idx, len(df) - FORWARD_CANDLES - 2):
        row = df.iloc[i]

        close = float(row["close"])
        volume = float(row["volume"])
        if close < settings.min_price or volume < settings.min_volume:
            continue

        score, conditions = _score_row(row)
        if score < min_score or conditions < min_conditions:
            continue

        if i >= 3:
            base = float(df.iloc[i - 3]["close"])
            if base > 0 and (close / base - 1) * 100 > settings.max_pump_pct:
                continue

        trade = _simulate_trade(df, i, ticker=ticker)

        if trade.exit_reason in ("INVALID", "NO_NEXT_BAR"):
            continue

        trades.append(trade)

    return trades


def _calc_metrics(trades: list[TradeResult], ticker: str, period_start: str, period_end: str) -> BacktestResult:
    """Hitung semua metrik dari list trades."""
    result = BacktestResult(
        ticker=ticker,
        period_start=period_start,
        period_end=period_end,
        total_trades=len(trades),
    )

    if not trades:
        result.fail_reason = "Tidak ada trade ditemukan"
        return result

    wins = [t for t in trades if t.win]
    losses = [t for t in trades if not t.win]

    result.winning_trades = len(wins)
    result.losing_trades = len(losses)
    result.win_rate = len(wins) / len(trades) if trades else 0

    net_pnls = [t.net_pnl_pct for t in trades]
    win_pnls = [t.net_pnl_pct for t in wins]
    loss_pnls = [t.net_pnl_pct for t in losses]

    result.avg_gain_pct = float(np.mean(win_pnls)) if win_pnls else 0
    result.avg_loss_pct = float(np.mean(loss_pnls)) if loss_pnls else 0
    result.max_gain_pct = float(max(win_pnls)) if win_pnls else 0
    result.max_loss_pct = float(min(loss_pnls)) if loss_pnls else 0

    gross_wins = sum(p for p in win_pnls if p > 0)
    gross_losses = abs(sum(p for p in loss_pnls if p < 0))
    result.profit_factor = round(gross_wins / gross_losses, 2) if gross_losses > 0 else float("inf")

    loss_rate = 1 - result.win_rate
    result.expectancy = round(
        (result.win_rate * result.avg_gain_pct) + (loss_rate * result.avg_loss_pct), 2
    )

    cum_return = 1.0
    equity_curve = []
    for t in trades:
        cum_return *= (1 + t.net_pnl_pct / 100)
        equity_curve.append(cum_return)

    result.total_return_pct = round((cum_return - 1) * 100, 2)

    if equity_curve:
        equity_arr = np.array(equity_curve)
        running_max = np.maximum.accumulate(equity_arr)
        drawdowns = (equity_arr - running_max) / running_max * 100
        result.max_drawdown_pct = round(float(abs(min(drawdowns))), 2)

    if len(net_pnls) > 1:
        pnl_array = np.array(net_pnls)
        mean_ret = np.mean(pnl_array)
        std_ret = np.std(pnl_array, ddof=1)
        if std_ret > 0:
            result.sharpe_ratio = round(mean_ret / std_ret * np.sqrt(25), 2)

    if losses:
        downside = np.array([t.net_pnl_pct for t in losses])
        downside_std = np.std(downside, ddof=1)
        mean_all = np.mean(net_pnls)
        if downside_std > 0:
            result.sortino_ratio = round(mean_all / downside_std * np.sqrt(25), 2)

    if result.max_drawdown_pct > 0:
        result.calmar_ratio = round(result.total_return_pct / result.max_drawdown_pct, 2)

    result.trades = [vars(t) for t in trades[-20:]]

    return result


def run_backtest(
    ticker: str,
    df: pd.DataFrame,
    min_score: float = 60.0,
    ihsg_close: Optional[pd.Series] = None,
) -> BacktestResult:
    """
    Jalankan walk-forward backtest untuk satu ticker.

    Args:
        ticker: Kode saham
        df: DataFrame OHLCV harian (minimal 252 baris)
        min_score: Minimum composite score untuk masuk trade (skala 0-100,
            selaras dengan composite scoring live — 60 = setara BUY)
        ihsg_close: Opsional, data close IHSG untuk hitung Relative
            Strength yang sesungguhnya (jika tidak diisi, RS dianggap
            netral/0 — backtest tetap jalan, hanya kurang satu dimensi)

    Returns:
        BacktestResult dengan semua metrik
    """
    if df is None or len(df) < MIN_WARMUP_ROWS + FORWARD_CANDLES + 10:
        return BacktestResult(
            ticker=ticker,
            fail_reason=f"Data tidak cukup: {len(df) if df is not None else 0} baris (minimum {MIN_WARMUP_ROWS + 20})"
        )

    log.info(f"Backtest {ticker}: {len(df)} candles, {len(df) - MIN_WARMUP_ROWS} hari aktif...")

    df_ind = _add_indicators(df, ihsg_close=ihsg_close)

    period_start = str(df_ind.index[MIN_WARMUP_ROWS])[:10]
    period_end = str(df_ind.index[-FORWARD_CANDLES - 1])[:10]

    trades = _run_period_backtest(df_ind, ticker, min_score=min_score)

    log.info(f"  → {len(trades)} trade ditemukan")

    if len(trades) < 5:
        result = BacktestResult(
            ticker=ticker,
            period_start=period_start,
            period_end=period_end,
            total_trades=len(trades),
            fail_reason=f"Terlalu sedikit trade: {len(trades)} (minimum 5)",
        )
        return result

    result = _calc_metrics(trades, ticker, period_start, period_end)
    result.passed = (
        result.win_rate >= settings.min_win_rate and
        result.profit_factor > 1.0 and
        result.total_trades >= 5
    )

    if not result.passed:
        reasons = []
        if result.win_rate < settings.min_win_rate:
            reasons.append(f"Win rate {result.win_rate:.0%} < {settings.min_win_rate:.0%}")
        if result.profit_factor <= 1.0:
            reasons.append(f"Profit factor {result.profit_factor:.2f} ≤ 1.0")
        result.fail_reason = " | ".join(reasons)

    log.info(
        f"  → WR={result.win_rate:.1%} PF={result.profit_factor:.2f} "
        f"MDD={result.max_drawdown_pct:.1f}% Sharpe={result.sharpe_ratio:.2f} "
        f"{'✓ PASSED' if result.passed else '✗ FAILED'}"
    )

    return result


def save_backtest_result(result: BacktestResult) -> bool:
    """Simpan hasil backtest ke database."""
    try:
        db = get_db()
        db.table("backtest_results").upsert({
            "run_date": date.today().isoformat(),
            "ticker": result.ticker,
            "strategy_name": result.strategy_name,
            "period_start": result.period_start or None,
            "period_end": result.period_end or None,
            "total_trades": result.total_trades,
            "winning_trades": result.winning_trades,
            "losing_trades": result.losing_trades,
            "win_rate": round(result.win_rate, 4),
            "profit_factor": round(result.profit_factor, 4) if result.profit_factor != float("inf") else 99.99,
            "expectancy": round(result.expectancy, 4),
            "avg_gain_pct": round(result.avg_gain_pct, 4),
            "avg_loss_pct": round(result.avg_loss_pct, 4),
            "max_gain_pct": round(result.max_gain_pct, 4),
            "max_loss_pct": round(result.max_loss_pct, 4),
            "max_drawdown": round(result.max_drawdown_pct / 100, 4),
            "sharpe_ratio": round(result.sharpe_ratio, 4),
            "sortino_ratio": round(result.sortino_ratio, 4),
            "calmar_ratio": round(result.calmar_ratio, 4),
            "parameters": {"min_score": 60.0, "forward_candles": FORWARD_CANDLES, "scale": "0-100 (selaras live)"},
            "notes": result.fail_reason if not result.passed else f"PASSED | {result.total_trades} trades",
        }, on_conflict="run_date,ticker,strategy_name").execute()
        return True
    except Exception as e:
        log.error(f"Gagal simpan backtest result: {e}")
        return False


def get_backtest_results(ticker: Optional[str] = None, limit: int = 50) -> list[dict]:
    """Ambil hasil backtest dari database."""
    try:
        db = get_db()
        query = db.table("backtest_results").select("*").order("run_date", desc=True)
        if ticker:
            query = query.eq("ticker", ticker)
        result = query.limit(limit).execute()
        return result.data or []
    except Exception as e:
        log.error(f"Gagal ambil backtest results: {e}")
        return []
