-- ════════════════════════════════════════════════════════════════
--  DAILY SIGNAL — Migration 008: Analog Matching (K-Nearest Neighbor)
--  Version: 2.8.0 (proposed)
--  Jalankan SETELAH 001-007. 100% additif.
--
--  Latar belakang: fitur BARU atas permintaan user -- untuk saham yang
--  lolos filter teknikal (signal_type STRONG_BUY/BUY/WATCHLIST), cari
--  K hari historis SAHAM ITU SENDIRI yang kondisi teknikalnya paling
--  mirip hari ini, simulasikan trade di situ (pakai _simulate_trade
--  yang SAMA PERSIS dengan backtest engine), dan jadikan win rate-nya
--  sebagai analog_score (0-5 poin, komponen baru composite score).
--  Lihat src/signals/analog_engine.py untuk detail metodologi & AUDIT
--  soal keterbatasannya.
--
--  PENTING: analog_score BARU, BELUM ADA VALIDASI EMPIRIS -- treat
--  sebagai hipotesis, bukan fakta, sampai cukup data live terkumpul.
-- ════════════════════════════════════════════════════════════════

ALTER TABLE signals
    ADD COLUMN IF NOT EXISTS analog_score      NUMERIC(6,2),
    ADD COLUMN IF NOT EXISTS analog_n          INTEGER,
    ADD COLUMN IF NOT EXISTS analog_win_rate   NUMERIC(6,2),
    ADD COLUMN IF NOT EXISTS analog_avg_return NUMERIC(8,2),
    ADD COLUMN IF NOT EXISTS analog_reliable   BOOLEAN;

COMMENT ON COLUMN signals.analog_score IS
    'K-Nearest Neighbor analog matching (src/signals/analog_engine.py), 0-5 poin. '
    'NULL/0 = analog belum/tidak cukup dihitung (co. ticker tidak lolos filter '
    'teknikal tahap 1, atau n_analogs < minimum).';
COMMENT ON COLUMN signals.analog_n IS
    'Jumlah hari historis analog yang benar-benar dipakai (setelah exclude data invalid).';
COMMENT ON COLUMN signals.analog_win_rate IS
    'Persentase analog yang net_pnl_pct > 0 (0-100). Basis analog_score.';
COMMENT ON COLUMN signals.analog_avg_return IS
    'Rata-rata net_pnl_pct dari seluruh analog (setelah exit TP1/TP2/SL/timeout realistis).';
COMMENT ON COLUMN signals.analog_reliable IS
    'FALSE kalau n_analogs di bawah minimum (default 5) -- analog_score dipaksa 0 kalau FALSE.';

-- signal_results -- supaya analog_score bisa divalidasi empiris nanti
-- lewat dashboard Score Calibration, sama seperti flow_score/trend_structure.
ALTER TABLE signal_results
    ADD COLUMN IF NOT EXISTS analog_score      NUMERIC(6,2),
    ADD COLUMN IF NOT EXISTS analog_win_rate   NUMERIC(6,2),
    ADD COLUMN IF NOT EXISTS analog_n          INTEGER;

DO $$
BEGIN
    RAISE NOTICE 'Migration 008 selesai: kolom analog matching siap.';
    RAISE NOTICE 'CATATAN: analog_score MENGGESER volume_score cap dari 20 ke 15';
    RAISE NOTICE '(lihat AUDIT CompositeScore di ta_engine.py) -- sinyal LAMA';
    RAISE NOTICE 'sebelum deploy ini masih pakai skala volume_score lama.';
END $$;
