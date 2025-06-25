"""Zero Configuration DLNA Server - A simple DLNA media server."""
import hashlib
import os
import socket
import threading
import time
from http.server import ThreadingHTTPServer
import argparse

try: # Hacky but needed to support both package and module imports
    from .constants import (
        SERVER_NAME,
        SERVER_DESCRIPTION,
        SERVER_VERSION,
        SERVER_MANUFACTURER,
        is_supported_media_file,
    )
    from .dlna import DLNAHandler
    from .ssdp import SSDPServer
except ImportError:
    from constants import (
        SERVER_NAME,
        SERVER_DESCRIPTION,
        SERVER_VERSION,
        SERVER_MANUFACTURER,
        is_supported_media_file,
    )
    from dlna import DLNAHandler
    from ssdp import SSDPServer


class ZeroConfigDLNA:
    """
    Zero Configuration DLNA Server class.

    Provides a DLNA/UPnP media server with automatic discovery.
    Serves media files from a specified directory to DLNA-compatible devices.
    """

    def __init__(
        self, media_directory=None, port=8200, verbose=False, server_name=None
    ):
        self.server_name = server_name
        self.version = SERVER_VERSION
        self.author = SERVER_MANUFACTURER
        self.description = SERVER_DESCRIPTION
        self.media_directory = media_directory or os.getcwd()
        self.port = port
        self.server = None
        self.server_thread = None
        self.verbose = verbose
        socket.setdefaulttimeout(60)  # 60 seconds timeout

        # Generate UUID based on directory content hash
        # This forces client cache refresh only when content actually changes
        self.device_uuid = self._generate_content_hash_uuid()
        self.server_ip = self.get_local_ip()
        self.running = False

        # Track directory content hash to detect changes
        self._content_hash = None
        self._last_hash_check = 0

        # Simple counter that increments on root folder access to force refresh
        self._system_update_id = (
            int(time.time()) % 1000000
        )  # Start with timestamp-based ID
        self.ssdp_server = SSDPServer(self, verbose=self.verbose)

    def find_a_port(self):
        """Find an available port starting from the specified port"""
        test_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        test_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        port = self.port
        while True:
            try:
                test_socket.bind((self.server_ip, port))
                test_socket.close()
                return port
            except OSError:
                if self.verbose:
                    print(f"Port {port} is in use, trying next port...")
                port += 1

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
        """
        Create a handler class with server instance
        """
        server_ref = self

        class Handler(DLNAHandler):  # Create a subclass of DLNAHandler
            """Custom DLNA handler with server instance reference."""

            server_instance = server_ref
            verbose = server_ref.verbose
            server_name = self.server_name

        return Handler

    def start(self):
        """Start the DLNA server"""
        try:
            print(f"{self.server_name} v{self.version} is starting...")
            print(f"Media directory: {os.path.abspath(self.media_directory)}")
            print(f"Server IP: {self.server_ip}")

            if not os.path.exists(self.media_directory):
                print(
                    f"Error: Media directory '{self.media_directory}' does not exist!"
                )
                return False

            # Find an available port starting from the specified port
            self.port = self.find_a_port()
            print(f"Port: {self.port}")

            # Count media files
            media_count = 0

            def count_media_files(directory):
                nonlocal media_count
                for item in os.listdir(directory):
                    item_path = os.path.join(directory, item)
                    if os.path.isfile(item_path):
                        if is_supported_media_file(item_path):
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
        print(f"{self.server_name} is stopping...")
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
        Also check if content has changed and update UUID if needed.
        """
        self._system_update_id += 1

        # Check if content has changed and update UUID if needed
        content_changed = self.has_content_changed()

        if self.verbose:
            print(
                f"Root folder accessed - refreshed SystemUpdateID to {self._system_update_id}"
            )
            if content_changed:
                print("Content change detected - UUID updated")

    def get_system_update_id(self):
        """Get the current system update ID."""
        return self._system_update_id

    def _get_directory_content_hash(self):
        """
        Generate a hash of all directory contents (files and subdirectories).
        This changes when files are added, removed, renamed, or modified.
        """
        try:
            content_items = []

            for root, dirs, files in os.walk(self.media_directory):
                # Sort for consistent ordering
                dirs.sort()
                files.sort()

                for file in files:
                    file_path = os.path.join(root, file)
                    try:
                        # Get relative path for portability
                        rel_path = os.path.relpath(file_path, self.media_directory)
                        stat_info = os.stat(file_path)
                        # Include path, size, and modification time
                        content_items.append(
                            f"{rel_path}:{stat_info.st_size}:{int(stat_info.st_mtime)}"
                        )
                    except OSError:
                        continue

            # Create hash from all content info
            content_string = "\n".join(content_items)
            return hashlib.md5(content_string.encode()).hexdigest()[:12]

        except Exception as e:
            if self.verbose:
                print(f"Error calculating content hash: {e}")
            # Fallback to timestamp
            return hashlib.md5(str(int(time.time())).encode()).hexdigest()[:12]

    def _generate_content_hash_uuid(self):
        """
        Generate a UUID that changes only when directory content changes.
        Much more efficient than time-based refresh.
        """
        # Directory path for basic stability
        path_hash = hashlib.md5(
            os.path.abspath(self.media_directory).encode()
        ).hexdigest()[:8]

        # Content hash that changes when files change
        content_hash = self._get_directory_content_hash()

        # Store the content hash for later comparison
        self._content_hash = content_hash

        uuid_string = (
            f"65da942e-1984-3309-{content_hash[:4]}-{content_hash[4:8]}{path_hash[:4]}"
        )

        if self.verbose:
            print(f"Generated content-hash UUID: {uuid_string}")
            print(f"Content hash: {content_hash}")

        return uuid_string

    def has_content_changed(self):
        """
        Check if directory content has changed since last check.
        Only recalculates hash every 30 seconds to avoid excessive disk I/O.
        """
        current_time = time.time()

        # Don't check too frequently to avoid performance issues
        if current_time - self._last_hash_check < 30:
            return False

        self._last_hash_check = current_time
        current_hash = self._get_directory_content_hash()

        if current_hash != self._content_hash:
            if self.verbose:
                print(f"Content changed: {self._content_hash} -> {current_hash}")
            self._content_hash = current_hash
            # Regenerate UUID with new content hash
            old_uuid = self.device_uuid
            self.device_uuid = self._generate_content_hash_uuid()
            if self.verbose:
                print(f"UUID updated: {old_uuid} -> {self.device_uuid}")
            return True

        return False


def main():
    """Main entry point for the DLNA server application."""
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
    parser.add_argument(
        "-n",
        "--server_name",
        default=SERVER_NAME,
        help="Set the DLNA server name (default: ZeroConfigDLNA_<hostname> or value from DLNA_HOSTNAME env var)",
    )

    args = parser.parse_args()

    server = ZeroConfigDLNA(
        media_directory=args.directory,
        port=args.port,
        verbose=args.verbose,
        server_name=args.server_name,
    )
    server.run()


if __name__ == "__main__":
    main()
