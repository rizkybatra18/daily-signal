"""
DAILY SIGNAL — Sector Rotation Engine
Analisis performa sektor untuk sector bonus/penalty scoring.

Menghitung ranking sektor berdasarkan:
    - Return 5 hari, 20 hari
    - Momentum relatif antar sektor
    - Breadth per sektor (% saham naik dalam sektor)
"""

import pandas as pd
import numpy as np
from dataclasses import dataclass
from datetime import date
from typing import Optional

from src.core.logger import get_logger
from src.core.database import save_sector_rankings, get_db

log = get_logger("sector_engine")


@dataclass
class SectorRanking:
    sector: str
    rank: int
    return_1d: float = 0.0
    return_5d: float = 0.0
    return_20d: float = 0.0
    momentum_score: float = 0.0
    breadth_pct: float = 50.0
    composite_score: float = 50.0
    trend: str = "STABLE"          # RISING/STABLE/FALLING
    score_bonus: float = 0.0       # -5 sampai +5, diterapkan ke saham di sektor ini


# Sektor ETF/proxy tickers untuk hitung sektor return
#
# AUDIT FIX (Scoring Engine Audit / Universe Manager Audit):
# Sebelumnya proxy per sektor HARDCODED hanya 3-4 saham big-cap
# (mis. Financials cuma BBCA/BBRI/BMRI/BBNI). Setelah Universe Manager
# diperluas ke ~550 ticker (lihat universe_manager.py), performa sektor
# yang dihitung dari 4 saham raksasa saja jadi TIDAK representatif dan
# menyisakan sebagian besar universe baru tidak termanfaatkan untuk
# perhitungan sector rotation — padahal sector_bonus ini yang langsung
# mempengaruhi raw_score tiap saham (lihat ta_engine.py).
#
# Fix: proxy kini diturunkan DINAMIS dari TICKER_SECTOR (peta sektor
# yang sama dipakai scanner untuk seluruh universe), bukan daftar
# terpisah yang gampang basi. _FALLBACK_SECTOR_PROXY tetap disimpan
# sebagai jaring pengaman jika import universe_manager gagal karena
# alasan apapun (defense in depth, bukan jalur normal).
_FALLBACK_SECTOR_PROXY = {
    "Financials": ["BBCA.JK", "BBRI.JK", "BMRI.JK", "BBNI.JK"],
    "Consumer Non-Cyclicals": ["UNVR.JK", "ICBP.JK", "INDF.JK", "MYOR.JK"],
    "Consumer Cyclicals": ["ASII.JK", "MAPI.JK", "ACES.JK", "GOTO.JK"],
    "Energy": ["ADRO.JK", "ITMG.JK", "PTBA.JK", "PGAS.JK"],
    "Basic Materials": ["ANTM.JK", "TINS.JK", "SMGR.JK", "INTP.JK"],
    "Technology": ["TLKM.JK", "EXCL.JK", "TOWR.JK", "EMTK.JK"],
    "Healthcare": ["KLBF.JK", "SIDO.JK", "MIKA.JK"],
    "Industrials": ["WSKT.JK", "WIKA.JK", "PTPP.JK"],
    "Infrastructure": ["JSMR.JK", "TOWR.JK", "TLKM.JK"],
    "Properties & Real Estate": ["BSDE.JK", "CTRA.JK", "PWON.JK"],
    "Transportation & Logistics": ["BIRD.JK", "GIAA.JK", "SMDR.JK"],
}


def _build_sector_proxy() -> dict[str, list[str]]:
    """Turunkan proxy sektor dari seluruh universe (TICKER_SECTOR)."""
    try:
        from src.providers.universe_manager import TICKER_SECTOR
        if not TICKER_SECTOR:
            return _FALLBACK_SECTOR_PROXY
        proxy: dict[str, list[str]] = {}
        for ticker_clean, sector in TICKER_SECTOR.items():
            proxy.setdefault(sector, []).append(f"{ticker_clean}.JK")
        return proxy or _FALLBACK_SECTOR_PROXY
    except Exception:
        return _FALLBACK_SECTOR_PROXY


SECTOR_PROXY = _build_sector_proxy()


def calculate_sector_rankings(stock_data: dict[str, pd.DataFrame]) -> list[SectorRanking]:
    """
    Hitung ranking performa sektor berdasarkan data saham yang sudah dimuat.

    Args:
        stock_data: dict {ticker: DataFrame OHLCV} — data yang SAMA
            yang dipakai untuk analisis TA per saham (tidak ada query
            tambahan ke provider/DB).

    Returns:
        list[SectorRanking] terurut dari terbaik ke terburuk
    """
    log.info("Menghitung sektor rotation rankings...")

    sector_stats = []

    for sector, proxy_tickers in SECTOR_PROXY.items():
        available = [t for t in proxy_tickers if t in stock_data]

        if not available:
            log.warning(f"Tidak ada data untuk sektor {sector}")
            continue

        returns_1d = []
        returns_5d = []
        returns_20d = []
        advance = 0
        decline = 0

        for ticker in available:
            df = stock_data[ticker]
            if df is None or df.empty or len(df) < 2:
                continue

            close = df["close"]
            last = float(close.iloc[-1])

            if len(close) >= 2:
                prev = float(close.iloc[-2])
                r1d = ((last / prev) - 1) * 100 if prev > 0 else 0
                returns_1d.append(r1d)
                if r1d > 0:
                    advance += 1
                elif r1d < 0:
                    decline += 1

            if len(close) >= 6:
                base5 = float(close.iloc[-6])
                r5d = ((last / base5) - 1) * 100 if base5 > 0 else 0
                returns_5d.append(r5d)

            if len(close) >= 21:
                base20 = float(close.iloc[-21])
                r20d = ((last / base20) - 1) * 100 if base20 > 0 else 0
                returns_20d.append(r20d)

        if not returns_1d:
            continue

        avg_1d = float(np.mean(returns_1d))
        avg_5d = float(np.mean(returns_5d)) if returns_5d else 0.0
        avg_20d = float(np.mean(returns_20d)) if returns_20d else 0.0

        total_stocks = advance + decline
        breadth_pct = (advance / total_stocks * 100) if total_stocks > 0 else 50.0

        momentum_score = (avg_5d * 0.6) + (avg_20d * 0.4)

        composite = 50 + (momentum_score * 3) + ((breadth_pct - 50) * 0.3)
        composite = max(0, min(100, composite))

        if momentum_score > 1.5:
            trend = "RISING"
        elif momentum_score < -1.5:
            trend = "FALLING"
        else:
            trend = "STABLE"

        sector_stats.append({
            "sector": sector,
            "return_1d": round(avg_1d, 2),
            "return_5d": round(avg_5d, 2),
            "return_20d": round(avg_20d, 2),
            "momentum_score": round(momentum_score, 2),
            "breadth_pct": round(breadth_pct, 1),
            "composite_score": round(composite, 1),
            "trend": trend,
        })

    sector_stats.sort(key=lambda x: x["composite_score"], reverse=True)

    n = len(sector_stats)
    rankings = []

    for i, stat in enumerate(sector_stats, 1):
        if n <= 1:
            bonus = 0.0
        elif i <= max(1, n // 3):
            bonus = 5.0
        elif i > n - max(1, n // 3):
            bonus = -5.0
        else:
            bonus = 0.0

        rankings.append(SectorRanking(
            sector=stat["sector"],
            rank=i,
            return_1d=stat["return_1d"],
            return_5d=stat["return_5d"],
            return_20d=stat["return_20d"],
            momentum_score=stat["momentum_score"],
            breadth_pct=stat["breadth_pct"],
            composite_score=stat["composite_score"],
            trend=stat["trend"],
            score_bonus=bonus,
        ))

    _save_rankings_to_db(rankings)

    if rankings:
        top = rankings[0]
        log.info(f"Sector rankings dihitung: #1 {top.sector} ({top.composite_score})")

    return rankings


def get_sector_bonus(ticker: str, sector_rankings: list[SectorRanking]) -> float:
    """
    Dapatkan score bonus/penalty untuk ticker berdasarkan sektornya.
    Return float: positif = bonus, negatif = penalty, 0 = neutral
    """
    from src.providers.universe_manager import TICKER_SECTOR

    ticker_clean = ticker.replace(".JK", "")
    sector = TICKER_SECTOR.get(ticker_clean)

    if not sector:
        return 0.0

    for sr in sector_rankings:
        if sr.sector == sector:
            return sr.score_bonus

    return 0.0


def _save_rankings_to_db(rankings: list[SectorRanking]):
    """Simpan sector rankings ke database (best-effort)."""
    try:
        records = [
            {
                "rank_date": date.today().isoformat(),
                "sector": r.sector,
                "rank_position": r.rank,
                "return_1d": r.return_1d,
                "return_5d": r.return_5d,
                "return_20d": r.return_20d,
                "momentum_score": r.momentum_score,
                "breadth_score": r.breadth_pct,
                "composite_score": r.composite_score,
                "trend": r.trend,
            }
            for r in rankings
        ]
        save_sector_rankings(records)
    except Exception as e:
        log.debug(f"Gagal simpan sector rankings: {e}")


def get_latest_sector_rankings() -> list[dict]:
    """Ambil ranking sektor terbaru dari database (untuk dashboard/telegram)."""
    try:
        db = get_db()
        result = (
            db.table("sector_rankings")
            .select("*")
            .order("rank_date", desc=True)
            .order("rank_position")
            .limit(11)
            .execute()
        )
        return result.data or []
    except Exception:
        return []
