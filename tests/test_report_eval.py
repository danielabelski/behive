"""Report evaluation is offline: completions and psql subprocess only are fake."""
import copy
import importlib
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def mod():
    assert (ROOT / 'tools/eval/report_eval.py').exists(), 'report evaluator missing'
    return importlib.import_module('tools.eval.report_eval')


def payload(n=3):
    rows = [{'number': i + 1, 'id': i + 1, 'claim': f'Company supplies {i + 100} tonnes of marine steel.',
             'source_url': f'https://source{i}.test/a', 'domain': f'source{i}.test'} for i in range(n)]
    points = [{'text': f'Company supplies {i + 100} tonnes.', 'cites': [i + 1]} for i in range(n)]
    return {'topic': 'Marine steel supply', 'report': '# Marine steel supply\n', 'claims': rows,
            'document': {'summary': points, 'sections': [], 'gaps': ['No price comparison.']},
            'metadata': {'method': 'model'}}


def test_automatic_validity_grounding_and_domain_coverage():
    p = payload()
    p['document']['summary'][1]['cites'] = [99]
    p['document']['summary'][2]['text'] = 'Invented 99999 tonnes.'
    result = mod().automatic_metrics(p)
    assert result['points_total'] == 3 and result['points_valid'] == 1
    assert result['citation_valid'] == 2 and result['number_grounded'] == 1
    assert result['claims_cited_share'] == pytest.approx(2 / 3)
    assert result['domains_cited_share'] == pytest.approx(2 / 3)
    assert result['sections_count'] == 0 and result['gaps_count'] == 1


def test_independent_judges_batches_receipts_resume_and_disagreements(tmp_path):
    m = mod()
    calls = []
    def complete(prompt, judge):
        calls.append((judge, prompt))
        assert 'untrusted' in prompt.lower()
        data = json.loads(prompt.split('DATA_JSON:\n', 1)[1])
        assert len(data['items']) <= 20
        if data['kind'] == 'support':
            assert all(item['cited_claims'] for item in data['items'])
            assert 'claude_grade' not in prompt and 'sol_grade' not in prompt
        return json.dumps([{'index': r['index'], 'grade': 2 if judge == 'sol' else 1,
                            'reason': 'Supported in supplied evidence'} for r in data['items']])
    result = m.evaluate_report(payload(21), tmp_path, complete=complete)
    assert len(calls) == 6  # 2 point batches + 1 overall call, for each judge.
    assert result['agreement']['compared'] == 21
    assert result['agreement']['agreed'] == 0
    assert len(result['disagreements']) == 21
    assert result['overall']['sol']['grade'] == 2
    assert result['overall']['claude']['grade'] == 1
    assert result['judges']['sol']['support']['labels'][0]['grade'] == 2
    assert result['judges']['claude']['support']['labels'][0]['grade'] == 1
    assert len(list(tmp_path.rglob('receipt.json'))) == 6
    again = m.evaluate_report(payload(21), tmp_path, complete=complete)
    assert len(calls) == 6
    assert result['agreement'] == again['agreement']


def test_invalid_judge_grade_is_failure_not_agreement(tmp_path):
    result = mod().evaluate_report(payload(), tmp_path, complete=lambda *a: '{}')
    assert result['agreement']['compared'] == 0
    assert result['overall']['sol'] is None and result['overall']['claude'] is None
    assert result['judges']['sol']['support']['failures']


def test_tampered_receipt_is_rejected(tmp_path):
    m = mod()
    def complete(prompt, judge):
        data = json.loads(prompt.split('DATA_JSON:\n', 1)[1])
        return json.dumps([{'index':r['index'],'grade':2,'reason':'Cited source supports point'} for r in data['items']])
    m.evaluate_report(payload(), tmp_path, complete=complete)
    raw = next(tmp_path.rglob('response.raw.txt'))
    raw.write_text('tampered')
    with pytest.raises(ValueError, match='hash'):
        m.evaluate_report(payload(), tmp_path, complete=complete)


def test_cli_automatic_only_never_calls_judge(tmp_path, monkeypatch):
    m = mod()
    from tools.eval import judge
    monkeypatch.setattr(judge, 'live_complete', lambda *a: pytest.fail('no live provider calls'))
    source = tmp_path / 'report.json'
    source.write_text(json.dumps(payload()))
    m.main([str(source), str(tmp_path / 'eval'), '--automatic-only'])
    result = json.loads((tmp_path / 'eval/report_eval.json').read_text())
    assert result['automatic']['points_valid'] == 3
    assert 'judges' not in result


def test_equal_point_grades_are_listed_as_agreements(tmp_path):
    m = mod()
    def complete(prompt, judge):
        data = json.loads(prompt.split('DATA_JSON:\n', 1)[1])
        return json.dumps([{'index': r['index'], 'grade': 2, 'reason': 'Supported by supplied claim'} for r in data['items']])
    result = m.evaluate_report(payload(), tmp_path, complete=complete)
    assert [row['index'] for row in result['agreements']] == [0, 1, 2]
    assert all(row['sol']['grade'] == row['claude']['grade'] == 2 for row in result['agreements'])


def test_live_sol_route_retains_strict_environment_guard(tmp_path, monkeypatch):
    m = mod()
    monkeypatch.delenv('BEHIVE_LLM_CODEX_BRIDGE', raising=False)
    # This fails before any provider call; Claude is replaced at its boundary.
    from tools.eval import judge
    real = judge.live_complete
    def boundary(prompt, name):
        if name == 'sol':
            return real(prompt, name)
        return '{}'
    monkeypatch.setattr(judge, 'live_complete', boundary)
    monkeypatch.setenv('BEHIVE_EVAL_LEDGER', str(tmp_path / 'ledger.jsonl'))
    result = m.evaluate_report(payload(), tmp_path / 'eval')
    assert result['judges']['sol']['support']['failures'][0]['error_type'] == 'RuntimeError'
    assert (tmp_path / 'ledger.jsonl').exists()


def test_psql_mission_reader_is_one_readonly_snapshot(monkeypatch):
    m = mod()
    from behive.engine.claim_synthesis import render_model
    p = payload()
    p['report'] = render_model(p['topic'], p['claims'], p['document'])
    rows = [dict(r, confidence=.8) for r in p['claims']]
    seen = []
    def run(command, **kw):
        seen.append((command, kw['input']))
        assert command[:5] == ['sudo','-u','postgres','psql','-X']
        assert 'BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY' in kw['input']
        assert 'ROLLBACK;' in kw['input']
        assert 'c.is_garbage' in kw['input'] and 'hive_content' in kw['input']
        assert "id=:'mission_id'" in kw['input']
        from subprocess import CompletedProcess
        return CompletedProcess(command, 0, json.dumps({'topic':p['topic'], 'report':p['report'],
            'config': {'synthesis':{'method':'model'}}, 'claims':rows,
            'read_only':'on', 'isolation':'repeatable read'}), '')
    monkeypatch.setattr(m.subprocess, 'run', run)
    loaded = m.load_mission_report("m'; SELECT secret;")
    assert len(seen) == 1 and loaded['read_only_verified'] is True
    assert m.automatic_metrics(loaded)['points_valid'] == 3


def test_persisted_source_map_cannot_be_rebound_to_a_different_claim():
    m = mod()
    p = payload()
    with pytest.raises(ValueError, match='eligible claim'):
        m.parse_persisted_report(p['topic'], '# Topic\n## Sources\n- [1] Invented claim — https://source0.test/a\n', p['claims'])
