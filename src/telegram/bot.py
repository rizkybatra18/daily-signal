"""
DAILY SIGNAL — Telegram Bot v3.0 "Sinyal Dari Langit"
Newsletter premium — market summary, alasan per sinyal, dan
elegant messaging saat tidak ada sinyal.

CATATAN PENTING soal sumber data:
    send_daily_signals() menerima StockAnalysis OBJECTS langsung dari
    scanner.py (bukan dict dari database) — dipanggil di scan yang
    SAMA saat objek itu baru selesai dianalisis analyze_stock(), jadi
    factor_contribution/confidence SELALU terisi (tidak perlu fallback
    "migration belum jalan" di jalur ini).

    send_market_open_alert() dan fungsi lain yang QUERY ke database
    (baca sinyal HARI SEBELUMNYA) tetap pakai .get() dengan default —
    baris lama sebelum migration 002 mungkin belum punya kolom baru.

Tidak ada perubahan ke engine/scoring/database — murni presentasi.
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

REGIME_EMOJI  = {"BULL": "🟢", "SIDEWAYS": "🟡", "BEAR": "🔴"}
SIGNAL_EMOJI  = {"STRONG_BUY": "🚀", "BUY": "🟢", "WATCHLIST": "👀", "AVOID": "🔴"}
TREND_EMOJI   = {"RISING": "⬆️", "STABLE": "➡️", "FALLING": "⬇️"}
CONF_EMOJI    = {"Very High": "●●●●", "High": "●●●○", "Medium": "●●○○", "Low": "●○○○"}

DIV  = "━━━━━━━━━━━━━━━━━━━━━━"
DIV2 = "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄"


# ════════ HELPERS ════════════════════════════════════════════════════

def _now_wib() -> str:
    return datetime.now(WIB).strftime("%d %b %Y • %H:%M WIB")


def _sf(v, d=0.0) -> float:
    if v is None:
        return d
    try:
        return float(v)
    except (TypeError, ValueError):
        return d


def _ss(v, d="") -> str:
    return str(v) if v is not None else d


def _he(text) -> str:
    """HTML escape — wajib untuk parse_mode=HTML di Telegram."""
    if not text:
        return ""
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _getattr_safe(obj, path, default=None):
    """Ambil nested attribute dari objek dataclass dengan aman (mis. 'trend.ema20')."""
    cur = obj
    try:
        for part in path.split("."):
            cur = getattr(cur, part)
        return cur if cur is not None else default
    except AttributeError:
        return default


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

    chunks, lines, current = [], text.split("\n"), ""
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


# ════════ FORMATTERS — DAILY SIGNAL (newsletter) ═══════════════════════

def _format_newsletter_header(regime, funnel: Optional[dict] = None) -> str:
    """
    Header newsletter premium: identitas + ringkasan market + scanner
    summary dalam satu blok yang enak dibaca.
    """
    r          = _ss(_getattr_safe(regime, "regime"), "N/A")
    emoji      = REGIME_EMOJI.get(r, "📊")
    ihsg_close = _sf(_getattr_safe(regime, "ihsg_close"))
    ihsg_rsi   = _sf(_getattr_safe(regime, "ihsg_rsi"))
    ihsg_adx   = _sf(_getattr_safe(regime, "ihsg_adx"))
    change_5d  = _sf(_getattr_safe(regime, "change_5d"))
    breadth    = _sf(_getattr_safe(regime, "breadth_score"), 50.0)
    pct_ema50  = _getattr_safe(regime, "pct_above_ema50")

    regime_note = {
        "BULL":     "Momentum mendukung — sinyal beli lebih terpercaya.",
        "SIDEWAYS": "Pasar konsolidasi — hanya setup terbaik yang lolos.",
        "BEAR":     "Pasar melemah — threshold sinyal diperketat otomatis.",
    }.get(r, "")

    lines = [
        "✦ <b>SINYAL DARI LANGIT</b>",
        f"<i>{_now_wib()}</i>",
        DIV,
        "",
        f"{emoji} <b>Market Regime: {r}</b>",
        f"<i>{regime_note}</i>",
        "",
        f"📍 IHSG      : Rp{ihsg_close:,.0f} ({change_5d:+.1f}% 5D)",
        f"📊 RSI / ADX  : {ihsg_rsi:.1f} / {ihsg_adx:.1f}",
        f"💠 Breadth   : {breadth:.0f}% saham naik"
        + (f" · {_sf(pct_ema50):.0f}% di atas EMA50" if pct_ema50 is not None else ""),
    ]

    if funnel:
        lines += [
            "",
            f"🔍 <b>Scanner:</b> {funnel.get('data_available','—')} saham dipindai · "
            f"{funnel.get('technical_pass','—')} lolos filter teknikal",
        ]

    lines.append("")
    return "\n".join(lines)


def _format_sector_summary(sector_rankings: list, top_n: int = 3) -> str:
    if not sector_rankings:
        return ""
    lines = ["🏭 <b>SEKTOR TERKUAT:</b>"]
    for sr in sector_rankings[:top_n]:
        rank        = getattr(sr, "rank", 0)
        sector_name = _he(_ss(getattr(sr, "sector", "—")))[:22]
        return_5d   = _sf(getattr(sr, "return_5d", 0))
        trend       = _ss(getattr(sr, "trend", "STABLE"), "STABLE")
        te          = TREND_EMOJI.get(trend, "➡️")
        lines.append(f"  #{rank} {te} {sector_name} ({return_5d:+.1f}% 5D)")
    return "\n".join(lines) + "\n\n"


def _signal_reasons(analysis) -> list[str]:
    """
    Ambil daftar alasan (highlights) dari factor_contribution yang sudah
    dihitung build_factor_contribution() di ta_engine.py — SATU sumber
    kebenaran yang sama dipakai Dashboard "Signal Detail". Fallback ke
    heuristik ringan kalau factor_contribution kosong (mis. exception
    saat compute, sudah ditangani ta_engine dengan default {}).
    """
    fc = getattr(analysis, "factor_contribution", None)
    if isinstance(fc, dict) and fc.get("highlights"):
        return list(fc["highlights"])

    reasons = []
    score = getattr(analysis, "score", None)
    if score and _sf(getattr(score, "trend_score", 0)) >= 24:
        reasons.append("EMA Bullish Alignment kuat")
    vol = getattr(analysis, "volume", None)
    if vol and getattr(vol, "volume_spike", False):
        reasons.append(f"Volume Spike {_sf(getattr(vol,'volume_ratio',1)):.1f}x")
    strength = getattr(analysis, "strength", None)
    if strength and _sf(getattr(strength, "rel_strength", 0)) > 5:
        reasons.append("Relative Strength tinggi vs IHSG")
    if strength and _sf(getattr(strength, "adx", 0)) >= 25:
        reasons.append("ADX kuat (trend jelas)")
    if not reasons:
        reasons.append("Memenuhi ambang skor minimum sistem")
    return reasons


def _format_signal_card(analysis, index: int) -> str:
    """Kartu sinyal premium — skor, alasan (reason checklist), risk mgmt."""
    ticker      = _ss(getattr(analysis, "ticker", "")).replace(".JK", "")
    score_obj   = getattr(analysis, "score", None)
    signal_type = _ss(getattr(score_obj, "signal_type", ""), "AVOID")
    raw_score   = _sf(getattr(score_obj, "raw_score", 0))
    confidence  = _ss(getattr(score_obj, "confidence", ""), "")
    sig_emoji   = SIGNAL_EMOJI.get(signal_type, "⚪")

    risk        = getattr(analysis, "risk", None)
    entry       = _sf(getattr(risk, "entry_price", 0))
    sl          = _sf(getattr(risk, "stop_loss", 0))
    tp1         = _sf(getattr(risk, "target_1", 0))
    tp2         = _sf(getattr(risk, "target_2", 0))
    rr          = _sf(getattr(risk, "risk_reward_tp1", 0))
    pos_size    = _sf(getattr(risk, "position_size_pct", 0), 5.0)

    sl_pct      = ((sl/entry)-1)*100 if entry > 0 else 0
    tp1_pct     = ((tp1/entry)-1)*100 if entry > 0 else 0
    tp2_pct     = ((tp2/entry)-1)*100 if entry > 0 else 0

    sector      = _he(_ss(getattr(analysis, "sector", ""), ""))
    reasons     = _signal_reasons(analysis)
    reason_txt  = "\n".join(f"  ✓ {_he(r)}" for r in reasons[:5])

    conf_dots = CONF_EMOJI.get(confidence, "")

    lines = [
        DIV2,
        f"<b>#{index}  {ticker}</b>  {sig_emoji} <b>{signal_type.replace('_',' ')}</b>",
        f"Skor <b>{raw_score:.0f}</b>/100"
        + (f" · Confidence <b>{confidence}</b> {conf_dots}" if confidence else ""),
        "",
        reason_txt,
        "",
        f"💰 Entry {entry:,.0f}  🛑 SL {sl:,.0f} ({sl_pct:.1f}%)",
        f"🎯 TP1 {tp1:,.0f} (+{tp1_pct:.1f}%)  TP2 {tp2:,.0f} (+{tp2_pct:.1f}%)",
        f"⚖️ R/R 1:{rr:.1f}  ·  Position Size ~{pos_size:.0f}%",
    ]
    return "\n".join(lines) + "\n"


def send_daily_signals(
    signals: list,
    regime,
    sector_rankings: list = None,
    funnel: Optional[dict] = None,
) -> bool:
    """
    Kirim newsletter sinyal harian. `signals` adalah list StockAnalysis
    (objek langsung dari scanner, bukan dict DB) — lihat catatan modul.
    """
    log.info(f"Mengirim {len(signals)} sinyal ke Telegram...")

    parts = [_format_newsletter_header(regime, funnel)]

    if sector_rankings:
        parts.append(_format_sector_summary(sector_rankings, top_n=3))

    strong_buy = sum(1 for s in signals if _ss(_getattr_safe(s, "score.signal_type")) == "STRONG_BUY")
    buy_count  = sum(1 for s in signals if _ss(_getattr_safe(s, "score.signal_type")) == "BUY")

    if not signals:
        r = _ss(_getattr_safe(regime, "regime"), "")
        parts.append(
            "🌙 <b>Tidak ada sinyal hari ini</b>\n\n"
            "<i>Tidak ada saham yang memenuhi standar kualitas sistem hari ini.\n\n"
            "Menunggu peluang terbaik lebih baik daripada mengambil peluang "
            "yang kurang berkualitas.</i>\n"
        )
        if r == "BEAR":
            ihsg_rsi = _sf(_getattr_safe(regime, "ihsg_rsi", 50))
            parts.append(
                f"<i>Market BEAR (RSI IHSG {ihsg_rsi:.0f}) — threshold sinyal "
                f"otomatis diperketat untuk melindungi modal.</i>\n"
            )
    else:
        parts.append(
            f"🎯 <b>{len(signals)} SINYAL TERBAIK</b> "
            f"({strong_buy} 🚀 Strong Buy + {buy_count} 🟢 Buy)\n"
        )
        for i, analysis in enumerate(signals, 1):
            parts.append(_format_signal_card(analysis, i))

    parts.append(DIV)
    parts.append(f"✦ <b>SINYAL DARI LANGIT</b> · {len(signals)} sinyal aktif")
    parts.append("<i>Bukan rekomendasi investasi. Selalu DYOR & kelola risiko.</i>")

    message = "\n".join(parts)
    ok = _split_and_send(message)

    if ok:
        log.info("✓ Sinyal berhasil dikirim ke Telegram")
    else:
        log.error("✗ Gagal kirim sinyal ke Telegram")
    return ok


# ════════ PRE-MARKET ALERT ═════════════════════════════════════════════

def send_market_open_alert(regime) -> bool:
    """
    Alert pre-market (08:30 WIB). Regime dari DATABASE (hasil scan
    kemarin, lihat runner.py cmd_pre_market) — data di sini adalah
    OBJECT (MarketRegime dataclass), bukan dict, karena get_latest_regime()
    sudah mengembalikan dataclass yang sama.

    Query tambahan ke tabel `signals` untuk reminder sinyal kemarin
    MEMANG pakai dict (baris database mentah) — kolom baru (confidence
    dkk) diakses dengan .get() aman untuk baris lama sebelum migration.
    """
    r          = _ss(_getattr_safe(regime, "regime"), "N/A")
    emoji      = REGIME_EMOJI.get(r, "📊")
    ihsg_close = _sf(_getattr_safe(regime, "ihsg_close"))
    ihsg_rsi   = _sf(_getattr_safe(regime, "ihsg_rsi"))
    change_5d  = _sf(_getattr_safe(regime, "change_5d"))

    regime_desc = {
        "BULL":     "✅ Kondisi bagus untuk trading",
        "SIDEWAYS": "⚠️ Selektif — pilih score tinggi",
        "BEAR":     "🚫 Hati-hati — kurangi eksposur",
    }.get(r, "")

    active_lines = []
    try:
        from src.core.database import get_db
        db = get_db()
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        result = (
            db.table("signals")
            .select("ticker,signal_type,composite_score,confidence")
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
                conf  = s.get("confidence")
                se    = "🚀" if s.get("signal_type") == "STRONG_BUY" else "🟢"
                conf_txt = f" · {_he(conf)}" if conf else ""
                active_lines.append(f"  {se} <b>{tk}</b> {st} (Skor {sc:.0f}{conf_txt})")
    except Exception:
        pass

    active_text = "\n".join(active_lines)

    lines = [
        "✦ <b>MARKET AKAN BUKA</b>",
        f"<i>{_now_wib()}</i>",
        DIV,
        f"{emoji} Regime: <b>{r}</b>  ·  {regime_desc}",
        "",
        f"📍 IHSG Terakhir : Rp{ihsg_close:,.0f}",
        f"📊 RSI IHSG      : {ihsg_rsi:.1f}",
        f"🔄 Change 5 Hari : {change_5d:+.1f}%",
        active_text,
        DIV,
        "<i>⏰ Sinyal baru dikirim ~17:30 WIB</i>",
    ]
    msg = "\n".join(lines)
    return _send_message(msg)


# ════════ TP/SL NOTIFICATION ════════════════════════════════════════════

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
        DIV2,
        f"📌 Saham: <b>{_he(ticker.replace('.JK',''))}</b>",
        f"💹 Harga: Rp{price:,.0f}",
        f"📍 Entry: Rp{entry_price:,.0f}",
    ]
    if pnl_line:
        lines.append(pnl_line)
    lines += [
        f"🕐 Waktu: {_now_wib()}",
        DIV2,
        "<i>Auto-monitor oleh Sinyal Dari Langit</i>",
    ]
    return _send_message("\n".join(lines))


# ════════ WEEKLY REPORT ══════════════════════════════════════════════

def send_weekly_report(stats: dict) -> bool:
    """
    Laporan mingguan premium — dipanggil dari runner.py cmd_weekly_report
    yang mengumpulkan `stats` dengan query langsung ke database (lihat
    gather_weekly_stats() di runner.py). Semua field diakses via .get()
    dengan default aman — laporan tetap terkirim walau sebagian data
    tidak tersedia (mis. belum ada backtest minggu ini).
    """
    uni    = stats.get("universe", {})
    db_    = stats.get("database", {})
    bt     = stats.get("backtest", {})
    scan   = stats.get("scanner", {})
    health = stats.get("health", {})
    mkt    = stats.get("market", {})
    top_sectors = stats.get("top_sectors", [])
    top_signals = stats.get("top_signals", [])

    def health_icon(ok):
        return "✅" if ok else "❌"

    lines = [
        "✦ <b>WEEKLY REPORT</b>",
        f"<i>{_now_wib()}</i>",
        DIV,
        "",
        "🌐 <b>UNIVERSE</b>",
        f"  Total saham aktif : {uni.get('total', 'N/A')}",
        f"  Penambahan        : {uni.get('added', 'N/A')}",
        f"  Delisting         : {uni.get('removed', 'N/A')}",
        "",
        "🗄️ <b>DATABASE</b>",
        f"  Status  : {health_icon(db_.get('healthy', False))} {db_.get('status', 'N/A')}",
        f"  Cleanup : {db_.get('cleanup_note', 'Log lama (>30 hari) dibersihkan')}",
        "",
        "🔬 <b>BACKTEST</b>",
    ]

    if bt.get("count"):
        lines += [
            f"  Saham dibacktest : {bt.get('count')}",
            f"  Avg Win Rate     : {_sf(bt.get('avg_win_rate'))*100:.1f}%",
            f"  Avg Profit Factor: {_sf(bt.get('avg_profit_factor')):.2f}",
            f"  Avg Sharpe       : {_sf(bt.get('avg_sharpe')):.2f}",
        ]
        if bt.get("best_ticker"):
            lines.append(
                f"  🏆 Strategi Terbaik: <b>{_he(bt['best_ticker'])}</b> "
                f"(WR {_sf(bt.get('best_win_rate'))*100:.0f}%)"
            )
    else:
        lines.append("  <i>Belum ada hasil backtest minggu ini</i>")

    lines += [
        "",
        "📊 <b>SCANNER STATISTICS</b>",
        f"  Jumlah scan  : {scan.get('total_runs', 'N/A')}",
        f"  STRONG BUY   : {scan.get('strong_buy', 'N/A')}",
        f"  BUY          : {scan.get('buy', 'N/A')}",
        f"  WATCHLIST    : {scan.get('watchlist', 'N/A')}",
        "",
        "🩺 <b>SYSTEM HEALTH</b>",
        f"  Database : {health_icon(health.get('database', False))}",
        f"  Telegram : {health_icon(health.get('telegram', False))}",
        f"  GitHub   : {health_icon(health.get('github', True))}",
        f"  Supabase : {health_icon(health.get('supabase', False))}",
        "",
        "🧭 <b>MARKET SUMMARY</b>",
        f"  Regime  : {REGIME_EMOJI.get(mkt.get('regime',''),'📊')} {mkt.get('regime', 'N/A')}",
        f"  Breadth : {mkt.get('breadth', 'N/A')}",
        f"  Strength (ADX): {mkt.get('strength', 'N/A')}",
    ]

    if top_sectors:
        lines.append("")
        lines.append("🏭 <b>TOP 5 SEKTOR</b>")
        for i, sec in enumerate(top_sectors[:5], 1):
            lines.append(f"  #{i} {_he(sec.get('sector',''))} ({_sf(sec.get('return_5d')):+.1f}% 5D)")

    if top_signals:
        lines.append("")
        lines.append("🏆 <b>TOP 5 SINYAL MINGGU INI</b>")
        for i, sig in enumerate(top_signals[:5], 1):
            tk = _ss(sig.get("ticker","")).replace(".JK","")
            sc = _sf(sig.get("composite_score"))
            st_ = _ss(sig.get("signal_type",""))
            se = SIGNAL_EMOJI.get(st_, "⚪")
            lines.append(f"  #{i} {se} <b>{tk}</b> — Skor {sc:.0f}")

    lines += [
        "",
        DIV,
        "<i>✦ Sinyal Dari Langit — laporan otomatis mingguan</i>",
    ]

    return _split_and_send("\n".join(lines))


def send_daily_summary(summary: dict) -> bool:
    """Dipertahankan untuk backward-compat (dipanggil di tempat lain jika ada)."""
    lines = [
        "📋 <b>RINGKASAN HARIAN</b>",
        f"<i>{_now_wib()}</i>",
        DIV,
        "",
        "📊 <b>Hasil Scan Hari Ini:</b>",
        f"• Saham di-scan : {summary.get('stocks_scanned', 0)}",
        f"• STRONG BUY   : {summary.get('strong_buy', 0)} 🚀",
        f"• BUY          : {summary.get('buy', 0)} 🟢",
        f"• WATCHLIST    : {summary.get('watchlist', 0)} 👀",
        "",
        f"🏛️ <b>Market:</b> {_he(str(summary.get('regime', 'N/A')))}",
        f"⏱ <b>Durasi:</b> {summary.get('duration_seconds', 0):.0f}s",
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
        "⚠️ <b>HEALTH ALERT</b>",
        f"<i>{_now_wib()}</i>",
        DIV2,
        f"Status: <b>{_he(overall.upper())}</b>",
        "",
    ] + comp_lines + [
        DIV2,
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
