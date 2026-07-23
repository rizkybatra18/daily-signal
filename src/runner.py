"""
DAILY SIGNAL — Main Runner v3.0
Entry point untuk GitHub Actions dan CLI.
"""

import sys
import argparse
from datetime import datetime, date, timedelta
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
    ulang. Lihat catatan lengkap di send_market_open_alert (bot.py).
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
    try:
        db = get_db()
        cutoff = (date.today() - timedelta(days=30)).isoformat()
        result = db.table("system_logs").delete().lt("log_time", cutoff).execute()
        deleted = len(result.data) if result.data else 0
        log.info(f"✓ DB cleanup selesai ({deleted} log lama dihapus)")
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


# ══════════════════════════════════════════════════════════════════
#  WEEKLY REPORT — pengumpulan statistik NYATA dari database
# ══════════════════════════════════════════════════════════════════

def gather_weekly_stats() -> dict:
    """
    Kumpulkan statistik 7 hari terakhir untuk Weekly Report.
    Murni QUERY (baca) ke tabel yang sudah ada — tidak ada perubahan
    skema/engine/scoring. Setiap bagian dibungkus try/except sendiri
    agar satu sumber data gagal tidak menggagalkan seluruh laporan
    (laporan tetap terkirim dengan bagian yang tersedia).
    """
    import re as _re
    from src.core.database import get_db
    from src.signals.regime_engine import get_latest_regime
    from src.telegram.bot import check_telegram_health

    since = (date.today() - timedelta(days=7)).isoformat()
    stats: dict = {}

    # ── Universe ─────────────────────────────────────────────────
    try:
        db = get_db()
        total = db.table("stocks").select("ticker", count="exact") \
                  .eq("is_active", True).eq("is_delisted", False).limit(1).execute()
        total_count = total.count or 0

        # Parse ringkasan terakhir dari log refresh_universe (sudah
        # dicatat log.info di universe_manager.py — bukan tabel baru,
        # murni membaca log yang memang sudah ada).
        added, removed = "N/A", "N/A"
        logs = db.table("system_logs").select("message") \
                 .order("log_time", desc=True).limit(200).execute()
        for row in (logs.data or []):
            msg = row.get("message", "")
            if "Universe refresh selesai" in msg:
                m_add = _re.search(r"\+(\d+) baru", msg)
                m_rem = _re.search(r"-(\d+) delisting", msg)
                if m_add: added = int(m_add.group(1))
                if m_rem: removed = int(m_rem.group(1))
                break

        stats["universe"] = {"total": total_count, "added": added, "removed": removed}
    except Exception as e:
        log.warning(f"gather_weekly_stats: universe gagal — {e}")
        stats["universe"] = {}

    # ── Database ─────────────────────────────────────────────────
    try:
        from src.core.database import health_check as db_health
        h = db_health()
        stats["database"] = {
            "healthy": h.get("status") == "healthy",
            "status": h.get("status", "unknown"),
            "cleanup_note": "Log > 30 hari dibersihkan otomatis",
        }
    except Exception as e:
        log.warning(f"gather_weekly_stats: database gagal — {e}")
        stats["database"] = {}

    # ── Backtest (7 hari terakhir) ───────────────────────────────
    try:
        db = get_db()
        bt = db.table("backtest_results").select("*") \
               .gte("run_date", since).execute()
        rows = bt.data or []
        if rows:
            win_rates = [float(r.get("win_rate") or 0) for r in rows]
            pfs       = [float(r.get("profit_factor") or 0) for r in rows]
            sharpes   = [float(r.get("sharpe_ratio") or 0) for r in rows]
            best = max(rows, key=lambda r: float(r.get("win_rate") or 0))
            stats["backtest"] = {
                "count": len(rows),
                "avg_win_rate": sum(win_rates)/len(win_rates),
                "avg_profit_factor": sum(pfs)/len(pfs),
                "avg_sharpe": sum(sharpes)/len(sharpes),
                "best_ticker": str(best.get("ticker","")).replace(".JK",""),
                "best_win_rate": float(best.get("win_rate") or 0),
            }
        else:
            stats["backtest"] = {"count": 0}
    except Exception as e:
        log.warning(f"gather_weekly_stats: backtest gagal — {e}")
        stats["backtest"] = {"count": 0}

    # ── Scanner statistics (7 hari terakhir) ─────────────────────
    try:
        db = get_db()
        runs = db.table("scan_runs").select("*") \
                 .eq("run_type", "DAILY_SCAN").gte("started_at", since).execute()
        sigs = db.table("signals").select("signal_type") \
                 .gte("signal_date", since).execute()
        sig_rows = sigs.data or []
        stats["scanner"] = {
            "total_runs": len(runs.data or []),
            "strong_buy": sum(1 for s in sig_rows if s.get("signal_type") == "STRONG_BUY"),
            "buy": sum(1 for s in sig_rows if s.get("signal_type") == "BUY"),
            "watchlist": sum(1 for s in sig_rows if s.get("signal_type") == "WATCHLIST"),
        }
    except Exception as e:
        log.warning(f"gather_weekly_stats: scanner gagal — {e}")
        stats["scanner"] = {}

    # ── System Health ────────────────────────────────────────────
    try:
        tg = check_telegram_health()
        stats["health"] = {
            "database": stats.get("database", {}).get("healthy", False),
            "telegram": tg.get("status") == "healthy",
            "github": True,   # Jika script ini berjalan, GitHub Actions sukses trigger
            "supabase": stats.get("database", {}).get("healthy", False),
        }
    except Exception as e:
        log.warning(f"gather_weekly_stats: health gagal — {e}")
        stats["health"] = {}

    # ── Market Summary ───────────────────────────────────────────
    try:
        regime = get_latest_regime()
        if regime:
            stats["market"] = {
                "regime": regime.regime,
                "breadth": f"{regime.breadth_score:.0f}% naik",
                "strength": f"{regime.ihsg_adx:.1f}",
            }
        else:
            stats["market"] = {}
    except Exception as e:
        log.warning(f"gather_weekly_stats: market gagal — {e}")
        stats["market"] = {}

    # ── Top 5 Sektor ─────────────────────────────────────────────
    try:
        db = get_db()
        sec = db.table("sector_rankings").select("*") \
                .order("rank_date", desc=True).order("rank_position").limit(5).execute()
        stats["top_sectors"] = sec.data or []
    except Exception as e:
        log.warning(f"gather_weekly_stats: sectors gagal — {e}")
        stats["top_sectors"] = []

    # ── Top 5 Sinyal Minggu Ini ──────────────────────────────────
    try:
        db = get_db()
        top = db.table("signals").select("ticker,signal_type,composite_score") \
                .gte("signal_date", since).order("composite_score", desc=True).limit(5).execute()
        stats["top_signals"] = top.data or []
    except Exception as e:
        log.warning(f"gather_weekly_stats: top_signals gagal — {e}")
        stats["top_signals"] = []

    return stats


def cmd_weekly_report(args):
    """Kumpulkan statistik 7 hari terakhir & kirim Weekly Report premium."""
    from src.telegram.bot import send_weekly_report
    log.info("▶ Mengumpulkan statistik mingguan...")
    stats = gather_weekly_stats()
    log.info("▶ Mengirim weekly report...")
    ok = send_weekly_report(stats)
    log.info("✓ Report dikirim" if ok else "✗ Gagal kirim report")


def main():
    setup_logging(settings.log_level)
    log.info(f"═══ DAILY SIGNAL Runner v3.0 | {datetime.now(WIB).strftime('%Y-%m-%d %H:%M WIB')} ═══")

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
