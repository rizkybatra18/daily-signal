-- ════════════════════════════════════════════════════════════════
--  DAILY SIGNAL — Migration 007: Seed Lengkap 93 Broker Indonesia
--  Version: 2.7.0 (proposed)
--  Jalankan SETELAH 001-006. 100% additif (ON CONFLICT DO NOTHING/
--  DO UPDATE), aman diulang.
--
--  Latar belakang: broker_classification sebelumnya (migration 004)
--  cuma diseed 11 kode contoh. User minta SEMUA broker Indonesia.
--
--  SUMBER: dikompilasi dari artikel publik (Bisnis.com, "Daftar
--  Sekuritas dan Kode Brokernya di Pasar Saham", per Agustus 2023,
--  93 perusahaan sekuritas aktif) -- BUKAN scraping idx.co.id
--  langsung (konsisten dengan kebijakan yang sudah diaudit di
--  config.py: IDX melarang scraping di ToS + bot-blocked).
--
--  ⚠️ PERINGATAN JUJUR SOAL AKURASI:
--  1. Sumber berumur ~3 tahun (2023) -- ada kemungkinan broker baru
--     belum masuk, atau broker yang SPAB-nya sudah dicabut BEI masih
--     tercantum. broker_summary API (IDX Edge PRO) akan tetap
--     mengirim kode broker yang aktif transaksi hari itu meski
--     belum ada di tabel ini -- kode yang tidak dikenal cukup akan
--     muncul TANPA nama/investor_type (LEFT JOIN di
--     v_broker_net_flow_daily sudah menangani ini, tidak akan error).
--  2. Klasifikasi investor_type (ASING/DOMESTIK/BUMN) di bawah
--     estimasi dari NAMA PERUSAHAAN & kepemilikan yang UMUM DIKETAHUI
--     (co. "JP Morgan" = asing, "BNI Sekuritas" = BUMN karena bank
--     induknya BUMN) -- BUKAN dari sumber resmi yang secara eksplisit
--     mempublikasikan klasifikasi ini per broker. Beberapa entri
--     genuinely ambigu (joint venture, merger/akuisisi terbaru,
--     rebranding) -- ditandai catatan "VERIFIKASI" di notes.
--  3. WAJIB dianggap starting point, bukan kebenaran final -- terutama
--     kalau dipakai untuk analisis yang datanya perlu akurat (co.
--     menghitung total net foreign flow pasar).
-- ════════════════════════════════════════════════════════════════

INSERT INTO broker_classification (broker_code, broker_name, investor_type, notes) VALUES
    ('XC', 'Ajaib Sekuritas Asia',                    'DOMESTIK', 'Sumber: Bisnis.com Sep 2023'),
    ('PP', 'Aldiracita Sekuritas Indonesia',           'DOMESTIK', 'Sumber: Bisnis.com Sep 2023'),
    ('YO', 'Amantara Sekuritas Indonesia',             'DOMESTIK', 'Sumber: Bisnis.com Sep 2023'),
    ('ID', 'Anugerah Sekuritas Indonesia',             'DOMESTIK', 'Sumber: Bisnis.com Sep 2023'),
    ('SH', 'Artha Sekuritas Indonesia',                'DOMESTIK', 'Sumber: Bisnis.com Sep 2023'),
    ('DX', 'Bahana Sekuritas',                         'BUMN',     'Induk PT Bahana Pembinaan Usaha Indonesia (BUMN)'),
    ('SQ', 'BCA Sekuritas',                             'DOMESTIK', 'BCA swasta (Djarum Group), BUKAN BUMN'),
    ('AR', 'Binaartha Sekuritas',                       'DOMESTIK', 'Sumber: Bisnis.com Sep 2023'),
    ('GA', 'BNC Sekuritas Indonesia',                   'DOMESTIK', 'Sumber: Bisnis.com Sep 2023'),
    ('NI', 'BNI Sekuritas',                             'BUMN',     'Induk Bank Negara Indonesia (BUMN)'),
    ('OD', 'BRI Danareksa Sekuritas',                   'BUMN',     'Induk BRI + Danareksa (BUMN)'),
    ('RF', 'Buana Capital Sekuritas',                   'DOMESTIK', 'Sumber: Bisnis.com Sep 2023'),
    ('ZR', 'Bumiputera Sekuritas',                      'DOMESTIK', 'Sumber: Bisnis.com Sep 2023'),
    ('YU', 'CGS-CIMB Sekuritas Indonesia',              'ASING',    'JV China Galaxy Securities + CIMB Malaysia'),
    ('KI', 'Ciptadana Sekuritas Asia',                  'DOMESTIK', 'VERIFIKASI -- nama "Asia" tapi umumnya dicatat grup domestik'),
    ('KZ', 'CLSA Sekuritas Indonesia',                  'ASING',    'Bagian grup CITIC (Hong Kong/China)'),
    ('CS', 'Credit Suisse Sekuritas Indonesia',         'ASING',    'VERIFIKASI -- Credit Suisse global diakuisisi UBS 2023, cek status entitas Indonesia'),
    ('PF', 'Danasakti Sekuritas Indonesia',             'DOMESTIK', 'Sumber: Bisnis.com Sep 2023'),
    ('II', 'Danatama Makmur Sekuritas',                 'DOMESTIK', 'Sumber: Bisnis.com Sep 2023'),
    ('DP', 'DBS Vickers Sekuritas Indonesia',           'ASING',    'Induk DBS Bank Singapura'),
    ('TX', 'Dhanawibawa Sekuritas Indonesia',           'DOMESTIK', 'Sumber: Bisnis.com Sep 2023'),
    ('TS', 'Dwidana Sakti Sekuritas',                   'DOMESTIK', 'Sumber: Bisnis.com Sep 2023'),
    ('ES', 'Ekokapital Sekuritas',                      'DOMESTIK', 'Sumber: Bisnis.com Sep 2023'),
    ('MK', 'Ekuator Swarna Sekuritas',                  'DOMESTIK', 'Sumber: Bisnis.com Sep 2023'),
    ('SA', 'Elit Sukses Sekuritas',                     'DOMESTIK', 'Sumber: Bisnis.com Sep 2023'),
    ('BS', 'Equity Sekuritas Indonesia',                'DOMESTIK', 'Sumber: Bisnis.com Sep 2023'),
    ('AO', 'Erdikha Elit Sekuritas',                    'DOMESTIK', 'Sumber: Bisnis.com Sep 2023'),
    ('EL', 'Evergreen Sekuritas Indonesia',             'DOMESTIK', 'Sumber: Bisnis.com Sep 2023'),
    ('PC', 'FAC Sekuritas Indonesia',                   'DOMESTIK', 'Sumber: Bisnis.com Sep 2023'),
    ('FO', 'Forte Global Sekuritas',                    'DOMESTIK', 'Sumber: Bisnis.com Sep 2023'),
    ('AF', 'Harita Kencana Sekuritas',                  'DOMESTIK', 'Sumber: Bisnis.com Sep 2023'),
    ('HP', 'Henan Putihrai Sekuritas',                  'DOMESTIK', 'Sumber: Bisnis.com Sep 2023'),
    ('GW', 'HSBC Sekuritas Indonesia',                  'ASING',    'Induk HSBC (Inggris/Hong Kong)'),
    ('SC', 'IMG Sekuritas',                              'DOMESTIK', 'Sumber: Bisnis.com Sep 2023'),
    ('RB', 'Ina Sekuritas Indonesia',                   'DOMESTIK', 'Sumber: Bisnis.com Sep 2023'),
    ('IU', 'Indo Capital Sekuritas',                    'DOMESTIK', 'Sumber: Bisnis.com Sep 2023'),
    ('PD', 'Indo Premier Sekuritas',                    'DOMESTIK', 'Sumber: Bisnis.com Sep 2023'),
    ('BF', 'Inti Fikasa Sekuritas',                     'DOMESTIK', 'Sumber: Bisnis.com Sep 2023'),
    ('IT', 'Inti Teladan Sekuritas',                    'DOMESTIK', 'Sumber: Bisnis.com Sep 2023'),
    ('IN', 'Investindo Nusantara Sekuritas',            'DOMESTIK', 'Sumber: Bisnis.com Sep 2023'),
    ('BK', 'J.P. Morgan Sekuritas Indonesia',           'ASING',    'Induk JP Morgan (AS)'),
    ('YB', 'Jasa Utama Capital Sekuritas',               'DOMESTIK', 'Sumber: Bisnis.com Sep 2023'),
    ('DU', 'KAF Sekuritas Indonesia',                    'DOMESTIK', 'VERIFIKASI -- riwayat rebranding, cek kepemilikan terkini'),
    ('CP', 'KB Valbury Sekuritas',                       'ASING',    'VERIFIKASI -- KB mengindikasikan afiliasi KB Financial Group Korea'),
    ('HD', 'KGI Sekuritas Indonesia',                    'ASING',    'Induk KGI Securities Taiwan'),
    ('AG', 'Kiwoom Sekuritas Indonesia',                 'ASING',    'Induk Kiwoom Securities Korea'),
    ('BQ', 'Korea Investment And Sekuritas Indonesia',   'ASING',    'Induk Korea Investment & Securities'),
    ('YJ', 'Lotus Andalan Sekuritas',                    'DOMESTIK', 'Sumber: Bisnis.com Sep 2023'),
    ('RX', 'Macquarie Sekuritas Indonesia',              'ASING',    'Induk Macquarie Group Australia'),
    ('DD', 'Makindo Sekuritas',                          'DOMESTIK', 'Sumber: Bisnis.com Sep 2023'),
    ('CC', 'Mandiri Sekuritas',                          'BUMN',     'Induk Bank Mandiri (BUMN)'),
    ('DM', 'Masindo Artha Sekuritas',                    'DOMESTIK', 'Sumber: Bisnis.com Sep 2023'),
    ('ZP', 'Maybank Sekuritas Indonesia',                'ASING',    'Induk Maybank Malaysia'),
    ('CD', 'Mega Capital Sekuritas',                     'DOMESTIK', 'Grup CT Corp/Mega, domestik'),
    ('MU', 'Minna Padi Investama Sekuritas Tbk.',        'DOMESTIK', 'Sumber: Bisnis.com Sep 2023'),
    ('YP', 'Mirae Asset Sekuritas Indonesia',            'ASING',    'Induk Mirae Asset Korea'),
    ('EP', 'MNC Sekuritas',                              'DOMESTIK', 'Grup MNC, domestik'),
    ('OK', 'Net Sekuritas',                              'DOMESTIK', 'Sumber: Bisnis.com Sep 2023'),
    ('XA', 'NH Korindo Sekuritas Indonesia',             'ASING',    'Induk NH Investment & Securities Korea'),
    ('RO', 'Nilai Inti Sekuritas',                       'DOMESTIK', 'Sumber: Bisnis.com Sep 2023'),
    ('TP', 'OCBC Sekuritas Indonesia',                   'ASING',    'Induk OCBC Bank Singapura'),
    ('IH', 'Pacific 2000 Sekuritas',                     'DOMESTIK', 'Sumber: Bisnis.com Sep 2023'),
    ('AP', 'Pacific Sekuritas Indonesia',                'DOMESTIK', 'Sumber: Bisnis.com Sep 2023'),
    ('PG', 'Panca Global Sekuritas',                     'DOMESTIK', 'Sumber: Bisnis.com Sep 2023'),
    ('GR', 'Panin Sekuritas Tbk.',                       'DOMESTIK', 'Grup Panin, domestik'),
    ('PS', 'Paramitra Alfa Sekuritas',                   'DOMESTIK', 'Sumber: Bisnis.com Sep 2023'),
    ('KK', 'Phillip Sekuritas Indonesia',                'ASING',    'Induk Phillip Capital Singapura'),
    ('AT', 'Phintraco Sekuritas',                        'DOMESTIK', 'Sumber: Bisnis.com Sep 2023'),
    ('PO', 'Pilarmas Investindo Sekuritas',              'DOMESTIK', 'Sumber: Bisnis.com Sep 2023'),
    ('RG', 'Profindo Sekuritas Indonesia',               'DOMESTIK', 'Sumber: Bisnis.com Sep 2023'),
    ('LS', 'Reliance Sekuritas Indonesia Tbk.',          'DOMESTIK', 'Sumber: Bisnis.com Sep 2023'),
    ('DR', 'RHB Sekuritas Indonesia',                    'ASING',    'Induk RHB Bank Malaysia'),
    ('IF', 'Samuel Sekuritas Indonesia',                 'DOMESTIK', 'Sumber: Bisnis.com Sep 2023'),
    ('MG', 'Semesta Indovest Sekuritas',                 'DOMESTIK', 'Sumber: Bisnis.com Sep 2023'),
    ('AH', 'Shinhan Sekuritas Indonesia',                'ASING',    'Induk Shinhan Financial Group Korea'),
    ('DH', 'Sinarmas Sekuritas',                         'DOMESTIK', 'Grup Sinarmas, domestik'),
    ('XL', 'Stockbit Sekuritas Digital',                 'DOMESTIK', 'Sumber: Bisnis.com Sep 2023'),
    ('AZ', 'Sucor Sekuritas',                            'DOMESTIK', 'Sumber: Bisnis.com Sep 2023'),
    ('SS', 'Supra Sekuritas Indonesia',                  'DOMESTIK', 'Sumber: Bisnis.com Sep 2023'),
    ('SF', 'Surya Fajar Sekuritas',                      'DOMESTIK', 'Sumber: Bisnis.com Sep 2023'),
    ('LG', 'Trimegah Sekuritas Indonesia Tbk.',          'DOMESTIK', 'Grup Recapital/Hashim Djojohadikusumo, domestik'),
    ('BR', 'Trust Sekuritas',                            'DOMESTIK', 'Sumber: Bisnis.com Sep 2023'),
    ('AK', 'UBS Sekuritas Indonesia',                    'ASING',    'Induk UBS Swiss'),
    ('TF', 'Universal Broker Indonesia Sekuritas',       'DOMESTIK', 'Sumber: Bisnis.com Sep 2023'),
    ('AI', 'UOB Kay Hian Sekuritas',                     'ASING',    'Induk UOB Singapura'),
    ('BB', 'Verdhana Sekuritas Indonesia',               'DOMESTIK', 'VERIFIKASI -- eks JV CLSA+Bahana, cek struktur kepemilikan terkini'),
    ('MI', 'Victoria Sekuritas Indonesia',               'DOMESTIK', 'Grup Victoria, domestik'),
    ('AN', 'Wanteg Sekuritas',                           'DOMESTIK', 'Sumber: Bisnis.com Sep 2023'),
    ('FZ', 'Waterfront Sekuritas Indonesia',             'DOMESTIK', 'Sumber: Bisnis.com Sep 2023'),
    ('GI', 'Webull Sekuritas Indonesia',                 'ASING',    'Induk Webull (asal AS/Tiongkok)'),
    ('FS', 'Yuanta Sekuritas Indonesia',                 'ASING',    'Induk Yuanta Financial Taiwan'),
    ('IP', 'Yugen Bertumbuh Sekuritas',                  'DOMESTIK', 'Sumber: Bisnis.com Sep 2023'),
    ('RS', 'Yulie Sekuritas Indonesia Tbk.',             'DOMESTIK', 'Sumber: Bisnis.com Sep 2023')
ON CONFLICT (broker_code) DO UPDATE SET
    broker_name   = EXCLUDED.broker_name,
    investor_type = EXCLUDED.investor_type,
    notes         = EXCLUDED.notes,
    updated_at    = NOW();

DO $$
DECLARE
    total_count INT;
BEGIN
    SELECT COUNT(*) INTO total_count FROM broker_classification;
    RAISE NOTICE 'Migration 007 selesai: % broker_classification total.', total_count;
    RAISE NOTICE 'INGAT: daftar ini dikompilasi dari sumber pihak ketiga (~2023),';
    RAISE NOTICE 'BUKAN dari IDX resmi -- verifikasi ulang berkala, terutama entri';
    RAISE NOTICE 'bertanda "VERIFIKASI" di kolom notes.';
END $$;
