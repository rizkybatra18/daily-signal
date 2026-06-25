"""
DAILY SIGNAL — Telegram Bot
Mengirim sinyal, notifikasi, dan summary ke Telegram.
"""

import requests
import time
from datetime import datetime, date, timedelta
from typing import Optional
import pytz

from src.core.config import settings
from src.core.logger import get_logger

log = get_logger("telegram_bot")

WIB = pytz.timezone("Asia/Jakarta")

REGIME_EMOJI = {
    "BULL": "📈",
    "SIDEWAYS": "↔️",
    "BEAR": "📉",
}

SIGNAL_EMOJI = {
    "STRONG_BUY": "🚀",
    "BUY": "🟢",
    "WATCHLIST": "👀",
    "AVOID": "🔴",
}

TREND_EMOJI = {
    "RISING": "⬆️",
    "STABLE": "➡️",
    "FALLING": "⬇️",
}


def _now_wib() -> str:
    return datetime.now(WIB).strftime("%d %b %Y • %H:%M WIB")


def _send_message(
    text: str,
    token: str = None,
    chat_id: str = None,
    parse_mode: str = "HTML",
    disable_preview: bool = True,
) -> bool:
    token = token or settings.telegram_bot_token
    chat_id = chat_id or settings.telegram_chat_id

    if not token or not chat_id:
        log.warning("Telegram token atau chat_id belum dikonfigurasi")
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": disable_preview,
    }

    try:
        resp = requests.post(url, json=payload, timeout=15)

        if resp.status_code == 429:
            retry_after = resp.json().get("parameters", {}).get("retry_after", 5)
            log.warning(f"Telegram rate limited, tunggu {retry_after}s")
            time.sleep(retry_after + 1)
            resp = requests.post(url, json=payload, timeout=15)

        if not resp.ok:
            log.error(f"Telegram gagal: {resp.status_code} — {resp.text[:200]}")
            return False

        return True

    except requests.exceptions.Timeout:
        log.error("Telegram timeout")
        return False
    except Exception as e:
        log.error(f"Telegram error: {e}")
        return False


def _split_and_send(text: str, max_len: int = 4000) -> bool:
    if len(text) <= max_len:
        return _send_message(text)

    chunks = []
    lines = text.split("\n")
    current = ""

    for line in lines:
        if len(current) + len(line) + 1 > max_len:
            if current:
                chunks.append(current)
            current = line
        else:
            current += ("\n" if current else "") + line

    if current:
        chunks.append(current)

    success = True
    for i, chunk in enumerate(chunks):
        ok = _send_message(chunk)
        if not ok:
            success = False
        if i < len(chunks) - 1:
            time.sleep(0.5)

    return success


def _format_signal_card(analysis, index: int) -> str:
    ticker = analysis.ticker.replace(".JK", "")
    signal_type = analysis.score.signal_type
    score = analysis.score.final_score

    sig_emoji = SIGNAL_EMOJI.get(signal_type, "⚪")

    bar_filled = int(score / 10)
    score_bar = "█" * bar_filled + "░" * (10 - bar_filled)

    risk = analysis.risk
    entry = risk.entry_price
    sl = risk.stop_loss
    tp1 = risk.target_1
    tp2 = risk.target_2
    rr = risk.risk_reward_tp1

    sl_pct = risk.risk_pct * (-1) if entry > 0 else 0
    tp1_pct = risk.reward_pct_tp1
    tp2_pct = risk.reward_pct_tp2

    vol_text = (
        f"⚡ Vol {analysis.volume.volume_ratio:.1f}x"
        if analysis.volume.volume_spike
        else f"📊 Vol {analysis.volume.volume_ratio:.1f}x"
    )

    rsi = analysis.momentum.rsi
    adx = analysis.strength.adx
    macd_dir = "▲" if analysis.momentum.macd_hist > 0 else "▼"
    ema_align = analysis.trend.ema_alignment
    rs = analysis.strength.rel_strength

    msg = (
        "──────────────────────\n"
        f"<b>#{index}  {ticker}</b>  {sig_emoji} <b>{signal_type.replace('_', ' ')}</b>\n"
        "──────────────────────\n"
        f"📊 Score: <b>{score:.0f}/100</b>  <code>[{score_bar}]</code>\n"
        "\n"
        f"💰 <b>Entry</b>  : Rp{entry:,.0f}\n"
        f"🛑 <b>Stop Loss</b>: Rp{sl:,.0f} <i>({sl_pct:.1f}%)</i>\n"
        f"🎯 <b>Target 1</b>: Rp{tp1:,.0f} <i>(+{tp1_pct:.1f}%)</i>\n"
        f"🎯 <b>Target 2</b>: Rp{tp2:,.0f} <i>(+{tp2_pct:.1f}%)</i>\n"
        f"⚖️ <b>R/R</b>: 1:{rr:.1f}  |  Pos. Size: {risk.position_size_pct:.0f}%\n"
        "\n"
        f"📈 RSI:{rsi:.0f} | ADX:{adx:.0f} | MACD:{macd_dir} | EMA:{ema_align[:4]}\n"
        f"{vol_text} | RS vs IHSG: {rs:+.1f}%\n"
    )

    return msg


def _format_regime_header(regime) -> str:
    emoji = REGIME_EMOJI.get(regime.regime, "📊")

    return (
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "🤖 <b>DAILY SIGNAL</b>\n"
        f"📅 {_now_wib()}\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "\n"
        f"{emoji} <b>Market Regime: {regime.regime}</b>\n"
        f"📍 IHSG: Rp{regime.ihsg_close:,.0f} | RSI: {regime.ihsg_rsi:.0f}\n"
        f"📊 5D: {regime.change_5d:+.1f}% | {regime.regime_reason[:60]}\n"
        "\n"
    )


def _format_sector_summary(sector_rankings: list, top_n: int = 5) -> str:
    if not sector_rankings:
        return ""

    msg = "🏭 <b>SEKTOR TERKUAT:</b>\n"
    for sr in sector_rankings[:top_n]:
        trend_emoji = TREND_EMOJI.get(sr.trend, "➡️")
        msg += f"  #{sr.rank} {trend_emoji} {sr.sector} ({sr.return_5d:+.1f}% 5D)\n"

    return msg + "\n"


def send_daily_signals(
    signals: list,
    regime,
    sector_rankings: list = None,
) -> bool:
    log.info(f"Mengirim {len(signals)} sinyal ke Telegram...")

    message = _format_regime_header(regime)

    if sector_rankings:
        message += _format_sector_summary(sector_rankings, top_n=3)

    strong_buy = sum(1 for s in signals if s.score.signal_type == "STRONG_BUY")
    buy = sum(1 for s in signals if s.score.signal_type == "BUY")

    if not signals:
        if regime.regime == "BEAR":
            message += "🚫 <b>Tidak ada sinyal</b>\n\n"
            message += "<i>Market sedang BEAR — bot menahan sinyal untuk keamanan modal.</i>\n"
        else:
            message += "🔍 <b>Tidak ada sinyal memenuhi kriteria hari ini.</b>\n"
    else:
        message += f"🔍 <b>{len(signals)} SINYAL</b> ({strong_buy} 🚀 STRONG BUY + {buy} 🟢 BUY)\n\n"
        for i, analysis in enumerate(signals, 1):
            message += _format_signal_card(analysis, i)

    message += "\n──────────────────────\n"
    message += f"🤖 <b>DAILY SIGNAL</b> | {len(signals)} sinyal aktif\n"
    message += "<i>⚠️ Bukan rekomendasi investasi. Selalu DYOR & gunakan risk management.</i>"

    ok = _split_and_send(message)

    if ok:
        log.info("✓ Sinyal berhasil dikirim ke Telegram")
    else:
        log.error("✗ Gagal kirim sinyal ke Telegram")

    return ok


def send_market_open_alert(regime) -> bool:
    """
    Kirim alert pre-market (08:30 WIB).
    Berisi: kondisi IHSG + reminder sinyal aktif dari kemarin.

    CATATAN: Ini BUKAN sinyal baru.
    Sinyal baru dikirim jam 17:30 WIB setelah market tutup.
    """
    emoji = REGIME_EMOJI.get(regime.regime, "📊")
    regime_desc = {
        "BULL": "✅ Kondisi bagus untuk trading",
        "SIDEWAYS": "⚠️ Selektif — pilih yang paling kuat",
        "BEAR": "🚫 Hati-hati — kurangi exposure",
    }.get(regime.regime, "")

    # Ambil sinyal aktif dari kemarin
    active_signals_text = ""
    try:
        from src.core.database import get_db
        db = get_db()
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        result = (
            db.table("signals")
            .select("ticker, signal_type, composite_score, entry_price, stop_loss, target_1")
            .in_("signal_type", ["STRONG_BUY", "BUY"])
            .gte("signal_date", yesterday)
            .order("composite_score", desc=True)
            .limit(5)
            .execute()
        )
        if result.data:
            lines = []
            for s in result.data:
                ticker = s["ticker"].replace(".JK", "")
                sig = s["signal_type"].replace("_", " ")
                score = s.get("composite_score", 0) or 0
                sig_e = "🚀" if s["signal_type"] == "STRONG_BUY" else "🟢"
                lines.append(f"  {sig_e} <b>{ticker}</b> {sig} (Score:{score:.0f})")
            active_signals_text = (
                "\n📋 <b>Sinyal Aktif dari Kemarin:</b>\n"
                + "\n".join(lines)
                + "\n"
            )
    except Exception:
        pass

    msg = (
        "🔔 <b>MARKET AKAN BUKA</b>\n"
        f"{_now_wib()}\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        f"{emoji} Regime: <b>{regime.regime}</b>\n"
        f"{regime_desc}\n"
        "\n"
        f"📍 IHSG Terakhir : Rp{regime.ihsg_close:,.0f}\n"
        f"📊 RSI IHSG      : {regime.ihsg_rsi:.1f}\n"
        f"🔄 Change 5 Hari : {regime.change_5d:+.1f}%\n"
        f"{active_signals_text}"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "<i>⏰ Sinyal baru hari ini dikirim ~17:30 WIB</i>"
    )

    return _send_message(msg)


def send_tp_sl_notification(
    ticker: str,
    update_type: str,
    price: float,
    entry_price: float = 0,
    pnl_pct: float = 0,
) -> bool:
    emojis = {
        "TP1_HIT": "✅",
        "TP2_HIT": "🏆",
        "SL_HIT": "🛑",
    }
    labels = {
        "TP1_HIT": "TARGET 1 TERCAPAI",
        "TP2_HIT": "TARGET 2 TERCAPAI",
        "SL_HIT": "STOP LOSS TERCAPAI",
    }

    emoji = emojis.get(update_type, "📊")
    label = labels.get(update_type, update_type)
    pnl_text = f"P&L: {pnl_pct:+.2f}%" if pnl_pct != 0 else ""

    msg = (
        f"{emoji} <b>{label}</b>\n"
        "──────────────────────\n"
        f"📌 Saham  : <b>{ticker.replace('.JK', '')}</b>\n"
        f"💹 Harga  : Rp{price:,.0f}\n"
        f"📍 Entry  : Rp{entry_price:,.0f}\n"
        + (f"📊 {pnl_text}\n" if pnl_text else "")
        + f"🕐 Waktu  : {_now_wib()}\n"
        "──────────────────────\n"
        "<i>Auto-monitor oleh DAILY SIGNAL</i>"
    )

    return _send_message(msg)


def send_daily_summary(summary: dict) -> bool:
    msg = (
        "📋 <b>RINGKASAN HARIAN</b>\n"
        f"{_now_wib()}\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "\n"
        "📊 <b>Hasil Scan Hari Ini:</b>\n"
        f"• Saham di-scan : {summary.get('stocks_scanned', 0)}\n"
        f"• STRONG BUY   : {summary.get('strong_buy', 0)} 🚀\n"
        f"• BUY          : {summary.get('buy', 0)} 🟢\n"
        f"• WATCHLIST    : {summary.get('watchlist', 0)} 👀\n"
        "\n"
        f"🏛️ <b>Market:</b> {summary.get('regime', 'N/A')}\n"
        f"⏱ <b>Durasi scan:</b> {summary.get('duration_seconds', 0):.0f}s\n"
        "\n"
        "<i>Sistem berjalan normal ✓</i>"
    )

    return _send_message(msg)


def send_health_alert(health_data: dict) -> bool:
    overall = health_data.get("overall", "unknown")
    if overall == "healthy":
        return True

    components = []
    for component, status in health_data.items():
        if component == "overall":
            continue
        status_str = (
            status.get("status", "unknown") if isinstance(status, dict) else str(status)
        )
        icon = "✅" if status_str == "healthy" else "❌"
        components.append(f"{icon} {component}: {status_str}")

    msg = (
        "⚠️ <b>HEALTH ALERT — DAILY SIGNAL</b>\n"
        f"{_now_wib()}\n"
        "──────────────────────\n"
        f"Status: <b>{overall.upper()}</b>\n"
        "\n"
        + "\n".join(components)
        + "\n──────────────────────\n"
        "<i>Periksa system logs untuk detail.</i>"
    )

    return _send_message(msg)


def check_telegram_health() -> dict:
    try:
        token = settings.telegram_bot_token
        chat_id = settings.telegram_chat_id

        if not token or not chat_id:
            return {"status": "unconfigured", "error": "Token atau chat_id belum diisi"}

        url = f"https://api.telegram.org/bot{token}/getMe"
        resp = requests.get(url, timeout=10)

        if resp.ok:
            data = resp.json()
            return {
                "status": "healthy",
                "bot_name": data.get("result", {}).get("username"),
            }
        else:
            return {"status": "unhealthy", "error": f"HTTP {resp.status_code}"}

    except Exception as e:
        return {"status": "error", "error": str(e)}
