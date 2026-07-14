from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from maldroid.llama_client import REASONING_BUDGETS, LocalLlamaClient


def stream_chunk(
    *,
    content=None,
    reasoning=None,
    tool_calls=None,
    completion_tokens=None,
):
    usage = (
        SimpleNamespace(completion_tokens=completion_tokens)
        if completion_tokens is not None
        else None
    )
    choices = []
    if content is not None or reasoning is not None or tool_calls is not None:
        choices = [
            SimpleNamespace(
                delta=SimpleNamespace(
                    content=content,
                    reasoning_content=reasoning,
                    model_extra={"reasoning_content": reasoning} if reasoning else {},
                    tool_calls=tool_calls or [],
                )
            )
        ]
    return SimpleNamespace(choices=choices, usage=usage)


@pytest.mark.parametrize("level,budget", REASONING_BUDGETS.items())
def test_reasoning_level_sends_dynamic_thinking_budget(level, budget) -> None:
    client = LocalLlamaClient(
        "http://127.0.0.1:7575/v1",
        None,
        "local-model",
        reasoning_level=level,
    )
    client.client = Mock()
    client.client.chat.completions.create.return_value = [
        stream_chunk(content="done"),
        stream_chunk(completion_tokens=2),
    ]

    client.complete([{"role": "user", "content": "test"}], [])

    request = client.client.chat.completions.create.call_args.kwargs
    assert request["extra_body"] == {"thinking_budget_tokens": budget}
    assert request["stream"] is True
    assert request["stream_options"] == {"include_usage": True}


def test_reasoning_level_can_change_without_restarting_client() -> None:
    client = LocalLlamaClient("http://127.0.0.1:7575/v1", None, "local-model")

    assert client.reasoning_level == "medium"

    client.set_reasoning_level("high")

    assert client.reasoning_level == "high"


def test_streaming_aggregates_reasoning_content_tools_and_usage() -> None:
    events = []
    client = LocalLlamaClient(
        "http://127.0.0.1:7575/v1",
        None,
        "local-model",
        event_handler=lambda event, data: events.append((event, data)),
    )
    client.client = Mock()
    client.client.chat.completions.create.return_value = [
        stream_chunk(reasoning="inspect "),
        stream_chunk(
            reasoning="first",
            tool_calls=[
                SimpleNamespace(
                    index=0,
                    id="call-1",
                    function=SimpleNamespace(name="MalDroid_read_", arguments='{"path":'),
                )
            ],
        ),
        stream_chunk(
            tool_calls=[
                SimpleNamespace(
                    index=0,
                    id=None,
                    function=SimpleNamespace(name="file", arguments='"a.txt"}'),
                )
            ]
        ),
        stream_chunk(completion_tokens=7),
    ]

    message = client.complete([{"role": "user", "content": "inspect"}], [{}])

    assert message.reasoning_content == "inspect first"
    assert message.tool_calls[0].name == "MalDroid_read_file"
    assert message.tool_calls[0].arguments == '{"path":"a.txt"}'
    assert any(event == "generation_progress" for event, _ in events)
    complete = next(data for event, data in events if event == "generation_complete")
    assert complete == {"completion_tokens": 7, "exact": True}
