"""
Morning login script.
Run this ONCE every morning before starting the trading system.

Usage:
    python kite_login.py              # local only
    python kite_login.py --push       # generate token + push to DigitalOcean server

What it does:
1. Opens Kite login URL in your browser
2. You log in and get redirected to a URL with ?request_token=XXXX
3. Paste that full URL here
4. Script generates access token and saves to .env automatically
5. (Optional) SSHes into your server and updates the token there too
"""

import os
import re
import sys
import webbrowser
import subprocess
from kiteconnect import KiteConnect
from dotenv import load_dotenv, set_key
from pathlib import Path

ENV_PATH     = Path(__file__).parent / ".env"
SERVER_CONF  = Path(__file__).parent / "deploy" / "server_config.env"

# ─── Server config (loaded from deploy/server_config.env — NOT committed) ────
# That file should contain:
#   SERVER_IP=your.droplet.ip
#   SERVER_USER=trading
#   SERVER_ENV_PATH=/opt/trading/.env
#   SSH_KEY_PATH=~/.ssh/id_rsa        (optional, uses default if omitted)
# ─────────────────────────────────────────────────────────────────────────────


def load_server_config() -> dict:
    """Load server SSH config from deploy/server_config.env."""
    conf = {}
    if SERVER_CONF.exists():
        for line in SERVER_CONF.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                conf[k.strip()] = v.strip()
    return conf


def update_env_token(token: str, env_path: Path = ENV_PATH):
    """Write KITE_ACCESS_TOKEN to an .env file."""
    set_key(str(env_path), "KITE_ACCESS_TOKEN", token)
    print(f"   ✅ Token saved to {env_path.name}")


def push_token_to_server(token: str) -> bool:
    """SSH into the DigitalOcean server and update KITE_ACCESS_TOKEN there."""
    conf = load_server_config()

    server_ip   = conf.get("SERVER_IP", "")
    server_user = conf.get("SERVER_USER", "trading")
    env_path    = conf.get("SERVER_ENV_PATH", "/opt/trading/.env")
    ssh_key     = conf.get("SSH_KEY_PATH", "")

    if not server_ip:
        print("\n   ⚠️  SERVER_IP not set in deploy/server_config.env")
        print("   Skipping server push. See deploy/server_config.env.example")
        return False

    ssh_key_part = f"-i {os.path.expanduser(ssh_key)}" if ssh_key else ""
    ssh_target   = f"{server_user}@{server_ip}"

    # Escape token for shell
    safe_token = token.replace("'", "'\"'\"'")

    # Commands to run on the server:
    # 1. Update the token in .env using sed
    # 2. Restart the trading service
    remote_cmd = (
        f"sed -i 's|^KITE_ACCESS_TOKEN=.*|KITE_ACCESS_TOKEN={safe_token}|' {env_path} && "
        f"echo '   ✅ Token updated on server' && "
        f"sudo systemctl restart trading-system && "
        f"echo '   ✅ Trading service restarted'"
    )

    ssh_cmd = f"ssh -o StrictHostKeyChecking=no {ssh_key_part} {ssh_target} \"{remote_cmd}\""

    print(f"\n   Pushing token to server {server_ip}...")
    result = subprocess.run(ssh_cmd, shell=True, capture_output=True, text=True)

    if result.returncode == 0:
        print(result.stdout)
        return True
    else:
        print(f"   ❌ Server push failed: {result.stderr}")
        print("   You can manually run on server:")
        print(f"   ssh {ssh_target}")
        print(f"   Then: nano {env_path}  (update KITE_ACCESS_TOKEN)")
        return False


def main():
    load_dotenv(ENV_PATH)

    push_to_server = "--push" in sys.argv

    api_key    = os.getenv("KITE_API_KEY", "")
    api_secret = os.getenv("KITE_API_SECRET", "")

    if not api_key or not api_secret:
        print("❌ KITE_API_KEY or KITE_API_SECRET missing from .env")
        print("   Add them first, then run this script again.")
        return

    kite = KiteConnect(api_key=api_key)
    login_url = kite.login_url()

    print("\n" + "="*55)
    print("  NSE Trading System — Morning Login")
    print("="*55)
    print("\nStep 1: Opening Kite login in your browser...")
    print(f"        {login_url}\n")

    try:
        webbrowser.open(login_url)
    except Exception:
        print("        (Could not auto-open — copy the URL above manually)")

    print("Step 2: Log in with your Zerodha credentials")
    print("        After login you'll be redirected to a URL like:")
    print("        https://127.0.0.1/?request_token=XXXXXXXX&action=login&status=success\n")

    redirected_url = input("Step 3: Paste the full redirected URL here:\n> ").strip()

    # Extract request_token from URL
    match = re.search(r"request_token=([^&]+)", redirected_url)
    if not match:
        if len(redirected_url) > 10 and " " not in redirected_url and "=" not in redirected_url:
            request_token = redirected_url
        else:
            print("\n❌ Could not find request_token in the URL you pasted.")
            print("   Make sure you paste the full redirect URL.")
            return
    else:
        request_token = match.group(1)

    print(f"\n   Found request_token: {request_token[:8]}...")

    # Generate access token
    try:
        data         = kite.generate_session(request_token, api_secret=api_secret)
        access_token = data["access_token"]
        print(f"   Generated access_token: {access_token[:8]}...")
    except Exception as e:
        print(f"\n❌ Failed to generate session: {e}")
        print("   The request_token may have expired — try again.")
        return

    # Save to local .env
    update_env_token(access_token)

    # Quick verify
    kite.set_access_token(access_token)
    try:
        profile = kite.profile()
        name    = profile.get("user_name", "Unknown")
        print(f"\n✅ Logged in as: {name}")
    except Exception:
        print("\n✅ Token saved (could not verify profile)")

    # Push to server if requested or if server config exists
    if push_to_server or SERVER_CONF.exists():
        if not push_to_server:
            answer = input("\n   Server config found. Push token to DigitalOcean server? (y/n): ").strip().lower()
            do_push = answer == "y"
        else:
            do_push = True

        if do_push:
            push_token_to_server(access_token)

    print("\n" + "="*55)
    print("  Ready! Trading system is running on the server.")
    print("  You can now close your MacBook.")
    print("="*55 + "\n")


if __name__ == "__main__":
    main()
