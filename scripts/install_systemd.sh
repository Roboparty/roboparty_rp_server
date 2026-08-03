#!/usr/bin/env bash
# Install rp_server as a strict production systemd service on RK3588.

set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
  echo "Run as root: sudo bash scripts/install_systemd.sh [robot.yaml]" >&2
  exit 1
fi

SOURCE_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ROBOT_CONFIG="${1:-${RP_ROBOT_CONFIG:-/opt/roboparty/share/roboto-inference/config/robot/robot.yaml}}"
PYTHON_SITE="/opt/roboparty/lib/python3/dist-packages"
VENDOR_SITE="/opt/roboparty/lib/python3/vendor-packages"
SHARE_ROOT="/opt/roboparty/share/roboparty-rp-server"
SECRET_DIR="/etc/rp-server"
SECRET_FILE="$SECRET_DIR/rp-server.env"

echo "[1/6] Checking real hardware packages and robot config"
PYTHONPATH="$VENDOR_SITE:$SOURCE_ROOT/src:$PYTHON_SITE" \
  PYTHONNOUSERSITE=1 \
  /usr/bin/python3 "$SOURCE_ROOT/scripts/hardware_preflight.py" \
    --config "$ROBOT_CONFIG" \
    --server-config "$SOURCE_ROOT/config/server.yaml"

echo "[2/6] Installing application files"
install -d "$PYTHON_SITE" "$SHARE_ROOT" "$SECRET_DIR"
rm -rf "$PYTHON_SITE/rp_server"
cp -a "$SOURCE_ROOT/src/rp_server" "$PYTHON_SITE/rp_server"
rm -rf "$SHARE_ROOT/config" "$SHARE_ROOT/docs" "$SHARE_ROOT/scripts"
cp -a "$SOURCE_ROOT/config" "$SHARE_ROOT/config"
cp -a "$SOURCE_ROOT/docs" "$SHARE_ROOT/docs"
cp -a "$SOURCE_ROOT/scripts" "$SHARE_ROOT/scripts"
install -m 0644 "$SOURCE_ROOT/requirements-board.txt" "$SHARE_ROOT/requirements-board.txt"

echo "[3/6] Ensuring a uvicorn-compatible board WebSocket runtime"
install -d "$VENDOR_SITE"
rm -rf "$VENDOR_SITE/websockets" "$VENDOR_SITE"/websockets-*.dist-info
# requirements-board.txt pins 10.4 for boards that ship websockets 9.1, which
# breaks on Python 3.10. Boards with websockets >= 13 keep the system build:
# uvicorn's sansio WebSocket implementation is unavailable in 10.4.
SYSTEM_WS="$(/usr/bin/python3 -c 'import websockets; print(websockets.__version__)' 2>/dev/null || true)"
case "${SYSTEM_WS%%.*}" in
  '' | *[!0-9]*) SYSTEM_WS_MAJOR=0 ;;
  *) SYSTEM_WS_MAJOR="${SYSTEM_WS%%.*}" ;;
esac
if [ "$SYSTEM_WS_MAJOR" -ge 13 ]; then
  echo "using system websockets $SYSTEM_WS"
else
  /usr/bin/python3 -m pip install \
    --disable-pip-version-check \
    --no-deps \
    --target "$VENDOR_SITE" \
    --requirement "$SOURCE_ROOT/requirements-board.txt"
  PYTHONPATH="$VENDOR_SITE" PYTHONNOUSERSITE=1 /usr/bin/python3 -c \
    "import websockets; assert websockets.__version__ == '10.4'; print('websockets', websockets.__version__)"
fi

echo "[4/6] Installing protected environment"
if [ ! -f "$SECRET_FILE" ]; then
  if [ -f "$SOURCE_ROOT/.env" ]; then
    install -m 0600 "$SOURCE_ROOT/.env" "$SECRET_FILE"
  else
    JWT_SECRET="$(openssl rand -hex 32)"
    printf 'RP_DEEPSEEK_API_KEY=\nRP_JWT_SECRET=%s\n' "$JWT_SECRET" >"$SECRET_FILE"
    chmod 0600 "$SECRET_FILE"
  fi
else
  echo "Preserving existing $SECRET_FILE"
fi

echo "[5/6] Installing and enabling systemd unit"
if [ -f /etc/default/rp-server ]; then
  cp -a /etc/default/rp-server /etc/default/rp-server.bak
fi
install -m 0644 "$SOURCE_ROOT/etc/default/rp-server" /etc/default/rp-server
sed -i "s|^RP_ROBOT_CONFIG=.*|RP_ROBOT_CONFIG=$ROBOT_CONFIG|" /etc/default/rp-server
install -m 0644 "$SOURCE_ROOT/etc/systemd/system/rp-server.service" \
  /etc/systemd/system/rp-server.service
install -m 0644 "$SOURCE_ROOT/etc/systemd/system/rp-btwifi.service" \
  /etc/systemd/system/rp-btwifi.service
systemctl daemon-reload
systemctl enable rp-server.service rp-btwifi.service
systemctl restart rp-server.service rp-btwifi.service

echo "[6/6] Verifying service"
sleep 3
if ! systemctl is-active --quiet rp-server.service; then
  systemctl status rp-server.service --no-pager || true
  journalctl -u rp-server.service -n 80 --no-pager || true
  exit 1
fi

curl --fail --silent "http://127.0.0.1:${RP_PORT:-8765}/health"
echo
echo "RP_SERVER_SYSTEMD_OK"
