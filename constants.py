"""Constants used throughout the ZeroConfigDLNA application.

This module contains configuration constants including server information,
hostname handling, and version details for the DLNA server.
"""

import os
import socket
try:
    from .custom_mimetypes import CustomMimeTypes
except ImportError:
    from custom_mimetypes import CustomMimeTypes

# Get hostname, truncate at first dot, then limit to 16 chars max
hostname = socket.gethostname().split(".")[0][:16]

SERVER_NAME = os.environ.get("DLNA_HOSTNAME") or f"ZeroConfigDLNA_{hostname}"
SERVER_DESCRIPTION = "ZeroConfigDLNA Server"
SERVER_VERSION = "1.1.13"
SERVER_MANUFACTURER = "richstokes"
SERVER_AGENT = f"ZeroConfigDLNA/{SERVER_VERSION} DLNA/1.50 UPnP/1.0"

# Create a global instance of CustomMimeTypes
custom_mimetypes = CustomMimeTypes()


def is_supported_media_file(file_path):
    """
    Check if a file is a supported media file (video, audio, or image).

    Args:
        file_path: Path to the file to check

    Returns:
        bool: True if the file is a supported media type, False otherwise
    """
    mime_type, _ = custom_mimetypes.guess_type(file_path)
    return mime_type and (
        mime_type.startswith("video/")
        or mime_type.startswith("audio/")
        or mime_type.startswith("image/")
    )
