"""Let users supply their own cookies.txt for videos they are legitimately allowed to access."""

from __future__ import annotations

import contextlib
import io
import os

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message

from .. import texts
from ..downloader import DownloadManager

router = Router(name="cookies")

MAX_COOKIE_BYTES = 1024 * 1024


class CookieStates(StatesGroup):
    waiting = State()


def looks_like_netscape(text: str) -> bool:
    if "Netscape HTTP Cookie File" in text[:200]:
        return True
    for line in text.splitlines():
        line = line.strip()
        if line and not line.startswith("#") or line.startswith("#HttpOnly_"):
            if len(line.split("\t")) >= 7:
                return True
    return False


@router.message(Command("cookies"))
async def cmd_cookies(m: Message, state: FSMContext) -> None:
    await state.set_state(CookieStates.waiting)
    await m.answer(texts.COOKIES_ASK)


@router.message(Command("delcookies"))
async def cmd_delcookies(m: Message, manager: DownloadManager) -> None:
    path = manager.user_cookie_path(m.from_user.id)
    if path.exists():
        path.unlink()
        await m.answer(texts.COOKIES_DELETED)
    else:
        await m.answer(texts.COOKIES_NONE)


@router.message(Command("cancel"), StateFilter(CookieStates.waiting))
async def cmd_cancel(m: Message, state: FSMContext) -> None:
    await state.clear()
    await m.answer(texts.CANCELLED)


@router.message(CookieStates.waiting, F.document)
async def receive_cookies(m: Message, bot: Bot, state: FSMContext, manager: DownloadManager) -> None:
    doc = m.document
    if doc.file_size and doc.file_size > MAX_COOKIE_BYTES:
        await m.answer(texts.COOKIES_TOO_BIG)
        return

    buffer = io.BytesIO()
    try:
        await bot.download(doc, destination=buffer)
    except Exception:  # e.g. local Bot API files not readable from this container
        await m.answer("❌ I couldn't read that file. Please try again later or contact the bot admin.")
        return
    raw = buffer.getvalue()
    if len(raw) > MAX_COOKIE_BYTES:
        await m.answer(texts.COOKIES_TOO_BIG)
        return

    text = raw.decode("utf-8", errors="replace")
    if not looks_like_netscape(text):
        await m.answer(texts.COOKIES_BAD)
        return

    path = manager.user_cookie_path(m.from_user.id)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(text)

    await state.clear()
    with contextlib.suppress(TelegramBadRequest):
        await m.delete()  # don't leave the cookie file sitting in the chat
    await m.answer(texts.COOKIES_SAVED)


@router.message(CookieStates.waiting, ~F.document)
async def waiting_reminder(m: Message) -> None:
    await m.answer(texts.COOKIES_ASK)
