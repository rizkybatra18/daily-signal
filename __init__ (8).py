"""
DAILY SIGNAL — Universe Manager
Auto-discover dan maintain seluruh universe saham BEI.

═══════════════════════════════════════════════════════════════════
AUDIT NOTE (lihat AUDIT_REPORT_v2.md bagian "Universe Manager Audit")
═══════════════════════════════════════════════════════════════════
Scraping idx.co.id LANGSUNG (baik via halaman resmi maupun endpoint
internal seperti /umbraco/Surface/...) TIDAK dipakai sebagai sumber
utama karena dua alasan konkret hasil riset:

  1. LEGAL — Syarat Penggunaan PT Bursa Efek Indonesia poin 6 secara
     eksplisit melarang "metode web scrapping/crawling" atas Website
     BEI, termasuk untuk tujuan non-komersial.
  2. TEKNIS — idx.co.id memakai bot detection yang memblokir request
     otomatis (dikonfirmasi langsung: request polos ke halaman resmi
     mereka menghasilkan block, terlepas dari endpoint yang dipakai).
     IP range GitHub Actions umumnya juga termasuk yang sering diblok
     oleh sistem anti-bot semacam ini, membuat pendekatan ini rapuh
     bahkan seandainya secara legal diperbolehkan.

Solusi yang dipakai di sini murni via Yahoo Finance (yfinance), yang
memang ditujukan untuk konsumsi otomatis/publik dan tidak melarang
akses terprogram wajar:

  1. UNIVERSE SEED — daftar ~550 ticker BEI aktif yang disusun dari
     pengetahuan umum emiten BEI per sektor (lihat _CURATED_SECTORS).
     Ini BUKAN daftar final yang dipakai mentah — hanya kandidat awal.
  2. VALIDASI — setiap kandidat divalidasi via Yahoo Finance: apakah
     benar-benar masih ada data perdagangan aktif. Ticker yang gagal
     divalidasi (delisting/suspend/salah kode) otomatis tersaring.
  3. PERSISTENCE — hasil validasi disimpan ke tabel `stocks` sebagai
     sumber kebenaran (source of truth) untuk scan berikutnya, bukan
     hardcoded list yang dibaca ulang setiap hari.
  4. EKSPANSI OPSIONAL — jika Anda punya sumber list ticker tambahan
     yang Anda percaya (mis. Google Sheet CSV yang Anda kelola), isi
     env var EXTRA_UNIVERSE_SOURCE_URL — sistem akan menggabungkannya
     ke kandidat sebelum validasi. Kosong = tidak dipakai (default).

Auto-detect:
  - IPO baru      → muncul begitu ticker baru ada di seed/extra source
                     DAN lolos validasi Yahoo (data trading aktif).
  - Delisting     → ticker yang dulu aktif tapi tidak lagi ada data
                     30 hari terakhir di Yahoo → ditandai delisted.
  - Safety guard  → jika hasil validasi tiba-tiba anjlok drastis
                     dibanding universe aktif yang sudah tersimpan
                     (indikasi gangguan Yahoo/network sesaat, BUKAN
                     delisting massal sungguhan), penandaan delisting
                     di-skip otomatis untuk mencegah false-mass-delist.
"""

import time
import threading
import requests
import pandas as pd
import yfinance as yf
from datetime import date, datetime, timedelta
from typing import Optional
from tenacity import retry, stop_after_attempt, wait_exponential

from src.core.config import settings
from src.core.logger import get_logger
from src.core.database import get_db, upsert_stock

log = get_logger("universe_manager")


# ═══════════════════════════════════════════════════════════════════
#  CURATED SEED — dikelompokkan per sektor IDX-IC (11 sektor resmi)
#  ~550 ticker. Ini KANDIDAT AWAL, bukan universe final — semua
#  tetap divalidasi likuiditasnya via Yahoo Finance sebelum dipakai.
# ═══════════════════════════════════════════════════════════════════

_CURATED_SECTORS: dict[str, list[str]] = {

    "Financials": [
        "BBCA", "BBRI", "BMRI", "BBNI", "BBTN", "BNGA", "BDMN", "BNII",
        "BNLI", "BJBR", "BJTM", "BTPN", "BTPS", "PNBN", "PNBS", "NISP",
        "MEGA", "BSIM", "BGTG", "BCIC", "AGRO", "ARTO", "JAGO", "BABP",
        "BACA", "BBHI", "BBMD", "BBYB", "BCAP", "BEKS", "BINA", "BKSW",
        "BMAS", "BNBA", "BRIS", "BSWD", "BVIC", "DNAR", "INPC", "MAYA",
        "MCOR", "NOBU", "PNIN", "SDRA", "AMAR", "AGRS", "BANK", "BSSR",
        "ADMF", "BFIN", "CFIN", "TRUS", "WOMF", "MFIN", "VRNA", "DEFI",
        "PADI", "POOL", "TIFA", "TUGU", "ASBI", "ASDM", "ASJT", "ASMI",
        "ASRM", "LPGI", "MREI", "PNLF", "VINS", "ABDA", "AHAP", "AMAG",
        "ASSA", "JMAS", "MTWI", "PGJO", "PPRO", "BBSI", "BBRM", "OCAP",
        "PEGE", "PLAS", "RELI", "SFAN", "TRIM", "YULE", "APIC", "ARTA",
        "GSMF", "STAR", "VICO", "WICO", "CASA", "ROCK",
    ],

    "Consumer Non-Cyclicals": [
        "UNVR", "ICBP", "INDF", "MYOR", "ROTI", "ULTJ", "CPIN", "JPFA",
        "GGRM", "HMSP", "WIIM", "SIDO", "KLBF", "MLBI", "DLTA", "STTP",
        "AISA", "ALTO", "ADES", "CAMP", "CEKA", "COCO", "DMND", "DSFI",
        "FOOD", "GOOD", "HOKI", "IIKP", "KEJU", "MAIN", "PANI", "PCAR",
        "PSGO", "SKBM", "SKLT", "TBLA", "TGKA", "TAYS", "AALI", "LSIP",
        "SIMP", "SSMS", "DSNG", "SGRO", "SMAR", "ANJT", "BWPT",
        "GZCO", "JAWA", "SMGA", "PALM", "TAPG", "UNSP", "MGRO", "PNGO",
        "CPRO", "CSAP", "DPUM", "IPPE", "SDPC", "AMFG", "TCID", "MBTO",
        "MRAT", "KINO", "UNIC", "PYFA", "BEEF", "CPDW", "CRAB", "OILS",
        "TLDN", "WMPP", "WAPO", "FISH", "LAPD", "BUDI", "EPMT",
        "AYAM", "CBUT", "DAYA", "ENZO", "FAPA", "GUNA", "SUNI", "UDNG",
        "SOTS",
    ],

    "Consumer Cyclicals": [
        "ASII", "MAPI", "ACES", "ERAA", "BUKA", "GOTO", "MNCN", "LPPF",
        "RALS", "MPPA", "HERO", "AMRT", "MIDI", "SCMA", "MSIN",
        "MDIA", "FILM", "EMTK", "KPIG", "PANR", "PZZA", "FAST", "MAPB",
        "MAPA", "TRIS", "BATA", "BAYU", "PDES", "PJAA", "PSKT", "SHID",
        "PANS", "HRTA", "CENT", "CLAY", "GLOB", "TRIO", "AUTO", "SMSM",
        "IMAS", "INDS", "GJTL", "BRAM", "MASA", "GDYR", "SIMA", "SUGI",
        "ARGO", "ERTX", "ESTI", "HDTX", "INDR", "MYTX", "PBRX", "POLY",
        "RICY", "SRIL", "SSTM", "TFCO", "UNIT", "VOKS", "IKAI", "KICI",
        "LMPI", "MTDL", "BOLT", "CSMI", "DFAM", "TELE", "GLVA", "MDRN",
        "RANC", "WOOD", "ZONE", "CINT", "CITY", "DIGI", "DUCK", "EAST",
        "FITT", "GOLD", "HRME", "JIHD", "KDTN", "MASB", "MICE", "NASA",
        "NATO", "PGLI", "PGUN", "PLAN", "PSAT", "PTSN", "SBAT", "SKRN",
        "SOFA", "SONA", "TAMA", "TRIL", "TURI", "UFOE", "VIVA", "WINE",
        "ATIC", "BLTZ", "CAKK", "DAAZ", "EPAC",
    ],

    "Energy": [
        "ADRO", "ITMG", "PTBA", "INDY", "HRUM", "DOID", "BSSR", "MYOH",
        "PGAS", "AKRA", "MEDC", "ENRG", "ELSA", "RATU", "BIPI", "RUIS",
        "SMMT", "TOBA", "WINS", "PKPK", "APEX", "ARII", "BSML", "PSSI",
        "SUNI", "MBAP", "ABMM", "GEMS", "BUMI", "DEWA", "DSSA", "PTRO",
        "TAMU", "ATLA", "CANI", "COAL", "KKGI", "PTIS", "TCPI",
    ],

    "Basic Materials": [
        "ANTM", "TINS", "MDKA", "INCO", "TPIA", "BRPT", "INKP", "TKIM",
        "SMGR", "INTP", "SMBR", "WTON", "KRAS", "NIKL", "CMPP", "SMCB",
        "ALKA", "ALMI", "ARNA", "BAJA", "BTON", "CTBN", "GDST", "INAI",
        "ISSP", "JKSW", "JPRS", "KIAS", "LION", "LMSH", "MLIA", "PICO",
        "SPMA", "TDPM", "TOTO", "AGII", "BRMS", "CTTH", "DKFT", "FASW",
        "IFSH", "IPOL", "KDSI", "MOLI", "SULI", "TIRT", "ZINC",
        "NICL", "NCKL", "MBMA", "OBMD", "HRTA",
    ],

    "Infrastructure": [
        "TLKM", "EXCL", "ISAT", "TOWR", "WEGE", "JSMR", "MTEL", "FREN",
        "LINK", "BALI", "SUPR", "TBIG", "META", "IBST", "GHON",
        "OASA", "MORA", "TOTL", "PTPP", "WSKT", "WIKA", "ADHI", "WSBP",
        "NRCA", "PBSA", "IDPR", "ACST", "APII", "SSIA", "PPRE", "DGIK",
        "HOME",
    ],

    "Properties & Real Estate": [
        "BSDE", "CTRA", "PWON", "SMRA", "LPKR", "DMAS", "JRPT", "APLN",
        "MTLA", "KIJA", "NIRO", "PANI", "PLIN", "RDTX", "RODA",
        "ASRI", "BAPA", "BCIP", "BEST", "BIKA", "BKDP", "BKSL", "COWL",
        "CPRI", "DUTI", "ELTY", "EMDE", "FMII", "GAMA", "GMTD", "GPRA",
        "GWSA", "INPP", "KOTA", "LCGP", "LPCK", "MDLN", "MKPI", "MMLP",
        "MPRO", "MTSM", "MYRX", "NZIA", "OMRE", "PUDP", "PWSI",
        "RBMS", "RIMO", "SATU", "SCBD", "SMDM", "TARA", "URBN", "VAST",
        "AMAN", "ATAP", "BOGA", "CBPE",
    ],

    "Industrials": [
        "UNTR", "HEXA", "KOBX", "SOCI", "IMPC", "ASGR", "SCCO", "IKBI",
        "JECC", "KBLI", "KBLM", "CCSI", "KRAH", "IPTV", "GDST",
        "AMIN", "ARKA", "BEBS", "CBMF", "IKAN", "INCF", "SLIS", "TRAM",
        "TRUK", "WEHA",
    ],

    "Technology": [
        "DMMX", "DCII", "WIFI", "MTDL", "MLPT", "MCAS", "KIOS", "LUCK",
        "NFCX", "TFAS", "UVCR", "ZYRX", "GLOB", "ENVY", "DIVA", "EDGE",
        "MSTI", "DIGI", "OPMS", "HDIT", "LMAS", "IOTF",
    ],

    "Healthcare": [
        "KLBF", "SIDO", "MIKA", "SILO", "HEAL", "PRDA", "SOHO", "DVLA",
        "TSPC", "PEHA", "SAME", "OMED", "RSGK", "PRAY", "PRIM", "IRRA",
        "BMHS", "MERK", "SCPI", "SQMI", "PYFA", "KAEF", "INAF", "BLUE",
        "MEDS",
    ],

    "Transportation & Logistics": [
        "BIRD", "GIAA", "SAFE", "SMDR", "MBSS", "TMAS", "ASSA", "TRUK",
        "WEHA", "HELI", "BULL", "TPMA", "IATA", "CMPP", "TAXI", "SDMU",
        "PTIS", "NELY", "HAIS", "SHIP", "KJEN", "LEAD", "TNCA", "ELPI",
        "DEAL",
    ],
}


def _flatten_curated() -> list[str]:
    """Flatten ke satu list '.JK' untuk kandidat validasi (dedup)."""
    seen = set()
    flat = []
    for tickers in _CURATED_SECTORS.values():
        for t in tickers:
            full = f"{t}.JK"
            if full not in seen:
                seen.add(full)
                flat.append(full)
    return flat


# Reverse map: ticker_clean → sektor (dipakai sector_engine & scanner)
TICKER_SECTOR: dict[str, str] = {
    t: sector for sector, tickers in _CURATED_SECTORS.items() for t in tickers
}

# Kompatibilitas dengan kode lama yang mengimpor SECTOR_MAP
SECTOR_MAP = _CURATED_SECTORS


# ═══════════════════════════════════════════════════════════════════
#  UNIVERSE DISCOVERY
# ═══════════════════════════════════════════════════════════════════

def get_all_bei_tickers() -> list[str]:
    """
    Ambil daftar semua ticker aktif di BEI.

    Strategy:
      1. Kandidat = curated seed (~550) + extra source (jika diset)
      2. Validasi kandidat via Yahoo Finance (batch, retry-friendly)
      3. Jika validasi gagal total → fallback ke database (universe
         hasil scan sebelumnya, sudah pasti valid)
      4. Jika database juga kosong → fallback ke curated mentah
         (skenario setup pertama kali sebelum scan pernah berjalan)

    Return list ticker dalam format "XXXX.JK"
    """
    log.info("Mengambil universe saham BEI...")

    candidates = _build_candidate_list()
    log.info(f"  Kandidat awal: {len(candidates)} ticker (curated + extra source)")

    validated = _validate_candidates_via_yahoo(candidates)

    if validated and len(validated) >= settings.universe_min_expected:
        log.info(f"✓ Universe tervalidasi via Yahoo Finance: {len(validated)} ticker aktif")
        return validated

    log.warning(
        f"Validasi Yahoo hanya menghasilkan {len(validated)} ticker "
        f"(di bawah ambang {settings.universe_min_expected}) — kemungkinan "
        f"gangguan Yahoo Finance sesaat. Coba fallback ke database."
    )

    db_tickers = _fetch_from_database()
    if db_tickers and len(db_tickers) >= settings.universe_min_expected:
        log.info(f"✓ Fallback ke database: {len(db_tickers)} ticker aktif")
        return db_tickers

    log.warning("Database fallback juga tidak memadai — pakai curated seed mentah (belum tervalidasi)")
    return candidates


def _build_candidate_list() -> list[str]:
    """Gabungkan curated seed + extra source (opsional) tanpa duplikat."""
    candidates = _flatten_curated()

    extra_url = settings.extra_universe_source_url.strip()
    if extra_url:
        extra = _fetch_extra_source(extra_url)
        if extra:
            existing = set(candidates)
            added = 0
            for t in extra:
                t_norm = t.strip().upper()
                if not t_norm:
                    continue
                if not t_norm.endswith(".JK"):
                    t_norm = f"{t_norm}.JK"
                if t_norm not in existing:
                    candidates.append(t_norm)
                    existing.add(t_norm)
                    added += 1
            log.info(f"  +{added} ticker tambahan dari EXTRA_UNIVERSE_SOURCE_URL")

    return candidates


def _fetch_extra_source(url: str) -> list[str]:
    """
    Ambil daftar ticker tambahan dari URL yang dikonfigurasi user.
    Mendukung: 1 ticker per baris, atau CSV dengan kolom 'ticker'.
    Best-effort — kegagalan di sini tidak boleh menghentikan sistem.
    """
    try:
        resp = requests.get(url, timeout=15)
        if not resp.ok:
            log.warning(f"EXTRA_UNIVERSE_SOURCE_URL gagal diakses: HTTP {resp.status_code}")
            return []

        text = resp.text.strip()
        if not text:
            return []

        if "," in text.splitlines()[0].lower() or "ticker" in text.splitlines()[0].lower():
            try:
                from io import StringIO
                df = pd.read_csv(StringIO(text))
                col = next((c for c in df.columns if c.strip().lower() == "ticker"), None)
                if col:
                    return [str(v) for v in df[col].dropna().tolist()]
            except Exception:
                pass

        return [line.strip() for line in text.splitlines() if line.strip()]

    except Exception as e:
        log.warning(f"EXTRA_UNIVERSE_SOURCE_URL error: {e}")
        return []


def _validate_candidates_via_yahoo(candidates: list[str]) -> list[str]:
    """
    Validasi kandidat ticker via Yahoo Finance secara batch.
    Ticker yang tidak punya data close terbaru dianggap tidak valid
    (delisting/suspend/kode salah).
    """
    if not candidates:
        return []

    log.info(f"Validating {len(candidates)} ticker via Yahoo Finance...")
    active_tickers: list[str] = []

    batch_size = 75
    total_batches = (len(candidates) + batch_size - 1) // batch_size

    for batch_num, i in enumerate(range(0, len(candidates), batch_size), 1):
        batch = candidates[i:i + batch_size]
        try:
            data = yf.download(
                batch,
                period="5d",
                interval="1d",
                progress=False,
                timeout=30,
                threads=True,
            )

            if data.empty:
                continue

            if isinstance(data.columns, pd.MultiIndex):
                if "Close" in data.columns.get_level_values(0):
                    close_data = data["Close"]
                else:
                    continue
                valid = close_data.columns[close_data.iloc[-1].notna()].tolist()
            else:
                valid = batch[:1] if not data["Close"].dropna().empty else []

            active_tickers.extend(valid)

        except Exception as e:
            log.warning(f"Batch validasi {batch_num}/{total_batches} error: {e}")
            continue

        time.sleep(0.5)

    return active_tickers


def _fetch_from_database() -> list[str]:
    """Ambil ticker aktif dari database (source of truth utama)."""
    try:
        db = get_db()
        result = (
            db.table("stocks")
            .select("ticker")
            .eq("is_active", True)
            .eq("is_delisted", False)
            .execute()
        )
        return [r["ticker"] for r in (result.data or [])]
    except Exception as e:
        log.error(f"DB fetch gagal: {e}")
        return []


# ═══════════════════════════════════════════════════════════════════
#  REFRESH — dijalankan mingguan (weekly_maintenance.yml)
# ═══════════════════════════════════════════════════════════════════

def refresh_universe() -> dict:
    """
    Refresh universe saham di database.
      - Tambah IPO baru (ticker tervalidasi tapi belum ada di DB)
      - Tandai saham delisting (ada di DB tapi tidak lagi valid)
      - Update info sektor & nama perusahaan

    SAFETY GUARD: jika jumlah ticker tervalidasi anjlok drastis
    dibanding yang sudah aktif di database (indikasi gangguan Yahoo
    sesaat, bukan delisting massal sungguhan), penandaan delisting
    di-skip untuk melindungi integritas data.

    Return: {"added": int, "removed": int, "total": int, "skipped_delisting_check": bool}
    """
    log.info("Memulai refresh universe saham BEI...")

    fresh_tickers = get_all_bei_tickers()
    db_tickers = _fetch_from_database()

    db_set = set(db_tickers)
    fresh_set = set(fresh_tickers)

    new_tickers = fresh_set - db_set
    possibly_delisted = db_set - fresh_set

    skip_delisting_check = False
    if db_set:
        retained_ratio = len(fresh_set & db_set) / len(db_set)
        if retained_ratio < 0.5 and len(fresh_set) < settings.universe_min_expected:
            log.error(
                f"⚠ SAFETY GUARD AKTIF: hanya {retained_ratio:.0%} ticker aktif "
                f"lama yang tervalidasi ulang (dari {len(db_set)} → {len(fresh_set & db_set)}). "
                f"Ini kemungkinan gangguan Yahoo Finance sesaat, BUKAN delisting massal. "
                f"Penandaan delisting DI-SKIP kali ini demi keamanan data."
            )
            skip_delisting_check = True

    added = 0
    for ticker in new_tickers:
        ticker_clean = ticker.replace(".JK", "")
        sector = TICKER_SECTOR.get(ticker_clean, "Uncategorized")

        success = upsert_stock(ticker, {
            "name": ticker_clean,
            "sector": sector,
            "is_active": True,
            "is_delisted": False,
        })

        if success:
            added += 1
            log.info(f"✓ Saham baru ditambahkan: {ticker} ({sector})")

    removed = 0
    if not skip_delisting_check:
        for ticker in possibly_delisted:
            is_delisted = _verify_delisting(ticker)
            if is_delisted:
                try:
                    db = get_db()
                    db.table("stocks").update({
                        "is_active": False,
                        "is_delisted": True,
                        "delisted_date": date.today().isoformat(),
                    }).eq("ticker", ticker).execute()
                    removed += 1
                    log.warning(f"⚠ Saham delisting ditandai: {ticker}")
                except Exception as e:
                    log.error(f"Gagal update delisting {ticker}: {e}")

    _update_stock_info(fresh_tickers[:30])

    result = {
        "added": added,
        "removed": removed,
        "total": len(fresh_tickers),
        "skipped_delisting_check": skip_delisting_check,
        "timestamp": datetime.utcnow().isoformat(),
    }

    log.info(
        f"Universe refresh selesai: +{added} baru, -{removed} delisting, "
        f"total {len(fresh_tickers)}"
        + (" [delisting check di-skip demi keamanan]" if skip_delisting_check else "")
    )
    return result


def _verify_delisting(ticker: str) -> bool:
    """
    Verifikasi apakah saham benar-benar delisting.
    Cek apakah ada data dalam 30 hari terakhir, dengan retry agar
    tidak salah tandai delisting hanya karena satu kali gagal network.
    """
    for attempt in range(2):
        try:
            df = yf.download(
                ticker,
                period="30d",
                interval="1d",
                progress=False,
                timeout=15,
            )
            if df is None or df.empty:
                if attempt == 0:
                    time.sleep(2)
                    continue
                return True

            if df["Volume"].sum() == 0:
                return True

            return False

        except Exception:
            if attempt == 0:
                time.sleep(2)
                continue
            return False

    return False


def _update_stock_info(tickers: list[str]):
    """Update nama, sektor, dan market cap dari Yahoo Finance info."""
    for ticker in tickers:
        try:
            info = yf.Ticker(ticker).info
            if not info:
                continue

            ticker_clean = ticker.replace(".JK", "")
            sector = TICKER_SECTOR.get(ticker_clean) or info.get("sector", "Uncategorized")

            upsert_stock(ticker, {
                "name": info.get("longName") or info.get("shortName") or ticker_clean,
                "sector": sector,
                "market_cap": info.get("marketCap"),
                "shares_outstanding": info.get("sharesOutstanding"),
            })

            time.sleep(0.2)

        except Exception as e:
            log.debug(f"Info update gagal untuk {ticker}: {e}")


def get_tickers_by_sector(sector: str) -> list[str]:
    """Dapatkan ticker berdasarkan sektor."""
    try:
        db = get_db()
        result = (
            db.table("stocks")
            .select("ticker")
            .eq("sector", sector)
            .eq("is_active", True)
            .execute()
        )
        tickers = [r["ticker"] for r in (result.data or [])]
        if tickers:
            return tickers
    except Exception:
        pass

    tickers = _CURATED_SECTORS.get(sector, [])
    return [f"{t}.JK" for t in tickers]
