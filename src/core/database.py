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



def ensure_stocks_registered(tickers: list[str]) -> int:
    """
    Pastikan semua ticker terdaftar di tabel stocks sebelum insert prices.
    Ini mencegah FK violation (23503) karena daily_prices reference stocks.
    Return jumlah ticker yang baru didaftarkan.
    """
    import time as _time
    if not tickers:
        return 0
    try:
        db = get_db()
        # Query dalam batch kecil untuk hindari timeout Supabase nano
        existing = set()
        batch_size = 50
        for i in range(0, len(tickers), batch_size):
            batch = tickers[i:i+batch_size]
            try:
                result = db.table("stocks").select("ticker").in_("ticker", batch).execute()
                existing.update(r["ticker"] for r in (result.data or []))
                _time.sleep(0.1)  # Jeda kecil antar query
            except Exception:
                pass  # Skip batch ini, akan dicoba saat insert

        missing = [t for t in tickers if t not in existing]
        if not missing:
            return 0

        # Insert batch kecil dengan jeda
        records = [
            {
                "ticker":       t,
                "ticker_clean": t.replace(".JK", ""),
                "name":         t.replace(".JK", ""),
                "is_active":    True,
                "is_delisted":  False,
            }
            for t in missing
        ]
        inserted = 0
        for i in range(0, len(records), 50):
            try:
                db.table("stocks").upsert(
                    records[i:i+50], on_conflict="ticker"
                ).execute()
                inserted += len(records[i:i+50])
                _time.sleep(0.2)  # Jeda antar batch untuk Supabase nano
            except Exception as e2:
                pass  # Log tapi lanjut

        from src.core.logger import get_logger
        log = get_logger("database")
        log.info(f"✓ {inserted} ticker baru didaftarkan ke tabel stocks")
        return inserted

    except Exception as e:
        from src.core.logger import get_logger
        log = get_logger("database")
        log.error(f"ensure_stocks_registered gagal: {e}")
        return 0

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
def get_price_row_count(ticker: str) -> int:
    """
    Hitung jumlah baris histori harga yang sudah tersimpan untuk 1 ticker.
    Dipakai untuk deteksi "data nyangkut" (backfill lama terhenti di
    tengah jalan) — lihat IncrementalDataUpdater.update_ticker().
    """
    try:
        db = get_db()
        result = (
            db.table("daily_prices")
            .select("trade_date", count="exact")
            .eq("ticker", ticker)
            .execute()
        )
        return result.count or 0
    except Exception:
        return 0    


def bulk_insert_prices(records: list[dict]) -> int:
    """
    Bulk insert harga harian dengan batch kecil + retry.
    Batch 100 (bukan 500) untuk hindari ConnectionTerminated di Supabase nano.
    """
    import time as _time
    if not records:
        return 0

    db = get_db()
    total_inserted = 0
    batch_size = 100  # Kecil agar tidak overload Supabase nano

    for i in range(0, len(records), batch_size):
        batch = records[i:i + batch_size]
        # Retry 3x per batch
        for attempt in range(3):
            try:
                db.table("daily_prices").upsert(
                    batch,
                    on_conflict="ticker,trade_date"
                ).execute()
                total_inserted += len(batch)
                _time.sleep(0.1)  # Jeda kecil antar batch
                break
            except Exception as e:
                err_str = str(e)
                if attempt < 2:
                    wait = (attempt + 1) * 1.0
                    _time.sleep(wait)
                    continue
                # Attempt terakhir gagal - log tapi jangan crash
                from src.core.logger import get_logger
                log = get_logger("database")
                log.error(f"Gagal bulk insert prices: {err_str[:200]}")
                break

    return total_inserted


def _upsert_with_schema_fallback(
    table: str,
    data: dict,
    on_conflict: Optional[str] = None,
    known_extra_columns: Optional[list[str]] = None,
) -> tuple[bool, Optional[dict]]:
    """
    Upsert/insert dengan fallback otomatis jika ada kolom yang belum
    ada di schema Supabase (PGRST204 "column not found in schema cache").

    AUDIT NOTE (Error Handling): Insiden produksi sebelumnya menunjukkan
    bahwa satu field tak dikenal di payload membuat SELURUH insert gagal
    (mis. seluruh 87 sinyal gagal tersimpan karena 1 kolom `analysis_date`
    yang tidak ada di schema). Helper ini mencegah kejadian serupa: jika
    error menyebut kolom yang memang termasuk fitur BARU (belum tentu
    migration sudah dijalankan user), kolom itu dibuang dan insert
    dicoba ulang SEKALI dengan payload yang sudah dibersihkan — sinyal
    inti tetap tersimpan meski fitur baru (mis. confidence, factor
    contribution) untuk sementara tidak tersimpan sampai migration
    dijalankan.

    Return: (success, result_data_or_None)
    """
    import re as _re

    db = get_db()
    payload = dict(data)

    for _ in range(2):  # max 1 retry setelah strip kolom bermasalah
        try:
            if on_conflict:
                res = db.table(table).upsert(payload, on_conflict=on_conflict).execute()
            else:
                res = db.table(table).insert(payload).execute()
            return True, (res.data[0] if res.data else None)

        except Exception as e:
            err_str = str(e)
            if "PGRST204" in err_str or "could not find" in err_str.lower():
                # Ekstrak nama kolom dari pesan error Supabase, contoh:
                # "Could not find the 'analysis_date' column of 'signals'"
                match = _re.search(r"'([a-zA-Z_][a-zA-Z0-9_]*)' column", err_str)
                bad_col = match.group(1) if match else None

                if bad_col and bad_col in payload:
                    from src.core.logger import get_logger
                    log = get_logger("database")
                    log.warning(
                        f"Kolom '{bad_col}' belum ada di tabel '{table}' "
                        f"(migration terbaru belum dijalankan?). Kolom ini "
                        f"dilewati untuk kali ini — data lain tetap disimpan."
                    )
                    del payload[bad_col]
                    continue  # Coba lagi tanpa kolom bermasalah

            from src.core.logger import get_logger
            log = get_logger("database")
            log.error(f"Gagal simpan ke '{table}': {err_str[:250]}")
            return False, None

    return False, None


def save_signal(signal_data: dict) -> Optional[str]:
    """Simpan sinyal ke database dengan retry + schema-drift fallback."""
    import time as _time
    for attempt in range(3):
        try:
            ok, row = _upsert_with_schema_fallback("signals", signal_data)
            if ok:
                return row["id"] if row else None
            return None
        except Exception as e:
            err_str = str(e)
            if attempt < 2 and "ConnectionTerminated" in err_str:
                _time.sleep((attempt + 1) * 0.5)
                continue
            from src.core.logger import get_logger
            log = get_logger("database")
            log.error(f"Gagal save signal: {err_str[:200]}")
            return None
    return None


def save_market_regime(regime_data: dict) -> bool:
    """Simpan atau update market regime hari ini, dengan schema-drift fallback."""
    ok, _ = _upsert_with_schema_fallback(
        "market_regimes", regime_data, on_conflict="regime_date"
    )
    return ok


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
