"""AGENT-017: Pause/resume durability tests."""

import pytest
from pathlib import Path
from maldroid.agent import MalDroidAgent, AgentState
from maldroid.case_manager import CaseManager
from maldroid.config import AppConfig
from maldroid.tools.registry import ToolRegistry
from maldroid.tools.dispatcher import ToolDispatcher
from maldroid.session_manager import SessionManager
from maldroid.llama_client import AssistantMessage

class MockClient:
    def __init__(self):
        self.call_count = 0

    def complete(self, messages, tools):
        self.call_count += 1
        if self.call_count == 1:
            raise KeyboardInterrupt("Simulated Pause/Interrupt")
        return AssistantMessage(content="Resumed successfully")

def test_agent_durability_interrupt(tmp_path: Path) -> None:
    config = AppConfig()
    config.general.cases_directory = str(tmp_path)
    manager = CaseManager(config)
    case = manager.create("test-durability")
    
    registry = ToolRegistry()
    context = type("ToolContextMock", (), {
        "config": config, "case": case, "case_manager": manager, "output_directory": lambda: tmp_path
    })()
    dispatcher = ToolDispatcher(registry, context) # type: ignore
    sessions = SessionManager(case, manager)
    client = MockClient()
    
    agent = MalDroidAgent(
        config=config,
        case=case,
        client=client, # type: ignore
        registry=registry,
        dispatcher=dispatcher,
        sessions=sessions
    )
    
    with pytest.raises(KeyboardInterrupt):
        agent.respond("Start task")
        
    assert agent.state == AgentState.PLANNER
    
    # Resume
    response = agent.respond("Continue")
    assert response == "Resumed successfully"
