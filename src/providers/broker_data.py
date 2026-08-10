"""
DAILY SIGNAL — Broker Summary Data Provider (Abstraction Layer)
Mengikuti pola src/providers/market_data.py (BaseMarketDataProvider).

STATUS: BELUM ADA PROVIDER KONKRET TERPASANG.

AUDIT (lihat AUDIT_REPORT_v2.md bagian Universe Manager & config.py
baris ~40): idx.co.id SECARA EKSPLISIT MELARANG scraping/crawling di
Syarat Penggunaan mereka (poin 6) dan situsnya bot-blocked. Broker
Summary resmi memang dipublikasikan gratis di idx.co.id/en/market-data/
trading-summary/broker-summary, TAPI karena larangan ToS yang sama
persis dengan yang sudah diaudit untuk data harga, scraping halaman
itu TIDAK direkomendasikan -- konsisten dengan keputusan yang sudah
diambil sistem ini untuk daily_prices (pindah ke Yahoo Finance).

Jalan yang konsisten dengan prinsip yang sama: pakai vendor API yang
sudah reselling/repackage data ini secara legal (co. Invezgo, Sectors.app,
atau vendor lain yang py punya lisensi redistribusi), ATAU data resmi
IDX Data Services (berbayar, langsung dari bursa, paling "bersih" secara
legal). Cara menambah provider baru:

    class VendorXProvider(BaseBrokerDataProvider):
        def fetch_broker_summary(self, ticker, trade_date) -> list[dict]:
            ...

lalu daftarkan di BrokerDataProvider._init_providers() di bawah,
dan set BROKER_DATA_PROVIDER di .env ke nama vendor tsb.
"""

import time
import threading
from abc import ABC, abstractmethod
from datetime import date
from typing import Optional

from tenacity import retry, stop_after_attempt, wait_exponential

from src.core.logger import get_logger

log = get_logger("broker_data_provider")


# ── Base Class ──────────────────────────────────────────────────────

class BaseBrokerDataProvider(ABC):
    """
    Interface untuk semua broker summary data provider.

    Kontrak return: list of dict, 1 dict per broker per ticker per hari,
    dengan key persis sesuai kolom tabel broker_summary (lihat migration
    004_broker_summary.sql):
        ticker, trade_date, broker_code,
        buy_volume, buy_value, avg_buy_price,
        sell_volume, sell_value, avg_sell_price

    net_volume/net_value TIDAK perlu dihitung provider -- itu tanggung
    jawab data layer (lihat save_broker_summary_batch di database.py)
    supaya konsisten apapun provider-nya.
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
        """Validasi minimal sebelum data masuk DB."""
        if not rows:
            return False
        required = {"ticker", "trade_date", "broker_code", "buy_volume", "sell_volume"}
        return all(required.issubset(r.keys()) for r in rows)


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
            "Set BROKER_DATA_PROVIDER di .env (mis. 'invezgo', 'sectors_app') "
            "dan implementasikan kelas provider-nya di "
            "src/providers/broker_data.py sebelum menjalankan broker scan. "
            "Lihat docstring modul ini untuk detail."
        )


# ── Contoh kerangka provider vendor (BELUM AKTIF, ISI SENDIRI) ───────
#
# class InvezgoProvider(BaseBrokerDataProvider):
#     """
#     Contoh kerangka -- SESUAIKAN dengan dokumentasi API vendor
#     sebenarnya sebelum dipakai (endpoint, auth header, bentuk
#     response JSON di bawah ini masih PLACEHOLDER, belum diverifikasi).
#     """
#
#     def __init__(self):
#         import os
#         self.api_key = os.environ.get("INVEZGO_API_KEY", "")
#         if not self.api_key:
#             raise EnvironmentError("INVEZGO_API_KEY belum diset di .env")
#         self._lock = threading.Lock()
#         self._last_call = 0.0
#         self._min_interval = 0.3   # sesuaikan rate limit vendor
#
#     @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
#     def fetch_broker_summary(self, ticker: str, trade_date: date) -> Optional[list[dict]]:
#         import requests
#         resp = requests.get(
#             "https://api.invezgo.com/v1/broker-summary",   # VERIFIKASI URL SEBENARNYA
#             params={"symbol": ticker.replace(".JK", ""), "date": trade_date.isoformat()},
#             headers={"Authorization": f"Bearer {self.api_key}"},
#             timeout=15,
#         )
#         resp.raise_for_status()
#         data = resp.json()
#         rows = []
#         for row in data.get("brokers", []):   # VERIFIKASI BENTUK RESPONSE SEBENARNYA
#             rows.append({
#                 "ticker": ticker,
#                 "trade_date": trade_date.isoformat(),
#                 "broker_code": row["broker_code"],
#                 "buy_volume": row.get("buy_volume", 0),
#                 "buy_value": row.get("buy_value", 0),
#                 "avg_buy_price": row.get("avg_buy_price"),
#                 "sell_volume": row.get("sell_volume", 0),
#                 "sell_value": row.get("sell_value", 0),
#                 "avg_sell_price": row.get("avg_sell_price"),
#                 "source_provider": "invezgo",
#             })
#         return rows if rows else None


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
        # Daftarkan provider vendor konkret di sini begitu diimplementasikan, mis.:
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
        max_workers: int = 5,
    ) -> dict[str, list[dict]]:
        """Fetch broker summary untuk banyak ticker secara paralel, 1 tanggal."""
        import concurrent.futures
        results: dict[str, list[dict]] = {}

        def fetch_one(ticker):
            return ticker, self.fetch_broker_summary(ticker, trade_date)

        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(fetch_one, t): t for t in tickers}
            for future in concurrent.futures.as_completed(futures, timeout=180):
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
