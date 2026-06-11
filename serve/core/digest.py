"""저장 종목 다이제스트 — 새 실질 사건 뉴스 + 큰 변동 감지.

알림 피로 방지: 트리거는 두 가지뿐.
  ① 최근 N일 내 실질 사건 뉴스 (event_bull/bear, 미반영)
  ② 직전 거래일 시장 대비 ±2.5% 이상 변동
"""
import time
from concurrent.futures import ThreadPoolExecutor
from .news import fetch_stock_news
from .quote import fetch_stock_chart

DAY_MS = 86400000
MOVE_THRESHOLD = 2.5


def _one(code, market, days):
    uni = market.universe()
    base = code.split('.')[0]
    name = ((uni.get(code) or uni.get(base) or {}).get('name')) or base
    out = {'code': code, 'name': name, 'events': [], 'big_move': None}
    try:
        news = fetch_stock_news(code, page=1, page_size=20, market=market, use_llm=True)
        cutoff = int(time.time() * 1000) - days * DAY_MS
        for a in news.get('articles', []):
            if (a.get('substance') == 'substantive' and not a.get('priced_in')
                    and a.get('sentiment') in ('bull', 'bear')
                    and (a.get('ts') or 0) >= cutoff):
                out['events'].append({
                    'title': a.get('title'), 'ts': a.get('ts'),
                    'sentiment': a.get('sentiment'),
                    'paper': a.get('paper') or a.get('source'),
                    'link': a.get('link'),
                    'comment': a.get('llm_comment'),
                })
        out['events'].sort(key=lambda e: -(e['ts'] or 0))
        out['events'] = out['events'][:5]
    except Exception:
        pass
    try:
        chart = fetch_stock_chart(code, '1mo', market)
        bars = chart.get('bars', [])
        bench = fetch_stock_chart(market.benchmark_symbol, '1mo', market)
        bench_by_day = {b['t'] // DAY_MS: b['c'] for b in bench.get('bars', [])}
        if len(bars) >= 2:
            cur, prev = bars[-1], bars[-2]
            if cur.get('c') and prev.get('c'):
                ret = (cur['c'] / prev['c'] - 1) * 100
                b_cur = bench_by_day.get(cur['t'] // DAY_MS)
                b_prev = bench_by_day.get(prev['t'] // DAY_MS)
                bench_ret = ((b_cur / b_prev - 1) * 100) if (b_cur and b_prev) else 0.0
                rel = ret - bench_ret
                if abs(rel) >= MOVE_THRESHOLD:
                    out['big_move'] = {
                        'date': time.strftime('%m/%d', time.localtime(cur['t'] / 1000)),
                        'ts': cur['t'],
                        'abs_pct': round(ret, 2),
                        'rel_pct': round(rel, 2),
                        'has_news': len(out['events']) > 0,
                    }
    except Exception:
        pass
    return out


def saved_digest(codes, market, days=3):
    """저장 종목들의 새 소식 일괄 조회. codes 최대 30개."""
    codes = [c for c in codes if c][:30]
    items = []
    if codes:
        with ThreadPoolExecutor(max_workers=6) as ex:
            for r in ex.map(lambda c: _one(c, market, days), codes):
                items.append(r)
    return {'ts': int(time.time() * 1000), 'days': days,
            'threshold': MOVE_THRESHOLD, 'items': items}
