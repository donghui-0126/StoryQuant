"""
Paper trading engine for StoryQuant.
Automatically generates trades from events/attributions and tracks performance.
"""
import json
import logging
from datetime import datetime, timezone, timedelta
import sqlite3
import pandas as pd

logger = logging.getLogger(__name__)


def generate_signals(conn) -> list[dict]:
    """
    Generate trading signals from recent events and attributions.
    Returns list of signal dicts ready for insert_trade.
    """
    signals = []

    # 1. High-confidence attribution signals
    # If a price event has high-confidence attribution, trade in that direction
    attr_df = pd.read_sql_query("""
        SELECT a.event_id, a.confidence, a.total_score, e.ticker, e.return_1h, e.event_type, e.timestamp,
               ar.title as news_title
        FROM attributions a
        JOIN events e ON a.event_id = e.id
        JOIN articles ar ON a.article_id = ar.id
        WHERE a.confidence = 'high' AND a.rank = 1
            AND e.timestamp >= datetime('now', '-1 hour')
            AND e.event_type IN ('surge', 'crash')
    """, conn)

    for _, row in attr_df.iterrows():
        direction = "long" if row["event_type"] == "surge" else "short"
        # Get current price
        price = conn.execute(
            "SELECT close FROM prices WHERE ticker = ? ORDER BY timestamp DESC LIMIT 1",
            [row["ticker"]]
        ).fetchone()
        if not price:
            continue

        signals.append({
            "signal_type": "attribution_signal",
            "ticker": row["ticker"],
            "direction": direction,
            "entry_price": price[0],
            "entry_time": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "signal_details": json.dumps({
                "event_type": row["event_type"],
                "return_1h": float(row["return_1h"]),
                "news": row["news_title"],
                "confidence": row["confidence"],
                "score": float(row["total_score"]),
            }, ensure_ascii=False),
            "event_id": int(row["event_id"]),
        })

    # 2. OI divergence signals
    # If OI is spiking but price is flat → potential liquidation cascade
    try:
        oi_df = pd.read_sql_query("""
            SELECT ticker, open_interest, long_short_ratio, timestamp
            FROM open_interest
            WHERE timestamp >= datetime('now', '-2 hours')
            ORDER BY timestamp DESC
        """, conn)

        if not oi_df.empty:
            for ticker in oi_df["ticker"].unique():
                ticker_oi = oi_df[oi_df["ticker"] == ticker]
                if len(ticker_oi) >= 2:
                    latest = ticker_oi.iloc[0]
                    prev = ticker_oi.iloc[-1]
                    oi_change = (latest["open_interest"] - prev["open_interest"]) / prev["open_interest"] if prev["open_interest"] else 0
                    ls_ratio = latest.get("long_short_ratio", 1.0) or 1.0

                    # Strong signal: OI up 5%+ and extreme L/S ratio
                    if abs(oi_change) > 0.05 and (ls_ratio > 2.0 or ls_ratio < 0.5):
                        direction = "short" if ls_ratio > 2.0 else "long"  # Contrarian
                        price = conn.execute(
                            "SELECT close FROM prices WHERE ticker = ? ORDER BY timestamp DESC LIMIT 1",
                            [ticker]
                        ).fetchone()
                        if price:
                            signals.append({
                                "signal_type": "oi_signal",
                                "ticker": ticker,
                                "direction": direction,
                                "entry_price": price[0],
                                "entry_time": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                                "signal_details": json.dumps({
                                    "oi_change_pct": round(oi_change * 100, 2),
                                    "long_short_ratio": float(ls_ratio),
                                    "reason": "extreme L/S ratio + OI spike (contrarian)",
                                }, ensure_ascii=False),
                            })
    except Exception:
        pass

    # 3. Narrative-based signals
    try:
        from src.analysis.narrative import detect_narratives, get_narrative_signals
        narratives = detect_narratives(conn, hours=6)
        narrative_sigs = get_narrative_signals(narratives)
        for ns in narrative_sigs:
            price = conn.execute(
                "SELECT close FROM prices WHERE ticker = ? ORDER BY timestamp DESC LIMIT 1",
                [ns["ticker"]]
            ).fetchone()
            if not price:
                continue
            signals.append({
                "signal_type": "narrative_signal",
                "ticker": ns["ticker"],
                "direction": ns["direction"],
                "entry_price": price[0],
                "entry_time": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "signal_details": json.dumps({
                    "narrative": ns["narrative"],
                    "lifecycle": ns["lifecycle"],
                    "strength": ns["strength"],
                    "confidence": ns["confidence"],
                }, ensure_ascii=False),
            })
    except Exception:
        pass

    return signals


def check_and_close_trades(conn, max_hold_hours: int = 24):
    """
    Check open trades and close them if:
    1. Take profit: pnl > 3%
    2. Stop loss: pnl < -2%
    3. Time expiry: held > max_hold_hours
    """
    from src.db.queries import close_trade

    open_trades = pd.read_sql_query("SELECT * FROM trades WHERE status = 'open'", conn)

    for _, trade in open_trades.iterrows():
        price = conn.execute(
            "SELECT close FROM prices WHERE ticker = ? ORDER BY timestamp DESC LIMIT 1",
            [trade["ticker"]]
        ).fetchone()
        if not price:
            continue

        current_price = price[0]
        entry_price = trade["entry_price"]
        direction = trade["direction"]

        if direction == "long":
            pnl_pct = (current_price - entry_price) / entry_price * 100
        else:
            pnl_pct = (entry_price - current_price) / entry_price * 100

        entry_time = pd.to_datetime(trade["entry_time"], utc=True)
        hours_held = (datetime.now(timezone.utc) - entry_time).total_seconds() / 3600

        should_close = False
        if pnl_pct >= 3.0:  # Take profit
            should_close = True
        elif pnl_pct <= -2.0:  # Stop loss
            should_close = True
        elif hours_held >= max_hold_hours:  # Time expiry
            should_close = True

        if should_close:
            close_trade(conn, int(trade["id"]), current_price,
                       datetime.now(timezone.utc).isoformat(timespec="seconds"))
            logger.info("Closed trade %d: %s %s pnl=%.2f%%",
                       trade["id"], trade["ticker"], trade["direction"], pnl_pct)


def run_paper_trading_cycle(conn):
    """Run one cycle: generate signals, open trades, check existing trades."""
    from src.db.queries import insert_trade, get_open_trades

    # Check existing trades first
    check_and_close_trades(conn)

    # Don't open new trades if we already have too many open
    open_trades = get_open_trades(conn)
    if len(open_trades) >= 5:  # Max 5 concurrent positions
        return

    # Generate and execute new signals
    signals = generate_signals(conn)
    for sig in signals:
        # Check we don't already have a position in this ticker
        existing = open_trades[open_trades["ticker"] == sig["ticker"]] if not open_trades.empty else pd.DataFrame()
        if not existing.empty:
            continue
        trade_id = insert_trade(conn, sig)
        logger.info("Opened trade %d: %s %s @ %.2f (%s)",
                    trade_id, sig["ticker"], sig["direction"], sig["entry_price"], sig["signal_type"])
