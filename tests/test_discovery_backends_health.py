"""Additional refusal/news/recovery regressions at HTTP/SDK boundaries."""
import asyncio
import json
import sys
from types import SimpleNamespace

import pytest

from behive.engine import search_backends as sb
from test_discovery_backends import (
    EN_QUERY, FIXTURES, HTTPBoundary, HTTPResponse, PL_QUERY, captured,
    clean_vendor_environment,  # pytest fixture, deliberately reused
)


@pytest.mark.parametrize('vendor,endpoint,response', [
    ('exa', 'https://mcp.exa.ai/mcp', HTTPResponse('<html>CAPTCHA required</html>')),
    ('keenable', 'https://api.keenable.ai/v1/search/public', HTTPResponse({'error': 'rate limit exceeded'})),
])
def test_200_status_refusal_is_not_mistaken_for_a_healthy_empty_search(vendor, endpoint, response):
    http = HTTPBoundary({endpoint: response, 'https://search.parallel.ai/mcp': captured('parallel', 'pl')})
    async def exercise():
        for query in (PL_QUERY, EN_QUERY):
            rows = await sb.SearchEngine().search(query, 1, vendor, http)
            assert rows[0]['source'] == 'parallel'
    asyncio.run(exercise())
    assert sum(url == endpoint for _, url, _ in http.calls) == 1


def test_circuit_expires_and_one_new_probe_can_recover(monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(sb, '_now', lambda: clock[0])
    http = HTTPBoundary({
        'https://mcp.exa.ai/mcp': [HTTPResponse({}, 429), captured('exa', 'pl')],
        'https://search.parallel.ai/mcp': captured('parallel', 'pl'),
    })
    async def exercise():
        first = await sb.SearchEngine().search(PL_QUERY, 1, None, http)
        assert first[0]['source'] == 'parallel'
        clock[0] += 601
        recovered = await sb.SearchEngine().search(PL_QUERY, 1, None, http)
        assert recovered[0]['source'] == 'exa'
    asyncio.run(exercise())
    assert sum(url == 'https://mcp.exa.ai/mcp' for _, url, _ in http.calls) == 2


def test_queued_queries_do_not_probe_vendor_after_first_request_is_refused():
    http = HTTPBoundary({
        'https://mcp.exa.ai/mcp': HTTPResponse({}, 403),
        'https://search.parallel.ai/mcp': captured('parallel', 'pl'),
    })
    async def exercise():
        rows = await asyncio.gather(*(sb.SearchEngine().search(q, 1, None, http) for q in (PL_QUERY, EN_QUERY, 'fuel tank suppliers')))
        assert all(result[0]['source'] == 'parallel' for result in rows)
    asyncio.run(exercise())
    assert sum(url == 'https://mcp.exa.ai/mcp' for _, url, _ in http.calls) == 1


def test_brave_news_refusal_opens_same_vendor_circuit_for_news_and_web(monkeypatch):
    monkeypatch.setenv('BRAVE_SEARCH_API_KEY', 'test-only-not-a-real-key')
    http = HTTPBoundary({
        'https://api.search.brave.com/res/v1/news/search': HTTPResponse({}, 403),
        'https://mcp.exa.ai/mcp': captured('exa', 'pl'),
    })
    async def exercise():
        engine = sb.SearchEngine()
        a = await engine.search_news(PL_QUERY, 1, http)
        b = await engine.search(EN_QUERY, 1, 'brave', http)
        c = await engine.search_news(EN_QUERY, 1, http)
        assert a[0]['source'] == b[0]['source'] == c[0]['source'] == 'exa'
    asyncio.run(exercise())
    assert [url for _, url, _ in http.calls].count('https://api.search.brave.com/res/v1/news/search') == 1
    assert not any('/v1/web/search' in url for _, url, _ in http.calls)


def test_ddgs_news_captcha_opens_shared_vendor_circuit(monkeypatch):
    calls = []
    class DDGSBoundary:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def news(self, query, **kwargs):
            calls.append(('news', query))
            raise RuntimeError('CAPTCHA rate limit')
        def text(self, query, **kwargs):
            calls.append(('text', query))
            raise RuntimeError('CAPTCHA rate limit')
    monkeypatch.setitem(sys.modules, 'ddgs', SimpleNamespace(DDGS=DDGSBoundary))
    http = HTTPBoundary({'https://mcp.exa.ai/mcp': captured('exa', 'pl')})
    async def exercise():
        engine = sb.SearchEngine()
        for query in (PL_QUERY, EN_QUERY):
            rows = await engine.search_news(query, 1, http, lang='pl')
            assert rows[0]['source'] == 'exa'
        rows = await engine.search(PL_QUERY, 1, 'duckduckgo', http)
        assert rows[0]['source'] == 'exa'
    asyncio.run(exercise())
    assert calls == [('news', PL_QUERY)]


def test_searxng_paper_suppliers_are_not_academic_intent(monkeypatch):
    monkeypatch.setenv('SEARXNG_URL', 'http://searx.invalid')
    http = HTTPBoundary({'http://searx.invalid/search': HTTPResponse({'results': [{'url': 'https://supplier.example/paper', 'title': 'Paper Supplier', 'content': 'Commercial paper supply'}]})})
    rows = asyncio.run(sb.SearchEngine().search('paper suppliers in Poland', 1, 'searxng', http, lang='en'))
    assert rows[0]['source'] == 'searxng'
    assert http.calls[0][2]['params']['categories'] == 'general'


def test_wikipedia_stays_available_when_all_web_tiers_fail_and_honors_language():
    http = HTTPBoundary({'https://pl.wikipedia.org/w/api.php': HTTPResponse({'query': {'search': [{'title': 'Telemetria', 'snippet': '<b>Telemetria</b> jest techniką pomiarów'}]}})})
    engine = sb.SearchEngine()
    engine.backends = [b for b in engine.backends if b.name == 'wikipedia']
    rows = asyncio.run(engine.search(PL_QUERY, 1, None, http, lang='pl'))
    assert rows == [{'url': 'https://pl.wikipedia.org/wiki/Telemetria', 'title': 'Telemetria', 'snippet': 'Telemetria jest techniką pomiarów', 'source': 'wikipedia'}]


def test_parallel_api_key_uses_documented_rest_endpoint_not_keyless_mcp(monkeypatch):
    monkeypatch.setenv('PARALLEL_API_KEY', 'test-only-not-a-real-key')
    envelope = json.loads((FIXTURES / 'parallel_pl.txt').read_text())
    payload = json.loads(envelope['result']['content'][0]['text'])
    http = HTTPBoundary({'https://api.parallel.ai/v1/search': HTTPResponse(payload)})
    rows = asyncio.run(sb.SearchEngine().search(PL_QUERY, 1, 'parallel', http))
    assert rows[0]['source'] == 'parallel'
    assert rows[0]['url'] == 'https://pogp.pl/en/czlonkowie/ips-system'
    assert len(http.calls) == 1
    kwargs = http.calls[0][2]
    assert kwargs['headers']['x-api-key'] == 'test-only-not-a-real-key'
    assert kwargs['json'] == {'objective': PL_QUERY, 'search_queries': [PL_QUERY], 'mode': 'fast'}


@pytest.mark.parametrize('vendor,endpoint,text', [
    ('exa', 'https://mcp.exa.ai/mcp', 'Free tier rate limit exceeded. Please try later.'),
    ('parallel', 'https://search.parallel.ai/mcp', json.dumps({'error': 'rate limit exceeded'})),
])
def test_unflagged_mcp_refusal_without_page_results_also_opens_circuit(vendor, endpoint, text):
    envelope = {'jsonrpc': '2.0', 'id': 1, 'result': {'content': [{'type': 'text', 'text': text}]}}
    fallback = 'https://api.keenable.ai/v1/search/public'
    http = HTTPBoundary({endpoint: HTTPResponse(envelope), fallback: captured('keenable', 'pl')})
    async def exercise():
        engine = sb.SearchEngine()
        engine.backends = [b for b in engine.backends if b.name in {vendor, 'keenable'}]
        for query in (PL_QUERY, EN_QUERY):
            rows = await engine.search(query, 1, vendor, http)
            assert rows[0]['source'] == 'keenable'
    asyncio.run(exercise())
    assert sum(url == endpoint for _, url, _ in http.calls) == 1


def test_ddgs_named_ratelimit_exception_with_no_message_is_circuit_broken(monkeypatch):
    calls = []
    RatelimitException = type('RatelimitException', (Exception,), {})
    class DDGSBoundary:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def text(self, query, **kwargs):
            calls.append(query)
            raise RatelimitException()
    monkeypatch.setitem(sys.modules, 'ddgs', SimpleNamespace(DDGS=DDGSBoundary))
    http = HTTPBoundary({'https://mcp.exa.ai/mcp': captured('exa', 'pl')})
    async def exercise():
        for query in (PL_QUERY, EN_QUERY):
            assert (await sb.SearchEngine().search(query, 1, 'duckduckgo', http))[0]['source'] == 'exa'
    asyncio.run(exercise())
    assert calls == [PL_QUERY]
