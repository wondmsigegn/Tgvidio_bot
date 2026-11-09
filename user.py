"""User-facing handlers: start/help, link analysis, quality selection, download + upload."""

from __future__ import annotations

import asyncio
import contextlib
import logging

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest, TelegramNetworkError, TelegramRetryAfter
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, Message

from .. import keyboards as kb
from .. import texts
from ..config import Config
from ..db import Database
from ..downloader import DownloadManager, DownloadResult, Job
from ..errors import CancelledByUser, TooLargeError, UserFacingError
from ..fmt import esc, extract_url, trim
from ..formats import FormatOption, detect_platform
from ..progress import Progress, run_reporter
from ..upload import TrackedFile

log = logging.getLogger(__name__)
router = Router(name="user")


# ------------------------------------------------------------------ helpers


def make_editor(msg):
    """Return an async function that edits a message's caption (photo card) or text."""

    async def edit(text: str, markup=None) -> None:
        try:
            if getattr(msg, "photo", None):
                await msg.edit_caption(caption=text, reply_markup=markup)
            else:
                await msg.edit_text(text, reply_markup=markup)
        except TelegramRetryAfter:
            pass  # next reporter tick will retry
        except TelegramBadRequest as e:
            if "not modified" not in str(e).lower():
                log.debug("edit failed: %s", e)

    return edit


async def _upload(
    bot: Bot,
    chat_id: int,
    result: DownloadResult,
    job: Job,
    progress: Progress,
    cfg: Config,
    bot_username: str,
) -> None:
    def on_progress(pct: float) -> None:
        progress.percent = pct

    caption = f"{esc(trim(job.title, 200))}\n\n🤖 @{esc(bot_username)}"
    last_error: Exception | None = None
    for attempt in (1, 2):
        progress.phase = "upload"
        progress.percent = 0.0
        file = TrackedFile(result.path, on_progress)
        try:
            if result.audio_only:
                await bot.send_audio(
                    chat_id,
                    audio=file,
                    caption=caption,
                    title=trim(job.title, 64),
                    performer=trim(job.uploader or "", 64) or None,
                    duration=result.duration,
                    request_timeout=cfg.upload_timeout,
                )
            else:
                await bot.send_video(
                    chat_id,
                    video=file,
                    caption=caption,
                    supports_streaming=True,
                    width=result.width,
                    height=result.height,
                    duration=result.duration,
                    request_timeout=cfg.upload_timeout,
                )
            return
        except TelegramRetryAfter as e:
            last_error = e
            await asyncio.sleep(min(e.retry_after, 30))
        except TelegramNetworkError as e:  # includes timeouts
            last_error = e
            log.warning("upload attempt %d failed: %s", attempt, e)
            await asyncio.sleep(2)
    assert last_error is not None
    raise last_error


# ------------------------------------------------------------ start & menus


@router.message(CommandStart())
async def cmd_start(m: Message) -> None:
    await m.answer(texts.start(m.from_user.first_name), reply_markup=kb.main_menu())


@router.message(Command("help"))
async def cmd_help(m: Message) -> None:
    await m.answer(texts.HELP)


@router.message(Command("mystats"))
async def cmd_mystats(m: Message, db: Database, cfg: Config, manager: DownloadManager) -> None:
    await m.answer(await _stats_text(m.from_user.id, db, cfg, manager))


async def _stats_text(user_id: int, db: Database, cfg: Config, manager: DownloadManager) -> str:
    s = await db.user_stats(user_id)
    if s is None:
        return texts.ERR_GENERIC
    return texts.user_stats(
        s["joined_at"], s["downloads"], s["bytes_sent"], s["today"], cfg.daily_limit, manager.user_cookie_path(user_id).exists()
    )


@router.callback_query(F.data.startswith("menu:"))
async def on_menu(cb: CallbackQuery, db: Database, cfg: Config, manager: DownloadManager) -> None:
    section = cb.data.split(":", 1)[1]
    if section == "home":
        text, markup = texts.start(cb.from_user.first_name), kb.main_menu()
    elif section == "help":
        text, markup = texts.HELP, kb.back_home()
    elif section == "platforms":
        text, markup = texts.PLATFORMS, kb.back_home()
    elif section == "private":
        text, markup = texts.PRIVATE_INFO, kb.back_home()
    elif section == "stats":
        text, markup = await _stats_text(cb.from_user.id, db, cfg, manager), kb.back_home()
    else:
        await cb.answer()
        return
    with contextlib.suppress(TelegramBadRequest):
        await cb.message.edit_text(text, reply_markup=markup)
    await cb.answer()


# --------------------------------------------------------------- link intake


@router.message(F.text.regexp(r"https?://\S+"))
async def on_link(m: Message, db: Database, cfg: Config, manager: DownloadManager, is_admin: bool) -> None:
    url = extract_url(m.text)
    platform = detect_platform(url, cfg.extra_domains) if url else None
    if not url or not platform:
        await m.answer(texts.UNSUPPORTED)
        return

    uid = m.from_user.id
    if uid in manager.active_users:
        await m.answer(texts.BUSY)
        return
    if cfg.daily_limit and not is_admin and await db.downloads_today(uid) >= cfg.daily_limit:
        await m.answer(texts.daily_limit(cfg.daily_limit))
        return

    status = await m.answer(texts.ANALYZING)
    try:
        job = await manager.fetch_info(url, platform, uid, is_admin)
    except UserFacingError as e:
        await db.log_download(uid, platform, "-", "info_failed")
        await status.edit_text(e.message)
        return

    caption = texts.card(job.title, job.uploader, job.duration, job.platform)
    markup = kb.quality_kb(job, cfg.max_upload_bytes)
    with contextlib.suppress(TelegramBadRequest):
        await status.delete()
    if job.thumbnail:
        try:
            await m.answer_photo(job.thumbnail, caption=caption, reply_markup=markup)
            return
        except (TelegramBadRequest, TelegramNetworkError):
            pass  # thumbnail not fetchable by Telegram -> plain card
    await m.answer(caption, reply_markup=markup)


# ----------------------------------------------------------- quality chosen


@router.callback_query(F.data.startswith("dl:"))
async def on_quality(
    cb: CallbackQuery,
    bot: Bot,
    db: Database,
    cfg: Config,
    manager: DownloadManager,
    bot_username: str,
) -> None:
    try:
        _, token, key = cb.data.split(":", 2)
    except ValueError:
        await cb.answer()
        return

    uid = cb.from_user.id
    job = manager.jobs.get(token)
    if job is None or job.user_id != uid:
        await cb.answer(texts.EXPIRED, show_alert=True)
        return
    opt: FormatOption | None = job.options.get(key)
    if opt is None:
        await cb.answer(texts.EXPIRED, show_alert=True)
        return
    if uid in manager.active_users:
        await cb.answer(texts.BUSY, show_alert=True)
        return

    manager.active_users.add(uid)
    await cb.answer()

    msg = cb.message
    edit = make_editor(msg)
    progress = Progress(streams=opt.streams)
    job.progress = progress

    def render(p: Progress) -> str:
        return texts.progress_text(p, job.title, opt.label)

    async def show(text: str, markup=None) -> None:
        await edit(text, markup)

    reporter = asyncio.create_task(run_reporter(progress, render, lambda t: show(t, kb.cancel_kb(token))))
    await show(render(progress), kb.cancel_kb(token))

    result: DownloadResult | None = None
    try:
        result = await manager.download(job, opt, progress)
        await _upload(bot, cb.message.chat.id, result, job, progress, cfg, bot_username)
        progress.phase = "done"
        await db.log_download(uid, job.platform, opt.key, "ok", result.size)
        manager.jobs.pop(token, None)
        with contextlib.suppress(TelegramBadRequest):
            await msg.delete()
    except TooLargeError as e:
        reporter.cancel()
        await db.log_download(uid, job.platform, opt.key, "too_large")
        await show(e.message, kb.quality_kb(job, cfg.max_upload_bytes))
    except CancelledByUser:
        reporter.cancel()
        await db.log_download(uid, job.platform, opt.key, "cancelled")
        manager.jobs.pop(token, None)
        await show(texts.CANCELLED)
    except UserFacingError as e:
        reporter.cancel()
        await db.log_download(uid, job.platform, opt.key, "failed")
        await show(e.message)
    except TelegramBadRequest as e:
        reporter.cancel()
        log.warning("telegram rejected upload: %s", e)
        await db.log_download(uid, job.platform, opt.key, "upload_failed")
        await show(texts.ERR_UPLOAD, kb.quality_kb(job, cfg.max_upload_bytes))
    except Exception:
        reporter.cancel()
        log.exception("download job crashed")
        await db.log_download(uid, job.platform, opt.key, "failed")
        await show(texts.ERR_GENERIC)
    finally:
        reporter.cancel()
        manager.active_users.discard(uid)
        job.progress = None
        if result is not None:
            result.cleanup()  # always delete temporary files


@router.callback_query(F.data.startswith("cx:"))
async def on_cancel(cb: CallbackQuery, manager: DownloadManager) -> None:
    token = cb.data.split(":", 1)[1]
    job = manager.jobs.get(token)
    if job is None or job.user_id != cb.from_user.id or job.progress is None:
        await cb.answer()
        return
    if job.progress.phase in ("upload", "done"):
        await cb.answer("Already uploading — almost done!")
        return
    job.progress.cancel.set()
    await cb.answer("Cancelling…")


@router.callback_query(F.data.startswith("close:"))
async def on_close(cb: CallbackQuery, manager: DownloadManager) -> None:
    token = cb.data.split(":", 1)[1]
    job = manager.jobs.get(token)
    if job and job.user_id == cb.from_user.id and cb.from_user.id not in manager.active_users:
        manager.jobs.pop(token, None)
    with contextlib.suppress(TelegramBadRequest):
        await cb.message.delete()
    await cb.answer()


# ------------------------------------------------------------------ fallback


@router.message(F.text & ~F.text.startswith("/"))
async def on_other_text(m: Message) -> None:
    await m.answer(texts.NOT_A_LINK)
