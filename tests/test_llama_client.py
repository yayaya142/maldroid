from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from maldroid.exceptions import TurnCancelledError
from maldroid.llama_client import (
    REASONING_BUDGETS,
    LocalLlamaClient,
    RepetitiveGenerationError,
    detect_repetitive_suffix,
)


def stream_chunk(
    *,
    content=None,
    reasoning=None,
    tool_calls=None,
    completion_tokens=None,
    prompt_tokens=None,
    cached_tokens=None,
    finish_reason=None,
    model_extra=None,
):
    usage = None
    if completion_tokens is not None or prompt_tokens is not None:
        details = (
            SimpleNamespace(cached_tokens=cached_tokens) if cached_tokens is not None else None
        )
        usage = SimpleNamespace(
            completion_tokens=completion_tokens,
            prompt_tokens=prompt_tokens,
            prompt_tokens_details=details,
        )
    choices = []
    if (
        content is not None
        or reasoning is not None
        or tool_calls is not None
        or finish_reason is not None
    ):
        choices = [
            SimpleNamespace(
                finish_reason=finish_reason,
                delta=SimpleNamespace(
                    content=content,
                    reasoning_content=reasoning,
                    model_extra={"reasoning_content": reasoning} if reasoning else {},
                    tool_calls=tool_calls or [],
                ),
            )
        ]
    return SimpleNamespace(choices=choices, usage=usage, model_extra=model_extra or {})


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
    assert request["extra_body"] == {
        "thinking_budget_tokens": budget,
        "cache_prompt": True,
        "return_progress": True,
        "sse_ping_interval": 5,
    }
    assert request["stream"] is True
    assert request["stream_options"] == {"include_usage": True}


def test_reasoning_level_can_change_without_restarting_client() -> None:
    client = LocalLlamaClient("http://127.0.0.1:7575/v1", None, "local-model")

    assert client.reasoning_level == "medium"

    client.set_reasoning_level("high")

    assert client.reasoning_level == "high"


def test_local_client_disables_nested_sdk_retries_and_bounds_stream_idle_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    constructor = Mock(return_value=Mock())
    monkeypatch.setattr("maldroid.llama_client.OpenAI", constructor)

    LocalLlamaClient(
        "http://127.0.0.1:7575/v1",
        None,
        "local-model",
        stream_idle_timeout_seconds=45,
    )

    assert constructor.call_args.kwargs["max_retries"] == 0
    assert constructor.call_args.kwargs["timeout"] == 45.0


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
        stream_chunk(
            completion_tokens=7,
            prompt_tokens=120,
            cached_tokens=80,
            finish_reason="tool_calls",
            model_extra={"timings": {"predicted_per_second": 22.5}},
        ),
    ]

    message = client.complete([{"role": "user", "content": "inspect"}], [{}])

    assert message.reasoning_content == "inspect first"
    assert message.tool_calls[0].name == "MalDroid_read_file"
    assert message.tool_calls[0].arguments == '{"path":"a.txt"}'
    assert message.finish_reason == "tool_calls"
    assert message.prompt_tokens == 120
    assert message.cached_prompt_tokens == 80
    assert message.timings == {"predicted_per_second": 22.5}
    assert any(event == "generation_progress" for event, _ in events)
    complete = next(data for event, data in events if event == "generation_complete")
    assert complete["completion_tokens"] == 7
    assert complete["exact"] is True
    assert complete["prompt_tokens"] == 120
    assert complete["cached_prompt_tokens"] == 80
    assert complete["finish_reason"] == "tool_calls"


def test_streaming_reports_prompt_progress_and_accepts_structured_arguments() -> None:
    events = []
    client = LocalLlamaClient(
        "http://127.0.0.1:7575/v1",
        None,
        "local-model",
        event_handler=lambda event, data: events.append((event, data)),
    )
    client.client = Mock()
    client.client.chat.completions.create.return_value = [
        stream_chunk(
            model_extra={
                "prompt_progress": {"processed": 800, "total": 1000, "cache": 600, "time_ms": 90}
            }
        ),
        stream_chunk(
            tool_calls=[
                SimpleNamespace(
                    index=0,
                    id="call-structured",
                    function=SimpleNamespace(name="MalDroid_read_file", arguments={"path": "x"}),
                )
            ],
            finish_reason="tool_calls",
        ),
    ]

    message = client.complete([{"role": "user", "content": "inspect"}], [{}])

    assert message.tool_calls[0].arguments == '{"path":"x"}'
    progress = next(data for event, data in events if event == "prompt_progress")
    assert progress == {"processed": 800, "total": 1000, "cached": 600, "time_ms": 90.0}
    assert any(event == "generation_first_token" for event, _ in events)


@pytest.mark.parametrize(
    "text",
    [
        "שלום שלום שלום שלום שלום שלום ",
        "final phrase final phrase final phrase final phrase final phrase final phrase ",
        "א" * 20,
    ],
)
def test_repetitive_suffix_detector_handles_words_phrases_and_unicode(text: str) -> None:
    match = detect_repetitive_suffix(text)

    assert match is not None
    assert match.repetitions >= 6


@pytest.mark.parametrize(
    "text",
    [
        "This is a normal answer with a short conclusion.",
        '{"items": [1, 1, 1, 1, 1, 1], "status": "complete"}',
        "for item in items:\n    print(item)\n",
        "---\n---\n---\n---\n---\n---\n",
    ],
)
def test_repetitive_suffix_detector_avoids_normal_text(text: str) -> None:
    assert detect_repetitive_suffix(text) is None


class ClosableStream(list):
    def __init__(self, chunks) -> None:
        super().__init__(chunks)
        self.closed = False

    def close(self) -> None:
        self.closed = True


class BlockingStream:
    def __init__(self) -> None:
        self.started = threading.Event()
        self.closed = threading.Event()

    def __iter__(self):
        return self

    def __next__(self):
        self.started.set()
        self.closed.wait(2)
        raise StopIteration

    def close(self) -> None:
        self.closed.set()


def test_cancel_current_closes_active_stream_and_discards_partial_response() -> None:
    stream = BlockingStream()
    client = LocalLlamaClient("http://127.0.0.1:7575/v1", None, "local-model")
    client.client = Mock()
    client.client.chat.completions.create.return_value = stream

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(client.complete, [{"role": "user", "content": "test"}], [])
        assert stream.started.wait(1)
        client.cancel_current()
        with pytest.raises(TurnCancelledError, match="stopped by user"):
            future.result(timeout=2)

    assert stream.closed.is_set()


def test_streaming_aborts_repetition_and_closes_response() -> None:
    events = []
    stream = ClosableStream([stream_chunk(content="שלום ") for _ in range(6)])
    client = LocalLlamaClient(
        "http://127.0.0.1:7575/v1",
        None,
        "local-model",
        event_handler=lambda event, data: events.append((event, data)),
    )
    client.client = Mock()
    client.client.chat.completions.create.return_value = stream

    with pytest.raises(RepetitiveGenerationError):
        client.complete([{"role": "user", "content": "test"}], [])

    assert stream.closed is True
    assert any(event == "generation_repetition_detected" for event, _ in events)
    assert not any(event == "generation_complete" for event, _ in events)


def test_repetition_guard_can_be_disabled() -> None:
    client = LocalLlamaClient(
        "http://127.0.0.1:7575/v1",
        None,
        "local-model",
        repetition_recovery_enabled=False,
    )
    client.client = Mock()
    client.client.chat.completions.create.return_value = [
        stream_chunk(content="שלום ") for _ in range(6)
    ]

    message = client.complete([{"role": "user", "content": "test"}], [])

    assert message.content == "שלום " * 6
