"""Progress tracking shared between the yt-dlp worker thread and the asyncio reporter."""

from __future__ import annotations

import asyncio
import logging
import threading
from collections.abc import Awaitable, Callable

log = logging.getLogger(__name__)


class HookCancelled(Exception):
    """Raised inside a yt-dlp progress hook to abort a running download."""


class Progress:
    """Mutable state written by the download thread, read by the reporter task."""

    def __init__(self, streams: int = 1) -> None:
        self.phase = "queued"  # queued | download | process | upload | done
        self.percent = 0.0
        self.speed: float | None = None
        self.eta: int | None = None
        self.done_bytes = 0
        self.total_bytes: float | None = None
        self.streams = max(1, streams)
        self._finished = 0
        self.cancel = threading.Event()

    # Called by yt-dlp in the worker thread.
    def hook(self, d: dict) -> None:
        if self.cancel.is_set():
            raise HookCancelled()
        status = d.get("status")
        if status == "downloading":
            self.phase = "download"
            total = d.get("total_bytes") or d.get("total_bytes_estimate")
            done = d.get("downloaded_bytes") or 0
            fraction = min(done / total, 1.0) if total else 0.0
            overall = (self._finished + fraction) / self.streams * 100
            self.percent = min(99.0, max(self.percent, overall))
            self.speed = d.get("speed")
            self.eta = d.get("eta")
            self.done_bytes = done
            self.total_bytes = total
        elif status == "finished":
            self._finished += 1
            self.percent = min(99.0, max(self.percent, self._finished / self.streams * 100))
            self.speed = None
            self.eta = None
            if self._finished >= self.streams:
                self.phase = "process"


async def run_reporter(
    progress: Progress,
    render: Callable[[Progress], str],
    edit: Callable[[str], Awaitable[None]],
    interval: float = 2.5,
) -> None:
    """Periodically push the rendered progress text to Telegram until cancelled."""
    last = ""
    try:
        while True:
            await asyncio.sleep(interval)
            text = render(progress)
            if text != last:
                last = text
                try:
                    await edit(text)
                except Exception:  # never let UI errors kill a download
                    log.debug("progress edit failed", exc_info=True)
    except asyncio.CancelledError:
        pass
