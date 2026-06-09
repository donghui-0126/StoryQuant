"""시장 무관 핵심 로직.

  classify  : sentiment / substance / category / specificity / surprise / source
  enrich    : article 객체에 위 모든 score 채워넣기
  feeds     : RSS 파싱 + 매체 통합
  news      : 종목별 native + Google News historical
  quote     : Yahoo Finance 가격 fetch
  strategy  : sweep / walkforward / recent-picks
"""
