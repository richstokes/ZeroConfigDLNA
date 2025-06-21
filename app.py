import hashlib
import os
import socket
import threading
import time
from http.server import ThreadingHTTPServer
import mimetypes
import argparse

from constants import (
    SERVER_NAME,
    SERVER_DESCRIPTION,
    SERVER_VERSION,
    SERVER_MANUFACTURER,
)
from dlna import DLNAHandler
from ssdp import SSDPServer


class ZeroConfigDLNA:
    def __init__(self, media_directory=None, port=8200, verbose=False):
        self.name = SERVER_NAME
        self.version = SERVER_VERSION
        self.author = SERVER_MANUFACTURER
        self.description = SERVER_DESCRIPTION
        self.media_directory = media_directory or os.getcwd()
        self.port = port
        self.server = None
        self.server_thread = None
        self.verbose = verbose
        socket.setdefaulttimeout(60)  # 60 seconds timeout

        # Generate UUID that includes directory content signature
        # This forces client cache refresh when content changes significantly
        self.device_uuid = self._generate_content_aware_uuid()
        self.server_ip = self.get_local_ip()
        self.running = False

        # Simple counter that increments on root folder access to force refresh
        self._system_update_id = (
            int(time.time()) % 1000000
        )  # Start with timestamp-based ID
        self._last_refresh_time = 0
        self.ssdp_server = SSDPServer(self, verbose=self.verbose)

    def get_local_ip(self):
        """Get the local IP address"""
        try:
            # Connect to a remote address to determine local IP
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect(("8.8.8.8", 80))
                return s.getsockname()[0]
        except Exception:
            return "127.0.0.1"

    def create_handler(self):
        """Create a handler class with server instance"""
        server_ref = self

        class Handler(DLNAHandler):  # Create a subclass of DLNAHandler
            server_instance = server_ref
            verbose = server_ref.verbose

        return Handler

    def start(self):
        """Start the DLNA server"""
        try:
            print(f"{self.name} v{self.version} is starting...")
            print(f"Media directory: {os.path.abspath(self.media_directory)}")
            print(f"Server IP: {self.server_ip}")
            print(f"Port: {self.port}")

            if not os.path.exists(self.media_directory):
                print(
                    f"Error: Media directory '{self.media_directory}' does not exist!"
                )
                return False

            # Check if port is available
            try:
                test_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                test_socket.bind((self.server_ip, self.port))
                test_socket.close()
            except OSError:
                print(
                    f"Error: Port {self.port} is already in use. Try a different port with -p option."
                )
                return False

            # Count media files
            media_count = 0

            def count_media_files(directory):
                nonlocal media_count
                for item in os.listdir(directory):
                    item_path = os.path.join(directory, item)
                    if os.path.isfile(item_path):
                        mime_type, _ = mimetypes.guess_type(item)
                        if mime_type and (
                            mime_type.startswith("video/")
                            or mime_type.startswith("audio/")
                            or mime_type.startswith("image/")
                        ):
                            media_count += 1
                    elif os.path.isdir(item_path):
                        # Recursively count files in subdirectories
                        count_media_files(item_path)

            count_media_files(self.media_directory)
            print(f"Found {media_count} media files to serve")

            # Use ThreadingHTTPServer to handle concurrent requests
            self.server = ThreadingHTTPServer(
                (self.server_ip, self.port), self.create_handler()
            )
            # Set server-side timeout to ensure we don't block forever on client operations
            self.server.timeout = 300  # Long timeout for media streaming / pausing etc
            self.server_thread = threading.Thread(target=self.server.serve_forever)
            self.server_thread.daemon = True
            self.server_thread.start()

            self.running = True
            print(f"DLNA Server running at http://{self.server_ip}:{self.port}/")
            print(
                f"Device description: http://{self.server_ip}:{self.port}/description.xml"
            )
            print(f"Browse media: http://{self.server_ip}:{self.port}/browse")
            print("Press Ctrl+C to stop the server")

            # Start SSDP server for UPnP discovery
            self.ssdp_server.start()

            return True

        except Exception as e:
            print(f"Error starting server: {e}")
            return False

    def stop(self):
        """Stop the DLNA server"""
        print(f"{self.name} is stopping...")
        self.running = False
        if self.server:
            self.server.shutdown()
            self.server.server_close()
        if self.server_thread:
            self.server_thread.join(timeout=5)
        # Stop SSDP server
        self.ssdp_server.stop()
        print("Server stopped")

    def run(self):
        """Run the server and handle keyboard interrupt"""
        if self.start():
            try:
                while self.running:
                    time.sleep(1)
            except KeyboardInterrupt:
                pass
            finally:
                self.stop()

    def refresh_cache_on_root_access(self):
        """
        Increment SystemUpdateID when clients access the root media folder.
        This forces clients to refresh their directory cache.
        """
        self._system_update_id += 1
        self._last_refresh_time = time.time()

        if self.verbose:
            print(
                f"Root folder accessed - refreshed SystemUpdateID to {self._system_update_id}"
            )

    def should_refresh_directory_mapping(self):
        """Check if directory mapping should be refreshed (within last 5 seconds of cache refresh)."""
        return time.time() - self._last_refresh_time < 5

    def get_system_update_id(self):
        """Get the current system update ID."""
        return self._system_update_id

    def _generate_content_aware_uuid(self):
        """
        Generate a UUID that changes when directory content changes significantly.
        This forces DLNA clients to refresh their cache when they see a 'new' device.

        The UUID includes:
        - Directory path (for basic stability)
        - File count and total size (changes when files added/removed)
        - Hash of file names (changes when files renamed/moved)
        """
        try:
            # Start with directory path for basic stability
            path_hash = hashlib.md5(
                os.path.abspath(self.media_directory).encode()
            ).hexdigest()[:8]

            # Get directory content signature
            file_count = 0
            total_size = 0
            file_names = []

            for root, dirs, files in os.walk(self.media_directory):
                # Sort for consistency
                files.sort()

                for file in files:
                    file_path = os.path.join(root, file)
                    try:
                        # Only count media files
                        mime_type, _ = mimetypes.guess_type(file_path)
                        if mime_type and (
                            mime_type.startswith("video/")
                            or mime_type.startswith("audio/")
                            or mime_type.startswith("image/")
                        ):
                            stat_info = os.stat(file_path)
                            file_count += 1
                            total_size += stat_info.st_size
                            # Use relative path for consistency
                            rel_path = os.path.relpath(file_path, self.media_directory)
                            file_names.append(rel_path)
                    except OSError:
                        continue

            # Create content signature - focus on structure, not individual file changes
            file_names.sort()  # Ensure consistent ordering
            # Use just count and size brackets to avoid changing too frequently
            size_bracket = total_size // (100 * 1024 * 1024)  # Changes every 100MB
            content_string = f"{file_count}:{size_bracket}:{hashlib.md5(':'.join(file_names).encode()).hexdigest()[:8]}"
            content_hash = hashlib.md5(content_string.encode()).hexdigest()[:8]

            # Add a time-based component that changes every few hours to force periodic refresh
            # This ensures clients get fresh content even if file structure hasn't changed much
            time_bracket = int(time.time()) // (4 * 3600)  # Changes every 4 hours
            time_hash = hashlib.md5(str(time_bracket).encode()).hexdigest()[:4]

            # Combine path, content, and time for UUID
            uuid_string = (
                f"65da942e-1984-3309-{time_hash}-{content_hash[:8]}{path_hash[8:12]}"
            )

            if self.verbose:
                print(f"Generated content-aware UUID: {uuid_string}")
                print(
                    f"Content signature: {file_count} files, {total_size//1024//1024}MB"
                )

            return uuid_string

        except Exception as e:
            if self.verbose:
                print(f"Error generating content-aware UUID: {e}")
            # Fallback to simple path-based UUID
            path_hash = hashlib.md5(
                os.path.abspath(self.media_directory).encode()
            ).hexdigest()
            return f"65da942e-1984-3309-1234-{path_hash[:12]}"


def main():
    parser = argparse.ArgumentParser(description=SERVER_DESCRIPTION)
    parser.add_argument(
        "-d",
        "--directory",
        default=os.getcwd(),
        help="Directory to serve media files from (default: current directory)",
    )
    parser.add_argument(
        "-p",
        "--port",
        type=int,
        default=8200,
        help="Port to run server on (default: 8200)",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose output",
    )

    args = parser.parse_args()

    server = ZeroConfigDLNA(
        media_directory=args.directory, port=args.port, verbose=args.verbose
    )
    server.run()


if __name__ == "__main__":
    main()
