"""
DAILY SIGNAL — Market Data Provider (Abstraction Layer)
Mendukung multiple provider dengan fallback otomatis.

Fix v1.1:
- yfinance >= 0.2.x: gunakan multi_level_index=False untuk hindari MultiIndex issue
- Tambah group_by="ticker" fallback
- Better error handling untuk GitHub Actions environment
"""

import time
import threading
import concurrent.futures
import pandas as pd
import numpy as np
import yfinance as yf
from abc import ABC, abstractmethod
from datetime import date, datetime, timedelta
from typing import Optional
from tenacity import retry, stop_after_attempt, wait_exponential

from src.core.logger import get_logger
from src.core.database import get_last_price_date, bulk_insert_prices

log = get_logger("data_provider")


# ── Base Class ──────────────────────────────────────────────────────

class BaseMarketDataProvider(ABC):
    """Interface untuk semua market data provider."""

    @abstractmethod
    def fetch_ohlcv(
        self,
        ticker: str,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        period: Optional[str] = None,
    ) -> Optional[pd.DataFrame]:
        pass

    def validate_ohlcv(self, df: pd.DataFrame, min_rows: int = 5) -> bool:
        """
        Validasi data OHLCV.
        min_rows diturunkan ke 5 agar health check (period=5d) bisa lolos.

        AUDIT FIX (Error Handling): sebelumnya fungsi ini TIDAK memeriksa
        candle yang tidak masuk akal (high < low) maupun data tanpa
        transaksi sama sekali (volume 0 di semua baris) — keduanya lolos
        validasi dan bisa mencemari perhitungan indikator. Kini keduanya
        diperiksa dengan toleransi wajar (data live kadang punya sedikit
        baris anomali dari provider, jadi tidak di-reject hanya karena
        1-2 baris bermasalah — hanya jika PROPORSI-nya signifikan).
        """
        if df is None or df.empty:
            return False

        required_cols = {"open", "high", "low", "close", "volume"}
        if not required_cols.issubset(df.columns):
            return False

        if len(df) < min_rows:
            return False

        if (df["close"] <= 0).all():
            return False

        # Candle tidak masuk akal (high < low) — toleransi 5%
        inverted_ratio = (df["high"] < df["low"]).sum() / len(df)
        if inverted_ratio > 0.05:
            return False

        # Tidak ada transaksi sama sekali — toleransi 50%
        # (saham yang jarang ditransaksikan bisa punya beberapa hari
        # volume 0 secara wajar, tapi mayoritas 0 menandakan data rusak
        # atau saham suspend total)
        zero_vol_ratio = (df["volume"] == 0).sum() / len(df)
        if zero_vol_ratio > 0.5:
            return False

        return True


# ── Yahoo Finance Provider ───────────────────────────────────────────

class YahooProvider(BaseMarketDataProvider):
    """
    Yahoo Finance provider menggunakan yfinance.
    Compatible dengan yfinance >= 0.2.x
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._last_call = 0.0
        self._min_interval = 0.2  # 200ms antar call

    def _rate_limit(self):
        with self._lock:
            elapsed = time.time() - self._last_call
            if elapsed < self._min_interval:
                time.sleep(self._min_interval - elapsed)
            self._last_call = time.time()

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
    )
    def fetch_ohlcv(
        self,
        ticker: str,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        period: Optional[str] = None,
    ) -> Optional[pd.DataFrame]:
        """
        Fetch OHLCV dari Yahoo Finance.
        
        Penting: yfinance 0.2.x mengubah default output format.
        Kita gunakan multi_level_index=False agar kolom flat (tidak MultiIndex).
        """
        self._rate_limit()

        try:
            kwargs = {
                "tickers": ticker,
                "auto_adjust": True,
                "progress": False,
                "timeout": 20,
            }

            # Fix untuk yfinance >= 0.2.x: parameter baru untuk flatten kolom
            try:
                import inspect
                sig = inspect.signature(yf.download)
                if "multi_level_index" in sig.parameters:
                    kwargs["multi_level_index"] = False
            except Exception:
                pass  # Versi lama, tidak ada parameter ini

            if start_date and end_date:
                kwargs["start"] = start_date.isoformat()
                kwargs["end"] = (end_date + timedelta(days=1)).isoformat()
            elif period:
                kwargs["period"] = period
            else:
                kwargs["period"] = "60d"

            df = yf.download(**kwargs)

            if df is None or df.empty:
                log.warning(f"Data kosong dari Yahoo untuk {ticker}")
                return None

            # Flatten MultiIndex jika ada (fallback untuk versi lama)
            if isinstance(df.columns, pd.MultiIndex):
                # Ambil level pertama (Price) dan drop level ticker
                df.columns = df.columns.get_level_values(0)

            # Rename kolom ke lowercase
            rename_map = {}
            for col in df.columns:
                col_lower = col.lower().strip()
                if col_lower in ("open", "high", "low", "close", "volume", "adj close", "adj_close"):
                    if col_lower in ("adj close", "adj_close"):
                        rename_map[col] = "close"
                    else:
                        rename_map[col] = col_lower
            df = df.rename(columns=rename_map)

            # Pastikan kolom yang dibutuhkan ada
            needed = ["open", "high", "low", "close", "volume"]
            available = [c for c in needed if c in df.columns]
            if "close" not in available:
                log.warning(f"Kolom 'close' tidak ditemukan untuk {ticker}. Kolom ada: {df.columns.tolist()}")
                return None

            df = df[available].copy()
            df = df.dropna(subset=["close"])

            # Pastikan index adalah DatetimeIndex timezone-naive
            if not isinstance(df.index, pd.DatetimeIndex):
                df.index = pd.to_datetime(df.index)
            if df.index.tz is not None:
                df.index = df.index.tz_localize(None)

            # Konversi ke numeric
            for col in available:
                df[col] = pd.to_numeric(df[col], errors="coerce")
            df = df.dropna(subset=["close"])

            if df.empty:
                return None

            log.debug(f"Yahoo OK: {ticker} → {len(df)} baris")
            return df

        except Exception as e:
            log.warning(f"Yahoo fetch error {ticker}: {e}")
            raise  # Let tenacity retry

    def fetch_batch(
        self,
        tickers: list[str],
        period: str = "60d",
        max_workers: int = 5,
    ) -> dict[str, pd.DataFrame]:
        """Fetch data untuk banyak ticker secara paralel."""
        results = {}

        def fetch_one(ticker):
            df = self.fetch_ohlcv(ticker, period=period)
            return ticker, df

        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(fetch_one, t): t for t in tickers}

            for future in concurrent.futures.as_completed(futures, timeout=180):
                ticker = futures[future]
                try:
                    t, df = future.result()
                    if df is not None and not df.empty:
                        results[t] = df
                except Exception as e:
                    log.warning(f"Fetch batch error {ticker}: {e}")

        return results


# ── Provider Factory ─────────────────────────────────────────────────

class MarketDataProvider:
    """Facade dengan fallback otomatis antar provider."""

    def __init__(self):
        self.providers = [YahooProvider()]
        self._primary = self.providers[0]

    def fetch_ohlcv(
        self,
        ticker: str,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        period: Optional[str] = None,
    ) -> Optional[pd.DataFrame]:
        for i, provider in enumerate(self.providers):
            try:
                df = provider.fetch_ohlcv(ticker, start_date, end_date, period)
                if df is not None and not df.empty:
                    return df
            except Exception as e:
                if i < len(self.providers) - 1:
                    log.warning(f"Provider {type(provider).__name__} gagal untuk {ticker}, coba berikutnya")
                else:
                    log.error(f"Semua provider gagal untuk {ticker}: {e}")
        return None

    def fetch_batch(
        self,
        tickers: list[str],
        period: str = "60d",
    ) -> dict[str, pd.DataFrame]:
        return self._primary.fetch_batch(tickers, period=period)


# ── Incremental Data Updater ─────────────────────────────────────────

class IncrementalDataUpdater:
    """Hanya download data yang belum ada di database."""

    def __init__(self, provider: Optional[MarketDataProvider] = None):
        self.provider = provider or MarketDataProvider()

    def update_ticker(self, ticker: str) -> dict:
        """Update data satu ticker secara incremental."""
        last_date_str = get_last_price_date(ticker)

        if last_date_str:
            last_date = date.fromisoformat(last_date_str)
            start_date = last_date + timedelta(days=1)

            if start_date > date.today():
                return {
                    "ticker": ticker,
                    "rows_added": 0,
                    "last_date": last_date_str,
                    "status": "up_to_date",
                }

            df = self.provider.fetch_ohlcv(
                ticker,
                start_date=start_date,
                end_date=date.today(),
            )
        else:
            df = self.provider.fetch_ohlcv(ticker, period="252d")

        if df is None or df.empty:
            return {
                "ticker": ticker,
                "rows_added": 0,
                "last_date": last_date_str,
                "status": "no_data",
            }

        # Konversi ke format database
        records = []
        prev_close = None

        for idx, row in df.iterrows():
            trade_date = idx.date() if hasattr(idx, "date") else idx

            close = float(row["close"]) if pd.notna(row.get("close")) else None
            if close is None or close <= 0:
                continue

            change_pct = ((close / prev_close) - 1) * 100 if prev_close else None
            prev_close = close

            records.append({
                "ticker": ticker,
                "trade_date": trade_date.isoformat(),
                "open": round(float(row["open"]), 2) if pd.notna(row.get("open")) else None,
                "high": round(float(row["high"]), 2) if pd.notna(row.get("high")) else None,
                "low": round(float(row["low"]), 2) if pd.notna(row.get("low")) else None,
                "close": round(close, 2),
                "volume": int(row["volume"]) if pd.notna(row.get("volume")) else 0,
                "change_pct": round(change_pct, 4) if change_pct is not None else None,
            })

        # Daftarkan ticker ke tabel stocks dulu (cegah FK violation)
        from src.core.database import ensure_stocks_registered
        ensure_stocks_registered([ticker])

        rows_added = bulk_insert_prices(records)
        last_date = df.index[-1].date().isoformat() if not df.empty else last_date_str

        return {
            "ticker": ticker,
            "rows_added": rows_added,
            "last_date": last_date,
            "status": "updated",
        }

    def update_batch(
        self,
        tickers: list[str],
        max_workers: int = 2,   # Supabase nano free tier: maks 2 koneksi paralel
    ) -> dict:
        """Update data semua ticker secara paralel."""
        # max_workers=2 untuk Supabase free tier (nano) yang max ~20 koneksi aktif
        # Terlalu banyak paralel → ConnectionTerminated
        log.info(f"Incremental update untuk {len(tickers)} ticker (sequential mode untuk Supabase nano)...")

        total_added = 0
        updated = 0
        up_to_date = 0
        errors = 0

        def update_one(ticker):
            try:
                return self.update_ticker(ticker)
            except Exception as e:
                log.error(f"Update gagal: {ticker}: {e}")
                return {"ticker": ticker, "rows_added": 0, "status": "error"}

        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(update_one, t): t for t in tickers}

            for future in concurrent.futures.as_completed(futures, timeout=300):
                try:
                    result = future.result()
                    status = result.get("status", "error")
                    if status == "updated":
                        updated += 1
                        total_added += result.get("rows_added", 0)
                    elif status == "up_to_date":
                        up_to_date += 1
                    else:
                        errors += 1
                except Exception:
                    errors += 1

        summary = {
            "total_tickers": len(tickers),
            "updated": updated,
            "up_to_date": up_to_date,
            "errors": errors,
            "rows_added": total_added,
        }

        log.info(
            f"Update selesai: {updated} diupdate (+{total_added} rows), "
            f"{up_to_date} sudah terbaru, {errors} error"
        )
        return summary


def get_ohlcv_from_db(ticker: str, days: int = 252) -> Optional[pd.DataFrame]:
    """Ambil data OHLCV dari database dengan retry."""
    import time as _time
    from src.core.database import get_db
    from datetime import date

    start_date = (date.today() - timedelta(days=days)).isoformat()

    for attempt in range(3):
        try:
            db = get_db()
            result = (
                db.table("daily_prices")
                .select("trade_date, open, high, low, close, volume")
                .eq("ticker", ticker)
                .gte("trade_date", start_date)
                .order("trade_date")
                .execute()
            )
            if not result.data:
                return None

            df = pd.DataFrame(result.data)
            df["trade_date"] = pd.to_datetime(df["trade_date"])
            df = df.set_index("trade_date")
            for col in ["open", "high", "low", "close", "volume"]:
                df[col] = pd.to_numeric(df[col], errors="coerce")
            df = df.dropna(subset=["close"])
            return df if not df.empty else None

        except Exception as e:
            if attempt < 2:
                _time.sleep((attempt + 1) * 1.0)
                continue
            log.error(f"DB fetch OHLCV gagal untuk {ticker}: {str(e)[:100]}")
            return None
    return None
