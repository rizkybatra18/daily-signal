-- ════════════════════════════════════════════════════════════════
--  DAILY SIGNAL — Migration 006: Trend Structure masuk Live Scoring
--  Version: 2.5.0 (proposed)
--  Jalankan SETELAH 001-005. 100% additif.
--
--  Latar belakang: trend_structure (pattern_engine.detect_trend_structure)
--  sebelumnya CUMA label deskriptif di signal_results (diisi terpisah
--  oleh signal_evaluator.py untuk tracking), TIDAK pernah dipakai
--  scoring/klasifikasi signal_type. Evidence dari signal_results
--  n=368 (update 10 Agu 2026, lihat AUDIT _score_trend di ta_engine.py):
--  Pullback avg return +8.9% (WR 89.5%, n=95) vs Breakout +4.0%
--  (WR 82.6%, n=23) -- gap besar & konsisten. Sekarang jadi bagian
--  trend_score (lihat _score_trend, cap naik 20->22, +2 dari structure
--  bonus, dipindah dari volatility_score yang dipotong 4->2).
--
--  signal_results.trend_structure SUDAH ADA sejak migration 003 --
--  ini cuma menambah kolom yang sama di tabel `signals` (live table),
--  yang SEBELUMNYA TIDAK PUNYA kolom ini sama sekali.
-- ════════════════════════════════════════════════════════════════

ALTER TABLE signals
    ADD COLUMN IF NOT EXISTS trend_structure VARCHAR(20);

COMMENT ON COLUMN signals.trend_structure IS
    'Diisi src/signals/pattern_engine.py::detect_trend_structure(), sejak '
    'v2.5.0 JUGA dipakai _score_trend() (bukan cuma label deskriptif lagi). '
    'HEURISTIK, bisa None kalau data historis kurang.';

DO $$
BEGIN
    RAISE NOTICE 'Migration 006 selesai.';
    RAISE NOTICE 'PENTING: trend_score MAX BERUBAH LAGI dari 20 ke 22, dan';
    RAISE NOTICE 'volatility_score MAX dari 4 ke 2 (lihat AUDIT ta_engine.py).';
    RAISE NOTICE 'Sinyal LAMA (sebelum deploy ini) masih pakai skala lama --';
    RAISE NOTICE 'JANGAN dibandingkan langsung dengan sinyal baru di dashboard.';
END $$;
