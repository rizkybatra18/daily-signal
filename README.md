# 📈 DAILY SIGNAL — BEI Stock Scanner

**Sistem sinyal trading saham BEI yang berjalan 100% otomatis dan gratis.**

[![GitHub Actions](https://img.shields.io/badge/scheduler-GitHub%20Actions-2088FF?logo=github)](https://github.com)
[![Supabase](https://img.shields.io/badge/database-Supabase-3ECF8E?logo=supabase)](https://supabase.com)
[![Streamlit](https://img.shields.io/badge/dashboard-Streamlit-FF4B4B?logo=streamlit)](https://streamlit.io)
[![Python](https://img.shields.io/badge/python-3.11+-blue?logo=python)](https://python.org)

---

## ✨ Fitur Utama

| Fitur | Status | Keterangan |
|-------|--------|------------|
| 🌐 Universe Manager | ✅ | Auto-scan seluruh saham BEI |
| 📊 TA Engine | ✅ | EMA, RSI, MACD, ADX, ATR deterministik |
| 🎯 Composite Scoring | ✅ | Skor 0-100 berbasis rule (bukan AI) |
| 🏛️ Market Regime | ✅ | Deteksi BULL/SIDEWAYS/BEAR |
| 🏭 Sector Rotation | ✅ | Ranking 11 sektor BEI |
| 📐 Relative Strength | ✅ | Mansfield RS vs IHSG |
| ⚖️ Risk Management | ✅ | Entry/SL/TP otomatis berbasis ATR |
| 📱 Telegram Bot | ✅ | Notifikasi sinyal & TP/SL hit |
| 📊 Dashboard | ✅ | Streamlit modern, akses dari HP |
| 💼 Portfolio Tracker | ✅ | Unrealized/Realized PnL |
| 📖 Trade Journal | ✅ | Alasan entry/exit, screenshot |
| 🔬 Backtesting | ✅ | Walk-forward, no look-ahead bias |
| 🗄️ Database | ✅ | Supabase PostgreSQL (gratis) |
| ⚙️ Auto Scheduler | ✅ | GitHub Actions (gratis, 2000 menit/bulan) |
| 🔍 Structured Logging | ✅ | Log ke database, level INFO-CRITICAL |

---

## 🏗️ Arsitektur

```
GitHub Repository
       │
       ▼
GitHub Actions (Cron: Senin-Jumat 17:30 WIB)
       │
       ▼
Universe Manager → Seluruh saham BEI (800+)
       │
       ▼
Incremental Data Update (hanya download yang belum ada)
       │
       ▼
Supabase PostgreSQL (12 tabel)
       │
  ┌────┼────┐
  ▼    ▼    ▼
TA   Regime  Sector
Engine Engine  Engine
  │    │    │
  └────┼────┘
       │
  Composite Score (0-100)
  STRONG_BUY / BUY / WATCHLIST / AVOID
       │
  ┌────┴────┐
  ▼         ▼
Telegram  Dashboard
  Bot      Streamlit
```

---

## 🚀 Quick Start (30 Menit)

### 1. Fork/Clone Repository

```bash
git clone https://github.com/USERNAME/daily-signal.git
cd daily-signal
```

### 2. Setup Supabase

1. Buka [supabase.com](https://supabase.com) → New Project
2. Buka **SQL Editor** → Paste isi file `migrations/001_initial_schema.sql` → Run
3. Pergi ke **Settings → API**:
   - Copy `Project URL` → ini adalah `SUPABASE_URL`
   - Copy `service_role` key → ini adalah `SUPABASE_SERVICE_KEY`

### 3. Setup Telegram Bot

1. Cari **@BotFather** di Telegram → `/newbot` → ikuti instruksi
2. Copy token → ini adalah `TELEGRAM_BOT_TOKEN`
3. Tambahkan bot ke grup/channel Anda
4. Kirim pesan ke grup → buka `https://api.telegram.org/bot{TOKEN}/getUpdates`
5. Cari `"chat":{"id":-100xxxxxxx}` → ini adalah `TELEGRAM_CHAT_ID`

### 4. Setup GitHub Secrets

Di repository GitHub: **Settings → Secrets → Actions → New repository secret**

Tambahkan 4 secrets:
| Secret | Nilai |
|--------|-------|
| `SUPABASE_URL` | URL dari Supabase |
| `SUPABASE_SERVICE_KEY` | Service role key |
| `TELEGRAM_BOT_TOKEN` | Token dari BotFather |
| `TELEGRAM_CHAT_ID` | Chat ID grup/channel |

### 5. Aktifkan GitHub Actions

Push ke repository → Pergi ke tab **Actions** → Enable workflows

### 6. Setup Streamlit Dashboard

1. Buka [share.streamlit.io](https://share.streamlit.io) → Connect GitHub
2. Pilih repository ini → `dashboard.py`
3. Di **Advanced Settings → Secrets**, tambahkan:

```toml
SUPABASE_URL = "https://xxx.supabase.co"
SUPABASE_SERVICE_KEY = "eyJ..."
TELEGRAM_BOT_TOKEN = "1234:xxx"
TELEGRAM_CHAT_ID = "-100xxx"
```

4. Deploy → Dashboard Anda siap!

### 7. Test Manual (Opsional)

```bash
pip install -r requirements.txt
cp .env.example .env
# Edit .env dengan nilai yang benar

# Test health check
python -m src.runner health_check

# Test scan manual (tanpa Telegram)
python -m src.runner daily_scan --no-telegram
```

---

## 📊 Cara Membaca Sinyal

### Signal Types

| Sinyal | Score | Artinya |
|--------|-------|---------|
| 🚀 STRONG_BUY | ≥ 75 | Semua indikator selaras, volume konfirmasi |
| 🟢 BUY | 60-74 | Setup bagus, layak trading |
| 👀 WATCHLIST | 45-59 | Menarik tapi belum konfirmasi |
| 🔴 AVOID | < 45 | Tidak memenuhi kriteria |

### Composite Score (0-100)

```
Trend Score     (0-30): EMA alignment, posisi vs EMA
Momentum Score  (0-25): RSI zone, MACD direction & crossover
Volume Score    (0-20): Volume ratio, volume spike
Strength Score  (0-15): ADX trend strength, RS vs IHSG
Volatility Score(0-10): ATR position, Bollinger Band
─────────────────────────────────────────────────
Total Raw       (0-100)
× Regime Weight (0.4 / 0.75 / 1.0)
= Final Score   (0-100)
```

### Risk Management

Semua level berbasis ATR (Average True Range):
- **Entry**: Harga close saat sinyal
- **Stop Loss**: Entry − (1.5 × ATR)  → risiko ~1.5 ATR
- **Target 1**: Entry + (1.5 × ATR)  → R:R = 1:1
- **Target 2**: Entry + (2.5 × ATR)  → R:R = 1:1.67

Position sizing: Maksimal 1% risiko modal per trade.

---

## 🏛️ Market Regime

| Regime | IHSG Condition | Scoring Weight | Aksi |
|--------|----------------|----------------|------|
| 📈 BULL | > EMA20, RSI > 55, 5D > +1% | 1.0 (normal) | Semua sinyal aktif |
| ↔️ SIDEWAYS | Mixed signals | 0.75 (-25%) | Selektif |
| 📉 BEAR | < EMA20, RSI < 40, 5D < -3% | 0.4 (-60%) | Suppress sinyal |

---

## 📂 Struktur Project

```
daily_signal/
├── .env.example                   # Template environment variables
├── .github/
│   └── workflows/
│       ├── daily_scan.yml         # Scan harian + pre-market alert
│       └── weekly_maintenance.yml # Maintenance & refresh universe
├── migrations/
│   └── 001_initial_schema.sql    # Database schema (12 tabel)
├── src/
│   ├── core/
│   │   ├── config.py             # Settings dari env vars
│   │   ├── database.py           # Supabase connection & CRUD
│   │   └── logger.py             # Structured logging
│   ├── providers/
│   │   ├── universe_manager.py   # Auto-discover saham BEI
│   │   └── market_data.py        # Provider abstraction (Yahoo Finance)
│   ├── signals/
│   │   ├── ta_engine.py          # TA indicators + composite scoring
│   │   ├── regime_engine.py      # Market regime detection
│   │   ├── sector_engine.py      # Sector rotation
│   │   └── scanner.py            # Main scan orchestrator
│   ├── telegram/
│   │   └── bot.py                # Telegram notifications
│   ├── portfolio/
│   │   └── tracker.py            # Portfolio & PnL tracking
│   ├── backtest/
│   │   └── engine.py             # Backtesting framework
│   └── runner.py                 # CLI entry point
├── tests/
│   ├── unit/test_core.py         # Unit tests
│   └── smoke/test_smoke.py       # Smoke tests
├── dashboard.py                  # Streamlit dashboard
├── requirements.txt
├── pyproject.toml                # Pytest config
├── AUDIT_REPORT.md               # Laporan audit sistem lama
└── README.md
```

---

## 🔄 Jadwal Otomatis

| Waktu (WIB) | Event | Keterangan |
|-------------|-------|------------|
| 08:30 | Pre-Market Alert | Kirimi kondisi IHSG + regime ke Telegram |
| 17:30 | Daily Scan | Scan semua saham, kirim sinyal |
| 17:35 | Portfolio Update | Update harga posisi aktif |
| 17:40 | Portfolio Snapshot | Simpan equity curve harian |
| Sabtu 09:00 | Weekly Maintenance | Cleanup DB + refresh universe + backtest |

---

## 🔧 Maintenance

### Update Universe (auto setiap Sabtu)
```bash
python -m src.runner refresh_universe
```

### Backup Database
Supabase menyediakan backup otomatis (pro tier) atau export manual:
1. Supabase Dashboard → Settings → Backups
2. Atau gunakan: `pg_dump $(supabase db url)` via CLI

### Troubleshooting

**Scan tidak berjalan:**
1. Cek GitHub Actions → tab Actions → lihat workflow run terbaru
2. Pastikan secrets sudah diisi dengan benar
3. Cek system_logs di Supabase Dashboard

**Telegram tidak menerima pesan:**
1. Cek apakah bot sudah di-add ke grup
2. Cek `TELEGRAM_CHAT_ID` — harus diawali `-100` untuk grup
3. Test: `python -m src.runner health_check`

**Data tidak terupdate:**
1. Cek koneksi Supabase: `python -m src.runner health_check`
2. Cek GitHub Actions logs
3. Yahoo Finance mungkin rate limit — coba lagi 1 jam kemudian

---

## ⚠️ Disclaimer

**DAILY SIGNAL adalah alat bantu analisis teknikal, BUKAN rekomendasi investasi.**

- Selalu lakukan riset mandiri (DYOR)
- Gunakan money management yang ketat
- Tidak ada sistem yang 100% akurat
- Investasi dan trading mengandung risiko kehilangan modal
- Sistem ini tidak bertanggung jawab atas keputusan investasi Anda

---

## 📜 License

MIT License — Bebas digunakan dan dimodifikasi untuk keperluan pribadi.
