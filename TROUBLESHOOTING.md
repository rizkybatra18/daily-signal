# 🔧 TROUBLESHOOTING GUIDE — DAILY SIGNAL

---

## ❌ Error 1: Database `PGRST125` — "Invalid path specified in request URL"

### Penyebab
Migration SQL **belum dijalankan** di Supabase. Tabel-tabel sistem belum ada.

### Cara Fix (2 menit)

1. Buka [supabase.com](https://supabase.com) → Login → pilih project Anda
2. Klik **"SQL Editor"** di menu kiri
3. Buka file `migrations/001_initial_schema.sql` dari ZIP
4. **Copy semua isi file** → paste ke SQL Editor
5. Klik tombol **"Run"** (▶)
6. Pastikan muncul pesan: `✅ DAILY SIGNAL Schema berhasil dibuat!`
7. Re-run GitHub Actions workflow

**Verifikasi (opsional):** Jalankan `migrations/000_check_migration.sql` dulu untuk cek tabel mana yang belum ada.

---

## ❌ Error 2: Data Provider `rows: 0` — Yahoo Finance tidak return data

### Penyebab
`yfinance` versi baru mengubah format output — kolom menjadi MultiIndex atau nama kolom berbeda.
Sudah difix di v1.1 dengan deteksi otomatis format output.

### Cara Fix
Sudah otomatis di v1.1. Pastikan Anda menggunakan file `src/providers/market_data.py` dari **ZIP v1.1**.

---

## ❌ Error 3: Health Check exit(1) menghentikan seluruh workflow

### Penyebab
Health check versi lama langsung `sys.exit(1)` bahkan untuk warning (Telegram lambat, Yahoo rate limit).

### Cara Fix (v1.1)
Health check sekarang hanya `exit(1)` jika **database** tidak bisa diakses.
- Telegram masalah → warning, workflow lanjut
- Yahoo Finance masalah → warning, workflow lanjut
- Database down → exit(1), workflow berhenti (ini memang harus berhenti)

---

## 📋 Urutan Setup yang Benar

```
1. Buat project Supabase
2. Jalankan migrations/001_initial_schema.sql di SQL Editor  ← WAJIB PERTAMA
3. Copy SUPABASE_URL dan SUPABASE_SERVICE_KEY
4. Buat Telegram bot via @BotFather
5. Tambah 4 secrets ke GitHub repository
6. Enable GitHub Actions
7. Run workflow manual: mode = health_check
8. Jika health check OK → Run mode = full_scan
```

---

## 🔍 Cara Baca Log GitHub Actions

Di tab **Actions** → klik run yang gagal → klik step yang merah:

| Pesan Log | Artinya | Solusi |
|-----------|---------|--------|
| `PGRST125` | Tabel tidak ada | Jalankan migration SQL |
| `Invalid API key` | SUPABASE_SERVICE_KEY salah | Cek dan update secret |
| `rows: 0` (data provider) | Yahoo rate limit | Coba lagi 1 jam kemudian |
| `Invalid token` (Telegram) | BOT_TOKEN salah | Cek token dari @BotFather |
| `chat not found` | CHAT_ID salah | Pastikan bot sudah di-add ke grup |
| `timeout` | Koneksi lambat | Retry otomatis, biasanya sembuh sendiri |

---

## ✅ Checklist Verifikasi Setelah Setup

- [ ] SQL Editor menampilkan "Schema berhasil dibuat"
- [ ] Supabase Table Editor menampilkan 12 tabel
- [ ] GitHub Secrets terisi: `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`
- [ ] Health check workflow berhasil (✓ database OK)
- [ ] Bot Telegram sudah di-add ke grup/channel
- [ ] Full scan menghasilkan pesan di Telegram
