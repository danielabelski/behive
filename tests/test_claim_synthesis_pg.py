"""Cited report contract against canonical tables on the private PG harness only.

Seams: orchestrator + persisted mission report (real SQL/commit, fake llm.complete);
dry-run CLI + a second connection (no writes); no live provider/process proof.
"""
import json
from pathlib import Path
import re

import psycopg2
import pytest
from psycopg2.extras import Json

from test_claim_persistence_pg import db


@pytest.fixture(autouse=True)
def utf8_private_pg(db, monkeypatch):
    # The mandated initdb --no-locale harness defaults to SQL_ASCII.
    db.set_client_encoding('UTF8')
    monkeypatch.setenv('PGCLIENTENCODING', 'UTF8')


def prepare(db, rows=None, topic='Steel suppliers', config=None):
    ddl = (Path(__file__).parents[1] / 'src/behive/init-db.sql').read_text()
    with db.cursor() as cur:
        cur.execute(re.search(r'CREATE TABLE IF NOT EXISTS hive_sources \(.*?\n\);', ddl, re.S).group())
        cur.execute("UPDATE hive_missions SET topic=%s,status='running',synthesis='',config=%s WHERE id='m'",
                    (topic, Json(config or {'keep': {'untouched': True}})))
        for n, row in enumerate(rows or [
            {'claim': 'Alpha supplies heavy steel plate to naval shipyards in Europe.', 'source_url': 'https://alpha.test/steel'},
            {'claim': 'Beta produces specialist naval steels for European customers.', 'source_url': 'https://beta.test/steel'},
            {'claim': 'Gamma holds marine classification certifications for its steel plate.', 'source_url': 'https://gamma.test/steel'},
        ]):
            cur.execute('INSERT INTO hive_content (mission_id,url,raw_text) VALUES (%s,%s,%s)',
                        ('m', row['source_url'], row['claim']))
            cur.execute('INSERT INTO hive_claims (mission_id,claim,source_url,confidence,claim_type) VALUES (%s,%s,%s,%s,%s)',
                        ('m', row['claim'], row['source_url'], row.get('confidence', .9), 'source_extraction'))
    db.commit()


def readback(db):
    # Separate real connection: neither uncommitted writes nor mocks count as proof.
    with psycopg2.connect(db.dsn) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT synthesis,config,status,synth_done_at FROM hive_missions WHERE id='m'")
            return cur.fetchone()


def test_orchestrator_descriptive_claims_persist_nonempty_report(db, monkeypatch):
    from behive.engine import llm, orchestrator
    from test_mission_completion_pg import RealBoundary
    prepare(db)
    def unavailable(*args, **kwargs):
        raise RuntimeError('controlled offline provider error')
    monkeypatch.setattr(llm, 'complete', unavailable)
    monkeypatch.setattr(orchestrator, '_connect_db', lambda **kwargs: RealBoundary(db))
    monkeypatch.setattr(orchestrator, '_emit', lambda *args, **kwargs: None)
    monkeypatch.setattr(orchestrator, 'run_phase', lambda *args, **kwargs: 0.)
    orchestrator._run_synthesis('m', 'Steel suppliers', {})
    report, config, status, done = readback(db)
    assert 'Alpha supplies heavy steel plate' in report
    assert 'Beta produces specialist naval steels' in report
    assert 'Gamma holds marine classification' in report
    assert config['synthesis']['method'] == 'deterministic'
    assert status == 'running' and done is not None


@pytest.mark.parametrize('with_entities', [False, True])
def test_master_intelligence_string_confidence(db, with_entities):
    from behive.engine.master_intelligence import summarize_bee_results
    from test_mission_completion_pg import RealBoundary
    with db.cursor() as cur:
        cur.execute('CREATE TABLE hive_entities (mission_id text,entity_type text,value text,context text,confidence text)')
        if with_entities:
            cur.execute("INSERT INTO hive_entities VALUES ('m','supplier','Alpha','Marine steel','0.82')")
        cur.execute("INSERT INTO hive_facts (mission_id,value,unit,context,confidence) VALUES ('m','25','tonnes','Steel production','0.75')")
        # A present empty bee table avoids deliberately aborting a PG transaction.
        cur.execute('CREATE TABLE hive_bee_results (mission_id text,operation_id text,operation_name text,tier int,output_json text,confidence text)')
    db.commit()
    text = summarize_bee_results('m', RealBoundary(db))
    assert 'conf=0.75' in text
    assert ('conf=0.82' in text) == with_entities


def test_steel_model_persists_citations_and_python_config_merge(db, monkeypatch):
    from behive.engine import claim_synthesis as cs, llm
    from claim_synthesis_support import STEEL_MODEL
    snapshot = json.loads((Path(__file__).parents[0] / 'fixtures/claim_synthesis/steel_claims.json').read_text())
    prepare(db, snapshot['items'], snapshot['topic'])
    calls = []
    def complete(prompt, **kw):
        calls.append((prompt, kw))
        return json.dumps(STEEL_MODEL)
    monkeypatch.setattr(llm, 'complete', complete)
    result = cs.persist_claim_synthesis('m')
    report, config, status, done = readback(db)
    assert result['persisted'] and result['chars'] == len(report) > 0
    assert config['keep'] == {'untouched': True}
    assert config['synthesis'] == result['metadata']
    assert config['synthesis']['method'] == 'model'
    assert config['synthesis']['claims_used'] == 87
    assert config['synthesis']['model_calls'] == len(calls) == 1
    assert '## Źródła' in report and '[34]' in report
    assert 'https://libertysteelgroup.com/our-operations/liberty-steel-uk' in report
    assert '[1] LIBERTY Steel UK is a steel manufacturer' in report
    assert done is not None and status == 'running'


@pytest.mark.parametrize('status', ['cancelled', 'error'])
def test_cancelled_or_error_mission_never_overwritten(db, monkeypatch, status):
    from behive.engine import claim_synthesis as cs, llm
    prepare(db)
    with db.cursor() as cur:
        cur.execute("UPDATE hive_missions SET status=%s,synthesis='Prior report' WHERE id='m'", (status,))
    db.commit()
    monkeypatch.setattr(llm, 'complete', lambda *a, **kw: '{}')
    result = cs.persist_claim_synthesis('m')
    report, config, actual_status, done = readback(db)
    assert report == 'Prior report' and actual_status == status and done is None
    assert 'synthesis' not in config
    assert result['chars'] == 0 and result['persisted'] is False


@pytest.mark.parametrize('json_type', ['json', 'jsonb'])
def test_dry_run_cli_read_only_snapshot_and_no_write(db, monkeypatch, tmp_path, json_type):
    from behive.engine import claim_synthesis as cs, llm
    from test_claim_synthesis import model, claims
    prepare(db, claims())
    with db.cursor() as cur:
        cur.execute(f'ALTER TABLE hive_missions ALTER COLUMN config TYPE {json_type} USING config::{json_type}')
    db.commit()
    before = readback(db)
    statements = []
    real_connect = psycopg2.connect
    class Cursor(psycopg2.extensions.cursor):
        def execute(self, query, vars=None):
            statements.append(str(query))
            return super().execute(query, vars)
    class Connection(psycopg2.extensions.connection):
        def cursor(self, *a, **kw):
            kw['cursor_factory'] = Cursor
            return super().cursor(*a, **kw)
    opened = []
    def connect(*a, **kw):
        conn = real_connect(*a, connection_factory=Connection, **kw)
        opened.append(conn)
        return conn
    monkeypatch.setattr(psycopg2, 'connect', connect)
    def complete(prompt, **kw):
        assert all(conn.closed for conn in opened)  # Model work holds no DB transaction.
        return json.dumps(model())
    monkeypatch.setattr(llm, 'complete', complete)
    out = tmp_path / 'dry-run.json'
    cs.main(['m', '--dry-run', '--out', str(out)])
    artifact = json.loads(out.read_text())
    assert artifact['read_only_verified'] is True
    assert artifact['isolation'] == 'repeatable read'
    assert artifact['persisted'] is False and artifact['report']
    assert len(artifact['claims']) == 3
    assert not any(re.search(r'\b(UPDATE|INSERT|DELETE|ALTER|CREATE)\b', s, re.I) for s in statements)
    assert readback(db) == before


def test_python_merge_supports_legacy_json_and_concurrent_config_write(db, monkeypatch):
    from behive.engine import claim_synthesis as cs, llm
    from test_claim_synthesis import model, claims
    prepare(db, claims())
    with db.cursor() as cur:
        cur.execute('ALTER TABLE hive_missions ALTER COLUMN config TYPE json USING config::json')
    db.commit()
    def complete(prompt, **kw):
        with psycopg2.connect(db.dsn) as other:
            with other.cursor() as cur:
                cur.execute("UPDATE hive_missions SET config=%s WHERE id='m'", (Json({'concurrent': True}),))
        return json.dumps(model())
    monkeypatch.setattr(llm, 'complete', complete)
    result = cs.persist_claim_synthesis('m')
    assert result['persisted']
    assert readback(db)[1]['concurrent'] is True


def test_eligibility_same_mission_dedupe_confidence_and_id_order(db, monkeypatch):
    from behive.engine import claim_synthesis as cs, llm
    prepare(db)
    with db.cursor() as cur:
        cur.execute("INSERT INTO hive_claims (mission_id,claim,source_url,confidence) VALUES ('m','  ALPHA supplies heavy steel plate to naval shipyards in Europe.  ','https://alpha.test/steel',0.1)")
        cur.execute("INSERT INTO hive_claims (mission_id,claim,source_url,is_garbage) VALUES ('m','Garbage claim','https://alpha.test/steel',true),('m','{\"claims\":[]}','https://alpha.test/steel',false),('m','Missing provenance','https://orphan.test/steel',false),('m','Blank URL','',false),('m','  ','https://alpha.test/steel',false)")
        cur.execute("INSERT INTO hive_missions (id,topic) VALUES ('other','Other mission')")
        cur.execute("INSERT INTO hive_content (mission_id,url,raw_text) VALUES ('other','https://foreign.test/steel','Other document')")
        cur.execute("INSERT INTO hive_claims (mission_id,claim,source_url) VALUES ('m','Foreign mission provenance','https://foreign.test/steel')")
    db.commit()
    monkeypatch.setattr(llm, 'complete', lambda *a, **kw: '{}')
    result = cs.persist_claim_synthesis('m', dry_run=True)
    assert len(result['claims']) == 3
    assert [c['number'] for c in result['claims']] == [1, 2, 3]
    assert result['claims'][0]['claim'].startswith('Alpha supplies')
    assert not any(s in result['report'] for s in ('Garbage claim', 'Foreign mission provenance', 'Missing provenance'))


def test_evaluator_reads_persisted_report_in_readonly_private_snapshot(db, monkeypatch, tmp_path):
    from behive.engine import claim_synthesis as cs, llm
    from test_claim_synthesis import model
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from tools.eval.report_eval import load_mission_report, automatic_metrics
    prepare(db)
    monkeypatch.setattr(llm, 'complete', lambda *a, **kw: json.dumps(model()))
    cs.persist_claim_synthesis('m')
    before = readback(db)
    payload = load_mission_report('m', dsn=db.dsn)
    assert payload['read_only_verified'] and payload['isolation'] == 'repeatable read'
    assert automatic_metrics(payload)['points_valid'] == 3
    assert readback(db) == before


def test_cancellation_during_model_call_guards_final_write(db, monkeypatch):
    from behive.engine import claim_synthesis as cs, llm
    from test_claim_synthesis import model, claims
    prepare(db, claims())
    def complete(*a, **kw):
        with psycopg2.connect(db.dsn) as conn:
            with conn.cursor() as cur:
                cur.execute("UPDATE hive_missions SET status='cancelled',synthesis='Prior report' WHERE id='m'")
        return json.dumps(model())
    monkeypatch.setattr(llm, 'complete', complete)
    result = cs.persist_claim_synthesis('m')
    assert result['chars'] == 0 and result['persisted'] is False
    assert readback(db)[0] == 'Prior report'


@pytest.mark.parametrize('status', ['running', 'cancelled', 'error'])
def test_fact_synthesis_chars_mean_affected_row(db, status):
    from behive.engine.fact_synth import persist_fact_synthesis
    prepare(db, [{'claim':'Alpha supplies 34,000 tonnes of steel plate for naval ships.', 'source_url':'https://alpha.test/steel'}], topic='Alpha steel')
    with db.cursor() as cur:
        cur.execute("UPDATE hive_missions SET status=%s,synthesis='Prior report' WHERE id='m'", (status,))
    db.commit()
    result = persist_fact_synthesis('m')
    assert (result['chars'] > 0) == (status == 'running')
    assert (readback(db)[0] != 'Prior report') == (status == 'running')


@pytest.mark.parametrize('writes', [False, True])
def test_legacy_exit_zero_requires_a_new_persisted_report(db, monkeypatch, writes):
    from behive.engine import claim_synthesis as cs, fact_synth, orchestrator
    from test_mission_completion_pg import RealBoundary
    prepare(db)
    with db.cursor() as cur:
        cur.execute("UPDATE hive_missions SET synthesis='Prior report' WHERE id='m'")
    db.commit()
    def failed_primary(mid): raise RuntimeError('controlled primary failure')
    monkeypatch.setattr(cs, 'persist_claim_synthesis', failed_primary)
    monkeypatch.setattr(fact_synth, 'persist_fact_synthesis', lambda mid: {'claims':3, 'chars':0})
    monkeypatch.setattr(orchestrator, '_connect_db', lambda **kw: RealBoundary(db))
    monkeypatch.setattr(orchestrator, '_emit', lambda *a, **kw: None)
    def phase(*args):
        if writes:
            with psycopg2.connect(db.dsn) as conn:
                with conn.cursor() as cur:
                    cur.execute("UPDATE hive_missions SET synthesis='New report',synth_done_at=NOW() WHERE id='m'")
        return .01
    monkeypatch.setattr(orchestrator, 'run_phase', phase)
    if writes:
        orchestrator._run_synthesis('m', 'Steel suppliers', {})
        assert readback(db)[0] == 'New report'
    else:
        with pytest.raises(RuntimeError, match='synthesis failed'):
            orchestrator._run_synthesis('m', 'Steel suppliers', {})


def test_cmd_synth_uses_cited_primary_path(db, monkeypatch):
    from behive.engine import llm, orchestrator
    from test_mission_completion_pg import RealBoundary
    prepare(db)
    class Boundary(RealBoundary):
        @property
        def description(self): return self.cur.description
    monkeypatch.setattr(orchestrator, '_connect_db', lambda **kw: Boundary(db))
    monkeypatch.setattr(orchestrator, '_init_db', lambda *a: None)
    monkeypatch.setattr(orchestrator, '_emit', lambda *a, **kw: None)
    monkeypatch.setattr(orchestrator, 'run_phase', lambda *a, **kw: pytest.fail('no legacy path'))
    def offline(*a, **kw): raise RuntimeError('controlled provider failure')
    monkeypatch.setattr(llm, 'complete', offline)
    orchestrator.cmd_synth('m')
    assert readback(db)[1]['synthesis']['method'] == 'deterministic'


@pytest.mark.parametrize('write_out', [False, True])
def test_python_module_cli_dry_run_in_separate_process(db, tmp_path, write_out):
    import os
    import subprocess
    import sys
    from test_claim_synthesis import model, claims
    prepare(db, claims())
    before = readback(db)
    hook = tmp_path / 'hook'
    hook.mkdir()
    (hook / 'sitecustomize.py').write_text(
        'import os\nfrom behive.engine import llm\n'
        'llm.complete = lambda *a, **kw: os.environ["FAKE_SYNTH_JSON"]\n')
    out = tmp_path / 'cli-result.json'
    source = Path(__file__).resolve().parents[1] / 'src'
    command = [sys.executable, '-m', 'behive.engine.claim_synthesis', 'm', '--dry-run']
    if write_out:
        command.extend(['--out', str(out)])
    run = subprocess.run(command,
                         env={**os.environ, 'PYTHONPATH': str(hook) + ':' + str(source),
                              'FAKE_SYNTH_JSON': json.dumps(model())}, text=True, capture_output=True, timeout=20)
    assert run.returncode == 0, run.stderr
    artifact = json.loads(out.read_text() if write_out else run.stdout)
    assert artifact['metadata']['method'] == 'model' and artifact['metadata']['model_calls'] == 1
    assert artifact['read_only_verified'] is True and artifact['persisted'] is False
    assert readback(db) == before
