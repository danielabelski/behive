"""Optional real PostgreSQL transport proof, PRIVATE socket-only cluster required.

Subprocess/planner/bridge boundaries stay controlled; SQL is executed unchanged.
Never falls back to the application's DB configuration. Tables are connection-local.
"""
import os

import psycopg2
import pytest

from behive.engine import orchestrator
from test_mission_completion_lifecycle import run_server
from test_mission_completion_orchestrator import run_cmd


class PrivatePostgresBoundary:
    def __init__(self, socket):
        self.db = psycopg2.connect(host=socket, port=55491, user='postgres', dbname='postgres')
        self.row = None
        self.execute('''CREATE TEMP TABLE hive_missions
            (id TEXT PRIMARY KEY, status TEXT, phase TEXT, quality_metrics JSONB,
             specificity_score FLOAT)''')
        self.execute("INSERT INTO hive_missions VALUES ('m', 'running', 'scout', '{}', NULL)")
        self.execute('CREATE TEMP TABLE hive_sources (mission_id TEXT, url TEXT)')
        self.execute('CREATE TEMP TABLE hive_content (mission_id TEXT, url TEXT)')
        self.execute('''CREATE TEMP TABLE hive_claims
            (mission_id TEXT, claim TEXT, source_url TEXT, is_garbage BOOLEAN, quality_score FLOAT)''')
        self.committed_status = 'running'
        self.commit()

    def cursor(self):
        return self

    def execute(self, sql, params=()):
        self.row = self.db.cursor()
        self.row.execute(sql.replace('?', '%s'), params)
        return self

    def fetchone(self):
        return self.row.fetchone()

    @property
    def status(self):
        with self.db.cursor() as cur:
            cur.execute("SELECT status FROM hive_missions WHERE id='m'")
            return cur.fetchone()[0]

    def commit(self):
        self.db.commit()
        self.committed_status = self.status

    def rollback(self):
        self.db.rollback()

    def close(self):
        pass  # Keep connection-local tables inspectable; fixture closes connection.

    def claim(self, text='A documented 2025 API claim.', garbage=False):
        self.execute('INSERT INTO hive_claims VALUES (%s,%s,%s,%s,%s)', ('m', text, 'api://doc', garbage, .8))
        self.commit()


@pytest.fixture
def pg():
    socket = os.environ.get('BEHIVE_TEST_PRIVATE_PG_SOCKET', '')
    if not socket.startswith('/tmp/behive-completion-pg-'):
        pytest.skip('requires explicitly supplied private completion-test PG socket')
    db = PrivatePostgresBoundary(socket)
    try:
        yield db
    finally:
        db.db.close()


@pytest.mark.parametrize('rc,cancel,worker_done', [(0, False, False), (1, False, False), (0, True, False), (0, False, True)])
def test_real_pg_terminal_transport(monkeypatch, pg, rc, cancel, worker_done):
    pg.execute("INSERT INTO hive_content VALUES ('m', 'api://doc')")
    for _ in range(3):
        pg.claim()
    events, bridges = run_server(monkeypatch, pg, rc=rc, cancel=cancel, worker_done=worker_done)
    assert pg.status == ('cancelled' if cancel else 'done')
    assert bridges == ([] if cancel else [('m', 'done')])
    assert ('done', 'done') in events if not cancel else not any(event == 'done' for event, state in events)


def test_real_pg_orchestrator_api_completion(monkeypatch, pg, tmp_path):
    pg.execute("INSERT INTO hive_content VALUES ('m', 'api://doc')")
    pg.claim()
    run_cmd(monkeypatch, pg, tmp_path)
    assert pg.status == 'done'


def test_real_pg_blob_empty_correction_and_jsonb_metadata(monkeypatch, pg):
    pg.execute("INSERT INTO hive_content VALUES ('m', 'api://doc')")
    pg.claim(text='\n\t {"facts":[]}')
    pg.execute("UPDATE hive_missions SET status='done', phase='done'")
    pg.commit()
    monkeypatch.setattr(orchestrator, '_connect_db', lambda **kwargs: pg)
    assert orchestrator._mark_mission_error('m', 'empty_mission sources=0 claims=0')
    assert pg.status == 'empty'
    assert pg.execute("SELECT quality_metrics->>'error_message' FROM hive_missions").fetchone()[0] == 'empty_mission sources=0 claims=0'
