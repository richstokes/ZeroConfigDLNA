"""Custom MIME types handler for ZeroConfigDLNA.

This module provides a custom implementation of MIME type detection
that uses a local mime.types file instead of the system default.
"""

import os
import re
from typing import Dict, List, Optional, Tuple


class CustomMimeTypes:
    """
    A custom implementation of the mimetypes module that reads from
    a local mime.types file in the current directory.
    """

    def __init__(self, mime_file_path: Optional[str] = None):
        """
        Initialize the CustomMimeTypes object.

        Args:
            mime_file_path: Path to the mime.types file. If None, looks for
                mime.types in the same directory as this module.
        """
        self.types_map: Dict[str, str] = {}
        self.extensions_map: Dict[str, str] = {}

        # If no path provided, use the mime.types file in the same directory as this module
        if mime_file_path is None:
            mime_file_path = os.path.join(os.path.dirname(__file__), "mime.types")

        # Load the mime types from the file
        self._load_mime_types(mime_file_path)

    def _load_mime_types(self, mime_file_path: str) -> None:
        """
        Load MIME types from the specified file.

        Args:
            mime_file_path: Path to the mime.types file.
        """
        try:
            with open(mime_file_path, "r", encoding="utf-8") as f:
                for line in f:
                    # Skip comments and empty lines
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue

                    # Parse the line: mime_type extension [extension ...]
                    parts = line.split()
                    if len(parts) < 2:
                        continue

                    mime_type = parts[0].lower()
                    for ext in parts[1:]:
                        ext = ext.lower()
                        if not ext.startswith("."):
                            ext = "." + ext

                        # Map extension to MIME type
                        self.types_map[ext] = mime_type

                        # Map MIME type to first extension for that type
                        if mime_type not in self.extensions_map:
                            self.extensions_map[mime_type] = ext
        except Exception as e:
            print(f"Error loading mime types from {mime_file_path}: {e}")
            # Initialize with basic MIME types if file loading fails
            self._init_basic_types()

    def _init_basic_types(self) -> None:
        """Initialize with basic MIME types to ensure operation even if file loading fails."""
        # Common video formats
        for ext in [".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".webm"]:
            self.types_map[ext] = (
                "video/mp4"
                if ext == ".mp4"
                else (
                    "video/x-matroska"
                    if ext == ".mkv"
                    else (
                        "video/x-msvideo"
                        if ext == ".avi"
                        else (
                            "video/quicktime"
                            if ext == ".mov"
                            else (
                                "video/x-ms-wmv"
                                if ext == ".wmv"
                                else "video/x-flv" if ext == ".flv" else "video/webm"
                            )
                        )
                    )
                )
            )

        # Common audio formats
        for ext in [".mp3", ".wav", ".ogg", ".aac", ".flac"]:
            self.types_map[ext] = (
                "audio/mpeg"
                if ext == ".mp3"
                else (
                    "audio/wav"
                    if ext == ".wav"
                    else (
                        "audio/ogg"
                        if ext == ".ogg"
                        else "audio/aac" if ext == ".aac" else "audio/flac"
                    )
                )
            )

        # Common image formats
        for ext in [".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp"]:
            self.types_map[ext] = (
                "image/jpeg"
                if ext in [".jpg", ".jpeg"]
                else (
                    "image/png"
                    if ext == ".png"
                    else (
                        "image/gif"
                        if ext == ".gif"
                        else "image/bmp" if ext == ".bmp" else "image/webp"
                    )
                )
            )

        # Create the extensions map
        for ext, mime_type in self.types_map.items():
            if mime_type not in self.extensions_map:
                self.extensions_map[mime_type] = ext

    def guess_type(
        self, url: str, strict: bool = True
    ) -> Tuple[Optional[str], Optional[str]]:
        """
        Guess the MIME type of a file based on its URL/filename.

        Args:
            url: URL or filename to guess the MIME type for.
            strict: Whether to be strict about the guessing.
                   If True, only return types found in the mime.types file.

        Returns:
            A tuple (type, encoding) where type is the MIME type and
            encoding is the encoding (always None in this implementation).
        """
        # Extract the filename from the URL and convert to lowercase
        filename = os.path.basename(url.lower())

        # Get the extension
        _, ext = os.path.splitext(filename)

        # Return the MIME type if found, otherwise None
        return (self.types_map.get(ext), None)

    def guess_extension(self, mime_type: str, strict: bool = True) -> Optional[str]:
        """
        Guess the extension for a given MIME type.

        Args:
            mime_type: The MIME type to guess the extension for.
            strict: Whether to be strict about the guessing.
                   If True, only return extensions found in the mime.types file.

        Returns:
            The extension including the leading dot, or None if not found.
        """
        # Convert to lowercase
        mime_type = mime_type.lower()

        # Return the extension if found, otherwise None
        return self.extensions_map.get(mime_type)

    def add_type(self, mime_type: str, ext: str, strict: bool = True) -> None:
        """
        Add a MIME type to the map.

        Args:
            mime_type: The MIME type to add.
            ext: The extension to associate with the MIME type.
            strict: Ignored, included for compatibility.
        """
        if not ext.startswith("."):
            ext = "." + ext

        mime_type = mime_type.lower()
        ext = ext.lower()

        self.types_map[ext] = mime_type
        if mime_type not in self.extensions_map:
            self.extensions_map[mime_type] = ext

    def read(self, filename: str, strict: bool = True) -> None:
        """
        Read MIME types from a file.

        Args:
            filename: Path to the file to read.
            strict: Ignored, included for compatibility.
        """
        self._load_mime_types(filename)


# Create a singleton instance
mime_types = CustomMimeTypes()


# Provide functions that mimic the standard mimetypes module
def guess_type(url: str, strict: bool = True) -> Tuple[Optional[str], Optional[str]]:
    """
    Guess the MIME type of a file based on its URL/filename.

    Args:
        url: URL or filename to guess the MIME type for.
        strict: Whether to be strict about the guessing.

    Returns:
        A tuple (type, encoding) where type is the MIME type and
        encoding is the encoding (always None in this implementation).
    """
    return mime_types.guess_type(url, strict)


def guess_extension(mime_type: str, strict: bool = True) -> Optional[str]:
    """
    Guess the extension for a given MIME type.

    Args:
        mime_type: The MIME type to guess the extension for.
        strict: Whether to be strict about the guessing.

    Returns:
        The extension including the leading dot, or None if not found.
    """
    return mime_types.guess_extension(mime_type, strict)


def add_type(mime_type: str, ext: str, strict: bool = True) -> None:
    """
    Add a MIME type to the map.

    Args:
        mime_type: The MIME type to add.
        ext: The extension to associate with the MIME type.
        strict: Ignored, included for compatibility.
    """
    mime_types.add_type(mime_type, ext, strict)


def read(filename: str, strict: bool = True) -> None:
    """
    Read MIME types from a file.

    Args:
        filename: Path to the file to read.
        strict: Ignored, included for compatibility.
    """
    mime_types.read(filename, strict)
