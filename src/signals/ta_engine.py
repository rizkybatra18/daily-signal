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
from src.signals.pattern_engine import detect_trend_structure

log = get_logger("ta_engine")


# ═══════════════════════════════════════════════════════════════════════
#  SCORE CAPS (v2.5.0, 2026-08)
#  SATU tempat sumber kebenaran untuk cap tiap komponen composite score.
#  Dulu tiap kali cap berubah (co. trend_score 30->20), angka hardcoded-nya
#  tersebar & ada yang lupa disesuaikan (lihat AUDIT di bot.py/dashboard.py
#  yang sempat ketinggalan). SEKARANG: ubah cap DI SINI SAJA, tempat lain
#  (highlight threshold, tampilan dashboard, telegram) import konstanta
#  ini, TIDAK boleh hardcode ulang angkanya.
# ═══════════════════════════════════════════════════════════════════════
TREND_SCORE_CAP      = 22.0   # SEBELUMNYA 30, lalu 20 -- lihat AUDIT CompositeScore
MOMENTUM_SCORE_CAP   = 25.0
VOLUME_SCORE_CAP     = 20.0
STRENGTH_SCORE_CAP   = 21.0
VOLATILITY_SCORE_CAP = 2.0    # SEBELUMNYA 10, lalu 4 -- lihat AUDIT CompositeScore
FLOW_SCORE_CAP       = 10.0   # BARU
TOTAL_SCORE_CAP      = (TREND_SCORE_CAP + MOMENTUM_SCORE_CAP + VOLUME_SCORE_CAP +
                         STRENGTH_SCORE_CAP + VOLATILITY_SCORE_CAP + FLOW_SCORE_CAP)
assert TOTAL_SCORE_CAP == 100.0, f"Total cap harus 100, sekarang {TOTAL_SCORE_CAP}"


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
    structure: Optional[str] = None  # BARU (v2.5.0) -- dari pattern_engine.detect_trend_structure()


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
class FlowIndicators:
    """
    Proxy bandarmology GRATIS -- dihitung murni dari OHLCV yang sudah
    ada (Yahoo Finance), TANPA data broker/institusi sungguhan. Bukan
    pengganti broker summary asli (lihat src/providers/broker_data.py,
    belum ada provider), tapi price-volume relationship yang secara
    metodologis dipakai luas (OBV oleh Joseph Granville, A/D Line +
    CMF oleh Marc Chaikin, VSA oleh Tom Williams) untuk menaksir apakah
    volume yang terjadi mencerminkan akumulasi atau distribusi.
    """
    obv: float = 0.0
    obv_slope_pct: float = 0.0      # % perubahan OBV vs 10 hari lalu -- arah akumulasi
    ad_line: float = 0.0            # Accumulation/Distribution Line (cumulative)
    cmf: float = 0.0                # Chaikin Money Flow, 20 hari, range -1..+1
    mfi: float = 50.0               # Money Flow Index, 14 hari, range 0..100
    vsa_signal: str = "NEUTRAL"     # ACCUMULATION/DISTRIBUTION/CLIMAX_UP/CLIMAX_DOWN/NO_DEMAND/NEUTRAL


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

    Formula (v2.4.0 -- lihat AUDIT di bawah untuk alasan trend_score
    dipotong & flow_score baru ditambahkan):
        trend_score     = 0-22  (EMA alignment + structure -- SEBELUMNYA 0-30, lalu 0-20)
        momentum_score  = 0-25  (RSI zone, MACD direction)
        volume_score    = 0-20  (volume ratio, spike)
        strength_score  = 0-21  (ADX, relative strength)
        volatility_score= 0-2   (ATR position, BB squeeze -- SEBELUMNYA 0-10, lalu 0-4)
        flow_score      = 0-10  (proxy bandarmology gratis dari OBV/CMF/MFI/VSA)
        ─────────────────────────
        Total           = 0-100

    AUDIT (trend_score dipotong 30->20, 2026-08, lihat analisis
    signal_results n=265, 27 Jul-7 Aug 2026): trend_score BERKORELASI
    NEGATIF dengan net_return_pct aktual (kuartil terendah->tertinggi:
    +9.2% -> +8.5% -> +4.6% -> +4.8%). Sample masih dari 1 live stream
    yang sama dgn audit strength/volatility_score sebelumnya (bukan
    sample independen baru), dan 93.5% masih regime BULL -- JANGAN
    balik arah formulanya dulu (logic internal EMA-alignment tidak
    terbukti salah, bisa jadi cuma redundan dgn strength_score/ADX),
    cukup diskon bobotnya dulu mengikuti pola volatility_score. 10 poin
    yang dipotong dipindah ke flow_score (baru) -- BUKAN redistribusi
    ke trend_score sendiri. Re-validasi berkala lewat dashboard Score
    Calibration seiring data live bertambah (target >=300 sinyal,
    idealnya juga cakupan regime SIDEWAYS/BEAR yang sekarang minim).

    AUDIT (Adaptive Threshold): raw_score (+ sector_bonus, sebelum
    dikali regime_weight) yang dipakai untuk klasifikasi signal_type,
    BUKAN final_score — lihat _determine_signal_type(). final_score
    tetap dihitung untuk tampilan (dashboard/telegram) apa adanya.
    """
    trend_score: float = 0.0
    momentum_score: float = 0.0
    volume_score: float = 0.0
    strength_score: float = 0.0
    volatility_score: float = 0.0
    flow_score: float = 0.0
    raw_score: float = 0.0          # Sum sebelum regime adjustment (+ sector bonus)
    sector_bonus: float = 0.0        # +5/-5/0 dari sector rotation, sudah masuk raw_score
    regime_weight: float = 1.0       # Multiplier dari market regime (untuk display)
    final_score: float = 0.0         # raw_score × regime_weight (TIDAK dipakai klasifikasi lagi)
    confidence: str = "Low"          # Very High / High / Medium / Low — lihat compute_confidence()
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
    flow: FlowIndicators = field(default_factory=FlowIndicators)
    risk: RiskLevels = field(default_factory=RiskLevels)
    score: CompositeScore = field(default_factory=CompositeScore)
    factor_contribution: dict = field(default_factory=dict)   # lihat build_factor_contribution()

    # Flags
    passed_basic_filter: bool = True
    filter_fail_reason: Optional[str] = None

    def to_dict(self) -> dict:
        """
        Convert ke flat dict untuk database insert.
        Kolom harus PERSIS match dengan schema tabel signals di Supabase.
        Kolom BARU (confidence, raw_score, sector_bonus, factor_contribution)
        butuh migration 002 — jika belum dijalankan, save_signal() otomatis
        toleran dan melewati kolom yang belum ada (lihat database.py).
        """
        return {
            # === WAJIB (NOT NULL) ===
            "ticker":      self.ticker,
            "signal_type": self.score.signal_type,
            # signal_date diisi oleh scanner.py, bukan di sini

            # === PRICE ===
            "close_price": self.close,

            # === TREND (kolom: ema20, ema50, ema200) ===
            "ema20":  self.trend.ema20,
            "ema50":  self.trend.ema50,
            "ema200": self.trend.ema200,
            "trend_structure": self.trend.structure,   # BARU (v2.5.0)

            # === MOMENTUM ===
            "rsi":         self.momentum.rsi,
            "macd_line":   self.momentum.macd_line,
            "macd_signal": self.momentum.macd_signal,
            "macd_hist":   self.momentum.macd_hist,

            # === STRENGTH ===
            "adx":          self.strength.adx,
            "rel_strength": self.strength.rel_strength,

            # === VOLUME ===
            "volume":       int(self.volume.volume),
            "avg_volume_20":int(self.volume.avg_volume_20),
            "volume_ratio": self.volume.volume_ratio,

            # === VOLATILITY ===
            "atr": self.volatility.atr,

            # === FLOW (BARU -- proxy bandarmology gratis, migration 005) ===
            "obv":            self.flow.obv,
            "obv_slope_pct":  self.flow.obv_slope_pct,
            "ad_line":        self.flow.ad_line,
            "cmf":            self.flow.cmf,
            "mfi":            self.flow.mfi,
            "vsa_signal":     self.flow.vsa_signal,
            "flow_score":     self.score.flow_score,

            # === RISK MANAGEMENT ===
            "entry_price":  self.risk.entry_price,
            "stop_loss":    self.risk.stop_loss,
            "target_1":     self.risk.target_1,
            "target_2":     self.risk.target_2,
            "risk_reward":  self.risk.risk_reward_tp1,
            "position_risk":self.risk.risk_pct,

            # === SCORE BREAKDOWN ===
            "composite_score":  self.score.final_score,
            "trend_score":      self.score.trend_score,
            "momentum_score":   self.score.momentum_score,
            "volume_score":     self.score.volume_score,
            "strength_score":   self.score.strength_score,
            "volatility_score": self.score.volatility_score,

            # === Adaptive Threshold / Confidence / Factor Contribution ===
            # (butuh migration 002 — lihat migrations/002_audit_improvements.sql)
            "raw_score":     self.score.raw_score,
            "sector_bonus":  self.score.sector_bonus,
            "confidence":    self.score.confidence,
            "factor_contribution": self.factor_contribution,

            # market_regime, sector, sector_rank diisi oleh scanner.py
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

    plus_dm = (high - prev_high).clip(lower=0)
    minus_dm = (prev_low - low).clip(lower=0)

    mask = plus_dm == minus_dm
    plus_dm[mask] = 0
    minus_dm[mask] = 0

    plus_dm[plus_dm < minus_dm] = 0
    minus_dm[minus_dm < plus_dm] = 0

    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)

    atr_smooth = tr.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    plus_dm_smooth = plus_dm.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    minus_dm_smooth = minus_dm.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()

    plus_di = 100 * (plus_dm_smooth / atr_smooth.replace(0, np.nan))
    minus_di = 100 * (minus_dm_smooth / atr_smooth.replace(0, np.nan))

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

    common_idx = close.index.intersection(benchmark_close.index)
    if len(common_idx) < period:
        return pd.Series([0.0] * len(close), index=close.index)

    stock_aligned = close.reindex(common_idx)
    bench_aligned = benchmark_close.reindex(common_idx)

    stock_return = stock_aligned.pct_change(period)
    bench_return = bench_aligned.pct_change(period)

    rs = ((1 + stock_return) / (1 + bench_return.replace(0, np.nan)) - 1) * 100

    return rs.reindex(close.index, fill_value=0)


# ═══════════════════════════════════════════════════════════════════════
#  INDIKATOR FLOW / BANDARMOLOGI-PROXY (BARU, migration 005)
#  Semua murni dari OHLCV -- GRATIS, tidak butuh data broker. Lihat
#  FlowIndicators docstring untuk atribusi metodologi.
# ═══════════════════════════════════════════════════════════════════════

def calc_obv(close: pd.Series, volume: pd.Series) -> pd.Series:
    """
    On-Balance Volume (Joseph Granville, 1963).
    Volume ditambahkan penuh saat harga naik, dikurangi penuh saat
    turun, netral saat flat. Cumulative -- yang penting SLOPE-nya
    (lihat calc_obv_slope_pct), bukan nilai absolutnya.
    """
    direction = np.sign(close.diff().fillna(0))
    return (direction * volume).fillna(0).cumsum()


def calc_obv_slope_pct(obv: pd.Series, period: int = 10) -> pd.Series:
    """% perubahan OBV vs N hari lalu -- proxy arah akumulasi/distribusi jangka pendek."""
    obv_prev = obv.shift(period)
    denom = obv_prev.abs().replace(0, np.nan)
    return ((obv - obv_prev) / denom * 100).fillna(0)


def calc_ad_line(df: pd.DataFrame) -> pd.Series:
    """
    Accumulation/Distribution Line (Marc Chaikin).
    Money Flow Multiplier = ((close-low) - (high-close)) / (high-low)
    -- posisi close dalam range hari itu, -1 (close=low) s/d +1 (close=high).
    Dikali volume, cumulative.
    """
    high, low, close, volume = df["high"], df["low"], df["close"], df["volume"]
    rng = (high - low).replace(0, np.nan)
    mfm = (((close - low) - (high - close)) / rng).fillna(0)
    return (mfm * volume).cumsum()


def calc_cmf(df: pd.DataFrame, period: int = 20) -> pd.Series:
    """
    Chaikin Money Flow: rolling sum(Money Flow Volume) / rolling sum(Volume).
    Range -1..+1. Beda dari A/D Line (cumulative) -- CMF ini OSCILLATOR,
    lebih gampang dipakai threshold di scoring.
    """
    high, low, close, volume = df["high"], df["low"], df["close"], df["volume"]
    rng = (high - low).replace(0, np.nan)
    mfm = (((close - low) - (high - close)) / rng).fillna(0)
    mfv = mfm * volume
    return (mfv.rolling(period, min_periods=max(5, period // 2)).sum() /
            volume.rolling(period, min_periods=max(5, period // 2)).sum().replace(0, np.nan)).fillna(0)


def calc_mfi(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """
    Money Flow Index -- RSI yang volume-weighted. Range 0-100.
    Typical Price = (H+L+C)/3, Raw Money Flow = TP × Volume.
    """
    high, low, close, volume = df["high"], df["low"], df["close"], df["volume"]
    tp = (high + low + close) / 3
    raw_mf = tp * volume

    tp_diff = tp.diff()
    pos_mf = raw_mf.where(tp_diff > 0, 0.0)
    neg_mf = raw_mf.where(tp_diff < 0, 0.0)

    pos_sum = pos_mf.rolling(period, min_periods=max(5, period // 2)).sum()
    neg_sum = neg_mf.rolling(period, min_periods=max(5, period // 2)).sum()

    mfr = pos_sum / neg_sum.replace(0, np.nan)
    mfi = 100 - (100 / (1 + mfr))
    return mfi.fillna(50.0)


def calc_vsa_signal(df: pd.DataFrame, period: int = 20) -> pd.Series:
    """
    Klasifikasi bar ala Volume Spread Analysis (Tom Williams / Wyckoff).
    Bandingkan volume & range hari ini vs rata-rata N hari, plus posisi
    close dalam range hari itu, untuk menaksir siapa yang "menang" --
    pembeli besar menyerap jualan (ACCUMULATION) atau sebaliknya
    (DISTRIBUTION), atau tanda exhaustion (CLIMAX_UP/DOWN), atau rally
    lemah tanpa partisipasi volume (NO_DEMAND).

    INI HEURISTIK, bukan sinyal pasti -- dipakai sebagai salah satu
    input _score_flow(), bukan berdiri sendiri.
    """
    high, low, close, volume = df["high"], df["low"], df["close"], df["volume"]
    rng = high - low
    avg_range = rng.rolling(period, min_periods=max(5, period // 2)).mean()
    avg_vol = volume.rolling(period, min_periods=max(5, period // 2)).mean()
    close_pos = ((close - low) / rng.replace(0, np.nan)).fillna(0.5)
    price_up = close.diff() > 0

    vol_ratio = volume / avg_vol.replace(0, np.nan)
    range_ratio = rng / avg_range.replace(0, np.nan)

    result = pd.Series("NEUTRAL", index=df.index)

    climax_mask = (vol_ratio > 2.5) & (range_ratio > 1.5)
    result[climax_mask & (close_pos > 0.6)] = "CLIMAX_UP"
    result[climax_mask & (close_pos < 0.4)] = "CLIMAX_DOWN"

    absorb_mask = (vol_ratio > 1.5) & (range_ratio < 1.2) & ~climax_mask
    result[absorb_mask & (close_pos > 0.6)] = "ACCUMULATION"
    result[absorb_mask & (close_pos < 0.4)] = "DISTRIBUTION"

    no_demand_mask = (vol_ratio < 0.7) & price_up & ~climax_mask & ~absorb_mask
    result[no_demand_mask] = "NO_DEMAND"

    return result


# ═══════════════════════════════════════════════════════════════════════
#  COMPOSITE SCORING ENGINE
# ═══════════════════════════════════════════════════════════════════════

def _score_trend(analysis: StockAnalysis, close: float) -> float:
    """
    Trend Score: 0-22 poin (v2.5.0 -- SEBELUMNYA 0-30, lalu 0-20, lihat
    AUDIT di CompositeScore docstring). +2 poin BARU dari trend_structure
    (pattern_engine.detect_trend_structure) -- evidence: signal_results
    n=368 (update 10 Agu 2026), trend_structure="Pullback" avg return
    +8.9% (n=95, WR 89.5%) vs "Breakout" +4.0% (n=23, WR 82.6%). Dipindah
    dari 2 poin volatility_score yang dipotong (lihat _score_volatility).

    +8:  EMA full alignment (close > EMA20 > EMA50 > EMA200)
    +5:  Partial alignment (close > EMA20 > EMA50)
    +3:  Minimal (close > EMA20)
    +5:  Strong EMA20 gap (close > EMA20 by >2%)
    +4:  Positive momentum (EMA20 trending up)
    +3:  Medium-term uptrend (EMA50 > EMA200)
    +2:  Structure bonus (BARU) -- Pullback/Higher Low = +2, Consolidation = +1,
         Higher High/Breakout = 0, Lower High/Lower Low = -1
    """
    score = 0.0
    t = analysis.trend

    if close > t.ema20 > t.ema50 > t.ema200 > 0:
        score += 8
    elif close > t.ema20 > t.ema50 > 0:
        score += 5
    elif close > t.ema20 > 0:
        score += 3

    if t.ema20 > 0:
        gap_pct = (close - t.ema20) / t.ema20 * 100
        if 0 < gap_pct <= 5:     score += 5
        elif 5 < gap_pct <= 10:  score += 3
        elif gap_pct > 10:       score += 1
        elif -2 < gap_pct <= 0:  score += 2

    if t.ema50 > t.ema200 > 0:
        score += 4
    elif t.ema50 > 0 and t.ema200 > 0 and t.ema50 > t.ema200 * 0.98:
        score += 2

    if t.price_vs_ema20 > 1:
        score += 3
    elif t.price_vs_ema20 > 0:
        score += 1

    structure_bonus = {
        "Pullback": 2, "Higher Low": 2,
        "Consolidation": 1,
        "Higher High": 0, "Breakout": 0,
        "Lower High": -1, "Lower Low": -1,
    }.get(t.structure or "", 0)
    score += structure_bonus

    return max(0.0, min(score, TREND_SCORE_CAP))


def _score_momentum(analysis: StockAnalysis) -> float:
    """
    Momentum Score: 0-25 poin

    RSI: 0-12 poin
    MACD: 0-13 poin
    """
    score = 0.0
    m = analysis.momentum

    rsi = m.rsi
    if 40 <= rsi <= 60:      score += 12
    elif 30 <= rsi < 40:     score += 10
    elif 60 < rsi <= 65:     score += 8
    elif 65 < rsi <= 70:     score += 5
    elif rsi < 30:           score += 6
    elif rsi > 70:           score += 2

    if m.rsi > m.rsi_prev and rsi < 70:
        score += 2

    if m.macd_hist > 0:
        score += 8
        if m.macd_hist > m.macd_hist_prev:
            score += 2
    elif m.macd_hist > -0.001:
        score += 4

    if m.macd_cross == "GOLDEN":
        score += 5
    elif m.macd_line > m.macd_signal:
        score += 3

    return min(score, MOMENTUM_SCORE_CAP)


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

    if ratio >= 2.0:        score += 15
    elif ratio >= 1.5:      score += 10
    elif ratio >= 1.2:      score += 7
    elif ratio >= 1.0:      score += 4
    elif ratio >= 0.7:      score += 2
    else:                   score += 0

    if v.volume_trend == "SURGE":      score += 5
    elif v.volume_trend == "INCREASING": score += 3

    return min(score, VOLUME_SCORE_CAP)


def _score_strength(analysis: StockAnalysis) -> float:
    """
    Strength Score: 0-21 poin (SEBELUMNYA 0-15 -- naik 6 poin, dipindah
    dari volatility_score yang dipotong, lihat _score_volatility di bawah)

    ADX: 0-8 poin (kekuatan tren, arah belum diperhitungkan)
    DI Quality (BARU): -3..+6 poin (arah tren, dari +DI/-DI)
    Relative Strength vs IHSG: 0-7 poin

    AUDIT (data 63 sinyal live, 27-31 Jul 2026; RE-VALIDASI di n=140,
    27 Jul-4 Aug 2026, lihat signal_results): plus_di/minus_di sudah
    dihitung & disimpan sejak lama tapi TIDAK PERNAH dipakai di scoring.
    Empiris (n=140): minus_di<10 -> 89.3% win / avg return +11.5%.
    minus_di>20 -> cuma 65.0% win / avg return +2.8%. Efeknya melunak
    dibanding estimasi awal n=63 (dulu 90%/+15.5% vs 45.5%/-0.29%) tapi
    ARAHNYA TETAP KONSISTEN & masih beda jauh antar bucket -- ADX tinggi
    + minus_di tinggi = tren KUAT tapi ARAHNYA TURUN, itu red flag,
    bukan alasan nambah skor beli, jadi ADX-nya di-discount kalau itu
    terjadi. Re-validasi berkala lewat dashboard Score Calibration
    seiring data live bertambah (target >=300 sinyal).
    """
    score = 0.0
    s = analysis.strength

    adx = s.adx
    if adx >= 40:           adx_pts = 8.0
    elif adx >= 30:         adx_pts = 6.0
    elif adx >= 25:         adx_pts = 4.0
    elif adx >= 20:         adx_pts = 2.0
    else:                   adx_pts = 0.0

    plus_di, minus_di = s.plus_di, s.minus_di
    if minus_di > 20 or minus_di > plus_di:
        # Tekanan jual dominan -> ADX tinggi mengukur kekuatan tren TURUN.
        adx_pts = min(adx_pts, 2.0)
    score += adx_pts

    if minus_di < 10 and plus_di > minus_di:
        score += 6
    elif minus_di < 15 and plus_di > minus_di:
        score += 3
    elif minus_di > 20:
        score -= 3

    rs = s.rel_strength
    if rs >= 10:            score += 7
    elif rs >= 5:           score += 5
    elif rs >= 0:           score += 3
    elif rs >= -5:          score += 1
    else:                   score += 0

    return max(0.0, min(score, STRENGTH_SCORE_CAP))


def _score_volatility(analysis: StockAnalysis, close: float) -> float:
    """
    Volatility Score: 0-2 poin (v2.5.0 -- SEBELUMNYA 0-10, lalu 0-4,
    sekarang dipotong lagi jadi 0-2. 2 poin yang dipotong dipindah ke
    trend_score sebagai structure bonus, lihat _score_trend.)

    ATR%: moderately volatile dianggap lebih baik dari sangat volatile
    Bollinger Position: near lower band = potensi rebound

    AUDIT (n=63, 27-31 Jul: rho=-0.50 → n=140, 27 Jul-4 Aug: rho=-0.45
    → n=368, 27 Jul-10 Aug 2026: rho=-0.42, p<0.0001): volatility_score
    KONSISTEN jadi prediktor terkuat/salah satu terkuat di SELURUH TIGA
    sample yang makin besar, arahnya TETAP TERBALIK dari desain, dan
    magnitudonya STABIL (-0.50 -> -0.45 -> -0.42, bukan meluruh ke nol)
    -- ini pola nyata, bukan noise sample kecil. Preferensi ATR%/BB-
    position di bawah TETAP belum diubah arahnya (masih belum divalidasi
    per-komponen), bobotnya yang terus didiskon. JANGAN naikkan bobot
    ini lagi tanpa re-validasi lewat Score Calibration di dashboard.
    """
    score = 0.0
    vol = analysis.volatility

    atr_pct = vol.atr_pct
    if 1.0 <= atr_pct <= 4.0:    score += 1.0
    elif 0.5 <= atr_pct < 1.0:   score += 0.5
    elif 4.0 < atr_pct <= 6.0:   score += 0.5
    else:                          score += 0

    bp = vol.bb_position
    if 0.1 <= bp <= 0.4:         score += 1.0
    elif 0.4 < bp <= 0.6:        score += 0.5
    else:                          score += 0

    return min(score, VOLATILITY_SCORE_CAP)


def _score_flow(analysis: StockAnalysis) -> float:
    """
    Flow Score: 0-10 poin (BARU, migration 005) -- proxy bandarmology
    gratis dari OBV/CMF/MFI/VSA (lihat FlowIndicators). 10 poin ini
    dipindah dari trend_score yang dipotong (lihat AUDIT di
    CompositeScore), BUKAN nambah total cap 100.

    BELUM ADA VALIDASI EMPIRIS (indikator baru, belum ada di
    signal_results historis) -- bobot 0-10 ini kecil SENGAJA supaya
    dampak ke raw_score kalau ternyata meleset juga kecil. Re-validasi
    lewat dashboard Score Calibration begitu signal_results terisi
    data dengan kolom flow_score (perlu minimal beberapa minggu live).

    CMF: 0-4 poin | OBV slope: 0-3 poin | MFI: 0-2 poin | VSA: -2..+1 poin
    """
    score = 0.0
    f = analysis.flow

    if f.cmf > 0.15:        score += 4
    elif f.cmf > 0.05:      score += 2
    elif f.cmf > -0.05:     score += 1
    else:                    score += 0

    if f.obv_slope_pct > 5:      score += 3
    elif f.obv_slope_pct > 0:    score += 1

    mfi = f.mfi
    if 40 <= mfi <= 75:      score += 2
    elif 30 <= mfi < 40:     score += 1
    elif mfi > 85:           score += 0

    if f.vsa_signal == "ACCUMULATION":   score += 1
    elif f.vsa_signal == "DISTRIBUTION": score -= 2
    elif f.vsa_signal == "NO_DEMAND":    score -= 1
    elif f.vsa_signal == "CLIMAX_UP":    score -= 1  # potensi exhaustion, bukan alasan beli

    return max(0.0, min(score, FLOW_SCORE_CAP))


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


def _determine_signal_type(raw_score: float, regime: str, analysis: 'StockAnalysis') -> str:
    """
    Tentukan tipe sinyal berdasarkan RAW composite score (0-100, SEBELUM
    dikalikan regime_weight) dan threshold adaptif per regime market.

    ═══════════════════════════════════════════════════════════════════
    AUDIT FINDING & FIX (Adaptive Threshold, lihat AUDIT_REPORT_v2.md):
    ═══════════════════════════════════════════════════════════════════
    Implementasi SEBELUMNYA membandingkan (raw_score × regime_weight)
    terhadap threshold TETAP (75/60/45). Karena regime_weight untuk
    BEAR=0.4, secara matematis TIDAK ADA raw_score (maks 100) yang bisa
    menghasilkan adjusted_score >= 45 (0.4×100=40 < 45) — artinya BEAR
    membuat SEMUA saham otomatis AVOID, tanpa kecuali, walau skornya
    sempurna. Untuk SIDEWAYS (weight=0.75), STRONG_BUY nyaris mustahil
    (butuh raw>=100, yaitu skor sempurna literal).

    Fix: threshold kini beradaptasi per regime dan dibandingkan
    terhadap RAW score (bukan raw×weight):
        BULL     : STRONG_BUY>=75  BUY>=60  WATCHLIST>=45  (baseline, TIDAK berubah)
        SIDEWAYS : STRONG_BUY>=82  BUY>=68  WATCHLIST>=55  (lebih ketat, tapi TERCAPAI)
        BEAR     : STRONG_BUY>=90  BUY>=80  WATCHLIST>=68  (sangat ketat, tapi TIDAK MUSTAHIL)

    final_score (raw×weight) TETAP dihitung & ditampilkan apa adanya
    di dashboard/telegram — tidak ada perubahan makna kolom itu. Hanya
    KEPUTUSAN KLASIFIKASI yang kini pakai raw_score + threshold adaptif.
    """
    thresholds = settings.adaptive_thresholds.get(regime, settings.adaptive_thresholds["BULL"])

    score = raw_score

    rsi = analysis.momentum.rsi
    volume_ratio = analysis.volume.volume_ratio

    if rsi > 75 or volume_ratio < 0.5:
        if score >= thresholds["strong_buy"]:
            score = thresholds["buy"]

    if score >= thresholds["strong_buy"]:
        return "STRONG_BUY"
    elif score >= thresholds["buy"]:
        return "BUY"
    elif score >= thresholds["watchlist"]:
        return "WATCHLIST"
    else:
        return "AVOID"


def compute_confidence(raw_score: float, analysis: 'StockAnalysis') -> str:
    """
    Confidence Engine — RULE-BASED (bukan Machine Learning).

    Confidence bukan sekadar pembulatan dari raw_score, tapi kombinasi:
      1. Level raw_score itu sendiri
      2. Berapa BANYAK dimensi (trend/momentum/volume/strength) yang
         benar-benar KUAT secara independen (bukan cuma total tinggi
         karena satu dimensi dominan menutupi dimensi lain yang lemah)

    Return: "Very High" | "High" | "Medium" | "Low"

    AUDIT (2026-08, ditemukan saat integrasi flow_score): cap di `dims`
    di bawah SUDAH BASI sebelum perubahan sesi ini pun -- strength_score
    ditulis 15.0 padahal cap sebenarnya sudah 21 sejak audit DI-quality
    sebelumnya (lihat _score_strength). Akibatnya strong_dims dihitung
    dari rasio yang salah (penyebut kegedean -> systematically under-
    count). Diperbaiki: pakai konstanta cap yang sama dengan _score_*,
    BUKAN angka hardcoded lagi (lihat SCORE CAPS di atas modul ini).
    """
    dims = [
        (analysis.score.trend_score, TREND_SCORE_CAP),
        (analysis.score.momentum_score, MOMENTUM_SCORE_CAP),
        (analysis.score.volume_score, VOLUME_SCORE_CAP),
        (analysis.score.strength_score, STRENGTH_SCORE_CAP),
    ]
    strong_dims = sum(1 for val, mx in dims if mx > 0 and (val / mx) >= 0.70)

    if raw_score >= settings.confidence_very_high and strong_dims >= 3:
        return "Very High"
    elif raw_score >= settings.confidence_high and strong_dims >= 2:
        return "High"
    elif raw_score >= settings.confidence_medium:
        return "Medium"
    else:
        return "Low"


def build_factor_contribution(analysis: 'StockAnalysis', sector_bonus: float = 0.0) -> dict:
    """
    Susun breakdown kontribusi setiap faktor ke composite score, siap
    dipakai Dashboard/Telegram untuk menjelaskan "Kenapa saham ini
    mendapat skor tinggi?" — data ini disimpan sebagai JSONB.
    """
    s = analysis.score
    highlights = []

    # Threshold di-skala ulang mengikuti pemotongan trend_score 30->20
    # (2026-08, lihat AUDIT di CompositeScore) -- 24/30 lama = 16/20 baru.
    # Threshold dinamis (TREND_SCORE_CAP × 0.8) -- BUKAN hardcoded lagi,
    # supaya tidak ketinggalan lagi kalau cap berubah (lihat AUDIT v2
    # di backtest/engine.py soal kenapa hardcoding ini bahaya).
    if s.trend_score >= TREND_SCORE_CAP * 0.8:
        highlights.append("EMA Alignment kuat")
    if analysis.volume.volume_spike:
        highlights.append(f"Volume Spike {analysis.volume.volume_ratio:.1f}x")
    if analysis.strength.rel_strength > 5:
        highlights.append("Outperform IHSG (RS positif)")
    if analysis.momentum.macd_cross == "GOLDEN":
        highlights.append("MACD Golden Cross")

    minus_di = analysis.strength.minus_di
    plus_di = analysis.strength.plus_di
    bearish_dominant = minus_di > 20 or minus_di > plus_di
    if analysis.strength.adx >= 25 and not bearish_dominant:
        highlights.append(f"Trend kuat (ADX {analysis.strength.adx:.0f})")
    # AUDIT (n=63 -> re-validasi n=140, 27 Jul-4 Aug 2026): minus_di>20
    # avg return +2.8% vs +11.5% saat minus_di<10 -- lihat _score_strength().
    if bearish_dominant:
        highlights.append(f"⚠️ Tekanan Jual Dominan (DI- {minus_di:.0f})")
    elif minus_di < 10 and plus_di > minus_di:
        highlights.append("DI Bullish Sehat (DI- rendah)")
    if sector_bonus > 0:
        highlights.append("Sektor sedang memimpin")

    # Flow (BARU) -- lihat AUDIT flow_score, belum tervalidasi empiris
    if analysis.flow.vsa_signal == "ACCUMULATION":
        highlights.append("Pola VSA: Akumulasi")
    elif analysis.flow.vsa_signal == "DISTRIBUTION":
        highlights.append("⚠️ Pola VSA: Distribusi")
    elif analysis.flow.vsa_signal == "NO_DEMAND":
        highlights.append("⚠️ Rally Tanpa Volume (No Demand)")
    if analysis.flow.cmf > 0.15:
        highlights.append(f"Money Flow Positif Kuat (CMF {analysis.flow.cmf:.2f})")

    return {
        "trend": round(s.trend_score, 1),
        "momentum": round(s.momentum_score, 1),
        "volume": round(s.volume_score, 1),
        "strength": round(s.strength_score, 1),
        "volatility": round(s.volatility_score, 1),
        "flow": round(s.flow_score, 1),
        "sector_bonus": round(sector_bonus, 1),
        "total_raw": round(s.raw_score, 1),
        "highlights": highlights,
    }


# ═══════════════════════════════════════════════════════════════════════
#  MAIN ANALYSIS FUNCTION
# ═══════════════════════════════════════════════════════════════════════

def _safe_detect_trend_structure(df: pd.DataFrame) -> Optional[str]:
    """
    Wrapper defensif untuk detect_trend_structure (pattern_engine.py) --
    dipakai di analyze_stock() DAN backtest/engine.py supaya keduanya
    identik. Gagal diam-diam (return None) kalau data kurang/error,
    TIDAK boleh bikin seluruh analyze_stock() gagal cuma gara-gara
    struktur trend tidak terklasifikasi.
    """
    try:
        return detect_trend_structure(df)
    except Exception as e:
        log.debug(f"detect_trend_structure gagal: {e}")
        return None


def analyze_stock(
    ticker: str,
    df: pd.DataFrame,
    ihsg_close: Optional[pd.Series] = None,
    regime_weight: float = 1.0,
    regime: str = "BULL",
    sector_bonus: float = 0.0,
) -> Optional[StockAnalysis]:
    """
    Analisis lengkap satu saham.

    Args:
        ticker: Kode saham
        df: DataFrame OHLCV harian (minimal 60 baris)
        ihsg_close: Close price IHSG untuk Relative Strength
        regime_weight: Multiplier dari market regime, dipakai untuk
            `final_score` (nilai TAMPILAN di dashboard/telegram, 0-100).
        regime: Label regime ("BULL"/"SIDEWAYS"/"BEAR"), dipakai untuk
            memilih threshold klasifikasi sinyal yang adaptif — lihat
            _determine_signal_type(). Default "BULL" agar backward
            compatible dengan caller lama yang hanya mengisi regime_weight.
        sector_bonus: +5/-5/0 dari sector rotation (top3/bottom3),
            diterapkan ke RAW score SEBELUM dikalikan regime_weight.

    Returns:
        StockAnalysis atau None jika data tidak memadai
    """
    if df is None or df.empty or len(df) < 30:
        return None

    try:
        from datetime import date as date_type

        close = df["close"]

        # ── Hitung Semua Indikator ───────────────────────────────

        ema20 = calc_ema(close, 20)
        ema50 = calc_ema(close, 50)
        ema200 = calc_ema(close, 200) if len(df) >= 200 else pd.Series([float("nan")] * len(df), index=df.index)

        rsi = calc_rsi(close, settings.rsi_period)

        macd_line, macd_sig, macd_hist = calc_macd(
            close,
            settings.macd_fast,
            settings.macd_slow,
            settings.macd_signal,
        )

        adx, plus_di, minus_di = calc_adx(df, settings.adx_period)

        atr = calc_atr(df, settings.atr_period)

        bb_upper, bb_mid, bb_lower = calc_bollinger(close, 20, 2.0)

        if ihsg_close is not None and not ihsg_close.empty:
            rs_series = calc_mansfield_rs(close, ihsg_close, period=20)
        else:
            rs_series = pd.Series([0.0] * len(close), index=close.index)

        # Flow (BARU) -- murni dari OHLCV, tidak butuh IHSG/data eksternal lain
        obv_series = calc_obv(close, df["volume"])
        obv_slope_series = calc_obv_slope_pct(obv_series, period=10)
        ad_line_series = calc_ad_line(df)
        cmf_series = calc_cmf(df, period=20)
        mfi_series = calc_mfi(df, period=14)
        vsa_series = calc_vsa_signal(df, period=20)

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

        change_pct = 0.0
        if len(close) >= 2:
            prev = safe_float(close, -2)
            if prev > 0:
                change_pct = ((last_close / prev) - 1) * 100

        pump_pct = 0.0
        if len(close) >= 4:
            base = safe_float(close, -4)
            if base > 0:
                pump_pct = ((last_close / base) - 1) * 100

        avg_vol_20 = float(df["volume"].tail(20).mean()) if len(df) >= 20 else last_volume

        vol_ratio = (last_volume / avg_vol_20) if avg_vol_20 > 0 else 1.0

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

        bb_low_last = safe_float(bb_lower)
        bb_up_last = safe_float(bb_upper)
        bb_mid_last = safe_float(bb_mid)
        bb_range = bb_up_last - bb_low_last
        bb_pos = (last_close - bb_low_last) / bb_range if bb_range > 0 else 0.5

        bb_width = bb_range / bb_mid_last if bb_mid_last > 0 else 0
        bb_squeeze = bb_width < 0.05

        last_atr = safe_float(atr)
        atr_pct = (last_atr / last_close * 100) if last_close > 0 else 0

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

        ema20_last = safe_float(ema20)
        ema50_last = safe_float(ema50)
        ema200_last = safe_float(ema200)

        if last_close > ema20_last > ema50_last and ema20_last > ema50_last:
            ema_align = "BULLISH"
        elif last_close < ema20_last < ema50_last:
            ema_align = "BEARISH"
        else:
            ema_align = "NEUTRAL"

        price_vs_ema20 = ((last_close / ema20_last) - 1) * 100 if ema20_last > 0 else 0
        price_vs_ema50 = ((last_close / ema50_last) - 1) * 100 if ema50_last > 0 else 0
        price_vs_ema200 = ((last_close / ema200_last) - 1) * 100 if ema200_last > 0 else 0

        rs_last = safe_float(rs_series)
        rs_trend = "OUTPERFORM" if rs_last > 5 else ("UNDERPERFORM" if rs_last < -5 else "NEUTRAL")

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
                structure=_safe_detect_trend_structure(df),
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
            flow=FlowIndicators(
                obv=round(safe_float(obv_series), 0),
                obv_slope_pct=round(safe_float(obv_slope_series), 2),
                ad_line=round(safe_float(ad_line_series), 0),
                cmf=round(safe_float(cmf_series), 4),
                mfi=round(safe_float(mfi_series), 1),
                vsa_signal=str(vsa_series.iloc[-1]) if len(vsa_series) else "NEUTRAL",
            ),
        )

        # ── Scoring ─────────────────────────────────────────────

        trend_score = _score_trend(analysis, last_close)
        momentum_score = _score_momentum(analysis)
        volume_score = _score_volume(analysis)
        strength_score = _score_strength(analysis)
        volatility_score = _score_volatility(analysis, last_close)
        flow_score = _score_flow(analysis)

        raw_score_base = (trend_score + momentum_score + volume_score +
                           strength_score + volatility_score + flow_score)

        # AUDIT FIX: sector_bonus diterapkan ke RAW score (bukan final_score
        # yang sudah dikalikan regime_weight). Sebelumnya bonus diterapkan
        # setelah pengalian regime_weight, membuat pengaruh bonus tidak
        # konsisten antar regime (proporsinya membesar tak wajar saat BEAR
        # karena base score sudah kecil). Diterapkan ke raw agar konsisten.
        raw_score = max(0.0, min(100.0, raw_score_base + sector_bonus))

        # final_score TETAP raw×weight — nilai TAMPILAN, tidak dipakai
        # untuk klasifikasi sinyal lagi (lihat _determine_signal_type).
        final_score = raw_score * regime_weight

        signal_type = _determine_signal_type(raw_score, regime, analysis)

        analysis.score = CompositeScore(
            trend_score=round(trend_score, 1),
            momentum_score=round(momentum_score, 1),
            volume_score=round(volume_score, 1),
            strength_score=round(strength_score, 1),
            volatility_score=round(volatility_score, 1),
            flow_score=round(flow_score, 1),
            raw_score=round(raw_score, 1),
            sector_bonus=round(sector_bonus, 1),
            regime_weight=regime_weight,
            final_score=round(final_score, 1),
            signal_type=signal_type,
        )

        try:
            analysis.score.confidence = compute_confidence(raw_score, analysis)
        except Exception as e:
            log.warning(f"compute_confidence gagal untuk {ticker}: {e}")
            analysis.score.confidence = "Low"

        try:
            analysis.factor_contribution = build_factor_contribution(analysis, sector_bonus)
        except Exception as e:
            log.warning(f"build_factor_contribution gagal untuk {ticker}: {e}")
            analysis.factor_contribution = {}

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

    if analysis.close < settings.min_price:
        reason = f"Harga Rp{analysis.close:.0f} < minimum Rp{settings.min_price:.0f}"

    elif analysis.volume.volume < settings.min_volume:
        reason = f"Volume {analysis.volume.volume:,.0f} < minimum {settings.min_volume:,}"

    elif analysis.pump_pct_3c > settings.max_pump_pct:
        reason = f"Pump {analysis.pump_pct_3c:.1f}% dalam 3 candle (gorengan)"

    elif analysis.trend.ema20 <= 0:
        reason = "Data tidak cukup untuk hitung EMA"

    if reason:
        analysis.passed_basic_filter = False
        analysis.filter_fail_reason = reason
        analysis.score.signal_type = "AVOID"

    return analysis
