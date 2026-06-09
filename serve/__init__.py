"""StoryQuant 서버 — 시장 어댑터 분리 아키텍처.

구조:
  serve/
    utils/        — 순수 유틸 (http, parsing, math)
    core/         — 시장 무관 핵심 로직 (classification, enrichment, strategy)
    markets/      — 시장 어댑터 (kr, us, ...)
    api/          — HTTP 라우팅, endpoint 핸들러
    main.py       — 부트스트랩
"""

__version__ = '21.0'
