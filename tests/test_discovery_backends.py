"""Discovery contracts, replaying captured real vendor HTTP responses offline.

No model/database mocks. HTTP is the only replaced boundary in vendor tests.
The raw fixtures are live captures; error variants in later tests are synthetic.
"""
import asyncio
import json
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from behive.engine import search_backends as sb

FIXTURES = Path(__file__).parent / 'fixtures' / 'discovery_backends'
PL_QUERY = 'dostawca systemu telemetrii zbiorników paliwa'
EN_QUERY = 'warehouse management system vendors Poland'


class HTTPResponse:
    def __init__(self, body, status=200):
        self.status = status
        self.body = body if isinstance(body, str) else json.dumps(body, ensure_ascii=False)
        self.headers = {'Content-Type': 'application/json'}

    async def text(self, **kwargs):
        return self.body

    async def json(self, **kwargs):
        return json.loads(self.body)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False


class HTTPBoundary:
    """Aiohttp session boundary: routes exact vendor URLs, never internal code."""
    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method.upper(), url, kwargs))
        if url not in self.routes:
            raise AssertionError(f'Unexpected HTTP request: {method} {url}')
        response = self.routes[url]
        if isinstance(response, list):
            response = response.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    def get(self, url, **kwargs):
        return self.request('GET', url, **kwargs)

    def post(self, url, **kwargs):
        return self.request('POST', url, **kwargs)


def captured(vendor, lang):
    return HTTPResponse((FIXTURES / f'{vendor}_{lang}.txt').read_text(encoding='utf-8'))


@pytest.fixture(autouse=True)
def clean_vendor_environment(monkeypatch):
    for name in ('EXA_API_KEY', 'PARALLEL_API_KEY', 'KEENABLE_API_KEY', 'BRAVE_SEARCH_API_KEY', 'SERPER_API_KEY', 'TAVILY_API_KEY', 'SEARXNG_URL'):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv('BEHIVE_BROWSER_SEARCH', '0')
    # Isolate process-wide vendor health across tests, without mocking its logic.
    if hasattr(sb, '_HEALTH'):
        sb._HEALTH.clear()
    yield
    if hasattr(sb, '_HEALTH'):
        sb._HEALTH.clear()


@pytest.mark.parametrize('lang,query,first_url,first_title,snippet_part', [
    ('pl', PL_QUERY, 'https://fuelprime.com/pl/rozwiazania/', 'Rozwiązania - FuelPrime', 'Zarządzanie stanami paliw'),
    ('en', EN_QUERY, 'https://zestawienie-wms.pl/', 'Systemy WMS w Polsce 2026', 'Zestawienie 18 dostawców'),
])
def test_exa_mcp_replays_captured_polish_and_english(lang, query, first_url, first_title, snippet_part):
    http = HTTPBoundary({'https://mcp.exa.ai/mcp': captured('exa', lang)})
    engine = sb.SearchEngine()
    results = asyncio.run(engine.search(query, 10, 'exa', http))
    assert len(results) == 10
    assert results[0]['url'].rstrip('/') == first_url.rstrip('/')
    assert results[0]['title'].startswith(first_title)
    assert snippet_part in results[0]['snippet']
    assert {row['source'] for row in results} == {'exa'}
    method, url, kwargs = http.calls[0]
    assert method == 'POST'
    assert kwargs['json'] == {
        'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
        'params': {'name': 'web_search_exa', 'arguments': {'query': query, 'numResults': 10}},
    }
    assert kwargs['headers']['Accept'] == 'application/json, text/event-stream'


@pytest.mark.parametrize('vendor,endpoint,first_url,title,snippet', [
    ('parallel', 'https://search.parallel.ai/mcp', 'https://www.pogp.pl/en/czlonkowie/ips-system', 'IPS System', 'Telemetria zbiornikowa'),
    ('keenable', 'https://api.keenable.ai/v1/search/public', 'https://svb24.pl/pl/kategoria/czujniki-zbiornika-wskazniki-zbiornika', 'Czujniki zbiornika', 'Wskaźnik poziomu paliwa'),
])
def test_parallel_and_keenable_replay_real_responses(vendor, endpoint, first_url, title, snippet):
    http = HTTPBoundary({endpoint: captured(vendor, 'pl')})
    results = asyncio.run(sb.SearchEngine().search(PL_QUERY, 10, vendor, http))
    assert len(results) == 10
    assert urlsplit(results[0]['url']).path == urlsplit(first_url).path
    assert results[0]['title'].startswith(title)
    assert snippet in results[0]['snippet']
    assert {row['source'] for row in results} == {vendor}
    kwargs = http.calls[0][2]
    if vendor == 'parallel':
        assert kwargs['json']['params']['name'] == 'web_search'
        arguments = kwargs['json']['params']['arguments']
        assert arguments['objective'] == PL_QUERY
        assert arguments['search_queries'] == [PL_QUERY]
        assert arguments['session_id']
        assert 'model_name' not in arguments
    else:
        assert kwargs['headers']['X-Keenable-Title'] == 'behive'
        assert kwargs['json'] == {'query': PL_QUERY, 'max_results': 10}


def test_exa_api_key_uses_official_rest_not_anonymous_mcp(monkeypatch):
    # Keyed envelope is an HTTP-boundary variant built from a captured page.
    monkeypatch.setenv('EXA_API_KEY', 'test-only-not-a-real-key')
    http = HTTPBoundary({'https://api.exa.ai/search': HTTPResponse({'results': [{
        'url': 'https://fuelprime.com/pl/rozwiazania/', 'title': 'Rozwiązania - FuelPrime',
        'highlights': ['Zarządzanie stanami paliw', 'Monitorowanie zbiorników'],
    }]})})
    results = asyncio.run(sb.SearchEngine().search(PL_QUERY, 1, None, http))
    assert results[0]['snippet'] == 'Zarządzanie stanami paliw Monitorowanie zbiorników'
    assert results[0]['source'] == 'exa'
    assert len(http.calls) == 1
    kwargs = http.calls[0][2]
    assert kwargs['headers']['x-api-key'] == 'test-only-not-a-real-key'
    assert kwargs['json'] == {'query': PL_QUERY, 'numResults': 1, 'contents': {'highlights': True}}


def test_keenable_api_key_uses_keyed_path_with_honest_app_title(monkeypatch):
    monkeypatch.setenv('KEENABLE_API_KEY', 'test-only-not-a-real-key')
    http = HTTPBoundary({'https://api.keenable.ai/v1/search': captured('keenable', 'pl')})
    results = asyncio.run(sb.SearchEngine().search(PL_QUERY, 1, 'keenable', http))
    assert results[0]['source'] == 'keenable'
    assert len(http.calls) == 1
    kwargs = http.calls[0][2]
    assert kwargs['headers']['X-Keenable-Title'] == 'behive'
    assert kwargs['headers']['Authorization'] == 'Bearer test-only-not-a-real-key'


def test_aggregates_captured_backends_in_priority_order_with_unique_urls():
    http = HTTPBoundary({
        'https://mcp.exa.ai/mcp': captured('exa', 'en'),
        'https://search.parallel.ai/mcp': captured('parallel', 'en'),
        'https://api.keenable.ai/v1/search/public': captured('keenable', 'en'),
    })
    results = asyncio.run(sb.SearchEngine().search(EN_QUERY, 20, None, http))
    assert len(results) == 20
    assert len({r['url'] for r in results}) == 20
    assert [r['source'] for r in results] == ['exa'] * 10 + ['parallel'] * 9 + ['keenable']
    assert results[10]['url'] == 'https://platform.tracxn.com/a/d/company/55e0a573e4b02d21939c6e68/rapidwms'
    assert results[-1]['url'] == 'https://ingenios.pl/en/magazyn'
    assert [url for _, url, _ in http.calls] == [
        'https://mcp.exa.ai/mcp', 'https://search.parallel.ai/mcp', 'https://api.keenable.ai/v1/search/public',
    ]
    assert http.calls[0][2]['json']['params']['arguments']['numResults'] == 10
    assert http.calls[-1][2]['json']['max_results'] == 1


def test_normalizes_tracking_fragments_www_and_slash_preserving_real_query(monkeypatch):
    monkeypatch.setenv('EXA_API_KEY', 'test-only-not-a-real-key')
    http = HTTPBoundary({'https://api.exa.ai/search': HTTPResponse({'results': [
        {'url': 'https://www.FuelPrime.com/pl/rozwiazania/?utm_source=search#section', 'title': 'First supplier'},
        {'url': 'https://fuelprime.com/pl/rozwiazania', 'title': 'Duplicate'},
        {'url': 'https://www.example.com/a/?b=2&utm_medium=test&a=1#section', 'title': 'Query page'},
        {'url': 'https://example.com/a?a=1&b=2', 'title': 'Duplicate query page'},
        {'url': 'javascript:alert(1)', 'title': 'Not a web URL'},
        {'url': '', 'title': 'Empty URL'},
    ]})})
    engine = sb.SearchEngine()
    engine.backends = [b for b in engine.backends if b.name == 'exa']
    results = asyncio.run(engine.search(PL_QUERY, 6, None, http))
    assert [r['url'] for r in results] == ['https://fuelprime.com/pl/rozwiazania', 'https://example.com/a?a=1&b=2']
    assert [r['title'] for r in results] == ['First supplier', 'Query page']
    assert all(set(r) >= {'url', 'title', 'snippet', 'source'} for r in results)


def test_per_backend_cap_prevents_one_provider_monopolizing_results(monkeypatch):
    monkeypatch.setenv('EXA_API_KEY', 'test-only-not-a-real-key')
    http = HTTPBoundary({
        'https://api.exa.ai/search': HTTPResponse({'results': [
            {'url': f'https://supplier.example/{i}', 'title': f'Supplier {i}'} for i in range(25)
        ]}),
        'https://search.parallel.ai/mcp': captured('parallel', 'pl'),
    })
    results = asyncio.run(sb.SearchEngine().search(PL_QUERY, 13, None, http))
    assert len(results) == 13
    assert [r['source'] for r in results] == ['exa'] * 10 + ['parallel'] * 3
    assert http.calls[0][2]['json']['numResults'] == 10


def test_signature_and_module_wrapper_preserve_positional_session_and_keyword_lang(monkeypatch):
    import inspect
    signature = inspect.signature(sb.SearchEngine.search)
    assert list(signature.parameters) == ['self', 'query', 'max_results', 'preferred_backend', 'session', 'lang']
    assert signature.parameters['lang'].kind is inspect.Parameter.KEYWORD_ONLY
    engine = sb.SearchEngine()
    monkeypatch.setattr(sb, '_engine', engine)
    http = HTTPBoundary({'https://mcp.exa.ai/mcp': captured('exa', 'pl')})
    results = asyncio.run(sb.search(PL_QUERY, 1, preferred_backend='exa', session=http, lang='pl'))
    assert results[0]['source'] == 'exa'
    assert sb.get_engine() is engine
    assert http.calls[0][2]['json']['params']['arguments']['query'] == PL_QUERY


@pytest.mark.parametrize('query,limit', [(PL_QUERY, 0), (PL_QUERY, -1), ('', 10), ('  ', 10)])
def test_empty_search_makes_no_vendor_request(query, limit):
    http = HTTPBoundary({})
    assert asyncio.run(sb.SearchEngine().search(query, limit, None, http)) == []
    assert http.calls == []


@pytest.mark.parametrize('status', [401, 402, 403, 429, 500, 503])
def test_vendor_refusal_opens_process_wide_circuit_and_fails_over(status, caplog):
    http = HTTPBoundary({
        'https://mcp.exa.ai/mcp': HTTPResponse({'error': 'synthetic refusal'}, status),
        'https://search.parallel.ai/mcp': captured('parallel', 'pl'),
    })
    with caplog.at_level('DEBUG', logger=sb.__name__):
        first = asyncio.run(sb.SearchEngine().search(PL_QUERY, 1, None, http))
        second = asyncio.run(sb.SearchEngine().search(EN_QUERY, 1, None, http))
    assert first[0]['source'] == second[0]['source'] == 'parallel'
    assert [url for _, url, _ in http.calls].count('https://mcp.exa.ai/mcp') == 1
    assert [url for _, url, _ in http.calls].count('https://search.parallel.ai/mcp') == 2
    summaries = [r.message for r in caplog.records if r.levelname == 'INFO' and 'circuit' in r.message.lower()]
    assert len(summaries) == 1
    assert 'exa' in summaries[0] and str(status) in summaries[0]
    assert any('exa' in r.message and 'skip' in r.message.lower() for r in caplog.records)


@pytest.mark.parametrize('envelope', [
    {'jsonrpc': '2.0', 'id': 1, 'result': {'isError': True, 'content': [{'type': 'text', 'text': 'Free tier rate limit exceeded'}]}},
    {'jsonrpc': '2.0', 'id': 1, 'error': {'code': -32000, 'message': 'CAPTCHA required'}},
])
def test_mcp_tool_and_rpc_refusals_break_circuit(envelope):
    http = HTTPBoundary({
        'https://mcp.exa.ai/mcp': HTTPResponse(envelope),
        'https://search.parallel.ai/mcp': captured('parallel', 'pl'),
    })
    async def exercise():
        engine = sb.SearchEngine()
        assert (await engine.search(PL_QUERY, 1, None, http))[0]['source'] == 'parallel'
        assert (await engine.search(EN_QUERY, 1, None, http))[0]['source'] == 'parallel'
    asyncio.run(exercise())
    assert sum(url == 'https://mcp.exa.ai/mcp' for _, url, _ in http.calls) == 1


def test_success_payload_mentions_rate_limits_without_opening_circuit():
    # Page text is untrusted content, not a provider refusal signal.
    text = (FIXTURES / 'exa_pl.txt').read_text().replace('Zarządzanie stanami paliw', 'CAPTCHA rate limit 429')
    http = HTTPBoundary({'https://mcp.exa.ai/mcp': HTTPResponse(text)})
    async def exercise():
        engine = sb.SearchEngine()
        assert (await engine.search(PL_QUERY, 1, None, http))[0]['source'] == 'exa'
        assert (await engine.search(EN_QUERY, 1, None, http))[0]['source'] == 'exa'
    asyncio.run(exercise())
    assert len(http.calls) == 2


def test_same_vendor_requests_are_serialized_and_spaced_across_engines():
    import time
    active = peak = 0
    started = []
    class SlowResponse(HTTPResponse):
        async def __aenter__(self):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            started.append(time.monotonic())
            await asyncio.sleep(0.025)
            return self
        async def __aexit__(self, *args):
            nonlocal active
            active -= 1
            return False
    http = HTTPBoundary({'https://mcp.exa.ai/mcp': SlowResponse((FIXTURES / 'exa_pl.txt').read_text())})
    async def exercise():
        a, b = await asyncio.gather(
            sb.SearchEngine().search(PL_QUERY, 1, None, http),
            sb.SearchEngine().search(EN_QUERY, 1, None, http),
        )
        assert a[0]['source'] == b[0]['source'] == 'exa'
    asyncio.run(exercise())
    assert peak == 1
    assert len(started) == 2
    assert started[1] - started[0] >= 0.2


def test_ddgs_captcha_is_not_retried_for_every_query(monkeypatch):
    import sys
    from types import SimpleNamespace
    calls = []
    class DDGSBoundary:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def text(self, query, **kwargs):
            calls.append(query)
            raise RuntimeError('CAPTCHA: DuckDuckGo rate limited this host')
    monkeypatch.setitem(sys.modules, 'ddgs', SimpleNamespace(DDGS=DDGSBoundary))
    http = HTTPBoundary({'https://mcp.exa.ai/mcp': captured('exa', 'pl')})
    async def exercise():
        for query in (PL_QUERY, EN_QUERY):
            rows = await sb.SearchEngine().search(query, 1, 'duckduckgo', http)
            assert rows[0]['source'] == 'exa'
    asyncio.run(exercise())
    assert calls == [PL_QUERY]


def test_searxng_captured_unresponsive_engines_are_a_failure_and_break_circuit(monkeypatch, caplog):
    monkeypatch.setenv('SEARXNG_URL', 'http://searx.invalid')
    http = HTTPBoundary({
        'http://searx.invalid/search': captured('searxng', 'pl'),
        'https://mcp.exa.ai/mcp': captured('exa', 'pl'),
    })
    async def exercise():
        for query in (PL_QUERY, EN_QUERY):
            rows = await sb.SearchEngine().search(query, 1, 'searxng', http, lang='pl')
            assert rows[0]['source'] == 'exa'
    with caplog.at_level('DEBUG', logger=sb.__name__):
        asyncio.run(exercise())
    searx_calls = [kwargs for _, url, kwargs in http.calls if url == 'http://searx.invalid/search']
    assert len(searx_calls) == 1
    assert searx_calls[0]['params']['categories'] == 'general'
    assert searx_calls[0]['params']['language'] == 'pl'
    assert any('searxng' in r.message and 'circuit=open' in r.message for r in caplog.records)


def test_searxng_partial_engine_outage_keeps_general_results_and_passes_lang(monkeypatch):
    monkeypatch.setenv('SEARXNG_URL', 'http://searx.invalid')
    # Boundary variant of a real SearXNG envelope: one live engine, others refused.
    data = json.loads((FIXTURES / 'searxng_pl.txt').read_text())
    data.update(results=[{'url': 'https://fuelprime.com/pl/rozwiazania/', 'title': 'FuelPrime', 'content': 'Telemetria paliwa', 'engines': ['bing'], 'category': 'general'}], unresponsive_engines=[['google', 'access denied'], ['duckduckgo', 'CAPTCHA']])
    http = HTTPBoundary({'http://searx.invalid/search': HTTPResponse(data)})
    rows = asyncio.run(sb.SearchEngine().search(PL_QUERY, 1, 'searxng', http, lang='pl'))
    assert rows == [{'url': 'https://fuelprime.com/pl/rozwiazania', 'title': 'FuelPrime', 'snippet': 'Telemetria paliwa', 'source': 'searxng'}]
    params = http.calls[0][2]['params']
    assert params['language'] == 'pl'
    assert params['categories'] == 'general'
    assert not any(x in params.get('engines', '') for x in ('arxiv', 'pubmed', 'scholar', 'crossref', 'wikipedia'))


def test_searxng_academic_engines_require_explicit_academic_query(monkeypatch):
    monkeypatch.setenv('SEARXNG_URL', 'http://searx.invalid')
    http = HTTPBoundary({'http://searx.invalid/search': HTTPResponse({'results': [{'url': 'https://arxiv.org/abs/2301.00001', 'title': 'Telemetry paper', 'content': 'Scientific methods', 'engines': ['arxiv']}], 'unresponsive_engines': []})})
    rows = asyncio.run(sb.SearchEngine().search('academic papers on fuel telemetry', 1, 'searxng', http, lang='en'))
    assert rows[0]['source'] == 'searxng'
    assert http.calls[0][2]['params']['categories'] == 'science'
    assert http.calls[0][2]['params']['language'] == 'en'


def test_wikipedia_ranks_last_and_does_not_fill_successful_commercial_web_set():
    http = HTTPBoundary({'https://mcp.exa.ai/mcp': captured('exa', 'pl')})
    engine = sb.SearchEngine()
    engine.backends = [b for b in engine.backends if b.name in {'exa', 'wikipedia'}]
    assert engine.backends[-1].name == 'wikipedia'
    rows = asyncio.run(engine.search(PL_QUERY, 20, None, http))
    assert len(rows) == 10
    assert {r['source'] for r in rows} == {'exa'}
    assert len(http.calls) == 1


@pytest.mark.parametrize('vendor,key,endpoint,payload', [
    ('brave', 'BRAVE_SEARCH_API_KEY', 'https://api.search.brave.com/res/v1/web/search', {'web': {'results': [{'url': 'https://fuelprime.com/', 'title': 'FuelPrime', 'description': 'Supplier'}]}}),
    ('serper', 'SERPER_API_KEY', 'https://google.serper.dev/search', {'organic': [{'link': 'https://fuelprime.com/', 'title': 'FuelPrime', 'snippet': 'Supplier'}]}),
    ('tavily', 'TAVILY_API_KEY', 'https://api.tavily.com/search', {'results': [{'url': 'https://fuelprime.com/', 'title': 'FuelPrime', 'content': 'Supplier'}]}),
])
def test_existing_keyed_backends_remain_available_and_share_circuit_behavior(vendor, key, endpoint, payload, monkeypatch):
    monkeypatch.setenv(key, 'test-only-not-a-real-key')
    http = HTTPBoundary({
        endpoint: [HTTPResponse(payload), HTTPResponse({}, 403)],
        'https://mcp.exa.ai/mcp': captured('exa', 'pl'),
    })
    async def exercise():
        engine = sb.SearchEngine()
        assert (await engine.search(PL_QUERY, 1, vendor, http, lang='pl'))[0]['source'] == vendor
        assert (await engine.search(PL_QUERY, 1, vendor, http, lang='pl'))[0]['source'] == 'exa'
        assert (await sb.SearchEngine().search(EN_QUERY, 1, vendor, http, lang='en'))[0]['source'] == 'exa'
    asyncio.run(exercise())
    assert sum(url == endpoint for _, url, _ in http.calls) == 2
