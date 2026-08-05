# LAPORAN AUDIT TOTAL — stock_bot
**Daily Signal System | Audit oleh: Principal Quant Developer**
**Tanggal Audit:** 2025-06-19

---

## RINGKASAN EKSEKUTIF

Sistem stock_bot yang ada adalah **Proof of Concept (PoC)** level — mampu berjalan di Google Colab untuk demonstrasi, namun memiliki **21 kelemahan kritis** yang menjadikannya tidak layak untuk produksi. Audit ini mendokumentasikan semua temuan dan menjadi landasan pembangunan ulang sistem menjadi **DAILY SIGNAL** yang production-grade.

**Overall Score: 2.5/10** (tidak layak produksi)

---

## 1. KELEMAHAN ARSITEKTUR

### 1.1 Tidak Ada Persistensi Data [KRITIS]
**Masalah:** Seluruh data tersimpan di memori RAM. Ketika Google Colab session berakhir (maksimal 12 jam untuk free tier), seluruh data hilang.
- `active_signals.json` hanya ada di filesystem lokal Colab
- `backtest_cache.json` sama
- Tidak ada database
- Tidak ada backup

**Dampak:** Sistem tidak bisa melacak trade history, tidak ada audit trail, data hilang setiap restart.

### 1.2 Scheduler Bergantung pada Colab [KRITIS]
**Masalah:** `main.py --schedule` menggunakan `while True: time.sleep()` — artinya membutuhkan komputer/Colab aktif 24 jam.
- Google Colab free tier disconnect setelah ~1-2 jam idle
- Tidak ada mekanisme recovery jika session mati
- Jika Colab crash, semua sinyal hari itu terlewat

**Dampak:** Bot tidak bisa berjalan otomatis tanpa manusia menjaga layar.

### 1.3 Ketergantungan Tunggal pada Yahoo Finance [KRITIS]
**Masalah:** `data_agent.py` hanya menggunakan `yfinance` tanpa fallback.
- Jika Yahoo Finance down/rate limit, seluruh sistem berhenti
- Tidak ada abstraction layer
- Tidak bisa diganti provider lain

### 1.4 Desain Tidak Modular [TINGGI]
**Masalah:** File `strategy_agent.py` berisi logika AI, filter, ranking, dan risk management sekaligus (500+ baris).
- Sulit di-test secara unit
- Sulit di-extend tanpa merusak yang lain
- Tight coupling antar komponen

### 1.5 Konfigurasi Hardcoded [TINGGI]
**Masalah:** API keys diisi langsung di `config.py`, bukan environment variables.
- Risiko commit secrets ke Git
- Tidak bisa deploy ke environment berbeda
- Tidak ada validation apakah key sudah diisi

---

## 2. BOTTLENECK PERFORMA

### 2.1 Download Data Serial [KRITIS]
**Masalah:** `fetch_all_stocks()` melakukan download satu per satu (sequential loop).
```python
for ticker in watchlist:          # ← serial, lambat!
    daily = fetch_ohlcv(ticker, ...) 
    intraday = fetch_ohlcv(ticker, ...)
```
- 50 saham × 2 request × ~2 detik = **200 detik** hanya untuk download
- GitHub Actions free tier: 2000 menit/bulan — akan habis dalam 10 hari

### 2.2 Re-Download Full History Setiap Run [KRITIS]
**Masalah:** Sistem mengunduh ulang 60 hari data setiap kali dijalankan, bahkan jika data sudah ada.
- `PERIOD_DAYS = "60d"` diunduh 3x sehari
- Pemborosan bandwidth dan API calls
- Tidak ada incremental update

### 2.3 Backtest Download Data 4+ Tahun Setiap Kali [KRITIS]
**Masalah:** `_fetch_history()` di `backtest_agent.py` mengunduh 2021-2024 setiap run.
- Cache 24 jam bisa expired → re-download
- Cache hanya di filesystem, hilang saat Colab restart
- 50 saham × 4 tahun data = massive API calls

### 2.4 AI API Call Serial Per Saham [TINGGI]
**Masalah:** Setiap saham dianalisis satu per satu dengan Gemini API.
- 5 saham × ~3 detik per call = 15 detik minimum
- Jika rate limit kena, per-saham retry menambah waktu

---

## 3. BUG POTENSIAL

### 3.1 NameError pada audit_agent.py [BUG KONFIRMASI]
```python
def get_current_price(ticker: str) -> float | None:
    df = yf.download(...)
    if isinstance(df.columns, pd.MultiIndex):    # ← pd tidak di-import!
        df.columns = df.columns.get_level_values(0)
```
`pandas` tidak di-import di `audit_agent.py` — akan crash saat runtime.

### 3.2 Race Condition pada active_signals.json [BUG KRITIS]
**Masalah:** `load_active_signals()` dan `save_active_signals()` tidak menggunakan locking.
- Jika `audit_loop` dan `pipeline` berjalan bersamaan → data corrupt
- Tidak ada atomic write

### 3.3 JSON Parsing Greedy Regex [BUG]
```python
json_match = re.search(r'\{[\s\S]*?\}', text)  # ← non-greedy, hanya match { }
```
Regex `.*?` (non-greedy) pada `\{[\s\S]*?\}` hanya mengambil JSON sampai `}` pertama, bukan JSON object lengkap. Jika ada nested object, hanya bagian pertama yang ter-parse.

### 3.4 Division by Zero Potensial [BUG]
```python
rr = abs(tp1 - entry) / abs(entry - sl)  # ← crash jika entry == sl
```
Tidak ada guard untuk kasus ATR = 0.

### 3.5 Type Error pada CONFIDENCE_LABEL [BUG]
```python
CONFIDENCE_LABEL = {
    range(0,  50): "Lemah",
    range(50, 65): "Moderat",  # ← dict key berupa range object
}
for r, label in CONFIDENCE_LABEL.items():
    if confidence in r:        # ← ini works di Python 3.x, tapi O(n) setiap call
```
Meskipun fungsional, penggunaan `range` sebagai dict key tidak idiomatis dan berpotensi error pada edge case.

---

## 4. TECHNICAL DEBT

### 4.1 Tidak Ada Error Recovery [KRITIS]
- Pipeline berhenti total jika satu saham error
- Tidak ada retry mechanism
- Tidak ada circuit breaker
- Tidak ada health monitoring

### 4.2 Tidak Ada Logging Terstruktur [TINGGI]
- Semua output menggunakan `print()` — tidak bisa di-filter atau di-monitor
- Tidak ada log level (DEBUG/INFO/WARNING/ERROR)
- Tidak ada log persistence

### 4.3 Tidak Ada Testing [TINGGI]
- Tidak ada unit test
- Tidak ada integration test  
- Tidak ada CI/CD pipeline
- Manual testing di Colab tidak reproducible

### 4.4 Secrets Management Buruk [TINGGI]
```python
TELEGRAM_BOT_TOKEN = "ISI_TOKEN_BOT_TELEGRAM_KAMU"  # ← hardcoded placeholder
```
Jika developer tidak hati-hati, bisa ter-commit ke Git.

### 4.5 Dependency Management Tidak Ada [TINGGI]
- Tidak ada `requirements.txt`
- Tidak ada version pinning
- Breaking change dari library bisa crash sistem kapan saja

---

## 5. MASALAH SKALABILITAS

### 5.1 Watchlist Statis 50 Saham [KRITIS]
**Masalah:** BEI memiliki 800+ saham aktif. Sistem hanya memonitor 50.
- Tidak bisa auto-detect IPO baru
- Tidak bisa auto-remove saham delisting
- Peluang saham bagus di luar watchlist terlewat

### 5.2 Tidak Bisa Scale Horizontal [TINGGI]
- Tidak ada queue/job system
- Semua proses single-threaded dan single-instance
- Tidak bisa distribute load ke multiple workers

---

## 6. MASALAH KEAMANAN

### 6.1 API Keys di Source Code [KRITIS]
- Token Telegram langsung di `config.py`
- Mudah ter-expose jika repo dipublikkan
- Tidak ada enkripsi

### 6.2 Tidak Ada Validasi Input [TINGGI]
- Tidak ada sanitasi pada ticker yang diproses
- Response AI tidak divalidasi schema secara ketat
- Tidak ada rate limiting pada Telegram bot

### 6.3 File JSON Tidak Terenkripsi [SEDANG]
- `active_signals.json` berisi data posisi trading tanpa enkripsi
- Siapa pun yang akses filesystem bisa baca dan modifikasi

---

## 7. MASALAH KUALITAS DATA

### 7.1 Tidak Ada Data Validation [KRITIS]
- Tidak ada cek apakah data OHLCV valid (high > low, volume > 0)
- Tidak ada deteksi data anomali (split saham, stock dividend)
- Tidak ada cek konsistensi tanggal

### 7.2 VWAP Tidak Reset Per Hari [BUG DATA]
```python
def calc_vwap(df: pd.DataFrame) -> pd.Series:
    typical_price = (df["high"] + df["low"] + df["close"]) / 3
    vwap = (typical_price * df["volume"]).cumsum() / df["volume"].cumsum()
```
VWAP seharusnya reset setiap hari perdagangan. Implementasi ini menggunakan cumulative dari seluruh periode (5 hari intraday) — hasilnya tidak akurat.

### 7.3 Corporate Action Tidak Ditangani [TINGGI]
- Stock split akan membuat harga anomali
- Dividen saham tidak di-adjust
- `auto_adjust=True` di yfinance membantu sebagian, tapi tidak semua kasus

---

## 8. MASALAH VALIDASI SINYAL

### 8.1 AI Menentukan Sinyal [KRITIS — DESIGN FLAW]
**Masalah:** Sistem menyerahkan keputusan BUY/SELL kepada Gemini AI.
- AI bisa menghasilkan sinyal yang tidak consistent untuk data yang sama
- Tidak deterministic — sinyal hari ini bisa berbeda dari hari lalu dengan data sama
- Tidak bisa diaudit/reproducible
- Temperature=0.2 tidak menjamin output yang sama

### 8.2 Confidence dari AI Tidak Tervalidasi [KRITIS]
- AI menghasilkan confidence 0-100 tanpa basis statistik yang jelas
- Angka ini arbitrary dan tidak backtested
- Dipakai untuk keputusan filter padahal tidak reliable

### 8.3 Risk Management dari AI [TINGGI]
- SL/TP dihitung oleh AI dengan instruksi "harus pakai ATR"
- AI bisa mengabaikan instruksi ini
- Entry price bisa berbeda dari harga pasar aktual

---

## 9. MASALAH SURVIVORSHIP BIAS

### 9.1 Backtest Hanya Pada Saham yang Ada Sekarang [KRITIS]
**Masalah:** `WATCHLIST` berisi saham yang masih aktif dan "survive" sampai sekarang.
- Saham yang delisting tidak ada di backtest
- Saham yang performa buruk sudah dihapus dari watchlist
- Win rate artificially inflated karena hanya test pada survivor

### 9.2 Tidak Ada Kontrol Universe Historis [KRITIS]
- Backtest 2021-2024 menggunakan universe saham 2025 (saat ini)
- Saham yang listing di 2023 tidak bisa di-backtest untuk 2021

---

## 10. MASALAH BACKTESTING

### 10.1 Look-Ahead Bias Potensial [KRITIS]
**Masalah:** Indikator dihitung pada seluruh dataset sebelum simulasi:
```python
df_train = _compute_indicators(df_train)  # ← hitung indikator dari seluruh data
for i in range(60, len(df)):              # ← baru scan
```
Indikator seperti ADX dan RSI yang menggunakan EWM secara teknis tidak look-ahead bias, namun Bollinger Band yang menggunakan `rolling().mean()` menggunakan data masa depan dalam proses warm-up jika tidak hati-hati.

### 10.2 Transaction Costs Diabaikan [TINGGI]
- Tidak ada biaya komisi (BEI: ~0.15-0.30%)
- Tidak ada biaya pajak (PPh Final 0.1%)
- Tidak ada slippage
- Win rate aktual akan lebih rendah dari backtest

### 10.3 Tidak Ada Drawdown Calculation [TINGGI]
- Backtest hanya melaporkan win rate
- Tidak ada max drawdown
- Tidak ada Sharpe Ratio atau Sortino Ratio
- Tidak bisa evaluasi risk-adjusted return

### 10.4 Forward Window Fixed 10 Candle [SEDANG]
- Menggunakan 10 candle forward untuk semua saham tanpa mempertimbangkan volatilitas
- Saham volatile butuh window berbeda dari saham stabil

---

## 11. MASALAH MAINTAINABILITY

### 11.1 Tidak Ada Documentation [TINGGI]
- Tidak ada docstring yang lengkap
- Tidak ada penjelasan formula scoring
- Tidak ada changelog

### 11.2 Magic Numbers [SEDANG]
```python
if 40 <= rsi <= 65:    # ← Mengapa 40-65?
    score += 20        # ← Mengapa 20 poin?
elif adx > 25:
    score += 15        # ← Mengapa 15?
```
Semua angka threshold hardcoded tanpa dokumentasi alasannya.

### 11.3 Tidak Ada Monitoring [KRITIS]
- Tidak ada health check
- Tidak ada alert jika sistem error
- Tidak ada metrics dashboard

---

## REKOMENDASI PRIORITAS

### 🔴 KRITIS (harus diperbaiki sebelum go-live)
1. Pindah ke GitHub Actions + Supabase (persistent, schedulable)
2. Sinyal harus deterministic/rule-based, bukan AI
3. Implementasi Universe Manager (seluruh BEI)
4. Secrets management via environment variables
5. Incremental data update
6. Fix bugs: pd import, race condition, regex

### 🟡 TINGGI (sprint 1)
7. Abstraction layer untuk data provider
8. Parallel data download
9. Structured logging ke database
10. Unit tests coverage >80%
11. Risk management engine yang proper

### 🟢 SEDANG (sprint 2-3)
12. Survivorship bias mitigation
13. Transaction costs dalam backtest
14. Dashboard Streamlit
15. Portfolio tracker lengkap

---

*Laporan ini menjadi basis pembangunan ulang sistem menjadi DAILY SIGNAL.*
