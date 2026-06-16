#!/usr/bin/env python3
"""StoryQuant 진입점 — 실제 로직은 serve/ 패키지.

실행:
  python3 serve.py [PORT]    (기본 8765)

구조:
  serve/utils      — http, parsing, stats
  serve/markets    — kr, us 어댑터
  serve/core       — classify / feeds / quote / news / strategy
  serve/api        — HTTP handler (/api/* + ?market=kr|us)
  serve/main       — 서버 부팅

원본 monolithic 코드는 serve.legacy.py 에 보존.
"""
import sys
from serve.main import run


if __name__ == '__main__':
    import os
    env_port = os.environ.get('PORT')   # Render 등 PaaS 가 주입
    port = int(sys.argv[1]) if len(sys.argv) > 1 else int(env_port or 8765)
    host = '0.0.0.0' if env_port else '127.0.0.1'
    run(port=port, host=host)
