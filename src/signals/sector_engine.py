"""
DAILY SIGNAL — Sector Rotation Engine
Rank sektor BEI berdasarkan momentum dan performa.
Digunakan untuk meningkatkan kualitas sinyal:
  - Saham dari sektor top-3 mendapat bonus score
  - Saham dari sektor bottom-3 mendapat penalty
"""

import pandas as pd
import numpy as np
from dataclasses import dataclass
from datetime import date
from typing import Optional

from src.core.logger import get_logger
from src.core.database import save_sector_rankings, get_db

log = get_logger("sector_engine")

# Sektor BEI
BEI_SECTORS = [
    "Financials",
    "Consumer Non-Cyclicals",
    "Consumer Cyclicals",
    "Energy",
    "Basic Materials",
    "Technology",
    "Healthcare",
    "Industrials",
    "Infrastructure",
    "Properties & Real Estate",
    "Transportation & Logistics",
]

# Sektor ETF/proxy tickers untuk hitung sektor return
# Menggunakan basket dari beberapa saham per sektor
SECTOR_PROXY = {
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


@dataclass
class SectorRanking:
    sector: str
    return_1d: float = 0.0
    return_5d: float = 0.0
    return_20d: float = 0.0
    momentum_score: float = 0.0
    breadth_score: float = 0.0    # % saham di sektor yang naik
    composite_score: float = 0.0
    rank: int = 0
    trend: str = "STABLE"         # RISING/STABLE/FALLING
    score_bonus: float = 0.0      # Bonus/penalty untuk sinyal di sektor ini


def calculate_sector_rankings(
    stock_data: dict[str, pd.DataFrame],  # {ticker: df_ohlcv}
) -> list[SectorRanking]:
    """
    Hitung ranking sektor dari data harga saham.
    
    Args:
        stock_data: Dictionary {ticker: OHLCV DataFrame}
    
    Returns:
        List SectorRanking diurutkan dari terbaik
    """
    log.info("Menghitung sektor rotation rankings...")
    
    sector_results = []
    
    for sector, proxy_tickers in SECTOR_PROXY.items():
        available_tickers = [t for t in proxy_tickers if t in stock_data]
        
        if not available_tickers:
            log.warning(f"Tidak ada data untuk sektor {sector}")
            sector_results.append(SectorRanking(
                sector=sector,
                composite_score=0.0,
                trend="STABLE",
            ))
            continue
        
        # Kumpulkan returns per saham di sektor
        returns_1d = []
        returns_5d = []
        returns_20d = []
        
        for ticker in available_tickers:
            df = stock_data[ticker]
            if df is None or len(df) < 5:
                continue
            
            close = df["close"]
            last = float(close.iloc[-1])
            
            if len(close) >= 2:
                r1d = ((last / float(close.iloc[-2])) - 1) * 100
                returns_1d.append(r1d)
            
            if len(close) >= 6:
                r5d = ((last / float(close.iloc[-6])) - 1) * 100
                returns_5d.append(r5d)
            
            if len(close) >= 21:
                r20d = ((last / float(close.iloc[-21])) - 1) * 100
                returns_20d.append(r20d)
        
        if not returns_1d:
            sector_results.append(SectorRanking(sector=sector))
            continue
        
        # Average return per sektor
        avg_1d = float(np.mean(returns_1d)) if returns_1d else 0.0
        avg_5d = float(np.mean(returns_5d)) if returns_5d else 0.0
        avg_20d = float(np.mean(returns_20d)) if returns_20d else 0.0
        
        # Breadth: % saham yang naik
        breadth = sum(1 for r in returns_1d if r > 0) / len(returns_1d) * 100 if returns_1d else 50.0
        
        # Momentum Score (0-100)
        # Weighted: recent lebih penting
        momentum = (avg_1d * 5) + (avg_5d * 2) + (avg_20d * 0.5)
        momentum_score = max(0, min(100, 50 + momentum * 5))  # Normalize ke 0-100
        
        # Composite Score
        composite = (momentum_score * 0.6) + (breadth * 0.4)
        
        # Trend
        if avg_5d > 2.0 and avg_20d > 0:
            trend = "RISING"
        elif avg_5d < -2.0:
            trend = "FALLING"
        else:
            trend = "STABLE"
        
        sector_results.append(SectorRanking(
            sector=sector,
            return_1d=round(avg_1d, 2),
            return_5d=round(avg_5d, 2),
            return_20d=round(avg_20d, 2),
            momentum_score=round(momentum_score, 1),
            breadth_score=round(breadth, 1),
            composite_score=round(composite, 1),
            trend=trend,
        ))
    
    # Sort by composite score
    sector_results.sort(key=lambda x: x.composite_score, reverse=True)
    
    # Assign ranks dan bonuses
    n = len(sector_results)
    for i, sr in enumerate(sector_results):
        sr.rank = i + 1
        
        # Score bonus untuk sinyal di sektor ini
        if i < 3:          # Top 3 sektor
            sr.score_bonus = 5.0    # +5 poin bonus
        elif i >= n - 3:   # Bottom 3 sektor
            sr.score_bonus = -5.0   # -5 poin penalty
        else:
            sr.score_bonus = 0.0
    
    # Simpan ke database
    _save_sector_rankings(sector_results)
    
    log.info(f"Sector rankings dihitung: #{1} {sector_results[0].sector} ({sector_results[0].composite_score:.1f})")
    
    return sector_results


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


def _save_sector_rankings(rankings: list[SectorRanking]):
    """Simpan rankings ke database."""
    try:
        today = date.today().isoformat()
        records = [
            {
                "rank_date": today,
                "sector": sr.sector,
                "return_1d": sr.return_1d,
                "return_5d": sr.return_5d,
                "return_20d": sr.return_20d,
                "momentum_score": sr.momentum_score,
                "breadth_score": sr.breadth_score,
                "composite_score": sr.composite_score,
                "rank_position": sr.rank,
                "trend": sr.trend,
            }
            for sr in rankings
        ]
        save_sector_rankings(records)
    except Exception as e:
        log.error(f"Gagal simpan sector rankings: {e}")


def get_latest_sector_rankings() -> list[dict]:
    """Ambil sector rankings terbaru dari database."""
    try:
        db = get_db()
        result = (
            db.table("sector_rankings")
            .select("*")
            .order("rank_date", desc=True)
            .order("rank_position")
            .limit(20)
            .execute()
        )
        return result.data or []
    except Exception:
        return []
