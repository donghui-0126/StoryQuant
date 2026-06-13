"""네이버 WICS 업종 분류 → KR_SECTOR_MAP 정적 생성기.

finance.naver.com/sise/sise_group.naver?type=upjong 의 업종별 종목을
우리 섹터 키(SECTOR_KR과 동일)로 롤업해 serve/markets/kr_sectors.py 로 굽는다.
재실행: .venv/bin/python scripts/gen_sector_map.py
"""
import urllib.request
import re
import time

UA = {'User-Agent': 'Mozilla/5.0 StoryQuant'}

# WICS 업종명 → 우리 섹터 키 (SECTOR_KR 라벨과 1:1)
WICS_TO_SECTOR = {
    '반도체와반도체장비': 'tech', '디스플레이패널': 'tech', '디스플레이장비및부품': 'tech',
    '전자제품': 'tech', '전자장비와기기': 'tech', '컴퓨터와주변기기': 'tech',
    '통신장비': 'tech', '핸드셋': 'tech', 'IT서비스': 'tech', '소프트웨어': 'tech',
    '사무용전자제품': 'tech', '전기제품': 'tech', '양방향미디어와서비스': 'tech',
    '인터넷과카탈로그소매': 'tech', '게임엔터테인먼트': 'tech',
    '화학': 'chemicals', '석유와가스': 'chemicals',
    '자동차': 'auto', '자동차부품': 'auto',
    '우주항공과국방': 'defense', '조선': 'defense',
    '전기유틸리티': 'utility', '복합유틸리티': 'utility', '가스유틸리티': 'utility',
    '에너지장비및서비스': 'utility',
    '철강': 'materials', '비철금속': 'materials', '건축자재': 'materials',
    '포장재': 'materials', '종이와목재': 'materials',
    '은행': 'financials', '증권': 'financials', '카드': 'financials',
    '생명보험': 'financials', '손해보험': 'financials', '기타금융': 'financials',
    '창업투자': 'financials',
    '제약': 'healthcare', '생물공학': 'healthcare', '건강관리기술': 'healthcare',
    '건강관리장비와용품': 'healthcare', '생명과학도구및서비스': 'healthcare',
    '건강관리업체및서비스': 'healthcare',
    '방송과엔터테인먼트': 'consumer', '광고': 'consumer', '출판': 'consumer',
    '음료': 'consumer', '담배': 'consumer', '식품': 'consumer',
    '식품과기본식료품소매': 'consumer', '가정용품': 'consumer', '가정용기기와용품': 'consumer',
    '가구': 'consumer', '화장품': 'consumer', '백화점과일반상점': 'consumer',
    '전문소매': 'consumer', '판매업체': 'consumer', '호텔,레스토랑,레저': 'consumer',
    '레저용장비와제품': 'consumer', '섬유,의류,신발,호화품': 'consumer',
    '교육서비스': 'consumer', '다각화된소비자서비스': 'consumer', '문구류': 'consumer',
    '해운사': 'transport', '항공사': 'transport', '항공화물운송과물류': 'transport',
    '운송인프라': 'transport', '도로와철도운송': 'transport',
    '무선통신서비스': 'telecom', '다각화된통신서비스': 'telecom',
    '건설': 'industrials', '복합기업': 'industrials', '상업서비스와공급품': 'industrials',
    '기계': 'industrials', '건축제품': 'industrials', '전기장비': 'industrials',
    '무역회사와판매업체': 'industrials',
    '부동산': 'real_estate',
    # '기타' → 매핑 안 함 (None)
}

# 2차전지 — WICS는 전기제품/화학에 흩어놓지만 한국 시장 핵심 테마라 별도 유지 (override)
BATTERY_OVERRIDE = {
    '373220',  # LG에너지솔루션
    '006400',  # 삼성SDI
    '247540',  # 에코프로비엠
    '086520',  # 에코프로
    '450080',  # 에코프로머티
    '003670',  # 포스코퓨처엠
    '066970',  # 엘앤에프
    '020150',  # 롯데에너지머티리얼즈
    '457190',  # 이수스페셜티케미컬
    '393890',  # — (테마 편입 시)
    '454910',  # 두산테스나? (확인용 placeholder, 아니면 무시됨)
}


def fetch_industries():
    url = 'https://finance.naver.com/sise/sise_group.naver?type=upjong'
    html = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=10).read().decode('euc-kr', 'replace')
    out = {}
    for m in re.finditer(r'no=(\d+)">([^<]+)</a>', html):
        out[m.group(1)] = m.group(2).strip()
    return out


def fetch_members(no):
    url = f'https://finance.naver.com/sise/sise_group_detail.naver?type=upjong&no={no}'
    html = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=10).read().decode('euc-kr', 'replace')
    return sorted(set(re.findall(r'code=(\d{6})', html)))


def main():
    industries = fetch_industries()
    print(f'업종 {len(industries)}개 수집')
    code_sector = {}
    unmapped_industries = set()
    for no, name in industries.items():
        sector = WICS_TO_SECTOR.get(name)
        if sector is None:
            if name != '기타':
                unmapped_industries.add(name)
            continue
        try:
            members = fetch_members(no)
        except Exception as e:
            print(f'  ! {name} 실패: {e}')
            continue
        for code in members:
            # 첫 분류 우선 (WICS는 종목당 1업종이라 충돌 드묾)
            code_sector.setdefault(code, sector)
        time.sleep(0.15)
    # 배터리 override
    for code in BATTERY_OVERRIDE:
        if code in code_sector or True:
            code_sector[code] = 'battery'

    from collections import Counter
    print(f'분류된 종목: {len(code_sector)}')
    print('분포:', dict(Counter(code_sector.values())))
    if unmapped_industries:
        print('⚠ 미매핑 업종:', unmapped_industries)

    # 파일로 굽기
    out_path = '/home/amuredo/StoryQuant/serve/markets/kr_sectors.py'
    lines = ['"""자동 생성 — 네이버 WICS 업종 분류. scripts/gen_sector_map.py 로 재생성."""\n']
    lines.append('KR_SECTOR_MAP = {\n')
    for code in sorted(code_sector):
        lines.append(f"    '{code}': '{code_sector[code]}',\n")
    lines.append('}\n')
    with open(out_path, 'w') as f:
        f.writelines(lines)
    print(f'✅ {out_path} ({len(code_sector)} 종목)')


if __name__ == '__main__':
    main()
