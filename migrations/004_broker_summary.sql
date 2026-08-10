-- ════════════════════════════════════════════════════════════════
--  DAILY SIGNAL — Migration 004: Broker Summary / Bandarmology
--  Version: 2.4.0 (proposed)
--  Jalankan via Supabase SQL Editor SETELAH 001-003.
--
--  Migration ini 100% ADDITIF — 2 tabel baru, tidak menyentuh tabel
--  yang sudah ada. Aman diulang (idempotent) berkat IF NOT EXISTS
--  di setiap statement, mengikuti pola migration 002/003.
--
--  Latar belakang: modul baru untuk fitur broker flow / bandarmology
--  (siapa broker yang akumulasi/distribusi per saham per hari).
--  BEDA SUMBER DATA dari seluruh sistem yang sudah ada — daily_prices
--  & signals berasal dari Yahoo Finance (lihat AUDIT_REPORT_v2.md
--  bagian Universe Manager, IDX scraping langsung TIDAK dipakai
--  karena dilarang ToS + bot-blocked). Broker summary BELUM punya
--  provider terpasang — lihat src/providers/broker_data.py, kelas
--  provider konkret masih perlu dipilih & diimplementasikan sebelum
--  tabel ini mulai terisi. Skema di bawah dibuat generik supaya
--  cocok untuk vendor manapun yang akhirnya dipakai.
-- ════════════════════════════════════════════════════════════════

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ── 1. BROKER_SUMMARY ─────────────────────────────────────────────
-- Ringkasan transaksi per broker per saham per hari (raw data bandarmology)
CREATE TABLE IF NOT EXISTS broker_summary (
    id              UUID DEFAULT uuid_generate_v4() PRIMARY KEY,
    ticker          VARCHAR(20) NOT NULL,       -- e.g. "BBCA.JK", konsisten dgn tabel stocks
    trade_date      DATE NOT NULL,
    broker_code     VARCHAR(5) NOT NULL,        -- e.g. "YP", "BK", "CC"

    -- Sisi Beli
    buy_volume      BIGINT DEFAULT 0,
    buy_value       NUMERIC(20,2) DEFAULT 0,
    avg_buy_price   NUMERIC(15,2),

    -- Sisi Jual
    sell_volume     BIGINT DEFAULT 0,
    sell_value      NUMERIC(20,2) DEFAULT 0,
    avg_sell_price  NUMERIC(15,2),

    -- Net (dihitung saat insert oleh data layer, bukan generated column --
    -- supaya provider manapun yg dipakai tetap kirim payload yg sama bentuknya)
    net_volume      BIGINT,          -- buy_volume - sell_volume
    net_value       NUMERIC(20,2),   -- buy_value - sell_value

    -- Provenance -- WAJIB diisi, dipakai buat audit/debug kalau data
    -- dari 1 provider ternyata bermasalah dan perlu ditelusuri/dihapus
    source_provider VARCHAR(50) NOT NULL,   -- e.g. "invezgo", "sectors_app", "manual"
    fetched_at      TIMESTAMPTZ DEFAULT NOW(),

    created_at      TIMESTAMPTZ DEFAULT NOW(),

    CONSTRAINT uq_broker_summary_ticker_date_broker UNIQUE (ticker, trade_date, broker_code)
);

CREATE INDEX IF NOT EXISTS idx_broker_summary_ticker       ON broker_summary(ticker);
CREATE INDEX IF NOT EXISTS idx_broker_summary_date         ON broker_summary(trade_date DESC);
CREATE INDEX IF NOT EXISTS idx_broker_summary_ticker_date  ON broker_summary(ticker, trade_date DESC);
CREATE INDEX IF NOT EXISTS idx_broker_summary_broker_code  ON broker_summary(broker_code);

-- ── 2. BROKER_CLASSIFICATION ──────────────────────────────────────
-- Klasifikasi broker (asing/domestik/BUMN) -- BUKAN data resmi IDX,
-- dikompilasi manual dari sumber komunitas & di-maintain sendiri.
-- Perlu di-review berkala karena kepemilikan sekuritas bisa berubah
-- dan SPAB bisa dicabut BEI (broker tutup/keluar).
CREATE TABLE IF NOT EXISTS broker_classification (
    broker_code     VARCHAR(5) PRIMARY KEY,
    broker_name     VARCHAR(200) NOT NULL,
    investor_type   VARCHAR(20) NOT NULL CHECK (investor_type IN ('ASING','DOMESTIK','BUMN')),
    is_active       BOOLEAN DEFAULT TRUE,      -- FALSE kalau SPAB sudah dicabut BEI
    notes           TEXT,
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

-- Seed AWAL -- hanya beberapa kode yang paling stabil/dikenal luas
-- sebagai contoh format. INI TIDAK LENGKAP -- lengkapi & verifikasi
-- sendiri dari sumber yang bisa dipercaya (jangan copy mentah dari
-- 1 blog, silangkan minimal 2-3 sumber). Cek juga daftar Anggota
-- Bursa resmi di idx.co.id untuk memastikan kode masih aktif.
INSERT INTO broker_classification (broker_code, broker_name, investor_type, notes) VALUES
    ('BK', 'JP Morgan Sekuritas Indonesia',   'ASING',    'Perlu diverifikasi ulang berkala'),
    ('YU', 'CGS-CIMB Sekuritas Indonesia',    'ASING',    'Perlu diverifikasi ulang berkala'),
    ('CS', 'Credit Suisse Sekuritas Indonesia','ASING',   'Perlu diverifikasi ulang berkala'),
    ('LG', 'Trimegah Sekuritas Indonesia',    'DOMESTIK', 'Perlu diverifikasi ulang berkala'),
    ('GR', 'Panin Sekuritas',                 'DOMESTIK', 'Perlu diverifikasi ulang berkala'),
    ('YP', 'Mirae Asset Sekuritas Indonesia', 'ASING',    'Perlu diverifikasi ulang berkala'),
    ('DX', 'Bahana Sekuritas',                'BUMN',     'Perlu diverifikasi ulang berkala'),
    ('CC', 'Mandiri Sekuritas',               'BUMN',     'Perlu diverifikasi ulang berkala'),
    ('NI', 'BNI Sekuritas',                   'BUMN',     'Perlu diverifikasi ulang berkala')
ON CONFLICT (broker_code) DO NOTHING;

-- ── 3. VIEW: Net Flow Harian per Saham ────────────────────────────
-- Agregat broker_summary + broker_classification -- basis untuk
-- broker_engine.py (foreign net flow %, broker concentration, dst)
CREATE OR REPLACE VIEW v_broker_net_flow_daily AS
SELECT
    bs.ticker,
    bs.trade_date,
    SUM(bs.buy_value)  AS total_buy_value,
    SUM(bs.sell_value) AS total_sell_value,
    SUM(bs.net_value)  AS total_net_value,
    SUM(bs.net_value) FILTER (WHERE bc.investor_type = 'ASING')    AS foreign_net_value,
    SUM(bs.net_value) FILTER (WHERE bc.investor_type = 'DOMESTIK') AS domestic_net_value,
    SUM(bs.net_value) FILTER (WHERE bc.investor_type = 'BUMN')     AS bumn_net_value,
    COUNT(DISTINCT bs.broker_code) AS broker_count
FROM broker_summary bs
LEFT JOIN broker_classification bc ON bc.broker_code = bs.broker_code
GROUP BY bs.ticker, bs.trade_date;

-- ── 4. VIEW: Rata-rata Volume 20 Hari per Ticker ──────────────────
-- Dipakai cmd_broker_scan (runner.py) buat pilih top-N saham PALING
-- LIKUID sebelum fetch broker summary dari vendor -- broker scan
-- vendor API biasanya charge per-call, jadi scan seluruh universe
-- (~550 ticker) tiap hari boros kalau saham likuiditas rendah jarang
-- ada aktivitas bandarmology yang berarti. Pakai daily_prices yang
-- SUDAH ada (diisi Yahoo Finance provider), tidak perlu data baru.
CREATE OR REPLACE VIEW v_ticker_avg_volume_20d AS
SELECT
    ticker,
    AVG(volume) AS avg_volume_20d,
    MAX(trade_date) AS last_trade_date
FROM (
    SELECT ticker, trade_date, volume,
           ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY trade_date DESC) AS rn
    FROM daily_prices
) ranked
WHERE rn <= 20
GROUP BY ticker;

-- ── RLS (samakan pola dgn tabel lain) ─────────────────────────────
ALTER TABLE broker_summary ENABLE ROW LEVEL SECURITY;
CREATE POLICY "service_role_all" ON broker_summary TO service_role USING (true) WITH CHECK (true);
CREATE POLICY "anon_read" ON broker_summary FOR SELECT TO anon USING (true);
CREATE POLICY "anon_read" ON broker_classification FOR SELECT TO anon USING (true);

DO $$
BEGIN
    RAISE NOTICE 'Migration 004 selesai: broker_summary + broker_classification siap.';
    RAISE NOTICE 'INGAT: tabel broker_summary masih KOSONG sampai provider di';
    RAISE NOTICE 'src/providers/broker_data.py dipilih & dikonfigurasi.';
END $$;
