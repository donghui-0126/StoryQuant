"""뉴스 분류 + enrichment scoring (시장-적용 시점에 키워드 셋 주입).

  classify_sentiment : (text, market) → ('bull'|'bear'|'neut', score)
  classify_substance : (text, market) → 'substantive' | 'reactive' | 'neutral'
  categorize         : (text, market) → 카테고리명
  specificity_score  : 0..3 — 숫자·금액·% 카운트
  surprise_score     : 0..3 — substantive×specificity×shock 키워드
  source_reliability : 0..1 — 매체별 prior
  time_of_day_bucket : 'pre' | 'intra' | 'after' (시장 TZ 기준)
  enrich_article     : 위 모두 적용해서 article 인플레이스 변경
"""
import re
import time
from datetime import datetime, timezone, timedelta


# A1 — Specificity 정규식 (한·영 공통: 숫자 + 단위 / %, 분기 등 패턴)
_NUM_AMOUNT = re.compile(
    r'\d{1,4}(?:,\d{3})*(?:\.\d+)?\s*(?:조|억|만|천|trillion|billion|million|thousand|bn|tn|mn|m|b)\s*'
    r'(?:원|달러|엔|위안|USD|EUR|JPY|KRW|CNY)?',
    re.I,
)
_NUM_USD = re.compile(r'\$\s*\d|\d{1,4}(?:,\d{3})*(?:\.\d+)?\s*(?:USD|달러)', re.I)
_PCT = re.compile(r'\d+(?:\.\d+)?\s*%')
_QTR = re.compile(r'(?:1Q|2Q|3Q|4Q|\d+분기|\d+년\s*\d+분기|상반기|하반기|FY\d{2,4}|Q\d/\d{4}|Q[1-4]\s*\d{2,4})', re.I)
_BIG_NUM = re.compile(r'\b\d{3,}\b')


def classify_sentiment(text, market):
    """('bull'|'bear'|'neut', score). 키워드 매칭 → bull/bear ratio.
       market.bull_keys / market.bear_keys 사용."""
    if not text:
        return ('neut', 0)
    bull = sum(1 for k in market.bull_keys if k in text)
    bear = sum(1 for k in market.bear_keys if k in text)
    total = bull + bear
    if total == 0:
        return ('neut', 0)
    score = (bull - bear) / total
    if score > 0.2:
        return ('bull', round(score, 2))
    if score < -0.2:
        return ('bear', round(score, 2))
    return ('neut', round(score, 2))


def classify_substance(text, market):
    """'substantive' (실질 정보) / 'reactive' (가격 묘사만) / 'neutral'."""
    if not text:
        return 'neutral'
    has_sub = any(k in text for k in market.substantive_keys)
    has_react = any(k in text for k in market.reactive_keys)
    if has_sub:
        return 'substantive'
    if has_react:
        return 'reactive'
    return 'neutral'


def specificity_score(text):
    """0..3. 숫자·금액·% 많을수록 alpha. 시장 무관."""
    if not text:
        return 0.0
    s = 0.0
    if _NUM_AMOUNT.search(text):
        s += 1.0
    elif _NUM_USD.search(text):
        s += 0.6
    pct = len(_PCT.findall(text))
    s += min(1.0, pct * 0.5)
    if _QTR.search(text):
        s += 0.5
    big = len(_BIG_NUM.findall(text))
    s += min(0.5, big * 0.2)
    return round(min(3.0, s), 2)


def surprise_score(text, substance, specificity, market):
    """0..3. substantive + specificity 보너스 + shock 키워드 추가, routine 키워드는 감점."""
    if not text:
        return 0.0
    s = 0.0
    if substance == 'substantive':
        s += 0.5 + min(1.0, specificity * 0.3)
    big_hits = sum(1 for k in market.big_surprise_keys if k in text)
    s += min(1.5, big_hits * 0.7)
    if any(k in text for k in market.routine_keys):
        s -= 0.4
    return round(max(0.0, min(3.0, s)), 2)


def source_reliability(paper, market):
    """매체별 신뢰도 prior. 0~1. 알 수 없으면 0.50."""
    if not paper:
        return 0.50
    p = paper.strip()
    priors = market.source_priors
    if p in priors:
        return priors[p]
    pl = p.lower()
    if pl in priors:
        return priors[pl]
    for k, v in priors.items():
        if k in p:
            return v
    return 0.50


def categorize(text, market):
    """카테고리 분류 — KR='실적'/'기타', US='Earnings'/'Other'. 시장별 키워드+fallback."""
    fallback = getattr(market, 'other_category', 'Other')
    if not text:
        return fallback
    cats = market.category_keys
    for cat, keys in cats.items():
        if any(k in text for k in keys):
            return cat
    return fallback


def time_of_day_bucket(ts_ms, market):
    """시장 TZ 기준 'pre' (장 전) / 'intra' (장중) / 'after' (장 후)."""
    try:
        dt = datetime.fromtimestamp(ts_ms / 1000, tz=timezone(timedelta(hours=market.tz_offset_hours)))
        h = dt.hour + dt.minute / 60.0
        if h < market.market_open_hour:
            return 'pre'
        if h < market.market_close_hour:
            return 'intra'
        return 'after'
    except Exception:
        return 'intra'


_TOKEN_RE = re.compile(r'[A-Za-z가-힣0-9]+')

def _title_tokens(title):
    """타이틀 → 토큰 set (대소문자 무시, 길이 ≥2)."""
    if not title: return set()
    toks = [t.lower() for t in _TOKEN_RE.findall(title) if len(t) >= 2]
    # stop-words 약간 제거
    stop = {'the','a','an','of','to','for','in','on','and','is','are','was','says','said',
            '뉴스','종합','업데이트','기사','속보','뉴시스','연합뉴스','오늘','이날'}
    return set(t for t in toks if t not in stop)


def _jaccard(a, b):
    if not a or not b: return 0.0
    inter = len(a & b)
    uni = len(a | b)
    return inter / uni if uni else 0.0


def simple_dedup(articles, prefix_words=8, jaccard_thresh=0.55, time_window_h=48):
    """E2 강화 — 다단계 dedup:
       1) 타이틀 prefix 8 단어 동일 → 즉시 dedup (기존)
       2) Jaccard token 유사도 ≥ 0.55 AND 같은 종목/매체 시간 윈도우 48h 내 → dedup
       3) 같은 link → dedup
       항상 신뢰도 높은 매체 + specificity 높은 article 으로 대표 선정."""
    out = []
    out_keys = []   # parallel to out: (prefix_key, link, tokens)
    for a in articles:
        title = (a.get('title') or '').strip()
        if not title:
            continue
        link = (a.get('link') or '').strip()
        ts = a.get('ts') or 0
        prefix_key = ' '.join(title.split()[:prefix_words])[:60].lower()
        toks = _title_tokens(title)
        cur_score = (a.get('source_score') or 0.5) + (a.get('specificity') or 0) * 0.2
        match_idx = -1
        for i, (pk, lk, tk, ats) in enumerate(out_keys):
            # 빠른 체크: 같은 link 또는 같은 prefix
            if link and lk and link == lk:
                match_idx = i; break
            if pk == prefix_key:
                match_idx = i; break
            # 시간 윈도우 + Jaccard fuzzy
            if abs(ts - ats) <= time_window_h * 3600 * 1000:
                if _jaccard(toks, tk) >= jaccard_thresh:
                    match_idx = i; break
        if match_idx < 0:
            out.append(a)
            out_keys.append((prefix_key, link, toks, ts))
        else:
            old = out[match_idx]
            old_score = (old.get('source_score') or 0.5) + (old.get('specificity') or 0) * 0.2
            if cur_score > old_score:
                a = dict(a)
                a['_dup_count'] = (old.get('_dup_count') or 1) + 1
                out[match_idx] = a
                out_keys[match_idx] = (prefix_key, link, toks, ts)
            else:
                out[match_idx] = dict(old)
                out[match_idx]['_dup_count'] = (old.get('_dup_count') or 1) + 1
    return out


def annotate_priced_in(articles, bars, sentiment_threshold_pct=5.0):
    """v21.6 — 각 article 에 priced_in flag 추가.
       bars = 종목의 최근 일봉 (60d 이상). bull/bear 뉴스 직전 5d 가격 변동 측정.
       bull인데 5d +5% 이상 올랐으면 → priced_in (이미 가격에 반영, 추가 alpha 작음)
       bear인데 5d -5% 이상 떨어졌으면 → priced_in
       반환: 인플레이스 mutate, priced_in field 추가 (bool)."""
    if not bars or len(bars) < 6:
        for a in articles:
            a['priced_in'] = False
        return articles
    bar_by_day = {}
    for b in bars:
        day = b['t'] // 86400000
        bar_by_day[day] = b['c']
    sorted_days = sorted(bar_by_day.keys())
    for a in articles:
        a['priced_in'] = False
        sent = a.get('sentiment')
        if sent not in ('bull', 'bear'):
            continue
        ts = a.get('ts') or 0
        if ts <= 0:
            continue
        article_day = ts // 86400000
        # 가장 가까운 trading day (article_day 이전 또는 동일)
        nearest = None
        for d in reversed(sorted_days):
            if d <= article_day:
                nearest = d; break
        if nearest is None: continue
        # 5 trading days 전 가격
        idx = sorted_days.index(nearest)
        if idx < 5:
            continue
        prev5 = sorted_days[idx - 5]
        cur_p = bar_by_day[nearest]
        prev_p = bar_by_day[prev5]
        if prev_p <= 0: continue
        chg = (cur_p - prev_p) / prev_p * 100
        if sent == 'bull' and chg >= sentiment_threshold_pct:
            a['priced_in'] = True
            a['priced_in_5d_chg'] = round(chg, 1)
        elif sent == 'bear' and chg <= -sentiment_threshold_pct:
            a['priced_in'] = True
            a['priced_in_5d_chg'] = round(chg, 1)
    return articles


def enrich_article(art, market, use_llm=False, ctx=None):
    """article 객체에 sentiment / substance / specificity / surprise / source_score / category / tod 채움.
       use_llm=True 면 LLM (gpt-4o-mini) 분류를 sentiment/substance/scope에 우선 적용 — 룰은 fallback.
       ctx = {'name', 'code', 'sector'} — LLM에 종목 컨텍스트 전달."""
    text = (art.get('title') or '') + ' ' + (art.get('body') or art.get('description') or '')
    # 룰 분류는 항상 (LLM 실패 시 폴백)
    rule_sentiment, rule_score = classify_sentiment(text, market)
    rule_substance = classify_substance(text, market)
    sentiment, score, substance = rule_sentiment, rule_score, rule_substance
    scope = 'stock'
    llm_label = None
    llm_conf = None
    llm_reason = None
    if use_llm:
        try:
            from . import llm_classify as _llm
            if _llm.is_enabled():
                ctx = ctx or {}
                title_only = art.get('title') or ''
                res = _llm.classify_one(title_only,
                                         name=ctx.get('name'),
                                         code=ctx.get('code'),
                                         sector=ctx.get('sector'))
                lbl = res.get('label')
                conf = float(res.get('confidence') or 0.0)
                llm_label = lbl; llm_conf = conf; llm_reason = res.get('reason')
                scope = res.get('scope') or 'stock'
                if lbl == 'rule_fallback' or conf < 0.7:
                    pass    # 룰 결과 유지
                elif lbl == 'event_bull':
                    sentiment, score, substance = 'bull', round(conf, 2), 'substantive'
                elif lbl == 'event_bear':
                    sentiment, score, substance = 'bear', -round(conf, 2), 'substantive'
                elif lbl == 'reactive':
                    sentiment, score, substance = 'neut', 0.0, 'reactive'
                elif lbl in ('speculative', 'off_topic'):
                    sentiment, score, substance = 'neut', 0.0, 'neutral'
        except Exception:
            pass
    spec = specificity_score(text)
    art['sentiment'] = sentiment
    art['score'] = score
    art['substance'] = substance
    art['scope'] = scope
    if llm_label is not None:
        art['llm_label'] = llm_label
        art['llm_confidence'] = llm_conf
        art['llm_reason'] = llm_reason
    art['specificity'] = spec
    art['surprise'] = surprise_score(text, substance, spec, market)
    art['source_score'] = source_reliability(art.get('paper') or art.get('source') or '', market)
    art['category'] = categorize(text, market)
    art['tod'] = time_of_day_bucket(art.get('ts') or int(time.time() * 1000), market)
    return art
