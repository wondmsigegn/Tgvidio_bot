"""Runtime configuration, loaded from environment variables (.env supported)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


def _str(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    return value.strip()


def _int(name: str, default: int) -> int:
    raw = _str(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        raise SystemExit(f"Config error: {name} must be an integer, got {raw!r}")


def _float(name: str, default: float) -> float:
    raw = _str(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        raise SystemExit(f"Config error: {name} must be a number, got {raw!r}")


def _bool(name: str, default: bool) -> bool:
    raw = _str(name)
    if raw is None:
        return default
    return raw.lower() in {"1", "true", "yes", "on"}


def _int_set(name: str) -> frozenset[int]:
    raw = _str(name, "") or ""
    out: set[int] = set()
    for part in raw.replace(";", ",").split(","):
        part = part.strip()
        if part:
            if not part.lstrip("-").isdigit():
                raise SystemExit(f"Config error: {name} contains non-numeric id {part!r}")
            out.add(int(part))
    return frozenset(out)


def _str_tuple(name: str) -> tuple[str, ...]:
    raw = _str(name, "") or ""
    return tuple(p.strip().lower() for p in raw.split(",") if p.strip())


@dataclass(frozen=True, slots=True)
class Config:
    bot_token: str
    admin_ids: frozenset[int]
    bot_api_url: str | None
    max_upload_mb: int
    max_height: int
    max_duration_min: int
    info_timeout: int
    download_timeout: int
    upload_timeout: int
    max_concurrent: int
    user_cooldown: float
    daily_limit: int
    data_dir: Path
    cookies_file: Path | None
    public_cookies: bool
    proxy: str | None
    extra_domains: tuple[str, ...]
    log_level: str

    @property
    def download_dir(self) -> Path:
        return self.data_dir / "downloads"

    @property
    def user_cookies_dir(self) -> Path:
        return self.data_dir / "cookies"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "bot.sqlite3"

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024


def load_config() -> Config:
    load_dotenv()

    token = _str("BOT_TOKEN")
    if not token or ":" not in token:
        raise SystemExit("Config error: BOT_TOKEN is missing. Get one from @BotFather and put it in .env")

    bot_api_url = _str("BOT_API_URL")
    # Cloud Bot API: 50 MB upload cap. Self-hosted local Bot API server: up to 2000 MB.
    default_upload = 2000 if bot_api_url else 50
    max_upload = min(_int("MAX_UPLOAD_MB", default_upload), 2000 if bot_api_url else 50)

    data_dir = Path(_str("DATA_DIR", "./data") or "./data").resolve()
    cookies = _str("COOKIES_FILE")

    cfg = Config(
        bot_token=token,
        admin_ids=_int_set("ADMIN_IDS"),
        bot_api_url=bot_api_url,
        max_upload_mb=max_upload,
        max_height=_int("MAX_HEIGHT", 1080),
        max_duration_min=_int("MAX_DURATION_MIN", 60),
        info_timeout=_int("INFO_TIMEOUT", 60),
        # Multi-GB files need far more time than 50 MB ones.
        download_timeout=_int("DOWNLOAD_TIMEOUT", 3600 if bot_api_url else 600),
        upload_timeout=_int("UPLOAD_TIMEOUT", 7200 if bot_api_url else 900),
        max_concurrent=max(1, _int("MAX_CONCURRENT_DOWNLOADS", 3)),
        user_cooldown=_float("USER_COOLDOWN", 1.0),
        daily_limit=_int("DAILY_LIMIT", 30),
        data_dir=data_dir,
        cookies_file=Path(cookies).resolve() if cookies else None,
        public_cookies=_bool("PUBLIC_COOKIES", False),
        proxy=_str("PROXY_URL"),
        extra_domains=_str_tuple("EXTRA_DOMAINS"),
        log_level=(_str("LOG_LEVEL", "INFO") or "INFO").upper(),
    )

    cfg.data_dir.mkdir(parents=True, exist_ok=True)
    cfg.download_dir.mkdir(parents=True, exist_ok=True)
    cfg.user_cookies_dir.mkdir(parents=True, exist_ok=True)
    return cfg
