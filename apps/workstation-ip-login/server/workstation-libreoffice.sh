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
export LANG="ko_KR.UTF-8"
export LANGUAGE="ko"
export LC_ALL="ko_KR.UTF-8"
export LC_CTYPE="ko_KR.UTF-8"
export LC_MESSAGES="ko_KR.UTF-8"
export SAL_UI_LANG="ko"
export SAL_LOCALE="ko-KR"
export TZ="${TZ:-Asia/Seoul}"

SOFFICE_BIN=""
for candidate in \
  /opt/libreoffice26.2/program/soffice \
  /usr/bin/libreoffice26.2 \
  /usr/bin/libreoffice
do
  if [ -x "${candidate}" ]; then
    SOFFICE_BIN="${candidate}"
    break
  fi
done

if [ -z "${SOFFICE_BIN}" ]; then
  printf 'workstation-libreoffice: no usable soffice binary found\n' >&2
  exit 1
fi

PROFILE_DIR="${XDG_CONFIG_HOME}/libreoffice/4/user"
PROFILE_XCU="${PROFILE_DIR}/registrymodifications.xcu"
PROFILE_SEED="/usr/local/share/workstation-desktop/skel/.config/libreoffice/4/user/registrymodifications.xcu"

mkdir -p "${XDG_CONFIG_HOME}" "${XDG_CACHE_HOME}" "${XDG_DATA_HOME}" "${PROFILE_DIR}" "${PROFILE_DIR}/pack"
if [ -e "${PROFILE_XCU}" ] && { [ ! -r "${PROFILE_XCU}" ] || [ ! -w "${PROFILE_XCU}" ]; }; then
  rm -f "${PROFILE_XCU}" || true
fi
if [ -d "${XDG_CACHE_HOME}/dconf" ] && [ ! -w "${XDG_CACHE_HOME}/dconf" ]; then
  rm -rf "${XDG_CACHE_HOME}/dconf" || true
fi
if [ -x /usr/local/lib/workstation-desktop/workstation-libreoffice-profile.py ]; then
  /usr/bin/python3 /usr/local/lib/workstation-desktop/workstation-libreoffice-profile.py \
    --seed "${PROFILE_SEED}" \
    --target "${PROFILE_XCU}"
fi
rm -f "${PROFILE_DIR}/pack/registrymodifications.pack"

cd "${HOME_DIR}"

if [ -n "${DISPLAY:-}" ] && command -v wmctrl >/dev/null 2>&1; then
  export WORKSTATION_LIBREOFFICE_DISPLAY="${DISPLAY}"
  export WORKSTATION_LIBREOFFICE_XAUTHORITY="${XAUTHORITY:-}"
  # Keep the first-run welcome dismiss watcher alive independently of the
  # launcher shell so it still runs after exec hands off to soffice.
  nohup /bin/bash -lc '
    export DISPLAY="${WORKSTATION_LIBREOFFICE_DISPLAY}"
    if [ -n "${WORKSTATION_LIBREOFFICE_XAUTHORITY:-}" ]; then
      export XAUTHORITY="${WORKSTATION_LIBREOFFICE_XAUTHORITY}"
    fi
    for _ in $(seq 1 120); do
      sleep 1
      wmctrl -l 2>/dev/null | grep -q "환영\\|Welcome to LibreOffice!" || continue
      wmctrl -c "환영" 2>/dev/null || true
      wmctrl -c "Welcome to LibreOffice!" 2>/dev/null || true
    done
  ' >/dev/null 2>&1 &
fi

exec "${SOFFICE_BIN}" --language=ko --nofirststartwizard "$@"
