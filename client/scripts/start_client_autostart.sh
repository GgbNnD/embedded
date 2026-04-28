#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLIENT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
LOG_FILE="${CLIENT_ROOT}/client_autostart.log"

cd "${CLIENT_ROOT}"

exec /usr/bin/env python3 "${CLIENT_ROOT}/scripts/run_client" \
  --camera-backend rpicam \
  --server-host 10.162.81.70 \
  --server-port 9000 \
  >>"${LOG_FILE}" 2>&1
