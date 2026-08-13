"""
DAILY SIGNAL — Broker Flow Engine (Bandarmologi)
Analisis akumulasi/distribusi broker per saham, dari tabel broker_summary.
Fitur ala NeoBDM: Broker Flow (1 saham, semua broker), Broker Stalker
(1 broker, semua saham), screener akumulasi, ringkasan broker lengkap.

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
            .select("broker_code, broker_name, buy_value, sell_value, net_value")
            .eq("ticker", ticker)
            .eq("trade_date", snap_date)
            .execute()
        )
        rows = raw.data or []
        rows_sorted_buy = sorted(rows, key=lambda r: r.get("net_value") or 0, reverse=True)

        top_buyers = [
            {"broker_code": r["broker_code"], "broker_name": r.get("broker_name"), "net_value": r.get("net_value") or 0}
            for r in rows_sorted_buy[:3] if (r.get("net_value") or 0) > 0
        ]
        top_sellers = [
            {"broker_code": r["broker_code"], "broker_name": r.get("broker_name"), "net_value": r.get("net_value") or 0}
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


def get_top_accumulated_tickers(
    trade_date: Optional[date] = None,
    limit: int = 20,
    min_streak_days: int = 0,
) -> list[dict]:
    """
    Screener: saham dengan net foreign+domestik value tertinggi pada 1
    tanggal. Dasar untuk halaman dashboard "Broker Flow".

    min_streak_days (BARU, ala NeoBDM "consistent accumulation" filter):
    kalau >0, cuma kembalikan saham yang net_value-nya positif beruntun
    minimal segitu hari. Streak DIHITUNG cuma untuk kandidat teratas (bukan
    seluruh universe) supaya tidak jadi N+1 query ke seluruh tabel --
    ambil kandidat 4x lebih banyak dari `limit` dulu, baru difilter.
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

        candidate_limit = limit * 4 if min_streak_days > 0 else limit
        result = q.order("total_net_value", desc=True).limit(candidate_limit).execute()
        rows = result.data or []

        if min_streak_days > 0:
            filtered = []
            for r in rows:
                streak = _calc_accumulation_streak(r["ticker"], r["trade_date"])
                if streak >= min_streak_days:
                    r["accumulation_streak_days"] = streak
                    filtered.append(r)
                if len(filtered) >= limit:
                    break
            return filtered

        return rows[:limit]
    except Exception as e:
        log.warning(f"Gagal ambil top accumulated tickers: {e}")
        return []


# ══════════════════════════════════════════════════════════════════
#  BROKER STALKER & fitur ala NeoBDM lainnya (BARU)
# ══════════════════════════════════════════════════════════════════

def get_known_brokers() -> list[dict]:
    """Daftar broker dari broker_classification -- buat dropdown Broker Stalker di dashboard."""
    try:
        db = get_db()
        result = (
            db.table("broker_classification")
            .select("broker_code, broker_name, investor_type")
            .eq("is_active", True)
            .order("broker_code")
            .execute()
        )
        return result.data or []
    except Exception as e:
        log.warning(f"Gagal ambil daftar broker: {e}")
        return []


def get_broker_stalker(broker_code: str, trade_date: Optional[date] = None, limit: int = 20) -> list[dict]:
    """
    "Broker Stalker" (ala NeoBDM) -- lacak SATU broker lintas SEMUA saham
    pada 1 tanggal, diranking dari |net_value| terbesar (entah akumulasi
    besar atau distribusi besar, keduanya "aktivitas besar" broker itu).
    Beda dari get_broker_flow_snapshot yang arahnya kebalik (1 saham,
    semua broker) -- ini 1 broker, semua saham.
    """
    try:
        db = get_db()
        q = db.table("broker_summary").select("*").eq("broker_code", broker_code)
        if trade_date:
            q = q.eq("trade_date", trade_date.isoformat())
        else:
            latest = (
                db.table("broker_summary").select("trade_date")
                .eq("broker_code", broker_code)
                .order("trade_date", desc=True).limit(1).execute()
            )
            if not latest.data:
                return []
            q = q.eq("trade_date", latest.data[0]["trade_date"])

        result = q.execute()
        rows = result.data or []
        rows.sort(key=lambda r: abs(r.get("net_value") or 0), reverse=True)
        return rows[:limit]
    except Exception as e:
        log.warning(f"Gagal ambil broker stalker {broker_code}: {e}")
        return []


def get_full_broker_summary(ticker: str, trade_date: Optional[date] = None) -> list[dict]:
    """
    Tabel broker summary MENTAH -- SEMUA broker (bukan cuma top-3 seperti
    get_broker_flow_snapshot) untuk 1 saham pada 1 tanggal. Basis tabel
    "Ringkasan Broker Lengkap" ala NeoBDM di halaman detail saham.
    """
    try:
        db = get_db()
        q = db.table("broker_summary").select("*").eq("ticker", ticker)
        if trade_date:
            q = q.eq("trade_date", trade_date.isoformat())
        else:
            latest = (
                db.table("broker_summary").select("trade_date")
                .eq("ticker", ticker)
                .order("trade_date", desc=True).limit(1).execute()
            )
            if not latest.data:
                return []
            q = q.eq("trade_date", latest.data[0]["trade_date"])

        result = q.order("net_value", desc=True).execute()
        return result.data or []
    except Exception as e:
        log.warning(f"Gagal ambil full broker summary {ticker}: {e}")
        return []


def get_broker_footprint(ticker: str, broker_code: str, days: int = 60) -> list[dict]:
    """
    "Jejak" 1 broker di 1 saham selama N hari terakhir -- histori
    buy/sell/net harian. Dasar chart footprint broker per saham.
    """
    try:
        db = get_db()
        since = (date.today() - timedelta(days=days)).isoformat()
        result = (
            db.table("broker_summary")
            .select("trade_date, buy_value, sell_value, net_value, net_volume")
            .eq("ticker", ticker).eq("broker_code", broker_code)
            .gte("trade_date", since)
            .order("trade_date")
            .execute()
        )
        return result.data or []
    except Exception as e:
        log.warning(f"Gagal ambil broker footprint {ticker}/{broker_code}: {e}")
        return []
