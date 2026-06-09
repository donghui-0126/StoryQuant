"""한국 시장 (KOSPI + KOSDAQ) 어댑터.

소스:
  - Universe / 시총 / 가격: Naver Finance 스크래핑 + Yahoo .KS/.KQ
  - 종목별 뉴스: m.stock.naver.com/api/news/stock/{code}
  - 시장 RSS: 12개 매체 (직접) + 8개 매체 (Google News 우회)
  - 키워드: 한국어 BULL/BEAR/SUBSTANTIVE/REACTIVE/CATEGORY
"""
import json
import re
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

from .base import MarketProvider
from ..utils.parsing import decode_entities


# ─── KR 신문사 RSS 매핑 ──────────────────────────────────
# 2026-04-30 검증된 작동 피드만. CF bot block / 404 매체는 제외.
RSS_FEEDS = {
    # 매일경제 (4 카테고리)
    'mk':          'https://www.mk.co.kr/rss/30000023/',
    'mk_econ':     'https://www.mk.co.kr/rss/30100041/',
    'mk_industry': 'https://www.mk.co.kr/rss/40300001/',
    'mk_general':  'https://www.mk.co.kr/rss/30000001/',
    # 파이낸셜뉴스
    'fnnews':   'https://www.fnnews.com/rss/r20/fn_realnews_stock.xml',
    'fn_econ':  'https://www.fnnews.com/rss/r20/fn_realnews_economy.xml',
    # 뉴시스
    'newsis':   'https://www.newsis.com/RSS/economy.xml',
    # 연합인포맥스
    'einfomax': 'https://news.einfomax.co.kr/rss/allArticle.xml',
    # 한겨레
    'hani':     'https://www.hani.co.kr/rss/economy/',
    # 시사저널 / 시사IN / KD프레스
    'sisajournal': 'https://www.sisajournal.com/rss/allArticle.xml',
    'sisain':   'https://www.sisain.co.kr/rss/allArticle.xml',
    'kdpress':  'https://www.kdpress.co.kr/rss/clickTop.xml',
    # ─── Google News RSS 우회 (직접 RSS 막힌 매체) ───
    'gn_hankyung':  'https://news.google.com/rss/search?q=site:hankyung.com+%EC%A6%9D%EA%B6%8C&hl=ko&gl=KR&ceid=KR:ko',
    'gn_chosunbiz': 'https://news.google.com/rss/search?q=site:biz.chosun.com&hl=ko&gl=KR&ceid=KR:ko',
    'gn_yna':       'https://news.google.com/rss/search?q=site:yna.co.kr+%EA%B2%BD%EC%A0%9C&hl=ko&gl=KR&ceid=KR:ko',
    'gn_sedaily':   'https://news.google.com/rss/search?q=site:sedaily.com+%EC%A6%9D%EA%B6%8C&hl=ko&gl=KR&ceid=KR:ko',
    'gn_edaily':    'https://news.google.com/rss/search?q=site:edaily.co.kr+%EC%A6%9D%EA%B6%8C&hl=ko&gl=KR&ceid=KR:ko',
    'gn_mt':        'https://news.google.com/rss/search?q=site:mt.co.kr+%EC%A6%9D%EA%B6%8C&hl=ko&gl=KR&ceid=KR:ko',
    'gn_asiae':     'https://news.google.com/rss/search?q=site:asiae.co.kr+%EA%B2%BD%EC%A0%9C&hl=ko&gl=KR&ceid=KR:ko',
    'gn_herald':    'https://news.google.com/rss/search?q=site:heraldcorp.com+%EA%B2%BD%EC%A0%9C&hl=ko&gl=KR&ceid=KR:ko',
    # ─── 신규 추가 (2026-05-04) ───
    'gn_chosun':    'https://news.google.com/rss/search?q=site:chosun.com+%EA%B2%BD%EC%A0%9C&hl=ko&gl=KR&ceid=KR:ko',
    'gn_donga':     'https://news.google.com/rss/search?q=site:donga.com+%EA%B2%BD%EC%A0%9C&hl=ko&gl=KR&ceid=KR:ko',
    'gn_joongang':  'https://news.google.com/rss/search?q=site:joongang.co.kr+%EA%B2%BD%EC%A0%9C&hl=ko&gl=KR&ceid=KR:ko',
    'gn_kbs':       'https://news.google.com/rss/search?q=site:news.kbs.co.kr+%EA%B2%BD%EC%A0%9C&hl=ko&gl=KR&ceid=KR:ko',
    'gn_sbs':       'https://news.google.com/rss/search?q=site:news.sbs.co.kr+%EA%B2%BD%EC%A0%9C&hl=ko&gl=KR&ceid=KR:ko',
    'gn_mbc':       'https://news.google.com/rss/search?q=site:imnews.imbc.com+%EA%B2%BD%EC%A0%9C&hl=ko&gl=KR&ceid=KR:ko',
    'gn_ytn':       'https://news.google.com/rss/search?q=site:ytn.co.kr+%EA%B2%BD%EC%A0%9C&hl=ko&gl=KR&ceid=KR:ko',
    'gn_jtbc':      'https://news.google.com/rss/search?q=site:news.jtbc.co.kr+%EA%B2%BD%EC%A0%9C&hl=ko&gl=KR&ceid=KR:ko',
    'gn_moneys':    'https://news.google.com/rss/search?q=site:moneys.mt.co.kr+%EC%A6%9D%EA%B6%8C&hl=ko&gl=KR&ceid=KR:ko',
    'gn_thebell':   'https://news.google.com/rss/search?q=site:thebell.co.kr&hl=ko&gl=KR&ceid=KR:ko',
    'gn_inews':     'https://news.google.com/rss/search?q=site:inews24.com+%EC%A6%9D%EA%B6%8C&hl=ko&gl=KR&ceid=KR:ko',
    'gn_etoday':    'https://news.google.com/rss/search?q=site:etoday.co.kr+%EC%A6%9D%EA%B6%8C&hl=ko&gl=KR&ceid=KR:ko',
}

GNEWS_PAPER_MAP = {
    'gn_hankyung':  '한경',
    'gn_chosunbiz': '조선비즈',
    'gn_yna':       '연합',
    'gn_sedaily':   '서경',
    'gn_edaily':    '이데일리',
    'gn_mt':        '머투',
    'gn_asiae':     '아시아경제',
    'gn_herald':    '헤럴드',
    'gn_chosun':    '조선일보',
    'gn_donga':     '동아일보',
    'gn_joongang':  '중앙일보',
    'gn_kbs':       'KBS',
    'gn_sbs':       'SBS',
    'gn_mbc':       'MBC',
    'gn_ytn':       'YTN',
    'gn_jtbc':      'JTBC',
    'gn_moneys':    '머니S',
    'gn_thebell':   '더벨',
    'gn_inews':     '아이뉴스24',
    'gn_etoday':    '이투데이',
}

# 시드 KR_TICKERS — universe loader 실패 시 fallback.
SEED_TICKERS = {
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
}

# ─── 분류 키워드 (한국어) ──────────────────────────────────
BULL_KEYS = ['급등','상승','돌파','신고가','강세','반등','상한가','최고가','호재','어닝서프라이즈','서프라이즈','흑자전환','흑자','수주','수출 증가','실적개선','실적 개선','최대실적','사상최대','사상 최대','역대 최대','성장','확대','증가','급증','신기록','매수','상향','목표가 상향','투자의견 상향','비중확대','추천','수혜','기대감','낙관','긍정적','승인','통과','체결','신규상장','재상장','편입']
BEAR_KEYS = ['급락','하락','폭락','약세','조정','하한가','최저가','신저가','악재','어닝쇼크','쇼크','적자','적자전환','감익','역성장','실적부진','실적 부진','어닝미스','가이던스 하향','수주 감소','감소','축소','둔화','위축','매도','하향','목표가 하향','투자의견 하향','비중축소','비관','리스크','우려','부정적','경계','규제','금지','제재','벌금','기소','조사','수사','압수수색','상장폐지','거래정지','감자','워크아웃','법정관리']

REACTIVE_KEYS = [
    '급등','급락','폭등','폭락','강세','약세','반등','반락',
    '상승세','하락세','오름세','내림세','상승전환','하락전환',
    '신고가','신저가','52주 신고','52주 신저','상한가','하한가',
    '랠리','폭주','급반등','급락세',
    '차트','캔들','저항선','지지선','골든크로스','데드크로스',
    '특징주','관심주','이슈주','테마주 부각',
    '거래량 급증','거래량 폭증','대량매수','대량매도',
    '주가 급등','주가 폭등','주가 강세','주가 상승','주가 하락',
]
SUBSTANTIVE_KEYS = [
    '영업이익','영업익','매출','순익','순이익','EPS','어닝서프라이즈','어닝쇼크',
    '컨센서스','가이던스','분기 실적','연간 실적','실적 발표',
    '수주','계약','체결','공급','MOU','파트너십','협력 체결','합작',
    '신제품','출시','런칭','공개','발표','선보여',
    '인수','합병','M&A','매각','지분 매입','지분 인수','블록딜',
    '임상','FDA','승인','신약','특허','품목허가','3상','2상','1상',
    '규제','제재','벌금','기소','조사','수사','압수수색',
    '대표','CEO','회장','사임','선임','이사회','인사','임원변경',
    '배당','자사주 매입','자사주 소각','유상증자','무상증자','감자',
    '주총','주주총회','주식 분할','액면분할',
    '정책','법안','국회','예산','규제 완화','지원','보조금',
    'AI 모델','신기술','특허 등록','개발 성공','개발성공',
    '투자 유치','자금 조달','상장','IPO','공모',
]

CATEGORY_KEYS = {
    '실적': ('영업이익', '영업익', '매출', '순이익', 'EPS', '어닝', '컨센서스', '가이던스',
            '분기 실적', '연간 실적', '실적 발표', '흑자전환', '적자전환', '사상최대', '사상 최대'),
    'M&A': ('인수', '합병', 'M&A', '매각', '지분 매입', '지분 인수', '블록딜', '경영권', '딜'),
    '임상·규제': ('임상', 'FDA', '신약', '품목허가', '3상', '2상', '1상', '특허',
                '규제', '제재', '벌금', '기소', '조사', '수사', '압수수색', '리콜', '승인'),
    '인사·거버넌스': ('대표', 'CEO', '회장', '사임', '선임', '이사회', '임원', '주총',
                    '주주총회', '경영', '이사 선임'),
    '배당·자본': ('배당', '자사주', '소각', '유상증자', '무상증자', '감자', '액면분할', '주식 분할'),
    '신제품·사업': ('수주', '계약', '체결', '공급', 'MOU', '파트너십', '협력', '신제품',
                  '출시', '런칭', '공개', '발표', '신기술', 'AI 모델', '개발 성공'),
    # v21.2 — 거시·지정학
    '거시·지정학': (
        # 전쟁/지정학
        '전쟁', '침공', '공습', '미사일', '드론', '핵', '도발', '휴전', '평화협정',
        '우크라이나', '러시아', '이스라엘', '이란', '하마스', '대만 해협', '북한',
        '제재', '봉쇄', '관세', '무역전쟁', '수출통제', '디커플링', 'TIKTOK 금지',
        # 통화/금리
        '연준', 'Fed', 'FOMC', '금리 인상', '금리 인하', '기준금리',
        '한은', '한국은행', '베이시스 포인트', 'bp', '국채', '채권 금리',
        # 인플레/경기
        'CPI', 'PPI', '인플레', '디플레', '실업률', 'GDP', '경기침체', '리세션',
        '경기지표', '소비자물가', '고용지표', '소매판매',
        # 원자재
        '원유', '유가', 'WTI', '브렌트유', 'OPEC', 'OPEC+', '감산', '증산',
        '천연가스', '구리', '금값', '농산물',
        # 정치/정책
        '대선', '탄핵', '대통령', '백악관', '의회', '연방정부', '셧다운',
        '환율', '달러 강세', '달러 약세', '엔저', '위안화',
    ),
}

ROUTINE_KEYS = ('실적 발표', '분기 실적', '컨센서스', '예상', '전망', '가이던스')
BIG_SURPRISE_KEYS = ('서프라이즈', '쇼크', '급증', '급감', '사상 최대', '사상최대', '역대 최대',
                     '리콜', '소송', '제재', '벌금', '압수수색', '구속', '기소', '배임', '횡령',
                     'M&A', '인수', '합병', 'FDA', '품목허가', '특허 승인', '신고가', 'IPO',
                     '회장 사임', '대표 사임', '갑작스럽', '돌연')

SOURCE_PRIORS = {
    # Tier 1: 통신사 (가장 신뢰)
    '연합뉴스': 1.00, '연합인포맥스': 0.95, 'yna': 1.00, '연합': 1.00,
    # Tier 1: 정통 일간지 + 경제지
    '한국경제': 0.92, '한경': 0.92, 'hankyung': 0.92,
    '매일경제': 0.92, '매경': 0.92, 'mk': 0.92,
    '조선일보': 0.90, '동아일보': 0.88, '중앙일보': 0.88,
    '조선비즈': 0.85,
    # Tier 1: 공중파 방송사
    'KBS': 0.88, 'SBS': 0.85, 'MBC': 0.82, 'YTN': 0.85, 'JTBC': 0.82,
    # Tier 2: 경제 매체
    '이데일리': 0.85, 'edaily': 0.85,
    '서울경제': 0.82, 'sedaily': 0.82, '서경': 0.82,
    '파이낸셜뉴스': 0.80, 'fnnews': 0.80,
    '뉴시스': 0.85, 'newsis': 0.85,
    '머니투데이': 0.75, 'mt': 0.75, '머투': 0.75,
    '아시아경제': 0.72,
    '헤럴드경제': 0.72, '헤럴드': 0.72,
    # Tier 2: 신규 추가
    '머니S': 0.70,
    '더벨': 0.78,                   # M&A·딜 전문 — 알파 잠재력 ↑
    '이투데이': 0.68,
    '아이뉴스24': 0.65,
    # Tier 3: 일반·웹
    'GNews': 0.55, 'gnews': 0.55,
    '한겨레': 0.78, 'hani': 0.78,
    '시사저널': 0.65, 'sisajournal': 0.65,
    '시사IN': 0.65, 'sisain': 0.65,
    'KD프레스': 0.50, 'kdpress': 0.50,
}


# ─── KR 종목 → 섹터 매핑 (시총 상위 + ETF + 주요 종목) ──────
KR_SECTOR_MAP = {
    # ── tech / 반도체 / IT ──
    '005930': 'tech', '000660': 'tech', '042700': 'tech', '058470': 'tech',
    '035420': 'tech', '035720': 'tech', '009150': 'tech', '005935': 'tech',
    '034730': 'tech',  # SK (지주, IT 자회사 중심) — financials 도 가능하나 SK 본질 IT
    '066570': 'tech',  # LG전자
    '011070': 'tech',  # LG이노텍
    '009830': 'tech',  # 한화솔루션 (전기·전자)
    '393890': 'tech',  # 파라텍 — IT
    '418550': 'tech',  # 제이오 (배터리 부품)
    '413640': 'tech', '432320': 'tech', '462520': 'tech',
    '014620': 'tech',  # SG등급 (전자부품)
    '058610': 'tech',  # SG&G
    '256940': 'tech',  # 케이피에스 (반도체장비)
    '418420': 'tech', '420770': 'tech',  # 기가비스 (반도체검사장비)
    '950140': 'tech',  # 잉글우드랩
    '108860': 'tech',  # 셀바스AI
    '034830': 'tech', '267850': 'tech', '060720': 'tech',
    '278280': 'tech', '396270': 'tech', '347860': 'tech',
    # ETF — 섹터별
    '091160': 'tech',         # KODEX 반도체
    '395160': 'tech',         # KODEX AI반도체TOP2플러스
    '102780': 'tech',         # KODEX 삼성그룹
    '305720': 'battery',      # KODEX 2차전지산업
    '091170': 'financials',   # KODEX 은행
    '244620': 'consumer',     # KODEX 게임
    '139220': 'industrials',  # TIGER 200 건설기계
    '139260': 'tech',         # TIGER 200 IT
    '139250': 'industrials',  # TIGER 200 산업재
    '278540': 'tech',         # KODEX MSCI Korea TR — proxy로 IT 우세
    # ── 2차전지 / 에너지소재 ──
    '373220': 'battery', '006400': 'battery', '247540': 'battery',
    '003670': 'battery', '051910': 'chemicals', '454910': 'battery',
    '450080': 'battery',  # 에코프로머티
    # ── 자동차 ──
    '005380': 'auto', '000270': 'auto', '012330': 'auto',
    '161390': 'auto',  # 한국타이어앤테크놀로지
    '011210': 'auto',  # 현대위아
    '204320': 'auto',  # 만도
    # ── 조선·방산·항공 ──
    '042660': 'defense', '009540': 'defense', '010140': 'defense',
    '012450': 'defense', '079550': 'defense', '047810': 'defense',
    '329180': 'defense',  # HD현대중공업
    '241560': 'defense',  # 두산밥캣
    '034020': 'utility',  # 두산에너빌리티 (원자력)
    '298690': 'defense',  # 에어부산
    '003490': 'transport', # 대한항공
    # ── 에너지·전력·원자력 ──
    '015760': 'utility', '267260': 'utility', '010120': 'utility',
    '021240': 'utility',  # 코웨이
    '052690': 'utility',  # 한전기술
    '298050': 'utility',  # 효성첨단소재
    # ── 화학·소재·정유 ──
    '005490': 'materials', '009830': 'chemicals',  # 한화솔루션
    '096770': 'chemicals',  # SK이노베이션
    '010950': 'chemicals',  # S-Oil
    '011170': 'chemicals',  # 롯데케미칼
    '298000': 'chemicals',  # 효성화학
    '298020': 'chemicals',  # 효성티앤씨
    '011790': 'chemicals',  # SKC
    '004020': 'materials',  # 현대제철
    '014820': 'materials',  # 동원시스템즈
    '003410': 'materials',  # 쌍용씨앤이
    # ── 금융·은행·증권·보험 ──
    '105560': 'financials', '055550': 'financials', '086790': 'financials',
    '316140': 'financials', '323410': 'financials',
    '024110': 'financials',  # 기업은행
    '139130': 'financials',  # DGB금융지주
    '138930': 'financials',  # BNK금융지주
    '175330': 'financials',  # JB금융지주
    '030200': 'telecom',     # KT (telecom 분류 더 정확)
    '029780': 'financials',  # 삼성카드
    '032830': 'financials',  # 삼성생명
    '000810': 'financials',  # 삼성화재
    '001450': 'financials',  # 현대해상
    '005830': 'financials',  # DB손해보험
    '088350': 'financials',  # 한화생명
    '006800': 'financials',  # 미래에셋증권
    '016360': 'financials',  # 삼성증권
    '030610': 'financials',  # 교보증권
    '039490': 'financials',  # 키움증권
    '071050': 'financials',  # 한국금융지주
    '003540': 'financials',  # 대신증권
    '034730_2': 'financials',
    # ── 바이오·제약·헬스케어 ──
    '207940': 'healthcare', '068270': 'healthcare', '196170': 'healthcare',
    '028300': 'healthcare', '326030': 'healthcare',
    '009420': 'healthcare',  # 한올바이오파마
    '048410': 'healthcare',  # 현대바이오랜드
    '085660': 'healthcare',  # 차바이오텍
    '237690': 'healthcare',  # 에스티팜
    '298380': 'healthcare',  # 에이비엘바이오
    '328130': 'healthcare',  # 루닛
    '145020': 'healthcare',  # 휴젤
    '214150': 'healthcare',  # 클래시스
    '950130': 'healthcare',  # 엑세스바이오
    '950160': 'healthcare',  # 코오롱티슈진
    '383310': 'healthcare',  # 에코프로에이치엔
    '048260': 'healthcare',  # 오스템임플란트
    '041830': 'healthcare',  # 인성정보
    # ── 소비재·엔터·게임 ──
    '352820': 'consumer', '259960': 'consumer', '036570': 'consumer',
    '041510': 'consumer',  # SM
    '122870': 'consumer',  # 와이지엔터테인먼트
    '035900': 'consumer',  # JYP엔터
    '293490': 'consumer',  # 카카오게임즈
    '263750': 'consumer',  # 펄어비스
    '194480': 'consumer',  # 데브시스터즈
    '251270': 'consumer',  # 넷마블
    '376300': 'consumer',  # 디어유
    '253450': 'consumer',  # 스튜디오드래곤
    '028260': 'consumer',  # 삼성물산 (가구·패션 부문)
    '004990': 'consumer',  # 롯데
    '023530': 'consumer',  # 롯데쇼핑
    '139480': 'consumer',  # 이마트
    '004170': 'consumer',  # 신세계
    '161890': 'consumer',  # 한국콜마
    '090430': 'consumer',  # 아모레퍼시픽
    '051900': 'consumer',  # LG생활건강
    '003230': 'consumer',  # 삼양식품
    '004370': 'consumer',  # 농심
    '097950': 'consumer',  # CJ제일제당
    '001680': 'consumer',  # 대상
    # 엔터 (consumer 세부)
    '086520': 'consumer',  # 에코프로 (소비재 + 화학) — battery로 분류
    # ── 운송·물류 ──
    '011200': 'transport', '028670': 'transport',  # 팬오션
    '000120': 'transport',  # CJ대한통운
    '180640': 'transport',  # 한진칼
    # ── 통신 ──
    '030200': 'telecom',  # KT
    '017670': 'telecom',  # SK텔레콤
    '032640': 'telecom',  # LG유플러스
    # ── 산업재 ──
    '028260_2': 'industrials',  # 삼성물산 (건설 부문)
    '000720': 'industrials',  # 현대건설
    '047040': 'industrials',  # 대우건설
    '375500': 'industrials',  # DL이앤씨
    '006360': 'industrials',  # GS건설
    '028050': 'industrials',  # 삼성E&A
    '241590': 'industrials',  # 화승엔터프라이즈
}

# KR Macro regime → sector 영향
# +1.0 = 강한 호재 / -1.0 = 강한 악재 / 0 = 중립
KR_MACRO_SECTOR_IMPACT = {
    'risk_off': {
        'defense': +0.6, 'utility': +0.3, 'consumer': +0.1,    # 방어주·필수재
        'tech': -0.5, 'battery': -0.4, 'auto': -0.4, 'transport': -0.5,
        'financials': -0.3, 'chemicals': -0.3,
    },
    'risk_on': {
        'tech': +0.5, 'battery': +0.4, 'auto': +0.3, 'consumer': +0.3,
        'transport': +0.4, 'chemicals': +0.2,
        'defense': -0.2, 'utility': -0.2,
    },
    'oil_up': {
        'utility': +0.4, 'chemicals': +0.3,                   # KR은 에너지 직접노출 적음
        'transport': -0.6, 'auto': -0.3, 'consumer': -0.2,    # 항공·해운·운송 비용↑
    },
    'rate_up': {
        'financials': +0.5,                                   # 은행 NIM↑
        'tech': -0.4, 'battery': -0.3, 'consumer': -0.2,      # 성장주·내구재 부담
        'utility': -0.3,                                      # 부채 많음
    },
    'krw_weak': {
        'auto': +0.5, 'tech': +0.4, 'chemicals': +0.3,        # 수출주
        'financials': -0.2, 'consumer': -0.2,                 # 수입 비용↑
    },
}


class KrMarket(MarketProvider):
    id = 'kr'
    name = '한국 (KOSPI + KOSDAQ)'
    currency = 'KRW'
    tz_offset_hours = 9
    benchmark_symbol = '^KS11'
    market_open_hour = 9.0
    market_close_hour = 15.5
    locale = 'ko-KR'
    other_category = '기타'
    sector_map = KR_SECTOR_MAP
    macro_sector_impact = KR_MACRO_SECTOR_IMPACT

    bull_keys = BULL_KEYS
    bear_keys = BEAR_KEYS
    substantive_keys = SUBSTANTIVE_KEYS
    reactive_keys = REACTIVE_KEYS
    category_keys = CATEGORY_KEYS
    routine_keys = ROUTINE_KEYS
    big_surprise_keys = BIG_SURPRISE_KEYS
    source_priors = SOURCE_PRIORS

    def __init__(self):
        super().__init__()
        # seed universe — fetch_universe 성공 후 덮어씀
        self._universe_cache = {c: {'name': n, 'market': '?'} for c, n in SEED_TICKERS.items()}

    # ───────── universe ─────────
    def fetch_universe(self, top_per_market=200):
        """Naver 시가총액 페이지 스크래핑."""
        out = {}
        pages = (top_per_market + 49) // 50
        sock_pat = re.compile(r'<a[^>]+href="/item/main\.naver\?code=(\d{6})"[^>]*>([^<]+)</a>')

        def fetch_one(market_code, page):
            market_name = 'KOSPI' if market_code == 0 else 'KOSDAQ'
            url = f'https://finance.naver.com/sise/sise_market_sum.naver?sosok={market_code}&page={page}'
            try:
                req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 StoryQuant'})
                with urllib.request.urlopen(req, timeout=8) as r:
                    raw = r.read()
                html = raw.decode('euc-kr', errors='replace')
                results = []
                for m in sock_pat.finditer(html):
                    code, name = m.group(1), decode_entities(m.group(2)).strip()
                    if name:
                        results.append({'code': code, 'name': name, 'market': market_name})
                return results
            except Exception:
                return []

        with ThreadPoolExecutor(max_workers=6) as ex:
            futs = []
            for market in (0, 1):
                for p in range(1, pages + 1):
                    futs.append(ex.submit(fetch_one, market, p))
            for f in as_completed(futs):
                for item in f.result():
                    if item['code'] not in out:
                        out[item['code']] = item
        return out

    # ───────── feeds ─────────
    def get_rss_feeds(self):
        return RSS_FEEDS

    def get_paper_map(self):
        return GNEWS_PAPER_MAP

    # ───────── 가격 ─────────
    def format_yahoo_symbol(self, code):
        """KR 6자리 코드 → 'XXXXXX.KS' / 'XXXXXX.KQ' (호출 측이 try-both 패턴 사용 권장).
           ^KS11 같은 인덱스 / =X FX 그대로."""
        if code.startswith('^') or code.endswith('=X') or '.' in code:
            return code
        return code + '.KS'

    def yahoo_symbol_candidates(self, code):
        """Yahoo Finance 시도 순서. KR은 KOSPI / KOSDAQ 둘 다."""
        if code.startswith('^') or code.endswith('=X') or '.' in code:
            return [code]
        return [code + '.KS', code + '.KQ']

    # ───────── 종목 뉴스 ─────────
    def fetch_stock_news_native(self, code, page=1, page_size=20):
        """Naver mobile API: m.stock.naver.com/api/news/stock/{code}."""
        url = f'https://m.stock.naver.com/api/news/stock/{code}?pageSize={page_size}&page={page}'
        try:
            req = urllib.request.Request(url, headers={
                'User-Agent': 'Mozilla/5.0 (iPhone) AppleWebKit/605 Mobile',
                'Accept': 'application/json,text/plain,*/*',
                'Referer': 'https://m.stock.naver.com/',
            })
            with urllib.request.urlopen(req, timeout=8) as r:
                raw = r.read()
            j = json.loads(raw.decode('utf-8', errors='replace'))
        except Exception:
            return []
        articles = []
        for cluster in (j if isinstance(j, list) else []):
            for it in cluster.get('items', []):
                title = decode_entities(it.get('title', '')).strip()
                if not title:
                    continue
                body_text = decode_entities(it.get('body', '')).strip()
                dt_str = it.get('datetime', '')
                ts = int(time.time() * 1000)
                try:
                    from datetime import datetime, timezone, timedelta
                    dt = datetime.strptime(dt_str, '%Y%m%d%H%M').replace(
                        tzinfo=timezone(timedelta(hours=9)))
                    ts = int(dt.timestamp() * 1000)
                except Exception:
                    pass
                link = it.get('mobileNewsUrl') or it.get('linkUrl') or ''
                articles.append({
                    'title': title,
                    'body': body_text[:200],
                    'link': link,
                    'paper': it.get('officeName', ''),
                    'ts': ts,
                })
        return articles

    # ───────── 시총 ─────────
    def fetch_marketcap(self, codes):
        """Naver Finance 스크래핑. 시총·PER·외국인지분율 추출."""
        def parse_kr_amount(s):
            s = (s or '').strip()
            total = 0
            m = re.search(r'([\d,]+)\s*조', s)
            if m:
                total += int(m.group(1).replace(',', '')) * 10**12
            m = re.search(r'([\d,]+)\s*억', s)
            if m:
                total += int(m.group(1).replace(',', '')) * 10**8
            if total == 0:
                m = re.search(r'([\d,]+)', s)
                if m:
                    total = int(m.group(1).replace(',', ''))
            return total or None

        def fetch_one(code):
            url = f'https://finance.naver.com/item/main.naver?code={code}'
            try:
                req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
                with urllib.request.urlopen(req, timeout=6) as r:
                    raw = r.read()
                html = raw.decode('utf-8', errors='replace')
            except Exception as e:
                return {'code': code, 'error': str(e)[:60]}
            cap = None
            m = re.search(r'<em[^>]*id="_market_sum"[^>]*>([\s\S]*?)</em>', html)
            if m:
                cap = parse_kr_amount(re.sub(r'<[^>]+>', '', m.group(1)))
            if not cap:
                m = re.search(r'<th[^>]*>\s*시가총액\s*</th>\s*<td[^>]*>(.*?)</td>', html, re.S)
                if m:
                    cap = parse_kr_amount(re.sub(r'<[^>]+>', '', m.group(1)))
            pe = None
            m = re.search(r'<em[^>]*id="_per"[^>]*>([\d,.\-]+)</em>', html)
            if m:
                try: pe = float(m.group(1).replace(',', ''))
                except: pass
            fpct = None
            m = re.search(r'외국인.*?소진율.*?<em[^>]*>([\d.]+)</em>', html, re.S)
            if m:
                try: fpct = float(m.group(1))
                except: pass
            name = None
            m = re.search(r'<div class="wrap_company">.*?<h2>.*?<a[^>]*>([^<]+)</a>', html, re.S)
            if m: name = m.group(1).strip()
            last = None
            m = re.search(r'<p class="no_today">.*?<span class="no_up\b[^"]*"[^>]*>(.*?)</span>', html, re.S)
            if m:
                try:
                    num = re.sub(r'<[^>]+>', '', m.group(1))
                    last = int(num.replace(',', '').strip())
                except: pass
            if not last:
                m = re.search(r'class="blind">([\d,]+)</span>', html)
                if m:
                    try: last = int(m.group(1).replace(',', ''))
                    except: pass
            return {'code': code, 'name': name, 'last': last, 'marketCap': cap,
                    'pe': pe, 'foreignPct': fpct}

        with ThreadPoolExecutor(max_workers=10) as ex:
            futs = [ex.submit(fetch_one, c) for c in codes[:80]
                    if not (c.startswith('^') or c.endswith('=X'))]
            results = [f.result() for f in as_completed(futs)]
        return {'ts': int(time.time() * 1000), 'quotes': results, 'source': 'naver'}


provider = KrMarket()
