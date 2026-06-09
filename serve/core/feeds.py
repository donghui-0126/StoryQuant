"""RSS 피드 파싱 + 다중 소스 통합."""
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from ..utils.http import http_get
from ..utils.parsing import decode_entities, strip_tags, parse_date
from .classify import enrich_article


def parse_rss(xml_text, source_key, market):
    """단일 RSS feed 파싱 → enriched article list. Google News 'gn_*' 매체명 분리."""
    is_gnews = source_key.startswith('gn_')
    paper_map = market.get_paper_map() if is_gnews else {}
    items = []
    for m in re.finditer(r'<item[^>]*>(.*?)</item>', xml_text, re.S):
        body = m.group(1)
        title_m = re.search(r'<title[^>]*>(.*?)</title>', body, re.S)
        link_m = re.search(r'<link[^>]*>(.*?)</link>', body, re.S)
        date_m = re.search(r'<pubDate[^>]*>(.*?)</pubDate>', body, re.S)
        desc_m = re.search(r'<description[^>]*>(.*?)</description>', body, re.S)
        if not title_m:
            continue
        title = strip_tags(decode_entities(title_m.group(1).strip()))
        link = strip_tags(decode_entities((link_m.group(1).strip() if link_m else '')))
        desc = strip_tags(decode_entities((desc_m.group(1).strip() if desc_m else '')))
        if is_gnews:
            sep = title.rfind(' - ')
            if sep > 0:
                paper_in_title = title[sep+3:].strip()
                title = title[:sep].strip()
            else:
                paper_in_title = paper_map.get(source_key, source_key)
        else:
            paper_in_title = None
        ts = parse_date(date_m.group(1).strip(), default_tz_offset_hours=market.tz_offset_hours) if date_m else int(time.time() * 1000)
        item = {
            'source': source_key,
            'paper': paper_in_title,
            'title': title,
            'description': desc,
            'link': link,
            'ts': ts,
            'tickers': market.tag_tickers(title + ' ' + desc),
        }
        items.append(enrich_article(item, market))
    return items


def fetch_news(sources, limit, market):
    """시장의 RSS feeds 중 sources 매체에서 통합 fetch + balancing.
       sources=[]면 전체 시장 feeds 사용."""
    feeds = market.get_rss_feeds()
    sources = [s for s in sources if s in feeds]
    if not sources:
        sources = list(feeds.keys())
    results = []
    errors = []

    def fetch_one(src):
        url = feeds[src]
        try:
            raw = http_get(url, timeout=8)
            text = raw.decode('utf-8', errors='replace')
            return src, parse_rss(text, src, market)
        except Exception as e:
            return src, e

    by_source = {}
    with ThreadPoolExecutor(max_workers=10) as ex:
        futs = {ex.submit(fetch_one, s): s for s in sources}
        for f in as_completed(futs):
            src, val = f.result()
            if isinstance(val, Exception):
                errors.append({'source': src, 'error': str(val)[:100]})
            else:
                val.sort(key=lambda x: -x['ts'])
                by_source[src] = val
                results.extend(val)

    if by_source and limit > 0:
        per_src = max(5, limit // max(1, len(by_source)) + 2)
        balanced = []
        for src, items in by_source.items():
            balanced.extend(items[:per_src])
        balanced.sort(key=lambda x: -x['ts'])
        trimmed = balanced[:limit]
    else:
        results.sort(key=lambda x: -x['ts'])
        trimmed = results[:limit]
    bull = sum(1 for x in trimmed if x['sentiment'] == 'bull')
    bear = sum(1 for x in trimmed if x['sentiment'] == 'bear')
    neut = sum(1 for x in trimmed if x['sentiment'] == 'neut')
    polarity = round((bull - bear) / max(1, bull + bear) * 100) if (bull + bear) > 0 else 0
    return {
        'ts': int(time.time() * 1000),
        'market': market.id,
        'stats': {
            'total': len(trimmed), 'bull': bull, 'bear': bear, 'neut': neut,
            'sources': len(sources), 'polarity': polarity,
        },
        'errors': errors,
        'articles': trimmed,
    }
