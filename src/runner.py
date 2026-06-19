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
        regime = detect_market_regime(ihsg_df)
    except Exception:
        regime = get_latest_regime()

    if regime:
        send_market_open_alert(regime)
        log.info(f"✓ Pre-market alert dikirim. Regime: {regime.regime}")
    else:
        log.warning("Tidak bisa ambil regime data untuk pre-market alert")


def cmd_health_check(args):
    """Jalankan health check semua komponen."""
    from src.signals.scanner import run_health_check
    from src.telegram.bot import send_health_alert

    log.info("▶ Health check...")
    health = run_health_check()

    overall = health.get("overall", "unknown")
    log.info(f"Health check result: {overall}")
    for component, status in health.items():
        if component != "overall":
            log.info(f"  {component}: {status}")

    if overall != "healthy":
        send_health_alert(health)
        log.warning(f"⚠ Health check DEGRADED — alert dikirim ke Telegram")
        sys.exit(1)

    log.info("✓ Semua komponen sehat")


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
        result = db.rpc("delete_old_logs", {"days_old": 30}).execute()
        log.info("✓ Log lama dihapus")

        # Hapus daily_prices lebih dari 2 tahun untuk saham tidak aktif
        log.info("✓ Database cleanup selesai")

    except Exception as e:
        log.error(f"DB cleanup gagal: {e}", exc=e)
        # Jangan exit 1 — cleanup failure tidak boleh gagalkan workflow


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
            "total_trades": stats.total_trades,
            "win_rate": f"{stats.win_rate:.1%}",
            "realized_pnl": f"Rp{stats.total_realized_pnl:,.0f}",
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
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Perintah tersedia:
  daily_scan         Jalankan full daily scan + kirim ke Telegram
  pre_market         Kirim alert pre-market (08:30 WIB)
  health_check       Cek status semua komponen
  refresh_universe   Update daftar saham BEI (IPO/delisting)
  run_backtests      Jalankan backtest
  db_cleanup         Bersihkan data lama
  update_portfolio   Update harga posisi aktif
  portfolio_snapshot Simpan snapshot portfolio
  weekly_report      Kirim weekly performance report
""",
    )

    parser.add_argument(
        "command",
        choices=[
            "daily_scan",
            "pre_market",
            "health_check",
            "refresh_universe",
            "run_backtests",
            "db_cleanup",
            "update_portfolio",
            "portfolio_snapshot",
            "weekly_report",
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
        except Exception as e:
            log.critical(f"Command '{args.command}' gagal: {e}", exc=e)
            sys.exit(1)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
