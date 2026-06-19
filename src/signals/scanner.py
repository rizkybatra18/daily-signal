"""
DAILY SIGNAL — Signal Scanner (Main Orchestrator)
Menyatukan semua komponen menjadi daily scan pipeline.

Pipeline:
    1. Universe Manager → daftar semua saham BEI
    2. Incremental Data Update → update database harga
    3. Regime Detection → kondisi pasar saat ini
    4. Sector Rotation → ranking sektor
    5. TA Engine → analisis teknikal per saham (parallel)
    6. Scoring → composite score 0-100 + signal type
    7. Filter → buang yang tidak layak
    8. Output → simpan ke database + kirim Telegram
"""

import concurrent.futures
import time
import uuid
from datetime import date, datetime
from typing import Optional

import pandas as pd

from src.core.config import settings
from src.core.logger import get_logger
from src.core.database import save_signal, log_scan_run, update_scan_run, get_db
from src.providers.universe_manager import get_all_bei_tickers, get_tickers_by_sector
from src.providers.market_data import MarketDataProvider, IncrementalDataUpdater, get_ohlcv_from_db
from src.signals.ta_engine import analyze_stock, apply_basic_filters, StockAnalysis
from src.signals.regime_engine import detect_market_regime, MarketRegime
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
            "summary": dict,
            "duration_seconds": float,
        }
    """
    run_id = str(uuid.uuid4())
    start_time = time.time()
    top_n = top_n or settings.top_n_signals
    
    log.info(f"═══ DAILY SIGNAL SCAN DIMULAI [run_id={run_id[:8]}] ═══")
    
    # Log scan run ke database
    log_scan_run({
        "run_id": run_id,
        "run_type": "DAILY_SCAN",
        "started_at": datetime.utcnow().isoformat(),
        "status": "RUNNING",
    })
    
    try:
        # ── Step 1: Dapatkan Universe ──────────────────────────────
        log.info("[1/7] Mengambil universe saham BEI...")
        all_tickers = get_all_bei_tickers()
        log.info(f"     → {len(all_tickers)} ticker di universe")
        
        # ── Step 2: Update Data Incremental ───────────────────────
        log.info("[2/7] Update data harga (incremental)...")
        updater = IncrementalDataUpdater()
        update_summary = updater.update_batch(all_tickers, max_workers=5)
        log.info(f"     → {update_summary['updated']} diupdate, +{update_summary['rows_added']} rows")
        
        # ── Step 3: Download IHSG ──────────────────────────────────
        log.info("[3/7] Mengambil data IHSG untuk regime detection...")
        provider = MarketDataProvider()
        ihsg_df = provider.fetch_ohlcv(settings.ihsg_ticker, period="60d")
        
        # ── Step 4: Deteksi Market Regime ──────────────────────────
        log.info("[4/7] Deteksi market regime...")
        regime = detect_market_regime(ihsg_df)
        log.info(f"     → Regime: {regime.regime} (weight={regime.regime_weight}) | {regime.regime_reason[:60]}")
        
        if regime.regime == "BEAR":
            log.warning("Market BEAR — scan tetap dijalankan tapi sinyal akan di-suppress")
        
        # ── Step 5: Load Data dari Database untuk Analisis ─────────
        log.info("[5/7] Load data OHLCV dari database...")
        ihsg_close = ihsg_df["close"] if ihsg_df is not None else None
        
        # Parallel load OHLCV dari database
        stock_data = _load_batch_from_db(all_tickers, days=settings.history_days_scan)
        log.info(f"     → {len(stock_data)} saham berhasil di-load")
        
        # ── Step 6: Sector Rotation ────────────────────────────────
        log.info("[6/7] Menghitung sector rotation...")
        sector_rankings = calculate_sector_rankings(stock_data)
        top_sectors = [f"#{sr.rank} {sr.sector}" for sr in sector_rankings[:3]]
        log.info(f"     → Top 3 sektor: {', '.join(top_sectors)}")
        
        # ── Step 7: Analisis TA per Saham (Parallel) ──────────────
        log.info(f"[7/7] Analisis teknikal {len(stock_data)} saham (parallel)...")
        analyses = _analyze_all_parallel(
            stock_data=stock_data,
            ihsg_close=ihsg_close,
            regime_weight=regime.regime_weight,
            sector_rankings=sector_rankings,
        )
        
        # ── Filter dan Sort ────────────────────────────────────────
        # Buang yang tidak lolos filter
        passed = [a for a in analyses if a.passed_basic_filter]
        
        # Sort by final score DESC
        passed.sort(key=lambda a: a.score.final_score, reverse=True)
        
        # Ambil sinyal yang actionable
        strong_buy = [a for a in passed if a.score.signal_type == "STRONG_BUY"]
        buy = [a for a in passed if a.score.signal_type == "BUY"]
        watchlist = [a for a in passed if a.score.signal_type == "WATCHLIST"]
        
        # Top signals untuk Telegram (prioritas STRONG_BUY dulu)
        top_signals = (strong_buy + buy)[:top_n]
        
        # ── Simpan ke Database ─────────────────────────────────────
        signal_ids = []
        if save_to_db:
            log.info(f"Menyimpan {len(passed)} sinyal ke database...")
            for analysis in passed:
                signal_data = {
                    "signal_date": date.today().isoformat(),
                    **analysis.to_dict(),
                }
                signal_id = save_signal(signal_data)
                if signal_id:
                    signal_ids.append(signal_id)
            log.info(f"✓ {len(signal_ids)} sinyal tersimpan")
        
        # ── Kirim ke Telegram ─────────────────────────────────────
        if send_telegram and top_signals:
            from src.telegram.bot import send_daily_signals
            _send_signals_telegram(top_signals, regime, sector_rankings)
        
        # ── Finish ────────────────────────────────────────────────
        duration = time.time() - start_time
        
        summary = {
            "stocks_scanned": len(analyses),
            "passed_filter": len(passed),
            "strong_buy": len(strong_buy),
            "buy": len(buy),
            "watchlist": len(watchlist),
            "avoid": len([a for a in passed if a.score.signal_type == "AVOID"]),
            "signals_saved": len(signal_ids),
            "regime": regime.regime,
            "duration_seconds": round(duration, 1),
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


def _load_batch_from_db(
    tickers: list[str],
    days: int = 60,
    max_workers: int = 10,
) -> dict[str, pd.DataFrame]:
    """Load OHLCV data dari database secara parallel."""
    results = {}
    
    def load_one(ticker):
        df = get_ohlcv_from_db(ticker, days=days + 50)  # +50 untuk warmup indikator
        return ticker, df
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(load_one, t): t for t in tickers}
        
        for future in concurrent.futures.as_completed(futures, timeout=120):
            try:
                ticker, df = future.result()
                if df is not None and not df.empty:
                    results[ticker] = df
            except Exception as e:
                log.debug(f"Load DB gagal untuk {futures[future]}: {e}")
    
    return results


def _analyze_all_parallel(
    stock_data: dict[str, pd.DataFrame],
    ihsg_close: Optional[pd.Series],
    regime_weight: float,
    sector_rankings: list,
    max_workers: int = 8,
) -> list[StockAnalysis]:
    """Analisis semua saham secara parallel."""
    results = []
    total = len(stock_data)
    completed = 0
    
    def analyze_one(ticker_df_pair):
        ticker, df = ticker_df_pair
        try:
            analysis = analyze_stock(
                ticker=ticker,
                df=df,
                ihsg_close=ihsg_close,
                regime_weight=regime_weight,
            )
            if analysis is None:
                return None
            
            # Apply basic filters
            analysis = apply_basic_filters(analysis)
            
            # Apply sector bonus
            bonus = get_sector_bonus(ticker, sector_rankings)
            if bonus != 0 and analysis.passed_basic_filter:
                # Adjust final score dengan sector bonus
                analysis.score.final_score = max(
                    0,
                    min(100, analysis.score.final_score + bonus)
                )
                # Re-determine signal type
                from src.signals.ta_engine import _determine_signal_type
                analysis.score.signal_type = _determine_signal_type(
                    analysis.score.final_score,
                    1.0,  # Already adjusted
                    analysis,
                )
            
            return analysis
        except Exception as e:
            log.debug(f"Analisis gagal {ticker}: {e}")
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
    
    # Database
    results["database"] = db_health()
    
    # Telegram
    try:
        from src.telegram.bot import check_telegram_health
        results["telegram"] = check_telegram_health()
    except Exception as e:
        results["telegram"] = {"status": "error", "error": str(e)}
    
    # Data Provider
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
