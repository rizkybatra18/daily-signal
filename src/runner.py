"""
DAILY SIGNAL — Main Runner
Entry point untuk GitHub Actions dan CLI.

Penggunaan:
    python -m src.runner daily_scan
    python -m src.runner pre_market
    python -m src.runner health_check
    python -m src.runner refresh_universe
    python -m src.runner run_backtests --limit 50
    python -m src.runner db_cleanup
    python -m src.runner update_portfolio
    python -m src.runner portfolio_snapshot
    python -m src.runner weekly_report
"""

import sys
import argparse
from datetime import datetime
import pytz

from src.core.logger import setup_logging, get_logger
from src.core.config import settings

WIB = pytz.timezone("Asia/Jakarta")
log = get_logger("runner")


def cmd_health_check(args):
    """
    Jalankan health check semua komponen.
    
    Perilaku:
    - WARNING level issues: log saja, TIDAK exit(1)
    - CRITICAL issues (database down): exit(1) untuk hentikan workflow
    - Telegram unhealthy: warning saja (workflow tetap lanjut)
    - Data provider unhealthy: warning saja (mungkin rate limit sementara)
    """
    from src.signals.scanner import run_health_check
    from src.telegram.bot import send_health_alert, check_telegram_health

    log.info("▶ Health check...")

    # ── 1. Database Check ──────────────────────────────────────────
    from src.core.database import health_check as db_health, ensure_tables_exist
    db_status = db_health()
    log.info(f"  database: {db_status}")

    if db_status["status"] != "healthy":
        err = db_status.get("error", "")
        log.error(
            f"❌ DATABASE TIDAK BISA DIAKSES!\n"
            f"   Error: {err}\n"
            f"   Solusi: Pastikan SUPABASE_URL dan SUPABASE_SERVICE_KEY benar di GitHub Secrets.\n"
            f"   Jika baru setup: jalankan migrations/001_initial_schema.sql di Supabase SQL Editor."
        )
        # Cek apakah ini masalah migration atau credentials
        if "migration" in err.lower() or "PGRST125" in str(db_status):
            log.error("   → Sepertinya migration SQL belum dijalankan!")
        sys.exit(1)  # Database HARUS sehat untuk lanjut

    # Cek tabel ada
    tables_ok = ensure_tables_exist()
    if not tables_ok:
        log.error(
            "❌ Tabel database tidak lengkap!\n"
            "   Jalankan migrations/001_initial_schema.sql di Supabase SQL Editor."
        )
        sys.exit(1)

    # ── 2. Telegram Check ─────────────────────────────────────────
    tg_status = check_telegram_health()
    log.info(f"  telegram: {tg_status}")
    if tg_status["status"] != "healthy":
        log.warning(
            f"⚠ Telegram tidak sehat: {tg_status.get('error', 'unknown')}\n"
            f"  → Cek TELEGRAM_BOT_TOKEN di GitHub Secrets.\n"
            f"  → Workflow tetap lanjut tapi sinyal tidak akan terkirim."
        )
        # TIDAK exit(1) — scan tetap berjalan meski Telegram bermasalah

    # ── 3. Data Provider Check ────────────────────────────────────
    from src.providers.market_data import MarketDataProvider
    try:
        provider = MarketDataProvider()
        # Coba beberapa ticker sekaligus — jika satu gagal, coba yang lain
        test_tickers = ["BBCA.JK", "TLKM.JK", "ASII.JK"]
        provider_ok = False
        for test_ticker in test_tickers:
            df = provider.fetch_ohlcv(test_ticker, period="5d")
            if df is not None and len(df) > 0:
                log.info(f"  data_provider: healthy (test={test_ticker}, rows={len(df)})")
                provider_ok = True
                break

        if not provider_ok:
            log.warning(
                "⚠ Yahoo Finance tidak bisa mengambil data saat ini.\n"
                "  → Mungkin rate limit sementara atau Yahoo Finance down.\n"
                "  → Workflow tetap lanjut — data akan di-fetch ulang saat scan."
            )
    except Exception as e:
        log.warning(f"⚠ Data provider check gagal: {e} — scan tetap dilanjutkan.")

    log.info("✓ Health check selesai — database OK, melanjutkan workflow.")


def cmd_daily_scan(args):
    """Jalankan full daily scan."""
    from src.signals.scanner import run_daily_scan
    log.info("▶ Menjalankan daily scan...")
    result = run_daily_scan(
        top_n=settings.top_n_signals,
        save_to_db=True,
        send_telegram=True,
    )
    summary = result.get("summary", {})
    log.info(f"✓ Daily scan selesai: {summary}")


def cmd_pre_market(args):
    """Kirim alert pre-market (08:30 WIB)."""
    from src.signals.regime_engine import detect_market_regime, get_latest_regime
    from src.telegram.bot import send_market_open_alert
    from src.providers.market_data import MarketDataProvider

    log.info("▶ Pre-market alert...")

    try:
        provider = MarketDataProvider()
        ihsg_df = provider.fetch_ohlcv(settings.ihsg_ticker, period="30d")
        if ihsg_df is not None and not ihsg_df.empty:
            regime = detect_market_regime(ihsg_df)
        else:
            log.warning("Tidak bisa ambil data IHSG, gunakan regime terakhir dari DB")
            regime = get_latest_regime()
    except Exception as e:
        log.warning(f"Regime detection gagal: {e}, gunakan DB")
        regime = get_latest_regime()

    if regime:
        send_market_open_alert(regime)
        log.info(f"✓ Pre-market alert dikirim. Regime: {regime.regime}")
    else:
        log.warning("Tidak ada data regime — pre-market alert dilewati")


def cmd_refresh_universe(args):
    """Refresh daftar saham BEI."""
    from src.providers.universe_manager import refresh_universe

    log.info("▶ Refresh universe saham BEI...")
    result = refresh_universe()
    log.info(
        f"✓ Universe refresh: +{result['added']} baru, "
        f"-{result['removed']} delisting, total {result['total']}"
    )

    if result["added"] > 0 or result["removed"] > 0:
        from src.telegram.bot import _send_message
        msg = (
            f"🔄 <b>Universe Update</b>\n"
            f"✅ +{result['added']} saham baru (IPO)\n"
            f"❌ -{result['removed']} saham delisting\n"
            f"📊 Total: {result['total']} saham aktif"
        )
        _send_message(msg)


def cmd_run_backtests(args):
    """Jalankan backtest untuk saham-saham teratas."""
    from src.providers.universe_manager import get_all_bei_tickers
    from src.providers.market_data import get_ohlcv_from_db
    from src.backtest.engine import run_backtest, save_backtest_result
    import concurrent.futures

    limit = getattr(args, "limit", 50)
    log.info(f"▶ Menjalankan backtest untuk {limit} saham...")

    tickers = get_all_bei_tickers()[:limit]
    passed = 0
    failed = 0

    def backtest_one(ticker):
        df = get_ohlcv_from_db(ticker, days=365 * 3)
        if df is None or len(df) < 100:
            return None
        result = run_backtest(ticker, df)
        save_backtest_result(result)
        return result

    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        futures = {executor.submit(backtest_one, t): t for t in tickers}
        for future in concurrent.futures.as_completed(futures, timeout=1200):
            try:
                result = future.result()
                if result:
                    if result.passed:
                        passed += 1
                    else:
                        failed += 1
            except Exception as e:
                log.warning(f"Backtest error: {e}")

    log.info(f"✓ Backtest selesai: {passed} passed, {failed} failed dari {len(tickers)} saham")


def cmd_db_cleanup(args):
    """Bersihkan data lama dari database."""
    try:
        from src.core.database import get_db
        db = get_db()
        log.info("▶ Database cleanup...")
        # Hapus system_logs lebih dari 30 hari
        from datetime import date, timedelta
        cutoff = (date.today() - timedelta(days=30)).isoformat()
        db.table("system_logs").delete().lt("log_time", cutoff).execute()
        log.info("✓ Database cleanup selesai")
    except Exception as e:
        log.error(f"DB cleanup gagal: {e}", exc=e)


def cmd_update_portfolio(args):
    """Update harga posisi aktif."""
    from src.portfolio.tracker import update_open_positions_prices
    log.info("▶ Update harga posisi aktif...")
    updated = update_open_positions_prices()
    log.info(f"✓ {updated} posisi diupdate")


def cmd_portfolio_snapshot(args):
    """Simpan snapshot portfolio harian."""
    from src.portfolio.tracker import save_portfolio_snapshot
    log.info("▶ Menyimpan portfolio snapshot...")
    save_portfolio_snapshot()
    log.info("✓ Portfolio snapshot tersimpan")


def cmd_weekly_report(args):
    """Kirim weekly performance report."""
    from src.portfolio.tracker import get_portfolio_stats
    from src.telegram.bot import send_daily_summary

    log.info("▶ Membuat weekly report...")
    try:
        stats = get_portfolio_stats()
        summary = {
            "stocks_scanned": "N/A",
            "strong_buy": "N/A",
            "buy": "N/A",
            "watchlist": "N/A",
            "regime": "N/A",
            "duration_seconds": 0,
        }
        send_daily_summary(summary)
        log.info("✓ Weekly report dikirim")
    except Exception as e:
        log.error(f"Weekly report gagal: {e}", exc=e)


def main():
    setup_logging(settings.log_level)

    log.info(f"═══ DAILY SIGNAL Runner v1.0 | {datetime.now(WIB).strftime('%Y-%m-%d %H:%M WIB')} ═══")

    parser = argparse.ArgumentParser(
        description="DAILY SIGNAL — BEI Stock Scanner Runner",
    )
    parser.add_argument(
        "command",
        choices=[
            "daily_scan", "pre_market", "health_check",
            "refresh_universe", "run_backtests", "db_cleanup",
            "update_portfolio", "portfolio_snapshot", "weekly_report",
        ],
    )
    parser.add_argument("--limit", type=int, default=50, help="Limit untuk backtest")
    parser.add_argument("--no-telegram", action="store_true", help="Skip Telegram notification")

    args = parser.parse_args()

    command_map = {
        "daily_scan": cmd_daily_scan,
        "pre_market": cmd_pre_market,
        "health_check": cmd_health_check,
        "refresh_universe": cmd_refresh_universe,
        "run_backtests": cmd_run_backtests,
        "db_cleanup": cmd_db_cleanup,
        "update_portfolio": cmd_update_portfolio,
        "portfolio_snapshot": cmd_portfolio_snapshot,
        "weekly_report": cmd_weekly_report,
    }

    cmd_fn = command_map.get(args.command)
    if cmd_fn:
        try:
            cmd_fn(args)
        except SystemExit:
            raise  # Biarkan sys.exit() propagate
        except Exception as e:
            log.critical(f"Command '{args.command}' gagal: {e}", exc=e)
            sys.exit(1)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
