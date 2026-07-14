from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from maldroid.llama_client import REASONING_BUDGETS, LocalLlamaClient


@pytest.mark.parametrize("level,budget", REASONING_BUDGETS.items())
def test_reasoning_level_sends_dynamic_thinking_budget(level, budget) -> None:
    client = LocalLlamaClient(
        "http://127.0.0.1:7575/v1",
        None,
        "local-model",
        reasoning_level=level,
    )
    completion = Mock()
    completion.choices = [
        SimpleNamespace(
            message=SimpleNamespace(
                content="done",
                model_extra={},
                reasoning_content=None,
                tool_calls=[],
            )
        )
    ]
    client.client = Mock()
    client.client.chat.completions.create.return_value = completion

    client.complete([{"role": "user", "content": "test"}], [])

    request = client.client.chat.completions.create.call_args.kwargs
    assert request["extra_body"] == {"thinking_budget_tokens": budget}


def test_reasoning_level_can_change_without_restarting_client() -> None:
    client = LocalLlamaClient("http://127.0.0.1:7575/v1", None, "local-model")

    assert client.reasoning_level == "medium"

    client.set_reasoning_level("high")

    assert client.reasoning_level == "high"
