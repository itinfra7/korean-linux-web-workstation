#!/usr/bin/env bash
set -euo pipefail

DESKTOP_FILE="${HOME}/Desktop/03-workstation-trash.desktop"
LOCAL_TRASH_DIR="${HOME}/.local/share/Trash/files"

start_gvfs_metadata() {
  local candidate
  for candidate in gvfsd-metadata /usr/libexec/gvfsd-metadata /usr/lib/gvfs/gvfsd-metadata; do
    if command -v "${candidate}" >/dev/null 2>&1; then
      "${candidate}" >/dev/null 2>&1 &
      return 0
    fi
  done
  return 1
}

ensure_trusted_trash_launcher() {
  local checksum
  [ -f "${DESKTOP_FILE}" ] || return 1
  chmod 755 "${DESKTOP_FILE}" >/dev/null 2>&1 || true
  command -v gio >/dev/null 2>&1 || return 0

  mkdir -p "${HOME}/.local/share/gvfs-metadata"
  chmod 700 "${HOME}/.local/share/gvfs-metadata" >/dev/null 2>&1 || true
  start_gvfs_metadata || true

  checksum="$(sha256sum "${DESKTOP_FILE}" | awk '{print $1}')"
  gio set "${DESKTOP_FILE}" metadata::trusted yes >/dev/null 2>&1 || return 1
  gio set "${DESKTOP_FILE}" metadata::xfce-exe-checksum "${checksum}" >/dev/null 2>&1 || return 1
  gio info -a metadata::xfce-exe-checksum "${DESKTOP_FILE}" 2>/dev/null | grep -Fq "${checksum}"
}

wait_for_desktop_file() {
  local _attempt
  for _attempt in $(seq 1 60); do
    if [ -f "${DESKTOP_FILE}" ]; then
      return 0
    fi
    sleep 1
  done
  return 1
}

trash_has_items() {
  local first_entry=""
  if command -v gio >/dev/null 2>&1; then
    first_entry="$(gio list trash:// 2>/dev/null | sed -n '1p' || true)"
    if [ -n "${first_entry}" ]; then
      return 0
    fi
    if gio info trash:// >/dev/null 2>&1; then
      return 1
    fi
  fi
  find "${LOCAL_TRASH_DIR}" -mindepth 1 -maxdepth 1 -print -quit 2>/dev/null | grep -q .
}

desired_trash_icon() {
  if trash_has_items; then
    printf '%s\n' 'user-trash-full'
  else
    printf '%s\n' 'user-trash'
  fi
}

reload_desktop() {
  local _attempt
  command -v xfdesktop >/dev/null 2>&1 || return 0
  for _attempt in $(seq 1 10); do
    if xfdesktop --reload >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
  done
  return 1
}

apply_trash_launcher_icon_state() {
  local icon_name current_icon
  [ -f "${DESKTOP_FILE}" ] || return 1
  icon_name="$(desired_trash_icon)"
  current_icon="$(sed -n 's/^Icon=//p' "${DESKTOP_FILE}" | head -n 1)"
  if [ "${current_icon}" = "${icon_name}" ]; then
    ensure_trusted_trash_launcher || true
    return 1
  fi
  if grep -q '^Icon=' "${DESKTOP_FILE}"; then
    sed -i "s/^Icon=.*/Icon=${icon_name}/" "${DESKTOP_FILE}" >/dev/null 2>&1 || return 1
  else
    printf '\nIcon=%s\n' "${icon_name}" >>"${DESKTOP_FILE}" || return 1
  fi
  ensure_trusted_trash_launcher || true
  reload_desktop || true
  return 0
}

monitor_with_gio() {
  local location="$1"
  if command -v stdbuf >/dev/null 2>&1; then
    while IFS= read -r _event_line; do
      apply_trash_launcher_icon_state || true
    done < <(stdbuf -oL -eL gio monitor -d "${location}" 2>/dev/null)
  else
    while IFS= read -r _event_line; do
      apply_trash_launcher_icon_state || true
    done < <(gio monitor -d "${location}" 2>/dev/null)
  fi
}

run_event_loop() {
  while true; do
    apply_trash_launcher_icon_state || true
    if command -v gio >/dev/null 2>&1 && [ -d "${LOCAL_TRASH_DIR}" ]; then
      monitor_with_gio "${LOCAL_TRASH_DIR}"
      sleep 1
      continue
    fi
    if command -v gio >/dev/null 2>&1; then
      if gio info trash:// >/dev/null 2>&1; then
        monitor_with_gio 'trash://'
        sleep 1
        continue
      fi
    fi
    sleep 10
  done
}

main() {
  wait_for_desktop_file || exit 0
  case "${1:-}" in
    --once)
      apply_trash_launcher_icon_state || true
      ;;
    *)
      run_event_loop
      ;;
  esac
}

main "$@"
