import os
import sys
import socket
import threading
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import unquote, urlparse
import mimetypes
import uuid
import xml.etree.ElementTree as ET
import struct
import select
import html
import traceback
import argparse

from constants import (
    SERVER_AGENT,
    SERVER_NAME,
    SERVER_DESCRIPTION,
    SERVER_VERSION,
    SERVER_MANUFACTURER,
)
from ssdp import SSDPServer


class DLNAHandler(BaseHTTPRequestHandler):
    def __init__(self, server_instance, *args, **kwargs):
        self.server_instance = server_instance
        super().__init__(*args, **kwargs)

    def do_GET(self):
        """Handle GET requests for media files and DLNA control"""
        parsed_path = urlparse(self.path)
        path = unquote(parsed_path.path)

        print(f"GET request: {self.path} -> {path}")
        print(f"Headers: {dict(self.headers)}")

        if path == "/description.xml":
            self.send_device_description()
        elif path == "/cd_scpd.xml":
            self.send_scpd_xml("ContentDirectory")
        elif path == "/cm_scpd.xml":
            self.send_scpd_xml("ConnectionManager")
        elif path == "/browse":
            self.send_browse_response()
        elif path.startswith("/media/"):
            print(f"Media request: {path[7:]}")
            print(f"Client: {self.client_address}")
            print(f"User-Agent: {self.headers.get('User-Agent', 'Unknown')}")
            print(f"Range: {self.headers.get('Range', 'None')}")
            self.serve_media_file(path[7:])  # Remove '/media/' prefix
        else:
            self.send_error(404, "File not found")

    def do_HEAD(self):
        """Handle HEAD requests for media files (for DLNA compatibility)"""
        parsed_path = urlparse(self.path)
        path = unquote(parsed_path.path)

        if path.startswith("/media/"):
            self.serve_media_file(path[7:], head_only=True)  # Remove '/media/' prefix
        else:
            self.send_error(404, "File not found")

    def do_POST(self):
        """Handle SOAP requests for DLNA control"""
        if self.path == "/control":
            content_length = int(self.headers.get("Content-Length", 0))
            post_data = self.rfile.read(content_length)
            soap_action = self.headers.get("SOAPAction", "").strip('"')
            self.handle_soap_request(post_data, soap_action)
        else:
            self.send_error(404, "Not found")

    def do_SUBSCRIBE(self):
        """Handle UPnP event subscription requests"""
        if self.path == "/events":
            self.handle_subscribe_request()
        else:
            self.send_error(404, "Not found")

    def do_UNSUBSCRIBE(self):
        """Handle UPnP event unsubscription requests"""
        if self.path == "/events":
            self.handle_unsubscribe_request()
        else:
            self.send_error(404, "Not found")

    def do_OPTIONS(self):
        """Handle OPTIONS requests for CORS"""
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header(
            "Access-Control-Allow-Methods", "GET, POST, OPTIONS, SUBSCRIBE, UNSUBSCRIBE"
        )
        self.send_header(
            "Access-Control-Allow-Headers",
            "Content-Type, SOAPAction, CALLBACK, NT, TIMEOUT, SID",
        )
        self.send_header("Content-Length", "0")
        self.end_headers()

    def send_device_description(self):
        """Send UPnP device description XML"""
        device_xml = f"""<?xml version="1.0" encoding="utf-8"?>
<root xmlns="urn:schemas-upnp-org:device-1-0" xmlns:dlna="urn:schemas-dlna-org:device-1-0">
    <specVersion>
        <major>1</major>
        <minor>0</minor>
    </specVersion>
    <device>
        <deviceType>urn:schemas-upnp-org:device:MediaServer:1</deviceType>
        <friendlyName>{SERVER_NAME}</friendlyName>
        <manufacturer>{SERVER_MANUFACTURER}</manufacturer>
        <manufacturerURL>https://github.com/richstokes/ZeroConfigDLNA</manufacturerURL>
        <modelDescription>DLNA/UPnP Media Server with Sony BRAVIA compatibility</modelDescription>
        <modelName>{SERVER_NAME}</modelName>
        <modelNumber>{SERVER_VERSION}</modelNumber>
        <modelURL>https://github.com/richstokes/ZeroConfigDLNA</modelURL>
        <serialNumber>12345678</serialNumber>
        <UDN>uuid:{self.server_instance.device_uuid}</UDN>
        <dlna:X_DLNADOC xmlns:dlna="urn:schemas-dlna-org:device-1-0">DMS-1.50</dlna:X_DLNADOC>
        <serviceList>
            <service>
                <serviceType>urn:schemas-upnp-org:service:ContentDirectory:1</serviceType>
                <serviceId>urn:upnp-org:serviceId:ContentDirectory</serviceId>
                <controlURL>/control</controlURL>
                <eventSubURL>/events</eventSubURL>
                <SCPDURL>/cd_scpd.xml</SCPDURL>
            </service>
            <service>
                <serviceType>urn:schemas-upnp-org:service:ConnectionManager:1</serviceType>
                <serviceId>urn:upnp-org:serviceId:ConnectionManager</serviceId>
                <controlURL>/control</controlURL>
                <eventSubURL>/events</eventSubURL>
                <SCPDURL>/cm_scpd.xml</SCPDURL>
            </service>
        </serviceList>
        <presentationURL>http://{self.server_instance.server_ip}:{self.server_instance.port}/</presentationURL>
    </device>
</root>"""

        self.send_response(200)
        self.send_header("Content-Type", "text/xml; charset=utf-8")
        self.send_header("Content-Length", str(len(device_xml)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, SOAPAction")
        self.send_header("Server", SERVER_AGENT)
        self.end_headers()
        self.wfile.write(device_xml.encode())

    def send_scpd_xml(self, service_type):
        """Send Service Control Point Definition XML for the specified service type."""
        scpd_xml = ""
        if service_type == "ContentDirectory":
            # Basic SCPD for ContentDirectory - this should be expanded based on actual implemented actions
            scpd_xml = f"""<?xml version="1.0" encoding="utf-8"?>
<scpd xmlns="urn:schemas-upnp-org:service-1-0">
    <specVersion>
        <major>1</major>
        <minor>0</minor>
    </specVersion>
    <actionList>
        <action>
            <name>Browse</name>
            <argumentList>
                <argument>
                    <name>ObjectID</name>
                    <direction>in</direction>
                    <relatedStateVariable>A_ARG_TYPE_ObjectID</relatedStateVariable>
                </argument>
                <argument>
                    <name>BrowseFlag</name>
                    <direction>in</direction>
                    <relatedStateVariable>A_ARG_TYPE_BrowseFlag</relatedStateVariable>
                </argument>
                <argument>
                    <name>Filter</name>
                    <direction>in</direction>
                    <relatedStateVariable>A_ARG_TYPE_Filter</relatedStateVariable>
                </argument>
                <argument>
                    <name>StartingIndex</name>
                    <direction>in</direction>
                    <relatedStateVariable>A_ARG_TYPE_Index</relatedStateVariable>
                </argument>
                <argument>
                    <name>RequestedCount</name>
                    <direction>in</direction>
                    <relatedStateVariable>A_ARG_TYPE_Count</relatedStateVariable>
                </argument>
                <argument>
                    <name>SortCriteria</name>
                    <direction>in</direction>
                    <relatedStateVariable>A_ARG_TYPE_SortCriteria</relatedStateVariable>
                </argument>
                <argument>
                    <name>Result</name>
                    <direction>out</direction>
                    <relatedStateVariable>A_ARG_TYPE_Result</relatedStateVariable>
                </argument>
                <argument>
                    <name>NumberReturned</name>
                    <direction>out</direction>
                    <relatedStateVariable>A_ARG_TYPE_Count</relatedStateVariable>
                </argument>
                <argument>
                    <name>TotalMatches</name>
                    <direction>out</direction>
                    <relatedStateVariable>A_ARG_TYPE_Count</relatedStateVariable>
                </argument>
                <argument>
                    <name>UpdateID</name>
                    <direction>out</direction>
                    <relatedStateVariable>A_ARG_TYPE_UpdateID</relatedStateVariable>
                </argument>
            </argumentList>
        </action>
        <action>
            <name>GetSearchCapabilities</name>
            <argumentList>
                <argument>
                    <name>SearchCaps</name>
                    <direction>out</direction>
                    <relatedStateVariable>SearchCapabilities</relatedStateVariable>
                </argument>
            </argumentList>
        </action>
        <action>
            <name>GetSortCapabilities</name>
            <argumentList>
                <argument>
                    <name>SortCaps</name>
                    <direction>out</direction>
                    <relatedStateVariable>SortCapabilities</relatedStateVariable>
                </argument>
            </argumentList>
        </action>
        <action>
            <name>GetSystemUpdateID</name>
            <argumentList>
                <argument>
                    <name>Id</name>
                    <direction>out</direction>
                    <relatedStateVariable>SystemUpdateID</relatedStateVariable>
                </argument>
            </argumentList>
        </action>
    </actionList>
    <serviceStateTable>
        <stateVariable sendEvents="no">
            <name>A_ARG_TYPE_ObjectID</name>
            <dataType>string</dataType>
        </stateVariable>
        <stateVariable sendEvents="no">
            <name>A_ARG_TYPE_BrowseFlag</name>
            <dataType>string</dataType>
            <allowedValueList>
                <allowedValue>BrowseMetadata</allowedValue>
                <allowedValue>BrowseDirectChildren</allowedValue>
            </allowedValueList>
        </stateVariable>
        <stateVariable sendEvents="no">
            <name>A_ARG_TYPE_Filter</name>
            <dataType>string</dataType>
        </stateVariable>
        <stateVariable sendEvents="no">
            <name>A_ARG_TYPE_Index</name>
            <dataType>ui4</dataType>
        </stateVariable>
        <stateVariable sendEvents="no">
            <name>A_ARG_TYPE_Count</name>
            <dataType>ui4</dataType>
        </stateVariable>
        <stateVariable sendEvents="no">
            <name>A_ARG_TYPE_SortCriteria</name>
            <dataType>string</dataType>
        </stateVariable>
        <stateVariable sendEvents="no">
            <name>A_ARG_TYPE_Result</name>
            <dataType>string</dataType>
        </stateVariable>
        <stateVariable sendEvents="no">
            <name>SearchCapabilities</name>
            <dataType>string</dataType>
        </stateVariable>
        <stateVariable sendEvents="no">
            <name>SortCapabilities</name>
            <dataType>string</dataType>
        </stateVariable>
        <stateVariable sendEvents="yes">
            <name>SystemUpdateID</name>
            <dataType>ui4</dataType>
        </stateVariable>
        <stateVariable sendEvents="yes">
            <name>ContainerUpdateIDs</name>
            <dataType>string</dataType>
        </stateVariable>
    </serviceStateTable>
</scpd>"""
        elif service_type == "ConnectionManager":
            scpd_xml = f"""<?xml version="1.0" encoding="utf-8"?>
<scpd xmlns="urn:schemas-upnp-org:service-1-0">
    <specVersion>
        <major>1</major>
        <minor>0</minor>
    </specVersion>
    <actionList>
        <action>
            <name>GetProtocolInfo</name>
            <argumentList>
                <argument>
                    <name>Source</name>
                    <direction>out</direction>
                    <relatedStateVariable>SourceProtocolInfo</relatedStateVariable>
                </argument>
                <argument>
                    <name>Sink</name>
                    <direction>out</direction>
                    <relatedStateVariable>SinkProtocolInfo</relatedStateVariable>
                </argument>
            </argumentList>
        </action>
        <action>
            <name>GetCurrentConnectionIDs</name>
            <argumentList>
                <argument>
                    <name>ConnectionIDs</name>
                    <direction>out</direction>
                    <relatedStateVariable>CurrentConnectionIDs</relatedStateVariable>
                </argument>
            </argumentList>
        </action>
        <action>
            <name>GetCurrentConnectionInfo</name>
            <argumentList>
                <argument>
                    <name>ConnectionID</name>
                    <direction>in</direction>
                    <relatedStateVariable>A_ARG_TYPE_ConnectionID</relatedStateVariable>
                </argument>
                <argument>
                    <name>RcsID</name>
                    <direction>out</direction>
                    <relatedStateVariable>A_ARG_TYPE_RcsID</relatedStateVariable>
                </argument>
                <argument>
                    <name>AVTransportID</name>
                    <direction>out</direction>
                    <relatedStateVariable>A_ARG_TYPE_AVTransportID</relatedStateVariable>
                </argument>
                <argument>
                    <name>ProtocolInfo</name>
                    <direction>out</direction>
                    <relatedStateVariable>A_ARG_TYPE_ProtocolInfo</relatedStateVariable>
                </argument>
                <argument>
                    <name>PeerConnectionManager</name>
                    <direction>out</direction>
                    <relatedStateVariable>A_ARG_TYPE_ConnectionManager</relatedStateVariable>
                </argument>
                <argument>
                    <name>PeerConnectionID</name>
                    <direction>out</direction>
                    <relatedStateVariable>A_ARG_TYPE_ConnectionID</relatedStateVariable>
                </argument>
                <argument>
                    <name>Direction</name>
                    <direction>out</direction>
                    <relatedStateVariable>A_ARG_TYPE_Direction</relatedStateVariable>
                </argument>
                <argument>
                    <name>Status</name>
                    <direction>out</direction>
                    <relatedStateVariable>A_ARG_TYPE_ConnectionStatus</relatedStateVariable>
                </argument>
            </argumentList>
        </action>
    </actionList>
    <serviceStateTable>
        <stateVariable sendEvents="no">
            <name>SourceProtocolInfo</name>
            <dataType>string</dataType>
        </stateVariable>
        <stateVariable sendEvents="no">
            <name>SinkProtocolInfo</name>
            <dataType>string</dataType>
        </stateVariable>
        <stateVariable sendEvents="yes">
            <name>CurrentConnectionIDs</name>
            <dataType>string</dataType>
        </stateVariable>
        <stateVariable sendEvents="no">
            <name>A_ARG_TYPE_ConnectionID</name>
            <dataType>i4</dataType>
        </stateVariable>
        <stateVariable sendEvents="no">
            <name>A_ARG_TYPE_RcsID</name>
            <dataType>i4</dataType>
        </stateVariable>
        <stateVariable sendEvents="no">
            <name>A_ARG_TYPE_AVTransportID</name>
            <dataType>i4</dataType>
        </stateVariable>
        <stateVariable sendEvents="no">
            <name>A_ARG_TYPE_ProtocolInfo</name>
            <dataType>string</dataType>
        </stateVariable>
        <stateVariable sendEvents="no">
            <name>A_ARG_TYPE_ConnectionManager</name>
            <dataType>string</dataType>
        </stateVariable>
        <stateVariable sendEvents="no">
            <name>A_ARG_TYPE_Direction</name>
            <dataType>string</dataType>
            <allowedValueList>
                <allowedValue>Input</allowedValue>
                <allowedValue>Output</allowedValue>
            </allowedValueList>
        </stateVariable>
        <stateVariable sendEvents="no">
            <name>A_ARG_TYPE_ConnectionStatus</name>
            <dataType>string</dataType>
            <allowedValueList>
                <allowedValue>OK</allowedValue>
                <allowedValue>ContentFormatMismatch</allowedValue>
                <allowedValue>InsufficientBandwidth</allowedValue>
                <allowedValue>UnreliableChannel</allowedValue>
                <allowedValue>Unknown</allowedValue>
            </allowedValueList>
        </stateVariable>
    </serviceStateTable>
</scpd>"""
        else:
            self.send_error(404, "SCPD Not Found")
            return

        self.send_response(200)
        self.send_header("Content-Type", "text/xml; charset=utf-8")
        self.send_header("Content-Length", str(len(scpd_xml)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Server", SERVER_AGENT)
        self.end_headers()
        self.wfile.write(scpd_xml.encode())

    def send_browse_response(self):
        """Send a simple directory listing"""
        try:
            files = os.listdir(self.server_instance.media_directory)
            media_files = []

            for file in files:
                file_path = os.path.join(self.server_instance.media_directory, file)
                if os.path.isfile(file_path):
                    mime_type, _ = mimetypes.guess_type(file)
                    if mime_type and (
                        mime_type.startswith("video/")
                        or mime_type.startswith("audio/")
                        or mime_type.startswith("image/")
                    ):
                        media_files.append(
                            {
                                "name": file,
                                "url": f"http://{self.server_instance.server_ip}:{self.server_instance.port}/media/{file}",
                                "mime_type": mime_type,
                                "size": os.path.getsize(file_path),
                            }
                        )

            # Simple HTML response for browser testing
            html = f"""<!DOCTYPE html>
<html>
<head>
    <title>{SERVER_DESCRIPTION}</title>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 40px; }}
        .file-list {{ list-style-type: none; padding: 0; }}
        .file-item {{ margin: 10px 0; padding: 10px; border: 1px solid #ddd; border-radius: 5px; }}
        .file-name {{ font-weight: bold; }}
        .file-info {{ color: #666; font-size: 0.9em; }}
    </style>
</head>
<body>
    <h1>{SERVER_DESCRIPTION}</h1>
    <p>Serving {len(media_files)} media files from: {self.server_instance.media_directory}</p>
    <ul class="file-list">"""

            for file in media_files:
                html += f"""
        <li class="file-item">
            <div class="file-name">
                <a href="{file['url']}" target="_blank">{file['name']}</a>
            </div>
            <div class="file-info">
                Type: {file['mime_type']} | Size: {file['size']:,} bytes
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

    def serve_media_file(self, filename, head_only=False):
        """Serve a media file"""
        try:
            # URL decode the filename
            from urllib.parse import unquote

            decoded_filename = unquote(filename)
            file_path = os.path.join(
                self.server_instance.media_directory, decoded_filename
            )

            if not os.path.exists(file_path) or not os.path.isfile(file_path):
                self.send_error(404, "File not found")
                return

            # Security check: ensure file is within media directory
            real_path = os.path.realpath(file_path)
            real_media_dir = os.path.realpath(self.server_instance.media_directory)
            if not real_path.startswith(real_media_dir):
                self.send_error(403, "Access denied")
                return

            mime_type, _ = mimetypes.guess_type(file_path)
            if not mime_type:
                mime_type = "application/octet-stream"

            file_size = os.path.getsize(file_path)

            print(
                f"Serving file: {decoded_filename} (size: {file_size}, type: {mime_type}, head_only: {head_only})"
            )

            # Handle range requests for video streaming
            range_header = self.headers.get("Range")
            if range_header and not head_only:
                self.handle_range_request(file_path, file_size, mime_type, range_header)
            else:
                self.send_response(200)
                self.send_header("Content-Type", mime_type)
                self.send_header("Content-Length", str(file_size))
                self.send_header("Accept-Ranges", "bytes")
                # Add DLNA headers for better Sony TV compatibility
                if mime_type.startswith("video/"):
                    if mime_type == "video/x-msvideo":
                        self.send_header(
                            "contentFeatures.dlna.org",
                            "DLNA.ORG_OP=01;DLNA.ORG_FLAGS=01700000000000000000000000000000",
                        )
                    elif mime_type == "video/mp4":
                        self.send_header(
                            "contentFeatures.dlna.org",
                            "DLNA.ORG_PN=MP4_SD_AAC_LTP;DLNA.ORG_OP=01;DLNA.ORG_FLAGS=01700000000000000000000000000000",
                        )
                    else:
                        self.send_header(
                            "contentFeatures.dlna.org",
                            "DLNA.ORG_OP=01;DLNA.ORG_FLAGS=01700000000000000000000000000000",
                        )
                elif mime_type.startswith("audio/"):
                    if mime_type == "audio/mpeg":
                        self.send_header(
                            "contentFeatures.dlna.org",
                            "DLNA.ORG_PN=MP3;DLNA.ORG_OP=01;DLNA.ORG_FLAGS=01700000000000000000000000000000",
                        )
                    else:
                        self.send_header(
                            "contentFeatures.dlna.org",
                            "DLNA.ORG_OP=01;DLNA.ORG_FLAGS=01700000000000000000000000000000",
                        )
                else:
                    self.send_header(
                        "contentFeatures.dlna.org",
                        "DLNA.ORG_OP=01;DLNA.ORG_FLAGS=00D00000000000000000000000000000",
                    )
                self.send_header("transferMode.dlna.org", "Streaming")
                # Add server identification and additional compatibility headers
                self.send_header("Server", SERVER_AGENT)
                # Add connection close to prevent hanging connections
                self.send_header("Connection", "close")
                self.end_headers()

                # Only send file content for GET requests, not HEAD
                if not head_only:
                    with open(file_path, "rb") as f:
                        self.wfile.write(f.read())

        except Exception as e:
            print(f"Error serving file {filename}: {str(e)}")
            self.send_error(500, f"Error serving file: {str(e)}")

    def handle_range_request(self, file_path, file_size, mime_type, range_header):
        """Handle HTTP range requests for streaming"""
        try:
            range_match = range_header.replace("bytes=", "").split("-")
            start = int(range_match[0]) if range_match[0] else 0
            end = int(range_match[1]) if range_match[1] else file_size - 1

            content_length = end - start + 1

            self.send_response(206)
            self.send_header("Content-Type", mime_type)
            self.send_header("Content-Length", str(content_length))
            self.send_header("Content-Range", f"bytes {start}-{end}/{file_size}")
            self.send_header("Accept-Ranges", "bytes")
            # Add DLNA headers for better Sony TV compatibility
            if mime_type.startswith("video/"):
                if mime_type == "video/x-msvideo":
                    self.send_header(
                        "contentFeatures.dlna.org",
                        "DLNA.ORG_OP=01;DLNA.ORG_FLAGS=01700000000000000000000000000000",
                    )
                elif mime_type == "video/mp4":
                    self.send_header(
                        "contentFeatures.dlna.org",
                        "DLNA.ORG_PN=MP4_SD_AAC_LTP;DLNA.ORG_OP=01;DLNA.ORG_FLAGS=01700000000000000000000000000000",
                    )
                else:
                    self.send_header(
                        "contentFeatures.dlna.org",
                        "DLNA.ORG_OP=01;DLNA.ORG_FLAGS=01700000000000000000000000000000",
                    )
            elif mime_type.startswith("audio/"):
                if mime_type == "audio/mpeg":
                    self.send_header(
                        "contentFeatures.dlna.org",
                        "DLNA.ORG_PN=MP3;DLNA.ORG_OP=01;DLNA.ORG_FLAGS=01700000000000000000000000000000",
                    )
                else:
                    self.send_header(
                        "contentFeatures.dlna.org",
                        "DLNA.ORG_OP=01;DLNA.ORG_FLAGS=01700000000000000000000000000000",
                    )
            else:
                self.send_header(
                    "contentFeatures.dlna.org",
                    "DLNA.ORG_OP=01;DLNA.ORG_FLAGS=00D00000000000000000000000000000",
                )
            self.send_header("transferMode.dlna.org", "Streaming")
            self.send_header("Server", SERVER_AGENT)
            self.send_header("Connection", "close")
            self.end_headers()

            with open(file_path, "rb") as f:
                f.seek(start)
                remaining = content_length
                while remaining > 0:
                    chunk_size = min(8192, remaining)
                    chunk = f.read(chunk_size)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)

        except Exception as e:
            self.send_error(500, f"Error handling range request: {str(e)}")

    def handle_soap_request(self, post_data, soap_action=""):
        """Handle SOAP requests for DLNA control"""
        try:
            soap_data = post_data.decode("utf-8")
            print(f"SOAP Action: {soap_action}")
            print(f"SOAP Data: {soap_data[:500]}...")  # First 500 chars for debugging
            print(f"SOAP Headers: {self.headers}")

            # Determine which service is being addressed
            service_type = None
            if "ContentDirectory" in soap_action:
                service_type = "ContentDirectory"
                print("ContentDirectory service action detected")
            elif "ConnectionManager" in soap_action:
                service_type = "ConnectionManager"
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

    def handle_browse_request(self, soap_data):
        """Handle ContentDirectory Browse requests"""
        try:
            print(f"Browse request: {soap_data}")

            # Parse SOAP parameters using simple string parsing
            object_id = "0"  # Default to root
            browse_flag = "BrowseDirectChildren"  # Default

            # Extract ObjectID from SOAP
            if "<ObjectID>" in soap_data:
                start = soap_data.find("<ObjectID>") + len("<ObjectID>")
                end = soap_data.find("</ObjectID>", start)
                if end > start:
                    object_id = soap_data[start:end]

            # Extract BrowseFlag from SOAP
            if "<BrowseFlag>" in soap_data:
                start = soap_data.find("<BrowseFlag>") + len("<BrowseFlag>")
                end = soap_data.find("</BrowseFlag>", start)
                if end > start:
                    browse_flag = soap_data[start:end]

            # Extract StartingIndex and RequestedCount from SOAP
            starting_index = 0
            requested_count = None
            if "<StartingIndex>" in soap_data:
                start = soap_data.find("<StartingIndex>") + len("<StartingIndex>")
                end = soap_data.find("</StartingIndex>", start)
                if end > start:
                    try:
                        starting_index = int(soap_data[start:end])
                    except Exception:
                        starting_index = 0
            if "<RequestedCount>" in soap_data:
                start = soap_data.find("<RequestedCount>") + len("<RequestedCount>")
                end = soap_data.find("</RequestedCount>", start)
                if end > start:
                    try:
                        requested_count = int(soap_data[start:end])
                    except Exception:
                        requested_count = None

            print(f"Browse ObjectID: {object_id}, BrowseFlag: {browse_flag}")
            print(f"StartingIndex: {starting_index}, RequestedCount: {requested_count}")

            # Generate DIDL-Lite XML for media files
            didl_items = []

            if object_id == "0" and browse_flag == "BrowseDirectChildren":
                # Root: return a single container ("All Media")
                didl_items.append(
                    '<container id="1" parentID="0" restricted="1" searchable="1" childCount="{child_count}">\n'
                    "    <dc:title>All Media</dc:title>\n"
                    "    <upnp:class>object.container.storageFolder</upnp:class>\n"
                    "    <upnp:writeStatus>NOT_WRITABLE</upnp:writeStatus>\n"
                    "</container>".format(child_count=self._count_media_files())
                )
                number_returned = 1
                total_matches = 1
            elif object_id == "1" and browse_flag == "BrowseDirectChildren":
                # "All Media" container: return all media items, honor StartingIndex/RequestedCount
                files = os.listdir(self.server_instance.media_directory)
                media_files = []
                print(f"Scanning directory: {self.server_instance.media_directory}")
                print(f"Found {len(files)} total files")

                for file in files:
                    file_path = os.path.join(self.server_instance.media_directory, file)
                    if os.path.isfile(file_path):
                        mime_type, _ = mimetypes.guess_type(file)
                        print(f"File: {file}, MIME: {mime_type}")
                        if mime_type and (
                            mime_type.startswith("video/")
                            or mime_type.startswith("audio/")
                            or mime_type.startswith("image/")
                        ):
                            media_files.append(file)
                            print(f"Added to media files: {file}")

                total_matches = len(media_files)
                print(f"Total media files found: {total_matches}")

                # Apply StartingIndex/RequestedCount
                if requested_count is not None and requested_count > 0:
                    media_files_slice = media_files[
                        starting_index : starting_index + requested_count
                    ]
                else:
                    media_files_slice = media_files[starting_index:]
                number_returned = len(media_files_slice)
                print(
                    f"Returning {number_returned} media files (slice from {starting_index})"
                )

                item_id = 2
                for file in media_files_slice:
                    file_path = os.path.join(self.server_instance.media_directory, file)
                    file_size = os.path.getsize(file_path)
                    from urllib.parse import quote

                    encoded_filename = quote(file, safe="")
                    file_url = f"http://{self.server_instance.server_ip}:{self.server_instance.port}/media/{encoded_filename}"
                    mime_type, _ = mimetypes.guess_type(file)

                    print(f"Processing item {item_id}: {file} ({mime_type})")

                    # Default values
                    dlna_profile = "DLNA.ORG_OP=01;DLNA.ORG_FLAGS=01700000000000000000000000000000"  # Generic
                    res_attrs = f'size="{file_size}"'
                    dc_date = "2024-01-01T00:00:00"  # Placeholder date
                    upnp_class = "object.item.videoItem"  # Default to video

                    if mime_type and mime_type.startswith("video/"):
                        if mime_type == "video/mp4":
                            dlna_profile = "DLNA.ORG_PN=AVC_MP4_MP_SD_AAC_MULT5;DLNA.ORG_OP=01;DLNA.ORG_FLAGS=01700000000000000000000000000000"
                            res_attrs = f'size="{file_size}" duration="01:30:00" resolution="1280x720" bitrate="4000000"'
                        elif mime_type == "video/x-msvideo":  # AVI
                            dlna_profile = "DLNA.ORG_PN=AVI;DLNA.ORG_OP=01;DLNA.ORG_FLAGS=01700000000000000000000000000000"
                            res_attrs = f'size="{file_size}" duration="00:45:00" resolution="720x576" bitrate="1500000"'
                        elif mime_type == "video/x-matroska" or file.lower().endswith(
                            ".mkv"
                        ):  # MKV
                            dlna_profile = "DLNA.ORG_PN=MATROSKA;DLNA.ORG_OP=01;DLNA.ORG_FLAGS=01700000000000000000000000000000"
                            res_attrs = f'size="{file_size}" duration="02:00:00" resolution="1920x1080" bitrate="8000000"'

                        escaped_title = html.escape(file)
                        protocol_info = f"http-get:*:{mime_type}:{dlna_profile}"
                        didl_item = (
                            f'<item id="{item_id}" parentID="1" restricted="1">\n'
                            f"    <dc:title>{escaped_title}</dc:title>\n"
                            f"    <upnp:class>{upnp_class}</upnp:class>\n"
                            f"    <dc:creator>Unknown Creator</dc:creator>\n"
                            f"    <upnp:artist>Unknown Artist</upnp:artist>\n"
                            f"    <upnp:genre>Video</upnp:genre>\n"
                            f"    <dc:description>Video File: {escaped_title}</dc:description>\n"
                            f'    <res protocolInfo="{protocol_info}" {res_attrs}>{file_url}</res>\n'
                            f"</item>"
                        )
                        didl_items.append(didl_item)
                        print(f"Added video item: {escaped_title}")

                    elif mime_type and mime_type.startswith("audio/"):
                        upnp_class = "object.item.audioItem.musicTrack"
                        if mime_type == "audio/mpeg":  # MP3
                            dlna_profile = "DLNA.ORG_PN=MP3;DLNA.ORG_OP=01;DLNA.ORG_FLAGS=01700000000000000000000000000000"
                            res_attrs = f'size="{file_size}" duration="00:03:30" bitrate="320000"'
                        elif mime_type == "audio/wav":
                            dlna_profile = "DLNA.ORG_PN=LPCM;DLNA.ORG_OP=01;DLNA.ORG_FLAGS=01700000000000000000000000000000"
                            res_attrs = f'size="{file_size}" duration="00:05:00" bitrate="1411200"'

                        escaped_title = html.escape(file)
                        protocol_info = f"http-get:*:{mime_type}:{dlna_profile}"
                        didl_item = (
                            f'<item id="{item_id}" parentID="1" restricted="1">\n'
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
                        didl_items.append(didl_item)
                        print(f"Added audio item: {escaped_title}")

                    elif mime_type and mime_type.startswith("image/"):
                        upnp_class = "object.item.imageItem.photo"
                        if mime_type == "image/jpeg":
                            dlna_profile = "DLNA.ORG_PN=JPEG_LRG;DLNA.ORG_OP=01;DLNA.ORG_FLAGS=00D00000000000000000000000000000"
                            res_attrs = f'size="{file_size}" resolution="1920x1080"'
                        elif mime_type == "image/png":
                            dlna_profile = "DLNA.ORG_PN=PNG_LRG;DLNA.ORG_OP=01;DLNA.ORG_FLAGS=00D00000000000000000000000000000"
                            res_attrs = f'size="{file_size}" resolution="1920x1080"'

                        escaped_title = html.escape(file)
                        protocol_info = f"http-get:*:{mime_type}:{dlna_profile}"
                        didl_item = (
                            f'<item id="{item_id}" parentID="1" restricted="1">\n'
                            f"    <dc:title>{escaped_title}</dc:title>\n"
                            f"    <upnp:class>{upnp_class}</upnp:class>\n"
                            f"    <dc:creator>Unknown Creator</dc:creator>\n"
                            f"    <upnp:genre>Photo</upnp:genre>\n"
                            f"    <dc:date>{dc_date}</dc:date>\n"
                            f'    <res protocolInfo="{protocol_info}" {res_attrs}>{file_url}</res>\n'
                            f"</item>"
                        )
                        didl_items.append(didl_item)
                        print(f"Added image item: {escaped_title}")
                    else:
                        print(f"Skipping unsupported file type: {file} ({mime_type})")

                    item_id += 1

            elif object_id == "0" and browse_flag == "BrowseMetadata":
                # Root container metadata
                didl_items.append(
                    '<container id="0" parentID="-1" restricted="1" searchable="1" childCount="1">\n'
                    "    <dc:title>EZDLNA Media Server</dc:title>\n"
                    "    <upnp:class>object.container</upnp:class>\n"
                    "    <upnp:writeStatus>NOT_WRITABLE</upnp:writeStatus>\n"
                    "</container>"
                )
                number_returned = 1
                total_matches = 1
                print("Returning root container metadata")

            elif object_id == "1" and browse_flag == "BrowseMetadata":
                # "All Media" container metadata
                didl_items.append(
                    '<container id="1" parentID="0" restricted="1" searchable="1" childCount="{child_count}">\n'
                    "    <dc:title>All Media</dc:title>\n"
                    "    <upnp:class>object.container.storageFolder</upnp:class>\n"
                    "    <upnp:writeStatus>NOT_WRITABLE</upnp:writeStatus>\n"
                    "</container>".format(child_count=self._count_media_files())
                )
                number_returned = 1
                total_matches = 1
                print("Returning 'All Media' container metadata")
            else:
                # Unknown object ID
                print(f"Unknown ObjectID: {object_id} with BrowseFlag: {browse_flag}")
                # Return empty result for unknown object
                number_returned = 0
                total_matches = 0

            didl_lite = f"""<DIDL-Lite xmlns="urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:upnp="urn:schemas-upnp-org:metadata-1-0/upnp/" xmlns:dlna="urn:schemas-dlna-org:metadata-1-0/">\n{''.join(didl_items)}\n</DIDL-Lite>"""

            print(f"Browse response - NumberReturned: {number_returned}")
            print(f"DIDL-Lite XML: {didl_lite}")

            # Construct SOAP response
            response = f"""<?xml version="1.0" encoding="utf-8"?>
<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" s:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">
    <s:Body>
        <u:BrowseResponse xmlns:u="urn:schemas-upnp-org:service:ContentDirectory:1">
            <Result>{html.escape(didl_lite)}</Result>
            <NumberReturned>{number_returned}</NumberReturned>
            <TotalMatches>{total_matches}</TotalMatches>
            <UpdateID>1</UpdateID>
        </u:BrowseResponse>
    </s:Body>
</s:Envelope>"""

            self.send_response(200)
            self.send_header("Content-Type", 'text/xml; charset="utf-8"')
            self.send_header("Content-Length", str(len(response)))
            self.send_header("Ext", "")
            self.send_header(f"Server", SERVER_AGENT)
            self.end_headers()
            self.wfile.write(response.encode())

        except Exception as e:
            print(f"Error in handle_browse_request: {e}")
            traceback.print_exc()
            self.send_error(500, f"Internal server error: {str(e)}")

    def handle_get_protocol_info(self):
        """Handle ConnectionManager GetProtocolInfo requests"""
        print("Handling GetProtocolInfo request")
        # Enhanced protocol info with more DLNA profiles for Sony BRAVIA compatibility
        protocols = [
            # Video formats
            "http-get:*:video/x-msvideo:DLNA.ORG_PN=AVI;DLNA.ORG_OP=01;DLNA.ORG_FLAGS=01700000000000000000000000000000",
            "http-get:*:video/mp4:DLNA.ORG_PN=AVC_MP4_MP_SD_AAC_MULT5;DLNA.ORG_OP=01;DLNA.ORG_FLAGS=01700000000000000000000000000000",
            "http-get:*:video/mp4:DLNA.ORG_PN=MP4_SD_AAC_LTP;DLNA.ORG_OP=01;DLNA.ORG_FLAGS=01700000000000000000000000000000",
            "http-get:*:video/mpeg:DLNA.ORG_PN=MPEG_PS_NTSC;DLNA.ORG_OP=01;DLNA.ORG_FLAGS=01700000000000000000000000000000",
            "http-get:*:video/mpeg:DLNA.ORG_PN=MPEG_PS_PAL;DLNA.ORG_OP=01;DLNA.ORG_FLAGS=01700000000000000000000000000000",
            "http-get:*:video/x-matroska:DLNA.ORG_PN=MATROSKA;DLNA.ORG_OP=01;DLNA.ORG_FLAGS=01700000000000000000000000000000",
            "http-get:*:video/mkv:DLNA.ORG_PN=MATROSKA;DLNA.ORG_OP=01;DLNA.ORG_FLAGS=01700000000000000000000000000000",
            "http-get:*:video/x-ms-wmv:DLNA.ORG_PN=WMVHIGH_FULL;DLNA.ORG_OP=01;DLNA.ORG_FLAGS=01700000000000000000000000000000",
            # Audio formats
            "http-get:*:audio/mpeg:DLNA.ORG_PN=MP3;DLNA.ORG_OP=01;DLNA.ORG_FLAGS=01700000000000000000000000000000",
            "http-get:*:audio/wav:DLNA.ORG_PN=LPCM;DLNA.ORG_OP=01;DLNA.ORG_FLAGS=01700000000000000000000000000000",
            "http-get:*:audio/L16;rate=44100;channels=2:DLNA.ORG_PN=LPCM;DLNA.ORG_OP=01;DLNA.ORG_FLAGS=01700000000000000000000000000000",
            "http-get:*:audio/L16;rate=48000;channels=2:DLNA.ORG_PN=LPCM;DLNA.ORG_OP=01;DLNA.ORG_FLAGS=01700000000000000000000000000000",
            # Image formats
            "http-get:*:image/jpeg:DLNA.ORG_PN=JPEG_LRG;DLNA.ORG_OP=01;DLNA.ORG_FLAGS=00D00000000000000000000000000000",
            "http-get:*:image/png:DLNA.ORG_PN=PNG_LRG;DLNA.ORG_OP=01;DLNA.ORG_FLAGS=00D00000000000000000000000000000",
            # For better compatibility with Sony BRAVIA, add some basic MIME types without DLNA params
            "http-get:*:video/mp4:*",
            "http-get:*:video/x-msvideo:*",
            "http-get:*:video/mpeg:*",
            "http-get:*:audio/mpeg:*",
            "http-get:*:image/jpeg:*",
            "http-get:*:image/png:*",
        ]

        protocol_info_str = ",".join(protocols)
        print(f"Supported protocols: {len(protocols)}")

        response = f"""<?xml version="1.0" encoding="utf-8"?>
<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" s:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">
    <s:Body>
        <u:GetProtocolInfoResponse xmlns:u="urn:schemas-upnp-org:service:ConnectionManager:1">
            <Source>{protocol_info_str}</Source>
            <Sink></Sink>
        </u:GetProtocolInfoResponse>
    </s:Body>
</s:Envelope>"""

        self.send_response(200)
        self.send_header("Content-Type", 'text/xml; charset="utf-8"')
        self.send_header("Content-Length", str(len(response)))
        self.send_header("Ext", "")
        self.send_header("Server", SERVER_AGENT)
        self.end_headers()
        self.wfile.write(response.encode())
        print("GetProtocolInfo response sent")

    def handle_get_current_connection_ids(self):
        """Handle ConnectionManager GetCurrentConnectionIDs requests"""
        print("Handling GetCurrentConnectionIDs request")
        response = """<?xml version="1.0" encoding="utf-8"?>
<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" s:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">
    <s:Body>
        <u:GetCurrentConnectionIDsResponse xmlns:u="urn:schemas-upnp-org:service:ConnectionManager:1">
            <ConnectionIDs>0</ConnectionIDs>
        </u:GetCurrentConnectionIDsResponse>
    </s:Body>
</s:Envelope>"""

        self.send_response(200)
        self.send_header("Content-Type", 'text/xml; charset="utf-8"')
        self.send_header("Content-Length", str(len(response)))
        self.send_header("Ext", "")
        self.send_header("Server", SERVER_AGENT)
        self.end_headers()
        self.wfile.write(response.encode())
        print("GetCurrentConnectionIDs response sent")

    def handle_get_current_connection_info(self):
        """Handle ConnectionManager GetCurrentConnectionInfo requests"""
        print("Handling GetCurrentConnectionInfo request")
        response = """<?xml version="1.0" encoding="utf-8"?>
<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" s:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">
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
        self.send_header("Content-Type", 'text/xml; charset="utf-8"')
        self.send_header("Content-Length", str(len(response)))
        self.send_header("Ext", "")
        self.send_header("Server", SERVER_AGENT)
        self.end_headers()
        self.wfile.write(response.encode())
        print("GetCurrentConnectionInfo response sent")

    def handle_get_search_capabilities(self):
        """Handle ContentDirectory GetSearchCapabilities requests"""
        print("Handling GetSearchCapabilities request")
        response = """<?xml version="1.0" encoding="utf-8"?>
<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" s:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">
    <s:Body>
        <u:GetSearchCapabilitiesResponse xmlns:u="urn:schemas-upnp-org:service:ContentDirectory:1">
            <SearchCaps>dc:title,upnp:class,upnp:genre</SearchCaps>
        </u:GetSearchCapabilitiesResponse>
    </s:Body>
</s:Envelope>"""

        self.send_response(200)
        self.send_header("Content-Type", 'text/xml; charset="utf-8"')
        self.send_header("Content-Length", str(len(response)))
        self.send_header("Ext", "")
        self.send_header("Server", SERVER_AGENT)
        self.end_headers()
        self.wfile.write(response.encode())
        print("GetSearchCapabilities response sent")

    def handle_get_sort_capabilities(self):
        """Handle ContentDirectory GetSortCapabilities requests"""
        print("Handling GetSortCapabilities request")
        response = """<?xml version="1.0" encoding="utf-8"?>
<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" s:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">
    <s:Body>
        <u:GetSortCapabilitiesResponse xmlns:u="urn:schemas-upnp-org:service:ContentDirectory:1">
            <SortCaps>dc:title,dc:date,upnp:class</SortCaps>
        </u:GetSortCapabilitiesResponse>
    </s:Body>
</s:Envelope>"""

        self.send_response(200)
        self.send_header("Content-Type", 'text/xml; charset="utf-8"')
        self.send_header("Content-Length", str(len(response)))
        self.send_header("Ext", "")
        self.send_header("Server", SERVER_AGENT)
        self.end_headers()
        self.wfile.write(response.encode())
        print("GetSortCapabilities response sent")

    def handle_get_system_update_id(self):
        """Handle ContentDirectory GetSystemUpdateID requests"""
        print("Handling GetSystemUpdateID request")
        response = """<?xml version="1.0" encoding="utf-8"?>
<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" s:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">
    <s:Body>
        <u:GetSystemUpdateIDResponse xmlns:u="urn:schemas-upnp-org:service:ContentDirectory:1">
            <Id>1</Id>
        </u:GetSystemUpdateIDResponse>
    </s:Body>
</s:Envelope>"""

        self.send_response(200)
        self.send_header("Content-Type", 'text/xml; charset="utf-8"')
        self.send_header("Content-Length", str(len(response)))
        self.send_header("Ext", "")
        self.send_header("Server", SERVER_AGENT)
        self.end_headers()
        self.wfile.write(response.encode())
        print("GetSystemUpdateID response sent")

    def handle_subscribe_request(self):
        """Handle UPnP event subscription requests"""
        try:
            # Generate a unique subscription ID
            import uuid

            sid = f"uuid:{uuid.uuid4()}"

            # Get callback URL from headers
            callback = self.headers.get("CALLBACK", "")
            nt = self.headers.get("NT", "")
            timeout = self.headers.get("TIMEOUT", "Second-1800")

            # Basic validation
            if not callback or nt != "upnp:event":
                self.send_error(400, "Bad Request - Invalid headers")
                return

            # For simplicity, we'll accept the subscription but not actually send events
            self.send_response(200)
            self.send_header("SID", sid)
            self.send_header("TIMEOUT", timeout)
            self.send_header("Content-Length", "0")
            self.end_headers()

            print(f"Event subscription accepted: SID={sid}, Callback={callback}")

        except Exception as e:
            print(f"Subscribe request error: {e}")
            self.send_error(500, "Internal server error")

    def handle_unsubscribe_request(self):
        """Handle UPnP event unsubscription requests"""
        try:
            sid = self.headers.get("SID", "")

            if not sid:
                self.send_error(400, "Bad Request - Missing SID")
                return

            # Accept the unsubscription
            self.send_response(200)
            self.send_header("Content-Length", "0")
            self.end_headers()

            print(f"Event unsubscription accepted: SID={sid}")

        except Exception as e:
            print(f"Unsubscribe request error: {e}")
            self.send_error(500, "Internal server error")

    def log_message(self, format, *args):
        """Override to provide custom logging"""
        message = format % args
        print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {message}")

        # Log any unusual requests
        if "404" in message or "500" in message:
            print(f"ERROR REQUEST: {self.path} from {self.client_address}")
            print(f"ERROR HEADERS: {dict(self.headers)}")
        elif "/media/" in message:
            print(f"MEDIA ACCESS: {self.path} from {self.client_address}")
            print(f"MEDIA HEADERS: {dict(self.headers)}")

    def _count_media_files(self):
        """Count all valid media files in the media directory (video, audio, image)"""
        count = 0
        files = os.listdir(self.server_instance.media_directory)
        for file in files:
            file_path = os.path.join(self.server_instance.media_directory, file)
            if os.path.isfile(file_path):
                mime_type, _ = mimetypes.guess_type(file)
                if mime_type and (
                    mime_type.startswith("video/")
                    or mime_type.startswith("audio/")
                    or mime_type.startswith("image/")
                ):
                    count += 1
        return count


class EZDLNA:
    def __init__(self, media_directory=None, port=8200):
        self.name = SERVER_NAME
        self.version = SERVER_VERSION
        self.author = SERVER_MANUFACTURER
        self.description = SERVER_DESCRIPTION
        self.media_directory = media_directory or os.getcwd()
        self.port = port
        self.server = None
        self.server_thread = None
        self.device_uuid = str(uuid.uuid4())
        self.server_ip = self.get_local_ip()
        self.running = False
        self.ssdp_server = SSDPServer(self)

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

        def handler(*args, **kwargs):
            return DLNAHandler(self, *args, **kwargs)

        return handler

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
            except OSError as e:
                print(
                    f"Error: Port {self.port} is already in use. Try a different port with -p option."
                )
                return False

            # Count media files
            media_count = 0
            for file in os.listdir(self.media_directory):
                file_path = os.path.join(self.media_directory, file)
                if os.path.isfile(file_path):
                    mime_type, _ = mimetypes.guess_type(file)
                    if mime_type and (
                        mime_type.startswith("video/")
                        or mime_type.startswith("audio/")
                        or mime_type.startswith("image/")
                    ):
                        media_count += 1

            print(f"Found {media_count} media files to serve")

            self.server = HTTPServer((self.server_ip, self.port), self.create_handler())
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


def main():
    import argparse

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

    args = parser.parse_args()

    server = EZDLNA(media_directory=args.directory, port=args.port)
    server.run()


if __name__ == "__main__":
    main()
