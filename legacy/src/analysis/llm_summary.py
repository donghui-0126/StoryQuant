"""
LLM-based event cause summary module for StoryQuant.
Uses Claude Haiku to generate concise cause summaries for price events.
Falls back to rule-based summary when ANTHROPIC_API_KEY is not set.
"""

import os
import logging
import sqlite3
from datetime import datetime, timezone, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

HAIKU_MODEL = "claude-haiku-4-5-20251001"


# ---------------------------------------------------------------------------
# Rule-based fallback helpers
# ---------------------------------------------------------------------------

def _rule_based_cause(event: dict, articles: list[dict]) -> str:
    """
    Construct a cause summary from attribution data and sentiment without LLM.
    """
    ticker = event.get("ticker", "???")
    ret = event.get("return_1h", 0.0)
    try:
        ret_pct = f"{float(ret):+.1%}"
    except (TypeError, ValueError):
        ret_pct = "N/A"

    if not articles:
        event_type = event.get("event_type", "move")
        return f"{ticker} {ret_pct} | 원인 데이터 없음 ({event_type})"

    # Sort by confidence if present
    sorted_articles = sorted(
        articles,
        key=lambda a: float(a.get("confidence", 0)),
        reverse=True,
    )

    primary = sorted_articles[0]
    primary_title = primary.get("news_title") or primary.get("title", "")
    primary_sentiment = primary.get("sentiment", "")

    parts = [f"{ticker} {ret_pct}"]

    if primary_title:
        parts.append(f"주요 원인: {primary_title[:60]}")

    if len(sorted_articles) > 1:
        secondary = sorted_articles[1]
        sec_title = secondary.get("news_title") or secondary.get("title", "")
        if sec_title:
            parts.append(f"보조 원인: {sec_title[:50]}")

    if primary_sentiment == "bullish":
        parts.append("(강세 센티먼트)")
    elif primary_sentiment == "bearish":
        parts.append("(약세 센티먼트)")

    return " | ".join(parts)


# ---------------------------------------------------------------------------
# LLM summary
# ---------------------------------------------------------------------------

def summarize_event_cause(
    event: dict,
    articles: list[dict],
    conn: Optional[sqlite3.Connection] = None,
) -> str:
    """
    Given a price event and related news articles, generate a concise
    cause summary using Claude Haiku.

    Returns a formatted summary like:
    "BTC +4.2% | 주요 원인: ETF inflow acceleration 관련 뉴스 | 보조 원인: short squeeze 가능성"

    Falls back to rule-based summary if ANTHROPIC_API_KEY is not set.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        logger.debug("ANTHROPIC_API_KEY not set; using rule-based fallback.")
        return _rule_based_cause(event, articles)

    ticker = event.get("ticker", "???")
    ret = event.get("return_1h", 0.0)
    try:
        ret_pct = f"{float(ret):+.1%}"
    except (TypeError, ValueError):
        ret_pct = "N/A"
    event_type = event.get("event_type", "")
    severity = event.get("severity", "")

    news_lines = []
    for i, a in enumerate(articles[:5], 1):
        title = a.get("news_title") or a.get("title", "")
        conf = a.get("confidence", "")
        news_lines.append(f"  {i}. {title} (confidence={conf})")
    news_block = "\n".join(news_lines) if news_lines else "  (관련 뉴스 없음)"

    prompt = f"""다음 가격 이벤트와 관련 뉴스를 보고 원인을 한 줄로 요약해줘.

이벤트: {ticker} {ret_pct} | {event_type} | severity={severity}

관련 뉴스:
{news_block}

요약 형식 (정확히 이 형식으로):
"{ticker} {ret_pct} | 주요 원인: <원인 요약> | 보조 원인: <보조 원인 또는 없음>"

한 줄, 간결하게."""

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model=HAIKU_MODEL,
            max_tokens=150,
            messages=[{"role": "user", "content": prompt}],
        )
        result = response.content[0].text.strip().strip('"')
        if result:
            return result
    except Exception as exc:
        logger.warning("LLM summarize_event_cause failed: %s", exc)

    return _rule_based_cause(event, articles)


# ---------------------------------------------------------------------------
# Market brief
# ---------------------------------------------------------------------------

def generate_market_brief(conn: sqlite3.Connection, hours: int = 6) -> str:
    """
    Generate a comprehensive market brief combining events, topics, and attributions.

    Parameters
    ----------
    conn : sqlite3.Connection
    hours : int
        Look-back window in hours.

    Returns
    -------
    str
        Formatted market brief text.
    """
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    since_str = since.strftime("%Y-%m-%d %H:%M:%S")

    # --- Collect data ---
    events = _fetch_events(conn, since_str)
    attributions = _fetch_attributions(conn, since_str)
    topics = _fetch_topics(conn)

    # --- Build cause summaries for each event ---
    event_summaries = []
    attr_by_ticker: dict[str, list] = {}
    for a in attributions:
        ticker = a.get("ticker", "")
        attr_by_ticker.setdefault(ticker, []).append(a)

    for ev in events:
        ticker = ev.get("ticker", "")
        related = attr_by_ticker.get(ticker, [])
        summary = summarize_event_cause(ev, related, conn)
        event_summaries.append(summary)

    # --- Format brief ---
    lines = [
        f"[StoryQuant 시장 브리프 | 최근 {hours}시간 | {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}]",
        "",
    ]

    if event_summaries:
        lines.append("=== 주요 가격 이벤트 ===")
        for s in event_summaries:
            lines.append(f"  • {s}")
        lines.append("")

    if topics:
        lines.append("=== 핫 토픽 ===")
        for t in topics[:5]:
            label = t.get("topic_label", "")
            freq = t.get("frequency", 0)
            momentum = t.get("momentum_score", 0)
            lines.append(f"  • {label} (기사 {freq}건, momentum={momentum:.2f})")
        lines.append("")

    if not event_summaries and not topics:
        lines.append("  (최근 주요 이벤트 없음)")

    return "\n".join(lines)


def _fetch_events(conn: sqlite3.Connection, since: str) -> list[dict]:
    try:
        import pandas as pd
        df = pd.read_sql_query(
            "SELECT ticker, return_1h, event_type, severity, timestamp FROM events WHERE timestamp >= ? ORDER BY ABS(return_1h) DESC LIMIT 10",
            conn,
            params=(since,),
        )
        return df.to_dict(orient="records")
    except Exception as exc:
        logger.warning("_fetch_events failed: %s", exc)
        return []


def _fetch_attributions(conn: sqlite3.Connection, since: str) -> list[dict]:
    try:
        import pandas as pd
        df = pd.read_sql_query(
            """SELECT e.ticker, ar.title as news_title, a.confidence, e.return_1h
               FROM attributions a
               JOIN events e ON a.event_id = e.id
               JOIN articles ar ON a.article_id = ar.id
               WHERE e.timestamp >= ?
               ORDER BY a.total_score DESC
               LIMIT 30""",
            conn,
            params=(since,),
        )
        return df.to_dict(orient="records")
    except Exception as exc:
        logger.warning("_fetch_attributions failed: %s", exc)
        return []


def _fetch_topics(conn: sqlite3.Connection) -> list[dict]:
    try:
        import pandas as pd
        df = pd.read_sql_query(
            "SELECT topic_label, frequency, momentum_score FROM topics ORDER BY momentum_score DESC LIMIT 10",
            conn,
        )
        return df.to_dict(orient="records")
    except Exception as exc:
        logger.warning("_fetch_topics failed: %s", exc)
        return []


# ---------------------------------------------------------------------------
# Telegram formatting
# ---------------------------------------------------------------------------

def format_brief_for_telegram(brief: str) -> str:
    """
    Format a market brief string for Telegram push notification.
    Escapes Markdown special characters and keeps within Telegram message limits.
    """
    # Telegram MarkdownV2 special chars that need escaping
    _ESCAPE_CHARS = r'_*[]()~`>#+-=|{}.!'

    def escape_md(text: str) -> str:
        for ch in _ESCAPE_CHARS:
            text = text.replace(ch, f"\\{ch}")
        return text

    lines = brief.split("\n")
    formatted = []
    for line in lines:
        if line.startswith("===") and line.endswith("==="):
            # Section headers -> bold
            header = line.strip("= ").strip()
            formatted.append(f"*{escape_md(header)}*")
        elif line.startswith("  •"):
            # Bullet items
            content = line[3:].strip()
            formatted.append(f"• {escape_md(content)}")
        elif line.startswith("[StoryQuant"):
            formatted.append(f"*{escape_md(line)}*")
        else:
            formatted.append(escape_md(line))

    full_text = "\n".join(formatted)
    # Telegram max message length is 4096 chars
    if len(full_text) > 4000:
        full_text = full_text[:3990] + "\n\\.\\.\\."
    return full_text


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    sample_event = {
        "ticker": "BTC",
        "return_1h": 0.042,
        "event_type": "surge",
        "severity": "high",
    }
    sample_articles = [
        {"news_title": "Bitcoin ETF inflow hits record $500M in single day", "confidence": 0.9, "sentiment": "bullish"},
        {"news_title": "Short squeeze drives BTC rally as funding rates spike", "confidence": 0.6, "sentiment": "bullish"},
    ]

    print("=== summarize_event_cause (rule-based fallback) ===")
    result = summarize_event_cause(sample_event, sample_articles)
    print(result)

    print("\n=== format_brief_for_telegram ===")
    sample_brief = (
        "[StoryQuant 시장 브리프 | 최근 6시간 | 2026-04-05 12:00 UTC]\n\n"
        "=== 주요 가격 이벤트 ===\n"
        f"  • {result}\n\n"
        "=== 핫 토픽 ===\n"
        "  • BTC / ETF / inflow (기사 8건, momentum=0.85)\n"
    )
    telegram_text = format_brief_for_telegram(sample_brief)
    print(telegram_text)
