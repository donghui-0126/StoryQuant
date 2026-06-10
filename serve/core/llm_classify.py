"""gpt-4o-mini 기반 한국 뉴스 헤드라인 분류기.

목적: 키워드 룰의 reverse-causality 오류 (가격 묘사 → 호악재 라벨) 제거.
출력: event_bull / event_bear / reactive / speculative / off_topic
      + scope (stock / sector / macro) — 섹터 단위 신호 분리.
"""
import json
import hashlib
import os
import threading
from concurrent.futures import ThreadPoolExecutor

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), '..', '..', '.env'))
except ImportError:
    pass

_CACHE_DIR = os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'llm_cache')
os.makedirs(_CACHE_DIR, exist_ok=True)
_MEM_CACHE = {}
_MEM_LOCK = threading.Lock()
_CLIENT = None
_CLIENT_LOCK = threading.Lock()

# 통계
_STATS = {'hit': 0, 'miss': 0, 'err': 0, 'cost_usd': 0.0}


def _get_client():
    global _CLIENT
    if _CLIENT is not None:
        return _CLIENT
    with _CLIENT_LOCK:
        if _CLIENT is not None:
            return _CLIENT
        api_key = os.environ.get('OPENAI_API_KEY')
        if not api_key:
            return None
        try:
            from openai import OpenAI
            _CLIENT = OpenAI(api_key=api_key, timeout=20)
        except Exception:
            _CLIENT = None
    return _CLIENT


def is_enabled():
    return _get_client() is not None


def _cache_key(title, name, sector):
    raw = f'{(title or "").strip()}|{name or ""}|{sector or ""}'
    return hashlib.sha1(raw.encode('utf-8')).hexdigest()[:20]


def _load_cached(key):
    with _MEM_LOCK:
        if key in _MEM_CACHE:
            return _MEM_CACHE[key]
    path = os.path.join(_CACHE_DIR, f'{key}.json')
    if not os.path.exists(path):
        return None
    try:
        with open(path) as f:
            data = json.load(f)
        with _MEM_LOCK:
            _MEM_CACHE[key] = data
        return data
    except Exception:
        return None


def _save_cached(key, data):
    with _MEM_LOCK:
        _MEM_CACHE[key] = data
    try:
        path = os.path.join(_CACHE_DIR, f'{key}.json')
        tmp = path + '.tmp'
        with open(tmp, 'w') as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp, path)
    except Exception:
        pass


SYSTEM_PROMPT = """당신은 한국 증시 뉴스 분류기입니다. 한 헤드라인이 특정 종목/섹터에 대해
펀더멘털을 바꾸는 새로운 사실 정보(event)인지, 가격 묘사·추측·논평인지 엄격하게 분류합니다.

분류 라벨:
- event_bull   : 새로운 사실로 인해 종목/섹터에 +영향 (수주, 흑자전환, 신규승인, 인수, 신제품 출시, 목표가 상향, 실적 상회, 규제 완화, 정책 수혜)
- event_bear   : 새로운 사실로 인해 종목/섹터에 -영향 (적자전환, 리콜, 압수수색, 규제 강화, 실적 미스, 소송, 인사 문제, 가이던스 하향)
- reactive     : 이미 일어난 가격·거래 변동을 묘사 ("급등", "급락", "외국인 순매수", "신고가 돌파", "5% 강세", "거래량 폭증", 주가 차트 분석)
- speculative  : 의견·전망·추측·기대·논평 (사실 X — "AI 시대 수혜 기대", "전문가 추천", "투자 매력", 칼럼, 분석가 인터뷰)
- off_topic    : 종목/섹터와 직접 관계 없는 일반 기사 (인물 칼럼, 거시 일반론, 사회 이슈)

scope (영향 범위):
- stock : 특정 종목 자체 사건
- sector : 업종 전반 영향 (예: "반도체 업황 회복", "철강 관세 부과", "전기차 보조금 확대")
- macro : 거시·시장 전반 (예: "코스피 2700 돌파", "원/달러 환율 급변동", "Fed 금리 인상")

규칙:
1. "급락", "급등", "신고가", "강세" 같은 가격 묘사가 헤드라인 핵심이면 → reactive (label=event_* 아님)
2. "수혜 기대", "관심 종목", "전망" 등 의견·전망이 핵심이면 → speculative
3. 헤드라인 주체가 다른 회사인데 우리 종목명이 부수적으로 나오면 → off_topic
4. 사건이 분명하지만 호악재 방향이 진짜 애매하면 → confidence 낮춤
5. confidence는 0.0~1.0. 0.7 이상이어야 점수 반영됨
6. ⚠ 기업 보도자료 재가공 기사 — 신제품 소개, MOU·업무협약, 수상, 캠페인, CSR,
   기념행사, 브랜드 홍보, 단순 출시 알림 등 주가에 유의미한 영향이 불확실한 것 →
   event_bull 이 아니라 speculative. event_bull 은 매출·계약금액·승인 등
   재무적 영향이 구체적인 사건에만 부여하세요. (한국 뉴스는 보도자료 기반 호재가
   과잉 생산되므로 event_bull 기준을 엄격하게.)

출력: 다음 JSON 한 줄만, 다른 텍스트 금지:
{"label":"event_bull|event_bear|reactive|speculative|off_topic","scope":"stock|sector|macro","confidence":0.0-1.0,"reason":"한 줄 한국어 근거"}"""


def _user_msg(title, name, code, sector):
    sec = f' / 섹터: {sector}' if sector else ''
    code_str = f' ({code})' if code else ''
    return f'종목: {name}{code_str}{sec}\n헤드라인: "{title}"'


def classify_one(title, name=None, code=None, sector=None, model='gpt-4o-mini'):
    """단건 분류. 캐시 hit 시 즉시 반환. fallback 시 'rule_fallback' 라벨."""
    if not title or not (title or '').strip():
        return _fallback_result('empty_title')
    key = _cache_key(title, name, sector)
    cached = _load_cached(key)
    if cached:
        _STATS['hit'] += 1
        return cached
    client = _get_client()
    if client is None:
        return _fallback_result('no_api_key')
    try:
        rsp = client.chat.completions.create(
            model=model,
            messages=[
                {'role': 'system', 'content': SYSTEM_PROMPT},
                {'role': 'user', 'content': _user_msg(title, name, code, sector)},
            ],
            temperature=0.0,
            max_tokens=120,
            response_format={'type': 'json_object'},
        )
        raw = rsp.choices[0].message.content or ''
        data = json.loads(raw)
        if data.get('label') not in ('event_bull', 'event_bear', 'reactive', 'speculative', 'off_topic'):
            return _fallback_result('bad_label')
        if data.get('scope') not in ('stock', 'sector', 'macro'):
            data['scope'] = 'stock'
        try:
            data['confidence'] = float(data.get('confidence', 0.0))
        except Exception:
            data['confidence'] = 0.5
        data['source'] = 'llm'
        _save_cached(key, data)
        _STATS['miss'] += 1
        # 비용 추정 (gpt-4o-mini: $0.15/M input, $0.60/M output)
        usage = getattr(rsp, 'usage', None)
        if usage:
            _STATS['cost_usd'] += usage.prompt_tokens * 0.15/1e6 + usage.completion_tokens * 0.60/1e6
        return data
    except Exception as e:
        _STATS['err'] += 1
        return _fallback_result(f'err:{type(e).__name__}')


def _fallback_result(reason):
    return {'label': 'rule_fallback', 'scope': 'stock',
            'confidence': 0.0, 'reason': reason, 'source': 'fallback'}


def classify_batch(items, max_workers=8):
    """items = [{'title':..., 'name':..., 'code':..., 'sector':...}, ...]
       parallel ThreadPoolExecutor. 같은 캐시 키는 한 번만 호출."""
    results = [None] * len(items)
    # 캐시 hit 분리
    pending_idx = []
    for i, it in enumerate(items):
        key = _cache_key(it.get('title'), it.get('name'), it.get('sector'))
        cached = _load_cached(key)
        if cached:
            _STATS['hit'] += 1
            results[i] = cached
        else:
            pending_idx.append(i)
    if not pending_idx:
        return results
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        fut_map = {}
        for i in pending_idx:
            it = items[i]
            fut_map[ex.submit(classify_one,
                              it.get('title'), it.get('name'),
                              it.get('code'), it.get('sector'))] = i
        for fut in fut_map:
            i = fut_map[fut]
            try:
                results[i] = fut.result()
            except Exception as e:
                results[i] = _fallback_result(f'parallel_err:{type(e).__name__}')
    return results


def stats():
    return dict(_STATS)
