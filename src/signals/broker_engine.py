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

import pandas as pd

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


# ══════════════════════════════════════════════════════════════════
#  NET BUY WINDOW (BARU, ala NeoBDM)
# ══════════════════════════════════════════════════════════════════

def get_net_buy_window(
    window_days: int = 3,
    min_brokers: int = 3,
    min_topn_net: float = 10_000_000,
    top_n_brokers: int = 5,
    limit: int = 20,
) -> list[dict]:
    """
    "Net Buy Window" (ala NeoBDM) -- saham dengan akumulasi beli KOLEKTIF
    oleh minimal `min_brokers` broker berbeda dalam `window_days` hari
    PERDAGANGAN terakhir (bukan hari kalender -- weekend/tanggal kosong
    di broker_summary otomatis dilompati), dengan Top-N Net (net value
    gabungan broker akumulasi terbesar) >= min_topn_net.

    Definisi tiap kolom (v2, 2026-08 -- disesuaikan PERSIS dengan
    referensi "Table Field Reference" yang diberikan user; v1 sebelumnya
    salah untuk broker_concentration & avg_net_per_broker, lihat AUDIT
    di bawah):
      - top_brokers    : 3 kode broker akumulasi (net positif) terbesar
      - dominant_broker: 1 kode broker akumulasi TERBESAR (buat statistik
                          agregat "Broker Dominan" di level halaman)
      - topn_net       : jumlah net_value dari `top_n_brokers` broker
                          akumulasi terbesar selama window ("power akumulasi")
      - topn_gross     : jumlah (buy_value+sell_value) broker2 itu
                          ("pembanding intensitas")
      - buyer_share_pct: topn_net/topn_gross*100 -- "rasio kekuatan beli
                          bersih terhadap total aktivitas broker kandidat".
                          Mendekati 100% = dominasi net buy (sedikit jual
                          balik dari broker yang sama)
      - broker_concentration_pct: net_value broker TERBESAR / topn_net * 100
                          -- "persentase dominasi broker terbesar terhadap
                          total net buy". RENDAH = akumulasi lebih sehat &
                          menyebar ke banyak broker, TINGGI = didominasi
                          1 broker (bisa 1 whale, bukan konsensus banyak
                          pihak -- beda konsep dari buyer_share_pct)
      - avg_net_per_broker: topn_net / jumlah broker YANG DIPAKAI hitung
                          topn_net (bukan broker_count total, biar
                          konsisten dgn pembilangnya) -- "kedalaman
                          komitmen, bukan sekadar partisipasi"
      - broker_count   : jumlah broker BERBEDA yang net-nya positif
                          selama window (BISA lebih dari top_n_brokers)
                          -- "validasi distribusi, hindari single-broker push"
      - consistency_days: dari `window_days` hari, berapa hari net TOTAL
                          saham itu (semua broker digabung) positif

    AUDIT (2026-08): v1 broker_concentration_pct pakai formula BEDA
    (topn_gross/total_market_gross -- "seberapa besar top-N vs SELURUH
    broker di saham itu") dari yang dimaksud user (dominasi broker
    TERBESAR vs total net buy KANDIDAT). Diperbaiki ke formula yang
    benar. avg_net_per_broker v1 juga tidak konsisten (pembilang topn_net
    cuma dari top-N, pembilang broker_count bisa lebih besar dari N) --
    diperbaiki jadi konsisten pakai jumlah broker yang SAMA dgn pembilang.

    CATATAN JUJUR SOAL METODOLOGI: meski sudah disesuaikan definisi
    tertulisnya, ini tetap REKONSTRUKSI dari deskripsi teks -- BUKAN
    salinan source code proprietary tool manapun. Diuji dengan data
    tiruan (lihat test di riwayat percakapan), tapi TIDAK divalidasi
    silang langsung terhadap tool referensi.

    Diurutkan sesuai prioritas yang diminta: consistency_days DESC,
    lalu broker_count/distribusi DESC, lalu buyer_share_pct/kualitas DESC.
    """
    try:
        db = get_db()

        latest = db.table("broker_summary").select("trade_date").order("trade_date", desc=True).limit(1).execute()
        if not latest.data:
            return []
        latest_date = latest.data[0]["trade_date"]

        # Cari window_days tanggal PERDAGANGAN unik terakhir (bukan window
        # kalender) -- ambil histori mentah lumayan lebar (500 baris
        # terbaru) buat nemu cukup tanggal unik walau ada gap data.
        recent_dates_raw = (
            db.table("broker_summary").select("trade_date")
            .lte("trade_date", latest_date)
            .order("trade_date", desc=True)
            .limit(500)
            .execute()
        )
        unique_dates = sorted({r["trade_date"] for r in (recent_dates_raw.data or [])}, reverse=True)
        window_dates = unique_dates[:window_days]
        if not window_dates:
            return []
        earliest_in_window = window_dates[-1]

        raw = (
            db.table("broker_summary")
            .select("ticker, trade_date, broker_code, buy_value, sell_value, net_value")
            .gte("trade_date", earliest_in_window)
            .lte("trade_date", latest_date)
            .execute()
        )
        rows = raw.data or []
        if not rows:
            return []

        df = pd.DataFrame(rows)
        df = df[df["trade_date"].isin(window_dates)]
        if df.empty:
            return []

        for col in ["buy_value", "sell_value", "net_value"]:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
        df["gross_value"] = df["buy_value"] + df["sell_value"]

        results = []
        for ticker, g in df.groupby("ticker"):
            per_broker = g.groupby("broker_code").agg(
                net_value=("net_value", "sum"),
                gross_value=("gross_value", "sum"),
            ).reset_index()

            accumulating = per_broker[per_broker["net_value"] > 0].sort_values("net_value", ascending=False)
            broker_count = len(accumulating)
            if broker_count < min_brokers:
                continue

            top_n = accumulating.head(top_n_brokers)
            n_used = len(top_n)
            topn_net = float(top_n["net_value"].sum())
            if topn_net < min_topn_net:
                continue
            topn_gross = float(top_n["gross_value"].sum())
            buyer_share = (topn_net / topn_gross * 100) if topn_gross > 0 else 0.0

            # broker_concentration: dominasi broker TERBESAR terhadap total
            # net buy kandidat (BUKAN top-N gross vs total market gross --
            # lihat AUDIT di docstring). Rendah = sehat/menyebar.
            largest_broker_net = float(top_n["net_value"].iloc[0])
            broker_concentration = (largest_broker_net / topn_net * 100) if topn_net > 0 else 0.0

            daily_net = g.groupby("trade_date")["net_value"].sum()
            consistency_days = int((daily_net > 0).sum())

            # avg_net_per_broker: dibagi jumlah broker yang SAMA dgn yang
            # dijumlah di topn_net (n_used), bukan broker_count total --
            # supaya konsisten & tidak menyesatkan kalau broker_count > N.
            avg_net_per_broker = topn_net / n_used if n_used > 0 else 0.0

            results.append({
                "ticker": ticker,
                "top_brokers": ",".join(top_n["broker_code"].head(3).tolist()),
                "dominant_broker": str(top_n["broker_code"].iloc[0]),
                "topn_net": round(topn_net, 2),
                "topn_gross": round(topn_gross, 2),
                "buyer_share_pct": round(buyer_share, 1),
                "broker_concentration_pct": round(broker_concentration, 1),
                "avg_net_per_broker": round(avg_net_per_broker, 2),
                "broker_count": broker_count,
                "consistency_days": consistency_days,
                "window_days": len(window_dates),
                "window_start": earliest_in_window,
                "window_end": latest_date,
            })

        results.sort(
            key=lambda r: (r["consistency_days"], r["broker_count"], r["buyer_share_pct"]),
            reverse=True,
        )
        return results[:limit]

    except Exception as e:
        log.warning(f"Gagal hitung net buy window: {e}")
        return []


# ══════════════════════════════════════════════════════════════════
#  ZONA AKUMULASI/DISTRIBUSI (BARU) -- overlay chart candlestick
# ══════════════════════════════════════════════════════════════════

def get_accumulation_distribution_zones(
    ticker: str,
    days: int = 90,
    min_zone_days: int = 2,
) -> list[dict]:
    """
    Kelompokkan hari-hari perdagangan BERTURUT-TURUT dengan net flow
    broker yang searah (net TOTAL positif = akumulasi, negatif =
    distribusi) jadi "zona" -- basis overlay kotak di chart candlestick
    (ala anotasi "AKUMULASI + SMART MONEY" di referensi visual).

    Zona dengan panjang < min_zone_days DIBUANG -- 1 hari nyembur bukan
    pola berkelanjutan, cuma noise kalau ditampilkan sebagai zona.

    HEURISTIK SEDERHANA -- bukan analisis Wyckoff formal (fase
    accumulation/markup/distribution/markdown yang sesungguhnya perlu
    analisis volume-price-range yang jauh lebih kompleks). Ini murni
    "berapa hari berturut-turut net broker searah", proxy kasar tapi
    transparan & mudah diverifikasi manual dari datanya.
    """
    try:
        db = get_db()
        since = (date.today() - timedelta(days=days)).isoformat()

        daily_result = (
            db.table("v_broker_net_flow_daily")
            .select("trade_date, total_net_value")
            .eq("ticker", ticker)
            .gte("trade_date", since)
            .order("trade_date")
            .execute()
        )
        daily_rows = daily_result.data or []
        if not daily_rows:
            return []

        raw_result = (
            db.table("broker_summary")
            .select("trade_date, broker_code, net_value")
            .eq("ticker", ticker)
            .gte("trade_date", since)
            .execute()
        )
        raw_rows = raw_result.data or []
        raw_df = pd.DataFrame(raw_rows) if raw_rows else pd.DataFrame(columns=["trade_date", "broker_code", "net_value"])
        if not raw_df.empty:
            raw_df["net_value"] = pd.to_numeric(raw_df["net_value"], errors="coerce").fillna(0)

        classified = []
        for r in daily_rows:
            net = float(r.get("total_net_value") or 0)
            cls = "AKUMULASI" if net > 0 else ("DISTRIBUSI" if net < 0 else "NETRAL")
            classified.append({"trade_date": r["trade_date"], "net_value": net, "cls": cls})

        zones = []
        current = None
        for row in classified:
            if row["cls"] == "NETRAL":
                # AUDIT (bug ditemukan via test): SEBELUMNYA reset current=None
                # di sini TANPA menyimpan zona yang sudah terbentuk ke `zones`
                # dulu -- zona yang sedang berjalan HILANG begitu ketemu 1 hari
                # netral di tengah. Diperbaiki: simpan dulu kalau ada.
                if current:
                    zones.append(current)
                current = None
                continue
            if current and current["cls"] == row["cls"]:
                current["end_date"] = row["trade_date"]
                current["total_net"] += row["net_value"]
                current["days"].append(row["trade_date"])
            else:
                if current:
                    zones.append(current)
                current = {
                    "cls": row["cls"], "start_date": row["trade_date"],
                    "end_date": row["trade_date"], "total_net": row["net_value"],
                    "days": [row["trade_date"]],
                }
        if current:
            zones.append(current)

        result_zones = []
        for z in zones:
            if len(z["days"]) < min_zone_days:
                continue

            dominant = None
            if not raw_df.empty:
                zone_df = raw_df[raw_df["trade_date"].isin(z["days"])]
                if not zone_df.empty:
                    per_broker = zone_df.groupby("broker_code")["net_value"].sum()
                    if len(per_broker):
                        dominant = str(per_broker.idxmax() if z["cls"] == "AKUMULASI" else per_broker.idxmin())

            result_zones.append({
                "zone_type": z["cls"],
                "start_date": z["start_date"],
                "end_date": z["end_date"],
                "total_net_value": round(z["total_net"], 2),
                "trading_days": len(z["days"]),
                "dominant_broker": dominant,
            })

        return result_zones

    except Exception as e:
        log.warning(f"Gagal hitung accumulation/distribution zones {ticker}: {e}")
        return []
