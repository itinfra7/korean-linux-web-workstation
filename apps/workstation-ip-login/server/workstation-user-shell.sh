#!/usr/bin/env bash
set -euo pipefail

PASSWD_HOME="$(getent passwd "$(id -un)" | cut -d: -f6)"
HOME_DIR="${HOME:-}"
START_DIR="${PWD:-}"

if [ -z "${HOME_DIR}" ] || [ "${HOME_DIR}" = "/" ] || [ ! -d "${HOME_DIR}" ] || [ ! -w "${HOME_DIR}" ]; then
  HOME_DIR="${PASSWD_HOME}"
fi

export HOME="${HOME_DIR}"
export SHELL="/bin/bash"
export XDG_CONFIG_HOME="${HOME_DIR}/.config"
export XDG_CACHE_HOME="${HOME_DIR}/.cache"
export XDG_DATA_HOME="${HOME_DIR}/.local/share"
export LANG="ko_KR.UTF-8"
export LC_ALL="ko_KR.UTF-8"
export LC_CTYPE="ko_KR.UTF-8"
export LC_MESSAGES="ko_KR.UTF-8"
export LANGUAGE="ko"

if [ -z "$START_DIR" ] || [ "$START_DIR" = "/" ] || [ ! -d "$START_DIR" ]; then
  START_DIR="${HOME_DIR}"
fi

mkdir -p "${XDG_CONFIG_HOME}" "${XDG_CACHE_HOME}" "${XDG_DATA_HOME}"
if ! cd "${START_DIR}" 2>/dev/null; then
  cd "${HOME_DIR}"
fi

if [ "$#" -gt 0 ]; then
  exec "$@"
fi

exec /bin/bash -l
