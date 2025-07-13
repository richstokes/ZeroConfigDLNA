import os
from constants import SERVER_MANUFACTURER, SERVER_VERSION, SERVER_AGENT


def is_safe_path(base_dir, requested_path):
    """
    Verify that the requested path is contained within the base directory.
    This is a security measure to prevent directory traversal attacks.

    Args:
        base_dir: The allowed base directory (media_directory)
        requested_path: The path requested by the client

    Returns:
        bool: True if the path is safe, False otherwise
    """
    # Normalize paths (handle case sensitivity, symbolic links, etc.)
    base_dir = os.path.normcase(os.path.normpath(os.path.realpath(base_dir)))

    # Handle relative paths before realpath resolves symlinks, then normalize
    requested_path = os.path.normcase(
        os.path.normpath(os.path.realpath(os.path.abspath(requested_path)))
    )

    # First quick check - if no common prefix, definitely unsafe
    if not os.path.commonprefix([base_dir, requested_path]) == base_dir:
        return False

    # For more accuracy, use commonpath if available (Python 3.5+)
    try:
        return os.path.commonpath([base_dir, requested_path]) == base_dir
    except (ValueError, AttributeError):
        # Fallback for older Python or if paths are on different drives
        rel_path = os.path.relpath(requested_path, base_dir)
        return not rel_path.startswith(os.pardir) and not os.path.isabs(rel_path)


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
    <friendlyName>{self.server_name}</friendlyName>
    <manufacturer>{SERVER_MANUFACTURER}</manufacturer>
    <manufacturerURL>https://github.com/richstokes/ZeroConfigDLNA</manufacturerURL>
    <modelDescription>DLNA/UPnP Media Server</modelDescription>
    <modelName>{self.server_name}</modelName>
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
        scpd_xml = """<?xml version="1.0" encoding="utf-8"?>
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
        <name>A_ARG_TYPE_UpdateID</name>
        <dataType>ui4</dataType>
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
        scpd_xml = """<?xml version="1.0" encoding="utf-8"?>
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