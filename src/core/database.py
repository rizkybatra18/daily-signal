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
        existing = set()
        batch_size = 50
        for i in range(0, len(tickers), batch_size):
            batch = tickers[i:i+batch_size]
            try:
                result = db.table("stocks").select("ticker").in_("ticker", batch).execute()
                existing.update(r["ticker"] for r in (result.data or []))
                _time.sleep(0.1)
            except Exception:
                pass

        missing = [t for t in tickers if t not in existing]
        if not missing:
            return 0

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
                _time.sleep(0.2)
            except Exception:
                pass

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
    Dipertahankan untuk backward-compat — untuk update_ticker(), pakai
    get_ticker_price_status() (1 query gabungan) alih-alih dua panggilan
    terpisah (get_last_price_date + get_price_row_count) demi mengurangi
    beban koneksi paralel ke Supabase nano.
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


def get_ticker_price_status(ticker: str) -> tuple[Optional[str], int]:
    """
    Dapatkan last_date DAN row_count sekaligus dalam SATU query.

    AUDIT FIX (insiden "500 saham tetap rows=17 walau healing sudah aktif"):
    versi sebelumnya melakukan 2 query terpisah (get_last_price_date lalu
    get_price_row_count) per ticker. Dengan 514 ticker × 2 query paralel
    di bawah ThreadPoolExecutor yang berbagi 1 Supabase client instance,
    ditemukan hasil yang tidak konsisten untuk sebagian besar ticker
    (row_count computed salah/tinggi padahal data asli cuma 17 baris) —
    kelas bug yang sama dengan insiden ConnectionTerminated sebelumnya
    di sistem ini (Supabase nano sensitif terhadap request paralel).

    PostgREST bisa mengembalikan COUNT TOTAL (lewat header Content-Range)
    BERSAMAAN dengan data yang di-limit — jadi last_date dan row_count
    bisa didapat dari SATU request, bukan dua, menghilangkan celah
    inkonsistensi sekaligus mengurangi beban koneksi jadi setengahnya.

    Return: (last_date_iso_atau_None, row_count)
    """
    try:
        db = get_db()
        result = (
            db.table("daily_prices")
            .select("trade_date", count="exact")
            .eq("ticker", ticker)
            .order("trade_date", desc=True)
            .limit(1)
            .execute()
        )
        last_date = result.data[0]["trade_date"] if result.data else None
        row_count = result.count if result.count is not None else 0
        return last_date, row_count
    except Exception:
        return None, 0


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
    batch_size = 100

    for i in range(0, len(records), batch_size):
        batch = records[i:i + batch_size]
        for attempt in range(3):
            try:
                db.table("daily_prices").upsert(
                    batch,
                    on_conflict="ticker,trade_date"
                ).execute()
                total_inserted += len(batch)
                _time.sleep(0.1)
                break
            except Exception as e:
                err_str = str(e)
                if attempt < 2:
                    wait = (attempt + 1) * 1.0
                    _time.sleep(wait)
                    continue
                from src.core.logger import get_logger
                log = get_logger("database")
                log.error(f"Gagal bulk insert prices: {err_str[:200]}")
                break

    return total_inserted


def _upsert_with_schema_fallback(
    table: str,
    data: dict,
    on_conflict: Optional[str] = None,
) -> tuple[bool, Optional[dict]]:
    """
    Upsert/insert dengan fallback otomatis jika ada kolom yang belum
    ada di schema Supabase (PGRST204 "column not found in schema cache").

    AUDIT (2026-08, ditemukan saat audit menyeluruh): retry loop
    SEBELUMNYA `for _ in range(2)` -- cuma sanggup membuang SATU kolom
    bermasalah sebelum menyerah. Kalau lebih dari 1 kolom baru belum
    ada di schema sekaligus (co. migration 005 DAN 006 sama-sama belum
    dijalankan -- persis situasi setelah rilis flow indicators +
    trend_structure bersamaan), upsert GAGAL TOTAL (return False, tidak
    ada sinyal tersimpan sama sekali hari itu) padahal harusnya tetap
    bisa simpan sisa kolom yang valid. Diperbaiki: jumlah percobaan
    mengikuti JUMLAH KOLOM di payload (bukan angka tetap 2), supaya bisa
    buang kolom bermasalah satu-per-satu sampai berhasil atau kolom
    habis. Tidak bisa infinite loop -- tiap retry yang sukses membuang
    kolom mengecilkan payload secara ketat.
    """
    import re as _re

    db = get_db()
    payload = dict(data)
    max_attempts = len(payload) + 1   # cukup untuk buang SEMUA kolom kalau perlu

    for _ in range(max_attempts):
        try:
            if on_conflict:
                res = db.table(table).upsert(payload, on_conflict=on_conflict).execute()
            else:
                res = db.table(table).insert(payload).execute()
            return True, (res.data[0] if res.data else None)

        except Exception as e:
            err_str = str(e)
            if "PGRST204" in err_str or "could not find" in err_str.lower():
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
                    continue

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


# ══════════════════════════════════════════════════════════════════
#  SIGNAL RESULTS — Automatic Signal Evaluation Engine
#  (Additive, tabel baru dari migration 003. Tidak menyentuh fungsi
#  save_signal/save_market_regime/dst di atas — lihat src/signals/
#  signal_evaluator.py untuk logika lengkapnya.)
# ══════════════════════════════════════════════════════════════════

def upsert_signal_result(data: dict) -> bool:
    """
    Simpan/update 1 baris signal_results. Upsert pakai constraint
    UNIQUE(ticker, signal_date, signal_type) dari migration 003 —
    aman dipanggil berulang (idempotent), baik untuk snapshot baru
    (INSERT) maupun update status evaluasi (OPEN -> CLOSED/EXPIRED).
    """
    ok, _ = _upsert_with_schema_fallback(
        "signal_results", data, on_conflict="ticker,signal_date,signal_type"
    )
    return ok


def get_open_signal_results(ticker: Optional[str] = None) -> list[dict]:
    """Ambil semua signal_results yang masih berstatus OPEN."""
    try:
        db = get_db()
        q = db.table("signal_results").select("*").eq("status", "OPEN")
        if ticker:
            q = q.eq("ticker", ticker)
        result = q.execute()
        return result.data or []
    except Exception as e:
        from src.core.logger import get_logger
        log = get_logger("database")
        log.error(f"Gagal ambil open signal_results: {e}")
        return []


def get_signal_results_missing_patterns(limit: int = 5000) -> list[dict]:
    """
    Ambil signal_results yang trend_structure-nya masih NULL -- dipakai
    src/signals/signal_evaluator.py::backfill_trend_and_patterns() buat
    isi data lama yang dibuat sebelum pattern_engine.py ada (v2.3).
    Idempotent secara alami: baris yang sudah keisi otomatis tidak
    kepanggil lagi di run berikutnya.
    """
    try:
        db = get_db()
        result = (
            db.table("signal_results")
            .select("ticker,signal_date,signal_type,atr,close_price,market_regime")
            .is_("trend_structure", "null")
            .order("signal_date")
            .limit(limit)
            .execute()
        )
        return result.data or []
    except Exception as e:
        from src.core.logger import get_logger
        log = get_logger("database")
        log.error(f"Gagal ambil signal_results missing patterns: {e}")
        return []


def get_weekly_scanner_stats(days: int = 7) -> dict:
    """
    Statistik scan mingguan dari tabel `signals` (BUKAN signal_results) --
    dipakai runner.py::gather_weekly_stats() buat isi WEEKLY REPORT.
    Return: {"total_runs": int (hari unik ada scan), "strong_buy": int,
             "buy": int, "watchlist": int}
    """
    try:
        from datetime import date, timedelta
        db = get_db()
        since = (date.today() - timedelta(days=days)).isoformat()
        result = (
            db.table("signals")
            .select("signal_date,signal_type")
            .gte("signal_date", since)
            .execute()
        )
        rows = result.data or []
        if not rows:
            return {}
        return {
            "total_runs": len({r["signal_date"] for r in rows}),
            "strong_buy": sum(1 for r in rows if r["signal_type"] == "STRONG_BUY"),
            "buy": sum(1 for r in rows if r["signal_type"] == "BUY"),
            "watchlist": sum(1 for r in rows if r["signal_type"] == "WATCHLIST"),
        }
    except Exception as e:
        from src.core.logger import get_logger
        log = get_logger("database")
        log.error(f"Gagal ambil weekly scanner stats: {e}")
        return {}


def get_top_signals_range(days: int = 7, limit: int = 5) -> list[dict]:
    """Top N sinyal (by raw_score) dalam N hari terakhir dari tabel `signals`."""
    try:
        from datetime import date, timedelta
        db = get_db()
        since = (date.today() - timedelta(days=days)).isoformat()
        result = (
            db.table("signals")
            .select("ticker,signal_type,raw_score")
            .gte("signal_date", since)
            .in_("signal_type", ["STRONG_BUY", "BUY"])
            .order("raw_score", desc=True)
            .limit(limit)
            .execute()
        )
        return result.data or []
    except Exception as e:
        from src.core.logger import get_logger
        log = get_logger("database")
        log.error(f"Gagal ambil top signals range: {e}")
        return []


def get_universe_weekly_diff(days: int = 7) -> dict:
    """
    Total saham aktif + berapa yang ditambah/didelisting dlm N hari terakhir,
    dihitung dari timestamp `created_at`/`delisted_date` di tabel `stocks`
    (bukan dari return value refresh_universe() -- itu tidak persisten
    lintas proses CLI yang terpisah, lihat CHANGELOG v2.3.1).
    """
    try:
        from datetime import date, timedelta
        db = get_db()
        since = (date.today() - timedelta(days=days)).isoformat()

        total = db.table("stocks").select("ticker", count="exact").eq("is_active", True).limit(1).execute()
        added = db.table("stocks").select("ticker", count="exact").gte("created_at", since).limit(1).execute()
        removed = (
            db.table("stocks").select("ticker", count="exact")
            .eq("is_delisted", True).gte("delisted_date", since).limit(1).execute()
        )
        return {
            "total": total.count if total.count is not None else "N/A",
            "added": added.count if added.count is not None else "N/A",
            "removed": removed.count if removed.count is not None else "N/A",
        }
    except Exception as e:
        from src.core.logger import get_logger
        log = get_logger("database")
        log.error(f"Gagal ambil universe weekly diff: {e}")
        return {}


def get_signal_results_range(days: int = 90, status: Optional[str] = None) -> list[dict]:
    """Ambil signal_results dalam rentang N hari terakhir (untuk Signal Performance)."""
    try:
        from datetime import date, timedelta
        db = get_db()
        since = (date.today() - timedelta(days=days)).isoformat()
        q = db.table("signal_results").select("*").gte("signal_date", since)
        if status:
            q = q.eq("status", status)
        result = q.order("signal_date", desc=True).execute()
        return result.data or []
    except Exception as e:
        from src.core.logger import get_logger
        log = get_logger("database")
        log.error(f"Gagal ambil signal_results range: {e}")
        return []


def signal_result_exists(ticker: str, signal_date: str, signal_type: str) -> bool:
    """Cek apakah snapshot untuk kombinasi ini sudah ada (idempotency check tambahan)."""
    try:
        db = get_db()
        result = (
            db.table("signal_results")
            .select("id", count="exact")
            .eq("ticker", ticker).eq("signal_date", signal_date).eq("signal_type", signal_type)
            .limit(1).execute()
        )
        return (result.count or 0) > 0
    except Exception:
        return False


# ══════════════════════════════════════════════════════════════════
#  BROKER SUMMARY — Bandarmology (migration 004, additif)
#  Provider fetch: src/providers/broker_data.py
#  Analisis: src/signals/broker_engine.py
# ══════════════════════════════════════════════════════════════════

def bulk_insert_broker_summary(rows: list[dict], source_provider: str) -> int:
    """
    Bulk upsert broker_summary.

    net_volume/net_value: PREFER nilai yang sudah dikirim provider kalau
    ada (co. IDX Edge PRO kirim nval/nvol langsung -- vendor ini malah
    TIDAK kasih buy_volume/sell_volume terpisah sama sekali, jadi net_volume
    HARUS dari provider, tidak bisa dihitung dari selisih). Fallback
    hitung dari buy_value-sell_value / buy_volume-sell_volume HANYA kalau
    provider tidak mengirim net_value/net_volume langsung -- supaya kode
    ini tetap kompatibel dengan provider LAIN yang mungkin kasih breakdown
    penuh tapi tidak menghitung net-nya sendiri.
    AUDIT (2026-08): sebelumnya SELALU dihitung dari buy-sell, mengabaikan
    net_value/net_volume yang mungkin sudah dikirim provider — untuk IDX
    Edge PRO ini berarti net_volume selalu jadi 0-(-0)=0 (salah, karena
    buy_volume/sell_volume memang tidak pernah diisi provider ini).
    Batch kecil + retry, mengikuti pola bulk_insert_prices (Supabase nano
    sensitif terhadap request paralel/besar).
    """
    import time as _time
    if not rows:
        return 0

    db = get_db()
    total_inserted = 0
    batch_size = 100

    payload = []
    for r in rows:
        row = dict(r)
        row["source_provider"] = source_provider

        if row.get("net_value") is None:
            buy_val = row.get("buy_value") or 0
            sell_val = row.get("sell_value") or 0
            row["net_value"] = buy_val - sell_val

        if row.get("net_volume") is None:
            buy_vol = row.get("buy_volume")
            sell_vol = row.get("sell_volume")
            if buy_vol is not None or sell_vol is not None:
                row["net_volume"] = (buy_vol or 0) - (sell_vol or 0)
            # kalau buy_volume & sell_volume DUANYA None (co. IDX Edge PRO
            # tanpa net_volume terkirim -- seharusnya tidak terjadi tapi
            # dijaga), net_volume dibiarkan None -- JANGAN paksa jadi 0,
            # nol dan "tidak diketahui" beda makna buat analisis flow.

        payload.append(row)

    for i in range(0, len(payload), batch_size):
        batch = payload[i:i + batch_size]
        # AUDIT (2026-08, ditemukan saat audit menyeluruh): SEBELUMNYA
        # retry loop cuma coba ulang BATCH YANG SAMA 3x dengan backoff --
        # kalau kegagalannya karena KOLOM HILANG di schema (co. migration
        # 004 belum di-update ke revisi terbaru), retry identik akan
        # SELALU gagal juga, dan SELURUH batch (sampai 100 baris) hilang
        # diam-diam. Ini persis pola bug yang sudah diperbaiki di
        # _upsert_with_schema_fallback() -- diperbaiki di sini juga
        # dengan logic yang sama: deteksi kolom hilang dari pesan error,
        # buang kolom itu dari SEMUA baris di batch, baru retry.
        import re as _re
        current_batch = batch
        max_attempts = len(current_batch[0].keys()) + 3 if current_batch else 3
        for attempt in range(max_attempts):
            try:
                db.table("broker_summary").upsert(
                    current_batch, on_conflict="ticker,trade_date,broker_code"
                ).execute()
                total_inserted += len(current_batch)
                _time.sleep(0.1)
                break
            except Exception as e:
                err_str = str(e)
                if "PGRST204" in err_str or "could not find" in err_str.lower():
                    match = _re.search(r"'([a-zA-Z_][a-zA-Z0-9_]*)' column", err_str)
                    bad_col = match.group(1) if match else None
                    if bad_col and bad_col in current_batch[0]:
                        from src.core.logger import get_logger
                        log = get_logger("database")
                        log.warning(
                            f"Kolom '{bad_col}' belum ada di tabel 'broker_summary' "
                            f"(migration 004 versi lama?). Kolom ini dilewati untuk "
                            f"batch ini — data lain tetap disimpan."
                        )
                        current_batch = [
                            {k: v for k, v in row.items() if k != bad_col}
                            for row in current_batch
                        ]
                        continue

                if attempt < max_attempts - 1:
                    _time.sleep(min(attempt + 1, 3) * 1.0)
                    continue
                from src.core.logger import get_logger
                log = get_logger("database")
                log.error(f"Gagal bulk insert broker_summary: {err_str[:200]}")
                break

    return total_inserted


def get_broker_flow_range(ticker: str, days: int = 30) -> list[dict]:
    """Ambil net flow harian (view v_broker_net_flow_daily) N hari terakhir untuk 1 ticker."""
    try:
        from datetime import date as _date, timedelta as _timedelta
        db = get_db()
        since = (_date.today() - _timedelta(days=days)).isoformat()
        result = (
            db.table("v_broker_net_flow_daily")
            .select("*")
            .eq("ticker", ticker)
            .gte("trade_date", since)
            .order("trade_date", desc=True)
            .execute()
        )
        return result.data or []
    except Exception as e:
        from src.core.logger import get_logger
        log = get_logger("database")
        log.error(f"Gagal ambil broker flow range {ticker}: {e}")
        return []


def get_broker_classification() -> dict[str, dict]:
    """Ambil seluruh broker_classification sebagai dict {broker_code: {name, investor_type}}."""
    try:
        db = get_db()
        result = db.table("broker_classification").select("*").eq("is_active", True).execute()
        return {r["broker_code"]: r for r in (result.data or [])}
    except Exception:
        return {}


def get_top_liquid_tickers(n: int = 100) -> list[str]:
    """
    Ambil N ticker paling likuid (avg volume 20 hari tertinggi) dari
    v_ticker_avg_volume_20d (migration 004). TIDAK dipakai cmd_broker_scan
    lagi sejak v2.7.1 (diganti get_signal_tickers_today, lihat AUDIT di
    sana) -- dibiarkan tersedia sebagai utilitas untuk kebutuhan lain.
    """
    try:
        db = get_db()
        result = (
            db.table("v_ticker_avg_volume_20d")
            .select("ticker")
            .order("avg_volume_20d", desc=True)
            .limit(n)
            .execute()
        )
        return [r["ticker"] for r in (result.data or [])]
    except Exception as e:
        from src.core.logger import get_logger
        log = get_logger("database")
        log.error(f"Gagal ambil top liquid tickers: {e}")
        return []


def get_signal_tickers_today(order_by_score: bool = True) -> list[str]:
    """
    Ambil ticker dari sinyal HARI INI dengan signal_type STRONG_BUY/BUY/
    WATCHLIST -- basis scan broker_summary sejak v2.7.1 (SEBELUMNYA pakai
    get_top_liquid_tickers/top-N generik, diganti atas permintaan user
    supaya broker data fokus ke saham yang benar-benar jadi kandidat
    sinyal, bukan saham likuid generik yang belum tentu relevan).

    order_by_score=True: urutkan raw_score tertinggi dulu -- penting
    karena cmd_broker_scan masih membatasi jumlah dgn broker_scan_top_n
    (kuota vendor terbatas), jadi kalau jumlah sinyal > kuota, yang
    paling berkualitas (skor tertinggi) yang diprioritaskan duluan.
    """
    try:
        from datetime import date as _date
        db = get_db()
        today = _date.today().isoformat()
        q = (
            db.table("signals")
            .select("ticker, raw_score")
            .eq("signal_date", today)
            .in_("signal_type", ["STRONG_BUY", "BUY", "WATCHLIST"])
        )
        if order_by_score:
            q = q.order("raw_score", desc=True)
        result = q.execute()
        rows = result.data or []
        # Dedup sambil pertahankan urutan (harusnya sudah unique per
        # ticker/tanggal, tapi dijaga kalau-kalau ada duplikat data)
        seen = set()
        tickers = []
        for r in rows:
            t = r.get("ticker")
            if t and t not in seen:
                seen.add(t)
                tickers.append(t)
        return tickers
    except Exception as e:
        from src.core.logger import get_logger
        log = get_logger("database")
        log.error(f"Gagal ambil ticker sinyal hari ini: {e}")
        return []


def get_latest_signal_snapshot(tickers: list[str]) -> dict[str, dict]:
    """
    Ambil close_price/ema20 terbaru untuk sekumpulan ticker dari tabel
    `signals` (sinyal terakhir yang tersimpan per ticker, TIDAK harus
    hari ini persis -- reuse data yang sudah ada, bukan re-fetch harga
    terpisah). Basis kolom "Harga"/"MA20" di fitur Net Buy Window.

    Return: {ticker: {"close_price": .., "ema20": .., "signal_date": ..}}
    Ticker yang tidak ketemu sinyal tersimpan TIDAK muncul di dict hasil
    (caller wajib .get() dengan default, jangan asumsikan semua ticker
    yang diminta pasti ada).
    """
    if not tickers:
        return {}
    try:
        db = get_db()
        result = (
            db.table("signals")
            .select("ticker, close_price, ema20, signal_date")
            .in_("ticker", tickers)
            .order("signal_date", desc=True)
            .execute()
        )
        rows = result.data or []
        snapshot: dict[str, dict] = {}
        for r in rows:
            t = r.get("ticker")
            if t and t not in snapshot:   # baris pertama per ticker = signal_date terbaru (sudah di-order desc)
                snapshot[t] = r
        return snapshot
    except Exception as e:
        from src.core.logger import get_logger
        log = get_logger("database")
        log.error(f"Gagal ambil signal snapshot: {e}")
        return {}
