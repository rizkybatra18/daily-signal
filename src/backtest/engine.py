"""
DAILY SIGNAL — Backtesting Framework
Walk-forward backtest: deterministic, reproducible, tanpa look-ahead
bias, dengan transaction cost dan model eksekusi yang realistis.

═══════════════════════════════════════════════════════════════════
AUDIT NOTE (Backtest Audit — lihat AUDIT_REPORT.md untuk detail)
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
     (0-100, bobot 30/25/20/15/10). Akibatnya backtest sebenarnya
     memvalidasi strategi yang BERBEDA dari yang benar-benar dipakai
     live. Diperbaiki: _score_row() kini meniru persis pita nilai
     _score_trend/_score_momentum/_score_volume/_score_strength/
     _score_volatility di ta_engine.py (total tetap 0-100).

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
    calc_mansfield_rs,
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
    sl: float
    win: bool
    exit_reason: str       # TP1/SL/TIMEOUT/INVALID/NO_NEXT_BAR
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

    return df.dropna(subset=["rsi", "ema20", "atr"])


def _score_row(row: pd.Series) -> tuple[float, int]:
    """
    Hitung composite score untuk satu baris (satu hari) — SKALA 0-100,
    meniru persis pita nilai di ta_engine.py (_score_trend dkk) agar
    backtest ini benar-benar menguji strategi yang sama dengan yang
    live berjalan (lihat AUDIT NOTE di atas modul ini).

    Return: (score 0-100, conditions_met) — signature TIDAK berubah
    dari versi sebelumnya (dipakai test_backtest_no_lookahead).
    """
    close = row.get("close", 0)
    conditions = 0

    # ── Trend (0-30) ──────────────────────────────────────────────
    ema20 = row.get("ema20", 0) or 0
    ema50 = row.get("ema50", 0) or 0
    ema200 = row.get("ema200", 0) or 0
    trend_score = 0.0

    if close > ema20 > ema50 > ema200 > 0:
        trend_score += 12
        conditions += 1
    elif close > ema20 > ema50 > 0:
        trend_score += 8
        conditions += 1
    elif close > ema20 > 0:
        trend_score += 4

    if ema20 > 0:
        gap_pct = (close - ema20) / ema20 * 100
        if 0 < gap_pct <= 5:
            trend_score += 8
        elif 5 < gap_pct <= 10:
            trend_score += 5
        elif gap_pct > 10:
            trend_score += 2
        elif -2 < gap_pct <= 0:
            trend_score += 3

    if ema50 > ema200 > 0:
        trend_score += 6
        conditions += 1
    elif ema50 > 0 and ema200 > 0 and ema50 > ema200 * 0.98:
        trend_score += 3

    if ema20 > 0:
        price_vs_ema20 = (close / ema20 - 1) * 100
        if price_vs_ema20 > 1:
            trend_score += 4
        elif price_vs_ema20 > 0:
            trend_score += 2

    trend_score = min(trend_score, 30.0)

    # ── Momentum (0-25) ───────────────────────────────────────────
    rsi = row.get("rsi", 50) or 50
    rsi_prev = row.get("rsi_prev", rsi) or rsi
    macd_hist = row.get("macd_hist", 0) or 0
    macd_hist_prev = row.get("macd_hist_prev", 0) or 0
    macd_line = row.get("macd_line", 0) or 0
    macd_signal = row.get("macd_signal", 0) or 0
    macd_cross = row.get("macd_cross", "NONE")
    momentum_score = 0.0

    if 40 <= rsi <= 60:
        momentum_score += 12
        conditions += 1
    elif 30 <= rsi < 40:
        momentum_score += 10
        conditions += 1
    elif 60 < rsi <= 65:
        momentum_score += 8
    elif 65 < rsi <= 70:
        momentum_score += 5
    elif rsi < 30:
        momentum_score += 6
    elif rsi > 70:
        momentum_score += 2

    if rsi > rsi_prev and rsi < 70:
        momentum_score += 2

    if macd_hist > 0:
        momentum_score += 8
        conditions += 1
        if macd_hist > macd_hist_prev:
            momentum_score += 2
    elif macd_hist > -0.001:
        momentum_score += 4

    if macd_cross == "GOLDEN":
        momentum_score += 5
    elif macd_line > macd_signal:
        momentum_score += 3

    momentum_score = min(momentum_score, 25.0)

    # ── Volume (0-20) ─────────────────────────────────────────────
    vol_ma20 = row.get("vol_ma20", 0) or 0
    vol = row.get("volume", 0) or 0
    volume_trend = row.get("volume_trend", "NORMAL")
    volume_score = 0.0
    ratio = (vol / vol_ma20) if vol_ma20 > 0 else 1.0

    if ratio >= 2.0:
        volume_score += 15
        conditions += 1
    elif ratio >= 1.5:
        volume_score += 10
        conditions += 1
    elif ratio >= 1.2:
        volume_score += 7
    elif ratio >= 1.0:
        volume_score += 4
    elif ratio >= 0.7:
        volume_score += 2

    if volume_trend == "SURGE":
        volume_score += 5
    elif volume_trend == "INCREASING":
        volume_score += 3

    volume_score = min(volume_score, 20.0)

    # ── Strength (0-15) ───────────────────────────────────────────
    adx = row.get("adx", 0) or 0
    rel_strength = row.get("rel_strength", 0) or 0
    strength_score = 0.0

    if adx >= 40:
        strength_score += 8
        conditions += 1
    elif adx >= 30:
        strength_score += 6
        conditions += 1
    elif adx >= 25:
        strength_score += 4
    elif adx >= 20:
        strength_score += 2

    if rel_strength >= 10:
        strength_score += 7
    elif rel_strength >= 5:
        strength_score += 5
    elif rel_strength >= 0:
        strength_score += 3
    elif rel_strength >= -5:
        strength_score += 1

    strength_score = min(strength_score, 15.0)

    # ── Volatility (0-10) ─────────────────────────────────────────
    atr_pct = row.get("atr_pct", 0) or 0
    bb_position = row.get("bb_position", 0.5)
    bb_squeeze = bool(row.get("bb_squeeze", False))
    volatility_score = 0.0

    if 1.0 <= atr_pct <= 4.0:
        volatility_score += 5
    elif 0.5 <= atr_pct < 1.0:
        volatility_score += 3
    elif 4.0 < atr_pct <= 6.0:
        volatility_score += 2
    elif atr_pct < 0.5:
        volatility_score += 1

    if 0.1 <= bb_position <= 0.4:
        volatility_score += 5
    elif 0.4 < bb_position <= 0.6:
        volatility_score += 3
    elif 0.6 < bb_position <= 0.8:
        volatility_score += 1

    if bb_squeeze:
        volatility_score += 2

    volatility_score = min(volatility_score, 10.0)

    total = trend_score + momentum_score + volume_score + strength_score + volatility_score
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

    # ATR diketahui saat sinyal terbentuk (bukan leakage)
    atr = signal_row.get("atr", None)
    if atr is None or pd.isna(atr) or atr <= 0:
        # Fallback: dari range high-low hari sinyal itu sendiri (kasar,
        # hanya dipakai jika kolom 'atr' benar-benar tidak tersedia —
        # backtest produksi SELALU sudah punya kolom 'atr' dari
        # _add_indicators, fallback ini murni untuk robustness)
        try:
            atr = float(signal_row["high"]) - float(signal_row["low"])
        except Exception:
            atr = 0.0

    entry_idx = signal_idx + 1
    if entry_idx >= len(df):
        return TradeResult(
            date=signal_date, ticker=ticker, entry=0, exit_price=0,
            atr=float(atr), tp1=0, sl=0, win=False, exit_reason="NO_NEXT_BAR",
            exit_candle=0, gross_pnl_pct=0, net_pnl_pct=0,
            max_gain_pct=0, conditions_met=0,
        )

    entry_row = df.iloc[entry_idx]
    entry = float(entry_row["open"])

    if atr <= 0 or entry <= 0:
        return TradeResult(
            date=signal_date, ticker=ticker, entry=entry, exit_price=entry,
            atr=float(atr), tp1=0, sl=0, win=False, exit_reason="INVALID",
            exit_candle=0, gross_pnl_pct=0, net_pnl_pct=0,
            max_gain_pct=0, conditions_met=0,
        )

    tp1 = entry + settings.atr_tp1_multiplier * atr
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

        # Konservatif: SL diperiksa LEBIH DULU (lihat AUDIT NOTE)
        if bar_low <= sl:
            exit_price = sl
            exit_reason = "SL"
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

    # -2 karena _simulate_trade butuh signal_idx+1 (entry bar) yang valid
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

        # Trade yang tidak benar-benar tereksekusi (data habis / invalid)
        # tidak dihitung sebagai trade sungguhan.
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
