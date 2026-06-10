"""Event-driven attribution — 일 단위 큰 변동 ↔ 직전 24~48h 뉴스 매칭.

기존 한계: 14일치 뉴스 평균 점수 vs 5일 가격 → 인과 시점이 뭉개짐.
여기서는 '특정일 시장 대비 ±threshold% 변동'을 이벤트로 잡고,
그 직전 1~2일 안에 나온 event_bull/event_bear 뉴스만 원인 후보로 연결한다.
"""
import time
from .quote import fetch_stock_chart
from .news import fetch_news_window_for_code

DAY_MS = 86400000


def detect_events(code, market, days=60, threshold=2.5, use_llm=True):
    """이벤트 데이 검출 + 뉴스 attribution.

    returns {
      code, threshold, days,
      events: [{date, ts, move_pct, rel_move_pct, direction,
                matched: [{title, ts, sentiment, llm_label, paper, link}],
                attribution: 'explained' | 'partial' | 'unexplained'}],
      coverage: {n_events, explained, partial, unexplained, explained_rate}
    }
    """
    chart = fetch_stock_chart(code, '3mo', market)
    bars = chart.get('bars', [])
    if len(bars) < 10:
        return {'error': 'insufficient chart data', 'code': code}

    bench = fetch_stock_chart(market.benchmark_symbol, '3mo', market)
    bench_bars = bench.get('bars', [])
    bench_by_day = {b['t'] // DAY_MS: b['c'] for b in bench_bars}

    # 일일 상대 수익률
    events = []
    cutoff_ts = int(time.time() * 1000) - days * DAY_MS
    for i in range(1, len(bars)):
        if bars[i]['t'] < cutoff_ts:
            continue
        prev_c, cur_c = bars[i-1]['c'], bars[i]['c']
        if not prev_c or not cur_c:
            continue
        ret = (cur_c / prev_c - 1) * 100
        # 같은 날 벤치마크 수익률
        d_cur, d_prev = bars[i]['t'] // DAY_MS, bars[i-1]['t'] // DAY_MS
        b_cur, b_prev = bench_by_day.get(d_cur), bench_by_day.get(d_prev)
        bench_ret = ((b_cur / b_prev - 1) * 100) if (b_cur and b_prev) else 0.0
        rel = ret - bench_ret
        if abs(rel) < threshold:
            continue
        events.append({
            'ts': bars[i]['t'],
            'date': time.strftime('%Y-%m-%d', time.localtime(bars[i]['t'] / 1000)),
            'move_pct': round(ret, 2),
            'bench_pct': round(bench_ret, 2),
            'rel_move_pct': round(rel, 2),
            'direction': 'up' if rel > 0 else 'down',
        })

    if not events:
        return {'code': code, 'threshold': threshold, 'days': days,
                'events': [], 'coverage': {'n_events': 0}}

    # 뉴스 — 날짜 범위를 '오늘 기준 days+3' 로 정규화 (캐시 키 일관 → 재사용 극대화)
    # universe 키는 suffix 없는 형식 ('066570') — '.KS' 붙은 코드도 처리
    uni = market.universe()
    base_code = code.split('.')[0]
    name = ((uni.get(code) or uni.get(base_code) or {}).get('name')) or base_code
    now_ms = int(time.time() * 1000)
    first_ts = now_ms - (days + 3) * DAY_MS
    last_ts = now_ms
    try:
        arts = fetch_news_window_for_code(code, name, first_ts, last_ts, market, use_llm)
    except Exception:
        arts = []
    # event_* 라벨만 원인 후보 (LLM 분류). LLM 없으면 substantive bull/bear.
    candidates = [a for a in arts
                  if (a.get('llm_label') in ('event_bull', 'event_bear'))
                  or (not a.get('llm_label') and a.get('substance') == 'substantive'
                      and a.get('sentiment') in ('bull', 'bear'))]

    explained = partial = unexplained = 0
    for ev in events:
        win_start = ev['ts'] - 2 * DAY_MS   # 직전 48h
        win_end = ev['ts'] + 12 * 3600 * 1000   # 당일 장중 포함
        near = [a for a in candidates if win_start <= (a.get('ts') or 0) <= win_end]
        want = 'bull' if ev['direction'] == 'up' else 'bear'
        right = [a for a in near if a.get('sentiment') == want]
        wrong = [a for a in near if a.get('sentiment') in ('bull', 'bear') and a.get('sentiment') != want]
        ev['matched'] = [{
            'title': a.get('title'), 'ts': a.get('ts'),
            'sentiment': a.get('sentiment'), 'llm_label': a.get('llm_label'),
            'llm_reason': a.get('llm_reason'),
            'paper': a.get('paper') or a.get('source'), 'link': a.get('link'),
        } for a in (right[:3] or wrong[:2])]
        if right:
            ev['attribution'] = 'explained'
            explained += 1
        elif wrong or near:
            ev['attribution'] = 'partial'     # 뉴스는 있는데 방향 안 맞음
            partial += 1
        else:
            ev['attribution'] = 'unexplained'  # mystery move
            unexplained += 1

    n = len(events)
    return {
        'code': code, 'name': name, 'threshold': threshold, 'days': days,
        'news_fetched': len(arts), 'news_candidates': len(candidates),
        'events': sorted(events, key=lambda e: -e['ts']),
        'coverage': {
            'n_events': n,
            'explained': explained,
            'partial': partial,
            'unexplained': unexplained,
            'explained_rate': round(explained / n, 3) if n else None,
        },
    }
