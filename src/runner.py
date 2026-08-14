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
    """
    Jalankan full daily scan, lalu Automatic Signal Evaluation.

    Evaluator dipanggil DI SINI (lapisan orkestrasi CLI), bukan di
    dalam scanner.py — scanner.py TIDAK diubah sama sekali. Ini
    otomatis berjalan "setelah harga terbaru masuk database" karena
    run_daily_scan() sudah menyelesaikan update harga (step 2) jauh
    sebelum fungsi ini return.
    """
    from src.signals.scanner import run_daily_scan
    log.info("▶ Menjalankan daily scan...")
    result = run_daily_scan(
        top_n=settings.top_n_signals,
        save_to_db=True,
        send_telegram=True,
    )
    summary = result.get("summary", {})
    log.info(f"✓ Daily scan selesai: {summary}")

    # ── Automatic Signal Evaluation (fitur baru, berdiri sendiri) ──
    # Dibungkus try/except terpisah: jika evaluator gagal karena
    # alasan apapun, daily scan & pengiriman Telegram TETAP dianggap
    # sukses (evaluator bukan bagian kritis dari alur sinyal utama).
    try:
        from src.signals.signal_evaluator import run_signal_evaluation
        log.info("▶ Menjalankan Automatic Signal Evaluation...")
        eval_summary = run_signal_evaluation()
        log.info(f"✓ Signal evaluation selesai: {eval_summary}")
    except Exception as e:
        log.error(f"⚠ Signal evaluation gagal (tidak menggagalkan daily scan): {e}")


def cmd_broker_scan(args):
    """
    Ambil broker summary untuk saham yang masuk sinyal STRONG_BUY/BUY/
    WATCHLIST hari ini dan simpan ke tabel broker_summary. Terpisah dari
    cmd_daily_scan supaya bisa dimatikan lewat BROKER_SCAN_ENABLED tanpa
    menyentuh alur utama.

    AUDIT (2026-08, v2.7.1): SEBELUMNYA scan top-N saham paling likuid
    (get_top_liquid_tickers) -- diganti get_signal_tickers_today atas
    permintaan user, supaya broker data fokus ke saham yang benar-benar
    jadi kandidat sinyal (bukan saham likuid generik yang belum tentu
    relevan). Tetap dibatasi broker_scan_top_n sebagai pengaman kuota
    vendor -- kalau jumlah sinyal lebih banyak dari itu, yang raw_score
    tertinggi diprioritaskan (lihat get_signal_tickers_today).
    """
    if not settings.broker_scan_enabled:
        log.info(
            "Broker scan dimatikan (BROKER_SCAN_ENABLED=False). "
            "Set BROKER_DATA_PROVIDER + BROKER_SCAN_ENABLED=True di .env "
            "setelah provider di src/providers/broker_data.py siap."
        )
        return

    from datetime import date as _date
    from src.providers.broker_data import BrokerDataProvider
    from src.core.database import bulk_insert_broker_summary, get_signal_tickers_today

    log.info("▶ Menjalankan broker summary scan...")
    provider = BrokerDataProvider()

    all_signal_tickers = get_signal_tickers_today()
    if not all_signal_tickers:
        log.warning(
            "Tidak ada sinyal STRONG_BUY/BUY/WATCHLIST hari ini (atau "
            "cmd_daily_scan belum jalan). Broker scan dibatalkan."
        )
        return

    tickers = all_signal_tickers[: settings.broker_scan_top_n]
    if len(all_signal_tickers) > len(tickers):
        log.info(
            f"{len(all_signal_tickers)} saham lolos sinyal hari ini, dibatasi ke "
            f"{len(tickers)} (BROKER_SCAN_TOP_N={settings.broker_scan_top_n}, "
            f"raw_score tertinggi diprioritaskan) -- hemat kuota vendor."
        )
    today = _date.today()

    results = provider.fetch_batch(tickers, trade_date=today)

    total_rows = 0
    for ticker, rows in results.items():
        total_rows += bulk_insert_broker_summary(rows, source_provider=provider.provider_name)

    log.info(f"✓ Broker scan selesai: {len(results)}/{len(tickers)} ticker, {total_rows} baris broker_summary")


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


def cmd_evaluate_signals(args):
    """
    Jalankan Automatic Signal Evaluation secara manual/mandiri —
    berguna untuk testing atau backfill, terpisah dari daily_scan.
    """
    from src.signals.signal_evaluator import run_signal_evaluation
    log.info("▶ Menjalankan Automatic Signal Evaluation (manual)...")
    result = run_signal_evaluation()
    log.info(f"✓ Selesai: {result}")


def cmd_backfill_patterns(args):
    """
    Isi trend_structure/pattern_detected untuk signal_results LAMA yang
    dibuat sebelum pattern_engine.py ada (v2.3). Aman dijalankan
    berkali-kali (idempotent) -- baris yang sudah keisi otomatis
    dilewati di run berikutnya. Jalankan SEKALI setelah deploy v2.3 +
    migration 003, baru signal baru akan keisi otomatis dgn sendirinya.
    """
    from src.signals.signal_evaluator import backfill_trend_and_patterns
    log.info("▶ Backfill trend_structure/pattern_detected untuk sinyal lama...")
    result = backfill_trend_and_patterns()
    log.info(f"✓ Selesai: {result}")


def gather_weekly_stats() -> dict:
    """
    Kumpulkan semua data buat WEEKLY REPORT dari database -- dipanggil
    cmd_weekly_report(). Tiap section dibungkus try/except sendiri-sendiri
    supaya 1 sumber data gagal tidak menggagalkan seluruh laporan
    (send_weekly_report() sendiri sudah aman terima field kosong via .get()).
    """
    from datetime import date, timedelta
    from src.core.database import (
        health_check,
        get_universe_weekly_diff,
        get_weekly_scanner_stats,
        get_top_signals_range,
    )
    from src.backtest.engine import get_backtest_results
    from src.signals.regime_engine import get_latest_regime
    from src.signals.sector_engine import get_latest_sector_rankings

    stats: dict = {}

    try:
        stats["universe"] = get_universe_weekly_diff(days=7)
    except Exception as e:
        log.warning(f"gather_weekly_stats: universe gagal: {e}")
        stats["universe"] = {}

    hc = {}
    try:
        hc = health_check()
        stats["database"] = {
            "healthy": hc.get("status") == "healthy",
            "status": hc.get("status", "unknown"),
        }
    except Exception as e:
        log.warning(f"gather_weekly_stats: database health gagal: {e}")
        stats["database"] = {}

    try:
        cutoff = (date.today() - timedelta(days=7)).isoformat()
        bt_recent = [r for r in get_backtest_results(limit=300) if (r.get("run_date") or "") >= cutoff]
        if bt_recent:
            win_rates = [r.get("win_rate") or 0 for r in bt_recent]
            pfs = [r.get("profit_factor") or 0 for r in bt_recent]
            sharpes = [r.get("sharpe_ratio") or 0 for r in bt_recent]
            best = max(bt_recent, key=lambda r: r.get("win_rate") or 0)
            stats["backtest"] = {
                "count": len(bt_recent),
                "avg_win_rate": sum(win_rates) / len(win_rates),
                "avg_profit_factor": sum(pfs) / len(pfs),
                "avg_sharpe": sum(sharpes) / len(sharpes),
                "best_ticker": best.get("ticker"),
                "best_win_rate": best.get("win_rate") or 0,
            }
        else:
            stats["backtest"] = {}
    except Exception as e:
        log.warning(f"gather_weekly_stats: backtest gagal: {e}")
        stats["backtest"] = {}

    try:
        stats["scanner"] = get_weekly_scanner_stats(days=7)
    except Exception as e:
        log.warning(f"gather_weekly_stats: scanner stats gagal: {e}")
        stats["scanner"] = {}

    try:
        from src.telegram.bot import check_telegram_health
        tg_health = check_telegram_health()
        stats["health"] = {
            "database": hc.get("status") == "healthy",
            "telegram": tg_health.get("status") == "healthy",
            "github": True,  # kalau kode ini jalan, berarti dieksekusi oleh GitHub Actions
            "supabase": hc.get("status") == "healthy",
        }
    except Exception as e:
        log.warning(f"gather_weekly_stats: system health gagal: {e}")
        stats["health"] = {}

    try:
        regime = get_latest_regime()
        if regime:
            total = (regime.advance_count or 0) + (regime.decline_count or 0)
            breadth_pct = (regime.advance_count / total * 100) if total else 0
            stats["market"] = {
                "regime": regime.regime,
                "breadth": f"{breadth_pct:.0f}% naik",
                "strength": f"{regime.ihsg_adx:.1f}",
            }
        else:
            stats["market"] = {}
    except Exception as e:
        log.warning(f"gather_weekly_stats: market summary gagal: {e}")
        stats["market"] = {}

    try:
        stats["top_sectors"] = (get_latest_sector_rankings() or [])[:5]
    except Exception as e:
        log.warning(f"gather_weekly_stats: top sectors gagal: {e}")
        stats["top_sectors"] = []

    try:
        stats["top_signals"] = get_top_signals_range(days=7, limit=5)
    except Exception as e:
        log.warning(f"gather_weekly_stats: top signals gagal: {e}")
        stats["top_signals"] = []

    return stats


def cmd_weekly_report(args):
    """
    Kumpulkan statistik seminggu terakhir dari database, kirim WEEKLY
    REPORT ke Telegram.

    AUDIT: versi sebelumnya adalah STUB -- manggil send_daily_summary()
    (format RINGKASAN HARIAN) dengan data palsu semua "N/A", BUKAN
    send_weekly_report() yang sudah ada dan benar formatnya. gather_weekly_stats()
    di atas yang sebelumnya cuma disebut di docstring send_weekly_report()
    tapi tidak pernah benar-benar ditulis. Diperbaiki di v2.3.1.
    """
    from src.telegram.bot import send_weekly_report
    log.info("▶ Mengumpulkan statistik mingguan...")
    stats = gather_weekly_stats()
    log.info(f"▶ Mengirim weekly report... (keys: {list(stats.keys())})")
    ok = send_weekly_report(stats)
    log.info(f"✓ Weekly report {'terkirim' if ok else 'GAGAL terkirim'}")


def main():
    setup_logging(settings.log_level)
    log.info(f"═══ DAILY SIGNAL Runner v2.2 | {datetime.now(WIB).strftime('%Y-%m-%d %H:%M WIB')} ═══")

    parser = argparse.ArgumentParser(description="DAILY SIGNAL Runner")
    parser.add_argument("command", choices=[
        "daily_scan", "pre_market", "health_check",
        "test_telegram",
        "refresh_universe", "run_backtests", "db_cleanup",
        "update_portfolio", "portfolio_snapshot", "weekly_report",
        "evaluate_signals", "backfill_patterns", "broker_scan",
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
        "evaluate_signals":  cmd_evaluate_signals,
        "backfill_patterns": cmd_backfill_patterns,
        "broker_scan":       cmd_broker_scan,
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
