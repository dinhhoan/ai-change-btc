#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/crypto-whale-radar}"
SERVICE_NAME="crypto-whale-radar"
SERVICE_USER="${SERVICE_USER:-crypto-whale}"

if [[ ! -d "$APP_DIR/src/whale_signal_lab" ]]; then
  echo "App directory is missing source files: $APP_DIR" >&2
  echo "Copy the repo to $APP_DIR first, then run this script on the VM." >&2
  exit 1
fi

sudo apt-get update
sudo apt-get install -y python3 python3-venv python3-pip curl

if ! id "$SERVICE_USER" >/dev/null 2>&1; then
  sudo useradd --system --home-dir "$APP_DIR" --shell /usr/sbin/nologin "$SERVICE_USER"
fi

python3 -m venv "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/python" -m pip install --upgrade pip
"$APP_DIR/.venv/bin/python" -m pip install -e "$APP_DIR"

if [[ ! -f "$APP_DIR/.env" ]]; then
  cp "$APP_DIR/deploy/google-cloud.env.example" "$APP_DIR/.env"
  chmod 600 "$APP_DIR/.env"
  echo "Created $APP_DIR/.env. Edit it before starting the service."
fi

sudo chown -R "$SERVICE_USER:$SERVICE_USER" "$APP_DIR"
sudo cp "$APP_DIR/deploy/crypto-whale-radar.service" "/etc/systemd/system/${SERVICE_NAME}.service"
sudo systemctl daemon-reload

echo "Install complete."
echo "Next:"
echo "  sudo nano $APP_DIR/.env"
echo "  sudo systemctl enable --now ${SERVICE_NAME}"
echo "  sudo journalctl -u ${SERVICE_NAME} -f"
