# DAILY SIGNAL — Changelog

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
