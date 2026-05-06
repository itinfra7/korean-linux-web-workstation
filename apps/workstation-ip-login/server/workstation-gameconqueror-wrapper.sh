#!/usr/bin/env bash
set -euo pipefail

if [ -z "${HOME:-}" ] || [ "${HOME}" = "/" ]; then
  export HOME="/home/$(id -un)"
fi

export USER="${USER:-$(id -un)}"
export LOGNAME="${LOGNAME:-${USER}}"
export SHELL="${SHELL:-/usr/local/bin/workstation-user-shell}"
export XDG_CONFIG_HOME="${XDG_CONFIG_HOME:-${HOME}/.config}"
export XDG_CACHE_HOME="${XDG_CACHE_HOME:-${HOME}/.cache}"
export XDG_DATA_HOME="${XDG_DATA_HOME:-${HOME}/.local/share}"
mkdir -p "${XDG_CONFIG_HOME}" "${XDG_CACHE_HOME}" "${XDG_DATA_HOME}"

if [ -z "${XAUTHORITY:-}" ] && [ -n "${HOME:-}" ]; then
  export XAUTHORITY="${HOME}/.Xauthority"
fi

if [ -z "${XDG_RUNTIME_DIR:-}" ]; then
  runtime_dir="/run/user/$(id -u)"
  if [ -d "${runtime_dir}" ]; then
    export XDG_RUNTIME_DIR="${runtime_dir}"
  fi
fi

if [ -z "${DBUS_SESSION_BUS_ADDRESS:-}" ] && [ -n "${XDG_RUNTIME_DIR:-}" ] && [ -S "${XDG_RUNTIME_DIR}/bus" ]; then
  export DBUS_SESSION_BUS_ADDRESS="unix:path=${XDG_RUNTIME_DIR}/bus"
fi

cd "${HOME}" 2>/dev/null || true

exec /usr/bin/python3 /usr/share/gameconqueror/GameConqueror.py "$@"
