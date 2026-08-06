"""
DAILY SIGNAL — Unit Tests: Pattern & Trend Structure Engine
Coverage: src/signals/pattern_engine.py
"""

import numpy as np
import pandas as pd
import pytest

from src.signals.pattern_engine import (
    detect_trend_structure,
    detect_candlestick_patterns,
    detect_breakout_pattern,
    detect_support_resistance,
    detect_divergence,
    detect_all_patterns,
)


def make_df(closes, highs=None, lows=None, opens=None, volume=None):
    n = len(closes)
    closes = np.array(closes, dtype=float)
    highs = np.array(highs, dtype=float) if highs is not None else closes * 1.01
    lows = np.array(lows, dtype=float) if lows is not None else closes * 0.99
    opens = np.array(opens, dtype=float) if opens is not None else np.roll(closes, 1)
    opens[0] = closes[0]
    volume = np.array(volume, dtype=float) if volume is not None else np.full(n, 1_000_000.0)
    idx = pd.date_range("2026-01-01", periods=n, freq="B")
    return pd.DataFrame(
        {"open": opens, "high": highs, "low": lows, "close": closes, "volume": volume}, index=idx
    )


def zigzag(points, bars_per_leg=8):
    """points: harga di tiap swing (turning point), diinterpolasi linear antar titik."""
    segs = []
    for i in range(len(points) - 1):
        segs.append(np.linspace(points[i], points[i + 1], bars_per_leg, endpoint=False))
    segs.append([points[-1]])
    return np.concatenate(segs)


class TestTrendStructure:
    def test_uptrend_zigzag(self):
        trend = zigzag([100, 95, 110, 103, 122, 114, 135])
        df = make_df(trend)
        result = detect_trend_structure(df, lookback=len(trend))
        assert result in ("Higher High", "Higher Low", "Breakout", "Pullback")

    def test_downtrend_zigzag(self):
        trend = zigzag([135, 140, 114, 122, 103, 110, 95])
        df = make_df(trend)
        result = detect_trend_structure(df, lookback=len(trend))
        assert result in ("Lower Low", "Lower High")

    def test_sharp_breakout(self):
        base = 100 + np.sin(np.linspace(0, 10, 78)) * 2
        side = np.concatenate([base, [108, 116]])
        df = make_df(side)
        assert detect_trend_structure(df, lookback=80) == "Breakout"

    def test_consolidation(self):
        np.random.seed(1)
        flat = 100 + np.random.normal(0, 0.15, 80)
        df = make_df(flat)
        assert detect_trend_structure(df) == "Consolidation"

    def test_insufficient_data_returns_none(self):
        df = make_df([100, 101, 102])
        assert detect_trend_structure(df) is None

    def test_none_input_safe(self):
        assert detect_trend_structure(None) is None


class TestCandlestickPatterns:
    def test_bullish_engulfing(self):
        closes = list(100 + np.random.default_rng(0).normal(0, 0.5, 10))
        opens = list(closes)
        opens[-2], closes[-2] = 105, 102   # candle sebelumnya bearish
        opens[-1], closes[-1] = 101, 107   # candle terakhir bullish, engulf penuh
        df = make_df(closes, opens=opens)
        assert "Bullish Engulfing" in detect_candlestick_patterns(df)

    def test_doji(self):
        closes = list(100 + np.random.default_rng(1).normal(0, 0.5, 10))
        opens = list(closes)
        opens[-1] = closes[-1] + 0.01
        highs = [c + 1 for c in closes]
        lows = [c - 1 for c in closes]
        df = make_df(closes, opens=opens, highs=highs, lows=lows)
        assert "Doji" in detect_candlestick_patterns(df)

    def test_short_data_no_crash(self):
        df = make_df([100, 101])
        assert detect_candlestick_patterns(df) == []

    def test_none_input_safe(self):
        assert detect_candlestick_patterns(None) == []


class TestBreakoutPattern:
    def test_breakout_with_volume_confirmation(self):
        base = 100 + np.sin(np.linspace(0, 10, 78)) * 2
        side = np.concatenate([base, [108, 116]])
        df = make_df(side)
        patterns = detect_breakout_pattern(df, volume_ratio=2.0)
        assert any("Volume Confirmed" in p for p in patterns)

    def test_no_breakout_when_flat(self):
        np.random.seed(2)
        flat = 100 + np.random.normal(0, 0.15, 30)
        df = make_df(flat)
        assert detect_breakout_pattern(df) == []


class TestSupportResistance:
    def test_no_crash_on_short_data(self):
        df = make_df([100, 101, 102])
        assert detect_support_resistance(df) == []


class TestDivergence:
    def test_bullish_divergence(self):
        trend = zigzag([135, 140, 114, 122, 103, 110, 95])  # downtrend harga
        df = make_df(trend)
        n = len(df)
        # RSI naik (higher low) walau harga turun (lower low) -> bullish divergence
        rsi_vals = np.concatenate([np.linspace(30, 25, n // 2), np.linspace(25, 35, n - n // 2)])
        rsi = pd.Series(rsi_vals, index=df.index)
        assert "RSI Bullish Divergence" in detect_divergence(df, rsi, lookback=n)

    def test_mismatched_length_safe(self):
        df = make_df([100, 101, 102, 103, 104])
        rsi = pd.Series([50, 51, 52], index=df.index[:3])
        assert detect_divergence(df, rsi) == []

    def test_none_rsi_safe(self):
        df = make_df([100, 101, 102])
        assert detect_divergence(df, None) == []


class TestDetectAllPatterns:
    def test_no_crash_combined(self):
        trend = zigzag([100, 95, 110, 103, 122, 114, 135])
        df = make_df(trend)
        rsi = pd.Series(np.full(len(df), 55.0), index=df.index)
        result = detect_all_patterns(df, rsi_series=rsi, volume_ratio=1.5)
        assert isinstance(result, list)

    def test_empty_on_insufficient_data(self):
        df = make_df([100, 101, 102])
        assert detect_all_patterns(df) == []

    def test_none_df_safe(self):
        # detect_all_patterns membungkus tiap sub-deteksi dgn try/except --
        # tidak boleh crash meski df None (hanya trend_structure yg butuh
        # None-check eksplisit, sub-fungsi lain guard via len()/attribute error)
        result = detect_all_patterns(None)
        assert isinstance(result, list)
