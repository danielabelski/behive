"""Execute only the bridge function AST: no FastAPI startup, DB, or SR imports."""
import ast
import builtins
import json
import logging
import os
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock

import pytest


@pytest.fixture
def gate(monkeypatch):
    monkeypatch.delenv('BEHIVE_SR_MANUAL_REVIEW_IDS_FILE', raising=False)
    source = Path(__file__).resolve().parents[1] / 'src/behive/server.py'
    tree = ast.parse(source.read_text())
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                    and node.name == '_bridge_done_mission')
    isolated = ast.Module(body=[function], type_ignores=[])
    namespace = {'os': os, 'json': json, 'log': logging.getLogger('gate_under_test')}
    exec(compile(isolated, str(source), 'exec'), namespace)
    bridge = ModuleType('behive.sr_bridge')
    bridge.bridge_mission = Mock()
    monkeypatch.setitem(sys.modules, 'behive.sr_bridge', bridge)
    # Verify both no import and no call for held/bad gate cases.
    original_import = builtins.__import__
    imports = []
    def watched_import(name, *args, **kwargs):
        if name == 'behive.sr_bridge':
            imports.append(name)
        return original_import(name, *args, **kwargs)
    monkeypatch.setattr(builtins, '__import__', watched_import)
    monkeypatch.setattr(sys, 'path', list(sys.path))
    return SimpleNamespace(call=namespace['_bridge_done_mission'], bridge=bridge.bridge_mission,
                           imports=imports)


def test_unset_flag_preserves_bridge(gate):
    gate.call('mission-A')
    gate.bridge.assert_called_once_with('mission-A')
    assert gate.imports == ['behive.sr_bridge']


def test_held_id_skips_bridge_import_and_call(gate, tmp_path, monkeypatch, caplog):
    path = tmp_path / 'private-review-list.json'
    path.write_text(json.dumps(['mission-A']))
    monkeypatch.setenv('BEHIVE_SR_MANUAL_REVIEW_IDS_FILE', str(path))
    with caplog.at_level(logging.INFO):
        gate.call('mission-A')
    gate.bridge.assert_not_called()
    assert gate.imports == []
    assert 'manual review' in caplog.text
    assert 'private-review-list' not in caplog.text


def test_other_id_still_bridges(gate, tmp_path, monkeypatch):
    path = tmp_path / 'review.json'
    path.write_text(json.dumps(['mission-A']))
    monkeypatch.setenv('BEHIVE_SR_MANUAL_REVIEW_IDS_FILE', str(path))
    gate.call('mission-B')
    gate.bridge.assert_called_once_with('mission-B')


@pytest.mark.parametrize('payload', ['{PRIVATE_BODY', '{}', 'null', '"mission-A"',
                                      '[123]', '["mission-A", null]', '[true]'])
def test_invalid_file_fails_closed_without_leaking_details(gate, tmp_path, monkeypatch, caplog, payload):
    path = tmp_path / 'SECRET_PATH.json'
    path.write_text(payload)
    monkeypatch.setenv('BEHIVE_SR_MANUAL_REVIEW_IDS_FILE', str(path))
    with caplog.at_level(logging.ERROR):
        gate.call('mission-A')
    gate.bridge.assert_not_called()
    assert gate.imports == []
    assert 'review gate unavailable' in caplog.text
    assert 'SECRET_PATH' not in caplog.text
    assert 'PRIVATE_BODY' not in caplog.text
    assert str(path) not in caplog.text


@pytest.mark.parametrize('kind', ['missing', 'directory', 'empty-env', 'denied', 'invalid-utf8'])
def test_unreadable_configured_file_fails_closed(gate, tmp_path, monkeypatch, caplog, kind):
    path = tmp_path / 'review.json'
    if kind == 'directory':
        path.mkdir()
    elif kind == 'invalid-utf8':
        path.write_bytes(b'\xff')
    elif kind == 'denied':
        monkeypatch.setattr(builtins, 'open', Mock(side_effect=PermissionError('SECRET_BODY')))
    monkeypatch.setenv('BEHIVE_SR_MANUAL_REVIEW_IDS_FILE', '' if kind == 'empty-env' else str(path))
    gate.call('mission-A')
    gate.bridge.assert_not_called()
    assert gate.imports == []
    assert 'review gate unavailable' in caplog.text
    assert 'SECRET_BODY' not in caplog.text


def test_gate_is_reread_on_each_mission_for_atomic_parent_updates(gate, tmp_path, monkeypatch):
    path = tmp_path / 'review.json'
    path.write_text('[]')
    monkeypatch.setenv('BEHIVE_SR_MANUAL_REVIEW_IDS_FILE', str(path))
    gate.call('mission-A')
    gate.bridge.assert_called_once_with('mission-A')
    replacement = tmp_path / 'next.json'
    replacement.write_text('["mission-B"]')
    replacement.replace(path)
    gate.call('mission-B')
    assert gate.bridge.call_count == 1
    assert gate.imports == ['behive.sr_bridge']


def test_gate_compares_exact_ids_without_normalization(gate, tmp_path, monkeypatch):
    path = tmp_path / 'review.json'
    path.write_text('["Mission-A", " mission-A "]')
    monkeypatch.setenv('BEHIVE_SR_MANUAL_REVIEW_IDS_FILE', str(path))
    gate.call('mission-A')
    gate.bridge.assert_called_once_with('mission-A')
