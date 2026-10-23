"""Artifact/schema acceptance, plus adversarial boundaries absent from the initial repair."""
import ast
import inspect
import json
import textwrap

import pytest

from behive.engine import orchestrator, scout
from test_discovery_planner import ENGLISH, POLISH, captured, model_boundary


def test_cmd_plan_json_matches_the_real_scout_dispatch_schema(monkeypatch, tmp_path):
    calls = model_boundary(monkeypatch, captured('captured_en_heat_pumps'))
    destination = tmp_path / 'plan.json'
    orchestrator.cmd_plan(ENGLISH, output_file=str(destination))
    plan = json.loads(destination.read_text(encoding='utf-8'))
    assert len(calls) == 1
    required = {'id', 'query', 'region', 'method', 'source', 'language', 'priority', 'rationale'}
    # The executor has no separate schema class: inspect its actual method map,
    # not a second invented allowlist that could silently drift out of sync.
    tree = ast.parse(textwrap.dedent(inspect.getsource(scout.SwarmScout._run_task)))
    method_map = next(node.value for node in ast.walk(tree) if isinstance(node, ast.Assign)
                      and any(isinstance(target, ast.Name) and target.id == 'primary_map' for target in node.targets))
    methods = {key.value for key in method_map.keys}
    assert 'web' in methods
    assert 10 <= len(plan) <= 16
    for task in plan:
        assert required <= task.keys()
        assert task['method'] in methods
        assert isinstance(task['priority'], int)
        assert len(task['query'].split()) <= 8


def test_model_proposed_sites_are_expressed_in_generic_search_queries(monkeypatch):
    model_boundary(monkeypatch, captured('captured_en_heat_pumps'))
    plan = orchestrator.QueenPlanner(ENGLISH).plan()
    restricted = [task for task in plan if 'site' in task]
    assert {task['site'] for task in restricted} == {'ehpa.org', 'europa.eu'}
    for task in restricted:
        assert task['method'] == 'web'
        assert f"site:{task['site']}" in task['query'].split()
        assert len(task['query'].split()) <= 8


@pytest.mark.parametrize('kind', ['bidi_query', 'surrogate_query', 'bidi_rationale', 'nonfinite', 'non_string_response', 'json_integer_limit'])
def test_remaining_malformed_outputs_cannot_escape_fallback(monkeypatch, caplog, kind):
    items = json.loads(captured('captured_pl_wms_telemetry'))
    if kind == 'effective_site_words':
        items[0].update(query='WMS suppliers in Poland warehouse software vendor directory', site='uodo.gov.pl')
    if kind == 'bidi_query':
        items[0]['query'] = 'WMS \u202eoferta Polska'
    if kind == 'surrogate_query':
        items[0]['query'] = 'WMS \ud800 oferta'
    if kind == 'bidi_rationale':
        items[0]['rationale'] = 'WMS \u202eoferta'
    if kind == 'nonfinite':
        items[0]['rationale'] = float('nan')
    response = None if kind == 'non_string_response' else json.dumps(items)
    if kind == 'json_integer_limit':
        response = '[' + '9' * 5000 + ']'
    calls = model_boundary(monkeypatch, response)
    planner = orchestrator.QueenPlanner(POLISH)
    assert planner.plan() == planner._fallback_plan()
    assert len(calls) == 1
    assert 'invalid_output' in caplog.text


def test_ascii_polish_stopwords_keep_polish_fallback_language(monkeypatch):
    model_boundary(monkeypatch, error=RuntimeError('offline'))
    plan = orchestrator.QueenPlanner('Systemy WMS i telemetria zbiornikow w kraju').plan()
    assert {task['language'] for task in plan} == {'pl'}
    assert {task['region'] for task in plan} == {'pl-pl'}


def test_invalid_primer_values_are_ignored_without_coercion(monkeypatch):
    model_boundary(monkeypatch, captured('captured_pl_wms_telemetry'))
    plan = orchestrator.QueenPlanner(POLISH, recommended_queries=[None, {}, 10, 'WMS cennik Polska']).plan()
    assert plan[0]['query'] == 'WMS cennik Polska'
    assert plan[0]['language'] == 'pl'


def test_site_operator_word_budget_drops_only_that_item(monkeypatch):
    """A site operator counts inside the 8-word budget; an over-long item is an
    ordinary quality fault (dropped), not a reason to distrust the whole plan."""
    items = json.loads(captured('captured_pl_wms_telemetry'))
    items[0].update(query='WMS suppliers in Poland warehouse software vendor directory', site='uodo.gov.pl')
    model_boundary(monkeypatch, json.dumps(items, ensure_ascii=False))
    plan = orchestrator.QueenPlanner(POLISH).plan()
    assert [t['query'] for t in plan] == [item['query'] for item in items[1:]]
