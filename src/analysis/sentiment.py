"""
News sentiment analysis for StoryQuant.
Rule-based sentiment with optional LLM enhancement.
"""
import os
import logging
import sqlite3
import pandas as pd

logger = logging.getLogger(__name__)

# Rule-based sentiment keywords
BULLISH_KEYWORDS = [
    "surge", "rally", "soar", "jump", "spike", "bull", "breakout", "all-time high",
    "record", "beat", "exceed", "outperform", "upgrade", "buy", "inflow",
    "급등", "상승", "돌파", "신고가", "호재", "매수", "상향", "서프라이즈",
    "listing", "new listing", "approval", "etf approved", "adoption",
]

BEARISH_KEYWORDS = [
    "crash", "plunge", "dump", "drop", "fall", "bear", "breakdown", "selloff",
    "decline", "downgrade", "sell", "outflow", "hack", "exploit", "ban",
    "급락", "하락", "폭락", "악재", "매도", "하향", "규제", "금지",
    "delist", "delisting", "liquidation", "bankrupt", "fraud",
]


def score_sentiment_rule_based(title: str, summary: str = "") -> tuple:
    """
    Rule-based sentiment scoring.
    Returns: (sentiment: bullish/bearish/neutral, score: -1.0 to 1.0)
    """
    text = f"{title} {summary}".lower()

    bull_count = sum(1 for kw in BULLISH_KEYWORDS if kw.lower() in text)
    bear_count = sum(1 for kw in BEARISH_KEYWORDS if kw.lower() in text)

    total = bull_count + bear_count
    if total == 0:
        return "neutral", 0.0

    score = (bull_count - bear_count) / total  # -1 to +1

    if score > 0.2:
        return "bullish", round(score, 2)
    elif score < -0.2:
        return "bearish", round(score, 2)
    return "neutral", round(score, 2)


def score_sentiment_llm(titles: list, api_key: str = None) -> list:
    """
    Batch sentiment scoring using LLM. Process up to 20 titles at once.
    Returns list of {sentiment, score} dicts.
    """
    key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
    if not key or not titles:
        return [{"sentiment": "neutral", "score": 0.0} for _ in titles]

    numbered = "\n".join([f"{i+1}. {t}" for i, t in enumerate(titles[:20])])
    prompt = f"""각 뉴스 헤드라인의 시장 센티먼트를 분석해. 숫자만 답변해.
+1 = 매우 강세, +0.5 = 약간 강세, 0 = 중립, -0.5 = 약간 약세, -1 = 매우 약세

{numbered}

답변 형식 (줄당 하나씩, 숫자만):
"""

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=key)
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}]
        )

        scores = []
        for line in response.content[0].text.strip().split("\n"):
            line = line.strip().lstrip("0123456789.)")
            try:
                score = float(line.strip())
                score = max(-1.0, min(1.0, score))
                sentiment = "bullish" if score > 0.2 else ("bearish" if score < -0.2 else "neutral")
                scores.append({"sentiment": sentiment, "score": round(score, 2)})
            except ValueError:
                scores.append({"sentiment": "neutral", "score": 0.0})

        # Pad if needed
        while len(scores) < len(titles):
            scores.append({"sentiment": "neutral", "score": 0.0})
        return scores[:len(titles)]

    except Exception as e:
        logger.warning("LLM sentiment scoring failed: %s", e)
        return [{"sentiment": "neutral", "score": 0.0} for _ in titles]


def update_article_sentiments(conn: sqlite3.Connection, use_llm: bool = False) -> int:
    """Score sentiment for articles that don't have it yet."""
    unscored = pd.read_sql_query(
        "SELECT id, title, summary FROM articles WHERE sentiment IS NULL LIMIT 50", conn
    )

    if unscored.empty:
        return 0

    if use_llm and os.environ.get("ANTHROPIC_API_KEY"):
        results = score_sentiment_llm(unscored["title"].tolist())
        for i, (_, row) in enumerate(unscored.iterrows()):
            if i < len(results):
                conn.execute(
                    "UPDATE articles SET sentiment = ?, sentiment_score = ? WHERE id = ?",
                    [results[i]["sentiment"], results[i]["score"], row["id"]]
                )
    else:
        for _, row in unscored.iterrows():
            sentiment, score = score_sentiment_rule_based(row["title"], row.get("summary", ""))
            conn.execute(
                "UPDATE articles SET sentiment = ?, sentiment_score = ? WHERE id = ?",
                [sentiment, score, row["id"]]
            )

    conn.commit()
    return len(unscored)


def get_sentiment_summary(conn: sqlite3.Connection) -> list:
    """Get overall sentiment summary."""
    df = pd.read_sql_query(
        "SELECT sentiment, COUNT(*) as cnt, AVG(sentiment_score) as avg_score FROM articles WHERE sentiment IS NOT NULL GROUP BY sentiment",
        conn
    )
    return df.to_dict(orient="records") if not df.empty else []
