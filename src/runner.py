"""
DAILY SIGNAL — Main Runner v2.2
Entry point untuk GitHub Actions dan CLI.
"""

import sys
import argparse
from datetime import datetime
import pytz

from src.core.logger import setup_logging, get_logger
from src.core.config import settings

WIB = pytz.timezone("Asia/Jakarta")
log = get_logger("runner")


def cmd_test_telegram(args):
    """
    Test kirim pesan sederhana ke Telegram.
    Jalankan ini untuk diagnosa apakah Telegram terkonfigurasi benar.
    """
    import os
    import requests

    log.info("▶ Test Telegram...")
    log.info(f"  TELEGRAM_BOT_TOKEN : {'SET (' + os.environ.get('TELEGRAM_BOT_TOKEN','')[:10] + '...)' if os.environ.get('TELEGRAM_BOT_TOKEN') else 'TIDAK ADA ❌'}")
    log.info(f"  TELEGRAM_CHAT_ID   : {os.environ.get('TELEGRAM_CHAT_ID', 'TIDAK ADA ❌')}")

    token   = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

    if not token:
        log.error("❌ TELEGRAM_BOT_TOKEN kosong! Cek GitHub Secrets.")
        sys.exit(1)
    if not chat_id:
        log.error("❌ TELEGRAM_CHAT_ID kosong! Cek GitHub Secrets.")
        sys.exit(1)

    log.info("  Test 1: Validasi token via getMe...")
    resp = requests.get(f"https://api.telegram.org/bot{token}/getMe", timeout=10)
    if resp.ok:
        bot_name = resp.json().get("result", {}).get("username", "?")
        log.info(f"  ✅ Token valid! Bot: @{bot_name}")
    else:
        log.error(f"  ❌ Token tidak valid: {resp.status_code} {resp.text[:200]}")
        sys.exit(1)

    log.info(f"  Test 2: Kirim pesan ke chat_id={chat_id}...")
    now = datetime.now(WIB).strftime("%d %b %Y %H:%M WIB")
    msg = (
        f"✅ <b>DAILY SIGNAL — Test Berhasil!</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🕐 Waktu: {now}\n"
        f"🤖 Bot terhubung dan siap mengirim sinyal.\n"
        f"<i>Pesan ini dikirim dari GitHub Actions.</i>"
    )
    resp2 = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={"chat_id": chat_id, "text": msg, "parse_mode": "HTML"},
        timeout=15,
    )
    if resp2.ok:
        log.info("  ✅ Pesan berhasil terkirim ke Telegram!")
    else:
        err = resp2.json()
        log.error(f"  ❌ Gagal kirim: {resp2.status_code}")
        log.error(f"  Detail: {err}")
        desc = err.get("description", "")
        if "chat not found" in desc:
            log.error("  → CHAT_ID salah atau bot belum di-add ke grup/channel")
            log.error("  → Pastikan bot sudah jadi member grup, lalu kirim /start ke bot")
        elif "Forbidden" in desc:
            log.error("  → Bot diblokir atau dikeluarkan dari grup")
        elif "Bad Request" in desc:
            log.error("  → Format chat_id salah. Grup harus diawali '-100', channel juga")
        sys.exit(1)


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
    """
    Kirim alert pre-market (08:30 WIB).

    Mengambil regime dari DATABASE (hasil scan kemarin) — bukan hitung
    ulang. Alasan:
      1. Jam 08:30 WIB Yahoo Finance belum update candle hari ini
      2. Data regime terbaru sudah tersimpan di DB dari scan 17:30 kemarin
      3. Konsisten dengan angka yang ditampilkan di daily scan sebelumnya
    """
    from src.signals.regime_engine import get_latest_regime
    from src.telegram.bot import send_market_open_alert

    log.info("▶ Pre-market alert (ambil regime dari DB)...")

    regime = get_latest_regime()

    if regime:
        send_market_open_alert(regime)
        log.info(f"✓ Pre-market alert dikirim. Regime: {regime.regime} | RSI: {regime.ihsg_rsi:.1f}")
    else:
        log.warning("Tidak ada data regime di database — scan pertama belum berjalan")


def cmd_health_check(args):
    """Health check semua komponen."""
    from src.signals.scanner import run_health_check
    from src.telegram.bot import send_health_alert, check_telegram_health
    from src.core.database import health_check as db_health, ensure_tables_exist

    log.info("▶ Health check...")

    db_status = db_health()
    log.info(f"  database: {db_status}")
    if db_status["status"] != "healthy":
        log.error(f"❌ Database tidak bisa diakses: {db_status.get('error','')}")
        sys.exit(1)

    tables_ok = ensure_tables_exist()
    if not tables_ok:
        log.error("❌ Tabel tidak lengkap — jalankan migrations/001_initial_schema.sql")
        sys.exit(1)

    tg = check_telegram_health()
    log.info(f"  telegram: {tg}")
    if tg["status"] != "healthy":
        log.warning(f"⚠ Telegram: {tg.get('error','unknown')}")

    from src.providers.market_data import MarketDataProvider
    try:
        provider = MarketDataProvider()
        for test_ticker in ["BBCA.JK", "TLKM.JK"]:
            df = provider.fetch_ohlcv(test_ticker, period="5d")
            if df is not None and len(df) > 0:
                log.info(f"  data_provider: healthy ({test_ticker}, {len(df)} rows)")
                break
        else:
            log.warning("⚠ Data provider: tidak bisa ambil data")
    except Exception as e:
        log.warning(f"⚠ Data provider: {e}")

    log.info("✓ Health check selesai")


def cmd_refresh_universe(args):
    from src.providers.universe_manager import refresh_universe
    log.info("▶ Refresh universe...")
    result = refresh_universe()
    log.info(f"✓ +{result['added']} baru, -{result['removed']} delisting, total {result['total']}")


def cmd_run_backtests(args):
    from src.providers.universe_manager import get_all_bei_tickers
    from src.providers.market_data import get_ohlcv_from_db
    from src.backtest.engine import run_backtest, save_backtest_result
    import concurrent.futures

    limit = getattr(args, "limit", 50)
    log.info(f"▶ Backtest {limit} saham...")
    tickers = get_all_bei_tickers()[:limit]
    passed = 0

    # AUDIT FIX: sertakan data IHSG agar backtest bisa menghitung
    # Relative Strength sungguhan (dimensi "strength" di composite
    # score), bukan selalu netral/0 seperti sebelumnya.
    ihsg_df = get_ohlcv_from_db(settings.ihsg_ticker, days=365 * 3)
    ihsg_close = ihsg_df["close"] if ihsg_df is not None and not ihsg_df.empty else None
    if ihsg_close is None:
        log.warning("Data IHSG tidak tersedia di DB — backtest jalan tanpa dimensi Relative Strength")

    def bt_one(ticker):
        df = get_ohlcv_from_db(ticker, days=365*3)
        if df is None or len(df) < 100:
            return None
        r = run_backtest(ticker, df, ihsg_close=ihsg_close)
        save_backtest_result(r)
        return r

    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as ex:
        for future in concurrent.futures.as_completed(
            {ex.submit(bt_one, t): t for t in tickers}, timeout=1200
        ):
            try:
                r = future.result()
                if r and r.passed:
                    passed += 1
            except Exception:
                pass

    log.info(f"✓ Backtest selesai: {passed} passed")


def cmd_db_cleanup(args):
    from src.core.database import get_db
    from datetime import date, timedelta
    try:
        db = get_db()
        cutoff = (date.today() - timedelta(days=30)).isoformat()
        db.table("system_logs").delete().lt("log_time", cutoff).execute()
        log.info("✓ DB cleanup selesai")
    except Exception as e:
        log.error(f"DB cleanup gagal: {e}")


def cmd_update_portfolio(args):
    from src.portfolio.tracker import update_open_positions_prices
    log.info("▶ Update portfolio...")
    n = update_open_positions_prices()
    log.info(f"✓ {n} posisi diupdate")


def cmd_portfolio_snapshot(args):
    from src.portfolio.tracker import save_portfolio_snapshot
    log.info("▶ Portfolio snapshot...")
    save_portfolio_snapshot()
    log.info("✓ Snapshot tersimpan")


def cmd_weekly_report(args):
    from src.telegram.bot import send_daily_summary
    log.info("▶ Weekly report...")
    send_daily_summary({"stocks_scanned":"N/A","strong_buy":"N/A",
                        "buy":"N/A","watchlist":"N/A","regime":"N/A","duration_seconds":0})
    log.info("✓ Report dikirim")


def main():
    setup_logging(settings.log_level)
    log.info(f"═══ DAILY SIGNAL Runner v2.2 | {datetime.now(WIB).strftime('%Y-%m-%d %H:%M WIB')} ═══")

    parser = argparse.ArgumentParser(description="DAILY SIGNAL Runner")
    parser.add_argument("command", choices=[
        "daily_scan", "pre_market", "health_check",
        "test_telegram",
        "refresh_universe", "run_backtests", "db_cleanup",
        "update_portfolio", "portfolio_snapshot", "weekly_report",
    ])
    parser.add_argument("--limit", type=int, default=50)

    args = parser.parse_args()

    cmd_map = {
        "daily_scan":        cmd_daily_scan,
        "pre_market":        cmd_pre_market,
        "health_check":      cmd_health_check,
        "test_telegram":     cmd_test_telegram,
        "refresh_universe":  cmd_refresh_universe,
        "run_backtests":     cmd_run_backtests,
        "db_cleanup":        cmd_db_cleanup,
        "update_portfolio":  cmd_update_portfolio,
        "portfolio_snapshot":cmd_portfolio_snapshot,
        "weekly_report":     cmd_weekly_report,
    }

    try:
        cmd_map[args.command](args)
    except SystemExit:
        raise
    except Exception as e:
        log.critical(f"Command '{args.command}' gagal: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
