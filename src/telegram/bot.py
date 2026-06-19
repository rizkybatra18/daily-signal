"""
DAILY SIGNAL — Telegram Bot
Mengirim sinyal, notifikasi, dan summary ke Telegram.
Semua pesan menggunakan HTML formatting.

Types of messages:
    1. Daily Scan (post-market signal summary)
    2. Signal Trigger (ketika BUY/SELL generated)
    3. TP/SL Hit notification (dari monitor)
    4. Daily Market Summary
    5. Health Check alert
"""

import requests
import time
from datetime import datetime
from typing import Optional
import pytz

from src.core.config import settings
from src.core.logger import get_logger

log = get_logger("telegram_bot")

WIB = pytz.timezone("Asia/Jakarta")

# ── Formatting Constants ─────────────────────────────────────────────

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
    """Waktu sekarang dalam WIB."""
    return datetime.now(WIB).strftime("%d %b %Y • %H:%M WIB")


def _send_message(
    text: str,
    token: str = None,
    chat_id: str = None,
    parse_mode: str = "HTML",
    disable_preview: bool = True,
) -> bool:
    """
    Kirim satu pesan ke Telegram.
    Return True jika berhasil.
    """
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
            # Rate limited — tunggu dan retry
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
    """Split pesan panjang dan kirim per chunk."""
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
            time.sleep(0.5)  # Delay antar chunk
    
    return success


# ── Message Formatters ───────────────────────────────────────────────

def _format_signal_card(analysis, index: int) -> str:
    """Format satu kartu sinyal."""
    from src.signals.ta_engine import StockAnalysis
    
    ticker = analysis.ticker.replace(".JK", "")
    signal_type = analysis.score.signal_type
    score = analysis.score.final_score
    
    sig_emoji = SIGNAL_EMOJI.get(signal_type, "⚪")
    
    # Score bar
    bar_filled = int(score / 10)
    score_bar = "█" * bar_filled + "░" * (10 - bar_filled)
    
    # Risk levels
    risk = analysis.risk
    entry = risk.entry_price
    sl = risk.stop_loss
    tp1 = risk.target_1
    tp2 = risk.target_2
    rr = risk.risk_reward_tp1
    
    # Pct calculations
    sl_pct = risk.risk_pct * (-1) if entry > 0 else 0
    tp1_pct = risk.reward_pct_tp1
    tp2_pct = risk.reward_pct_tp2
    
    # Volume spike indicator
    vol_text = f"⚡ Vol {analysis.volume.volume_ratio:.1f}x" if analysis.volume.volume_spike else f"📊 Vol {analysis.volume.volume_ratio:.1f}x"
    
    # Key indicators
    rsi = analysis.momentum.rsi
    adx = analysis.strength.adx
    macd_dir = "▲" if analysis.momentum.macd_hist > 0 else "▼"
    ema_align = analysis.trend.ema_alignment
    rs = analysis.strength.rel_strength
    
    msg = f"""──────────────────────
<b>#{index}  {ticker}</b>  {sig_emoji} <b>{signal_type.replace('_', ' ')}</b>
──────────────────────
📊 Score: <b>{score:.0f}/100</b>  <code>[{score_bar}]</code>

💰 <b>Entry</b>  : Rp{entry:,.0f}
🛑 <b>Stop Loss</b>: Rp{sl:,.0f} <i>({sl_pct:.1f}%)</i>
🎯 <b>Target 1</b>: Rp{tp1:,.0f} <i>(+{tp1_pct:.1f}%)</i>
🎯 <b>Target 2</b>: Rp{tp2:,.0f} <i>(+{tp2_pct:.1f}%)</i>
⚖️ <b>R/R</b>: 1:{rr:.1f}  |  Pos. Size: {risk.position_size_pct:.0f}%

📈 RSI:{rsi:.0f} | ADX:{adx:.0f} | MACD:{macd_dir} | EMA:{ema_align[:4]}
{vol_text} | RS vs IHSG: {rs:+.1f}%
"""
    
    return msg


def _format_regime_header(regime) -> str:
    """Format header dengan market regime info."""
    emoji = REGIME_EMOJI.get(regime.regime, "📊")
    
    return f"""━━━━━━━━━━━━━━━━━━━━━━
🤖 <b>DAILY SIGNAL</b>
📅 {_now_wib()}
━━━━━━━━━━━━━━━━━━━━━━

{emoji} <b>Market Regime: {regime.regime}</b>
📍 IHSG: Rp{regime.ihsg_close:,.0f} | RSI: {regime.ihsg_rsi:.0f}
📊 5D: {regime.change_5d:+.1f}% | {regime.regime_reason[:60]}

"""


def _format_sector_summary(sector_rankings: list, top_n: int = 5) -> str:
    """Format ringkasan sektor rotation."""
    if not sector_rankings:
        return ""
    
    msg = "🏭 <b>SEKTOR TERKUAT:</b>\n"
    for sr in sector_rankings[:top_n]:
        trend_emoji = TREND_EMOJI.get(sr.trend, "➡️")
        msg += f"  #{sr.rank} {trend_emoji} {sr.sector} ({sr.return_5d:+.1f}% 5D)\n"
    
    return msg + "\n"


# ── Public API ────────────────────────────────────────────────────────

def send_daily_signals(
    signals: list,
    regime,
    sector_rankings: list = None,
) -> bool:
    """
    Kirim sinyal harian ke Telegram.
    
    Args:
        signals: List StockAnalysis dengan signal_type STRONG_BUY/BUY
        regime: MarketRegime object
        sector_rankings: List SectorRanking
    
    Returns:
        True jika berhasil kirim
    """
    log.info(f"Mengirim {len(signals)} sinyal ke Telegram...")
    
    # Header
    message = _format_regime_header(regime)
    
    # Sector summary
    if sector_rankings:
        message += _format_sector_summary(sector_rankings, top_n=3)
    
    # Sinyal count
    strong_buy = sum(1 for s in signals if s.score.signal_type == "STRONG_BUY")
    buy = sum(1 for s in signals if s.score.signal_type == "BUY")
    
    if not signals:
        regime_label = regime.regime
        if regime_label == "BEAR":
            message += "🚫 <b>Tidak ada sinyal</b>\n\n"
            message += "<i>Market sedang BEAR — bot menahan sinyal untuk keamanan modal.</i>\n"
        else:
            message += "🔍 <b>Tidak ada sinyal memenuhi kriteria hari ini.</b>\n"
    else:
        message += f"🔍 <b>{len(signals)} SINYAL</b> ({strong_buy} 🚀 STRONG BUY + {buy} 🟢 BUY)\n\n"
        
        for i, analysis in enumerate(signals, 1):
            message += _format_signal_card(analysis, i)
    
    # Footer
    message += f"\n──────────────────────\n"
    message += f"🤖 <b>DAILY SIGNAL</b> | {len(signals)} sinyal aktif\n"
    message += f"<i>⚠️ Bukan rekomendasi investasi. Selalu DYOR & gunakan risk management.</i>"
    
    ok = _split_and_send(message)
    
    if ok:
        log.info("✓ Sinyal berhasil dikirim ke Telegram")
    else:
        log.error("✗ Gagal kirim sinyal ke Telegram")
    
    return ok


def send_tp_sl_notification(
    ticker: str,
    update_type: str,    # "TP1_HIT", "TP2_HIT", "SL_HIT"
    price: float,
    entry_price: float = 0,
    pnl_pct: float = 0,
) -> bool:
    """Kirim notifikasi TP/SL hit."""
    
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
    
    msg = f"""{emoji} <b>{label}</b>
──────────────────────
📌 Saham  : <b>{ticker.replace('.JK','')}</b>
💹 Harga  : Rp{price:,.0f}
📍 Entry  : Rp{entry_price:,.0f}
{f'📊 {pnl_text}' if pnl_text else ''}
🕐 Waktu  : {_now_wib()}
──────────────────────
<i>Auto-monitor oleh DAILY SIGNAL</i>"""
    
    return _send_message(msg)


def send_daily_summary(summary: dict) -> bool:
    """Kirim ringkasan harian setelah market tutup."""
    
    msg = f"""📋 <b>RINGKASAN HARIAN</b>
{_now_wib()}
━━━━━━━━━━━━━━━━━━━━━━

📊 <b>Hasil Scan Hari Ini:</b>
• Saham di-scan : {summary.get('stocks_scanned', 0)}
• STRONG BUY   : {summary.get('strong_buy', 0)} 🚀
• BUY          : {summary.get('buy', 0)} 🟢
• WATCHLIST    : {summary.get('watchlist', 0)} 👀

🏛️ <b>Market:</b> {summary.get('regime', 'N/A')}
⏱ <b>Durasi scan:</b> {summary.get('duration_seconds', 0):.0f}s

<i>Sistem berjalan normal ✓</i>"""
    
    return _send_message(msg)


def send_health_alert(health_data: dict) -> bool:
    """Kirim alert jika ada komponen yang tidak sehat."""
    
    overall = health_data.get("overall", "unknown")
    if overall == "healthy":
        return True  # Tidak perlu kirim alert jika sehat
    
    components = []
    for component, status in health_data.items():
        if component == "overall":
            continue
        status_str = status.get("status", "unknown") if isinstance(status, dict) else str(status)
        emoji = "✅" if status_str == "healthy" else "❌"
        components.append(f"{emoji} {component}: {status_str}")
    
    msg = f"""⚠️ <b>HEALTH ALERT — DAILY SIGNAL</b>
{_now_wib()}
──────────────────────
Status: <b>{overall.upper()}</b>

{chr(10).join(components)}
──────────────────────
<i>Periksa system logs untuk detail.</i>"""
    
    return _send_message(msg)


def send_market_open_alert(regime) -> bool:
    """Kirim alert saat market akan buka (08:30 WIB)."""
    
    emoji = REGIME_EMOJI.get(regime.regime, "📊")
    
    msg = f"""🔔 <b>MARKET AKAN BUKA</b>
{_now_wib()}
━━━━━━━━━━━━━━━━━━━━━━
{emoji} Regime: <b>{regime.regime}</b>
📍 IHSG Kemarin: Rp{regime.ihsg_close:,.0f}
📊 RSI IHSG: {regime.ihsg_rsi:.1f}
🔄 5D Change: {regime.change_5d:+.1f}%

<i>Scan post-market akan dikirim setelah market tutup.</i>"""
    
    return _send_message(msg)


def check_telegram_health() -> dict:
    """Cek apakah Telegram bot bisa mengirim pesan."""
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
