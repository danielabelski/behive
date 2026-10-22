"""Local harmless children only; run with --noconftest (global fixtures use PG)."""
import builtins
import json
import os
import subprocess
import sys
import time
import uuid
from types import SimpleNamespace

import pytest
from behive.engine import orchestrator as orch


@pytest.fixture
def phase(monkeypatch, tmp_path):
    monkeypatch.delenv('BEHIVE_PHASE_TIMEOUT', raising=False)
    tag = 'repair_' + uuid.uuid4().hex
    paths = [f'/tmp/hive_{name}_{tag}{suffix}' for name in ('queen-synthesis', 'process')
             for suffix in ('.pid', '_proc.log')]
    yield tag, tmp_path
    for path in paths:
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass


def test_synthesis_preserves_literal_topic(monkeypatch, phase):
    tag, tmp = phase
    output = tmp / 'argv.json'
    marker = tmp / 'must_not_exist'
    topic = f"B2B O'Brien spaces ; $(touch {marker}) & | < > \"quoted\"\nnext"
    child = 'import json,sys; json.dump(sys.argv[1:],open(sys.argv[1],"w")); print("child stdout"); print("child stderr",file=sys.stderr)'
    child_path = tmp / 'harmless_child.py'
    child_path.write_text(child)
    monkeypatch.setattr(orch, '_resolve_cmd', lambda script: [sys.executable, str(child_path), str(output)])
    # Bound the legacy fixed 900s marker poll; subprocess itself is real.
    ticks = iter(range(0, 10000, 500))
    monkeypatch.setattr(orch, 'time', SimpleNamespace(time=lambda: next(ticks), sleep=lambda _: time.sleep(.05), monotonic=time.monotonic))
    orch.run_phase('hive2_master_intelligence.py', [tag, topic], 'queen-synthesis', timeout=2)
    assert json.loads(output.read_text()) == [str(output), tag, topic]
    assert not marker.exists()
    log = builtins.open(f'/tmp/hive_queen-synthesis_{tag}_proc.log').read()
    assert 'OUTPUT_LINES:2' in log and 'EXIT:0' in log


def test_non_synthesis_nonzero_exit_is_not_hidden(monkeypatch, phase):
    tag, _ = phase
    monkeypatch.setattr(orch, '_resolve_cmd', lambda script: [sys.executable, '-c', 'import sys; print("failure",file=sys.stderr); sys.exit(7)'])
    with pytest.raises(subprocess.CalledProcessError) as error:
        orch.run_phase('hive2_process.py', [tag], 'process', timeout=2)
    assert error.value.returncode == 7


@pytest.mark.parametrize('outcome', ['timeout', 'interrupted', 'zero', 'nonzero'])
@pytest.mark.parametrize('script,name', [('hive2_synth.py','queen-synthesis'), ('hive2_process.py','process')])
def test_timeout_kills_owned_process_group(monkeypatch, phase, script, name, outcome):
    import ctypes
    import signal
    tag, tmp = phase
    descendants = tmp / 'descendants.json'
    child = tmp / 'sleeper.py'
    child.write_text(
        'import os,json,subprocess,sys,time\n'
        'p=subprocess.Popen([sys.executable,"-c","import time; time.sleep(60)"])\n'
        f'json.dump([os.getpid(),p.pid],open({str(descendants)!r},"w"))\n'
        + ('time.sleep(60)\n' if outcome in ('timeout','interrupted') else f'sys.exit({7 if outcome == "nonzero" else 0})\n')
    )
    # Adopt/reap this test's grandchild so even container PID 1 cannot leave a zombie.
    libc = ctypes.CDLL(None)
    old = ctypes.c_int()
    assert libc.prctl(37, ctypes.byref(old), 0, 0, 0) == 0
    assert libc.prctl(36, 1, 0, 0, 0) == 0
    unrelated = subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)'])
    seen = []
    real_popen = subprocess.Popen
    def popen(*args,**kw):
        p = real_popen(*args,**kw)
        seen.append(p)
        if outcome == 'interrupted':
            real_wait = p.wait
            def wait(timeout=None):
                if timeout is not None:
                    deadline = time.monotonic()+2
                    while not descendants.exists() and time.monotonic()<deadline:
                        time.sleep(.01)
                    assert descendants.exists()
                    raise KeyboardInterrupt
                return real_wait()
            monkeypatch.setattr(p,'wait',wait)
        return p
    monkeypatch.setattr(orch.subprocess,'Popen',popen)
    monkeypatch.setattr(orch,'_resolve_cmd',lambda _: [sys.executable,str(child)])
    monkeypatch.setenv('BEHIVE_PHASE_TIMEOUT','1')
    pids = []
    t0 = time.monotonic()
    try:
        if outcome == 'zero':
            orch.run_phase(script,[tag],name,timeout=5)
        else:
            expected = {'timeout':subprocess.TimeoutExpired, 'interrupted':KeyboardInterrupt,
                        'nonzero':subprocess.CalledProcessError}[outcome]
            with pytest.raises(expected) as error:
                orch.run_phase(script,[tag],name,timeout=5)
            if outcome == 'timeout':
                assert error.value.timeout == 1
        assert time.monotonic()-t0 < 4
        pids = json.loads(descendants.read_text())
        assert unrelated.poll() is None
        assert seen and seen[0].returncode is not None
        # Wait/reap the adopted grandchild. A running survivor never exits here.
        deadline = time.monotonic()+1
        while time.monotonic()<deadline:
            got, _ = os.waitpid(pids[1],os.WNOHANG)
            if got: break
            time.sleep(.01)
        else: pytest.fail('grandchild survived timeout cleanup')
        for pid in pids:
            with pytest.raises(ProcessLookupError): os.kill(pid,0)
        assert not os.path.exists(f'/tmp/hive_{name}_{tag}.pid')
    finally:
        if not pids and descendants.exists(): pids = json.loads(descendants.read_text())
        for pid in pids:
            try: os.kill(pid,signal.SIGKILL)
            except ProcessLookupError: pass
        for pid in pids:
            try: os.waitpid(pid,0)
            except ChildProcessError: pass
        for proc in seen:
            if proc.poll() is None:
                proc.kill()
                proc.wait()
        unrelated.kill(); unrelated.wait()
        libc.prctl(36,old.value,0,0,0)


@pytest.mark.parametrize('rc', [0, 7])
def test_synthesis_exit_marker_does_not_control_result(monkeypatch,phase,rc):
    tag, _ = phase
    monkeypatch.setattr(orch,'_resolve_cmd',lambda _: [sys.executable,'-c',f'import sys; print("EXIT:0"); sys.exit({rc})'])
    if rc:
        with pytest.raises(subprocess.CalledProcessError) as error:
            orch.run_phase('hive2_synth.py',[tag],'queen-synthesis',timeout=2)
        assert error.value.returncode == rc
    else:
        assert orch.run_phase('hive2_synth.py',[tag],'queen-synthesis',timeout=2) >= 0



@pytest.mark.parametrize('rc', [0, 7])
def test_phase_logs_never_publish_provider_body(monkeypatch,phase,rc,capsys):
    tag,_ = phase
    child = 'import sys; print(' + repr('Authorization: Bearer ***') + '); print(' + repr('{"request_body":"private prompt"}') + f'); sys.exit({rc})'
    monkeypatch.setattr(orch,'_resolve_cmd',lambda _: [sys.executable,'-c',child])
    try: orch.run_phase('hive2_process.py',[tag],'process',timeout=2)
    except subprocess.CalledProcessError: pass
    text = builtins.open(f'/tmp/hive_process_{tag}_proc.log').read()+capsys.readouterr().out
    assert 'secret-credential' not in text and 'private prompt' not in text
    assert 'Authorization' not in text and 'request_body' not in text
    assert f'EXIT:{rc}' in text



def test_redacted_progress_keeps_phase_order(monkeypatch,phase):
    tag,_ = phase
    monkeypatch.setattr(orch,'_resolve_cmd',lambda _: [sys.executable,'-c','print("Scout done"); print("Harvest done"); print("Process done")'])
    orch.run_phase('hive2_process.py',[tag],'process',timeout=2)
    lines=builtins.open(f'/tmp/hive_process_{tag}_proc.log').read().splitlines()
    assert lines[:3] == ['Scout done','Harvest done','Process done']
