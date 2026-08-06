-- ═══════════════════════════════════════════════════════════════════
--  Migration 003 — signal_results: dokumentasi skema lengkap +
--  kolom baru trend_structure/pattern_detected
-- ═══════════════════════════════════════════════════════════════════
--
-- AUDIT: tabel `signal_results` sudah dipakai src/signals/signal_evaluator.py
-- & dashboard.py (referensi "migration 003" ada di komentar
-- src/core/database.py::upsert_signal_result), TAPI file migration-nya
-- sendiri hilang/tidak pernah masuk version control -- tabel ini
-- sepertinya dibuat manual di Supabase SQL editor. Migration ini
-- MENDOKUMENTASIKAN skema yang sudah berjalan (CREATE TABLE IF NOT
-- EXISTS, aman dijalankan meski tabel sudah ada) + menambah 2 kolom
-- yang sebelumnya cuma "reserved"/selalu NULL karena belum ada engine
-- yang mengisi: `trend_structure` & `pattern_detected`
-- (lihat src/signals/pattern_engine.py, BARU di v2.3).
--
-- Aman dijalankan berkali-kali (semua statement pakai IF NOT EXISTS).

CREATE TABLE IF NOT EXISTS signal_results (
    id                      BIGSERIAL PRIMARY KEY,

    -- Identitas
    ticker                  TEXT NOT NULL,
    signal_date             DATE NOT NULL,
    timeframe               TEXT DEFAULT '1D',
    sector                  TEXT,
    market_regime           TEXT,
    signal_type             TEXT,

    -- Nilai indikator (snapshot saat sinyal dibuat)
    close_price             NUMERIC(14,2),
    rsi                     NUMERIC(6,2),
    rsi_prev                NUMERIC(6,2),
    rsi_slope               NUMERIC(6,3),
    macd_line               NUMERIC(12,4),
    macd_signal             NUMERIC(12,4),
    macd_hist               NUMERIC(12,4),
    ema20                   NUMERIC(14,2),
    ema50                   NUMERIC(14,2),
    ema200                  NUMERIC(14,2),
    sma20                   NUMERIC(14,2),
    sma50                   NUMERIC(14,2),
    sma200                  NUMERIC(14,2),
    atr                     NUMERIC(12,3),
    adx                     NUMERIC(6,2),
    plus_di                 NUMERIC(6,2),
    minus_di                NUMERIC(6,2),
    volume                  BIGINT,
    avg_volume_20           NUMERIC(18,2),
    relative_volume         NUMERIC(8,3),
    bollinger_position      NUMERIC(6,4),
    distance_ema20_pct      NUMERIC(8,3),
    distance_ema50_pct      NUMERIC(8,3),
    distance_ema200_pct     NUMERIC(8,3),

    -- Kondisi (label turunan, bukan angka mentah)
    trend_condition         TEXT,   -- Uptrend / Sideways / Downtrend
    momentum_condition      TEXT,   -- RSI Oversold / Neutral / Overbought
    volume_condition        TEXT,   -- High Volume / Normal / Low Volume

    -- Struktur & Pattern (BARU v2.3, lihat pattern_engine.py -- HEURISTIK,
    -- belum divalidasi empiris, belum dipakai scoring)
    trend_structure         TEXT,   -- Higher High/Low, Lower High/Low, Breakout, Pullback, Consolidation
    pattern_detected        JSONB,  -- array teks, e.g. ["Bullish Engulfing", "Near Support"]

    -- Komponen scoring LENGKAP (bukan cuma final_score)
    trend_score             NUMERIC(6,2),
    momentum_score          NUMERIC(6,2),
    volume_score            NUMERIC(6,2),
    strength_score          NUMERIC(6,2),
    volatility_score        NUMERIC(6,2),
    sector_bonus            NUMERIC(6,2),
    regime_weight           NUMERIC(4,2),
    raw_score                NUMERIC(6,2),
    final_score              NUMERIC(6,2),
    confidence               TEXT,

    -- Alasan sinyal muncul (highlight dari factor_contribution + tag turunan)
    reasons                  JSONB,

    -- Rencana trading saat sinyal dibuat
    entry_price               NUMERIC(14,2),
    stop_loss                 NUMERIC(14,2),
    target_1                  NUMERIC(14,2),
    target_2                  NUMERIC(14,2),
    risk_reward                NUMERIC(6,3),

    -- Status & evaluasi
    status                     TEXT NOT NULL DEFAULT 'OPEN',   -- OPEN / CLOSED / EXPIRED
    exit_price                 NUMERIC(14,2),
    exit_date                  DATE,
    exit_reason                TEXT,   -- SL / TP1 / TP2 / EXPIRED
    holding_days                INTEGER,
    gross_return_pct            NUMERIC(8,3),
    net_return_pct              NUMERIC(8,3),
    evaluated_at                 TIMESTAMPTZ,

    created_at                    TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT uq_signal_results_ticker_date_type UNIQUE (ticker, signal_date, signal_type)
);

-- Kolom baru buat DB yang tabelnya SUDAH ada dari sebelum migration ini
-- (idempotent, tidak akan error kalau kolom sudah ada / tabel baru dibuat
-- oleh CREATE TABLE di atas)
ALTER TABLE signal_results ADD COLUMN IF NOT EXISTS trend_structure TEXT;
ALTER TABLE signal_results ADD COLUMN IF NOT EXISTS pattern_detected JSONB;

COMMENT ON COLUMN signal_results.trend_structure IS
    'Higher High / Higher Low / Lower High / Lower Low / Breakout / Pullback / Consolidation. '
    'Diisi src/signals/pattern_engine.py::detect_trend_structure() sejak v2.3. HEURISTIK.';
COMMENT ON COLUMN signal_results.pattern_detected IS
    'Array JSON pattern terdeteksi (candlestick, breakout, S/R, divergence). '
    'Diisi src/signals/pattern_engine.py::detect_all_patterns() sejak v2.3. HEURISTIK, belum dipakai scoring.';

CREATE INDEX IF NOT EXISTS idx_signal_results_ticker       ON signal_results(ticker);
CREATE INDEX IF NOT EXISTS idx_signal_results_signal_date  ON signal_results(signal_date DESC);
CREATE INDEX IF NOT EXISTS idx_signal_results_status       ON signal_results(status);
CREATE INDEX IF NOT EXISTS idx_signal_results_raw_score    ON signal_results(raw_score DESC);

DO $$
BEGIN
    RAISE NOTICE 'Migration 003 selesai: signal_results terdokumentasi + trend_structure/pattern_detected siap diisi.';
END $$;
