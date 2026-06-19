"""
DAILY SIGNAL — Market Data Provider (Abstraction Layer)
Mendukung multiple provider dengan fallback otomatis.

Cara menambah provider baru:
    class NewProvider(BaseMarketDataProvider):
        def fetch_ohlcv(self, ticker, start_date, end_date) -> pd.DataFrame:
            ...

Providers:
    - YahooProvider (primary, gratis, 800+ saham BEI)
    - IDXProvider   (future: data resmi BEI)
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
        """
        Ambil data OHLCV.
        
        Args:
            ticker: Kode saham (misal "BBCA.JK")
            start_date: Tanggal mulai (opsional, prioritas lebih tinggi dari period)
            end_date: Tanggal akhir
            period: Yahoo-style period string ("60d", "1y", dll)
            
        Returns:
            DataFrame dengan kolom: open, high, low, close, volume
            Index: DatetimeIndex dengan timezone-naive dates
            None jika gagal atau data tidak cukup
        """
        pass

    def validate_ohlcv(self, df: pd.DataFrame, min_rows: int = 26) -> bool:
        """
        Validasi data OHLCV.
        
        Cek:
        - DataFrame tidak kosong
        - Punya kolom yang diperlukan
        - Minimal rows untuk indikator
        - Tidak ada negative price
        - High >= Low (tidak inverted candle)
        - Volume > 0 (tidak semua 0)
        """
        if df is None or df.empty:
            return False
        
        required_cols = {"open", "high", "low", "close", "volume"}
        if not required_cols.issubset(df.columns):
            return False
        
        if len(df) < min_rows:
            return False
        
        # Price sanity check
        if (df["close"] < 0).any():
            return False
        
        # High harus >= Low
        inverted = (df["high"] < df["low"]).sum()
        if inverted > len(df) * 0.05:  # Toleransi 5% anomali
            return False
        
        # Setidaknya beberapa candle punya volume
        zero_vol_ratio = (df["volume"] == 0).sum() / len(df)
        if zero_vol_ratio > 0.5:
            return False
        
        return True


# ── Yahoo Finance Provider ───────────────────────────────────────────

class YahooProvider(BaseMarketDataProvider):
    """
    Yahoo Finance provider menggunakan yfinance.
    Primary provider, gratis, support 800+ saham BEI.
    """

    def __init__(self):
        self._lock = threading.Lock()  # Thread-safe rate limiting
        self._last_call = 0.0
        self._min_interval = 0.1  # Min 100ms antar call

    def _rate_limit(self):
        """Simple rate limiting."""
        with self._lock:
            elapsed = time.time() - self._last_call
            if elapsed < self._min_interval:
                time.sleep(self._min_interval - elapsed)
            self._last_call = time.time()

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=5),
    )
    def fetch_ohlcv(
        self,
        ticker: str,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        period: Optional[str] = None,
    ) -> Optional[pd.DataFrame]:
        """Fetch OHLCV dari Yahoo Finance."""
        self._rate_limit()
        
        try:
            kwargs = {
                "tickers": ticker,
                "auto_adjust": True,
                "progress": False,
                "timeout": 15,
            }
            
            if start_date and end_date:
                kwargs["start"] = start_date.isoformat()
                kwargs["end"] = (end_date + timedelta(days=1)).isoformat()  # end exclusive
            elif period:
                kwargs["period"] = period
            else:
                kwargs["period"] = "60d"
            
            df = yf.download(**kwargs)
            
            if df is None or df.empty:
                return None
            
            # Flatten MultiIndex
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            
            # Rename ke lowercase
            df = df.rename(columns={
                "Open": "open", "High": "high",
                "Low": "low", "Close": "close", "Volume": "volume",
            })
            
            # Pastikan hanya kolom yang dibutuhkan
            available = [c for c in ["open", "high", "low", "close", "volume"] if c in df.columns]
            df = df[available].copy()
            
            # Drop NaN rows
            df = df.dropna(subset=["close"])
            
            # Pastikan index adalah DatetimeIndex
            if not isinstance(df.index, pd.DatetimeIndex):
                df.index = pd.to_datetime(df.index)
            
            # Remove timezone info untuk konsistensi
            if df.index.tz is not None:
                df.index = df.index.tz_localize(None)
            
            if not self.validate_ohlcv(df):
                return None
            
            return df
            
        except Exception as e:
            log.warning(f"Yahoo fetch gagal untuk {ticker}: {e}")
            raise  # Let tenacity retry


    def fetch_batch(
        self,
        tickers: list[str],
        period: str = "60d",
        max_workers: int = 5,
    ) -> dict[str, pd.DataFrame]:
        """
        Fetch data untuk banyak ticker secara paralel.
        Lebih efisien dari sequential loop.
        
        Return: {ticker: DataFrame}
        """
        results = {}
        
        def fetch_one(ticker):
            df = self.fetch_ohlcv(ticker, period=period)
            return ticker, df
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(fetch_one, t): t for t in tickers}
            
            for future in concurrent.futures.as_completed(futures, timeout=120):
                ticker = futures[future]
                try:
                    t, df = future.result()
                    if df is not None:
                        results[t] = df
                except Exception as e:
                    log.warning(f"Fetch gagal: {ticker}: {e}")
        
        return results


# ── Provider Factory ─────────────────────────────────────────────────

class MarketDataProvider:
    """
    Facade class dengan fallback otomatis antar provider.
    Semua kode lain harus pakai class ini, bukan provider langsung.
    """

    def __init__(self):
        self.providers = [
            YahooProvider(),
            # IDXProvider(),  # Future: uncomment jika sudah implement
        ]
        self._primary = self.providers[0]

    def fetch_ohlcv(
        self,
        ticker: str,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        period: Optional[str] = None,
    ) -> Optional[pd.DataFrame]:
        """Fetch dengan fallback ke provider berikutnya jika gagal."""
        for i, provider in enumerate(self.providers):
            try:
                df = provider.fetch_ohlcv(ticker, start_date, end_date, period)
                if df is not None:
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
        """Batch fetch via primary provider."""
        return self._primary.fetch_batch(tickers, period=period)


# ── Incremental Data Updater ─────────────────────────────────────────

class IncrementalDataUpdater:
    """
    Hanya download data yang belum ada di database.
    Kunci untuk efisiensi di GitHub Actions Free Tier.
    """

    def __init__(self, provider: Optional[MarketDataProvider] = None):
        self.provider = provider or MarketDataProvider()

    def update_ticker(self, ticker: str) -> dict:
        """
        Update data satu ticker secara incremental.
        Return stats: {"ticker", "rows_added", "last_date", "status"}
        """
        # Cek tanggal terakhir di database
        last_date_str = get_last_price_date(ticker)
        
        if last_date_str:
            last_date = date.fromisoformat(last_date_str)
            # Download mulai dari sehari setelah last date
            start_date = last_date + timedelta(days=1)
            
            # Jika sudah up to date, skip
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
            # Ticker baru — download 1 tahun + warmup
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
            trade_date = idx.date() if hasattr(idx, 'date') else idx
            
            close = float(row["close"]) if pd.notna(row.get("close")) else None
            if close is None:
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
        max_workers: int = 5,
    ) -> dict:
        """
        Update data semua ticker secara paralel.
        Return summary stats.
        """
        log.info(f"Incremental update untuk {len(tickers)} ticker...")
        
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
                        
                except Exception as e:
                    errors += 1
                    log.error(f"Batch update error: {e}")
        
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
    """
    Ambil data OHLCV dari database (bukan dari Yahoo langsung).
    Lebih cepat karena tidak perlu download.
    """
    try:
        from src.core.database import get_db
        db = get_db()
        
        start_date = (date.today() - timedelta(days=days)).isoformat()
        
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
        df = df.astype({
            "open": float, "high": float, "low": float,
            "close": float, "volume": float,
        })
        
        return df if not df.empty else None
        
    except Exception as e:
        log.error(f"DB fetch OHLCV gagal untuk {ticker}: {e}")
        return None
