"""Upload helper that reports how many bytes have been streamed to Telegram."""

from __future__ import annotations

import os
from collections.abc import AsyncGenerator, Callable

from aiogram import Bot
from aiogram.types import FSInputFile


class TrackedFile(FSInputFile):
    def __init__(self, path: str | os.PathLike, on_progress: Callable[[float], None], chunk_size: int = 64 * 1024):
        super().__init__(path, chunk_size=chunk_size)
        self._on_progress = on_progress
        self._total = max(os.path.getsize(path), 1)

    async def read(self, bot: Bot) -> AsyncGenerator[bytes, None]:
        sent = 0
        async for chunk in super().read(bot):
            sent += len(chunk)
            self._on_progress(min(100.0, sent * 100 / self._total))
            yield chunk
