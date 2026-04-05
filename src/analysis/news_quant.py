"""
news_quant.py - News data quantification for StoryQuant.

Transforms qualitative news data into trading-grade quantitative signals:

1. News Velocity    — 특정 티커/토픽의 기사 발행 속도 (건/시간)
2. Sentiment Score  — 집계 감성 점수 (-1 ~ +1)
3. Source Consensus — 복수 소스 보도 일치율 (0 ~ 1)
4. Novelty Score    — 새로운 내러티브 vs 반복 뉴스 (0 ~ 1)
5. News Impact      — 과거 유사 뉴스 후 평균 가격 변동
6. Composite Signal — 위 5개 결합 최종 시그널 (-1 ~ +1)
"""

import logging
import sqlite3
import re
from datetime import datetime, timezone, timedelta
from collections import Counter

import numpy as np
import pandas as pd

from src.config.tickers import get_ticker_keywords

logger = logging.getLogger(__name__)

# Ticker keywords for matching articles to tickers
TICKER_KEYWORDS = get_ticker_keywords()

# Sentiment keywords
BULLISH_KW = [
    "surge", "soar", "rally", "bullish", "breakout", "record high", "all-time high",
    "inflow", "accumulate", "upgrade", "beat", "exceed", "approval", "launch",
    "급등", "상승", "돌파", "강세", "매수", "호재", "승인", "사상최고",
]
BEARISH_KW = [
    "crash", "plunge", "dump", "bearish", "breakdown", "sell-off", "liquidat",
    "outflow", "hack", "ban", "restrict", "downgrade", "miss", "delay", "fraud",
    "급락", "하락", "폭락", "약세", "매도", "악재", "규제", "해킹",
]


# ---------------------------------------------------------------------------
# 1. News Velocity
# ---------------------------------------------------------------------------

def compute_velocity(conn: sqlite3.Connection, hours: int = 6) -> pd.DataFrame:
    """Compute article publication rate per ticker per hour.

    Returns DataFrame: ticker, articles_total, articles_per_hour,
                       velocity_zscore (vs 7-day average)
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    cutoff_7d = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()

    articles = pd.read_sql_query(
        "SELECT title, summary, published_at, source FROM articles WHERE published_at >= ?",
        conn, params=[cutoff],
    )
    articles_7d = pd.read_sql_query(
        "SELECT title, summary, published_at FROM articles WHERE published_at >= ?",
        conn, params=[cutoff_7d],
    )

    results = []
    for ticker, keywords in TICKER_KEYWORDS.items():
        # Count recent mentions
        pattern = "|".join(re.escape(kw) for kw in keywords)
        if not articles.empty:
            mask = articles["title"].str.contains(pattern, case=False, na=False) | \
                   articles["summary"].fillna("").str.contains(pattern, case=False, na=False)
            count_now = mask.sum()
        else:
            count_now = 0

        rate_now = count_now / max(hours, 1)

        # 7-day baseline
        if not articles_7d.empty:
            mask_7d = articles_7d["title"].str.contains(pattern, case=False, na=False) | \
                      articles_7d["summary"].fillna("").str.contains(pattern, case=False, na=False)
            count_7d = mask_7d.sum()
        else:
            count_7d = 0

        rate_7d = count_7d / (7 * 24)  # per hour baseline
        velocity_z = (rate_now - rate_7d) / max(rate_7d, 0.01)

        results.append({
            "ticker": ticker,
            "articles_total": int(count_now),
            "articles_per_hour": round(rate_now, 2),
            "baseline_per_hour": round(rate_7d, 2),
            "velocity_zscore": round(velocity_z, 2),
        })

    return pd.DataFrame(results).sort_values("velocity_zscore", ascending=False).reset_index(drop=True)


# ---------------------------------------------------------------------------
# 2. Sentiment Aggregation
# ---------------------------------------------------------------------------

def compute_sentiment(conn: sqlite3.Connection, hours: int = 6) -> pd.DataFrame:
    """Compute aggregate sentiment score per ticker.

    Returns DataFrame: ticker, sentiment_score (-1~+1), bullish_count,
                       bearish_count, neutral_count, total_articles
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()

    articles = pd.read_sql_query(
        "SELECT title, summary FROM articles WHERE published_at >= ?",
        conn, params=[cutoff],
    )

    results = []
    for ticker, keywords in TICKER_KEYWORDS.items():
        pattern = "|".join(re.escape(kw) for kw in keywords)
        if articles.empty:
            results.append({"ticker": ticker, "sentiment_score": 0, "bullish_count": 0,
                           "bearish_count": 0, "neutral_count": 0, "total_articles": 0})
            continue

        mask = articles["title"].str.contains(pattern, case=False, na=False) | \
               articles["summary"].fillna("").str.contains(pattern, case=False, na=False)
        matched = articles[mask]

        if matched.empty:
            results.append({"ticker": ticker, "sentiment_score": 0, "bullish_count": 0,
                           "bearish_count": 0, "neutral_count": 0, "total_articles": 0})
            continue

        bullish = bearish = neutral = 0
        for _, row in matched.iterrows():
            text = f"{row['title']} {row.get('summary', '')}".lower()
            b_score = sum(1 for kw in BULLISH_KW if kw.lower() in text)
            s_score = sum(1 for kw in BEARISH_KW if kw.lower() in text)
            if b_score > s_score:
                bullish += 1
            elif s_score > b_score:
                bearish += 1
            else:
                neutral += 1

        total = bullish + bearish + neutral
        score = (bullish - bearish) / total if total > 0 else 0

        results.append({
            "ticker": ticker,
            "sentiment_score": round(score, 3),
            "bullish_count": bullish,
            "bearish_count": bearish,
            "neutral_count": neutral,
            "total_articles": total,
        })

    return pd.DataFrame(results).sort_values("sentiment_score", ascending=False).reset_index(drop=True)


# ---------------------------------------------------------------------------
# 3. Source Consensus
# ---------------------------------------------------------------------------

def compute_consensus(conn: sqlite3.Connection, hours: int = 6) -> pd.DataFrame:
    """How many independent sources are reporting the same ticker/topic?

    Returns DataFrame: ticker, unique_sources, consensus_ratio (0~1),
                       sources_list
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()

    articles = pd.read_sql_query(
        "SELECT title, summary, source FROM articles WHERE published_at >= ?",
        conn, params=[cutoff],
    )

    all_sources = articles["source"].nunique() if not articles.empty else 1

    results = []
    for ticker, keywords in TICKER_KEYWORDS.items():
        pattern = "|".join(re.escape(kw) for kw in keywords)
        if articles.empty:
            results.append({"ticker": ticker, "unique_sources": 0,
                           "consensus_ratio": 0, "sources_list": ""})
            continue

        mask = articles["title"].str.contains(pattern, case=False, na=False) | \
               articles["summary"].fillna("").str.contains(pattern, case=False, na=False)
        matched = articles[mask]
        sources = matched["source"].unique().tolist() if not matched.empty else []

        results.append({
            "ticker": ticker,
            "unique_sources": len(sources),
            "consensus_ratio": round(len(sources) / max(all_sources, 1), 2),
            "sources_list": ", ".join(sources[:5]),
        })

    return pd.DataFrame(results).sort_values("unique_sources", ascending=False).reset_index(drop=True)


# ---------------------------------------------------------------------------
# 4. Novelty Score
# ---------------------------------------------------------------------------

def compute_novelty(conn: sqlite3.Connection, hours: int = 6) -> pd.DataFrame:
    """Is this a new narrative or old news being repeated?

    Compares recent article titles against 7-day history using word overlap.
    High novelty = new story. Low novelty = recycled headlines.

    Returns DataFrame: ticker, novelty_score (0~1), new_keywords
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    cutoff_7d = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()

    recent = pd.read_sql_query(
        "SELECT title, summary FROM articles WHERE published_at >= ?",
        conn, params=[cutoff],
    )
    history = pd.read_sql_query(
        "SELECT title FROM articles WHERE published_at >= ? AND published_at < ?",
        conn, params=[cutoff_7d, cutoff],
    )

    # Build historical word set
    hist_words = set()
    if not history.empty:
        for title in history["title"].dropna():
            hist_words.update(re.findall(r'\b[a-zA-Z가-힣]{2,}\b', title.lower()))

    results = []
    for ticker, keywords in TICKER_KEYWORDS.items():
        pattern = "|".join(re.escape(kw) for kw in keywords)
        if recent.empty:
            results.append({"ticker": ticker, "novelty_score": 0, "new_keywords": ""})
            continue

        mask = recent["title"].str.contains(pattern, case=False, na=False)
        matched = recent[mask]

        if matched.empty:
            results.append({"ticker": ticker, "novelty_score": 0, "new_keywords": ""})
            continue

        # Extract words from recent articles
        recent_words = Counter()
        for title in matched["title"].dropna():
            words = re.findall(r'\b[a-zA-Z가-힣]{2,}\b', title.lower())
            recent_words.update(words)

        # Novelty = % of recent words not in history
        if recent_words:
            new_words = [w for w in recent_words if w not in hist_words and w not in [k.lower() for k in keywords]]
            novelty = len(new_words) / max(len(recent_words), 1)
            top_new = [w for w, _ in Counter({w: recent_words[w] for w in new_words}).most_common(5)]
        else:
            novelty = 0
            top_new = []

        results.append({
            "ticker": ticker,
            "novelty_score": round(min(novelty, 1.0), 2),
            "new_keywords": ", ".join(top_new),
        })

    return pd.DataFrame(results).sort_values("novelty_score", ascending=False).reset_index(drop=True)


# ---------------------------------------------------------------------------
# 5. Historical News Impact
# ---------------------------------------------------------------------------

def compute_news_impact(conn: sqlite3.Connection, lookback_days: int = 30) -> pd.DataFrame:
    """When news about this ticker spiked before, what happened to the price?

    Returns DataFrame: ticker, avg_return_after_spike, hit_rate, sample_count
    """
    results = []

    for ticker in TICKER_KEYWORDS.keys():
        try:
            row = conn.execute("""
                SELECT
                    AVG(e.return_1h) as avg_return,
                    COUNT(*) as sample_count,
                    SUM(CASE WHEN e.return_1h > 0 THEN 1 ELSE 0 END) * 1.0 / COUNT(*) as hit_rate
                FROM attributions a
                JOIN events e ON a.event_id = e.id
                WHERE e.ticker = ? AND a.confidence = 'high'
                    AND e.timestamp >= datetime('now', ?)
            """, [ticker, f'-{lookback_days} days']).fetchone()

            results.append({
                "ticker": ticker,
                "avg_return_after_news": round(float(row[0] or 0), 4),
                "hit_rate": round(float(row[2] or 0), 2),
                "sample_count": int(row[1] or 0),
            })
        except Exception:
            results.append({"ticker": ticker, "avg_return_after_news": 0, "hit_rate": 0, "sample_count": 0})

    return pd.DataFrame(results).sort_values("sample_count", ascending=False).reset_index(drop=True)


# ---------------------------------------------------------------------------
# 6. Composite Signal
# ---------------------------------------------------------------------------

def compute_composite_signal(conn: sqlite3.Connection, hours: int = 6) -> pd.DataFrame:
    """Combine all 5 quantitative news metrics into a single composite signal.

    Signal range: -1 (strong bearish) to +1 (strong bullish)

    Weights:
      - Sentiment:  35%  (방향성의 핵심)
      - Velocity:   25%  (뉴스 급증 = 큰 움직임 예고)
      - Consensus:  15%  (복수 소스 = 신뢰도)
      - Novelty:    15%  (새 내러티브 = 더 큰 임팩트)
      - Impact:     10%  (과거 성과)
    """
    velocity = compute_velocity(conn, hours)
    sentiment = compute_sentiment(conn, hours)
    consensus = compute_consensus(conn, hours)
    novelty = compute_novelty(conn, hours)
    impact = compute_news_impact(conn)

    # Merge all on ticker
    df = velocity[["ticker", "velocity_zscore", "articles_total"]].copy()
    df = df.merge(sentiment[["ticker", "sentiment_score"]], on="ticker", how="left")
    df = df.merge(consensus[["ticker", "consensus_ratio", "unique_sources"]], on="ticker", how="left")
    df = df.merge(novelty[["ticker", "novelty_score"]], on="ticker", how="left")
    df = df.merge(impact[["ticker", "avg_return_after_news", "hit_rate", "sample_count"]], on="ticker", how="left")
    df = df.fillna(0)

    # Normalize velocity zscore to -1~1
    v_max = max(df["velocity_zscore"].abs().max(), 1)
    df["velocity_norm"] = (df["velocity_zscore"] / v_max).clip(-1, 1)

    # Impact direction: positive = bullish bias
    df["impact_norm"] = df["avg_return_after_news"].clip(-0.05, 0.05) / 0.05

    # Composite signal
    df["composite_signal"] = (
        0.35 * df["sentiment_score"] +
        0.25 * df["velocity_norm"] * df["sentiment_score"].apply(lambda s: 1 if s >= 0 else -1) +
        0.15 * df["consensus_ratio"] * df["sentiment_score"].apply(lambda s: 1 if s >= 0 else -1) +
        0.15 * df["novelty_score"] * df["sentiment_score"].apply(lambda s: 1 if s >= 0 else -1) +
        0.10 * df["impact_norm"]
    ).round(3)

    # Signal strength: absolute value
    df["signal_strength"] = df["composite_signal"].abs()

    # Signal label
    df["signal_label"] = df["composite_signal"].apply(
        lambda s: "STRONG BUY" if s >= 0.5 else
                  "BUY" if s >= 0.2 else
                  "WEAK BUY" if s > 0.05 else
                  "NEUTRAL" if abs(s) <= 0.05 else
                  "WEAK SELL" if s > -0.2 else
                  "SELL" if s > -0.5 else
                  "STRONG SELL"
    )

    # Sort by signal strength
    df = df.sort_values("signal_strength", ascending=False).reset_index(drop=True)

    return df


# ---------------------------------------------------------------------------
# Report formatting
# ---------------------------------------------------------------------------

def format_quant_report(df: pd.DataFrame) -> str:
    """Format composite signal as human-readable text."""
    lines = [
        "═══════════════════════════════════════════════",
        "  StoryQuant News Quantification Report",
        "═══════════════════════════════════════════════",
        "",
        f"  {'Ticker':<12} {'Signal':>8} {'Label':<12} {'News':>5} {'Sent':>6} {'Vel':>6} {'Cons':>5} {'Nov':>5}",
        f"  {'─'*60}",
    ]

    for _, r in df.iterrows():
        sig = r["composite_signal"]
        color_marker = "▲" if sig > 0.05 else "▼" if sig < -0.05 else "─"
        lines.append(
            f"  {r['ticker']:<12} {sig:>+.3f} {color_marker} {r['signal_label']:<12} "
            f"{int(r['articles_total']):>5} {r['sentiment_score']:>+.2f} "
            f"{r['velocity_zscore']:>+.1f} {r['consensus_ratio']:>.2f} {r['novelty_score']:>.2f}"
        )

    lines.extend(["", "  Legend: Sent=Sentiment, Vel=Velocity Z, Cons=Consensus, Nov=Novelty"])
    lines.append("═══════════════════════════════════════════════")
    return "\n".join(lines)


def format_quant_telegram(df: pd.DataFrame) -> str:
    """Format top signals for Telegram push."""
    actionable = df[df["signal_strength"] >= 0.1]
    if actionable.empty:
        return "📊 <b>StoryQuant News Signal</b>\n\nNo actionable signals right now."

    lines = ["📊 <b>StoryQuant News Signal</b>", ""]

    for _, r in actionable.head(5).iterrows():
        sig = r["composite_signal"]
        icon = "🟢" if sig >= 0.2 else "🔴" if sig <= -0.2 else "🟡"
        lines.append(
            f"{icon} <b>{r['ticker']}</b> {sig:+.2f} ({r['signal_label']})"
        )
        details = []
        if r["articles_total"] > 0:
            details.append(f"뉴스 {int(r['articles_total'])}건")
        if r["sentiment_score"] != 0:
            details.append(f"감성 {r['sentiment_score']:+.2f}")
        if r["velocity_zscore"] > 1:
            details.append(f"속도 {r['velocity_zscore']:+.1f}σ")
        if r["unique_sources"] >= 3:
            details.append(f"소스 {int(r['unique_sources'])}개")
        if details:
            lines.append(f"   {' | '.join(details)}")
        lines.append("")

    lines.append("🤖 StoryQuant Quant Signal")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    from src.db.schema import thread_connection

    with thread_connection() as conn:
        print("Computing news quantification...\n")

        df = compute_composite_signal(conn, hours=24)
        print(format_quant_report(df))

        print("\n--- Telegram Format ---")
        print(format_quant_telegram(df))

        print("\n--- Detail: Velocity ---")
        vel = compute_velocity(conn, hours=24)
        print(vel.to_string(index=False))

        print("\n--- Detail: Sentiment ---")
        sent = compute_sentiment(conn, hours=24)
        print(sent.to_string(index=False))
