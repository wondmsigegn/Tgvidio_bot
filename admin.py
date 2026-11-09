"""Admin panel: statistics, user management and broadcasts. Only for ADMIN_IDS."""

from __future__ import annotations

import asyncio
import contextlib
import logging

from aiogram import Bot, F, Router
from aiogram.exceptions import (
    TelegramAPIError,
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramRetryAfter,
)
from aiogram.filters import BaseFilter, Command, CommandObject, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from .. import keyboards as kb
from ..config import Config
from ..db import Database
from ..fmt import esc, format_bytes, trim
from ..formats import PLATFORM_LABELS

log = logging.getLogger(__name__)


class IsAdmin(BaseFilter):
    async def __call__(self, event, cfg: Config, event_from_user=None) -> bool:
        return event_from_user is not None and event_from_user.id in cfg.admin_ids


router = Router(name="admin")
router.message.filter(IsAdmin())
router.callback_query.filter(IsAdmin())

_background: set[asyncio.Task] = set()


class Broadcast(StatesGroup):
    waiting = State()
    confirm = State()


# ----------------------------------------------------------------- rendering

ADMIN_HOME = (
    "🛠 <b>Admin panel</b>\n\n"
    "Commands:\n"
    "/stats — statistics\n"
    "/broadcast — message all users\n"
    "/ban <code>id</code> · /unban <code>id</code>\n"
    "/user <code>id</code> — user info"
)


def _name(row) -> str:
    label = row["full_name"] or row["username"] or str(row["user_id"])
    return f'<a href="tg://user?id={row["user_id"]}">{esc(trim(label, 30))}</a>'


async def stats_text(db: Database) -> str:
    s = await db.global_stats()
    platforms = "\n".join(
        f"• {PLATFORM_LABELS.get(name, name)} — <b>{count}</b>" for name, count in s["platforms"]
    ) or "• no downloads yet"
    return (
        "📊 <b>Bot statistics</b>\n\n"
        f"👥 Users: <b>{s['users']}</b> (+{s['new_24h']} in 24h)\n"
        f"🟢 Active: <b>{s['active_24h']}</b> in 24h · <b>{s['active_7d']}</b> in 7d\n"
        f"🚫 Banned: {s['banned']} · 🔕 Blocked the bot: {s['blocked']}\n\n"
        f"⬇️ Downloads: <b>{s['dl_ok']}</b> ({s['dl_ok_24h']} in 24h)\n"
        f"❌ Failed/cancelled: {s['dl_failed']}\n"
        f"💾 Data sent: <b>{format_bytes(s['bytes'])}</b>\n\n"
        f"🌐 <b>By platform</b>\n{platforms}"
    )


async def users_text(db: Database) -> str:
    recent = await db.recent_users(10)
    top = await db.top_users(5)
    recent_lines = "\n".join(f"• {_name(r)} — <code>{r['user_id']}</code>" for r in recent) or "• none"
    top_lines = "\n".join(f"• {_name(r)} — <b>{r['downloads']}</b>" for r in top) or "• none"
    return f"👥 <b>Newest users</b>\n{recent_lines}\n\n🏆 <b>Top downloaders</b>\n{top_lines}"


# ------------------------------------------------------------------ commands


@router.message(Command("admin"))
async def cmd_admin(m: Message) -> None:
    await m.answer(ADMIN_HOME, reply_markup=kb.admin_panel())


@router.message(Command("stats"))
async def cmd_stats(m: Message, db: Database) -> None:
    await m.answer(await stats_text(db), reply_markup=kb.admin_panel())


def _parse_id(command: CommandObject) -> int | None:
    arg = (command.args or "").strip().split(" ")[0]
    return int(arg) if arg.lstrip("-").isdigit() else None


@router.message(Command("ban"))
async def cmd_ban(m: Message, command: CommandObject, db: Database, cfg: Config) -> None:
    uid = _parse_id(command)
    if uid is None:
        await m.answer("Usage: /ban <code>user_id</code>")
    elif uid in cfg.admin_ids:
        await m.answer("You can't ban an admin.")
    elif await db.set_banned(uid, True):
        await m.answer(f"🚫 User <code>{uid}</code> banned.")
    else:
        await m.answer("User not found.")


@router.message(Command("unban"))
async def cmd_unban(m: Message, command: CommandObject, db: Database) -> None:
    uid = _parse_id(command)
    if uid is None:
        await m.answer("Usage: /unban <code>user_id</code>")
    elif await db.set_banned(uid, False):
        await m.answer(f"✅ User <code>{uid}</code> unbanned.")
    else:
        await m.answer("User not found.")


@router.message(Command("user"))
async def cmd_user(m: Message, command: CommandObject, db: Database) -> None:
    uid = _parse_id(command)
    row = await db.get_user(uid) if uid is not None else None
    if row is None:
        await m.answer("Usage: /user <code>user_id</code> (user must exist)")
        return
    username = f"@{esc(row['username'])}" if row["username"] else "—"
    await m.answer(
        f"👤 {_name(row)} ({username})\n"
        f"ID: <code>{row['user_id']}</code>\n"
        f"Downloads: <b>{row['downloads']}</b> · Data: <b>{format_bytes(row['bytes_sent'])}</b>\n"
        f"Banned: {'yes' if row['is_banned'] else 'no'} · Blocked bot: {'yes' if row['is_blocked'] else 'no'}"
    )


# ------------------------------------------------------------ panel callbacks


@router.callback_query(F.data.startswith("adm:"))
async def on_admin_cb(cb: CallbackQuery, db: Database, state: FSMContext) -> None:
    action = cb.data.split(":", 1)[1]
    if action == "close":
        with contextlib.suppress(TelegramBadRequest):
            await cb.message.delete()
        await cb.answer()
        return
    if action == "bc":
        await _start_broadcast(cb.message, state)
        await cb.answer()
        return

    if action == "stats":
        text, markup = await stats_text(db), kb.admin_panel()
    elif action == "users":
        text, markup = await users_text(db), kb.admin_back()
    else:
        text, markup = ADMIN_HOME, kb.admin_panel()
    with contextlib.suppress(TelegramBadRequest):  # "message is not modified" on refresh
        await cb.message.edit_text(text, reply_markup=markup)
    await cb.answer("Updated")


# ----------------------------------------------------------------- broadcast


async def _start_broadcast(message: Message, state: FSMContext) -> None:
    await state.set_state(Broadcast.waiting)
    await message.answer(
        "📢 <b>Broadcast</b>\n\nSend the message you want to deliver to all users "
        "(text, photo, video, document… formatting is preserved).\n\nSend /cancel to abort."
    )


@router.message(Command("broadcast"))
async def cmd_broadcast(m: Message, state: FSMContext) -> None:
    await _start_broadcast(m, state)


@router.message(Command("cancel"), StateFilter(Broadcast.waiting, Broadcast.confirm))
async def cmd_cancel(m: Message, state: FSMContext) -> None:
    await state.clear()
    await m.answer("✖ Broadcast cancelled.")


@router.message(Broadcast.waiting)
async def broadcast_receive(m: Message, state: FSMContext, db: Database) -> None:
    await state.update_data(chat_id=m.chat.id, message_id=m.message_id)
    await state.set_state(Broadcast.confirm)
    targets = await db.broadcast_targets()
    await m.answer("👆 <b>Preview</b> of your broadcast.")
    with contextlib.suppress(TelegramAPIError):
        await m.copy_to(m.chat.id)
    await m.answer(f"Send this to <b>{len(targets)}</b> users?", reply_markup=kb.broadcast_confirm())


@router.callback_query(Broadcast.confirm, F.data == "bc:cancel")
async def broadcast_cancel(cb: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    with contextlib.suppress(TelegramBadRequest):
        await cb.message.edit_text("✖ Broadcast cancelled.")
    await cb.answer()


@router.callback_query(Broadcast.confirm, F.data == "bc:send")
async def broadcast_send(cb: CallbackQuery, state: FSMContext, bot: Bot, db: Database) -> None:
    data = await state.get_data()
    await state.clear()
    await cb.answer("Broadcast started")
    task = asyncio.create_task(_run_broadcast(bot, db, cb.message, data["chat_id"], data["message_id"]))
    _background.add(task)  # keep a reference so it isn't garbage-collected
    task.add_done_callback(_background.discard)


async def _run_broadcast(bot: Bot, db: Database, status: Message, from_chat: int, message_id: int) -> None:
    targets = await db.broadcast_targets()
    total = len(targets)
    sent = blocked = failed = 0

    async def update(prefix: str) -> None:
        with contextlib.suppress(TelegramAPIError):
            await status.edit_text(
                f"{prefix}\n\n✅ Sent: <b>{sent}</b>\n🔕 Blocked: <b>{blocked}</b>\n❌ Failed: <b>{failed}</b>\n"
                f"Total: {total}"
            )

    await update("📢 <b>Broadcasting…</b>")
    for index, uid in enumerate(targets, start=1):
        for _ in range(3):
            try:
                await bot.copy_message(uid, from_chat, message_id)
                sent += 1
            except TelegramRetryAfter as e:
                await asyncio.sleep(e.retry_after + 1)
                continue
            except TelegramForbiddenError:
                blocked += 1
                await db.mark_blocked(uid)
            except TelegramAPIError:
                failed += 1
            break
        else:
            failed += 1
        await asyncio.sleep(0.05)  # stay well under Telegram's ~30 msg/s limit
        if index % 100 == 0:
            await update("📢 <b>Broadcasting…</b>")
    await update("✅ <b>Broadcast finished</b>")
    log.info("broadcast done: sent=%d blocked=%d failed=%d", sent, blocked, failed)
