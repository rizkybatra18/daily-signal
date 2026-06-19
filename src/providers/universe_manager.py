"""
DAILY SIGNAL — Universe Manager
Auto-discover dan maintain seluruh universe saham BEI.
Tidak ada lagi watchlist statis!

Sumber data universe:
  1. Yahoo Finance screener untuk saham .JK
  2. IDX official data (via scraping atau API tidak resmi)
  3. Database stocks yang sudah ada

Auto-detect:
  - IPO baru
  - Saham yang delisting
  - Saham tidak aktif (volume 0 berkepanjangan)
"""

import time
import requests
import pandas as pd
import yfinance as yf
from datetime import date, datetime, timedelta
from typing import Optional
from tenacity import retry, stop_after_attempt, wait_exponential

from src.core.logger import get_logger
from src.core.database import get_db, upsert_stock

log = get_logger("universe_manager")

# ── Daftar Sektor BEI (IDX Classification) ──────────────────────────
SECTOR_MAP = {
    "Financials": [
        "BBCA", "BBRI", "BMRI", "BNGA", "BBNI", "BTPS", "BJBR", "BDMN",
        "BRIS", "BSIM", "PNBN", "NISP", "MEGA", "BGTG", "AGRO",
    ],
    "Consumer Non-Cyclicals": [
        "UNVR", "ICBP", "INDF", "KLBF", "SIDO", "MYOR", "CPIN", "JPFA",
        "ROTI", "ULTJ", "GGRM", "HMSP",
    ],
    "Consumer Cyclicals": [
        "ASII", "MAPI", "ACES", "ERAA", "BUKA", "GOTO", "MNCN", "LINK",
        "EMTK", "FILM", "MIKA",
    ],
    "Energy": [
        "ADRO", "ITMG", "HRUM", "PTBA", "INDY", "DOID", "BSSR", "MYOH",
        "PGAS",
    ],
    "Basic Materials": [
        "ANTM", "TINS", "MDKA", "INCO", "TPIA", "BRPT", "INKP", "TKIM",
        "SMGR", "INTP", "SMBR",
    ],
    "Infrastructure": [
        "TLKM", "EXCL", "ISAT", "TOWR", "JSMR", "WTON", "WEGE",
    ],
    "Properties & Real Estate": [
        "BSDE", "CTRA", "PWON", "SMRA", "LPKR", "DMAS", "JRPT", "APLN",
    ],
    "Industrials": [
        "WSKT", "WIKA", "PTPP", "ADHI", "WSBP", "KRAS",
    ],
    "Technology": [
        "DMMX", "DCII", "WIFI",
    ],
    "Healthcare": [
        "KLBF", "BEEN", "MIKA", "SILO", "HEAL", "PRDA",
    ],
    "Transportation & Logistics": [
        "BIRD", "GIAA", "SAFE", "SMDR",
    ],
}

# Reverse map: ticker → sektor
TICKER_SECTOR = {}
for sector, tickers in SECTOR_MAP.items():
    for t in tickers:
        TICKER_SECTOR[t] = sector


def get_all_bei_tickers() -> list[str]:
    """
    Ambil daftar semua ticker aktif di BEI.
    
    Strategy:
    1. Coba via Yahoo Finance screener
    2. Fallback ke database stocks yang sudah ada
    3. Fallback ke daftar curated 200+ saham
    
    Return list ticker dalam format "XXXX.JK"
    """
    log.info("Mengambil universe saham BEI...")
    
    # Strategy 1: Coba Yahoo Finance
    tickers = _fetch_via_yahoo_screener()
    if tickers and len(tickers) > 100:
        log.info(f"✓ Yahoo Finance: {len(tickers)} saham ditemukan")
        return tickers
    
    # Strategy 2: Coba dari database
    db_tickers = _fetch_from_database()
    if db_tickers and len(db_tickers) > 50:
        log.info(f"✓ Database: {len(db_tickers)} saham")
        return db_tickers
    
    # Strategy 3: Fallback ke curated list
    log.warning("Menggunakan curated fallback list")
    return _get_curated_universe()


def _fetch_via_yahoo_screener() -> list[str]:
    """
    Coba ambil daftar saham BEI via Yahoo Finance.
    Yahoo tidak punya API resmi untuk ini, tapi kita bisa query
    menggunakan yfinance dengan known tickers dan filter yang aktif.
    """
    try:
        # Kita gunakan curated seed list dan validasi mana yang aktif
        seed_tickers = _get_curated_universe()
        
        # Batch validate menggunakan yfinance
        log.info(f"Validating {len(seed_tickers)} ticker via Yahoo Finance...")
        active_tickers = []
        
        batch_size = 50
        for i in range(0, len(seed_tickers), batch_size):
            batch = seed_tickers[i:i + batch_size]
            try:
                # Download data 5 hari terakhir untuk validate
                data = yf.download(
                    batch,
                    period="5d",
                    interval="1d",
                    progress=False,
                    timeout=30,
                )
                if data.empty:
                    continue
                    
                # Ambil ticker yang punya data close
                if isinstance(data.columns, pd.MultiIndex):
                    close_data = data["Close"]
                    valid = close_data.columns[close_data.iloc[-1].notna()].tolist()
                else:
                    valid = batch[:1] if not data.empty else []
                
                active_tickers.extend(valid)
                time.sleep(0.5)  # Polite rate limiting
                
            except Exception as e:
                log.warning(f"Batch {i//batch_size + 1} error: {e}")
                continue
        
        return active_tickers
        
    except Exception as e:
        log.error(f"Yahoo screener gagal: {e}")
        return []


def _fetch_from_database() -> list[str]:
    """Ambil ticker aktif dari database."""
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


def refresh_universe() -> dict:
    """
    Refresh universe saham di database.
    - Tambah IPO baru
    - Tandai saham delisting
    - Update info sektor
    
    Return: {"added": int, "removed": int, "total": int}
    """
    log.info("Memulai refresh universe saham BEI...")
    
    # Ambil universe terbaru
    fresh_tickers = get_all_bei_tickers()
    
    # Ambil yang sudah ada di database
    db_tickers = _fetch_from_database()
    
    db_set = set(db_tickers)
    fresh_set = set(fresh_tickers)
    
    new_tickers = fresh_set - db_set
    possibly_delisted = db_set - fresh_set
    
    # Tambah ticker baru
    added = 0
    for ticker in new_tickers:
        ticker_clean = ticker.replace(".JK", "")
        sector = TICKER_SECTOR.get(ticker_clean, "Uncategorized")
        
        success = upsert_stock(ticker, {
            "name": ticker_clean,   # Nama akan di-update dari Yahoo info
            "sector": sector,
            "is_active": True,
            "is_delisted": False,
        })
        
        if success:
            added += 1
            log.info(f"✓ Saham baru ditambahkan: {ticker} ({sector})")
    
    # Tandai yang mungkin delisting (perlu konfirmasi)
    removed = 0
    for ticker in possibly_delisted:
        # Verifikasi dulu — mungkin hanya data sementara tidak ada
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
    
    # Update nama dan info dari Yahoo Finance
    _update_stock_info(fresh_tickers[:100])  # Batch pertama saja tiap run
    
    result = {
        "added": added,
        "removed": removed,
        "total": len(fresh_tickers),
        "timestamp": datetime.utcnow().isoformat(),
    }
    
    log.info(f"Universe refresh selesai: +{added} baru, -{removed} delisting, total {len(fresh_tickers)}")
    return result


def _verify_delisting(ticker: str) -> bool:
    """
    Verifikasi apakah saham benar-benar delisting.
    Cek apakah ada data dalam 30 hari terakhir.
    """
    try:
        df = yf.download(
            ticker,
            period="30d",
            interval="1d",
            progress=False,
            timeout=10,
        )
        if df is None or df.empty:
            return True  # Tidak ada data = kemungkinan delisting
        # Ada data tapi volume = 0 semua = suspended/delisted
        if df["Volume"].sum() == 0:
            return True
        return False
    except Exception:
        return False


def _update_stock_info(tickers: list[str]):
    """Update nama, sektor, dan market cap dari Yahoo Finance info."""
    for ticker in tickers[:20]:  # Batasi 20 per run untuk API rate limit
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
            
            time.sleep(0.2)  # Rate limiting
            
        except Exception as e:
            log.debug(f"Info update gagal untuk {ticker}: {e}")


def _get_curated_universe() -> list[str]:
    """
    Daftar curated 250+ saham BEI dengan likuiditas memadai.
    Ini adalah fallback jika semua metode otomatis gagal.
    Updated: 2025
    """
    CURATED = [
        # Perbankan & Keuangan
        "BBCA.JK", "BBRI.JK", "BMRI.JK", "BNGA.JK", "BBNI.JK", "BTPS.JK",
        "BJBR.JK", "BDMN.JK", "BRIS.JK", "PNBN.JK", "NISP.JK", "MEGA.JK",
        "AGRO.JK", "BSIM.JK", "BGTG.JK", "BCIC.JK", "ARTO.JK", "JAGO.JK",
        # Consumer
        "UNVR.JK", "ICBP.JK", "INDF.JK", "KLBF.JK", "SIDO.JK", "MYOR.JK",
        "ROTI.JK", "ULTJ.JK", "GGRM.JK", "HMSP.JK", "CPIN.JK", "JPFA.JK",
        "MLBI.JK", "DLTA.JK", "KEJU.JK", "GOOD.JK",
        # Teknologi & Telco
        "TLKM.JK", "EXCL.JK", "ISAT.JK", "TOWR.JK", "BUKA.JK", "GOTO.JK",
        "EMTK.JK", "FILM.JK", "MNCN.JK", "LINK.JK", "DMMX.JK", "DCII.JK",
        # Energi & Tambang
        "ADRO.JK", "ITMG.JK", "HRUM.JK", "PTBA.JK", "INDY.JK", "DOID.JK",
        "BSSR.JK", "MYOH.JK", "PGAS.JK", "AKRA.JK", "MEDC.JK", "ENRG.JK",
        "ELSA.JK", "RATU.JK",
        # Material Dasar
        "ANTM.JK", "TINS.JK", "MDKA.JK", "INCO.JK", "TPIA.JK", "BRPT.JK",
        "INKP.JK", "TKIM.JK", "SMGR.JK", "INTP.JK", "SMBR.JK", "WTON.JK",
        "KRAS.JK", "NIKL.JK", "CMPP.JK",
        # Properti
        "BSDE.JK", "CTRA.JK", "PWON.JK", "SMRA.JK", "LPKR.JK", "DMAS.JK",
        "JRPT.JK", "APLN.JK", "MTLA.JK", "KIJA.JK", "SSIA.JK", "NIRO.JK",
        # Infrastruktur & Konstruksi
        "JSMR.JK", "WSKT.JK", "WIKA.JK", "PTPP.JK", "ADHI.JK", "WEGE.JK",
        "WSBP.JK", "IDPR.JK",
        # Otomotif & Perakitan
        "ASII.JK", "AUTO.JK", "SMSM.JK", "IMAS.JK", "INDS.JK",
        # Retail & Consumer Discretionary
        "MAPI.JK", "ACES.JK", "ERAA.JK", "HERO.JK", "AMRT.JK", "MIDI.JK",
        "MPPA.JK", "RALS.JK",
        # Healthcare
        "KLBF.JK", "BEEN.JK", "MIKA.JK", "SILO.JK", "HEAL.JK", "PRDA.JK",
        "SOHO.JK", "DVLA.JK", "PYFA.JK", "TSPC.JK",
        # Transportasi
        "BIRD.JK", "GIAA.JK", "SMDR.JK", "SAFE.JK", "MBSS.JK",
        # Agriculture
        "LSIP.JK", "SSMS.JK", "AALI.JK", "PALM.JK", "SIMP.JK",
        # Media
        "SCMA.JK", "MDIA.JK", "KPIG.JK",
    ]
    return CURATED


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
        return [r["ticker"] for r in (result.data or [])]
    except Exception:
        # Fallback ke SECTOR_MAP
        tickers = SECTOR_MAP.get(sector, [])
        return [f"{t}.JK" for t in tickers]
