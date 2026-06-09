"""시장 어댑터 — KR / US / ... 별 universe·뉴스피드·키워드·테마 캡슐화."""
from .base import MarketProvider
from . import kr
from . import us

_REGISTRY = {
    'kr': kr.provider,
    'us': us.provider,
}


def get_market(market_id='kr'):
    """market_id ('kr' | 'us') → MarketProvider 인스턴스. 알 수 없으면 KR fallback."""
    return _REGISTRY.get((market_id or 'kr').lower(), _REGISTRY['kr'])


def list_markets():
    """등록된 모든 market id."""
    return list(_REGISTRY.keys())
