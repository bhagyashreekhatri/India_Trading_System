#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# NSE Trading System — DigitalOcean Server Setup Script
# Run this ONCE on a fresh Ubuntu 22.04 droplet as root
#
# Usage:
#   ssh root@YOUR_SERVER_IP
#   curl -O https://raw.githubusercontent.com/YOUR_USERNAME/India_Trading_System/main/deploy/setup_server.sh
#   chmod +x setup_server.sh && bash setup_server.sh
# ─────────────────────────────────────────────────────────────────────────────

set -e  # exit on any error

echo ""
echo "╔══════════════════════════════════════════════════╗"
echo "║   NSE Trading System — Server Setup              ║"
echo "╚══════════════════════════════════════════════════╝"
echo ""

# ── Config (edit these before running) ───────────────────────────────────────
GITHUB_REPO="https://github.com/YOUR_USERNAME/India_Trading_System.git"
PROJECT_DIR="/opt/trading"
SERVICE_USER="trading"
# ─────────────────────────────────────────────────────────────────────────────

echo "▶ Step 1: Updating system packages..."
apt-get update -qq && apt-get upgrade -y -qq

echo "▶ Step 2: Installing Python 3.10 and dependencies..."
apt-get install -y -qq python3.10 python3.10-venv python3-pip git curl wget

echo "▶ Step 3: Creating service user '$SERVICE_USER'..."
id -u $SERVICE_USER &>/dev/null || useradd -m -s /bin/bash $SERVICE_USER

echo "▶ Step 4: Cloning project from GitHub..."
if [ -d "$PROJECT_DIR" ]; then
    echo "   Directory exists — pulling latest..."
    cd $PROJECT_DIR && git pull
else
    git clone $GITHUB_REPO $PROJECT_DIR
fi
chown -R $SERVICE_USER:$SERVICE_USER $PROJECT_DIR

echo "▶ Step 5: Creating Python virtual environment..."
cd $PROJECT_DIR
sudo -u $SERVICE_USER python3.10 -m venv venv
sudo -u $SERVICE_USER venv/bin/pip install --upgrade pip -q
sudo -u $SERVICE_USER venv/bin/pip install -r requirements.txt -q
echo "   ✅ Packages installed"

echo "▶ Step 6: Creating .env file from template..."
if [ ! -f "$PROJECT_DIR/.env" ]; then
    cp $PROJECT_DIR/.env.example $PROJECT_DIR/.env
    chown $SERVICE_USER:$SERVICE_USER $PROJECT_DIR/.env
    chmod 600 $PROJECT_DIR/.env
    echo ""
    echo "   ⚠️  IMPORTANT: Edit $PROJECT_DIR/.env with your real API keys!"
    echo "   Run: nano $PROJECT_DIR/.env"
    echo ""
else
    echo "   .env already exists — skipping"
fi

echo "▶ Step 7: Installing systemd service..."
cp $PROJECT_DIR/deploy/trading-system.service /etc/systemd/system/
sed -i "s|/opt/trading|$PROJECT_DIR|g" /etc/systemd/system/trading-system.service
sed -i "s|trading|$SERVICE_USER|g" /etc/systemd/system/trading-system.service
systemctl daemon-reload
systemctl enable trading-system
echo "   ✅ Service installed and enabled on boot"

echo "▶ Step 8: Setting up log directory..."
mkdir -p /var/log/trading
chown $SERVICE_USER:$SERVICE_USER /var/log/trading

echo ""
echo "╔══════════════════════════════════════════════════╗"
echo "║   Setup Complete!                                ║"
echo "╚══════════════════════════════════════════════════╝"
echo ""
echo "Next steps:"
echo "  1. Fill in your API keys:  nano $PROJECT_DIR/.env"
echo "  2. Start the service:      systemctl start trading-system"
echo "  3. Check status:           systemctl status trading-system"
echo "  4. View live logs:         journalctl -u trading-system -f"
echo ""
echo "The service will auto-start on every server reboot."
echo "Use kite_login.py on your Mac each morning to push the daily token."
echo ""
