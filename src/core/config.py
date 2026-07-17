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

    # ── Universe Manager ──────────────────────────────────────────
    # AUDIT FINDING: idx.co.id secara eksplisit MELARANG web scraping/
    # crawling di Syarat Penggunaan mereka (poin 6), dan situs mereka
    # memblokir request otomatis (bot detection). Karena itu, scraping
    # IDX langsung TIDAK dipakai — lihat AUDIT_REPORT.md untuk detail
    # riset dan alasan teknis+legal lengkapnya.
    #
    # Solusi: curated seed list diperluas signifikan (~700+ ticker,
    # representasi mayoritas saham aktif BEI dari seluruh sektor),
    # lalu SETIAP ticker divalidasi likuiditasnya via Yahoo Finance
    # (bukan sekadar dipakai mentah). Ticker yang tidak lagi ada
    # datanya di Yahoo otomatis dianggap delisting/suspend.
    #
    # EXTRA_UNIVERSE_SOURCE_URL (opsional): jika diisi, sistem akan
    # mengambil daftar ticker TAMBAHAN dari URL ini (format: 1 ticker
    # per baris atau CSV kolom "ticker"). Berguna jika Anda ingin
    # menambah cakupan dari sumber pilihan Anda sendiri tanpa mengubah
    # kode. Dibiarkan kosong = tidak dipakai (default aman).
    extra_universe_source_url: str = ""
    universe_min_expected: int = 100   # Alert jika universe tiba-tiba menyusut drastis

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

    # ── Signal Thresholds (BULL / default baseline) ──────────────
    score_strong_buy: float = 75.0   # >= 75 → STRONG_BUY
    score_buy: float = 60.0          # >= 60 → BUY
    score_watchlist: float = 45.0    # >= 45 → WATCHLIST
    # < 45 → AVOID

    # ── Adaptive Regime Thresholds ───────────────────────────────
    # AUDIT FINDING: Skema lama mengalikan raw_score dengan regime_weight
    # lalu membandingkan ke threshold TETAP (75/60/45). Ini membuat
    # STRONG_BUY nyaris MUSTAHIL saat SIDEWAYS (butuh raw=100/100) dan
    # BENAR-BENAR MUSTAHIL saat BEAR (butuh raw>100, max raw=100).
    # Solusi: threshold minimum kini beradaptasi per regime dan
    # dibandingkan terhadap RAW score (bukan raw*weight), sehingga
    # sinyal berkualitas luar biasa tetap bisa lolos bahkan saat BEAR
    # (mis. saham defensif yang reversal duluan saat market mulai pulih).
    # final_score (raw*weight) tetap dihitung & disimpan apa adanya
    # untuk tampilan dashboard/telegram — tidak ada perubahan makna kolom.
    adaptive_thresholds: dict = {
        "BULL":     {"strong_buy": 75.0, "buy": 60.0, "watchlist": 45.0},
        "SIDEWAYS": {"strong_buy": 82.0, "buy": 68.0, "watchlist": 55.0},
        "BEAR":     {"strong_buy": 90.0, "buy": 80.0, "watchlist": 68.0},
    }

    # ── Confidence Engine (rule-based, bukan ML) ─────────────────
    # Confidence menggabungkan raw_score + jumlah dimensi yang selaras
    # (trend/momentum/volume/strength semuanya kuat vs hanya sebagian).
    confidence_very_high: float = 88.0
    confidence_high: float = 75.0
    confidence_medium: float = 60.0
    # < 60 → Low

    # ── Market Breadth ────────────────────────────────────────────
    breadth_bullish_pct: float = 60.0   # % saham di atas EMA20 → breadth bullish
    breadth_bearish_pct: float = 35.0   # % saham di atas EMA20 → breadth bearish

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
