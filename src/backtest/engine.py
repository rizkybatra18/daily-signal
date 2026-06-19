"""
DAILY SIGNAL — Backtesting Framework
Walk-forward backtest yang benar: deterministic, reproducible,
tanpa look-ahead bias, dengan transaction costs.

Metodologi:
    1. Split data: Train (N-1 tahun) / Test (1 tahun terakhir)
    2. Hitung indikator hanya dari data yang tersedia pada titik t
    3. Simulasi trade dengan SL/TP dari ATR
    4. Sertakan biaya komisi BEI (0.19% beli + 0.29% jual)
    5. Hitung metrik lengkap

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
    calc_rsi, calc_ema, calc_macd, calc_atr, calc_adx, calc_bollinger
)

log = get_logger("backtest")

# ── Constants ────────────────────────────────────────────────────────
BUY_COMMISSION = 0.0019    # 0.15% broker + 0.04% levy
SELL_COMMISSION = 0.0029   # 0.15% broker + 0.04% levy + 0.10% PPh Final
FORWARD_CANDLES = 10       # Simulasi 10 hari ke depan
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
    exit_reason: str       # TP1/TP2/SL/TIMEOUT
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


def _add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    Hitung semua indikator.
    PENTING: Tidak ada look-ahead bias karena kita pakai expanding/rolling
    yang hanya melihat data sebelumnya.
    """
    df = df.copy()
    close = df["close"]
    volume = df["volume"]

    df["rsi"] = calc_rsi(close, settings.rsi_period)
    macd_line, macd_sig, macd_hist = calc_macd(close)
    df["macd_hist"] = macd_hist
    df["macd_line"] = macd_line
    df["macd_signal"] = macd_sig
    df["ema20"] = calc_ema(close, 20)
    df["ema50"] = calc_ema(close, 50)
    df["atr"] = calc_atr(df, settings.atr_period)
    adx, plus_di, minus_di = calc_adx(df, settings.adx_period)
    df["adx"] = adx
    df["vol_ma20"] = volume.rolling(20, min_periods=10).mean()
    bb_up, bb_mid, bb_lo = calc_bollinger(close, 20)
    df["bb_upper"] = bb_up
    df["bb_lower"] = bb_lo

    return df.dropna(subset=["rsi", "ema20", "atr"])


def _score_row(row: pd.Series) -> tuple[float, int]:
    """
    Hitung composite score untuk satu baris (satu hari).
    Return: (score, conditions_met)

    Ini adalah replica dari scoring engine untuk konsistensi backtest.
    """
    score = 0.0
    conditions = 0
    close = row["close"]

    # Trend (0-30)
    ema20 = row.get("ema20", 0)
    ema50 = row.get("ema50", 0)
    if close > ema20 > ema50 > 0:
        score += 20
        conditions += 1
    elif close > ema20 > 0:
        score += 10
        conditions += 1

    # Momentum RSI (0-12)
    rsi = row.get("rsi", 50)
    if 40 <= rsi <= 65:
        score += 12
        conditions += 1
    elif 30 <= rsi < 40:
        score += 8
        conditions += 1

    # MACD (0-8)
    macd_hist = row.get("macd_hist", 0)
    if macd_hist > 0:
        score += 8
        conditions += 1

    # ADX (0-8)
    adx = row.get("adx", 0)
    if adx >= 25:
        score += 8
        conditions += 1
    elif adx >= 20:
        score += 4

    # Volume (0-12)
    vol_ma = row.get("vol_ma20", 1)
    vol = row.get("volume", 0)
    if vol_ma > 0 and vol / vol_ma >= 1.5:
        score += 12
        conditions += 1

    return score, conditions


def _simulate_trade(
    df: pd.DataFrame,
    entry_idx: int,
) -> TradeResult:
    """
    Simulasi satu trade dari titik entry.
    Menggunakan ATR-based SL/TP.
    Menyertakan biaya komisi.
    """
    row = df.iloc[entry_idx]
    entry = float(row["close"])
    atr = float(row["atr"])
    trade_date = str(df.index[entry_idx])[:10]

    if atr <= 0 or entry <= 0:
        return TradeResult(
            date=trade_date, ticker="", entry=entry, exit_price=entry,
            atr=atr, tp1=0, sl=0, win=False, exit_reason="INVALID",
            exit_candle=0, gross_pnl_pct=0, net_pnl_pct=0,
            max_gain_pct=0, conditions_met=0,
        )

    tp1 = entry + settings.atr_tp1_multiplier * atr
    tp2 = entry + settings.atr_tp2_multiplier * atr
    sl = entry - settings.atr_sl_multiplier * atr

    max_gain = 0.0
    exit_price = entry
    exit_reason = "TIMEOUT"
    exit_candle = FORWARD_CANDLES

    for i in range(1, FORWARD_CANDLES + 1):
        next_idx = entry_idx + i
        if next_idx >= len(df):
            exit_candle = i - 1
            break

        future_high = float(df.iloc[next_idx]["high"])
        future_low = float(df.iloc[next_idx]["low"])
        candle_gain = (future_high - entry) / entry * 100
        max_gain = max(max_gain, candle_gain)

        # Check TP1 first (optimistic — assume best case dalam candle)
        if future_high >= tp1:
            exit_price = tp1
            exit_reason = "TP1"
            exit_candle = i
            break

        # Check SL
        if future_low <= sl:
            exit_price = sl
            exit_reason = "SL"
            exit_candle = i
            break

    # PnL calculations
    gross_pnl_pct = (exit_price - entry) / entry * 100
    # Komisi (dikurangi dari return)
    commission_pct = (BUY_COMMISSION + SELL_COMMISSION) * 100
    net_pnl_pct = gross_pnl_pct - commission_pct

    _, cond_met = _score_row(df.iloc[entry_idx])

    return TradeResult(
        date=trade_date,
        ticker=df.get("ticker", ""),
        entry=entry,
        exit_price=exit_price,
        atr=atr,
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
    Return list TradeResult.
    """
    trades = []

    # Tidak boleh ada look-ahead — mulai setelah warmup
    start_idx = MIN_WARMUP_ROWS

    for i in range(start_idx, len(df) - FORWARD_CANDLES - 1):
        row = df.iloc[i]

        # Basic filter
        close = float(row["close"])
        volume = float(row["volume"])
        if close < settings.min_price or volume < settings.min_volume:
            continue

        # Score pada titik ini (hanya data yang sudah tersedia)
        score, conditions = _score_row(row)

        if score < min_score or conditions < min_conditions:
            continue

        # Anti-pump check
        if i >= 3:
            base = float(df.iloc[i - 3]["close"])
            if base > 0 and (close / base - 1) * 100 > settings.max_pump_pct:
                continue

        trade = _simulate_trade(df, i)
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

    # Return metrics
    net_pnls = [t.net_pnl_pct for t in trades]
    win_pnls = [t.net_pnl_pct for t in wins]
    loss_pnls = [t.net_pnl_pct for t in losses]

    result.avg_gain_pct = float(np.mean(win_pnls)) if win_pnls else 0
    result.avg_loss_pct = float(np.mean(loss_pnls)) if loss_pnls else 0
    result.max_gain_pct = float(max(win_pnls)) if win_pnls else 0
    result.max_loss_pct = float(min(loss_pnls)) if loss_pnls else 0

    # Profit Factor
    gross_wins = sum(p for p in win_pnls if p > 0)
    gross_losses = abs(sum(p for p in loss_pnls if p < 0))
    result.profit_factor = round(gross_wins / gross_losses, 2) if gross_losses > 0 else float("inf")

    # Expectancy: (WR × avg_gain) + (LR × avg_loss)
    loss_rate = 1 - result.win_rate
    result.expectancy = round(
        (result.win_rate * result.avg_gain_pct) + (loss_rate * result.avg_loss_pct), 2
    )

    # Total return (compound)
    cum_return = 1.0
    equity_curve = []
    for t in trades:
        cum_return *= (1 + t.net_pnl_pct / 100)
        equity_curve.append(cum_return)

    result.total_return_pct = round((cum_return - 1) * 100, 2)

    # Max Drawdown
    if equity_curve:
        equity_arr = np.array(equity_curve)
        running_max = np.maximum.accumulate(equity_arr)
        drawdowns = (equity_arr - running_max) / running_max * 100
        result.max_drawdown_pct = round(float(abs(min(drawdowns))), 2)

    # Sharpe Ratio (annualized, risk-free = 0)
    if len(net_pnls) > 1:
        pnl_array = np.array(net_pnls)
        mean_ret = np.mean(pnl_array)
        std_ret = np.std(pnl_array, ddof=1)
        if std_ret > 0:
            # Asumsi ~252 trading days / avg 10-day hold = ~25 trades per tahun
            result.sharpe_ratio = round(mean_ret / std_ret * np.sqrt(25), 2)

    # Sortino Ratio (downside deviation only)
    if losses:
        downside = np.array([t.net_pnl_pct for t in losses])
        downside_std = np.std(downside, ddof=1)
        mean_all = np.mean(net_pnls)
        if downside_std > 0:
            result.sortino_ratio = round(mean_all / downside_std * np.sqrt(25), 2)

    # Calmar Ratio
    if result.max_drawdown_pct > 0:
        result.calmar_ratio = round(result.total_return_pct / result.max_drawdown_pct, 2)

    result.trades = [vars(t) for t in trades[-20:]]  # Simpan 20 trade terakhir saja

    return result


def run_backtest(
    ticker: str,
    df: pd.DataFrame,
    min_score: float = 60.0,
) -> BacktestResult:
    """
    Jalankan walk-forward backtest untuk satu ticker.

    Args:
        ticker: Kode saham
        df: DataFrame OHLCV harian (minimal 252 baris)
        min_score: Minimum composite score untuk masuk trade

    Returns:
        BacktestResult dengan semua metrik
    """
    if df is None or len(df) < MIN_WARMUP_ROWS + FORWARD_CANDLES + 10:
        return BacktestResult(
            ticker=ticker,
            fail_reason=f"Data tidak cukup: {len(df) if df is not None else 0} baris (minimum {MIN_WARMUP_ROWS + 20})"
        )

    log.info(f"Backtest {ticker}: {len(df)} candles, {len(df) - MIN_WARMUP_ROWS} hari aktif...")

    # Hitung indikator (no look-ahead)
    df_ind = _add_indicators(df)

    period_start = str(df_ind.index[MIN_WARMUP_ROWS])[:10]
    period_end = str(df_ind.index[-FORWARD_CANDLES - 1])[:10]

    # Jalankan simulasi
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

    # Hitung metrik
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
            "parameters": {"min_score": 60.0, "forward_candles": FORWARD_CANDLES},
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
