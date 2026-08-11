"""
DAILY SIGNAL — Pattern & Trend Structure Detection Engine
Modul BERDIRI SENDIRI (fungsi murni, tidak menyentuh ta_engine.py /
scanner.py secara langsung — dipanggil DARI ta_engine.py &
signal_evaluator.py, bukan sebaliknya), dipanggil untuk mengisi kolom
`trend_structure` dan `pattern_detected`.

═══════════════════════════════════════════════════════════════════
KETERBATASAN YANG DIAKUI JUJUR (baca sebelum pakai hasilnya):
═══════════════════════════════════════════════════════════════════
Semua deteksi di sini HEURISTIK berbasis aturan sederhana (swing pivot,
rasio body/wick candle, RSI vs harga) — BUKAN machine learning.

STATUS WIRING KE SCORING (v2.5.0, 2026-08 — CATATAN INI PERNAH BASI,
lihat AUDIT trend_score di ta_engine.py::CompositeScore untuk riwayat
lengkap kenapa berubah):
  - `detect_trend_structure()` SUDAH di-wire ke _score_trend() di
    ta_engine.py (bonus ±2 poin) sejak evidence signal_results n=368
    menunjukkan gap besar & konsisten (Pullback +8.9% vs Breakout
    +4.0%) — BUKAN lagi sekadar konteks deskriptif.
  - Fungsi LAIN di modul ini (`detect_candlestick_patterns`,
    `detect_breakout_pattern`, `detect_support_resistance`,
    `detect_divergence`, dan `detect_all_patterns` secara umum) BELUM
    di-wire ke _score_*() manapun — masih murni konteks tambahan untuk
    dibaca manusia (lewat dashboard/reasons), belum divalidasi empiris.
    Jangan wire sebelum ada validasi seperti yang dilakukan untuk
    volatility_score/minus_di/trend_structure di atas.
"""

from typing import Optional

import numpy as np
import pandas as pd


# ═══════════════════════════════════════════════════════════════════
#  SWING PIVOT (dasar buat trend_structure & support/resistance)
# ═══════════════════════════════════════════════════════════════════

def _confirmed_swing_pivots(df: pd.DataFrame, window: int = 3) -> tuple[list, list]:
    """
    Swing high/low TERKONFIRMASI (butuh `window` bar di kiri & kanan
    yang lebih rendah/tinggi). Sengaja pakai konfirmasi window kanan
    (bukan cuma window kiri) supaya konsisten dgn cara manusia baca
    chart -- konsekuensinya, `window` pivot paling akhir tidak akan
    pernah muncul (belum terkonfirmasi), ini DISENGAJA untuk menghindari
    lookahead bias, bukan bug.

    Return: ([(idx_posisi, harga_high), ...], [(idx_posisi, harga_low), ...])
    terurut dari yang paling lama ke paling baru.
    """
    highs = df["high"].to_numpy()
    lows = df["low"].to_numpy()
    n = len(df)
    swing_highs, swing_lows = [], []

    for i in range(window, n - window):
        h_slice = highs[i - window: i + window + 1]
        l_slice = lows[i - window: i + window + 1]
        if highs[i] == h_slice.max() and (h_slice == h_slice.max()).sum() == 1:
            swing_highs.append((i, float(highs[i])))
        if lows[i] == l_slice.min() and (l_slice == l_slice.min()).sum() == 1:
            swing_lows.append((i, float(lows[i])))

    return swing_highs, swing_lows


# ═══════════════════════════════════════════════════════════════════
#  TREND STRUCTURE: Higher High / Higher Low / Lower High / Lower Low
#  / Breakout / Pullback / Consolidation
# ═══════════════════════════════════════════════════════════════════

def detect_trend_structure(df: pd.DataFrame, lookback: int = 60, pivot_window: int = 3) -> Optional[str]:
    """
    Klasifikasi struktur trend jadi SATU label paling relevan, prioritas:
      1. Breakout      — close menembus resistance N-bar terakhir
      2. Consolidation — range 10-bar terakhir sempit banget relatif ATR
      3. Pullback       — struktur uptrend (HH+HL) tapi harga lagi
                          terkoreksi dari swing high terakhir
      4. Higher High / Higher Low / Lower High / Lower Low — dari
         perbandingan 2 swing pivot terkonfirmasi terakhir

    Return None kalau data kurang (butuh minimal ~2*pivot_window+20 bar).
    """
    if df is None or len(df) < max(lookback, 2 * pivot_window + 20):
        return None

    d = df.tail(lookback).reset_index(drop=True)
    highs, lows, closes = d["high"].to_numpy(), d["low"].to_numpy(), d["close"].to_numpy()
    last_close = float(closes[-1])

    # 1) Breakout: close > resistance 20-bar SEBELUM bar ini sendiri
    if len(highs) >= 21:
        prior_high = highs[-21:-1].max()
        if last_close > prior_high:
            return "Breakout"

    # 2) Consolidation: range 10-bar terakhir sempit relatif ATR proxy 14-bar
    if len(highs) >= 14:
        atr_proxy = float(np.mean(highs[-14:] - lows[-14:]))
        recent10_range = float(highs[-10:].max() - lows[-10:].min())
        if atr_proxy > 0 and recent10_range < atr_proxy * 2.5:
            return "Consolidation"

    # 3) & 4) dari swing pivot
    swing_highs, swing_lows = _confirmed_swing_pivots(d, pivot_window)
    if len(swing_highs) >= 2 and len(swing_lows) >= 2:
        hh = swing_highs[-1][1] > swing_highs[-2][1]
        hl = swing_lows[-1][1] > swing_lows[-2][1]
        lh = swing_highs[-1][1] < swing_highs[-2][1]
        ll = swing_lows[-1][1] < swing_lows[-2][1]

        if hh and hl:
            # uptrend structure -- tapi kalau harga sekarang sudah turun
            # >=2% dari swing high terakhir, itu Pullback bukan HH murni
            if last_close < swing_highs[-1][1] * 0.98:
                return "Pullback"
            return "Higher High"
        if hl and not hh:
            return "Higher Low"
        if lh and ll:
            return "Lower Low"
        if lh and not ll:
            return "Lower High"

    return None


# ═══════════════════════════════════════════════════════════════════
#  CANDLESTICK PATTERNS (1-3 candle terakhir)
# ═══════════════════════════════════════════════════════════════════

def detect_candlestick_patterns(df: pd.DataFrame) -> list[str]:
    """Deteksi beberapa pola candlestick umum di 1-3 candle terakhir."""
    if df is None or len(df) < 3:
        return []

    patterns = []
    o, h, l, c = df["open"].to_numpy(), df["high"].to_numpy(), df["low"].to_numpy(), df["close"].to_numpy()

    o1, h1, l1, c1 = o[-1], h[-1], l[-1], c[-1]        # candle terakhir
    o2, h2, l2, c2 = o[-2], h[-2], l[-2], c[-2]        # candle sebelumnya

    body1 = abs(c1 - o1)
    range1 = h1 - l1 if h1 > l1 else 1e-9
    upper_wick1 = h1 - max(c1, o1)
    lower_wick1 = min(c1, o1) - l1

    # Doji: body sangat kecil relatif range
    if body1 <= range1 * 0.1:
        patterns.append("Doji")

    # Hammer: body kecil di atas range, lower wick panjang (>=2x body), upper wick minim
    if body1 > 0 and lower_wick1 >= body1 * 2 and upper_wick1 <= body1 * 0.5 and body1 <= range1 * 0.35:
        patterns.append("Hammer")

    # Bullish Engulfing: candle-2 bearish, candle-1 bullish, body candle-1
    # menutupi penuh body candle-2
    body2_bearish = c2 < o2
    body1_bullish = c1 > o1
    if body2_bearish and body1_bullish and c1 >= o2 and o1 <= c2:
        patterns.append("Bullish Engulfing")

    # Morning Star (3 candle): bearish besar, body kecil (indecision), bullish
    # yang menutup >=50% ke body candle pertama
    if len(df) >= 3:
        o3, c3 = o[-3], c[-3]
        body3 = abs(c3 - o3)
        mid3 = (o3 + c3) / 2
        first_bearish = c3 < o3
        second_small = abs(c2 - o2) <= body3 * 0.4
        third_recovers = body1_bullish and c1 > mid3
        if first_bearish and second_small and third_recovers:
            patterns.append("Morning Star")

    return patterns


# ═══════════════════════════════════════════════════════════════════
#  BREAKOUT PATTERN (dengan konfirmasi volume, beda dari trend_structure
#  yang cuma liat harga -- di sini eksplisit butuh volume utk dibilang
#  "pattern" yang meyakinkan)
# ═══════════════════════════════════════════════════════════════════

def detect_breakout_pattern(df: pd.DataFrame, volume_ratio: Optional[float] = None) -> list[str]:
    """Breakout resistance N-bar dengan/tanpa konfirmasi volume."""
    if df is None or len(df) < 21:
        return []
    highs = df["high"].to_numpy()
    closes = df["close"].to_numpy()
    prior_high = highs[-21:-1].max()
    last_close = float(closes[-1])

    if last_close <= prior_high:
        return []
    if volume_ratio is not None and volume_ratio >= 1.3:
        return ["Breakout Resistance (Volume Confirmed)"]
    return ["Breakout Resistance"]


# ═══════════════════════════════════════════════════════════════════
#  SUPPORT / RESISTANCE (dari swing pivot terdekat)
# ═══════════════════════════════════════════════════════════════════

def detect_support_resistance(df: pd.DataFrame, lookback: int = 60, pivot_window: int = 3,
                               proximity_pct: float = 2.0) -> list[str]:
    """
    Cek apakah harga sekarang lagi 'dekat' (dalam proximity_pct%) ke
    level support/resistance dari swing pivot terkonfirmasi terdekat.
    """
    if df is None or len(df) < max(lookback, 2 * pivot_window + 20):
        return []

    d = df.tail(lookback).reset_index(drop=True)
    last_close = float(d["close"].iloc[-1])
    swing_highs, swing_lows = _confirmed_swing_pivots(d, pivot_window)

    tags = []
    if swing_highs:
        nearest_res = min((p for _, p in swing_highs if p >= last_close), default=None)
        if nearest_res is not None and (nearest_res - last_close) / last_close * 100 <= proximity_pct:
            tags.append("Near Resistance")
    if swing_lows:
        nearest_sup = max((p for _, p in swing_lows if p <= last_close), default=None)
        if nearest_sup is not None and (last_close - nearest_sup) / last_close * 100 <= proximity_pct:
            tags.append("Near Support")
    return tags


# ═══════════════════════════════════════════════════════════════════
#  DIVERGENCE (harga vs RSI, bullish & bearish)
# ═══════════════════════════════════════════════════════════════════

def detect_divergence(df: pd.DataFrame, rsi_series: pd.Series, lookback: int = 30,
                       pivot_window: int = 3) -> list[str]:
    """
    Bullish divergence: harga bikin Lower Low, RSI bikin Higher Low (momentum
    jual melemah meski harga masih turun -- sinyal potensi rebound).
    Bearish divergence: kebalikannya.
    Dibandingkan dari 2 swing low/high harga terkonfirmasi terakhir vs
    nilai RSI di titik yang sama.
    """
    if df is None or rsi_series is None or len(df) < lookback or len(rsi_series) < lookback:
        return []

    d = df.tail(lookback).reset_index(drop=True)
    rsi = rsi_series.tail(lookback).reset_index(drop=True)
    if len(rsi) != len(d):
        return []

    swing_highs, swing_lows = _confirmed_swing_pivots(d, pivot_window)
    tags = []

    if len(swing_lows) >= 2:
        (i1, p1), (i2, p2) = swing_lows[-2], swing_lows[-1]
        if i1 < len(rsi) and i2 < len(rsi):
            r1, r2 = rsi.iloc[i1], rsi.iloc[i2]
            if pd.notna(r1) and pd.notna(r2) and p2 < p1 and r2 > r1:
                tags.append("RSI Bullish Divergence")

    if len(swing_highs) >= 2:
        (i1, p1), (i2, p2) = swing_highs[-2], swing_highs[-1]
        if i1 < len(rsi) and i2 < len(rsi):
            r1, r2 = rsi.iloc[i1], rsi.iloc[i2]
            if pd.notna(r1) and pd.notna(r2) and p2 > p1 and r2 < r1:
                tags.append("RSI Bearish Divergence")

    return tags


# ═══════════════════════════════════════════════════════════════════
#  GABUNGAN — dipanggil dari signal_evaluator.py
# ═══════════════════════════════════════════════════════════════════

def detect_all_patterns(df: pd.DataFrame, rsi_series: Optional[pd.Series] = None,
                         volume_ratio: Optional[float] = None) -> list[str]:
    """Gabungkan semua deteksi pattern jadi satu list (utk kolom pattern_detected)."""
    patterns: list[str] = []
    try:
        patterns += detect_candlestick_patterns(df)
    except Exception:
        pass
    try:
        patterns += detect_breakout_pattern(df, volume_ratio)
    except Exception:
        pass
    try:
        patterns += detect_support_resistance(df)
    except Exception:
        pass
    if rsi_series is not None:
        try:
            patterns += detect_divergence(df, rsi_series)
        except Exception:
            pass
    return patterns
