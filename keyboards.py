"""Inline keyboards."""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton as Btn
from aiogram.types import InlineKeyboardMarkup

from .downloader import Job
from .fmt import format_bytes
from .formats import FormatOption


def _kb(rows: list[list[Btn]]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=rows)


def main_menu() -> InlineKeyboardMarkup:
    return _kb(
        [
            [Btn(text="📖 How to use", callback_data="menu:help"), Btn(text="🌐 Platforms", callback_data="menu:platforms")],
            [Btn(text="🔐 Private videos", callback_data="menu:private"), Btn(text="📊 My stats", callback_data="menu:stats")],
        ]
    )


def back_home() -> InlineKeyboardMarkup:
    return _kb([[Btn(text="⬅️ Back", callback_data="menu:home")]])


def _option_text(o: FormatOption, max_bytes: int) -> str:
    icon = "🎵" if o.audio_only else "🎬"
    text = f"{icon} {o.label}"
    if o.size:
        text += f" · {format_bytes(o.size)}"
        if o.size > max_bytes:
            text += " ⚠️"
    return text


def quality_kb(job: Job, max_bytes: int) -> InlineKeyboardMarkup:
    videos = [o for o in job.options.values() if not o.audio_only]
    audio = [o for o in job.options.values() if o.audio_only]
    buttons = [Btn(text=_option_text(o, max_bytes), callback_data=f"dl:{job.token}:{o.key}") for o in videos]
    rows = [buttons[i : i + 2] for i in range(0, len(buttons), 2)]
    for o in audio:
        rows.append([Btn(text=_option_text(o, max_bytes), callback_data=f"dl:{job.token}:{o.key}")])
    rows.append([Btn(text="✖ Close", callback_data=f"close:{job.token}")])
    return _kb(rows)


def cancel_kb(token: str) -> InlineKeyboardMarkup:
    return _kb([[Btn(text="✖ Cancel", callback_data=f"cx:{token}")]])


def admin_panel() -> InlineKeyboardMarkup:
    return _kb(
        [
            [Btn(text="📊 Statistics", callback_data="adm:stats"), Btn(text="👥 Users", callback_data="adm:users")],
            [Btn(text="📢 Broadcast", callback_data="adm:bc")],
            [Btn(text="🔄 Refresh", callback_data="adm:stats"), Btn(text="✖ Close", callback_data="adm:close")],
        ]
    )


def admin_back() -> InlineKeyboardMarkup:
    return _kb([[Btn(text="⬅️ Admin panel", callback_data="adm:home")]])


def broadcast_confirm() -> InlineKeyboardMarkup:
    return _kb(
        [[Btn(text="✅ Send to everyone", callback_data="bc:send"), Btn(text="❌ Cancel", callback_data="bc:cancel")]]
    )
