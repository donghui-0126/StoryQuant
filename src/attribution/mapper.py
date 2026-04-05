"""
News-event attribution mapper.
Maps price move events to their likely news causes using rule-based scoring.
"""

import logging
import os
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Ticker metadata (hardcoded for PoC)
# ---------------------------------------------------------------------------

TICKER_METADATA = {
    "BTC-USD": {
        "name": "Bitcoin",
        "sector": "crypto",
        "keywords": ["bitcoin", "btc", "crypto", "etf"],
    },
    "ETH-USD": {
        "name": "Ethereum",
        "sector": "crypto",
        "keywords": ["ethereum", "eth", "defi"],
    },
    "SOL-USD": {
        "name": "Solana",
        "sector": "crypto",
        "keywords": ["solana", "sol"],
    },
    "NVDA": {
        "name": "NVIDIA",
        "sector": "semiconductors",
        "keywords": ["nvidia", "gpu", "ai", "chip"],
    },
    "AAPL": {
        "name": "Apple",
        "sector": "tech",
        "keywords": ["apple", "iphone", "mac"],
    },
    "TSLA": {
        "name": "Tesla",
        "sector": "ev",
        "keywords": ["tesla", "ev", "musk", "electric"],
    },
    "SPY": {
        "name": "S&P 500",
        "sector": "index",
        "keywords": ["s&p", "market", "fed", "rate", "inflation"],
    },
    "005930.KS": {
        "name": "삼성전자",
        "sector": "semiconductors",
        "keywords": ["삼성", "samsung", "반도체", "갤럭시"],
    },
    "000660.KS": {
        "name": "SK하이닉스",
        "sector": "semiconductors",
        "keywords": ["하이닉스", "hynix", "반도체", "hbm"],
    },
    "035420.KS": {
        "name": "네이버",
        "sector": "tech",
        "keywords": ["네이버", "naver", "검색", "라인"],
    },
}

# Sector-level shared keywords
SECTOR_KEYWORDS = {
    "crypto": ["crypto", "blockchain", "defi", "web3", "token", "coin"],
    "semiconductors": ["chip", "semiconductor", "wafer", "foundry", "fab", "hbm", "반도체"],
    "tech": ["tech", "software", "cloud", "ai", "digital"],
    "ev": ["electric vehicle", "ev", "battery", "charging"],
    "index": ["market", "index", "s&p", "dow", "nasdaq", "fed", "rate", "inflation", "gdp"],
}

TIME_WINDOW_HOURS = 2  # news published within this window before the event


# ---------------------------------------------------------------------------
# Scoring helpers
# ---------------------------------------------------------------------------

def _text_contains(text: str, terms: list[str]) -> bool:
    """Return True if any term appears in lowercased text."""
    low = text.lower()
    return any(t.lower() in low for t in terms)


def _ticker_mention_score(ticker: str, meta: dict, title: str, summary: str) -> float:
    """Score 0-1: does the news mention the ticker or company name?"""
    combined = f"{title} {summary}".lower()
    # Direct ticker symbol match (e.g. "NVDA", "BTC")
    base_ticker = ticker.split("-")[0].split(".")[0].lower()
    if base_ticker in combined:
        return 1.0
    # Company name match
    if meta["name"].lower() in combined:
        return 1.0
    # Keyword match (at least one primary keyword)
    if _text_contains(combined, meta["keywords"]):
        return 0.7
    return 0.0


def _sector_score(meta: dict, title: str, summary: str) -> float:
    """Score 0-1: does the news mention sector-level keywords?"""
    combined = f"{title} {summary}".lower()
    sector = meta.get("sector", "")
    # Sector name itself
    if sector and sector in combined:
        return 0.8
    # Sector shared keywords
    sector_kws = SECTOR_KEYWORDS.get(sector, [])
    if sector_kws and _text_contains(combined, sector_kws):
        return 0.5
    return 0.0


def _time_proximity_score(event_time: pd.Timestamp, news_time: pd.Timestamp) -> float:
    """
    Score 0-1 based on how close the news is to the event.
    Full score for news within 30 min, decaying to 0 at TIME_WINDOW_HOURS.
    News after the event gets 0.
    """
    if pd.isna(news_time) or pd.isna(event_time):
        return 0.0
    # Ensure tz-aware comparison
    if event_time.tzinfo is not None and news_time.tzinfo is None:
        news_time = news_time.tz_localize(event_time.tzinfo)
    elif event_time.tzinfo is None and news_time.tzinfo is not None:
        event_time = event_time.tz_localize(news_time.tzinfo)

    delta_hours = (event_time - news_time).total_seconds() / 3600.0
    if delta_hours < 0:
        # News published after the event — still somewhat relevant if very close
        if abs(delta_hours) <= 0.5:
            return 0.3
        return 0.0
    if delta_hours > TIME_WINDOW_HOURS:
        return 0.0
    # Linear decay: 0 hours -> 1.0, TIME_WINDOW_HOURS -> 0.1
    return max(0.1, 1.0 - (delta_hours / TIME_WINDOW_HOURS) * 0.9)


def _keyword_overlap_score(meta: dict, title: str, summary: str) -> float:
    """Score 0-1: overlap between ticker keywords and news text."""
    combined = f"{title} {summary}".lower()
    keywords = meta.get("keywords", [])
    if not keywords:
        return 0.0
    hits = sum(1 for kw in keywords if kw.lower() in combined)
    return min(1.0, hits / len(keywords))


def _confidence_label(score: float) -> str:
    if score >= 0.6:
        return "high"
    elif score >= 0.3:
        return "medium"
    return "low"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def compute_attribution_score(event_row: pd.Series, news_df: pd.DataFrame) -> pd.DataFrame:
    """
    Score all news articles for a single price-move event.

    Parameters
    ----------
    event_row : pd.Series
        A row from events_df with fields: ticker, timestamp, return_1h, etc.
    news_df : pd.DataFrame
        News articles with columns: timestamp, title, source, market, url,
        summary, topic_id, topic_label

    Returns
    -------
    pd.DataFrame
        Top matching news articles with attribution scores. Columns:
        ticker, event_time, news_title, news_time, news_url,
        ticker_mention_score, sector_score, time_proximity_score,
        keyword_score, total_score, confidence
    """
    ticker = event_row["ticker"]
    event_time = pd.Timestamp(event_row["timestamp"])
    meta = TICKER_METADATA.get(ticker, {
        "name": ticker,
        "sector": "",
        "keywords": [ticker.lower()],
    })

    if news_df.empty:
        return pd.DataFrame()

    records = []
    for _, news_row in news_df.iterrows():
        title = str(news_row.get("title", ""))
        summary = str(news_row.get("summary", ""))
        news_time = pd.Timestamp(news_row.get("timestamp", pd.NaT))
        news_url = news_row.get("url", "")

        tm = _ticker_mention_score(ticker, meta, title, summary)
        sec = _sector_score(meta, title, summary)
        prox = _time_proximity_score(event_time, news_time)
        kw = _keyword_overlap_score(meta, title, summary)

        # Weighted total: ticker mention is most important
        total = (tm * 0.40) + (sec * 0.20) + (prox * 0.25) + (kw * 0.15)

        records.append({
            "ticker": ticker,
            "event_time": event_time,
            "news_title": title,
            "news_time": news_time,
            "news_url": news_url,
            "ticker_mention_score": round(tm, 3),
            "sector_score": round(sec, 3),
            "time_proximity_score": round(prox, 3),
            "keyword_score": round(kw, 3),
            "total_score": round(total, 3),
            "confidence": _confidence_label(total),
        })

    if not records:
        return pd.DataFrame()

    result = pd.DataFrame(records)
    result = result.sort_values("total_score", ascending=False).reset_index(drop=True)
    return result


def attribute_all_events(events_df: pd.DataFrame, news_df: pd.DataFrame) -> pd.DataFrame:
    """
    Run attribution for all events, returning top 3 news matches per event.

    Parameters
    ----------
    events_df : pd.DataFrame
        Price-move events with columns: ticker, timestamp, return_1h,
        volume_ratio, event_type, severity
    news_df : pd.DataFrame
        News articles (same schema as compute_attribution_score)

    Returns
    -------
    pd.DataFrame
        Combined attribution results (up to 3 news rows per event).
    """
    if events_df.empty or news_df.empty:
        return pd.DataFrame()

    all_results = []
    for _, event_row in events_df.iterrows():
        scored = compute_attribution_score(event_row, news_df)
        if scored.empty:
            continue
        top3 = scored.head(3)
        all_results.append(top3)

    if not all_results:
        return pd.DataFrame()

    return pd.concat(all_results, ignore_index=True)


def generate_attribution_summary(attribution_df: pd.DataFrame) -> pd.DataFrame:
    """
    Generate a one-line human-readable summary per event.

    Parameters
    ----------
    attribution_df : pd.DataFrame
        Output of attribute_all_events()

    Returns
    -------
    pd.DataFrame
        Columns: ticker, event_time, return_1h, event_type,
                 top_cause, confidence, summary_text
    """
    if attribution_df.empty:
        return pd.DataFrame()

    # Keep only the best-scoring news per (ticker, event_time)
    idx = attribution_df.groupby(["ticker", "event_time"])["total_score"].idxmax()
    best = attribution_df.loc[idx].copy().reset_index(drop=True)

    rows = []
    for _, row in best.iterrows():
        ticker = row["ticker"]
        event_time = row["event_time"]
        confidence = row["confidence"]
        top_cause = row["news_title"]

        # Pull return_1h from attribution_df if available, else NaN
        ret = attribution_df.loc[
            (attribution_df["ticker"] == ticker) &
            (attribution_df["event_time"] == event_time),
            "total_score"
        ].iloc[0]  # placeholder; actual return comes from events_df

        # Build summary text
        ret_str = ""  # will be enriched if events_df is merged later
        summary = (
            f"{ticker} | 주요 원인: {top_cause[:60]}{'...' if len(top_cause) > 60 else ''} "
            f"(confidence: {confidence})"
        )

        rows.append({
            "ticker": ticker,
            "event_time": event_time,
            "return_1h": np.nan,  # caller should merge with events_df for actual value
            "event_type": "",
            "top_cause": top_cause,
            "confidence": confidence,
            "summary_text": summary,
        })

    return pd.DataFrame(rows)


def generate_attribution_summary_with_events(
    attribution_df: pd.DataFrame,
    events_df: pd.DataFrame,
) -> pd.DataFrame:
    """
    Like generate_attribution_summary but enriches with return_1h and event_type
    from the original events_df.
    """
    summary = generate_attribution_summary(attribution_df)
    if summary.empty or events_df.empty:
        return summary

    events_key = events_df[["ticker", "timestamp", "return_1h", "event_type"]].copy()
    events_key = events_key.rename(columns={"timestamp": "event_time"})
    events_key["event_time"] = pd.to_datetime(events_key["event_time"])
    summary["event_time"] = pd.to_datetime(summary["event_time"])

    merged = summary.merge(
        events_key,
        on=["ticker", "event_time"],
        how="left",
        suffixes=("_old", ""),
    )
    # Drop placeholder columns if overwritten
    for col in ["return_1h", "event_type"]:
        old_col = f"{col}_old"
        if old_col in merged.columns:
            merged = merged.drop(columns=[old_col])

    # Rebuild summary_text with actual return
    def _rebuild(row):
        ret_val = row.get("return_1h", np.nan)
        ret_str = f" {ret_val:+.2%}" if pd.notna(ret_val) else ""
        top = str(row["top_cause"])
        short_cause = top[:60] + ("..." if len(top) > 60 else "")
        return (
            f"{row['ticker']}{ret_str} | 주요 원인: {short_cause} "
            f"(confidence: {row['confidence']})"
        )

    merged["summary_text"] = merged.apply(_rebuild, axis=1)
    return merged[[
        "ticker", "event_time", "return_1h", "event_type",
        "top_cause", "confidence", "summary_text",
    ]]


def llm_verify_attribution(event: dict, top_news: list, api_key: str = None) -> dict:
    """
    Use LLM to verify if the rule-based attribution makes sense.

    Args:
        event: dict with ticker, return_1h, event_type, timestamp
        top_news: list of dicts with title, source, summary
        api_key: Anthropic API key (from env if None)

    Returns:
        dict: {
            verified: bool,
            best_match_idx: int (index in top_news),
            confidence: str (high/medium/low),
            explanation: str (1-2 sentence explanation),
            sentiment: str (bullish/bearish/neutral)
        }
    """
    import os
    key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
    if not key:
        return {"verified": False, "explanation": "API key not available", "confidence": "low", "sentiment": "neutral", "best_match_idx": 0}

    # Build prompt
    news_text = "\n".join([f"{i+1}. [{n.get('source','')}] {n.get('title','')}" for i, n in enumerate(top_news[:5])])

    prompt = f"""다음 가격 이벤트의 원인을 뉴스에서 찾아줘.

이벤트: {event.get('ticker','')} {float(event.get('return_1h',0)):+.2%} ({event.get('event_type','')})
시간: {event.get('timestamp','')}

후보 뉴스:
{news_text}

JSON으로 답변해:
{{"best_match": 번호(1-5), "confidence": "high/medium/low", "explanation": "원인 설명 1문장", "sentiment": "bullish/bearish/neutral"}}

뉴스 중 원인이 없으면 {{"best_match": 0, "confidence": "low", "explanation": "관련 뉴스 없음", "sentiment": "neutral"}}"""

    try:
        import anthropic
        import json
        client = anthropic.Anthropic(api_key=key)
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",  # Fast and cheap
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}]
        )

        text = response.content[0].text.strip()
        # Extract JSON from response
        if "{" in text:
            json_str = text[text.index("{"):text.rindex("}")+1]
            result = json.loads(json_str)
            return {
                "verified": result.get("best_match", 0) > 0,
                "best_match_idx": result.get("best_match", 0) - 1,
                "confidence": result.get("confidence", "low"),
                "explanation": result.get("explanation", ""),
                "sentiment": result.get("sentiment", "neutral"),
            }
    except Exception as e:
        logger.warning("LLM attribution verification failed: %s", e)

    return {"verified": False, "explanation": "LLM verification failed", "confidence": "low", "sentiment": "neutral", "best_match_idx": 0}


def save_attribution_csv(df: pd.DataFrame, data_dir: str = "data/events") -> str:
    """
    Save attribution DataFrame to a timestamped CSV file.

    Returns the path of the saved file.
    """
    os.makedirs(data_dir, exist_ok=True)
    now = datetime.utcnow()
    filename = f"attribution_{now.strftime('%Y%m%d_%H')}.csv"
    path = os.path.join(data_dir, filename)
    df.to_csv(path, index=False, encoding="utf-8-sig")
    print(f"[attribution] Saved {len(df)} rows -> {path}")
    return path


# ---------------------------------------------------------------------------
# Standalone test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # --- Sample events ---
    events_df = pd.DataFrame([
        {
            "ticker": "BTC-USD",
            "timestamp": "2024-01-15 10:00:00",
            "return_1h": 0.042,
            "volume_ratio": 2.3,
            "event_type": "spike",
            "severity": "high",
        },
        {
            "ticker": "NVDA",
            "timestamp": "2024-01-15 14:30:00",
            "return_1h": -0.031,
            "volume_ratio": 1.8,
            "event_type": "drop",
            "severity": "medium",
        },
        {
            "ticker": "005930.KS",
            "timestamp": "2024-01-15 09:00:00",
            "return_1h": 0.025,
            "volume_ratio": 1.5,
            "event_type": "spike",
            "severity": "medium",
        },
    ])

    # --- Sample news ---
    news_df = pd.DataFrame([
        {
            "timestamp": "2024-01-15 09:30:00",
            "title": "Bitcoin ETF inflow hits record $500M as BTC surges",
            "source": "CoinDesk",
            "market": "crypto",
            "url": "https://coindesk.com/btc-etf-inflow",
            "summary": "Bitcoin ETF products saw record inflows of $500M, pushing BTC price higher.",
            "topic_id": "t001",
            "topic_label": "crypto_etf",
        },
        {
            "timestamp": "2024-01-15 14:00:00",
            "title": "NVIDIA faces new export restrictions on AI chips",
            "source": "Reuters",
            "market": "tech",
            "url": "https://reuters.com/nvda-export",
            "summary": "US government announces new restrictions on NVIDIA GPU exports to China.",
            "topic_id": "t002",
            "topic_label": "chip_regulation",
        },
        {
            "timestamp": "2024-01-15 08:45:00",
            "title": "삼성전자, HBM 반도체 공급 확대 발표",
            "source": "한국경제",
            "market": "kr_stock",
            "url": "https://hankyung.com/samsung-hbm",
            "summary": "삼성전자가 차세대 HBM 반도체 생산량을 두 배로 늘리겠다고 발표했다.",
            "topic_id": "t003",
            "topic_label": "semiconductor",
        },
        {
            "timestamp": "2024-01-14 20:00:00",
            "title": "Fed signals rate hold for Q1 2024",
            "source": "Bloomberg",
            "market": "macro",
            "url": "https://bloomberg.com/fed-rate",
            "summary": "Federal Reserve officials signal rates will remain steady through Q1.",
            "topic_id": "t004",
            "topic_label": "macro",
        },
    ])

    print("=" * 60)
    print("1. Single-event attribution (BTC-USD)")
    print("=" * 60)
    btc_event = events_df.iloc[0]
    scored = compute_attribution_score(btc_event, news_df)
    print(scored[["news_title", "ticker_mention_score", "sector_score",
                  "time_proximity_score", "keyword_score", "total_score", "confidence"]])

    print("\n" + "=" * 60)
    print("2. All events attribution (top 3 per event)")
    print("=" * 60)
    attribution_df = attribute_all_events(events_df, news_df)
    print(attribution_df[["ticker", "event_time", "news_title", "total_score", "confidence"]])

    print("\n" + "=" * 60)
    print("3. Attribution summary with return_1h")
    print("=" * 60)
    summary_df = generate_attribution_summary_with_events(attribution_df, events_df)
    for _, row in summary_df.iterrows():
        print(row["summary_text"])

    print("\n" + "=" * 60)
    print("4. Save to CSV")
    print("=" * 60)
    path = save_attribution_csv(attribution_df, data_dir="data/events")
    print(f"Saved to: {path}")
