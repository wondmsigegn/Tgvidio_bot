"""Application entry point: wiring, startup and graceful shutdown."""

from __future__ import annotations

import asyncio
import logging
import shutil
import signal

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand, BotCommandScopeChat

from .config import Config, load_config
from .db import Database
from .downloader import DownloadManager
from .handlers import admin, cookies, user
from .middlewares import UserMiddleware

log = logging.getLogger("videobot")

USER_COMMANDS = [
    BotCommand(command="start", description="Start the bot"),
    BotCommand(command="help", description="How to use"),
    BotCommand(command="mystats", description="Your statistics"),
    BotCommand(command="cookies", description="Access private videos you own"),
    BotCommand(command="delcookies", description="Delete your saved cookies"),
]
ADMIN_COMMANDS = USER_COMMANDS + [
    BotCommand(command="admin", description="Admin panel"),
    BotCommand(command="stats", description="Bot statistics"),
    BotCommand(command="broadcast", description="Message all users"),
]


def _setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )
    logging.getLogger("aiogram.event").setLevel(logging.WARNING)


async def _set_commands(bot: Bot, cfg: Config) -> None:
    await bot.set_my_commands(USER_COMMANDS)
    for admin_id in cfg.admin_ids:
        try:
            await bot.set_my_commands(ADMIN_COMMANDS, scope=BotCommandScopeChat(chat_id=admin_id))
        except Exception:  # the admin may not have started the bot yet
            log.warning("could not set admin commands for %s", admin_id)


async def main() -> None:
    cfg = load_config()
    _setup_logging(cfg.log_level)

    # Start with a clean temp area: leftovers from a crash are never needed.
    shutil.rmtree(cfg.download_dir, ignore_errors=True)
    cfg.download_dir.mkdir(parents=True, exist_ok=True)

    db = Database(cfg.db_path)
    await db.init()

    api = TelegramAPIServer.from_base(cfg.bot_api_url, is_local=True) if cfg.bot_api_url else None
    session = AiohttpSession(api=api, timeout=cfg.upload_timeout) if api else AiohttpSession(timeout=cfg.upload_timeout)
    bot = Bot(cfg.bot_token, session=session, default=DefaultBotProperties(parse_mode=ParseMode.HTML))

    me = await bot.get_me()
    manager = DownloadManager(cfg)

    dp = Dispatcher(storage=MemoryStorage())
    dp["cfg"] = cfg
    dp["db"] = db
    dp["manager"] = manager
    dp["bot_username"] = me.username or "bot"

    user_mw = UserMiddleware(db, cfg)
    dp.message.outer_middleware(user_mw)
    dp.callback_query.outer_middleware(user_mw)

    # Order matters: admin first, then cookies (stateful), then the general user handlers.
    dp.include_router(admin.router)
    dp.include_router(cookies.router)
    dp.include_router(user.router)

    await bot.delete_webhook(drop_pending_updates=True)
    await _set_commands(bot, cfg)
    maintenance = asyncio.create_task(manager.maintenance_loop())

    log.info(
        "Started @%s | admins=%d | max upload=%d MB | concurrency=%d",
        me.username, len(cfg.admin_ids), cfg.max_upload_mb, cfg.max_concurrent,
    )

    loop = asyncio.get_running_loop()
    polling = asyncio.create_task(dp.start_polling(bot, handle_signals=False, allowed_updates=["message", "callback_query"]))

    def _stop() -> None:
        log.info("Shutdown requested")
        asyncio.create_task(dp.stop_polling())

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _stop)
        except NotImplementedError:  # e.g. Windows
            pass

    try:
        await polling
    finally:
        maintenance.cancel()
        await bot.session.close()
        await db.close()
        shutil.rmtree(cfg.download_dir, ignore_errors=True)
        log.info("Bye")
