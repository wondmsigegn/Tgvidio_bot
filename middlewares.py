"""Registers users, blocks banned ones, and throttles message spam."""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from . import texts
from .config import Config
from .db import Database


class UserMiddleware(BaseMiddleware):
    def __init__(self, db: Database, cfg: Config) -> None:
        self.db = db
        self.cfg = cfg
        self._last: dict[int, float] = {}

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = data.get("event_from_user")
        chat = data.get("event_chat")
        if user is None or user.is_bot or (chat is not None and chat.type != "private"):
            return None  # the bot only works in private chats

        is_admin = user.id in self.cfg.admin_ids
        row = await self.db.upsert_user(user.id, user.username, user.full_name)
        if row is not None and row["is_banned"] and not is_admin:
            if isinstance(event, Message):
                await event.answer(texts.BANNED)
            elif isinstance(event, CallbackQuery):
                await event.answer(texts.BANNED, show_alert=True)
            return None

        if isinstance(event, Message) and not is_admin:
            now = time.monotonic()
            if now - self._last.get(user.id, 0.0) < self.cfg.user_cooldown:
                return None  # silently drop floods
            self._last[user.id] = now
            if len(self._last) > 10_000:  # keep memory bounded
                cutoff = now - 60
                self._last = {k: v for k, v in self._last.items() if v > cutoff}

        data["is_admin"] = is_admin
        return await handler(event, data)
