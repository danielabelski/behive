"""Real PG regression tests, runnable only against the owned private harness.

Table DDL is taken verbatim from canonical init-db.sql. No provider/model seam.
"""
import os
from pathlib import Path
import re
import uuid

import psycopg2
from psycopg2 import sql
from psycopg2.extensions import parse_dsn, make_dsn
from psycopg2.extras import Json
import pytest

from behive.engine import claims_fallback, facts_to_claims


def sentence(i):
    return f'Solar capacity in region {i} reached 120 megawatts during the documented annual reporting period.'


@pytest.fixture
def db(monkeypatch):
    dsn = os.environ.get('CLAIM_TEST_PG_DSN')
    if not dsn:
        pytest.skip('Requires owned claim-persistence-pg/run.py disposable cluster')
    assert parse_dsn(dsn)['host'].startswith('/tmp/behive-claim-pg-')
    name = 'claims_' + uuid.uuid4().hex
    admin = psycopg2.connect(dsn)
    admin.autocommit = True
    with admin.cursor() as cur:
        cur.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(name)))
    scoped = make_dsn(dsn, options=f'-c search_path={name}')
    conn = psycopg2.connect(scoped)
    ddl = (Path(__file__).parents[1] / 'src/behive/init-db.sql').read_text()
    with conn.cursor() as cur:
        for table in ('hive_missions', 'hive_content', 'hive_claims', 'hive_facts'):
            match = re.search(rf'CREATE TABLE IF NOT EXISTS {table} \(.*?\n\);', ddl, re.S)
            assert match
            cur.execute(match.group())
        cur.execute("INSERT INTO hive_missions (id, topic) VALUES ('m', 'Solar capacity')")
    conn.commit()
    monkeypatch.setenv('BEHIVE_DB_URL', scoped)
    try:
        yield conn
    finally:
        conn.close()
        with admin.cursor() as cur:
            cur.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(name)))
        admin.close()


def seed(db, kind, count=1, confidence='0.8'):
    with db.cursor() as cur:
        for i in range(count):
            if kind == 'facts':
                cur.execute('INSERT INTO hive_facts (mission_id, value, context, sources, confidence) VALUES (%s, %s, %s, %s, %s)', ('m', 120, sentence(i), Json(['https://example.test/solar']), confidence))
            else:
                cur.execute('INSERT INTO hive_content (mission_id, url, raw_text, title, word_count) VALUES (%s, %s, %s, %s, %s)', ('m', 'https://example.test/solar', sentence(i), 'Solar report', 100))
    db.commit()


def persist(kind, **kwargs):
    if kind == 'facts':
        return facts_to_claims.persist_facts_as_claims('m', **kwargs)
    return claims_fallback.salvage_claims_from_content('m', **kwargs)


@pytest.mark.parametrize('confidence, expected', [('-0.1', 0.62), ('NaN', 0.62), ('Infinity', 0.62), ('-Infinity', 0.62), ('1.1', 0.62), ('nonsense', 0.62), (None, 0.62), ('LOW', 0.55), ('0', 0.0), ('1', 1.0), ('0.8', 0.8)])
def test_fact_confidence_is_finite_probability(db, confidence, expected):
    seed(db, 'facts', confidence=confidence)
    assert persist('facts') == 1
    with db.cursor() as cur:
        cur.execute('SELECT confidence, quality_score FROM hive_claims')
        assert cur.fetchone() == pytest.approx((expected, expected))


class TrackedConnection(psycopg2.extensions.connection):
    """Observe lifecycle while all SQL/transactions still execute on real PG."""
    rolled_back = False
    def rollback(self):
        self.rolled_back = True
        return super().rollback()


@pytest.mark.parametrize('kind', ['facts', 'content'])
def test_write_failure_rolls_back_batch_and_closes(db, monkeypatch, kind):
    seed(db, kind, count=2)
    with db.cursor() as cur:
        cur.execute("ALTER TABLE hive_claims ADD CHECK (claim NOT LIKE '%region 1 %')")
    db.commit()
    real_connect = psycopg2.connect
    opened = []
    def connect(*args, **kwargs):
        conn = real_connect(*args, connection_factory=TrackedConnection, **kwargs)
        opened.append(conn)
        return conn
    monkeypatch.setattr(psycopg2, 'connect', connect)
    with pytest.raises(psycopg2.errors.CheckViolation):
        persist(kind)
    assert len(opened) == 1
    assert opened[0].closed
    assert opened[0].rolled_back
    with db.cursor() as cur:
        cur.execute('SELECT COUNT(*) FROM hive_claims')
        assert cur.fetchone()[0] == 0


@pytest.mark.parametrize('kind', ['facts', 'content'])
def test_insert_uses_configured_claim_id_default(db, kind):
    # Explicit compatibility seam: alternate installation-provided ID default.
    # The relevant canonical table definition is unchanged except this default.
    with db.cursor() as cur:
        cur.execute('CREATE SEQUENCE installation_claim_ids START 500')
        cur.execute("ALTER TABLE hive_claims ALTER COLUMN id SET DEFAULT nextval('installation_claim_ids')")
        cur.execute('CREATE SEQUENCE hive_facts_seq START 1')
    db.commit()
    seed(db, kind)
    assert persist(kind) == 1
    with db.cursor() as cur:
        cur.execute('SELECT id FROM hive_claims')
        assert cur.fetchone()[0] == 500
        cur.execute('SELECT is_called FROM hive_facts_seq')
        assert cur.fetchone()[0] is False


@pytest.mark.parametrize('kind', ['facts', 'content'])
def test_cursor_failure_still_closes_real_connection(db, monkeypatch, kind):
    real_connect = psycopg2.connect
    opened = []
    class CursorFailure(TrackedConnection):
        def cursor(self, *args, **kwargs):
            # Controlled resource-failure seam, never a fabricated DB response.
            raise RuntimeError('controlled cursor failure')
    def connect(*args, **kwargs):
        conn = real_connect(*args, connection_factory=CursorFailure, **kwargs)
        opened.append(conn)
        return conn
    monkeypatch.setattr(psycopg2, 'connect', connect)
    with pytest.raises(RuntimeError, match='controlled cursor failure'):
        persist(kind)
    assert opened[0].closed
    assert opened[0].rolled_back


@pytest.mark.parametrize('kind', ['facts', 'content'])
def test_existing_serial_claim_id_does_not_collide_with_fact_sequence(db, kind):
    with db.cursor() as cur:
        cur.execute("INSERT INTO hive_claims (mission_id, claim) VALUES ('m', 'Existing claim')")
        cur.execute('CREATE SEQUENCE hive_facts_seq START 1')
    db.commit()
    seed(db, kind)
    assert persist(kind) == 1
    with db.cursor() as cur:
        cur.execute('SELECT id FROM hive_claims ORDER BY id')
        assert cur.fetchall() == [(1,), (2,)]
        cur.execute('SELECT is_called FROM hive_facts_seq')
        assert cur.fetchone()[0] is False


@pytest.mark.parametrize('per_doc', [0, -1])
def test_nonpositive_per_doc_does_not_persist(db, per_doc):
    seed(db, 'content')
    assert persist('content', per_doc=per_doc) == 0
    with db.cursor() as cur:
        cur.execute('SELECT COUNT(*) FROM hive_claims')
        assert cur.fetchone()[0] == 0


def test_fallback_stops_at_missing_claim_count(db):
    with db.cursor() as cur:
        cur.execute("INSERT INTO hive_claims (mission_id, claim) VALUES ('m', 'Existing first claim'), ('m', 'Existing second claim')")
    db.commit()
    seed(db, 'content', count=6)
    assert persist('content', cap=24) == 1
    assert persist('content', cap=24) == 0


@pytest.mark.parametrize('cap', [0, -1, 1, 2])
def test_fallback_cap_is_a_hard_bound(db, cap):
    seed(db, 'content', count=6)
    assert persist('content', cap=cap) == max(cap, 0)
    with db.cursor() as cur:
        cur.execute('SELECT COUNT(*) FROM hive_claims')
        assert cur.fetchone()[0] == max(cap, 0)


@pytest.mark.parametrize('limit', [0, -1])
def test_nonpositive_sentence_limit_is_empty(limit):
    assert claims_fallback.sentences_from_text(sentence(0), limit=limit) == []


@pytest.mark.parametrize('kind', ['facts', 'content'])
def test_canonical_serial_inserts_and_deduplicates(db, kind):
    seed(db, kind)
    with db.cursor() as cur:
        cur.execute("SELECT to_regclass('hive_facts_seq')")
        assert cur.fetchone()[0] is None
    assert persist(kind) == 1
    assert persist(kind) == 0
    with db.cursor() as cur:
        cur.execute('SELECT id, claim, source_url, source_operation, is_garbage FROM hive_claims')
        assert cur.fetchall() == [(1, sentence(0), 'https://example.test/solar', 'facts_to_claims' if kind == 'facts' else 'claims_fallback', False)]
