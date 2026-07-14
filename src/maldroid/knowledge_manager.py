"""Markdown playbook discovery and bounded FTS5 retrieval."""

from __future__ import annotations

import re
import shutil
import sqlite3
import sys
from pathlib import Path
from typing import Any

import yaml

from maldroid.case_manager import Case
from maldroid.exceptions import CaseError
from maldroid.paths import config_directory, expand_path


class KnowledgeManager:
    def __init__(self, case: Case):
        self.case = case
        self.database = case.internal / "indexes" / "knowledge.sqlite"
        self.database.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS documents (
                    id INTEGER PRIMARY KEY,
                    document_key TEXT UNIQUE NOT NULL,
                    path TEXT NOT NULL,
                    title TEXT NOT NULL,
                    profile TEXT NOT NULL,
                    tags TEXT NOT NULL,
                    last_verified TEXT
                );
                CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_search USING fts5(
                    document_key UNINDEXED, title, profile, tags, content
                );
                """
            )

    def roots(self) -> list[Path]:
        installed = Path(sys.prefix) / "share" / "maldroid" / "knowledge"
        source_tree = Path(__file__).resolve().parents[2] / "knowledge"
        built_in = installed if installed.exists() else source_tree
        return [built_in, config_directory() / "knowledge", self.case.internal / "knowledge"]

    def add(self, source: Path, profile: str = "generic", copy: bool = True) -> Path:
        source = expand_path(source)
        if not source.is_file() or source.suffix.lower() != ".md":
            raise CaseError("Knowledge sources must be existing Markdown files.")
        destination_root = config_directory() / "knowledge" / profile
        destination_root.mkdir(parents=True, exist_ok=True)
        destination = destination_root / source.name
        if destination.exists():
            raise CaseError(f"Knowledge document already exists: {destination}")
        if not copy:
            raise CaseError("User knowledge must be copied to remain stable and local.")
        shutil.copy2(source, destination)
        return destination

    def reindex(self) -> dict[str, int]:
        documents: list[tuple[str, Path, dict[str, Any], str]] = []
        for root in self.roots():
            if not root.exists():
                continue
            for path in root.rglob("*.md"):
                content = path.read_text(encoding="utf-8", errors="replace")
                metadata, body = _front_matter(content)
                key = f"{root.name}/{path.relative_to(root).as_posix()}"
                metadata.setdefault("title", _first_heading(body) or path.stem)
                metadata.setdefault(
                    "profile", path.parent.name if path.parent != root else "generic"
                )
                documents.append((key, path, metadata, body))
        with self._connect() as connection:
            connection.execute("DELETE FROM documents")
            connection.execute("DELETE FROM knowledge_search")
            for key, path, metadata, body in documents:
                tags = metadata.get("tags", [])
                tags_text = ",".join(tags) if isinstance(tags, list) else str(tags)
                connection.execute(
                    "INSERT INTO documents(document_key,path,title,profile,tags,last_verified) "
                    "VALUES(?,?,?,?,?,?)",
                    (
                        key,
                        str(path),
                        str(metadata["title"]),
                        str(metadata["profile"]),
                        tags_text,
                        str(metadata.get("last_verified"))
                        if metadata.get("last_verified")
                        else None,
                    ),
                )
                connection.execute(
                    "INSERT INTO knowledge_search(document_key,title,profile,tags,content) VALUES(?,?,?,?,?)",
                    (key, metadata["title"], metadata["profile"], tags_text, body),
                )
        return {"documents": len(documents)}

    def list_documents(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT document_key,title,profile,tags,last_verified FROM documents ORDER BY profile,title"
            ).fetchall()
        return [dict(row) for row in rows]

    def search(self, query: str, profile: str, limit: int = 10) -> list[dict[str, Any]]:
        terms = re.findall(r"[\w.-]+", query, re.UNICODE)
        if not terms:
            raise CaseError("The knowledge query has no indexable terms.")
        expression = " OR ".join(f'"{term}"' for term in terms)
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT s.document_key, s.title, s.profile, snippet(knowledge_search,4,'[',']',' … ',24) "
                "AS excerpt, bm25(knowledge_search) AS score FROM knowledge_search s "
                "WHERE knowledge_search MATCH ? AND (s.profile=? OR s.profile='generic' OR s.profile='android') "
                "ORDER BY score LIMIT ?",
                (expression, profile, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def read_range(self, document_key: str, start_line: int, end_line: int) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT path FROM documents WHERE document_key=?", (document_key,)
            ).fetchone()
        if not row:
            raise CaseError(f"Knowledge document not found: {document_key}")
        path = Path(row["path"])
        lines: list[str] = []
        with path.open(encoding="utf-8", errors="replace") as handle:
            for number, line in enumerate(handle, 1):
                if number > end_line:
                    break
                if number >= start_line:
                    lines.append(f"{number}: {line.rstrip()}")
        return {
            "document_key": document_key,
            "start_line": start_line,
            "end_line": end_line,
            "lines": lines,
        }


def _front_matter(content: str) -> tuple[dict[str, Any], str]:
    if not content.startswith("---\n"):
        return {}, content
    marker = content.find("\n---\n", 4)
    if marker == -1:
        return {}, content
    raw = yaml.safe_load(content[4:marker]) or {}
    if not isinstance(raw, dict):
        raise CaseError("Knowledge front matter must be a mapping.")
    return raw, content[marker + 5 :]


def _first_heading(content: str) -> str | None:
    match = re.search(r"^#\s+(.+)$", content, re.MULTILINE)
    return match.group(1).strip() if match else None
