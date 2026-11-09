"""SQLite persistence (users, download log, statistics). Privacy note: full URLs are never stored."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import aiosqlite

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id     INTEGER PRIMARY KEY,
    username    TEXT,
    full_name   TEXT,
    joined_at   INTEGER NOT NULL,
    last_seen   INTEGER NOT NULL,
    is_banned   INTEGER NOT NULL DEFAULT 0,
    is_blocked  INTEGER NOT NULL DEFAULT 0,
    downloads   INTEGER NOT NULL DEFAULT 0,
    bytes_sent  INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS downloads (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL,
    platform    TEXT NOT NULL,
    quality     TEXT,
    status      TEXT NOT NULL,
    size        INTEGER NOT NULL DEFAULT 0,
    created_at  INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_dl_user_time ON downloads(user_id, created_at);
CREATE INDEX IF NOT EXISTS idx_dl_time ON downloads(created_at);
"""

DAY = 86400


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._db: aiosqlite.Connection | None = None

    @property
    def db(self) -> aiosqlite.Connection:
        assert self._db is not None, "Database.init() was not called"
        return self._db

    async def init(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(self.path)
        self._db.row_factory = aiosqlite.Row
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute("PRAGMA synchronous=NORMAL")
        await self._db.executescript(SCHEMA)
        await self._db.commit()

    async def close(self) -> None:
        if self._db is not None:
            await self._db.close()
            self._db = None

    async def _scalar(self, sql: str, params: tuple = ()) -> Any:
        async with self.db.execute(sql, params) as cur:
            row = await cur.fetchone()
        return row[0] if row and row[0] is not None else 0

    # ------------------------------------------------------------------ users

    async def upsert_user(self, user_id: int, username: str | None, full_name: str) -> sqlite_row | None:
        """Create/refresh a user and return their row (is_banned etc.)."""
        now = int(time.time())
        await self.db.execute(
            """
            INSERT INTO users (user_id, username, full_name, joined_at, last_seen)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                username = excluded.username,
                full_name = excluded.full_name,
                last_seen = excluded.last_seen,
                is_blocked = 0
            """,
            (user_id, username, full_name, now, now),
        )
        await self.db.commit()
        return await self.get_user(user_id)

    async def get_user(self, user_id: int):
        async with self.db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)) as cur:
            return await cur.fetchone()

    async def set_banned(self, user_id: int, banned: bool) -> bool:
        cur = await self.db.execute("UPDATE users SET is_banned = ? WHERE user_id = ?", (int(banned), user_id))
        await self.db.commit()
        return cur.rowcount > 0

    async def mark_blocked(self, user_id: int) -> None:
        await self.db.execute("UPDATE users SET is_blocked = 1 WHERE user_id = ?", (user_id,))
        await self.db.commit()

    async def broadcast_targets(self) -> list[int]:
        async with self.db.execute("SELECT user_id FROM users WHERE is_banned = 0 AND is_blocked = 0") as cur:
            return [r[0] for r in await cur.fetchall()]

    # -------------------------------------------------------------- downloads

    async def log_download(self, user_id: int, platform: str, quality: str, status: str, size: int = 0) -> None:
        now = int(time.time())
        await self.db.execute(
            "INSERT INTO downloads (user_id, platform, quality, status, size, created_at) VALUES (?,?,?,?,?,?)",
            (user_id, platform, quality, status, size, now),
        )
        if status == "ok":
            await self.db.execute(
                "UPDATE users SET downloads = downloads + 1, bytes_sent = bytes_sent + ? WHERE user_id = ?",
                (size, user_id),
            )
        await self.db.commit()

    async def downloads_today(self, user_id: int) -> int:
        since = int(time.time()) - DAY
        return await self._scalar(
            "SELECT COUNT(*) FROM downloads WHERE user_id = ? AND status = 'ok' AND created_at > ?",
            (user_id, since),
        )

    # ------------------------------------------------------------- statistics

    async def global_stats(self) -> dict[str, Any]:
        now = int(time.time())
        d1, d7 = now - DAY, now - 7 * DAY
        stats: dict[str, Any] = {
            "users": await self._scalar("SELECT COUNT(*) FROM users"),
            "new_24h": await self._scalar("SELECT COUNT(*) FROM users WHERE joined_at > ?", (d1,)),
            "active_24h": await self._scalar("SELECT COUNT(*) FROM users WHERE last_seen > ?", (d1,)),
            "active_7d": await self._scalar("SELECT COUNT(*) FROM users WHERE last_seen > ?", (d7,)),
            "banned": await self._scalar("SELECT COUNT(*) FROM users WHERE is_banned = 1"),
            "blocked": await self._scalar("SELECT COUNT(*) FROM users WHERE is_blocked = 1"),
            "dl_ok": await self._scalar("SELECT COUNT(*) FROM downloads WHERE status = 'ok'"),
            "dl_ok_24h": await self._scalar(
                "SELECT COUNT(*) FROM downloads WHERE status = 'ok' AND created_at > ?", (d1,)
            ),
            "dl_failed": await self._scalar("SELECT COUNT(*) FROM downloads WHERE status != 'ok'"),
            "bytes": await self._scalar("SELECT SUM(size) FROM downloads WHERE status = 'ok'"),
        }
        async with self.db.execute(
            "SELECT platform, COUNT(*) c FROM downloads WHERE status = 'ok' GROUP BY platform ORDER BY c DESC"
        ) as cur:
            stats["platforms"] = [(r["platform"], r["c"]) for r in await cur.fetchall()]
        return stats

    async def user_stats(self, user_id: int) -> dict[str, Any] | None:
        row = await self.get_user(user_id)
        if row is None:
            return None
        return {
            "joined_at": row["joined_at"],
            "downloads": row["downloads"],
            "bytes_sent": row["bytes_sent"],
            "today": await self.downloads_today(user_id),
        }

    async def recent_users(self, limit: int = 10):
        async with self.db.execute(
            "SELECT user_id, username, full_name, downloads FROM users ORDER BY joined_at DESC LIMIT ?", (limit,)
        ) as cur:
            return await cur.fetchall()

    async def top_users(self, limit: int = 5):
        async with self.db.execute(
            "SELECT user_id, username, full_name, downloads FROM users WHERE downloads > 0 "
            "ORDER BY downloads DESC LIMIT ?",
            (limit,),
        ) as cur:
            return await cur.fetchall()


sqlite_row = aiosqlite.Row
