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
    8. Analog Matching     → K-Nearest Neighbor utk kandidat lolos teknikal (BARU, v2.8.0)
    9. Output              → simpan ke database + kirim Telegram
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
from src.signals.ta_engine import analyze_stock, apply_basic_filters, StockAnalysis, AnalogInfo
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
        log.info("[1/9] Mengambil universe saham BEI...")
        all_tickers = get_all_bei_tickers()
        universe_count = len(all_tickers)
        log.info(f"      → {universe_count} ticker di universe")

        # ── Step 2: Update Data Incremental ───────────────────────
        log.info("[2/9] Update data harga (incremental)...")
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
        log.info("[3/9] Load data OHLCV seluruh saham dari database...")
        stock_data = _load_batch_from_db(all_tickers, days=252, max_workers=3)
        data_available_count = len(stock_data)
        log.info(f"      → {data_available_count} saham berhasil di-load")

        # ── Step 4: Market Breadth + Regime Detection ──────────────
        log.info("[4/9] Menghitung market breadth & deteksi regime...")
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
        log.info("[5/9] Menghitung sector rotation...")
        sector_rankings = calculate_sector_rankings(stock_data)
        top_sectors = [f"#{sr.rank} {sr.sector}" for sr in sector_rankings[:3]]
        log.info(f"      → Top 3 sektor: {', '.join(top_sectors)}")

        # ── Step 6: Analisis TA per Saham (Parallel) ──────────────
        log.info(f"[6/9] Analisis teknikal {len(stock_data)} saham (parallel)...")
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
        log.info("[7/9] Filter & ranking (pra-analog)...")
        passed = [a for a in analyses if a.passed_basic_filter]
        technical_pass_count = len(passed)

        # AUDIT: sort pakai raw_score (bukan final_score) biar konsisten
        # dengan klasifikasi signal_type & ranking di dashboard/telegram
        # -- lihat _determine_signal_type(). Dalam 1x scan run hasilnya
        # identik (regime_weight sama utk semua kandidat di run yg sama),
        # tapi raw_score lebih jelas maknanya utk pembaca kode.
        passed.sort(key=lambda a: a.score.raw_score, reverse=True)

        strong_buy = [a for a in passed if a.score.signal_type == "STRONG_BUY"]
        buy = [a for a in passed if a.score.signal_type == "BUY"]
        watchlist = [a for a in passed if a.score.signal_type == "WATCHLIST"]
        avoid = [a for a in passed if a.score.signal_type == "AVOID"]
        score_pass_count_pre_analog = len(strong_buy) + len(buy) + len(watchlist)

        # ── Step 8: Analog Matching (BARU, v2.8.0) ──────────────────
        # Cuma utk yang SUDAH lolos teknikal (strong_buy/buy/watchlist
        # dari kategorisasi PRA-analog di atas) -- sesuai permintaan
        # user, hindari fetch histori 3 tahun utk saham yang toh besar
        # kemungkinan AVOID. Lihat _apply_analog_scoring() untuk detail.
        if settings.analog_scan_enabled:
            log.info(f"[8/9] Analog matching (K-Nearest Neighbor) utk {score_pass_count_pre_analog} kandidat...")
            passed, analog_summary = _apply_analog_scoring(
                passed=passed,
                stock_data=stock_data,
                ihsg_close=ihsg_close,
                regime_weight=regime.regime_weight,
                regime_label=regime.regime,
                sector_rankings=sector_rankings,
            )
            log.info(
                f"      → {analog_summary['computed']}/{analog_summary['candidates']} dihitung, "
                f"{analog_summary['reliable']} reliable (n_analogs cukup), "
                f"{analog_summary['errors']} error"
            )

            # Re-kategorisasi -- raw_score bisa berubah (analog_score
            # ditambahkan), jadi urutan/signal_type WAJIB dihitung ulang,
            # bukan cuma di-patch sebagian.
            passed.sort(key=lambda a: a.score.raw_score, reverse=True)
            strong_buy = [a for a in passed if a.score.signal_type == "STRONG_BUY"]
            buy = [a for a in passed if a.score.signal_type == "BUY"]
            watchlist = [a for a in passed if a.score.signal_type == "WATCHLIST"]
            avoid = [a for a in passed if a.score.signal_type == "AVOID"]
        else:
            log.info("[8/9] Analog matching dimatikan (ANALOG_SCAN_ENABLED=False), dilewati.")
            analog_summary = {"candidates": 0, "computed": 0, "reliable": 0, "errors": 0}

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
            "analog": analog_summary,
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
        batch_no = i // batch_size + 1
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
                n_returned = len(res.data) if res.data else 0
                n_tickers_returned = len({r["ticker"] for r in res.data}) if res.data else 0
                log.debug(
                    f"Batch {batch_no} ({batch[0]}..{batch[-1]}): "
                    f"{n_returned} baris dari {n_tickers_returned}/{len(batch)} ticker"
                )
                all_rows.extend(res.data or [])
                _time.sleep(0.3)   # jeda antar batch
                break
            except Exception as e:
                if attempt < 2:
                    _time.sleep((attempt + 1) * 1.5)
                else:
                    log.warning(
                        f"Batch {batch_no} gagal load setelah 3x: {str(e)[:80]}"
                    )

    if not all_rows:
        log.warning("Tidak ada data OHLCV berhasil di-load dari database")
        return {}

    df_all = pd.DataFrame(all_rows)
    df_all["trade_date"] = pd.to_datetime(df_all["trade_date"])
    log.debug(f"Total baris ter-load: {len(df_all)} ({df_all['ticker'].nunique()} ticker unik)")

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

    missing = sorted(set(tickers) - set(results.keys()))
    if missing:
        log.info(f"{len(missing)}/{len(tickers)} ticker tidak ada data OHLCV cukup: {missing[:20]}{'...' if len(missing) > 20 else ''}")

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


def _apply_analog_scoring(
    passed: list[StockAnalysis],
    stock_data: dict[str, pd.DataFrame],
    ihsg_close: Optional[pd.Series],
    regime_weight: float,
    regime_label: str,
    sector_rankings: list,
    max_workers: int = 3,
) -> tuple[list[StockAnalysis], dict]:
    """
    Step BARU (v2.8.0): untuk saham yang SUDAH lolos filter teknikal
    (signal_type STRONG_BUY/BUY/WATCHLIST dari analisis awal TANPA
    analog_score), hitung K-Nearest Neighbor analog matching (lihat
    src/signals/analog_engine.py) dan RE-RUN analyze_stock() untuk
    ticker itu SAJA dengan analog_score terisi -- supaya raw_score/
    signal_type akhir benar-benar mencerminkan kontribusi analog.

    KENAPA 2-PASS (bukan langsung dihitung di step 6 bareng semua
    saham): analog matching butuh histori 3 TAHUN (get_ohlcv_from_db
    days=365*3), jauh lebih panjang dari window scan normal (252 hari)
    -- fetch 3 tahun utk SELURUH ~550 ticker tiap hari scan akan boros
    I/O & waktu utk saham yang toh besar kemungkinan berujung AVOID.
    Sesuai permintaan user: cuma hitung utk yang "lolos teknikal".

    Return: (passed list yang sudah diupdate utk kandidat, summary dict)
    """
    from src.providers.market_data import get_ohlcv_from_db
    from src.signals.analog_engine import find_analogs, score_from_analog

    candidates = [a for a in passed if a.score.signal_type in ("STRONG_BUY", "BUY", "WATCHLIST")]
    if not candidates:
        return passed, {"candidates": 0, "computed": 0, "reliable": 0, "errors": 0}

    by_ticker = {a.ticker: a for a in passed}
    computed_count = 0
    reliable_count = 0
    error_count = 0
    error_samples = []

    def process_one(analysis: StockAnalysis):
        nonlocal error_count
        ticker = analysis.ticker
        try:
            df_3y = get_ohlcv_from_db(ticker, days=365 * 3)
            if df_3y is None or df_3y.empty:
                return None

            analog_result = find_analogs(ticker, df_3y, ihsg_close=ihsg_close)
            analog_score = score_from_analog(analog_result)

            # AUDIT (ditemukan saat integrasi): analog_engine.py punya
            # dataclass SENDIRI (AnalogResult, field lebih lengkap --
            # ada median_return_pct & analog_dates) terpisah dari
            # ta_engine.py::AnalogInfo (subset field, cuma yang perlu
            # disimpan/ditampilkan). Ini DISENGAJA (hindari ta_engine.py
            # import analog_engine.py -> circular import, lihat docstring
            # analyze_stock parameter analog_info) -- TAPI konsekuensinya
            # konversi WAJIB eksplisit di sini, bukan asal oper objeknya
            # (structural typing Python akan "jalan" tanpa ini karena
            # kebetulan nama field yang dipakai sama, tapi itu rapuh &
            # membingungkan pembaca kode).
            analog_info = AnalogInfo(
                n_analogs=analog_result.n_analogs,
                win_rate=analog_result.win_rate,
                avg_return_pct=analog_result.avg_return_pct,
                reliable=analog_result.reliable,
            )

            sector_bonus = get_sector_bonus(ticker, sector_rankings)
            # Reuse df yg SAMA dgn pass pertama (window scan normal) --
            # cuma analog matching yang butuh histori 3 tahun terpisah,
            # indikator inti tetap konsisten dgn seluruh sistem.
            original_df = stock_data.get(ticker)
            if original_df is None:
                return None
            updated = analyze_stock(
                ticker=ticker,
                df=original_df,
                ihsg_close=ihsg_close,
                regime_weight=regime_weight,
                regime=regime_label,
                sector_bonus=sector_bonus,
                analog_score=analog_score,
                analog_info=analog_info,
            )
            if updated is None:
                return None
            updated = apply_basic_filters(updated)
            return updated, analog_info
        except Exception as e:
            error_count += 1
            if len(error_samples) < 8:
                error_samples.append(f"{ticker}: {type(e).__name__}: {e}")
            return None

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(process_one, a): a.ticker for a in candidates}
        for future in concurrent.futures.as_completed(futures, timeout=600):
            ticker = futures[future]
            try:
                result = future.result()
                if result is not None:
                    updated, analog_info = result
                    by_ticker[ticker] = updated
                    computed_count += 1
                    if analog_info.reliable:
                        reliable_count += 1
            except Exception as e:
                error_count += 1
                log.debug(f"Analog scoring error {ticker}: {e}")

    if error_samples:
        log.warning(f"⚠ {error_count} ticker gagal analog scoring. Contoh: {'; '.join(error_samples)}")

    updated_passed = list(by_ticker.values())
    summary = {
        "candidates": len(candidates),
        "computed": computed_count,
        "reliable": reliable_count,
        "errors": error_count,
    }
    return updated_passed, summary


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
