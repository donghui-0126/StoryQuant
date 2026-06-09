"""거시·지정학 분석 — risk regime 판단 + 종목별 macro beta.

  classify_macro_event(text, market) : str
    headline → 'war' / 'sanctions' / 'rate_hike' / 'oil_spike' / 'cpi_hot' / ...
    또는 None (거시 아님)

  compute_macro_stress(articles, vix_chg_pct, oil_chg_pct, market) : dict
    {
      'regime': 'risk_off' | 'risk_on' | 'oil_up' | 'rate_up' | 'neutral',
      'macro_polarity': -100..+100,
      'stress_score': 0..100,
      'recent_events': [{title, paper, ts, event_type, sentiment}],
      'event_counts': {event_type: count},
    }

  compute_macro_beta(charts, vix_bars, oil_bars) : {code: {beta_vix, beta_oil, r2}}
    각 종목 일일 수익률 ~ ΔVIX + ΔOil regression.

  apply_macro_adjustment(score, code, regime, market) : float
    score formula에 ±α 보너스 적용 (sector × regime → impact factor).
"""
import math
import re


# ─── Event 분류 키워드 ─────────────────────────────────────────
_EVENT_PATTERNS = (
    # (event_type, default_sentiment, [keywords KR + EN])
    ('war',         'bear',  ('전쟁', '침공', '공습', '미사일', 'war', 'invasion', 'airstrike', 'missile',
                              'ukraine', 'russia', 'israel', 'iran', 'hamas', 'taiwan strait', '북한 도발')),
    ('sanctions',   'bear',  ('제재', '봉쇄', '관세', '무역전쟁', '수출통제', 'sanctions', 'embargo',
                              'tariff', 'trade war', 'export control', 'decoupling')),
    ('rate_hike',   'bear',  ('금리 인상', '기준금리 인상', 'rate hike', 'hawkish', '매파',
                              'tighten', 'tightening')),
    ('rate_cut',    'bull',  ('금리 인하', 'rate cut', 'dovish', '비둘기파', 'easing', '완화')),
    ('cpi_hot',     'bear',  ('CPI 쇼크', 'inflation surge', 'hot inflation', 'cpi above', '인플레 가속')),
    ('cpi_cool',    'bull',  ('CPI 둔화', 'inflation cool', 'disinflation', '인플레 둔화')),
    ('oil_spike',   'bear',  ('유가 급등', 'oil surge', 'crude oil rally', 'opec cut', '감산',
                              '브렌트유 급등', 'WTI 급등')),
    ('oil_drop',    'bull',  ('유가 급락', 'oil drop', 'opec increase', '증산')),
    ('recession',   'bear',  ('경기침체', '리세션', 'recession', 'gdp contract', '성장 둔화',
                              'unemployment surge')),
    ('peace',       'bull',  ('휴전', '평화협정', 'ceasefire', 'peace deal', 'truce')),
    ('fed_speak',   'neut',  ('연준 의장', 'jerome powell', 'fomc statement', 'fed minutes',
                              '한은 총재', '한국은행 발표')),
)


def classify_macro_event(text):
    """headline → event_type 또는 None."""
    if not text:
        return None
    tl = text.lower()
    for event_type, _, keys in _EVENT_PATTERNS:
        for k in keys:
            if k.lower() in tl:
                return event_type
    return None


def macro_event_default_sentiment(event_type):
    for et, sent, _ in _EVENT_PATTERNS:
        if et == event_type:
            return sent
    return 'neut'


# ─── Stress / Regime 판단 ────────────────────────────────────
def compute_macro_stress(macro_articles, vix_now=None, vix_5d_chg=None,
                          oil_5d_chg=None, rate_5d_chg=None):
    """거시 뉴스 + 시장 변수로 regime + stress score 산정.

    macro_articles: 카테고리=거시·지정학|Macro 인 article 리스트
    vix_now/5d_chg: VIX 현재값 / 5일 변화율 (%)
    oil_5d_chg: WTI 또는 브렌트 5일 변화율 (%)
    rate_5d_chg: 10년 국채금리 5일 변화 (bp)

    반환:
      regime ∈ {risk_off, risk_on, oil_up, rate_up, neutral}
      macro_polarity ∈ -100..+100 (거시 뉴스 sentiment 통합)
      stress_score ∈ 0..100 (높을수록 위험)
    """
    # 이벤트 카운트
    event_counts = {}
    bull_news = 0; bear_news = 0
    recent_events = []
    for a in macro_articles:
        title = a.get('title') or ''
        et = classify_macro_event(title) or classify_macro_event(a.get('description', '') or '')
        sent = a.get('sentiment') or 'neut'
        if sent == 'bull': bull_news += 1
        elif sent == 'bear': bear_news += 1
        if et:
            event_counts[et] = event_counts.get(et, 0) + 1
            if len(recent_events) < 8:
                recent_events.append({
                    'title': title[:120],
                    'paper': a.get('paper') or a.get('source', ''),
                    'ts': a.get('ts'),
                    'event_type': et,
                    'sentiment': sent,
                    'macro_default': macro_event_default_sentiment(et),
                })
    macro_polarity = ((bull_news - bear_news) / max(1, bull_news + bear_news)) * 100 if (bull_news + bear_news) > 0 else 0

    # Stress score 산정
    stress = 0.0
    war_count = event_counts.get('war', 0)
    sanc_count = event_counts.get('sanctions', 0)
    cpi_hot = event_counts.get('cpi_hot', 0)
    rate_hike = event_counts.get('rate_hike', 0)
    oil_spike = event_counts.get('oil_spike', 0)
    recession = event_counts.get('recession', 0)
    stress += min(40, war_count * 8)
    stress += min(20, sanc_count * 4)
    stress += min(15, cpi_hot * 5)
    stress += min(15, rate_hike * 4)
    stress += min(15, oil_spike * 3)
    stress += min(15, recession * 5)
    if vix_now is not None:
        # VIX > 25 = elevated, > 35 = panic
        if vix_now > 35: stress += 25
        elif vix_now > 25: stress += 15
        elif vix_now > 20: stress += 8
    if vix_5d_chg is not None and vix_5d_chg > 20:
        stress += min(15, vix_5d_chg / 4)
    if macro_polarity < -50:
        stress += 10
    stress = max(0.0, min(100.0, stress))

    # Regime 판단
    regime = 'neutral'
    regime_reasons = []
    if oil_spike >= 2 or (oil_5d_chg is not None and oil_5d_chg > 7):
        regime = 'oil_up'
        regime_reasons.append(f'oil 5d {oil_5d_chg:+.1f}%' if oil_5d_chg else f'oil_spike news ×{oil_spike}')
    if rate_hike >= 1 or (rate_5d_chg is not None and rate_5d_chg > 30):
        regime = 'rate_up'
        regime_reasons.append(f'rates 5d +{rate_5d_chg}bp' if rate_5d_chg else f'rate_hike news ×{rate_hike}')
    if stress >= 35 or war_count >= 2 or recession >= 2:
        regime = 'risk_off'
        regime_reasons.append(f'stress {stress:.0f}')
        if war_count >= 2: regime_reasons.append(f'war news ×{war_count}')
        if vix_now and vix_now > 25: regime_reasons.append(f'VIX {vix_now:.1f}')
    elif macro_polarity > 30 and stress < 15 and vix_now and vix_now < 18:
        regime = 'risk_on'
        regime_reasons.append(f'macro pol {macro_polarity:+.0f}, stress {stress:.0f}, VIX {vix_now:.1f}')

    return {
        'regime': regime,
        'regime_reasons': regime_reasons,
        'macro_polarity': round(macro_polarity, 1),
        'stress_score': round(stress, 1),
        'event_counts': event_counts,
        'recent_events': recent_events,
        'vix_now': vix_now,
        'vix_5d_chg': vix_5d_chg,
        'oil_5d_chg': oil_5d_chg,
        'rate_5d_chg': rate_5d_chg,
        'bull_news': bull_news, 'bear_news': bear_news, 'macro_news_total': len(macro_articles),
    }


# ─── Sector × regime score 보정 ─────────────────────────────
def apply_macro_adjustment(base_score, code, regime, market, weight=1.5):
    """종목 sector × regime → ±α 보정.
       weight: macro 영향력 곱 (1.5 = 상당히 강조). score 단위는 약 ±15 범위.
       sector 매핑 안 되거나 regime=neutral 이면 base_score 그대로."""
    if regime == 'neutral' or not code:
        return base_score, 0.0
    sector = market.sector_map.get(code)
    if not sector:
        return base_score, 0.0
    impacts = market.macro_sector_impact.get(regime, {})
    impact = impacts.get(sector, 0.0)
    if impact == 0.0:
        return base_score, 0.0
    adj = impact * weight
    return base_score + adj, adj


# ─── Macro Beta — 종목별 vs 거시변수 다변량 OLS ───────────────
def _bars_to_chg_by_day(bars, days, mode='abs'):
    """bars[-days:] → {epoch_day: change}. mode='abs' for VIX/rates, 'pct' for oil/dxy."""
    if not bars or len(bars) < 2:
        return {}
    recent = bars[-days:] if len(bars) >= days else bars
    out = {}
    for i in range(1, len(recent)):
        if recent[i-1]['c'] <= 0:
            continue
        day = recent[i]['t'] // 86400000
        if mode == 'pct':
            chg = (recent[i]['c'] - recent[i-1]['c']) / recent[i-1]['c'] * 100
        else:
            chg = recent[i]['c'] - recent[i-1]['c']
        out[day] = chg
    return out


def _ols_multivariate(y, X):
    """단순 다변량 OLS (k=4): β = (X'X)^-1 X'y. X는 list of lists [[v1,v2,v3,v4], ...].
       작은 k에 대한 가우스-조던 inverse. None 반환 = 분산 부족 / 특이행렬."""
    n = len(y)
    if n < 10 or not X or len(X) != n:
        return None
    k = len(X[0])
    # Build X'X (k x k) and X'y (k)
    XtX = [[0.0] * k for _ in range(k)]
    Xty = [0.0] * k
    for i in range(n):
        for a in range(k):
            Xty[a] += X[i][a] * y[i]
            for b in range(k):
                XtX[a][b] += X[i][a] * X[i][b]
    # Invert XtX via Gauss-Jordan
    aug = [row[:] + ([1.0 if i == j else 0.0 for j in range(k)]) for i, row in enumerate(XtX)]
    for col in range(k):
        # find pivot
        piv = -1; pivval = 0.0
        for r in range(col, k):
            if abs(aug[r][col]) > abs(pivval):
                pivval = aug[r][col]; piv = r
        if abs(pivval) < 1e-12:
            return None
        aug[col], aug[piv] = aug[piv], aug[col]
        # normalize
        for j in range(2*k):
            aug[col][j] /= pivval
        # eliminate other rows
        for r in range(k):
            if r == col: continue
            factor = aug[r][col]
            for j in range(2*k):
                aug[r][j] -= factor * aug[col][j]
    inv = [row[k:] for row in aug]
    # β = inv * Xty
    beta = [sum(inv[i][j] * Xty[j] for j in range(k)) for i in range(k)]
    # R² = 1 - SSres/SStot
    my = sum(y) / n
    sstot = sum((v - my) ** 2 for v in y)
    ssres = 0.0
    for i in range(n):
        pred = sum(beta[a] * X[i][a] for a in range(k))
        ssres += (y[i] - pred) ** 2
    r2 = 1 - ssres / sstot if sstot > 0 else 0
    return beta, r2


def compute_macro_beta(charts, vix_bars=None, oil_bars=None, rates_bars=None, dxy_bars=None, days=60):
    """다변량 OLS: stock_daily_return ~ ΔVIX + Δoil_pct + Δrates + Δdxy_pct.
       VIX/rates는 절대 변화, oil/dxy는 % 변화.
       주 변수 없으면 0으로 채움 (해당 β=0 강제). 반환 {code: {beta_vix, beta_oil, beta_rates, beta_dxy, r2, n}}."""
    vix_by_day   = _bars_to_chg_by_day(vix_bars or [], days, 'abs')
    oil_by_day   = _bars_to_chg_by_day(oil_bars or [], days, 'pct')
    rates_by_day = _bars_to_chg_by_day(rates_bars or [], days, 'abs')
    dxy_by_day   = _bars_to_chg_by_day(dxy_bars or [], days, 'pct')

    out = {}
    for code, bars in charts.items():
        if len(bars) < 20:
            continue
        recent = bars[-days:] if len(bars) >= days else bars
        y = []; X = []
        for i in range(1, len(recent)):
            day = recent[i]['t'] // 86400000
            if recent[i-1]['c'] <= 0:
                continue
            stk = (recent[i]['c'] - recent[i-1]['c']) / recent[i-1]['c'] * 100
            row = [
                vix_by_day.get(day, 0.0),
                oil_by_day.get(day, 0.0),
                rates_by_day.get(day, 0.0),
                dxy_by_day.get(day, 0.0),
            ]
            # 모든 macro 변수가 0이면 그날 데이터 미반영 (정보 0)
            if all(r == 0.0 for r in row):
                continue
            y.append(stk)
            X.append(row)
        if len(y) < 20:
            continue
        result = _ols_multivariate(y, X)
        if result is None:
            continue
        beta, r2 = result
        out[code] = {
            'beta_vix':   round(beta[0], 3),
            'beta_oil':   round(beta[1], 3),
            'beta_rates': round(beta[2], 3),
            'beta_dxy':   round(beta[3], 3),
            'r2': round(r2, 3),
            'n': len(y),
        }
    return out
