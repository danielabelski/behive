"""Planner replay: captured real LLM text; no provider/network or mission writes.

Run with --noconftest inside unshare --net. The only replaced boundary is
behive.engine.llm.complete. Mutations below are explicitly synthetic negatives.
"""
import hashlib
import json
from pathlib import Path

import pytest

from behive.engine import llm, orchestrator

FIXTURES = Path(__file__).parent / 'fixtures' / 'discovery_planner'
POLISH = 'Dostawcy systemów WMS i telemetrii zbiorników w Polsce: oferta, cennik, wdrożenia'
ENGLISH = 'European heat pump market 2025: installed base, leading manufacturers, subsidies'


def captured(stem):
    text = (FIXTURES / f'{stem}.txt').read_text(encoding='utf-8')
    meta = json.loads((FIXTURES / f'{stem}.meta.json').read_text(encoding='utf-8'))
    assert meta['provenance'] == 'captured real configured LLM response (not synthetic)'
    assert hashlib.sha256(text.encode()).hexdigest() == meta['response_sha256']
    return text


def model_boundary(monkeypatch, response=None, error=None):
    calls = []

    def complete(prompt, **kwargs):
        calls.append({'prompt': prompt, **kwargs})
        if error is not None:
            raise error
        return response

    monkeypatch.setenv('BEHIVE_LLM_STRICT', '1')
    monkeypatch.setattr(llm, 'complete', complete)
    # Legacy Queen batch callers held an imported alias of the same model boundary.
    monkeypatch.setattr(orchestrator, '_llm_complete', complete)
    return calls


@pytest.mark.parametrize('topic,stem', [
    (POLISH, 'captured_pl_wms_telemetry'),
    (ENGLISH, 'captured_en_heat_pumps'),
])
def test_captured_real_response_is_the_plan(monkeypatch, topic, stem):
    text = captured(stem)
    expected = json.loads(text)
    calls = model_boundary(monkeypatch, text)
    plan = orchestrator.QueenPlanner(topic).plan()
    assert len(calls) == 1, 'The configured scout model must be called once, not skipped or retried'
    assert calls[0]['stage'] == 'scout'
    assert 'strict JSON array' in calls[0]['system']
    assert json.loads(calls[0]['prompt'].split('\n', 1)[1])['topic'] == topic
    assert 10 <= len(plan) <= 16
    # Optional concrete sites become operators because SearchEngine.search takes
    # only (query, lang), not a site field. Captured raw bytes remain unchanged.
    assert [task['query'] for task in plan] == [
        f"site:{item['site']} {item['query']}" if item.get('site') else item['query']
        for item in expected
    ]
    assert [task['source'] for task in plan] == [item['intent'] for item in expected]
    assert [task['rationale'] for task in plan] == [item['rationale'] for item in expected]
    assert [task['id'] for task in plan] == list(range(1, len(plan) + 1))
    for task, item in zip(plan, expected):
        assert task['method'] == ('ddg_news' if item['intent'] == 'news' else 'web')
        assert task['language'] == item['language']
        assert task['region'] == {'pl': 'pl-pl', 'en': 'en-us'}[item['language']]
        assert 1 <= task['priority'] <= 10
        assert 2 <= len(task['query'].split()) <= 8
        if 'site' in item:
            assert task['site'] == item['site']
