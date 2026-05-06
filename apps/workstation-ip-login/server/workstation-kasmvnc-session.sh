#!/usr/bin/env bash
set -euo pipefail

MODE="${1:-start}"
USERNAME="${2:-${WORKSTATION_DESKTOP_USERNAME:-}}"

: "${USERNAME:?missing username}"

compute_display_from_uid() {
  local uid_num="$1"
  if ! [[ "$uid_num" =~ ^[0-9]+$ ]]; then
    return 1
  fi
  if [ "$uid_num" -ge 50000 ]; then
    printf '%s\n' "$((uid_num - 50000 + 100))"
  else
    printf '%s\n' "$((uid_num - 20000 + 10000))"
  fi
}

default_home_real="/var/lib/workstation-desktop/users/${USERNAME}/home"
default_state_dir="/var/lib/workstation-desktop/users/${USERNAME}"
default_base_rootfs="/var/lib/workstation-desktop/rootfs-base"
default_runtime_dir="/run/workstation-desktop/${USERNAME}"

WORKSTATION_DESKTOP_HOME_REAL="${WORKSTATION_DESKTOP_HOME_REAL:-${default_home_real}}"
WORKSTATION_DESKTOP_STATE_DIR="${WORKSTATION_DESKTOP_STATE_DIR:-${default_state_dir}}"
WORKSTATION_DESKTOP_BASE_ROOTFS="${WORKSTATION_DESKTOP_BASE_ROOTFS:-${default_base_rootfs}}"
WORKSTATION_DESKTOP_RUNTIME_DIR="${WORKSTATION_DESKTOP_RUNTIME_DIR:-${default_runtime_dir}}"

if [ -z "${WORKSTATION_DESKTOP_UID:-}" ] && [ -d "${WORKSTATION_DESKTOP_HOME_REAL}" ]; then
  WORKSTATION_DESKTOP_UID="$(stat -c '%u' "${WORKSTATION_DESKTOP_HOME_REAL}" 2>/dev/null || true)"
fi
if [ -z "${WORKSTATION_DESKTOP_GID:-}" ] && [ -d "${WORKSTATION_DESKTOP_HOME_REAL}" ]; then
  WORKSTATION_DESKTOP_GID="$(stat -c '%g' "${WORKSTATION_DESKTOP_HOME_REAL}" 2>/dev/null || true)"
fi
WORKSTATION_DESKTOP_UID="${WORKSTATION_DESKTOP_UID:-$(id -u "$USERNAME" 2>/dev/null || true)}"
WORKSTATION_DESKTOP_GID="${WORKSTATION_DESKTOP_GID:-$(id -g "$USERNAME" 2>/dev/null || true)}"
if [ -z "${KASMVNC_DISPLAY:-}" ] && [ -n "${WORKSTATION_DESKTOP_UID:-}" ]; then
  KASMVNC_DISPLAY="$(compute_display_from_uid "${WORKSTATION_DESKTOP_UID}")"
fi

if [ "$MODE" = "stop" ]; then
  :
else
  : "${WORKSTATION_DESKTOP_UID:?missing WORKSTATION_DESKTOP_UID}"
  : "${WORKSTATION_DESKTOP_GID:?missing WORKSTATION_DESKTOP_GID}"
  : "${WORKSTATION_DESKTOP_HOME_REAL:?missing WORKSTATION_DESKTOP_HOME_REAL}"
  : "${WORKSTATION_DESKTOP_STATE_DIR:?missing WORKSTATION_DESKTOP_STATE_DIR}"
  : "${WORKSTATION_DESKTOP_BASE_ROOTFS:?missing WORKSTATION_DESKTOP_BASE_ROOTFS}"
  : "${WORKSTATION_DESKTOP_RUNTIME_DIR:?missing WORKSTATION_DESKTOP_RUNTIME_DIR}"
  : "${KASMVNC_DISPLAY:?missing KASMVNC_DISPLAY}"
fi

UID_NUM="${WORKSTATION_DESKTOP_UID}"
GID_NUM="${WORKSTATION_DESKTOP_GID}"
HOME_REAL="${WORKSTATION_DESKTOP_HOME_REAL}"
STATE_DIR="${WORKSTATION_DESKTOP_STATE_DIR}"
BASE_ROOTFS="${WORKSTATION_DESKTOP_BASE_ROOTFS}"
RUNTIME_DIR="${WORKSTATION_DESKTOP_RUNTIME_DIR}"
UPPER_DIR="${STATE_DIR}/rootfs/upper"
WORK_DIR="${STATE_DIR}/rootfs/work"
MERGED_ROOT="${RUNTIME_DIR}/root"

log() {
  printf '[workstation-kasmvnc-session] %s\n' "$*" >&2
}

die() {
  log "ERROR: $*"
  exit 1
}

require_root() {
  [ "$(id -u)" -eq 0 ] || die "must run as root"
}

proc_mount_options() {
  local current_opts filtered_opts proc_gid
  current_opts="$(findmnt -no OPTIONS /proc 2>/dev/null || true)"
  filtered_opts="$(
    printf '%s\n' "${current_opts}" \
      | tr ',' '\n' \
      | grep -E '^(rw|nosuid|nodev|noexec|relatime)$' \
      | paste -sd, - \
      || true
  )"
  proc_gid="$(
    printf '%s\n' "${current_opts}" \
      | tr ',' '\n' \
      | sed -n 's/^gid=//p' \
      | head -n1
  )"
  if printf '%s\n' "${current_opts}" | tr ',' '\n' | grep -Eq '^hidepid='; then
    filtered_opts="${filtered_opts:+${filtered_opts},}hidepid=2"
  fi
  if [ -n "${proc_gid}" ]; then
    filtered_opts="${filtered_opts:+${filtered_opts},}gid=${proc_gid}"
  fi
  if [ -n "${filtered_opts}" ]; then
    printf '%s\n' "${filtered_opts}"
  else
    printf '%s\n' "rw,nosuid,nodev,noexec,relatime"
  fi
}

mount_bind_rw() {
  local source="$1"
  local target="$2"
  mkdir -p "$target"
  mount --rbind "$source" "$target"
}

mount_bind_ro() {
  local source="$1"
  local target="$2"
  mkdir -p "$target"
  mount --rbind "$source" "$target"
  mount -o remount,bind,ro "$target" >/dev/null 2>&1 || true
}

mount_bind_file_rw() {
  local source="$1"
  local target="$2"
  mkdir -p "$(dirname "$target")"
  [ -e "$target" ] || : >"$target"
  mount --bind "$source" "$target"
}

mount_bind_file_ro() {
  local source="$1"
  local target="$2"
  mkdir -p "$(dirname "$target")"
  [ -e "$target" ] || : >"$target"
  mount --bind "$source" "$target"
  mount -o remount,bind,ro "$target" >/dev/null 2>&1 || true
}

replace_runtime_file_from_host() {
  local source="$1"
  local target="$2"
  local target_dir tmp_file
  target_dir="$(dirname "$target")"
  tmp_file="${target}.tmp.$$"
  mkdir -p "$target_dir"
  rm -f "$target" "$tmp_file"
  cat "$source" >"$tmp_file"
  chmod 644 "$tmp_file" >/dev/null 2>&1 || true
  chown root:root "$tmp_file" >/dev/null 2>&1 || true
  mv -fT "$tmp_file" "$target"
}

write_runtime_etc() {
  local primary_group
  primary_group="$(id -gn "$USERNAME")"

  install -d -m 755 "${MERGED_ROOT}/etc" "${MERGED_ROOT}/var/lib/dbus"

  rm -f "${MERGED_ROOT}/etc/passwd"
  cat >"${MERGED_ROOT}/etc/passwd" <<EOF
root:x:0:0:root:/root:/bin/bash
${USERNAME}:x:${UID_NUM}:${GID_NUM}:${USERNAME}:/home/${USERNAME}:/usr/local/bin/workstation-user-shell
nobody:x:65534:65534:nobody:/nonexistent:/usr/sbin/nologin
EOF

  rm -f "${MERGED_ROOT}/etc/group"
  cat >"${MERGED_ROOT}/etc/group" <<EOF
root:x:0:
${primary_group}:x:${GID_NUM}:${USERNAME}
nogroup:x:65534:
EOF

  local workspace_public_domain="${WORKSTATION_PUBLIC_DOMAIN:-example.com}"

  rm -f "${MERGED_ROOT}/etc/hosts"
  cat >"${MERGED_ROOT}/etc/hosts" <<EOF
127.0.0.1 localhost ${workspace_public_domain}
127.0.1.1 workstation-workspace
::1 localhost ip6-localhost ip6-loopback
EOF

  replace_runtime_file_from_host /etc/resolv.conf "${MERGED_ROOT}/etc/resolv.conf"
  replace_runtime_file_from_host /etc/nsswitch.conf "${MERGED_ROOT}/etc/nsswitch.conf"
  if [ -f /etc/machine-id ]; then
    replace_runtime_file_from_host /etc/machine-id "${MERGED_ROOT}/etc/machine-id"
    replace_runtime_file_from_host /etc/machine-id "${MERGED_ROOT}/var/lib/dbus/machine-id"
  fi
  if [ -f /etc/timezone ]; then
    replace_runtime_file_from_host /etc/timezone "${MERGED_ROOT}/etc/timezone"
  fi
  if [ -e /etc/localtime ]; then
    replace_runtime_file_from_host /etc/localtime "${MERGED_ROOT}/etc/localtime"
  fi
  ln -sfn /proc/self/mounts "${MERGED_ROOT}/etc/mtab"
}

prepare_host_namespace_views() {
  install -d -m 755 /home
  mount -t tmpfs -o "mode=755,nosuid,nodev" tmpfs /home
  mount_bind_rw "${HOME_REAL}" "/home/${USERNAME}"
}

start_snap_bridge() {
  local socket_path
  socket_path="${HOME_REAL}/.local/share/workstation-snap/bridge.sock"
  install -d -m 700 -o "${UID_NUM}" -g "${GID_NUM}" "${HOME_REAL}/.local/share/workstation-snap"
  rm -f "$socket_path"

  /usr/bin/setpriv --reuid="${UID_NUM}" --regid="${GID_NUM}" --init-groups \
    /usr/bin/env \
      HOME="/home/${USERNAME}" \
      USER="${USERNAME}" \
      LOGNAME="${USERNAME}" \
      WORKSTATION_SNAP_BRIDGE_SOCKET="/home/${USERNAME}/.local/share/workstation-snap/bridge.sock" \
      WORKSTATION_SNAP_LAUNCHERS_DIR="/usr/local/share/workstation-desktop/snap-launchers" \
      WORKSTATION_SNAP_USERNAME="${USERNAME}" \
      WORKSTATION_SNAP_HOME="/home/${USERNAME}" \
      WORKSTATION_SNAP_DISPLAY=":${KASMVNC_DISPLAY}" \
      WORKSTATION_SNAP_XAUTHORITY="/home/${USERNAME}/.Xauthority" \
      WORKSTATION_SNAP_XDG_RUNTIME_DIR="/run/user/${UID_NUM}" \
      WORKSTATION_SNAP_PULSE_SERVER="unix:/run/user/${UID_NUM}/pulse/native" \
      WORKSTATION_SNAP_TZ="${TZ:-Asia/Seoul}" \
      WORKSTATION_SNAP_GTK_IM_MODULE="ibus" \
      WORKSTATION_SNAP_QT_IM_MODULE="ibus" \
      WORKSTATION_SNAP_XMODIFIERS="@im=ibus" \
      WORKSTATION_SNAP_SDL_IM_MODULE="ibus" \
      WORKSTATION_SNAP_GLFW_IM_MODULE="ibus" \
      WORKSTATION_SNAP_CLUTTER_IM_MODULE="ibus" \
      PATH="/usr/local/bin:/usr/bin:/bin:/usr/games:/usr/local/sbin:/usr/sbin:/sbin:/snap/bin" \
      LANG="ko_KR.UTF-8" \
      LANGUAGE="ko" \
      LC_ALL="ko_KR.UTF-8" \
      /usr/bin/python3 /usr/local/lib/workstation-desktop/workstation-snap-bridge.py &
}

prepare_mounts() {
  install -d -m 755 "$RUNTIME_DIR" "$MERGED_ROOT" "$UPPER_DIR" "$WORK_DIR"
  install -d -m 700 "$HOME_REAL"

  mount -t overlay overlay -o "lowerdir=${BASE_ROOTFS},upperdir=${UPPER_DIR},workdir=${WORK_DIR}" "${MERGED_ROOT}"

  install -d -m 755 \
    "${MERGED_ROOT}/usr" \
    "${MERGED_ROOT}/bin" \
    "${MERGED_ROOT}/sbin" \
    "${MERGED_ROOT}/lib" \
    "${MERGED_ROOT}/lib64" \
    "${MERGED_ROOT}/usr/local" \
    "${MERGED_ROOT}/opt" \
    "${MERGED_ROOT}/snap" \
    "${MERGED_ROOT}/etc/kasmvnc" \
    "${MERGED_ROOT}/proc" \
    "${MERGED_ROOT}/dev" \
    "${MERGED_ROOT}/sys" \
    "${MERGED_ROOT}/tmp" \
    "${MERGED_ROOT}/run" \
    "${MERGED_ROOT}/home/${USERNAME}" \
    "${MERGED_ROOT}/var/tmp" \
    "${MERGED_ROOT}/var/snap" \
    "${MERGED_ROOT}/var/lib/snapd"

  mount_bind_ro /usr "${MERGED_ROOT}/usr"
  mount_bind_ro /bin "${MERGED_ROOT}/bin"
  mount_bind_ro /sbin "${MERGED_ROOT}/sbin"
  mount_bind_ro /lib "${MERGED_ROOT}/lib"
  if [ -d /lib64 ]; then
    mount_bind_ro /lib64 "${MERGED_ROOT}/lib64"
  fi
  if [ -d /usr/local ]; then
    mount_bind_ro /usr/local "${MERGED_ROOT}/usr/local"
  fi
  if [ -d /opt ]; then
    mount_bind_ro /opt "${MERGED_ROOT}/opt"
  fi
  if [ -d /snap ]; then
    mount_bind_ro /snap "${MERGED_ROOT}/snap"
  fi
  if [ -d /etc/kasmvnc ]; then
    mount_bind_ro /etc/kasmvnc "${MERGED_ROOT}/etc/kasmvnc"
  fi
  if [ -d /var/lib/snapd ]; then
    mount_bind_ro /var/lib/snapd "${MERGED_ROOT}/var/lib/snapd"
  fi
  if [ -d /var/snap ]; then
    mount_bind_rw /var/snap "${MERGED_ROOT}/var/snap"
  fi

  mount -t proc -o "$(proc_mount_options)" proc "${MERGED_ROOT}/proc"
  mount_bind_rw /dev "${MERGED_ROOT}/dev"
  if [ -d /sys ]; then
    mount_bind_ro /sys "${MERGED_ROOT}/sys"
  fi

  mount -t tmpfs -o "mode=1777,nosuid,nodev" tmpfs "${MERGED_ROOT}/tmp"
  mount -t tmpfs -o "mode=755,nosuid,nodev" tmpfs "${MERGED_ROOT}/run"
  mount -t tmpfs -o "mode=1777,nosuid,nodev" tmpfs "${MERGED_ROOT}/var/tmp"

  if [ -S /run/dbus/system_bus_socket ]; then
    mount_bind_file_rw /run/dbus/system_bus_socket "${MERGED_ROOT}/run/dbus/system_bus_socket"
  fi

  install -d -m 700 -o "${UID_NUM}" -g "${GID_NUM}" "/run/user/${UID_NUM}" "${MERGED_ROOT}/run/user/${UID_NUM}"
  if [ -d "/run/user/${UID_NUM}" ]; then
    mount_bind_rw "/run/user/${UID_NUM}" "${MERGED_ROOT}/run/user/${UID_NUM}"
  fi

  if [ -d /run/snapd ]; then
    mount_bind_rw /run/snapd "${MERGED_ROOT}/run/snapd"
  fi
  if [ -S /run/snapd.socket ]; then
    mount_bind_file_rw /run/snapd.socket "${MERGED_ROOT}/run/snapd.socket"
  fi
  if [ -S /run/snapd-snap.socket ]; then
    mount_bind_file_rw /run/snapd-snap.socket "${MERGED_ROOT}/run/snapd-snap.socket"
  fi

  mount_bind_rw "${HOME_REAL}" "${MERGED_ROOT}/home/${USERNAME}"

  write_runtime_etc
  prepare_host_namespace_views
}

start_session() {
  require_root
  [ -d "$BASE_ROOTFS" ] || die "missing base rootfs ${BASE_ROOTFS}"
  [ -d "$HOME_REAL" ] || die "missing workspace home ${HOME_REAL}"

  prepare_mounts
  start_snap_bridge

  exec chroot --userspec="${UID_NUM}:${GID_NUM}" "${MERGED_ROOT}" /usr/bin/env -i \
    HOME="/home/${USERNAME}" \
    USER="${USERNAME}" \
    LOGNAME="${USERNAME}" \
    SHELL="/usr/local/bin/workstation-user-shell" \
    XAUTHORITY="/home/${USERNAME}/.Xauthority" \
    PATH="/usr/local/bin:/usr/bin:/bin:/usr/games:/usr/local/sbin:/usr/sbin:/sbin:/snap/bin" \
    LANG="ko_KR.UTF-8" \
    LANGUAGE="ko" \
    LC_ALL="ko_KR.UTF-8" \
    XDG_RUNTIME_DIR="/run/user/${UID_NUM}" \
    XDG_DATA_DIRS="/usr/share/gnome:/usr/local/share:/usr/share:/var/lib/snapd/desktop" \
    /usr/bin/vncserver ":${KASMVNC_DISPLAY}" -fg -autokill -geometry 1440x900 -depth 24 -xstartup /usr/local/lib/workstation-desktop/workstation-xfce-session.sh
}

stop_session() {
  require_root
  if [ -d "${MERGED_ROOT}/home/${USERNAME}" ]; then
    chroot --userspec="${UID_NUM}:${GID_NUM}" "${MERGED_ROOT}" /usr/bin/vncserver -kill ":${KASMVNC_DISPLAY}" >/dev/null 2>&1 || true
  fi
}

case "$MODE" in
  start)
    start_session
    ;;
  stop)
    stop_session
    ;;
  *)
    die "unsupported mode ${MODE}"
    ;;
esac
