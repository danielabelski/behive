"""Controlled Qdrant transport outage: no model, corpus, or network used."""
import urllib.error
from behive.engine import qdrant_claims


def test_search_transport_outage_returns_explicit_failure(monkeypatch):
    monkeypatch.setattr(qdrant_claims, 'collection_stats', lambda: {'ok': True})
    monkeypatch.setattr(qdrant_claims, 'embed_query', lambda query: [0.1] * 384)
    def fail(*args, **kwargs):
        raise urllib.error.URLError('controlled outage')
    monkeypatch.setattr(qdrant_claims, '_http', fail)
    result = qdrant_claims.semantic_search('test')
    assert result['ok'] is False
    assert result['hits'] == []
    assert 'qdrant' in result['error']
