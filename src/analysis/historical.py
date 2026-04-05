"""
historical.py - Historical pattern analysis for StoryQuant.

Computes post-hoc statistics over the SQLite database to answer:
  1. Which topics tend to move prices (and by how much)?
  2. Which news sources are reliably matched to real price events?
  3. After a price event fires, does the move continue or reverse?

All functions return empty DataFrames (with correct columns) when there is
insufficient data, so the dashboard can render cleanly before enough history
has accumulated.
"""

import logging
import sqlite3
from datetime import datetime, timezone, timedelta

import pandas as pd

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Column contracts for empty-DataFrame returns
# ---------------------------------------------------------------------------

_NEWS_IMPACT_COLS = [
    "topic_label", "ticker",
    "avg_return_1h", "avg_return_24h",
    "occurrence_count", "last_seen",
]

_SOURCE_RELIABILITY_COLS = [
    "source", "total_articles", "matched_events",
    "high_confidence_rate", "avg_score",
]

_EVENT_CONTINUATION_COLS = [
    "event_type", "severity",
    "avg_return_next_1h", "avg_return_next_24h",
    "continuation_rate",
]


# ---------------------------------------------------------------------------
# Forward return helper
# ---------------------------------------------------------------------------

def _compute_forward_return(
    conn: sqlite3.Connection,
    ticker: str,
    event_ts: pd.Timestamp,
    hours: int = 24,
) -> float:
    """Compute the price return from event_ts to event_ts + N hours.

    Looks up the closest price rows in the prices table around the event
    time and N hours later. Returns NaN if data is insufficient.
    """
    if pd.isna(event_ts):
        return float("nan")

    ts_str = event_ts.isoformat()
    target_ts = (event_ts + timedelta(hours=hours)).isoformat()

    # Get closest price at event time (within 1h window)
    sql_at = """
        SELECT close FROM prices
        WHERE ticker = ? AND timestamp BETWEEN datetime(?, '-1 hour') AND datetime(?, '+1 hour')
        ORDER BY ABS(julianday(timestamp) - julianday(?))
        LIMIT 1
    """
    # Get closest price N hours later (within 2h window)
    sql_after = """
        SELECT close FROM prices
        WHERE ticker = ? AND timestamp BETWEEN datetime(?, '-2 hours') AND datetime(?, '+2 hours')
        ORDER BY ABS(julianday(timestamp) - julianday(?))
        LIMIT 1
    """
    try:
        row_at = conn.execute(sql_at, [ticker, ts_str, ts_str, ts_str]).fetchone()
        row_after = conn.execute(sql_after, [ticker, target_ts, target_ts, target_ts]).fetchone()

        if row_at and row_after and row_at[0] and row_after[0] and row_at[0] != 0:
            return (row_after[0] - row_at[0]) / row_at[0]
    except Exception as exc:
        logger.debug("Forward return lookup failed for %s: %s", ticker, exc)

    return float("nan")


# ---------------------------------------------------------------------------
# 1. News-topic → price impact
# ---------------------------------------------------------------------------

def compute_news_impact(
    conn: sqlite3.Connection,
    lookback_days: int = 30,
) -> pd.DataFrame:
    """
    For each (topic_label, ticker) pair seen in the past N days, compute the
    average price return 1 h and 24 h *after* the topic first appeared in a
    matched article.

    A match is defined as: an attribution row that links an article to an event,
    where the article's published_at is within 2 h before the event timestamp.

    Returns
    -------
    pd.DataFrame
        Columns: topic_label, ticker, avg_return_1h, avg_return_24h,
                 occurrence_count, last_seen
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(days=lookback_days)).isoformat()

    sql = """
        SELECT
            a.topic_label,
            e.ticker,
            e.return_1h,
            e.timestamp        AS event_ts,
            a.published_at     AS article_ts
        FROM attributions atr
        JOIN articles a ON atr.article_id = a.id
        JOIN events   e ON atr.event_id   = e.id
        WHERE
            a.published_at >= :cutoff
            AND a.topic_label IS NOT NULL
            AND a.topic_label != ''
            -- article published within 2 h before the event
            AND CAST((julianday(e.timestamp) - julianday(a.published_at)) * 24 AS REAL)
                BETWEEN 0 AND 2
    """
    try:
        df = pd.read_sql_query(sql, conn, params={"cutoff": cutoff})
    except Exception as exc:
        logger.warning("compute_news_impact query failed: %s", exc)
        return pd.DataFrame(columns=_NEWS_IMPACT_COLS)

    if df.empty:
        return pd.DataFrame(columns=_NEWS_IMPACT_COLS)

    df["event_ts"] = pd.to_datetime(df["event_ts"], utc=True, errors="coerce")
    df["article_ts"] = pd.to_datetime(df["article_ts"], utc=True, errors="coerce")

    # Compute actual 24h forward return from prices table
    df["return_24h"] = df.apply(
        lambda row: _compute_forward_return(conn, row["ticker"], row["event_ts"], hours=24),
        axis=1,
    )

    agg = (
        df.groupby(["topic_label", "ticker"])
        .agg(
            avg_return_1h=("return_1h", "mean"),
            avg_return_24h=("return_24h", "mean"),
            occurrence_count=("return_1h", "count"),
            last_seen=("article_ts", "max"),
        )
        .reset_index()
    )
    agg["last_seen"] = agg["last_seen"].astype(str)

    return agg[_NEWS_IMPACT_COLS]


# ---------------------------------------------------------------------------
# 2. Source reliability
# ---------------------------------------------------------------------------

def compute_source_reliability(
    conn: sqlite3.Connection,
    lookback_days: int = 30,
) -> pd.DataFrame:
    """
    For each news source, compute how often their articles were matched to
    actual price events and with what average confidence.

    Returns
    -------
    pd.DataFrame
        Columns: source, total_articles, matched_events,
                 high_confidence_rate, avg_score
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(days=lookback_days)).isoformat()

    # Total articles per source in the window
    total_sql = """
        SELECT source, COUNT(*) AS total_articles
        FROM articles
        WHERE published_at >= :cutoff
          AND source IS NOT NULL
        GROUP BY source
    """

    # Matched articles (have at least one attribution row)
    matched_sql = """
        SELECT
            a.source,
            COUNT(DISTINCT atr.article_id)               AS matched_events,
            AVG(atr.total_score)                         AS avg_score,
            AVG(CASE WHEN atr.confidence = 'high' THEN 1.0 ELSE 0.0 END)
                                                         AS high_confidence_rate
        FROM attributions atr
        JOIN articles a ON atr.article_id = a.id
        WHERE a.published_at >= :cutoff
          AND a.source IS NOT NULL
        GROUP BY a.source
    """

    try:
        total_df = pd.read_sql_query(total_sql, conn, params={"cutoff": cutoff})
        matched_df = pd.read_sql_query(matched_sql, conn, params={"cutoff": cutoff})
    except Exception as exc:
        logger.warning("compute_source_reliability query failed: %s", exc)
        return pd.DataFrame(columns=_SOURCE_RELIABILITY_COLS)

    if total_df.empty:
        return pd.DataFrame(columns=_SOURCE_RELIABILITY_COLS)

    result = total_df.merge(matched_df, on="source", how="left")
    result["matched_events"] = result["matched_events"].fillna(0).astype(int)
    result["avg_score"] = result["avg_score"].round(4)
    result["high_confidence_rate"] = result["high_confidence_rate"].round(4)
    result = result.sort_values("matched_events", ascending=False).reset_index(drop=True)

    return result[_SOURCE_RELIABILITY_COLS]


# ---------------------------------------------------------------------------
# 3. Event continuation / reversal
# ---------------------------------------------------------------------------

def compute_event_continuation(
    conn: sqlite3.Connection,
    lookback_days: int = 30,
) -> pd.DataFrame:
    """
    After a price event fires, does the move continue or reverse in the next
    period?

    We look for a subsequent event on the same ticker within 1 h and 24 h and
    measure whether the direction is the same (continuation) or opposite
    (reversal).  When no follow-on event exists within the window the row is
    excluded from the rate calculation.

    Returns
    -------
    pd.DataFrame
        Columns: event_type, severity,
                 avg_return_next_1h, avg_return_next_24h,
                 continuation_rate
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(days=lookback_days)).isoformat()

    # Pull all events in the window; we self-join in Python for flexibility.
    events_sql = """
        SELECT id, ticker, timestamp, return_1h, event_type, severity
        FROM events
        WHERE timestamp >= :cutoff
        ORDER BY ticker, timestamp
    """
    try:
        ev = pd.read_sql_query(events_sql, conn, params={"cutoff": cutoff})
    except Exception as exc:
        logger.warning("compute_event_continuation query failed: %s", exc)
        return pd.DataFrame(columns=_EVENT_CONTINUATION_COLS)

    if len(ev) < 2:
        return pd.DataFrame(columns=_EVENT_CONTINUATION_COLS)

    ev["timestamp"] = pd.to_datetime(ev["timestamp"], utc=True, errors="coerce")
    ev = ev.dropna(subset=["timestamp"]).sort_values(["ticker", "timestamp"])

    records = []
    for ticker, group in ev.groupby("ticker"):
        group = group.reset_index(drop=True)
        for i, row in group.iterrows():
            t0 = row["timestamp"]
            orig_ret = row["return_1h"]
            if pd.isna(orig_ret):
                continue

            # Next event within 1 h
            future = group[
                (group["timestamp"] > t0) &
                (group["timestamp"] <= t0 + pd.Timedelta(hours=1))
            ]
            ret_next_1h = future["return_1h"].mean() if not future.empty else float("nan")

            # Actual 24h forward return from price data
            ret_next_24h = _compute_forward_return(conn, ticker, t0, hours=24)

            # Continuation: same sign as original move
            continued = (
                (not pd.isna(ret_next_1h)) and
                (orig_ret * ret_next_1h > 0)
            )

            records.append({
                "event_type": row["event_type"],
                "severity": row["severity"],
                "return_next_1h": ret_next_1h,
                "return_next_24h": ret_next_24h,
                "continued": continued,
                "has_followon": not pd.isna(ret_next_1h),
            })

    if not records:
        return pd.DataFrame(columns=_EVENT_CONTINUATION_COLS)

    df = pd.DataFrame(records)
    agg = (
        df.groupby(["event_type", "severity"])
        .apply(
            lambda g: pd.Series({
                "avg_return_next_1h": g["return_next_1h"].mean(),
                "avg_return_next_24h": g["return_next_24h"].mean(),
                "continuation_rate": (
                    g.loc[g["has_followon"], "continued"].mean()
                    if g["has_followon"].any() else float("nan")
                ),
            })
        )
        .reset_index()
    )

    for col in ["avg_return_next_1h", "avg_return_next_24h", "continuation_rate"]:
        agg[col] = agg[col].round(4)

    return agg[_EVENT_CONTINUATION_COLS]


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def save_patterns(conn: sqlite3.Connection, patterns_df: pd.DataFrame) -> None:
    """
    Upsert computed patterns into the historical_patterns table.

    Expects columns matching the table schema:
        pattern_type, ticker, topic_label,
        avg_return_1h, avg_return_24h, occurrence_count, last_seen, notes
    """
    if patterns_df is None or patterns_df.empty:
        return

    cols = [
        "pattern_type", "ticker", "topic_label",
        "avg_return_1h", "avg_return_24h",
        "occurrence_count", "last_seen", "notes",
    ]
    present = [c for c in cols if c in patterns_df.columns]
    placeholders = ",".join("?" * len(present))
    col_list = ",".join(present)
    sql = (
        f"INSERT OR REPLACE INTO historical_patterns ({col_list}) "
        f"VALUES ({placeholders})"
    )
    rows = [
        tuple(row)
        for row in patterns_df[present].itertuples(index=False, name=None)
    ]
    conn.executemany(sql, rows)
    conn.commit()
    logger.info("Saved %d pattern rows to historical_patterns", len(rows))


# ---------------------------------------------------------------------------
# Report facade
# ---------------------------------------------------------------------------

def generate_historical_report(conn: sqlite3.Connection) -> dict:
    """
    Run all analyses and return a dict of DataFrames suitable for the dashboard.

    Keys
    ----
    news_impact         pd.DataFrame  (topic x ticker price impact)
    source_reliability  pd.DataFrame  (per-source match quality)
    event_continuation  pd.DataFrame  (post-event momentum/reversal)
    """
    logger.info("Generating historical report…")

    report = {
        "news_impact": compute_news_impact(conn),
        "source_reliability": compute_source_reliability(conn),
        "event_continuation": compute_event_continuation(conn),
    }

    for key, df in report.items():
        logger.info("  %s: %d rows", key, len(df))

    return report


# ---------------------------------------------------------------------------
# Prompt-context helpers (new functions for historical performance backing)
# ---------------------------------------------------------------------------

def compute_topic_performance(conn, lookback_days=30) -> pd.DataFrame:
    """
    For each topic keyword that appeared historically, what was the average
    price return of related assets AFTER the topic appeared?

    Logic:
    1. Get all topics with their window_start timestamps
    2. For each topic, find price events within 1-24h AFTER the topic appeared
    3. Compute avg_return_1h, avg_return_24h, hit_rate (% positive returns)

    Returns: topic_label, avg_return_1h, avg_return_24h, hit_rate, sample_count
    """
    # Use SQL to join topics with events based on time proximity
    sql = """
        SELECT
            t.topic_label,
            e.ticker,
            e.return_1h,
            e.timestamp as event_ts,
            t.created_at as topic_ts
        FROM topics t
        JOIN events e ON e.timestamp > t.created_at
            AND e.timestamp <= datetime(t.created_at, '+24 hours')
            AND e.event_type IS NOT NULL
        WHERE t.created_at >= datetime('now', ?)
    """
    try:
        raw = pd.read_sql_query(sql, conn, params=[f'-{lookback_days} days'])
        if raw.empty:
            return pd.DataFrame(columns=["topic_label", "avg_return_1h", "avg_return_24h", "hit_rate", "sample_count"])

        # Compute 24h forward return for each event
        raw["event_ts"] = pd.to_datetime(raw["event_ts"], utc=True, errors="coerce")
        raw["return_24h"] = raw.apply(
            lambda r: _compute_forward_return(conn, r["ticker"], r["event_ts"], hours=24),
            axis=1,
        )

        df = (
            raw.groupby("topic_label")
            .agg(
                avg_return_1h=("return_1h", "mean"),
                avg_return_24h=("return_24h", "mean"),
                sample_count=("return_1h", "count"),
                hit_rate=("return_1h", lambda x: (x > 0).mean()),
            )
            .reset_index()
            .query("sample_count >= 2")
            .sort_values("sample_count", ascending=False)
        )
        return df
    except Exception:
        return pd.DataFrame(columns=["topic_label", "avg_return_1h", "hit_rate", "sample_count"])


def compute_event_type_stats(conn, lookback_days=30) -> pd.DataFrame:
    """
    Historical stats per event type per ticker:
    After a surge/crash/volume_spike, what typically happens next?

    For each (ticker, event_type), compute:
    - avg subsequent 1h return
    - continuation rate (% of times price continues in same direction)
    - reversal rate
    - sample count

    Returns: ticker, event_type, avg_next_return, continuation_rate, reversal_rate, sample_count
    """
    sql = """
        SELECT
            e1.ticker,
            e1.event_type,
            e1.severity,
            AVG(e2.return_1h) as avg_next_return,
            COUNT(*) as sample_count
        FROM events e1
        JOIN events e2 ON e1.ticker = e2.ticker
            AND e2.timestamp > e1.timestamp
            AND e2.timestamp <= datetime(e1.timestamp, '+2 hours')
            AND e2.event_type IS NOT NULL
        WHERE e1.event_type IS NOT NULL
            AND e1.timestamp >= datetime('now', ?)
        GROUP BY e1.ticker, e1.event_type, e1.severity
        HAVING sample_count >= 2
        ORDER BY sample_count DESC
    """
    try:
        df = pd.read_sql_query(sql, conn, params=[f'-{lookback_days} days'])
        # Calculate continuation rate
        if not df.empty and 'avg_next_return' in df.columns:
            df['continuation_pct'] = df.apply(
                lambda r: f"{abs(r['avg_next_return'])*100:.1f}% {'지속' if (r['event_type']=='surge' and r['avg_next_return']>0) or (r['event_type']=='crash' and r['avg_next_return']<0) else '반전'}",
                axis=1
            )
        return df
    except Exception:
        return pd.DataFrame(columns=["ticker", "event_type", "severity", "avg_next_return", "sample_count"])


def compute_source_hit_rate(conn, lookback_days=30) -> pd.DataFrame:
    """
    For each news source, when their articles were matched to price events,
    how often was the direction prediction correct?

    Returns: source, total_attributions, high_confidence_count, avg_score,
             avg_event_return, positive_rate
    """
    sql = """
        SELECT
            ar.source,
            COUNT(*) as total_attributions,
            SUM(CASE WHEN a.confidence = 'high' THEN 1 ELSE 0 END) as high_confidence_count,
            AVG(a.total_score) as avg_score,
            AVG(e.return_1h) as avg_event_return
        FROM attributions a
        JOIN articles ar ON a.article_id = ar.id
        JOIN events e ON a.event_id = e.id
        WHERE e.event_type IS NOT NULL
        GROUP BY ar.source
        HAVING total_attributions >= 3
        ORDER BY avg_score DESC
    """
    try:
        return pd.read_sql_query(sql, conn)
    except Exception:
        return pd.DataFrame(columns=["source", "total_attributions", "high_confidence_count", "avg_score", "avg_event_return"])


def compute_similar_events_lookup(conn, ticker: str, event_type: str, lookback_days=90) -> pd.DataFrame:
    """
    Find past events similar to a current one and show what happened afterward.

    Returns: ticker, event_timestamp, return_1h, severity,
             next_1h_return, next_4h_return, related_news
    """
    sql = """
        SELECT
            e.ticker, e.timestamp, e.return_1h, e.severity,
            ar.title as related_news
        FROM events e
        LEFT JOIN attributions a ON a.event_id = e.id AND a.rank = 1
        LEFT JOIN articles ar ON a.article_id = ar.id
        WHERE e.ticker = ? AND e.event_type = ?
            AND e.timestamp >= datetime('now', ?)
        ORDER BY e.timestamp DESC
        LIMIT 20
    """
    try:
        return pd.read_sql_query(sql, conn, params=[ticker, event_type, f'-{lookback_days} days'])
    except Exception:
        return pd.DataFrame()


def generate_historical_context(conn) -> str:
    """
    Generate a formatted string of historical performance data
    to include in market analysis prompts.
    """
    lines = []

    # Topic performance
    topic_perf = compute_topic_performance(conn)
    if not topic_perf.empty:
        lines.append("=== 토픽별 과거 성과 ===")
        for _, r in topic_perf.head(10).iterrows():
            hit = r.get('hit_rate', 0) * 100
            avg_ret_1h = r.get('avg_return_1h', 0) * 100
            avg_ret_24h = r.get('avg_return_24h', float('nan'))
            ret_24h_str = f", 24h {avg_ret_24h*100:+.2f}%" if pd.notna(avg_ret_24h) else ""
            lines.append(f"  '{r['topic_label']}' 등장 후: 1h 평균 {avg_ret_1h:+.2f}%{ret_24h_str}, 적중률 {hit:.0f}%, 샘플 {r.get('sample_count',0)}건")

    # Event type stats
    event_stats = compute_event_type_stats(conn)
    if not event_stats.empty:
        lines.append("\n=== 이벤트 유형별 후속 움직임 ===")
        for _, r in event_stats.head(15).iterrows():
            next_ret = r.get('avg_next_return', 0) * 100
            lines.append(f"  {r['ticker']} {r['event_type']}({r.get('severity','')}) 이후: 평균 {next_ret:+.2f}%, {r.get('continuation_pct','')} (n={r.get('sample_count',0)})")

    # Source reliability
    source_stats = compute_source_hit_rate(conn)
    if not source_stats.empty:
        lines.append("\n=== 뉴스 소스별 신뢰도 ===")
        for _, r in source_stats.head(8).iterrows():
            lines.append(f"  {r['source']}: 매칭 {r['total_attributions']}건, 고신뢰 {r.get('high_confidence_count',0)}건, 평균 점수 {r.get('avg_score',0):.2f}")

    if not lines:
        lines.append("(아직 충분한 히스토리컬 데이터가 없습니다. 데이터가 누적되면 과거 성과가 표시됩니다.)")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    from pathlib import Path

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    # Allow overriding the DB path via argv
    db_path = sys.argv[1] if len(sys.argv) > 1 else "data/storyquant.db"

    if not Path(db_path).exists():
        print(f"Database not found: {db_path}")
        print("Run the pipeline first to populate data.")
        sys.exit(1)

    import sqlite3 as _sqlite3
    conn = _sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")

    report = generate_historical_report(conn)

    for section, df in report.items():
        print(f"\n{'='*60}")
        print(f"  {section.upper().replace('_', ' ')}")
        print(f"{'='*60}")
        if df.empty:
            print("  (no data yet)")
        else:
            print(df.to_string(index=False))

    conn.close()
