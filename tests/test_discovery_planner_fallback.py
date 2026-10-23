"""Offline fallback contract; no full-topic or macro-domain spray."""
import pytest

from behive.engine import orchestrator
from behive.engine.scout import generate_standalone_plan
from test_discovery_planner import ENGLISH, POLISH, model_boundary


@pytest.mark.parametrize('topic,language,regions', [
    (POLISH, 'pl', {'pl-pl', 'en-us'}),
    (ENGLISH, 'en', {'en-us'}),
    ('Dostawcy systemow WMS w Polsce; oferta / cennik', 'pl', {'pl-pl', 'en-us'}),
    ('Waermepumpen Hersteller in Deutschland: Preise und Foerderung', 'de', {'de-de', 'en-us'}),
])
def test_unavailable_model_uses_short_language_appropriate_fallback(monkeypatch, caplog, topic, language, regions):
    calls = model_boundary(monkeypatch, error=RuntimeError('SECRET_PROVIDER_MESSAGE must never be logged'))
    planner = orchestrator.QueenPlanner(topic)
    plan = planner.plan()
    assert len(calls) == 1
    assert 10 <= len(plan) <= 16
    assert {task['region'] for task in plan} <= regions
    assert {task['language'] for task in plan} == {language}
    assert all(task['method'] == 'web' for task in plan)
    assert all('site' not in task for task in plan)
    assert all(task['query'].casefold() != topic.casefold() for task in plan)
    assert all(2 <= len(task['query'].split()) <= 8 for task in plan)
    assert all(not any(character in task['query'] for character in ':;,') for task in plan)
    assert len({task['query'].casefold() for task in plan}) == len(plan)
    rendered = ' '.join(task['query'] for task in plan).casefold()
    assert not any(value in rendered for value in (
        'statistics 2025 2026', 'research study findings', 'annual report',
        'datareportal', 'statista', 'gsma', 'itu.int', 'worldbank', 'imf.org'))
    assert 'SECRET_PROVIDER_MESSAGE' not in caplog.text
    assert 'fallback' in caplog.text.casefold()
    assert planner._fallback_plan() == planner._fallback_plan()
    if language == 'pl':
        assert any('WMS' in task['query'] and 'telemetr' not in task['query'] for task in plan)
        assert any('cennik' in task['query'] for task in plan)
    if topic == POLISH:
        assert any('telemetr' in task['query'] and 'WMS' not in task['query'] for task in plan)
        assert any('wdrożenia' in task['query'] for task in plan)
    if topic == ENGLISH:
        assert any('installed base' in task['query'] for task in plan)
        assert any('subsidies' in task['query'] for task in plan)


def test_standalone_uses_same_deterministic_plan_without_a_model(monkeypatch):
    calls = model_boundary(monkeypatch, error=AssertionError('Standalone must stay offline'))
    plan = generate_standalone_plan(POLISH)
    assert len(plan) <= 16
    assert plan == orchestrator.QueenPlanner(POLISH)._fallback_plan()
    assert calls == []
