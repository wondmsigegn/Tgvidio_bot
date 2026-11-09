"""All user-facing strings live here, so the UI is easy to translate or reword."""

from __future__ import annotations

from .fmt import esc, format_bytes, format_duration, format_speed_eta, progress_bar, trim
from .formats import PLATFORM_LABELS

# --------------------------------------------------------------------------- general

BANNED = "🚫 You are not allowed to use this bot."
BUSY = "⏳ You already have a download running. Please wait for it to finish."
EXPIRED = "⌛ This request expired. Please send the link again."
ANALYZING = "🔎 <b>Analyzing link…</b>"
NOT_A_LINK = "🔗 Send me a video link from TikTok, Instagram, YouTube, Facebook or X (Twitter)."
COOLDOWN = "⏱ Slow down a little — try again in a moment."

UNSUPPORTED = (
    "🤔 <b>That link isn't supported.</b>\n\n"
    "I can download from:\n"
    "• TikTok\n• Instagram (Reels & posts)\n• YouTube (videos & Shorts)\n"
    "• Facebook\n• X (Twitter)"
)

HELP = (
    "📖 <b>How to use</b>\n\n"
    "1️⃣ Copy a video link\n"
    "2️⃣ Paste it here\n"
    "3️⃣ Pick a quality (up to 1080p) or MP3\n"
    "4️⃣ Get your video — no watermark when the platform offers a clean version\n\n"
    "<b>Commands</b>\n"
    "/mystats — your download statistics\n"
    "/cookies — access private videos you are allowed to see\n"
    "/delcookies — remove your saved cookies\n"
    "/help — this message"
)

PLATFORMS = (
    "🌐 <b>Supported platforms</b>\n\n"
    "🎵 TikTok — original video, no watermark when available\n"
    "📸 Instagram — Reels and public videos\n"
    "▶️ YouTube — videos and Shorts\n"
    "👥 Facebook — public videos and Reels\n"
    "🐦 X (Twitter) — videos in posts\n\n"
    "Videos are limited by Telegram's upload size, and by a maximum length set by the bot owner."
)

PRIVATE_INFO = (
    "🔐 <b>Private or login-only videos</b>\n\n"
    "If you have <b>legitimate access</b> (your own account, or content shared with you), "
    "you can give the bot your browser cookies so it can fetch that video as you.\n\n"
    "<b>How</b>\n"
    "1. Log in to the site in your browser\n"
    "2. Export cookies with a \"cookies.txt\" browser extension (Netscape format)\n"
    "3. Send /cookies, then upload the file here\n\n"
    "⚠️ Cookies work like a password for that session. Only upload cookies from your own "
    "account, never share them with anyone else, and use /delcookies when you're done. "
    "Your cookies are used only for your own downloads."
)

COOKIES_ASK = (
    "📎 <b>Send your cookies.txt file now</b> (Netscape format, max 1 MB).\n\n"
    "⚠️ Only upload cookies from your own account. I will delete your message once saved. "
    "Send /cancel to abort."
)
COOKIES_SAVED = (
    "✅ <b>Cookies saved.</b> They will be used for your downloads.\n"
    "I deleted the file message. Remove them anytime with /delcookies."
)
COOKIES_BAD = "❌ That doesn't look like a valid Netscape cookies.txt file. Please try again, or /cancel."
COOKIES_TOO_BIG = "❌ File is too large (max 1 MB)."
COOKIES_DELETED = "🗑 Your saved cookies were deleted."
COOKIES_NONE = "ℹ️ You have no saved cookies."
CANCELLED = "✖ Cancelled."

# --------------------------------------------------------------------------- errors

ERR_GENERIC = "❌ Something went wrong while processing this link. Please try again later."
ERR_TIMEOUT = "⏱ This took too long and was stopped. Try a lower quality or another link."
ERR_NOT_FOUND = "❌ I couldn't find a video at that link. It may be removed or contain only photos."
ERR_NO_FILE = "❌ The download finished but no video file was produced."
ERR_NO_VIDEO = "❌ That link has no video in it (it may be photos only)."
ERR_CONVERT = "❌ I couldn't convert this video into a Telegram-compatible format."
ERR_LIVE = "📡 Live streams can't be downloaded. Try again after it ends."
ERR_PRIVATE = (
    "🔒 <b>This video needs a login.</b> It is private, age-restricted, or the site asks for sign-in.\n\n"
    "If you have legitimate access, use /cookies to provide your account cookies."
)
ERR_UNAVAILABLE = "🚫 This video is unavailable — it may have been removed or made private."
ERR_GEO = "🌍 This video isn't available in the server's region."
ERR_RATE = "🚦 The platform is rate-limiting me right now. Please try again in a few minutes."
ERR_UNSUPPORTED_URL = "🤔 I can't extract a video from that link."
ERR_UPLOAD = "❌ Telegram rejected the upload. Try a lower quality."


def err_too_long(max_min: int) -> str:
    return f"⏳ This video is longer than the {max_min} minute limit."


def too_large(size: int, limit: int) -> str:
    return (
        f"📦 <b>File too big for Telegram</b>\n"
        f"This quality is {format_bytes(size)}, the limit is {format_bytes(limit)}.\n\n"
        "Pick a lower quality or MP3:"
    )


def daily_limit(n: int) -> str:
    return f"📅 Daily limit reached ({n} downloads). Come back tomorrow!"


# --------------------------------------------------------------------------- dynamic cards


def start(name: str | None) -> str:
    greeting = f"Welcome, {esc(name)}!" if name else "Welcome!"
    return (
        f"👋 <b>{greeting}</b>\n\n"
        "Send me a video link and I'll download it in HD — without watermarks when the platform allows it.\n\n"
        "✅ TikTok · Instagram · YouTube · Facebook · X\n\n"
        "👇 <b>Paste a link to get started.</b>"
    )


def card(title: str, uploader: str | None, duration: int | None, platform: str) -> str:
    meta = []
    if uploader:
        meta.append(f"👤 {esc(trim(uploader, 40))}")
    if duration:
        meta.append(f"⏱ {format_duration(duration)}")
    meta.append(f"🌐 {PLATFORM_LABELS.get(platform, platform)}")
    return f"🎬 <b>{esc(trim(title, 120))}</b>\n{'  ·  '.join(meta)}\n\n👇 <b>Choose quality</b>"


_PHASES = {
    "queued": "⏳ <b>Waiting in queue…</b>",
    "download": "⬇️ <b>Downloading…</b>",
    "process": "⚙️ <b>Processing…</b>",
    "upload": "📤 <b>Uploading to Telegram…</b>",
    "done": "✅ <b>Done</b>",
}


def progress_text(p, title: str, quality_label: str) -> str:
    lines = [
        _PHASES.get(p.phase, "⏳"),
        f"🎬 {esc(trim(title, 60))} · <i>{esc(quality_label)}</i>",
        "",
        f"<code>{progress_bar(p.percent)}</code>  <b>{p.percent:.0f}%</b>",
    ]
    if p.phase == "download":
        details = format_speed_eta(p.speed, p.eta)
        if p.total_bytes:
            details = f"{format_bytes(p.done_bytes)} / {format_bytes(p.total_bytes)}" + (f" · {details}" if details else "")
        if details:
            lines.append(details)
    return "\n".join(lines)


def user_stats(joined: int, downloads: int, bytes_sent: int, today: int, limit: int, has_cookies: bool) -> str:
    from datetime import datetime, timezone

    since = datetime.fromtimestamp(joined, tz=timezone.utc).strftime("%Y-%m-%d")
    limit_line = f"\n📅 Today: <b>{today}</b>" + (f" / {limit}" if limit else "")
    return (
        "📊 <b>Your statistics</b>\n\n"
        f"⬇️ Downloads: <b>{downloads}</b>{limit_line}\n"
        f"💾 Data received: <b>{format_bytes(bytes_sent)}</b>\n"
        f"🔐 Cookies saved: <b>{'yes' if has_cookies else 'no'}</b>\n"
        f"🗓 Member since: <b>{since}</b>"
    )
