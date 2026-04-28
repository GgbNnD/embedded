#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLIENT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
LOG_FILE="${CLIENT_ROOT}/client_autostart.log"
DEFAULT_CONDA_PYTHON="${HOME}/miniconda3/envs/alg/bin/python"

if [[ -n "${CLIENT_PYTHON_BIN:-}" ]]; then
  PYTHON_BIN="${CLIENT_PYTHON_BIN}"
elif [[ -x "${CLIENT_ROOT}/.venv/bin/python" ]]; then
  PYTHON_BIN="${CLIENT_ROOT}/.venv/bin/python"
elif [[ -x "${DEFAULT_CONDA_PYTHON}" ]]; then
  PYTHON_BIN="${DEFAULT_CONDA_PYTHON}"
else
  PYTHON_BIN="$(command -v python3)"
fi

cd "${CLIENT_ROOT}"

{
  echo "==== $(date '+%Y-%m-%d %H:%M:%S') ===="
  echo "CLIENT_ROOT=${CLIENT_ROOT}"
  echo "PYTHON_BIN=${PYTHON_BIN}"
  "${PYTHON_BIN}" --version
  "${PYTHON_BIN}" -c "import cv2, tkinter; print('cv2_ok', cv2.__version__)"
} >>"${LOG_FILE}" 2>&1

exec "${PYTHON_BIN}" "${CLIENT_ROOT}/scripts/run_client" \
  --camera-backend rpicam \
  --server-host 10.162.81.70 \
  --server-port 9000 \
  >>"${LOG_FILE}" 2>&1
