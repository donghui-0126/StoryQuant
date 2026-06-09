"""Yahoo Finance 가격/차트 fetch — 시장 무관 (어댑터의 yahoo_symbol_candidates 사용)."""
import json
import urllib.parse

from ..utils.http import http_get


def fetch_stock_chart(code, range_, market):
    """Yahoo Finance daily candles. 어댑터의 yahoo_symbol_candidates 순회 → 첫 성공.
       반환: {code, symbol, last, currency, bars: [{t,c,v}]} 또는 {code, error, bars:[]}"""
    candidates = market.yahoo_symbol_candidates(code)
    for sym in candidates:
        url = f'https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(sym)}?interval=1d&range={range_}'
        try:
            raw = http_get(url, timeout=8)
            j = json.loads(raw)
            result = j.get('chart', {}).get('result', [None])[0]
            if not result:
                continue
            meta = result.get('meta', {})
            ts_arr = result.get('timestamp', []) or []
            q = (result.get('indicators', {}).get('quote', [{}])[0]) if result.get('indicators') else {}
            bars = []
            n = len(ts_arr)
            opens = q.get('open',  [None] * n)
            highs = q.get('high',  [None] * n)
            lows  = q.get('low',   [None] * n)
            closes = q.get('close', [None] * n)
            vols  = q.get('volume',[None] * n)
            for i, t in enumerate(ts_arr):
                c = closes[i]
                if c is None:
                    continue
                bars.append({'t': t * 1000, 'o': opens[i], 'h': highs[i], 'l': lows[i], 'c': c, 'v': vols[i]})
            return {
                'code': code, 'symbol': sym,
                'last': meta.get('regularMarketPrice'),
                'currency': meta.get('currency', market.currency),
                'bars': bars,
            }
        except Exception:
            continue
    return {'code': code, 'error': 'no_data', 'bars': []}


def fetch_quote(codes, interval, range_, market):
    """Yahoo v8 chart 분봉 프록시 — 다중 종목 batch."""
    from concurrent.futures import ThreadPoolExecutor, as_completed
    import time

    def fetch_one(code):
        candidates = market.yahoo_symbol_candidates(code)
        for sym in candidates:
            url = f'https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(sym)}?interval={interval}&range={range_}'
            try:
                raw = http_get(url, timeout=6)
                j = json.loads(raw)
                result = j.get('chart', {}).get('result', [None])[0]
                if not result:
                    continue
                meta = result.get('meta', {})
                ts_arr = result.get('timestamp', []) or []
                q = (result.get('indicators', {}).get('quote', [{}])[0]) if result.get('indicators') else {}
                bars = []
                for i, t in enumerate(ts_arr):
                    c = q.get('close', [None] * len(ts_arr))[i]
                    if c is None:
                        continue
                    bars.append({'t': t * 1000, 'c': c, 'v': q.get('volume', [None] * len(ts_arr))[i]})
                return {
                    'code': code, 'symbol': sym,
                    'last': meta.get('regularMarketPrice'),
                    'prev': meta.get('chartPreviousClose'),
                    'currency': meta.get('currency', market.currency),
                    'bars': bars,
                }
            except Exception:
                continue
        return {'code': code, 'error': 'no_data', 'bars': []}

    out = {}
    with ThreadPoolExecutor(max_workers=10) as ex:
        futs = {ex.submit(fetch_one, c): c for c in codes}
        for f in as_completed(futs):
            r = f.result()
            out[r['code']] = r
    return {'ts': int(time.time() * 1000), 'market': market.id, 'quotes': out}
