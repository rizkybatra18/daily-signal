"""
DAILY SIGNAL — Automatic Signal Evaluation Engine
Engine BERDIRI SENDIRI, terpisah dari scanner.py — lihat AUDIT NOTE.

═══════════════════════════════════════════════════════════════════
ALUR (tidak menyentuh scanner.py / Telegram / workflow sama sekali):
═══════════════════════════════════════════════════════════════════

    Daily Scan (scanner.py, TIDAK diubah)
        ↓  menyimpan ke tabel `signals` (sudah ada, TIDAK diubah)
    cmd_daily_scan() di runner.py memanggil run_signal_evaluation()
    SETELAH run_daily_scan() selesai — lihat runner.py.
        ↓
    [1] capture_todays_signals()
        Ambil sinyal STRONG_BUY/BUY/WATCHLIST hari ini dari `signals`,
        lengkapi dengan indikator turunan (SMA/DI+-/Bollinger/RSI slope)
        yang dihitung di sini (reuse fungsi murni ta_engine.py, TIDAK
        mengubah ta_engine.py), simpan sebagai baris baru status OPEN
        di `signal_results` (idempotent — upsert).
        ↓
    [2] evaluate_open_signals()
        Untuk SEMUA baris status OPEN (termasuk dari hari-hari
        sebelumnya), cek harga sejak hari SETELAH sinyal terbit:
        apakah SL/TP1/TP2 tersentuh, atau sudah melewati batas hari
        (EXPIRED). Update status + hasil.

═══════════════════════════════════════════════════════════════════
ATURAN EVALUASI (konservatif, konsisten dengan backtest engine —
lihat src/backtest/engine.py yang sudah memakai konvensi yang sama):
═══════════════════════════════════════════════════════════════════

  1. ENTRY REALISTIS: evaluasi baru mulai dihitung dari hari
     PERDAGANGAN BERIKUTNYA setelah signal_date, bukan hari yang
     sama (sinyal baru diketahui setelah market tutup).
  2. SATU CANDLE, SL & TP SAMA-SAMA TERSENTUH: SL diprioritaskan
     lebih dulu (asumsi terburuk/konservatif). Urutan pengecekan
     per hari: SL -> TP2 -> TP1.
  3. RE-EVALUASI SELALU DARI AWAL: setiap kali dipanggil, sinyal
     OPEN di-walk ulang dari hari pertama setelah entry sampai hari
     terbaru yang tersedia — BUKAN cuma "kemarin vs hari ini". Ini
     membuat evaluator tetap benar walau sempat tidak jalan
     beberapa hari (idempotent, aman di-backfill).
  4. EXPIRED: jika melewati `settings.signal_max_holding_days` hari
     bursa tanpa TP/SL tersentuh, ditutup EXPIRED di harga close
     terakhir yang tersedia.

═══════════════════════════════════════════════════════════════════
KETERBATASAN YANG DIAKUI JUJUR:
═══════════════════════════════════════════════════════════════════
  - trend_structure & pattern_detected: sejak v2.3 diisi oleh
    src/signals/pattern_engine.py (swing pivot HH/HL/LH/LL, breakout,
    consolidation, candlestick, S/R, RSI divergence). HEURISTIK
    berbasis aturan sederhana, BELUM divalidasi empiris seperti
    volatility_score/minus_di (lihat CHANGELOG v2.2.0) dan BELUM
    di-wire ke scoring manapun -- perlakukan sebagai konteks tambahan
    utk dibaca manusia, bukan sinyal yang sudah terbukti prediktif.
    Kalau deteksi gagal/data kurang, tetap NULL (bukan dikarang).
"""

from datetime import date, timedelta
from typing import Optional

import pandas as pd
import numpy as np

from src.core.config import settings
from src.core.logger import get_logger
from src.core.database import (
    get_db,
    upsert_signal_result,
    get_open_signal_results,
    signal_result_exists,
    get_signal_results_missing_patterns,
)
from src.providers.market_data import get_ohlcv_from_db
from src.signals.ta_engine import calc_rsi, calc_adx, calc_bollinger
from src.signals.pattern_engine import detect_trend_structure, detect_all_patterns

log = get_logger("signal_evaluator")

# Komisi sama persis dengan backtest engine — satu sumber kebenaran,
# supaya net_return_pct di sini comparable dengan hasil backtest.
from src.backtest.engine import BUY_COMMISSION, SELL_COMMISSION

_COMMISSION_PCT = (BUY_COMMISSION + SELL_COMMISSION) * 100


# ═══════════════════════════════════════════════════════════════════
#  BAGIAN 1 — INDIKATOR TURUNAN (reuse fungsi murni ta_engine.py)
# ═══════════════════════════════════════════════════════════════════

def _calc_sma(close: pd.Series, period: int) -> Optional[float]:
    """SMA sederhana — tidak ada di ta_engine.py, dihitung lokal di sini saja."""
    if len(close) < period:
        return None
    val = close.rolling(period, min_periods=period).mean().iloc[-1]
    return float(val) if pd.notna(val) else None


def _compute_extra_indicators(ohlcv_df: pd.DataFrame) -> dict:
    """
    Hitung indikator tambahan yang diminta tapi belum tersimpan di
    tabel `signals`: SMA20/50/200, DI+/DI-, Bollinger Position,
    RSI slope. Semua via fungsi MURNI yang di-reuse dari ta_engine.py
    (calc_rsi, calc_adx, calc_bollinger) — ta_engine.py itu sendiri
    TIDAK disentuh.
    """
    extras = {
        "sma20": None, "sma50": None, "sma200": None,
        "plus_di": None, "minus_di": None,
        "bollinger_position": None,
        "rsi_prev": None, "rsi_slope": None,
    }
    if ohlcv_df is None or ohlcv_df.empty or len(ohlcv_df) < 15:
        return extras

    close = ohlcv_df["close"]

    try:
        extras["sma20"]  = _calc_sma(close, 20)
        extras["sma50"]  = _calc_sma(close, 50)
        extras["sma200"] = _calc_sma(close, 200)
    except Exception as e:
        log.debug(f"SMA calc gagal: {e}")

    try:
        adx, plus_di, minus_di = calc_adx(ohlcv_df, settings.adx_period)
        if not plus_di.empty and pd.notna(plus_di.iloc[-1]):
            extras["plus_di"] = round(float(plus_di.iloc[-1]), 2)
        if not minus_di.empty and pd.notna(minus_di.iloc[-1]):
            extras["minus_di"] = round(float(minus_di.iloc[-1]), 2)
    except Exception as e:
        log.debug(f"DI+/DI- calc gagal: {e}")

    try:
        bb_up, bb_mid, bb_lo = calc_bollinger(close, 20)
        last_close = float(close.iloc[-1])
        up, lo = float(bb_up.iloc[-1]), float(bb_lo.iloc[-1])
        if pd.notna(up) and pd.notna(lo) and (up - lo) > 0:
            extras["bollinger_position"] = round((last_close - lo) / (up - lo), 3)
    except Exception as e:
        log.debug(f"Bollinger position calc gagal: {e}")

    try:
        rsi_series = calc_rsi(close, settings.rsi_period)
        if len(rsi_series) >= 2:
            rsi_now  = float(rsi_series.iloc[-1])
            rsi_prev = float(rsi_series.iloc[-2])
            extras["rsi_prev"]  = round(rsi_prev, 2)
            extras["rsi_slope"] = round(rsi_now - rsi_prev, 2)
    except Exception as e:
        log.debug(f"RSI slope calc gagal: {e}")

    return extras


def _classify_conditions(sig: dict, extras: dict) -> dict:
    """
    Turunkan label kualitatif (Trend/Momentum/Volume condition) dari
    angka yang sudah ada — logika sederhana & independen, tidak
    memanggil ta_engine.py (menghindari duplikasi state internal).
    """
    close = float(sig.get("close_price") or 0)
    ema20 = float(sig.get("ema20") or 0)
    ema50 = float(sig.get("ema50") or 0)
    rsi   = float(sig.get("rsi") or 50)
    vol_ratio = float(sig.get("volume_ratio") or 1.0)

    if close > ema20 > ema50 > 0:
        trend_condition = "Uptrend"
    elif close < ema20 < ema50 and ema50 > 0:
        trend_condition = "Downtrend"
    else:
        trend_condition = "Sideways"

    if rsi < settings.rsi_oversold:
        momentum_condition = "Oversold"
    elif rsi > settings.rsi_overbought:
        momentum_condition = "Overbought"
    else:
        momentum_condition = "Neutral"

    if vol_ratio >= 1.5:
        volume_condition = "High"
    elif vol_ratio < 0.7:
        volume_condition = "Low"
    else:
        volume_condition = "Normal"

    distance_ema20  = round((close / ema20 - 1) * 100, 2) if ema20 > 0 else None
    distance_ema50  = round((close / ema50 - 1) * 100, 2) if ema50 > 0 else None
    ema200 = float(sig.get("ema200") or 0)
    distance_ema200 = round((close / ema200 - 1) * 100, 2) if ema200 > 0 else None

    return {
        "trend_condition": trend_condition,
        "momentum_condition": momentum_condition,
        "volume_condition": volume_condition,
        "distance_ema20_pct": distance_ema20,
        "distance_ema50_pct": distance_ema50,
        "distance_ema200_pct": distance_ema200,
    }


# ═══════════════════════════════════════════════════════════════════
#  BAGIAN 2 — CAPTURE SNAPSHOT SINYAL BARU
# ═══════════════════════════════════════════════════════════════════

def capture_todays_signals(signal_date: Optional[str] = None) -> dict:
    """
    Ambil sinyal STRONG_BUY/BUY/WATCHLIST untuk `signal_date` (default
    hari ini) dari tabel `signals`, lengkapi indikator turunan, dan
    simpan sebagai baris baru status OPEN di `signal_results`.

    Idempotent: upsert dengan UNIQUE(ticker, signal_date, signal_type)
    — dipanggil berkali-kali untuk tanggal yang sama tidak membuat
    duplikat, hanya me-refresh snapshot yang sama.
    """
    sig_date = signal_date or date.today().isoformat()
    log.info(f"[Signal Evaluator] Capture snapshot sinyal {sig_date}...")

    try:
        db = get_db()
        result = (
            db.table("signals")
            .select("*")
            .eq("signal_date", sig_date)
            .in_("signal_type", ["STRONG_BUY", "BUY", "WATCHLIST"])
            .execute()
        )
        today_signals = result.data or []
    except Exception as e:
        log.error(f"Gagal ambil sinyal {sig_date} dari tabel signals: {e}")
        return {"captured": 0, "skipped": 0, "errors": 1}

    if not today_signals:
        log.info("  Tidak ada sinyal STRONG_BUY/BUY/WATCHLIST hari ini.")
        return {"captured": 0, "skipped": 0, "errors": 0}

    captured = 0
    skipped = 0
    errors = 0

    for sig in today_signals:
        ticker = sig.get("ticker")
        try:
            # AUDIT FIX (idempotency — ditemukan lewat pengujian):
            # Snapshot adalah catatan POINT-IN-TIME saat sinyal terbit,
            # tidak boleh pernah ditimpa ulang. Tanpa pengecekan ini,
            # memanggil capture_todays_signals() dua kali di hari yang
            # sama (mis. daily_scan sempat retry, atau evaluate_signals
            # dipanggil manual setelahnya) akan menimpa status yang
            # SUDAH dievaluasi (CLOSED/EXPIRED) balik menjadi OPEN —
            # karena payload capture selalu berisi status="OPEN".
            # Sekali baris untuk (ticker, signal_date, signal_type) ada,
            # capture untuk kombinasi itu dilewati selamanya — hanya
            # evaluate_open_signals() yang boleh mengubah status/exit
            # setelahnya.
            if signal_result_exists(ticker, sig_date, sig.get("signal_type")):
                skipped += 1
                continue

            ohlcv = get_ohlcv_from_db(ticker, days=260)
            extras = _compute_extra_indicators(ohlcv) if ohlcv is not None else {}
            conditions = _classify_conditions(sig, extras)

            reasons = []
            fc = sig.get("factor_contribution")
            if isinstance(fc, dict) and fc.get("highlights"):
                reasons = list(fc["highlights"])

            # trend_structure & pattern_detected (BARU) -- lihat pattern_engine.py.
            # AUDIT (2026-08, ditemukan saat audit menyeluruh): trend_structure
            # SEBELUMNYA dihitung ULANG di sini secara independen dari yang
            # dipakai live scoring (_score_trend di ta_engine.py, migration 006).
            # Karena keduanya jalan dari data yang sama, hasilnya SELALU sama
            # secara praktis -- tapi ini persis pola "2 sumber kebenaran" yang
            # sudah terbukti berisiko (lihat AUDIT backtest/engine.py poin 4).
            # Diperbaiki: REUSE nilai yang sudah tersimpan di `sig` (hasil
            # analyze_stock() yang SUNGGUHAN dipakai untuk trend_score hari
            # itu) -- hanya recompute sebagai fallback untuk data lama
            # sebelum migration 006 (kolom belum ada/masih NULL).
            trend_structure = sig.get("trend_structure")
            pattern_detected: list[str] = []
            if trend_structure is None and ohlcv is not None and not ohlcv.empty:
                try:
                    trend_structure = detect_trend_structure(ohlcv)
                except Exception as e:
                    log.debug(f"{ticker}: detect_trend_structure gagal: {e}")
            if ohlcv is not None and not ohlcv.empty:
                try:
                    rsi_series = calc_rsi(ohlcv["close"], settings.rsi_period)
                    pattern_detected = detect_all_patterns(
                        ohlcv, rsi_series=rsi_series, volume_ratio=sig.get("volume_ratio")
                    )
                except Exception as e:
                    log.debug(f"{ticker}: detect_all_patterns gagal: {e}")

            # tambahan reason tag sederhana (AUDIT: sesuai permintaan, "ATR sehat"
            # & "Market Regime Bull" -- keduanya derivasi angka yg sudah ada,
            # bukan klaim baru) + pattern yg terdeteksi ikut ditampilkan sbg reason
            # biar konsisten dgn contoh yg diminta ("Breakout Resistance" dst).
            atr_pct_now = (float(sig.get("atr")) / float(sig.get("close_price")) * 100
                           if sig.get("atr") and sig.get("close_price") else None)
            if atr_pct_now is not None and 1.0 <= atr_pct_now <= 4.0:
                reasons.append("ATR Sehat")
            if sig.get("market_regime") == "BULL":
                reasons.append("Market Regime Bull")
            reasons.extend(pattern_detected)

            # regime_weight tidak disimpan langsung di tabel signals,
            # tapi composite_score = raw_score * regime_weight (lihat
            # CompositeScore di ta_engine.py) — jadi bisa diturunkan
            # balik dari dua kolom yang memang sudah tersimpan.
            raw_score = sig.get("raw_score")
            composite_score = sig.get("composite_score")
            regime_weight = None
            if raw_score and composite_score and float(raw_score) > 0:
                regime_weight = round(float(composite_score) / float(raw_score), 2)

            row = {
                "ticker": ticker,
                "signal_date": sig_date,
                "timeframe": "1D",
                "sector": sig.get("sector"),
                "market_regime": sig.get("market_regime"),
                "signal_type": sig.get("signal_type"),

                "close_price": sig.get("close_price"),
                "rsi": sig.get("rsi"),
                "rsi_prev": extras.get("rsi_prev"),
                "rsi_slope": extras.get("rsi_slope"),
                "macd_line": sig.get("macd_line"),
                "macd_signal": sig.get("macd_signal"),
                "macd_hist": sig.get("macd_hist"),
                "ema20": sig.get("ema20"),
                "ema50": sig.get("ema50"),
                "ema200": sig.get("ema200"),
                "sma20": extras.get("sma20"),
                "sma50": extras.get("sma50"),
                "sma200": extras.get("sma200"),
                "atr": sig.get("atr"),
                "adx": sig.get("adx"),
                "plus_di": extras.get("plus_di"),
                "minus_di": extras.get("minus_di"),
                "volume": sig.get("volume"),
                "avg_volume_20": sig.get("avg_volume_20"),
                "relative_volume": sig.get("volume_ratio"),
                "bollinger_position": extras.get("bollinger_position"),
                "distance_ema20_pct": conditions["distance_ema20_pct"],
                "distance_ema50_pct": conditions["distance_ema50_pct"],
                "distance_ema200_pct": conditions["distance_ema200_pct"],

                "trend_condition": conditions["trend_condition"],
                "momentum_condition": conditions["momentum_condition"],
                "volume_condition": conditions["volume_condition"],

                "trend_structure": trend_structure,
                "pattern_detected": pattern_detected or None,

                "trend_score": sig.get("trend_score"),
                "momentum_score": sig.get("momentum_score"),
                "volume_score": sig.get("volume_score"),
                "strength_score": sig.get("strength_score"),
                "volatility_score": sig.get("volatility_score"),
                "flow_score": sig.get("flow_score"),
                "analog_score": sig.get("analog_score"),
                "analog_win_rate": sig.get("analog_win_rate"),
                "analog_n": sig.get("analog_n"),
                "cmf": sig.get("cmf"),
                "vsa_signal": sig.get("vsa_signal"),
                "sector_bonus": sig.get("sector_bonus"),
                "regime_weight": regime_weight,
                "raw_score": sig.get("raw_score"),
                "final_score": sig.get("composite_score"),
                "confidence": sig.get("confidence"),

                "reasons": reasons,

                "entry_price": sig.get("entry_price") or sig.get("close_price"),
                "stop_loss": sig.get("stop_loss"),
                "target_1": sig.get("target_1"),
                "target_2": sig.get("target_2"),
                "risk_reward": sig.get("risk_reward"),

                "status": "OPEN",
                "evaluated_at": None,
            }

            if upsert_signal_result(row):
                captured += 1
            else:
                errors += 1

        except Exception as e:
            log.warning(f"Gagal capture snapshot {ticker}: {e}")
            errors += 1

    log.info(f"  ✓ {captured} snapshot baru, {skipped} dilewati (sudah ada), {errors} error")
    return {"captured": captured, "skipped": skipped, "errors": errors}


# ═══════════════════════════════════════════════════════════════════
#  BAGIAN 2.5 — BACKFILL trend_structure/pattern_detected (v2.3, sekali jalan)
# ═══════════════════════════════════════════════════════════════════

def backfill_trend_and_patterns(min_history_days: int = 90) -> dict:
    """
    Isi `trend_structure`/`pattern_detected` untuk baris signal_results LAMA
    yang dibuat SEBELUM pattern_engine.py ada (v2.3) -- kolom itu cuma
    keisi otomatis buat sinyal BARU sejak deploy, TIDAK retroaktif ke
    yang sudah ada (lihat CHANGELOG v2.3.0).

    Cara jalan: ambil semua baris trend_structure IS NULL, kelompokkan
    per ticker (irit query OHLCV), lalu utk tiap baris SLICE data harga
    sampai signal_date-nya SAJA (bukan sampai hari ini) -- supaya hasil
    deteksi persis seperti kalau pattern_engine ini sudah ada sejak awal,
    tanpa lookahead bias.

    SENGAJA tidak menyentuh kolom `reasons` (biar tidak mengubah histori
    "alasan sinyal muncul" yang sudah tercatat) -- cuma isi 2 kolom yang
    tadinya kosong. Aman dijalankan berkali-kali (idempotent: baris yang
    sudah keisi otomatis tidak kepanggil lagi run berikutnya).
    """
    rows = get_signal_results_missing_patterns()
    if not rows:
        log.info("Backfill trend_structure/pattern_detected: tidak ada baris yang perlu diisi.")
        return {"updated": 0, "skipped_no_data": 0, "errors": 0}

    by_ticker: dict[str, list[dict]] = {}
    for r in rows:
        by_ticker.setdefault(r["ticker"], []).append(r)

    log.info(f"Backfill: {len(rows)} baris lama ({len(by_ticker)} ticker) perlu trend_structure/pattern_detected.")

    updated = skipped_no_data = errors = 0
    for ticker, ticker_rows in by_ticker.items():
        try:
            ohlcv = get_ohlcv_from_db(ticker, days=730)  # jendela lebar, cover sinyal lama
        except Exception as e:
            log.warning(f"{ticker}: gagal ambil OHLCV buat backfill: {e}")
            errors += len(ticker_rows)
            continue

        if ohlcv is None or ohlcv.empty:
            skipped_no_data += len(ticker_rows)
            continue

        for r in ticker_rows:
            try:
                sig_date = pd.Timestamp(r["signal_date"])
                snapshot = ohlcv[ohlcv.index <= sig_date]
                if len(snapshot) < min_history_days:
                    skipped_no_data += 1
                    continue

                trend_structure = detect_trend_structure(snapshot)
                rsi_series = calc_rsi(snapshot["close"], settings.rsi_period)
                pattern_detected = detect_all_patterns(snapshot, rsi_series=rsi_series)

                update_row = {
                    "ticker": r["ticker"],
                    "signal_date": r["signal_date"],
                    "signal_type": r["signal_type"],
                    "trend_structure": trend_structure,
                    "pattern_detected": pattern_detected or None,
                }
                if upsert_signal_result(update_row):
                    updated += 1
                else:
                    errors += 1
            except Exception as e:
                log.warning(f"{ticker} {r.get('signal_date')}: backfill gagal: {e}")
                errors += 1

    log.info(f"✓ Backfill selesai: {updated} diupdate, {skipped_no_data} dilewati (data harga kurang), {errors} error")
    return {"updated": updated, "skipped_no_data": skipped_no_data, "errors": errors}


# ═══════════════════════════════════════════════════════════════════
#  BAGIAN 3 — EVALUASI SINYAL YANG MASIH OPEN
# ═══════════════════════════════════════════════════════════════════

def _walk_price_path(
    ohlcv_after_entry: pd.DataFrame,
    stop_loss: float,
    target_1: float,
    target_2: float,
    max_days: int,
) -> Optional[dict]:
    """
    Jalan hari demi hari sejak entry, cek TP/SL dengan aturan
    konservatif (lihat docstring modul): SL -> TP2 -> TP1 per hari.
    Return None jika masih OPEN (belum ada yang tersentuh & belum
    kadaluarsa dalam window yang tersedia).
    """
    for i, (idx, bar) in enumerate(ohlcv_after_entry.iterrows(), 1):
        if i > max_days:
            break

        bar_low  = float(bar["low"])
        bar_high = float(bar["high"])

        if stop_loss and bar_low <= stop_loss:
            return {"exit_price": stop_loss, "exit_reason": "SL",
                    "exit_date": idx, "holding_days": i}

        if target_2 and bar_high >= target_2:
            return {"exit_price": target_2, "exit_reason": "TP2",
                    "exit_date": idx, "holding_days": i}

        if target_1 and bar_high >= target_1:
            return {"exit_price": target_1, "exit_reason": "TP1",
                    "exit_date": idx, "holding_days": i}

    return None


def evaluate_open_signals() -> dict:
    """
    Evaluasi SEMUA signal_results berstatus OPEN. Untuk tiap ticker,
    fetch OHLCV sekali (efisien), lalu evaluasi seluruh sinyal OPEN
    milik ticker itu terhadap data yang sama.

    Aman dipanggil berulang kali (idempotent) — hanya baris OPEN yang
    diproses; yang sudah CLOSED/EXPIRED tidak disentuh lagi. Setiap
    panggilan me-walk ulang dari awal entry, bukan incremental, jadi
    tetap benar walau evaluator sempat tidak jalan beberapa hari.
    """
    log.info("[Signal Evaluator] Evaluasi sinyal OPEN...")

    open_signals = get_open_signal_results()
    if not open_signals:
        log.info("  Tidak ada sinyal OPEN untuk dievaluasi.")
        return {"evaluated": 0, "closed": 0, "expired": 0, "still_open": 0, "errors": 0}

    by_ticker: dict[str, list[dict]] = {}
    for s in open_signals:
        by_ticker.setdefault(s["ticker"], []).append(s)

    closed = expired = still_open = errors = 0
    max_days = settings.signal_max_holding_days
    today = date.today()

    for ticker, sigs in by_ticker.items():
        try:
            ohlcv = get_ohlcv_from_db(ticker, days=max_days + 30)
        except Exception as e:
            log.warning(f"Gagal load OHLCV untuk evaluasi {ticker}: {e}")
            errors += len(sigs)
            continue

        if ohlcv is None or ohlcv.empty:
            errors += len(sigs)
            continue

        for sig in sigs:
            try:
                signal_date = pd.Timestamp(sig["signal_date"])
                # Entry realistis: evaluasi mulai H+1 (lihat docstring modul)
                after_entry = ohlcv[ohlcv.index > signal_date]

                if after_entry.empty:
                    still_open += 1
                    continue

                trading_days_elapsed = len(after_entry)

                hit = _walk_price_path(
                    after_entry,
                    stop_loss=float(sig.get("stop_loss") or 0),
                    target_1=float(sig.get("target_1") or 0),
                    target_2=float(sig.get("target_2") or 0),
                    max_days=max_days,
                )

                if hit:
                    entry = float(sig.get("entry_price") or 0)
                    exit_price = hit["exit_price"]
                    gross = ((exit_price / entry) - 1) * 100 if entry > 0 else 0
                    net = gross - _COMMISSION_PCT

                    upsert_signal_result({
                        "ticker": ticker,
                        "signal_date": sig["signal_date"],
                        "signal_type": sig["signal_type"],
                        "status": "CLOSED",
                        "exit_price": round(exit_price, 2),
                        "exit_date": hit["exit_date"].date().isoformat(),
                        "exit_reason": hit["exit_reason"],
                        "holding_days": hit["holding_days"],
                        "gross_return_pct": round(gross, 3),
                        "net_return_pct": round(net, 3),
                        "evaluated_at": datetime_now_iso(),
                    })
                    closed += 1

                elif trading_days_elapsed >= max_days:
                    entry = float(sig.get("entry_price") or 0)
                    last_close = float(after_entry.iloc[max_days - 1]["close"])
                    exit_date = after_entry.index[max_days - 1]
                    gross = ((last_close / entry) - 1) * 100 if entry > 0 else 0
                    net = gross - _COMMISSION_PCT

                    upsert_signal_result({
                        "ticker": ticker,
                        "signal_date": sig["signal_date"],
                        "signal_type": sig["signal_type"],
                        "status": "EXPIRED",
                        "exit_price": round(last_close, 2),
                        "exit_date": exit_date.date().isoformat(),
                        "exit_reason": "EXPIRED",
                        "holding_days": max_days,
                        "gross_return_pct": round(gross, 3),
                        "net_return_pct": round(net, 3),
                        "evaluated_at": datetime_now_iso(),
                    })
                    expired += 1

                else:
                    still_open += 1

            except Exception as e:
                log.warning(f"Gagal evaluasi {ticker} ({sig.get('signal_date')}): {e}")
                errors += 1

    summary = {
        "evaluated": len(open_signals),
        "closed": closed, "expired": expired,
        "still_open": still_open, "errors": errors,
    }
    log.info(
        f"  ✓ {len(open_signals)} sinyal OPEN diperiksa: "
        f"{closed} CLOSED, {expired} EXPIRED, {still_open} tetap OPEN, {errors} error"
    )
    return summary


def datetime_now_iso() -> str:
    from datetime import datetime
    return datetime.utcnow().isoformat()


# ═══════════════════════════════════════════════════════════════════
#  ORCHESTRATOR
# ═══════════════════════════════════════════════════════════════════

def run_signal_evaluation() -> dict:
    """
    Entry point tunggal dipanggil dari runner.py cmd_daily_scan(),
    SETELAH run_daily_scan() selesai. Urutan: capture dulu (sinyal
    baru hari ini jadi OPEN), baru evaluate (termasuk yang baru saja
    di-capture akan tetap OPEN karena entry-nya baru hari ini —
    evaluasi efektifnya baru mulai besok).
    """
    log.info("═══ AUTOMATIC SIGNAL EVALUATION DIMULAI ═══")
    capture_result = capture_todays_signals()
    evaluate_result = evaluate_open_signals()
    log.info("═══ AUTOMATIC SIGNAL EVALUATION SELESAI ═══")
    return {"capture": capture_result, "evaluate": evaluate_result}
