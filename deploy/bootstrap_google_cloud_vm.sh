#!/usr/bin/env bash
set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/dinhhoan/ai-change-btc.git}"
APP_DIR="${APP_DIR:-/opt/crypto-whale-radar}"

sudo apt-get update
sudo apt-get install -y git curl

if [[ ! -e "$APP_DIR" ]]; then
  sudo mkdir -p "$APP_DIR"
  sudo chown -R "$USER:$USER" "$APP_DIR"
  git clone "$REPO_URL" "$APP_DIR"
elif [[ -d "$APP_DIR/.git" ]]; then
  git -C "$APP_DIR" pull --ff-only
else
  if [[ -z "$(find "$APP_DIR" -mindepth 1 -maxdepth 1 -print -quit 2>/dev/null)" ]]; then
    sudo chown -R "$USER:$USER" "$APP_DIR"
    git clone "$REPO_URL" "$APP_DIR"
  else
    echo "$APP_DIR exists but is not a git checkout. Move it first or set APP_DIR to another path." >&2
    exit 1
  fi
fi

cd "$APP_DIR"
chmod +x deploy/install_google_cloud_vm.sh
./deploy/install_google_cloud_vm.sh

echo
echo "Bootstrap complete."
echo "Edit Telegram env:"
echo "  sudo nano $APP_DIR/.env"
echo
echo "Start service:"
echo "  sudo systemctl enable --now crypto-whale-radar"
echo "  sudo journalctl -u crypto-whale-radar -f"

