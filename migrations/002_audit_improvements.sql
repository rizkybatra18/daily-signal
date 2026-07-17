-- ════════════════════════════════════════════════════════════════
--  DAILY SIGNAL — Migration 002: Audit Improvements
--  Version: 2.0.0
--  Jalankan via Supabase SQL Editor SETELAH 001_initial_schema.sql
--
--  Migration ini 100% ADDITIVE — tidak menghapus/mengubah kolom
--  atau tabel yang sudah ada, tidak merusak data lama. Aman
--  dijalankan kapan saja, dan aman DIULANG (idempotent) berkat
--  IF NOT EXISTS di setiap statement.
--
--  Latar belakang: lihat AUDIT_REPORT.md bagian:
--    - Market Breadth Audit       → kolom pct_above_ema20/50/200
--    - Factor Contribution        → kolom factor_contribution (JSONB)
--    - Confidence Engine          → kolom confidence, raw_score, sector_bonus
--
--  CATATAN: Sistem tetap berjalan normal SEBELUM migration ini
--  dijalankan — kode secara otomatis melewati kolom yang belum ada
--  (lihat _upsert_with_schema_fallback di src/core/database.py).
--  Tapi fitur baru (confidence, factor contribution, breadth EMA)
--  baru aktif SETELAH migration ini dijalankan.
-- ════════════════════════════════════════════════════════════════

-- ── signals: Adaptive Threshold / Confidence / Factor Contribution ──
ALTER TABLE signals
    ADD COLUMN IF NOT EXISTS raw_score            NUMERIC(6,2),
    ADD COLUMN IF NOT EXISTS sector_bonus         NUMERIC(5,2) DEFAULT 0,
    ADD COLUMN IF NOT EXISTS confidence           VARCHAR(20),
    ADD COLUMN IF NOT EXISTS factor_contribution  JSONB;

COMMENT ON COLUMN signals.raw_score IS
    'Composite score 0-100 SEBELUM dikalikan regime_weight (dipakai untuk klasifikasi sinyal adaptif — lihat _determine_signal_type di ta_engine.py)';
COMMENT ON COLUMN signals.confidence IS
    'Very High / High / Medium / Low — rule-based, lihat compute_confidence() di ta_engine.py';
COMMENT ON COLUMN signals.factor_contribution IS
    'Breakdown kontribusi tiap faktor ke skor (trend/momentum/volume/strength/volatility/sector_bonus + highlights) — untuk Dashboard & Telegram';

-- ── market_regimes: Market Breadth yang lebih dalam ──────────────
ALTER TABLE market_regimes
    ADD COLUMN IF NOT EXISTS pct_above_ema20  NUMERIC(5,2),
    ADD COLUMN IF NOT EXISTS pct_above_ema50  NUMERIC(5,2),
    ADD COLUMN IF NOT EXISTS pct_above_ema200 NUMERIC(5,2);

COMMENT ON COLUMN market_regimes.pct_above_ema50 IS
    '% saham (dari stock_data yang dimuat scan hari itu) yang harganya di atas EMA50 — indikator partisipasi pasar, dihitung dari compute_market_breadth() di regime_engine.py';

-- ── Index tambahan untuk query dashboard berbasis confidence ─────
CREATE INDEX IF NOT EXISTS idx_signals_confidence ON signals(confidence);
CREATE INDEX IF NOT EXISTS idx_signals_raw_score ON signals(raw_score DESC);

DO $$
BEGIN
    RAISE NOTICE '✅ Migration 002 (Audit Improvements) berhasil diterapkan!';
    RAISE NOTICE '   signals: +raw_score, +sector_bonus, +confidence, +factor_contribution';
    RAISE NOTICE '   market_regimes: +pct_above_ema20, +pct_above_ema50, +pct_above_ema200';
    RAISE NOTICE '   Tidak ada data lama yang terhapus atau berubah.';
END $$;
