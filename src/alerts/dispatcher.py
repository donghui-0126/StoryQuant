"""
Alert dispatcher - checks for new events, hot topics, and whale movements,
then sends real-time alerts with historical context via Telegram.

Persists last alert time in DB to avoid duplicates across restarts.
"""
import logging
import sqlite3
from datetime import datetime, timezone, timedelta

import pandas as pd

logger = logging.getLogger(__name__)


def _get_last_alert_time(conn: sqlite3.Connection) -> str:
    """Read last alert time from DB. Falls back to 5 min ago."""
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS alert_state (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)
        row = conn.execute(
            "SELECT value FROM alert_state WHERE key = 'last_alert_time'"
        ).fetchone()
        if row:
            return row[0]
    except Exception:
        pass
    return (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat(timespec="seconds")


def _set_last_alert_time(conn: sqlite3.Connection, ts: str):
    """Persist last alert time to DB."""
    try:
        conn.execute(
            "INSERT OR REPLACE INTO alert_state (key, value) VALUES ('last_alert_time', ?)",
            [ts],
        )
        conn.commit()
    except Exception as exc:
        logger.debug("Failed to persist alert time: %s", exc)


def dispatch_alerts(conn: sqlite3.Connection):
    """Check for new events, hot topics, and send alerts with historical context."""
    try:
        from src.alerts.telegram_bot import (
            telegram_available, send_message,
            format_event_alert, format_hot_topic_alert,
            format_whale_alert_msg,
        )
    except ImportError:
        return

    if not telegram_available():
        return

    cutoff = _get_last_alert_time(conn)

    # --- 1. Price Event Alerts (with historical context) ---
    _dispatch_event_alerts(conn, cutoff, send_message, format_event_alert)

    # --- 2. Hot Topic Alerts (proactive, pre-signal) ---
    _dispatch_topic_alerts(conn, cutoff, send_message, format_hot_topic_alert)

    # --- 3. Whale Movement Alerts ---
    _dispatch_whale_alerts(conn, cutoff, send_message, format_whale_alert_msg)

    # --- 4. Narrative Alerts ---
    _dispatch_narrative_alerts(conn, send_message)

    _set_last_alert_time(conn, datetime.now(timezone.utc).isoformat(timespec="seconds"))


def _dispatch_event_alerts(conn, cutoff, send_message, format_event_alert):
    """Send alerts for high/medium severity price events with historical stats."""
    events = pd.read_sql_query(
        """SELECT * FROM events
           WHERE event_type IS NOT NULL
             AND severity IN ('high','medium')
             AND timestamp >= ?
           ORDER BY timestamp DESC""",
        conn, params=[cutoff],
    )

    for _, event in events.iterrows():
        # Get top attribution
        attr = None
        if "id" in event:
            attr_row = pd.read_sql_query(
                """SELECT a.*, ar.title as news_title
                   FROM attributions a JOIN articles ar ON a.article_id = ar.id
                   WHERE a.event_id = ? AND a.rank = 1""",
                conn, params=[int(event["id"])],
            )
            if not attr_row.empty:
                attr = attr_row.iloc[0].to_dict()

        # Get historical stats for this event type
        historical = _get_historical_stats(conn, event.get("ticker"), event.get("event_type"))

        msg = format_event_alert(event.to_dict(), attr, historical)
        send_message(msg)
        logger.info("[alerts] Event alert: %s %s", event.get("ticker"), event.get("event_type"))


def _dispatch_topic_alerts(conn, cutoff, send_message, format_hot_topic_alert):
    """Send alerts when a new hot topic emerges that historically moved prices."""
    topics = pd.read_sql_query(
        """SELECT * FROM topics
           WHERE created_at >= ?
           ORDER BY momentum_score DESC
           LIMIT 3""",
        conn, params=[cutoff],
    )

    if topics.empty:
        return

    for _, topic in topics.iterrows():
        momentum = topic.get("momentum_score", 0)
        novelty = topic.get("novelty_score", 0)

        # Only alert on high-momentum or novel topics
        if momentum < 0.5 and novelty < 0.7:
            continue

        # Get historical performance for this topic type
        topic_hist = _get_topic_historical(conn, topic.get("topic_label", ""))

        msg = format_hot_topic_alert(topic.to_dict(), topic_hist)
        send_message(msg)
        logger.info("[alerts] Topic alert: %s", topic.get("topic_label"))


def _dispatch_whale_alerts(conn, cutoff, send_message, format_whale_alert_msg):
    """Send alerts for large whale transfers."""
    whales = pd.read_sql_query(
        """SELECT * FROM whale_transfers
           WHERE timestamp >= ? AND usd_value >= 5000000
           ORDER BY usd_value DESC
           LIMIT 5""",
        conn, params=[cutoff],
    )

    for _, whale in whales.iterrows():
        msg = format_whale_alert_msg(whale.to_dict())
        send_message(msg)
        logger.info("[alerts] Whale alert: %s $%.0fM", whale.get("token"), whale.get("usd_value", 0) / 1e6)


def _get_historical_stats(conn, ticker, event_type) -> dict:
    """Get historical stats for a given ticker + event_type combo."""
    try:
        row = conn.execute(
            """SELECT
                AVG(e2.return_1h) as avg_next_return,
                COUNT(*) as sample_count,
                SUM(CASE WHEN
                    (e1.event_type = 'surge' AND e2.return_1h > 0)
                    OR (e1.event_type = 'crash' AND e2.return_1h < 0)
                    THEN 1 ELSE 0 END) * 1.0 / COUNT(*) as continuation_rate
               FROM events e1
               JOIN events e2 ON e1.ticker = e2.ticker
                   AND e2.timestamp > e1.timestamp
                   AND e2.timestamp <= datetime(e1.timestamp, '+4 hours')
               WHERE e1.ticker = ? AND e1.event_type = ?
                   AND e1.timestamp >= datetime('now', '-30 days')""",
            [ticker, event_type],
        ).fetchone()

        if row and row[1] and row[1] >= 2:
            return {
                "avg_next_return": row[0] or 0,
                "sample_count": row[1],
                "continuation_rate": row[2] or 0,
            }
    except Exception:
        pass
    return None


def _dispatch_narrative_alerts(conn, send_message):
    """Send alerts for emerging/building narratives with strength >= 0.3."""
    try:
        from src.analysis.narrative import (
            detect_narratives, format_narrative_telegram,
            get_narrative_signals, format_signals_telegram,
        )
    except ImportError:
        return

    try:
        narratives = detect_narratives(conn, hours=6)
    except Exception as exc:
        logger.debug("detect_narratives failed: %s", exc)
        return

    actionable = [
        n for n in narratives
        if n.get("lifecycle") in ("EMERGING", "BUILDING")
        and n.get("strength", 0) >= 0.3
    ]

    if not actionable:
        return

    try:
        msg = format_narrative_telegram(actionable)
        signals = get_narrative_signals(actionable)
        if signals:
            msg += "\n\n" + format_signals_telegram(signals)
        send_message(msg)
        logger.info("[alerts] Narrative alert: %d actionable narratives", len(actionable))
    except Exception as exc:
        logger.warning("[alerts] Narrative alert send failed: %s", exc)


def _get_topic_historical(conn, topic_label: str) -> dict:
    """Get historical price impact when this topic appeared before."""
    try:
        row = conn.execute(
            """SELECT
                AVG(e.return_1h) as avg_return,
                COUNT(*) as sample_count,
                SUM(CASE WHEN e.return_1h > 0 THEN 1 ELSE 0 END) * 1.0 / COUNT(*) as hit_rate
               FROM topics t
               JOIN events e ON e.timestamp > t.created_at
                   AND e.timestamp <= datetime(t.created_at, '+24 hours')
               WHERE t.topic_label = ?
                   AND t.created_at >= datetime('now', '-30 days')""",
            [topic_label],
        ).fetchone()

        if row and row[1] and row[1] >= 3:
            return {
                "avg_return": row[0] or 0,
                "sample_count": row[1],
                "hit_rate": row[2] or 0,
            }
    except Exception:
        pass
    return None
