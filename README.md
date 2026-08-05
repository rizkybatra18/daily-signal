# DAILY SIGNAL — Changelog

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
