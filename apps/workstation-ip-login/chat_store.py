from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Any


BASE_SCHEMA_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS messages (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      conversation_key TEXT NOT NULL,
      sender TEXT NOT NULL,
      recipient TEXT NOT NULL,
      body TEXT NOT NULL,
      message_type TEXT NOT NULL DEFAULT 'text',
      media_token TEXT NOT NULL DEFAULT '',
      media_mime TEXT NOT NULL DEFAULT '',
      media_filename TEXT NOT NULL DEFAULT '',
      media_width INTEGER NOT NULL DEFAULT 0,
      media_height INTEGER NOT NULL DEFAULT 0,
      media_size INTEGER NOT NULL DEFAULT 0,
      created_at_epoch INTEGER NOT NULL,
      created_at_display TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS chat_read_state (
      username TEXT NOT NULL,
      peer TEXT NOT NULL,
      last_read_message_id INTEGER NOT NULL DEFAULT 0,
      updated_at_epoch INTEGER NOT NULL,
      PRIMARY KEY (username, peer)
    )
    """,
)

INDEX_STATEMENTS = (
    "CREATE INDEX IF NOT EXISTS idx_messages_conversation_id ON messages(conversation_key, id DESC)",
    "CREATE INDEX IF NOT EXISTS idx_messages_sender ON messages(sender, id DESC)",
    "CREATE INDEX IF NOT EXISTS idx_messages_recipient ON messages(recipient, id DESC)",
    "CREATE INDEX IF NOT EXISTS idx_messages_media_token ON messages(media_token)",
    "CREATE INDEX IF NOT EXISTS idx_chat_read_state_username ON chat_read_state(username)",
)

REQUIRED_MESSAGE_COLUMNS = {
    "message_type": "TEXT NOT NULL DEFAULT 'text'",
    "media_token": "TEXT NOT NULL DEFAULT ''",
    "media_mime": "TEXT NOT NULL DEFAULT ''",
    "media_filename": "TEXT NOT NULL DEFAULT ''",
    "media_width": "INTEGER NOT NULL DEFAULT 0",
    "media_height": "INTEGER NOT NULL DEFAULT 0",
    "media_size": "INTEGER NOT NULL DEFAULT 0",
}

CHAT_SCREENSHOT_PREVIEW_TEXT = "[스크린샷]"


def conversation_key(user_a: str, user_b: str) -> str:
    left = str(user_a or "").strip().lower()
    right = str(user_b or "").strip().lower()
    if left <= right:
        return f"{left}:{right}"
    return f"{right}:{left}"


def _ensure_message_columns(conn: sqlite3.Connection) -> None:
    rows = conn.execute("PRAGMA table_info(messages)").fetchall()
    existing = {str(row["name"]) for row in rows}
    for column, definition in REQUIRED_MESSAGE_COLUMNS.items():
        if column in existing:
            continue
        conn.execute(f"ALTER TABLE messages ADD COLUMN {column} {definition}")


def _connect(path: str | Path) -> sqlite3.Connection:
    db_path = Path(path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=15000")
    for statement in BASE_SCHEMA_STATEMENTS:
        conn.execute(statement)
    _ensure_message_columns(conn)
    for statement in INDEX_STATEMENTS:
        conn.execute(statement)
    return conn


def init_chat_store(path: str | Path) -> None:
    conn = _connect(path)
    conn.close()


def _row_to_payload(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "id": int(row["id"]),
        "sender": str(row["sender"]),
        "recipient": str(row["recipient"]),
        "body": str(row["body"]),
        "message_type": str(row["message_type"]),
        "media_token": str(row["media_token"]),
        "media_mime": str(row["media_mime"]),
        "media_filename": str(row["media_filename"]),
        "media_width": int(row["media_width"]),
        "media_height": int(row["media_height"]),
        "media_size": int(row["media_size"]),
        "created_at_epoch": int(row["created_at_epoch"]),
        "created_at_display": str(row["created_at_display"]),
    }


def _message_select_sql(where_clause: str) -> str:
    return f"""
    SELECT
      id,
      sender,
      recipient,
      body,
      message_type,
      media_token,
      media_mime,
      media_filename,
      media_width,
      media_height,
      media_size,
      created_at_epoch,
      created_at_display
    FROM messages
    WHERE {where_clause}
    """


def append_chat_message(path: str | Path, sender: str, recipient: str, body: str) -> dict[str, Any]:
    now_epoch = int(time.time())
    created_at_display = time.strftime("%Y-%m-%d-%H:%M:%S", time.localtime(now_epoch))
    conn = _connect(path)
    try:
        with conn:
            cursor = conn.execute(
                """
                INSERT INTO messages (
                  conversation_key,
                  sender,
                  recipient,
                  body,
                  message_type,
                  media_token,
                  media_mime,
                  media_filename,
                  media_width,
                  media_height,
                  media_size,
                  created_at_epoch,
                  created_at_display
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    conversation_key(sender, recipient),
                    str(sender).strip().lower(),
                    str(recipient).strip().lower(),
                    str(body),
                    "text",
                    "",
                    "",
                    "",
                    0,
                    0,
                    0,
                    now_epoch,
                    created_at_display,
                ),
            )
            row = conn.execute(
                _message_select_sql("id = ?"),
                (int(cursor.lastrowid),),
            ).fetchone()
        payload = _row_to_payload(row)
        if payload is None:
            raise RuntimeError("chat message insert verification failed")
        return payload
    finally:
        conn.close()


def append_chat_media_message(
    path: str | Path,
    sender: str,
    recipient: str,
    *,
    media_token: str,
    media_mime: str,
    media_filename: str,
    media_width: int,
    media_height: int,
    media_size: int,
) -> dict[str, Any]:
    now_epoch = int(time.time())
    created_at_display = time.strftime("%Y-%m-%d-%H:%M:%S", time.localtime(now_epoch))
    conn = _connect(path)
    try:
        with conn:
            cursor = conn.execute(
                """
                INSERT INTO messages (
                  conversation_key,
                  sender,
                  recipient,
                  body,
                  message_type,
                  media_token,
                  media_mime,
                  media_filename,
                  media_width,
                  media_height,
                  media_size,
                  created_at_epoch,
                  created_at_display
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    conversation_key(sender, recipient),
                    str(sender).strip().lower(),
                    str(recipient).strip().lower(),
                    "",
                    "image",
                    str(media_token or "").strip(),
                    str(media_mime or "").strip(),
                    str(media_filename or "").strip(),
                    int(media_width or 0),
                    int(media_height or 0),
                    int(media_size or 0),
                    now_epoch,
                    created_at_display,
                ),
            )
            row = conn.execute(
                _message_select_sql("id = ?"),
                (int(cursor.lastrowid),),
            ).fetchone()
        payload = _row_to_payload(row)
        if payload is None:
            raise RuntimeError("chat media message insert verification failed")
        return payload
    finally:
        conn.close()


def fetch_chat_messages(
    path: str | Path,
    current_user: str,
    peer_user: str,
    *,
    before_id: int | None = None,
    after_id: int | None = None,
    limit: int = 30,
) -> dict[str, Any]:
    normalized_limit = max(1, min(int(limit or 30), 100))
    key = conversation_key(current_user, peer_user)
    conn = _connect(path)
    try:
        if after_id is not None:
            rows = conn.execute(
                _message_select_sql("conversation_key = ? AND id > ?") + """
                ORDER BY id ASC
                LIMIT ?
                """,
                (key, int(after_id), normalized_limit),
            ).fetchall()
            items = [_row_to_payload(row) for row in rows]
            return {
                "messages": [item for item in items if item is not None],
                "has_more": False,
            }

        params: list[Any] = [key]
        where = "conversation_key = ?"
        if before_id is not None:
            where += " AND id < ?"
            params.append(int(before_id))
        params.append(normalized_limit + 1)
        rows = conn.execute(
            _message_select_sql(where) + """
            ORDER BY id DESC
            LIMIT ?
            """,
            params,
        ).fetchall()
        has_more = len(rows) > normalized_limit
        visible_rows = rows[:normalized_limit]
        visible_rows.reverse()
        items = [_row_to_payload(row) for row in visible_rows]
        return {
            "messages": [item for item in items if item is not None],
            "has_more": has_more,
        }
    finally:
        conn.close()


def list_chat_peer_summaries(path: str | Path, current_user: str, peers: list[str]) -> dict[str, dict[str, Any]]:
    normalized_current = str(current_user or "").strip().lower()
    normalized_peers = sorted({str(peer or "").strip().lower() for peer in peers if str(peer or "").strip()})
    if not normalized_peers:
        return {}
    conn = _connect(path)
    try:
        result: dict[str, dict[str, Any]] = {}
        for peer in normalized_peers:
            row = conn.execute(
                _message_select_sql("conversation_key = ?") + """
                ORDER BY id DESC
                LIMIT 1
                """,
                (conversation_key(normalized_current, peer),),
            ).fetchone()
            payload = _row_to_payload(row)
            if payload is None:
                continue
            preview_text = str(payload["body"])
            if str(payload["message_type"]) == "image":
                preview_text = CHAT_SCREENSHOT_PREVIEW_TEXT
            result[peer] = {
                "last_message_id": int(payload["id"]),
                "last_message_body": preview_text,
                "last_message_sender": str(payload["sender"]),
                "last_message_created_at_epoch": int(payload["created_at_epoch"]),
                "last_message_created_at_display": str(payload["created_at_display"]),
            }
        return result
    finally:
        conn.close()


def chat_media_record(path: str | Path, media_token: str) -> dict[str, Any] | None:
    normalized = str(media_token or "").strip()
    if not normalized:
        return None
    conn = _connect(path)
    try:
        row = conn.execute(
            _message_select_sql("media_token = ?") + """
            LIMIT 1
            """,
            (normalized,),
        ).fetchone()
        return _row_to_payload(row)
    finally:
        conn.close()


def chat_unread_summary(path: str | Path, current_user: str, peers: list[str]) -> dict[str, Any]:
    normalized_current = str(current_user or "").strip().lower()
    normalized_peers = sorted({str(peer or "").strip().lower() for peer in peers if str(peer or "").strip()})
    if not normalized_current or not normalized_peers:
        return {
            "total_unread": 0,
            "latest_unread_id": 0,
            "peers": {},
        }

    conn = _connect(path)
    try:
        result: dict[str, Any] = {}
        total_unread = 0
        latest_unread_id = 0
        for peer in normalized_peers:
            read_row = conn.execute(
                """
                SELECT last_read_message_id
                FROM chat_read_state
                WHERE username = ? AND peer = ?
                """,
                (normalized_current, peer),
            ).fetchone()
            last_read_id = int(read_row["last_read_message_id"]) if read_row is not None else 0
            unread_row = conn.execute(
                """
                SELECT COUNT(*) AS unread_count, COALESCE(MAX(id), 0) AS latest_unread_id
                FROM messages
                WHERE conversation_key = ?
                  AND sender = ?
                  AND recipient = ?
                  AND id > ?
                """,
                (conversation_key(normalized_current, peer), peer, normalized_current, last_read_id),
            ).fetchone()
            unread_count = int(unread_row["unread_count"]) if unread_row is not None else 0
            peer_latest_unread_id = int(unread_row["latest_unread_id"]) if unread_row is not None else 0
            total_unread += unread_count
            latest_unread_id = max(latest_unread_id, peer_latest_unread_id)
            result[peer] = {
                "unread_count": unread_count,
                "latest_unread_id": peer_latest_unread_id,
            }
        return {
            "total_unread": total_unread,
            "latest_unread_id": latest_unread_id,
            "peers": result,
        }
    finally:
        conn.close()


def mark_chat_peer_read(path: str | Path, current_user: str, peer_user: str) -> dict[str, Any]:
    normalized_current = str(current_user or "").strip().lower()
    normalized_peer = str(peer_user or "").strip().lower()
    if not normalized_current or not normalized_peer:
        return {
            "last_read_message_id": 0,
        }

    conn = _connect(path)
    try:
        with conn:
            max_row = conn.execute(
                """
                SELECT COALESCE(MAX(id), 0) AS latest_peer_message_id
                FROM messages
                WHERE conversation_key = ?
                  AND sender = ?
                  AND recipient = ?
                """,
                (conversation_key(normalized_current, normalized_peer), normalized_peer, normalized_current),
            ).fetchone()
            latest_peer_message_id = int(max_row["latest_peer_message_id"]) if max_row is not None else 0
            current_row = conn.execute(
                """
                SELECT last_read_message_id
                FROM chat_read_state
                WHERE username = ? AND peer = ?
                """,
                (normalized_current, normalized_peer),
            ).fetchone()
            current_read_id = int(current_row["last_read_message_id"]) if current_row is not None else 0
            next_read_id = max(current_read_id, latest_peer_message_id)
            conn.execute(
                """
                INSERT INTO chat_read_state (
                  username,
                  peer,
                  last_read_message_id,
                  updated_at_epoch
                ) VALUES (?, ?, ?, ?)
                ON CONFLICT(username, peer) DO UPDATE SET
                  last_read_message_id = MAX(chat_read_state.last_read_message_id, excluded.last_read_message_id),
                  updated_at_epoch = excluded.updated_at_epoch
                """,
                (normalized_current, normalized_peer, next_read_id, int(time.time())),
            )
        return {
            "last_read_message_id": next_read_id,
        }
    finally:
        conn.close()
