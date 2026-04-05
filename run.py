#!/usr/bin/env python3
"""
StoryQuant v2 실행 스크립트

Usage:
    python run.py pipeline    # 데이터 파이프라인 실행 (1회) — amure-db 필요
    python run.py dashboard   # Streamlit 대시보드 실행
    python run.py live        # 백그라운드 수집 + 대시보드 동시 실행
    python run.py status      # amure-db 연결 상태 확인

Prerequisites:
    amure-db 서버가 localhost:8081에서 실행 중이어야 합니다.
    cd ../amure-db && cargo run
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))


def init_db():
    from src.db.schema import get_connection, init_db as _init
    conn = get_connection()
    _init(conn)
    print("SQLite DB initialized (time-series only): data/storyquant.db")
    return conn


def check_amure_db():
    from src.graph.client import AmureClient
    client = AmureClient()
    if client.is_available():
        summary = client.graph_summary()
        node_count = summary.get("total_nodes", summary.get("node_count", 0))
        edge_count = summary.get("total_edges", summary.get("edge_count", 0))
        print(f"amure-db: ONLINE ({node_count} nodes, {edge_count} edges)")
        client.close()
        return True
    else:
        print("amure-db: OFFLINE")
        print("  → cd ../amure-db && cargo run")
        client.close()
        return False


def run_pipeline():
    print("=" * 50)
    print("StoryQuant v2 Pipeline")
    print("=" * 50)
    init_db()
    if not check_amure_db():
        print("\n[WARNING] amure-db is offline. Data collection only (no graph analysis).")

    from src.pipeline import run_pipeline as pipeline
    results = pipeline()
    print("\n=== Results ===")
    for key, val in results.items():
        print(f"  {key}: {val}")
    return results


def run_dashboard():
    print("=" * 50)
    print("StoryQuant v2 Dashboard")
    print("=" * 50)
    check_amure_db()
    app_path = ROOT / "src" / "dashboard" / "app.py"
    subprocess.run([sys.executable, "-m", "streamlit", "run", str(app_path),
                    "--server.port", "8501", "--server.headless", "true"])


def run_live():
    """백그라운드 수집 + 대시보드"""
    print("=" * 50)
    print("StoryQuant v2 LIVE MODE")
    print("=" * 50)
    init_db()
    online = check_amure_db()
    if not online:
        print("\n[WARNING] amure-db offline. Starting in degraded mode (data collection only).\n")

    from src.background import BackgroundIngester
    ingester = BackgroundIngester()
    ingester.start()
    print("Background ingester started (14 workers + Binance WS)")

    try:
        run_dashboard()
    finally:
        ingester.stop()
        print("Background ingester stopped")


def run_status():
    """Show system status."""
    print("=" * 50)
    print("StoryQuant v2 Status")
    print("=" * 50)

    # amure-db
    check_amure_db()

    # SQLite
    from src.db.schema import get_connection
    try:
        conn = get_connection()
        prices = conn.execute("SELECT COUNT(*) FROM prices").fetchone()[0]
        print(f"SQLite: {prices} price rows")
        conn.close()
    except Exception as e:
        print(f"SQLite: error ({e})")

    # Config
    from src.config.settings import AMURE_DB_URL, SQLITE_DB_PATH
    print(f"\nConfig:")
    print(f"  amure-db URL: {AMURE_DB_URL}")
    print(f"  SQLite path:  {SQLITE_DB_PATH}")

    import os
    for key in ["ANTHROPIC_API_KEY", "ARKHAM_API_KEY", "TELEGRAM_BOT_TOKEN"]:
        val = os.environ.get(key, "")
        status = "set" if val else "not set"
        print(f"  {key}: {status}")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    cmd = sys.argv[1].lower()

    if cmd == "pipeline":
        run_pipeline()
    elif cmd == "dashboard":
        run_dashboard()
    elif cmd == "live":
        run_live()
    elif cmd == "status":
        run_status()
    elif cmd == "all":
        run_pipeline()
        run_dashboard()
    else:
        print(f"Unknown command: {cmd}")
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
