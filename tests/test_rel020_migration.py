import json
import pytest
from pathlib import Path
from maldroid.case_manager import CaseManager
from maldroid.exceptions import CaseError

def test_corrupt_json_detection(app_config):
    manager = CaseManager(app_config)
    case = manager.create("case1")
    root = case.root
    
    # Corrupt the json
    state_path = root / ".maldroid" / "state.json"
    state_path.write_text("{ truncated json", encoding="utf-8")
    
    with pytest.raises(CaseError, match="Case state is truncated or corrupt"):
        manager.open(root)

def test_v1_to_v2_migration(app_config):
    manager = CaseManager(app_config)
    case = manager.create("case2")
    root = case.root
    
    # Write a v1 state JSON
    state_path = root / ".maldroid" / "state.json"
    v1_state = {
        "schema_version": 1,
        "active_profile": "generic",
        "context_size": 128000,
        "model_path": "/some/model",
        "findings": [
            {
                "id": "FIND-0001",
                "title": "A finding",
                "summary": "Summary",
                "confidence": "medium",
                "severity": "medium",
                "status": "tentative",
                "evidence": [],
                "tags": [],
                "created_at": "2023-01-01T00:00:00Z",
                "updated_at": "2023-01-01T00:00:00Z"
            }
        ],
        "todos": [
            {
                "id": "TODO-0001",
                "text": "A todo",
                "status": "open",
                "created_at": "2023-01-01T00:00:00Z",
                "updated_at": "2023-01-01T00:00:00Z"
            }
        ],
        "notes": [
            {
                "id": "NOTE-0001",
                "text": "A note",
                "evidence": [],
                "created_at": "2023-01-01T00:00:00Z"
            }
        ],
        "sessions": [],
        "knowledge_documents_used": [],
        "external_tool_versions": {},
        "indexes": {}
    }
    state_path.write_text(json.dumps(v1_state), encoding="utf-8")
    
    loaded_case = manager.open(root)
    
    assert loaded_case.state.schema_version == 2
    
    assert loaded_case.state.findings[0].client_mutation_id is None
    
    assert loaded_case.state.todos[0].priority == "medium"
    assert loaded_case.state.todos[0].dependencies == []
    assert loaded_case.state.todos[0].client_mutation_id is None
    assert loaded_case.state.todos[0].owner is None
    
    assert loaded_case.state.notes[0].kind == "general"
    assert loaded_case.state.notes[0].status == "active"
    assert loaded_case.state.notes[0].client_mutation_id is None
    assert loaded_case.state.notes[0].updated_at == "2023-01-01T00:00:00Z"
