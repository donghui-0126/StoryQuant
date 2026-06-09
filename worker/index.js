/* ======================================================================
 *  StoryQuant API — Cloudflare Worker
 *
 *  GET /api/quote?codes=005930,000660,...&interval=1m&range=1d
 *      → Yahoo Finance v8 chart 프록시 (분봉 + 메타)
 *      Cache: 60s edge
 *
 *  GET /api/news?sources=hankyung,maeil,chosunbiz,edaily,yna&limit=80
 *      → 한국 신문사 RSS 크롤링 + 룰 기반 호재/악재 분류
 *      Cache: 120s edge
 *
 *  CORS: 모든 출처 허용 (Pages 도메인이든 로컬이든 사용 가능)
 * ====================================================================== */

const RSS_FEEDS = {
  hankyung:  'https://www.hankyung.com/feed/finance',
  maeil:     'https://www.mk.co.kr/rss/30000023/',
  chosunbiz: 'https://biz.chosun.com/site/data/rss/rss.xml',
  edaily:    'https://rss.edaily.co.kr/stock_news.xml',
  yna:       'https://www.yna.co.kr/RSS/economy.xml',
  sedaily:   'https://www.sedaily.com/RSS/Market.xml',
  fnnews:    'https://www.fnnews.com/rss/r20/fn_realnews_stock.xml',
  newsis:    'https://newsis.com/RSS/economy.xml'
};

// 종목코드 → 한글명 (RSS 헤드라인에서 자동 태깅)
const KR_TICKERS = {
  '005930':'삼성전자','000660':'SK하이닉스','373220':'LG에너지솔루션',
  '006400':'삼성SDI','051910':'LG화학','207940':'삼성바이오로직스',
  '068270':'셀트리온','005380':'현대차','000270':'기아',
  '005490':'POSCO홀딩스','003670':'포스코퓨처엠','012330':'현대모비스',
  '012450':'한화에어로스페이스','034020':'두산에너빌리티','267260':'HD현대일렉트릭',
  '010120':'LS ELECTRIC','079550':'LIG넥스원','047810':'한국항공우주',
  '042660':'한화오션','009540':'HD한국조선해양','010140':'삼성중공업',
  '066570':'LG전자','105560':'KB금융','055550':'신한지주',
  '086790':'하나금융지주','316140':'우리금융지주','035420':'네이버',
  '035720':'카카오','352820':'하이브','259960':'크래프톤',
  '036570':'엔씨소프트','086520':'에코프로','247540':'에코프로비엠',
  '196170':'알테오젠','058470':'리노공업','042700':'한미반도체',
  '011200':'HMM','015760':'한국전력','323410':'카카오뱅크',
  '028300':'HLB','326030':'SK바이오팜'
};

// 룰 기반 호재/악재 키워드 (HTML 쪽과 동일 규칙)
const BULL_KEYS = [
  '급등','상승','돌파','신고가','강세','반등','상한가','최고가',
  '호재','어닝서프라이즈','서프라이즈','흑자전환','흑자','수주','수출 증가',
  '실적개선','실적 개선','최대실적','사상최대','사상 최대','역대 최대',
  '성장','확대','증가','급증','신기록',
  '매수','상향','목표가 상향','투자의견 상향','비중확대','추천',
  '수혜','기대감','낙관','긍정적',
  '승인','통과','체결','신규상장','재상장','편입'
];
const BEAR_KEYS = [
  '급락','하락','폭락','약세','조정','하한가','최저가','신저가',
  '악재','어닝쇼크','쇼크','적자','적자전환','감익','역성장',
  '실적부진','실적 부진','어닝미스','가이던스 하향','수주 감소',
  '감소','축소','둔화','위축',
  '매도','하향','목표가 하향','투자의견 하향','비중축소','비관',
  '리스크','우려','부정적','경계',
  '규제','금지','제재','벌금','기소','조사','수사','압수수색',
  '상장폐지','거래정지','감자','워크아웃','법정관리'
];

function classifySentiment(text) {
  if (!text) return { sentiment: 'neut', score: 0 };
  let bull = 0, bear = 0;
  for (const k of BULL_KEYS) if (text.includes(k)) bull++;
  for (const k of BEAR_KEYS) if (text.includes(k)) bear++;
  const total = bull + bear;
  if (total === 0) return { sentiment: 'neut', score: 0 };
  const score = (bull - bear) / total;
  if (score > 0.2) return { sentiment: 'bull', score: +score.toFixed(2) };
  if (score < -0.2) return { sentiment: 'bear', score: +score.toFixed(2) };
  return { sentiment: 'neut', score: +score.toFixed(2) };
}

function tagTickers(text) {
  if (!text) return [];
  const out = [];
  for (const [code, name] of Object.entries(KR_TICKERS)) {
    if (text.includes(name)) out.push({ code, name });
  }
  return out;
}

/* ─── RSS 파싱 (정규식 기반, dependency 0) ─── */
function pick(body, re) {
  const m = body.match(re);
  if (!m) return '';
  return m[1].replace(/<!\[CDATA\[/, '').replace(/\]\]>/, '').trim();
}
function decode(s) {
  return (s || '')
    .replace(/&lt;/g, '<').replace(/&gt;/g, '>')
    .replace(/&amp;/g, '&').replace(/&quot;/g, '"')
    .replace(/&#(\d+);/g, (_, n) => String.fromCharCode(+n))
    .replace(/&apos;/g, "'");
}
function parseRSS(xml, sourceKey) {
  const items = [];
  const itemRe = /<item[^>]*>([\s\S]*?)<\/item>/g;
  let m;
  while ((m = itemRe.exec(xml))) {
    const body = m[1];
    const title = decode(pick(body, /<title[^>]*>([\s\S]*?)<\/title>/));
    const link = decode(pick(body, /<link[^>]*>([\s\S]*?)<\/link>/));
    const desc = decode(pick(body, /<description[^>]*>([\s\S]*?)<\/description>/));
    const pubDate = pick(body, /<pubDate[^>]*>([\s\S]*?)<\/pubDate>/);
    if (!title) continue;
    const cls = classifySentiment(title + ' ' + desc);
    items.push({
      source: sourceKey,
      title,
      link,
      ts: pubDate ? new Date(pubDate).getTime() : Date.now(),
      sentiment: cls.sentiment,
      score: cls.score,
      tickers: tagTickers(title + ' ' + desc)
    });
  }
  return items;
}

/* ─── /api/quote — Yahoo Finance v8 ─── */
async function handleQuote(url) {
  const codes = (url.searchParams.get('codes') || '').split(',').map(s => s.trim()).filter(Boolean);
  const interval = url.searchParams.get('interval') || '1m';
  const range = url.searchParams.get('range') || '1d';
  if (!codes.length) return jsonError('codes parameter required (e.g. ?codes=005930,000660)');

  // 6자리 KR 종목코드는 .KS 또는 .KQ 둘 중 하나로 시도
  // 인덱스/특수 심볼 통과: ^KS11(KOSPI), ^KQ11(KOSDAQ), KRW=X
  async function fetchOne(code) {
    const candidates = code.startsWith('^') || code.endsWith('=X')
      ? [code]
      : [code + '.KS', code + '.KQ'];
    for (const sym of candidates) {
      const u = `https://query1.finance.yahoo.com/v8/finance/chart/${encodeURIComponent(sym)}?interval=${interval}&range=${range}`;
      try {
        const r = await fetch(u, {
          headers: { 'User-Agent': 'Mozilla/5.0 (StoryQuant)', 'Accept': 'application/json' },
          cf: { cacheTtl: 60, cacheEverything: true }
        });
        if (!r.ok) continue;
        const j = await r.json();
        const result = j?.chart?.result?.[0];
        if (!result) continue;
        const meta = result.meta;
        const ts = result.timestamp || [];
        const q = result.indicators?.quote?.[0];
        if (!q) continue;
        const bars = ts.map((t, i) => ({
          t, o: q.open?.[i], h: q.high?.[i], l: q.low?.[i],
          c: q.close?.[i], v: q.volume?.[i]
        })).filter(b => b.c != null);
        return {
          code, symbol: sym,
          last: meta.regularMarketPrice,
          prev: meta.chartPreviousClose ?? meta.previousClose,
          currency: meta.currency,
          exchange: meta.exchangeName,
          bars
        };
      } catch (e) { /* try next candidate */ }
    }
    return { code, error: 'no_data' };
  }

  const results = await Promise.all(codes.slice(0, 50).map(fetchOne));
  return json({ ts: Date.now(), quotes: results }, { 'Cache-Control': 'public, max-age=60' });
}

/* ─── /api/news — RSS 멀티소스 수집 ─── */
async function handleNews(url) {
  const sourcesParam = url.searchParams.get('sources') || 'hankyung,maeil,chosunbiz,edaily,yna';
  const limit = Math.min(parseInt(url.searchParams.get('limit') || '60', 10), 200);
  const sources = sourcesParam.split(',').map(s => s.trim()).filter(s => RSS_FEEDS[s]);

  async function fetchOne(src) {
    try {
      const r = await fetch(RSS_FEEDS[src], {
        headers: { 'User-Agent': 'Mozilla/5.0 (StoryQuantBot/1.0; +RSS)' },
        cf: { cacheTtl: 120, cacheEverything: true }
      });
      if (!r.ok) return { src, error: 'http_' + r.status, items: [] };
      const xml = await r.text();
      return { src, items: parseRSS(xml, src) };
    } catch (e) {
      return { src, error: 'fetch_failed', items: [] };
    }
  }

  const all = await Promise.all(sources.map(fetchOne));
  const articles = [];
  const errors = [];
  for (const r of all) {
    if (r.error) errors.push({ source: r.src, error: r.error });
    articles.push(...r.items);
  }
  // 시간 역순
  articles.sort((a, b) => b.ts - a.ts);
  const trimmed = articles.slice(0, limit);

  // 통계
  const stats = {
    total: trimmed.length,
    bull: trimmed.filter(a => a.sentiment === 'bull').length,
    bear: trimmed.filter(a => a.sentiment === 'bear').length,
    neut: trimmed.filter(a => a.sentiment === 'neut').length,
    sources: sources.length,
    polarity: 0
  };
  if (stats.bull + stats.bear > 0) {
    stats.polarity = Math.round((stats.bull - stats.bear) / (stats.bull + stats.bear) * 100);
  }

  return json({ ts: Date.now(), stats, errors, articles: trimmed }, { 'Cache-Control': 'public, max-age=120' });
}

/* ─── 응답 헬퍼 ─── */
const CORS = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Methods': 'GET, OPTIONS',
  'Access-Control-Allow-Headers': 'Content-Type'
};
function json(obj, extra = {}) {
  return new Response(JSON.stringify(obj), {
    headers: { 'Content-Type': 'application/json; charset=utf-8', ...CORS, ...extra }
  });
}
function jsonError(msg, status = 400) {
  return new Response(JSON.stringify({ error: msg }), {
    status, headers: { 'Content-Type': 'application/json', ...CORS }
  });
}

export default {
  async fetch(request) {
    if (request.method === 'OPTIONS') return new Response(null, { headers: CORS });
    const url = new URL(request.url);
    try {
      if (url.pathname === '/api/quote') return await handleQuote(url);
      if (url.pathname === '/api/news')  return await handleNews(url);
      if (url.pathname === '/' || url.pathname === '/api') {
        return json({
          name: 'StoryQuant API',
          version: '1.0.0',
          endpoints: {
            '/api/quote': 'codes=005930,000660&interval=1m&range=1d',
            '/api/news':  'sources=hankyung,maeil,chosunbiz,edaily,yna&limit=60'
          },
          rss_sources: Object.keys(RSS_FEEDS)
        });
      }
      return new Response('Not Found', { status: 404, headers: CORS });
    } catch (e) {
      return jsonError('worker_error: ' + (e?.message || 'unknown'), 500);
    }
  }
};
