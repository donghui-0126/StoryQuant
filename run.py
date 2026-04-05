#!/usr/bin/env python3
"""
StoryQuant 실행 스크립트
Usage:
    python run.py pipeline    # 데이터 파이프라인 실행 (1회)
    python run.py dashboard   # Streamlit 대시보드 실행
    python run.py live        # 백그라운드 수집 + 대시보드 동시 실행
    python run.py migrate     # CSV 데이터를 SQLite로 마이그레이션
    python run.py all         # 파이프라인 실행 후 대시보드 시작
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
    print("DB initialized: data/storyquant.db")
    return conn


def run_pipeline():
    print("=" * 50)
    print("StoryQuant Pipeline 실행")
    print("=" * 50)
    init_db()
    from src.pipeline import run_pipeline as pipeline
    results = pipeline()
    print("\n=== 결과 요약 ===")
    import pandas as pd
    for key, df in results.items():
        if isinstance(df, pd.DataFrame):
            print(f"  {key}: {len(df)} rows")
    return results


def run_dashboard():
    print("=" * 50)
    print("StoryQuant Dashboard 시작")
    print("=" * 50)
    app_path = ROOT / "src" / "dashboard" / "app.py"
    subprocess.run([sys.executable, "-m", "streamlit", "run", str(app_path),
                    "--server.port", "8501", "--server.headless", "true"])


def run_live():
    """백그라운드 수집 시작 + 대시보드"""
    print("=" * 50)
    print("StoryQuant LIVE 모드")
    print("=" * 50)
    conn = init_db()

    # 백그라운드 수집 시작
    from src.background import BackgroundIngester
    ingester = BackgroundIngester()
    ingester.start()
    print("백그라운드 수집 시작됨")

    try:
        run_dashboard()
    finally:
        ingester.stop()
        print("백그라운드 수집 중지됨")


def run_migrate():
    print("=" * 50)
    print("CSV → SQLite 마이그레이션")
    print("=" * 50)
    from src.db.migrate_csv import migrate
    migrate()
    print("마이그레이션 완료!")


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
    elif cmd == "migrate":
        run_migrate()
    elif cmd == "all":
        run_pipeline()
        run_dashboard()
    else:
        print(f"Unknown command: {cmd}")
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
