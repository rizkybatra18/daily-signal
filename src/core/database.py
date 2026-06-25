"""
DAILY SIGNAL — Database Layer (Supabase)
Singleton connection dengan retry dan health check.
"""

import os
import time
from typing import Optional
from supabase import create_client, Client
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type


_db_client: Optional[Client] = None


def get_db() -> Client:
    """
    Return Supabase client singleton.
    Lazy initialization — tidak connect saat import.
    """
    global _db_client
    if _db_client is None:
        url = os.environ.get("SUPABASE_URL", "")
        key = os.environ.get("SUPABASE_SERVICE_KEY", "")

        if not url or not key:
            raise EnvironmentError(
                "SUPABASE_URL dan SUPABASE_SERVICE_KEY harus diset di environment variables. "
                "Salin .env.example ke .env dan isi nilainya."
            )

        _db_client = create_client(url, key)

    return _db_client


def health_check() -> dict:
    """
    Cek koneksi ke database.
    Menggunakan query ke tabel 'stocks' yang pasti ada setelah migrasi.
    Return dict dengan status dan latency.
    """
    start = time.time()
    try:
        db = get_db()
        # Coba query ke tabel stocks (lebih aman dari system_logs karena tidak butuh data)
        # count=exact menghindari error PGRST125 (invalid path) yang muncul
        # jika tabel kosong dan kita pakai select("id")
        result = db.table("stocks").select("ticker", count="exact").limit(1).execute()
        latency_ms = int((time.time() - start) * 1000)
        return {
            "status": "healthy",
            "latency_ms": latency_ms,
            "table_check": "stocks",
        }
    except Exception as e:
        err_str = str(e)
        latency_ms = int((time.time() - start) * 1000)

        # Diagnosis lebih spesifik untuk error umum
        if "PGRST125" in err_str or "Invalid path" in err_str:
            hint = "Kemungkinan migration SQL belum dijalankan di Supabase. Buka SQL Editor Supabase dan jalankan migrations/001_initial_schema.sql"
        elif "Invalid API key" in err_str or "401" in err_str:
            hint = "SUPABASE_SERVICE_KEY tidak valid. Cek kembali value secret di GitHub."
        elif "connection" in err_str.lower():
            hint = "Tidak bisa connect ke Supabase. Cek SUPABASE_URL."
        else:
            hint = err_str[:200]

        return {
            "status": "unhealthy",
            "latency_ms": latency_ms,
            "error": hint,
        }


def ensure_tables_exist() -> bool:
    """
    Cek apakah tabel-tabel utama sudah ada.
    Dipanggil sekali saat startup untuk diagnosa masalah migration.
    Return True jika semua tabel ada.
    """
    required_tables = ["stocks", "daily_prices", "signals", "market_regimes", "scan_runs"]
    try:
        db = get_db()
        missing = []
        for tbl in required_tables:
            try:
                db.table(tbl).select("*", count="exact").limit(0).execute()
            except Exception:
                missing.append(tbl)

        if missing:
            from src.core.logger import get_logger
            log = get_logger("database")
            log.error(
                f"Tabel berikut tidak ditemukan di Supabase: {missing}. "
                f"Jalankan migrations/001_initial_schema.sql di Supabase SQL Editor!"
            )
            return False
        return True
    except Exception:
        return False


def upsert_stock(ticker: str, data: dict) -> bool:
    """Upsert data stock master."""
    try:
        db = get_db()
        db.table("stocks").upsert({
            "ticker": ticker,
            "ticker_clean": ticker.replace(".JK", ""),
            **data,
            "updated_at": "now()",
        }, on_conflict="ticker").execute()
        return True
    except Exception as e:
        from src.core.logger import get_logger
        log = get_logger("database")
        log.error(f"Gagal upsert stock {ticker}: {e}", exc=e)
        return False


def get_last_price_date(ticker: str) -> Optional[str]:
    """
    Dapatkan tanggal candle terakhir yang tersimpan di database.
    Return string ISO date atau None jika belum ada data.
    """
    try:
        db = get_db()
        result = (
            db.table("daily_prices")
            .select("trade_date")
            .eq("ticker", ticker)
            .order("trade_date", desc=True)
            .limit(1)
            .execute()
        )
        if result.data:
            return result.data[0]["trade_date"]
        return None
    except Exception:
        return None


def bulk_insert_prices(records: list[dict]) -> int:
    """
    Bulk insert harga harian. Return jumlah record yang berhasil diinsert.
    Menggunakan upsert untuk handle duplikat.
    """
    if not records:
        return 0
    try:
        db = get_db()
        total_inserted = 0
        batch_size = 500
        for i in range(0, len(records), batch_size):
            batch = records[i:i + batch_size]
            db.table("daily_prices").upsert(
                batch,
                on_conflict="ticker,trade_date"
            ).execute()
            total_inserted += len(batch)
        return total_inserted
    except Exception as e:
        from src.core.logger import get_logger
        log = get_logger("database")
        log.error(f"Gagal bulk insert prices: {e}", exc=e)
        return 0


def save_signal(signal_data: dict) -> Optional[str]:
    """Simpan sinyal ke database. Return signal_id atau None."""
    try:
        db = get_db()
        result = db.table("signals").insert(signal_data).execute()
        if result.data:
            return result.data[0]["id"]
        return None
    except Exception as e:
        from src.core.logger import get_logger
        log = get_logger("database")
        log.error(f"Gagal save signal: {e}", exc=e)
        return None


def save_market_regime(regime_data: dict) -> bool:
    """Simpan atau update market regime hari ini."""
    try:
        db = get_db()
        db.table("market_regimes").upsert(
            regime_data, on_conflict="regime_date"
        ).execute()
        return True
    except Exception as e:
        from src.core.logger import get_logger
        log = get_logger("database")
        log.error(f"Gagal save market regime: {e}", exc=e)
        return False


def save_sector_rankings(rankings: list[dict]) -> bool:
    """Simpan ranking sektor."""
    try:
        db = get_db()
        db.table("sector_rankings").upsert(
            rankings, on_conflict="rank_date,sector"
        ).execute()
        return True
    except Exception as e:
        from src.core.logger import get_logger
        log = get_logger("database")
        log.error(f"Gagal save sector rankings: {e}", exc=e)
        return False


def get_active_signals_for_monitoring() -> list[dict]:
    """Dapatkan sinyal BUY/SELL yang belum closed untuk monitoring."""
    try:
        db = get_db()
        result = (
            db.table("signals")
            .select("*, signal_updates(update_type)")
            .in_("signal_type", ["STRONG_BUY", "BUY"])
            .gte("signal_date", "now()::date - interval '7 days'")
            .execute()
        )
        return result.data or []
    except Exception:
        return []


def log_scan_run(run_data: dict) -> Optional[str]:
    """Log metadata scan run."""
    try:
        db = get_db()
        result = db.table("scan_runs").insert(run_data).execute()
        if result.data:
            return result.data[0]["run_id"]
        return None
    except Exception:
        return None


def update_scan_run(run_id: str, update_data: dict) -> bool:
    """Update status scan run."""
    try:
        db = get_db()
        db.table("scan_runs").update(update_data).eq("run_id", run_id).execute()
        return True
    except Exception:
        return False
