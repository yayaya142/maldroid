"""Contentless FTS5 indexes for large text artifacts."""

from __future__ import annotations

import hashlib
import re
import sqlite3
from pathlib import Path
from typing import Any

from maldroid.exceptions import CaseError

URL_PATTERN = re.compile(r"https?://[^\s\"'<>]+", re.IGNORECASE)
DOMAIN_PATTERN = re.compile(r"(?<![\w.-])(?:[a-z0-9-]+\.)+[a-z]{2,63}(?![\w.-])", re.IGNORECASE)


class LargeTextIndexer:
    def __init__(self, case_root: Path):
        self.case_root = case_root
        self.database = case_root / ".maldroid" / "indexes" / "large-text.sqlite"
        self.database.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS files (
                    id INTEGER PRIMARY KEY,
                    case_path TEXT UNIQUE NOT NULL,
                    source_path TEXT NOT NULL,
                    sha256 TEXT NOT NULL,
                    size INTEGER NOT NULL,
                    mtime_ns INTEGER NOT NULL,
                    line_count INTEGER NOT NULL,
                    chunk_lines INTEGER NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS chunks (
                    id INTEGER PRIMARY KEY,
                    file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
                    chunk_number INTEGER NOT NULL,
                    start_line INTEGER NOT NULL,
                    end_line INTEGER NOT NULL,
                    start_offset INTEGER NOT NULL,
                    end_offset INTEGER NOT NULL,
                    UNIQUE(file_id, chunk_number)
                );
                CREATE VIRTUAL TABLE IF NOT EXISTS chunk_search USING fts5(
                    text,
                    content=''
                );
                CREATE TABLE IF NOT EXISTS indicators (
                    file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
                    kind TEXT NOT NULL,
                    value TEXT NOT NULL,
                    line INTEGER NOT NULL,
                    UNIQUE(file_id, kind, value, line)
                );
                """
            )

    def index(self, path: Path, case_path: str, chunk_lines: int = 200) -> dict[str, Any]:
        if chunk_lines < 10 or chunk_lines > 2000:
            raise CaseError("chunk_lines must be between 10 and 2000.")
        stat = path.stat()
        digest = _sha256(path)
        with self._connect() as connection:
            existing = connection.execute(
                "SELECT * FROM files WHERE case_path = ?", (case_path,)
            ).fetchone()
            if (
                existing
                and existing["sha256"] == digest
                and existing["size"] == stat.st_size
                and existing["mtime_ns"] == stat.st_mtime_ns
                and existing["chunk_lines"] == chunk_lines
            ):
                return self.info(case_path) | {"status": "current"}
            if existing:
                rowids = [
                    row[0]
                    for row in connection.execute(
                        "SELECT id FROM chunks WHERE file_id = ?", (existing["id"],)
                    )
                ]
                connection.executemany(
                    "INSERT INTO chunk_search(chunk_search, rowid, text) VALUES('delete', ?, '')",
                    [(rowid,) for rowid in rowids],
                )
                connection.execute("DELETE FROM files WHERE id = ?", (existing["id"],))
            cursor = connection.execute(
                "INSERT INTO files(case_path, source_path, sha256, size, mtime_ns, line_count, chunk_lines) "
                "VALUES (?, ?, ?, ?, ?, 0, ?)",
                (case_path, str(path), digest, stat.st_size, stat.st_mtime_ns, chunk_lines),
            )
            if cursor.lastrowid is None:
                raise CaseError("SQLite did not return a file index identifier.")
            file_id = int(cursor.lastrowid)
            line_number = 0
            chunk_number = 0
            chunk_start_line = 1
            chunk_start_offset = 0
            offset = 0
            buffered: list[str] = []
            with path.open("rb") as handle:
                for raw_line in handle:
                    line_number += 1
                    text_line = raw_line.decode("utf-8", errors="replace")
                    buffered.append(text_line)
                    for value in URL_PATTERN.findall(text_line):
                        connection.execute(
                            "INSERT OR IGNORE INTO indicators VALUES (?, 'url', ?, ?)",
                            (file_id, value.rstrip(".,);]"), line_number),
                        )
                    for value in DOMAIN_PATTERN.findall(text_line):
                        connection.execute(
                            "INSERT OR IGNORE INTO indicators VALUES (?, 'domain', ?, ?)",
                            (file_id, value.lower(), line_number),
                        )
                    offset += len(raw_line)
                    if len(buffered) >= chunk_lines:
                        chunk_number += 1
                        self._store_chunk(
                            connection,
                            file_id,
                            chunk_number,
                            chunk_start_line,
                            line_number,
                            chunk_start_offset,
                            offset,
                            "".join(buffered),
                        )
                        buffered = []
                        chunk_start_line = line_number + 1
                        chunk_start_offset = offset
            if buffered or line_number == 0:
                chunk_number += 1
                self._store_chunk(
                    connection,
                    file_id,
                    chunk_number,
                    chunk_start_line,
                    max(line_number, chunk_start_line),
                    chunk_start_offset,
                    offset,
                    "".join(buffered),
                )
            connection.execute(
                "UPDATE files SET line_count = ? WHERE id = ?", (line_number, file_id)
            )
        return self.info(case_path) | {"status": "created"}

    @staticmethod
    def _store_chunk(
        connection: sqlite3.Connection,
        file_id: int,
        number: int,
        start_line: int,
        end_line: int,
        start_offset: int,
        end_offset: int,
        text: str,
    ) -> None:
        cursor = connection.execute(
            "INSERT INTO chunks(file_id, chunk_number, start_line, end_line, start_offset, end_offset) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (file_id, number, start_line, end_line, start_offset, end_offset),
        )
        connection.execute(
            "INSERT INTO chunk_search(rowid, text) VALUES (?, ?)", (cursor.lastrowid, text)
        )

    def info(self, case_path: str) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT f.*, COUNT(c.id) AS chunks FROM files f LEFT JOIN chunks c ON c.file_id=f.id "
                "WHERE f.case_path=? GROUP BY f.id",
                (case_path,),
            ).fetchone()
            if not row:
                raise CaseError(f"No large-text index exists for: {case_path}")
            return dict(row)

    def search(self, case_path: str, query: str, page: int, page_size: int) -> dict[str, Any]:
        terms = re.findall(r"[\w.-]+", query, re.UNICODE)
        if not terms:
            raise CaseError("The search query has no indexable terms.")
        expression = " AND ".join(f'"{term.replace(chr(34), chr(34) * 2)}"' for term in terms)
        offset = (page - 1) * page_size
        with self._connect() as connection:
            file_row = connection.execute(
                "SELECT id FROM files WHERE case_path=?", (case_path,)
            ).fetchone()
            if not file_row:
                raise CaseError(f"No large-text index exists for: {case_path}")
            total = connection.execute(
                "SELECT COUNT(*) FROM chunk_search s JOIN chunks c ON c.id=s.rowid "
                "WHERE c.file_id=? AND chunk_search MATCH ?",
                (file_row["id"], expression),
            ).fetchone()[0]
            rows = connection.execute(
                "SELECT c.chunk_number, c.start_line, c.end_line, c.start_offset, c.end_offset "
                "FROM chunk_search s JOIN chunks c ON c.id=s.rowid "
                "WHERE c.file_id=? AND chunk_search MATCH ? ORDER BY c.chunk_number LIMIT ? OFFSET ?",
                (file_row["id"], expression, page_size, offset),
            ).fetchall()
        return {
            "query": query,
            "total_matches": total,
            "returned_matches": len(rows),
            "page": page,
            "truncated": offset + len(rows) < total,
            "results": [dict(row) for row in rows],
        }

    def read_chunk(self, case_path: str, chunk_number: int, max_characters: int) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT f.source_path, f.sha256, f.size, f.mtime_ns, c.* FROM files f "
                "JOIN chunks c ON c.file_id=f.id WHERE f.case_path=? AND c.chunk_number=?",
                (case_path, chunk_number),
            ).fetchone()
            if not row:
                raise CaseError(f"Indexed chunk not found: {case_path} chunk {chunk_number}")
        source = Path(row["source_path"])
        stat = source.stat()
        if stat.st_size != row["size"] or stat.st_mtime_ns != row["mtime_ns"]:
            raise CaseError(
                "The source file changed after indexing. Reindex it before reading chunks."
            )
        with source.open("rb") as handle:
            handle.seek(row["start_offset"])
            raw = handle.read(row["end_offset"] - row["start_offset"])
        text = raw.decode("utf-8", errors="replace")
        truncated = len(text) > max_characters
        return {
            "path": case_path,
            "chunk_number": chunk_number,
            "start_line": row["start_line"],
            "end_line": row["end_line"],
            "start_offset": row["start_offset"],
            "end_offset": row["end_offset"],
            "content": text[:max_characters],
            "truncated": truncated,
        }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()
