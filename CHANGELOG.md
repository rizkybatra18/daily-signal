# DAILY SIGNAL — Changelog

---

## v2.5.1 — Audit Menyeluruh Hulu-ke-Hilir (2026-08)

### 🔍 Latar belakang
Audit penuh atas permintaan user: baca ulang SELURUH sistem dari data
ingestion sampai dashboard, cari bug/perhitungan salah, perbaiki
langsung. Ditemukan 6 masalah nyata (2 berdampak signifikan, 4 pola
berulang) — semua sudah diuji dengan smoke test, bukan cuma dibaca.

### 🐛 Bug signifikan
1. **`_upsert_with_schema_fallback()` di `database.py` — retry loop
   cuma sanggup buang 1 kolom bermasalah** (`for _ in range(2)`). Kalau
   lebih dari 1 kolom baru belum ada di schema sekaligus (persis situasi
   sekarang: migration 005 & 006 sama-sama belum jalan = 8 kolom baru
   sekaligus), `save_signal()` gagal TOTAL — bukan cuma skip kolom yang
   belum ada. **Berpotensi bikin scan harian gagal simpan APAPUN** kalau
   migration tidak lengkap dijalankan. Diperbaiki: jumlah percobaan
   mengikuti jumlah kolom di payload, bukan angka tetap. Dibuktikan
   dengan unit test tiruan (3 kolom hilang sekaligus, tetap berhasil).
2. **Backtest `_simulate_trade()` tidak pernah simulasikan TP2** —
   cuma cek TP1/SL, padahal `settings.atr_tp2_multiplier` ada dan
   dipakai live tracking (`signal_evaluator.py::_walk_price_path`,
   urutan SL->TP2->TP1). Backtest jadi menguji strategi single-target
   yang beda dari yang dilacak live. Diperbaiki: tp2 dihitung, urutan
   cek disamakan persis. Dibuktikan: skenario gap-up sintetis sekarang
   benar keluar sebagai TP2, bukan berhenti di TP1.

### 🔁 Pola berulang: cap score hardcoded basi (ketemu di 5 lokasi terpisah)
Setelah trend_score cap berubah 2x (30→20→22) & volatility 2x (10→4→2)
dalam sesi-sesi sebelumnya, ditemukan **5 lokasi berbeda** yang masih
menyalin angka cap lama secara manual alih-alih pakai konstanta:
`compute_confidence()` (basi SEBELUM sesi manapun — strength_score
ditulis 15 padahal sudah 21), `telegram/bot.py` (threshold 16, harusnya
ikut naik ke 17.6 pas trend cap naik ke 22), `dashboard.py` 3 lokasi
terpisah (reason-builder, gauge "Score Breakdown", tile "Trend/
Volatility Score" di Signal Detail). **Diperbaiki permanen di SEMUA
lokasi**: import `TREND_SCORE_CAP` dkk dari `ta_engine.py` langsung,
tidak ada lagi angka cap yang disalin manual di tempat lain manapun.

### 🔧 Konsistensi hulu-hilir
- `signal_evaluator.py::capture_todays_signals()` menghitung ULANG
  `trend_structure` secara independen dari yang dipakai live scoring
  (`_score_trend`), padahal nilainya sudah tersimpan di `sig.get(
  "trend_structure")` sejak migration 006. Diperbaiki: reuse nilai yang
  sudah ada, recompute cuma sebagai fallback data lama.
- `pattern_engine.py`: docstring modul masih bilang trend_structure
  "belum di-wire ke scoring" — sudah basi sejak trend_structure
  diintegrasikan ke `_score_trend()`. Diperbaiki, sekaligus diperjelas
  pattern LAIN (candlestick/breakout/S-R/divergence) memang masih belum
  di-wire (itu tetap benar).
- `backtest/engine.py`: docstring modul masih sebut bobot statis lama
  (30/25/20/21/4) yang sudah 2x berubah. Diperbaiki — sekarang menunjuk
  ke `CompositeScore` di `ta_engine.py` sebagai sumber kebenaran,
  bukan angka yang bisa basi lagi.

### ✅ Area yang dicek, tidak ada masalah ditemukan
`scanner.py` (orkestrasi pipeline), `regime_engine.py`, `sector_engine.py`,
`market_data.py` (fetch & incremental update), `portfolio/tracker.py`
(fitur tersembunyi dari UI, komisi konsisten dengan backtest), migration
SQL, `_calc_metrics` (tidak terpengaruh perubahan TradeResult karena
cuma pakai `win`/`net_pnl_pct`, bukan `exit_reason` string).

---

## v2.5.0 — Flow Indicators, Trend Structure Scoring & Backtest Parity (2026-08)

### 🎯 Latar belakang
Skip fitur broker summary berbayar (lihat v2.4.0 di bawah, provider belum
ada) — fokus dialihkan ke 2 hal yang bisa dikerjakan GRATIS & langsung
berdasarkan data: (1) proxy bandarmology dari OHLCV yang sudah ada, (2)
perbaikan scoring berdasarkan analisis signal_results yang terus membesar
(n=265 → n=368, update 10 Agu 2026) dan audit ulang seluruh cap komponen.

### ✨ Flow Indicators (BARU) — proxy bandarmology gratis
- 5 indikator baru murni dari OHLCV (`src/signals/ta_engine.py`): OBV
  (Granville), A/D Line + Chaikin Money Flow (Marc Chaikin), Money Flow
  Index, klasifikasi bar ala Volume Spread Analysis (Tom Williams/Wyckoff:
  ACCUMULATION/DISTRIBUTION/CLIMAX_UP/CLIMAX_DOWN/NO_DEMAND/NEUTRAL).
- `flow_score` BARU (0-10 poin) sebagai komponen ke-6 composite score.
  BELUM ada validasi empiris (indikator baru) — bobot sengaja kecil,
  cek berkala lewat dashboard Score Calibration begitu data live terisi.

### 📊 Audit & Rebalancing Composite Score (n=368, 27 Jul–10 Agu 2026)
Re-analisis signal_results dengan Spearman correlation formal (bukan cuma
kuartil manual) terhadap `net_return_pct`:

| Komponen | rho | p-value | Aksi |
|---|---|---|---|
| `volatility_score` | **-0.420** | <0.0001 | Cap dipotong LAGI: 4 → **2** (riwayat: 10→4→2, korelasi stabil -0.50→-0.45→-0.42 di 3 sample — pola nyata, bukan noise) |
| `trend_score` | -0.217 | <0.0001 | Konfirmasi cap 20 sudah tepat dipotong sesi sebelumnya (dari 30) |
| `trend_structure` (Pullback vs Breakout) | — | — | Gap ~5pp mean return (Pullback +8.9% n=95 vs Breakout +4.0% n=23) — **BARU dijadikan bagian scoring** (sebelumnya cuma label deskriptif), +2 poin bonus di `_score_trend`, cap trend naik 20→**22** |
| `momentum_score` | +0.173 | 0.0008 | Sudah benar arahnya, tidak diubah |
| `strength_score` | +0.136 | 0.0087 | Sudah benar arahnya, tidak diubah |
| `volume_score` | -0.057 | 0.278 (**tidak signifikan**) | **TIDAK diubah** — bukti belum cukup kuat, konsisten prinsip "jangan ubah tanpa validasi" |

Cap final: trend 22, momentum 25, volume 20, strength 21, volatility 2,
flow 10 = tetap 100. 2 poin yang dipotong dari volatility dipindah ke
trend (structure bonus) — bukan redistribusi acak, ada jejak audit jelas.

### 🐛 Bug ditemukan & diperbaiki sekalian
- **`compute_confidence()` pakai cap BASI** — `strength_score` ditulis
  hardcoded 15.0 padahal cap sebenarnya sudah 21 sejak audit DI-quality
  sebelumnya (bug ini SUDAH ADA sebelum sesi ini, ketemu tidak sengaja
  saat menambahkan konstanta cap). Akibatnya `strong_dims` dihitung dari
  rasio yang salah, systematically undercount.
- 4 titik hardcoded threshold/cap trend_score (`telegram/bot.py`,
  `dashboard.py` 3 titik) yang ketinggalan tiap kali cap trend_score
  berubah — pola bug yang SAMA berulang. **Diperbaiki permanen**: semua
  cap sekarang konstanta bernama di `ta_engine.py`
  (`TREND_SCORE_CAP`, `MOMENTUM_SCORE_CAP`, `VOLUME_SCORE_CAP`,
  `STRENGTH_SCORE_CAP`, `VOLATILITY_SCORE_CAP`, `FLOW_SCORE_CAP`,
  `TOTAL_SCORE_CAP` dengan `assert ==100` saat modul di-load) — tempat
  lain WAJIB import, tidak boleh hardcode ulang.
- Dashboard "Score Calibration": bucket `volatility_score` masih pakai
  skala 0-10 yang sudah 2x basi. Diperbaiki + ditambah bucket
  `trend_score` & `flow_score` (baru) untuk validasi ke depan.

### 🔧 Backtest/Live Parity (lanjutan perbaikan v2.3.1 poin 3)
`_score_row()` di `src/backtest/engine.py` SEBELUMNYA masih duplikat
manual formula ta_engine.py (rapuh — terbukti: begitu trend_score &
volatility_score di atas berubah, kalau tidak disentuh manual backtest
akan diam-diam pakai formula lama). **Diperbaiki secara struktural**:
`_score_row()` sekarang membangun `StockAnalysis` dari row lalu MEMANGGIL
LANGSUNG `_score_trend/_score_momentum/_score_volume/_score_strength/
_score_volatility/_score_flow` dari `ta_engine.py` — bukan menyalin
formula lagi. `trend_structure` juga dihitung di backtest (window 120-bar
per baris, no-lookahead-safe) supaya bonus struktur ikut konsisten.

**Dibuktikan, bukan cuma diklaim**: diuji 5 dataset sintetis berbeda
lewat `analyze_stock()` (live) vs `_score_row()` (backtest) — **0/5
mismatch**, skor identik sampai 2 desimal termasuk breakdown per
komponen.

### 🗄️ Migration baru
- `005_flow_indicators.sql` — kolom flow di `signals` & `signal_results`
- `006_trend_structure_scoring.sql` — kolom `trend_structure` di `signals`
  (sebelumnya cuma ada di `signal_results`)

### ⚠️ Belum selesai
- `flow_score` & bonus `trend_structure` belum ada data historis untuk
  divalidasi — perlu beberapa minggu live dulu sebelum re-audit lewat
  Score Calibration

### 🎨 Dashboard — Insight & Visual Baru
Extend design system yang sudah ada (bukan rebuild) — tambah komponen
visual + insight baru untuk flow/struktur, TANPA mengubah engine/scoring:

- **Flow Radar (BARU)** di halaman Home — leaderboard 6 saham dengan
  pola VSA "Akumulasi" + CMF tertinggi hari itu, satu widget yang
  merangkum flow_score/CMF/VSA/trend_structure jadi satu pandangan
  sekilas. Kosong dengan pesan jelas kalau belum ada pola terdeteksi.
- **Badge VSA & chip Trend Structure baru** (`vsa_badge()`,
  `structure_chip()`) — dipakai di Top Signals (kolom baru "Flow"),
  Flow Radar, dan Signal Detail. Warna konsisten dengan design token
  yang sudah ada (var(--strong-buy)/--avoid/--watchlist), bukan palet baru.
- **Signal Detail** — bagian "Money Flow & Struktur" baru: CMF, MFI,
  OBV Slope 10D, badge VSA, plus satu baris interpretasi bahasa natural
  (co. "volume besar terserap tanpa melebarkan range... OBV naik 6.4%
  dalam 10 hari... struktur trend saat ini: Pullback") — deskriptif,
  BUKAN rekomendasi beli/jual.
- **Bug tile label basi diperbaiki lagi**: Trend Score & Volatility
  Score di Signal Detail masih menampilkan "/20" dan "/4" (cap lama
  SEBELUM perubahan trend_structure/volatility di atas) — diperbaiki
  jadi "/22" dan "/2".

---

## v2.4.0 — Modul Broker Flow / Bandarmology (Kerangka, Belum Aktif) (2026-08)

### ✨ Fitur Baru: Broker Summary & Broker Flow
Kerangka modul bandarmology terintegrasi (bukan tools terpisah): tabel baru,
provider abstraction, engine analisis, halaman dashboard. **BELUM AKTIF
secara default** (`BROKER_SCAN_ENABLED=False`) karena provider data vendor
belum dipilih/dikonfigurasi — lihat catatan di bawah.

- **`migrations/004_broker_summary.sql`** (baru) — tabel `broker_summary`
  (transaksi per broker per saham per hari) + `broker_classification`
  (asing/domestik/BUMN, di-seed contoh 9 broker, PERLU DILENGKAPI &
  diverifikasi manual — bukan data resmi IDX) + view
  `v_broker_net_flow_daily` (agregat net flow) + view
  `v_ticker_avg_volume_20d` (buat pilih saham paling likuid sebelum
  broker scan, hemat quota API vendor).
- **`src/providers/broker_data.py`** (baru) — `BaseBrokerDataProvider`
  abstraction mengikuti pola persis `market_data.py`. Default
  `NotConfiguredProvider` sengaja gagal EKSPLISIT (bukan silent no-op)
  kalau dipanggil sebelum provider vendor dipilih.
- **`src/signals/broker_engine.py`** (baru) — analisis net flow per
  saham, top buyer/seller broker, konsentrasi top-3 broker, streak
  akumulasi. Murni baca dari DB, tidak fetch — bisa langsung dipakai
  begitu `broker_summary` mulai terisi, apapun vendor yang dipilih.
- **`src/core/database.py`** — fungsi baru: `bulk_insert_broker_summary`,
  `get_broker_flow_range`, `get_broker_classification`,
  `get_top_liquid_tickers`.
- **`src/core/config.py`** — setting baru: `broker_data_provider`,
  `broker_scan_enabled` (default `False`), `broker_scan_top_n` (default 100).
- **`src/runner.py`** — command baru `broker_scan` (`cmd_broker_scan`),
  no-op aman kalau `broker_scan_enabled=False`.
- **`dashboard.py`** — halaman baru "Broker Flow" (leaderboard net flow +
  chart per saham), tampil "belum ada data" kalau `broker_summary` kosong.
  BELUM masuk composite scoring (`raw_score`) — murni informasional
  sampai ada validasi empiris memadai (pola sama dgn AUDIT di `ta_engine.py`).

### ⚠️ BELUM SELESAI — keputusan yang masih perlu diambil
1. **Sumber data broker summary belum dipilih.** `idx.co.id` melarang
   scraping di ToS + bot-blocked (sama seperti temuan Universe Manager
   di `AUDIT_REPORT_v2.md`) — jalan yang konsisten adalah vendor API
   berbayar (Invezgo, Sectors.app, dll), BUKAN scraper. Kerangka provider
   di `broker_data.py` sudah siap, tinggal isi 1 kelas provider konkret.
2. **`broker_classification` cuma di-seed 9 broker sebagai contoh** —
   perlu dilengkapi & diverifikasi dari sumber yang bisa dipercaya
   sebelum dipakai serius untuk analisis foreign flow.
3. Migration 004 belum dijalankan di Supabase (jalankan manual di SQL
   Editor seperti migration 001-003).

---

## v2.3.1 — Weekly Report Beneran Kirim Weekly Report (2026-08)

### 🐛 Bug ditemukan dari laporan user: pesan Telegram salah total
User lapor pesan mingguan yang diterima format-nya "RINGKASAN HARIAN" isinya
semua "N/A" (lihat screenshot), bukan format WEEKLY REPORT yang seharusnya.
Ditelusuri: `cmd_weekly_report()` di `runner.py` ternyata **STUB** — manggil
`send_daily_summary()` (fungsi buat notifikasi HARIAN) dengan data hardcode
`"N/A"` semua, BUKAN `send_weekly_report()` yang sudah ada & benar formatnya.
`send_weekly_report()` sendiri sudah lama nunggu `stats` dict dari
`gather_weekly_stats()` yang **disebut di docstring tapi tidak pernah ditulis**.

### ✅ Fix: `gather_weekly_stats()` (BARU, `src/runner.py`)
Kumpulkan data asli dari database, tiap section dibungkus try/except sendiri
(1 sumber gagal tidak menggagalkan section lain):
- **Universe**: total saham aktif + added/removed 7 hari terakhir, dihitung
  dari `created_at`/`delisted_date` di tabel `stocks` (BUKAN dari return
  value `refresh_universe()` — itu tidak persisten lintas proses CLI yang
  terpisah, karena tiap `python -m src.runner X` adalah proses baru).
- **Database**: dari `health_check()` yang sudah ada.
- **Backtest**: agregat `get_backtest_results()` yang di-filter ke `run_date`
  7 hari terakhir (avg win rate/profit factor/sharpe, strategi terbaik).
- **Scanner**: `get_weekly_scanner_stats()` (BARU) — hitung STRONG_BUY/BUY/
  WATCHLIST dari tabel `signals` 7 hari terakhir.
- **System Health**: database + `check_telegram_health()` (ping API beneran,
  bukan cuma cek token ada) + GitHub (implisit True kalau kode ini jalan) + Supabase.
- **Market**: `get_latest_regime()` — breadth dari advance/decline count.
- **Top 5 Sektor**: `get_latest_sector_rankings()`.
- **Top 5 Sinyal**: `get_top_signals_range()` (BARU) — top `raw_score` 7 hari terakhir.

Diuji dgn mock data realistis (termasuk skenario SEMUA sumber gagal sekaligus)
sebelum dianggap aman — pesan yang dihasilkan persis cocok format yang diminta user.

### ⏮️ `backfill_patterns` ditambahkan ke `weekly_maintenance.yml`
Sesuai request — step baru "🔎 Backfill Trend/Pattern" jalan tiap Sabtu,
setelah DB Cleanup, sebelum Refresh Universe. Aman (idempotent, `continue-on-error`)
karena cuma proses baris yang trend_structure-nya masih NULL.

### 🎲 Ketemu & fix bug lain yang TIDAK berhubungan (sekalian, bukan disengaja cari)
`tests/unit/test_core.py` (6 tempat) & `tests/smoke/test_smoke.py` (1 tempat):
`pd.date_range(end=date.today(), periods=n, freq="B")` kembalikan `n-1` tanggal
kalau `date.today()` jatuh di Sabtu/Minggu (pandas business-day anchor behavior).
Baru ketahuan sekarang murni karena kebetulan tanggal jalan test = akhir pekan,
sama sekali tidak terkait perubahan manapun di CHANGELOG ini. Diperbaiki dengan
helper kecil yang mundurkan anchor ke business day terdekat sebelum generate range.


## v2.3.0 — Snapshot Sinyal Lengkap + Trend Structure & Pattern Detection (2026-08)

### 🔍 Audit dulu, baru kerja: sebagian besar sudah ada
Sebelum menulis kode, saya audit `signal_evaluator.py` dulu terhadap permintaan
"simpan snapshot lengkap per sinyal". Ternyata **sebagian besar SUDAH tersimpan**
sejak sebelumnya: identitas (ticker/signal_date/timeframe/sector/market_regime/
signal_type), semua nilai indikator mentah (RSI+slope, MACD line/signal/hist,
EMA20/50/200, SMA20/50/200, ATR, ADX, DI+/-, volume+relative volume, Bollinger
position, distance EMA), kondisi (trend/momentum/volume condition), SELURUH
komponen scoring (trend/momentum/volume/strength/volatility score, sector_bonus,
regime_weight, raw_score, final_score, confidence), dan `reasons` (alasan sinyal).
Yang GENUINELY kosong cuma 2 kolom: `trend_structure` dan `pattern_detected`
(ada di schema, RESERVED, tidak pernah diisi — tidak ada engine-nya).

### 🆕 `src/signals/pattern_engine.py` (modul baru, berdiri sendiri)
- `detect_trend_structure()` — swing pivot terkonfirmasi (window kiri-kanan, no
  lookahead) → klasifikasi Higher High / Higher Low / Lower High / Lower Low /
  Breakout / Pullback / Consolidation.
- `detect_candlestick_patterns()` — Bullish Engulfing, Hammer, Doji, Morning Star.
- `detect_breakout_pattern()` — breakout resistance 20-bar, dengan/tanpa konfirmasi volume.
- `detect_support_resistance()` — dekat swing high/low terkonfirmasi (proximity 2%).
- `detect_divergence()` — RSI bullish/bearish divergence vs swing pivot harga.
- `detect_all_patterns()` — gabungan semuanya, tiap sub-deteksi dibungkus try/except
  (satu gagal tidak menggagalkan yang lain).
- **19 unit test baru** (`tests/unit/test_pattern_engine.py`), termasuk edge case
  data pendek/None.
- ⚠️ **HEURISTIK berbasis aturan, BUKAN divalidasi empiris** (beda dgn
  volatility_score/minus_di di v2.2.0 yang sudah teruji ke data live). Belum
  di-wire ke scoring manapun — sengaja, sampai ada validasi seperti yang lain.

### 🔌 Wiring (`src/signals/signal_evaluator.py`)
- `capture_todays_signals()` sekarang panggil `detect_trend_structure()` &
  `detect_all_patterns()`, isi kolom `trend_structure`/`pattern_detected`.
- `reasons` diperluas 2 tag baru: "ATR Sehat" (atr_pct 1-4%) & "Market Regime Bull",
  plus pattern yang terdeteksi ikut masuk `reasons` (mis. "Breakout Resistance").

### 🗄️ `migrations/003_signal_results.sql` (BARU)
Ketemu gap infra: tabel `signal_results` direferensikan di kode ("migration 003")
tapi FILE MIGRATION-NYA TIDAK ADA di repo — sepertinya dibuat manual di Supabase.
Migration ini mendokumentasikan skema lengkap yang sudah berjalan (idempotent,
`CREATE TABLE IF NOT EXISTS`) + resmi menambah `trend_structure`/`pattern_detected`.
**WAJIB dijalankan di Supabase SQL editor sebelum deploy**, kalau tidak field baru
akan silently didrop oleh `_upsert_with_schema_fallback()`.

### ⏮️ Backfill data lama (jawaban atas "apa sinyal lama ikut keisi?")
**Tidak, otomatis** — `capture_todays_signals()` cuma jalan sekali per sinyal
saat PERTAMA dibuat, tidak pernah re-run ke baris lama; `evaluate_open_signals()`
(yang menutup sinyal OPEN→CLOSED) juga cuma update kolom exit-related, tidak
menyentuh trend_structure/pattern_detected. Jadi sinyal lama (baik yang sudah
CLOSED maupun yang masih OPEN dan baru ditutup nanti) akan **tetap NULL** di
2 kolom itu kecuali di-backfill manual.

**BARU: `backfill_trend_and_patterns()`** (`src/signals/signal_evaluator.py`) +
command `python -m src.runner backfill_patterns`:
- Ambil semua baris `trend_structure IS NULL`, kelompok per ticker (irit query).
- Untuk tiap baris, SLICE data harga sampai `signal_date`-nya saja (bukan sampai
  hari ini) — hasil deteksi persis seolah pattern_engine sudah ada sejak awal,
  tanpa lookahead bias.
- Skip baris yang riwayat harga sebelum `signal_date`-nya kurang dari 90 hari
  (data tidak cukup buat swing pivot yang bermakna) — dicatat sbg `skipped_no_data`,
  bukan dipaksa isi dengan hasil tidak reliable.
- **Sengaja TIDAK menyentuh `reasons`** — cuma isi 2 kolom yang tadinya kosong,
  histori "alasan sinyal muncul" yang sudah tercatat dibiarkan apa adanya.
- Idempotent — aman dijalankan berkali-kali, baris yang sudah keisi otomatis
  terlewat di run berikutnya (tidak reset ke NULL, tidak dobel proses).
- Diuji dgn mock DB (grouping per ticker, skip data kurang, skip ticker tanpa
  data, konfirmasi `reasons` tidak ikut terkirim) sebelum dianggap aman jalan.

**Cara pakai**: jalankan migration 003 dulu, deploy kode ini, lalu jalankan
`python -m src.runner backfill_patterns` SEKALI buat isi data lama. Sinyal baru
setelah itu otomatis terisi lewat `capture_todays_signals()`, tidak perlu backfill lagi.

### 🖥️ Dashboard — Signal Performance
**BARU: tab "SNAPSHOT SINYAL"** — drill-down per SATU sinyal spesifik (bukan
agregat), pilih dari dropdown, tampilkan semua data di atas dalam 5 tab:
Indikator, Kondisi & Struktur, Pattern, Score Breakdown (semua komponen, bukan
cuma Final Score), Alasan & Trading Plan.

Sempat ketemu & perbaiki bug NaN-truthy sebelum rilis: kalau `pattern_detected`/
`reasons` kosong, pandas mengembalikan `NaN` (float) — `if nan_value:` di Python
itu **True** (NaN truthy), jadi `for p in pats:` bisa crash. Diperbaiki dengan
normalisasi NaN→None sekali di awal (`row.astype(object).where(pd.notna(row), None)`)
sebelum dipakai fungsi manapun.


## v2.2.0 — Kalibrasi Scoring dari Data Live + Konsistensi raw_score (2026-08)

Basis: analisis empiris 63 sinyal `signal_results` CLOSED (27-31 Jul 2026),
**re-validasi di n=140** (27 Jul - 4 Aug 2026) sebelum implementasi — lihat
bagian "Validasi n=140" di bawah.

### 🎯 Scoring (`src/signals/ta_engine.py`, dicerminkan di `src/backtest/engine.py`)
- **`volatility_score`: bobot dipotong 10 → 4 poin.** Prediktor terkuat di
  seluruh fitur, di KEDUA sample (korelasi -0.50 lalu -0.45 dgn net_return_pct),
  arahnya terbalik dari desain: skor rendah avg return +12.8% lalu +11.3%,
  skor menengah cuma +0.7% lalu +3.4%. Pola makin kuat tervalidasi dgn sample
  lebih besar. Didiskon berat sampai ada cukup data buat re-validasi per-komponen
  (ATR%/BB-position).
- **`strength_score`: bobot naik 15 → 21 poin, tambah DI Quality.** `plus_di`/`minus_di`
  sudah dihitung & disimpan sejak lama tapi tidak pernah dipakai scoring. Empiris
  (n=140): `minus_di<10` → 89.3% win/+11.5% avg. `minus_di>20` → 65.0% win/+2.8% avg.
  Efeknya melunak dibanding estimasi awal n=63 (dulu 90%/+15.5% vs 45.5%/-0.29%) tapi
  arahnya tetap konsisten. ADX tinggi kini di-discount kalau `minus_di` dominan
  (tren kuat tapi arahnya turun bukan alasan nambah skor).
- Total tetap 0-100 (30/25/20/21/4). `config.py::weight_*` disinkronkan (masih dokumentasi,
  belum live-wired — lihat catatan baru di situ).
- `build_factor_contribution()`: highlight baru "⚠️ Tekanan Jual Dominan" / "DI Bullish Sehat";
  highlight "Trend kuat (ADX)" tidak lagi muncul kalau trennya ternyata bearish-dominant.
- `backtest/engine.py::_add_indicators()`: `plus_di`/`minus_di` kini disimpan sbg kolom
  (sebelumnya cuma `adx` — bikin `_score_row()` versi lama tidak bisa akses DI sama sekali).

### 🐛 Konsistensi raw_score vs final_score (composite_score)
`final_score` sejak v2.1 sudah bukan dasar klasifikasi sinyal (lihat `_determine_signal_type`),
tapi 3 tempat masih pakai `composite_score` (final_score) buat ranking/filter/tampilan:
- `dashboard.py`: `load_signals()`/`load_signals_range()` ORDER BY, slider "Skor Minimum" filter,
  badge skor di list & detail sinyal, gauge breakdown (max value disesuaikan ke 21/4 juga).
- `src/telegram/bot.py`: pesan "Sinyal Aktif dari Kemarin" & "Top 5 Sinyal Minggu Ini".
- `src/signals/scanner.py`: sort kandidat pakai `raw_score` (identik hasil dgn `final_score`
  dalam 1x scan run karena `regime_weight` sama utk semua kandidat, tapi lebih jelas maknanya).

  *(Catatan kejujuran: alasan utama fix ini adalah KONSISTENSI DESAIN — raw_score yang
  benar-benar dipakai `_determine_signal_type()`, bukan klaim "raw_score jauh lebih
  prediktif". Di re-validasi n=140, korelasi raw_score (0.086) dan final_score (0.011)
  sama-sama lemah — gap-nya menyempit dibanding estimasi awal n=63. Fix ini tetap
  dipertahankan atas dasar konsistensi, bukan atas dasar keunggulan prediktif raw_score.)*

### 🧹 Housekeeping
- `scanner.py::_load_batch_from_db()`: hapus log `[DEBUG]` verbose sisa debugging (termasuk
  satu baris yang hardcode cek ticker `AGRO.JK`), turunkan sisanya ke `log.debug()`.

### 🖥️ Dashboard — Signal Performance
- **BARU: "Detail Per Saham"** — breakdown per-ticker dari `signal_results` (n, win rate,
  avg/total return, best/worst, avg holding), dgn filter minimal jumlah sinyal biar tidak
  kepancing sampel n=1. Sebelumnya cuma ada agregat + backtest summary (sumber data terpisah).
- **BARU: "Score Calibration"** — bar chart avg return per bucket utk `raw_score`,
  `volatility_score`, `minus_di`, `adx`. Tujuannya supaya validasi "apakah skor benar-benar
  prediktif" bisa dicek kapan saja langsung dari dashboard, tidak perlu analisis CSV manual lagi.

### ✅ Validasi n=140 (27 Jul - 4 Aug 2026, sebelum implementasi ke production)
Data closed bertambah dari 63 → 140 baris (697 total, 557 masih OPEN) sebelum
perubahan di atas benar-benar di-deploy. Hasil re-cek:

| Temuan | Status |
|---|---|
| `volatility_score` prediktor terkuat, arah terbalik | ✅ Makin kuat (korelasi -0.50→-0.45, bucket rendah tetap ~2x lipat return bucket menengah) |
| Rule gabungan (`volatility_score≤4` + `minus_di<20` + `adx≥25` + bukan Energy) | ✅ Makin kuat (n=20→35, 90%/15.9% → 91.4%/15.1% win/avg, p<0.0001) |
| Regime SIDEWAYS > BULL | ✅ Konsisten (81.5% vs 75.7% win rate) |
| `minus_di>20` = bucket terlemah | ✅ Arah konsisten, tapi ⚠️ efeknya melunak (lihat tabel di atas) |
| Sektor Energy sangat jelek (0% win, n=5) | ⚠️ Melunak jadi avg -0.09% (n=16) — masih terlemah tapi tidak seekstrem awal, sebagian besar itu noise sampel kecil |
| "raw_score jauh lebih prediktif dari final_score" | ❌ **Dikoreksi** — korelasi keduanya sama-sama lemah di n=140 (0.086 vs 0.011). Fix konsistensi tetap jalan, tapi bukan atas alasan ini |
| "ADX sweet spot 35-45" (dari analisis pertama) | ❌ **Tidak terbukti** — data n=140 malah monoton bersih, ADX 40+ jadi bucket terbaik (87% win). Untungnya scoring ADX magnitude tidak diubah di fix ini, jadi tidak ada kontradiksi kode |

**Belum diimplementasikan** (kandidat perbaikan lanjutan, bukan bagian rilis ini):
`plus_di` kini juga menunjukkan pola monoton bersih (0-20→+2.7%, 40+→+17.7% avg) —
berpotensi jadi bonus eksplisit di `_score_strength()`, belum ditambahkan.

Re-validasi berkala lewat dashboard Score Calibration tetap dianjurkan begitu data
live bertambah (target ≥300 sinyal).

---

## v2.1.0 — Audit Menyeluruh: Universe, Adaptive Threshold, Backtest Realism (2026-07)

Lihat `AUDIT_REPORT_v2.md` untuk laporan lengkap dengan bukti empiris tiap perubahan.

### 🌐 Universe Manager
- Curated seed diperluas dari ~140 → **551 ticker unik** (11 sektor IDX-IC), setelah riset
  konfirmasi bahwa scraping idx.co.id langsung melanggar ToS resmi mereka DAN diblokir bot
  detection — solusi via Yahoo Finance validation tetap dipertahankan sebagai satu-satunya
  sumber otomatis yang legal & stabil.
- `EXTRA_UNIVERSE_SOURCE_URL` (opsional) — tambah ticker dari sumber pilihan sendiri tanpa edit kode.
- Safety guard baru: mencegah gangguan Yahoo Finance sesaat disalahartikan sebagai delisting massal.

### 🎯 Adaptive Threshold (Fix Signifikan)
- **STRONG_BUY yang sebelumnya matematis MUSTAHIL saat regime BEAR** (dan nyaris mustahil saat
  SIDEWAYS) kini bisa tercapai untuk setup yang benar-benar kuat, lewat threshold per-regime
  yang dibandingkan ke raw_score (bukan raw×regime_weight terhadap threshold tetap).
- Sector bonus kini diterapkan ke raw_score (bukan final_score yang sudah ter-diskon regime weight)
  — konsisten antar semua kondisi market.

### 📊 Market Breadth, Confidence Engine, Factor Contribution
- `breadth_data` yang sebelumnya parameter mati (tidak pernah terisi karena urutan pipeline)
  kini dihitung nyata dari % saham di atas EMA20/50/200 + advance/decline.
- Confidence Engine rule-based (Very High/High/Medium/Low) berdasar raw_score + jumlah dimensi kuat.
- Factor Contribution breakdown + highlights disiapkan untuk Dashboard/Telegram (data-only, UI belum diubah).

### 🔬 Backtest Engine
- Entry kini di open H+1 (bukan close hari sinyal) — realistis sesuai jadwal kirim sinyal 17:30 WIB.
- Resolusi SL/TP dalam candle yang sama kini konservatif (SL diperiksa lebih dulu).
- Skema scoring backtest diselaraskan persis dengan composite scoring live (0-100, 5 dimensi).

### 🛡️ Error Handling
- `_upsert_with_schema_fallback()` — mencegah 1 kolom baru menggagalkan seluruh insert (kelas bug
  yang sama dengan insiden 87 sinyal gagal tersimpan sebelumnya).
- `validate_ohlcv` kini menolak candle terbalik dan data tanpa volume sama sekali.

### 🗄️ Database
- `migrations/002_audit_improvements.sql` — additive, aman dijalankan kapan saja, tidak merusak data lama.

### ✅ Testing
- 49/49 test lulus (naik dari 46/49 — 3 bug pre-existing ikut diperbaiki), 0 regresi.

---

## v2.0.0 — Dashboard Upgrade (2025-06-25)

### 🆕 Pages Baru
- **Why This Signal?** — breakdown score per komponen (bar chart), detail semua indikator,
  dan interpretasi otomatis dalam bahasa Indonesia untuk Trend / Momentum / Volume / Strength / Volatility.
  Bisa diakses langsung dari tombol "Detail" di Top Signals.
- **Historical Signals** — tabel sinyal 7/14/30/60/90 hari terakhir, filterable by date/ticker/sector/type,
  distribusi sinyal (pie chart + bar chart per sektor), download CSV.
- **Signal Performance** — KPI utama (win rate, profit factor, expectancy, max drawdown),
  equity curve, win/loss pie, distribusi return histogram, monthly PnL bar chart, backtest summary table.

### ✨ Upgrade Pages Existing
- **Market Overview** — regime card dengan deskripsi teks, sparkline IHSG 30 hari
  dengan color-coded dots (🟢🟡🔴), A/D ratio, top/worst sektor, top 3 sinyal hari ini.
- **Top Signals** — tabel custom dengan score progress bar, signal badge warna,
  volume ratio color (hijau/kuning/merah), RS% color, tombol "Detail" per baris, download CSV.
- **Sector Rotation** — leaderboard dengan medal 🥇🥈🥉, score bar per sektor,
  return heatmap (1D/5D/20D), bubble chart momentum vs breadth.
- **Portfolio** — styled dataframe dengan warna PnL hijau/merah.
- **System Logs** — filter by level, color-coded messages.

### 🔧 Fixes & Robustness
- Semua nilai DB dikonversi via `sf()` / `si()` / `ss()` — tidak ada lagi TypeError dari None.
- `score_color()` dan `signal_badge()` dipakai konsisten di semua halaman.
- Navigation "Detail" dari Top Signals → Why This Signal? via `session_state`.
- Sidebar menampilkan regime + IHSG live.

### 📋 Backward Compatibility
- Tidak ada perubahan pada scanner, scoring engine, database schema, atau workflow.
- Semua query menggunakan kolom yang sudah ada sejak v1.0.

---

## v1.3.0 (2025-06-25)
- Fix SyntaxError di bot.py (unterminated string literal line 408)
- Tulis ulang bot.py menggunakan string concatenation

## v1.2.0 (2025-06-25)
- Workflow dipecah menjadi 3 job terpisah (pre_market / daily_scan / health_check)
- Pre-market alert sekarang tampilkan sinyal aktif dari kemarin
- Fix kondisi `if` di GitHub Actions yang tidak reliable

## v1.1.0 (2025-06-21)
- Hapus pandas-ta (package mati, tidak pernah digunakan)
- Fix yfinance MultiIndex column handling
- Health check tidak lagi exit(1) untuk warning non-kritis
- Tambah migrations/000_check_migration.sql
- Tambah TROUBLESHOOTING.md

## v1.0.0 (2025-06-19)
- Initial release: Universe Manager, TA Engine, Regime Engine,
  Sector Engine, Scanner, Telegram Bot, Portfolio Tracker,
  Backtest Framework, Streamlit Dashboard, GitHub Actions workflow
