"""
DAILY SIGNAL — Analog Matching Engine (K-Nearest Neighbor)

Untuk 1 saham, cari K hari di masa lalu SAHAM ITU SENDIRI yang kondisi
teknikalnya paling mirip dengan HARI INI, lalu simulasikan trade di
hari-hari analog itu pakai _simulate_trade yang SAMA PERSIS dengan
backtest engine (single source of truth, bukan reimplement) -- supaya
definisi TP1/TP2/SL/komisi konsisten di seluruh sistem. Win rate &
rata-rata return dari analog-analog itu = "probabilitas" empiris.

KENAPA KNN, BUKAN MODEL ML "KOTAK HITAM" (co. XGBoost terlatih di
seluruh pasar): data live sistem ini baru ~368-500 baris (lihat
CHANGELOG v2.5.0 dst) -- jauh dari cukup untuk melatih classifier
generik tanpa overfitting parah. KNN per-saham TIDAK butuh data
sebanyak itu (cukup histori 3 tahun saham itu sendiri, yang sudah ada
via get_ohlcv_from_db), hasilnya bisa ditelusuri manual per analog
(bukan kotak hitam), dan tetap genuine machine learning (KNN adalah
algoritma ML klasik) -- cuma lebih jujur soal keterbatasan data yang
kita punya.

KETERBATASAN YANG DIAKUI JUJUR:
- N analog per saham BISA SANGAT KECIL (sebagian saham mungkin cuma
  punya beberapa hari yang benar2 mirip dalam 3 tahun) -- probabilitas
  dari n kecil PASTI noisy. min_analogs adalah pengaman, BUKAN jaminan
  n=15 selalu representatif secara statistik.
- Fitur yang dipakai (7 dimensi) dipilih SUBJEKTIF berdasarkan relevansi
  teknikal umum -- bukan hasil feature selection otomatis, dan BELUM
  divalidasi dimensi mana yang benar2 prediktif untuk analog matching
  (beda dari validasi trend_score/volatility_score yang sudah dites
  langsung terhadap signal_results).
- "Mirip" cuma dari 7 dimensi teknikal harga/volume -- TIDAK memperhauthkan
  konteks lain (berita, sektor, kondisi makro saat itu vs sekarang).
"""

import numpy as np
import pandas as pd
from dataclasses import dataclass, field
from typing import Optional

from src.core.logger import get_logger
from src.backtest.engine import _add_indicators, _simulate_trade, MIN_WARMUP_ROWS, FORWARD_CANDLES

log = get_logger("analog_engine")

ANALOG_FEATURES = ["rsi", "adx", "di_diff", "atr_pct", "bb_position", "price_vs_ema20_pct", "cmf"]

MIN_ANALOGS = 5            # di bawah ini, probabilitas dianggap TIDAK reliable
DEFAULT_K = 15              # jumlah analog yang diambil (kalau tersedia)
EXCLUDE_RECENT_DAYS = 15    # jangan izinkan analog dari N hari terakhir --
                             # hindari autokorelasi trivial (besok mirip hari ini)
ANALOG_SCORE_CAP = 5.0      # lihat ta_engine.py::CompositeScore untuk alokasi poin


@dataclass
class AnalogResult:
    ticker: str
    n_analogs: int = 0
    win_rate: float = 0.0          # 0-100, % analog yang net_pnl_pct > 0
    avg_return_pct: float = 0.0
    median_return_pct: float = 0.0
    analog_dates: list = field(default_factory=list)
    reliable: bool = False          # True kalau n_analogs >= min_analogs yang diminta


def _build_feature_matrix(df_ind: pd.DataFrame) -> pd.DataFrame:
    """7 dimensi teknikal -- lihat AUDIT soal subjektivitas pemilihan fitur di docstring modul."""
    feat = pd.DataFrame(index=df_ind.index)
    feat["rsi"] = df_ind["rsi"]
    feat["adx"] = df_ind["adx"]
    feat["di_diff"] = df_ind["plus_di"] - df_ind["minus_di"]
    feat["atr_pct"] = df_ind["atr_pct"]
    feat["bb_position"] = df_ind["bb_position"]
    feat["price_vs_ema20_pct"] = ((df_ind["close"] / df_ind["ema20"].replace(0, np.nan)) - 1) * 100
    feat["cmf"] = df_ind["cmf"]
    return feat


def find_analogs(
    ticker: str,
    df: pd.DataFrame,
    ihsg_close: Optional[pd.Series] = None,
    k: int = DEFAULT_K,
    min_analogs: int = MIN_ANALOGS,
) -> AnalogResult:
    """
    Cari K analog historis untuk `ticker` berdasarkan `df` (OHLCV, idealnya
    ~3 tahun -- lihat get_ohlcv_from_db(ticker, days=365*3)), simulasikan
    trade di tiap analog, kembalikan AnalogResult.

    NO-LOOKAHEAD: kandidat analog dibatasi punya cukup hari SETELAHNYA
    untuk simulasi FORWARD_CANDLES hari (sama seperti backtest biasa),
    dan EXCLUDE_RECENT_DAYS hari terakhir di-exclude dari kandidat.
    """
    min_rows_needed = MIN_WARMUP_ROWS + FORWARD_CANDLES + EXCLUDE_RECENT_DAYS + min_analogs + 5
    if df is None or len(df) < min_rows_needed:
        return AnalogResult(ticker=ticker)

    df_ind = _add_indicators(df, ihsg_close=ihsg_close)
    if df_ind is None or len(df_ind) < min_rows_needed:
        return AnalogResult(ticker=ticker)

    feat = _build_feature_matrix(df_ind)
    n = len(df_ind)
    today_pos = n - 1
    today_vec = feat.iloc[today_pos]
    if today_vec.isna().any():
        # Data hari terakhir sendiri belum lengkap (co. baru IPO/baru
        # delisting sebentar, indikator belum matang) -- jangan paksa.
        return AnalogResult(ticker=ticker)

    candidate_end = min(n - FORWARD_CANDLES - 2, n - EXCLUDE_RECENT_DAYS)
    candidate_positions = [
        i for i in range(MIN_WARMUP_ROWS, candidate_end)
        if not feat.iloc[i].isna().any()
    ]

    if len(candidate_positions) < min_analogs:
        return AnalogResult(ticker=ticker)

    cand_matrix = feat.iloc[candidate_positions].to_numpy(dtype=float)
    mean = np.nanmean(cand_matrix, axis=0)
    std = np.nanstd(cand_matrix, axis=0)
    std[std == 0] = 1.0  # hindari div-by-zero kalau 1 fitur konstan di seluruh histori

    cand_z = (cand_matrix - mean) / std
    today_z = (today_vec.to_numpy(dtype=float) - mean) / std

    dist = np.sqrt(np.sum((cand_z - today_z) ** 2, axis=1))
    order = np.argsort(dist)[:k]
    nearest_positions = [candidate_positions[i] for i in order]

    outcomes = []
    analog_dates = []
    for pos in nearest_positions:
        try:
            trade = _simulate_trade(df_ind, pos, ticker=ticker)
        except Exception as e:
            log.debug(f"{ticker}: simulate_trade gagal di posisi {pos}: {e}")
            continue
        if trade.exit_reason in ("INVALID", "NO_NEXT_BAR"):
            continue
        outcomes.append(trade.net_pnl_pct)
        analog_dates.append(str(df_ind.index[pos])[:10])

    n_analogs = len(outcomes)
    if n_analogs < min_analogs:
        return AnalogResult(ticker=ticker, n_analogs=n_analogs)

    outcomes_arr = np.array(outcomes)
    win_rate = float((outcomes_arr > 0).mean() * 100)
    avg_return = float(outcomes_arr.mean())
    median_return = float(np.median(outcomes_arr))

    return AnalogResult(
        ticker=ticker,
        n_analogs=n_analogs,
        win_rate=round(win_rate, 1),
        avg_return_pct=round(avg_return, 2),
        median_return_pct=round(median_return, 2),
        analog_dates=sorted(analog_dates),
        reliable=n_analogs >= min_analogs,
    )


def score_from_analog(result: AnalogResult) -> float:
    """
    Konversi AnalogResult jadi analog_score (0-5 poin, komponen BARU di
    composite score -- lihat AUDIT CompositeScore di ta_engine.py, 5
    poin diambil dari volume_score yang paling lemah buktinya sejauh
    ini, bukan potongan sembarangan).

    Kalau tidak reliable (n_analogs < minimum), return 0 -- JANGAN
    paksa jadi skor kalau datanya tidak cukup dipercaya, konsisten
    dengan prinsip yang sama dipakai di seluruh sistem ini.

    Linear dari win_rate 50% (setara lempar koin, tidak ada edge
    historis) -> 0 poin, sampai 100% -> ANALOG_SCORE_CAP poin. Di
    bawah 50%, TETAP 0 -- jangan reward performa historis di bawah
    rata-rata.
    """
    if not result.reliable:
        return 0.0
    if result.win_rate <= 50:
        return 0.0
    return round(min(ANALOG_SCORE_CAP, (result.win_rate - 50) / 50 * ANALOG_SCORE_CAP), 1)
