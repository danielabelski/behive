"""Scout dispatch through the real captured-DDL PostgreSQL save seam.

SearchEngine.search is the network boundary. News/RSS HTTP boundaries are also
controlled so the old unconditional fan-out is observable without networking.
Always run with the private PG runner, --noconftest, and unshare --net.
"""
import asyncio
import json
import os
from collections import Counter
from pathlib import Path
import re
from types import SimpleNamespace
import uuid

import psycopg2
from psycopg2 import sql
from psycopg2.extensions import make_dsn, parse_dsn
from psycopg2.pool import ThreadedConnectionPool
import pytest

from behive.engine import db as engine_db
from behive.engine import scout as scout_module
from behive.engine import search_backends


FIXTURES = Path(__file__).parent / 'fixtures' / 'discovery_scout'
TOPIC = 'Systemy telemetrii zbiorników paliw i chemikaliów w Polsce: dostawcy i wdrożenia'


@pytest.fixture
def private_scout(monkeypatch):
    """Real PgConnection pool, unique schema, captured production table/index DDL."""
    dsn = os.environ.get('CLAIM_TEST_PG_DSN')
    if not dsn:
        pytest.skip('Requires run_existing_pg_regressions.py private socket cluster')
    assert dsn is not None
    host = parse_dsn(dsn)['host']
    assert host.startswith('/tmp/behive-claim-pg-repair-'), host
    assert parse_dsn(dsn).get('dbname') == 'postgres'
    assert parse_dsn(dsn).get('user') == 'postgres'
    assert parse_dsn(dsn).get('port') == '55438'
    schema = 'scout_' + uuid.uuid4().hex
    admin = psycopg2.connect(dsn)
    admin.autocommit = True
    with admin.cursor() as cur:
        cur.execute("SELECT current_database(), current_user, current_setting('listen_addresses'), current_setting('data_directory')")
        preflight = cur.fetchone()
        assert preflight is not None
        database, role, tcp, data_directory = preflight
        assert (database, role, tcp) == ('postgres', 'postgres', '')
        assert Path(data_directory).resolve().parent == Path(host).resolve()
        cur.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
    # The shared runner's --no-locale cluster defaults to SQL_ASCII. Explicit
    # UTF8 client encoding is necessary to replay real Polish captures.
    scoped = make_dsn(dsn, options=f'-c search_path={schema} -c client_encoding=UTF8')
    ddl = (FIXTURES / 'hive_sources_schema.sql').read_text()
    # Omit dump transport/session/production-role statements, not table/index DDL.
    ddl = '\n'.join(line for line in ddl.splitlines()
                    if not line.startswith(('\\', 'GRANT ', 'ALTER TABLE public.hive_sources OWNER ',
                                            'SELECT pg_catalog.set_config')))
    ddl = ddl.replace('public.hive_sources', f'{schema}.hive_sources')
    with admin.cursor() as cur:
        cur.execute(ddl)
    pool = ThreadedConnectionPool(1, 6, dsn=scoped)
    monkeypatch.setattr(engine_db, '_pool', pool)
    monkeypatch.setattr(engine_db, 'DSN', scoped)
    monkeypatch.setenv('BEHIVE_DB_URL', scoped)
    instances = []

    def create(topic=TOPIC):
        instance = scout_module.SwarmScout('private_scout_' + uuid.uuid4().hex, topic)
        instances.append(instance)
        return instance

    try:
        yield create
    finally:
        for instance in instances:
            instance.db.close()
            instance._executor.shutdown(wait=True)
        pool.closeall()
        with admin.cursor() as cur:
            cur.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))
            cur.execute('SELECT count(*) FROM pg_namespace WHERE nspname = %s', (schema,))
            assert cur.fetchone() == (0,)
        admin.close()


@pytest.fixture
def search_boundary(monkeypatch):
    """Captured real supplier result returned at SearchEngine.search only."""
    calls = []
    suppliers = json.loads((FIXTURES / 'exa_suppliers.json').read_text())

    async def search(self, query, max_results=30, *args, **kwargs):
        calls.append(('web', query, max_results, kwargs))
        return suppliers[:1]

    async def news(self, query, max_results=30, *args, **kwargs):
        calls.append(('news', query, max_results, kwargs))
        return []

    def rss(url, *args, **kwargs):
        calls.append(('rss', url, kwargs))
        return SimpleNamespace(entries=[])

    monkeypatch.setattr(search_backends.SearchEngine, 'search', search)
    monkeypatch.setattr(search_backends.SearchEngine, 'search_news', news)
    monkeypatch.setattr(scout_module.feedparser, 'parse', rss)
    return calls


def test_web_task_forwards_language_without_news_fanout(private_scout, search_boundary):
    scout = private_scout()
    saved = asyncio.run(scout._run_task({
        'method': 'web', 'source': 'primary_intel', 'query': 'dostawca systemu telemetrii zbiorników paliwa',
        'language': 'pl', 'region': 'pl-pl',
    }))
    assert search_boundary == [('web', 'dostawca systemu telemetrii zbiorników paliwa', 40, {'lang': 'pl'})]
    assert saved == 1
    rows = scout.db.execute('SELECT source_type, harvest_method, status FROM hive_sources').fetchall()
    assert rows == [('web', 'web', 'scouted')]


@pytest.mark.parametrize('method, query, max_results', [
    ('ddg_site', 'site:fuelprime.com telemetria zbiorników', 35),
    ('ddg_filetype', 'telemetria zbiorników filetype:pdf', 30),
    ('ddg_reddit', 'site:reddit.com telemetria zbiorników', 30),
    ('ddg_academic', 'site:arxiv.org OR site:scholar.google.com telemetria zbiorników', 25),
])
def test_legacy_search_methods_keep_constraints_and_task_language(private_scout, search_boundary, method, query, max_results):
    scout = private_scout()
    assert asyncio.run(scout._run_task({'method': method, 'query': 'telemetria zbiorników', 'site': 'fuelprime.com', 'language': 'pl'})) == 1
    assert search_boundary == [('web', query, max_results, {'lang': 'pl'})]


def test_web_task_supports_legacy_search_signature(private_scout, search_boundary, monkeypatch):
    rows = json.loads((FIXTURES / 'exa_suppliers.json').read_text())
    calls = []

    async def legacy_search(self, query, max_results=30):
        calls.append((query, max_results))
        return rows[:1]

    monkeypatch.setattr(search_backends.SearchEngine, 'search', legacy_search)
    scout = private_scout()
    assert asyncio.run(scout._run_task({'method': 'web', 'query': 'telemetria zbiorników', 'language': 'pl'})) == 1
    assert calls == [('telemetria zbiorników', 40)]
    assert search_boundary == []


@pytest.mark.parametrize('error', ['controlled backend payload failure', "SearchBackend.search() got an unexpected keyword argument 'lang'"])
def test_backend_internal_typeerror_does_not_repeat_search(private_scout, search_boundary, monkeypatch, error):
    calls = []

    async def broken_search(self, query, max_results=30, *, lang=None):
        calls.append(lang)
        raise TypeError(error)

    monkeypatch.setattr(search_backends.SearchEngine, 'search', broken_search)
    scout = private_scout()
    assert asyncio.run(scout._run_task({'method': 'web', 'language': 'pl'})) == 0
    assert calls == ['pl']
    assert search_boundary == []
    assert scout.db.execute('SELECT count(*) FROM hive_sources').fetchone() == (0,)


@pytest.mark.parametrize('task, expected', [
    ({'method': 'web', 'source': 'news'}, {'web': 1, 'news': 1, 'rss': 1}),
    ({'method': 'web', 'intent': 'news'}, {'web': 1, 'news': 1, 'rss': 1}),
    ({'method': 'ddg_news', 'source': 'news'}, {'news': 1, 'rss': 1}),
    ({'method': 'google_rss', 'source': 'rss'}, {'news': 1, 'rss': 1}),
    ({'method': 'ddg_text', 'source': 'ddg'}, {'web': 1}),
    ({'method': 'web', 'intent': 'vendors_list'}, {'web': 1}),
])
def test_news_companions_require_explicit_task_intent(private_scout, search_boundary, task, expected):
    scout = private_scout()
    asyncio.run(scout._run_task({**task, 'query': 'telemetria zbiorników news', 'language': 'pl'}))
    assert Counter(call[0] for call in search_boundary) == expected


def test_captured_31_task_old_plan_keeps_methods_without_generic_fanout(private_scout, search_boundary, monkeypatch):
    plan = json.loads((FIXTURES / 'captured_plan.json').read_text())
    wayback_calls = []

    def offline_wayback(url, **kwargs):
        wayback_calls.append(url)
        raise OSError('controlled offline archive boundary')

    monkeypatch.setattr(scout_module.urllib.request, 'urlopen', offline_wayback)
    scout = private_scout()

    async def replay():
        return await asyncio.gather(*(scout._run_task(task) for task in plan))

    assert sum(asyncio.run(replay())) == 1  # same captured URL, real mission-wide dedupe
    assert len(plan) == 31
    assert Counter(call[0] for call in search_boundary) == {'web': 26, 'news': 4, 'rss': 4}
    assert len(wayback_calls) == 1
    assert wayback_calls[0].startswith('http://web.archive.org/cdx/search/cdx?')
    assert scout.db.execute('SELECT count(*) FROM hive_sources').fetchone() == (1,)
