from pathlib import Path

from behive.engine.orchestrator import PYTHON, _resolve_cmd


def test_scout_is_package_not_home_stub():
    cmd = _resolve_cmd("hive2_scout.py")
    assert cmd[0] == PYTHON
    assert cmd[1:3] == ["-m", "behive.engine.scout"]
    assert "/root/hive2_scout.py" not in cmd
    assert str(Path.home() / "hive2_scout.py") not in cmd


def test_harvest_process_synth_are_package():
    assert _resolve_cmd("hive2_harvest.py")[1:3] == ["-m", "behive.engine.harvest"]
    assert _resolve_cmd("hive2_process.py")[1:3] == ["-m", "behive.engine.process"]
    assert _resolve_cmd("hive2_synth.py")[1:3] == ["-m", "behive.engine.synth"]
