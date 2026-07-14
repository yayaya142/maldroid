import pytest
from pydantic import ValidationError
from maldroid.exceptions import CaseError
from maldroid.investigation import InvestigationManager
from maldroid.case_manager import Case, CaseManager
from maldroid.config import AppConfig

def test_save_finding_idempotency(tmp_path):
    config = AppConfig()
    config.general.cases_directory = str(tmp_path)
    manager = CaseManager(config)
    case = manager.create("case1")
    inv = InvestigationManager(manager)

    # Save initial finding
    f1 = inv.save_finding(case, "Test Title", "Test Summary", client_mutation_id="mut-1")
    assert f1.title == "Test Title"
    assert len(case.state.findings) == 1

    # Retry with same mutation ID should return the exact same finding without adding
    f2 = inv.save_finding(case, "Test Title", "Test Summary", client_mutation_id="mut-1")
    assert f2.id == f1.id
    assert len(case.state.findings) == 1

    # Save with different mutation ID but same title -> should raise CaseError for duplicate
    with pytest.raises(CaseError, match="Duplicate finding detected"):
        inv.save_finding(case, "Test Title", "Different Summary", client_mutation_id="mut-2")

def test_save_note_idempotency(tmp_path):
    config = AppConfig()
    config.general.cases_directory = str(tmp_path)
    manager = CaseManager(config)
    case = manager.create("case2")
    inv = InvestigationManager(manager)

    n1 = inv.save_note(case, "Note text", client_mutation_id="note-mut")
    assert len(case.state.notes) == 1

    n2 = inv.save_note(case, "Note text", client_mutation_id="note-mut")
    assert n2.id == n1.id
    assert len(case.state.notes) == 1

def test_update_todo_idempotency(tmp_path):
    config = AppConfig()
    config.general.cases_directory = str(tmp_path)
    manager = CaseManager(config)
    case = manager.create("case3")
    inv = InvestigationManager(manager)

    t1 = inv.update_todo(case, "add", "Do this", client_mutation_id="todo-mut")
    assert len(case.state.todos) == 1

    t2 = inv.update_todo(case, "add", "Do this", client_mutation_id="todo-mut")
    assert t2.id == t1.id
    assert len(case.state.todos) == 1

    with pytest.raises(CaseError, match="Duplicate TODO detected"):
        inv.update_todo(case, "add", "Do this", client_mutation_id="todo-mut-2")
