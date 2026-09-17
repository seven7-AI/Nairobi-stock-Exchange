#!/usr/bin/env bash
# Install the public dashboard as a user systemd service on port 4747.
#
#   scripts/install_dashboard_service.sh            # render, install, enable --now, wait for /health
#   scripts/install_dashboard_service.sh --print    # show the rendered unit, change nothing
#   scripts/install_dashboard_service.sh --verify   # exit 1 unless enabled, active, current and healthy
#   scripts/install_dashboard_service.sh --build    # build the SPA (npm ci && npm run build) first
#   scripts/install_dashboard_service.sh --restart  # systemctl --user restart
#
# Refuses to install while something else listens on the port: the leftover container
# that held 4747 on this host is stopped explicitly, never silently replaced.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PORT="${DASHBOARD_PORT:-4747}"
UV_BIN="${UV_BIN:-$(command -v uv || echo "${HOME}/.local/bin/uv")}"
UNIT_NAME="nse-dashboard"
TEMPLATE="${REPO_ROOT}/deployment/systemd/${UNIT_NAME}.service"
INSTALLED_COPY="${REPO_ROOT}/deployment/systemd/${UNIT_NAME}.installed"
UNIT_DIR="${HOME}/.config/systemd/user"
UNIT_PATH="${UNIT_DIR}/${UNIT_NAME}.service"
HEALTH_URL="http://127.0.0.1:${PORT}/health"

render() {
  sed -e "s#__REPO_ROOT__#${REPO_ROOT}#g" -e "s#__UV_BIN__#${UV_BIN}#g" -e "s#__PORT__#${PORT}#g" "${TEMPLATE}"
}

port_holder() {
  ss -ltnp 2>/dev/null | awk -v p=":${PORT}" '$4 ~ p"$" {print $0}'
}

build_spa() {
  # nvm is not on PATH in a non-interactive shell
  [[ -s "${HOME}/.nvm/nvm.sh" ]] && . "${HOME}/.nvm/nvm.sh" >/dev/null 2>&1 || true
  command -v npm >/dev/null 2>&1 || { echo "npm not found (install Node 20 via nvm)"; exit 1; }
  ( cd "${REPO_ROOT}/dashboard" \
    && NODE_OPTIONS=--max-old-space-size=1024 nice -n 19 npm ci --no-audit --no-fund --prefer-offline \
    && NODE_OPTIONS=--max-old-space-size=1024 nice -n 19 npm run build )
}

mode="${1:-install}"
case "${mode}" in
  --print)
    render
    exit 0 ;;
  --verify)
    status=0
    systemctl --user is-enabled --quiet "${UNIT_NAME}" && echo "enabled" || { echo "NOT ENABLED"; status=1; }
    systemctl --user is-active --quiet "${UNIT_NAME}" && echo "active" || { echo "NOT ACTIVE"; status=1; }
    if [[ -f "${UNIT_PATH}" ]] && diff -q <(render) "${UNIT_PATH}" >/dev/null; then
      echo "installed unit is current"
    else
      echo "INSTALLED UNIT DIFFERS FROM THE TEMPLATE (rerun the installer)"; status=1
    fi
    if curl -fsS --max-time 10 "${HEALTH_URL}" >/dev/null; then
      echo "health OK at ${HEALTH_URL}"
    else
      echo "HEALTH FAILED at ${HEALTH_URL}"; status=1
    fi
    if [[ -f "${REPO_ROOT}/dashboard/dist/index.html" ]]; then
      echo "dashboard build present"
    else
      echo "dashboard build missing (dashboard/dist/index.html) - the API is served without the SPA"
    fi
    exit "${status}" ;;
  --restart)
    systemctl --user restart "${UNIT_NAME}"
    echo "restarted ${UNIT_NAME}"
    exit 0 ;;
  --build)
    build_spa
    if systemctl --user is-active --quiet "${UNIT_NAME}"; then
      systemctl --user restart "${UNIT_NAME}"
      echo "built the dashboard and restarted ${UNIT_NAME}"
    else
      echo "built the dashboard (service not running; run the installer)"
    fi
    exit 0 ;;
  install) ;;
  *) echo "usage: $0 [--print|--verify|--build|--restart]"; exit 2 ;;
esac

if ! systemctl --user is-active --quiet "${UNIT_NAME}"; then
  holder="$(port_holder)"
  if [[ -n "${holder}" ]]; then
    echo "port ${PORT} is already in use:"
    echo "${holder}"
    echo "stop that process first (docker ps / docker stop for a container)."
    exit 1
  fi
fi
linger="$(loginctl show-user "${USER}" -p Linger --value 2>/dev/null || echo unknown)"
if [[ "${linger}" != "yes" ]]; then
  echo "lingering is '${linger}' for ${USER}: the service would stop at logout."
  echo "run once (needs sudo): sudo loginctl enable-linger ${USER}"
  exit 1
fi
mkdir -p "${UNIT_DIR}"
render > "${UNIT_PATH}"
render > "${INSTALLED_COPY}"
systemctl --user daemon-reload
systemctl --user enable --now "${UNIT_NAME}"
systemctl --user restart "${UNIT_NAME}"
for _ in $(seq 1 40); do
  if curl -fsS --max-time 5 "${HEALTH_URL}" >/dev/null 2>&1; then
    ip="$(hostname -I 2>/dev/null | awk '{print $1}')"
    echo "${UNIT_NAME} is up: http://${ip:-127.0.0.1}:${PORT}/  (logs: journalctl --user -u ${UNIT_NAME} -f)"
    exit 0
  fi
  sleep 3
done
echo "${UNIT_NAME} did not answer at ${HEALTH_URL} within 120 s; see: journalctl --user -u ${UNIT_NAME} -n 50"
exit 1
