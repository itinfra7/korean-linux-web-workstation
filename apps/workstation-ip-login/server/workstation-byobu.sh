#!/usr/bin/env bash
set -euo pipefail

PASSWD_HOME="$(getent passwd "$(id -un)" | cut -d: -f6)"
HOME_DIR="${HOME:-}"

if [ -z "${HOME_DIR}" ] || [ "${HOME_DIR}" = "/" ] || [ ! -d "${HOME_DIR}" ] || [ ! -w "${HOME_DIR}" ]; then
  HOME_DIR="${PASSWD_HOME}"
fi

export HOME="${HOME_DIR}"
export XDG_CONFIG_HOME="${HOME_DIR}/.config"
export XDG_CACHE_HOME="${HOME_DIR}/.cache"
export XDG_DATA_HOME="${HOME_DIR}/.local/share"
export BYOBU_CONFIG_DIR="${XDG_CONFIG_HOME}/byobu"
export TMUX_TMPDIR="${XDG_CACHE_HOME}/tmux"
export LANG="ko_KR.UTF-8"
export LANGUAGE="ko_KR:ko:en_US:en"
export LC_ALL="ko_KR.UTF-8"
export LC_CTYPE="ko_KR.UTF-8"
export LC_MESSAGES="ko_KR.UTF-8"
export TERM="${TERM:-xterm-256color}"

mkdir -p "${XDG_CONFIG_HOME}" "${XDG_CACHE_HOME}" "${XDG_DATA_HOME}" "${BYOBU_CONFIG_DIR}" "${TMUX_TMPDIR}"
cd "${HOME_DIR}"

exec /usr/bin/byobu "$@"
