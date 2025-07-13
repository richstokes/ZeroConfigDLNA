"""
DLNA media server handler module.

This module provides the HTTP request handler for a DLNA media server,
implementing the necessary DLNA and UPnP protocols for media streaming.
"""

import html
import traceback
import os
import socket
import struct
import subprocess
import uuid
from helpers import is_safe_path, send_device_description, send_scpd_xml
from http.server import BaseHTTPRequestHandler
from urllib.parse import unquote, urlparse, quote

try:
    from .constants import (
        SERVER_AGENT,
        SERVER_DESCRIPTION,
        SERVER_VERSION,
        SERVER_MANUFACTURER,
        is_supported_media_file,
    )
    from .custom_mimetypes import CustomMimeTypes
except ImportError:
    from constants import (
        SERVER_AGENT,
        SERVER_DESCRIPTION,
        SERVER_VERSION,
        SERVER_MANUFACTURER,
        is_supported_media_file,
    )
    from custom_mimetypes import CustomMimeTypes

# Create a global instance of CustomMimeTypes
custom_mimetypes = CustomMimeTypes()


class DLNAHandler(BaseHTTPRequestHandler):
    """
    HTTP request handler for DLNA media server.

    This class handles HTTP requests from DLNA clients, including device description,
    service control point descriptions, browse requests, and media file streaming.
    It implements the necessary DLNA and UPnP protocols for media server functionality.
    """

    # Class attributes that will be set by the server instance
    # These are set dynamically in app.py when creating the Handler subclass
    server_instance = None  # Reference to the ZeroConfigDLNA server instance
    verbose = False  # Verbose logging flag
    server_name = None  # Server name, set by the server instance
    fast = False  # Fast mode flag to disable subprocess calls

    def __init__(self, *args, **kwargs):
        # Set default timeout for socket operations (5 minutes)
        self.timeout = 300
        # Initialize directory mapping attribute
        self.directory_mapping = None
        try:
            super().__init__(*args, **kwargs)
        except (
            BrokenPipeError,
            ConnectionResetError,
            ConnectionAbortedError,
            OSError,
        ) as e:
            # Client disconnected during initialization - this is common with DLNA clients
            # Just log it and return gracefully
            print(f"Client disconnected during handler initialization: {e}")

        if self.fast:
            print("Fast mode enabled - subprocess calls will be disabled")

        self.now_playing = "None"

    def get_now_playing(self):
        """Get the currently playing media file."""
        return self.now_playing

    def setup(self):
        """Set up the connection with timeout"""
        super().setup()
        # Set socket timeout to prevent hanging connections
        self.connection.settimeout(self.timeout)
        # Set TCP_NODELAY on the socket
        self.connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        buffer_size = 32 * 1024 * 1024  # 32MB buffer
        self.connection.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, buffer_size)
        self.connection.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, buffer_size)

    def log_message(self, format, *args):  # pylint: disable=redefined-builtin
        """Override BaseHTTPRequestHandler's log_message to only log when verbose mode is enabled"""
        if hasattr(self, "verbose") and self.verbose:
            # Use the default logging behavior from BaseHTTPRequestHandler
            super().log_message(format, *args)
        # If verbose is False or not set, don't log anything

    def do_GET(self):  # pylint: disable=invalid-name
        """Handle GET requests for media files and DLNA control"""
        try:
            parsed_path = urlparse(self.path)
            path = unquote(parsed_path.path)

            if self.verbose:
                print(f"GET request: {self.path} -> {path}")
                print(f"Headers: {dict(self.headers)}")

            if path == "/description.xml":
                send_device_description(self)
            elif path == "/cd_scpd.xml":
                send_scpd_xml(self, "ContentDirectory")
            elif path == "/cm_scpd.xml":
                send_scpd_xml(self, "ConnectionManager")
            elif path == "/browse":
                self.send_browse_response()
            elif path.startswith("/media/"):
                if self.verbose:
                    print(f"Media request: {path[7:]}")
                    print(f"Client: {self.client_address}")
                    print(f"User-Agent: {self.headers.get('User-Agent', 'Unknown')}")
                    print(f"Range: {self.headers.get('Range', 'None')}")

                self.serve_media_file(path[7:])  # Remove '/media/' prefix
            else:
                self.send_error(404, "File not found")
        except (BrokenPipeError, ConnectionResetError):
            # Client disconnected during request processing
            print(
                f"Client {self.client_address} disconnected during GET request processing"
            )
            return
        except Exception as e:
            print(f"Error handling GET request: {str(e)}")
            try:
                self.send_error(500, f"Internal server error: {str(e)}")
            except (BrokenPipeError, ConnectionResetError):
                # If sending the error also fails due to client disconnect, just log it
                print("Client disconnected while sending error response")
                return

    def do_HEAD(self):  # pylint: disable=invalid-name
        """Handle HEAD requests for media files (for DLNA compatibility)"""
        try:
            parsed_path = urlparse(self.path)
            path = unquote(parsed_path.path)

            if self.verbose:
                print(f"HEAD request: {self.path} -> {path}")
                print(f"Headers: {dict(self.headers)}")

            if path.startswith("/media/"):
                self.serve_media_file(
                    path[7:], head_only=True
                )  # Remove '/media/' prefix
            else:
                self.send_error(404, "File not found")
        except (BrokenPipeError, ConnectionResetError):
            # Client disconnected during request processing
            print(
                f"Client {self.client_address} disconnected during HEAD request processing"
            )
            return
        except Exception as e:
            print(f"Error handling HEAD request: {str(e)}")
            try:
                self.send_error(500, f"Internal server error: {str(e)}")
            except (BrokenPipeError, ConnectionResetError):
                # If sending the error also fails due to client disconnect, just log it
                print("Client disconnected while sending error response")
                return

    def do_POST(self):  # pylint: disable=invalid-name
        """Handle SOAP requests for DLNA control"""
        try:
            if self.verbose:
                print(f"POST request: {self.path}")
                print(f"POST Headers: {dict(self.headers)}")
                print(f"Client: {self.client_address}")

            if self.path == "/control":
                content_length = int(self.headers.get("Content-Length", 0))
                post_data = self.rfile.read(content_length)
                soap_action = self.headers.get("SOAPAction", "").strip('"')
                print(f"SOAP Action: {soap_action}")
                self.handle_soap_request(post_data, soap_action)
            else:
                print(f"POST to unknown path: {self.path}")
                self.send_error(404, "Not found")
        except (BrokenPipeError, ConnectionResetError):
            # Client disconnected during request processing
            print(
                f"Client {self.client_address} disconnected during POST request processing"
            )
            return
        except Exception as e:
            print(f"Error handling POST request: {str(e)}")
            try:
                self.send_error(500, f"Internal server error: {str(e)}")
            except (BrokenPipeError, ConnectionResetError):
                # If sending the error also fails due to client disconnect, just log it
                print("Client disconnected while sending error response")
                return

    def do_SUBSCRIBE(self):  # pylint: disable=invalid-name
        """Handle UPnP event subscription requests"""
        try:
            if self.path == "/events":
                self.handle_subscribe_request()
            else:
                self.send_error(404, "Not found")
        except (BrokenPipeError, ConnectionResetError):
            # Client disconnected during request processing
            print(
                f"Client {self.client_address} disconnected during SUBSCRIBE request processing"
            )
            return
        except Exception as e:
            print(f"Error handling SUBSCRIBE request: {str(e)}")
            try:
                self.send_error(500, f"Internal server error: {str(e)}")
            except (BrokenPipeError, ConnectionResetError):
                # If sending the error also fails due to client disconnect, just log it
                print("Client disconnected while sending error response")
                return

    def do_UNSUBSCRIBE(self):  # pylint: disable=invalid-name
        """Handle UPnP event unsubscription requests"""
        try:
            if self.path == "/events":
                self.handle_unsubscribe_request()
            else:
                self.send_error(404, "Not found")
        except (BrokenPipeError, ConnectionResetError):
            # Client disconnected during request processing
            print(
                f"Client {self.client_address} disconnected during UNSUBSCRIBE request processing"
            )
            return
        except Exception as e:
            print(f"Error handling UNSUBSCRIBE request: {str(e)}")
            try:
                self.send_error(500, f"Internal server error: {str(e)}")
            except (BrokenPipeError, ConnectionResetError):
                # If sending the error also fails due to client disconnect, just log it
                print("Client disconnected while sending error response")
                return

    def do_OPTIONS(self):  # pylint: disable=invalid-name
        """Handle OPTIONS requests for CORS"""
        try:
            self.send_response(200)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header(
                "Access-Control-Allow-Methods",
                "GET, POST, OPTIONS, SUBSCRIBE, UNSUBSCRIBE",
            )
            self.send_header(
                "Access-Control-Allow-Headers",
                "Content-Type, SOAPAction, CALLBACK, NT, TIMEOUT, SID",
            )
            self.send_header("Content-Length", "0")
            self.end_headers()
        except (BrokenPipeError, ConnectionResetError):
            # Client disconnected during request processing
            print(
                f"Client {self.client_address} disconnected during OPTIONS request processing"
            )
            return
        except Exception as e:
            print(f"Error handling OPTIONS request: {str(e)}")
            # Don't try to send an error response for OPTIONS requests

    def send_browse_response(self):
        """Send a simple directory listing"""
        try:
            path_param = urlparse(self.path).query
            current_dir = ""

            # Parse path parameter if it exists
            if path_param.startswith("path="):
                current_dir = unquote(path_param[5:])

            # Get the full directory path
            current_full_path = os.path.join(
                self.server_instance.media_directory, current_dir
            )

            # Security check: ensure requested directory is within media directory
            if not is_safe_path(
                self.server_instance.media_directory, current_full_path
            ):
                self.send_error(403, "Access denied")
                print(
                    f"SECURITY WARNING: Attempted directory traversal to {current_full_path}"
                )
                return

            # Make sure path exists
            if not os.path.exists(current_full_path) or not os.path.isdir(
                current_full_path
            ):
                self.send_error(404, "Directory not found")
                return  # Get directory contents
            items = []
            for item_name in os.listdir(current_full_path):
                item_path = os.path.join(current_full_path, item_name)
                relative_path = (
                    os.path.join(current_dir, item_name) if current_dir else item_name
                )

                if os.path.isdir(item_path):
                    # Add directory
                    items.append(
                        {"name": item_name, "path": relative_path, "is_dir": True}
                    )
                elif os.path.isfile(item_path):
                    mime_type, _ = custom_mimetypes.guess_type(item_name)
                    if mime_type and (
                        mime_type.startswith("video/")
                        or mime_type.startswith("audio/")
                        or mime_type.startswith("image/")
                    ):
                        # Add media file
                        url_path = relative_path.replace("\\", "/")
                        encoded_path = quote(url_path)
                        items.append(
                            {
                                "name": item_name,
                                "path": relative_path,
                                "is_dir": False,
                                "url": f"http://{self.server_instance.server_ip}:{self.server_instance.port}/media/{encoded_path}",
                                "mime_type": mime_type,
                                "size": os.path.getsize(item_path),
                            }
                        )

            # Count media files
            media_file_count = sum(1 for item in items if not item.get("is_dir", False))

            # Build breadcrumb navigation
            breadcrumbs = []
            breadcrumbs.append({"name": "Home", "path": ""})

            if current_dir:
                parts = current_dir.split(os.sep)
                cumulative_path = ""
                for part in parts:
                    if part:
                        cumulative_path = os.path.join(cumulative_path, part)
                        breadcrumbs.append({"name": part, "path": cumulative_path})

            # Simple HTML response for browser testing
            html = f"""<!DOCTYPE html>
<html>
<head>
    <title>{self.server_name}</title>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 40px; }}
        .breadcrumb {{ display: flex; flex-wrap: wrap; list-style: none; padding: 0; margin-bottom: 20px; }}
        .breadcrumb li {{ margin-right: 10px; }}
        .breadcrumb li:after {{ content: " > "; margin-left: 10px; color: #666; }}
        .breadcrumb li:last-child:after {{ content: ""; }}
        .breadcrumb a {{ text-decoration: none; color: #0066cc; }}
        .breadcrumb a:hover {{ text-decoration: underline; }}
        .current-path {{ margin-bottom: 20px; color: #666; }}
        .file-list {{ list-style-type: none; padding: 0; }}
        .file-item {{ margin: 10px 0; padding: 10px; border: 1px solid #ddd; border-radius: 5px; }}
        .dir-item {{ background-color: #f5f5f5; }}
        .file-name {{ font-weight: bold; }}
        .file-info {{ color: #666; font-size: 0.9em; }}
        .folder-icon {{ margin-right: 5px; color: #ffa500; }}
    </style>
</head>
<body>
    <h1>{self.server_name}</h1>
    
    <ul class="breadcrumb">
"""

            # Add breadcrumb navigation
            for crumb in breadcrumbs:
                if crumb == breadcrumbs[-1]:  # Current directory
                    html += f'        <li>{crumb["name"]}</li>\n'
                else:
                    html += f'        <li><a href="/browse?path={quote(crumb["path"])}">{crumb["name"]}</a></li>\n'

            html += f"""    </ul>
    
    <div class="current-path">Current directory: {os.path.join(self.server_instance.media_directory, current_dir)}</div>
    <p>Found {media_file_count} media files in this directory</p>
    
    <ul class="file-list">"""

            # Sort items: directories first, then files
            sorted_items = sorted(
                items, key=lambda x: (not x.get("is_dir", False), x["name"])
            )

            for item in sorted_items:
                if item.get("is_dir", False):
                    # Display directory with folder icon and link to browse
                    html += f"""
        <li class="file-item dir-item">
            <div class="file-name">
                <a href="/browse?path={quote(item['path'])}"><span class="folder-icon">📁</span> {item['name']}</a>
            </div>
        </li>"""
                else:
                    # Display media file with link
                    html += f"""
        <li class="file-item">
            <div class="file-name">
                <a href="{item['url']}" target="_blank">{item['name']}</a>
            </div>
            <div class="file-info">
                Type: {item['mime_type']} | Size: {item['size']:,} bytes
            </div>
        </li>"""

            html += """
    </ul>
</body>
</html>"""

            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(html)))
            self.end_headers()
            self.wfile.write(html.encode())

        except Exception as e:
            self.send_error(500, f"Error reading directory: {str(e)}")
            traceback.print_exc()

    def serve_media_file(self, filename, head_only=False):
        """Serve a media file"""
        try:
            # URL decode the filename
            decoded_filename = unquote(filename)
            file_path = os.path.join(
                self.server_instance.media_directory, decoded_filename
            )

            if not os.path.exists(file_path) or not os.path.isfile(file_path):
                self.send_error(404, "File not found")
                return

            # Security check: ensure file is within media directory
            if not is_safe_path(self.server_instance.media_directory, file_path):
                self.send_error(403, "Access denied")
                print(f"SECURITY WARNING: Attempted directory traversal to {file_path}")
                return

            mime_type, _ = custom_mimetypes.guess_type(file_path)
            if not mime_type:
                mime_type = "application/octet-stream"

            file_size = os.path.getsize(file_path)

            print(
                f"Serving file: {decoded_filename} (size: {file_size}, type: {mime_type}, head_only: {head_only})"
            )

            # Log DLNA client info
            client_addr = self.client_address
            if self.verbose:
                print(f"MEDIA ACCESS: {self.path} from {client_addr}")
                print(f"MEDIA HEADERS: {dict(self.headers)}")

            # Set the current playing file for DLNA clients
            # Get filename after the last slash for display
            self.now_playing = os.path.basename(decoded_filename)
            # Also update the server instance's now_playing for external access
            if self.server_instance:
                self.server_instance.set_now_playing(self.now_playing)
            print(f"NOW PLAYING: {self.now_playing}")

            # Handle range requests for video streaming
            # Xbox Media Player requires 206 Partial Content for ALL media files,
            # even when Range header is missing, malformed, or Range: bytes=0-
            range_header = self.headers.get("Range")

            # Always use range request handling for media files to ensure Xbox compatibility
            try:
                self.handle_range_request(
                    file_path, file_size, mime_type, range_header, head_only
                )
            except (BrokenPipeError, ConnectionResetError):
                # Client disconnected, log and return without further error handling
                if self.verbose:
                    print(
                        f"Client disconnected during range request for {decoded_filename}"
                    )
                return

        except (BrokenPipeError, ConnectionResetError):
            # Client disconnected
            print(f"Client disconnected before streaming of {decoded_filename} began")
            return
        except Exception as e:
            print(f"Error serving file {filename}: {str(e)}")
            try:
                self.send_error(500, f"Error serving file: {str(e)}")
            except (BrokenPipeError, ConnectionResetError):
                # If sending the error also fails due to client disconnect, just log it
                print("Client disconnected while sending error response")
                return

    def handle_range_request(
        self, file_path, file_size, mime_type, range_header, head_only=False
    ):
        """Handle HTTP range requests for streaming

        Uses smaller chunk sizes compared to full file streaming to improve
        responsiveness during video resume/seek operations and reduce choppiness.

        For Xbox compatibility, this method ALWAYS returns 206 Partial Content,
        even when Range header is missing, malformed, or Range: bytes=0-

        Args:
            file_path: Path to the file being served
            file_size: Size of the file in bytes
            mime_type: MIME type of the file
            range_header: The Range header value from the request (can be None/malformed)
            head_only: If True, only send headers (for HEAD requests)
        """
        try:
            # Default to entire file range (Xbox compatibility requirement)
            start = 0
            end = file_size - 1

            # Parse Range header if present and valid
            if range_header and range_header.startswith("bytes="):
                range_match = range_header.replace("bytes=", "").split("-")
                if len(range_match) == 2:
                    try:
                        # Parse start position
                        if range_match[0]:
                            start = int(range_match[0])
                        # Parse end position
                        if range_match[1]:
                            end = int(range_match[1])

                        # Validate range bounds
                        if start < 0 or end >= file_size or start > end:
                            # Invalid range, fall back to entire file
                            start = 0
                            end = file_size - 1
                    except ValueError:
                        # Invalid range values, fall back to entire file
                        start = 0
                        end = file_size - 1

            content_length = end - start + 1

            # Always send 206 Partial Content for Xbox compatibility
            if self.verbose:
                if not range_header:
                    print(f"Xbox compatibility: Using 206 for missing Range header")
                elif not range_header.startswith("bytes="):
                    print(
                        f"Xbox compatibility: Using 206 for malformed Range header: {range_header}"
                    )
                else:
                    print(f"Standard range request: {range_header}")

            self.send_response(206)
            self.send_header("Content-Type", mime_type)
            self.send_header("Content-Length", str(content_length))
            self.send_header("Content-Range", f"bytes {start}-{end}/{file_size}")
            self.send_header("Accept-Ranges", "bytes")
            # Add DLNA headers for better device compatibility
            if mime_type.startswith("video/"):
                if mime_type == "video/x-msvideo":
                    self.send_header(
                        "ContentFeatures.DLNA.ORG",
                        "DLNA.ORG_OP=01;DLNA.ORG_CI=0;DLNA.ORG_FLAGS=01700000000000000000000000000000",
                    )
                elif mime_type == "video/mp4":
                    self.send_header(
                        "ContentFeatures.DLNA.ORG",
                        "DLNA.ORG_PN=MP4_SD_AAC_LTP;DLNA.ORG_OP=01;DLNA.ORG_CI=0;DLNA.ORG_FLAGS=01700000000000000000000000000000",
                    )
                elif mime_type == "video/x-matroska":
                    # MKV files - use generic video profile with streaming support
                    self.send_header(
                        "ContentFeatures.DLNA.ORG",
                        "DLNA.ORG_PN=AVC_MP4_BL_CIF15_AAC_520;DLNA.ORG_OP=01;DLNA.ORG_CI=0;DLNA.ORG_FLAGS=01700000000000000000000000000000",
                    )
                elif mime_type in (
                    "video/quicktime",
                    "video/x-ms-wmv",
                    "video/x-flv",
                    "video/webm",
                    "video/x-m4v",
                    "video/3gpp",
                ):
                    self.send_header(
                        "ContentFeatures.DLNA.ORG",
                        "DLNA.ORG_OP=01;DLNA.ORG_CI=0;DLNA.ORG_FLAGS=01700000000000000000000000000000",
                    )
                else:
                    self.send_header(
                        "ContentFeatures.DLNA.ORG",
                        "DLNA.ORG_PN=AVC_MP4_BL_CIF15_AAC_520;DLNA.ORG_OP=01;DLNA.ORG_CI=0;DLNA.ORG_FLAGS=01700000000000000000000000000000",
                    )
            elif mime_type.startswith("audio/"):
                if mime_type == "audio/mpeg":
                    self.send_header(
                        "ContentFeatures.DLNA.ORG",
                        "DLNA.ORG_PN=MP3;DLNA.ORG_OP=01;DLNA.ORG_CI=0;DLNA.ORG_FLAGS=01700000000000000000000000000000",
                    )
                elif mime_type == "audio/wav":
                    self.send_header(
                        "ContentFeatures.DLNA.ORG",
                        "DLNA.ORG_PN=LPCM;DLNA.ORG_OP=01;DLNA.ORG_CI=0;DLNA.ORG_FLAGS=01700000000000000000000000000000",
                    )
                elif mime_type in ("audio/mp4", "audio/x-m4a"):
                    self.send_header(
                        "ContentFeatures.DLNA.ORG",
                        "DLNA.ORG_PN=AAC_ISO_320;DLNA.ORG_OP=01;DLNA.ORG_CI=0;DLNA.ORG_FLAGS=01700000000000000000000000000000",
                    )
                elif mime_type in (
                    "audio/flac",
                    "audio/ogg",
                    "audio/x-ms-wma",
                    "audio/aiff",
                ):
                    self.send_header(
                        "ContentFeatures.DLNA.ORG",
                        "DLNA.ORG_OP=01;DLNA.ORG_CI=0;DLNA.ORG_FLAGS=01700000000000000000000000000000",
                    )
                else:
                    self.send_header(
                        "ContentFeatures.DLNA.ORG",
                        "DLNA.ORG_OP=01;DLNA.ORG_CI=0;DLNA.ORG_FLAGS=01700000000000000000000000000000",
                    )
            else:
                self.send_header(
                    "ContentFeatures.DLNA.ORG",
                    "DLNA.ORG_OP=01;DLNA.ORG_CI=0;DLNA.ORG_FLAGS=00D00000000000000000000000000000",
                )
            self.send_header("TransferMode.DLNA.ORG", "Streaming")
            self.send_header("Server", SERVER_AGENT)
            # Keep connection alive for range requests
            self.send_header("Connection", "keep-alive")
            # Add cache control - allow short-term caching for range requests
            self.send_header("Cache-Control", "max-age=3600")
            self.end_headers()

            # Only send file content for GET requests, not HEAD
            if not head_only:
                with open(file_path, "rb") as f:
                    f.seek(start)
                    remaining = content_length

                    # Set a timeout for socket operations to prevent blocking
                    self.wfile.flush()

                    # Use smaller chunks for range requests to improve resume/seek performance
                    # Large chunks can cause choppy playback when resuming video
                    base_chunk_size = 512 * 1024  # 512KB

                    while remaining > 0:
                        # For range requests, use smaller chunks for better streaming
                        # This helps with choppy playback when resuming videos
                        chunk_size = min(base_chunk_size, remaining)
                        if remaining > 2 * 1024 * 1024:  # If more than 2MB remaining
                            chunk_size = min(
                                16 * 1024, remaining
                            )  # Use 16KB chunks max

                        chunk = f.read(chunk_size)
                        if not chunk:
                            break
                        try:
                            self.wfile.write(chunk)
                            # Flush more frequently for range requests to reduce latency
                            # This helps with responsive seeking and resume functionality
                            if remaining % (base_chunk_size * 2) == 0:
                                self.wfile.flush()
                            remaining -= len(chunk)
                        except BrokenPipeError:
                            # Client disconnected, log it and exit gracefully
                            # This happens a lot due to how DLNA clients handle streaming
                            if self.verbose:
                                print(
                                    f"Client disconnected during streaming of {os.path.basename(file_path)}"
                                )
                            return
                        except ConnectionResetError:
                            # Connection reset by client
                            if self.verbose:
                                print(
                                    f"Connection reset during streaming of {os.path.basename(file_path)}"
                                )
                            return
                    # Final flush
                    self.wfile.flush()

        except BrokenPipeError:
            # Client disconnected before we could send headers
            print(
                f"Client disconnected before streaming of {os.path.basename(file_path)} began"
            )
            return
        except Exception as e:
            # For other exceptions, log but don't try to send an error response as it might fail too
            print(
                f"Error handling range request for {os.path.basename(file_path)}: {str(e)}"
            )
            try:
                self.send_error(500, f"Error handling range request: {str(e)}")
            except (BrokenPipeError, ConnectionResetError):
                # If sending the error also fails due to client disconnect, just log it
                print("Client disconnected while sending error response")
                return

    def handle_soap_request(self, post_data, soap_action=""):
        """Handle SOAP requests for DLNA control"""
        try:
            soap_data = post_data.decode("utf-8")
            if self.verbose:
                print(f"SOAP Action: {soap_action}")
                print(
                    f"SOAP Data: {soap_data[:500]}..."
                )  # First 500 chars for debugging
                print(f"SOAP Headers: {self.headers}")

            # Determine which service is being addressed
            if "ContentDirectory" in soap_action:
                print("ContentDirectory service action detected")
            elif "ConnectionManager" in soap_action:
                print("ConnectionManager service action detected")
            else:
                print(f"Unknown service in SOAP action: {soap_action}")

            # Parse SOAP action from the request or header
            if "Browse" in soap_data or "Browse" in soap_action:
                self.handle_browse_request(soap_data)
            elif "GetProtocolInfo" in soap_data or "GetProtocolInfo" in soap_action:
                self.handle_get_protocol_info()
            elif (
                "GetCurrentConnectionIDs" in soap_data
                or "GetCurrentConnectionIDs" in soap_action
            ):
                self.handle_get_current_connection_ids()
            elif (
                "GetCurrentConnectionInfo" in soap_data
                or "GetCurrentConnectionInfo" in soap_action
            ):
                self.handle_get_current_connection_info()
            elif (
                "GetSearchCapabilities" in soap_data
                or "GetSearchCapabilities" in soap_action
            ):
                self.handle_get_search_capabilities()
            elif (
                "GetSortCapabilities" in soap_data
                or "GetSortCapabilities" in soap_action
            ):
                self.handle_get_sort_capabilities()
            elif "GetSystemUpdateID" in soap_data or "GetSystemUpdateID" in soap_action:
                self.handle_get_system_update_id()
            else:
                print(f"Unsupported SOAP action: {soap_action}")
                print(
                    f"SOAP data contains: {[key for key in ['Browse', 'GetProtocolInfo', 'GetCurrentConnectionIDs', 'GetCurrentConnectionInfo'] if key in soap_data]}"
                )

                # Default response for unsupported actions
                response = """<?xml version="1.0" encoding="utf-8"?>
<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/">
    <s:Body>
        <s:Fault>
            <faultcode>s:Client</faultcode>
            <faultstring>UPnPError</faultstring>
            <detail>
                <UPnPError xmlns="urn:schemas-upnp-org:control-1-0">
                    <errorCode>401</errorCode>
                    <errorDescription>Invalid Action</errorDescription>
                </UPnPError>
            </detail>
        </s:Fault>
    </s:Body>
</s:Envelope>"""

                self.send_response(500)
                self.send_header("Content-Type", "text/xml; charset=utf-8")
                self.send_header("Content-Length", str(len(response)))
                self.end_headers()
                self.wfile.write(response.encode())
                print("Sent error response for unsupported action")

        except Exception as e:
            print(f"SOAP request error: {e}")
            traceback.print_exc()
            self.send_error(500, "Internal server error")

    def handle_get_protocol_info(self):
        """Handle ConnectionManager GetProtocolInfo requests"""
        try:
            print("Handling GetProtocolInfo request")

            # Define supported protocols with expanded format support
            source_protocols = [
                # Video formats
                "http-get:*:video/mp4:DLNA.ORG_PN=AVC_MP4_MP_SD_AAC_MULT5;DLNA.ORG_OP=01;DLNA.ORG_FLAGS=01700000000000000000000000000000",
                "http-get:*:video/x-msvideo:DLNA.ORG_PN=AVI;DLNA.ORG_OP=01;DLNA.ORG_FLAGS=01700000000000000000000000000000",
                "http-get:*:video/x-matroska:DLNA.ORG_PN=MATROSKA;DLNA.ORG_OP=01;DLNA.ORG_FLAGS=01700000000000000000000000000000",
                "http-get:*:video/quicktime:DLNA.ORG_OP=01;DLNA.ORG_FLAGS=01700000000000000000000000000000",
                "http-get:*:video/x-ms-wmv:DLNA.ORG_OP=01;DLNA.ORG_FLAGS=01700000000000000000000000000000",
                "http-get:*:video/x-flv:DLNA.ORG_OP=01;DLNA.ORG_FLAGS=01700000000000000000000000000000",
                "http-get:*:video/webm:DLNA.ORG_OP=01;DLNA.ORG_FLAGS=01700000000000000000000000000000",
                "http-get:*:video/x-m4v:DLNA.ORG_OP=01;DLNA.ORG_FLAGS=01700000000000000000000000000000",
                "http-get:*:video/3gpp:DLNA.ORG_OP=01;DLNA.ORG_FLAGS=01700000000000000000000000000000",
                # Audio formats
                "http-get:*:audio/mpeg:DLNA.ORG_PN=MP3;DLNA.ORG_OP=01;DLNA.ORG_FLAGS=01700000000000000000000000000000",
                "http-get:*:audio/wav:DLNA.ORG_PN=LPCM;DLNA.ORG_OP=01;DLNA.ORG_FLAGS=01700000000000000000000000000000",
                "http-get:*:audio/mp4:DLNA.ORG_PN=AAC_ISO_320;DLNA.ORG_OP=01;DLNA.ORG_FLAGS=01700000000000000000000000000000",
                "http-get:*:audio/x-m4a:DLNA.ORG_PN=AAC_ISO_320;DLNA.ORG_OP=01;DLNA.ORG_FLAGS=01700000000000000000000000000000",
                "http-get:*:audio/flac:DLNA.ORG_OP=01;DLNA.ORG_FLAGS=01700000000000000000000000000000",
                "http-get:*:audio/ogg:DLNA.ORG_OP=01;DLNA.ORG_FLAGS=01700000000000000000000000000000",
                "http-get:*:audio/x-ms-wma:DLNA.ORG_OP=01;DLNA.ORG_FLAGS=01700000000000000000000000000000",
                "http-get:*:audio/aiff:DLNA.ORG_OP=01;DLNA.ORG_FLAGS=01700000000000000000000000000000",
                # Image formats
                "http-get:*:image/jpeg:DLNA.ORG_PN=JPEG_LRG;DLNA.ORG_OP=01;DLNA.ORG_FLAGS=00D00000000000000000000000000000",
                "http-get:*:image/png:DLNA.ORG_PN=PNG_LRG;DLNA.ORG_OP=01;DLNA.ORG_FLAGS=00D00000000000000000000000000000",
                "http-get:*:image/gif:DLNA.ORG_OP=01;DLNA.ORG_FLAGS=00D00000000000000000000000000000",
                "http-get:*:image/bmp:DLNA.ORG_OP=01;DLNA.ORG_FLAGS=00D00000000000000000000000000000",
                "http-get:*:image/tiff:DLNA.ORG_OP=01;DLNA.ORG_FLAGS=00D00000000000000000000000000000",
                "http-get:*:image/webp:DLNA.ORG_OP=01;DLNA.ORG_FLAGS=00D00000000000000000000000000000",
            ]

            source_info = ",".join(source_protocols)
            sink_info = ""  # This server doesn't act as a sink

            response = f"""<?xml version="1.0" encoding="utf-8"?>
<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/">
    <s:Body>
        <u:GetProtocolInfoResponse xmlns:u="urn:schemas-upnp-org:service:ConnectionManager:1">
            <Source>{source_info}</Source>
            <Sink>{sink_info}</Sink>
        </u:GetProtocolInfoResponse>
    </s:Body>
</s:Envelope>"""

            self.send_response(200)
            self.send_header("Content-Type", "text/xml; charset=utf-8")
            self.send_header("Content-Length", str(len(response)))
            self.end_headers()
            self.wfile.write(response.encode())
            if self.verbose:
                print("Sent GetProtocolInfo response")

        except Exception as e:
            print(f"Error handling GetProtocolInfo: {e}")
            traceback.print_exc()
            self.send_error(500, "Internal server error")

    def handle_get_current_connection_ids(self):
        """Handle ConnectionManager GetCurrentConnectionIDs requests"""
        try:
            print("Handling GetCurrentConnectionIDs request")

            response = """<?xml version="1.0" encoding="utf-8"?>
<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/">
    <s:Body>
        <u:GetCurrentConnectionIDsResponse xmlns:u="urn:schemas-upnp-org:service:ConnectionManager:1">
            <ConnectionIDs>0</ConnectionIDs>
        </u:GetCurrentConnectionIDsResponse>
    </s:Body>
</s:Envelope>"""

            self.send_response(200)
            self.send_header("Content-Type", "text/xml; charset=utf-8")
            self.send_header("Content-Length", str(len(response)))
            self.end_headers()
            self.wfile.write(response.encode())
            if self.verbose:
                print("Sent GetCurrentConnectionIDs response")

        except Exception as e:
            print(f"Error handling GetCurrentConnectionIDs: {e}")
            traceback.print_exc()
            self.send_error(500, "Internal server error")

    def handle_get_current_connection_info(self):
        """Handle ConnectionManager GetCurrentConnectionInfo requests"""
        try:
            print("Handling GetCurrentConnectionInfo request")

            response = """<?xml version="1.0" encoding="utf-8"?>
<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/">
    <s:Body>
        <u:GetCurrentConnectionInfoResponse xmlns:u="urn:schemas-upnp-org:service:ConnectionManager:1">
            <RcsID>-1</RcsID>
            <AVTransportID>-1</AVTransportID>
            <ProtocolInfo></ProtocolInfo>
            <PeerConnectionManager></PeerConnectionManager>
            <PeerConnectionID>-1</PeerConnectionID>
            <Direction>Output</Direction>
            <Status>OK</Status>
        </u:GetCurrentConnectionInfoResponse>
    </s:Body>
</s:Envelope>"""

            self.send_response(200)
            self.send_header("Content-Type", "text/xml; charset=utf-8")
            self.send_header("Content-Length", str(len(response)))
            self.end_headers()
            self.wfile.write(response.encode())
            if self.verbose:
                print("Sent GetCurrentConnectionInfo response")

        except Exception as e:
            print(f"Error handling GetCurrentConnectionInfo: {e}")
            traceback.print_exc()
            self.send_error(500, "Internal server error")

    def handle_get_search_capabilities(self):
        """Handle ContentDirectory GetSearchCapabilities requests"""
        try:
            print("Handling GetSearchCapabilities request")

            # Define basic search capabilities
            search_caps = "dc:title,dc:creator,upnp:class,upnp:genre,dc:date"

            response = f"""<?xml version="1.0" encoding="utf-8"?>
<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/">
    <s:Body>
        <u:GetSearchCapabilitiesResponse xmlns:u="urn:schemas-upnp-org:service:ContentDirectory:1">
            <SearchCaps>{search_caps}</SearchCaps>
        </u:GetSearchCapabilitiesResponse>
    </s:Body>
</s:Envelope>"""

            self.send_response(200)
            self.send_header("Content-Type", "text/xml; charset=utf-8")
            self.send_header("Content-Length", str(len(response)))
            self.end_headers()
            self.wfile.write(response.encode())
            if self.verbose:
                print("Sent GetSearchCapabilities response")

        except Exception as e:
            print(f"Error handling GetSearchCapabilities: {e}")
            traceback.print_exc()
            self.send_error(500, "Internal server error")

    def handle_get_sort_capabilities(self):
        """Handle ContentDirectory GetSortCapabilities requests"""
        try:
            print("Handling GetSortCapabilities request")

            # Define basic sort capabilities
            sort_caps = "dc:title,dc:creator,dc:date,upnp:class"

            response = f"""<?xml version="1.0" encoding="utf-8"?>
<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/">
    <s:Body>
        <u:GetSortCapabilitiesResponse xmlns:u="urn:schemas-upnp-org:service:ContentDirectory:1">
            <SortCaps>{sort_caps}</SortCaps>
        </u:GetSortCapabilitiesResponse>
    </s:Body>
</s:Envelope>"""

            self.send_response(200)
            self.send_header("Content-Type", "text/xml; charset=utf-8")
            self.send_header("Content-Length", str(len(response)))
            self.end_headers()
            self.wfile.write(response.encode())
            if self.verbose:
                print("Sent GetSortCapabilities response")

        except Exception as e:
            print(f"Error handling GetSortCapabilities: {e}")
            traceback.print_exc()
            self.send_error(500, "Internal server error")

    def handle_get_system_update_id(self):
        """Handle ContentDirectory GetSystemUpdateID requests"""
        try:
            if self.verbose:
                print("Handling GetSystemUpdateID request")

            # Use the server's managed system update ID
            system_update_id = self.server_instance.get_system_update_id()

            response = f"""<?xml version="1.0" encoding="utf-8"?>
<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/">
    <s:Body>
        <u:GetSystemUpdateIDResponse xmlns:u="urn:schemas-upnp-org:service:ContentDirectory:1">
            <Id>{system_update_id}</Id>
        </u:GetSystemUpdateIDResponse>
    </s:Body>
</s:Envelope>"""

            self.send_response(200)
            self.send_header("Content-Type", "text/xml; charset=utf-8")
            self.send_header("Content-Length", str(len(response)))
            # Allow reasonable caching of SystemUpdateID response
            self.send_header("Cache-Control", "max-age=30")
            self.end_headers()
            self.wfile.write(response.encode())
            if self.verbose:
                print(f"Sent GetSystemUpdateID response: {system_update_id}")

        except Exception as e:
            print(f"Error handling GetSystemUpdateID: {e}")
            traceback.print_exc()
            self.send_error(500, "Internal server error")

    def handle_browse_request(self, soap_data):
        """Handle ContentDirectory Browse requests"""
        try:
            if self.verbose:
                print(f"Browse request: {soap_data}")

            # Parse SOAP parameters using simple string parsing
            object_id = "0"  # Default to root
            browse_flag = "BrowseDirectChildren"  # Default

            # Extract ObjectID from SOAP - handle XML with attributes
            if "<ObjectID" in soap_data:
                # Find the opening tag (might have attributes)
                start_tag_start = soap_data.find("<ObjectID")
                if start_tag_start != -1:
                    # Find the end of the opening tag
                    start_tag_end = soap_data.find(">", start_tag_start)
                    if start_tag_end != -1:
                        # Find the closing tag
                        end_tag_start = soap_data.find("</ObjectID>", start_tag_end)
                        if end_tag_start != -1:
                            # Extract the content between tags
                            object_id = soap_data[
                                start_tag_end + 1 : end_tag_start
                            ].strip()
                            print(f"Extracted ObjectID: '{object_id}'")

            # Extract BrowseFlag from SOAP - handle XML with attributes
            if "<BrowseFlag" in soap_data:
                start_tag_start = soap_data.find("<BrowseFlag")
                if start_tag_start != -1:
                    start_tag_end = soap_data.find(">", start_tag_start)
                    if start_tag_end != -1:
                        end_tag_start = soap_data.find("</BrowseFlag>", start_tag_end)
                        if end_tag_start != -1:
                            browse_flag = soap_data[
                                start_tag_end + 1 : end_tag_start
                            ].strip()
                            print(f"Extracted BrowseFlag: '{browse_flag}'")

            # Extract StartingIndex and RequestedCount from SOAP - handle XML with attributes
            starting_index = 0
            requested_count = None
            if "<StartingIndex" in soap_data:
                start_tag_start = soap_data.find("<StartingIndex")
                if start_tag_start != -1:
                    start_tag_end = soap_data.find(">", start_tag_start)
                    if start_tag_end != -1:
                        end_tag_start = soap_data.find(
                            "</StartingIndex>", start_tag_end
                        )
                        if end_tag_start != -1:
                            try:
                                starting_index = int(
                                    soap_data[start_tag_end + 1 : end_tag_start].strip()
                                )
                            except Exception:
                                starting_index = 0
            if "<RequestedCount" in soap_data:
                start_tag_start = soap_data.find("<RequestedCount")
                if start_tag_start != -1:
                    start_tag_end = soap_data.find(">", start_tag_start)
                    if start_tag_end != -1:
                        end_tag_start = soap_data.find(
                            "</RequestedCount>", start_tag_end
                        )
                        if end_tag_start != -1:
                            try:
                                requested_count = int(
                                    soap_data[start_tag_end + 1 : end_tag_start].strip()
                                )
                            except Exception:
                                requested_count = None

            if self.verbose:
                print(f"Browse ObjectID: {object_id}, BrowseFlag: {browse_flag}")
                print(
                    f"StartingIndex: {starting_index}, RequestedCount: {requested_count}"
                )

            # Setup the directory structure mapping - regenerate on each browse for fresh content
            # This is simpler and ensures clients always see current directory state
            self.directory_mapping = self._create_directory_mapping()

            # Generate DIDL-Lite XML for media files
            didl_items = []

            # ObjectID 0 is the root container
            if object_id == "0" and browse_flag == "BrowseDirectChildren":
                # Refresh cache when clients access the root container
                self.server_instance.refresh_cache_on_root_access()

                # Root: Show the main media directory as a container
                # Count the actual children in the media directory
                child_count = self._count_dir_children(
                    self.server_instance.media_directory
                )
                didl_items.append(
                    f'<container id="1" parentID="0" restricted="1" searchable="1" childCount="{child_count}">\n'
                    "    <dc:title>Media Library</dc:title>\n"
                    "    <upnp:class>object.container.storageFolder</upnp:class>\n"
                    "    <upnp:writeStatus>NOT_WRITABLE</upnp:writeStatus>\n"
                    "</container>"
                )
                number_returned = 1
                total_matches = 1

            # ObjectID 1 is the main media directory
            elif object_id == "1" and browse_flag == "BrowseDirectChildren":
                # Refresh cache when clients access the main media library
                self.server_instance.refresh_cache_on_root_access()

                if self.verbose:
                    print(
                        f"Browsing main media directory: {self.server_instance.media_directory}"
                    )
                # Get direct children (files and folders) in the root media directory
                children = []

                # List directory contents for debugging
                try:
                    dir_contents = os.listdir(self.server_instance.media_directory)
                    if self.verbose:
                        print(
                            f"Directory contains {len(dir_contents)} items: {dir_contents[:10]}..."
                        )  # Show first 10 items
                except Exception as e:
                    print(f"Error listing directory: {e}")
                    total_matches = 0
                    number_returned = 0

                for item_name in os.listdir(self.server_instance.media_directory):
                    item_path = os.path.join(
                        self.server_instance.media_directory, item_name
                    )
                    if os.path.isdir(item_path):
                        # Add directory
                        dir_id = self._get_id_for_path(item_name)
                        # Count child items
                        child_count = self._count_dir_children(item_path)
                        children.append(
                            {
                                "id": dir_id,
                                "name": item_name,
                                "is_dir": True,
                                "child_count": child_count,
                            }
                        )
                    elif os.path.isfile(item_path):
                        mime_type, _ = custom_mimetypes.guess_type(item_name)
                        if mime_type and (
                            mime_type.startswith("video/")
                            or mime_type.startswith("audio/")
                            or mime_type.startswith("image/")
                        ):
                            # Add media file
                            file_id = self._get_id_for_path(item_name)
                            children.append(
                                {
                                    "id": file_id,
                                    "name": item_name,
                                    "is_dir": False,
                                    "path": item_name,
                                    "full_path": item_path,
                                    "mime_type": mime_type,
                                    "size": os.path.getsize(item_path),
                                }
                            )

                # Get total number of direct children
                total_matches = len(children)
                if self.verbose:
                    print(f"Found {total_matches} children in media directory")
                    print(
                        f"Children: {[child['name'] for child in children[:5]]}..."
                    )  # Show first 5 names

                # Apply pagination
                if requested_count is not None and requested_count > 0:
                    children_slice = children[
                        starting_index : starting_index + requested_count
                    ]
                else:
                    children_slice = children[starting_index:]

                number_returned = len(children_slice)
                if self.verbose:
                    print(
                        f"Returning {number_returned} items (pagination: start={starting_index}, count={requested_count})"
                    )

                # Generate DIDL items for each child
                for child in children_slice:
                    if child["is_dir"]:
                        # This is a directory/container
                        container = (
                            f'<container id="{child["id"]}" parentID="1" restricted="1" searchable="1" childCount="{child["child_count"]}">\n'
                            f'    <dc:title>{html.escape(child["name"])}</dc:title>\n'
                            f"    <upnp:class>object.container.storageFolder</upnp:class>\n"
                            f"    <upnp:writeStatus>NOT_WRITABLE</upnp:writeStatus>\n"
                            f"</container>"
                        )
                        didl_items.append(container)
                    else:
                        # This is a media file
                        didl_items.append(self._create_media_item_didl(child, "1"))

            # Handle browsing of subdirectories or specific directory
            elif browse_flag == "BrowseDirectChildren" and object_id not in ["0", "1"]:
                if self.verbose:
                    print(f"Browsing directory with ID: {object_id}")
                # Get the path for this directory ID
                dir_path = self._get_path_for_id(object_id)

                if dir_path:
                    full_path = os.path.join(
                        self.server_instance.media_directory, dir_path
                    )

                    # Check if the path exists and is a directory
                    if os.path.exists(full_path) and os.path.isdir(full_path):
                        # Get contents of this directory
                        children = []
                        for item_name in os.listdir(full_path):
                            item_path = os.path.join(full_path, item_name)
                            rel_path = os.path.join(dir_path, item_name)

                            if os.path.isdir(item_path):
                                # Add subdirectory
                                subdir_id = self._get_id_for_path(rel_path)
                                child_count = self._count_dir_children(item_path)
                                children.append(
                                    {
                                        "id": subdir_id,
                                        "name": item_name,
                                        "is_dir": True,
                                        "child_count": child_count,
                                    }
                                )
                            elif os.path.isfile(item_path):
                                mime_type, _ = custom_mimetypes.guess_type(item_name)
                                if mime_type and (
                                    mime_type.startswith("video/")
                                    or mime_type.startswith("audio/")
                                    or mime_type.startswith("image/")
                                ):
                                    # Add media file
                                    file_id = self._get_id_for_path(rel_path)
                                    children.append(
                                        {
                                            "id": file_id,
                                            "name": item_name,
                                            "is_dir": False,
                                            "path": rel_path,
                                            "full_path": item_path,
                                            "mime_type": mime_type,
                                            "size": os.path.getsize(item_path),
                                        }
                                    )

                        # Get total number of direct children
                        total_matches = len(children)

                        # Apply pagination
                        if requested_count is not None and requested_count > 0:
                            children_slice = children[
                                starting_index : starting_index + requested_count
                            ]
                        else:
                            children_slice = children[starting_index:]

                        number_returned = len(children_slice)

                        # Generate DIDL items for each child
                        for child in children_slice:
                            if child["is_dir"]:
                                # This is a directory/container
                                container = (
                                    f'<container id="{child["id"]}" parentID="{object_id}" restricted="1" searchable="1" childCount="{child["child_count"]}">\n'
                                    f'    <dc:title>{html.escape(child["name"])}</dc:title>\n'
                                    f"    <upnp:class>object.container.storageFolder</upnp:class>\n"
                                    f"    <upnp:writeStatus>NOT_WRITABLE</upnp:writeStatus>\n"
                                    f"</container>"
                                )
                                didl_items.append(container)
                            else:
                                # This is a media file
                                didl_items.append(
                                    self._create_media_item_didl(child, object_id)
                                )
                    else:
                        # Directory not found
                        print(f"Directory not found: {full_path}")
                        total_matches = 0
                        number_returned = 0
                else:
                    # Invalid directory ID
                    print(f"Invalid directory ID: {object_id}")
                    total_matches = 0
                    number_returned = 0

            # Handle metadata requests for an item
            elif browse_flag == "BrowseMetadata":
                if self.verbose:
                    print(f"Browsing metadata for item with ID: {object_id}")

                if object_id == "0":
                    # Root container metadata
                    didl_items.append(
                        '<container id="0" parentID="-1" restricted="1" searchable="1" childCount="1">\n'
                        "    <dc:title>Media Library</dc:title>\n"
                        "    <upnp:class>object.container.storageFolder</upnp:class>\n"
                        "    <upnp:writeStatus>NOT_WRITABLE</upnp:writeStatus>\n"
                        "</container>"
                    )
                    total_matches = 1
                    number_returned = 1
                elif object_id == "1":
                    # Main media directory metadata
                    child_count = self._count_dir_children(
                        self.server_instance.media_directory
                    )
                    didl_items.append(
                        f'<container id="1" parentID="0" restricted="1" searchable="1" childCount="{child_count}">\n'
                        "    <dc:title>Media Library</dc:title>\n"
                        "    <upnp:class>object.container.storageFolder</upnp:class>\n"
                        "    <upnp:writeStatus>NOT_WRITABLE</upnp:writeStatus>\n"
                        "</container>"
                    )
                    total_matches = 1
                    number_returned = 1
                else:
                    # Get metadata for a specific item
                    item_path = self._get_path_for_id(object_id)

                    if item_path:
                        full_path = os.path.join(
                            self.server_instance.media_directory, item_path
                        )
                        parent_id = self._get_parent_id(object_id)

                        if os.path.isdir(full_path):
                            # Directory metadata
                            dir_name = os.path.basename(item_path)
                            child_count = self._count_dir_children(full_path)

                            container = (
                                f'<container id="{object_id}" parentID="{parent_id}" restricted="1" searchable="1" childCount="{child_count}">\n'
                                f"    <dc:title>{html.escape(dir_name)}</dc:title>\n"
                                f"    <upnp:class>object.container.storageFolder</upnp:class>\n"
                                f"    <upnp:writeStatus>NOT_WRITABLE</upnp:writeStatus>\n"
                                f"</container>"
                            )
                            didl_items.append(container)
                        elif os.path.isfile(full_path):
                            # File metadata
                            file_name = os.path.basename(item_path)
                            mime_type, _ = custom_mimetypes.guess_type(file_name)

                            if mime_type and (
                                mime_type.startswith("video/")
                                or mime_type.startswith("audio/")
                                or mime_type.startswith("image/")
                            ):

                                file_info = {
                                    "id": object_id,
                                    "name": file_name,
                                    "is_dir": False,
                                    "path": item_path,
                                    "full_path": full_path,
                                    "mime_type": mime_type,
                                    "size": os.path.getsize(full_path),
                                }

                                didl_items.append(
                                    self._create_media_item_didl(file_info, parent_id)
                                )

                        total_matches = 1
                        number_returned = 1
                    else:
                        # Item not found
                        total_matches = 0
                        number_returned = 0
            else:
                # Unsupported browse request
                total_matches = 0
                number_returned = 0

            # Create DIDL-Lite response
            didl_xml = (
                '<?xml version="1.0" encoding="utf-8"?>\n'
                '<DIDL-Lite xmlns="urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/" '
                'xmlns:dc="http://purl.org/dc/elements/1.1/" '
                'xmlns:upnp="urn:schemas-upnp-org:metadata-1-0/upnp/" '
                'xmlns:dlna="urn:schemas-dlna-org:metadata-1-0/">\n'
                + "\n".join(didl_items)
                + "\n</DIDL-Lite>"
            )

            if self.verbose:
                print(f"Result: {number_returned} items of {total_matches} total")

            # Create SOAP response using the server's SystemUpdateID
            system_update_id = self.server_instance.get_system_update_id()

            response = f"""<?xml version="1.0" encoding="utf-8"?>
<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" s:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">
    <s:Body>
        <u:BrowseResponse xmlns:u="urn:schemas-upnp-org:service:ContentDirectory:1">
            <Result>{html.escape(didl_xml)}</Result>
            <NumberReturned>{number_returned}</NumberReturned>
            <TotalMatches>{total_matches}</TotalMatches>
            <UpdateID>{system_update_id}</UpdateID>
        </u:BrowseResponse>
    </s:Body>
</s:Envelope>"""

            self.send_response(200)
            self.send_header("Content-Type", 'text/xml; charset="utf-8"')
            self.send_header("Content-Length", str(len(response)))
            self.send_header("Ext", "")
            self.send_header("Server", SERVER_AGENT)
            # Allow very short-term caching but ensure revalidation with server
            self.send_header("Cache-Control", "max-age=10, must-revalidate")
            self.end_headers()
            self.wfile.write(response.encode())

            if self.verbose:
                print(f"Browse response sent with SystemUpdateID: {system_update_id}")

        except Exception as e:
            print(f"Browse request error: {e}")
            traceback.print_exc()
            self.send_error(500, "Internal server error")

    def _create_directory_mapping(self):
        """Create a mapping between directory paths and IDs"""
        # This is a simple mapping system that assigns numeric IDs to each path
        # Root (0) and Media directory (1) are already assigned
        mapping = {
            "0": "",  # Root
            "1": "",  # Media directory
        }

        # Start ID counter from 2 (0 and 1 are reserved)
        id_counter = 2

        # Helper function to scan directories recursively
        def scan_dir(dir_path, relative_path=""):
            nonlocal id_counter

            try:
                for item in os.listdir(dir_path):
                    item_path = os.path.join(dir_path, item)
                    item_rel_path = (
                        os.path.join(relative_path, item) if relative_path else item
                    )

                    # Assign an ID to this path
                    mapping[str(id_counter)] = item_rel_path
                    mapping[item_rel_path] = str(id_counter)
                    id_counter += 1

                    # Recursively scan subdirectories
                    if os.path.isdir(item_path):
                        scan_dir(item_path, item_rel_path)
            except Exception as e:
                print(f"Error scanning directory {dir_path}: {e}")

        # Start scanning from the media directory
        scan_dir(self.server_instance.media_directory)

        return mapping

    def _get_id_for_path(self, path):
        """Get the ID for a specific path"""
        if self.directory_mapping is None:
            self.directory_mapping = self._create_directory_mapping()

        # Check if the path exists in the mapping
        if path in self.directory_mapping:
            return self.directory_mapping[path]

        # If not found, add it to the mapping
        new_id = str(max(int(id) for id in self.directory_mapping if id.isdigit()) + 1)
        self.directory_mapping[new_id] = path
        self.directory_mapping[path] = new_id
        return new_id

    def _get_path_for_id(self, id_str):
        """Get the path for a specific ID"""
        if self.directory_mapping is None:
            self.directory_mapping = self._create_directory_mapping()

        return self.directory_mapping.get(id_str)

    def _get_parent_id(self, id_str):
        """Get the parent ID for a given item ID"""
        if id_str == "0":
            return "-1"  # Root has no parent
        if id_str == "1":
            return "0"  # Media directory's parent is root

        path = self._get_path_for_id(id_str)
        if not path:
            return "1"  # Default to media directory if path not found

        parent_path = os.path.dirname(path)
        if not parent_path:
            return "1"  # If no parent path, then parent is the media directory

        return self._get_id_for_path(parent_path)

    def _count_dir_children(self, dir_path):
        """Count the number of media files and subdirectories in a directory"""
        count = 0
        try:
            for item in os.listdir(dir_path):
                item_path = os.path.join(dir_path, item)
                if os.path.isdir(item_path):
                    count += 1
                elif os.path.isfile(item_path):
                    if is_supported_media_file(item_path):
                        count += 1
        except Exception as e:
            print(f"Error counting directory children in {dir_path}: {e}")
        return count

    def _get_media_duration(self, file_path, mime_type):
        """
        Attempt to get the actual duration of a media file.
        Falls back to default values if extraction fails.
        Uses only Python standard library methods.
        """
        try:
            # Default fallback durations based on file type
            default_durations = {
                # Video formats
                "video/mp4": "01:30:00",
                "video/x-msvideo": "00:45:00",
                "video/x-matroska": "02:00:00",
                "video/quicktime": "01:15:00",
                "video/x-ms-wmv": "01:00:00",
                "video/x-flv": "00:30:00",
                "video/webm": "01:00:00",
                "video/x-m4v": "01:30:00",
                "video/3gpp": "00:15:00",
                # Audio formats
                "audio/mpeg": "00:03:30",
                "audio/wav": "00:05:00",
                "audio/mp4": "00:04:00",
                "audio/x-m4a": "00:04:00",
                "audio/flac": "00:05:00",
                "audio/ogg": "00:04:00",
                "audio/x-ms-wma": "00:04:00",
                "audio/aiff": "00:05:00",
            }

            # Try to get duration using ffprobe if available (skip if fast mode is enabled)
            if (
                not self.fast
                and mime_type
                and (mime_type.startswith("video/") or mime_type.startswith("audio/"))
            ):
                try:
                    # Try ffprobe first (most reliable)
                    result = subprocess.run(
                        [
                            "ffprobe",
                            "-v",
                            "quiet",
                            "-show_entries",
                            "format=duration",
                            "-of",
                            "csv=p=0",
                            file_path,
                        ],
                        capture_output=True,
                        text=True,
                        timeout=10,
                        check=False,
                    )

                    if result.returncode == 0 and result.stdout.strip():
                        duration_seconds = float(result.stdout.strip())
                        return self._seconds_to_hms(duration_seconds)
                except (
                    subprocess.SubprocessError,
                    FileNotFoundError,
                    ValueError,
                    subprocess.TimeoutExpired,
                ):
                    pass

                # Try mediainfo as fallback
                try:
                    result = subprocess.run(
                        ["mediainfo", "--Inform=General;%Duration%", file_path],
                        capture_output=True,
                        text=True,
                        timeout=10,
                        check=False,
                    )

                    if result.returncode == 0 and result.stdout.strip():
                        duration_ms = int(result.stdout.strip())
                        duration_seconds = duration_ms / 1000
                        return self._seconds_to_hms(duration_seconds)
                except (
                    subprocess.SubprocessError,
                    FileNotFoundError,
                    ValueError,
                    subprocess.TimeoutExpired,
                ):
                    pass

            # Try basic MP4 parsing for MP4 files (works even in fast mode)
            if mime_type == "video/mp4":
                mp4_duration = self._parse_mp4_duration(file_path)
                if mp4_duration:
                    return mp4_duration

            # Try basic AVI parsing for AVI files (works even in fast mode)
            if mime_type == "video/x-msvideo":
                avi_duration = self._parse_avi_duration(file_path)
                if avi_duration:
                    return avi_duration

            # Return default duration for the mime type
            return default_durations.get(mime_type, "01:00:00")

        except Exception as e:
            print(f"Error getting duration for {file_path}: {e}")
            # Return a reasonable default
            if mime_type and mime_type.startswith("video/"):
                return "01:30:00"
            if mime_type and mime_type.startswith("audio/"):
                return "00:04:00"
            return "01:00:00"

    def _seconds_to_hms(self, seconds):
        """Convert seconds to HH:MM:SS format"""
        try:
            hours = int(seconds // 3600)
            minutes = int((seconds % 3600) // 60)
            secs = int(seconds % 60)
            return f"{hours:02d}:{minutes:02d}:{secs:02d}"
        except Exception:
            return "01:00:00"

    def _parse_mp4_duration(self, file_path):
        """
        Basic MP4 duration parsing using binary file reading.
        Looks for mvhd atom which contains duration information.
        """
        try:
            with open(file_path, "rb") as f:
                # Read first 64KB to look for mvhd atom
                data = f.read(65536)

                # Look for 'mvhd' atom
                mvhd_pos = data.find(b"mvhd")
                if mvhd_pos == -1:
                    return None

                # Skip to timescale and duration fields
                # mvhd structure: size(4) + type(4) + version(1) + flags(3) +
                # creation_time(4) + modification_time(4) + timescale(4) + duration(4)
                timescale_pos = (
                    mvhd_pos + 12
                )  # Skip mvhd + version/flags + creation/modification time
                duration_pos = timescale_pos + 4

                if duration_pos + 4 <= len(data):
                    timescale = struct.unpack(
                        ">I", data[timescale_pos : timescale_pos + 4]
                    )[0]
                    duration = struct.unpack(
                        ">I", data[duration_pos : duration_pos + 4]
                    )[0]

                    if timescale > 0:
                        duration_seconds = duration / timescale
                        return self._seconds_to_hms(duration_seconds)

        except Exception as e:
            print(f"Error parsing MP4 duration: {e}")

        return None

    def _parse_avi_duration(self, file_path):
        """
        Basic AVI duration parsing using binary file reading.
        Looks for avih chunk which contains frame rate and total frames.
        """
        try:
            with open(file_path, "rb") as f:
                # Read first 64KB to look for avih chunk
                data = f.read(65536)

                # Look for 'avih' chunk
                avih_pos = data.find(b"avih")
                if avih_pos == -1:
                    return None

                # avih structure includes microseconds per frame and total frames
                # Skip chunk header and get to the data
                microsec_per_frame_pos = avih_pos + 8  # Skip 'avih' + size
                total_frames_pos = microsec_per_frame_pos + 4

                if total_frames_pos + 4 <= len(data):
                    microsec_per_frame = struct.unpack(
                        "<I", data[microsec_per_frame_pos : microsec_per_frame_pos + 4]
                    )[0]
                    total_frames = struct.unpack(
                        "<I", data[total_frames_pos : total_frames_pos + 4]
                    )[0]

                    if microsec_per_frame > 0 and total_frames > 0:
                        duration_seconds = (total_frames * microsec_per_frame) / 1000000
                        return self._seconds_to_hms(duration_seconds)

        except Exception as e:
            print(f"Error parsing AVI duration: {e}")

        return None

    def _create_media_item_didl(self, file_info, parent_id):
        """Create DIDL-Lite XML for a media item"""
        file_path = file_info["full_path"]
        file_size = file_info["size"]
        file = file_info["name"]
        relative_path = file_info["path"]
        mime_type = file_info["mime_type"]
        file_id = file_info["id"]

        # Use the relative path for the URL
        encoded_path = quote(relative_path, safe="")
        file_url = f"http://{self.server_instance.server_ip}:{self.server_instance.port}/media/{encoded_path}"

        # Default values
        dlna_profile = "DLNA.ORG_OP=01;DLNA.ORG_FLAGS=01700000000000000000000000000000000"  # Generic
        res_attrs = f'size="{file_size}"'
        dc_date = "2024-01-01T00:00:00"  # Placeholder date
        upnp_class = "object.item.videoItem"  # Default to video

        # Get actual duration for media files
        duration = self._get_media_duration(file_path, mime_type)

        if mime_type and mime_type.startswith("video/"):
            if mime_type == "video/mp4":
                dlna_profile = "DLNA.ORG_PN=AVC_MP4_MP_SD_AAC_MULT5;DLNA.ORG_OP=01;DLNA.ORG_FLAGS=01700000000000000000000000000000"
                res_attrs = f'size="{file_size}" duration="{duration}" resolution="1280x720" bitrate="4000000"'
            elif mime_type == "video/x-msvideo":  # AVI
                dlna_profile = "DLNA.ORG_PN=AVI;DLNA.ORG_OP=01;DLNA.ORG_FLAGS=01700000000000000000000000000000"
                res_attrs = f'size="{file_size}" duration="{duration}" resolution="720x576" bitrate="1500000"'
            elif mime_type == "video/x-matroska" or file.lower().endswith(
                ".mkv"
            ):  # MKV
                dlna_profile = "DLNA.ORG_PN=MATROSKA;DLNA.ORG_OP=01;DLNA.ORG_FLAGS=01700000000000000000000000000000"
                res_attrs = f'size="{file_size}" duration="{duration}" resolution="1920x1080" bitrate="8000000"'
            elif mime_type == "video/quicktime":  # MOV
                dlna_profile = (
                    "DLNA.ORG_OP=01;DLNA.ORG_FLAGS=01700000000000000000000000000000"
                )
                res_attrs = f'size="{file_size}" duration="{duration}" resolution="1280x720" bitrate="4000000"'
            elif mime_type == "video/x-ms-wmv":  # WMV
                dlna_profile = (
                    "DLNA.ORG_OP=01;DLNA.ORG_FLAGS=01700000000000000000000000000000"
                )
                res_attrs = f'size="{file_size}" duration="{duration}" resolution="1024x768" bitrate="2000000"'
            elif mime_type == "video/x-flv":  # FLV
                dlna_profile = (
                    "DLNA.ORG_OP=01;DLNA.ORG_FLAGS=01700000000000000000000000000000"
                )
                res_attrs = f'size="{file_size}" duration="{duration}" resolution="640x480" bitrate="1000000"'
            elif mime_type == "video/webm":  # WEBM
                dlna_profile = (
                    "DLNA.ORG_OP=01;DLNA.ORG_FLAGS=01700000000000000000000000000000"
                )
                res_attrs = f'size="{file_size}" duration="{duration}" resolution="1280x720" bitrate="3000000"'
            elif mime_type == "video/x-m4v":  # M4V
                dlna_profile = (
                    "DLNA.ORG_OP=01;DLNA.ORG_FLAGS=01700000000000000000000000000000"
                )
                res_attrs = f'size="{file_size}" duration="{duration}" resolution="1280x720" bitrate="4000000"'
            elif mime_type == "video/3gpp":  # 3GP
                dlna_profile = (
                    "DLNA.ORG_OP=01;DLNA.ORG_FLAGS=01700000000000000000000000000000"
                )
                res_attrs = f'size="{file_size}" duration="{duration}" resolution="320x240" bitrate="500000"'
            else:
                # Default for unknown video formats
                dlna_profile = (
                    "DLNA.ORG_OP=01;DLNA.ORG_FLAGS=01700000000000000000000000000000"
                )
                res_attrs = f'size="{file_size}" duration="{duration}"'

            escaped_title = html.escape(file)
            protocol_info = f"http-get:*:{mime_type}:{dlna_profile}"

            return (
                f'<item id="{file_id}" parentID="{parent_id}" restricted="1">\n'
                f"    <dc:title>{escaped_title}</dc:title>\n"
                f"    <upnp:class>{upnp_class}</upnp:class>\n"
                f"    <dc:creator>Unknown Creator</dc:creator>\n"
                f"    <upnp:artist>Unknown Artist</upnp:artist>\n"
                f"    <upnp:genre>Video</upnp:genre>\n"
                f"    <dc:description>Video File: {escaped_title}</dc:description>\n"
                f'    <res protocolInfo="{protocol_info}" {res_attrs}>{file_url}</res>\n'
                f"</item>"
            )

        if mime_type and mime_type.startswith("audio/"):
            upnp_class = "object.item.audioItem.musicTrack"
            if mime_type == "audio/mpeg":  # MP3
                dlna_profile = "DLNA.ORG_PN=MP3;DLNA.ORG_OP=01;DLNA.ORG_FLAGS=01700000000000000000000000000000"
                res_attrs = f'size="{file_size}" duration="{duration}" bitrate="320000"'
            elif mime_type == "audio/wav":  # WAV
                dlna_profile = "DLNA.ORG_PN=LPCM;DLNA.ORG_OP=01;DLNA.ORG_FLAGS=01700000000000000000000000000000"
                res_attrs = (
                    f'size="{file_size}" duration="{duration}" bitrate="1411200"'
                )
            elif mime_type in ("audio/mp4", "audio/x-m4a"):  # AAC/M4A
                dlna_profile = "DLNA.ORG_PN=AAC_ISO_320;DLNA.ORG_OP=01;DLNA.ORG_FLAGS=01700000000000000000000000000000"
                res_attrs = f'size="{file_size}" duration="{duration}" bitrate="320000"'
            elif mime_type == "audio/flac":  # FLAC
                dlna_profile = (
                    "DLNA.ORG_OP=01;DLNA.ORG_FLAGS=01700000000000000000000000000000"
                )
                res_attrs = (
                    f'size="{file_size}" duration="{duration}" bitrate="1000000"'
                )
            elif mime_type == "audio/ogg":  # OGG
                dlna_profile = (
                    "DLNA.ORG_OP=01;DLNA.ORG_FLAGS=01700000000000000000000000000000"
                )
                res_attrs = f'size="{file_size}" duration="{duration}" bitrate="320000"'
            elif mime_type == "audio/x-ms-wma":  # WMA
                dlna_profile = (
                    "DLNA.ORG_OP=01;DLNA.ORG_FLAGS=01700000000000000000000000000000"
                )
                res_attrs = f'size="{file_size}" duration="{duration}" bitrate="256000"'
            elif mime_type == "audio/aiff":  # AIFF
                dlna_profile = (
                    "DLNA.ORG_OP=01;DLNA.ORG_FLAGS=01700000000000000000000000000000"
                )
                res_attrs = (
                    f'size="{file_size}" duration="{duration}" bitrate="1411200"'
                )
            else:
                # Default for unknown audio formats
                dlna_profile = (
                    "DLNA.ORG_OP=01;DLNA.ORG_FLAGS=01700000000000000000000000000000"
                )
                res_attrs = f'size="{file_size}" duration="{duration}"'

            escaped_title = html.escape(file)
            protocol_info = f"http-get:*:{mime_type}:{dlna_profile}"

            return (
                f'<item id="{file_id}" parentID="{parent_id}" restricted="1">\n'
                f"    <dc:title>{escaped_title}</dc:title>\n"
                f"    <upnp:class>{upnp_class}</upnp:class>\n"
                f"    <dc:creator>Unknown Artist</dc:creator>\n"
                f"    <upnp:artist>Unknown Artist</upnp:artist>\n"
                f"    <upnp:album>Unknown Album</upnp:album>\n"
                f"    <upnp:genre>Music</upnp:genre>\n"
                f"    <dc:date>{dc_date}</dc:date>\n"
                f'    <res protocolInfo="{protocol_info}" {res_attrs}>{file_url}</res>\n'
                f"</item>"
            )

        if mime_type and mime_type.startswith("image/"):
            upnp_class = "object.item.imageItem.photo"
            if mime_type == "image/jpeg":
                dlna_profile = "DLNA.ORG_PN=JPEG_LRG;DLNA.ORG_OP=01;DLNA.ORG_FLAGS=00D00000000000000000000000000000"
                res_attrs = f'size="{file_size}" resolution="1920x1080"'
            elif mime_type == "image/png":
                dlna_profile = "DLNA.ORG_PN=PNG_LRG;DLNA.ORG_OP=01;DLNA.ORG_FLAGS=00D00000000000000000000000000000"
                res_attrs = f'size="{file_size}" resolution="1920x1080"'
            elif mime_type == "image/gif":  # GIF
                dlna_profile = (
                    "DLNA.ORG_OP=01;DLNA.ORG_FLAGS=00D00000000000000000000000000000"
                )
                res_attrs = f'size="{file_size}" resolution="800x600"'
            elif mime_type == "image/bmp":  # BMP
                dlna_profile = (
                    "DLNA.ORG_OP=01;DLNA.ORG_FLAGS=00D00000000000000000000000000000"
                )
                res_attrs = f'size="{file_size}" resolution="1024x768"'
            elif mime_type == "image/tiff":  # TIFF
                dlna_profile = (
                    "DLNA.ORG_OP=01;DLNA.ORG_FLAGS=00D00000000000000000000000000000"
                )
                res_attrs = f'size="{file_size}" resolution="2048x1536"'
            elif mime_type == "image/webp":  # WEBP
                dlna_profile = (
                    "DLNA.ORG_OP=01;DLNA.ORG_FLAGS=00D00000000000000000000000000000"
                )
                res_attrs = f'size="{file_size}" resolution="1920x1080"'
            else:
                # Default for unknown image formats
                dlna_profile = (
                    "DLNA.ORG_OP=01;DLNA.ORG_FLAGS=00D00000000000000000000000000000"
                )
                res_attrs = f'size="{file_size}"'

            escaped_title = html.escape(file)
            protocol_info = f"http-get:*:{mime_type}:{dlna_profile}"

            return (
                f'<item id="{file_id}" parentID="{parent_id}" restricted="1">\n'
                f"    <dc:title>{escaped_title}</dc:title>\n"
                f"    <upnp:class>{upnp_class}</upnp:class>\n"
                f"    <dc:creator>Unknown Creator</dc:creator>\n"
                f"    <upnp:artist>Unknown Artist</upnp:artist>\n"
                f"    <dc:description>Image: {escaped_title}</dc:description>\n"
                f'    <res protocolInfo="{protocol_info}" {res_attrs}>{file_url}</res>\n'
                f"</item>"
            )

        # Default case (should not happen if filtering correctly)
        escaped_title = html.escape(file)
        protocol_info = f"http-get:*:{mime_type}:{dlna_profile}"

        return (
            f'<item id="{file_id}" parentID="{parent_id}" restricted="1">\n'
            f"    <dc:title>{escaped_title}</dc:title>\n"
            f"    <upnp:class>object.item</upnp:class>\n"
            f'    <res protocolInfo="{protocol_info}" {res_attrs}>{file_url}</res>\n'
            f"</item>"
        )

    def handle_subscribe_request(self):
        """Handle UPnP event subscription requests"""
        try:
            if self.verbose:
                print(f"SUBSCRIBE request to {self.path}")
                print(f"SUBSCRIBE Headers: {dict(self.headers)}")

            # Generate a simple subscription ID
            sid = str(uuid.uuid4())

            # Basic subscription response
            self.send_response(200)
            self.send_header("SID", f"uuid:{sid}")
            self.send_header("TIMEOUT", "Second-1800")  # 30 minutes
            self.send_header("Content-Length", "0")
            self.end_headers()

            print(f"Sent SUBSCRIBE response with SID: {sid}")

        except Exception as e:
            print(f"Error handling SUBSCRIBE request: {e}")
            self.send_error(500, "Internal server error")

    def handle_unsubscribe_request(self):
        """Handle UPnP event unsubscription requests"""
        try:
            if self.verbose:
                print(f"UNSUBSCRIBE request to {self.path}")
                print(f"UNSUBSCRIBE Headers: {dict(self.headers)}")

            # Basic unsubscription response
            self.send_response(200)
            self.send_header("Content-Length", "0")
            self.end_headers()

            print("Sent UNSUBSCRIBE response")

        except Exception as e:
            print(f"Error handling UNSUBSCRIBE request: {e}")
            self.send_error(500, "Internal server error")
