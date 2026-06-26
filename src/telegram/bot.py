"""
DAILY SIGNAL — Telegram Bot v2.3
Semua string di-escape HTML sebelum dikirim.
Semua attribute regime di-guard terhadap None.
Tidak ada f-string kompleks dengan .replace() di dalam kurung kurawal.
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

REGIME_EMOJI  = {"BULL": "📈", "SIDEWAYS": "↔️", "BEAR": "📉"}
SIGNAL_EMOJI  = {"STRONG_BUY": "🚀", "BUY": "🟢", "WATCHLIST": "👀", "AVOID": "🔴"}
TREND_EMOJI   = {"RISING": "⬆️", "STABLE": "➡️", "FALLING": "⬇️"}


# ════════ HELPERS ════════════════════════════════════════════════════

def _now_wib() -> str:
    return datetime.now(WIB).strftime("%d %b %Y • %H:%M WIB")


def _sf(v, d=0.0) -> float:
    """Safe float — None/invalid → default."""
    if v is None:
        return d
    try:
        return float(v)
    except (TypeError, ValueError):
        return d


def _ss(v, d="") -> str:
    """Safe string — None → default."""
    return str(v) if v is not None else d


def _he(text: str) -> str:
    """
    HTML escape untuk string yang masuk ke pesan Telegram (parse_mode=HTML).
    Karakter < > & harus di-escape agar tidak diinterpretasikan sebagai HTML tag.
    """
    if not text:
        return ""
    return (
        str(text)
        .replace("&", "&amp;")   # harus pertama
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


# ════════ SEND ════════════════════════════════════════════════════════

def _send_message(
    text: str,
    token: str = None,
    chat_id: str = None,
    parse_mode: str = "HTML",
    disable_preview: bool = True,
) -> bool:
    token   = token   or settings.telegram_bot_token
    chat_id = chat_id or settings.telegram_chat_id

    if not token or not chat_id:
        log.error(
            "Telegram TIDAK terkonfigurasi! "
            + ("token KOSONG " if not token   else "")
            + ("chat_id KOSONG" if not chat_id else "")
            + " — cek GitHub Secrets."
        )
        return False

    log.info(f"Mengirim ke Telegram chat_id={str(chat_id)[:8]}...")

    url     = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id":                  chat_id,
        "text":                     text,
        "parse_mode":               parse_mode,
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
            log.error(f"Telegram gagal: {resp.status_code} — {resp.text[:300]}")
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

    chunks  = []
    lines   = text.split("\n")
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
        if not _send_message(chunk):
            success = False
        if i < len(chunks) - 1:
            time.sleep(0.5)
    return success


# ════════ FORMATTERS ══════════════════════════════════════════════════

def _format_signal_card(analysis, index: int) -> str:
    """Format kartu sinyal satu saham. Tidak ada f-string kompleks."""
    ticker      = _ss(analysis.ticker).replace(".JK", "")
    signal_type = _ss(analysis.score.signal_type, "AVOID")
    score       = _sf(analysis.score.final_score)
    sig_emoji   = SIGNAL_EMOJI.get(signal_type, "⚪")

    bar_filled  = int(score / 10)
    score_bar   = "█" * bar_filled + "░" * (10 - bar_filled)

    risk        = analysis.risk
    entry       = _sf(risk.entry_price)
    sl          = _sf(risk.stop_loss)
    tp1         = _sf(risk.target_1)
    tp2         = _sf(risk.target_2)
    rr          = _sf(risk.risk_reward_tp1)
    pos_size    = _sf(risk.position_size_pct, 5.0)

    sl_pct      = _sf(risk.risk_pct) * (-1) if entry > 0 else 0
    tp1_pct     = _sf(risk.reward_pct_tp1)
    tp2_pct     = _sf(risk.reward_pct_tp2)

    vr          = _sf(analysis.volume.volume_ratio, 1.0)
    vol_text    = ("⚡ Vol " if analysis.volume.volume_spike else "📊 Vol ") + f"{vr:.1f}x"

    rsi         = _sf(analysis.momentum.rsi)
    adx         = _sf(analysis.strength.adx)
    macd_dir    = "▲" if _sf(analysis.momentum.macd_hist) > 0 else "▼"
    ema_align   = _ss(analysis.trend.ema_alignment, "N/A")[:4]
    rs          = _sf(analysis.strength.rel_strength)

    lines = [
        "──────────────────────",
        f"<b>#{index}  {ticker}</b>  {sig_emoji} <b>{signal_type.replace('_', ' ')}</b>",
        "──────────────────────",
        f"📊 Score: <b>{score:.0f}/100</b>  <code>[{score_bar}]</code>",
        "",
        f"💰 <b>Entry</b>   : Rp{entry:,.0f}",
        f"🛑 <b>Stop Loss</b>: Rp{sl:,.0f} ({sl_pct:.1f}%)",
        f"🎯 <b>Target 1</b> : Rp{tp1:,.0f} (+{tp1_pct:.1f}%)",
        f"🎯 <b>Target 2</b> : Rp{tp2:,.0f} (+{tp2_pct:.1f}%)",
        f"⚖️ <b>R/R</b>: 1:{rr:.1f}  |  Pos: {pos_size:.0f}%",
        "",
        f"📈 RSI:{rsi:.0f} | ADX:{adx:.0f} | MACD:{macd_dir} | EMA:{ema_align}",
        f"{vol_text} | RS vs IHSG: {rs:+.1f}%",
    ]
    return "\n".join(lines) + "\n"


def _format_regime_header(regime) -> str:
    """Format header dengan info regime. Semua string di-escape HTML."""
    r           = _ss(getattr(regime, "regime", None), "N/A")
    emoji       = REGIME_EMOJI.get(r, "📊")
    ihsg_close  = _sf(getattr(regime, "ihsg_close",  0))
    ihsg_rsi    = _sf(getattr(regime, "ihsg_rsi",    0))
    change_5d   = _sf(getattr(regime, "change_5d",   0))

    # KUNCI: escape regime_reason karena bisa mengandung < > dari komparasi EMA
    raw_reason  = _ss(getattr(regime, "regime_reason", ""), "")
    safe_reason = _he(raw_reason[:60])

    lines = [
        "━━━━━━━━━━━━━━━━━━━━━━",
        "🤖 <b>DAILY SIGNAL</b>",
        f"📅 {_now_wib()}",
        "━━━━━━━━━━━━━━━━━━━━━━",
        "",
        f"{emoji} <b>Market Regime: {r}</b>",
        f"📍 IHSG: Rp{ihsg_close:,.0f} | RSI: {ihsg_rsi:.0f}",
        f"📊 5D: {change_5d:+.1f}% | {safe_reason}",
        "",
    ]
    return "\n".join(lines)


def _format_sector_summary(sector_rankings: list, top_n: int = 3) -> str:
    if not sector_rankings:
        return ""
    lines = ["🏭 <b>SEKTOR TERKUAT:</b>"]
    for sr in sector_rankings[:top_n]:
        rank        = getattr(sr, "rank", 0)
        sector_name = _he(_ss(getattr(sr, "sector", "—")))[:20]
        return_5d   = _sf(getattr(sr, "return_5d", 0))
        trend       = _ss(getattr(sr, "trend", "STABLE"), "STABLE")
        te          = TREND_EMOJI.get(trend, "➡️")
        lines.append(f"  #{rank} {te} {sector_name} ({return_5d:+.1f}% 5D)")
    return "\n".join(lines) + "\n\n"


# ════════ PUBLIC API ══════════════════════════════════════════════════

def send_daily_signals(signals: list, regime, sector_rankings: list = None) -> bool:
    """Kirim sinyal harian ke Telegram."""
    log.info(f"Mengirim {len(signals)} sinyal ke Telegram...")

    parts = [_format_regime_header(regime)]

    if sector_rankings:
        parts.append(_format_sector_summary(sector_rankings, top_n=3))

    strong_buy = sum(1 for s in signals if _ss(getattr(s.score, "signal_type", "")) == "STRONG_BUY")
    buy_count  = sum(1 for s in signals if _ss(getattr(s.score, "signal_type", "")) == "BUY")

    if not signals:
        r = _ss(getattr(regime, "regime", ""), "")
        if r == "BEAR":
            ihsg_rsi = _sf(getattr(regime, "ihsg_rsi", 50))
            parts.append("🚫 <b>Tidak ada sinyal BUY hari ini</b>\n")
            parts.append(
                "<i>Market sedang BEAR (RSI IHSG "
                + f"{ihsg_rsi:.0f}"
                + "). Bot menahan sinyal untuk melindungi modal.\n"
                + "Tunggu RSI IHSG > 45 atau EMA20 kembali naik sebelum entry.</i>\n"
            )
        else:
            parts.append("🔍 <b>Tidak ada sinyal yang memenuhi kriteria hari ini.</b>\n")
            parts.append("<i>Semua saham tidak memenuhi minimum score. Coba lagi besok.</i>\n")
    else:
        parts.append(f"🔍 <b>{len(signals)} SINYAL</b> ({strong_buy} 🚀 STRONG BUY + {buy_count} 🟢 BUY)\n")
        for i, analysis in enumerate(signals, 1):
            parts.append(_format_signal_card(analysis, i))

    parts.append("──────────────────────")
    parts.append(f"🤖 <b>DAILY SIGNAL</b> | {len(signals)} sinyal aktif")
    parts.append("<i>Bukan rekomendasi investasi. Selalu DYOR.</i>")

    message = "\n".join(parts)
    ok = _split_and_send(message)

    if ok:
        log.info("✓ Sinyal berhasil dikirim ke Telegram")
    else:
        log.error("✗ Gagal kirim sinyal ke Telegram")
    return ok


def send_market_open_alert(regime) -> bool:
    """
    Kirim alert pre-market (08:30 WIB).
    Berisi kondisi IHSG + reminder sinyal aktif dari kemarin.
    """
    r           = _ss(getattr(regime, "regime", None), "N/A")
    emoji       = REGIME_EMOJI.get(r, "📊")
    ihsg_close  = _sf(getattr(regime, "ihsg_close",  0))
    ihsg_rsi    = _sf(getattr(regime, "ihsg_rsi",    0))
    change_5d   = _sf(getattr(regime, "change_5d",   0))

    regime_desc = {
        "BULL":     "✅ Kondisi bagus untuk trading",
        "SIDEWAYS": "⚠️ Selektif — pilih score tinggi",
        "BEAR":     "🚫 Hati-hati — kurangi eksposur",
    }.get(r, "")

    # Sinyal aktif dari kemarin
    active_lines = []
    try:
        from src.core.database import get_db
        db = get_db()
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        result = (
            db.table("signals")
            .select("ticker,signal_type,composite_score")
            .in_("signal_type", ["STRONG_BUY", "BUY"])
            .gte("signal_date", yesterday)
            .order("composite_score", desc=True)
            .limit(5)
            .execute()
        )
        if result.data:
            active_lines.append("\n📋 <b>Sinyal Aktif dari Kemarin:</b>")
            for s in result.data:
                tk    = _ss(s.get("ticker"), "").replace(".JK", "")
                st    = _ss(s.get("signal_type"), "").replace("_", " ")
                sc    = _sf(s.get("composite_score"))
                se    = "🚀" if s.get("signal_type") == "STRONG_BUY" else "🟢"
                active_lines.append(f"  {se} <b>{tk}</b> {st} (Score:{sc:.0f})")
    except Exception:
        pass

    active_text = "\n".join(active_lines)

    lines = [
        "🔔 <b>MARKET AKAN BUKA</b>",
        f"{_now_wib()}",
        "━━━━━━━━━━━━━━━━━━━━━━",
        f"{emoji} Regime: <b>{r}</b>",
        regime_desc,
        "",
        f"📍 IHSG Terakhir : Rp{ihsg_close:,.0f}",
        f"📊 RSI IHSG      : {ihsg_rsi:.1f}",
        f"🔄 Change 5 Hari : {change_5d:+.1f}%",
        active_text,
        "━━━━━━━━━━━━━━━━━━━━━━",
        "<i>⏰ Sinyal baru dikirim ~17:30 WIB</i>",
    ]
    msg = "\n".join(lines)
    return _send_message(msg)


def send_tp_sl_notification(
    ticker: str,
    update_type: str,
    price: float,
    entry_price: float = 0,
    pnl_pct: float = 0,
) -> bool:
    emojis = {"TP1_HIT": "✅", "TP2_HIT": "🏆", "SL_HIT": "🛑"}
    labels = {"TP1_HIT": "TARGET 1 TERCAPAI", "TP2_HIT": "TARGET 2 TERCAPAI", "SL_HIT": "STOP LOSS TERCAPAI"}

    emoji = emojis.get(update_type, "📊")
    label = labels.get(update_type, update_type)
    pnl_line = f"📊 P&L: {pnl_pct:+.2f}%" if pnl_pct != 0 else ""

    lines = [
        f"{emoji} <b>{label}</b>",
        "──────────────────────",
        f"📌 Saham: <b>{_he(ticker.replace('.JK',''))}</b>",
        f"💹 Harga: Rp{price:,.0f}",
        f"📍 Entry: Rp{entry_price:,.0f}",
    ]
    if pnl_line:
        lines.append(pnl_line)
    lines += [
        f"🕐 Waktu: {_now_wib()}",
        "──────────────────────",
        "<i>Auto-monitor oleh DAILY SIGNAL</i>",
    ]
    return _send_message("\n".join(lines))


def send_daily_summary(summary: dict) -> bool:
    lines = [
        "📋 <b>RINGKASAN HARIAN</b>",
        f"{_now_wib()}",
        "━━━━━━━━━━━━━━━━━━━━━━",
        "",
        "📊 <b>Hasil Scan Hari Ini:</b>",
        f"• Saham di-scan : {summary.get('stocks_scanned', 0)}",
        f"• STRONG BUY   : {summary.get('strong_buy', 0)} 🚀",
        f"• BUY          : {summary.get('buy', 0)} 🟢",
        f"• WATCHLIST    : {summary.get('watchlist', 0)} 👀",
        "",
        f"🏛️ <b>Market:</b> {_he(str(summary.get('regime', 'N/A')))}",
        f"⏱ <b>Durasi:</b> {summary.get('duration_seconds', 0):.0f}s",
        "",
        "<i>Sistem berjalan normal ✓</i>",
    ]
    return _send_message("\n".join(lines))


def send_health_alert(health_data: dict) -> bool:
    overall = health_data.get("overall", "unknown")
    if overall == "healthy":
        return True

    icons = {"healthy": "✅", "unhealthy": "❌", "error": "🔴", "degraded": "⚠️"}
    comp_lines = []
    for component, status in health_data.items():
        if component == "overall":
            continue
        s     = status.get("status", "unknown") if isinstance(status, dict) else str(status)
        icon  = icons.get(s, "⚪")
        comp_lines.append(f"{icon} {_he(component)}: {_he(s)}")

    lines = [
        "⚠️ <b>HEALTH ALERT — DAILY SIGNAL</b>",
        f"{_now_wib()}",
        "──────────────────────",
        f"Status: <b>{_he(overall.upper())}</b>",
        "",
    ] + comp_lines + [
        "──────────────────────",
        "<i>Periksa system logs untuk detail.</i>",
    ]
    return _send_message("\n".join(lines))


def check_telegram_health() -> dict:
    try:
        token   = settings.telegram_bot_token
        chat_id = settings.telegram_chat_id
        if not token or not chat_id:
            return {"status": "unconfigured", "error": "Token atau chat_id kosong"}
        resp = requests.get(f"https://api.telegram.org/bot{token}/getMe", timeout=10)
        if resp.ok:
            return {
                "status":   "healthy",
                "bot_name": resp.json().get("result", {}).get("username"),
            }
        return {"status": "unhealthy", "error": f"HTTP {resp.status_code}"}
    except Exception as e:
        return {"status": "error", "error": str(e)}
