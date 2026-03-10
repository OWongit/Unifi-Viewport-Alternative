#!/bin/bash
# UniFi Viewport Alternative - Raspberry Pi Install Script
# Installs dependencies, configures the app (API key + host), and sets up autostart.

# ANSI colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BLUE='\033[0;34m'
MAGENTA='\033[0;35m'
BOLD='\033[1m'
NC='\033[0m'

echo -e "${CYAN}${BOLD}"
echo "=============================================="
echo "  UniFi Viewport Alternative - Pi Install"
echo "=============================================="
echo -e "${NC}"

# Step 1: Check sudo
echo -e "${BLUE}[1/10]${NC} Checking privileges..."
if [ "$EUID" -eq 0 ]; then
    echo -e "${YELLOW}Running as root. Consider running as regular user with sudo.${NC}"
fi
if ! sudo -v 2>/dev/null; then
    echo -e "${RED}Error: sudo access required.${NC}"
    exit 1
fi
echo -e "${GREEN}OK${NC}"

# Step 2: Detect project directory
echo -e "${BLUE}[2/10]${NC} Locating project..."
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$SCRIPT_DIR"
if [ ! -f "$PROJECT_DIR/main.py" ]; then
    echo -e "${RED}Error: main.py not found in $PROJECT_DIR${NC}"
    exit 1
fi
echo -e "${GREEN}Project: ${MAGENTA}$PROJECT_DIR${NC}"

# Step 3: Update apt and install system deps
echo -e "${BLUE}[3/10]${NC} Installing system dependencies..."
sudo apt-get update -qq
sudo apt-get install -y -qq python3 python3-venv python3-pip ffmpeg 2>/dev/null || true
echo -e "${GREEN}OK${NC}"

# Step 4: Create venv and install requirements
echo -e "${BLUE}[4/10]${NC} Creating virtual environment..."
cd "$PROJECT_DIR"
if [ ! -d ".venv" ]; then
    python3 -m venv .venv
fi
source .venv/bin/activate
pip install -q -r requirements.txt
echo -e "${GREEN}OK${NC}"

# Step 5 & 6: Interactive config setup
echo -e "${BLUE}[5/10]${NC} Configuring UniFi Protect credentials..."
echo ""
read -sp "$(echo -e ${YELLOW}Enter your UniFi Protect API key: ${NC})" API_KEY
echo ""
read -p "$(echo -e ${YELLOW}Enter your UniFi Protect host \(e.g. 192.168.1.1\): ${NC})" UNIFI_HOST
echo ""

if [ -z "$API_KEY" ] || [ -z "$UNIFI_HOST" ]; then
    echo -e "${RED}Error: API key and host are required.${NC}"
    echo -e "${YELLOW}You can edit config.py manually later.${NC}"
fi

echo -e "${BLUE}[6/10]${NC} Writing config.py..."
export API_KEY
export UNIFI_HOST
python3 << 'PYEOF'
import os
api_key = os.environ.get("API_KEY", "")
unifi_host = os.environ.get("UNIFI_HOST", "")
with open("config.example.py") as f:
    content = f.read()
content = content.replace("API_KEY_HERE", api_key).replace("UNIFI_HOST_HERE", unifi_host)
with open("config.py", "w") as f:
    f.write(content)
PYEOF
echo -e "${GREEN}Config saved.${NC}"

# Step 7: Create start_cams.sh
echo -e "${BLUE}[7/10]${NC} Creating start_cams.sh..."
cat > "$PROJECT_DIR/start_cams.sh" << EOF
#!/bin/bash
cd "$PROJECT_DIR"
source .venv/bin/activate
export DISPLAY=:0
python main.py
EOF
chmod +x "$PROJECT_DIR/start_cams.sh"
echo -e "${GREEN}OK${NC}"

# Step 8: Configure autostart
echo -e "${BLUE}[8/10]${NC} Configuring autostart..."
AUTOSTART_DIR="$HOME/.config/autostart"
mkdir -p "$AUTOSTART_DIR"
DESKTOP_FILE="$AUTOSTART_DIR/vid-board.desktop"
cat > "$DESKTOP_FILE" << EOF
[Desktop Entry]
Type=Application
Name=UniFi Viewport Alternative
Exec=$PROJECT_DIR/start_cams.sh
X-GNOME-Autostart-enabled=true
EOF
echo -e "${GREEN}Autostart configured: ${MAGENTA}$DESKTOP_FILE${NC}"

# Step 9: Make install script executable
echo -e "${BLUE}[9/10]${NC} Setting permissions..."
chmod +x "$PROJECT_DIR/install_pi.sh" 2>/dev/null || true
echo -e "${GREEN}OK${NC}"

# Step 10: Done
echo -e "${BLUE}[10/10]${NC} Install complete."
echo ""
echo -e "${GREEN}${BOLD}Success!${NC}"
echo ""
echo -e "Control panel: ${MAGENTA}http://<your-pi-ip>:5000${NC}"
echo ""
echo -e "${YELLOW}Next steps:${NC}"
echo "  1. Ensure Desktop Autologin is enabled: raspi-config -> Boot -> Desktop Autologin"
echo "  2. Reboot to test autostart: sudo reboot"
echo "  3. Or run now: $PROJECT_DIR/start_cams.sh"
echo ""
