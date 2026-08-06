# DAILY SIGNAL — Changelog

---

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
