"""
narrative.py - Narrative-driven market intelligence engine.

"시장은 숫자가 아니라 이야기로 움직인다"

뉴스를 개별 기사가 아닌 '내러티브(스토리라인)'로 클러스터링하고,
각 내러티브의 생명주기(등장→확산→정점→쇠퇴)를 추적한다.

Core concepts:
  - Narrative: 시장을 움직이는 하나의 스토리라인 (예: "AI capex 확대", "관세 전쟁")
  - Lifecycle: EMERGING → BUILDING → PEAKING → FADING → DEAD
  - Affected Assets: 내러티브에 연동되는 자산들
  - Price Reaction: 내러티브 등장 후 실제 가격 반응
"""

import logging
import re
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Narrative templates - predefined market narratives to detect
# ---------------------------------------------------------------------------

NARRATIVE_TEMPLATES = {
    "ai_capex": {
        "label": "AI Capex Expansion",
        "label_ko": "AI 투자 확대",
        "keywords": ["ai", "artificial intelligence", "gpu", "capex", "data center",
                     "nvidia", "hyperscaler", "cloud", "인공지능", "AI 투자",
                     "데이터센터", "반도체"],
        "assets": ["NVDA", "000660.KS", "005930.KS"],
        "direction": "bullish",
    },
    "etf_flow": {
        "label": "Crypto ETF Flows",
        "label_ko": "크립토 ETF 자금 유입",
        "keywords": ["etf", "inflow", "outflow", "grayscale", "blackrock", "fidelity",
                     "spot bitcoin", "spot ethereum", "etf 승인", "자금 유입"],
        "assets": ["BTC-USD", "ETH-USD"],
        "direction": "bullish",
    },
    "fed_hawkish": {
        "label": "Fed Hawkish Pivot",
        "label_ko": "연준 긴축 시그널",
        "keywords": ["fed", "fomc", "rate hike", "hawkish", "powell", "inflation",
                     "cpi", "금리", "긴축", "연준", "인플레이션"],
        "assets": ["SPY", "BTC-USD", "TSLA"],
        "direction": "bearish",
    },
    "fed_dovish": {
        "label": "Fed Dovish Signal",
        "label_ko": "연준 완화 시그널",
        "keywords": ["rate cut", "dovish", "pivot", "easing", "pause",
                     "금리 인하", "완화", "피벗"],
        "assets": ["SPY", "BTC-USD", "TSLA", "NVDA"],
        "direction": "bullish",
    },
    "trade_war": {
        "label": "Trade War / Tariffs",
        "label_ko": "무역전쟁 / 관세",
        "keywords": ["tariff", "trade war", "sanctions", "ban", "restrict",
                     "china", "관세", "무역전쟁", "제재", "규제"],
        "assets": ["SPY", "AAPL", "NVDA", "005930.KS", "000660.KS"],
        "direction": "bearish",
    },
    "defi_boom": {
        "label": "DeFi / L1 Momentum",
        "label_ko": "디파이 / L1 모멘텀",
        "keywords": ["defi", "tvl", "staking", "layer 1", "l1", "solana",
                     "ethereum upgrade", "디파이", "스테이킹"],
        "assets": ["ETH-USD", "SOL-USD"],
        "direction": "bullish",
    },
    "regulation": {
        "label": "Crypto Regulation",
        "label_ko": "크립토 규제",
        "keywords": ["sec", "regulation", "lawsuit", "enforcement", "compliance",
                     "규제", "소송", "단속", "법안"],
        "assets": ["BTC-USD", "ETH-USD", "SOL-USD"],
        "direction": "bearish",
    },
    "macro_risk": {
        "label": "Macro Risk-Off",
        "label_ko": "매크로 리스크오프",
        "keywords": ["recession", "crisis", "default", "bank run", "contagion",
                     "geopolitical", "war", "경기침체", "위기", "전쟁", "지정학"],
        "assets": ["SPY", "BTC-USD", "TSLA"],
        "direction": "bearish",
    },
    "earnings_beat": {
        "label": "Earnings Beat Cycle",
        "label_ko": "실적 서프라이즈",
        "keywords": ["earnings beat", "revenue growth", "guidance raise", "record profit",
                     "실적", "어닝 서프라이즈", "가이던스 상향", "매출 성장"],
        "assets": ["NVDA", "AAPL", "TSLA", "005930.KS"],
        "direction": "bullish",
    },
    "whale_accumulation": {
        "label": "Whale Accumulation",
        "label_ko": "고래 매집",
        "keywords": ["whale", "accumulate", "large transfer", "exchange outflow",
                     "고래", "매집", "대량 이체", "거래소 출금"],
        "assets": ["BTC-USD", "ETH-USD"],
        "direction": "bullish",
    },
    "kr_semiconductor": {
        "label": "K-Semiconductor Rally",
        "label_ko": "한국 반도체 랠리",
        "keywords": ["hbm", "hynix", "samsung foundry", "memory", "dram", "nand",
                     "HBM", "하이닉스", "삼성 파운드리", "메모리", "반도체"],
        "assets": ["000660.KS", "005930.KS"],
        "direction": "bullish",
    },
    "stablecoin_risk": {
        "label": "Stablecoin Risk",
        "label_ko": "스테이블코인 리스크",
        "keywords": ["usdt", "usdc", "tether", "depeg", "stablecoin", "reserve",
                     "테더", "디페깅", "스테이블코인"],
        "assets": ["BTC-USD", "ETH-USD", "SOL-USD"],
        "direction": "bearish",
    },
}

LIFECYCLE_LABELS = {
    "EMERGING": "🌱",
    "BUILDING": "📈",
    "PEAKING": "🔥",
    "FADING": "📉",
    "DEAD": "💀",
}


# ---------------------------------------------------------------------------
# Core: Detect active narratives
# ---------------------------------------------------------------------------

def detect_narratives(conn: sqlite3.Connection, hours: int = 24) -> list[dict]:
    """Detect which narratives are active based on recent news.

    Returns list of narrative dicts sorted by strength, each containing:
      - narrative_id, label, label_ko, lifecycle, strength (0~1)
      - article_count, velocity, sentiment_bias
      - affected_assets, direction
      - price_reaction (actual returns of affected assets)
      - sample_headlines
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    cutoff_prev = (datetime.now(timezone.utc) - timedelta(hours=hours * 2)).isoformat()

    articles = pd.read_sql_query(
        "SELECT title, summary, published_at, source FROM articles WHERE published_at >= ?",
        conn, params=[cutoff],
    )
    articles_prev = pd.read_sql_query(
        "SELECT title, summary FROM articles WHERE published_at >= ? AND published_at < ?",
        conn, params=[cutoff_prev, cutoff],
    )

    if articles.empty:
        return []

    results = []

    for nid, template in NARRATIVE_TEMPLATES.items():
        keywords = template["keywords"]
        pattern = "|".join(re.escape(kw) for kw in keywords)

        # Match current period
        mask = articles["title"].str.contains(pattern, case=False, na=False) | \
               articles["summary"].fillna("").str.contains(pattern, case=False, na=False)
        matched = articles[mask]
        count_now = len(matched)

        if count_now == 0:
            continue

        # Match previous period (for lifecycle detection)
        if not articles_prev.empty:
            mask_prev = articles_prev["title"].str.contains(pattern, case=False, na=False) | \
                        articles_prev["summary"].fillna("").str.contains(pattern, case=False, na=False)
            count_prev = mask_prev.sum()
        else:
            count_prev = 0

        # --- Lifecycle ---
        if count_prev == 0 and count_now >= 2:
            lifecycle = "EMERGING"
        elif count_now > count_prev * 1.5:
            lifecycle = "BUILDING"
        elif count_now >= count_prev * 0.8:
            lifecycle = "PEAKING"
        elif count_now >= 1:
            lifecycle = "FADING"
        else:
            lifecycle = "DEAD"

        # --- Strength (0~1) ---
        velocity = count_now / max(hours, 1)
        unique_sources = matched["source"].nunique()
        source_ratio = unique_sources / max(articles["source"].nunique(), 1)

        strength = min(1.0, (
            0.4 * min(count_now / 10, 1.0) +      # article volume
            0.3 * min(velocity / 2.0, 1.0) +       # velocity
            0.3 * source_ratio                      # source breadth
        ))

        # --- Sentiment bias ---
        from src.analysis.news_quant import BULLISH_KW, BEARISH_KW
        bullish = bearish = 0
        for _, row in matched.iterrows():
            text = f"{row['title']} {row.get('summary', '')}".lower()
            b = sum(1 for kw in BULLISH_KW if kw.lower() in text)
            s = sum(1 for kw in BEARISH_KW if kw.lower() in text)
            if b > s:
                bullish += 1
            elif s > b:
                bearish += 1
        sentiment_bias = (bullish - bearish) / max(count_now, 1)

        # --- Price reaction of affected assets ---
        price_reactions = {}
        for ticker in template["assets"]:
            try:
                row = conn.execute("""
                    SELECT
                        (SELECT close FROM prices WHERE ticker = ? ORDER BY timestamp DESC LIMIT 1) as latest,
                        (SELECT close FROM prices WHERE ticker = ? AND timestamp <= ? ORDER BY timestamp DESC LIMIT 1) as before
                """, [ticker, ticker, cutoff]).fetchone()
                if row and row[0] and row[1] and row[1] != 0:
                    ret = (row[0] - row[1]) / row[1]
                    price_reactions[ticker] = round(ret, 4)
            except Exception:
                pass

        # --- Sample headlines ---
        headlines = matched["title"].head(3).tolist()

        results.append({
            "narrative_id": nid,
            "label": template["label"],
            "label_ko": template["label_ko"],
            "lifecycle": lifecycle,
            "lifecycle_icon": LIFECYCLE_LABELS.get(lifecycle, ""),
            "strength": round(strength, 2),
            "article_count": count_now,
            "prev_count": count_prev,
            "velocity": round(velocity, 2),
            "unique_sources": unique_sources,
            "sentiment_bias": round(sentiment_bias, 2),
            "direction": template["direction"],
            "affected_assets": template["assets"],
            "price_reactions": price_reactions,
            "headlines": headlines,
        })

    # Sort by strength
    results.sort(key=lambda x: x["strength"], reverse=True)
    return results


# ---------------------------------------------------------------------------
# Narrative report
# ---------------------------------------------------------------------------

def format_narrative_report(narratives: list[dict]) -> str:
    """Format narratives as a human-readable market narrative report."""
    if not narratives:
        return "현재 활성화된 내러티브가 없습니다."

    lines = [
        "═══════════════════════════════════════════════════",
        "  StoryQuant Narrative Intelligence Report",
        "  시장을 움직이는 스토리",
        "═══════════════════════════════════════════════════",
        "",
    ]

    for i, n in enumerate(narratives):
        icon = n["lifecycle_icon"]
        direction_icon = "📈" if n["direction"] == "bullish" else "📉"
        strength_bar = "█" * int(n["strength"] * 10) + "░" * (10 - int(n["strength"] * 10))

        lines.append(f"  {icon} {n['label_ko']} ({n['label']})")
        lines.append(f"     {direction_icon} {n['direction'].upper()} | {n['lifecycle']} | 강도 [{strength_bar}] {n['strength']:.0%}")
        lines.append(f"     기사 {n['article_count']}건 (이전 {n['prev_count']}건) | 소스 {n['unique_sources']}개 | 감성 {n['sentiment_bias']:+.2f}")

        # Price reactions
        if n["price_reactions"]:
            reactions = " | ".join(f"{t} {r:+.1%}" for t, r in n["price_reactions"].items())
            lines.append(f"     자산 반응: {reactions}")

        # Headlines
        if n["headlines"]:
            lines.append(f"     주요 헤드라인:")
            for h in n["headlines"][:2]:
                lines.append(f"       • {h[:70]}")

        lines.append("")

    lines.append("═══════════════════════════════════════════════════")
    return "\n".join(lines)


def format_narrative_telegram(narratives: list[dict]) -> str:
    """Format top narratives for Telegram push."""
    if not narratives:
        return "📖 <b>StoryQuant Narrative</b>\n\n활성 내러티브 없음"

    lines = ["📖 <b>StoryQuant Narrative Report</b>", ""]

    for n in narratives[:5]:
        icon = n["lifecycle_icon"]
        direction = "📈" if n["direction"] == "bullish" else "📉"
        strength_pct = f"{n['strength']:.0%}"

        lines.append(f"{icon} <b>{n['label_ko']}</b> ({n['lifecycle']})")
        lines.append(f"   {direction} {n['direction']} | 강도 {strength_pct} | 기사 {n['article_count']}건")

        # Price reactions
        if n["price_reactions"]:
            reactions = " ".join(
                f"{'🟢' if r > 0 else '🔴'}{t.split('-')[0]} {r:+.1%}"
                for t, r in list(n["price_reactions"].items())[:3]
            )
            lines.append(f"   {reactions}")

        # Top headline
        if n["headlines"]:
            lines.append(f"   → {n['headlines'][0][:60]}")

        lines.append("")

    lines.append("🤖 StoryQuant Narrative Intelligence")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Narrative-based trading signal
# ---------------------------------------------------------------------------

def get_narrative_signals(narratives: list[dict]) -> list[dict]:
    """Convert active narratives into actionable trading signals.

    Only generates signals for EMERGING or BUILDING narratives
    with sufficient strength.
    """
    signals = []

    for n in narratives:
        if n["lifecycle"] not in ("EMERGING", "BUILDING"):
            continue
        if n["strength"] < 0.3:
            continue

        for ticker in n["affected_assets"]:
            reaction = n["price_reactions"].get(ticker, 0)

            # Don't signal if price already moved significantly
            if abs(reaction) > 0.05:
                continue

            direction = "long" if n["direction"] == "bullish" else "short"

            signals.append({
                "ticker": ticker,
                "direction": direction,
                "narrative": n["label_ko"],
                "lifecycle": n["lifecycle"],
                "strength": n["strength"],
                "sentiment": n["sentiment_bias"],
                "article_count": n["article_count"],
                "confidence": round(n["strength"] * (1 + abs(n["sentiment_bias"])) / 2, 2),
            })

    # Sort by confidence
    signals.sort(key=lambda x: x["confidence"], reverse=True)
    return signals


def format_signals_telegram(signals: list[dict]) -> str:
    """Format narrative-based signals for Telegram."""
    if not signals:
        return ""

    lines = ["", "⚡ <b>Narrative Signals</b>", ""]
    for s in signals[:5]:
        icon = "🟢" if s["direction"] == "long" else "🔴"
        lines.append(
            f"{icon} <b>{s['ticker']}</b> {s['direction'].upper()} "
            f"(conf {s['confidence']:.0%})"
        )
        lines.append(f"   {s['narrative']} [{s['lifecycle']}] 강도 {s['strength']:.0%}")
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    from src.db.schema import thread_connection

    with thread_connection() as conn:
        print("Detecting narratives (24h)...\n")
        narratives = detect_narratives(conn, hours=24)
        print(format_narrative_report(narratives))

        print("\n--- Telegram Format ---")
        print(format_narrative_telegram(narratives))

        signals = get_narrative_signals(narratives)
        if signals:
            print("\n--- Trading Signals ---")
            print(format_signals_telegram(signals))

        print(f"\n--- 48h window ---")
        narratives_48 = detect_narratives(conn, hours=48)
        for n in narratives_48:
            print(f"  {n['lifecycle_icon']} {n['label_ko']:<20} {n['lifecycle']:<10} "
                  f"강도 {n['strength']:.0%}  기사 {n['article_count']}건  감성 {n['sentiment_bias']:+.2f}")
