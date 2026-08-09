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


if __name__ == "__main__":
    unittest.main()
