# Deployment Guide — NSE Trading System on DigitalOcean

## Overview

Your trading system runs 24/7 on a DigitalOcean droplet.  
Every morning you run one command on your Mac to push the Kite token, then close your laptop.

---

## Part 1 — One-Time Setup (Do this once)

### 1. Create a GitHub Private Repository

1. Go to https://github.com/new
2. Name it `India_Trading_System`, set to **Private**
3. Do NOT add README or .gitignore (you already have them)

### 2. Push your code to GitHub

Open Terminal on your Mac:

```bash
cd ~/Desktop/India_Trading_System

# Initialize git
git init
git add .
git commit -m "Initial commit"

# Connect to GitHub (replace YOUR_USERNAME)
git remote add origin https://github.com/YOUR_USERNAME/India_Trading_System.git
git branch -M main
git push -u origin main
```

Verify your `.env` was NOT pushed — it should not appear on GitHub.

---

### 3. Create a DigitalOcean Droplet

1. Log in at https://cloud.digitalocean.com
2. Create Droplet:
   - **Image:** Ubuntu 22.04 LTS
   - **Plan:** Basic — $6/month (1 vCPU, 1GB RAM) is enough
   - **Region:** Bangalore (BLR1) — closest to NSE
   - **Authentication:** SSH Key (recommended) or Password

---

### 4. Set Up Your SSH Key (if not done already)

On your Mac:

```bash
# Generate SSH key (skip if you already have one)
ssh-keygen -t rsa -b 4096 -C "trading-server"

# Copy your public key (paste this into DigitalOcean when creating droplet)
cat ~/.ssh/id_rsa.pub
```

---

### 5. Run the Server Setup Script

```bash
# SSH into your new droplet
ssh root@YOUR_SERVER_IP

# Download and run setup script
curl -O https://raw.githubusercontent.com/YOUR_USERNAME/India_Trading_System/main/deploy/setup_server.sh
chmod +x setup_server.sh
bash setup_server.sh
```

When it finishes, fill in your real API keys:

```bash
nano /opt/trading/.env
```

Fill in:
```
KITE_API_KEY=your_real_key
KITE_API_SECRET=your_real_secret
KITE_ACCESS_TOKEN=will_be_updated_daily
GROQ_API_KEY=your_groq_key
NEWS_API_KEY=your_news_key
CHROMA_PERSIST_DIR=./chroma_store
```

Save with `Ctrl+O`, exit with `Ctrl+X`.

---

### 6. Configure Your Mac for Daily Token Push

Back on your Mac, create the server config:

```bash
cp ~/Desktop/India_Trading_System/deploy/server_config.env.example \
   ~/Desktop/India_Trading_System/deploy/server_config.env

# Edit it with your server details
nano ~/Desktop/India_Trading_System/deploy/server_config.env
```

Fill in your droplet IP:
```
SERVER_IP=your.droplet.ip
SERVER_USER=trading
SERVER_ENV_PATH=/opt/trading/.env
SSH_KEY_PATH=~/.ssh/id_rsa
```

---

### 7. Start the Trading Service on Server

```bash
ssh root@YOUR_SERVER_IP
systemctl start trading-system
systemctl status trading-system
```

You should see it running. It will sleep until market hours (9:20 AM IST).

---

## Part 2 — Every Morning Routine (2 minutes)

Each trading day, run this ONE command on your Mac:

```bash
cd ~/Desktop/India_Trading_System
source venv/bin/activate
python kite_login.py
```

It will:
1. Open Kite login in your browser
2. You log in and paste the redirect URL
3. Token is saved locally AND pushed to your DigitalOcean server
4. Trading service restarts automatically with the new token

**Then close your MacBook.** The server runs everything.

---

## Useful Server Commands

```bash
# SSH into server
ssh trading@YOUR_SERVER_IP

# View live trading logs
journalctl -u trading-system -f

# Restart the service manually
sudo systemctl restart trading-system

# Stop the service (emergency)
sudo systemctl stop trading-system

# Check service status
systemctl status trading-system

# Pull latest code updates from GitHub
cd /opt/trading && git pull && sudo systemctl restart trading-system
```

---

## Emergency Kill Switch

To pause trading without stopping the server, create this file on the server:

```bash
echo '{"kill_switch": true}' > /opt/trading/system_controls.json
```

The system checks this every tick and will pause immediately.

To resume:
```bash
echo '{"kill_switch": false}' > /opt/trading/system_controls.json
```

---

## What Runs Where

| Task | Where |
|------|-------|
| Trading engine (main.py) | DigitalOcean server 24/7 |
| Streamlit dashboard | DigitalOcean server (port 8501) |
| Kite token refresh | Your Mac (each morning, 2 min) |
| GitHub code updates | Push from Mac → Pull on server |

---

## Dashboard Access

Once deployed, your dashboard is accessible at:

```
http://YOUR_SERVER_IP:8501
```

To run dashboard on server, open a second systemd service or run in screen:

```bash
ssh trading@YOUR_SERVER_IP
cd /opt/trading
screen -S dashboard
source venv/bin/activate
streamlit run dashboard/app.py --server.port 8501 --server.address 0.0.0.0
# Press Ctrl+A then D to detach
```
