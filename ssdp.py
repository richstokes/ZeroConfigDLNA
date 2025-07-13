"""
SSDP (Simple Service Discovery Protocol) server implementation for UPnP device discovery.

This module provides SSDP server functionality to enable DLNA/UPnP device discovery
on the network. It handles multicast M-SEARCH requests and sends NOTIFY messages
to announce the media server's presence.
"""

import socket
import threading
import time
import struct
import select

try:
    from .constants import (
        SERVER_AGENT,
    )
except ImportError:
    from constants import (
        SERVER_AGENT,
    )


class SSDPServer:
    """Simple Service Discovery Protocol server for UPnP device discovery"""

    MULTICAST_IP = "239.255.255.250"
    MULTICAST_PORT = 1900

    def __init__(self, server_instance, verbose=False):
        self.server_instance = server_instance
        self.verbose = verbose
        self.socket = None
        self.running = False
        self.thread = None
        self.notify_thread = None
        self.notify_count = 0  # Track number of NOTIFY messages sent

    def start(self):
        """Start the SSDP server"""
        try:
            # Create UDP socket
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

            # On macOS, we might need to set SO_REUSEPORT as well
            try:
                self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
            except AttributeError:
                pass  # SO_REUSEPORT not available on all systems

            # Bind to multicast address
            self.socket.bind(("", self.MULTICAST_PORT))

            # Join multicast group
            mreq = struct.pack(
                "4sl", socket.inet_aton(self.MULTICAST_IP), socket.INADDR_ANY
            )
            self.socket.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)

            self.running = True
            self.thread = threading.Thread(target=self._listen)
            self.thread.daemon = True
            self.thread.start()

            # Send initial NOTIFY messages
            time.sleep(0.5)  # Give socket time to initialize
            self._send_notify_alive()

            # Start periodic NOTIFY thread
            self.notify_thread = threading.Thread(target=self._periodic_notify)
            self.notify_thread.daemon = True
            self.notify_thread.start()

            if self.verbose:
                print("SSDP server started for UPnP discovery")
                print(f"Listening on {self.MULTICAST_IP}:{self.MULTICAST_PORT}")
            return True

        except Exception as e:
            print(f"Error starting SSDP server: {e}")
            return False

    def stop(self):
        """Stop the SSDP server"""
        if self.running:
            if self.verbose:
                print("Stopping SSDP server...")
            self._send_notify_byebye()
            self.running = False
            if self.socket:
                self.socket.close()
            if self.thread:
                self.thread.join(timeout=5)
            if self.notify_thread:
                self.notify_thread.join(timeout=5)

    def _listen(self):
        """Listen for SSDP M-SEARCH requests"""
        while self.running:
            try:
                ready = select.select([self.socket], [], [], 1.0)
                if ready[0]:
                    data, addr = self.socket.recvfrom(1024)
                    self._handle_request(data.decode("utf-8", errors="ignore"), addr)
            except Exception as e:
                if self.running:
                    if self.verbose:
                        print(f"SSDP listen error: {e}")
                break

    def _handle_request(self, data, addr):
        """Handle incoming SSDP requests"""
        lines = data.strip().split("\r\n")
        if not lines:
            return

        request_line = lines[0]
        if request_line.startswith("M-SEARCH"):
            # Parse headers
            headers = {}
            for line in lines[1:]:
                if ":" in line:
                    key, value = line.split(":", 1)
                    headers[key.strip().upper()] = value.strip()

            # Check if this is a search for our device type
            st = headers.get("ST", "").lower()
            if (
                st in ["upnp:rootdevice", "urn:schemas-upnp-org:device:mediaserver:1"]
                or st.startswith("urn:schemas-upnp-org:service:")
                or st == "ssdp:all"
                or st == f"uuid:{self.server_instance.device_uuid}".lower()
            ):
                self._send_search_response(addr, st)

    def _send_search_response(self, addr, search_target="upnp:rootdevice"):
        """Send response to M-SEARCH request"""
        location = f"http://{self.server_instance.server_ip}:{self.server_instance.port}/description.xml"
        # Determine the appropriate ST and USN based on search target
        if search_target.lower() == "upnp:rootdevice":
            st = "upnp:rootdevice"
            usn = f"uuid:{self.server_instance.device_uuid}::upnp:rootdevice"
        elif "mediaserver" in search_target.lower():
            st = "urn:schemas-upnp-org:device:MediaServer:1"
            usn = f"uuid:{self.server_instance.device_uuid}::urn:schemas-upnp-org:device:MediaServer:1"
        elif "contentdirectory" in search_target.lower():
            st = "urn:schemas-upnp-org:service:ContentDirectory:1"
            usn = f"uuid:{self.server_instance.device_uuid}::urn:schemas-upnp-org:service:ContentDirectory:1"
        elif "connectionmanager" in search_target.lower():
            st = "urn:schemas-upnp-org:service:ConnectionManager:1"
            usn = f"uuid:{self.server_instance.device_uuid}::urn:schemas-upnp-org:service:ConnectionManager:1"
        elif search_target.lower().startswith("uuid:"):
            st = f"uuid:{self.server_instance.device_uuid}"
            usn = f"uuid:{self.server_instance.device_uuid}"
        else:
            st = "upnp:rootdevice"
            usn = f"uuid:{self.server_instance.device_uuid}::upnp:rootdevice"

        # Build response using f-strings
        current_date = time.strftime("%a, %d %b %Y %H:%M:%S GMT", time.gmtime())
        response = (
            f"HTTP/1.1 200 OK\r\n"
            f"CACHE-CONTROL: max-age=1800\r\n"
            f"DATE: {current_date}\r\n"
            f"EXT:\r\n"
            f"LOCATION: {location}\r\n"
            f"SERVER: {SERVER_AGENT}\r\n"
            f"ST: {st}\r\n"
            f"USN: {usn}\r\n"
            "\r\n"
        )

        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.sendto(response.encode(), addr)
            sock.close()
        except Exception as e:
            if self.verbose:
                print(f"Error sending SSDP response: {e}")

    def _send_notify_alive(self):
        """Send NOTIFY alive messages"""
        location = f"http://{self.server_instance.server_ip}:{self.server_instance.port}/description.xml"

        messages = [
            # Root device
            (
                "NOTIFY * HTTP/1.1\r\n"
                f"HOST: {self.MULTICAST_IP}:{self.MULTICAST_PORT}\r\n"
                "CACHE-CONTROL: max-age=300\r\n"
                f"LOCATION: {location}\r\n"
                "NT: upnp:rootdevice\r\n"
                "NTS: ssdp:alive\r\n"
                f"USN: uuid:{self.server_instance.device_uuid}::upnp:rootdevice\r\n"
                f"SERVER: {SERVER_AGENT}\r\n"
                "\r\n"
            ),
            # Device UUID
            (
                "NOTIFY * HTTP/1.1\r\n"
                f"HOST: {self.MULTICAST_IP}:{self.MULTICAST_PORT}\r\n"
                "CACHE-CONTROL: max-age=300\r\n"
                f"LOCATION: {location}\r\n"
                f"NT: uuid:{self.server_instance.device_uuid}\r\n"
                "NTS: ssdp:alive\r\n"
                f"USN: uuid:{self.server_instance.device_uuid}\r\n"
                f"SERVER: {SERVER_AGENT}\r\n"
                "\r\n"
            ),
            # Media Server device type
            (
                "NOTIFY * HTTP/1.1\r\n"
                f"HOST: {self.MULTICAST_IP}:{self.MULTICAST_PORT}\r\n"
                "CACHE-CONTROL: max-age=300\r\n"
                f"LOCATION: {location}\r\n"
                "NT: urn:schemas-upnp-org:device:MediaServer:1\r\n"
                "NTS: ssdp:alive\r\n"
                f"USN: uuid:{self.server_instance.device_uuid}::urn:schemas-upnp-org:device:MediaServer:1\r\n"
                f"SERVER: {SERVER_AGENT}\r\n"
                "\r\n"
            ),
            # Content Directory service
            (
                "NOTIFY * HTTP/1.1\r\n"
                f"HOST: {self.MULTICAST_IP}:{self.MULTICAST_PORT}\r\n"
                "CACHE-CONTROL: max-age=300\r\n"
                f"LOCATION: {location}\r\n"
                "NT: urn:schemas-upnp-org:service:ContentDirectory:1\r\n"
                "NTS: ssdp:alive\r\n"
                f"USN: uuid:{self.server_instance.device_uuid}::urn:schemas-upnp-org:service:ContentDirectory:1\r\n"
                f"SERVER: {SERVER_AGENT}\r\n"
                "\r\n"
            ),
            # Connection Manager service
            (
                "NOTIFY * HTTP/1.1\r\n"
                f"HOST: {self.MULTICAST_IP}:{self.MULTICAST_PORT}\r\n"
                "CACHE-CONTROL: max-age=300\r\n"
                f"LOCATION: {location}\r\n"
                "NT: urn:schemas-upnp-org:service:ConnectionManager:1\r\n"
                "NTS: ssdp:alive\r\n"
                f"USN: uuid:{self.server_instance.device_uuid}::urn:schemas-upnp-org:service:ConnectionManager:1\r\n"
                f"SERVER: {SERVER_AGENT}\r\n"
                "\r\n"
            ),
        ]

        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            for message in messages:
                sock.sendto(message.encode(), (self.MULTICAST_IP, self.MULTICAST_PORT))
                time.sleep(0.1)  # Small delay between messages
            sock.close()

            self.notify_count += 1
            if self.verbose:
                print(f"Sent SSDP NOTIFY alive messages (#{self.notify_count})")
        except Exception as e:
            if self.verbose:
                print(f"Error sending SSDP NOTIFY: {e}")

    def _send_notify_byebye(self):
        """Send NOTIFY byebye messages when shutting down"""
        messages = [
            # Root device
            (
                "NOTIFY * HTTP/1.1\r\n"
                f"HOST: {self.MULTICAST_IP}:{self.MULTICAST_PORT}\r\n"
                "NT: upnp:rootdevice\r\n"
                "NTS: ssdp:byebye\r\n"
                f"USN: uuid:{self.server_instance.device_uuid}::upnp:rootdevice\r\n"
                "\r\n"
            ),
            # Device UUID
            (
                "NOTIFY * HTTP/1.1\r\n"
                f"HOST: {self.MULTICAST_IP}:{self.MULTICAST_PORT}\r\n"
                f"NT: uuid:{self.server_instance.device_uuid}\r\n"
                "NTS: ssdp:byebye\r\n"
                f"USN: uuid:{self.server_instance.device_uuid}\r\n"
                "\r\n"
            ),
            # Media Server device type
            (
                "NOTIFY * HTTP/1.1\r\n"
                f"HOST: {self.MULTICAST_IP}:{self.MULTICAST_PORT}\r\n"
                "NT: urn:schemas-upnp-org:device:MediaServer:1\r\n"
                "NTS: ssdp:byebye\r\n"
                f"USN: uuid:{self.server_instance.device_uuid}::urn:schemas-upnp-org:device:MediaServer:1\r\n"
                "\r\n"
            ),
        ]

        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            for message in messages:
                sock.sendto(message.encode(), (self.MULTICAST_IP, self.MULTICAST_PORT))
                time.sleep(0.1)
            sock.close()
            if self.verbose:
                print("Sent SSDP NOTIFY byebye messages")
        except Exception as e:
            if self.verbose:
                print(f"Error sending SSDP byebye: {e}")

    def _periodic_notify(self):
        """Send periodic NOTIFY alive messages with backoff"""
        while self.running:
            # First 30 messages: send every 3 seconds
            if self.notify_count < 30:
                sleep_time = 3
            else:
                # After first 30 messages: send every 60 seconds (1 minute)
                sleep_time = 60

            for _ in range(sleep_time):
                if not self.running:
                    return
                time.sleep(1)

            if self.running:
                self._send_notify_alive()
