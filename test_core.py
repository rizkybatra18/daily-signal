"""
DAILY SIGNAL — Smoke Tests
Test cepat untuk memastikan sistem bisa berjalan end-to-end.
Tidak memerlukan koneksi database (mock).
"""

import pytest
import pandas as pd
import numpy as np
from datetime import date
from unittest.mock import patch, MagicMock


def make_ohlcv(n=100, trend="up", base_price=1000.0) -> pd.DataFrame:
    """Buat DataFrame OHLCV sintetis."""
    np.random.seed(42)
    closes = [base_price]
    for _ in range(n - 1):
        change = np.random.normal(0.003 if trend == "up" else -0.003, 0.02)
        closes.append(closes[-1] * (1 + change))
    closes = np.array(closes)
    dates = pd.date_range(end=date.today(), periods=n, freq="B")
    return pd.DataFrame({
        "open": closes * 0.999,
        "high": closes * 1.015,
        "low": closes * 0.985,
        "close": closes,
        "volume": np.random.randint(5_000_000, 20_000_000, n).astype(float),
    }, index=dates)


class TestEndToEndPipeline:
    """Test pipeline dari data sampai signal output."""

    def test_full_analysis_pipeline(self):
        """
        Test end-to-end: OHLCV → TA → Score → Signal.
        Tidak perlu database.
        """
        from src.signals.ta_engine import analyze_stock, apply_basic_filters

        df = make_ohlcv(100, trend="up", base_price=2000)
        ihsg = make_ohlcv(60, trend="up", base_price=7000)["close"]

        result = analyze_stock("BBCA.JK", df, ihsg_close=ihsg, regime_weight=1.0)

        assert result is not None
        assert result.ticker == "BBCA.JK"
        assert result.close > 0
        assert 0 <= result.score.final_score <= 100
        assert result.score.signal_type in ("STRONG_BUY", "BUY", "WATCHLIST", "AVOID")
        assert result.trend.ema20 > 0
        assert result.momentum.rsi > 0
        assert result.volatility.atr > 0

    def test_filter_pipeline(self):
        """Test filter menolak saham tidak layak."""
        from src.signals.ta_engine import analyze_stock, apply_basic_filters

        # Saham harga rendah (di bawah minimum Rp100)
        df_cheap = make_ohlcv(60, base_price=50)
        analysis = analyze_stock("CHEAP.JK", df_cheap)

        if analysis:
            analysis = apply_basic_filters(analysis)
            # Harga 50 harus difilter
            if analysis.close < 100:
                assert not analysis.passed_basic_filter

    def test_regime_pipeline(self):
        """Test regime detection dari IHSG data."""
        from src.signals.regime_engine import detect_market_regime

        # Mock save_market_regime supaya tidak perlu database
        with patch("src.signals.regime_engine.save_market_regime"):
            ihsg_df = make_ohlcv(60, trend="up", base_price=7000)
            regime = detect_market_regime(ihsg_df)

        assert regime is not None
        assert regime.regime in ("BULL", "SIDEWAYS", "BEAR")
        assert 0 < regime.regime_weight <= 1.0

    def test_backtest_pipeline(self):
        """Test backtest pipeline tanpa database."""
        from src.backtest.engine import run_backtest

        df = make_ohlcv(200, trend="up", base_price=1500)
        result = run_backtest("BBCA.JK", df)

        assert result is not None
        assert result.ticker == "BBCA.JK"
        assert 0 <= result.win_rate <= 1.0
        assert result.total_trades >= 0

    def test_sector_engine_no_db(self):
        """Test sector engine tanpa database."""
        from src.signals.sector_engine import calculate_sector_rankings

        # Buat stock data
        stock_data = {}
        for ticker in ["BBCA.JK", "BBRI.JK", "ADRO.JK", "TLKM.JK"]:
            stock_data[ticker] = make_ohlcv(30, base_price=1000)

        with patch("src.signals.sector_engine.save_sector_rankings"):
            rankings = calculate_sector_rankings(stock_data)

        assert rankings is not None
        assert len(rankings) > 0
        assert all(0 <= sr.rank <= len(rankings) for sr in rankings if sr.rank > 0)

    def test_telegram_format(self):
        """Test format pesan Telegram tanpa kirim."""
        from src.telegram.bot import _format_signal_card
        from src.signals.ta_engine import analyze_stock, StockAnalysis
        from src.signals.ta_engine import RiskLevels, CompositeScore

        # Buat mock analysis
        df = make_ohlcv(80, trend="up", base_price=5000)
        analysis = analyze_stock("BBCA.JK", df)

        if analysis:
            card = _format_signal_card(analysis, 1)
            assert isinstance(card, str)
            assert "BBCA" in card
            assert len(card) > 50


class TestDataValidation:
    """Test validasi data OHLCV."""

    def test_valid_ohlcv_passes(self):
        from src.providers.market_data import YahooProvider
        provider = YahooProvider()
        df = make_ohlcv(50)
        assert provider.validate_ohlcv(df)

    def test_empty_df_fails(self):
        from src.providers.market_data import YahooProvider
        provider = YahooProvider()
        assert not provider.validate_ohlcv(pd.DataFrame())

    def test_none_fails(self):
        from src.providers.market_data import YahooProvider
        provider = YahooProvider()
        assert not provider.validate_ohlcv(None)

    def test_inverted_candles_fails(self):
        from src.providers.market_data import YahooProvider
        provider = YahooProvider()
        df = make_ohlcv(50)
        # Invert semua candles (high < low)
        df["high"], df["low"] = df["low"].copy(), df["high"].copy()
        assert not provider.validate_ohlcv(df)

    def test_zero_volume_fails(self):
        from src.providers.market_data import YahooProvider
        provider = YahooProvider()
        df = make_ohlcv(50)
        df["volume"] = 0
        assert not provider.validate_ohlcv(df)


class TestConfigValidation:
    """Test konfigurasi dan environment variables."""

    def test_scoring_weights_sum_100(self):
        """Total bobot scoring harus 100."""
        from src.core.config import settings
        total = (
            settings.weight_trend +
            settings.weight_momentum +
            settings.weight_volume +
            settings.weight_strength +
            settings.weight_volatility
        )
        assert abs(total - 100.0) < 0.01, f"Total weight harus 100, got {total}"

    def test_signal_thresholds_ordered(self):
        """Threshold sinyal harus berurutan."""
        from src.core.config import settings
        assert settings.score_strong_buy > settings.score_buy > settings.score_watchlist, \
            "Threshold STRONG_BUY > BUY > WATCHLIST"

    def test_atr_multipliers_positive(self):
        from src.core.config import settings
        assert settings.atr_sl_multiplier > 0
        assert settings.atr_tp1_multiplier > 0
        assert settings.atr_tp2_multiplier > settings.atr_tp1_multiplier
