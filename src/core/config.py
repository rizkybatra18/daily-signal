"""
DAILY SIGNAL — Core Configuration
Semua konfigurasi dari environment variables. Tidak ada hardcoded secrets.
"""

import os
from functools import lru_cache
from pydantic import field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """
    Semua konfigurasi sistem.
    Nilai diambil dari environment variables atau file .env
    """

    # ── Supabase ────────────────────────────────────────────────
    supabase_url: str
    supabase_service_key: str

    # ── Telegram ────────────────────────────────────────────────
    telegram_bot_token: str
    telegram_chat_id: str

    # ── App ─────────────────────────────────────────────────────
    app_env: str = "production"
    log_level: str = "INFO"
    tz: str = "Asia/Jakarta"

    # ── Market ──────────────────────────────────────────────────
    ihsg_ticker: str = "^JKSE"
    min_price: float = 100.0
    min_volume: int = 500_000
    max_pump_pct: float = 7.0
    top_n_signals: int = 10
    scan_batch_size: int = 50      # Saham per batch untuk parallel download

    # ── Technical Analysis ──────────────────────────────────────
    # EMA periods
    ema_fast: int = 20
    ema_mid: int = 50
    ema_slow: int = 200

    # RSI
    rsi_period: int = 14
    rsi_oversold: float = 30.0
    rsi_overbought: float = 70.0

    # MACD
    macd_fast: int = 12
    macd_slow: int = 26
    macd_signal: int = 9

    # ADX
    adx_period: int = 14
    adx_strong: float = 25.0       # ADX > 25 = trend kuat

    # ATR
    atr_period: int = 14
    atr_sl_multiplier: float = 1.5   # SL = entry ± 1.5 × ATR
    atr_tp1_multiplier: float = 1.5  # TP1 = entry ± 1.5 × ATR
    atr_tp2_multiplier: float = 2.5  # TP2 = entry ± 2.5 × ATR

    # Volume
    volume_spike_threshold: float = 1.5   # Volume > 1.5x avg = spike
    avg_volume_period: int = 20

    # ── Scoring Weights (total harus 100) ───────────────────────
    weight_trend: float = 30.0       # EMA alignment + price vs EMA
    weight_momentum: float = 25.0    # RSI + MACD
    weight_volume: float = 20.0      # Volume ratio + spike
    weight_strength: float = 15.0    # ADX + Relative Strength
    weight_volatility: float = 10.0  # ATR position

    # ── Signal Thresholds ───────────────────────────────────────
    score_strong_buy: float = 75.0   # >= 75 → STRONG_BUY
    score_buy: float = 60.0          # >= 60 → BUY
    score_watchlist: float = 45.0    # >= 45 → WATCHLIST
    # < 45 → AVOID

    # ── Backtest ────────────────────────────────────────────────
    backtest_lookback_years: int = 3
    backtest_forward_candles: int = 10
    min_win_rate: float = 0.55
    min_pattern_count: int = 10

    # ── Data History ────────────────────────────────────────────
    history_days_warmup: int = 252    # ~1 tahun untuk warm up indikator
    history_days_scan: int = 60       # Data yang diambil untuk scan

    @field_validator("app_env")
    @classmethod
    def validate_env(cls, v):
        allowed = ["development", "staging", "production"]
        if v not in allowed:
            raise ValueError(f"app_env harus salah satu dari {allowed}")
        return v

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v):
        allowed = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        if v.upper() not in allowed:
            raise ValueError(f"log_level harus salah satu dari {allowed}")
        return v.upper()

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "case_sensitive": False,
        "extra": "ignore",
    }


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached settings instance."""
    return Settings()


# Shortcut untuk akses mudah
settings = get_settings()
