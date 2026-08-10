"""
DAILY SIGNAL — Broker Flow Engine (Bandarmology)
Analisis akumulasi/distribusi broker per saham, dari tabel broker_summary.

Modul ini TIDAK melakukan fetch data (lihat src/providers/broker_data.py) --
murni menganalisis apa yang sudah ada di database. Artinya modul ini bisa
langsung dites/dipakai begitu broker_summary mulai terisi, apapun provider
yang akhirnya dipilih.

Belum diikutsertakan ke composite scoring (raw_score) di ta_engine.py --
menyusul _score_strength/_score_volatility yang butuh validasi empiris n
memadai dulu sebelum masuk scoring (lihat pola AUDIT di ta_engine.py).
Untuk sekarang: sinyal informasional di dashboard, bukan bagian scoring.
"""

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional

from src.core.logger import get_logger
from src.core.database import get_db

log = get_logger("broker_engine")


@dataclass
class BrokerFlowSnapshot:
    ticker: str
    trade_date: str
    total_buy_value: float = 0.0
    total_sell_value: float = 0.0
    net_value: float = 0.0
    foreign_net_value: float = 0.0
    domestic_net_value: float = 0.0
    bumn_net_value: float = 0.0
    broker_count: int = 0
    top_buyers: list[dict] = field(default_factory=list)   # [{broker_code, net_value}, ...]
    top_sellers: list[dict] = field(default_factory=list)
    top3_concentration_pct: float = 0.0   # % dari total_buy_value yg dikuasai top 3 broker
    accumulation_streak_days: int = 0     # berapa hari beruntun net_value > 0


def get_broker_flow_snapshot(ticker: str, trade_date: Optional[date] = None) -> Optional[BrokerFlowSnapshot]:
    """
    Ambil 1 snapshot broker flow untuk 1 ticker pada 1 tanggal (default: hari
    terakhir yang ada datanya), pakai view v_broker_net_flow_daily + query
    top buyer/seller dari broker_summary mentah.
    """
    try:
        db = get_db()

        q = db.table("v_broker_net_flow_daily").select("*").eq("ticker", ticker)
        if trade_date:
            q = q.eq("trade_date", trade_date.isoformat())
        result = q.order("trade_date", desc=True).limit(1).execute()

        if not result.data:
            return None
        row = result.data[0]
        snap_date = row["trade_date"]

        raw = (
            db.table("broker_summary")
            .select("broker_code, buy_value, sell_value, net_value")
            .eq("ticker", ticker)
            .eq("trade_date", snap_date)
            .execute()
        )
        rows = raw.data or []
        rows_sorted_buy = sorted(rows, key=lambda r: r.get("net_value") or 0, reverse=True)

        top_buyers = [
            {"broker_code": r["broker_code"], "net_value": r.get("net_value") or 0}
            for r in rows_sorted_buy[:3] if (r.get("net_value") or 0) > 0
        ]
        top_sellers = [
            {"broker_code": r["broker_code"], "net_value": r.get("net_value") or 0}
            for r in rows_sorted_buy[-3:][::-1] if (r.get("net_value") or 0) < 0
        ]

        total_buy = sum(float(r.get("buy_value") or 0) for r in rows)
        top3_buy = sum(float(r.get("buy_value") or 0) for r in rows_sorted_buy[:3])
        concentration = round((top3_buy / total_buy * 100), 1) if total_buy > 0 else 0.0

        streak = _calc_accumulation_streak(ticker, snap_date)

        return BrokerFlowSnapshot(
            ticker=ticker,
            trade_date=snap_date,
            total_buy_value=float(row.get("total_buy_value") or 0),
            total_sell_value=float(row.get("total_sell_value") or 0),
            net_value=float(row.get("total_net_value") or 0),
            foreign_net_value=float(row.get("foreign_net_value") or 0),
            domestic_net_value=float(row.get("domestic_net_value") or 0),
            bumn_net_value=float(row.get("bumn_net_value") or 0),
            broker_count=int(row.get("broker_count") or 0),
            top_buyers=top_buyers,
            top_sellers=top_sellers,
            top3_concentration_pct=concentration,
            accumulation_streak_days=streak,
        )
    except Exception as e:
        log.warning(f"Gagal ambil broker flow snapshot {ticker}: {e}")
        return None


def _calc_accumulation_streak(ticker: str, as_of_date: str, max_lookback_days: int = 30) -> int:
    """Hitung berapa hari bursa beruntun net_value > 0 sampai as_of_date."""
    try:
        db = get_db()
        since = (date.fromisoformat(as_of_date) - timedelta(days=max_lookback_days)).isoformat()
        result = (
            db.table("v_broker_net_flow_daily")
            .select("trade_date, total_net_value")
            .eq("ticker", ticker)
            .gte("trade_date", since)
            .lte("trade_date", as_of_date)
            .order("trade_date", desc=True)
            .execute()
        )
        rows = result.data or []
        streak = 0
        for r in rows:
            if (r.get("total_net_value") or 0) > 0:
                streak += 1
            else:
                break
        return streak
    except Exception:
        return 0


def get_top_accumulated_tickers(trade_date: Optional[date] = None, limit: int = 20) -> list[dict]:
    """
    Screener sederhana: saham dengan net foreign+domestik value tertinggi
    pada 1 tanggal. Dasar untuk halaman dashboard "Broker Flow" dan
    kandidat screener otomatis yang diminta user.
    """
    try:
        db = get_db()
        q = db.table("v_broker_net_flow_daily").select("*")
        if trade_date:
            q = q.eq("trade_date", trade_date.isoformat())
        else:
            latest = db.table("broker_summary").select("trade_date").order("trade_date", desc=True).limit(1).execute()
            if not latest.data:
                return []
            q = q.eq("trade_date", latest.data[0]["trade_date"])
        result = q.order("total_net_value", desc=True).limit(limit).execute()
        return result.data or []
    except Exception as e:
        log.warning(f"Gagal ambil top accumulated tickers: {e}")
        return []
