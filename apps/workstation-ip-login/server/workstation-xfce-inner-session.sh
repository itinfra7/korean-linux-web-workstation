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
export XAUTHORITY="${XAUTHORITY:-${HOME:-/home/$(id -un)}/.Xauthority}"

if command -v ibus-daemon >/dev/null 2>&1; then
  ibus-daemon -drxR >/dev/null 2>&1 &
  sleep 1
  ibus engine hangul >/dev/null 2>&1 || true
fi

(/usr/local/lib/workstation-desktop/workstation-xfce-poststart.sh >/dev/null 2>&1 &) 
exec startxfce4
