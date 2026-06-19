"""
DAILY SIGNAL — Portfolio Tracker
Melacak posisi aktif, PnL, dan statistik trading.

Features:
    - Open/Close positions
    - Unrealized & Realized PnL
    - Win Rate, Expectancy, Profit Factor
    - Max Drawdown
    - Equity Curve data untuk dashboard
"""

from datetime import date, datetime
from typing import Optional
from dataclasses import dataclass

from src.core.database import get_db
from src.core.logger import get_logger

log = get_logger("portfolio")


@dataclass
class PortfolioStats:
    """Statistik lengkap portfolio."""
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    win_rate: float = 0.0
    total_realized_pnl: float = 0.0
    total_unrealized_pnl: float = 0.0
    avg_gain_pct: float = 0.0
    avg_loss_pct: float = 0.0
    profit_factor: float = 0.0
    expectancy: float = 0.0
    max_drawdown_pct: float = 0.0
    num_open_positions: int = 0
    total_invested: float = 0.0


def open_position(
    ticker: str,
    entry_price: float,
    shares: int,
    stop_loss: float,
    target_1: float,
    target_2: float,
    signal_id: Optional[str] = None,
    notes: str = "",
) -> Optional[str]:
    """
    Buka posisi baru.
    Return position_id atau None jika gagal.
    """
    try:
        db = get_db()
        result = db.table("open_positions").insert({
            "ticker": ticker,
            "signal_id": signal_id,
            "entry_date": date.today().isoformat(),
            "entry_price": entry_price,
            "shares": shares,
            "stop_loss": stop_loss,
            "target_1": target_1,
            "target_2": target_2,
            "current_price": entry_price,
            "unrealized_pnl": 0.0,
            "unrealized_pct": 0.0,
            "notes": notes,
        }).execute()

        if result.data:
            pos_id = result.data[0]["id"]
            log.info(f"✓ Posisi dibuka: {ticker} × {shares} @ Rp{entry_price:,.0f} [id={pos_id[:8]}]")
            return pos_id
        return None
    except Exception as e:
        log.error(f"Gagal buka posisi {ticker}: {e}", exc=e)
        return None


def close_position(
    position_id: str,
    exit_price: float,
    exit_reason: str = "MANUAL",
    notes: str = "",
    screenshot_url: str = "",
) -> Optional[dict]:
    """
    Tutup posisi dan pindahkan ke closed_positions.
    Return dict PnL summary atau None jika gagal.
    """
    try:
        db = get_db()

        # Ambil data posisi
        result = db.table("open_positions").select("*").eq("id", position_id).execute()
        if not result.data:
            log.warning(f"Posisi {position_id} tidak ditemukan")
            return None

        pos = result.data[0]
        ticker = pos["ticker"]
        entry_price = float(pos["entry_price"])
        shares = int(pos["shares"])

        # Hitung PnL
        gross_pnl = (exit_price - entry_price) * shares
        # Komisi BEI: beli 0.19% + jual 0.29% (termasuk PPh 0.1%)
        buy_commission = entry_price * shares * 0.0019
        sell_commission = exit_price * shares * 0.0029
        total_commission = buy_commission + sell_commission
        net_pnl = gross_pnl - total_commission
        return_pct = (exit_price / entry_price - 1) * 100

        entry_date = date.fromisoformat(pos["entry_date"])
        exit_date = date.today()
        holding_days = (exit_date - entry_date).days

        # Insert ke closed_positions
        db.table("closed_positions").insert({
            "ticker": ticker,
            "signal_id": pos.get("signal_id"),
            "entry_date": pos["entry_date"],
            "exit_date": exit_date.isoformat(),
            "entry_price": entry_price,
            "exit_price": exit_price,
            "shares": shares,
            "gross_pnl": round(gross_pnl, 2),
            "commission": round(total_commission, 2),
            "net_pnl": round(net_pnl, 2),
            "return_pct": round(return_pct / 100, 6),
            "exit_reason": exit_reason,
            "holding_days": holding_days,
            "exit_reason_note": notes,
            "screenshot_url": screenshot_url,
        }).execute()

        # Hapus dari open_positions
        db.table("open_positions").delete().eq("id", position_id).execute()

        log.info(
            f"✓ Posisi ditutup: {ticker} | Entry: Rp{entry_price:,.0f} "
            f"Exit: Rp{exit_price:,.0f} | PnL: Rp{net_pnl:,.0f} ({return_pct:+.2f}%)"
        )

        return {
            "ticker": ticker,
            "entry_price": entry_price,
            "exit_price": exit_price,
            "shares": shares,
            "gross_pnl": gross_pnl,
            "commission": total_commission,
            "net_pnl": net_pnl,
            "return_pct": return_pct,
            "holding_days": holding_days,
        }

    except Exception as e:
        log.error(f"Gagal tutup posisi {position_id}: {e}", exc=e)
        return None


def update_open_positions_prices() -> int:
    """
    Update harga terkini untuk semua posisi aktif.
    Dipanggil setiap hari untuk update unrealized PnL.
    Return jumlah posisi yang diupdate.
    """
    from src.providers.market_data import MarketDataProvider

    try:
        db = get_db()
        result = db.table("open_positions").select("id, ticker, entry_price, shares").execute()
        positions = result.data or []

        if not positions:
            return 0

        provider = MarketDataProvider()
        updated = 0

        for pos in positions:
            try:
                df = provider.fetch_ohlcv(pos["ticker"], period="2d")
                if df is None or df.empty:
                    continue

                current_price = float(df["close"].iloc[-1])
                entry_price = float(pos["entry_price"])
                shares = int(pos["shares"])

                unrealized_pnl = (current_price - entry_price) * shares
                unrealized_pct = (current_price / entry_price - 1) * 100

                db.table("open_positions").update({
                    "current_price": current_price,
                    "unrealized_pnl": round(unrealized_pnl, 2),
                    "unrealized_pct": round(unrealized_pct / 100, 6),
                    "updated_at": datetime.utcnow().isoformat(),
                }).eq("id", pos["id"]).execute()

                updated += 1
            except Exception as e:
                log.warning(f"Update harga gagal untuk {pos['ticker']}: {e}")

        log.info(f"Updated harga {updated} posisi aktif")
        return updated

    except Exception as e:
        log.error(f"Update posisi gagal: {e}", exc=e)
        return 0


def get_portfolio_stats() -> PortfolioStats:
    """Hitung statistik lengkap portfolio."""
    try:
        db = get_db()

        # Open positions
        open_result = db.table("open_positions").select("unrealized_pnl, entry_price, shares").execute()
        open_pos = open_result.data or []

        total_unrealized = sum(float(p.get("unrealized_pnl") or 0) for p in open_pos)
        total_invested = sum(
            float(p.get("entry_price", 0)) * int(p.get("shares", 0))
            for p in open_pos
        )

        # Closed positions
        closed_result = db.table("closed_positions").select(
            "net_pnl, return_pct, gross_pnl"
        ).execute()
        closed = closed_result.data or []

        if not closed:
            return PortfolioStats(
                num_open_positions=len(open_pos),
                total_unrealized_pnl=round(total_unrealized, 2),
                total_invested=round(total_invested, 2),
            )

        wins = [c for c in closed if float(c.get("net_pnl", 0)) > 0]
        losses = [c for c in closed if float(c.get("net_pnl", 0)) <= 0]

        total_trades = len(closed)
        win_count = len(wins)
        loss_count = len(losses)
        win_rate = win_count / total_trades if total_trades > 0 else 0

        total_realized = sum(float(c.get("net_pnl", 0)) for c in closed)

        avg_gain = (
            sum(float(c.get("return_pct", 0)) * 100 for c in wins) / win_count
            if wins else 0
        )
        avg_loss = (
            sum(float(c.get("return_pct", 0)) * 100 for c in losses) / loss_count
            if losses else 0
        )

        # Profit Factor: total gain / total loss (absolute)
        gross_gains = sum(float(c.get("gross_pnl", 0)) for c in wins)
        gross_losses = abs(sum(float(c.get("gross_pnl", 0)) for c in losses))
        profit_factor = gross_gains / gross_losses if gross_losses > 0 else float("inf")

        # Expectancy: (WR × avg_gain) - (LR × avg_loss)
        loss_rate = 1 - win_rate
        expectancy = (win_rate * avg_gain) - (loss_rate * abs(avg_loss))

        # Max Drawdown (simplified — dari equity curve)
        max_dd = _calc_max_drawdown(closed)

        return PortfolioStats(
            total_trades=total_trades,
            winning_trades=win_count,
            losing_trades=loss_count,
            win_rate=round(win_rate, 4),
            total_realized_pnl=round(total_realized, 2),
            total_unrealized_pnl=round(total_unrealized, 2),
            avg_gain_pct=round(avg_gain, 2),
            avg_loss_pct=round(avg_loss, 2),
            profit_factor=round(profit_factor, 2),
            expectancy=round(expectancy, 2),
            max_drawdown_pct=round(max_dd, 2),
            num_open_positions=len(open_pos),
            total_invested=round(total_invested, 2),
        )

    except Exception as e:
        log.error(f"Gagal hitung stats: {e}", exc=e)
        return PortfolioStats()


def _calc_max_drawdown(closed_positions: list) -> float:
    """Hitung max drawdown dari sequential closed positions."""
    if not closed_positions:
        return 0.0

    cumulative = 0.0
    peak = 0.0
    max_dd = 0.0

    for pos in sorted(closed_positions, key=lambda x: x.get("exit_date", "")):
        pnl = float(pos.get("net_pnl", 0))
        cumulative += pnl

        if cumulative > peak:
            peak = cumulative

        drawdown = (peak - cumulative) / abs(peak) * 100 if peak > 0 else 0
        if drawdown > max_dd:
            max_dd = drawdown

    return max_dd


def get_open_positions() -> list[dict]:
    """Ambil semua posisi aktif dengan data lengkap."""
    try:
        db = get_db()
        result = db.table("open_positions").select("*").order("entry_date", desc=True).execute()
        return result.data or []
    except Exception as e:
        log.error(f"Gagal ambil posisi: {e}")
        return []


def get_closed_positions(limit: int = 50) -> list[dict]:
    """Ambil posisi yang sudah ditutup."""
    try:
        db = get_db()
        result = (
            db.table("closed_positions")
            .select("*")
            .order("exit_date", desc=True)
            .limit(limit)
            .execute()
        )
        return result.data or []
    except Exception as e:
        log.error(f"Gagal ambil closed positions: {e}")
        return []


def save_portfolio_snapshot():
    """Simpan snapshot portfolio harian untuk equity curve."""
    try:
        stats = get_portfolio_stats()
        db = get_db()

        db.table("portfolio_snapshots").upsert({
            "snapshot_date": date.today().isoformat(),
            "total_equity": stats.total_invested + stats.total_unrealized_pnl,
            "invested_value": stats.total_invested,
            "unrealized_pnl": stats.total_unrealized_pnl,
            "realized_pnl_ytd": stats.total_realized_pnl,
            "num_open_positions": stats.num_open_positions,
        }, on_conflict="snapshot_date").execute()

        log.info("Portfolio snapshot disimpan")
    except Exception as e:
        log.error(f"Gagal simpan portfolio snapshot: {e}")
