"""A5: real harmless children; retained combined output and unchanged exits."""
from pathlib import Path
import stat
import subprocess
import sys
import uuid

import pytest

from behive.engine import orchestrator


@pytest.fixture
def phase_paths(monkeypatch):
    monkeypatch.delenv('BEHIVE_PHASE_TIMEOUT', raising=False)
    tag = 'repair1022_' + uuid.uuid4().hex
    log = Path(f'/tmp/hive_process_{tag}_proc.log')
    pid = Path(f'/tmp/hive_process_{tag}.pid')
    try:
        yield tag, log, pid
    finally:
        log.unlink(missing_ok=True)
        pid.unlink(missing_ok=True)


@pytest.mark.parametrize('outcome', ['success', 'nonzero', 'timeout'])
def test_phase_log_retains_combined_output_and_real_outcome(monkeypatch, phase_paths, outcome, capsys):
    tag, log, pid = phase_paths
    child = """import os, sys, time
for i in range(45):
    print(f'ordinary stdout detail {i}', flush=True)
    print(f'ordinary stderr detail {i}', file=sys.stderr, flush=True)
print('exception context: failed SQL relation fixture', file=sys.stderr, flush=True)
"""
    if outcome == 'timeout':
        child += 'time.sleep(30)\n'
    elif outcome == 'nonzero':
        # The child's fake log marker must not override its actual exit status.
        child += 'print("EXIT:0", flush=True)\nsys.exit(7)\n'
    monkeypatch.setattr(orchestrator, '_resolve_cmd', lambda _: [sys.executable, '-u', '-c', child])
    if outcome == 'success':
        assert orchestrator.run_phase('hive2_process.py', [tag], 'process', timeout=1) >= 0
    elif outcome == 'nonzero':
        with pytest.raises(subprocess.CalledProcessError) as error:
            orchestrator.run_phase('hive2_process.py', [tag], 'process', timeout=1)
        assert error.value.returncode == 7
    else:
        with pytest.raises(subprocess.TimeoutExpired):
            orchestrator.run_phase('hive2_process.py', [tag], 'process', timeout=1)
    text = log.read_text()
    expected = [line for i in range(45) for line in (f'ordinary stdout detail {i}', f'ordinary stderr detail {i}')]
    assert text.splitlines()[:90] == expected, 'Keep actual phase output, not only the two summary lines'
    assert 'exception context: failed SQL relation fixture' in text
    assert 'OUTPUT_LINES:91' in text if outcome != 'nonzero' else 'OUTPUT_LINES:92' in text
    if outcome == 'success':
        assert text.endswith('EXIT:0\n')
    elif outcome == 'nonzero':
        assert text.endswith('EXIT:7\n')
    assert stat.S_IMODE(log.stat().st_mode) == 0o600
    assert not pid.exists()
    # Retention does not publish detailed worker output into API/SSE logs.
    forwarded = capsys.readouterr().out
    assert 'ordinary stdout detail' not in forwarded
    assert 'failed SQL relation' not in forwarded


def test_phase_log_keeps_bounded_tail_including_single_large_line(monkeypatch, phase_paths):
    tag, log, _ = phase_paths
    child = "import sys; print('old header'); sys.stdout.write('x' * (6 * 1024 * 1024)); print('tail detail retained'); print('stderr tail retained',file=sys.stderr)"
    monkeypatch.setattr(orchestrator, '_resolve_cmd', lambda _: [sys.executable, '-u', '-c', child])
    orchestrator.run_phase('hive2_process.py', [tag], 'process', timeout=5)
    data = log.read_bytes()
    assert b'tail detail retained' in data and b'stderr tail retained' in data
    assert b'old header' not in data
    assert b'TRUNCATED' in data
    assert data.endswith(b'OUTPUT_LINES:3\nEXIT:0\n')
    assert len(data) <= 4 * 1024 * 1024
