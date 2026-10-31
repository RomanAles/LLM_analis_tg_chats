from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from .models import Message


class Store:
    def __init__(self, path="data/chats.sqlite"):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(str(path), timeout=30)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys=ON")
        version = self.connection.execute("PRAGMA user_version").fetchone()[0]
        if version > 1:
            self.connection.close()
            raise ValueError("База создана более новой версией приложения")
        self.connection.executescript("""
            CREATE TABLE IF NOT EXISTS chats(
                id TEXT PRIMARY KEY, name TEXT NOT NULL, metadata TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS messages(
                chat_id TEXT NOT NULL REFERENCES chats(id), id INTEGER NOT NULL,
                date TEXT NOT NULL, author TEXT NOT NULL, author_id TEXT,
                text TEXT NOT NULL, reply_to INTEGER, thread_id INTEGER,
                attachment TEXT, content_hash TEXT NOT NULL, raw_json TEXT NOT NULL,
                PRIMARY KEY(chat_id,id));
            CREATE INDEX IF NOT EXISTS messages_date ON messages(date,chat_id,id);
            CREATE TABLE IF NOT EXISTS source_documents(
                hash TEXT PRIMARY KEY, raw_json TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS imports(
                id INTEGER PRIMARY KEY, source TEXT NOT NULL, source_hash TEXT NOT NULL,
                chat_id TEXT NOT NULL, report TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
            PRAGMA user_version=1;
        """)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def close(self):
        self.connection.close()

    def list_chats(self):
        return [dict(row) for row in self.connection.execute("""
            SELECT c.id,c.name,COUNT(m.id) AS messages,
                   SUM(CASE WHEN m.attachment IS NOT NULL THEN 1 ELSE 0 END) AS attachments
            FROM chats c LEFT JOIN messages m ON c.id=m.chat_id GROUP BY c.id ORDER BY c.name
        """)]

    def messages(self, chat_ids=None, since=None, until=None):
        clauses, values = [], []
        if chat_ids:
            clauses.append("chat_id IN (" + ",".join("?" for _ in chat_ids) + ")")
            values.extend(str(x) for x in chat_ids)
        if since:
            clauses.append("date >= ?")
            values.append(since)
        if until:
            clauses.append("date <= ?")
            values.append(until)
        sql = "SELECT " + ",".join(Message.__dataclass_fields__) + " FROM messages"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY chat_id,date,id"
        return [Message(**dict(row)) for row in self.connection.execute(sql, values)]

    def import_history(self):
        return [dict(row) for row in self.connection.execute(
            "SELECT id,source,chat_id,report,created_at FROM imports ORDER BY id DESC LIMIT 100")]
