#!/usr/bin/env bash
set -euo pipefail

export LANG="ko_KR.UTF-8"
export LC_ALL="ko_KR.UTF-8"
export LC_CTYPE="ko_KR.UTF-8"
export LC_MESSAGES="ko_KR.UTF-8"
export LANGUAGE="ko"
export TZ="${TZ:-Asia/Seoul}"
export GTK_OVERLAY_SCROLLING=0
export NO_AT_BRIDGE=1
export XDG_CURRENT_DESKTOP=XFCE
export GTK_IM_MODULE="${GTK_IM_MODULE:-ibus}"
export QT_IM_MODULE="${QT_IM_MODULE:-ibus}"
export XMODIFIERS="${XMODIFIERS:-@im=ibus}"
export SDL_IM_MODULE="${SDL_IM_MODULE:-ibus}"
export GLFW_IM_MODULE="${GLFW_IM_MODULE:-ibus}"
export CLUTTER_IM_MODULE="${CLUTTER_IM_MODULE:-ibus}"
export TERMINAL="${TERMINAL:-xfce4-terminal}"
export BROWSER="${BROWSER:-brave-browser}"
append_path_entry() {
  local entry="$1"
  case ":${PATH:-}:" in
    *:"${entry}":*) ;;
    *) export PATH="${PATH:+${PATH}:}${entry}" ;;
  esac
}

append_path_entry "/usr/games"
append_path_entry "/snap/bin"
case ":${XDG_DATA_DIRS:-}:" in
  *:/var/lib/snapd/desktop:*) ;;
  *) export XDG_DATA_DIRS="${XDG_DATA_DIRS:+${XDG_DATA_DIRS}:}/var/lib/snapd/desktop" ;;
esac
case ":${XDG_DATA_DIRS:-}:" in
  *:/usr/share:*) ;;
  *) export XDG_DATA_DIRS="${XDG_DATA_DIRS:+${XDG_DATA_DIRS}:}/usr/share" ;;
esac
case ":${XDG_DATA_DIRS:-}:" in
  *:/usr/local/share:*) ;;
  *) export XDG_DATA_DIRS="${XDG_DATA_DIRS:+${XDG_DATA_DIRS}:}/usr/local/share" ;;
esac

PASSWD_HOME="$(getent passwd "$(id -un)" | cut -d: -f6)"
HOME_DIR="${HOME:-}"
if [ -z "${HOME_DIR}" ] || [ "${HOME_DIR}" = "/" ] || [ ! -d "${HOME_DIR}" ] || [ ! -w "${HOME_DIR}" ]; then
  HOME_DIR="${PASSWD_HOME}"
fi
export HOME="${HOME_DIR}"
export XDG_CONFIG_HOME="${HOME_DIR}/.config"
export XDG_CACHE_HOME="${HOME_DIR}/.cache"
export XDG_DATA_HOME="${HOME_DIR}/.local/share"
export XAUTHORITY="${XAUTHORITY:-${HOME_DIR}/.Xauthority}"

mkdir -p "${XDG_CONFIG_HOME}" "${XDG_CACHE_HOME}" "${XDG_DATA_HOME}"
cd "${HOME_DIR}"

if command -v pulseaudio >/dev/null 2>&1; then
  pulseaudio --check >/dev/null 2>&1 || pulseaudio --start --daemonize=yes --exit-idle-time=-1 >/dev/null 2>&1 || true
fi

if [ -z "${PULSE_SERVER:-}" ] && [ -S "${XDG_RUNTIME_DIR}/pulse/native" ]; then
  export PULSE_SERVER="unix:${XDG_RUNTIME_DIR}/pulse/native"
fi

run_inner_session() {
  exec dbus-launch --exit-with-session /usr/local/lib/workstation-desktop/workstation-xfce-inner-session.sh
}

run_inner_session
