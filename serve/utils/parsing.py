"""HTML / RSS / 날짜 파싱 유틸 (stdlib only)."""
import re
import time
from datetime import datetime, timezone, timedelta


def decode_entities(s):
    s = re.sub(r'<!\[CDATA\[(.*?)\]\]>', r'\1', s, flags=re.S)
    s = (s.replace('&lt;', '<').replace('&gt;', '>')
           .replace('&amp;', '&').replace('&quot;', '"')
           .replace('&apos;', "'").replace('&#039;', "'"))
    s = re.sub(r'&#(\d+);', lambda m: chr(int(m.group(1))), s)
    return s


def strip_tags(s):
    return re.sub(r'<[^>]+>', '', s).strip()


def parse_date(s, default_tz_offset_hours=9):
    """RFC 2822 / ISO 형식 날짜 → epoch ms.
       default_tz_offset_hours: TZ 미포함 ISO 시 가정값 (KR=9, US=-5)."""
    s = (s or '').strip()
    if not s:
        return int(time.time() * 1000)
    try:
        from email.utils import parsedate_to_datetime
        dt = parsedate_to_datetime(s)
        if dt:
            return int(dt.timestamp() * 1000)
    except Exception:
        pass
    for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%dT%H:%M:%S', '%Y/%m/%d %H:%M:%S', '%Y-%m-%d %H:%M'):
        try:
            dt = datetime.strptime(s, fmt).replace(tzinfo=timezone(timedelta(hours=default_tz_offset_hours)))
            return int(dt.timestamp() * 1000)
        except Exception:
            continue
    try:
        dt = datetime.fromisoformat(s.replace('Z', '+00:00'))
        return int(dt.timestamp() * 1000)
    except Exception:
        pass
    return int(time.time() * 1000)
