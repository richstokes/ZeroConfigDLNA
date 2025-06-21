import os
import socket

# Get hostname, truncate at first dot, then limit to 16 chars max
hostname = socket.gethostname().split(".")[0][:16]

SERVER_NAME = os.environ.get("DLNA_HOSTNAME") or f"ZeroConfigDLNA_{hostname}"
SERVER_DESCRIPTION = "ZeroConfigDLNA Server"
SERVER_VERSION = "1.0.3"
SERVER_MANUFACTURER = "richstokes"
SERVER_AGENT = f"ZeroConfigDLNA/{SERVER_VERSION} DLNA/1.50 UPnP/1.0"
