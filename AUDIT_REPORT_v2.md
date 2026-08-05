# LAPORAN AUDIT MENYELURUH — DAILY SIGNAL v2.1
**Audit oleh: Principal Quant Developer / Senior Software Architect**
**Baseline yang diaudit:** source code TERKINI dari `rizkybatra18/daily-signal` (bukan versi lama dari sesi sebelumnya — lihat AUDIT_REPORT.md untuk audit generasi pertama terhadap prototype `stock_bot`)
**Tanggal:** Juli 2026

---

## 0. RINGKASAN EKSEKUTIF

Audit ini mencakup **14 area** yang diminta plus **1 audit tambahan prioritas tinggi** (Universe Manager) yang diminta menyusul. Metodologi: seluruh source code TERKINI dibaca dan dipahami dulu sebagai baseline — **tidak ada kode yang ditimpa balik ke versi lama** — sebelum satu baris pun diubah. Baseline test suite dijalankan lebih dulu (46/49 lulus, 3 gagal pre-existing) untuk membedakan bug lama vs regresi baru.

**Hasil akhir: 49/49 test lulus (0 regresi, 3 bug pre-existing ikut diperbaiki).**

### Temuan Kritis Utama

| # | Temuan | Dampak | Status |
|---|--------|--------|--------|
| 1 | Universe Manager memakai **curated list ~140 ticker**, bukan seluruh BEI | Signal universe sempit, banyak peluang terlewat | ✅ Diperluas ke **551 ticker** |
| 2 | `breadth_data` di regime engine **tidak pernah terisi** (parameter mati) | Market Breadth yang diminta sebelumnya tidak pernah benar-benar aktif | ✅ Pipeline diurutkan ulang + breadth nyata dihitung |
| 3 | **STRONG_BUY matematis mustahil saat BEAR**, nyaris mustahil saat SIDEWAYS | Sistem tidak adaptif — inti masalah "sinyal terlalu sedikit" | ✅ Adaptive threshold per regime |
| 4 | Sector bonus diterapkan ke `final_score` (sudah dikali regime_weight), bukan raw score | Pengaruh bonus tidak konsisten antar regime | ✅ Diterapkan ke raw score |
| 5 | Sector rotation hanya pakai 3-4 saham big-cap per sektor sebagai proxy | Ranking sektor tidak representatif | ✅ Diperluas ke seluruh universe (551 ticker) |
| 6 | Backtest entry di close hari sinyal (bukan open H+1) | Backtest terlalu optimis, tidak realistis | ✅ Entry di open H+1 |
| 7 | Backtest resolusi TP/SL selalu asumsi TP duluan jika sama-sama kena | Bias optimis, win rate ter-inflate | ✅ SL diperiksa lebih dulu (konservatif) |
| 8 | Backtest scoring beda skala (0-60) dari live scoring (0-100) | Backtest menguji strategi BERBEDA dari yang live | ✅ Diselaraskan persis |
| 9 | `validate_ohlcv` tidak cek candle terbalik / volume nol | Data kotor bisa lolos ke indikator | ✅ Diperbaiki |
| 10 | 1 kolom baru di payload bisa gagalkan SELURUH insert (PGRST204) | Insiden produksi sebelumnya (87 sinyal gagal tersimpan) | ✅ Helper fallback skema-aman |

---

## 1. AUDIT UNIVERSE MANAGER (Prioritas Tinggi — diminta menyusul)

### 1.1 Dugaan Terkonfirmasi BENAR

Source code `universe_manager.py` versi sebelumnya memang memakai **curated/manual seed list (~140 ticker)** sebagai basis utama. Fungsi `_fetch_via_yahoo_screener()` **tidak benar-benar melakukan screening/discovery** — namanya menyesatkan; isinya hanya memvalidasi ulang daftar curated yang sudah ada, bukan menemukan ticker baru dari BEI secara independen.

### 1.2 Riset Sumber Data Alternatif (Gratis, Legal, Stabil)

Sebelum implementasi, dilakukan riset langsung (web search + fetch, bukan asumsi):

**a. idx.co.id (situs resmi BEI) — DITOLAK sebagai sumber otomatis**
- **Alasan legal**: Syarat Penggunaan PT Bursa Efek Indonesia poin 6 secara eksplisit melarang *"metode web scrapping/crawling"* atas situs mereka — dikonfirmasi dari riset terhadap proyek open-source yang membahas scraping IDX (`antonizer/IDX-Scrapper`, `ExRonin/Stock-Scrapper-IDX`), yang sama-sama mengutip larangan ini.
- **Alasan teknis**: Dikonfirmasi **langsung secara empiris** — percobaan fetch ke `idx.co.id/id/data-pasar/data-saham/daftar-saham` diblokir oleh bot detection mereka. IP range GitHub Actions (datacenter/cloud) umumnya termasuk yang paling sering diblok sistem anti-bot semacam ini, membuat pendekatan ini rapuh bahkan seandainya legal.

**b. Dataset komunitas GitHub (mis. `wildangunawan/Dataset-Saham-IDX`) — DITOLAK sebagai dependency otomatis**
- Repo semacam ini **diperbarui manual "kalau ada waktu kosong"** menurut pengakuan pemiliknya sendiri — tidak ada jaminan freshness, bisa basi berbulan-bulan tanpa peringatan.
- Berlisensi CC BY-NC 4.0 (non-komersial) dan tetap berbasis scraping IDX di baliknya — mewarisi risiko legal yang sama.

**c. Yahoo Finance (yfinance) — DIPAKAI sebagai satu-satunya sumber otomatis**
- Yahoo Finance API publik memang ditujukan untuk konsumsi terprogram (berbeda dari IDX yang eksplisit melarang), dan sudah dipakai sistem ini untuk OHLCV — tidak menambah risiko baru.
- Coverage Yahoo untuk ticker `.JK` (BEI) sudah sangat luas mencakup mayoritas saham aktif — masalahnya bukan cakupan Yahoo, tapi **daftar kandidat yang dikirim ke Yahoo untuk divalidasi terlalu pendek**.

### 1.3 Solusi yang Diimplementasikan

Karena scraping IDX langsung tidak layak (legal+teknis), solusi yang dipakai adalah **memperbesar signifikan kandidat awal + memperkuat lapisan validasi**, bukan scraping baru:

1. **Curated seed diperluas dari ~140 → 551 ticker unik**, disusun manual berdasarkan 11 sektor resmi IDX-IC. Ini bukan angka bulat yang dipoles — `len(_flatten_curated())` menghasilkan **551** persis, diverifikasi programatis, bukan diklaim.
2. **Setiap kandidat tetap divalidasi via Yahoo Finance** sebelum dipakai (batch 75 ticker, retry-friendly) — ticker yang tidak lagi ada data trading otomatis tersaring (delisting/suspend/kode salah).
3. **Safety guard baru** di `refresh_universe()`: jika hasil validasi anjlok drastis (<50% dari yang sudah aktif di DB) dibanding sebelumnya, penandaan delisting **otomatis di-skip** — mencegah gangguan Yahoo sesaat disalahartikan sebagai delisting massal (bug laten yang ditemukan saat audit, lihat detail di bawah).
4. **`EXTRA_UNIVERSE_SOURCE_URL`** (opsional, kosong secara default): jika Anda punya sumber list ticker tambahan yang Anda percaya (mis. Google Sheet CSV pribadi), isi env var ini — sistem otomatis menggabungkannya sebelum validasi, tanpa perlu edit kode.
5. **Sector proxy untuk sector rotation ikut diperluas** dari ~37 ticker (hardcoded) menjadi seluruh 551 ticker — lihat bagian 3.4.

### 1.4 Bug Laten yang Ditemukan Saat Audit: False Mass-Delisting

```python
# SEBELUM (bug laten, belum pernah kejadian tapi berpotensi):
possibly_delisted = db_set - fresh_set
for ticker in possibly_delisted:
    if _verify_delisting(ticker):
        # tandai delisted...
```

Jika `get_all_bei_tickers()` mengembalikan hasil sangat sedikit karena gangguan Yahoo Finance sesaat (rate limit, outage), maka `fresh_set` akan jauh lebih kecil dari `db_set`, dan **HAMPIR SEMUA saham yang sudah aktif di database berisiko tertandai delisting** dalam satu kali `refresh_universe()` run. Ini adalah kelas bug yang sama dengan insiden `ConnectionTerminated` yang pernah dialami sistem ini sebelumnya — gangguan jaringan sesaat yang salah diinterpretasikan sebagai kondisi permanen. Sudah diperbaiki dengan safety guard (lihat 1.3 poin 3).

### 1.5 Hasil Verifikasi (Ticker per Sektor, dihitung programatis)

```
Financials                 : 94 ticker unik
Consumer Non-Cyclicals     : 87 ticker unik
Consumer Cyclicals         : 109 ticker unik
Energy                     : 39 ticker unik
Basic Materials            : 53 ticker unik
Infrastructure             : 33 ticker unik
Properties & Real Estate   : 60 ticker unik
Industrials                : 26 ticker unik
Technology                 : 22 ticker unik
Healthcare                 : 25 ticker unik
Transportation & Logistics : 25 ticker unik
─────────────────────────────────────────────
TOTAL UNIK                 : 551 ticker
```

### 1.6 Keterbatasan yang Jujur Diakui

- Ini **bukan** discovery real-time terhadap IPO baru di hari yang sama saat listing — ticker baru butuh ditambahkan ke curated seed (manual) atau lewat `EXTRA_UNIVERSE_SOURCE_URL` (jika user mengelola sumber sendiri). IPO baru umumnya juga belum layak swing-trade di minggu pertama (likuiditas tipis, lock-up, volatilitas ekstrem) sehingga trade-off ini wajar.
- 551 ticker adalah representasi luas namun bukan 100% dari seluruh ~900+ perusahaan tercatat di BEI (termasuk yang sangat tidak likuid, yang toh akan tersaring oleh filter `min_volume` sistem ini sendiri).

---

## 2. AUDIT MARKET REGIME ENGINE

### 2.1 Apakah Filter Terlalu Ketat?

**Analisis klasifikasi regime (BULL/SIDEWAYS/BEAR) itu sendiri TIDAK diubah** — threshold-nya (EMA20/50, RSI, ADX, breadth) sudah masuk akal untuk praktik swing trading Indonesia dan tidak ditemukan bukti kuat bahwa klasifikasi regime-nya sendiri "terlalu sulit berubah". Regime BULL butuh `bull_ratio >= 0.65` dari 6 sinyal (EMA20, EMA50, RSI, 5D momentum, ADX, breadth) — proporsional, bukan ekstrem.

**Yang justru bermasalah bukan klasifikasi regime, tapi APA YANG DILAKUKAN SETELAH regime diketahui** — lihat bagian 4 (Adaptive Threshold), temuan paling signifikan dari seluruh audit ini.

### 2.2 Bug Ditemukan: `breadth_data` Parameter Mati

```python
# scanner.py — urutan LAMA:
# [3/7] IHSG di-download
# [4/7] detect_market_regime(ihsg_df)   ← breadth_data TIDAK PERNAH dikirim!
# [5/7] Load data OHLCV seluruh saham    ← breadth baru bisa dihitung DI SINI
```

Data yang dibutuhkan untuk menghitung breadth (harga seluruh saham) baru dimuat SETELAH regime dideteksi. Akibatnya `detect_market_regime(ihsg_df, breadth_data=None)` **selalu** dipanggil dengan `breadth_data=None` — parameter itu secara fungsional mati sejak awal, meski kodenya terlihat lengkap.

**Fix**: Urutan pipeline diubah — load OHLCV seluruh saham (Step 3) sekarang terjadi SEBELUM deteksi regime (Step 4), sehingga breadth bisa dihitung nyata dari data yang sudah tersedia.

### 2.3 Market Breadth — Diimplementasikan Nyata

Fungsi baru `compute_market_breadth(stock_data)` di `regime_engine.py` menghitung:
- **Advance/Decline**: jumlah saham naik vs turun hari itu (dari data yang SAMA yang dipakai analisis TA — tidak ada API/biaya tambahan)
- **% saham di atas EMA20 / EMA50 / EMA200**: partisipasi pasar yang lebih dalam dari sekadar breadth harian — menangkap kondisi "IHSG naik tapi hanya didukung segelintir saham besar" vs "kenaikan didukung luas"

Metrik ini kini masuk ke skema bull/bear signal scoring regime engine dan disimpan ke kolom baru `pct_above_ema20/50/200` di tabel `market_regimes` (migration 002).

---

## 3. AUDIT SCORING ENGINE

### 3.1 Proporsi Bobot

Bobot Trend(30)/Momentum(25)/Volume(20)/Strength(15)/Volatility(10) = 100 **tidak diubah** — proporsinya sudah wajar untuk strategi swing trading. `settings.weight_trend` dkk di `config.py` **secara teknis tidak wired** ke logika scoring (nilai di sana hanya dokumentasi yang kebetulan cocok dengan cap hardcoded di kode) — dicatat sebagai temuan minor, TIDAK diubah karena mengubahnya berarti me-refactor "konsep utama scoring" yang eksplisit diminta untuk tidak disentuh tanpa alasan kuat.

### 3.2 Bug Ditemukan & Diperbaiki: Urutan Sector Bonus vs Regime Weight

```python
# SEBELUM (scanner.py, dijalankan SETELAH analyze_stock selesai):
analysis.score.final_score = max(0, min(100, analysis.score.final_score + bonus))
#                                              ^^^^^^^^^^^^^^^^^^^^^^^^^
#                                              ini SUDAH raw × regime_weight!
analysis.score.signal_type = _determine_signal_type(
    analysis.score.final_score, 1.0, analysis   # ← regime_weight di-HARDCODE 1.0!
)
```

Dua masalah sekaligus:
1. Sector bonus (+5/-5) ditambahkan ke `final_score` yang **sudah dikalikan regime_weight**. Efeknya tidak konsisten antar regime — pengaruh proporsional bonus jadi jauh lebih besar saat BEAR (base kecil) dibanding BULL (base besar).
2. Regime asli **diabaikan** saat klasifikasi ulang (`weight=1.0` hardcoded) — workaround yang menutupi symptom, bukan fix.

**Fix**: `sector_bonus` kini dihitung LEBIH DULU (sebelum `analyze_stock` dipanggil) dan dikirim langsung sebagai parameter. Di dalam `analyze_stock`, bonus diterapkan ke **raw_score** (sebelum dikali `regime_weight`), satu kali proses, tidak ada override/workaround.

### 3.3 Verifikasi Empiris (dijalankan nyata, bukan simulasi di atas kertas)

```
Skenario: raw_score=69 (setup cukup kuat), sector_bonus=+5

SEBELUM fix:  BEAR (weight=0.4) → final=27.6 → AVOID (selalu, apapun skornya)
SESUDAH fix:  BEAR (weight=0.4) → raw=69     → WATCHLIST (69 >= threshold BEAR 68)
```

### 3.4 Sector Rotation — Sample Diperluas

`SECTOR_PROXY` yang tadinya hardcoded ~4 saham big-cap per sektor (37 ticker total) kini diturunkan otomatis dari `TICKER_SECTOR` (551 ticker, hasil ekspansi Universe Manager di bagian 1). Ranking sektor kini dihitung dari puluhan saham aktual per sektor, bukan hanya beberapa saham raksasa yang mendominasi persepsi performa seluruh sektor.

---

## 4. ADAPTIVE THRESHOLD — TEMUAN & FIX PALING SIGNIFIKAN

### 4.1 Bug Matematis Fundamental

```python
# _determine_signal_type SEBELUM:
adjusted_score = score * regime_weight   # score = raw (0-100), weight ∈ {1.0, 0.75, 0.4}
if adjusted_score >= 75: STRONG_BUY
elif adjusted_score >= 60: BUY
elif adjusted_score >= 45: WATCHLIST
```

Dengan `regime_weight` BEAR = 0.4: **tidak ada nilai `score` (maks 100) yang bisa menghasilkan `adjusted_score >= 45`** (0.4×100=40 < 45). Artinya **BEAR membuat 100% saham otomatis AVOID**, tanpa kecuali, walau skornya sempurna literal. Untuk SIDEWAYS (weight=0.75): STRONG_BUY butuh `score>=100` — skor sempurna literal, praktis mustahil.

Ini secara langsung bertentangan dengan tujuan eksplisit permintaan audit: *"memastikan sistem benar-benar mampu menghasilkan sinyal berkualitas ketika market mulai bullish"* — karena begitu market baru saja keluar dari BEAR menuju SIDEWAYS, sistem TETAP nyaris tidak pernah mengeluarkan STRONG_BUY walau ada saham dengan setup luar biasa.

### 4.2 Solusi: Threshold Adaptif Berbasis Raw Score

Alih-alih mengalikan score dengan weight lalu membandingkan ke threshold TETAP, threshold kini **beradaptasi** per regime dan dibandingkan terhadap **raw_score** (sebelum dikali weight):

| Regime | STRONG_BUY | BUY | WATCHLIST | Mustahil? |
|--------|-----------|-----|-----------|-----------|
| BULL | raw ≥ 75 | raw ≥ 60 | raw ≥ 45 | Tidak (baseline, tidak berubah) |
| SIDEWAYS | raw ≥ 82 | raw ≥ 68 | raw ≥ 55 | Tidak — lebih ketat tapi tercapai |
| BEAR | raw ≥ 90 | raw ≥ 80 | raw ≥ 68 | Tidak — sangat ketat tapi tetap mungkin |

`final_score` (raw×weight) **tetap dihitung dan ditampilkan apa adanya** di dashboard/telegram — tidak ada perubahan makna kolom itu untuk konsumen di hilir. Hanya **keputusan klasifikasi sinyal** yang kini pakai raw_score + tabel adaptif ini (`settings.adaptive_thresholds`, bisa disesuaikan lewat konfigurasi tanpa mengubah kode).

### 4.3 Verifikasi Empiris — Skenario Setup Sangat Kuat (raw=84)

```
BULL      raw=84.0  final=84.0  → STRONG_BUY  (Confidence: High)
SIDEWAYS  raw=84.0  final=63.0  → STRONG_BUY  (Confidence: High)   [SEBELUMNYA: AVOID]
BEAR      raw=84.0  final=33.6  → BUY         (Confidence: High)   [SEBELUMNYA: AVOID, MUSTAHIL]
```

Ini membuktikan langsung: saham dengan skor teknikal luar biasa (reversal awal di tengah BEAR, misalnya) sekarang **bisa terdeteksi**, bukan otomatis tersapu bersih oleh regime multiplier. Ini juga secara langsung menjawab concern: begitu market mulai bullish (regime beranjak dari BEAR→SIDEWAYS→BULL), sistem akan mulai mengeluarkan lebih banyak sinyal berkualitas secara PROGRESIF, bukan tiba-tiba "buntu total lalu meledak" seperti sebelumnya.

---

## 5. CONFIDENCE ENGINE (Rule-Based, Bukan ML)

Fungsi baru `compute_confidence(raw_score, analysis)` di `ta_engine.py`. Confidence **bukan** sekadar pembulatan dari raw_score — dikombinasikan dengan **berapa banyak dimensi yang benar-benar kuat secara independen** (>=70% dari skor maksimal masing-masing: trend/momentum/volume/strength), sehingga skor 90 yang didukung SEMUA dimensi lebih dipercaya dibanding skor 90 yang didapat dari satu dimensi ekstrem menutupi dimensi lain yang lemah.

```
raw_score >= 88 DAN >=3 dimensi kuat  → "Very High"
raw_score >= 75 DAN >=2 dimensi kuat  → "High"
raw_score >= 60                        → "Medium"
lainnya                                → "Low"
```

Disimpan ke kolom baru `signals.confidence` (migration 002). **Tampilan Dashboard/Telegram TIDAK diubah** sesuai instruksi — data sudah siap dikonsumsi di iterasi UI berikutnya.

---

## 6. FACTOR CONTRIBUTION

Fungsi baru `build_factor_contribution(analysis, sector_bonus)` menyusun breakdown kontribusi per faktor + daftar "highlight" (alasan singkat kenapa skor tinggi), contoh output nyata (dari uji end-to-end):

```json
{
  "trend": 30.0, "momentum": 14.0, "volume": 7.0,
  "strength": 5.0, "volatility": 8.0, "sector_bonus": 5.0,
  "total_raw": 69.0,
  "highlights": ["EMA Alignment kuat", "Sektor sedang memimpin"]
}
```

Disimpan sebagai JSONB ke kolom baru `signals.factor_contribution` (migration 002) — siap dipakai Dashboard ("Kenapa saham ini dapat skor tinggi?") maupun Telegram ("✓ EMA Alignment ✓ Volume Spike ...") di iterasi UI berikutnya, sesuai instruksi untuk tidak mengubah tampilan sekarang.

---

## 7. FILTER AUDIT & FUNNEL LOGGING

### 7.1 Catatan Jujur Soal Konsep Funnel

Contoh funnel yang diminta (`Regime Pass → Sector Pass → Technical Pass → Score Pass`) mengasumsikan regime dan sektor sebagai **gate per-saham** yang menggugurkan kandidat satu-persatu. Setelah audit arsitektur, **ini tidak sepenuhnya sesuai dengan desain sistem**: regime adalah **satu nilai untuk seluruh pasar** hari itu (bukan per-saham), dan sector adalah **modifier skor** (+5/-5/0), bukan gate yang men-drop saham. Membuat funnel palsu yang seolah-olah keduanya menggugurkan kandidat akan menyesatkan, bukan informatif.

### 7.2 Funnel yang Diimplementasikan (Jujur Sesuai Arsitektur Nyata)

```
============================================
  DAILY SCAN — FUNNEL
============================================
  Universe             : 551
  Data Tersedia         : 542
  Berhasil Dianalisis   : 540
  Lolos Filter Teknikal : 498
  Lolos Score (>=WL)    : 47
  BUY                   : 12
  STRONG BUY            : 3
--------------------------------------------
  Market Regime aktif   : BULL
============================================
```

Tahapan ini **benar-benar mengurangi kandidat secara nyata** (data availability → technical filter → score threshold), berbeda dari funnel contoh yang sebagian tahapannya tidak eksis sebagai gate literal di arsitektur ini. Log ini otomatis muncul di setiap `daily_scan` run (GitHub Actions), plus tersimpan terstruktur (`details=funnel` di logger, bisa di-query dari `system_logs`).

---

## 8. BACKTEST ENGINE AUDIT

### 8.1 Look-Ahead Bias / Data Leakage: TIDAK DITEMUKAN

Semua indikator memakai `.ewm()`/`.rolling()`/`.shift()` yang murni backward-looking. Anti-pump check pakai `df.iloc[i-3]` (mundur). **Tidak ada leakage literal ditemukan** — klaim "no look-ahead bias" di versi sebelumnya akurat untuk perhitungan indikatornya.

### 8.2 Masalah Realisme Eksekusi: DITEMUKAN 2 (Diperbaiki)

**a. Entry di hari yang sama dengan sinyal**
Versi sebelumnya "membeli" tepat di harga close hari sinyal terbentuk. Di dunia nyata, sinyal baru dikirim ~17:30 WIB SETELAH market tutup — eksekusi tercepat yang mungkin adalah open hari berikutnya. **Fix**: entry kini di open H+1, ATR/SL/TP tetap dihitung dari informasi yang sudah diketahui saat sinyal terbentuk (tidak ada leakage baru).

**b. Resolusi TP/SL optimistis dalam candle yang sama**
Jika SL dan TP1 sama-sama tersentuh dalam satu candle (gap besar), versi lama SELALU mengasumsikan TP1 terjadi lebih dulu — bias optimis klasik yang meng-inflate win rate. **Fix**: SL diperiksa lebih dulu (konvensi konservatif standar backtesting).

### 8.3 Scoring Backtest vs Live: Tidak Selaras (Diperbaiki)

Backtest sebelumnya pakai skala 0-60 dengan bobot berbeda (Trend 20, RSI 12, MACD 8, ADX 8, Volume 12 — tidak ada Relative Strength maupun Volatility sama sekali). Ini berarti **backtest memvalidasi strategi yang BERBEDA** dari composite scoring live (0-100, 5 dimensi lengkap). `_score_row()` ditulis ulang untuk meniru persis pita nilai `_score_trend`/`_score_momentum`/`_score_volume`/`_score_strength`/`_score_volatility` di `ta_engine.py`, termasuk EMA200 alignment, RSI trending bonus, MACD cross, volume trend, Relative Strength (opsional via parameter `ihsg_close` baru di `run_backtest()`), Bollinger position & squeeze. `min_score` default (60.0) kini punya makna yang SAMA persis dengan threshold BUY di live.

### 8.4 Bug Kecil Diperbaiki

- `TradeResult.ticker`: sebelumnya `df.get("ticker", "")` dipanggil pada **DataFrame** (bukan row) — selalu mengembalikan string kosong. Diperbaiki: ticker dikirim eksplisit sebagai parameter.
- Fallback ATR: jika kolom 'atr' tidak tersedia (robustness untuk pemanggilan langsung), kini dihitung fallback kasar dari range high-low hari itu, bukan crash `KeyError`.

---

## 9. ERROR HANDLING

### 9.1 Schema-Drift-Safe Upsert (Perbaikan Paling Berdampak)

Insiden produksi sebelumnya (87 sinyal gagal tersimpan hanya karena 1 kolom `analysis_date` tidak dikenal skema) menunjukkan pola bug berbahaya: **satu kolom asing di payload menggagalkan SELURUH insert**. Karena audit ini menambah beberapa kolom baru yang butuh migration 002, risiko ini nyata jika migration belum dijalankan user.

Helper baru `_upsert_with_schema_fallback()` di `database.py`: jika Supabase menolak dengan `PGRST204` (kolom tidak ditemukan), kolom bermasalah otomatis dibuang dari payload dan insert dicoba ulang **sekali** — data inti tetap tersimpan meski fitur baru belum aktif (sampai migration dijalankan). Diterapkan ke `save_signal` dan `save_market_regime`.

### 9.2 Validasi Data OHLCV Diperkuat

`validate_ohlcv` sebelumnya tidak memeriksa candle terbalik (`high < low`) maupun volume nol total. Ditambahkan dengan toleransi wajar (5% untuk inverted candle, 50% untuk zero-volume) agar tidak overly-strict terhadap anomali kecil yang wajar dari provider data.

### 9.3 False Mass-Delisting Guard

Lihat bagian 1.4 — safety guard baru mencegah gangguan Yahoo Finance sesaat disalahartikan sebagai delisting massal.

---

## 10. PERFORMANCE

Tidak ditemukan bottleneck baru yang butuh optimasi mendesak di luar yang sudah diperbaiki di iterasi sebelumnya (batch query Supabase, incremental data update). Perluasan universe (140→551 ticker) meningkatkan volume kerja secara linear — sudah diantisipasi lewat batch validation Yahoo (75 ticker/batch) dan batch load OHLCV (60 ticker/batch, IN clause) yang sudah ada, jadi skalanya tetap terkendali dalam batas waktu GitHub Actions.

---

## 11. FILE YANG DIUBAH (Lengkap)

| File | Jenis Perubahan | Alasan |
|------|-----------------|--------|
| `src/core/config.py` | Additive — tambah `adaptive_thresholds`, confidence bands, breadth params, universe config | Dasar konfigurasi untuk fix #3, #5, #6 |
| `src/providers/universe_manager.py` | **Rewrite besar** — curated list 140→551, safety guard, extra source URL | Bagian 1 |
| `src/signals/regime_engine.py` | Additive — `compute_market_breadth()`, field breadth baru | Bagian 2 |
| `src/signals/ta_engine.py` | Perubahan signifikan — adaptive `_determine_signal_type`, `compute_confidence()`, `build_factor_contribution()`, fix urutan sector_bonus | Bagian 3, 4, 5, 6 |
| `src/signals/scanner.py` | **Rewrite** — pipeline diurutkan ulang, funnel logging, hapus double-classification bug | Bagian 2.2, 3.2, 7 |
| `src/signals/sector_engine.py` | Additive — `SECTOR_PROXY` dinamis dari universe penuh | Bagian 3.4 |
| `src/backtest/engine.py` | **Rewrite** — entry realism, scoring alignment, bug fixes | Bagian 8 |
| `src/providers/market_data.py` | Additive — `validate_ohlcv` diperkuat | Bagian 9.2 |
| `src/core/database.py` | Additive — `_upsert_with_schema_fallback()` | Bagian 9.1 |
| `src/runner.py` | Additive — wire IHSG ke backtest | Bagian 8.3 |
| `migrations/002_audit_improvements.sql` | **Baru** — kolom additive, tidak merusak data lama | Semua fitur baru |

### TIDAK Diubah (Sesuai Instruksi)

- `src/telegram/bot.py` — format Telegram tidak disentuh
- `dashboard.py` — tampilan dashboard tidak disentuh
- `src/portfolio/tracker.py`, `src/core/logger.py` — sudah baik, tidak ada alasan kuat mengubah
- `.github/workflows/*.yml` — deployment online tidak disentuh
- `migrations/001_initial_schema.sql` — tidak diubah, hanya ditambah lewat 002

---

## 12. HASIL TEST — SEBELUM vs SESUDAH

```
SEBELUM (baseline, source code TERKINI sebelum audit ini):
  46 passed, 3 failed
  - test_inverted_candles_fails       (bug validate_ohlcv)
  - test_zero_volume_fails            (bug validate_ohlcv)
  - test_backtest_includes_commission (bug _simulate_trade butuh kolom 'atr')

SESUDAH (setelah seluruh perubahan audit ini):
  49 passed, 0 failed  ← 0 REGRESI, 3 bug lama ikut diperbaiki
```

Diverifikasi juga: `python -m py_compile` bersih di seluruh `src/` + `dashboard.py`, tidak ada `SyntaxError` di manapun.

**Catatan jujur soal coverage gate**: `pyproject.toml` menetapkan `--cov-fail-under=70`, namun test suite yang ada (sejak awal, bukan perubahan hari ini) secara sengaja hanya menguji fungsi murni (`ta_engine`, `regime_engine`, `backtest`) dan tidak meng-cover modul I/O-berat (`scanner.py`, `database.py`, `telegram/bot.py`, `universe_manager.py`) karena butuh mocking Supabase/Yahoo/Telegram yang belum dibangun. Gate 70% ini sudah tidak tercapai SEBELUM audit ini pun. Tidak ada test yang dihapus/dilemahkan untuk "mengakali" angka ini — direkomendasikan sebagai future work (lihat bagian 15).

---

## 13. KOMPATIBILITAS & DEPLOYMENT

- ✅ **GitHub Actions**: tidak ada perubahan ke workflow — command `python -m src.runner daily_scan` dkk tetap sama persis.
- ✅ **Streamlit**: `dashboard.py` tidak disentuh, semua query `select("*")` yang ada otomatis kompatibel dengan kolom baru (nullable, additive).
- ✅ **Telegram**: `bot.py` tidak disentuh, format pesan sama persis.
- ✅ **Supabase**: perlu jalankan `migrations/002_audit_improvements.sql` untuk mengaktifkan kolom baru (confidence, factor_contribution, dst) — **tapi sistem tetap berjalan normal walau migration ini belum dijalankan**, berkat schema-drift-safe fallback (bagian 9.1). Sinyal inti tetap tersimpan; hanya kolom baru yang tertunda sampai migration dijalankan.
- ✅ **Tidak ada fitur dihapus** — semua fungsi lama tetap ada dengan signature backward-compatible (parameter baru selalu punya default value).

### Langkah Deploy

1. Jalankan `migrations/002_audit_improvements.sql` di Supabase SQL Editor (aman, additive, idempotent).
2. Push seluruh isi ZIP ke repository (replace semua file yang tercantum di bagian 11).
3. Trigger `health_check` manual sekali untuk verifikasi.
4. Scan berikutnya otomatis memakai 551-ticker universe + semua perbaikan di atas.

---

## 14. ESTIMASI DAMPAK TERHADAP KUALITAS SINYAL

| Perubahan | Dampak Terhadap Kualitas Sinyal |
|-----------|----------------------------------|
| Universe 140→551 ticker | **Cakupan peluang naik ~4x** — lebih banyak saham dipindai, termasuk mid/small-cap yang sebelumnya tidak pernah dilihat sistem sama sekali |
| Adaptive threshold | **Sinyal tidak lagi "buntu total" saat BEAR/SIDEWAYS** — saham reversal awal kini terdeteksi, khususnya relevan saat market mulai berbalik bullish (tujuan eksplisit) |
| Sector bonus fix + proxy diperluas | Ranking sektor lebih representatif → bonus/penalty lebih akurat mencerminkan momentum sektor sungguhan |
| Market breadth nyata | Regime detection kini mempertimbangkan partisipasi pasar yang lebih dalam, bukan hanya pergerakan IHSG semata |
| Backtest realistis | Angka win rate/profit factor yang ditampilkan akan **sedikit lebih rendah tapi lebih jujur** — memberi ekspektasi yang lebih dekat ke kondisi trading sungguhan |
| Confidence + Factor Contribution | Tidak mengubah sinyal itu sendiri, tapi menyiapkan data agar user bisa MEMBEDAKAN sinyal skor-90-solid dari skor-90-fluke di iterasi UI berikutnya |

---

## 15. REKOMENDASI UNTUK ITERASI BERIKUTNYA (Tidak Dikerjakan Sekarang — Di Luar Scope)

1. **Integration test dengan mock Supabase/Yahoo/Telegram** — agar `scanner.py`/`database.py`/`universe_manager.py` bisa masuk hitungan coverage gate secara jujur, bukan cuma unit test fungsi murni.
2. **UI Dashboard/Telegram untuk Confidence & Factor Contribution** — data sudah siap di database (bagian 5, 6), tinggal dikonsumsi saat user memutuskan untuk mengubah tampilan.
3. **EXTRA_UNIVERSE_SOURCE_URL** — pertimbangkan menyiapkan Google Sheet pribadi berisi ticker tambahan di luar 551 curated jika ditemukan gap spesifik di masa depan.

---

*Untuk audit generasi pertama (rebuild dari prototype `stock_bot` lama), lihat `AUDIT_REPORT.md`. Untuk changelog ringkas seluruh versi, lihat `CHANGELOG.md`.*
