"""Small pure helpers for formatting text. No third-party imports."""

from __future__ import annotations

import html
import re

URL_RE = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)


def extract_url(text: str | None) -> str | None:
    match = URL_RE.search(text or "")
    if not match:
        return None
    return match.group(0).rstrip(".,;:!?)]}'\"")


def esc(value: object) -> str:
    return html.escape(str(value), quote=False)


def trim(value: object, limit: int) -> str:
    text = " ".join(str(value).split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def format_bytes(num: float | int | None) -> str:
    if num is None:
        return "?"
    size = float(num)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit in ("B", "KB") else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"


def format_duration(seconds: float | int | None) -> str:
    if seconds is None:
        return "?"
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def format_speed_eta(speed: float | None, eta: float | int | None) -> str:
    parts = []
    if speed:
        parts.append(f"🚀 {format_bytes(speed)}/s")
    if eta is not None:
        parts.append(f"⏳ {format_duration(eta)}")
    return " · ".join(parts)


def progress_bar(percent: float, width: int = 12) -> str:
    percent = max(0.0, min(100.0, percent))
    filled = int(round(width * percent / 100))
    return "▰" * filled + "▱" * (width - filled)
