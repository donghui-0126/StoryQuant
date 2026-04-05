"""
LLM-powered market view generator.
Aggregates all collected data and generates a coherent market narrative using Claude API.

Requires: ANTHROPIC_API_KEY environment variable
"""

import os
import json
import logging
from datetime import datetime, timezone
import sqlite3

import pandas as pd

logger = logging.getLogger(__name__)


def _get_api_key():
    return os.environ.get("ANTHROPIC_API_KEY", "")


def collect_market_context(conn: sqlite3.Connection) -> dict:
    """
    Collect all relevant data from DB for market view generation.
    Returns a dict with all context needed for the LLM.
    """
    context = {}

    # 1. Recent hot topics (last 6h)
    topics = pd.read_sql_query(
        "SELECT topic_label, frequency, momentum_score FROM topics ORDER BY created_at DESC LIMIT 10", conn
    )
    context["hot_topics"] = topics.to_dict(orient="records") if not topics.empty else []

    # 2. Recent price events (last 24h)
    events = pd.read_sql_query(
        "SELECT ticker, timestamp, return_1h, event_type, severity FROM events WHERE event_type IS NOT NULL ORDER BY timestamp DESC LIMIT 20", conn
    )
    context["price_events"] = events.to_dict(orient="records") if not events.empty else []

    # 3. Top news headlines (last 12h, diverse sources)
    news = pd.read_sql_query(
        "SELECT title, source, source_type, market, published_at FROM articles ORDER BY published_at DESC LIMIT 30", conn
    )
    context["recent_news"] = news.to_dict(orient="records") if not news.empty else []

    # 4. Open Interest data (latest per ticker)
    try:
        oi = pd.read_sql_query(
            "SELECT ticker, open_interest, oi_value_usd, long_short_ratio, long_pct, short_pct, timestamp FROM open_interest ORDER BY timestamp DESC LIMIT 9", conn
        )
        context["open_interest"] = oi.to_dict(orient="records") if not oi.empty else []
    except Exception:
        context["open_interest"] = []

    # 5. Recent attributions (top confidence)
    attr = pd.read_sql_query("""
        SELECT e.ticker, e.return_1h, e.event_type, a.confidence, a.total_score,
               ar.title as news_title, ar.source
        FROM attributions a
        JOIN events e ON a.event_id = e.id
        JOIN articles ar ON a.article_id = ar.id
        WHERE a.confidence IN ('high', 'medium')
        ORDER BY a.total_score DESC LIMIT 10
    """, conn)
    context["top_attributions"] = attr.to_dict(orient="records") if not attr.empty else []

    # 6. Price summary (latest close per ticker)
    prices = pd.read_sql_query("""
        SELECT ticker, close, timestamp FROM prices
        WHERE (ticker, timestamp) IN (
            SELECT ticker, MAX(timestamp) FROM prices GROUP BY ticker
        )
    """, conn)
    context["current_prices"] = prices.to_dict(orient="records") if not prices.empty else []

    # 7. Exchange announcements
    announcements = pd.read_sql_query(
        "SELECT title, summary FROM articles WHERE source_type = 'exchange_announcement' ORDER BY published_at DESC LIMIT 5", conn
    )
    context["exchange_announcements"] = announcements.to_dict(orient="records") if not announcements.empty else []

    context["generated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")

    return context


def generate_market_view(conn: sqlite3.Connection, language: str = "ko") -> str:
    """
    Generate a market view using Claude API.

    Args:
        conn: SQLite connection
        language: "ko" for Korean, "en" for English

    Returns:
        Markdown-formatted market view string
    """
    api_key = _get_api_key()
    if not api_key:
        return _generate_fallback_view(conn)

    context = collect_market_context(conn)

    lang_instruction = "한국어로 작성해주세요." if language == "ko" else "Write in English."

    prompt = f"""당신은 전문 크립토/금융 시장 애널리스트입니다. 아래 수집된 실시간 데이터를 기반으로 현재 시장 뷰를 작성해주세요.

{lang_instruction}

## 수집된 데이터

### Hot Topics (최근 핫한 주제)
{json.dumps(context['hot_topics'], ensure_ascii=False, indent=2)}

### 가격 이벤트 (급등/급락/거래량 이상)
{json.dumps(context['price_events'], ensure_ascii=False, indent=2)}

### 주요 뉴스 헤드라인
{json.dumps(context['recent_news'][:15], ensure_ascii=False, indent=2)}

### 미결제약정 (OI) & 롱숏비율
{json.dumps(context['open_interest'], ensure_ascii=False, indent=2)}

### 뉴스-가격 Attribution (높은 신뢰도)
{json.dumps(context['top_attributions'], ensure_ascii=False, indent=2)}

### 현재 가격
{json.dumps(context['current_prices'], ensure_ascii=False, indent=2)}

### 거래소 공지
{json.dumps(context['exchange_announcements'], ensure_ascii=False, indent=2)}

## 요청사항

위 데이터를 종합하여 다음 형식으로 시장 뷰를 작성해주세요:

### 📊 시장 요약
(현재 시장 전반적인 분위기와 핵심 테마 2-3문장)

### 🔥 핵심 이벤트
(가장 중요한 가격 움직임과 그 원인 3-5개, bullet point)

### 📈 크립토 시장
(BTC, ETH, SOL 중심으로 가격 동향, OI/롱숏 분석, 주요 뉴스)

### 🇺🇸 미국 시장
(NVDA, AAPL, TSLA, SPY 관련 동향)

### 🇰🇷 한국 시장
(삼성전자, SK하이닉스, 네이버 관련 동향)

### ⚠️ 리스크 & 주의사항
(현재 주의해야 할 포인트, 이상 신호)

### 💡 트레이딩 인사이트
(데이터 기반 실행 가능한 인사이트 2-3개)

간결하고 데이터 기반으로 작성하세요. 추측이 아닌 수집된 데이터에서 도출된 결론만 포함하세요."""

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)

        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=2000,
            messages=[{"role": "user", "content": prompt}]
        )

        return response.content[0].text

    except ImportError:
        logger.warning("anthropic package not installed. pip install anthropic")
        return _generate_fallback_view(conn)
    except Exception as exc:
        logger.error("LLM market view generation failed: %s", exc)
        return _generate_fallback_view(conn)


def _generate_fallback_view(conn: sqlite3.Connection) -> str:
    """
    Generate a simple rule-based market view when LLM is not available.
    Uses the collected data to create a basic summary.
    """
    context = collect_market_context(conn)

    lines = ["## 📊 시장 요약 (자동 생성)\n"]
    lines.append(f"*생성 시각: {context['generated_at']}*\n")

    # Hot topics
    if context["hot_topics"]:
        lines.append("### 🔥 Hot Topics")
        for t in context["hot_topics"][:5]:
            lines.append(f"- **{t.get('topic_label', 'N/A')}** (빈도: {t.get('frequency', 0)})")
        lines.append("")

    # Price events
    if context["price_events"]:
        lines.append("### ⚡ 최근 가격 이벤트")
        for e in context["price_events"][:10]:
            ret = e.get("return_1h", 0)
            try:
                ret_str = f"{float(ret):+.2%}"
            except (TypeError, ValueError):
                ret_str = str(ret)
            severity_icon = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(e.get("severity", ""), "⚪")
            lines.append(f"- {severity_icon} **{e.get('ticker', '?')}** {ret_str} ({e.get('event_type', '')})")
        lines.append("")

    # OI summary
    if context["open_interest"]:
        lines.append("### 📊 미결제약정")
        for oi in context["open_interest"][:3]:
            ls = oi.get("long_short_ratio", "N/A")
            lines.append(f"- **{oi.get('ticker', '?')}**: OI ${oi.get('oi_value_usd', 0):,.0f} | 롱/숏 비율: {ls}")
        lines.append("")

    # Top attributions
    if context["top_attributions"]:
        lines.append("### 🔗 주요 원인 분석")
        for a in context["top_attributions"][:5]:
            ret = a.get("return_1h", 0)
            try:
                ret_str = f"{float(ret):+.2%}"
            except (TypeError, ValueError):
                ret_str = str(ret)
            lines.append(f"- **{a.get('ticker', '?')}** {ret_str} ← {a.get('news_title', 'N/A')} ({a.get('confidence', '')})")
        lines.append("")

    # Top news
    if context["recent_news"]:
        lines.append("### 📰 주요 뉴스")
        seen = set()
        for n in context["recent_news"][:10]:
            title = n.get("title", "")
            if title not in seen:
                seen.add(title)
                badge = {"twitter": "🐦", "exchange_announcement": "🏛️", "community": "💬"}.get(n.get("source_type", ""), "📡")
                lines.append(f"- {badge} {title}")
        lines.append("")

    # Historical context
    try:
        from src.analysis.historical import generate_historical_context
        hist = generate_historical_context(conn)
        if hist and "(아직 충분한" not in hist:
            lines.append("### 📜 과거 성과 기반 분석")
            lines.append(hist)
            lines.append("")
    except Exception:
        pass

    if not any(context.values()):
        lines.append("\n데이터가 부족합니다. 파이프라인을 실행해주세요.")

    lines.append("\n---\n*LLM 분석을 활성화하려면 `export ANTHROPIC_API_KEY=your_key`를 설정하세요.*")

    return "\n".join(lines)


if __name__ == "__main__":
    import sys
    from pathlib import Path

    ROOT = Path(__file__).resolve().parent.parent.parent
    sys.path.insert(0, str(ROOT))

    DB_PATH = str(ROOT / "data" / "storyquant.db")

    try:
        from src.db.schema import get_connection, init_db
        conn = get_connection(DB_PATH)
        init_db(conn)
    except Exception as e:
        print(f"DB connection failed: {e}")
        sys.exit(1)

    lang = sys.argv[1] if len(sys.argv) > 1 else "ko"
    view = generate_market_view(conn, language=lang)
    print(view)
