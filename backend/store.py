from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    return uuid.uuid4().hex


@dataclass
class ToolCallRecord:
    id: str
    name: str
    args: dict[str, Any]
    status: Literal["running", "ok", "error"]
    preview: str = ""
    error: str | None = None


@dataclass
class MessageRecord:
    id: str
    role: Literal["user", "assistant"]
    content: str
    created_at: str
    tools: list[ToolCallRecord] = field(default_factory=list)


@dataclass
class ConversationRecord:
    id: str
    title: str
    model: str
    created_at: str
    updated_at: str
    messages: list[MessageRecord] = field(default_factory=list)


class ConversationStore:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _init(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS conversations (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    model TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS messages (
                    id TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS tool_calls (
                    id TEXT PRIMARY KEY,
                    message_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    args_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    preview TEXT NOT NULL DEFAULT '',
                    error TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (message_id) REFERENCES messages(id) ON DELETE CASCADE
                );
                """
            )

    def create_conversation(self, model: str, title: str = "新对话") -> ConversationRecord:
        record = ConversationRecord(
            id=_new_id(),
            title=title,
            model=model,
            created_at=_now(),
            updated_at=_now(),
        )
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO conversations (id, title, model, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                (record.id, record.title, record.model, record.created_at, record.updated_at),
            )
        return record

    def list_conversations(self, query: str | None = None) -> list[ConversationRecord]:
        sql = "SELECT id, title, model, created_at, updated_at FROM conversations"
        params: list[Any] = []
        if query and query.strip():
            sql += " WHERE title LIKE ?"
            params.append(f"%{query.strip()}%")
        sql += " ORDER BY updated_at DESC"
        with self._connect() as connection:
            rows = connection.execute(sql, params).fetchall()
        return [
            ConversationRecord(
                id=row["id"],
                title=row["title"],
                model=row["model"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )
            for row in rows
        ]

    def get_conversation(self, conversation_id: str) -> ConversationRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT id, title, model, created_at, updated_at FROM conversations WHERE id = ?",
                (conversation_id,),
            ).fetchone()
            if row is None:
                return None
            messages = connection.execute(
                "SELECT id, role, content, created_at FROM messages WHERE conversation_id = ? ORDER BY created_at ASC, rowid ASC",
                (conversation_id,),
            ).fetchall()
            tools_by_message: dict[str, list[ToolCallRecord]] = {message["id"]: [] for message in messages}
            if messages:
                placeholders = ",".join("?" * len(messages))
                tool_rows = connection.execute(
                    f"SELECT id, message_id, name, args_json, status, preview, error FROM tool_calls WHERE message_id IN ({placeholders}) ORDER BY created_at ASC, rowid ASC",
                    [message["id"] for message in messages],
                ).fetchall()
                for tool in tool_rows:
                    tools_by_message[tool["message_id"]].append(
                        ToolCallRecord(
                            id=tool["id"],
                            name=tool["name"],
                            args=json.loads(tool["args_json"]),
                            status=tool["status"],
                            preview=tool["preview"] or "",
                            error=tool["error"],
                        )
                    )
        return ConversationRecord(
            id=row["id"],
            title=row["title"],
            model=row["model"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            messages=[
                MessageRecord(
                    id=message["id"],
                    role=message["role"],
                    content=message["content"],
                    created_at=message["created_at"],
                    tools=tools_by_message[message["id"]],
                )
                for message in messages
            ],
        )

    def rename_conversation(self, conversation_id: str, title: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE conversations SET title = ?, updated_at = ? WHERE id = ?",
                (title.strip() or "新对话", _now(), conversation_id),
            )

    def delete_conversation(self, conversation_id: str) -> bool:
        with self._connect() as connection:
            cursor = connection.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))
            return cursor.rowcount > 0

    def touch(self, conversation_id: str, model: str | None = None) -> None:
        if model:
            with self._connect() as connection:
                connection.execute(
                    "UPDATE conversations SET model = ?, updated_at = ? WHERE id = ?",
                    (model, _now(), conversation_id),
                )
            return
        with self._connect() as connection:
            connection.execute(
                "UPDATE conversations SET updated_at = ? WHERE id = ?",
                (_now(), conversation_id),
            )

    def add_message(self, conversation_id: str, role: Literal["user", "assistant"], content: str) -> MessageRecord:
        record = MessageRecord(id=_new_id(), role=role, content=content, created_at=_now())
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO messages (id, conversation_id, role, content, created_at) VALUES (?, ?, ?, ?, ?)",
                (record.id, conversation_id, record.role, record.content, record.created_at),
            )
            connection.execute(
                "UPDATE conversations SET updated_at = ? WHERE id = ?",
                (record.created_at, conversation_id),
            )
        return record

    def update_message_content(self, message_id: str, content: str) -> None:
        with self._connect() as connection:
            connection.execute("UPDATE messages SET content = ? WHERE id = ?", (content, message_id))

    def set_title_from_first_message(self, conversation_id: str) -> str:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT content FROM messages WHERE conversation_id = ? AND role = 'user' ORDER BY created_at ASC, rowid ASC LIMIT 1",
                (conversation_id,),
            ).fetchone()
            current = connection.execute(
                "SELECT title FROM conversations WHERE id = ?",
                (conversation_id,),
            ).fetchone()
        if row is None:
            return current["title"] if current else "新对话"
        title = " ".join(row["content"].split())
        if len(title) > 28:
            title = title[:28].rstrip() + "…"
        if not title:
            title = "新对话"
        if current and current["title"] not in {"新对话", ""}:
            return current["title"]
        self.rename_conversation(conversation_id, title)
        return title

    def add_tool_call(
        self,
        message_id: str,
        name: str,
        args: dict[str, Any],
        status: Literal["running", "ok", "error"] = "running",
        preview: str = "",
        error: str | None = None,
    ) -> ToolCallRecord:
        record = ToolCallRecord(id=_new_id(), name=name, args=args, status=status, preview=preview, error=error)
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO tool_calls (id, message_id, name, args_json, status, preview, error, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    record.id,
                    message_id,
                    record.name,
                    json.dumps(record.args, ensure_ascii=False),
                    record.status,
                    record.preview,
                    record.error,
                    _now(),
                ),
            )
        return record

    def update_tool_call(
        self,
        tool_id: str,
        *,
        status: Literal["running", "ok", "error"] | None = None,
        preview: str | None = None,
        error: str | None = None,
    ) -> None:
        assignments: list[str] = []
        params: list[Any] = []
        if status is not None:
            assignments.append("status = ?")
            params.append(status)
        if preview is not None:
            assignments.append("preview = ?")
            params.append(preview)
        if error is not None:
            assignments.append("error = ?")
            params.append(error)
        if not assignments:
            return
        params.append(tool_id)
        with self._connect() as connection:
            connection.execute(f"UPDATE tool_calls SET {', '.join(assignments)} WHERE id = ?", params)

    def history_turns(self, conversation_id: str) -> list[dict[str, str]]:
        conversation = self.get_conversation(conversation_id)
        if conversation is None:
            return []
        return [{"role": message.role, "content": message.content} for message in conversation.messages if message.content]
