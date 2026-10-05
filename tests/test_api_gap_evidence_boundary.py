"""Controlled provider response tests; no external API or database."""
from types import SimpleNamespace

import pytest


@pytest.mark.asyncio
@pytest.mark.parametrize('skipped', [True, False])
async def test_api_gap_not_admitted_as_research_document(monkeypatch, skipped):
    from behive.engine import api_scout
    api = {'name': 'Test provider'}
    match = SimpleNamespace(api=api, best_endpoint={'use_when': 'test'}, score=1.0)
    monkeypatch.setattr(api_scout, 'load_registry', lambda: [api])
    monkeypatch.setattr(api_scout, 'resolve_entity', lambda *a, **k: SimpleNamespace(domain='test', krs='', nip='', source='test'))
    monkeypatch.setattr(api_scout, 'enrich_query', lambda query, ent: query)
    monkeypatch.setattr(api_scout, 'match_apis', lambda *a, **k: [match])
    async def query(*a, **k):
        return {'api_name': 'Test provider', 'url': 'https://example.org/source',
                'raw_text': 'Source response', 'source': 'api:test',
                'category': 'test', 'query_type': 'test', 'data': {'skipped': skipped}}
    monkeypatch.setattr(api_scout, 'query_api', query)
    docs = await api_scout.scout_apis('test topic')
    assert len(docs) == (0 if skipped else 1)


@pytest.mark.asyncio
async def test_lex_key_without_contract_endpoint_never_queries_login_portal(monkeypatch):
    from behive.engine import api_scout
    monkeypatch.setenv('LEX_API_KEY', 'test-key')
    monkeypatch.delenv('LEX_API_BASE', raising=False)
    api = {'name': 'LEX Wolters Kluwer', 'auth': 'apiKey', 'url': 'https://sip.lex.pl'}
    match = SimpleNamespace(api=api, best_endpoint={'path': '/v1/search?q={query}'})
    class NoDispatch:
        def get(self, *args, **kwargs):
            raise AssertionError('login portal dispatched')
    result = await api_scout.query_api(match, 'test', NoDispatch())
    assert result is not None
    assert result['data']['skipped'] is True
    assert 'LEX_API_BASE' in result['data']['missing']


def test_comtrade_public_preview_registry_does_not_require_paid_key():
    from behive.engine import api_scout
    api = next(row for row in api_scout.load_registry() if row['name'] == 'UN Comtrade')
    assert all(endpoint['path'].startswith('/public/v1/preview/') for endpoint in api['endpoints'])
    assert api['auth'] == 'none'
