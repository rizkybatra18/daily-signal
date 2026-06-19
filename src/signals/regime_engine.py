"""
DAILY SIGNAL — Market Regime Engine
Deteksi kondisi pasar: BULL / SIDEWAYS / BEAR
Menentukan bobot scoring (regime_weight) untuk semua sinyal.

Metodologi:
    1. Trend IHSG vs EMA20, EMA50
    2. RSI IHSG (momentum)
    3. Market Breadth (Advance-Decline ratio)
    4. Short-term change (5 hari)
    5. ADX IHSG (kekuatan trend)

Regime:
    BULL:     scoring normal (weight = 1.0)
    SIDEWAYS: scoring dikurangi (weight = 0.75)
    BEAR:     scoring drastis dikurangi (weight = 0.4)
"""

import pandas as pd
import numpy as np
from dataclasses import dataclass
from datetime import date
from typing import Optional

from src.signals.ta_engine import calc_rsi, calc_ema, calc_adx, calc_atr
from src.core.logger import get_logger
from src.core.database import save_market_regime, get_db

log = get_logger("regime_engine")


@dataclass
class MarketRegime:
    regime: str = "SIDEWAYS"       # BULL / SIDEWAYS / BEAR
    regime_weight: float = 0.75    # Multiplier untuk scoring
    ihsg_close: float = 0.0
    ihsg_ema20: float = 0.0
    ihsg_ema50: float = 0.0
    ihsg_rsi: float = 50.0
    ihsg_adx: float = 0.0
    change_1d: float = 0.0
    change_5d: float = 0.0
    change_20d: float = 0.0
    advance_count: int = 0
    decline_count: int = 0
    ad_ratio: float = 1.0          # Advance/Decline ratio
    breadth_score: float = 50.0    # 0-100
    regime_reason: str = ""
    
    # Signal modifier berdasarkan regime
    # BULL: sinyal BUY normal, SELL dikurangi
    # SIDEWAYS: semua sinyal dikurangi 25%
    # BEAR: semua sinyal BUY di-suppress, SL lebih ketat
    signal_modifier: str = "NORMAL"


def detect_market_regime(
    ihsg_df: pd.DataFrame,
    breadth_data: Optional[dict] = None,  # {"advance": int, "decline": int}
) -> MarketRegime:
    """
    Deteksi regime pasar saat ini.
    
    Args:
        ihsg_df: DataFrame OHLCV IHSG (minimal 50 baris)
        breadth_data: Optional breadth data (advance/decline counts)
    
    Returns:
        MarketRegime object
    """
    if ihsg_df is None or ihsg_df.empty or len(ihsg_df) < 20:
        log.warning("Data IHSG tidak cukup untuk deteksi regime")
        return MarketRegime(
            regime="SIDEWAYS",
            regime_weight=0.75,
            regime_reason="Data IHSG tidak cukup — default SIDEWAYS",
        )
    
    try:
        close = ihsg_df["close"]
        
        # Indikator IHSG
        ema20 = calc_ema(close, 20)
        ema50 = calc_ema(close, 50)
        rsi = calc_rsi(close, 14)
        adx, plus_di, minus_di = calc_adx(ihsg_df, 14)
        
        # Nilai terbaru
        last_close = float(close.iloc[-1])
        last_ema20 = float(ema20.iloc[-1])
        last_ema50 = float(ema50.iloc[-1]) if len(ema50.dropna()) > 0 else last_ema20
        last_rsi = float(rsi.iloc[-1])
        last_adx = float(adx.iloc[-1]) if not adx.empty else 20.0
        last_plus_di = float(plus_di.iloc[-1]) if not plus_di.empty else 0.0
        last_minus_di = float(minus_di.iloc[-1]) if not minus_di.empty else 0.0
        
        # Changes
        change_1d = 0.0
        change_5d = 0.0
        change_20d = 0.0
        
        if len(close) >= 2:
            change_1d = ((last_close / float(close.iloc[-2])) - 1) * 100
        if len(close) >= 6:
            change_5d = ((last_close / float(close.iloc[-6])) - 1) * 100
        if len(close) >= 21:
            change_20d = ((last_close / float(close.iloc[-21])) - 1) * 100
        
        # ── Scoring Components ────────────────────────────────
        
        bull_signals = 0
        bear_signals = 0
        reasons = []
        
        # 1. Price vs EMA20
        if last_close > last_ema20:
            bull_signals += 2
            reasons.append(f"IHSG > EMA20 ({last_ema20:,.0f})")
        else:
            bear_signals += 2
            reasons.append(f"IHSG < EMA20 ({last_ema20:,.0f})")
        
        # 2. Price vs EMA50
        if last_close > last_ema50:
            bull_signals += 1
            reasons.append("IHSG > EMA50")
        else:
            bear_signals += 1
            reasons.append("IHSG < EMA50")
        
        # 3. RSI
        if last_rsi > 55:
            bull_signals += 2
            reasons.append(f"RSI bullish ({last_rsi:.1f})")
        elif last_rsi < 40:
            bear_signals += 2
            reasons.append(f"RSI bearish ({last_rsi:.1f})")
        else:
            reasons.append(f"RSI neutral ({last_rsi:.1f})")
        
        # 4. 5-day momentum
        if change_5d > 1.0:
            bull_signals += 2
            reasons.append(f"5D momentum positif ({change_5d:+.1f}%)")
        elif change_5d < -3.0:
            bear_signals += 3
            reasons.append(f"5D momentum negatif ({change_5d:+.1f}%)")
        elif change_5d < -1.5:
            bear_signals += 1
            reasons.append(f"5D melemah ({change_5d:+.1f}%)")
        
        # 5. ADX trend direction
        if last_adx > 25 and last_plus_di > last_minus_di:
            bull_signals += 2
            reasons.append(f"Trend naik kuat ADX={last_adx:.1f}")
        elif last_adx > 25 and last_minus_di > last_plus_di:
            bear_signals += 2
            reasons.append(f"Trend turun kuat ADX={last_adx:.1f}")
        
        # 6. Breadth (advance-decline)
        advance_count = 0
        decline_count = 0
        ad_ratio = 1.0
        breadth_score = 50.0
        
        if breadth_data:
            advance_count = breadth_data.get("advance", 0)
            decline_count = breadth_data.get("decline", 0)
            total = advance_count + decline_count
            if total > 0:
                ad_ratio = advance_count / (decline_count + 1)  # Avoid div by 0
                breadth_score = (advance_count / total) * 100
                
                if breadth_score > 60:
                    bull_signals += 2
                    reasons.append(f"Breadth bullish ({breadth_score:.0f}% saham naik)")
                elif breadth_score < 35:
                    bear_signals += 2
                    reasons.append(f"Breadth bearish ({breadth_score:.0f}% saham naik)")
        
        # ── Determine Regime ─────────────────────────────────
        
        total_signals = bull_signals + bear_signals
        bull_ratio = bull_signals / total_signals if total_signals > 0 else 0.5
        
        # Extreme conditions override
        extreme_bear = (
            change_5d < -5.0 or
            last_rsi < 30 or
            (last_close < last_ema20 and last_close < last_ema50 and change_5d < -2)
        )
        
        extreme_bull = (
            change_5d > 3.0 or
            (last_close > last_ema20 and last_close > last_ema50 and last_rsi > 60)
        )
        
        if extreme_bear or bull_ratio < 0.3:
            regime = "BEAR"
            regime_weight = 0.4
            signal_modifier = "SUPPRESS_BUY"
        elif extreme_bull or bull_ratio >= 0.65:
            regime = "BULL"
            regime_weight = 1.0
            signal_modifier = "NORMAL"
        else:
            regime = "SIDEWAYS"
            regime_weight = 0.75
            signal_modifier = "SELECTIVE"
        
        regime_reason = f"Bull:{bull_signals} Bear:{bear_signals} | " + " | ".join(reasons[:3])
        
        result = MarketRegime(
            regime=regime,
            regime_weight=regime_weight,
            ihsg_close=round(last_close, 2),
            ihsg_ema20=round(last_ema20, 2),
            ihsg_ema50=round(last_ema50, 2),
            ihsg_rsi=round(last_rsi, 1),
            ihsg_adx=round(last_adx, 1),
            change_1d=round(change_1d, 2),
            change_5d=round(change_5d, 2),
            change_20d=round(change_20d, 2),
            advance_count=advance_count,
            decline_count=decline_count,
            ad_ratio=round(ad_ratio, 2),
            breadth_score=round(breadth_score, 1),
            regime_reason=regime_reason,
            signal_modifier=signal_modifier,
        )
        
        # Simpan ke database
        _save_regime_to_db(result)
        
        log.info(
            f"Market Regime: {regime} (weight={regime_weight}) | "
            f"IHSG={last_close:,.0f} | RSI={last_rsi:.1f} | 5D={change_5d:+.1f}%"
        )
        
        return result
        
    except Exception as e:
        log.error(f"Deteksi regime gagal: {e}", exc=e)
        return MarketRegime(
            regime="SIDEWAYS",
            regime_weight=0.75,
            regime_reason=f"Error dalam deteksi: {str(e)[:100]}",
        )


def _save_regime_to_db(regime: MarketRegime):
    """Simpan regime ke database (best-effort)."""
    try:
        save_market_regime({
            "regime_date": date.today().isoformat(),
            "regime": regime.regime,
            "ihsg_close": regime.ihsg_close,
            "ihsg_ema20": regime.ihsg_ema20,
            "ihsg_ema50": regime.ihsg_ema50,
            "ihsg_rsi": regime.ihsg_rsi,
            "ihsg_adx": regime.ihsg_adx,
            "advance_count": regime.advance_count,
            "decline_count": regime.decline_count,
            "advance_decline_ratio": regime.ad_ratio,
            "change_5d_pct": regime.change_5d,
            "regime_reason": regime.regime_reason,
            "bull_weight": 1.0,
            "sideways_weight": 0.75,
            "bear_weight": 0.4,
        })
    except Exception:
        pass  # Non-critical


def get_latest_regime() -> Optional[MarketRegime]:
    """Ambil regime terbaru dari database."""
    try:
        db = get_db()
        result = (
            db.table("market_regimes")
            .select("*")
            .order("regime_date", desc=True)
            .limit(1)
            .execute()
        )
        if not result.data:
            return None
        
        row = result.data[0]
        return MarketRegime(
            regime=row["regime"],
            regime_weight={"BULL": 1.0, "SIDEWAYS": 0.75, "BEAR": 0.4}.get(row["regime"], 0.75),
            ihsg_close=row.get("ihsg_close", 0),
            ihsg_rsi=row.get("ihsg_rsi", 50),
            change_5d=row.get("change_5d_pct", 0),
            regime_reason=row.get("regime_reason", ""),
        )
    except Exception:
        return None
