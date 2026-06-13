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


# ═══════════════════════════════════════════════════════════
#  뉴스별 한줄평 — 실질 사건(event_*)에만 생성. 분류 캐시와 분리.
# ═══════════════════════════════════════════════════════════
COMMENT_PROMPT = """당신은 한국 증권가의 베테랑 애널리스트입니다. 기사 하나를 읽고
개인 투자자가 "아 그래서 이게 중요하구나"를 깨닫게 하는 한 문장을 씁니다.

핵심 원칙 — 헤드라인을 반복하지 말고, 헤드라인에 '없는' 통찰 하나를 더하세요:
- 숫자의 의미: 계약·실적 금액이 그 회사 규모에서 큰가 작은가, 무엇과 비교되는가
- 진짜 수혜 경로: 이 사건이 매출/이익에 닿는 구체적 경로 (또는 안 닿는 이유)
- 숨은 맥락: 업황 사이클 위치, 경쟁 구도, 일회성인지 반복인지, 이미 알려진 건지
- 흔한 오해: 투자자가 이 뉴스를 과대/과소평가하기 쉬운 지점

절대 금지:
- 양비론 구조 금지: "A이나/하나/지만 B우려", "긍정적이나 ~", "기대되나 ~"처럼
  좋은 점 하나 + 나쁜 점 하나로 균형 맞추는 문장. 한쪽으로 단정하세요.
- 면피성 마무리 금지: "확인 필요", "지켜봐야", "주목된다", "기대된다"
- 헤드라인 동어반복 금지 ("수주는 수주 증가를 의미" 류)
- 매수·매도 권유, 주가 방향 예측 금지
- 정말 더할 통찰이 없으면 빈 문자열 "" 반환 (억지로 채우지 말 것)

방법: 헤드라인이 못 말해주는 가장 중요한 사실 '하나'만 골라 단정적으로.

숫자 관련 — 매우 중요:
- 본문/헤드라인에 '명시된' 숫자만 인용. 본문에 "매출의 30%"라고 적혀 있으면 OK.
- 회사 연매출·시총을 당신이 추정해 비율("연매출의 24%")을 계산하지 말 것.
  실제 수치를 모르면서 지어낸 정밀한 비율은 거짓 정보임. 절대 금지.
- 비교가 필요하면 본문 근거 없이는 "단일 계약치곤 큰 규모" 같은 정성적 표현만.

형식: 한국어 한 문장, 45자 내외, 단정적 평어체(~임/~음/명사형). '하나'에 집중.

좋은 예 (한쪽으로 단정, 통찰 하나):
- "A사, 1883억 LNG 발전설비 수주" → {"comment":"연매출 맞먹는 단일 수주지만 발전설비라 인도까지 2~3년 분할 인식"}
- "B사 1분기 영업익 14% 증가" → {"comment":"반도체 바닥 통과 구간이라 전년 기저효과 비중이 큰 증가율"}
- "C사 코스닥150 지수 편입" → {"comment":"패시브 자금 기계적 유입일 뿐 펀더멘털 변화는 아님"}
- "D사 HBM 장비 빅3 납품" → {"comment":"HBM 후공정 장비는 고객 다변화가 핵심 — 빅3 동시 진입은 의미 큼"}
- 통찰 없는 홍보성 → {"comment":""}

출력: JSON 한 줄만 {"comment":"..."}"""

# 면피·양비론·동어반복 마커 — 포함 시 한줄평 폐기 (없느니만 못한 코멘트 제거)
_HEDGE_MARKERS = ('확인 필요', '지켜봐야', '주목', '귀추', '관심이 필요',
                  '신중', '유의', '필요해 보', '될 전망', '기대됨', '기대된다',
                  '기대되나', '기대되지만', '긍정적이나', '긍정적이지만',
                  '우려가 존재', '우려도 있', '주의 필요', '주의가 필요')


import re as _re
# 매출/시총 대비 비율 — LLM이 실제 수치를 모르면서 계산한 거짓 정밀도일 위험 → 폐기
_FAKE_RATIO = _re.compile(r'(연?매출|시총|시가총액)\D{0,6}\d')


def _comment_useful(comment, title, body=None):
    """면피·양비론·지어낸 비율 한줄평이면 False. (없느니만 못한 코멘트 게이트)"""
    if not comment or len(comment) < 10:
        return False
    if any(m in comment for m in _HEDGE_MARKERS):
        return False
    # '연매출의 24%' 류 — 본문에 같은 표현이 없으면 LLM이 지어낸 비율로 간주
    m = _FAKE_RATIO.search(comment)
    if m and (not body or '매출' not in (body or '')):
        return False
    return True


def comment_one(title, name=None, sector=None, label=None, body=None, model='gpt-4o-mini'):
    """기사 한 건 한줄평. 본문(body) 있으면 함께 투입. 'c5_' 캐시 (프롬프트 v2)."""
    if not title or not (title or '').strip():
        return None
    key = 'c5_' + _cache_key(title, name, sector)
    cached = _load_cached(key)
    if cached:
        _STATS['hit'] += 1
        return cached.get('comment') or None
    client = _get_client()
    if client is None:
        return None
    sent = '(호재 분류)' if label == 'event_bull' else ('(악재 분류)' if label == 'event_bear' else '')
    sec = f' / 섹터: {sector}' if sector else ''
    body_str = f'\n본문 일부: "{(body or "")[:200]}"' if body else ''
    try:
        rsp = client.chat.completions.create(
            model=model,
            messages=[
                {'role': 'system', 'content': COMMENT_PROMPT},
                {'role': 'user', 'content': f'종목: {name or "?"}{sec} {sent}\n헤드라인: "{title}"{body_str}'},
            ],
            temperature=0.3,
            max_tokens=120,
            response_format={'type': 'json_object'},
        )
        data = json.loads(rsp.choices[0].message.content or '{}')
        comment = (data.get('comment') or '').strip()[:90]
        if not _comment_useful(comment, title, body):
            comment = ''     # 면피·지어낸 비율이면 캐시엔 빈값 저장 → UI엔 미표시
        _save_cached(key, {'comment': comment})
        _STATS['miss'] += 1
        usage = getattr(rsp, 'usage', None)
        if usage:
            _STATS['cost_usd'] += usage.prompt_tokens * 0.15/1e6 + usage.completion_tokens * 0.60/1e6
        return comment or None
    except Exception:
        _STATS['err'] += 1
        return None


def comment_batch(items, max_workers=6):
    """items = [{'title','name','sector','label','body'}] → [comment|None]."""
    results = [None] * len(items)
    pending = []
    for i, it in enumerate(items):
        key = 'c5_' + _cache_key(it.get('title'), it.get('name'), it.get('sector'))
        cached = _load_cached(key)
        if cached:
            _STATS['hit'] += 1
            results[i] = cached.get('comment') or None
        else:
            pending.append(i)
    if not pending:
        return results
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futs = {ex.submit(comment_one, items[i].get('title'), items[i].get('name'),
                          items[i].get('sector'), items[i].get('label'), items[i].get('body')): i
                for i in pending}
        for f in futs:
            try:
                results[futs[f]] = f.result()
            except Exception:
                results[futs[f]] = None
    return results
