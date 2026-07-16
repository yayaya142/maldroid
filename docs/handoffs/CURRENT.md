# Current Handoff

Task: `PLATFORM-012`
Next task: `PLATFORM-011`

Implementation commit: `f09cebb`

## Outcome

The owner reprioritized two problems: the Web workspace still felt cramped/off-center at 100% zoom,
and local-model turns were too slow, opaque, and prone to an empty final response. This task measured
the packaged Web page, audited the complete model/profile/tool/checkpoint/compaction path, checked
current upstream guidance, and implemented a single coherent response-latency/reliability change.

Physical Gemma 4/macOS acceptance is not claimed. This Linux workspace does not have the configured
llama-server binary or GGUF, so `PLATFORM-011` remains the active real-model gate.

## Web fit and centering

- Desktop side panes now share `clamp(224px, 19vw, 276px)` instead of the denser
  `clamp(240px, 23vw, 320px)`. At the normal 1280×720 browser viewport, Chat grew from about 691px
  to 793.6px without hiding Files or Projects.
- Welcome, messages, Live Work, and composer use a bounded viewport-balancing offset. When only one
  desktop pane is collapsed, content remains centered on the physical viewport instead of the
  asymmetric remaining grid area. Mobile drawers reset the offset.
- Packaged-browser measurement at 1280×720 and 100% zoom reported sidebar/workspace/inspector widths
  of 243.19/793.63/243.19px, exact content center 640px, and no horizontal or vertical overflow.
  With Projects collapsed and Files open, the welcome center was 640.006px with zero overflow.
- The sidebar was restored after the collapsed-state check. No viewport override was retained.

## Local-model response pipeline

- `LocalLlamaClient` now disables the OpenAI SDK's internal retry layer. The agent is the sole retry
  authority and retries only connection, timeout, 408/409/429, and server failures. Invalid requests
  such as a broken chat template fail once with their real error.
- `llama.stream_idle_timeout_seconds` defaults to 120 seconds, is validated, reaches the runtime
  client, and appears in English Web Model Settings. llama.cpp requests enable prompt caching,
  prompt-progress events, and five-second SSE keepalive.
- The stream accumulator preserves finish reason, prompt/cache/completion usage, first-token latency,
  and llama.cpp timings. High-frequency generation progress is throttled to four UI updates/second.
  Structured tool arguments are normalized safely when llama.cpp emits an object instead of text.
- Web Live Work distinguishes context loading, cached tokens, first token, generation, empty-response
  recovery, tools, and compaction. Completion activity can show token count and prediction speed;
  private reasoning remains outside the DOM.
- Default dynamic thought budgets are now 256/768/1536 tokens for low/medium/high. Off remains zero
  and unlimited remains `-1`. Completed-turn reasoning is stripped before the next user message but
  remains available within the current tool-calling turn and append-only session history.
- A reasoning-only or otherwise empty response is not appended to conversation history. The agent
  makes one immediate recovery attempt with reasoning temporarily off and in the user's language.
  If that also returns empty, the error includes both finish reasons and directs the owner to the
  chat template/response-token settings.

## Removed redundant work

- Automatic profile detection runs once per active evidence set rather than recursively scanning up
  to 20,000 files before every user turn. New evidence and explicit/auto-profile refreshes invalidate
  the cache. A model-initiated `MalDroid_detect_profile` result is applied directly without rescanning.
- An accepted investigation final now gets an automatic semantic MCP checkpoint immediately when
  needed. The old checkpoint reminder could force another entire model generation after the answer
  was already ready; that path is removed.
- Web returns the accepted answer immediately. It no longer performs a synchronous post-answer
  compaction; compaction occurs during an active context rollover or before the next turn.
- React Native and Native prompts use the already injected bounded methodology. They no longer force
  a redundant initial knowledge search unless version-specific or missing detail is needed.

## Research basis

- llama.cpp server documentation: prompt caching, `return_progress`, `sse_ping_interval`, usage,
  timings, and structured tool calling.
- llama.cpp function-calling documentation: correct `--jinja` tool template and `/props` verification.
- Google Gemma 4 prompt/function-calling documentation: remove generated thoughts between completed
  turns while retaining the single tool turn, and summarize durable long-run state.
- Official openai-python documentation: SDK defaults to two retries and a ten-minute timeout unless
  configured. MalDroid now explicitly owns both policies.
- ADR 0017 records the single-pass/observable-turn decision and its physical-acceptance boundary.

## Files changed

- Runtime: `src/maldroid/agent.py`, `cli.py`, `config.py`, `llama_client.py`, `profiles.py`,
  `prompts.py`, `runtime.py`, `ui.py`, and `web/server.py`.
- Web: `src/maldroid/web/static/app.js`, `index.html`, and `styles.css`.
- Tests: `tests/test_config.py`, `test_llama_client.py`, `test_tools_agent.py`, and
  `test_web_workspace.py`.
- Documentation: `ARCHITECTURE.md`, `CHANGELOG.md`, `DECISIONS.md`, `NEXT_AGENT_MASTER_PLAN.md`,
  `NEXT_STEPS.md`, `PROJECT_STATUS.md`, `README.md`, `SYSTEM_PROMPT.md`, `docs/CLI.md`,
  `docs/WEB.md`, and ADR 0017.

## Verification

Startup baseline before edits:

- `git status --short --branch` — clean `main...origin/main`.
- `git fetch origin && git pull --ff-only origin main` — already up to date.
- `./scripts/dev doctor` — Python/platform/ripgrep/config boundaries passed; expected local Linux
  absence of the owner's macOS llama-server and GGUF was reported.
- `./scripts/dev test` — 140 passed, one known Starlette/httpx2 deprecation warning.

Implementation checks:

- `./scripts/dev test tests/test_config.py tests/test_llama_client.py tests/test_tools_agent.py tests/test_web_workspace.py`
  — 74 passed, one known warning.
- `./scripts/dev lint` — Ruff passed; mypy passed for 43 source files.
- `./scripts/dev format-check` — 56 files formatted.
- Packaged in-app browser at 1280×720 — exact default and collapsed-pane centering, no overflow.
- `./scripts/dev release-check` after this handoff update — formatting, lint, type checking, 147
  tests, 72% coverage, wheel/archive verification, and installer dry-run passed.
- `./.venv/bin/python scripts/check_project_hygiene.py` — passed.
- `git diff --check` and `node --check src/maldroid/web/static/app.js` — passed.

## Known limitations and next task

- No real GGUF generation ran in this Linux workspace. `PLATFORM-011` must measure real prompt-cache
  hits, prompt-evaluation time, first-token latency, generation speed, tool-call correctness,
  checkpoint quality, Hebrew output, empty-response recovery, and cancellation on the owner's macOS
  installation.
- This task fixes transport/generation duplication and empty finals. It does not implement
  `AGENT-013` repeated identical tool/result strategy-loop detection.
- The existing Starlette `TestClient` warning about future httpx2 migration remains unchanged.
- The implementation tree was clean after commit `f09cebb`; this exact-commit handoff update is the
  only expected follow-up change before the final handoff commit.

Exact next command:

```bash
git status --short --branch && git log -5 --oneline && ./scripts/dev test
```

After commit/push/CI, begin `PLATFORM-011` on the owner's configured host. Do not mark this task as
physical-model accepted based only on synthetic stream fixtures.
