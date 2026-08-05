-- ════════════════════════════════════════════════════════════════
--  DAILY SIGNAL — Migration Checker
--  Jalankan SEBELUM 001_initial_schema.sql untuk cek status
-- ════════════════════════════════════════════════════════════════

DO $$
DECLARE
    tbl TEXT;
    missing_tables TEXT[] := ARRAY[]::TEXT[];
    required_tables TEXT[] := ARRAY[
        'stocks', 'daily_prices', 'signals', 'signal_updates',
        'open_positions', 'closed_positions', 'portfolio_snapshots',
        'backtest_results', 'sector_rankings', 'market_regimes',
        'system_logs', 'scan_runs'
    ];
BEGIN
    FOREACH tbl IN ARRAY required_tables LOOP
        IF NOT EXISTS (
            SELECT 1 FROM information_schema.tables
            WHERE table_schema = 'public' AND table_name = tbl
        ) THEN
            missing_tables := array_append(missing_tables, tbl);
        END IF;
    END LOOP;

    IF array_length(missing_tables, 1) IS NULL THEN
        RAISE NOTICE '✅ Semua tabel sudah ada! Migration sudah dijalankan.';
    ELSE
        RAISE NOTICE '❌ Tabel yang belum ada: %', array_to_string(missing_tables, ', ');
        RAISE NOTICE '   → Jalankan migrations/001_initial_schema.sql';
    END IF;
END $$;
