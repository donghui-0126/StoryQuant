"""
Claude Code server-side market analysis hook.
Pre-collects data from DB, then spawns claude CLI for analysis only.
"""

import json
import subprocess
import logging
import os
from pathlib import Path
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent.parent
REPORTS_DIR = ROOT / "data" / "reports"
DB_PATH = ROOT / "data" / "storyquant.db"
CONTEXT_PATH = ROOT / "data" / "reports" / "_market_context.json"


def _ensure_reports_dir():
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)


def _collect_context() -> str:
    """Pre-collect all market data from DB and return as formatted string."""
    from src.analysis.market_view import collect_market_context
    from src.db.schema import get_connection, init_db

    conn = get_connection(str(DB_PATH))
    init_db(conn)
    ctx = collect_market_context(conn)
    conn.close()

    sections = []

    sections.append("=== Hot Topics ===")
    for t in ctx.get("hot_topics", []):
        sections.append(f"  {t.get('topic_label','')} (freq={t.get('frequency',0)}, momentum={t.get('momentum_score',0):.2f})")

    sections.append("\n=== 가격 이벤트 ===")
    for e in ctx.get("price_events", []):
        ret = e.get("return_1h", 0)
        sections.append(f"  {e.get('ticker','')} {float(ret):+.2%} {e.get('event_type','')} severity={e.get('severity','')}")

    sections.append("\n=== 주요 뉴스 (최근 30건) ===")
    for n in ctx.get("recent_news", [])[:20]:
        sections.append(f"  [{n.get('source','')}] [{n.get('market','')}] {n.get('title','')}")

    sections.append("\n=== 미결제약정 (OI) ===")
    for o in ctx.get("open_interest", []):
        sections.append(f"  {o.get('ticker','')}: OI=${o.get('oi_value_usd',0):,.0f} L/S={o.get('long_short_ratio','N/A')} long={o.get('long_pct','')}")

    sections.append("\n=== Attribution (뉴스→가격 매핑, 높은 신뢰도) ===")
    for a in ctx.get("top_attributions", []):
        ret = a.get("return_1h", 0)
        sections.append(f"  {a.get('ticker','')} {float(ret):+.2%} ← {a.get('news_title','')} (conf={a.get('confidence','')})")

    sections.append("\n=== 현재 가격 ===")
    for p in ctx.get("current_prices", []):
        sections.append(f"  {p.get('ticker','')}: {p.get('close',0):,.2f} (at {p.get('timestamp','')})")

    sections.append("\n=== 거래소 공지 ===")
    for a in ctx.get("exchange_announcements", []):
        sections.append(f"  {a.get('title','')}")

    # Historical performance data
    from src.analysis.historical import generate_historical_context
    conn2 = get_connection(str(DB_PATH))
    init_db(conn2)
    hist_context = generate_historical_context(conn2)
    conn2.close()
    sections.append(f"\n{hist_context}")

    return "\n".join(sections)


def generate_market_report(timeout: int = 180) -> dict:
    """
    Pre-collect data, then spawn claude CLI for analysis only (no tool use needed).
    """
    _ensure_reports_dir()

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = REPORTS_DIR / f"market_view_{timestamp}.md"

    # Step 1: Collect data in Python (fast)
    try:
        context_str = _collect_context()
    except Exception as exc:
        logger.error("Failed to collect market context: %s", exc)
        return {"success": False, "report_path": "", "report_text": "", "error": f"데이터 수집 실패: {exc}"}

    # Step 2: Build a concise prompt with pre-collected data
    prompt = f"""아래는 StoryQuant 시스템이 수집한 실시간 시장 데이터입니다. 이 데이터를 분석해서 시장 리포트를 한국어 마크다운으로 작성해주세요.

{context_str}

아래 형식으로 작성해주세요:

# 📊 StoryQuant 시장 분석 리포트
*생성: {datetime.now().strftime('%Y-%m-%d %H:%M')}*

## 시장 요약
(전체 시장 분위기 2-3문장)

## 🔥 핵심 이벤트 & 원인 분석
(가장 중요한 가격 움직임과 뉴스 기반 원인 3-5개)

## 📈 크립토 시장
(BTC/ETH/SOL 가격, OI/롱숏 분석)

## 🇺🇸 미국 시장
(NVDA/AAPL/TSLA/SPY)

## 🇰🇷 한국 시장
(삼성전자/SK하이닉스/네이버)

## ⚠️ 리스크 & 주의사항

## 💡 트레이딩 인사이트
(데이터 기반 실행 가능한 인사이트 3개)

중요: 주장을 할 때는 반드시 '=== 과거 성과 ===' 섹션의 히스토리컬 데이터를 인용하세요.
예: "과거 유사한 surge 이벤트 후 BTC는 평균 +X% 상승했으며(n=Y건), 이번에도 지속 가능성이 높다"
데이터가 없는 주장은 '(데이터 부족)' 표시를 하세요.

간결하게, 데이터 수치를 인용하며 작성하세요."""

    # Step 3: Call claude CLI — no tools needed, just text analysis
    try:
        result = subprocess.run(
            ["claude", "-p", prompt, "--output-format", "text", "--max-turns", "1"],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(ROOT),
        )

        output = result.stdout.strip()

        if output and len(output) > 200:
            report_path.write_text(output, encoding="utf-8")
            logger.info("Market report generated: %s (%d chars)", report_path, len(output))
            return {
                "success": True,
                "report_path": str(report_path),
                "report_text": output,
                "error": "",
            }

        return {
            "success": False,
            "report_path": "",
            "report_text": "",
            "error": f"리포트가 생성되지 않았습니다. stderr: {result.stderr[:300]}",
        }

    except subprocess.TimeoutExpired:
        logger.error("Claude CLI timed out after %ds", timeout)
        return {
            "success": False,
            "report_path": "",
            "report_text": "",
            "error": f"분석 시간 초과 ({timeout}초). 다시 시도해주세요.",
        }
    except FileNotFoundError:
        logger.error("claude CLI not found")
        return {
            "success": False,
            "report_path": "",
            "report_text": "",
            "error": "claude CLI가 설치되지 않았습니다.",
        }
    except Exception as exc:
        logger.error("Claude hook failed: %s", exc)
        return {"success": False, "report_path": "", "report_text": "", "error": str(exc)}


def get_latest_report() -> dict:
    """Get the most recent market report."""
    _ensure_reports_dir()
    reports = sorted(REPORTS_DIR.glob("market_view_*.md"), key=lambda f: f.stat().st_mtime, reverse=True)
    if not reports:
        return {"exists": False, "report_text": "", "report_path": "", "generated_at": ""}
    latest = reports[0]
    return {
        "exists": True,
        "report_text": latest.read_text(encoding="utf-8"),
        "report_path": str(latest),
        "generated_at": datetime.fromtimestamp(latest.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
    }


def list_reports(limit: int = 10) -> list:
    """List recent reports."""
    _ensure_reports_dir()
    reports = sorted(REPORTS_DIR.glob("market_view_*.md"), key=lambda f: f.stat().st_mtime, reverse=True)
    return [
        {
            "filename": r.name,
            "path": str(r),
            "generated_at": datetime.fromtimestamp(r.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
            "size_kb": round(r.stat().st_size / 1024, 1),
        }
        for r in reports[:limit]
    ]


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print("Collecting market context...")
    ctx = _collect_context()
    print(ctx[:1000])
    print(f"\n... ({len(ctx)} chars total)")
    print("\nGenerating report...")
    result = generate_market_report()
    if result["success"]:
        print(f"\nReport saved: {result['report_path']}")
        print(result["report_text"][:500])
    else:
        print(f"\nFailed: {result['error']}")
