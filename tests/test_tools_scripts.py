"""PY-016: Adversarial escape tests for Python scripts."""

import pytest
import time
from maldroid.tools.core.scripts import RunScriptInput, RunScriptHandler, WriteScriptHandler, WriteScriptInput
from maldroid.tools.models import ToolContext

def test_script_timeout_kills_infinite_loop(tmp_path):
    case_mock = type("CaseMock", (), {"workspace": tmp_path})()
    context = ToolContext(config=None, case=case_mock, case_manager=None, investigation=None, path_policy=None)
    
    writer = WriteScriptHandler()
    writer(context=context, parsed=WriteScriptInput(filename="loop.py", code="while True: pass"))
    
    runner = RunScriptHandler()
    start = time.time()
    result = runner(context=context, parsed=RunScriptInput(filename="loop.py", timeout=1))
    duration = time.time() - start
    
    assert duration < 2.0, "Script failed to timeout within 1 second"
    assert "timed out after 1" in result or "TimeoutExpired" in result

def test_script_cannot_run_missing_script(tmp_path):
    case_mock = type("CaseMock", (), {"workspace": tmp_path})()
    context = ToolContext(config=None, case=case_mock, case_manager=None, investigation=None, path_policy=None)
    
    runner = RunScriptHandler()
    with pytest.raises(FileNotFoundError):
        runner(context=context, parsed=RunScriptInput(filename="missing.py"))
