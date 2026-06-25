"""
DAILY SIGNAL — Technical Analysis Engine
Seluruh indikator teknikal dihitung deterministik.
Tidak ada AI dalam modul ini.

Indikator:
    Trend    : EMA20, EMA50, EMA200, price vs EMA alignment
    Momentum : RSI(14), MACD(12,26,9), MACD Histogram
    Strength : ADX(14), Relative Strength vs IHSG
    Volume   : Volume Ratio, Volume Spike, Relative Volume
    Volatility: ATR(14), Bollinger Bands(20,2), ATR%
"""

import pandas as pd
import numpy as np
from dataclasses import dataclass, field, asdict
from typing import Optional
from src.core.config import settings
from src.core.logger import get_logger

log = get_logger("ta_engine")


# ═══════════════════════════════════════════════════════════════════════
#  DATA CLASSES
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class TrendIndicators:
    ema20: float = 0.0
    ema50: float = 0.0
    ema200: float = 0.0
    price_vs_ema20: float = 0.0    # % difference
    price_vs_ema50: float = 0.0
    price_vs_ema200: float = 0.0
    ema_alignment: str = "NEUTRAL"  # BULLISH/NEUTRAL/BEARISH
    trend_direction: str = "SIDEWAYS"


@dataclass
class MomentumIndicators:
    rsi: float = 50.0
    rsi_prev: float = 50.0        # RSI hari sebelumnya (untuk divergence)
    macd_line: float = 0.0
    macd_signal: float = 0.0
    macd_hist: float = 0.0
    macd_hist_prev: float = 0.0
    macd_cross: str = "NONE"      # GOLDEN/DEATH/NONE
    rsi_zone: str = "NEUTRAL"     # OVERSOLD/NEUTRAL/OVERBOUGHT


@dataclass
class StrengthIndicators:
    adx: float = 0.0
    plus_di: float = 0.0
    minus_di: float = 0.0
    trend_strength: str = "WEAK"    # WEAK/MODERATE/STRONG
    rel_strength: float = 0.0       # RS vs IHSG (Mansfield RS)
    rs_trend: str = "NEUTRAL"       # OUTPERFORM/NEUTRAL/UNDERPERFORM


@dataclass
class VolumeIndicators:
    volume: float = 0.0
    avg_volume_20: float = 0.0
    volume_ratio: float = 1.0
    volume_spike: bool = False
    volume_trend: str = "NORMAL"    # SURGE/INCREASING/NORMAL/DECLINING


@dataclass
class VolatilityIndicators:
    atr: float = 0.0
    atr_pct: float = 0.0            # ATR as % of price
    bb_upper: float = 0.0
    bb_mid: float = 0.0
    bb_lower: float = 0.0
    bb_width: float = 0.0           # (upper-lower)/mid = bandwidth
    bb_position: float = 0.5        # 0=at lower, 1=at upper
    bb_squeeze: bool = False         # Bollinger Squeeze detected


@dataclass
class RiskLevels:
    entry_price: float = 0.0
    stop_loss: float = 0.0
    target_1: float = 0.0
    target_2: float = 0.0
    risk_pct: float = 0.0           # % risk dari entry ke SL
    reward_pct_tp1: float = 0.0
    reward_pct_tp2: float = 0.0
    risk_reward_tp1: float = 0.0
    risk_reward_tp2: float = 0.0
    position_size_pct: float = 0.0  # Suggested position size (% portfolio)


@dataclass
class CompositeScore:
    """
    Composite Score 0-100.
    
    Formula:
        trend_score     = 0-30  (EMA alignment, price position)
        momentum_score  = 0-25  (RSI zone, MACD direction)
        volume_score    = 0-20  (volume ratio, spike)
        strength_score  = 0-15  (ADX, relative strength)
        volatility_score= 0-10  (ATR position, BB squeeze)
        ─────────────────────────
        Total           = 0-100
    
    Multiplied by regime_weight (0.3-1.0) based on market regime.
    """
    trend_score: float = 0.0
    momentum_score: float = 0.0
    volume_score: float = 0.0
    strength_score: float = 0.0
    volatility_score: float = 0.0
    raw_score: float = 0.0          # Sum sebelum regime adjustment
    regime_weight: float = 1.0       # Multiplier dari market regime
    final_score: float = 0.0         # raw_score × regime_weight
    signal_type: str = "AVOID"        # STRONG_BUY/BUY/WATCHLIST/AVOID


@dataclass
class StockAnalysis:
    """Hasil lengkap analisis satu saham."""
    ticker: str = ""
    analysis_date: str = ""
    close: float = 0.0
    open_price: float = 0.0
    change_pct: float = 0.0
    pump_pct_3c: float = 0.0
    
    trend: TrendIndicators = field(default_factory=TrendIndicators)
    momentum: MomentumIndicators = field(default_factory=MomentumIndicators)
    strength: StrengthIndicators = field(default_factory=StrengthIndicators)
    volume: VolumeIndicators = field(default_factory=VolumeIndicators)
    volatility: VolatilityIndicators = field(default_factory=VolatilityIndicators)
    risk: RiskLevels = field(default_factory=RiskLevels)
    score: CompositeScore = field(default_factory=CompositeScore)
    
    # Flags
    passed_basic_filter: bool = True
    filter_fail_reason: Optional[str] = None

    def to_dict(self) -> dict:
        """Convert ke flat dict untuk database insert."""
        return {
            "ticker": self.ticker,
            "analysis_date": self.analysis_date,
            "close_price": self.close,
            "change_pct": self.change_pct,
            # Trend
            "ema20": self.trend.ema20,
            "ema50": self.trend.ema50,
            "ema200": self.trend.ema200,
            # Momentum
            "rsi": self.momentum.rsi,
            "macd_line": self.momentum.macd_line,
            "macd_signal": self.momentum.macd_signal,
            "macd_hist": self.momentum.macd_hist,
            # Strength
            "adx": self.strength.adx,
            "rel_strength": self.strength.rel_strength,
            # Volume
            "volume": int(self.volume.volume),
            "avg_volume_20": int(self.volume.avg_volume_20),
            "volume_ratio": self.volume.volume_ratio,
            # Volatility
            "atr": self.volatility.atr,
            # Risk
            "entry_price": self.risk.entry_price,
            "stop_loss": self.risk.stop_loss,
            "target_1": self.risk.target_1,
            "target_2": self.risk.target_2,
            "risk_reward": self.risk.risk_reward_tp1,
            # Score
            "composite_score": self.score.final_score,
            "trend_score": self.score.trend_score,
            "momentum_score": self.score.momentum_score,
            "volume_score": self.score.volume_score,
            "strength_score": self.score.strength_score,
            "volatility_score": self.score.volatility_score,
            "signal_type": self.score.signal_type,
        }


# ═══════════════════════════════════════════════════════════════════════
#  INDIKATOR DASAR (Pure Functions — mudah di-test)
# ═══════════════════════════════════════════════════════════════════════

def calc_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """
    RSI (Relative Strength Index) via Wilder smoothing (EWM).
    Ini adalah implementasi yang benar — bukan rolling average biasa.
    """
    if len(close) < period + 1:
        return pd.Series([50.0] * len(close), index=close.index)
    
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    
    # Wilder smoothing (alpha = 1/period)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    rsi = rsi.fillna(50)
    
    return rsi


def calc_ema(close: pd.Series, period: int) -> pd.Series:
    """EMA (Exponential Moving Average)."""
    return close.ewm(span=period, adjust=False, min_periods=period).mean()


def calc_macd(
    close: pd.Series,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """
    MACD = EMA(fast) - EMA(slow)
    Signal = EMA(MACD, signal)
    Histogram = MACD - Signal
    """
    ema_fast = calc_ema(close, fast)
    ema_slow = calc_ema(close, slow)
    macd_line = ema_fast - ema_slow
    signal_line = calc_ema(macd_line, signal)
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def calc_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """ATR (Average True Range) via Wilder smoothing."""
    high = df["high"]
    low = df["low"]
    close = df["close"]
    prev_close = close.shift(1)
    
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    
    return tr.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()


def calc_adx(df: pd.DataFrame, period: int = 14) -> tuple[pd.Series, pd.Series, pd.Series]:
    """
    ADX + +DI + -DI.
    Return: (adx, plus_di, minus_di)
    """
    high = df["high"]
    low = df["low"]
    close = df["close"]
    
    prev_high = high.shift(1)
    prev_low = low.shift(1)
    prev_close = close.shift(1)
    
    # Directional Movement
    plus_dm = (high - prev_high).clip(lower=0)
    minus_dm = (prev_low - low).clip(lower=0)
    
    # Jika keduanya sama, set keduanya 0
    mask = plus_dm == minus_dm
    plus_dm[mask] = 0
    minus_dm[mask] = 0
    
    # Plus DM valid hanya jika lebih besar dari minus DM
    plus_dm[plus_dm < minus_dm] = 0
    minus_dm[minus_dm < plus_dm] = 0
    
    # True Range
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    
    # Smoothed values
    atr_smooth = tr.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    plus_dm_smooth = plus_dm.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    minus_dm_smooth = minus_dm.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    
    # Directional Indicators
    plus_di = 100 * (plus_dm_smooth / atr_smooth.replace(0, np.nan))
    minus_di = 100 * (minus_dm_smooth / atr_smooth.replace(0, np.nan))
    
    # DX dan ADX
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    adx = dx.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    
    return adx.fillna(0), plus_di.fillna(0), minus_di.fillna(0)


def calc_bollinger(
    close: pd.Series,
    period: int = 20,
    num_std: float = 2.0,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Bollinger Bands (SMA-based)."""
    mid = close.rolling(period, min_periods=period).mean()
    std = close.rolling(period, min_periods=period).std()
    upper = mid + num_std * std
    lower = mid - num_std * std
    return upper, mid, lower


def calc_mansfield_rs(
    close: pd.Series,
    benchmark_close: pd.Series,
    period: int = 52,
) -> pd.Series:
    """
    Mansfield Relative Strength vs benchmark (IHSG).
    Formula: RS = (Stock_return_N_weeks / Benchmark_return_N_weeks) × 100
    
    > 0 = outperform, < 0 = underperform
    Menggunakan skala relatif, bukan absolut.
    """
    if close.empty or benchmark_close.empty:
        return pd.Series([0.0] * len(close), index=close.index)
    
    # Align index
    common_idx = close.index.intersection(benchmark_close.index)
    if len(common_idx) < period:
        return pd.Series([0.0] * len(close), index=close.index)
    
    stock_aligned = close.reindex(common_idx)
    bench_aligned = benchmark_close.reindex(common_idx)
    
    # Rolling return
    stock_return = stock_aligned.pct_change(period)
    bench_return = bench_aligned.pct_change(period)
    
    # Mansfield RS
    rs = ((1 + stock_return) / (1 + bench_return.replace(0, np.nan)) - 1) * 100
    
    # Reindex ke original index
    return rs.reindex(close.index, fill_value=0)


# ═══════════════════════════════════════════════════════════════════════
#  COMPOSITE SCORING ENGINE
# ═══════════════════════════════════════════════════════════════════════

def _score_trend(analysis: StockAnalysis, close: float) -> float:
    """
    Trend Score: 0-30 poin
    
    +12: EMA full alignment (close > EMA20 > EMA50 > EMA200)
    +8:  Partial alignment (close > EMA20 > EMA50)
    +4:  Minimal (close > EMA20)
    +8:  Strong EMA20 gap (close > EMA20 by >2%)
    +6:  Positive momentum (EMA20 trending up)
    +4:  Medium-term uptrend (EMA50 > EMA200)
    """
    score = 0.0
    t = analysis.trend
    
    # EMA Alignment (0-12)
    if close > t.ema20 > t.ema50 > t.ema200 > 0:
        score += 12
    elif close > t.ema20 > t.ema50 > 0:
        score += 8
    elif close > t.ema20 > 0:
        score += 4
    
    # Gap dari EMA20 (0-8): tidak terlalu jauh, tidak terlalu dekat
    if t.ema20 > 0:
        gap_pct = (close - t.ema20) / t.ema20 * 100
        if 0 < gap_pct <= 5:     score += 8   # Ideal: baru break EMA20
        elif 5 < gap_pct <= 10:  score += 5   # Sudah naik tapi masih ok
        elif gap_pct > 10:       score += 2   # Terlalu jauh, overbought
        elif -2 < gap_pct <= 0:  score += 3   # Tepat di EMA20, bisa bounce
    
    # EMA50 vs EMA200 (0-6): medium-term trend
    if t.ema50 > t.ema200 > 0:
        score += 6  # Golden alignment
    elif t.ema50 > 0 and t.ema200 > 0 and t.ema50 > t.ema200 * 0.98:
        score += 3  # Approaching golden
    
    # EMA20 direction: apakah EMA20 sedang naik? (0-4)
    # Proxy: price vs EMA20 positif dan makin lebar
    if t.price_vs_ema20 > 1:
        score += 4
    elif t.price_vs_ema20 > 0:
        score += 2
    
    return min(score, 30.0)


def _score_momentum(analysis: StockAnalysis) -> float:
    """
    Momentum Score: 0-25 poin
    
    RSI: 0-12 poin
    MACD: 0-13 poin
    """
    score = 0.0
    m = analysis.momentum
    
    # RSI Score (0-12)
    rsi = m.rsi
    if 40 <= rsi <= 60:      score += 12   # Sweet spot
    elif 30 <= rsi < 40:     score += 10   # Oversold area, potensi rebound
    elif 60 < rsi <= 65:     score += 8    # Masih momentum
    elif 65 < rsi <= 70:     score += 5    # Mendekati overbought
    elif rsi < 30:           score += 6    # Sangat oversold, extreme rebound
    elif rsi > 70:           score += 2    # Overbought, hati-hati
    
    # RSI trending up (0-2 bonus)
    if m.rsi > m.rsi_prev and rsi < 70:
        score += 2
    
    # MACD Histogram (0-8)
    if m.macd_hist > 0:
        score += 8                         # Momentum bullish
        # Bonus jika histogram sedang membesar
        if m.macd_hist > m.macd_hist_prev:
            score += 2
    elif m.macd_hist > -0.001:
        score += 4                         # Hampir ke positif
    
    # MACD Crossover (0-5)
    if m.macd_cross == "GOLDEN":
        score += 5                         # Fresh golden cross
    elif m.macd_line > m.macd_signal:
        score += 3                         # MACD di atas signal
    
    return min(score, 25.0)


def _score_volume(analysis: StockAnalysis) -> float:
    """
    Volume Score: 0-20 poin
    
    Volume Ratio (actual/avg):
    > 2.0x: surge (15 poin)
    1.5-2.0x: spike (10 poin)
    1.0-1.5x: above average (6 poin)
    < 1.0x: below average (2 poin)
    
    Volume Trend (0-5 bonus)
    """
    score = 0.0
    v = analysis.volume
    
    ratio = v.volume_ratio
    
    # Volume ratio (0-15)
    if ratio >= 2.0:        score += 15   # Volume surge
    elif ratio >= 1.5:      score += 10   # Volume spike
    elif ratio >= 1.2:      score += 7    # Above average
    elif ratio >= 1.0:      score += 4    # Normal
    elif ratio >= 0.7:      score += 2    # Below average
    else:                   score += 0    # Very low volume
    
    # Volume trend bonus (0-5)
    if v.volume_trend == "SURGE":      score += 5
    elif v.volume_trend == "INCREASING": score += 3
    
    return min(score, 20.0)


def _score_strength(analysis: StockAnalysis) -> float:
    """
    Strength Score: 0-15 poin
    
    ADX: 0-8 poin
    Relative Strength vs IHSG: 0-7 poin
    """
    score = 0.0
    s = analysis.strength
    
    # ADX Score (0-8)
    adx = s.adx
    if adx >= 40:           score += 8    # Sangat kuat
    elif adx >= 30:         score += 6    # Kuat
    elif adx >= 25:         score += 4    # Trending
    elif adx >= 20:         score += 2    # Weak trend
    else:                   score += 0    # Sideways
    
    # Relative Strength vs IHSG (0-7)
    rs = s.rel_strength
    if rs >= 10:            score += 7    # Outperform signifikan
    elif rs >= 5:           score += 5    # Outperform
    elif rs >= 0:           score += 3    # Inline dengan IHSG
    elif rs >= -5:          score += 1    # Sedikit underperform
    else:                   score += 0    # Underperform
    
    return min(score, 15.0)


def _score_volatility(analysis: StockAnalysis, close: float) -> float:
    """
    Volatility Score: 0-10 poin
    
    ATR%: moderately volatile = lebih baik dari sangat volatile
    Bollinger Position: near lower band = potensi rebound
    """
    score = 0.0
    vol = analysis.volatility
    
    # ATR% Score (0-5): idealnya 1-4% — cukup volatile untuk profit, tidak terlalu risky
    atr_pct = vol.atr_pct
    if 1.0 <= atr_pct <= 4.0:    score += 5
    elif 0.5 <= atr_pct < 1.0:   score += 3
    elif 4.0 < atr_pct <= 6.0:   score += 2
    elif atr_pct < 0.5:           score += 1   # Terlalu stabil, sulit profit
    else:                          score += 0   # Terlalu volatile (>6%)
    
    # Bollinger Position (0-5)
    bp = vol.bb_position
    if 0.1 <= bp <= 0.4:         score += 5   # Near lower band, potensi bounce
    elif 0.4 < bp <= 0.6:        score += 3   # Mid band, neutral
    elif 0.6 < bp <= 0.8:        score += 1   # Near upper, hati-hati
    else:                         score += 0   # At extreme
    
    # Bollinger Squeeze bonus
    if vol.bb_squeeze:
        score += 2   # Squeeze = potensi breakout
    
    return min(score, 10.0)


def _calc_risk_levels(close: float, atr: float, direction: str = "BUY") -> RiskLevels:
    """
    Hitung risk management levels berbasis ATR.
    
    Formula:
        Entry = close
        SL = entry - (ATR_SL_MULT × ATR)  untuk BUY
        TP1 = entry + (ATR_TP1_MULT × ATR)
        TP2 = entry + (ATR_TP2_MULT × ATR)
    
    Position sizing menggunakan 1% risk rule:
        position_size% = 1% / risk%
    """
    if close <= 0 or atr <= 0:
        return RiskLevels(entry_price=close)
    
    sl_mult = settings.atr_sl_multiplier
    tp1_mult = settings.atr_tp1_multiplier
    tp2_mult = settings.atr_tp2_multiplier
    
    entry = close
    
    if direction == "BUY":
        stop_loss = entry - (sl_mult * atr)
        target_1 = entry + (tp1_mult * atr)
        target_2 = entry + (tp2_mult * atr)
    else:
        stop_loss = entry + (sl_mult * atr)
        target_1 = entry - (tp1_mult * atr)
        target_2 = entry - (tp2_mult * atr)
    
    risk_pct = abs(entry - stop_loss) / entry * 100
    reward_tp1 = abs(target_1 - entry) / entry * 100
    reward_tp2 = abs(target_2 - entry) / entry * 100
    
    rr_tp1 = reward_tp1 / risk_pct if risk_pct > 0 else 0
    rr_tp2 = reward_tp2 / risk_pct if risk_pct > 0 else 0
    
    # Position sizing: risk 1% modal per trade
    position_size_pct = min(25.0, 1.0 / (risk_pct / 100) * 100) if risk_pct > 0 else 5.0
    
    return RiskLevels(
        entry_price=round(entry, 0),
        stop_loss=round(stop_loss, 0),
        target_1=round(target_1, 0),
        target_2=round(target_2, 0),
        risk_pct=round(risk_pct, 2),
        reward_pct_tp1=round(reward_tp1, 2),
        reward_pct_tp2=round(reward_tp2, 2),
        risk_reward_tp1=round(rr_tp1, 2),
        risk_reward_tp2=round(rr_tp2, 2),
        position_size_pct=round(position_size_pct, 1),
    )


def _determine_signal_type(score: float, regime_weight: float, analysis: 'StockAnalysis') -> str:
    """
    Tentukan tipe sinyal berdasarkan composite score dan market regime.
    
    Rules:
        >= 75 dan regime normal: STRONG_BUY
        >= 60: BUY
        >= 45: WATCHLIST
        < 45:  AVOID
    
    Override BEARISH regime:
        Semua sinyal turun 1 level
    """
    adjusted_score = score * regime_weight
    
    # Minimum filter tambahan
    rsi = analysis.momentum.rsi
    volume_ratio = analysis.volume.volume_ratio
    
    # Tidak boleh STRONG_BUY jika RSI overbought atau volume sangat rendah
    if rsi > 75 or volume_ratio < 0.5:
        if adjusted_score >= settings.score_strong_buy:
            adjusted_score = settings.score_buy  # Turunkan satu level
    
    if adjusted_score >= settings.score_strong_buy:
        return "STRONG_BUY"
    elif adjusted_score >= settings.score_buy:
        return "BUY"
    elif adjusted_score >= settings.score_watchlist:
        return "WATCHLIST"
    else:
        return "AVOID"


# ═══════════════════════════════════════════════════════════════════════
#  MAIN ANALYSIS FUNCTION
# ═══════════════════════════════════════════════════════════════════════

def analyze_stock(
    ticker: str,
    df: pd.DataFrame,
    ihsg_close: Optional[pd.Series] = None,
    regime_weight: float = 1.0,
) -> Optional[StockAnalysis]:
    """
    Analisis lengkap satu saham.
    
    Args:
        ticker: Kode saham
        df: DataFrame OHLCV harian (minimal 60 baris)
        ihsg_close: Close price IHSG untuk Relative Strength
        regime_weight: Multiplier dari market regime (0.3-1.0)
    
    Returns:
        StockAnalysis atau None jika data tidak memadai
    """
    if df is None or df.empty or len(df) < 30:
        return None
    
    try:
        from datetime import date as date_type
        
        close = df["close"]
        
        # ── Hitung Semua Indikator ───────────────────────────────
        
        # EMA
        ema20 = calc_ema(close, 20)
        ema50 = calc_ema(close, 50)
        ema200 = calc_ema(close, 200) if len(df) >= 200 else pd.Series([float("nan")] * len(df), index=df.index)
        
        # RSI
        rsi = calc_rsi(close, settings.rsi_period)
        
        # MACD
        macd_line, macd_sig, macd_hist = calc_macd(
            close,
            settings.macd_fast,
            settings.macd_slow,
            settings.macd_signal,
        )
        
        # ADX
        adx, plus_di, minus_di = calc_adx(df, settings.adx_period)
        
        # ATR
        atr = calc_atr(df, settings.atr_period)
        
        # Bollinger Bands
        bb_upper, bb_mid, bb_lower = calc_bollinger(close, 20, 2.0)
        
        # Relative Strength vs IHSG
        if ihsg_close is not None and not ihsg_close.empty:
            rs_series = calc_mansfield_rs(close, ihsg_close, period=20)
        else:
            rs_series = pd.Series([0.0] * len(close), index=close.index)
        
        # ── Extract Nilai Terbaru ────────────────────────────────
        
        def safe_float(series: pd.Series, idx: int = -1) -> float:
            try:
                v = series.iloc[idx]
                return float(v) if pd.notna(v) else 0.0
            except (IndexError, TypeError):
                return 0.0
        
        last_close = safe_float(close)
        last_open = safe_float(df["open"])
        last_volume = safe_float(df["volume"])
        
        # Change pct
        change_pct = 0.0
        if len(close) >= 2:
            prev = safe_float(close, -2)
            if prev > 0:
                change_pct = ((last_close / prev) - 1) * 100
        
        # Pump detection (anti-gorengan) — 3 candle terakhir
        pump_pct = 0.0
        if len(close) >= 4:
            base = safe_float(close, -4)
            if base > 0:
                pump_pct = ((last_close / base) - 1) * 100
        
        # Average volume
        avg_vol_20 = float(df["volume"].tail(20).mean()) if len(df) >= 20 else last_volume
        
        # Volume ratio
        vol_ratio = (last_volume / avg_vol_20) if avg_vol_20 > 0 else 1.0
        
        # Volume trend
        vol_5 = float(df["volume"].tail(5).mean()) if len(df) >= 5 else last_volume
        vol_20 = avg_vol_20
        if vol_5 > vol_20 * 1.8:
            vol_trend = "SURGE"
        elif vol_5 > vol_20 * 1.2:
            vol_trend = "INCREASING"
        elif vol_5 < vol_20 * 0.7:
            vol_trend = "DECLINING"
        else:
            vol_trend = "NORMAL"
        
        # Bollinger position (0=lower, 1=upper)
        bb_low_last = safe_float(bb_lower)
        bb_up_last = safe_float(bb_upper)
        bb_mid_last = safe_float(bb_mid)
        bb_range = bb_up_last - bb_low_last
        bb_pos = (last_close - bb_low_last) / bb_range if bb_range > 0 else 0.5
        
        # Bollinger Squeeze: bandwidth < 5% of mid
        bb_width = bb_range / bb_mid_last if bb_mid_last > 0 else 0
        bb_squeeze = bb_width < 0.05
        
        # ATR%
        last_atr = safe_float(atr)
        atr_pct = (last_atr / last_close * 100) if last_close > 0 else 0
        
        # MACD Cross
        macd_curr = safe_float(macd_line)
        macd_sig_curr = safe_float(macd_sig)
        macd_hist_curr = safe_float(macd_hist)
        macd_hist_prev = safe_float(macd_hist, -2)
        
        if len(macd_hist) >= 2:
            prev_hist = safe_float(macd_hist, -2)
            if prev_hist < 0 and macd_hist_curr > 0:
                macd_cross = "GOLDEN"
            elif prev_hist > 0 and macd_hist_curr < 0:
                macd_cross = "DEATH"
            else:
                macd_cross = "NONE"
        else:
            macd_cross = "NONE"
        
        # EMA alignment
        ema20_last = safe_float(ema20)
        ema50_last = safe_float(ema50)
        ema200_last = safe_float(ema200)
        
        if last_close > ema20_last > ema50_last and ema20_last > ema50_last:
            ema_align = "BULLISH"
        elif last_close < ema20_last < ema50_last:
            ema_align = "BEARISH"
        else:
            ema_align = "NEUTRAL"
        
        # Price vs EMA pct
        price_vs_ema20 = ((last_close / ema20_last) - 1) * 100 if ema20_last > 0 else 0
        price_vs_ema50 = ((last_close / ema50_last) - 1) * 100 if ema50_last > 0 else 0
        price_vs_ema200 = ((last_close / ema200_last) - 1) * 100 if ema200_last > 0 else 0
        
        # Relative Strength
        rs_last = safe_float(rs_series)
        rs_trend = "OUTPERFORM" if rs_last > 5 else ("UNDERPERFORM" if rs_last < -5 else "NEUTRAL")
        
        # ADX values
        adx_last = safe_float(adx)
        plus_di_last = safe_float(plus_di)
        minus_di_last = safe_float(minus_di)
        trend_strength = (
            "STRONG" if adx_last >= 30 else
            "MODERATE" if adx_last >= 20 else
            "WEAK"
        )
        
        # ── Build Analysis Object ───────────────────────────────
        
        analysis = StockAnalysis(
            ticker=ticker,
            analysis_date=date_type.today().isoformat(),
            close=last_close,
            open_price=last_open,
            change_pct=round(change_pct, 2),
            pump_pct_3c=round(pump_pct, 2),
            trend=TrendIndicators(
                ema20=round(ema20_last, 2),
                ema50=round(ema50_last, 2),
                ema200=round(ema200_last, 2),
                price_vs_ema20=round(price_vs_ema20, 2),
                price_vs_ema50=round(price_vs_ema50, 2),
                price_vs_ema200=round(price_vs_ema200, 2),
                ema_alignment=ema_align,
            ),
            momentum=MomentumIndicators(
                rsi=round(safe_float(rsi), 1),
                rsi_prev=round(safe_float(rsi, -2), 1),
                macd_line=round(macd_curr, 6),
                macd_signal=round(macd_sig_curr, 6),
                macd_hist=round(macd_hist_curr, 6),
                macd_hist_prev=round(macd_hist_prev, 6),
                macd_cross=macd_cross,
                rsi_zone=(
                    "OVERSOLD" if safe_float(rsi) < settings.rsi_oversold else
                    "OVERBOUGHT" if safe_float(rsi) > settings.rsi_overbought else
                    "NEUTRAL"
                ),
            ),
            strength=StrengthIndicators(
                adx=round(adx_last, 1),
                plus_di=round(plus_di_last, 1),
                minus_di=round(minus_di_last, 1),
                trend_strength=trend_strength,
                rel_strength=round(rs_last, 2),
                rs_trend=rs_trend,
            ),
            volume=VolumeIndicators(
                volume=last_volume,
                avg_volume_20=avg_vol_20,
                volume_ratio=round(vol_ratio, 2),
                volume_spike=vol_ratio >= settings.volume_spike_threshold,
                volume_trend=vol_trend,
            ),
            volatility=VolatilityIndicators(
                atr=round(last_atr, 2),
                atr_pct=round(atr_pct, 2),
                bb_upper=round(bb_up_last, 2),
                bb_mid=round(bb_mid_last, 2),
                bb_lower=round(bb_low_last, 2),
                bb_width=round(bb_width * 100, 2),
                bb_position=round(bb_pos, 3),
                bb_squeeze=bb_squeeze,
            ),
        )
        
        # ── Scoring ─────────────────────────────────────────────
        
        trend_score = _score_trend(analysis, last_close)
        momentum_score = _score_momentum(analysis)
        volume_score = _score_volume(analysis)
        strength_score = _score_strength(analysis)
        volatility_score = _score_volatility(analysis, last_close)
        
        raw_score = trend_score + momentum_score + volume_score + strength_score + volatility_score
        final_score = raw_score * regime_weight
        
        signal_type = _determine_signal_type(final_score, regime_weight, analysis)
        
        analysis.score = CompositeScore(
            trend_score=round(trend_score, 1),
            momentum_score=round(momentum_score, 1),
            volume_score=round(volume_score, 1),
            strength_score=round(strength_score, 1),
            volatility_score=round(volatility_score, 1),
            raw_score=round(raw_score, 1),
            regime_weight=regime_weight,
            final_score=round(final_score, 1),
            signal_type=signal_type,
        )
        
        # ── Risk Levels ─────────────────────────────────────────
        if signal_type in ("STRONG_BUY", "BUY"):
            analysis.risk = _calc_risk_levels(last_close, last_atr, "BUY")
        elif signal_type == "WATCHLIST":
            analysis.risk = _calc_risk_levels(last_close, last_atr, "BUY")  # Indicative
        
        return analysis
        
    except Exception as e:
        log.error(f"Analisis gagal untuk {ticker}: {e}", exc=e)
        return None


def apply_basic_filters(analysis: StockAnalysis) -> StockAnalysis:
    """
    Apply filter dasar untuk menyaring saham tidak layak.
    Modifikasi analysis object in-place.
    """
    reason = None
    
    # Harga minimum
    if analysis.close < settings.min_price:
        reason = f"Harga Rp{analysis.close:.0f} < minimum Rp{settings.min_price:.0f}"
    
    # Volume minimum
    elif analysis.volume.volume < settings.min_volume:
        reason = f"Volume {analysis.volume.volume:,.0f} < minimum {settings.min_volume:,}"
    
    # Anti pump/gorengan
    elif analysis.pump_pct_3c > settings.max_pump_pct:
        reason = f"Pump {analysis.pump_pct_3c:.1f}% dalam 3 candle (gorengan)"
    
    # Tidak ada data EMA (data terlalu sedikit)
    elif analysis.trend.ema20 <= 0:
        reason = "Data tidak cukup untuk hitung EMA"
    
    if reason:
        analysis.passed_basic_filter = False
        analysis.filter_fail_reason = reason
        analysis.score.signal_type = "AVOID"
    
    return analysis
