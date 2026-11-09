"""yt-dlp + FFmpeg download pipeline with timeouts, cancellation and size limits."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import shutil
import tempfile
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yt_dlp
from yt_dlp.utils import DownloadError, ExtractorError

from . import texts
from .config import Config
from .errors import CancelledByUser, TooLargeError, UserFacingError, friendly_error
from .formats import FormatOption, build_options
from .progress import HookCancelled, Progress

log = logging.getLogger(__name__)

VIDEO_EXTS = (".mp4", ".mkv", ".webm", ".mov")
AUDIO_EXTS = (".mp3", ".m4a", ".opus", ".ogg", ".aac")


@dataclass(slots=True)
class Job:
    token: str
    user_id: int
    url: str
    platform: str
    title: str
    uploader: str | None
    duration: int | None
    thumbnail: str | None
    options: dict[str, FormatOption]
    is_admin: bool
    progress: Progress | None = None
    created: float = field(default_factory=time.time)


@dataclass(slots=True)
class DownloadResult:
    path: Path
    size: int
    width: int | None
    height: int | None
    duration: int | None
    audio_only: bool
    workdir: Path

    def cleanup(self) -> None:
        shutil.rmtree(self.workdir, ignore_errors=True)


async def _run(cmd: list[str], timeout: float) -> tuple[int, bytes, bytes]:
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout)
    except BaseException:
        with contextlib.suppress(ProcessLookupError):
            proc.kill()
        with contextlib.suppress(BaseException):
            await proc.wait()
        raise
    return proc.returncode or 0, out, err


class DownloadManager:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.sem = asyncio.Semaphore(cfg.max_concurrent)
        self.jobs: dict[str, Job] = {}
        self.active_users: set[int] = set()

    # ------------------------------------------------------------- cookies

    def user_cookie_path(self, user_id: int) -> Path:
        return self.cfg.user_cookies_dir / f"{user_id}.txt"

    def cookies_for(self, user_id: int, is_admin: bool) -> Path | None:
        """Per-user cookies win. The operator's global cookie file is admin-only unless PUBLIC_COOKIES=true,
        so ordinary users can never fetch content through the operator's logged-in session."""
        own = self.user_cookie_path(user_id)
        if own.exists():
            return own
        glob = self.cfg.cookies_file
        if glob and glob.exists() and (is_admin or self.cfg.public_cookies):
            return glob
        return None

    @contextmanager
    def _cookie_copy(self, src: Path | None) -> Iterator[str | None]:
        # yt-dlp rewrites the cookie jar on exit, so always work on a private copy.
        if src is None:
            yield None
            return
        with tempfile.TemporaryDirectory(dir=self.cfg.download_dir) as tmp:
            dst = Path(tmp) / "cookies.txt"
            shutil.copyfile(src, dst)
            os.chmod(dst, 0o600)
            yield str(dst)

    # ------------------------------------------------------------ yt-dlp opts

    def _base_opts(self, outdir: Path | None, cookiefile: str | None) -> dict[str, Any]:
        opts: dict[str, Any] = {
            "quiet": True,
            "no_warnings": True,
            "noprogress": True,
            "noplaylist": True,
            "playlist_items": "1",
            "socket_timeout": 30,
            "retries": 3,
            "fragment_retries": 3,
            "concurrent_fragment_downloads": 4,
            "restrictfilenames": True,
            # The generic extractor can fetch arbitrary URLs; keep it off.
            "allowed_extractors": ["default", "-generic"],
        }
        if outdir is not None:
            opts["outtmpl"] = str(outdir / "%(id)s.%(ext)s")
        if cookiefile:
            opts["cookiefile"] = cookiefile
        if self.cfg.proxy:
            opts["proxy"] = self.cfg.proxy
        return opts

    # ---------------------------------------------------------------- info

    def _extract_sync(self, url: str, cookies: Path | None) -> dict[str, Any]:
        with self._cookie_copy(cookies) as cookiefile:
            opts = self._base_opts(None, cookiefile)
            opts["skip_download"] = True
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
                info = ydl.sanitize_info(info) if info else None
        if not info:
            raise UserFacingError(texts.ERR_NOT_FOUND)
        if info.get("_type") in ("playlist", "multi_video"):
            entries = [e for e in (info.get("entries") or []) if e]
            if not entries:
                raise UserFacingError(texts.ERR_NOT_FOUND)
            info = entries[0]
        return info

    async def fetch_info(self, url: str, platform: str, user_id: int, is_admin: bool) -> Job:
        cookies = self.cookies_for(user_id, is_admin)
        try:
            info = await asyncio.wait_for(
                asyncio.to_thread(self._extract_sync, url, cookies), self.cfg.info_timeout
            )
        except TimeoutError:
            raise UserFacingError(texts.ERR_TIMEOUT) from None
        except UserFacingError:
            raise
        except (DownloadError, ExtractorError) as e:
            log.info("extract failed (%s): %s", platform, str(e)[:300])
            raise UserFacingError(friendly_error(str(e))) from e
        except Exception:
            log.exception("unexpected extract error")
            raise UserFacingError(texts.ERR_GENERIC) from None

        if info.get("is_live") or info.get("live_status") in ("is_live", "is_upcoming"):
            raise UserFacingError(texts.ERR_LIVE)
        duration = info.get("duration")
        if duration and duration > self.cfg.max_duration_min * 60:
            raise UserFacingError(texts.err_too_long(self.cfg.max_duration_min))

        options = build_options(info, platform, self.cfg.max_height)
        job = Job(
            token=uuid.uuid4().hex[:10],
            user_id=user_id,
            url=url,
            platform=platform,
            title=str(info.get("title") or info.get("fulltitle") or "Video"),
            uploader=info.get("uploader") or info.get("channel"),
            duration=int(duration) if duration else None,
            thumbnail=info.get("thumbnail"),
            options=options,
            is_admin=is_admin,
        )
        self.jobs[job.token] = job
        return job

    # ------------------------------------------------------------ download

    def _download_sync(
        self, url: str, opt: FormatOption, workdir: Path, progress: Progress, cookies: Path | None
    ) -> None:
        with self._cookie_copy(cookies) as cookiefile:
            opts = self._base_opts(workdir, cookiefile)
            opts["format"] = opt.selector
            opts["progress_hooks"] = [progress.hook]
            if opt.audio_only:
                opts["postprocessors"] = [
                    {"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"}
                ]
            else:
                opts["merge_output_format"] = "mp4"
                opts["postprocessor_args"] = {"merger": ["-movflags", "+faststart"]}
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([url])

    @staticmethod
    def _find_output(workdir: Path, audio: bool) -> Path | None:
        exts = AUDIO_EXTS if audio else VIDEO_EXTS
        files = [p for p in workdir.iterdir() if p.is_file() and p.suffix.lower() in exts]
        return max(files, key=lambda p: p.stat().st_size, default=None)

    async def _probe(self, path: Path) -> dict[str, Any]:
        cmd = ["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)]
        try:
            rc, out, _ = await _run(cmd, timeout=30)
            return json.loads(out) if rc == 0 and out else {}
        except (OSError, ValueError, TimeoutError):
            return {}

    async def _ensure_telegram_compatible(self, path: Path) -> Path:
        """Telegram plays H.264/AAC MP4 inline. Remux/transcode anything else."""
        meta = await self._probe(path)
        streams = meta.get("streams", [])
        video = next((s for s in streams if s.get("codec_type") == "video"), None)
        audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
        if video is None:
            raise UserFacingError(texts.ERR_NO_VIDEO)

        v_ok = video.get("codec_name") == "h264" and video.get("pix_fmt") in (None, "yuv420p", "yuvj420p")
        a_ok = audio is None or audio.get("codec_name") in ("aac", "mp3")
        if path.suffix.lower() == ".mp4" and v_ok and a_ok:
            return path

        out = path.with_name(path.stem + "_tg.mp4")
        cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(path), "-map", "0:v:0", "-map", "0:a:0?"]
        cmd += ["-c:v", "copy"] if v_ok else ["-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p"]
        cmd += ["-c:a", "copy"] if a_ok else ["-c:a", "aac", "-b:a", "128k"]
        cmd += ["-movflags", "+faststart", str(out)]
        rc, _, err = await _run(cmd, timeout=self.cfg.download_timeout)
        if rc != 0 or not out.exists():
            log.warning("ffmpeg failed: %s", err.decode(errors="replace")[:300])
            raise UserFacingError(texts.ERR_CONVERT)
        path.unlink(missing_ok=True)
        return out

    async def _fetch(
        self, job: Job, opt: FormatOption, workdir: Path, progress: Progress, cookies: Path | None
    ) -> DownloadResult:
        try:
            await asyncio.to_thread(self._download_sync, job.url, opt, workdir, progress, cookies)
        except HookCancelled:
            raise CancelledByUser() from None
        except (DownloadError, ExtractorError) as e:
            if progress.cancel.is_set():
                raise CancelledByUser() from None
            log.info("download failed (%s): %s", job.platform, str(e)[:300])
            raise UserFacingError(friendly_error(str(e))) from e
        except Exception:
            if progress.cancel.is_set():
                raise CancelledByUser() from None
            log.exception("unexpected download error")
            raise UserFacingError(texts.ERR_GENERIC) from None

        path = self._find_output(workdir, opt.audio_only)
        if path is None:
            raise UserFacingError(texts.ERR_NO_FILE)

        progress.phase = "process"
        if not opt.audio_only:
            path = await self._ensure_telegram_compatible(path)

        size = path.stat().st_size
        if size > self.cfg.max_upload_bytes:
            raise TooLargeError(size, self.cfg.max_upload_bytes)

        meta = await self._probe(path)
        video = next((s for s in meta.get("streams", []) if s.get("codec_type") == "video"), {})
        raw_duration = (meta.get("format") or {}).get("duration")
        return DownloadResult(
            path=path,
            size=size,
            width=video.get("width"),
            height=video.get("height"),
            duration=int(float(raw_duration)) if raw_duration else job.duration,
            audio_only=opt.audio_only,
            workdir=workdir,
        )

    async def download(self, job: Job, opt: FormatOption, progress: Progress) -> DownloadResult:
        """Queue, download, post-process. The caller must call result.cleanup() after uploading."""
        workdir = self.cfg.download_dir / f"{job.user_id}_{job.token}_{int(time.time())}"
        cookies = self.cookies_for(job.user_id, job.is_admin)
        progress.phase = "queued"
        succeeded = False
        async with self.sem:
            if progress.cancel.is_set():
                raise CancelledByUser()
            progress.phase = "download"
            workdir.mkdir(parents=True, exist_ok=True)
            try:
                result = await asyncio.wait_for(
                    self._fetch(job, opt, workdir, progress, cookies), self.cfg.download_timeout
                )
                succeeded = True
                return result
            except TimeoutError:
                progress.cancel.set()  # makes the worker thread stop at its next progress tick
                raise UserFacingError(texts.ERR_TIMEOUT) from None
            finally:
                if not succeeded:
                    shutil.rmtree(workdir, ignore_errors=True)

    # --------------------------------------------------------- housekeeping

    def purge(self) -> None:
        now = time.time()
        for token, job in list(self.jobs.items()):
            if now - job.created > 1800 and job.user_id not in self.active_users:
                self.jobs.pop(token, None)
        for entry in self.cfg.download_dir.iterdir():
            try:
                if entry.is_dir() and now - entry.stat().st_mtime > 3600:
                    shutil.rmtree(entry, ignore_errors=True)
            except OSError:
                pass

    async def maintenance_loop(self) -> None:
        while True:
            await asyncio.sleep(600)
            try:
                self.purge()
            except Exception:
                log.exception("maintenance failed")
