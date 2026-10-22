"""Offline contract tests: load only llm.py, never BeHive config/DB or models."""
import asyncio
import importlib.util
import logging
import os
from pathlib import Path
import socket
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest


@pytest.fixture
def harness(monkeypatch):
    # Even when run inside the repository, do not import its config or packages.
    for name in tuple(os.environ):
        if name.startswith(('BEHIVE_', 'AWS_')) or name.endswith('_API_KEY') or name == 'OPENAI_API_BASE':
            monkeypatch.delenv(name)
    monkeypatch.setenv('BEHIVE_MODEL', 'openai/gpt-6.1-sol')
    config = ModuleType('behive.config')
    config.get_model_for_stage = Mock(return_value='')
    monkeypatch.setitem(sys.modules, 'behive.config', config)
    source = Path(__file__).resolve().parents[1] / 'src/behive/engine/llm.py'
    spec = importlib.util.spec_from_file_location('llm_under_test', source)
    llm = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(llm)
    aws = Mock(side_effect=AssertionError('Credential discovery forbidden in isolated tests'))
    monkeypatch.setattr(llm, '_has_aws_credentials', aws)
    response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='OK'))])
    lite = ModuleType('litellm')
    lite.completion = Mock(return_value=response)
    lite.acompletion = AsyncMock(return_value=response)
    lite.num_retries = None
    lite.model_fallbacks = None
    monkeypatch.setitem(sys.modules, 'litellm', lite)
    direct = Mock(return_value='DIRECT')
    monkeypatch.setattr(llm, '_direct_call', direct)
    monkeypatch.setattr(socket.socket, 'connect', Mock(side_effect=AssertionError('Network forbidden')))
    monkeypatch.setattr(socket, 'create_connection', Mock(side_effect=AssertionError('Network forbidden')))
    monkeypatch.setattr('time.sleep', Mock())
    yield SimpleNamespace(llm=llm, lite=lite, direct=direct, config=config, aws=aws)
    aws.assert_not_called()


def invoke(h, mode, **kwargs):
    if mode == 'sync':
        return h.llm.complete('private-prompt', **kwargs)
    return asyncio.run(h.llm.complete_async('private-prompt', **kwargs))


def called(h, mode):
    return h.lite.completion if mode == 'sync' else h.lite.acompletion


@pytest.mark.parametrize('mode', ['sync', 'async'])
def test_strict_success_routes_explicit_base_stage_json_system_and_budgets(harness, monkeypatch, mode):
    monkeypatch.setenv('BEHIVE_LLM_STRICT', '1')
    monkeypatch.setenv('BEHIVE_LLM_TIMEOUT', '240.5')
    monkeypatch.setenv('OPENAI_API_BASE', 'http://127.0.0.1:8646/v1')
    monkeypatch.setenv('BEHIVE_MODEL_SYNTH', 'openai/stage-model')
    assert invoke(harness, mode, stage='synth', system='private-system', max_tokens=1234,
                  temperature=0.1, json_mode=True) == 'OK'
    fn = called(harness, mode)
    fn.assert_called_once()
    kwargs = fn.call_args.kwargs
    assert kwargs['api_base'] == 'http://127.0.0.1:8646/v1'
    assert kwargs['model'] == 'openai/stage-model'
    assert kwargs['timeout'] == 240.5
    assert kwargs['num_retries'] == kwargs['max_retries'] == 0
    assert kwargs['fallbacks'] == []
    assert kwargs['context_window_fallback_dict'] == {}
    assert kwargs['response_format'] == {'type': 'json_object'}
    assert kwargs['messages'] == [{'role': 'system', 'content': 'private-system'},
                                  {'role': 'user', 'content': 'private-prompt'}]
    assert kwargs['max_tokens'] == 1234
    assert kwargs['temperature'] == 0.1
    harness.direct.assert_not_called()


@pytest.mark.parametrize('mode', ['sync', 'async'])
@pytest.mark.parametrize('exc_type', [TimeoutError, RuntimeError, ValueError, ImportError])
def test_strict_failure_propagates_same_exception_once_without_fallback_or_logs(harness, monkeypatch, caplog, mode, exc_type):
    monkeypatch.setenv('BEHIVE_LLM_STRICT', '1')
    error = exc_type('provider-private-body SECRET_API_KEY')
    fn = called(harness, mode)
    fn.side_effect = error
    with caplog.at_level(logging.DEBUG):
        with pytest.raises(exc_type) as caught:
            invoke(harness, mode)
    assert caught.value is error
    fn.assert_called_once()
    harness.direct.assert_not_called()
    assert 'provider-private-body' not in caplog.text
    assert 'SECRET_API_KEY' not in caplog.text
    assert 'private-prompt' not in caplog.text


@pytest.mark.parametrize('mode', ['sync', 'async'])
def test_strict_missing_litellm_raises_no_direct_or_sync_fallback(harness, monkeypatch, mode):
    monkeypatch.setenv('BEHIVE_LLM_STRICT', '1')
    monkeypatch.setitem(sys.modules, 'litellm', None)
    with pytest.raises(ImportError):
        invoke(harness, mode)
    harness.direct.assert_not_called()
    harness.lite.completion.assert_not_called()
    harness.lite.acompletion.assert_not_called()


@pytest.mark.parametrize('mode', ['sync', 'async'])
def test_strict_default_timeout_is_180_seconds(harness, monkeypatch, mode):
    monkeypatch.setenv('BEHIVE_LLM_STRICT', '1')
    assert invoke(harness, mode) == 'OK'
    assert called(harness, mode).call_args.kwargs['timeout'] == 180


@pytest.mark.parametrize('mode', ['sync', 'async'])
@pytest.mark.parametrize('strict', [False, True])
@pytest.mark.parametrize('value', ['', 'abc', '0', '-1', 'nan', 'inf', '-inf', '3600.1'])
def test_invalid_timeout_fails_before_any_provider_call(harness, monkeypatch, mode, strict, value):
    if strict:
        monkeypatch.setenv('BEHIVE_LLM_STRICT', '1')
    monkeypatch.setenv('BEHIVE_LLM_TIMEOUT', value)
    with pytest.raises(ValueError, match='BEHIVE_LLM_TIMEOUT'):
        invoke(harness, mode)
    harness.lite.completion.assert_not_called()
    harness.lite.acompletion.assert_not_called()
    harness.direct.assert_not_called()


@pytest.mark.parametrize('mode', ['sync', 'async'])
@pytest.mark.parametrize('strict', [False, True])
@pytest.mark.parametrize('value', ['0.01', '3600'])
def test_timeout_accepts_positive_finite_bounded_seconds(harness, monkeypatch, mode, strict, value):
    if strict:
        monkeypatch.setenv('BEHIVE_LLM_STRICT', '1')
    monkeypatch.setenv('BEHIVE_LLM_TIMEOUT', value)
    assert invoke(harness, mode) == 'OK'
    assert called(harness, mode).call_args.kwargs['timeout'] == float(value)


@pytest.mark.parametrize('mode', ['sync', 'async'])
@pytest.mark.parametrize('name,value', [('num_retries', 2), ('model_fallbacks', ['openai/other'])])
def test_strict_rejects_unsafe_litellm_globals_before_call(harness, monkeypatch, mode, name, value):
    monkeypatch.setenv('BEHIVE_LLM_STRICT', '1')
    setattr(harness.lite, name, value)
    with pytest.raises(RuntimeError, match='strict'):
        invoke(harness, mode)
    called(harness, mode).assert_not_called()
    harness.direct.assert_not_called()
    assert getattr(harness.lite, name) == value  # no shared global rewrites


@pytest.mark.parametrize('mode', ['sync', 'async'])
def test_strict_empty_explicit_openai_base_fails_closed(harness, monkeypatch, mode):
    monkeypatch.setenv('BEHIVE_LLM_STRICT', '1')
    monkeypatch.setenv('OPENAI_API_BASE', '')
    with pytest.raises(ValueError, match='OPENAI_API_BASE'):
        invoke(harness, mode)
    called(harness, mode).assert_not_called()
    harness.direct.assert_not_called()


@pytest.mark.parametrize('mode', ['sync', 'async'])
def test_strict_openai_base_overrides_legacy_local_url(harness, monkeypatch, mode):
    monkeypatch.setenv('BEHIVE_LLM_STRICT', '1')
    monkeypatch.setenv('BEHIVE_MODEL', 'openai/local-model')
    monkeypatch.setenv('BEHIVE_LLM_URL', 'http://127.0.0.1:11434/v1')
    monkeypatch.setenv('OPENAI_API_BASE', 'http://127.0.0.1:8646/v1')
    assert invoke(harness, mode) == 'OK'
    assert called(harness, mode).call_args.kwargs['api_base'] == 'http://127.0.0.1:8646/v1'


@pytest.mark.parametrize('mode', ['sync', 'async'])
def test_strict_preserves_nonopenai_provider_routing(harness, monkeypatch, mode):
    monkeypatch.setenv('BEHIVE_LLM_STRICT', '1')
    monkeypatch.setenv('BEHIVE_MODEL', 'anthropic/configured-model')
    assert invoke(harness, mode) == 'OK'
    assert called(harness, mode).call_args.kwargs['model'] == 'anthropic/configured-model'
    harness.direct.assert_not_called()


@pytest.mark.parametrize('mode', ['sync', 'async'])
@pytest.mark.parametrize('strict_value', [None, '0', 'true'])
def test_legacy_defaults_unchanged_without_exact_strict_opt_in(harness, monkeypatch, mode, strict_value):
    if strict_value is not None:
        monkeypatch.setenv('BEHIVE_LLM_STRICT', strict_value)
    assert invoke(harness, mode) == 'OK'
    kwargs = called(harness, mode).call_args.kwargs
    assert kwargs == dict(model='openai/gpt-6.1-sol',
                          messages=[{'role': 'user', 'content': 'private-prompt'}],
                          max_tokens=4096, temperature=0.3, **({'timeout': 25} if mode == 'sync' else {}))


def test_legacy_sync_retries_three_times_then_direct(harness):
    harness.lite.completion.side_effect = TimeoutError('timeout')
    assert invoke(harness, 'sync') == 'DIRECT'
    assert harness.lite.completion.call_count == 3
    harness.direct.assert_called_once_with('openai/gpt-6.1-sol', 'private-prompt', '', 4096, 0.3)


def test_legacy_sync_transient_retry_can_succeed(harness):
    response = harness.lite.completion.return_value
    harness.lite.completion.side_effect = [TimeoutError('timeout'), response]
    assert invoke(harness, 'sync') == 'OK'
    assert harness.lite.completion.call_count == 2
    harness.direct.assert_not_called()


def test_legacy_sync_auth_error_propagates_without_direct(harness):
    harness.lite.completion.side_effect = RuntimeError('invalid_api_key')
    with pytest.raises(RuntimeError, match='invalid_api_key'):
        invoke(harness, 'sync')
    harness.lite.completion.assert_called_once()
    harness.direct.assert_not_called()


def test_legacy_sync_rate_limit_skips_loop_and_uses_direct(harness):
    harness.lite.completion.side_effect = RuntimeError('429 rate limit')
    assert invoke(harness, 'sync') == 'DIRECT'
    harness.lite.completion.assert_called_once()
    harness.direct.assert_called_once()


def test_legacy_async_error_returns_empty(harness):
    harness.lite.acompletion.side_effect = TimeoutError('timeout')
    assert invoke(harness, 'async') == ''
    harness.lite.acompletion.assert_called_once()
    harness.direct.assert_not_called()


@pytest.mark.parametrize('mode', ['sync', 'async'])
def test_legacy_missing_dependency_uses_direct(harness, monkeypatch, mode):
    monkeypatch.setitem(sys.modules, 'litellm', None)
    assert invoke(harness, mode) == 'DIRECT'
    harness.direct.assert_called_once()


@pytest.mark.parametrize('mode', ['sync', 'async'])
@pytest.mark.parametrize('strict', [False, True])
def test_local_auto_detect_and_json_options_remain(harness, monkeypatch, mode, strict):
    monkeypatch.delenv('BEHIVE_MODEL')
    monkeypatch.setenv('BEHIVE_LOCAL_LLM_URL', 'http://127.0.0.1:11434/v1')
    if strict:
        monkeypatch.setenv('BEHIVE_LLM_STRICT', '1')
    assert invoke(harness, mode, json_mode=True) == 'OK'
    kwargs = called(harness, mode).call_args.kwargs
    assert kwargs['model'] == 'openai/local-model'
    assert kwargs['api_base'] == 'http://127.0.0.1:11434/v1'
    assert kwargs['api_key'] == 'not-needed'
    assert kwargs['response_format'] == {'type': 'json_object'}


@pytest.mark.parametrize('mode', ['sync', 'async'])
@pytest.mark.parametrize('strict', [False, True])
def test_byok_auto_detect_preserved_with_dummy_key(harness, monkeypatch, mode, strict):
    monkeypatch.delenv('BEHIVE_MODEL')
    monkeypatch.setenv('OPENAI_API_KEY', 'test-only-not-a-secret')
    if strict:
        monkeypatch.setenv('BEHIVE_LLM_STRICT', '1')
    assert invoke(harness, mode) == 'OK'
    assert called(harness, mode).call_args.kwargs['model'] == 'openai/gpt-4o'


def test_strict_async_cancellation_propagates_once(harness, monkeypatch):
    monkeypatch.setenv('BEHIVE_LLM_STRICT', '1')
    harness.lite.acompletion.side_effect = asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        invoke(harness, 'async')
    harness.lite.acompletion.assert_called_once()
    harness.direct.assert_not_called()


@pytest.mark.parametrize('mode', ['sync', 'async'])
def test_strict_explicit_zero_global_retries_is_safe(harness, monkeypatch, mode):
    monkeypatch.setenv('BEHIVE_LLM_STRICT', '1')
    harness.lite.num_retries = 0
    assert invoke(harness, mode) == 'OK'
    called(harness, mode).assert_called_once()


@pytest.mark.parametrize('mode', ['sync', 'async'])
def test_strict_empty_global_fallback_list_is_rejected(harness, monkeypatch, mode):
    # LiteLLM enters its fallback handler for ANY non-None global value.
    monkeypatch.setenv('BEHIVE_LLM_STRICT', '1')
    harness.lite.model_fallbacks = []
    with pytest.raises(RuntimeError, match='strict'):
        invoke(harness, mode)
    called(harness, mode).assert_not_called()
    harness.direct.assert_not_called()


@pytest.mark.parametrize('mode', ['sync', 'async'])
def test_legacy_failure_logs_do_not_disclose_provider_bodies(harness, caplog, mode):
    called(harness, mode).side_effect = RuntimeError('PRIVATE_PROVIDER_BODY private-prompt')
    with caplog.at_level(logging.DEBUG):
        invoke(harness, mode)
    assert 'PRIVATE_PROVIDER_BODY' not in caplog.text
    assert 'private-prompt' not in caplog.text


@pytest.mark.parametrize('mode', ['sync', 'async'])
@pytest.mark.parametrize('stage', ['scout', 'harvest', 'process', 'synth'])
@pytest.mark.parametrize('options', [{}, {'max_tokens': 8192, 'temperature': 0, 'json_mode': True}])
def test_codex_bridge_explicit_route_omits_unsupported_options(harness, monkeypatch, mode, stage, options):
    monkeypatch.setenv('BEHIVE_LLM_CODEX_BRIDGE', '1')
    monkeypatch.setenv('BEHIVE_LLM_STRICT', '1')
    monkeypatch.setenv('OPENAI_API_BASE', 'http://127.0.0.1:8646/v1')
    # Stage resolution must still win, not a forced global model substitution.
    monkeypatch.setenv('BEHIVE_MODEL', 'anthropic/unselected-model')
    monkeypatch.setenv(f'BEHIVE_MODEL_{stage.upper()}', 'openai/gpt-6.1-sol')
    monkeypatch.setenv('BEHIVE_LLM_URL', 'http://127.0.0.1:11434/v1')
    assert invoke(harness, mode, stage=stage, system='private-system', **options) == 'OK'
    fn = called(harness, mode)
    fn.assert_called_once()
    expected = dict(model='openai/gpt-6.1-sol', api_base='http://127.0.0.1:8646/v1',
                    messages=[{'role': 'system', 'content': 'private-system'},
                              {'role': 'user', 'content': 'private-prompt'}],
                    timeout=180, num_retries=0, max_retries=0, fallbacks=[],
                    context_window_fallback_dict={})
    if options.get('json_mode'):
        expected['response_format'] = {'type': 'json_object'}
    assert fn.call_args.kwargs == expected  # No temperature or either token-cap key.
    harness.direct.assert_not_called()


@pytest.mark.parametrize('mode', ['sync', 'async'])
@pytest.mark.parametrize('name,value', [
    ('BEHIVE_LLM_STRICT', None), ('BEHIVE_LLM_STRICT', '0'),
    ('BEHIVE_LLM_STRICT', 'true'), ('BEHIVE_LLM_STRICT', ' 1'),
    ('OPENAI_API_BASE', None), ('OPENAI_API_BASE', ''),
    ('OPENAI_API_BASE', 'http://127.0.0.1:8646/v1/'),
    ('OPENAI_API_BASE', 'http://localhost:8646/v1'),
    ('OPENAI_API_BASE', 'https://127.0.0.1:8646/v1'),
    ('OPENAI_API_BASE', 'http://127.0.0.1:8647/v1'),
    ('OPENAI_API_BASE', 'http://127.0.0.1:8646/v1 '),
    ('OPENAI_API_BASE', 'https://api.openai.com/v1'),
    ('BEHIVE_MODEL_SYNTH', 'openai/gpt-4o'),
    ('BEHIVE_MODEL_SYNTH', 'gpt-6.1-sol'),
    ('BEHIVE_MODEL_SYNTH', 'openai/gpt-6.1-sol '),
    ('BEHIVE_MODEL_SYNTH', 'anthropic/gpt-6.1-sol'),
    ('BEHIVE_MODEL_SYNTH', 'ollama/gpt-6.1-sol'),
])
def test_codex_bridge_invalid_contract_rejected_before_any_call(harness, monkeypatch, mode, name, value):
    monkeypatch.setenv('BEHIVE_LLM_CODEX_BRIDGE', '1')
    monkeypatch.setenv('BEHIVE_LLM_STRICT', '1')
    monkeypatch.setenv('OPENAI_API_BASE', 'http://127.0.0.1:8646/v1')
    if value is None:
        monkeypatch.delenv(name)
    else:
        monkeypatch.setenv(name, value)
    with pytest.raises(ValueError, match='Codex bridge'):
        invoke(harness, mode, stage='synth')
    harness.lite.completion.assert_not_called()
    harness.lite.acompletion.assert_not_called()
    harness.direct.assert_not_called()


@pytest.mark.parametrize('mode', ['sync', 'async'])
@pytest.mark.parametrize('flag', [None, '0', 'true', ' 1', '1 '])
def test_codex_bridge_requires_exact_opt_in_and_other_routes_keep_budgets(harness, monkeypatch, mode, flag):
    if flag is not None:
        monkeypatch.setenv('BEHIVE_LLM_CODEX_BRIDGE', flag)
    monkeypatch.setenv('BEHIVE_LLM_STRICT', '1')
    monkeypatch.setenv('OPENAI_API_BASE', 'http://127.0.0.1:8646/v1')
    assert invoke(harness, mode, max_tokens=8192, temperature=0) == 'OK'
    kwargs = called(harness, mode).call_args.kwargs
    assert kwargs['max_tokens'] == 8192
    assert kwargs['temperature'] == 0


@pytest.mark.parametrize('mode', ['sync', 'async'])
@pytest.mark.parametrize('error_type', [TimeoutError, RuntimeError, ImportError])
def test_codex_bridge_failure_is_single_call_no_fallback(harness, monkeypatch, mode, error_type):
    monkeypatch.setenv('BEHIVE_LLM_CODEX_BRIDGE', '1')
    monkeypatch.setenv('BEHIVE_LLM_STRICT', '1')
    monkeypatch.setenv('OPENAI_API_BASE', 'http://127.0.0.1:8646/v1')
    error = error_type('synthetic provider error')
    called(harness, mode).side_effect = error
    with pytest.raises(error_type) as caught:
        invoke(harness, mode)
    assert caught.value is error
    called(harness, mode).assert_called_once()
    assert 'max_tokens' not in called(harness, mode).call_args.kwargs
    assert 'temperature' not in called(harness, mode).call_args.kwargs
    harness.direct.assert_not_called()


@pytest.mark.parametrize('mode', ['sync', 'async'])
def test_codex_bridge_preserves_explicit_timeout(harness, monkeypatch, mode):
    monkeypatch.setenv('BEHIVE_LLM_CODEX_BRIDGE', '1')
    monkeypatch.setenv('BEHIVE_LLM_STRICT', '1')
    monkeypatch.setenv('OPENAI_API_BASE', 'http://127.0.0.1:8646/v1')
    monkeypatch.setenv('BEHIVE_LLM_TIMEOUT', '170.5')
    assert invoke(harness, mode) == 'OK'
    assert called(harness, mode).call_args.kwargs['timeout'] == 170.5
    assert 'max_tokens' not in called(harness, mode).call_args.kwargs
