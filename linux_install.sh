#!/bin/bash

# ZeroConfigDLNA Installation Script for Linux (Ubuntu/Debian/systemd)
# This script will install ZeroConfigDLNA as a system service

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
REPO_URL="https://github.com/richstokes/ZeroConfigDLNA.git"
INSTALL_DIR="/opt/zeroconfigdlna"
SERVICE_NAME="zeroconfigdlna"
SERVICE_USER="dlna"

echo -e "${BLUE}ZeroConfigDLNA Installation Script${NC}"
echo "=================================="

# Check if running as root
if [[ $EUID -ne 0 ]]; then
   echo -e "${RED}Error: This script must be run as root (use sudo)${NC}"
   exit 1
fi

# Check if systemd is available
if ! command -v systemctl &> /dev/null; then
    echo -e "${RED}Error: systemctl not found. This script requires a systemd-based system.${NC}"
    exit 1
fi

# Check if git is installed
if ! command -v git &> /dev/null; then
    echo -e "${YELLOW}Git not found. Please install with `apt-get install -y git` or similar.${NC}"
    exit 1
fi

# Check if python3 is installed
if ! command -v python3 &> /dev/null; then
    echo -e "${YELLOW}Python3 not found. Please install with `apt-get install -y python3` or similar.${NC}"
    exit 1
fi

# Prompt for media directory
echo
echo -e "${BLUE}Media Directory Configuration${NC}"
echo "Please enter the path to your media directory:"
echo "This is where your video, audio, and image files are stored."
echo "Examples: /home/username/Videos, /media/storage/movies, /mnt/nas/media"
echo
read -p "Media directory path: " MEDIA_DIR

# Validate media directory
if [[ -z "$MEDIA_DIR" ]]; then
    echo -e "${RED}Error: Media directory cannot be empty${NC}"
    exit 1
fi

if [[ ! -d "$MEDIA_DIR" ]]; then
    echo -e "${RED}Error: Directory '$MEDIA_DIR' does not exist${NC}"
    exit 1
fi

# Convert to absolute path
MEDIA_DIR=$(realpath "$MEDIA_DIR")
echo -e "${GREEN}Using media directory: $MEDIA_DIR${NC}"

# Prompt for port (optional)
echo
read -p "Port number (default: 8200): " PORT
PORT=${PORT:-8200}

# Validate port
if ! [[ "$PORT" =~ ^[0-9]+$ ]] || [ "$PORT" -lt 1024 ] || [ "$PORT" -gt 65535 ]; then
    echo -e "${RED}Error: Port must be a number between 1024 and 65535${NC}"
    exit 1
fi

echo -e "${GREEN}Using port: $PORT${NC}"

# Stop service if it exists
if systemctl is-active --quiet $SERVICE_NAME; then
    echo -e "${YELLOW}Stopping existing $SERVICE_NAME service...${NC}"
    systemctl stop $SERVICE_NAME
fi

# Create service user
if ! id "$SERVICE_USER" &>/dev/null; then
    echo -e "${YELLOW}Creating service user '$SERVICE_USER'...${NC}"
    useradd --system --home-dir /nonexistent --no-create-home --shell /bin/false $SERVICE_USER
fi

# Remove existing installation
if [[ -d "$INSTALL_DIR" ]]; then
    echo -e "${YELLOW}Removing existing installation...${NC}"
    rm -rf "$INSTALL_DIR"
fi

# Clone repository
echo -e "${YELLOW}Cloning ZeroConfigDLNA repository...${NC}"
git clone "$REPO_URL" "$INSTALL_DIR"

# Set ownership
chown -R $SERVICE_USER:$SERVICE_USER "$INSTALL_DIR"

# Give read access to media directory for the service user
echo -e "${YELLOW}Setting up media directory permissions...${NC}"
# Add the service user to the group that owns the media directory
MEDIA_GROUP=$(stat -c '%G' "$MEDIA_DIR")
usermod -a -G "$MEDIA_GROUP" "$SERVICE_USER"

# Create systemd service file
echo -e "${YELLOW}Creating systemd service file...${NC}"
cat > /etc/systemd/system/$SERVICE_NAME.service << EOF
[Unit]
Description=ZeroConfigDLNA Media Server
Documentation=https://github.com/richstokes/ZeroConfigDLNA
After=network.target
Wants=network.target

[Service]
Type=simple
User=$SERVICE_USER
Group=$SERVICE_USER
WorkingDirectory=$INSTALL_DIR
ExecStart=/usr/bin/python3 $INSTALL_DIR/app.py -d "$MEDIA_DIR" -p $PORT
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal
SyslogIdentifier=$SERVICE_NAME

# Security settings
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=$INSTALL_DIR
ReadOnlyPaths=$MEDIA_DIR

# Network settings
RestrictAddressFamilies=AF_INET AF_INET6

[Install]
WantedBy=multi-user.target
EOF

# Reload systemd and enable service
echo -e "${YELLOW}Enabling systemd service...${NC}"
systemctl daemon-reload
systemctl enable $SERVICE_NAME

# Start the service
echo -e "${YELLOW}Starting $SERVICE_NAME service...${NC}"
systemctl start $SERVICE_NAME

# Wait a moment for service to start
sleep 2

# Check service status
if systemctl is-active --quiet $SERVICE_NAME; then
    echo -e "${GREEN}✓ Service started successfully!${NC}"
    
    # Get the local IP address
    LOCAL_IP=$(ip route get 1.1.1.1 | grep -oP 'src \K\S+' 2>/dev/null || echo "localhost")
    
    echo
    echo -e "${GREEN}Installation completed successfully!${NC}"
    echo
    echo "Service Information:"
    echo "  Service name: $SERVICE_NAME"
    echo "  Media directory: $MEDIA_DIR"
    echo "  Port: $PORT"
    echo "  Server URL: http://$LOCAL_IP:$PORT/"
    echo "  Device description: http://$LOCAL_IP:$PORT/description.xml"
    echo "  Browse media: http://$LOCAL_IP:$PORT/browse"
    echo
    echo "Service Management Commands:"
    echo "  Start:   sudo systemctl start $SERVICE_NAME"
    echo "  Stop:    sudo systemctl stop $SERVICE_NAME"
    echo "  Restart: sudo systemctl restart $SERVICE_NAME"
    echo "  Status:  sudo systemctl status $SERVICE_NAME"
    echo "  Logs:    sudo journalctl -u $SERVICE_NAME -f"
    echo
    echo "The service will automatically start on boot."
    echo "Your DLNA server should now be discoverable on your network!"
    
else
    echo -e "${RED}✗ Service failed to start${NC}"
    echo "Check the service status with: sudo systemctl status $SERVICE_NAME"
    echo "Check the logs with: sudo journalctl -u $SERVICE_NAME"
    exit 1
fi
