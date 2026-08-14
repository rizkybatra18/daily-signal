"""
DAILY SIGNAL — Broker Summary Data Provider (Abstraction Layer)
Mengikuti pola src/providers/market_data.py (BaseMarketDataProvider).

STATUS: AKTIF -- provider IDX Edge PRO (stock.arjum.com) terpasang.

AUDIT (lihat AUDIT_REPORT_v2.md bagian Universe Manager & config.py
baris ~40): idx.co.id SECARA EKSPLISIT MELARANG scraping/crawling di
Syarat Penggunaan mereka (poin 6) dan situsnya bot-blocked. Broker
Summary resmi IDX memang gratis, TAPI karena larangan ToS yang sama
persis dengan yang sudah diaudit untuk data harga, scraping halaman
itu TIDAK dipakai -- konsisten dengan keputusan sistem ini untuk
daily_prices (pakai Yahoo Finance, bukan scraping IDX langsung).

Provider yang dipakai: IDX Edge PRO (stock.arjum.com) -- REST API
pihak ketiga dengan kuota harian GRATIS (reset 00:00 WIB). Sudah
diverifikasi: ToS & Privacy Policy publik ada (stock.arjum.com/terms,
/privacy), tidak melarang pemakaian terprogram selama tidak scraping
berlebihan/eksploitasi kuota -- konsisten dipakai lewat REST API resmi
dengan API key terdaftar (bukan scraping HTML), rate-limited di bawah.

Cara menambah provider lain (kalau suatu saat pindah/nambah vendor):

    class VendorXProvider(BaseBrokerDataProvider):
        def fetch_broker_summary(self, ticker, trade_date) -> list[dict]:
            ...

lalu daftarkan di BrokerDataProvider._init_provider() di bawah,
dan set BROKER_DATA_PROVIDER di .env ke nama vendor tsb.
"""

import time
import threading
from abc import ABC, abstractmethod
from datetime import date, timedelta as _timedelta
from typing import Optional

from tenacity import retry, stop_after_attempt, wait_exponential

from src.core.logger import get_logger

log = get_logger("broker_data_provider")


# ── Base Class ──────────────────────────────────────────────────────

class BaseBrokerDataProvider(ABC):
    """
    Interface untuk semua broker summary data provider.

    Kontrak return: list of dict, 1 dict per broker per ticker per hari,
    dengan key sesuai kolom tabel broker_summary (lihat migration
    004_broker_summary.sql). WAJIB ada: ticker, trade_date, broker_code.
    Field lain OPSIONAL tergantung apa yang disediakan vendor -- tidak
    semua vendor kasih breakdown yang sama (co. IDX Edge PRO cuma kasih
    net_volume, bukan buy_volume/sell_volume terpisah):
        buy_value, sell_value, net_value, net_volume,
        buy_frequency, sell_frequency, broker_name,
        buy_volume, sell_volume, avg_buy_price, avg_sell_price  (opsional)

    net_value/net_volume BOLEH dikirim langsung oleh provider (kalau
    vendor sudah menghitungnya, seperti IDX Edge PRO) -- data layer
    (bulk_insert_broker_summary di database.py) hanya menghitung ulang
    dari buy/sell KALAU provider tidak mengirimkannya langsung.
    """

    @abstractmethod
    def fetch_broker_summary(
        self,
        ticker: str,
        trade_date: date,
    ) -> Optional[list[dict]]:
        """
        Ambil broker summary untuk 1 ticker pada 1 tanggal.

        Returns:
            List of dict (1 per broker code yang bertransaksi hari itu),
            atau None kalau gagal/tidak ada data.
        """
        pass

    def validate_broker_summary(self, rows: list[dict]) -> bool:
        """
        Validasi minimal sebelum data masuk DB. Cuma cek identitas baris
        (ticker/trade_date/broker_code) -- TIDAK mewajibkan buy_volume/
        sell_volume lagi (lihat AUDIT di atas, tidak semua vendor kasih
        breakdown itu) selama ada minimal satu ukuran nilai transaksi.
        """
        if not rows:
            return False
        required = {"ticker", "trade_date", "broker_code"}
        value_keys = {"buy_value", "sell_value", "net_value", "net_volume"}
        return all(
            required.issubset(r.keys()) and any(r.get(k) is not None for k in value_keys)
            for r in rows
        )


# ── Provider belum dikonfigurasi (default aman) ──────────────────────

class NotConfiguredProvider(BaseBrokerDataProvider):
    """
    Default provider selama BROKER_DATA_PROVIDER belum diset di .env.
    Gagal EKSPLISIT & JELAS alih-alih diam-diam return None -- supaya
    kalau cmd_broker_scan kepanggil sebelum provider dipilih, errornya
    langsung jelas ke user (bukan silent no-op yang membingungkan).
    """

    def fetch_broker_summary(self, ticker: str, trade_date: date) -> Optional[list[dict]]:
        raise NotImplementedError(
            "Belum ada broker data provider yang dikonfigurasi. "
            "Set BROKER_DATA_PROVIDER=arjum_idx_edge dan ARJUM_IDX_EDGE_API_KEY "
            "di .env untuk pakai IDX Edge PRO (stock.arjum.com), atau "
            "implementasikan provider lain di src/providers/broker_data.py. "
            "Lihat docstring modul ini untuk detail."
        )


# ── IDX Edge PRO (stock.arjum.com) ────────────────────────────────────

class ArjumIdxEdgeProvider(BaseBrokerDataProvider):
    """
    Provider aktif: IDX Edge PRO (stock.arjum.com), endpoint
    GET /api/broker-summary/{code}.

    Kuota harian GRATIS (reset 00:00 WIB) -- ToS platform ini melarang
    "scraping berlebihan yang mengganggu kestabilan server" dan
    "eksploitasi celah kuota harian" (stock.arjum.com/terms). Provider
    ini dipakai lewat REST API resmi dengan API key terdaftar (bukan
    scraping HTML), dan SENGAJA rate-limited (_min_interval) + hanya
    dipanggil untuk top-N saham paling likuid (lihat
    get_top_liquid_tickers di database.py, dipakai cmd_broker_scan di
    runner.py) supaya hemat kuota, konsisten dengan semangat ToS.

    Bentuk response (diverifikasi langsung dari dokumentasi vendor,
    2026-08 -- BUKAN tebakan):
        {
          "flow": "all", "stock_code": "BBCA", "latest_date": "...",
          "broker_start": "...", "broker_end": "...",
          "brokers": [
            {"broker_code": "BK", "broker_name": "J.P. Morgan Sekuritas",
             "bval": 85400000000, "sval": 12000000000, "nval": 73400000000,
             "nvol": 71600, "bfrq": 1500, "sfrq": 2800},
            ...
          ]
        }

    CATATAN: vendor ini TIDAK memberi breakdown buy_volume/sell_volume
    terpisah -- cuma net_volume (nvol). buy_volume/sell_volume/
    avg_buy_price/avg_sell_price di kontrak dasar SENGAJA dibiarkan
    kosong untuk provider ini (lihat migration 004, kolom nullable).
    """

    BASE_URL = "https://stock.arjum.com/api/broker-summary"

    def __init__(self):
        import os
        self.api_key = os.environ.get("ARJUM_IDX_EDGE_API_KEY", "")
        if not self.api_key:
            raise EnvironmentError("ARJUM_IDX_EDGE_API_KEY belum diset di .env")
        self._lock = threading.Lock()
        self._last_call = 0.0
        # Vendor tidak publish angka rate-limit resmi di dokumentasi yang
        # kami baca -- 0.5s jeda antar call adalah pilihan konservatif
        # sendiri (hemat kuota + hormati ToS "jangan ganggu kestabilan
        # server"), BUKAN angka resmi dari vendor. Sesuaikan turun kalau
        # vendor mempublikasikan rate limit resmi yang lebih longgar.
        self._min_interval = 0.5

    def _throttle(self):
        with self._lock:
            elapsed = time.time() - self._last_call
            if elapsed < self._min_interval:
                time.sleep(self._min_interval - elapsed)
            self._last_call = time.time()

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    def _fetch_one_date(self, code: str, date_str: str) -> Optional[dict]:
        """Satu request mentah ke vendor untuk 1 tanggal spesifik. Return payload JSON atau None kalau kosong."""
        import requests

        self._throttle()
        url = f"{self.BASE_URL}/{code}"
        params = {
            "start_date": date_str,
            "end_date": date_str,
            "net": "false",
            "broker_limit": 30,
            "level_limit": 25,
            "all_data": "false",
            "flow": "all",
        }
        headers = {"X-API-Key": self.api_key, "Accept": "application/json"}

        resp = requests.get(url, params=params, headers=headers, timeout=15)

        if resp.status_code in (401, 403):
            # API key salah/expired -- jangan retry (percuma), gagal jelas
            raise EnvironmentError(
                f"IDX Edge PRO menolak API key (HTTP {resp.status_code}). "
                "Cek ARJUM_IDX_EDGE_API_KEY di .env."
            )
        resp.raise_for_status()
        payload = resp.json()
        return payload if payload.get("brokers") else None

    def fetch_broker_summary(self, ticker: str, trade_date: date) -> Optional[list[dict]]:
        """
        AUDIT (2026-08, bug ditemukan dari laporan user: broker_summary
        selalu 0 baris walau scan "sukses"): request awal SELALU minta
        start_date=end_date=trade_date (biasanya "hari ini", karena
        cmd_broker_scan jalan tiap sore lewat cron 17:18 WIB). Vendor
        ternyata BELUM TENTU sudah publish data broker untuk tanggal
        yang sama hari itu (lag publikasi tidak didokumentasikan resmi
        di API-nya) -- hasilnya `brokers: []` KOSONG, bukan error, jadi
        lolos begitu saja tanpa exception dan tercatat "0 baris" tanpa
        penjelasan.

        Diperbaiki: kalau tanggal yang diminta kosong, MUNDUR sampai 5
        hari kalender ke belakang (cukup buat lewati weekend + 1-2 hari
        lag), pakai tanggal PERTAMA yang beneran ada datanya. Baris
        disimpan dengan trade_date dari vendor (broker_end/latest_date
        di response), BUKAN trade_date yang awalnya diminta -- supaya
        akurat kalau ternyata mundur beberapa hari.
        """
        code = ticker.replace(".JK", "")
        max_lookback_days = 5

        for offset in range(max_lookback_days):
            try_date = trade_date - _timedelta(days=offset)
            try:
                payload = self._fetch_one_date(code, try_date.isoformat())
            except EnvironmentError:
                raise  # API key salah -- jangan buang waktu mundur-mundur, langsung gagal
            except Exception as e:
                log.warning(f"Fetch {ticker} tanggal {try_date} gagal: {e}")
                continue

            if payload:
                actual_date = payload.get("broker_end") or payload.get("latest_date") or try_date.isoformat()
                if offset > 0:
                    log.info(
                        f"{ticker}: data {trade_date.isoformat()} belum terbit, "
                        f"mundur ke {actual_date} (offset {offset} hari)."
                    )
                rows = []
                for b in payload.get("brokers", []):
                    broker_code = b.get("broker_code")
                    if not broker_code:
                        continue
                    rows.append({
                        "ticker": ticker,
                        "trade_date": actual_date,
                        "broker_code": broker_code,
                        "broker_name": b.get("broker_name"),
                        "buy_value": b.get("bval", 0) or 0,
                        "sell_value": b.get("sval", 0) or 0,
                        "net_value": b.get("nval"),
                        "net_volume": b.get("nvol"),
                        "buy_frequency": b.get("bfrq"),
                        "sell_frequency": b.get("sfrq"),
                        "source_provider": "arjum_idx_edge",
                    })
                return rows if rows else None

        log.warning(f"{ticker}: tidak ada data broker summary dalam {max_lookback_days} hari terakhir.")
        return None


# ── Provider Factory ─────────────────────────────────────────────────

class BrokerDataProvider:
    """Facade -- pilih provider konkret berdasarkan env var, mirror MarketDataProvider."""

    def __init__(self):
        import os
        provider_name = os.environ.get("BROKER_DATA_PROVIDER", "").strip().lower()
        self._provider = self._init_provider(provider_name)
        self._provider_name = provider_name or "not_configured"

    @property
    def provider_name(self) -> str:
        return self._provider_name

    def _init_provider(self, name: str) -> BaseBrokerDataProvider:
        if name == "arjum_idx_edge":
            return ArjumIdxEdgeProvider()
        # Daftarkan provider vendor lain di sini kalau suatu saat pindah/nambah, mis.:
        # if name == "invezgo":
        #     return InvezgoProvider()
        return NotConfiguredProvider()

    def fetch_broker_summary(self, ticker: str, trade_date: date) -> Optional[list[dict]]:
        try:
            return self._provider.fetch_broker_summary(ticker, trade_date)
        except NotImplementedError:
            raise
        except Exception as e:
            log.warning(f"Broker summary fetch gagal {ticker} {trade_date}: {e}")
            return None

    def fetch_batch(
        self,
        tickers: list[str],
        trade_date: date,
        max_workers: int = 3,
    ) -> dict[str, list[dict]]:
        """
        Fetch broker summary untuk banyak ticker secara paralel, 1 tanggal.
        max_workers default DIKECILKAN (5->3) dibanding market_data.py --
        provider broker summary rate-limited internal (_throttle), jadi
        paralelisme tinggi di sini tidak menambah throughput, cuma bikin
        thread nunggu di lock yang sama.
        """
        import concurrent.futures
        results: dict[str, list[dict]] = {}

        def fetch_one(ticker):
            return ticker, self.fetch_broker_summary(ticker, trade_date)

        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(fetch_one, t): t for t in tickers}
            for future in concurrent.futures.as_completed(futures, timeout=300):
                ticker = futures[future]
                try:
                    t, rows = future.result()
                    if rows:
                        results[t] = rows
                except NotImplementedError:
                    raise
                except Exception as e:
                    log.warning(f"Fetch batch broker summary error {ticker}: {e}")

        return results
