"""Polished terminal-first interactive chat for MalDroid."""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any

from prompt_toolkit import PromptSession
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.history import FileHistory
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.styles import Style as PromptStyle
from rich import box
from rich.console import Console, Group
from rich.markdown import Markdown
from rich.padding import Padding
from rich.panel import Panel
from rich.status import Status
from rich.table import Table
from rich.text import Text

from maldroid.agent import MalDroidAgent
from maldroid.case_manager import Case, CaseManager
from maldroid.investigation import InvestigationManager
from maldroid.process_manager import LlamaServerProcess
from maldroid.profiles import PROFILES, get_profile
from maldroid.tools.dispatcher import ToolExecutor
from maldroid.tools.models import mcp_tool_name
from maldroid.tools.registry import ToolRegistry

COMMANDS: dict[str, str] = {
    "/help": "Show commands and keyboard shortcuts",
    "/status": "Show the complete workspace status",
    "/context": "Show context usage and estimated capacity remaining",
    "/reasoning": "Show or change the model reasoning level",
    "/profile": "Show or change the active analysis profile",
    "/tools": "List tools available to the active profile",
    "/files": "List registered case files",
    "/findings": "Show durable investigation findings",
    "/todo": "List or update TODO items",
    "/plan": "Alias for /todo to view the investigation plan",
    "/dashboard": "Show the investigation dashboard",
    "/detail": "Show detailed, expandable view of recent activities or specific items",
    "/report": "Export the investigation state to a Markdown report in the case directory",
    "/skip-todo": "Mark a TODO item as completed/skipped",
    "/mark-blocked": "Mark a TODO item as blocked",
    "/note": "Save a durable progress note",
    "/explain": "Explain the agent's last decision",
    "/pause": "Pause autonomous investigation (or use Ctrl+C)",
    "/cancel": "Cancel the currently executing tool (or use Ctrl+C)",
    "/continue": "Resume autonomous investigation",
    "/checkpoints": "Show recent durable notes and session summary",
    "/history": "Show current session statistics",
    "/compact": "Save a summary and reclaim context",
    "/clear": "Clear chat context while preserving case state",
    "/server": "Show llama.cpp and MCP connection information",
    "/mcp": "Show the MCP endpoint and exposed tool count",
    "/knowledge": "Search the local static-analysis knowledge base",
    "/shortcuts": "Show terminal keyboard shortcuts",
    "/exit": "Save progress and exit",
    "/quit": "Alias for /exit",
}


class MalDroidCompleter(Completer):
    """Complete slash commands and profile names without network access."""

    def get_completions(self, document: Any, complete_event: Any) -> Any:
        before = document.text_before_cursor
        if not before.startswith("/"):
            return
        if before.startswith("/profile "):
            fragment = before.removeprefix("/profile ").lower()
            for profile in ("auto", *PROFILES):
                if profile.startswith(fragment):
                    yield Completion(profile, start_position=-len(fragment))
            return
        if before.startswith("/reasoning "):
            fragment = before.removeprefix("/reasoning ").lower()
            for level in ("off", "low", "medium", "high", "unlimited"):
                if level.startswith(fragment):
                    yield Completion(level, start_position=-len(fragment))
            return
        if " " in before:
            return
        for command, description in COMMANDS.items():
            if command.startswith(before):
                yield Completion(command, start_position=-len(before), display_meta=description)


class InteractiveChat:
    def __init__(
        self,
        console: Console,
        case: Case,
        case_manager: CaseManager,
        investigation: InvestigationManager,
        server: LlamaServerProcess,
        agent: MalDroidAgent,
        registry: ToolRegistry,
        dispatcher: ToolExecutor,
        mcp_endpoint: str,
    ):
        self.console = console
        self.case = case
        self.case_manager = case_manager
        self.investigation = investigation
        self.server = server
        self.agent = agent
        self.registry = registry
        self.dispatcher = dispatcher
        self.mcp_endpoint = mcp_endpoint
        self._status: Status | None = None
        self._turn_tools = 0
        self._turn_errors = 0
        self._active_phase = 1
        self._turn_started = 0.0
        self._turn_generated_tokens = 0
        self._current_generation_tokens = 0
        self._prompt_session: PromptSession[str] | None = None
        self.agent.event_handler = self._handle_agent_event

    def run(self) -> None:
        self._show_welcome()
        self._prompt_session = self._create_prompt_session()
        while True:
            try:
                text = self._read_input().strip()
            except EOFError:
                self.console.print("\n[dim]End of input received. Closing MalDroid.[/dim]")
                break
            except KeyboardInterrupt:
                self.console.print(
                    "\n[dim]Input cancelled. Press Ctrl+D or use /exit to close.[/dim]"
                )
                continue
            if not text:
                continue
            if text.startswith("/"):
                if not self._slash(text):
                    break
                continue
            self._run_turn(text)

    def _create_prompt_session(self) -> PromptSession[str] | None:
        if (
            not sys.stdin.isatty()
            or not self.console.is_terminal
            or os.environ.get("MALDROID_SIMPLE_INPUT") == "1"
        ):
            return None
        history_path = self.case.internal / "input-history"
        history_path.parent.mkdir(parents=True, exist_ok=True)
        bindings = KeyBindings()

        @bindings.add("enter")
        def submit(event: Any) -> None:
            event.current_buffer.validate_and_handle()

        @bindings.add("escape", "enter")
        def newline(event: Any) -> None:
            event.current_buffer.insert_text("\n")

        @bindings.add("c-l")
        def clear_screen(event: Any) -> None:
            event.app.renderer.clear()

        style = PromptStyle.from_dict(
            {
                "prompt": "bold #5fd7ff",
                "continuation": "#5f6b7a",
                "bottom-toolbar": "bg:#20252d #d0d7de",
                "toolbar.key": "bg:#20252d #5fd7ff bold",
                "toolbar.warning": "bg:#20252d #ffaf5f bold",
                "completion-menu.completion": "bg:#252b35 #d0d7de",
                "completion-menu.completion.current": "bg:#005f87 #ffffff",
                "completion-menu.meta.completion": "bg:#252b35 #8b949e",
                "completion-menu.meta.completion.current": "bg:#005f87 #ffffff",
            }
        )
        return PromptSession(
            history=FileHistory(str(history_path)),
            auto_suggest=AutoSuggestFromHistory(),
            completer=MalDroidCompleter(),
            complete_while_typing=False,
            key_bindings=bindings,
            style=style,
        )

    def _read_input(self) -> str:
        if self._prompt_session is None:
            return self.console.input("[bold cyan]❯[/bold cyan] ")
        return self._prompt_session.prompt(
            FormattedText([("class:prompt", "❯ ")]),
            multiline=True,
            prompt_continuation=FormattedText([("class:continuation", "│ ")]),
            bottom_toolbar=self._bottom_toolbar,
        )

    def _run_turn(self, text: str) -> None:
        self._turn_tools = 0
        self._turn_errors = 0
        self._active_phase = 1
        self._turn_generated_tokens = 0
        self._current_generation_tokens = 0
        if self.agent.should_auto_compact():
            self.console.print(
                "[yellow]Context threshold reached — creating a checkpoint…[/yellow]"
            )
            self.agent.compact()
        started = time.monotonic()
        self._turn_started = started
        try:
            with self.console.status("[bold cyan]Thinking…[/bold cyan]", spinner="dots") as status:
                self._status = status
                response = self.agent.respond(text)
        except KeyboardInterrupt:
            self.console.print("\n[yellow]Current response interrupted.[/yellow]")
            return
        except Exception as exc:
            self.console.print()
            error_id = f"ERR-{int(time.time())}"
            self.console.print(
                Panel(
                    Text.assemble(
                        (f"[{error_id}] The active turn paused after an error.\n\n", "bold yellow"),
                        ("Failed Component: ", "bold"), f"{exc.__class__.__name__}\n",
                        ("Details: ", "bold"), f"{str(exc)}\n\n",
                        ("State Impact: ", "bold cyan"), "Durable case state is preserved. No corruption occurred.\n",
                        ("Next Steps: ", "bold cyan"), "Check /server status, verify dependencies, and press Enter to retry.",
                    ),
                    title="Execution Interrupted",
                    border_style="yellow",
                )
            )
            return
        finally:
            self._status = None
        elapsed = time.monotonic() - started
        self.console.print()
        self.console.print(Text("MalDroid", style="bold cyan"))
        try:
            self.console.print(Padding(Markdown(response), (0, 0, 0, 2)))
        except Exception:
            self.console.print(Padding(response, (0, 0, 0, 2)))
        if self.agent.should_auto_compact():
            self.console.print("[yellow]Saving progress and reclaiming context…[/yellow]")
            self.agent.compact()
        self._show_turn_footer(elapsed)

    def _handle_agent_event(self, event: str, data: dict[str, Any]) -> None:
        if event == "model_start":
            self._current_generation_tokens = 0
            phase = int(data.get("phase", 1))
            self._active_phase = phase
            round_number = int(data.get("total_tool_rounds", 0)) + 1
            self._update_status(f"Thinking · phase {phase} · round {round_number}")
        elif event == "generation_progress":
            self._current_generation_tokens = int(data.get("completion_tokens_estimate", 0))
            activity = (
                "Reasoning"
                if int(data.get("reasoning_characters", 0)) > int(data.get("content_characters", 0))
                else "Generating"
            )
            self._update_status(activity + "…")
        elif event == "generation_complete":
            self._turn_generated_tokens += int(data.get("completion_tokens", 0))
            self._current_generation_tokens = 0
        elif event == "tool_start":
            self._turn_tools += 1
            name = self._short_tool_name(str(data.get("name", "tool")))
            preview = self._argument_preview(data.get("arguments"))
            self._update_status(f"Running {name}…")
            line = Text()
            line.append("● ", style="cyan")
            line.append(name, style="bold")
            if preview:
                line.append("  " + preview, style="dim")
            self.console.print(line)
        elif event == "tool_result":
            status = str(data.get("status", "completed"))
            name = self._short_tool_name(str(data.get("name", "tool")))
            if status == "completed":
                suffix = " · output saved" if data.get("output_file") else ""
                if data.get("truncated"):
                    suffix += " · preview truncated"
                self.console.print(f"  [green]✓[/green] [dim]{name}{suffix}[/dim]")
            else:
                self._turn_errors += 1
                error = str(data.get("error") or "unknown error")
                self.console.print(f"  [red]✗ {name}:[/red] {error}")
        elif event == "checkpoint_required":
            self._update_status("Saving a durable progress checkpoint…")
            self.console.print("[yellow]◆ Ensuring progress is recorded before answering[/yellow]")
        elif event == "state_discipline_required":
            self._update_status("Organizing TODOs and findings…")
            self.console.print(
                "[cyan]◆ Updating durable TODO/Finding state before deeper investigation[/cyan]"
            )
        elif event == "automatic_checkpoint":
            self.console.print("[yellow]◆ Automatic progress checkpoint saved[/yellow]")
        elif event == "phase_checkpoint":
            phase = data.get("phase", "?")
            rounds = data.get("total_tool_rounds", "?")
            self.console.print(
                f"[yellow]◆ Autonomous phase {phase} checkpoint saved after {rounds} rounds[/yellow]"
            )
        elif event == "phase_rollover":
            phase = int(data.get("completed_phase", 1)) + 1
            reason = str(data.get("reason", "tool_window"))
            self._update_status(f"Preparing autonomous phase {phase}…")
            reason_text = (
                "context threshold reached"
                if reason == "context_threshold"
                else "tool window completed"
            )
            self.console.print(
                f"[cyan]↻ {reason_text}; continuing automatically in phase {phase}. "
                "No input required.[/cyan]"
            )
        elif event == "model_retry":
            attempt = int(data.get("attempt", 1)) + 1
            maximum = data.get("max_attempts", "?")
            delay = data.get("delay_seconds", 0)
            self._current_generation_tokens = 0
            self.console.print(
                f"[yellow]↻ Model request interrupted; retrying {attempt}/{maximum} "
                f"in {delay:g}s.[/yellow]"
            )
        elif event == "profile_change":
            profile = data.get("profile", "generic")
            mode = data.get("mode", "auto")
            self.console.print(
                f"[green]◆ Profile selected: [bold]{profile}[/bold] ({mode})[/green]"
            )
            self._update_status(f"Profile adapted to {profile}…")
        elif event == "compaction_start":
            self._update_status("Compacting context…")
        elif event == "compaction_complete":
            self.console.print(
                "[green]✓ Context compacted; durable case state was preserved.[/green]"
            )

    def _update_status(self, message: str) -> None:
        if self._status is not None:
            generated = self._turn_generated_tokens + self._current_generation_tokens
            used = self.agent.estimate_tokens() + self._current_generation_tokens
            total = max(1, self.case.state.context_size)
            remaining = max(0, total - used)
            elapsed = max(0.0, time.monotonic() - self._turn_started)
            self._status.update(
                f"[bold cyan]{message}[/bold cyan] [dim]· {elapsed:.0f}s · "
                f"out ≈{generated:,} tok · ctx ≈{used:,}/{total:,} · "
                f"≈{remaining:,} left[/dim]"
            )

    def _show_welcome(self) -> None:
        server_status = self.server.status()
        model = Path(self.case.state.model_path).name or "not configured"
        details = Table.grid(padding=(0, 2))
        details.add_column(style="dim", no_wrap=True)
        details.add_column()
        details.add_row("Case", self.case.metadata.name)
        details.add_row("Profile", f"{self.case.state.active_profile} · {self.agent.profile_mode}")
        details.add_row("Reasoning", self.agent.reasoning_level)
        details.add_row("Model", model)
        details.add_row("llama.cpp", self._server_label(server_status))
        details.add_row("MCP", self.mcp_endpoint)
        details.add_row("Workspace", str(self.case.root))
        title = Text("MalDroid", style="bold cyan")
        subtitle = Text("Local Android static-analysis workspace", style="dim")
        self.console.print()
        self.console.print(
            Panel(
                Group(title, subtitle, Text(), details),
                border_style="cyan",
                padding=(1, 2),
            )
        )
        
        if not self.case.state.findings and not self.case.state.todos:
            self.console.print(
                Panel(
                    Text.assemble(
                        ("Welcome to your new MalDroid investigation!\n\n", "bold green"),
                        "This case workspace is managed and tracked. Here is how it works:\n",
                        ("Evidence: ", "bold cyan"), "Drop files or symlinks into the workspace.\n",
                        ("Profiles: ", "bold cyan"), "MalDroid uses specific profiles (e.g. android-static) to guide analysis.\n",
                        ("State: ", "bold cyan"), "The agent works autonomously but records explicit TODOs and Findings.\n",
                        ("Commands: ", "bold cyan"), "Use `/dashboard` to view status, or type a natural language prompt to begin.\n\n",
                        ("Try this: ", "dim"), "Analyze the main binary for hardcoded credentials."
                    ),
                    title="Getting Started",
                    border_style="green",
                    padding=(1, 2)
                )
            )
        self.console.print(
            "[dim]Enter[/dim] send  [dim]Alt+Enter[/dim] newline  "
            "[dim]Tab[/dim] complete  [dim]↑/↓[/dim] history  "
            "[dim]Ctrl+D[/dim] exit  [cyan]/help[/cyan] commands\n"
        )

    def _bottom_toolbar(self) -> FormattedText:
        used, total, remaining, percent = self._context_numbers()
        style = "class:toolbar.warning" if percent >= 70 else "class:toolbar.key"
        open_todos = sum(item.status == "open" for item in self.case.state.todos)
        return FormattedText(
            [
                (
                    "class:toolbar.key",
                    f" {self.agent.profile_mode}:{self.case.state.active_profile} ",
                ),
                ("class:bottom-toolbar", "│ "),
                ("class:toolbar.key", f"reason {self.agent.reasoning_level}"),
                ("class:bottom-toolbar", " │ "),
                (style, f"ctx {percent:.0f}% · ~{remaining:,} left"),
                ("class:bottom-toolbar", " │ "),
                ("class:toolbar.key", f"{len(self.case.state.findings)} findings"),
                ("class:bottom-toolbar", " · "),
                ("class:toolbar.key", f"{open_todos} todos"),
                ("class:bottom-toolbar", " · "),
                ("class:toolbar.key", f"{len(self.case.state.notes)} notes "),
            ]
        )

    def _show_turn_footer(self, elapsed: float) -> None:
        _, _, remaining, percent = self._context_numbers()
        color = "yellow" if percent >= 70 else "dim"
        phase_label = "phase" if self._active_phase == 1 else "phases"
        error_label = "error" if self._turn_errors == 1 else "errors"
        self.console.print(
            f"[{color}]── {elapsed:.1f}s · {self._turn_tools} tools · "
            f"{self._active_phase} {phase_label} · {self._turn_errors} {error_label} · "
            f"≈{self._turn_generated_tokens:,} generated tokens · "
            f"context {percent:.1f}% · ~{remaining:,} tokens left[/{color}]\n"
        )

    def _slash(self, command: str) -> bool:
        name, _, rest = command.partition(" ")
        name = name.lower()
        rest = rest.strip()
        if name in {"/exit", "/quit"}:
            return False
        if name == "/help":
            self._show_help()
        elif name == "/shortcuts":
            self._show_shortcuts()
        elif name == "/status":
            self._show_status()
        elif name == "/context":
            self._show_context()
        elif name == "/reasoning":
            self._reasoning(rest)
        elif name == "/profile":
            self._profile(rest)
        elif name == "/tools":
            self._show_tools()
        elif name == "/files":
            self._render_tool_result(self.dispatcher.execute(mcp_tool_name("list_case_files"), {}))
        elif name == "/findings":
            self._show_findings()
        elif name == "/todo" or name == "/plan":
            self._todo(rest)
        elif name == "/dashboard":
            self._show_dashboard()
        elif name == "/detail":
            self._show_detail(rest)
        elif name == "/report":
            self._export_report()
        elif name == "/skip-todo":
            if not rest:
                self.console.print("Usage: [cyan]/skip-todo TODO_ID[/cyan]")
            else:
                self._todo(f"{rest} status completed")
        elif name == "/mark-blocked":
            if not rest:
                self.console.print("Usage: [cyan]/mark-blocked TODO_ID[/cyan]")
            else:
                self._todo(f"{rest} status blocked")
        elif name == "/explain":
            self.console.print("[dim]Generating explanation...[/dim]")
            self.console.print("The agent's state is currently: " + self.agent.state.value)
        elif name in {"/pause", "/cancel"}:
            self.console.print("[yellow]To interrupt the agent or cancel a tool, use Ctrl+C.[/yellow]")
        elif name == "/continue":
            self.console.print("[green]Resuming investigation...[/green]")
            return False # allow loop to run agent again
        elif name == "/note":
            self._note(rest)
        elif name == "/checkpoints":
            self._show_checkpoints()
        elif name == "/history":
            self._show_history()
        elif name == "/compact":
            with self.console.status("[cyan]Compacting context…[/cyan]", spinner="dots") as status:
                self._status = status
                summary = self.agent.compact()
                self._status = None
            self.console.print(
                Panel(Markdown(summary), title="Session checkpoint", border_style="green")
            )
        elif name == "/clear":
            self.agent.clear()
            self.console.print(
                "[green]✓[/green] Chat context cleared; durable case state was preserved."
            )
        elif name in {"/server", "/mcp"}:
            self._show_server(mcp_only=name == "/mcp")
        elif name == "/knowledge":
            self._render_tool_result(
                self.dispatcher.execute(
                    mcp_tool_name("search_knowledge"),
                    {"query": rest or "Android static analysis"},
                )
            )
        else:
            self.console.print(f"[red]Unknown command:[/red] {name}. Type [cyan]/help[/cyan].")
        return True

    def _show_help(self) -> None:
        table = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
        table.add_column(style="bold cyan", no_wrap=True)
        table.add_column()
        for command, description in COMMANDS.items():
            table.add_row(command, description)
        self.console.print(Panel(table, title="Commands", border_style="cyan"))
        self.console.print("[dim]Tip: type part of a slash command and press Tab.[/dim]")

    def _show_shortcuts(self) -> None:
        rows = [
            ("Enter", "Send the current message"),
            ("Alt+Enter / Esc then Enter", "Insert a newline"),
            ("Tab", "Complete slash commands and profiles"),
            ("↑ / ↓", "Navigate persistent input history"),
            ("Ctrl+L", "Clear the terminal display"),
            ("Ctrl+C", "Cancel current input or response"),
            ("Ctrl+D", "Exit when the input is empty"),
        ]
        table = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
        table.add_column(style="bold cyan")
        table.add_column()
        for key, action in rows:
            table.add_row(key, action)
        self.console.print(Panel(table, title="Keyboard shortcuts", border_style="cyan"))

    def _show_status(self) -> None:
        used, total, remaining, percent = self._context_numbers()
        server = self.server.status()
        rows = [
            ("Case", self.case.metadata.name),
            ("Case ID", self.case.metadata.case_id),
            ("Workspace", str(self.case.root)),
            (
                "Profile",
                f"{self.case.state.active_profile} ({self.agent.profile_mode})",
            ),
            ("Reasoning", self.agent.reasoning_level),
            ("Model", self.case.state.model_path or "not configured"),
            ("Context", f"~{used:,} / {total:,} tokens ({percent:.1f}%)"),
            ("Remaining", f"~{remaining:,} tokens"),
            ("llama.cpp", self._server_label(server)),
            ("MCP", self.mcp_endpoint),
            ("Available tools", str(len(self.registry.enabled(self.case.state.active_profile)))),
            ("Findings", str(len(self.case.state.findings))),
            ("Open TODOs", str(sum(item.status == "open" for item in self.case.state.todos))),
            ("Progress notes", str(len(self.case.state.notes))),
        ]
        if server.get("api_key_enabled"):
            rows.insert(9, ("API key", str(server.get("api_key") or "unavailable")))
        table = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
        table.add_column(style="dim", no_wrap=True)
        table.add_column()
        for key, value in rows:
            table.add_row(key, value)
        self.console.print(Panel(table, title="Workspace status", border_style="cyan"))

    def _show_dashboard(self) -> None:
        from rich.layout import Layout
        from rich.panel import Panel
        from rich.table import Table

        layout = Layout()
        layout.split_column(
            Layout(name="header", size=3),
            Layout(name="main"),
        )
        layout["main"].split_row(
            Layout(name="left"),
            Layout(name="right"),
        )

        # Header
        used, total, remaining, percent = self._context_numbers()
        header = Text(f"MalDroid Dashboard: {self.case.metadata.name} ({self.case.metadata.case_id}) | Context: {percent:.1f}% used", style="bold cyan", justify="center")
        layout["header"].update(Panel(header, border_style="blue"))

        # Left: Findings
        findings_table = Table(box=box.SIMPLE, show_header=False)
        for item in self.case.state.findings[:5]:
            findings_table.add_row(f"[{item.severity}]", item.title)
        if not self.case.state.findings:
            findings_table.add_row("[dim]No findings recorded[/dim]")
        layout["left"].update(Panel(findings_table, title="Top Findings", border_style="cyan"))

        # Right: TODOs
        todos_table = Table(box=box.SIMPLE, show_header=False)
        open_todos = [t for t in self.case.state.todos if t.status == "open"]
        for item in open_todos[:5]:
            todos_table.add_row(f"[{item.priority}]", item.text)
        if not open_todos:
            todos_table.add_row("[dim]No open TODOs[/dim]")
        layout["right"].update(Panel(todos_table, title="Open TODOs", border_style="cyan"))

        self.console.print(layout)

    def _show_detail(self, target: str) -> None:
        if not target:
            self.console.print("Usage: [cyan]/detail recent[/cyan] or [cyan]/detail TODO_ID[/cyan]")
            return
            
        from rich.panel import Panel
        
        if target.lower() == "recent":
            self.console.print(Panel("Recent Activity Details", border_style="blue"))
            self.console.print("Expanded activity details are not fully implemented yet in this interface.")
            return
            
        # Try finding a matching TODO
        matched = [t for t in self.case.state.todos if str(t.id) == target]
        if matched:
            t = matched[0]
            self.console.print(Panel(f"TODO {t.id} Details:\nStatus: {t.status}\nText: {t.text}\nDependencies: {t.dependencies}", border_style="cyan"))
            return
            
        self.console.print(f"[yellow]Target '{target}' not found for detailed expansion.[/yellow]")

    def _export_report(self) -> None:
        report_path = self.case.root / "report.md"
        lines = [
            f"# MalDroid Investigation Report: {self.case.metadata.name}",
            f"**Case ID:** {self.case.metadata.case_id}",
            f"**Created:** {self.case.metadata.created_at}",
            f"**Profile:** {self.case.state.active_profile}",
            "",
            "## Findings",
        ]
        
        for f in self.case.state.findings:
            lines.extend([
                f"### {f.title} [{f.severity}]",
                f"**Confidence:** {f.confidence} | **Status:** {f.status} | **Verified:** {f.verification_status}",
                f"{f.summary}",
                "",
                "**Evidence:**",
                f"```json\n{f.evidence}\n```",
                "",
            ])
            
        lines.extend(["## Open TODOs"])
        for t in self.case.state.todos:
            if t.status == "open":
                lines.extend([f"- [{t.priority}] {t.text}"])
                
        lines.extend(["", "## Notes"])
        for n in self.case.state.notes:
            lines.extend([f"- **{n.kind}**: {n.text}"])
            
        report_path.write_text("\n".join(lines), encoding="utf-8")
        self.console.print(f"[bold green]Report exported to:[/bold green] {report_path}")

    def _show_context(self) -> None:
        used, total, remaining, percent = self._context_numbers()
        width = 36
        filled = min(width, round(width * percent / 100))
        meter = Text("█" * filled, style="yellow" if percent >= 70 else "cyan")
        meter.append("░" * (width - filled), style="bright_black")
        message = Text.assemble(
            meter,
            f"  {percent:.1f}%\n\n",
            (f"~{used:,}", "bold"),
            f" estimated tokens used\n~{remaining:,} estimated tokens remain\n",
            (
                f"Automatic compaction starts at {self.agent.config.limits.auto_compact_ratio:.0%}.",
                "dim",
            ),
        )
        self.console.print(Panel(message, title=f"Context · {total:,} tokens", border_style="cyan"))

    def _profile(self, name: str) -> None:
        if not name:
            table = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
            for profile in PROFILES.values():
                marker = "●" if profile.name == self.case.state.active_profile else "○"
                table.add_row(marker, profile.name, profile.instruction)
            self.console.print(
                Panel(
                    table,
                    title=f"Analysis profiles · mode {self.agent.profile_mode}",
                    border_style="cyan",
                )
            )
            self.console.print(
                "[dim]Auto mode inspects bounded artifact indicators and adapts the active "
                "profile. Use /profile NAME only to force a manual override.[/dim]"
            )
            return
        if name == "auto":
            self.agent.enable_auto_profile()
            self.console.print(
                f"[green]✓[/green] Automatic profile selection enabled: "
                f"[bold]{self.case.state.active_profile}[/bold]"
            )
            return
        profile = get_profile(name)
        if profile.status != "implemented":
            self.console.print(
                f"[yellow]Profile {name} is documented but not implemented yet.[/yellow]"
            )
            return
        self.agent.switch_profile(name, automatic=False)
        self.console.print(
            f"[green]✓[/green] Manual profile override: [bold]{name}[/bold]. "
            "Use /profile auto to resume detection."
        )

    def _reasoning(self, level: str) -> None:
        levels = {
            "off": "No thinking budget; answer immediately",
            "low": "Up to 512 reasoning tokens for quick tasks",
            "medium": "Up to 1,536 reasoning tokens for normal analysis",
            "high": "Up to 3,072 reasoning tokens for difficult analysis",
            "unlimited": "No explicit reasoning-token limit",
        }
        if not level:
            table = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
            for name, description in levels.items():
                marker = "●" if name == self.agent.reasoning_level else "○"
                table.add_row(marker, name, description)
            self.console.print(Panel(table, title="Reasoning level", border_style="cyan"))
            self.console.print(
                "[dim]Change for this session with /reasoning LEVEL; persist with "
                "maldroid config set llama.reasoning_level LEVEL.[/dim]"
            )
            return
        if level not in levels:
            self.console.print("[red]Unknown reasoning level.[/red] Choose: " + ", ".join(levels))
            return
        self.agent.set_reasoning_level(level)  # type: ignore[arg-type]
        self.console.print(
            f"[green]✓[/green] Reasoning changed to [bold]{level}[/bold] for this session."
        )

    def _show_tools(self) -> None:
        tools = self.registry.enabled(self.case.state.active_profile)
        table = Table("Tool", "Scope", "Description", box=box.SIMPLE, padding=(0, 1))
        for tool in tools:
            table.add_row(tool.name, tool.profile, tool.description)
        external_count = 0
        if self.agent.external_mcp is not None:
            for schema in self.agent.external_mcp.schemas():
                function = schema.get("function", {})
                table.add_row(
                    str(function.get("name", "external-tool")),
                    "external MCP",
                    str(function.get("description", "")),
                )
                external_count += 1
        self.console.print(
            Panel(
                table,
                title=(f"Tools · {self.case.state.active_profile} · {len(tools) + external_count}"),
                border_style="cyan",
            )
        )

    def _show_findings(self) -> None:
        if not self.case.state.findings:
            self.console.print("[dim]No findings have been recorded yet.[/dim]")
            return
        table = Table("ID", "Severity", "Status", "Finding", box=box.SIMPLE, padding=(0, 1))
        for item in self.case.state.findings:
            table.add_row(item.id, item.severity, item.status, item.title)
        self.console.print(Panel(table, title="Findings", border_style="cyan"))

    def _todo(self, rest: str) -> None:
        if rest:
            action, _, value = rest.partition(" ")
            try:
                result = self.investigation.update_todo(self.case, action, value)
            except Exception as exc:
                self.console.print(f"[red]TODO update failed:[/red] {exc}")
                return
            label = result.id if result else value
            self.console.print(f"[green]✓[/green] TODO updated: {label}")
            return
        if not self.case.state.todos:
            self.console.print("[dim]No TODO items have been recorded yet.[/dim]")
            return
        table = Table("", "ID", "Task", box=box.SIMPLE, padding=(0, 1))
        for item in self.case.state.todos:
            marker = "✓" if item.status == "completed" else "○"
            style = "dim" if item.status == "completed" else ""
            table.add_row(marker, item.id, Text(item.text, style=style))
        self.console.print(Panel(table, title="TODO", border_style="cyan"))

    def _note(self, text: str) -> None:
        if not text:
            self.console.print("Usage: [cyan]/note TEXT[/cyan]")
            return
        note = self.investigation.save_note(self.case, text)
        self.console.print(f"[green]✓[/green] Durable note saved: [bold]{note.id}[/bold]")

    def _show_checkpoints(self) -> None:
        if not self.case.state.notes and not self.case.state.summary:
            self.console.print("[dim]No progress checkpoints have been recorded yet.[/dim]")
            return
        blocks: list[Any] = []
        if self.case.state.summary:
            blocks.extend(
                [
                    Text("Latest session summary", style="bold cyan"),
                    Markdown(self.case.state.summary),
                ]
            )
        if self.case.state.notes:
            blocks.append(Text("Recent Checkpoints & Notes", style="bold cyan"))
            for note in self.case.state.notes[-5:]:
                if note.kind == "checkpoint":
                    cp_text = f"[bold]Objective:[/bold] {note.objective}\n"
                    cp_text += f"[bold]Completed Work:[/bold] {note.completed_work}\n"
                    cp_text += f"[bold]Next Action:[/bold] {note.next_action}"
                    if note.failed_approaches and note.failed_approaches.lower() not in ("none", "n/a"):
                        cp_text += f"\n[bold yellow]Failed Approaches:[/bold yellow] {note.failed_approaches}"
                    blocks.append(Panel(Text.from_markup(cp_text), title=f"Checkpoint {note.id} · {note.created_at}", border_style="blue"))
                else:
                    blocks.append(Text(f"[{note.kind}] {note.id} · {note.created_at}", style="dim"))
                    blocks.append(Text(note.text))
        self.console.print(Panel(Group(*blocks), title="State Progress", border_style="cyan"))

    def _show_history(self) -> None:
        history_path = self.agent.sessions.history_path
        counts: dict[str, int] = {}
        if history_path.exists():
            for line in history_path.read_text(encoding="utf-8", errors="replace").splitlines():
                try:
                    event = json.loads(line)
                    event_type = str(event.get("type", "unknown"))
                    counts[event_type] = counts.get(event_type, 0) + 1
                except json.JSONDecodeError:
                    counts["invalid"] = counts.get("invalid", 0) + 1
        table = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
        table.add_row("Session", str(self.agent.sessions.number))
        table.add_row("Log", str(history_path))
        table.add_row("Messages", str(counts.get("message", 0)))
        table.add_row("Tool calls", str(counts.get("tool_call", 0)))
        table.add_row("Compactions", str(counts.get("compaction", 0)))
        self.console.print(Panel(table, title="Current session", border_style="cyan"))

    def _show_server(self, mcp_only: bool = False) -> None:
        table = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
        if not mcp_only:
            for key, value in self.server.status().items():
                table.add_row("llama." + str(key), str(value))
        table.add_row("mcp.endpoint", self.mcp_endpoint)
        table.add_row("mcp.transport", "streamable-http")
        table.add_row("mcp.tools", str(len(self.registry.enabled(self.case.state.active_profile))))
        if self.agent.external_mcp is not None:
            for status in self.agent.external_mcp.statuses:
                details = f"{status['status']} · {status['tools']} tools · {status['url']}"
                if status.get("error"):
                    details += " · " + str(status["error"])[:160]
                table.add_row(
                    "external." + str(status["nickname"]),
                    details,
                )
        self.console.print(
            Panel(table, title="MCP" if mcp_only else "Local servers", border_style="cyan")
        )

    def _render_tool_result(self, result: Any) -> None:
        if result.status == "error":
            message = result.error.message if result.error else "Unknown tool error"
            self.console.print(f"[red]Tool failed:[/red] {message}")
            return
        payload = json.dumps(result.data, ensure_ascii=False, indent=2, default=str)
        if len(payload) > 12000:
            payload = payload[:12000] + "\n… output preview truncated"
        self.console.print(Panel(payload, border_style="cyan"))
        if result.output_file:
            self.console.print(f"[dim]Full output: {result.output_file}[/dim]")

    def _context_numbers(self) -> tuple[int, int, int, float]:
        used = self.agent.estimate_tokens()
        total = max(1, self.case.state.context_size)
        remaining = max(0, total - used)
        percent = min(100.0, used / total * 100)
        return used, total, remaining, percent

    @staticmethod
    def _short_tool_name(name: str) -> str:
        return name.removeprefix("MalDroid_")

    @staticmethod
    def _argument_preview(arguments: Any) -> str:
        if not arguments:
            return ""
        if isinstance(arguments, str):
            value = arguments
        else:
            value = json.dumps(arguments, ensure_ascii=False, default=str)
        value = " ".join(value.split())
        return value if len(value) <= 160 else value[:157] + "…"

    @staticmethod
    def _server_label(status: dict[str, Any]) -> str:
        if not status.get("running"):
            return "stopped"
        port = status.get("port")
        pid = status.get("pid")
        return f"running · port {port} · pid {pid}"
