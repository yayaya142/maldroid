"""Reliable line-oriented terminal chat and slash commands."""

from __future__ import annotations

from rich.console import Console

from maldroid.agent import MalDroidAgent
from maldroid.case_manager import Case, CaseManager
from maldroid.investigation import InvestigationManager
from maldroid.process_manager import LlamaServerProcess
from maldroid.profiles import get_profile
from maldroid.tools.dispatcher import ToolDispatcher
from maldroid.tools.registry import ToolRegistry

HELP = """/help, /exit, /status, /profile [NAME], /tools, /files, /findings,
/todo [add|complete|reopen|remove VALUE], /note TEXT, /compact, /clear,
/server, /knowledge"""


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
        dispatcher: ToolDispatcher,
    ):
        self.console = console
        self.case = case
        self.case_manager = case_manager
        self.investigation = investigation
        self.server = server
        self.agent = agent
        self.registry = registry
        self.dispatcher = dispatcher

    def run(self) -> None:
        self.console.print("\n[bold]MalDroid[/bold]\n")
        self.console.print(f"Case: {self.case.metadata.name}")
        self.console.print(f"Path: {self.case.root}")
        self.console.print(f"Profile: {self.case.state.active_profile}")
        self.console.print(f"Context: {self.case.state.context_size}")
        self.console.print("\nType /help for available commands.\n")
        while True:
            try:
                text = self.console.input("[bold cyan]>[/bold cyan] ").strip()
            except (EOFError, KeyboardInterrupt):
                self.console.print()
                break
            if not text:
                continue
            if text.startswith("/"):
                if not self._slash(text):
                    break
                continue
            estimate = self.agent.estimate_tokens()
            ratio = estimate / self.case.state.context_size
            if ratio >= 0.85:
                self.console.print("Context usage is above 85%. Run /compact before continuing.")
                continue
            if ratio >= 0.75:
                self.console.print(
                    "[yellow]Context usage is above 75%; consider /compact.[/yellow]"
                )
            self.console.print(self.agent.respond(text))

    def _slash(self, command: str) -> bool:
        name, _, rest = command.partition(" ")
        rest = rest.strip()
        if name == "/exit":
            return False
        if name == "/help":
            self.console.print(HELP)
        elif name == "/status":
            self.console.print_json(
                data={
                    "case_id": self.case.metadata.case_id,
                    "name": self.case.metadata.name,
                    "path": str(self.case.root),
                    "profile": self.case.state.active_profile,
                    "model": self.case.state.model_path,
                    "context_size": self.case.state.context_size,
                    "server": self.server.status(),
                    "tool_count": len(self.registry.enabled(self.case.state.active_profile)),
                    "findings": len(self.case.state.findings),
                    "open_todos": sum(item.status == "open" for item in self.case.state.todos),
                    "conversation_tokens_estimate": self.agent.estimate_tokens(),
                }
            )
        elif name == "/profile":
            if not rest:
                self.console.print(self.case.state.active_profile)
            else:
                profile = get_profile(rest)
                if profile.status != "implemented":
                    self.console.print(f"Profile {rest} is documented but not implemented yet.")
                else:
                    self.agent.switch_profile(rest)
                    self.case_manager.save(self.case)
                    self.console.print(f"Active profile: {rest}")
        elif name == "/tools":
            self.console.print("\n".join(self.registry.names(self.case.state.active_profile)))
        elif name == "/files":
            self.console.print_json(
                data=self.dispatcher.execute("list_case_files", {}).model_dump()
            )
        elif name == "/findings":
            self.console.print_json(data=[item.model_dump() for item in self.case.state.findings])
        elif name == "/todo":
            if rest:
                action, _, value = rest.partition(" ")
                result = self.investigation.update_todo(self.case, action, value)
                self.console.print_json(data=result.model_dump() if result else {"removed": value})
            else:
                self.console.print_json(data=[item.model_dump() for item in self.case.state.todos])
        elif name == "/note":
            if not rest:
                self.console.print("Usage: /note TEXT")
            else:
                note = self.investigation.save_note(self.case, rest)
                self.console.print(f"Saved {note.id}")
        elif name == "/compact":
            self.console.print(self.agent.compact())
        elif name == "/clear":
            self.agent.clear()
            self.console.print("Active conversation context cleared; case state was preserved.")
        elif name == "/server":
            self.console.print_json(data=self.server.status())
        elif name == "/knowledge":
            tool_result = self.dispatcher.execute(
                "search_knowledge", {"query": rest or "Android static analysis"}
            )
            self.console.print_json(data=tool_result.model_dump())
        else:
            self.console.print(f"Unknown command: {name}. Type /help.")
        return True
