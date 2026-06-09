"""HTTP fetch 유틸."""
import urllib.request


def http_get(url, timeout=8, extra_headers=None):
    headers = {
        'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) StoryQuant/1.0',
        'Accept': '*/*',
        'Accept-Language': 'ko-KR,ko;q=0.9,en;q=0.5',
    }
    if extra_headers:
        headers.update(extra_headers)
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()
