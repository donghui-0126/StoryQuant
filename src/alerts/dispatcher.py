"""
Alert dispatcher - checks for new events and sends alerts via configured channels.
"""
import logging
import sqlite3
from datetime import datetime, timezone, timedelta
import pandas as pd

logger = logging.getLogger(__name__)

# Track last alerted event to avoid duplicates
_last_alert_time = None

def dispatch_alerts(conn: sqlite3.Connection):
    """Check for new events and dispatch alerts."""
    global _last_alert_time

    try:
        from src.alerts.telegram_bot import telegram_available, send_message, format_event_alert
    except ImportError:
        return

    if not telegram_available():
        return

    # Get events from last 5 minutes that we haven't alerted yet
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat(timespec="seconds")
    if _last_alert_time:
        cutoff = max(cutoff, _last_alert_time)

    events = pd.read_sql_query(
        "SELECT * FROM events WHERE event_type IS NOT NULL AND severity IN ('high','medium') AND timestamp >= ? ORDER BY timestamp DESC",
        conn, params=[cutoff]
    )

    for _, event in events.iterrows():
        # Get attribution if available
        attr = None
        if "id" in event:
            attr_row = pd.read_sql_query(
                """SELECT a.*, ar.title as news_title
                   FROM attributions a JOIN articles ar ON a.article_id = ar.id
                   WHERE a.event_id = ? AND a.rank = 1""",
                conn, params=[int(event["id"])]
            )
            if not attr_row.empty:
                attr = attr_row.iloc[0].to_dict()

        msg = format_event_alert(event.to_dict(), attr)
        send_message(msg)
        logger.info("[alerts] Sent alert for %s %s", event.get("ticker"), event.get("event_type"))

    _last_alert_time = datetime.now(timezone.utc).isoformat(timespec="seconds")
