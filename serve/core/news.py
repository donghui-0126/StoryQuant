"""종목별 뉴스 — native API + Google News historical fallback."""
import re
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta

from ..utils.http import http_get
from ..utils.parsing import decode_entities, parse_date
from .classify import enrich_article, simple_dedup, annotate_priced_in


def fetch_stock_news(code, page, page_size, market, use_llm=False):
    """시장 native API → 룰 enrich → (옵션) LLM batch override → dedup → priced_in."""
    try:
        articles = market.fetch_stock_news_native(code, page=page, page_size=page_size)
    except Exception as e:
        return {'code': code, 'error': str(e)[:80], 'articles': []}
    info = market.universe().get(code, {})
    name = info.get('name') or code
    sector = market.sector_map.get(code)
    enriched = [enrich_article(dict(a), market) for a in articles]    # 룰만 (fast)
    if use_llm and enriched:
        try:
            from . import llm_classify as _llm
            if _llm.is_enabled():
                batch_items = [{'title': a.get('title') or '', 'name': name,
                                 'code': code, 'sector': sector} for a in enriched]
                llm_results = _llm.classify_batch(batch_items, max_workers=8)
                for a, res in zip(enriched, llm_results):
                    if not res or res.get('label') == 'rule_fallback':
                        continue
                    lbl = res.get('label')
                    conf = float(res.get('confidence') or 0.0)
                    a['llm_label'] = lbl
                    a['llm_confidence'] = conf
                    a['llm_reason'] = res.get('reason')
                    a['scope'] = res.get('scope') or 'stock'
                    # event_* 는 conf>=0.7 일 때만 점수 반영 (호악재 오판 방지).
                    # 중립화 라벨은 conf 무관 적용 — LLM이 확신해도 conf 0.0 을
                    # 주는 사례가 있어, 게이트에 걸리면 룰의 substantive 가
                    # 살아남아 무관 기사가 호재로 집계되는 버그가 있었음.
                    if lbl == 'event_bull' and conf >= 0.7:
                        a['sentiment'], a['score'], a['substance'] = 'bull', round(conf, 2), 'substantive'
                    elif lbl == 'event_bear' and conf >= 0.7:
                        a['sentiment'], a['score'], a['substance'] = 'bear', -round(conf, 2), 'substantive'
                    elif lbl == 'reactive':
                        a['sentiment'], a['score'], a['substance'] = 'neut', 0.0, 'reactive'
                    elif lbl in ('speculative', 'off_topic'):
                        a['sentiment'], a['score'], a['substance'] = 'neut', 0.0, 'neutral'
                    elif lbl in ('event_bull', 'event_bear'):
                        # 저신뢰 event — 방향 점수는 주지 않되 호재 집계에서도 제외
                        a['sentiment'], a['score'], a['substance'] = 'neut', 0.0, 'neutral'
        except Exception:
            pass
    enriched = simple_dedup(enriched)
    # v21.6 — priced_in: 종목 차트 fetch (3mo) 후 annotate
    try:
        from .quote import fetch_stock_chart
        chart = fetch_stock_chart(code, '3mo', market)
        bars = chart.get('bars', [])
        if bars:
            annotate_priced_in(enriched, bars)
    except Exception:
        pass
    return {'code': code, 'page': page, 'articles': enriched, 'total': len(enriched)}


def fetch_historical_news(query, start_date, end_date, market):
    """Google News date-range 검색. start/end_date = 'YYYY-MM-DD' string."""
    q = f'{query} after:{start_date} before:{end_date}'
    # 시장 locale 따라 Google News 도메인 / hl 파라미터
    if market.locale.startswith('ko'):
        suffix = '&hl=ko&gl=KR&ceid=KR:ko'
    elif market.locale.startswith('en'):
        suffix = '&hl=en-US&gl=US&ceid=US:en'
    else:
        suffix = ''
    url = 'https://news.google.com/rss/search?q=' + urllib.parse.quote(q) + suffix
    try:
        raw = http_get(url, timeout=10)
        xml = raw.decode('utf-8', errors='replace')
    except Exception:
        return []
    items = []
    for m in re.finditer(r'<item>(.*?)</item>', xml, re.S):
        body = m.group(1)
        title_m = re.search(r'<title[^>]*>(.*?)</title>', body, re.S)
        date_m = re.search(r'<pubDate[^>]*>(.*?)</pubDate>', body, re.S)
        link_m = re.search(r'<link[^>]*>(.*?)</link>', body, re.S)
        if not title_m:
            continue
        title = decode_entities(title_m.group(1).strip())
        sep = title.rfind(' - ')
        paper = title[sep+3:].strip() if sep > 0 else 'GNews'
        title = title[:sep].strip() if sep > 0 else title
        ts = parse_date(date_m.group(1).strip(), default_tz_offset_hours=market.tz_offset_hours) if date_m else 0
        item = {
            'title': title, 'paper': paper, 'ts': ts,
            'link': link_m.group(1).strip() if link_m else '',
        }
        items.append(enrich_article(item, market))
    return items


# Process-level cache for historical news (24h memory + disk persistence)
import os
import json as _json
_HIST_NEWS_CACHE = {}
_HIST_NEWS_CACHE_DIR = '/tmp/sq_news_cache'

def _load_disk_cache():
    """서버 재시작 시 disk 캐시 hot-load."""
    try:
        os.makedirs(_HIST_NEWS_CACHE_DIR, exist_ok=True)
        loaded = 0
        for fn in os.listdir(_HIST_NEWS_CACHE_DIR):
            if not fn.endswith('.json'): continue
            try:
                with open(os.path.join(_HIST_NEWS_CACHE_DIR, fn)) as f:
                    obj = _json.load(f)
                key = tuple(obj['key'])
                ts = obj['ts']
                if (time.time() - ts) < 86400 * 7:    # 7일 disk TTL
                    _HIST_NEWS_CACHE[key] = (ts, obj['data'])
                    loaded += 1
            except Exception:
                continue
        if loaded:
            print(f'[NewsCache] disk: loaded {loaded} cached windows')
    except Exception:
        pass

_load_disk_cache()


def _save_disk_cache(key, ts, data):
    try:
        # filename = sha-like from key
        import hashlib
        h = hashlib.md5(_json.dumps(key, ensure_ascii=False).encode()).hexdigest()[:16]
        path = os.path.join(_HIST_NEWS_CACHE_DIR, f'{h}.json')
        with open(path, 'w') as f:
            _json.dump({'key': list(key), 'ts': ts, 'data': data}, f, ensure_ascii=False)
    except Exception:
        pass


def fetch_news_window_for_code(code, name, start_ts, end_ts, market, use_llm=False):
    """주어진 시간 범위의 종목 historical 뉴스. 14d chunks. 24h 캐시 + 7d disk.
       use_llm=True 시 enriched 후 LLM 분류로 sentiment/substance/scope 재라벨링 (batch parallel)."""
    start_d = datetime.fromtimestamp(start_ts / 1000).date()
    end_d = datetime.fromtimestamp(end_ts / 1000).date()
    mode_tag = 'llm' if use_llm else 'rule'
    cache_key = (market.id, name, start_d.isoformat(), end_d.isoformat(), mode_tag)
    now = time.time()
    window_days = max(1, (end_d - start_d).days)
    cached = _HIST_NEWS_CACHE.get(cache_key)
    # 정확 키 hit — 단 장기간인데 데이터가 비정상적으로 적으면 (rate-limit 오염 의심)
    # 신뢰하지 않고 fuzzy / 재fetch 로 진행
    healthy = lambda data: len(data) >= 5 or window_days <= 7
    if cached and (now - cached[0]) < 86400 and healthy(cached[1]):
        return cached[1]
    # fuzzy 캐시 — 같은 종목의 다른 범위 캐시가 요청 범위를 커버하면 재사용
    fuzzy_start = (start_d + timedelta(days=2)).isoformat()
    fuzzy_end = (end_d - timedelta(days=2)).isoformat()
    best_fuzzy = None
    for k, (ts_c, data_c) in list(_HIST_NEWS_CACHE.items()):
        if (len(k) >= 5 and k[0] == market.id and k[1] == name and k[4] == mode_tag
                and k[2] <= fuzzy_start and k[3] >= fuzzy_end
                and (now - ts_c) < 86400 * 3 and len(data_c) >= 5):
            if best_fuzzy is None or len(data_c) > len(best_fuzzy):
                best_fuzzy = data_c
    if best_fuzzy is not None:
        return best_fuzzy
    all_items = []
    chunk = timedelta(days=14)
    cur = start_d
    while cur < end_d:
        nxt = min(cur + chunk, end_d)
        items = fetch_historical_news(name, cur.isoformat(), nxt.isoformat(), market)
        all_items.extend(items)
        cur = nxt
    seen = set()
    out = []
    for it in all_items:
        k = (it['title'][:40], it['ts'] // 86400000)
        if k in seen:
            continue
        seen.add(k)
        out.append(it)
    out.sort(key=lambda x: x['ts'])
    # use_llm 이면 LLM batch parallel 로 sentiment/substance/scope override
    # (기본 룰 enrich는 fetch_historical_news 안에서 이미 적용됨)
    try:
        from . import llm_classify as _llm
        sec = market.sector_map.get(code)
        if use_llm and _llm.is_enabled() and out:
            batch_items = [{'title': o.get('title') or '', 'name': name,
                            'code': code, 'sector': sec} for o in out]
            llm_results = _llm.classify_batch(batch_items, max_workers=8)
            for o, res in zip(out, llm_results):
                if not res or res.get('label') == 'rule_fallback':
                    continue
                lbl = res.get('label')
                conf = float(res.get('confidence') or 0.0)
                o['llm_label'] = lbl
                o['llm_confidence'] = conf
                o['llm_reason'] = res.get('reason')
                o['scope'] = res.get('scope') or 'stock'
                # event_* 만 conf 게이트 — 중립화 라벨은 conf 무관 적용 (위 fetch_stock_news 와 동일)
                if lbl == 'event_bull' and conf >= 0.7:
                    o['sentiment'], o['score'], o['substance'] = 'bull', round(conf, 2), 'substantive'
                elif lbl == 'event_bear' and conf >= 0.7:
                    o['sentiment'], o['score'], o['substance'] = 'bear', -round(conf, 2), 'substantive'
                elif lbl == 'reactive':
                    o['sentiment'], o['score'], o['substance'] = 'neut', 0.0, 'reactive'
                elif lbl in ('speculative', 'off_topic'):
                    o['sentiment'], o['score'], o['substance'] = 'neut', 0.0, 'neutral'
                elif lbl in ('event_bull', 'event_bear'):
                    o['sentiment'], o['score'], o['substance'] = 'neut', 0.0, 'neutral'
    except Exception:
        pass
    # rate-limit 오염 방지 — 장기간 요청인데 결과가 비정상적으로 적으면 캐시 저장 skip
    # (Google News 429 시 빈 결과가 정상 캐시를 덮어쓰는 사고 방지)
    if len(out) >= 5 or window_days <= 7:
        _HIST_NEWS_CACHE[cache_key] = (now, out)
        _save_disk_cache(cache_key, now, out)   # v21.4 — disk persistence
    if len(_HIST_NEWS_CACHE) > 5000:
        oldest = min(_HIST_NEWS_CACHE.items(), key=lambda kv: kv[1][0])
        _HIST_NEWS_CACHE.pop(oldest[0])
    return out
