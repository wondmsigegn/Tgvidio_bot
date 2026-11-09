"""Exceptions and translation of raw yt-dlp errors into friendly messages."""

from __future__ import annotations

from . import texts


class UserFacingError(Exception):
    """An error whose message is safe and useful to show to the user (HTML)."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class TooLargeError(UserFacingError):
    def __init__(self, size: int, limit: int) -> None:
        super().__init__(texts.too_large(size, limit))
        self.size = size
        self.limit = limit


class CancelledByUser(Exception):
    """The user pressed the Cancel button."""


_RULES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("429", "too many requests", "rate-limit", "rate limit", "rate limited"), texts.ERR_RATE),
    (
        (
            "private video",
            "video is private",
            "private account",
            "login required",
            "log in",
            "sign in",
            "cookies",
            "authentication",
            "members-only",
            "members only",
            "checkpoint",
            "age-restricted",
            "confirm your age",
            "not available without",
            "requires login",
            "restricted video",
            "need to log in",
        ),
        texts.ERR_PRIVATE,
    ),
    (("geo", "not available in your country", "not made this video available"), texts.ERR_GEO),
    (
        (
            "unavailable",
            "has been removed",
            "no longer available",
            "does not exist",
            "video not found",
            "404",
            "deleted",
            "terminated",
            "copyright",
        ),
        texts.ERR_UNAVAILABLE,
    ),
    (("unsupported url", "no video formats", "no video could be found", "no media"), texts.ERR_UNSUPPORTED_URL),
)


def friendly_error(raw: str) -> str:
    text = raw.lower()
    for keywords, message in _RULES:
        if any(k in text for k in keywords):
            return message
    return texts.ERR_GENERIC
