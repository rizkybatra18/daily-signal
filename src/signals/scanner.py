"""
DAILY SIGNAL — Signal Scanner (Main Orchestrator)
Menyatukan semua komponen menjadi daily scan pipeline.

Pipeline (AUDIT: urutan diubah dari versi sebelumnya — lihat catatan
di Step 3/4/5 di bawah untuk alasannya):
    1. Universe Manager  → daftar semua saham BEI
    2. Incremental Update → update database harga
    3. Load OHLCV         → load data harga SEMUA saham dari DB
    4. Regime + Breadth   → kondisi pasar, kini pakai breadth NYATA
                             dari data yang sudah dimuat di step 3
    5. Sector Rotation    → ranking sektor
    6. TA Engine          → analisis teknikal + scoring per saham (parallel)
    7. Filter & Funnel    → buang yang tidak layak, log funnel lengkap
    8. Output             → simpan ke database + kirim Telegram
"""

import concurrent.futures
import time
import uuid
from datetime import date, datetime
from typing import Optional

import pandas as pd

from src.core.config import settings
from src.core.logger import get_logger
from src.core.database import save_signal, log_scan_run, update_scan_run, get_db, ensure_stocks_registered
from src.providers.universe_manager import get_all_bei_tickers, get_tickers_by_sector, TICKER_SECTOR
from src.providers.market_data import MarketDataProvider, IncrementalDataUpdater, get_ohlcv_from_db
from src.signals.ta_engine import analyze_stock, apply_basic_filters, StockAnalysis
from src.signals.regime_engine import detect_market_regime, compute_market_breadth, MarketRegime
from src.signals.sector_engine import calculate_sector_rankings, get_sector_bonus

log = get_logger("scanner")


def run_daily_scan(
    top_n: int = None,
    save_to_db: bool = True,
    send_telegram: bool = True,
) -> dict:
    """
    Jalankan full daily scan pipeline.

    Args:
        top_n: Jumlah sinyal teratas yang dikirim ke Telegram (default dari settings)
        save_to_db: Simpan sinyal ke database
        send_telegram: Kirim sinyal ke Telegram

    Returns:
        dict berisi: {
            "run_id": str,
            "regime": MarketRegime,
            "signals": list[StockAnalysis],
            "summary": dict,   # termasuk "funnel" — lihat _log_funnel()
            "duration_seconds": float,
        }
    """
    run_id = str(uuid.uuid4())
    start_time = time.time()
    top_n = top_n or settings.top_n_signals

    log.info(f"═══ DAILY SIGNAL SCAN DIMULAI [run_id={run_id[:8]}] ═══")

    log_scan_run({
        "run_id": run_id,
        "run_type": "DAILY_SCAN",
        "started_at": datetime.utcnow().isoformat(),
        "status": "RUNNING",
    })

    try:
        # ── Step 1: Dapatkan Universe ──────────────────────────────
        log.info("[1/8] Mengambil universe saham BEI...")
        all_tickers = get_all_bei_tickers()
        universe_count = len(all_tickers)
        log.info(f"      → {universe_count} ticker di universe")

        # ── Step 2: Update Data Incremental ───────────────────────
        log.info("[2/8] Update data harga (incremental)...")
        n_registered = ensure_stocks_registered(all_tickers)
        if n_registered > 0:
            log.info(f"      → {n_registered} ticker baru didaftarkan ke tabel stocks")
        updater = IncrementalDataUpdater()
        update_summary = updater.update_batch(all_tickers, max_workers=2)
        log.info(f"      → {update_summary['updated']} diupdate, +{update_summary['rows_added']} rows")

        # ── Step 3: Load OHLCV Semua Saham dari Database ───────────
        # AUDIT FIX (Market Breadth): sebelumnya deteksi regime (step
        # lama #4) dijalankan SEBELUM data harga seluruh saham dimuat,
        # sehingga breadth_data yang dikirim ke detect_market_regime()
        # selalu None (parameter itu efektif mati, tidak pernah terisi).
        # Urutan diubah: load dulu di sini, baru breadth bisa dihitung
        # NYATA dari data ini sebelum deteksi regime dijalankan.
        log.info("[3/8] Load data OHLCV seluruh saham dari database...")
        stock_data = _load_batch_from_db(all_tickers, days=252, max_workers=3)
        data_available_count = len(stock_data)
        log.info(f"      → {data_available_count} saham berhasil di-load")

        # ── Step 4: Market Breadth + Regime Detection ──────────────
        log.info("[4/8] Menghitung market breadth & deteksi regime...")
        provider = MarketDataProvider()
        ihsg_df = provider.fetch_ohlcv(settings.ihsg_ticker, period="60d")
        ihsg_close = ihsg_df["close"] if ihsg_df is not None else None

        breadth_data = compute_market_breadth(stock_data)
        regime = detect_market_regime(ihsg_df, breadth_data=breadth_data)
        log.info(
            f"      → Regime: {regime.regime} (weight={regime.regime_weight}) | "
            f"Breadth: {regime.breadth_score:.0f}% naik, "
            f"{regime.pct_above_ema50:.0f}% di atas EMA50"
        )

        if regime.regime == "BEAR":
            log.warning(
                "Market BEAR — scan tetap dijalankan, threshold sinyal diperketat "
                f"otomatis (STRONG_BUY>={settings.adaptive_thresholds['BEAR']['strong_buy']:.0f}, "
                "bukan disuppress total — saham reversal awal tetap bisa terdeteksi)"
            )

        # ── Step 5: Sector Rotation ────────────────────────────────
        log.info("[5/8] Menghitung sector rotation...")
        sector_rankings = calculate_sector_rankings(stock_data)
        top_sectors = [f"#{sr.rank} {sr.sector}" for sr in sector_rankings[:3]]
        log.info(f"      → Top 3 sektor: {', '.join(top_sectors)}")

        # ── Step 6: Analisis TA per Saham (Parallel) ──────────────
        log.info(f"[6/8] Analisis teknikal {len(stock_data)} saham (parallel)...")
        analyses = _analyze_all_parallel(
            stock_data=stock_data,
            ihsg_close=ihsg_close,
            regime_weight=regime.regime_weight,
            regime_label=regime.regime,
            sector_rankings=sector_rankings,
            max_workers=4,
        )
        analyzed_count = len(analyses)

        # ── Step 7: Filter, Sort, Funnel ────────────────────────────
        log.info("[7/8] Filter & ranking...")
        passed = [a for a in analyses if a.passed_basic_filter]
        technical_pass_count = len(passed)

        passed.sort(key=lambda a: a.score.final_score, reverse=True)

        strong_buy = [a for a in passed if a.score.signal_type == "STRONG_BUY"]
        buy = [a for a in passed if a.score.signal_type == "BUY"]
        watchlist = [a for a in passed if a.score.signal_type == "WATCHLIST"]
        avoid = [a for a in passed if a.score.signal_type == "AVOID"]
        score_pass_count = len(strong_buy) + len(buy) + len(watchlist)

        top_signals = (strong_buy + buy)[:top_n]

        funnel = {
            "universe": universe_count,
            "data_available": data_available_count,
            "analyzed": analyzed_count,
            "technical_pass": technical_pass_count,
            "score_pass_watchlist_plus": score_pass_count,
            "buy": len(buy),
            "strong_buy": len(strong_buy),
        }
        _log_funnel(funnel, regime.regime)

        # ── Simpan ke Database ─────────────────────────────────────
        signal_ids = []
        if save_to_db:
            log.info(f"Menyimpan {len(passed)} sinyal ke database...")
            for analysis in passed:
                ticker_clean = analysis.ticker.replace(".JK", "")
                sector = TICKER_SECTOR.get(ticker_clean, "Uncategorized")

                sec_rank = next(
                    (sr.rank for sr in sector_rankings if sr.sector == sector),
                    None,
                )

                signal_data = {
                    "signal_date":  date.today().isoformat(),
                    "market_regime": regime.regime,
                    "sector":        sector,
                    "sector_rank":   sec_rank,
                    **analysis.to_dict(),
                }
                signal_id = save_signal(signal_data)
                if signal_id:
                    signal_ids.append(signal_id)
            log.info(f"✓ {len(signal_ids)} sinyal tersimpan")

        # ── Kirim ke Telegram ─────────────────────────────────────
        if send_telegram:
            _send_signals_telegram(top_signals, regime, sector_rankings)

        # ── Finish ────────────────────────────────────────────────
        duration = time.time() - start_time

        summary = {
            "stocks_scanned": len(analyses),
            "passed_filter": len(passed),
            "strong_buy": len(strong_buy),
            "buy": len(buy),
            "watchlist": len(watchlist),
            "avoid": len(avoid),
            "signals_saved": len(signal_ids),
            "regime": regime.regime,
            "duration_seconds": round(duration, 1),
            "funnel": funnel,
        }

        update_scan_run(run_id, {
            "completed_at": datetime.utcnow().isoformat(),
            "status": "SUCCESS",
            "stocks_scanned": summary["stocks_scanned"],
            "signals_generated": summary["strong_buy"] + summary["buy"],
            "duration_seconds": int(duration),
        })

        log.info(
            f"═══ SCAN SELESAI dalam {duration:.1f}s ═══ | "
            f"STRONG_BUY={len(strong_buy)} BUY={len(buy)} "
            f"WATCHLIST={len(watchlist)}"
        )

        return {
            "run_id": run_id,
            "regime": regime,
            "signals": top_signals,
            "all_signals": passed,
            "sector_rankings": sector_rankings,
            "summary": summary,
            "duration_seconds": duration,
        }

    except Exception as e:
        duration = time.time() - start_time
        log.error(f"Scan gagal setelah {duration:.1f}s: {e}", exc=e)

        update_scan_run(run_id, {
            "completed_at": datetime.utcnow().isoformat(),
            "status": "FAILED",
            "error_message": str(e)[:500],
            "duration_seconds": int(duration),
        })

        raise


def _log_funnel(funnel: dict, regime_label: str):
    """
    Log funnel scan secara terstruktur (AUDIT: Filter Audit / Logging).

    CATATAN JUJUR: "Regime" dan "Sector" di sistem ini BUKAN gate yang
    men-drop kandidat satu-per-satu — keduanya adalah MODIFIER yang
    diterapkan SAMA ke semua saham (regime = satu nilai untuk seluruh
    pasar hari itu; sector_bonus = +5/-5/0 tergantung ranking sektor
    saham tsb). Karena itu funnel di bawah menampilkan tahapan yang
    SUNGGUHAN mengurangi kandidat (data availability → technical
    filter → score threshold), bukan tahapan fiktif yang sebenarnya
    tidak meng-gugurkan saham satupun.
    """
    lines = [
        "=" * 44,
        "  DAILY SCAN — FUNNEL",
        "=" * 44,
        f"  Universe             : {funnel['universe']}",
        f"  Data Tersedia         : {funnel['data_available']}",
        f"  Berhasil Dianalisis   : {funnel['analyzed']}",
        f"  Lolos Filter Teknikal : {funnel['technical_pass']}",
        f"  Lolos Score (>=WL)    : {funnel['score_pass_watchlist_plus']}",
        f"  BUY                   : {funnel['buy']}",
        f"  STRONG BUY            : {funnel['strong_buy']}",
        "-" * 44,
        f"  Market Regime aktif   : {regime_label}",
        "=" * 44,
    ]
    log.info("\n" + "\n".join(lines), details=funnel)


def _load_batch_from_db(
    tickers: list[str],
    days: int = 252,
    max_workers: int = 3,  # tidak dipakai lagi, kept for compatibility
) -> dict[str, pd.DataFrame]:
    """
    Load OHLCV semua ticker dalam batch query ke Supabase.
    Gunakan IN clause (60 ticker per batch) bukan N query paralel.
    Satu koneksi, satu round-trip — tidak ada ServerDisconnected.
    """
    import time as _time
    from datetime import date as _date, timedelta

    if not tickers:
        return {}

    results     = {}
    start_date  = (_date.today() - timedelta(days=days)).isoformat()
    all_rows    = []
    batch_size  = 60   # aman untuk URL length Supabase

    for i in range(0, len(tickers), batch_size):
        batch = tickers[i:i + batch_size]
        for attempt in range(3):
            try:
                db = get_db()
                res = (
                    db.table("daily_prices")
                    .select("ticker, trade_date, open, high, low, close, volume")
                    .in_("ticker", batch)
                    .gte("trade_date", start_date)
                    .order("ticker")
                    .order("trade_date")
                    .range(0, 100000)
                    .execute()
                )
                log.info(f"[DEBUG] res.count = {getattr(res, 'count', None)}")
                log.info(f"[DEBUG] len(res.data) = {len(res.data) if res.data else 0}")
                log.info(f"[DEBUG] first row = {res.data[0] if res.data else None}")
                log.info(f"[DEBUG] Batch {i//batch_size+1}: returned {len(res.data or [])} rows")
                all_rows.extend(res.data or [])
                _time.sleep(0.3)   # jeda antar batch
                break
            except Exception as e:
                if attempt < 2:
                    _time.sleep((attempt + 1) * 1.5)
                else:
                    log.warning(
                        f"Batch {i//batch_size+1} gagal load setelah 3x: {str(e)[:80]}"
                    )

    if not all_rows:
        log.warning("Tidak ada data OHLCV berhasil di-load dari database")
        return {}

    df_all = pd.DataFrame(all_rows)
    df_all["trade_date"] = pd.to_datetime(df_all["trade_date"])
    log.info(f"[DEBUG] Total rows loaded: {len(df_all)}")
    log.info(f"[DEBUG] AGRO.JK rows in df_all: {len(df_all[df_all['ticker']=='AGRO.JK'])}")

    for ticker in tickers:
        df_t = df_all[df_all["ticker"] == ticker].copy()
        if df_t.empty:
            continue
        df_t = df_t.drop(columns=["ticker"]).set_index("trade_date")
        for col in ["open", "high", "low", "close", "volume"]:
            if col in df_t.columns:
                df_t[col] = pd.to_numeric(df_t[col], errors="coerce")
        df_t = df_t.dropna(subset=["close"])
        if not df_t.empty:
            results[ticker] = df_t
    log.info(f"[DEBUG] results tickers = {len(results)}")
    log.info(f"[DEBUG] unique tickers df_all = {df_all['ticker'].nunique()}")

    missing = sorted(set(tickers) - set(results.keys()))
    log.info(f"[DEBUG] missing ticker count = {len(missing)}")
    log.info(f"[DEBUG] first missing = {missing[:20]}")

    return results


def _analyze_all_parallel(
    stock_data: dict[str, pd.DataFrame],
    ihsg_close: Optional[pd.Series],
    regime_weight: float,
    regime_label: str,
    sector_rankings: list,
    max_workers: int = 4,
) -> list[StockAnalysis]:
    """
    Analisis semua saham secara parallel.

    AUDIT FIX (Scoring Engine): sebelumnya sector_bonus diterapkan
    SETELAH analyze_stock() selesai (bolt-on ke final_score, lalu
    _determine_signal_type dipanggil ULANG dengan regime_weight
    di-hardcode 1.0 — mengabaikan regime asli untuk klasifikasi kedua
    ini). Sekarang sector_bonus dihitung LEBIH DULU dan dikirim
    langsung ke analyze_stock(), yang menerapkannya ke raw_score
    sebelum klasifikasi — satu kali proses, konsisten, tidak ada
    override regime yang terselip.
    """
    results = []
    total = len(stock_data)
    completed = 0

    none_count = 0
    none_samples = []
    exc_count = 0
    exc_samples = []

    def analyze_one(ticker_df_pair):
        nonlocal none_count, exc_count
        ticker, df = ticker_df_pair
        try:
            sector_bonus = get_sector_bonus(ticker, sector_rankings)

            analysis = analyze_stock(
                ticker=ticker,
                df=df,
                ihsg_close=ihsg_close,
                regime_weight=regime_weight,
                regime=regime_label,
                sector_bonus=sector_bonus,
            )
            if analysis is None:
                none_count += 1
                if len(none_samples) < 8:
                    rows = len(df) if df is not None else 0
                    none_samples.append(f"{ticker}(rows={rows})")
                return None

            analysis = apply_basic_filters(analysis)
            return analysis
        except Exception as e:
            exc_count += 1
            if len(exc_samples) < 8:
                exc_samples.append(f"{ticker}: {type(e).__name__}: {e}")
            return None

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(analyze_one, item): item[0]
            for item in stock_data.items()
        }

        for future in concurrent.futures.as_completed(futures, timeout=300):
            ticker = futures[future]
            completed += 1

            try:
                result = future.result()
                if result is not None:
                    results.append(result)
            except Exception as e:
                log.debug(f"Analisis error {ticker}: {e}")

            if completed % 50 == 0:
                log.info(f"  Progress: {completed}/{total} saham dianalisis...")

    log.info(f"Analisis selesai: {len(results)}/{total} berhasil")

    if none_count > 0:
        log.warning(
            f"⚠ {none_count}/{total} saham di-skip (analyze_stock return None — "
            f"biasanya data < 30 baris). Contoh: {'; '.join(none_samples)}"
        )
    if exc_count > 0:
        log.error(
            f"❌ {exc_count}/{total} saham GAGAL karena exception. "
            f"Contoh: {'; '.join(exc_samples)}"
        )

    return results


def _send_signals_telegram(
    signals: list[StockAnalysis],
    regime: MarketRegime,
    sector_rankings: list,
):
    """Kirim sinyal ke Telegram (wrapper dengan error handling)."""
    try:
        from src.telegram.bot import send_daily_signals
        send_daily_signals(signals, regime, sector_rankings)
    except Exception as e:
        log.error(f"Gagal kirim Telegram: {e}", exc=e)
        # Tidak re-raise — Telegram failure tidak boleh gagalkan scan


def run_health_check() -> dict:
    """
    Jalankan health check semua komponen.
    Return dict status semua komponen.
    """
    from src.core.database import health_check as db_health

    results = {}

    results["database"] = db_health()

    try:
        from src.telegram.bot import check_telegram_health
        results["telegram"] = check_telegram_health()
    except Exception as e:
        results["telegram"] = {"status": "error", "error": str(e)}

    try:
        provider = MarketDataProvider()
        df = provider.fetch_ohlcv("BBCA.JK", period="5d")
        results["data_provider"] = {
            "status": "healthy" if df is not None else "unhealthy",
            "test_ticker": "BBCA.JK",
            "rows": len(df) if df is not None else 0,
        }
    except Exception as e:
        results["data_provider"] = {"status": "error", "error": str(e)}

    overall = "healthy" if all(
        r.get("status") == "healthy" for r in results.values()
    ) else "degraded"

    results["overall"] = overall
    log.info(f"Health check: {overall}")

    return results
