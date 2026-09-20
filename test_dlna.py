"""Regression tests for DLNA media HTTP responses."""

import io
import os
import tempfile
import unittest
from unittest.mock import Mock

from dlna import DLNAHandler


class MediaResponseTest(unittest.TestCase):
    """Verify standard HTTP behavior while retaining Xbox compatibility."""

    def setUp(self):
        """Create a small media fixture."""
        with tempfile.NamedTemporaryFile(delete=False) as temp_file:
            temp_file.write(b"0123456789")
            self.temp_path = temp_file.name

    def tearDown(self):
        """Remove the media fixture."""
        os.unlink(self.temp_path)

    def make_handler(self, headers=None):
        """Build a handler without opening a network socket."""
        handler = DLNAHandler.__new__(DLNAHandler)
        handler.headers = headers or {}
        handler.verbose = False
        handler.wfile = io.BytesIO()
        handler.response_status = None
        handler.response_headers = {}
        handler.send_response = lambda status: setattr(
            handler, "response_status", status
        )
        handler.send_header = handler.response_headers.__setitem__
        handler.end_headers = Mock()
        return handler

    def serve(self, headers=None, head_only=False):
        """Serve the fixture with the supplied request headers."""
        handler = self.make_handler(headers)
        handler.handle_range_request(
            self.temp_path,
            10,
            "audio/x-flac",
            handler.headers.get("Range"),
            head_only,
        )
        return handler

    def test_full_get_without_range_returns_200(self):
        """A normal full GET uses 200 and omits Content-Range."""
        handler = self.serve({"User-Agent": "Lavf/ffprobe"})

        self.assertEqual(handler.response_status, 200)
        self.assertEqual(handler.response_headers["Content-Length"], "10")
        self.assertNotIn("Content-Range", handler.response_headers)
        self.assertEqual(handler.wfile.getvalue(), b"0123456789")

    def test_head_without_range_returns_200_without_body(self):
        """A normal HEAD uses 200 and never writes the media body."""
        handler = self.serve(head_only=True)

        self.assertEqual(handler.response_status, 200)
        self.assertNotIn("Content-Range", handler.response_headers)
        self.assertEqual(handler.wfile.getvalue(), b"")

    def test_range_get_returns_206_and_requested_bytes(self):
        """A valid byte range uses 206 and writes only that range."""
        handler = self.serve({"Range": "bytes=3-6"})

        self.assertEqual(handler.response_status, 206)
        self.assertEqual(handler.response_headers["Content-Range"], "bytes 3-6/10")
        self.assertEqual(handler.response_headers["Content-Length"], "4")
        self.assertEqual(handler.wfile.getvalue(), b"3456")

    def test_xbox_without_range_retains_206_compatibility(self):
        """An Xbox still gets the legacy full-file 206 response."""
        handler = self.serve({"User-Agent": "Xbox/10.0 UPnP/1.0"})

        self.assertEqual(handler.response_status, 206)
        self.assertEqual(handler.response_headers["Content-Range"], "bytes 0-9/10")
        self.assertEqual(handler.wfile.getvalue(), b"0123456789")

    def test_subtitle_url_is_added_to_media_response(self):
        """A sidecar URL is exposed through the Samsung response header."""
        handler = self.make_handler()
        subtitle_url = "http://127.0.0.1:8000/subtitles/Movie.srt"

        handler.handle_range_request(
            self.temp_path,
            10,
            "video/x-matroska",
            None,
            True,
            subtitle_url,
        )

        self.assertEqual(handler.response_headers["CaptionInfo.sec"], subtitle_url)


class SubtitleSupportTest(unittest.TestCase):
    """Verify SRT sidecar discovery, metadata, and delivery."""

    def setUp(self):
        """Create a video and language-tagged subtitle fixture."""
        self.temp_directory = tempfile.TemporaryDirectory()
        self.video_path = os.path.join(self.temp_directory.name, "Movie.mkv")
        self.language_subtitle_path = os.path.join(
            self.temp_directory.name, "Movie.en.srt"
        )
        with open(self.video_path, "wb") as video_file:
            video_file.write(b"video")
        with open(self.language_subtitle_path, "wb") as subtitle_file:
            subtitle_file.write(b"language subtitle")

        self.handler = DLNAHandler.__new__(DLNAHandler)
        self.handler.fast = True
        self.handler.verbose = False
        self.handler.server_instance = Mock(
            media_directory=self.temp_directory.name,
            server_ip="127.0.0.1",
            port=8000,
        )

    def tearDown(self):
        """Remove the subtitle fixtures."""
        self.temp_directory.cleanup()

    def test_exact_sidecar_is_preferred_over_language_variant(self):
        """Movie.srt wins over language-tagged sidecars when both exist."""
        self.assertEqual(
            self.handler._find_sidecar_subtitle(self.video_path),
            self.language_subtitle_path,
        )

        exact_subtitle_path = os.path.join(self.temp_directory.name, "Movie.srt")
        with open(exact_subtitle_path, "wb") as subtitle_file:
            subtitle_file.write(b"exact subtitle")

        self.assertEqual(
            self.handler._find_sidecar_subtitle(self.video_path), exact_subtitle_path
        )

    def test_didl_advertises_common_subtitle_extensions(self):
        """DIDL includes generic, Samsung, and Panasonic-style hints."""
        file_info = {
            "id": "2",
            "name": "Movie.mkv",
            "path": "Movie.mkv",
            "full_path": self.video_path,
            "mime_type": "video/x-matroska",
            "size": os.path.getsize(self.video_path),
        }

        didl = self.handler._create_media_item_didl(file_info, "1")
        subtitle_url = "http://127.0.0.1:8000/subtitles/Movie.en.srt"

        self.assertIn('pv:subtitleFileType="SRT"', didl)
        self.assertIn(f'pv:subtitleFileUri="{subtitle_url}"', didl)
        self.assertIn(
            f'<res protocolInfo="http-get:*:text/srt:*">{subtitle_url}</res>', didl
        )
        self.assertIn(
            f'<sec:CaptionInfoEx sec:type="srt">{subtitle_url}</sec:CaptionInfoEx>',
            didl,
        )

    def test_subtitle_response_is_utf8_text(self):
        """The dedicated endpoint returns a normal full subtitle response."""
        self.handler.wfile = io.BytesIO()
        self.handler.response_status = None
        self.handler.response_headers = {}
        self.handler.send_response = lambda status: setattr(
            self.handler, "response_status", status
        )
        self.handler.send_header = self.handler.response_headers.__setitem__
        self.handler.end_headers = Mock()

        self.handler.serve_subtitle_file("Movie.en.srt")

        self.assertEqual(self.handler.response_status, 200)
        self.assertEqual(
            self.handler.response_headers["Content-Type"], "text/srt; charset=utf-8"
        )
        self.assertEqual(self.handler.wfile.getvalue(), b"language subtitle")


if __name__ == "__main__":
    unittest.main()
