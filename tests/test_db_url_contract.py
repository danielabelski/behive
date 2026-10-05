"""Parse database configuration without connecting to any database."""
import importlib.util
from pathlib import Path

import psycopg2.extensions


def load_config(monkeypatch, url):
    monkeypatch.setenv('BEHIVE_DB_URL', url)
    from behive.engine import db
    spec = importlib.util.spec_from_file_location('behive_db_config_probe', Path(db.__file__))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_url_preserves_encoded_credentials_and_ssl(monkeypatch):
    module = load_config(monkeypatch, 'postgresql://test:p%20a%27ss@localhost:6543/test_db?sslmode=require')
    parsed = psycopg2.extensions.parse_dsn(module.DSN)
    assert parsed['password'] == "p a'ss"
    assert parsed['sslmode'] == 'require'
    assert parsed['port'] == '6543'


def test_pool_uses_same_complete_dsn_as_direct_connection(monkeypatch):
    module = load_config(monkeypatch, 'postgres://test:key@localhost:6543/test_db?application_name=behive_test')
    observed = []
    class Pool:
        closed = False
        def __init__(self, *args, **kwargs):
            observed.append((args, kwargs))
    monkeypatch.setattr(module.psycopg2.pool, 'ThreadedConnectionPool', Pool)
    module.get_pg_pool()
    args, kwargs = observed[0]
    dsn = kwargs.get('dsn') or (args[2] if len(args) > 2 else '')
    assert psycopg2.extensions.parse_dsn(dsn)['application_name'] == 'behive_test'
    assert module.PG_DATABASE == 'test_db'
