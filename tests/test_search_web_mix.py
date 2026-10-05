from urllib.parse import urlparse

from behive.engine.search_backends import SearchEngine


def _arxiv_share(results):
    if not results:
        return 1.0
    n = sum(1 for r in results if "arxiv.org" in (r.get("url") or "").lower())
    return n / len(results)


def test_arxiv_share_helper():
    assert _arxiv_share([{"url": "http://arxiv.org/abs/1"}]) == 1.0
    assert _arxiv_share([{"url": "https://en.wikipedia.org/wiki/X"}]) == 0.0
