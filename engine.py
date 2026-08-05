"""
DAILY SIGNAL — Generate BOT_DAILY_SIGNAL.pdf
Dokumentasi profesional lengkap (12 bab + FAQ 50 pertanyaan)
"""

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.lib.colors import (
    HexColor, white, black, Color
)
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, PageBreak,
    Table, TableStyle, HRFlowable, KeepTogether
)
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_JUSTIFY
from reportlab.platypus.flowables import Flowable
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
import os

# ── Colors ─────────────────────────────────────────────────────────
C_DARK_BG   = HexColor("#0F3460")
C_ACCENT    = HexColor("#00FF88")
C_ACCENT2   = HexColor("#4488FF")
C_WARN      = HexColor("#FFD700")
C_DANGER    = HexColor("#FF4757")
C_LIGHT_BG  = HexColor("#F0F4FF")
C_BORDER    = HexColor("#C0D0E8")
C_TEXT_DARK = HexColor("#1A1A2E")
C_TEXT_MID  = HexColor("#444466")

# ── Document Setup ─────────────────────────────────────────────────
OUTPUT_PATH = "/mnt/user-data/outputs/BOT_DAILY_SIGNAL.pdf"
os.makedirs("/mnt/user-data/outputs", exist_ok=True)

PAGE_W, PAGE_H = A4
MARGIN = 2.0 * cm


def build_styles():
    base = getSampleStyleSheet()

    styles = {
        "cover_title": ParagraphStyle(
            "cover_title",
            fontSize=32,
            fontName="Helvetica-Bold",
            textColor=C_ACCENT,
            alignment=TA_CENTER,
            spaceAfter=10,
        ),
        "cover_sub": ParagraphStyle(
            "cover_sub",
            fontSize=16,
            fontName="Helvetica",
            textColor=white,
            alignment=TA_CENTER,
            spaceAfter=6,
        ),
        "cover_version": ParagraphStyle(
            "cover_version",
            fontSize=11,
            fontName="Helvetica",
            textColor=HexColor("#AABBCC"),
            alignment=TA_CENTER,
        ),
        "chapter_heading": ParagraphStyle(
            "chapter_heading",
            fontSize=22,
            fontName="Helvetica-Bold",
            textColor=C_DARK_BG,
            spaceBefore=16,
            spaceAfter=10,
            borderPad=8,
        ),
        "section_heading": ParagraphStyle(
            "section_heading",
            fontSize=14,
            fontName="Helvetica-Bold",
            textColor=C_DARK_BG,
            spaceBefore=12,
            spaceAfter=5,
        ),
        "subsection": ParagraphStyle(
            "subsection",
            fontSize=12,
            fontName="Helvetica-Bold",
            textColor=C_ACCENT2,
            spaceBefore=8,
            spaceAfter=4,
        ),
        "body": ParagraphStyle(
            "body",
            fontSize=10.5,
            fontName="Helvetica",
            textColor=C_TEXT_DARK,
            leading=16,
            spaceAfter=6,
            alignment=TA_JUSTIFY,
        ),
        "bullet": ParagraphStyle(
            "bullet",
            fontSize=10.5,
            fontName="Helvetica",
            textColor=C_TEXT_DARK,
            leading=15,
            leftIndent=16,
            firstLineIndent=-8,
            spaceAfter=3,
        ),
        "code": ParagraphStyle(
            "code",
            fontSize=9,
            fontName="Courier",
            textColor=C_TEXT_DARK,
            backColor=C_LIGHT_BG,
            leading=13,
            leftIndent=10,
            rightIndent=10,
            spaceBefore=4,
            spaceAfter=6,
            borderPad=6,
        ),
        "note": ParagraphStyle(
            "note",
            fontSize=10,
            fontName="Helvetica-Oblique",
            textColor=C_TEXT_MID,
            leading=14,
            leftIndent=12,
            spaceAfter=6,
        ),
        "warning": ParagraphStyle(
            "warning",
            fontSize=10.5,
            fontName="Helvetica-Bold",
            textColor=C_DANGER,
            spaceAfter=6,
        ),
        "toc_entry": ParagraphStyle(
            "toc_entry",
            fontSize=11,
            fontName="Helvetica",
            textColor=C_TEXT_DARK,
            spaceAfter=4,
        ),
        "faq_q": ParagraphStyle(
            "faq_q",
            fontSize=11,
            fontName="Helvetica-Bold",
            textColor=C_DARK_BG,
            spaceBefore=10,
            spaceAfter=2,
        ),
        "faq_a": ParagraphStyle(
            "faq_a",
            fontSize=10.5,
            fontName="Helvetica",
            textColor=C_TEXT_DARK,
            leading=15,
            leftIndent=12,
            spaceAfter=4,
        ),
    }
    return styles


def S(text): return Spacer(1, text)
def HR(): return HRFlowable(width="100%", thickness=1, color=C_BORDER, spaceAfter=6)


def chapter_title(text, styles):
    """Create a styled chapter title block."""
    data = [[Paragraph(text, styles["chapter_heading"])]]
    tbl = Table(data, colWidths=[PAGE_W - 2*MARGIN])
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,-1), C_LIGHT_BG),
        ("LEFTPADDING", (0,0), (-1,-1), 12),
        ("RIGHTPADDING", (0,0), (-1,-1), 12),
        ("TOPPADDING", (0,0), (-1,-1), 10),
        ("BOTTOMPADDING", (0,0), (-1,-1), 10),
        ("LINEBELOW", (0,0), (-1,-1), 3, C_ACCENT2),
    ]))
    return tbl


def info_table(rows, styles, col_widths=None):
    """Create a styled 2-column info table."""
    col_widths = col_widths or [5*cm, PAGE_W - 2*MARGIN - 5*cm - 0.5*cm]
    data = [[Paragraph(f"<b>{k}</b>", styles["body"]), Paragraph(v, styles["body"])]
            for k, v in rows]
    tbl = Table(data, colWidths=col_widths, repeatRows=0)
    tbl.setStyle(TableStyle([
        ("GRID", (0,0), (-1,-1), 0.5, C_BORDER),
        ("BACKGROUND", (0,0), (0,-1), C_LIGHT_BG),
        ("VALIGN", (0,0), (-1,-1), "TOP"),
        ("LEFTPADDING", (0,0), (-1,-1), 8),
        ("RIGHTPADDING", (0,0), (-1,-1), 8),
        ("TOPPADDING", (0,0), (-1,-1), 6),
        ("BOTTOMPADDING", (0,0), (-1,-1), 6),
    ]))
    return tbl


def build_pdf():
    story = []
    styles = build_styles()
    S_ = lambda n: Spacer(1, n)

    # ════════════════════════════════════════════════════════════
    # COVER PAGE
    # ════════════════════════════════════════════════════════════
    cover_bg = Table(
        [[Paragraph("📈 DAILY SIGNAL", styles["cover_title"]),
          Paragraph("Sistem Sinyal Trading Saham BEI<br/>100% Otomatis &amp; Gratis", styles["cover_sub"]),
          Paragraph("Dokumentasi Teknis v1.0 | 2025", styles["cover_version"]),
          S_(1*cm),
          Paragraph("GitHub Actions &bull; Supabase &bull; Streamlit &bull; Telegram", styles["cover_version"]),
        ]],
        colWidths=[PAGE_W - 2*MARGIN],
    )
    cover_bg.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,-1), C_DARK_BG),
        ("ALIGN", (0,0), (-1,-1), "CENTER"),
        ("TOPPADDING", (0,0), (-1,-1), 80),
        ("BOTTOMPADDING", (0,0), (-1,-1), 80),
    ]))
    story.append(cover_bg)
    story.append(PageBreak())

    # ════════════════════════════════════════════════════════════
    # DAFTAR ISI
    # ════════════════════════════════════════════════════════════
    story.append(chapter_title("DAFTAR ISI", styles))
    story.append(S_(0.5*cm))

    toc_items = [
        ("BAB 1", "Pengenalan Sistem"),
        ("BAB 2", "Persiapan Akun"),
        ("BAB 3", "Instalasi dari Nol"),
        ("BAB 4", "Konfigurasi"),
        ("BAB 5", "Deployment"),
        ("BAB 6", "Cara Menjalankan Sistem"),
        ("BAB 7", "Cara Membaca Dashboard"),
        ("BAB 8", "Cara Mengelola Portfolio"),
        ("BAB 9", "Maintenance"),
        ("BAB 10", "Disaster Recovery"),
        ("BAB 11", "FAQ (50 Pertanyaan)"),
        ("BAB 12", "Roadmap v3"),
    ]
    for bab, judul in toc_items:
        story.append(Paragraph(f"  <b>{bab}</b>  —  {judul}", styles["toc_entry"]))
    story.append(PageBreak())

    # ════════════════════════════════════════════════════════════
    # BAB 1 — PENGENALAN
    # ════════════════════════════════════════════════════════════
    story.append(chapter_title("BAB 1 — Pengenalan Sistem", styles))
    story.append(S_(0.3*cm))

    story.append(Paragraph("1.1 Tujuan Sistem", styles["section_heading"]))
    story.append(Paragraph(
        "DAILY SIGNAL adalah sistem analisis teknikal saham Bursa Efek Indonesia (BEI) yang "
        "berjalan sepenuhnya otomatis tanpa memerlukan komputer lokal menyala atau VPS berbayar. "
        "Sistem ini memanfaatkan layanan gratis (GitHub Actions, Supabase, Streamlit) untuk menghasilkan "
        "sinyal trading yang konsisten, deterministic, dan dapat diaudit.",
        styles["body"],
    ))

    story.append(Paragraph("Tujuan Utama:", styles["subsection"]))
    goals = [
        "Memonitor seluruh saham BEI setiap hari secara otomatis",
        "Menghasilkan sinyal trading berbasis analisis teknikal murni (bukan AI/opini)",
        "Mengirim sinyal ke Telegram setelah market tutup (17:30 WIB)",
        "Menyediakan dashboard online yang bisa diakses dari HP",
        "Melacak portfolio, trade journal, dan performa strategi",
        "Berjalan 100% gratis menggunakan free tier layanan cloud",
    ]
    for g in goals:
        story.append(Paragraph(f"• {g}", styles["bullet"]))

    story.append(Paragraph("1.2 Arsitektur Sistem", styles["section_heading"]))
    story.append(Paragraph(
        "Sistem menggunakan arsitektur event-driven berbasis cloud dengan komponen utama sebagai berikut:",
        styles["body"],
    ))

    arch_data = [
        ["Komponen", "Teknologi", "Fungsi"],
        ["Scheduler", "GitHub Actions (gratis)", "Menjalankan scan otomatis setiap hari"],
        ["Database", "Supabase PostgreSQL (gratis)", "Menyimpan harga, sinyal, portfolio"],
        ["Data Provider", "Yahoo Finance via yfinance", "Data OHLCV semua saham BEI"],
        ["TA Engine", "Python + pandas (custom)", "Hitung indikator teknikal"],
        ["Scoring Engine", "Rule-based (0-100)", "Composite score deterministik"],
        ["Notifikasi", "Telegram Bot API", "Kirim sinyal ke grup/channel"],
        ["Dashboard", "Streamlit (gratis)", "Visualisasi sinyal & portfolio"],
    ]
    arch_tbl = Table(arch_data, colWidths=[3.5*cm, 5*cm, 8*cm])
    arch_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,0), C_DARK_BG),
        ("TEXTCOLOR", (0,0), (-1,0), white),
        ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"),
        ("FONTSIZE", (0,0), (-1,-1), 9),
        ("GRID", (0,0), (-1,-1), 0.5, C_BORDER),
        ("VALIGN", (0,0), (-1,-1), "TOP"),
        ("LEFTPADDING", (0,0), (-1,-1), 6),
        ("TOPPADDING", (0,0), (-1,-1), 5),
        ("BOTTOMPADDING", (0,0), (-1,-1), 5),
        ("ROWBACKGROUNDS", (0,1), (-1,-1), [white, C_LIGHT_BG]),
    ]))
    story.append(arch_tbl)
    story.append(S_(0.3*cm))

    story.append(Paragraph("1.3 Alur Kerja Harian", styles["section_heading"]))
    steps = [
        ("08:30 WIB", "GitHub Actions menjalankan job pre-market — deteksi regime IHSG, kirim alert Telegram"),
        ("16:30 WIB", "Market BEI tutup"),
        ("17:30 WIB", "GitHub Actions menjalankan full daily scan"),
        ("17:31 WIB", "Universe Manager memastikan semua saham BEI terdaftar"),
        ("17:32 WIB", "Incremental Data Updater download OHLCV yang belum ada"),
        ("17:35 WIB", "TA Engine hitung indikator untuk semua saham (parallel)"),
        ("17:38 WIB", "Regime Engine + Sector Engine dijalankan"),
        ("17:40 WIB", "Composite Score dihitung, sinyal difilter dan diranking"),
        ("17:42 WIB", "Top sinyal dikirim ke Telegram"),
        ("17:45 WIB", "Sinyal disimpan ke database, portfolio snapshot disimpan"),
    ]
    for time_str, desc in steps:
        story.append(Paragraph(f"<b>{time_str}</b> — {desc}", styles["bullet"]))

    story.append(PageBreak())

    # ════════════════════════════════════════════════════════════
    # BAB 2 — PERSIAPAN AKUN
    # ════════════════════════════════════════════════════════════
    story.append(chapter_title("BAB 2 — Persiapan Akun", styles))
    story.append(S_(0.3*cm))

    accs = [
        ("2.1 GitHub", "github.com", "Repository kode + GitHub Actions scheduler (gratis)"),
        ("2.2 Supabase", "supabase.com", "Database PostgreSQL cloud (free tier: 500MB, 2 projects)"),
        ("2.3 Telegram", "telegram.org", "Bot notifikasi sinyal"),
        ("2.4 Streamlit", "share.streamlit.io", "Hosting dashboard (gratis, 1 app)"),
    ]
    for name, url, desc in accs:
        story.append(Paragraph(f"<b>{name}</b>", styles["subsection"]))
        story.append(Paragraph(f"URL: {url}", styles["note"]))
        story.append(Paragraph(desc, styles["body"]))
        story.append(Paragraph(
            "Daftar dengan email. Tidak diperlukan kartu kredit untuk free tier.",
            styles["note"],
        ))

    story.append(Paragraph("2.5 Telegram Bot Token", styles["subsection"]))
    steps_tg = [
        "Buka aplikasi Telegram",
        "Cari @BotFather",
        "Kirim pesan: /newbot",
        "Ikuti instruksi: masukkan nama bot dan username (harus diakhiri 'bot')",
        "Simpan token yang diberikan (format: 1234567890:AAH...)",
        "Cari @userinfobot untuk mendapatkan Chat ID pribadi Anda",
        "Atau tambahkan bot ke grup dan gunakan getUpdates API untuk Chat ID grup",
    ]
    for i, s in enumerate(steps_tg, 1):
        story.append(Paragraph(f"{i}. {s}", styles["bullet"]))

    story.append(PageBreak())

    # ════════════════════════════════════════════════════════════
    # BAB 3 — INSTALASI
    # ════════════════════════════════════════════════════════════
    story.append(chapter_title("BAB 3 — Instalasi dari Nol", styles))
    story.append(S_(0.3*cm))

    story.append(Paragraph("3.1 Setup Database Supabase", styles["section_heading"]))
    db_steps = [
        "Login ke supabase.com → klik 'New Project'",
        "Isi nama project: daily-signal, pilih region terdekat (Singapore), set password database",
        "Tunggu project selesai dibuat (~2 menit)",
        "Klik menu 'SQL Editor' di sidebar kiri",
        "Buka file migrations/001_initial_schema.sql dari repository",
        "Paste seluruh isi file ke SQL Editor → klik 'Run'",
        "Pastikan muncul pesan: '✅ DAILY SIGNAL Schema berhasil dibuat!'",
        "Pergi ke Settings → API → copy 'Project URL' dan 'service_role' key",
    ]
    for i, s in enumerate(db_steps, 1):
        story.append(Paragraph(f"{i}. {s}", styles["bullet"]))

    story.append(Paragraph("3.2 Fork Repository GitHub", styles["section_heading"]))
    story.append(Paragraph(
        "Fork repository DAILY SIGNAL ke akun GitHub Anda. Semua kode sudah termasuk "
        "GitHub Actions workflow yang akan berjalan otomatis.",
        styles["body"],
    ))

    story.append(Paragraph("3.3 Setup GitHub Secrets", styles["section_heading"]))
    story.append(Paragraph(
        "Secrets adalah cara aman menyimpan API keys tanpa expose ke kode. "
        "Masuk ke repository → Settings → Secrets and variables → Actions → New repository secret.",
        styles["body"],
    ))
    secrets_data = [
        ["Secret Name", "Nilai", "Cara Mendapatkan"],
        ["SUPABASE_URL", "https://xxx.supabase.co", "Supabase → Settings → API → Project URL"],
        ["SUPABASE_SERVICE_KEY", "eyJ...", "Supabase → Settings → API → service_role"],
        ["TELEGRAM_BOT_TOKEN", "1234:AAH...", "Dari @BotFather di Telegram"],
        ["TELEGRAM_CHAT_ID", "-100123456", "Dari getUpdates API atau @userinfobot"],
    ]
    sec_tbl = Table(secrets_data, colWidths=[5*cm, 5*cm, 7*cm])
    sec_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,0), C_DARK_BG),
        ("TEXTCOLOR", (0,0), (-1,0), white),
        ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"),
        ("FONTSIZE", (0,0), (-1,-1), 9),
        ("GRID", (0,0), (-1,-1), 0.5, C_BORDER),
        ("VALIGN", (0,0), (-1,-1), "TOP"),
        ("LEFTPADDING", (0,0), (-1,-1), 6),
        ("TOPPADDING", (0,0), (-1,-1), 5),
        ("ROWBACKGROUNDS", (0,1), (-1,-1), [white, C_LIGHT_BG]),
    ]))
    story.append(sec_tbl)
    story.append(PageBreak())

    # ════════════════════════════════════════════════════════════
    # BAB 4 — KONFIGURASI
    # ════════════════════════════════════════════════════════════
    story.append(chapter_title("BAB 4 — Konfigurasi", styles))
    story.append(S_(0.3*cm))

    story.append(Paragraph("4.1 Environment Variables", styles["section_heading"]))
    story.append(Paragraph(
        "Semua konfigurasi disimpan sebagai environment variables, bukan hardcoded dalam kode. "
        "File .env.example tersedia sebagai template.",
        styles["body"],
    ))

    env_vars = [
        ["Variable", "Default", "Keterangan"],
        ["MIN_PRICE", "100", "Minimum harga saham (Rp) — filter saham gorengan"],
        ["MIN_VOLUME", "500000", "Minimum volume harian — filter saham tidak likuid"],
        ["MAX_PUMP_PCT", "7.0", "Max kenaikan 3 hari terakhir (%) — anti gorengan"],
        ["TOP_N_SIGNALS", "10", "Jumlah sinyal teratas yang dikirim ke Telegram"],
        ["SCAN_BATCH_SIZE", "50", "Jumlah saham per batch untuk parallel download"],
        ["LOG_LEVEL", "INFO", "Level log: DEBUG/INFO/WARNING/ERROR/CRITICAL"],
    ]
    env_tbl = Table(env_vars, colWidths=[5.5*cm, 3*cm, 8.5*cm])
    env_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,0), C_DARK_BG),
        ("TEXTCOLOR", (0,0), (-1,0), white),
        ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"),
        ("FONTSIZE", (0,0), (-1,-1), 9),
        ("GRID", (0,0), (-1,-1), 0.5, C_BORDER),
        ("ROWBACKGROUNDS", (0,1), (-1,-1), [white, C_LIGHT_BG]),
        ("LEFTPADDING", (0,0), (-1,-1), 6),
        ("TOPPADDING", (0,0), (-1,-1), 5),
    ]))
    story.append(env_tbl)

    story.append(Paragraph("4.2 Scoring Weights", styles["section_heading"]))
    story.append(Paragraph(
        "Bobot composite scoring dapat disesuaikan. Total HARUS = 100.",
        styles["body"],
    ))
    weights = [
        ("WEIGHT_TREND", "30", "EMA alignment, posisi harga vs EMA"),
        ("WEIGHT_MOMENTUM", "25", "RSI zone, MACD direction & crossover"),
        ("WEIGHT_VOLUME", "20", "Volume ratio, volume spike"),
        ("WEIGHT_STRENGTH", "15", "ADX trend strength, Relative Strength vs IHSG"),
        ("WEIGHT_VOLATILITY", "10", "ATR position, Bollinger Band width"),
    ]
    for var, val, desc in weights:
        story.append(Paragraph(f"• <b>{var}</b> = {val}  — {desc}", styles["bullet"]))

    story.append(PageBreak())

    # ════════════════════════════════════════════════════════════
    # BAB 5 — DEPLOYMENT
    # ════════════════════════════════════════════════════════════
    story.append(chapter_title("BAB 5 — Deployment", styles))

    story.append(Paragraph("5.1 Deploy ke GitHub Actions", styles["section_heading"]))
    deploy_steps = [
        "Push semua kode ke repository GitHub",
        "Pergi ke tab 'Actions' di repository",
        "Klik 'I understand my workflows, go ahead and enable them'",
        "Workflow akan otomatis berjalan sesuai jadwal cron",
        "Test manual: Actions → Daily Signal → Run workflow → full_scan",
        "Cek log di tab Actions untuk memastikan tidak ada error",
    ]
    for i, s in enumerate(deploy_steps, 1):
        story.append(Paragraph(f"{i}. {s}", styles["bullet"]))

    story.append(Paragraph("5.2 Deploy Dashboard ke Streamlit", styles["section_heading"]))
    st_steps = [
        "Buka share.streamlit.io → Login dengan GitHub",
        "Klik 'New app' → pilih repository daily-signal",
        "Main file path: dashboard.py",
        "Klik 'Advanced settings' → Secrets → paste isi .env Anda",
        "Klik 'Deploy' → tunggu ~2 menit",
        "Dashboard siap diakses dari URL yang diberikan",
        "Bagikan URL ke HP — dashboard responsif untuk mobile",
    ]
    for i, s in enumerate(st_steps, 1):
        story.append(Paragraph(f"{i}. {s}", styles["bullet"]))

    story.append(Paragraph("5.3 Verifikasi Deployment", styles["section_heading"]))
    story.append(Paragraph(
        "Setelah deployment, jalankan health check:",
        styles["body"],
    ))
    story.append(Paragraph(
        "python -m src.runner health_check",
        styles["code"],
    ))
    story.append(Paragraph(
        "Semua komponen harus menunjukkan status 'healthy'. "
        "Jika ada yang 'unhealthy', periksa secrets dan koneksi network.",
        styles["body"],
    ))
    story.append(PageBreak())

    # ════════════════════════════════════════════════════════════
    # BAB 6 — CARA MENJALANKAN
    # ════════════════════════════════════════════════════════════
    story.append(chapter_title("BAB 6 — Cara Menjalankan Sistem", styles))

    story.append(Paragraph("6.1 Mode Otomatis (Rekomendasi)", styles["section_heading"]))
    story.append(Paragraph(
        "Setelah deployment, sistem berjalan otomatis. Tidak perlu tindakan apa pun. "
        "GitHub Actions akan menjalankan scan sesuai jadwal setiap hari bursa.",
        styles["body"],
    ))

    story.append(Paragraph("6.2 Trigger Manual via GitHub", styles["section_heading"]))
    story.append(Paragraph(
        "Jika ingin menjalankan scan di luar jadwal:",
        styles["body"],
    ))
    manual_steps = [
        "Buka repository di GitHub",
        "Klik tab 'Actions'",
        "Pilih 'Daily Signal — Daily Scan'",
        "Klik 'Run workflow'",
        "Pilih mode: full_scan / pre_market / health_check",
        "Klik 'Run workflow' hijau",
    ]
    for i, s in enumerate(manual_steps, 1):
        story.append(Paragraph(f"{i}. {s}", styles["bullet"]))

    story.append(Paragraph("6.3 Monitoring Harian", styles["section_heading"]))
    monitoring = [
        "Pagi (08:30 WIB): Cek pesan Telegram untuk pre-market alert",
        "Sore (17:30+ WIB): Terima sinyal harian di Telegram",
        "Dashboard: Cek Overview setiap hari untuk kondisi market",
        "Mingguan: Cek tab Performance untuk evaluasi strategi",
        "Jika tidak ada pesan Telegram: Cek tab Actions di GitHub untuk error",
    ]
    for m in monitoring:
        story.append(Paragraph(f"• {m}", styles["bullet"]))
    story.append(PageBreak())

    # ════════════════════════════════════════════════════════════
    # BAB 7 — MEMBACA DASHBOARD
    # ════════════════════════════════════════════════════════════
    story.append(chapter_title("BAB 7 — Cara Membaca Dashboard", styles))

    story.append(Paragraph("7.1 Halaman Overview", styles["section_heading"]))
    overview_items = [
        ("Market Regime", "BULL/SIDEWAYS/BEAR — kondisi pasar saat ini berdasarkan IHSG"),
        ("IHSG", "Harga penutupan IHSG + perubahan 5 hari"),
        ("Sinyal Hari Ini", "Jumlah sinyal STRONG_BUY + BUY yang dihasilkan"),
        ("Posisi Aktif", "Jumlah posisi yang sedang terbuka + unrealized PnL"),
        ("Win Rate", "Persentase trade profitable dari semua trade yang sudah ditutup"),
    ]
    for metric, desc in overview_items:
        story.append(Paragraph(f"• <b>{metric}</b>: {desc}", styles["bullet"]))

    story.append(Paragraph("7.2 Composite Score (0-100)", styles["section_heading"]))
    score_items = [
        ("75-100: STRONG_BUY", "Semua indikator selaras, volume konfirmasi, trend kuat"),
        ("60-74: BUY", "Setup bagus, layak untuk masuk posisi"),
        ("45-59: WATCHLIST", "Menarik tapi belum ada konfirmasi — pantau saja"),
        ("0-44: AVOID", "Tidak memenuhi kriteria minimum — jangan masuk"),
    ]
    for score, desc in score_items:
        story.append(Paragraph(f"• <b>{score}</b> — {desc}", styles["bullet"]))

    story.append(Paragraph("7.3 Risk Management Levels", styles["section_heading"]))
    rm_items = [
        ("Entry", "Harga close saat sinyal dihasilkan"),
        ("Stop Loss", "Entry - (1.5 x ATR) — jual rugi jika harga turun ke sini"),
        ("Target 1 (TP1)", "Entry + (1.5 x ATR) — ambil profit pertama di sini"),
        ("Target 2 (TP2)", "Entry + (2.5 x ATR) — ambil profit penuh di sini"),
        ("R/R Ratio", "Perbandingan potensi keuntungan vs risiko (>1 = lebih banyak untung)"),
        ("Position Size", "Saran % modal untuk posisi ini (berbasis 1% risk rule)"),
    ]
    story.append(info_table(rm_items, styles))
    story.append(PageBreak())

    # ════════════════════════════════════════════════════════════
    # BAB 8 — PORTFOLIO
    # ════════════════════════════════════════════════════════════
    story.append(chapter_title("BAB 8 — Cara Mengelola Portfolio", styles))

    story.append(Paragraph("8.1 Menambah Posisi Baru", styles["section_heading"]))
    story.append(Paragraph("Melalui Dashboard Streamlit:", styles["body"]))
    add_pos = [
        "Buka Dashboard → Portfolio",
        "Scroll ke bawah ke form 'Buka Posisi Baru'",
        "Isi: Ticker (tanpa .JK), Harga Entry, Jumlah Saham",
        "Isi SL, TP1, TP2 sesuai sinyal yang diterima",
        "Tulis catatan alasan entry",
        "Klik 'Buka Posisi'",
    ]
    for i, s in enumerate(add_pos, 1):
        story.append(Paragraph(f"{i}. {s}", styles["bullet"]))

    story.append(Paragraph("8.2 Menutup Posisi", styles["section_heading"]))
    story.append(Paragraph(
        "Saat ini penutupan posisi dilakukan melalui Supabase Dashboard (SQL) atau "
        "dengan memanggil fungsi close_position() dari Python. "
        "Fitur UI untuk menutup posisi dijadwalkan di versi berikutnya.",
        styles["body"],
    ))
    story.append(Paragraph(
        "python -c \"from src.portfolio.tracker import close_position; "
        "close_position('POSITION_ID', exit_price=1200, exit_reason='TP1')\"",
        styles["code"],
    ))

    story.append(Paragraph("8.3 Melihat Statistik", styles["section_heading"]))
    perf_items = [
        ("Win Rate", "% trade yang profit dari total trade"),
        ("Profit Factor", "Total gross gain / total gross loss (>1 = strategi profitable)"),
        ("Expectancy", "(WR × avg gain) + (LR × avg loss) — rata-rata return per trade"),
        ("Max Drawdown", "Penurunan maksimum dari peak equity"),
        ("Sharpe Ratio", "Return vs risiko (>1 = baik, >2 = sangat baik)"),
    ]
    story.append(info_table(perf_items, styles))
    story.append(PageBreak())

    # ════════════════════════════════════════════════════════════
    # BAB 9 — MAINTENANCE
    # ════════════════════════════════════════════════════════════
    story.append(chapter_title("BAB 9 — Maintenance", styles))

    story.append(Paragraph("9.1 Update Sistem", styles["section_heading"]))
    update_steps = [
        "Pull perubahan terbaru dari repository",
        "Jalankan migrations SQL jika ada file baru di folder migrations/",
        "Push ke GitHub — GitHub Actions akan otomatis menggunakan kode terbaru",
        "Test dengan health check: python -m src.runner health_check",
    ]
    for i, s in enumerate(update_steps, 1):
        story.append(Paragraph(f"{i}. {s}", styles["bullet"]))

    story.append(Paragraph("9.2 Backup Database", styles["section_heading"]))
    backup_opts = [
        "Manual: Supabase Dashboard → Settings → Database → Backups",
        "Export SQL: Supabase CLI → supabase db dump > backup.sql",
        "Export CSV: Supabase Dashboard → Table Editor → pilih tabel → Export",
    ]
    for b in backup_opts:
        story.append(Paragraph(f"• {b}", styles["bullet"]))

    story.append(Paragraph("9.3 Database Cleanup (Otomatis Sabtu)", styles["section_heading"]))
    story.append(Paragraph(
        "GitHub Actions menjalankan weekly_maintenance setiap Sabtu pagi. "
        "Ini akan menghapus log lama (>30 hari) dan menjalankan backtest mingguan.",
        styles["body"],
    ))

    story.append(Paragraph("9.4 Monitoring GitHub Actions Usage", styles["section_heading"]))
    story.append(Paragraph(
        "GitHub Actions free tier: 2.000 menit/bulan. DAILY SIGNAL menggunakan sekitar "
        "~30 menit/hari (2 run × ~15 menit), total ~600 menit/bulan — jauh di bawah limit. "
        "Pantau usage di: GitHub → Settings → Billing → Minutes used.",
        styles["body"],
    ))
    story.append(PageBreak())

    # ════════════════════════════════════════════════════════════
    # BAB 10 — DISASTER RECOVERY
    # ════════════════════════════════════════════════════════════
    story.append(chapter_title("BAB 10 — Disaster Recovery", styles))

    story.append(Paragraph("10.1 Database Rusak / Data Hilang", styles["section_heading"]))
    dr1 = [
        "Buka Supabase Dashboard → Settings → Database → Backups",
        "Pilih backup terakhir sebelum masalah terjadi → Restore",
        "Jika tidak ada backup: jalankan ulang migrations SQL dari awal",
        "Data harga historis akan di-download ulang secara otomatis pada scan berikutnya",
        "Data sinyal sebelumnya tidak bisa direcovery kecuali ada backup manual",
    ]
    for i, s in enumerate(dr1, 1):
        story.append(Paragraph(f"{i}. {s}", styles["bullet"]))

    story.append(Paragraph("10.2 Token / API Key Hilang atau Expired", styles["section_heading"]))
    dr2_cases = [
        ("Telegram token", "Buat bot baru di @BotFather → update secret TELEGRAM_BOT_TOKEN di GitHub"),
        ("Supabase key", "Supabase → Settings → API → Regenerate key → update secrets"),
        ("Setelah update", "Jalankan health check untuk memastikan semua berfungsi kembali"),
    ]
    for case, action in dr2_cases:
        story.append(Paragraph(f"• <b>{case}</b>: {action}", styles["bullet"]))

    story.append(Paragraph("10.3 GitHub Actions Scheduler Tidak Berjalan", styles["section_heading"]))
    dr3 = [
        "Cek tab Actions di GitHub — apakah ada error di workflow run terakhir?",
        "GitHub menonaktifkan Actions jika repository tidak aktif >60 hari — buka Actions dan re-enable",
        "Cek billing minutes — jika 0 menit tersisa, upgrade atau tunggu bulan berikutnya",
        "Test trigger manual: Actions → workflow → Run workflow",
        "Jika secrets berubah, update di Settings → Secrets",
    ]
    for i, s in enumerate(dr3, 1):
        story.append(Paragraph(f"{i}. {s}", styles["bullet"]))

    story.append(Paragraph("10.4 Yahoo Finance Down / Rate Limit", styles["section_heading"]))
    story.append(Paragraph(
        "Yahoo Finance adalah layanan tidak resmi yang bisa mengalami downtime atau perubahan. "
        "Sistem menggunakan retry otomatis (3x dengan exponential backoff). "
        "Jika tetap gagal, scan akan skip tapi tidak crash. "
        "Data akan diupdate pada scan berikutnya saat Yahoo Finance kembali normal.",
        styles["body"],
    ))
    story.append(PageBreak())

    # ════════════════════════════════════════════════════════════
    # BAB 11 — FAQ
    # ════════════════════════════════════════════════════════════
    story.append(chapter_title("BAB 11 — FAQ (50 Pertanyaan)", styles))

    faqs = [
        # Setup & Akun
        ("1. Apakah sistem ini benar-benar gratis?",
         "Ya, 100% gratis. Menggunakan GitHub Actions (2000 menit/bulan gratis), Supabase (500MB gratis), "
         "Streamlit Community Cloud (gratis untuk 1 app), Yahoo Finance (gratis tanpa API key)."),
        ("2. Berapa lama waktu setup awal?",
         "Sekitar 30-60 menit untuk pertama kali. Setup Supabase ~15 menit, GitHub Secrets ~5 menit, "
         "Streamlit deployment ~10 menit."),
        ("3. Apakah saya perlu pengetahuan coding?",
         "Tidak diperlukan untuk operasi harian. Setup awal memerlukan pemahaman dasar copy-paste "
         "perintah dan konfigurasi web interface."),
        ("4. Berapa saham yang bisa di-monitor?",
         "Seluruh saham BEI (800+ saham). Universe Manager secara otomatis mendeteksi semua saham aktif."),
        ("5. Apakah berjalan di akhir pekan?",
         "GitHub Actions hanya aktif Senin-Jumat (hari bursa). Tidak ada proses yang berjalan di weekend."),
        ("6. Apakah perlu HP/PC menyala?",
         "Tidak. Semua berjalan di cloud. Cukup cek Telegram atau dashboard dari HP kapan saja."),
        ("7. Apa yang terjadi jika Yahoo Finance bermasalah?",
         "Sistem akan retry otomatis 3x. Jika tetap gagal, scan akan skip saham tersebut "
         "dan lanjut ke saham berikutnya. Log error tersimpan di database."),
        ("8. Bisa digunakan untuk saham selain BEI?",
         "Secara teknis bisa dengan modifikasi kode Universe Manager, tapi saat ini fokus pada saham BEI."),
        # Sinyal & Strategi
        ("9. Apakah sinyal selalu akurat?",
         "Tidak ada sistem yang 100% akurat. Backtest menunjukkan win rate 55-70% tergantung saham "
         "dan kondisi pasar. Selalu gunakan stop loss dan money management."),
        ("10. Apa perbedaan STRONG_BUY dan BUY?",
         "STRONG_BUY: score ≥75 — semua indikator selaras dengan konfirmasi volume. "
         "BUY: score 60-74 — setup bagus tapi tidak semua indikator align sempurna."),
        ("11. Apakah AI digunakan untuk menentukan sinyal?",
         "TIDAK. Semua sinyal ditentukan oleh sistem scoring deterministik berbasis rule. "
         "Hasilnya reproducible dan bisa diaudit. AI tidak digunakan dalam pengambilan keputusan."),
        ("12. Kapan sinyal dikirim ke Telegram?",
         "Sekitar 17:30-17:45 WIB setiap hari Senin-Jumat (30-45 menit setelah market tutup)."),
        ("13. Berapa sinyal yang dikirim setiap hari?",
         "Default 10 sinyal teratas (STRONG_BUY dan BUY). Bisa diubah via TOP_N_SIGNALS."),
        ("14. Apakah ada sinyal SELL?",
         "Versi saat ini hanya menghasilkan sinyal BUY (swing trading dari sisi beli). "
         "SELL/SHORT dijadwalkan di versi berikutnya."),
        ("15. Apa itu Composite Score?",
         "Skor 0-100 yang menggabungkan 5 komponen: Trend (30), Momentum (25), Volume (20), "
         "Strength (15), Volatility (10). Skor lebih tinggi = setup lebih kuat."),
        ("16. Bagaimana cara kerja Relative Strength?",
         "Menggunakan Mansfield RS: membandingkan return saham vs return IHSG dalam periode 20 hari. "
         "RS positif = outperform IHSG, RS negatif = underperform."),
        ("17. Apa itu Market Regime?",
         "Klasifikasi kondisi pasar: BULL (semua sistem jalan normal), SIDEWAYS (scoring dikurangi 25%), "
         "BEAR (scoring dikurangi 60%). Membantu menghindari sinyal di kondisi pasar yang tidak mendukung."),
        ("18. Bagaimana Sector Rotation mempengaruhi sinyal?",
         "Saham dari sektor Top 3 mendapat bonus +5 poin. Saham dari sektor Bottom 3 mendapat penalty -5 poin. "
         "Ini mendorong pemilihan saham dari sektor yang sedang kuat."),
        # Risk Management
        ("19. Bagaimana Stop Loss dihitung?",
         "SL = Entry - (1.5 × ATR14). ATR adalah Average True Range 14 hari, "
         "ukuran volatilitas khas saham tersebut. Ini memastikan SL tidak terlalu ketat atau terlalu lebar."),
        ("20. Apa itu Position Size yang disarankan?",
         "Berbasis '1% risk rule': jika risiko per saham = 3%, maka position size = 1%/3% = 33% modal. "
         "Maksimal disarankan 25% per posisi."),
        ("21. Bolehkah mengabaikan Stop Loss?",
         "TIDAK disarankan. Stop loss adalah proteksi modal utama. "
         "Tanpa stop loss, satu trade buruk bisa menghapus profit berbulan-bulan."),
        ("22. Apakah comisi termasuk dalam kalkulasi?",
         "Ya, dalam backtest. Komisi BEI: beli 0.19%, jual 0.29% (termasuk PPh 0.1%)."),
        # Portfolio
        ("23. Bagaimana cara menambah posisi?",
         "Melalui Dashboard → Portfolio → form 'Buka Posisi Baru'. Isi ticker, harga, lot, SL, TP."),
        ("24. Bagaimana cara menutup posisi?",
         "Saat ini melalui API Python atau SQL langsung. UI untuk menutup posisi dijadwalkan di v2."),
        ("25. Apakah unrealized PnL update otomatis?",
         "Ya, setiap hari setelah scan harian (~17:40 WIB) harga terbaru diambil dan PnL diupdate."),
        # Teknis
        ("26. Berapa penggunaan GitHub Actions per bulan?",
         "Sekitar 600 menit/bulan (2 run/hari × 15 menit × 20 hari). "
         "Limit free tier adalah 2.000 menit — masih ada sisa 1.400 menit."),
        ("27. Berapa ukuran database Supabase?",
         "Tergantung jumlah saham dan sejarah. Untuk 800 saham dengan 1 tahun harga: ~150MB. "
         "Limit free tier Supabase: 500MB."),
        ("28. Apakah data aman di Supabase?",
         "Supabase menggunakan enkripsi at-rest dan in-transit. Row Level Security (RLS) diaktifkan. "
         "Service key hanya untuk GitHub Actions, bukan untuk akses publik."),
        ("29. Bagaimana cara backup data?",
         "Manual via Supabase Dashboard → Settings → Backups. "
         "Atau export CSV dari Table Editor. Direkomendasikan backup mingguan."),
        ("30. Apakah bisa dijalankan lokal tanpa cloud?",
         "Ya, dengan membuat file .env lokal dan menjalankan python -m src.runner daily_scan. "
         "Tapi scheduler manual — tidak otomatis."),
        # Backtest
        ("31. Apa perbedaan backtesting sistem ini dengan yang lain?",
         "Sistem ini walk-forward: tidak ada look-ahead bias, termasuk biaya komisi, "
         "dan deterministik (hasil sama untuk data yang sama)."),
        ("32. Mengapa backtest tidak menggunakan seluruh saham?",
         "Weekly backtest default 50 saham untuk efisiensi waktu GitHub Actions. "
         "Bisa ditambah via parameter --limit."),
        ("33. Apa itu survivorship bias dan apakah diatasi?",
         "Survivorship bias = hanya backtest saham yang masih ada, bukan yang sudah delisting. "
         "Sistem ini memitigasi dengan Universe Manager yang track saham delisting, "
         "tapi tidak sepenuhnya hilang karena data historis Yahoo terbatas."),
        # Telegram
        ("34. Kapan Telegram mengirim pesan?",
         "Pre-market alert: 08:30 WIB. Sinyal harian: ~17:30 WIB. "
         "TP/SL hit: real-time (melalui monitoring harian)."),
        ("35. Apakah bisa kirim ke multiple grup?",
         "Saat ini satu grup/channel. Multiple destinations bisa ditambahkan dengan memodifikasi "
         "TELEGRAM_CHAT_ID menjadi list dan iterasi di bot.py."),
        ("36. Apa format pesan Telegram?",
         "HTML formatting dengan emoji. Berisi: IHSG info, sector top 3, "
         "daftar sinyal dengan entry/SL/TP/score breakdown."),
        # Dashboard
        ("37. Apakah dashboard bisa diakses dari HP?",
         "Ya, Streamlit responsive untuk mobile. Buka URL dashboard dari browser HP."),
        ("38. Seberapa sering dashboard diupdate?",
         "Dashboard cache data 5 menit. Klik tombol 'Refresh Data' untuk update manual."),
        ("39. Apakah ada password untuk dashboard?",
         "Tidak by default. Untuk privasi, bisa aktifkan Streamlit authentication "
         "atau gunakan Streamlit private apps (berbayar)."),
        # Error & Troubleshooting
        ("40. Tidak ada pesan Telegram hari ini — apa yang salah?",
         "Cek: (1) GitHub Actions → lihat log workflow terakhir, "
         "(2) health check — apakah Telegram token masih valid?, "
         "(3) apakah market libur nasional?"),
        ("41. Dashboard error 'Connection failed'?",
         "Cek Streamlit secrets — apakah SUPABASE_URL dan SERVICE_KEY sudah diisi dengan benar?"),
        ("42. Scan berjalan tapi tidak ada sinyal?",
         "Kemungkinan: (1) Regime BEAR — semua sinyal di-suppress, "
         "(2) Tidak ada saham yang memenuhi score minimum, "
         "(3) Yahoo Finance rate limit — data tidak lengkap."),
        ("43. Backtest selalu FAILED untuk semua saham?",
         "Cek apakah MIN_WIN_RATE terlalu tinggi di config. Default 55%. "
         "Juga pastikan data historis sudah diupdate (minimal 252 baris per saham)."),
        ("44. Error 'SUPABASE_URL tidak diset'?",
         "Pastikan file .env ada dan berisi nilai yang benar. "
         "Atau untuk GitHub Actions, pastikan secrets sudah ditambahkan."),
        ("45. Saham baru tidak muncul di scan?",
         "Universe Manager refresh otomatis setiap Sabtu. "
         "Untuk refresh manual: python -m src.runner refresh_universe"),
        # Strategi Penggunaan
        ("46. Berapa posisi yang ideal dibuka bersamaan?",
         "Tergantung modal. Dengan rule position size 1% risk, "
         "bisa buka 5-10 posisi secara bersamaan dengan diversifikasi sektor."),
        ("47. Apakah sinyal ini untuk trading jangka pendek atau panjang?",
         "Desain untuk swing trading 3-10 hari. TP berbasis ATR biasanya tercapai dalam 5-7 hari."),
        ("48. Apakah WATCHLIST perlu dibeli?",
         "WATCHLIST = pantau saja, belum saatnya beli. Tunggu sinyal naik ke BUY atau STRONG_BUY."),
        ("49. Bagaimana jika IHSG sedang crash besar?",
         "Regime Engine akan mendeteksi BEAR dan mengurangi semua sinyal 60%. "
         "Sinyal yang tersisa score-nya sangat tinggi — pertimbangkan untuk tidak masuk sama sekali."),
        ("50. Apakah perlu cek sinyal setiap hari?",
         "Tidak wajib. Telegram akan memberitahu secara otomatis. "
         "Cukup cek Telegram setelah 17:30 WIB dan tindak lanjuti sinyal yang relevan."),
    ]

    for q, a in faqs:
        story.append(KeepTogether([
            Paragraph(q, styles["faq_q"]),
            Paragraph(a, styles["faq_a"]),
        ]))

    story.append(PageBreak())

    # ════════════════════════════════════════════════════════════
    # BAB 12 — ROADMAP V3
    # ════════════════════════════════════════════════════════════
    story.append(chapter_title("BAB 12 — Roadmap DAILY SIGNAL V3", styles))

    story.append(Paragraph("12.1 Fitur Prioritas Tinggi", styles["section_heading"]))
    high = [
        "Short/SELL signal — sinyal untuk short selling (saham yang lemah)",
        "UI tutup posisi — tombol close position di dashboard tanpa perlu SQL",
        "Alert TP/SL real-time — monitoring harga intraday, bukan hanya harian",
        "Trade journal screenshot — upload screenshot chart langsung dari HP",
        "Multiple Telegram targets — kirim ke beberapa grup sekaligus",
    ]
    for f in high:
        story.append(Paragraph(f"• {f}", styles["bullet"]))

    story.append(Paragraph("12.2 Fitur Jangka Menengah", styles["section_heading"]))
    mid = [
        "IDX Official Provider — integrasi data dari IDX.co.id sebagai alternatif Yahoo",
        "Fundamental Filter — tambahkan filter P/E, PBV untuk stock selection",
        "Alert Watchlist — notifikasi otomatis saat watchlist naik ke BUY",
        "Export laporan — download PDF laporan portfolio dan performa bulanan",
        "Multiple timeframe — konfirmasi sinyal dari D1 + W1 untuk swing trading",
    ]
    for f in mid:
        story.append(Paragraph(f"• {f}", styles["bullet"]))

    story.append(Paragraph("12.3 Fitur Jangka Panjang", styles["section_heading"]))
    long_term = [
        "Options analysis — analisis Call/Put untuk hedging",
        "Backtesting UI — interface visual untuk test strategi baru",
        "Mobile app (PWA) — dashboard yang bisa di-install di homescreen HP",
        "Community signals — berbagi dan diskusi sinyal antar pengguna",
        "Paper trading mode — simulasi trading tanpa uang sungguhan untuk belajar",
        "Integration broker API — order otomatis ke broker yang mendukung API",
    ]
    for f in long_term:
        story.append(Paragraph(f"• {f}", styles["bullet"]))

    story.append(S_(0.5*cm))
    story.append(HR())
    story.append(Paragraph(
        "DAILY SIGNAL v1.0 | Dokumentasi dibuat otomatis | 2025",
        ParagraphStyle("footer", fontSize=9, fontName="Helvetica",
                       textColor=C_TEXT_MID, alignment=TA_CENTER),
    ))
    story.append(Paragraph(
        "Sistem ini bukan rekomendasi investasi. Selalu DYOR. Investasi mengandung risiko.",
        ParagraphStyle("disclaimer", fontSize=8, fontName="Helvetica-Oblique",
                       textColor=C_DANGER, alignment=TA_CENTER),
    ))

    # ── Build PDF ──────────────────────────────────────────────
    def on_page(canvas, doc):
        """Header/footer setiap halaman."""
        canvas.saveState()
        # Header line
        canvas.setStrokeColor(C_ACCENT2)
        canvas.setLineWidth(0.5)
        canvas.line(MARGIN, PAGE_H - MARGIN + 0.3*cm, PAGE_W - MARGIN, PAGE_H - MARGIN + 0.3*cm)
        # Header text
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(C_TEXT_MID)
        canvas.drawString(MARGIN, PAGE_H - MARGIN + 0.5*cm, "DAILY SIGNAL — Dokumentasi Teknis v1.0")
        canvas.drawRightString(PAGE_W - MARGIN, PAGE_H - MARGIN + 0.5*cm, "BEI Stock Scanner")
        # Footer
        canvas.line(MARGIN, MARGIN - 0.2*cm, PAGE_W - MARGIN, MARGIN - 0.2*cm)
        canvas.drawCentredString(PAGE_W/2, MARGIN - 0.5*cm, f"Halaman {doc.page}")
        canvas.restoreState()

    doc = SimpleDocTemplate(
        OUTPUT_PATH,
        pagesize=A4,
        leftMargin=MARGIN,
        rightMargin=MARGIN,
        topMargin=MARGIN + 0.5*cm,
        bottomMargin=MARGIN + 0.5*cm,
        title="DAILY SIGNAL — Dokumentasi Teknis",
        author="DAILY SIGNAL System",
        subject="BEI Stock Scanner Documentation",
    )
    doc.build(story, onFirstPage=on_page, onLaterPages=on_page)
    print(f"✅ PDF berhasil dibuat: {OUTPUT_PATH}")


if __name__ == "__main__":
    build_pdf()
