"""Credential and notification boundaries; run with --noconftest."""
import json
from pathlib import Path
from types import SimpleNamespace
import sys


def test_completion_preserves_explicit_provider_key(monkeypatch, tmp_path):
    import importlib
    from behive.engine import llm
    # Root conftest replaces complete itself; restore the implementation under
    # test before controlling only the provider transport boundary.
    importlib.reload(llm)
    auth = tmp_path / '.hermes' / 'auth.json'
    auth.parent.mkdir()
    auth.write_text(json.dumps({'providers': {'xai-oauth': {'tokens': {'access_token': 'foreign-test-token'}}}}))
    monkeypatch.setenv('HOME', str(tmp_path))
    monkeypatch.setenv('XAI_API_KEY', 'explicit-test-key')
    monkeypatch.setattr(llm, '_check_keys', lambda: '')
    monkeypatch.setattr(llm, '_get_configured_model', lambda stage: 'xai/test-model')
    import os
    observed = []
    def completion(**kwargs):
        observed.append(os.environ['XAI_API_KEY'])
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='ok'))])
    monkeypatch.setitem(sys.modules, 'litellm', SimpleNamespace(completion=completion))
    assert llm.complete('test') == 'ok'
    assert observed == ['explicit-test-key']


def test_gap_notice_is_pure_without_explicit_notification_opt_in(monkeypatch):
    from behive.engine import byok
    monkeypatch.delenv('BEHIVE_BYOK_NOTIFICATIONS', raising=False)
    calls = []
    monkeypatch.setattr(byok, 'queue_discord', lambda *args, **kwargs: calls.append('queue'))
    monkeypatch.setattr(byok, 'notify_discord', lambda *args, **kwargs: calls.append('send'))
    notice = byok.gap_doc({'name': 'OpenCorporates'}, 'test topic')
    assert notice is not None
    assert notice['data']['reason'] == 'missing_api_key'
    assert calls == []


def test_discord_credentials_are_only_explicit_environment(monkeypatch):
    from behive.engine import byok
    monkeypatch.delenv('BEHIVE_DISCORD_BOT_TOKEN', raising=False)
    monkeypatch.delenv('DISCORD_BOT_TOKEN', raising=False)
    original = Path.exists
    def exists(path):
        if str(path) == '/root/.hermes/.env':
            raise AssertionError('foreign profile credentials accessed')
        return original(path)
    monkeypatch.setattr(Path, 'exists', exists)
    assert byok._discord_token() == ''


def test_cli_runtime_env_uses_current_home_not_root_account(monkeypatch, tmp_path):
    from behive import cli
    monkeypatch.setenv('HOME', str(tmp_path))
    monkeypatch.delenv('BEHIVE_ENV_FILE', raising=False)
    monkeypatch.delenv('BEHIVE_TEST_RUNTIME_VALUE', raising=False)
    (tmp_path / '.behive_runtime.env').write_text('BEHIVE_TEST_RUNTIME_VALUE=owned\n')
    original = cli.os.path.isfile
    def isfile(path):
        if path == '/root/.behive_runtime.env':
            raise AssertionError('another account runtime env accessed')
        return original(path)
    monkeypatch.setattr(cli.os.path, 'isfile', isfile)
    cli._load_runtime_env()
    assert cli.os.environ['BEHIVE_TEST_RUNTIME_VALUE'] == 'owned'


def test_discord_notifications_require_explicit_destination(monkeypatch):
    from behive.engine import byok
    monkeypatch.delenv('BEHIVE_DISCORD_CHANNEL_ID', raising=False)
    monkeypatch.delenv('DISCORD_HOME_CHANNEL', raising=False)
    assert byok._channel_id() == ''
