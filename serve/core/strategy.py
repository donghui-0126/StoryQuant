"""트레이딩 전략 — sweep / walkforward / recent_picks. 시장 무관 (어댑터 주입)."""
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from ..utils.stats import pearson
from .quote import fetch_stock_chart
from .news import fetch_news_window_for_code, fetch_stock_news
from .macro import apply_macro_adjustment, compute_macro_stress, compute_macro_beta


# ─── 단일 종목 sweep candidate 계산 ─────────────────────────
def fetch_one_for_sweep(code, market, macro_regime='neutral'):
    """Composite signal — mom5+mom20+뉴스 polarity·density+거래량 z + macro_adj."""
    try:
        chart = fetch_stock_chart(code, '1mo', market)
        bars = chart.get('bars', [])
        if len(bars) < 5:
            return None
        news = fetch_stock_news(code, page=1, page_size=20, market=market, use_llm=True)
        articles = news.get('articles', [])

        last = bars[-1]['c']
        b5 = bars[-6]['c'] if len(bars) >= 6 else bars[0]['c']
        b20 = bars[-21]['c'] if len(bars) >= 21 else bars[0]['c']
        mom_5 = (last - b5) / b5 * 100
        mom_20 = (last - b20) / b20 * 100

        # 거래량 z (오늘 vs 직전 20일)
        vols = [b.get('v') or 0 for b in bars[-21:-1]]
        vols = [v for v in vols if v > 0]
        vol_z = 0
        if len(vols) >= 5:
            avg = sum(vols) / len(vols)
            std = (sum((v - avg) ** 2 for v in vols) / len(vols)) ** 0.5
            last_v = bars[-1].get('v') or 0
            if std > 0:
                vol_z = (last_v - avg) / std

        bull = sum(1 for a in articles if a.get('sentiment') == 'bull')
        bear = sum(1 for a in articles if a.get('sentiment') == 'bear')
        polarity = ((bull - bear) / (bull + bear) * 100) if (bull + bear) > 0 else 0
        density = min(3.0, len(articles) * 0.15)
        # scope별 호악재 카운트 (LLM 분류 시 활용)
        stock_bull  = sum(1 for a in articles if a.get('sentiment') == 'bull' and a.get('scope') == 'stock')
        stock_bear  = sum(1 for a in articles if a.get('sentiment') == 'bear' and a.get('scope') == 'stock')
        sector_bull = sum(1 for a in articles if a.get('sentiment') == 'bull' and a.get('scope') == 'sector')
        sector_bear = sum(1 for a in articles if a.get('sentiment') == 'bear' and a.get('scope') == 'sector')
        reactive_n  = sum(1 for a in articles if a.get('substance') == 'reactive')
        speculative_n = sum(1 for a in articles if a.get('llm_label') == 'speculative')
        offtopic_n   = sum(1 for a in articles if a.get('llm_label') == 'off_topic')
        llm_used     = sum(1 for a in articles if a.get('llm_label'))

        spec_avg = (sum(a.get('specificity') or 0 for a in articles) / len(articles)) if articles else 0
        surp_max = max((a.get('surprise') or 0 for a in articles), default=0)
        src_avg = (sum(a.get('source_score') or 0.5 for a in articles) / len(articles)) if articles else 0.5
        sub_count = sum(1 for a in articles if a.get('substance') == 'substantive')
        cat_dist = {}
        for a in articles:
            c = a.get('category') or '기타'
            cat_dist[c] = cat_dist.get(c, 0) + 1
        is_mystery = (abs(mom_5) >= 3.0 and len(articles) <= 1)

        # v21.6 — priced_in annotation + ratio 산정
        from .classify import annotate_priced_in
        annotate_priced_in(articles, bars)
        priced_in_count = sum(1 for a in articles if a.get('priced_in'))
        priced_in_ratio = priced_in_count / max(1, len(articles))

        base_score = (
            0.30 * max(-15, min(15, mom_5))
            + 0.20 * max(-25, min(25, mom_20)) / 2
            + 0.25 * (polarity / 10)
            + 0.15 * density
            + 0.10 * max(-3, min(3, vol_z))
        )
        # v21.6 — priced_in penalty: bull 뉴스가 이미 priced_in 비율 높으면 score 감점
        # 0.5 (절반 priced_in) → -1.0 점, 1.0 (전부) → -2.0 점
        priced_in_penalty = -2.0 * priced_in_ratio if (polarity > 0 and priced_in_ratio > 0.3) else 0
        base_score += priced_in_penalty
        # v21.2 — macro regime 보정
        score, macro_adj = apply_macro_adjustment(base_score, code, macro_regime, market, weight=1.5)
        info = market.universe().get(code, {})
        sector = market.sector_map.get(code)
        return {
            'code': code,
            'name': info.get('name', code),
            'market': info.get('market', '?'),
            'last': last,
            'mom_5': round(mom_5, 2),
            'mom_20': round(mom_20, 2),
            'polarity': round(polarity, 0),
            'news_count': len(articles),
            'news_bull': bull,
            'news_bear': bear,
            'vol_z': round(vol_z, 2),
            'score': round(score, 2),
            'base_score': round(base_score, 2),
            'macro_adj': round(macro_adj, 2),
            'sector': sector,
            'specificity': round(spec_avg, 2),
            'surprise_max': round(surp_max, 2),
            'src_avg': round(src_avg, 2),
            'sub_count': sub_count,
            'cat_dist': cat_dist,
            'is_mystery': is_mystery,
            # v21.6 — priced-in 정보
            'priced_in_count': priced_in_count,
            'priced_in_ratio': round(priced_in_ratio, 2),
            'priced_in_penalty': round(priced_in_penalty, 2),
            # LLM 분류 결과 — scope 분리 + 노이즈 카운트
            'stock_bull': stock_bull,
            'stock_bear': stock_bear,
            'sector_bull': sector_bull,
            'sector_bear': sector_bear,
            'reactive_n': reactive_n,
            'speculative_n': speculative_n,
            'offtopic_n': offtopic_n,
            'llm_used': llm_used,
            # 카드 큐레이션용 — 실질 사건 뉴스 상위 3건 (미반영 우선, 최신순)
            'top_news': [
                {'title': a.get('title'), 'link': a.get('link'),
                 'paper': a.get('paper') or a.get('source'),
                 'ts': a.get('ts'), 'sentiment': a.get('sentiment'),
                 'scope': a.get('scope') or 'stock',
                 'comment': a.get('llm_comment'),
                 'priced_in': bool(a.get('priced_in'))}
                for a in sorted(
                    [a for a in articles if a.get('substance') == 'substantive'
                     and a.get('sentiment') in ('bull', 'bear')],
                    key=lambda a: (a.get('priced_in') and 1 or 0, -(a.get('ts') or 0)))[:3]
            ],
            # scope=sector + event_* 인 기사만 — 섹터 sheet 용
            '_sector_articles': [
                {'title': a.get('title'), 'link': a.get('link'),
                 'paper': a.get('paper') or a.get('source'),
                 'ts': a.get('ts'), 'sentiment': a.get('sentiment'),
                 'llm_label': a.get('llm_label'), 'llm_reason': a.get('llm_reason')}
                for a in articles
                if a.get('scope') == 'sector' and a.get('llm_label') in ('event_bull','event_bear')
            ],
        }
    except Exception:
        return None


def fetch_sweep(top_n, market):
    """Universe top N composite sweep — macro regime 검출 후 score formula에 ±α 적용."""
    universe = market.universe()
    codes = list(universe.keys())[:top_n]

    # v21.2 — macro regime 미리 산정 (sweep articles 가 아닌 시장 RSS 사용)
    macro_regime = 'neutral'
    macro_summary = None
    try:
        from .feeds import fetch_news
        news = fetch_news([], 200, market)
        macro_cat_names = {'거시·지정학', 'Macro·Geopolitics'}
        macro_arts = [a for a in news.get('articles', [])
                      if a.get('category') in macro_cat_names]
        vix_now = vix_5d_chg = oil_5d_chg = None
        try:
            vix_chart = fetch_stock_chart('^VIX', '1mo', market)
            vb = vix_chart.get('bars', [])
            if vb:
                vix_now = vb[-1]['c']
                if len(vb) >= 6:
                    vix_5d_chg = (vb[-1]['c'] - vb[-6]['c']) / vb[-6]['c'] * 100
        except Exception:
            pass
        try:
            oil_chart = fetch_stock_chart('CL=F', '1mo', market)
            ob = oil_chart.get('bars', [])
            if ob and len(ob) >= 6:
                oil_5d_chg = (ob[-1]['c'] - ob[-6]['c']) / ob[-6]['c'] * 100
        except Exception:
            pass
        macro_summary = compute_macro_stress(macro_arts, vix_now=vix_now,
                                              vix_5d_chg=vix_5d_chg, oil_5d_chg=oil_5d_chg)
        macro_regime = macro_summary.get('regime', 'neutral')
    except Exception:
        pass

    results = []
    with ThreadPoolExecutor(max_workers=14) as ex:
        futs = [ex.submit(fetch_one_for_sweep, c, market, macro_regime) for c in codes]
        for f in as_completed(futs):
            r = f.result()
            if r:
                results.append(r)
    results.sort(key=lambda x: -x['score'])
    mystery_movers = sorted(
        [r for r in results if r.get('is_mystery')],
        key=lambda x: -abs(x['mom_5'])
    )[:10]
    # 섹터별 신호 집계 — LLM scope='sector' 뉴스만 (업종 전반 영향)
    sector_signals = {}
    for r in results:
        sec = r.get('sector')
        if not sec: continue
        s = sector_signals.setdefault(sec, {
            'n_stocks': 0, 'sector_bull': 0, 'sector_bear': 0,
            'stock_bull': 0, 'stock_bear': 0,
            'avg_polarity': 0.0, 'avg_mom5': 0.0,
            'codes': [], 'articles': [], '_seen_titles': set(),
            '_pol_sum': 0.0, '_mom_sum': 0.0,
        })
        s['n_stocks'] += 1
        s['codes'].append({'code': r['code'], 'name': r['name'], 'mom_5': r['mom_5'],
                           'news_count': r.get('sub_count', 0),
                           'news_rating': r.get('polarity', 0),
                           'score': r.get('score', 0)})
        s['sector_bull'] += r.get('sector_bull', 0)
        s['sector_bear'] += r.get('sector_bear', 0)
        s['stock_bull']  += r.get('stock_bull', 0)
        s['stock_bear']  += r.get('stock_bear', 0)
        s['_pol_sum']    += r.get('polarity', 0)
        s['_mom_sum']    += r.get('mom_5', 0)
        # 섹터 뉴스 dedup (title prefix 기준)
        for art in r.get('_sector_articles', []) or []:
            key = (art.get('title') or '')[:40]
            if key in s['_seen_titles']: continue
            s['_seen_titles'].add(key)
            s['articles'].append(art)
    for sec, s in sector_signals.items():
        n = max(1, s['n_stocks'])
        s['avg_polarity'] = round(s['_pol_sum'] / n, 1)
        s['avg_mom5']     = round(s['_mom_sum'] / n, 2)
        sb, sx = s['sector_bull'], s['sector_bear']
        s['sector_news_rating'] = round(((sb - sx) / (sb + sx + 5)) * 100, 1) if (sb + sx) > 0 else 0.0
        s['articles'].sort(key=lambda a: -(a.get('ts') or 0))
        s['articles'] = s['articles'][:50]    # 상위 50건
        del s['_pol_sum'], s['_mom_sum'], s['_seen_titles']
    # 종목 응답에서는 _sector_articles 제거 (응답 size 축소)
    for r in results:
        r.pop('_sector_articles', None)
    try:
        from . import llm_classify as _llm
        llm_stats = _llm.stats()
    except Exception:
        llm_stats = None
    return {
        'ts': int(time.time() * 1000),
        'market': market.id,
        'count': len(results),
        'macro_regime': macro_regime,
        'macro_summary': macro_summary,
        'top_bull': results[:15],
        'top_bear': results[-15:][::-1],
        'mystery_movers': mystery_movers,
        'sector_signals': sector_signals,
        'llm_stats': llm_stats,
        'all': results,
    }


# ─── Recent picks forward test ─────────────────────────────
def fetch_recent_picks(top_n, market, lookbacks=(5, 10, 20)):
    """매 N일 전 시점 sweep top10 매수 → 오늘 실제 수익. Full sweep formula 사용 (뉴스 포함)."""
    universe = market.universe()
    codes = list(universe.keys())[:top_n]
    charts = {}
    needed = max(lookbacks) + 21
    with ThreadPoolExecutor(max_workers=14) as ex:
        futs = {ex.submit(fetch_stock_chart, c, '3mo', market): c for c in codes}
        for f in as_completed(futs):
            r = f.result()
            if r and len(r.get('bars', [])) >= needed:
                charts[r['code']] = r['bars']

    bench = fetch_stock_chart(market.benchmark_symbol, '3mo', market)
    kospi_bars = bench.get('bars', []) if bench else []

    news_by_code = {}
    if charts:
        first_ts_needed = min(b[-1 - max(lookbacks)]['t'] - 14 * 86400000 for b in charts.values())
        last_ts_needed = max(b[-1]['t'] for b in charts.values())
        with ThreadPoolExecutor(max_workers=10) as ex:
            futs = {}
            for c, bars in charts.items():
                name = (universe.get(c) or {}).get('name') or c
                if len(name) < 2:
                    news_by_code[c] = []
                    continue
                futs[ex.submit(fetch_news_window_for_code, c, name, first_ts_needed, last_ts_needed, market, True)] = c
            for f in as_completed(futs):
                code = futs[f]
                try:
                    news_by_code[code] = f.result()
                except Exception:
                    news_by_code[code] = []

    snapshots = []
    for lb in lookbacks:
        t_idx = -1 - lb
        cands = []
        for code, bars in charts.items():
            if abs(t_idx) + 20 >= len(bars):
                continue
            cur = bars[t_idx]['c']
            t_ts = bars[t_idx]['t']
            news_window_start = t_ts - 14 * 86400000

            m5 = (cur / bars[t_idx - 5]['c'] - 1) * 100
            m20 = (cur / bars[t_idx - 20]['c'] - 1) * 100

            vols = [b.get('v') or 0 for b in bars[t_idx - 21:t_idx]]
            vols = [v for v in vols if v > 0]
            vol_z = 0
            if len(vols) >= 5:
                avg = sum(vols) / len(vols)
                std = (sum((v - avg) ** 2 for v in vols) / len(vols)) ** 0.5
                last_v = bars[t_idx].get('v') or 0
                if std > 0:
                    vol_z = (last_v - avg) / std

            polarity = 0; density = 0; n_count = 0; bull = bear = 0
            if code in news_by_code:
                relevant = [a for a in news_by_code[code] if news_window_start <= a['ts'] <= t_ts]
                bull = sum(1 for a in relevant if a.get('sentiment') == 'bull')
                bear = sum(1 for a in relevant if a.get('sentiment') == 'bear')
                n_count = len(relevant)
                if (bull + bear) > 0:
                    polarity = (bull - bear) / (bull + bear) * 100
                density = min(3.0, n_count * 0.15)

            score = (
                0.30 * max(-15, min(15, m5))
                + 0.20 * max(-25, min(25, m20)) / 2
                + 0.25 * (polarity / 10)
                + 0.15 * density
                + 0.10 * max(-3, min(3, vol_z))
            )

            p_now = bars[-1]['c']
            forward = (p_now - cur) / cur * 100
            info = universe.get(code, {})
            cands.append({
                'code': code,
                'name': info.get('name', code),
                'score': round(score, 2),
                'mom5_T': round(m5, 1),
                'mom20_T': round(m20, 1),
                'polarity_T': round(polarity, 0),
                'density_T': round(density, 1),
                'news_count_T': n_count,
                'news_bull_T': bull,
                'news_bear_T': bear,
                'vol_z_T': round(vol_z, 2),
                'forward_pct': round(forward, 2),
                'price_T': cur,
                'price_now': p_now,
            })
        if not cands:
            continue
        cands.sort(key=lambda x: -x['score'])
        top = cands[:10]
        avg_fwd = sum(t['forward_pct'] for t in top) / len(top)
        win = sum(1 for t in top if t['forward_pct'] > 0)
        kospi_fwd = 0.0
        if abs(t_idx) <= len(kospi_bars):
            k_T = kospi_bars[t_idx]['c']
            kospi_fwd = (kospi_bars[-1]['c'] - k_T) / k_T * 100
        sample = next(iter(charts.values()))
        snapshots.append({
            'lookback_days': lb,
            'snapshot_ts': sample[t_idx]['t'],
            'today_ts': sample[-1]['t'],
            'top': top,
            'avg_fwd_pct': round(avg_fwd, 2),
            'kospi_fwd_pct': round(kospi_fwd, 2),
            'alpha_pct': round(avg_fwd - kospi_fwd, 2),
            'win_count': win,
            'total': len(top),
        })

    return {
        'ts': int(time.time() * 1000),
        'market': market.id,
        'universe_size': len(charts),
        'note': f'Full sweep formula (가격 + 뉴스 polarity·density + 거래량 z). Benchmark={market.benchmark_symbol}. 미래 참조 X. 24h 캐시.',
        'snapshots': snapshots,
    }


# ─── Walk-forward backtest ─────────────────────────────────
def walkforward_backtest(market, top_n=80, days=120, top_k=8, hold=5,
                         use_news=True, mode='blend', universe_mode='current',
                         cat_filter=(), start_offset_days=0):
    """과거 N일 walk-forward — 미래 참조 X. 시장 무관."""
    if mode == 'price_only':
        use_news = False
    elif mode in ('news_only', 'attention', 'attn_blend'):
        use_news = True

    universe = market.universe()

    if universe_mode == 'kospi200':
        # KR 전용 — KOSPI 종목만. 다른 시장에선 universe filter 필요.
        codes = [c for c, info in universe.items() if info.get('market') == 'KOSPI'][:200]
    elif universe_mode == 'dynamic':
        codes = list(universe.keys())[:400]
    else:
        codes = list(universe.keys())[:top_n]

    # v21.4 — 장기 백테 지원: days 또는 offset 큰 경우 더 긴 chart range
    # Yahoo bar count 보수적으로 추정: 1y ≈ 250, 2y ≈ 500, 5y ≈ 1250, 10y ≈ 2500
    # buffer 30 + needed 만큼 여유 있어야 함. 임계값을 보수적으로.
    total_span = days + 30 + start_offset_days
    if total_span > 1100:
        chart_range = '10y'
    elif total_span > 450:
        chart_range = '5y'
    elif total_span > 200:
        chart_range = '2y'
    else:
        chart_range = '1y'
    needed = total_span
    charts = {}
    with ThreadPoolExecutor(max_workers=14) as ex:
        futs = {ex.submit(fetch_stock_chart, c, chart_range, market): c for c in codes}
        for f in as_completed(futs):
            r = f.result()
            bars = r.get('bars', []) if r else []
            if r and len(bars) >= needed:
                if start_offset_days > 0:
                    charts[r['code']] = bars[-(days + 30 + start_offset_days): -start_offset_days]
                else:
                    charts[r['code']] = bars[-(days + 30):]

    if len(charts) < top_k * 2 + 5:
        return {'error': f'insufficient charts: {len(charts)} (need {top_k*2+5}+)'}

    implied_shares = {}
    if universe_mode == 'dynamic':
        try:
            mc = market.fetch_marketcap(list(charts.keys()))
            for q in mc.get('quotes', []):
                code = q.get('code')
                cap = q.get('marketCap'); last = q.get('last')
                if code and cap and last and last > 0:
                    implied_shares[code] = cap / last
        except Exception:
            pass

    news_by_code = {}
    if use_news:
        # v21.4 — 과거 뉴스까지 전체 chart 기간 fetch. 처음 호출 시 매우 느림 (4년 = ~30분),
        # 이후 _HIST_NEWS_CACHE 24h hit 으로 즉시.
        first_ts = min(charts[c][0]['t'] for c in charts)
        last_ts = max(charts[c][-1]['t'] for c in charts)
        with ThreadPoolExecutor(max_workers=14) as ex:
            futs = {}
            for c, bars in charts.items():
                name = (universe.get(c) or {}).get('name') or c
                if len(name) < 2:
                    continue
                futs[ex.submit(fetch_news_window_for_code, c, name, first_ts, last_ts, market, True)] = c
            for f in as_completed(futs):
                code = futs[f]
                try:
                    news_by_code[code] = f.result()
                except Exception:
                    news_by_code[code] = []

    bench = fetch_stock_chart(market.benchmark_symbol, '1y', market)
    bench_bars_full = bench.get('bars', []) if bench else []

    # v21.3+v21.4 — 다변량 Macro Beta + regime classification: VIX/oil/rates/DXY.
    # backtest 길이에 따라 macro range 도 확장 (regime classification에 모든 시점 VIX 필요).
    macro_range = chart_range
    macro_betas = {}
    vix_bars = oil_bars = rates_bars = dxy_bars = []
    try:
        vix_bars = (fetch_stock_chart('^VIX', macro_range, market).get('bars') or [])
    except Exception: pass
    try:
        oil_bars = (fetch_stock_chart('CL=F', macro_range, market).get('bars') or [])
    except Exception: pass
    try:
        rates_bars = (fetch_stock_chart('^TNX', macro_range, market).get('bars') or [])
    except Exception: pass
    try:
        dxy_bars = (fetch_stock_chart('DX-Y.NYB', macro_range, market).get('bars') or [])
    except Exception: pass
    try:
        macro_betas = compute_macro_beta(charts, vix_bars, oil_bars, rates_bars, dxy_bars, days=60)
    except Exception:
        macro_betas = {}

    min_len = min(len(b) for b in charts.values())
    series = {c: bars[-min_len:] for c, bars in charts.items()}

    bench_bars = []
    if bench_bars_full:
        from datetime import datetime, timezone
        bench_by_day = {}
        for b in bench_bars_full:
            day = datetime.fromtimestamp(b['t'] / 1000, tz=timezone.utc).date()
            bench_by_day[day] = b
        any_stock = next(iter(series.values()))
        sorted_bench_days = sorted(bench_by_day.keys())
        for stock_bar in any_stock:
            stock_day = datetime.fromtimestamp(stock_bar['t'] / 1000, tz=timezone.utc).date()
            if stock_day in bench_by_day:
                bench_bars.append(bench_by_day[stock_day])
            else:
                prior = [d for d in sorted_bench_days if d <= stock_day]
                if prior:
                    bench_bars.append(bench_by_day[prior[-1]])
                else:
                    bench_bars.append(bench_bars_full[0] if bench_bars_full else None)

    rebalance_points = list(range(20, min_len - hold, hold))
    trades = []
    equity = [1.0]
    bench_equity = [1.0]
    ic_history = []
    cat_forwards = {c: [] for c in market.category_keys}
    cat_forwards['기타'] = []
    all_feat = []

    # v21.3 — VIX 시점별 일자 매핑 → regime 분류
    # rebalance 시점의 VIX 값 → (high>=22 → risk_off / low<=15 → risk_on / 그 외 neutral)
    vix_by_day_close = {}
    if vix_bars:
        for vb in vix_bars:
            day = vb['t'] // 86400000
            vix_by_day_close[day] = vb['c']
    regime_trades = {'risk_off': [], 'risk_on': [], 'neutral': []}

    categories = tuple(market.category_keys.keys()) + (('기타',) if '기타' not in market.category_keys else ())

    for t in rebalance_points:
        scores = []
        t_ts = series[next(iter(series))][t]['t']
        news_window_start = t_ts - 14 * 86400000
        attn_window_start = t_ts - 3 * 86400000

        # v21.5 — regime classification 미리 계산 (regime_polarity mode가 사용)
        t_day_pre = t_ts // 86400000
        regime_pre = 'neutral'; vix_pre = None
        if vix_by_day_close:
            for d in (t_day_pre, t_day_pre - 1, t_day_pre - 2, t_day_pre - 3):
                if d in vix_by_day_close:
                    vix_pre = vix_by_day_close[d]; break
            if vix_pre is not None:
                if vix_pre >= 22: regime_pre = 'risk_off'
                elif vix_pre <= 15: regime_pre = 'risk_on'

        if universe_mode == 'dynamic' and implied_shares:
            cap_at_t = []
            for code, bars in series.items():
                if code not in implied_shares:
                    continue
                cap_at_t.append((code, bars[t]['c'] * implied_shares[code]))
            cap_at_t.sort(key=lambda x: -x[1])
            allowed_codes = set(c for c, _ in cap_at_t[:top_n])
        else:
            allowed_codes = None

        feat_rows = []
        for code, bars in series.items():
            if allowed_codes is not None and code not in allowed_codes:
                continue
            cur = bars[t]['c']
            mom5 = (cur / bars[t-5]['c'] - 1) * 100 if t >= 5 else 0
            mom20 = (cur / bars[t-20]['c'] - 1) * 100 if t >= 20 else 0
            mom5_clip = max(-15, min(15, mom5))
            mom20_clip = max(-25, min(25, mom20))

            polarity = 0; n_count = 0; n_recent = 0; bull = bear = 0
            s_bull = s_bear = s_count = r_count = 0
            spec_avg = surp_avg = 0.0; src_avg = 0.5; info_score = 0.0
            tod_pre = tod_intra = tod_after = 0
            cat_counts = {c: 0 for c in categories}

            if use_news and code in news_by_code:
                relevant = [a for a in news_by_code[code] if news_window_start <= a['ts'] <= t_ts]
                bull = sum(1 for a in relevant if a.get('sentiment') == 'bull')
                bear = sum(1 for a in relevant if a.get('sentiment') == 'bear')
                n_count = len(relevant)
                if (bull + bear) > 0:
                    polarity = (bull - bear) / (bull + bear) * 100
                n_recent = sum(1 for a in relevant if a['ts'] >= attn_window_start)
                substantive = [a for a in relevant if a.get('substance') == 'substantive']
                reactive = [a for a in relevant if a.get('substance') == 'reactive']
                s_bull = sum(1 for a in substantive if a.get('sentiment') == 'bull')
                s_bear = sum(1 for a in substantive if a.get('sentiment') == 'bear')
                s_count = len(substantive)
                r_count = len(reactive)
                if relevant:
                    spec_vals = [a.get('specificity') or 0 for a in relevant]
                    surp_vals = [a.get('surprise') or 0 for a in relevant]
                    src_vals = [a.get('source_score') or 0.5 for a in relevant]
                    spec_avg = sum(spec_vals) / len(spec_vals)
                    surp_avg = sum(surp_vals) / len(surp_vals)
                    src_avg = sum(src_vals) / len(src_vals)
                    for a in relevant:
                        tod = a.get('tod') or 'intra'
                        if tod == 'pre': tod_pre += 1
                        elif tod == 'after': tod_after += 1
                        else: tod_intra += 1
                        cat = a.get('category') or '기타'
                        if cat in cat_counts: cat_counts[cat] += 1
                sub_ratio = s_count / max(1, n_count)
                info_score = (polarity / 100.0) * (1 + spec_avg) * src_avg * (0.5 + sub_ratio)

            density = min(3.0, n_count * 0.15)
            attention = (n_recent / max(1, n_count)) if n_count >= 3 else 0
            disagree = (min(bull, bear) / max(1, max(bull, bear))) if (bull + bear) >= 3 else 0
            s_polarity = ((s_bull - s_bear) / (s_bull + s_bear) * 100) if (s_bull + s_bear) > 0 else 0
            s_density = min(3.0, s_count * 0.20)
            reactive_ratio = (r_count / max(1, n_count)) if n_count >= 3 else 0
            tod_offmkt = ((tod_pre + tod_after) / max(1, n_count)) if n_count >= 3 else 0

            forward = (bars[t+hold]['c'] / cur - 1) * 100
            # horizon 비교용 — 1일/20일 forward (범위 밖이면 None)
            forward_1 = (bars[t+1]['c'] / cur - 1) * 100 if t + 1 < len(bars) else None
            forward_20 = (bars[t+20]['c'] / cur - 1) * 100 if t + 20 < len(bars) else None
            # v21.2 — macro beta (negative = defensive: VIX 상승 시 가격 하락 안 함)
            macro_beta = (macro_betas.get(code) or {}).get('beta_vix', 0)
            feat_rows.append({
                'code': code, 'mom5': mom5_clip, 'mom20': mom20_clip,
                'polarity': polarity, 'density': density, 'attention': attention,
                'disagree': disagree, 'n_count': n_count, 'forward': forward,
                'forward_1': forward_1, 'forward_20': forward_20,
                's_polarity': s_polarity, 's_density': s_density,
                's_count': s_count, 'reactive_ratio': reactive_ratio,
                'specificity': spec_avg, 'surprise': surp_avg, 'src_avg': src_avg,
                'info_score': info_score, 'tod_offmkt': tod_offmkt,
                'macro_beta': macro_beta,
                'cat_counts': cat_counts,
                'sector': market.sector_map.get(code) or '기타',    # 섹터 식별자
            })

        # 시점별 섹터 평균 (polarity, mom5, forward) — feature 컨텍스트 + target 용
        sector_pol = {}; sector_mom = {}; sector_fwd = {}
        for r in feat_rows:
            sec = r['sector']
            sector_pol.setdefault(sec, []).append(r['polarity'])
            sector_mom.setdefault(sec, []).append(r['mom5'])
            sector_fwd.setdefault(sec, []).append(r['forward'])
        sector_pol_avg = {k: sum(v)/len(v) for k, v in sector_pol.items() if v}
        sector_mom_avg = {k: sum(v)/len(v) for k, v in sector_mom.items() if v}
        sector_fwd_avg = {k: sum(v)/len(v) for k, v in sector_fwd.items() if v}
        for r in feat_rows:
            sec = r['sector']
            r['sector_polarity'] = sector_pol_avg.get(sec, 0.0)
            r['sector_mom5'] = sector_mom_avg.get(sec, 0.0)
            r['sector_forward'] = sector_fwd_avg.get(sec, 0.0)
            r['sector_alpha_target'] = r['forward'] - sector_fwd_avg.get(sec, 0.0)    # 섹터 대비 forward

        scores = []
        for f in feat_rows:
            if cat_filter:
                cc = f.get('cat_counts') or {}
                if not cc:
                    continue
                non_etc = {k: v for k, v in cc.items() if k != '기타' and v > 0}
                if not non_etc:
                    continue
                top_cat = max(non_etc, key=lambda k: non_etc[k])
                if top_cat not in cat_filter:
                    continue
            if mode == 'price_only':
                s = 0.7 * f['mom5'] + 0.3 * (f['mom20'] / 2)
            elif mode == 'news_only':
                if f['n_count'] < 2: continue
                s = 0.6 * (f['polarity'] / 10) + 0.4 * f['density']
            elif mode == 'substantive':
                if f['s_count'] < 1: continue
                s = (0.30 * f['mom5'] + 0.20 * (f['mom20'] / 2)
                     + 0.35 * (f['s_polarity'] / 10) + 0.15 * f['s_density'])
            elif mode == 'attention':
                if f['n_count'] < 3: continue
                s = f['attention'] * 100 + 0.2 * f['polarity'] / 10
            elif mode == 'attn_blend':
                s = 0.5 * f['mom5'] + 0.5 * (f['attention'] * 100)
            elif mode == 'informational':
                if f['n_count'] < 1: continue
                s = (0.30 * f['mom5'] + 0.20 * (f['mom20'] / 2)
                     + 0.40 * (f['info_score'] * 50) + 0.10 * f['density'])
            elif mode == 'regime_polarity':
                # v21.5 — KR/US 양시장 universal alpha source 발견:
                #   1) polarity IR +0.115 양시장 일치
                #   2) risk_off 시기에 alpha 집중 (KR +3.05% / US +2.23% / win 70%+)
                # 가설: regime 따라 polarity 가중치 조절. risk_on 은 cash (skip).
                if regime_pre == 'risk_off':
                    # 위기 시기: polarity 핵심, mom 보조
                    if f['n_count'] < 1: continue
                    s = (0.20 * f['mom5'] + 0.10 * (f['mom20'] / 2)
                         + 0.55 * (f['polarity'] / 10) + 0.15 * f['density'])
                elif regime_pre == 'risk_on':
                    # 평온 시기 알파 소실 → cash 유지 (모든 종목 score = 0)
                    s = 0.0
                else:    # neutral
                    s = (0.30 * f['mom5'] + 0.20 * (f['mom20'] / 2)
                         + 0.35 * (f['polarity'] / 10) + 0.15 * f['density'])
            else:
                s = (0.40 * f['mom5'] + 0.20 * (f['mom20'] / 2)
                     + 0.30 * (f['polarity'] / 10) + 0.10 * f['density'])
            scores.append((f['code'], s, f['forward'] / 100, f['polarity'], f['n_count']))

        # bench forward (t → t+hold / +1 / +20) 미리 계산 — all_feat 의 alpha 산출용
        bench_fwd_pct = 0.0
        bench_fwd1_pct = None
        bench_fwd20_pct = None
        if bench_bars and t + hold < len(bench_bars) and bench_bars[t] and bench_bars[t+hold]:
            bench_fwd_pct = (bench_bars[t+hold]['c'] / bench_bars[t]['c'] - 1) * 100
        if bench_bars and t + 1 < len(bench_bars) and bench_bars[t] and bench_bars[t+1]:
            bench_fwd1_pct = (bench_bars[t+1]['c'] / bench_bars[t]['c'] - 1) * 100
        if bench_bars and t + 20 < len(bench_bars) and bench_bars[t] and bench_bars[t+20]:
            bench_fwd20_pct = (bench_bars[t+20]['c'] / bench_bars[t]['c'] - 1) * 100
        for r in feat_rows:
            cc = r.get('cat_counts') or {}
            if cc:
                top_cat = max(cc, key=lambda k: cc[k])
                if cc[top_cat] >= 1 and top_cat != '기타' and top_cat in cat_forwards:
                    cat_forwards[top_cat].append(r['forward'])
            all_feat.append({
                'mom5': r['mom5'], 'mom20': r['mom20'],
                'polarity': r['polarity'], 'n_count': r['n_count'],
                'density': r['density'], 'specificity': r['specificity'],
                'surprise': r['surprise'], 'src_avg': r['src_avg'],
                's_polarity': r['s_polarity'], 's_count': r['s_count'],
                'reactive_ratio': r['reactive_ratio'],
                'forward': r['forward'],
                'bench_forward': bench_fwd_pct,
                'alpha': r['forward'] - bench_fwd_pct,
                'alpha_1': (r['forward_1'] - bench_fwd1_pct)
                            if (r['forward_1'] is not None and bench_fwd1_pct is not None) else None,
                'alpha_20': (r['forward_20'] - bench_fwd20_pct)
                            if (r['forward_20'] is not None and bench_fwd20_pct is not None) else None,
                'sector_polarity': r['sector_polarity'],
                'sector_mom5': r['sector_mom5'],
                'sector_forward': r['sector_forward'],
                'sector_alpha': r['sector_alpha_target'],
            })

        if len(feat_rows) >= 5:
            fwd = [r['forward'] for r in feat_rows]
            ic_period = {}
            for fac in ('mom5', 'mom20', 'polarity', 'density', 'attention', 'disagree',
                        's_polarity', 's_density', 'reactive_ratio',
                        'specificity', 'surprise', 'src_avg', 'info_score', 'tod_offmkt',
                        'macro_beta'):
                xs = [r[fac] for r in feat_rows]
                ic_period[fac] = pearson(xs, fwd)
            ic_history.append(ic_period)

        if len(scores) < top_k * 2:
            continue
        # v21.5 — regime_polarity mode 의 risk_on 시기 → cash 유지 (no trade, equity flat)
        if mode == 'regime_polarity' and regime_pre == 'risk_on':
            equity.append(equity[-1])
            if bench_bars and t + hold < len(bench_bars) and bench_bars[t] and bench_bars[t+hold]:
                br = bench_bars[t+hold]['c'] / bench_bars[t]['c'] - 1
                bench_equity.append(bench_equity[-1] * (1 + br))
            else:
                bench_equity.append(bench_equity[-1])
            regime_trades['risk_on'].append({'long_ret': 0, 'bench_ret': br if 'br' in dir() else 0,
                                              'alpha': -(br if 'br' in dir() else 0), 'vix': vix_pre})
            trades.append({'t_idx': t, 't_ts': t_ts, 'long_ret_pct': 0, 'short_ret_pct': 0,
                           'regime': 'risk_on', 'vix_at_t': round(vix_pre,1) if vix_pre else None,
                           'longs': [('CASH','— cash —',0,0,0)], 'shorts': []})
            continue
        scores.sort(key=lambda x: -x[1])
        longs = scores[:top_k]
        shorts = scores[-top_k:]
        long_ret = sum(s[2] for s in longs) / top_k
        short_ret = -sum(s[2] for s in shorts) / top_k
        equity.append(equity[-1] * (1 + long_ret))
        if bench_bars and t + hold < len(bench_bars) and bench_bars[t] and bench_bars[t+hold]:
            br = bench_bars[t+hold]['c'] / bench_bars[t]['c'] - 1
            bench_equity.append(bench_equity[-1] * (1 + br))
        else:
            bench_equity.append(bench_equity[-1])
        # v21.3 — regime 분류 (이 시점 VIX 기준)
        t_day = t_ts // 86400000
        # 가장 가까운 vix close 사용
        regime_t = 'neutral'
        vix_t = None
        if vix_by_day_close:
            for d in (t_day, t_day-1, t_day-2, t_day-3):
                if d in vix_by_day_close:
                    vix_t = vix_by_day_close[d]; break
            if vix_t is not None:
                if vix_t >= 22: regime_t = 'risk_off'
                elif vix_t <= 15: regime_t = 'risk_on'
        bench_ret = (bench_bars[t+hold]['c'] / bench_bars[t]['c'] - 1) if (
            bench_bars and t + hold < len(bench_bars) and bench_bars[t] and bench_bars[t+hold]) else 0
        regime_trades[regime_t].append({
            'long_ret': long_ret, 'bench_ret': bench_ret, 'alpha': long_ret - bench_ret,
            'vix': vix_t,
        })

        trades.append({
            't_idx': t, 't_ts': t_ts,
            'long_ret_pct': round(long_ret * 100, 2),
            'short_ret_pct': round(short_ret * 100, 2),
            'regime': regime_t,
            'vix_at_t': round(vix_t, 1) if vix_t is not None else None,
            'longs': [(s[0], (universe.get(s[0]) or {}).get('name', s[0]),
                       round(s[1], 2), round(s[3], 0), s[4]) for s in longs[:5]],
            'shorts': [(s[0], (universe.get(s[0]) or {}).get('name', s[0]),
                        round(s[1], 2), round(s[3], 0), s[4]) for s in shorts[-5:]],
        })

    rets = [tr['long_ret_pct'] / 100 for tr in trades]
    if not rets:
        return {'error': 'no trades produced'}
    total_return = (equity[-1] - 1) * 100
    win_rate = sum(1 for r in rets if r > 0) / len(rets) * 100
    mean_ret = sum(rets) / len(rets)
    var_ret = sum((r - mean_ret) ** 2 for r in rets) / max(1, len(rets) - 1)
    std_ret = var_ret ** 0.5
    n_per_year = 252 / hold
    sharpe = (mean_ret * n_per_year) / (std_ret * (n_per_year ** 0.5)) if std_ret > 0 else 0
    peak = 1.0; mdd = 0
    for v in equity:
        if v > peak: peak = v
        d = (v - peak) / peak
        if d < mdd: mdd = d
    bench_total = (bench_equity[-1] - 1) * 100 if bench_equity else 0

    start_date = end_date = ''
    if trades:
        from datetime import datetime
        start_date = datetime.fromtimestamp(trades[0]['t_ts'] / 1000).strftime('%Y-%m-%d')
        end_date = datetime.fromtimestamp(trades[-1]['t_ts'] / 1000).strftime('%Y-%m-%d')
    curve_dates = []
    for i, t in enumerate(rebalance_points[:len(equity) - 1]):
        if i < len(series[next(iter(series))]) - 1 and t < len(series[next(iter(series))]):
            ts = series[next(iter(series))][t]['t']
            curve_dates.append(ts)

    ic_summary = {}
    factors = ('mom5', 'mom20', 'polarity', 'density', 'attention', 'disagree',
               's_polarity', 's_density', 'reactive_ratio',
               'specificity', 'surprise', 'src_avg', 'info_score', 'tod_offmkt',
               'macro_beta')
    for fac in factors:
        vals = [period[fac] for period in ic_history if period.get(fac) is not None]
        if not vals:
            ic_summary[fac] = {'mean': None, 'std': None, 'ir': None, 'n': 0, 'hit_rate': None}
            continue
        m = sum(vals) / len(vals)
        v = (sum((x - m) ** 2 for x in vals) / max(1, len(vals) - 1)) ** 0.5
        ir = m / v if v > 0 else None
        hit = sum(1 for x in vals if x > 0) / len(vals)
        ic_summary[fac] = {
            'mean': round(m, 4), 'std': round(v, 4),
            'ir': round(ir, 3) if ir is not None else None,
            'n': len(vals), 'hit_rate': round(hit, 3),
        }

    ortho = {}
    for fa in factors:
        ortho[fa] = {}
        for fb in factors:
            if fa == fb:
                ortho[fa][fb] = 1.0
                continue
            paired = [(p[fa], p[fb]) for p in ic_history
                      if p.get(fa) is not None and p.get(fb) is not None]
            if len(paired) < 3:
                ortho[fa][fb] = None
                continue
            mx = sum(x for x, _ in paired) / len(paired)
            my = sum(y for _, y in paired) / len(paired)
            num = sum((x - mx) * (y - my) for x, y in paired)
            vx = sum((x - mx) ** 2 for x, _ in paired) ** 0.5
            vy = sum((y - my) ** 2 for _, y in paired) ** 0.5
            ortho[fa][fb] = round(num / (vx * vy), 3) if vx * vy > 0 else None

    cat_halflife = {}
    for cat, vals in cat_forwards.items():
        if len(vals) >= 5:
            mean_v = sum(vals) / len(vals)
            std_v = (sum((x - mean_v) ** 2 for x in vals) / max(1, len(vals) - 1)) ** 0.5
            hit = sum(1 for x in vals if x > 0) / len(vals)
            cat_halflife[cat] = {
                'mean_pct': round(mean_v, 2), 'std_pct': round(std_v, 2),
                'n': len(vals), 'hit_rate': round(hit, 3),
                'hold_days': hold,
            }

    decile_spread = None
    pol_rows = [r for r in all_feat if r['n_count'] >= 2]
    if len(pol_rows) >= 25:
        sorted_pol = sorted(pol_rows, key=lambda r: r['polarity'])
        bsz = max(1, len(sorted_pol) // 5)
        deciles = []
        for i in range(5):
            chunk = sorted_pol[i*bsz: (i+1)*bsz] if i < 4 else sorted_pol[i*bsz:]
            if chunk:
                m = sum(r['forward'] for r in chunk) / len(chunk)
                deciles.append({
                    'q': i + 1,
                    'mean_pol': round(sum(r['polarity'] for r in chunk) / len(chunk), 1),
                    'mean_forward_pct': round(m, 2),
                    'n': len(chunk),
                })
        decile_spread = {
            'quintiles': deciles,
            'q5_minus_q1_pct': round(deciles[-1]['mean_forward_pct'] - deciles[0]['mean_forward_pct'], 2)
                if len(deciles) == 5 else None,
        }

    mystery_count = sum(1 for r in all_feat if abs(r['mom5']) >= 3 and r['n_count'] <= 1)
    mystery_avg_fwd = (sum(r['forward'] for r in all_feat
                           if abs(r['mom5']) >= 3 and r['n_count'] <= 1)
                      / max(1, mystery_count)) if mystery_count >= 5 else None

    # ────────────────────────────────────────────────────────────────
    # 회귀 분석 (Logistic + Linear) — 2026-06 사용자 요청
    # X : [shrink_polarity, density, sub_ratio, src_avg, specificity, mom5, mom20]
    # y_alpha (linear)      : forward - bench_forward  (KOSPI 대비 초과수익)
    # y_ret (linear)        : forward                  (절대 수익)
    # y_outperform (binary) : alpha > 0                (KOSPI 이김?)
    # y_strong_up (binary)  : forward > 2              (절대 +2% 이상 상승?)
    # ────────────────────────────────────────────────────────────────
    regression = None
    try:
        rows = [r for r in all_feat if r['n_count'] >= 1]
        if len(rows) >= 50:
            import numpy as np
            from sklearn.linear_model import LogisticRegression, LinearRegression
            from sklearn.metrics import (accuracy_score, precision_score, recall_score,
                                          f1_score, r2_score, mean_squared_error)
            from sklearn.preprocessing import StandardScaler
            from sklearn.model_selection import train_test_split

            # 뉴스-only (가격 모멘텀·섹터 제외)
            news_feat_names = ['shrink_polarity', 'density', 'sub_ratio',
                               'src_avg', 'specificity', 's_polarity', 'reactive_ratio']
            # FULL (개별 뉴스 + 가격 모멘텀 + 섹터 컨텍스트)
            full_feat_names = ['shrink_polarity', 'density', 'sub_ratio',
                               'src_avg', 'specificity', 's_polarity', 'reactive_ratio',
                               'mom5', 'mom20',
                               'sector_polarity', 'sector_mom5']
            X_news_list, X_full_list = [], []
            y_alpha, y_sector_alpha, y_past = [], [], []
            y_alpha_1, y_alpha_20 = [], []      # horizon 비교 (None 가능)
            for r in rows:
                pn = r['polarity']; n = r['n_count']
                diff = pn / 100.0 * n
                shrink_pol = (diff / (n + 5)) * 100
                sub_ratio = r['s_count'] / max(1, n)
                X_news_list.append([shrink_pol, r['density'], sub_ratio,
                                    r['src_avg'], r['specificity'],
                                    r['s_polarity'], r['reactive_ratio']])
                X_full_list.append([shrink_pol, r['density'], sub_ratio,
                                    r['src_avg'], r['specificity'],
                                    r['s_polarity'], r['reactive_ratio'],
                                    r['mom5'], r['mom20'],
                                    r['sector_polarity'], r['sector_mom5']])
                y_alpha.append(r['alpha'])              # KOSPI 대비
                y_sector_alpha.append(r['sector_alpha'])  # 섹터 평균 대비
                y_past.append(r['mom5'])                # 동시기 (과거 5일)
                y_alpha_1.append(r.get('alpha_1'))
                y_alpha_20.append(r.get('alpha_20'))

            X_news = np.array(X_news_list)
            X_full = np.array(X_full_list)
            y_a = np.array(y_alpha)
            y_sa = np.array(y_sector_alpha)
            y_p = np.array(y_past)
            y_out = (y_a > 0).astype(int)               # KOSPI 이김
            y_sout = (y_sa > 0).astype(int)             # 섹터 평균 이김
            y_past_up = (y_p > 0).astype(int)

            # ── 시계열 split (rows 는 rebalance 시간순) ──
            # random split 은 시점 간 autocorrelation 으로 leakage — 앞 75% train / 뒤 25% test
            cut = int(len(X_full) * 0.75)
            scaler_full = StandardScaler().fit(X_full[:cut])    # train 에만 fit (leakage 방지)
            X_full_s = scaler_full.transform(X_full)
            scaler_news = StandardScaler().fit(X_news[:cut])
            X_news_s = scaler_news.transform(X_news)

            Xftr, Xfte = X_full_s[:cut], X_full_s[cut:]
            yatr, yate = y_a[:cut], y_a[cut:]
            ysatr, ysate = y_sa[:cut], y_sa[cut:]
            yotr, yote = y_out[:cut], y_out[cut:]
            ysotr, ysote = y_sout[:cut], y_sout[cut:]
            Xntr, Xnte = X_news_s[:cut], X_news_s[cut:]
            yptr, ypte = y_p[:cut], y_p[cut:]
            yputr, ypute = y_past_up[:cut], y_past_up[cut:]

            def lin_block(Xtr, ytr, Xte, yte, label, names=full_feat_names):
                m = LinearRegression(); m.fit(Xtr, ytr)
                p_tr = m.predict(Xtr); p_te = m.predict(Xte)
                return {
                    'target': label,
                    'r2_train': round(float(r2_score(ytr, p_tr)), 4),
                    'r2_test': round(float(r2_score(yte, p_te)), 4),
                    'mse_test': round(float(mean_squared_error(yte, p_te)), 3),
                    'mean_y_test_pct': round(float(yte.mean()), 3),
                    'std_y_test_pct': round(float(yte.std()), 3),
                    'coefficients': {names[i]: round(float(m.coef_[i]), 4)
                                     for i in range(len(names))},
                    'intercept': round(float(m.intercept_), 4),
                }

            def log_block(Xtr, ytr, Xte, yte, label, names=full_feat_names):
                if len(set(ytr)) < 2 or len(set(yte)) < 2:
                    return {'target': label, 'error': 'single-class data'}
                m = LogisticRegression(max_iter=500, class_weight='balanced')
                m.fit(Xtr, ytr)
                pr = m.predict(Xte)
                base = float(yte.mean())  # positive class rate
                return {
                    'target': label,
                    'accuracy': round(float(accuracy_score(yte, pr)), 4),
                    'precision': round(float(precision_score(yte, pr, zero_division=0)), 4),
                    'recall': round(float(recall_score(yte, pr, zero_division=0)), 4),
                    'f1': round(float(f1_score(yte, pr, zero_division=0)), 4),
                    'baseline_positive_rate': round(base, 4),
                    'n_test_positive': int(yte.sum()),
                    'n_test_total': int(len(yte)),
                    'coefficients': {names[i]: round(float(m.coef_[0][i]), 4)
                                     for i in range(len(names))},
                    'intercept': round(float(m.intercept_[0]), 4),
                }

            regression = {
                'n_samples': int(len(X_full)),
                'n_train': int(len(Xftr)),
                'n_test': int(len(Xfte)),
                'horizon_days': hold,
                'full_feature_names': full_feat_names,
                'news_only_feature_names': news_feat_names,
                'note': ('Features standardized (Z-score). Logistic uses class_weight=balanced. '
                         'shrink_polarity = (bull-bear)/(n+5)*100 (Bayesian shrinkage). '
                         'FULL = 뉴스 + 가격 모멘텀 + 섹터 컨텍스트. NEWS_ONLY = 뉴스만. '
                         '절대 수익률 회귀는 제거됨 — KOSPI 대비 / 섹터 평균 대비만 사용.'),
                # ─── 미래 예측 (FULL: 뉴스+모멘텀+섹터) ───
                'linear_alpha_kospi':    lin_block(Xftr, yatr, Xfte, yate,
                                                  'forward_alpha (KOSPI 대비 %)'),
                'linear_alpha_sector':   lin_block(Xftr, ysatr, Xfte, ysate,
                                                  'forward_alpha (섹터 평균 대비 %)'),
                'logistic_beat_kospi':   log_block(Xftr, yotr, Xfte, yote,
                                                  'alpha > 0 (KOSPI 이김)'),
                'logistic_beat_sector':  log_block(Xftr, ysotr, Xfte, ysote,
                                                  'sector_alpha > 0 (섹터 평균 이김)'),
                # ─── 과거 설명 (뉴스만) ───
                'linear_past_news_only': lin_block(Xntr, yptr, Xnte, ypte,
                                                  'past mom5 (t-5→t, 뉴스만)',
                                                  names=news_feat_names),
                'logistic_past_news_only': log_block(Xntr, yputr, Xnte, ypute,
                                                  'past_up (mom5>0, 뉴스만)',
                                                  names=news_feat_names),
            }

            # ─── Horizon 비교 (1d / hold / 20d) — alpha 대상, valid rows 만 ───
            def horizon_block(y_list, label):
                mask = np.array([v is not None for v in y_list])
                if mask.sum() < 80:
                    return {'target': label, 'error': f'insufficient rows ({int(mask.sum())})'}
                Xh = X_full[mask]
                yh = np.array([v for v in y_list if v is not None])
                cut_h = int(len(Xh) * 0.75)
                sch = StandardScaler().fit(Xh[:cut_h])
                Xh_s = sch.transform(Xh)
                return lin_block(Xh_s[:cut_h], yh[:cut_h], Xh_s[cut_h:], yh[cut_h:], label)

            regression['horizon_comparison'] = {
                '1d':  horizon_block(y_alpha_1, 'forward_alpha 1일 (KOSPI 대비)'),
                f'{hold}d': {'target': f'forward_alpha {hold}일',
                             'r2_test': regression['linear_alpha_kospi']['r2_test'],
                             'r2_train': regression['linear_alpha_kospi']['r2_train']},
                '20d': horizon_block(y_alpha_20, 'forward_alpha 20일 (KOSPI 대비)'),
            }
    except Exception as e:
        regression = {'error': f'{type(e).__name__}: {e}'}

    # v21.3 — Regime-conditional alpha 분해
    regime_alpha = {}
    for rname, recs in regime_trades.items():
        if not recs: continue
        n = len(recs)
        long_avg = sum(r['long_ret'] for r in recs) / n * 100
        bench_avg = sum(r['bench_ret'] for r in recs) / n * 100
        alpha_avg = sum(r['alpha'] for r in recs) / n * 100
        win = sum(1 for r in recs if r['alpha'] > 0) / n * 100
        vixs = [r['vix'] for r in recs if r.get('vix') is not None]
        regime_alpha[rname] = {
            'n': n,
            'long_pct': round(long_avg, 2),
            'bench_pct': round(bench_avg, 2),
            'alpha_pct': round(alpha_avg, 2),
            'alpha_win_pct': round(win, 1),
            'vix_avg': round(sum(vixs)/len(vixs), 1) if vixs else None,
            'vix_range': [round(min(vixs),1), round(max(vixs),1)] if vixs else None,
        }

    return {
        'period': {'start': start_date, 'end': end_date, 'days': min_len},
        'config': {
            'top_n': top_n, 'top_k': top_k, 'hold': hold, 'use_news': use_news,
            'mode': mode, 'universe_mode': universe_mode,
            'cat_filter': list(cat_filter),
            'start_offset_days': start_offset_days,
            'eligible_stocks': len(series), 'rebalances': len(trades),
            'market': market.id,
        },
        'stats': {
            'total_return_pct': round(total_return, 2),
            'win_rate_pct': round(win_rate, 1),
            'sharpe_annualized': round(sharpe, 2),
            'max_drawdown_pct': round(mdd * 100, 2),
            'mean_per_rebalance_pct': round(mean_ret * 100, 2),
            'std_per_rebalance_pct': round(std_ret * 100, 2),
        },
        'ic_summary': ic_summary,
        'ic_orthogonality': ortho,
        'cat_halflife': cat_halflife,
        'decile_spread': decile_spread,
        'mystery_mover': {
            'n': mystery_count,
            'avg_forward_pct': round(mystery_avg_fwd, 2) if mystery_avg_fwd is not None else None,
        },
        'regression': regression,        # 2026-06
        'regime_alpha': regime_alpha,    # v21.3
        'benchmark': {
            'name': f'{market.benchmark_symbol} buy-and-hold',
            'total_return_pct': round(bench_total, 2),
            'curve': bench_equity,
        },
        'equity_curve': equity,
        'curve_ts': curve_dates,
        'trades_first': trades[:5],
        'trades_last': trades[-5:],
    }
