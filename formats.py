"""Platform detection and quality selection. Pure logic (no yt-dlp import) so it is unit-testable."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

PLATFORM_DOMAINS: dict[str, tuple[str, ...]] = {
    "tiktok": ("tiktok.com",),
    "instagram": ("instagram.com", "instagr.am"),
    "youtube": ("youtube.com", "youtu.be", "youtube-nocookie.com"),
    "facebook": ("facebook.com", "fb.watch", "fb.com"),
    "twitter": ("twitter.com", "x.com"),
}

PLATFORM_LABELS: dict[str, str] = {
    "tiktok": "TikTok",
    "instagram": "Instagram",
    "youtube": "YouTube",
    "facebook": "Facebook",
    "twitter": "X (Twitter)",
    "other": "Other",
}

# Quality rungs offered to the user, highest first.
LADDER: tuple[int, ...] = (1080, 720, 480, 360)


def _host_matches(host: str, domain: str) -> bool:
    return host == domain or host.endswith("." + domain)


def detect_platform(url: str, extra_domains: tuple[str, ...] = ()) -> str | None:
    """Return the platform key for an allowed URL, else None.

    Only an allow-list of domains is accepted. This prevents the bot from being used to
    fetch arbitrary or internal addresses (SSRF) from the server it runs on.
    """
    try:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower().rstrip(".")
    except ValueError:
        return None
    if parsed.scheme not in ("http", "https") or not host:
        return None
    for name, domains in PLATFORM_DOMAINS.items():
        if any(_host_matches(host, d) for d in domains):
            return name
    if any(_host_matches(host, d) for d in extra_domains):
        return "other"
    return None


@dataclass(frozen=True, slots=True)
class FormatOption:
    key: str  # callback key: "1080", "720", ..., "mp3", "best"
    label: str  # human label, e.g. "1080p"
    selector: str  # yt-dlp format selector, e.g. "137+140"
    quality: int  # 0 for audio
    size: int | None
    audio_only: bool = False

    @property
    def streams(self) -> int:
        return self.selector.count("+") + 1


# --------------------------------------------------------------------------- format helpers


def _q(f: dict[str, Any]) -> int:
    """Quality = the shorter side, so vertical 1080x1920 clips count as 1080p."""
    h, w = f.get("height"), f.get("width")
    if h and w:
        return int(min(h, w))
    return int(h or 0)


def _has_video(f: dict[str, Any]) -> bool:
    vcodec = f.get("vcodec")
    if vcodec == "none":
        return False
    return bool(vcodec or f.get("height") or f.get("width"))


def _has_audio(f: dict[str, Any]) -> bool:
    return f.get("acodec") != "none"


def _is_h264(f: dict[str, Any]) -> bool:
    return str(f.get("vcodec") or "").lower().startswith(("avc1", "h264"))


def _video_score(f: dict[str, Any]) -> tuple[int, int, float]:
    return (_q(f), 1 if _is_h264(f) else 0, float(f.get("tbr") or 0))


def _audio_score(f: dict[str, Any]) -> tuple[int, float]:
    return (1 if str(f.get("acodec") or "").lower().startswith("mp4a") else 0, float(f.get("abr") or f.get("tbr") or 0))


def _usable(info: dict[str, Any], platform: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for f in info.get("formats") or []:
        if not f.get("format_id"):
            continue
        if f.get("has_drm"):
            continue
        if f.get("ext") == "mhtml" or f.get("format_note") == "storyboard":
            continue
        if str(f.get("protocol") or "").startswith("mhtml"):
            continue
        if f.get("vcodec") == "none" and f.get("acodec") == "none":
            continue
        out.append(f)

    if platform == "tiktok":
        # Prefer the original stream; drop the variant TikTok marks as watermarked.
        clean = [f for f in out if "watermark" not in str(f.get("format_note") or "").lower()]
        if any(_has_video(f) for f in clean):
            out = clean
    return out


def select_format(formats: list[dict[str, Any]], limit: int) -> str | None:
    """Best format selector whose quality is <= limit, or None when nothing fits."""
    videos = [f for f in formats if _has_video(f) and 0 < _q(f) <= limit]
    if not videos:
        return None

    progressive = [f for f in videos if _has_audio(f)]
    video_only = [f for f in videos if f.get("acodec") == "none"]
    audio_only = [f for f in formats if f.get("vcodec") == "none" and _has_audio(f)]

    best_prog = max(progressive, key=_video_score, default=None)
    best_video = max(video_only, key=_video_score, default=None)
    best_audio = max(audio_only, key=_audio_score, default=None)

    if best_video and best_audio and (best_prog is None or _q(best_video) > _q(best_prog)):
        return f"{best_video['format_id']}+{best_audio['format_id']}"
    if best_prog:
        return str(best_prog["format_id"])
    if best_video:
        return str(best_video["format_id"])
    return None


def select_audio(formats: list[dict[str, Any]]) -> str | None:
    audio = [f for f in formats if f.get("vcodec") == "none" and _has_audio(f)]
    if audio:
        return str(max(audio, key=_audio_score)["format_id"])
    return None


def _format_size(f: dict[str, Any], duration: float | None) -> int | None:
    size = f.get("filesize") or f.get("filesize_approx")
    if size:
        return int(size)
    tbr = f.get("tbr")
    if tbr and duration:
        return int(float(tbr) * 1000 / 8 * float(duration))
    return None


def _selection_size(selector: str, by_id: dict[str, dict[str, Any]], duration: float | None) -> int | None:
    total = 0
    for fid in selector.split("+"):
        f = by_id.get(fid)
        if f is None:
            return None
        size = _format_size(f, duration)
        if size is None:
            return None
        total += size
    return total


def build_options(info: dict[str, Any], platform: str, max_height: int = 1080) -> dict[str, FormatOption]:
    """Build the quality choices (ordered best -> worst, audio last) for an extracted video."""
    formats = _usable(info, platform)
    by_id = {str(f["format_id"]): f for f in formats}
    duration = info.get("duration")

    options: dict[str, FormatOption] = {}
    seen: set[str] = set()

    for rung in LADDER:
        if rung > max_height:
            continue
        selector = select_format(formats, rung)
        if not selector or selector in seen:
            continue
        seen.add(selector)
        quality = max((_q(by_id[i]) for i in selector.split("+") if i in by_id), default=rung)
        options[str(rung)] = FormatOption(
            key=str(rung),
            label=f"{quality}p",
            selector=selector,
            quality=quality,
            size=_selection_size(selector, by_id, duration),
        )

    if not options:
        # Extractor gave no usable format list: let yt-dlp pick the best itself.
        options["best"] = FormatOption(
            key="best",
            label="Best",
            selector="bv*+ba/b",
            quality=0,
            size=info.get("filesize") or info.get("filesize_approx"),
        )

    audio_selector = select_audio(formats)
    options["mp3"] = FormatOption(
        key="mp3",
        label="MP3",
        selector=audio_selector or "bestaudio/best",
        quality=0,
        size=_selection_size(audio_selector, by_id, duration) if audio_selector else None,
        audio_only=True,
    )
    return options
