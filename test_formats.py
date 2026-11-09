"""Run with:  python -m unittest discover -s tests -v   (no third-party packages needed)"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# formats.py and fmt.py are dependency-free, so import them directly.
import importlib.util


def _load(name: str):
    path = Path(__file__).resolve().parent.parent / "bot" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


formats = _load("formats")
fmt = _load("fmt")


def f(fid, w=None, h=None, v="avc1.64001f", a="none", **kw):
    d = {"format_id": fid, "width": w, "height": h, "vcodec": v, "acodec": a}
    d.update(kw)
    return d


YOUTUBE = {
    "duration": 100,
    "formats": [
        f("137", 1920, 1080, tbr=4000),
        f("248", 1920, 1080, v="vp9", tbr=2500),
        f("136", 1280, 720, tbr=2000),
        f("134", 640, 360, tbr=600),
        f("140", v="none", a="mp4a.40.2", abr=128, tbr=128),
        f("251", v="none", a="opus", abr=130, tbr=130),
        f("18", 640, 360, a="mp4a.40.2", tbr=700),
        f("sb0", 160, 90, v="none", a="none", ext="mhtml", format_note="storyboard"),
    ],
}


class PlatformTests(unittest.TestCase):
    def test_allowed(self):
        cases = {
            "https://vm.tiktok.com/abc": "tiktok",
            "https://www.instagram.com/reel/x/": "instagram",
            "https://youtu.be/abc": "youtube",
            "https://www.youtube.com/shorts/x": "youtube",
            "https://fb.watch/abc": "facebook",
            "https://x.com/u/status/1": "twitter",
            "https://mobile.twitter.com/u/status/1": "twitter",
        }
        for url, expected in cases.items():
            self.assertEqual(formats.detect_platform(url), expected, url)

    def test_blocked(self):
        for url in (
            "http://169.254.169.254/latest/meta-data",
            "http://localhost:8080/",
            "https://nottiktok.com/x",
            "https://evil.com/?u=tiktok.com",
            "https://tiktok.com@evil.com/",
            "file:///etc/passwd",
            "ftp://tiktok.com/x",
        ):
            self.assertIsNone(formats.detect_platform(url), url)

    def test_extra_domains(self):
        self.assertEqual(formats.detect_platform("https://vimeo.com/1", ("vimeo.com",)), "other")
        self.assertIsNone(formats.detect_platform("https://vimeo.com/1"))


class SelectionTests(unittest.TestCase):
    def test_youtube_ladder(self):
        opts = formats.build_options(YOUTUBE, "youtube", 1080)
        self.assertEqual(opts["1080"].selector, "137+140")  # prefers H.264 + AAC
        self.assertEqual(opts["720"].selector, "136+140")
        self.assertEqual(opts["480"].selector, "18")  # nothing between 360 and 720 -> progressive 360p
        self.assertNotIn("360", opts)  # deduplicated
        self.assertTrue(opts["mp3"].audio_only)
        self.assertEqual(opts["mp3"].selector, "140")
        self.assertEqual(opts["1080"].streams, 2)

    def test_max_height_cap(self):
        opts = formats.build_options(YOUTUBE, "youtube", 720)
        self.assertNotIn("1080", opts)
        self.assertEqual(opts["720"].label, "720p")

    def test_size_estimate(self):
        opts = formats.build_options(YOUTUBE, "youtube", 1080)
        expected = int(4000 * 1000 / 8 * 100) + int(128 * 1000 / 8 * 100)
        self.assertEqual(opts["1080"].size, expected)

    def test_tiktok_skips_watermarked(self):
        info = {
            "formats": [
                f("download", 1080, 1920, a="aac", format_note="Download video, watermarked"),
                f("play", 576, 1024, a="aac", format_note="Direct video"),
            ]
        }
        opts = formats.build_options(info, "tiktok", 1080)
        selectors = {o.selector for o in opts.values() if not o.audio_only}
        self.assertEqual(selectors, {"play"})

    def test_vertical_1080_counts_as_1080p(self):
        info = {"formats": [f("v", 1080, 1920, a="aac")]}
        opts = formats.build_options(info, "tiktok", 1080)
        self.assertEqual(opts["1080"].selector, "v")
        self.assertEqual(opts["1080"].label, "1080p")

    def test_no_format_list_falls_back(self):
        opts = formats.build_options({"formats": []}, "facebook", 1080)
        self.assertIn("best", opts)
        self.assertIn("mp3", opts)


class FmtTests(unittest.TestCase):
    def test_extract_url(self):
        self.assertEqual(fmt.extract_url("look https://youtu.be/x). nice"), "https://youtu.be/x")
        self.assertIsNone(fmt.extract_url("no link"))

    def test_bytes_and_duration(self):
        self.assertEqual(fmt.format_bytes(1536), "2 KB")
        self.assertEqual(fmt.format_bytes(5 * 1024 * 1024), "5.0 MB")
        self.assertEqual(fmt.format_duration(75), "01:15")
        self.assertEqual(fmt.format_duration(3725), "1:02:05")

    def test_progress_bar(self):
        self.assertEqual(fmt.progress_bar(0), "▱" * 12)
        self.assertEqual(fmt.progress_bar(100), "▰" * 12)


if __name__ == "__main__":
    unittest.main()
