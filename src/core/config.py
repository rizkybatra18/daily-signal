"""
DAILY SIGNAL — Configuration
Semua parameter sistem terpusat di sini. Baca dari environment
variables (.env lokal, atau GitHub Secrets di production).
"""

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── Supabase ──────────────────────────────────────────────────
    supabase_url: str
    supabase_service_key: str

    # ── Telegram ──────────────────────────────────────────────────
    telegram_bot_token: str
    telegram_chat_id: str

    # ── App ───────────────────────────────────────────────────────
    app_env: str = "development"
    log_level: str = "INFO"
    timezone: str = "Asia/Jakarta"

    # ── Data Provider ─────────────────────────────────────────────
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
    # IDX langsung TIDAK dipakai — lihat AUDIT_REPORT_v2.md untuk detail
    # riset dan alasan teknis+legal lengkapnya.
    #
    # Solusi: curated seed list diperluas signifikan (~550 ticker,
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
    rsi_period: int = 14
    rsi_oversold: float = 30.0
    rsi_overbought: float = 70.0

    macd_fast: int = 12
    macd_slow: int = 26
    macd_signal: int = 9

    adx_period: int = 14
    adx_strong: float = 25.0

    atr_period: int = 14
    atr_sl_multiplier: float = 1.5
    atr_tp1_multiplier: float = 2.0
    atr_tp2_multiplier: float = 3.5

    volume_spike_threshold: float = 2.0
    avg_volume_period: int = 20

    # ── Composite Scoring Weights (0-100 total) ──────────────────
    # CATATAN: konstanta ini REFERENSI/DOKUMENTASI -- angka poin aktual
    # di-hardcode langsung di masing-masing fungsi _score_*() di
    # ta_engine.py (dan versi cermin di backtest/engine.py::_score_row).
    # Kalau ubah bobot di sini, WAJIB ubah juga cap poin di kedua tempat
    # itu supaya tidak jadi dokumentasi bohong.
    weight_trend: float = 30.0       # EMA alignment + price vs EMA
    weight_momentum: float = 25.0    # RSI + MACD
    weight_volume: float = 20.0      # Volume ratio + spike
    weight_strength: float = 21.0    # ADX (arah-aware) + DI quality + Relative Strength
    weight_volatility: float = 4.0   # ATR position -- didiskon dari 10, lihat AUDIT di _score_volatility()

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

    # ── Automatic Signal Evaluation ──────────────────────────────
    # Berapa hari bursa maksimum sebuah sinyal dipantau sebelum
    # dianggap EXPIRED jika TP/SL belum tersentuh — lihat
    # src/signals/signal_evaluator.py.
    signal_max_holding_days: int = 10

    # ── Data History ──────────────────────────────────────────────
    history_days_warmup: int = 252    # ~1 tahun untuk warm up indikator
    history_days_scan: int = 252      # Data yang diambil untuk scan

    # ── Broker Summary / Bandarmologi (migration 004) ─────────────
    # Provider aktif: IDX Edge PRO (stock.arjum.com), kuota harian
    # GRATIS (reset 00:00 WIB) -- lihat src/providers/broker_data.py::
    # ArjumIdxEdgeProvider. Wajib diisi di .env/secrets (TIDAK di-set
    # default di sini -- ARJUM_IDX_EDGE_API_KEY adalah kredensial,
    # tidak boleh ada nilai default di source code):
    #   BROKER_DATA_PROVIDER=arjum_idx_edge
    #   ARJUM_IDX_EDGE_API_KEY=sk_live_xxx   (dari dashboard developer stock.arjum.com)
    # broker_scan_enabled DIAKTIFKAN (True) atas instruksi eksplisit
    # user (2026-08) -- SEBELUMNYA default False sampai user setup
    # provider & migration 004 selesai. Kalau BROKER_DATA_PROVIDER
    # belum diisi meski broker_scan_enabled=True, cmd_broker_scan akan
    # gagal jelas (NotConfiguredProvider melempar NotImplementedError)
    # -- bukan silent no-op, tapi juga TIDAK menggagalkan daily_scan
    # utama (continue-on-error: true di workflow).
    broker_data_provider: str = ""
    broker_scan_enabled: bool = True
    # Kuota harian gratis vendor terbatas -- get_signal_tickers_today()
    # cuma ambil saham STRONG_BUY/BUY/WATCHLIST hari itu (bukan seluruh
    # universe ~550 ticker), tapi tetap dibatasi angka ini sebagai
    # pengaman kalau jumlah sinyal meledak di hari tertentu. Default
    # DINAIKKAN 30->150 (v2.7.1) karena user eksplisit minta SEMUA
    # saham bersinyal tercover, dan observasi 1 hari nyata sudah 98
    # saham lolos WATCHLIST+ -- 150 kasih ruang lebih. TETAP cek sisa
    # kuota di dashboard developer stock.arjum.com; turunkan lewat env
    # var BROKER_SCAN_TOP_N di workflow (bukan edit .py) kalau kuota
    # ternyata lebih kecil dari ini.
    broker_scan_top_n: int = 150

    # ── Analog Matching / K-Nearest Neighbor (migration 008) ──────
    # BARU (v2.8.0) -- untuk saham yang lolos filter teknikal, cari K
    # hari historis saham itu sendiri yang kondisi teknikalnya mirip
    # hari ini, simulasikan trade di situ (analog_engine.py).
    # analog_scan_enabled DIAKTIFKAN (True) atas instruksi eksplisit
    # user (2026-08) -- SEBELUMNYA default False (fitur baru, belum
    # ada validasi empiris, menambah waktu scan: fetch histori 3 tahun
    # + KNN + simulasi trade utk tiap kandidat lolos teknikal). WAJIB
    # migration 008 sudah dijalankan di Supabase -- kalau belum, kolom
    # analog_* otomatis dilewati oleh _upsert_with_schema_fallback
    # (tidak menggagalkan scan, tapi datanya juga tidak tersimpan).
    analog_scan_enabled: bool = True


settings = Settings()
