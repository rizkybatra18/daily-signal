-- ════════════════════════════════════════════════════════════════
--  DAILY SIGNAL — Migration 005: Flow Indicators (Bandarmology-Proxy Gratis)
--  Version: 2.5.0 (proposed)
--  Jalankan SETELAH 001-004. 100% additif (ADD COLUMN IF NOT EXISTS).
--
--  Latar belakang: skip fitur broker_summary berbayar (lihat migration
--  004, provider belum ada) -- diganti proxy bandarmology GRATIS dari
--  OHLCV yang sudah ada (OBV, A/D Line, CMF, MFI, klasifikasi bar VSA).
--  Juga bagian dari audit trend_score (dipotong 30->20, lihat AUDIT
--  di src/signals/ta_engine.py::CompositeScore).
-- ════════════════════════════════════════════════════════════════

ALTER TABLE signals
    ADD COLUMN IF NOT EXISTS obv             NUMERIC(20,2),
    ADD COLUMN IF NOT EXISTS obv_slope_pct   NUMERIC(8,2),
    ADD COLUMN IF NOT EXISTS ad_line         NUMERIC(20,2),
    ADD COLUMN IF NOT EXISTS cmf             NUMERIC(6,4),
    ADD COLUMN IF NOT EXISTS mfi             NUMERIC(6,2),
    ADD COLUMN IF NOT EXISTS vsa_signal      VARCHAR(20),
    ADD COLUMN IF NOT EXISTS flow_score      NUMERIC(6,2);

-- signal_results — WAJIB ditambah juga supaya flow_score bisa
-- divalidasi empiris lewat dashboard Score Calibration (lihat AUDIT
-- di _score_flow(), belum ada data historis untuk komponen ini).
ALTER TABLE signal_results
    ADD COLUMN IF NOT EXISTS flow_score      NUMERIC(6,2),
    ADD COLUMN IF NOT EXISTS cmf             NUMERIC(6,4),
    ADD COLUMN IF NOT EXISTS vsa_signal      VARCHAR(20);

CREATE INDEX IF NOT EXISTS idx_signals_vsa_signal ON signals(vsa_signal);

DO $$
BEGIN
    RAISE NOTICE 'Migration 005 selesai: kolom flow indicator siap.';
    RAISE NOTICE 'CATATAN: trend_score MAX BERUBAH dari 30 ke 20 (baca';
    RAISE NOTICE 'AUDIT di ta_engine.py::CompositeScore) -- sinyal LAMA';
    RAISE NOTICE 'yang sudah tersimpan sebelum deploy ini masih pakai skala';
    RAISE NOTICE 'lama, JANGAN dibandingkan langsung dengan sinyal baru.';
END $$;
