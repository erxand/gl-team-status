from __future__ import annotations

import sqlite3
from pathlib import Path

from models import TeamMember

_DB_PATH = Path(__file__).resolve().parent / "team_status.db"


def _connect() -> sqlite3.Connection:
    return sqlite3.connect(_DB_PATH)


def init_db() -> None:
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS followed_users (
                user_id   INTEGER PRIMARY KEY,
                username  TEXT NOT NULL,
                name      TEXT NOT NULL
            )
            """
        )


def get_followed_users() -> list[TeamMember]:
    with _connect() as conn:
        rows = conn.execute("SELECT user_id, username, name FROM followed_users").fetchall()
    return [TeamMember(user_id=r[0], username=r[1], name=r[2]) for r in rows]


def get_followed_usernames() -> set[str]:
    return {u.username for u in get_followed_users()}


def add_followed_user(user_id: int, username: str, name: str) -> None:
    with _connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO followed_users (user_id, username, name) VALUES (?, ?, ?)",
            (user_id, username, name),
        )


def remove_followed_user(user_id: int) -> None:
    with _connect() as conn:
        conn.execute("DELETE FROM followed_users WHERE user_id = ?", (user_id,))


def is_following(user_id: int) -> bool:
    with _connect() as conn:
        row = conn.execute(
            "SELECT 1 FROM followed_users WHERE user_id = ?", (user_id,)
        ).fetchone()
    return row is not None
