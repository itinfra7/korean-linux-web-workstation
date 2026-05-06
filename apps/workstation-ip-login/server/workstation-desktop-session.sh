#!/usr/bin/env bash
set -euo pipefail

SUDOERS_USER="workstation-login"
SKEL_DIR="/usr/local/share/workstation-desktop/skel"
RUNTIME_ROOT="/run/workstation-desktop"
STATE_ROOT="/var/lib/workstation-desktop/users"
SNAPSHOT_ROOT="/backup/workspace-snapshots"
ROOTFS_BASE="/var/lib/workstation-desktop/rootfs-base"
UNIT_NAME="workstation-kasmvnc@"
CONFIG_ENV_FILE="/etc/workstation-ip-login.env"
LOCK_ROOT="${RUNTIME_ROOT}/locks"
LEGACY_SHARED_HOME_NAME="공유"

die() {
  printf 'workstation-desktop-session: %s\n' "$*" >&2
  exit 1
}

require_root() {
  [ "$(id -u)" -eq 0 ] || die "must run as root"
}

require_ldap_user() {
  local username="$1"
  ldap-user show "$username" >/dev/null 2>&1 || die "LDAP user ${username} does not exist"
}

primary_group_name() {
  local username="$1"
  id -gn "$username"
}

uid_number() {
  local username="$1"
  id -u "$username"
}

gid_number() {
  local username="$1"
  id -g "$username"
}

process_env_value() {
  local pid="$1"
  local key="$2"
  [ -n "$pid" ] || return 1
  [ -r "/proc/${pid}/environ" ] || return 1
  tr '\0' '\n' <"/proc/${pid}/environ" | awk -F= -v target="$key" '$1 == target { sub(/^[^=]*=/, ""); print; exit }'
}

session_bus_address() {
  local username="$1"
  local session_pid bus_address

  session_pid="$(pgrep -u "$username" -n xfce4-session 2>/dev/null || true)"
  if [[ "$session_pid" =~ ^[1-9][0-9]*$ ]]; then
    bus_address="$(process_env_value "$session_pid" "DBUS_SESSION_BUS_ADDRESS" || true)"
    if [ -n "$bus_address" ]; then
      printf '%s\n' "$bus_address"
      return 0
    fi
  fi

  printf 'unix:path=/run/user/%s/bus\n' "$(uid_number "$username")"
}

workspace_state_dir() {
  local username="$1"
  printf '%s/%s\n' "$STATE_ROOT" "$username"
}

workspace_home_dir() {
  local username="$1"
  printf '%s/home\n' "$(workspace_state_dir "$username")"
}

login_home_dir() {
  local username="$1"
  printf '/home/%s\n' "$username"
}

workspace_rootfs_upper() {
  local username="$1"
  printf '%s/rootfs/upper\n' "$(workspace_state_dir "$username")"
}

workspace_rootfs_work() {
  local username="$1"
  printf '%s/rootfs/work\n' "$(workspace_state_dir "$username")"
}

runtime_dir() {
  local username="$1"
  printf '%s/%s\n' "$RUNTIME_ROOT" "$username"
}

user_lock_path() {
  local username="$1"
  printf '%s/%s.lock\n' "$LOCK_ROOT" "$username"
}

with_user_lock() {
  local username="$1"
  shift
  local lock_path lock_fd status
  install -d -m 755 "$LOCK_ROOT"
  lock_path="$(user_lock_path "$username")"
  exec {lock_fd}>"$lock_path"
  flock "$lock_fd"
  "$@"
  status=$?
  flock -u "$lock_fd" || true
  exec {lock_fd}>&-
  return "$status"
}

snapshot_user_dir() {
  local username="$1"
  printf '%s/%s\n' "$SNAPSHOT_ROOT" "$username"
}

snapshot_home_dir() {
  local username="$1"
  local snapshot_id="$2"
  printf '%s/%s/home\n' "$(snapshot_user_dir "$username")" "$snapshot_id"
}

snapshot_upper_dir() {
  local username="$1"
  local snapshot_id="$2"
  printf '%s/%s/rootfs/upper\n' "$(snapshot_user_dir "$username")" "$snapshot_id"
}

snapshot_metadata_path() {
  local username="$1"
  local snapshot_id="$2"
  printf '%s/%s/metadata.json\n' "$(snapshot_user_dir "$username")" "$snapshot_id"
}

snapshot_title_default() {
  local created_at_display="$1"
  printf '%s\n' "$created_at_display"
}

desktop_display() {
  local username="$1"
  local uid_num
  uid_num="$(uid_number "$username")"
  if ! [[ "$uid_num" =~ ^[0-9]+$ ]]; then
    die "invalid uid for ${username}"
  fi
  if [ "$uid_num" -lt 20000 ] || [ "$uid_num" -gt 65535 ]; then
    die "uid ${uid_num} cannot be mapped safely to a desktop display"
  fi
  if [ "$uid_num" -ge 50000 ]; then
    printf '%s\n' "$((uid_num - 50000 + 100))"
  else
    printf '%s\n' "$((uid_num - 20000 + 10000))"
  fi
}

desktop_port() {
  local username="$1"
  local display_num
  display_num="$(desktop_display "$username")"
  printf '%s\n' "$((8443 + display_num))"
}

load_proxy_credentials() {
  [ -r "$CONFIG_ENV_FILE" ] || die "missing config env file ${CONFIG_ENV_FILE}"
  # shellcheck disable=SC1090
  source "$CONFIG_ENV_FILE"
  [ -n "${WORKSTATION_IPLOGIN_DESKTOP_PROXY_USER:-}" ] || die "missing desktop proxy user"
  [ -n "${WORKSTATION_IPLOGIN_DESKTOP_PROXY_PASSWORD:-}" ] || die "missing desktop proxy password"
}

workspace_users() {
  [ -d "$STATE_ROOT" ] || return 0
  find "$STATE_ROOT" -mindepth 1 -maxdepth 1 -type d -printf '%f\n' | sort -u
}

service_name() {
  local username="$1"
  printf '%s%s.service\n' "$UNIT_NAME" "$username"
}

service_main_pid() {
  local username="$1"
  systemctl show -p MainPID --value "$(service_name "$username")"
}

require_active_session() {
  local username="$1"
  systemctl is-active --quiet "$(service_name "$username")" || die "desktop session not active for ${username}"
}

ensure_workspace_home() {
  local username="$1"
  local group_name="$2"
  local state_dir user_home
  state_dir="$(workspace_state_dir "$username")"
  user_home="$(workspace_home_dir "$username")"

  install -d -m 755 "$STATE_ROOT" "$state_dir"
  install -d -m 700 -o "$username" -g "$group_name" \
    "$user_home" \
    "$user_home/Desktop" \
    "$user_home/문서" \
    "$user_home/다운로드" \
    "$user_home/.cache" \
    "$user_home/.config" \
    "$user_home/.config/Thunar" \
    "$user_home/.config/gtk-3.0" \
    "$user_home/.config/xfce4" \
    "$user_home/.config/xfce4/panel" \
    "$user_home/.config/xfce4/xfconf/xfce-perchannel-xml" \
    "$user_home/.local/share" \
    "$user_home/.local/share/workstation-transfer" \
    "$user_home/.local/share/workstation-transfer/clipboard" \
    "$user_home/.local/share/Trash/files" \
    "$user_home/.local/share/Trash/info" \
    "$user_home/.local/share/gvfs-metadata" \
    "$user_home/.vnc"

  chmod 700 "$user_home"
  printf 'workspace-home=%s\n' "$username" >"${user_home}/.workstation-home-marker"
  chown "$username:$group_name" "${user_home}/.workstation-home-marker"
  chmod 600 "${user_home}/.workstation-home-marker"
}

cleanup_legacy_shared_home_path() {
  local target_path="$1"
  [ -n "$target_path" ] || return 0

  if mountpoint -q "$target_path"; then
    umount "$target_path" >/dev/null 2>&1 || umount -l "$target_path" >/dev/null 2>&1 || true
  fi

  if [ -e "$target_path" ] || [ -L "$target_path" ]; then
    rm -rf -- "$target_path" 2>/dev/null || true
  fi
}

cleanup_legacy_shared_home() {
  local username="$1"
  cleanup_legacy_shared_home_path "$(workspace_home_dir "$username")/${LEGACY_SHARED_HOME_NAME}"
  cleanup_legacy_shared_home_path "$(login_home_dir "$username")/${LEGACY_SHARED_HOME_NAME}"
}

ensure_host_login_home() {
  local username="$1"
  local group_name="$2"
  local user_home host_home
  user_home="$(workspace_home_dir "$username")"
  host_home="$(login_home_dir "$username")"

  install -d -m 755 /home

  if mountpoint -q "$host_home"; then
    cleanup_legacy_shared_home "$username"
    if [ -f "${host_home}/.workstation-home-marker" ]; then
      return 0
    fi
    umount "$host_home"
  fi

  if [ -L "$host_home" ]; then
    rm -f "$host_home"
  elif [ -e "$host_home" ] && [ ! -d "$host_home" ]; then
    rm -f "$host_home"
  fi

  cleanup_legacy_shared_home "$username"

  if [ -d "$host_home" ]; then
    rsync -a --ignore-existing "${host_home}/" "${user_home}/"
    find "$host_home" -mindepth 1 -delete
  fi

  install -d -m 700 -o "$username" -g "$group_name" "$host_home"
  mount --bind "$user_home" "$host_home"
}

migrate_legacy_transfer_dirs() {
  local username="$1"
  local group_name="$2"
  local user_home legacy_uploads legacy_clipboard hidden_clipboard
  user_home="$(workspace_home_dir "$username")"
  legacy_uploads="${user_home}/Downloads/Uploads"
  legacy_clipboard="${user_home}/Downloads/Clipboard"
  hidden_clipboard="${user_home}/.local/share/workstation-transfer/clipboard"

  install -d -m 700 -o "$username" -g "$group_name" "$hidden_clipboard"

  python3 - "$user_home" "$username" "$group_name" <<'PY'
import os
import pwd
import grp
import shutil
import sys
from pathlib import Path

home = Path(sys.argv[1]).resolve()
uid = pwd.getpwnam(sys.argv[2]).pw_uid
gid = grp.getgrnam(sys.argv[3]).gr_gid


def merge_tree(src: Path, dest: Path) -> None:
    if not src.exists() or src.resolve() == dest.resolve():
        return
    dest.mkdir(mode=0o700, parents=True, exist_ok=True)
    for entry in list(src.iterdir()):
        target = dest / entry.name
        if target.exists():
            if entry.is_dir() and target.is_dir():
                merge_tree(entry, target)
                try:
                    entry.rmdir()
                except OSError:
                    pass
                continue
            stem = target.stem or entry.stem or "migrated"
            suffix = target.suffix or entry.suffix
            counter = 1
            while target.exists():
                target = dest / f"{stem}-{counter}{suffix}"
                counter += 1
        shutil.move(str(entry), str(target))
    try:
        src.rmdir()
    except OSError:
        pass


localized_documents = home / "문서"
localized_downloads = home / "다운로드"
localized_documents.mkdir(mode=0o700, parents=True, exist_ok=True)
localized_downloads.mkdir(mode=0o700, parents=True, exist_ok=True)
merge_tree(home / "Documents", localized_documents)
merge_tree(home / "Downloads", localized_downloads)

for path in (localized_documents, localized_downloads):
    for current_root, current_dirs, current_files in os.walk(path):
        os.chown(current_root, uid, gid)
        os.chmod(current_root, 0o700)
        for name in current_dirs:
            target = Path(current_root) / name
            os.chown(target, uid, gid)
            os.chmod(target, 0o700)
        for name in current_files:
            target = Path(current_root) / name
            os.chown(target, uid, gid)
            os.chmod(target, 0o600)
PY

  if [ -d "$legacy_uploads" ]; then
    find "$legacy_uploads" -mindepth 1 -maxdepth 1 -type f -print0 | while IFS= read -r -d '' src; do
      dest="${user_home}/다운로드/$(basename "$src")"
      if [ -e "$dest" ]; then
        python3 - "$src" "$dest" <<'PY'
from pathlib import Path
import shutil
import sys

src = Path(sys.argv[1])
dest = Path(sys.argv[2])
stem = dest.stem or "upload"
suffix = dest.suffix
candidate = dest
counter = 1
while candidate.exists():
    candidate = dest.with_name(f"{stem}-{counter}{suffix}")
    counter += 1
shutil.move(str(src), candidate)
PY
      else
        mv "$src" "$dest"
      fi
    done
    rmdir "$legacy_uploads" 2>/dev/null || true
  fi

  if [ -d "$legacy_clipboard" ]; then
    find "$legacy_clipboard" -mindepth 1 -maxdepth 1 -type f -exec mv {} "$hidden_clipboard"/ \;
    rmdir "$legacy_clipboard" 2>/dev/null || true
  fi

  rmdir "${user_home}/Downloads" 2>/dev/null || true
  rmdir "${user_home}/Documents" 2>/dev/null || true
  chown -R "$username:$group_name" "${user_home}/다운로드" "${user_home}/문서" "${user_home}/.local/share/workstation-transfer"
}

ensure_seeded_home() {
  local username="$1"
  local group_name="$2"
  local user_home seed_marker
  user_home="$(workspace_home_dir "$username")"
  seed_marker="${user_home}/.workstation-desktop-seeded"

  if [ ! -f "$seed_marker" ]; then
    if [ -d "$SKEL_DIR" ]; then
      cp -a "$SKEL_DIR"/. "$user_home"/
      chown -R "$username:$group_name" "$user_home"
    fi
    touch "$seed_marker"
    chown "$username:$group_name" "$seed_marker"
    chmod 600 "$seed_marker"
  fi
}

sync_desktop_profile() {
  local username="$1"
  local group_name="$2"
  local user_home
  user_home="$(workspace_home_dir "$username")"

  install -d -m 700 -o "$username" -g "$group_name" \
    "${user_home}/.config/nomacs" \
    "${user_home}/.config/Thunar" \
    "${user_home}/.config/peazip" \
    "${user_home}/.config/libreoffice/4/user" \
    "${user_home}/.config/xfce4" \
    "${user_home}/.config/xfce4/panel" \
    "${user_home}/.config/xfce4/xfconf/xfce-perchannel-xml" \
    "${user_home}/.config/gtk-3.0" \
    "${user_home}/Desktop"

  cat >"${user_home}/.config/user-dirs.dirs" <<'EOF'
XDG_DESKTOP_DIR="$HOME/Desktop"
XDG_DOWNLOAD_DIR="$HOME/다운로드"
XDG_TEMPLATES_DIR="$HOME/.templates"
XDG_PUBLICSHARE_DIR="$HOME/.public"
XDG_DOCUMENTS_DIR="$HOME/문서"
XDG_MUSIC_DIR="$HOME/.music"
XDG_PICTURES_DIR="$HOME/.pictures"
XDG_VIDEOS_DIR="$HOME/.videos"
EOF
  printf 'ko_KR.UTF-8\n' >"${user_home}/.config/user-dirs.locale"
  chown "$username:$group_name" "${user_home}/.config/user-dirs.dirs" "${user_home}/.config/user-dirs.locale"
  chmod 644 "${user_home}/.config/user-dirs.dirs" "${user_home}/.config/user-dirs.locale"

  rm -rf "${user_home}/.config/xfce4/panel"
  install -d -m 700 -o "$username" -g "$group_name" "${user_home}/.config/xfce4/panel"

  if [ -f "${SKEL_DIR}/.config/xfce4/helpers.rc" ]; then
    install -D -m 644 -o "$username" -g "$group_name" \
      "${SKEL_DIR}/.config/xfce4/helpers.rc" \
      "${user_home}/.config/xfce4/helpers.rc"
  fi
  if [ -f "${SKEL_DIR}/.config/mimeapps.list" ]; then
    install -D -m 644 -o "$username" -g "$group_name" \
      "${SKEL_DIR}/.config/mimeapps.list" \
      "${user_home}/.config/mimeapps.list"
  fi
  if [ -f "${SKEL_DIR}/.config/nomacs/Image Lounge.conf" ]; then
    install -D -m 644 -o "$username" -g "$group_name" \
      "${SKEL_DIR}/.config/nomacs/Image Lounge.conf" \
      "${user_home}/.config/nomacs/Image Lounge.conf"
  fi
  if [ -f "${SKEL_DIR}/.config/peazip/conf.txt" ] && [ -x /usr/local/lib/workstation-desktop/workstation-peazip-profile.py ]; then
    /usr/bin/python3 /usr/local/lib/workstation-desktop/workstation-peazip-profile.py \
      --seed "${SKEL_DIR}/.config/peazip/conf.txt" \
      --target-dir "${user_home}/.config/peazip"
    chown "$username:$group_name" "${user_home}/.config/peazip/conf.txt" "${user_home}/.config/peazip/conf-lastgood.txt"
    chmod 644 "${user_home}/.config/peazip/conf.txt" "${user_home}/.config/peazip/conf-lastgood.txt"
  fi
  if [ -f "${SKEL_DIR}/.config/libreoffice/4/user/registrymodifications.xcu" ] && [ -x /usr/local/lib/workstation-desktop/workstation-libreoffice-profile.py ]; then
    /usr/bin/python3 /usr/local/lib/workstation-desktop/workstation-libreoffice-profile.py \
      --seed "${SKEL_DIR}/.config/libreoffice/4/user/registrymodifications.xcu" \
      --target "${user_home}/.config/libreoffice/4/user/registrymodifications.xcu"
    chown "$username:$group_name" "${user_home}/.config/libreoffice/4/user/registrymodifications.xcu"
    chmod 644 "${user_home}/.config/libreoffice/4/user/registrymodifications.xcu"
    rm -f "${user_home}/.config/libreoffice/4/user/pack/registrymodifications.pack"
  fi
  if [ -f "${SKEL_DIR}/.config/xfce4/xfconf/xfce-perchannel-xml/xsettings.xml" ]; then
    install -D -m 644 -o "$username" -g "$group_name" \
      "${SKEL_DIR}/.config/xfce4/xfconf/xfce-perchannel-xml/xsettings.xml" \
      "${user_home}/.config/xfce4/xfconf/xfce-perchannel-xml/xsettings.xml"
  fi
  if [ -f "${SKEL_DIR}/.config/xfce4/xfconf/xfce-perchannel-xml/xfwm4.xml" ]; then
    install -D -m 644 -o "$username" -g "$group_name" \
      "${SKEL_DIR}/.config/xfce4/xfconf/xfce-perchannel-xml/xfwm4.xml" \
      "${user_home}/.config/xfce4/xfconf/xfce-perchannel-xml/xfwm4.xml"
  fi
  if [ -f "${SKEL_DIR}/.config/xfce4/xfconf/xfce-perchannel-xml/xfce4-desktop.xml" ]; then
    install -D -m 644 -o "$username" -g "$group_name" \
      "${SKEL_DIR}/.config/xfce4/xfconf/xfce-perchannel-xml/xfce4-desktop.xml" \
      "${user_home}/.config/xfce4/xfconf/xfce-perchannel-xml/xfce4-desktop.xml"
  fi
  if [ -f "${SKEL_DIR}/.config/xfce4/xfconf/xfce-perchannel-xml/keyboard-layout.xml" ]; then
    install -D -m 644 -o "$username" -g "$group_name" \
      "${SKEL_DIR}/.config/xfce4/xfconf/xfce-perchannel-xml/keyboard-layout.xml" \
      "${user_home}/.config/xfce4/xfconf/xfce-perchannel-xml/keyboard-layout.xml"
  fi
  if [ -f "${SKEL_DIR}/.config/xfce4/xfconf/xfce-perchannel-xml/thunar.xml" ]; then
    install -D -m 644 -o "$username" -g "$group_name" \
      "${SKEL_DIR}/.config/xfce4/xfconf/xfce-perchannel-xml/thunar.xml" \
      "${user_home}/.config/xfce4/xfconf/xfce-perchannel-xml/thunar.xml"
  fi
  if [ -f "${SKEL_DIR}/.config/xfce4/xfconf/xfce-perchannel-xml/xfce4-panel.xml" ]; then
    install -D -m 644 -o "$username" -g "$group_name" \
      "${SKEL_DIR}/.config/xfce4/xfconf/xfce-perchannel-xml/xfce4-panel.xml" \
      "${user_home}/.config/xfce4/xfconf/xfce-perchannel-xml/xfce4-panel.xml"
  fi
  if [ -d "${SKEL_DIR}/.config/xfce4/panel" ]; then
    cp -a "${SKEL_DIR}/.config/xfce4/panel"/. "${user_home}/.config/xfce4/panel"/
    chown -R "$username:$group_name" "${user_home}/.config/xfce4/panel"
  fi
  if [ -f "${SKEL_DIR}/.config/gtk-3.0/gtk.css" ]; then
    install -D -m 644 -o "$username" -g "$group_name" \
      "${SKEL_DIR}/.config/gtk-3.0/gtk.css" \
      "${user_home}/.config/gtk-3.0/gtk.css"
  fi
  if [ -f "${SKEL_DIR}/.config/Thunar/uca.xml" ] && [ -x /usr/local/lib/workstation-desktop/workstation-thunar-uca-merge.py ]; then
    python3 /usr/local/lib/workstation-desktop/workstation-thunar-uca-merge.py \
      "${SKEL_DIR}/.config/Thunar/uca.xml" \
      "${user_home}/.config/Thunar/uca.xml"
    chown "$username:$group_name" "${user_home}/.config/Thunar/uca.xml"
    chmod 600 "${user_home}/.config/Thunar/uca.xml"
  fi

  find "${user_home}/Desktop" -maxdepth 1 \( -type f -o -type l \) -name '*.desktop' -delete
  install -D -m 755 -o "$username" -g "$group_name" \
    /usr/local/share/applications/workstation-my-computer.desktop \
    "${user_home}/Desktop/01-workstation-my-computer.desktop"
  install -D -m 755 -o "$username" -g "$group_name" \
    /usr/local/share/applications/workstation-my-documents.desktop \
    "${user_home}/Desktop/02-workstation-my-documents.desktop"
  install -D -m 755 -o "$username" -g "$group_name" \
    /usr/local/share/applications/workstation-trash.desktop \
    "${user_home}/Desktop/03-workstation-trash.desktop"
  install -D -m 755 -o "$username" -g "$group_name" \
    /usr/local/share/applications/workstation-terminal.desktop \
    "${user_home}/Desktop/04-workstation-terminal.desktop"

  install -d -m 700 -o "$username" -g "$group_name" "${user_home}/.config/xfce4/desktop"
  find "${user_home}/.config/xfce4/desktop" -maxdepth 1 -type f -name 'icons.screen0-*.rc' -exec chown "$username:$group_name" {} + >/dev/null 2>&1 || true
  find "${user_home}/.config/xfce4/desktop" -maxdepth 1 -type f -name 'icons.screen0-*.rc' -exec chmod 600 {} + >/dev/null 2>&1 || true
  chmod 700 "${user_home}"
}

sync_thunderbird_profile_defaults() {
  local username="$1"
  local host_home
  host_home="$(login_home_dir "$username")"

  [ -x /usr/local/lib/workstation-desktop/workstation-thunderbird-profile.py ] || return 0

  if runuser -u "$username" -- env \
    HOME="$host_home" \
    LANG="ko_KR.UTF-8" \
    LANGUAGE="ko" \
    LC_ALL="ko_KR.UTF-8" \
    /usr/bin/python3 /usr/local/lib/workstation-desktop/workstation-thunderbird-profile.py sync-existing >/dev/null
  then
    return 0
  fi

  printf 'workstation-desktop-session: thunderbird profile sync failed for %s; continuing without blocking workspace sync\n' "$username" >&2
}

sync_brave_profile_defaults() {
  local username="$1"
  local user_home
  user_home="$(workspace_home_dir "$username")"

  [ -x /usr/local/lib/workstation-desktop/workstation-brave-profile.py ] || return 0

  /usr/bin/python3 /usr/local/lib/workstation-desktop/workstation-brave-profile.py \
    "$username" \
    "$user_home" >/dev/null
}

sync_wine_runtime_defaults() {
  local username="$1"
  local user_home hook profile
  user_home="$(workspace_home_dir "$username")"

  [ -x /usr/local/bin/workstation-wine-run ] || return 0

  for profile in modern64 compat32 kakaotalk32; do
    hook=""
    case "$profile" in
      modern64)
        hook="/usr/local/lib/workstation-desktop/workstation-notepad-plus-plus-init.py"
        ;;
      kakaotalk32)
        hook="/usr/local/lib/workstation-desktop/workstation-kakaotalk-init.py"
        ;;
    esac
    [ -n "$hook" ] && [ ! -x "$hook" ] && hook=""

    if [ -n "$hook" ]; then
      runuser -u "$username" -- env \
        HOME="$user_home" \
        USER="$username" \
        LOGNAME="$username" \
        LANG="ko_KR.UTF-8" \
        LANGUAGE="ko" \
        LC_ALL="ko_KR.UTF-8" \
        LC_CTYPE="ko_KR.UTF-8" \
        WORKSTATION_WINE_READY_HOOK="$hook" \
        /usr/bin/python3 /usr/local/bin/workstation-wine-run --prepare-profile --profile "$profile" >/dev/null
    else
      runuser -u "$username" -- env \
        HOME="$user_home" \
        USER="$username" \
        LOGNAME="$username" \
        LANG="ko_KR.UTF-8" \
        LANGUAGE="ko" \
        LC_ALL="ko_KR.UTF-8" \
        LC_CTYPE="ko_KR.UTF-8" \
        /usr/bin/python3 /usr/local/bin/workstation-wine-run --prepare-profile --profile "$profile" >/dev/null
    fi
  done
}

queue_wine_runtime_defaults() {
  local username="$1"
  local unit_file="/etc/systemd/system/workstation-wine-prewarm@.service"
  if [ -f "$unit_file" ] && systemctl start --no-block "workstation-wine-prewarm@${username}.service" >/dev/null 2>&1; then
    return 0
  fi
  sync_wine_runtime_defaults "$username"
}

sync_mail_bridge_state() {
  local username="$1"
  [ -x /usr/local/sbin/workstation-mail-bridge-sync ] || return 0
  /usr/local/sbin/workstation-mail-bridge-sync --user "$username" >/dev/null
}

ensure_rootfs_state() {
  local username="$1"
  local state_dir upper_dir work_dir
  state_dir="$(workspace_state_dir "$username")"
  upper_dir="$(workspace_rootfs_upper "$username")"
  work_dir="$(workspace_rootfs_work "$username")"

  install -d -m 755 "$state_dir" "${state_dir}/rootfs"
  install -d -m 700 "$upper_dir" "$work_dir"
}

ensure_runtime_dirs() {
  local username="$1"
  local group_name="$2"
  local uid_num gid_num port_num display_num user_runtime user_state user_home
  uid_num="$(uid_number "$username")"
  gid_num="$(gid_number "$username")"
  port_num="$(desktop_port "$username")"
  display_num="$(desktop_display "$username")"
  user_runtime="$(runtime_dir "$username")"
  user_state="$(workspace_state_dir "$username")"
  user_home="$(workspace_home_dir "$username")"

  install -d -m 755 "$RUNTIME_ROOT" "$STATE_ROOT"
  install -d -m 700 -o "$username" -g "$group_name" "$user_runtime"

  cat >"${RUNTIME_ROOT}/${username}.env" <<EOF
WORKSTATION_DESKTOP_USERNAME=${username}
WORKSTATION_DESKTOP_UID=${uid_num}
WORKSTATION_DESKTOP_GID=${gid_num}
WORKSTATION_DESKTOP_HOME_REAL=${user_home}
WORKSTATION_DESKTOP_STATE_DIR=${user_state}
WORKSTATION_DESKTOP_BASE_ROOTFS=${ROOTFS_BASE}
WORKSTATION_DESKTOP_RUNTIME_DIR=${user_runtime}
KASMVNC_DISPLAY=${display_num}
KASMVNC_PORT=${port_num}
EOF
  chown root:root "${RUNTIME_ROOT}/${username}.env"
  chmod 644 "${RUNTIME_ROOT}/${username}.env"
}

clear_directory_contents() {
  local target_dir="$1"
  [ -d "$target_dir" ] || return 0
  find "$target_dir" -mindepth 1 -maxdepth 1 -exec rm -rf -- {} +
}

sync_directory_tree() {
  local source_dir="$1"
  local target_dir="$2"
  install -d -m 700 "$target_dir"
  if [ -d "$source_dir" ]; then
    rsync -aHAX --delete --numeric-ids "${source_dir}/" "${target_dir}/"
  else
    clear_directory_contents "$target_dir"
  fi
}

sync_home_directory_tree() {
  local source_dir="$1"
  local target_dir="$2"
  install -d -m 700 "$target_dir"
  if [ -d "$source_dir" ]; then
    rsync -aHAX --delete --numeric-ids "${source_dir}/" "${target_dir}/"
  else
    clear_directory_contents "$target_dir"
  fi
}

prune_overlay_runtime_artifacts() {
  local upper_dir="$1"
  [ -d "$upper_dir" ] || return 0
  rm -f \
    "${upper_dir}/etc/passwd" \
    "${upper_dir}/etc/group" \
    "${upper_dir}/etc/hosts" \
    "${upper_dir}/etc/resolv.conf" \
    "${upper_dir}/etc/nsswitch.conf" \
    "${upper_dir}/etc/machine-id" \
    "${upper_dir}/etc/timezone" \
    "${upper_dir}/etc/localtime" \
    "${upper_dir}/etc/mtab" \
    "${upper_dir}/var/lib/dbus/machine-id"
}

reset_runtime_state() {
  local username="$1"
  rm -rf "$(runtime_dir "$username")"
  rm -f "${RUNTIME_ROOT}/${username}.env"
}

cleanup_workspace_processes() {
  local username="$1"
  local uid_num
  local attempt
  local wine_pattern
  require_ldap_user "$username"
  uid_num="$(uid_number "$username")"
  wine_pattern='wineserver|wine-preloader|wine64|wine32|winedevice\.exe|explorer\.exe|services\.exe|plugplay\.exe|rpcss\.exe|svchost\.exe|rundll32\.exe|conhost\.exe|KakaoTalk\.exe|notepad\+\+\.exe|thunderbird|plugin-container'

  pkill -TERM -u "$uid_num" -f "$wine_pattern" >/dev/null 2>&1 || true
  sleep 1
  pkill -KILL -u "$uid_num" -f "$wine_pattern" >/dev/null 2>&1 || true

  # Workspace reset and rollback must not leave stale desktop daemons behind.
  pkill -TERM -u "$uid_num" >/dev/null 2>&1 || true
  for attempt in 1 2 3 4 5; do
    if ! pgrep -u "$uid_num" >/dev/null 2>&1; then
      break
    fi
    sleep 1
  done
  pkill -KILL -u "$uid_num" >/dev/null 2>&1 || true

  systemctl stop "user@${uid_num}.service" >/dev/null 2>&1 || true
  systemctl reset-failed "user@${uid_num}.service" >/dev/null 2>&1 || true
}

generate_snapshot_id() {
  local username="$1"
  local snapshot_id counter candidate user_snapshot_dir
  user_snapshot_dir="$(snapshot_user_dir "$username")"
  snapshot_id="$(date +%Y-%m-%d_%H%M%S)"
  candidate="$snapshot_id"
  counter=1
  while [ -e "${user_snapshot_dir}/${candidate}" ]; do
    candidate="${snapshot_id}-${counter}"
    counter=$((counter + 1))
  done
  printf '%s\n' "$candidate"
}

snapshot_ids() {
  local username="$1"
  local user_snapshot_dir
  user_snapshot_dir="$(snapshot_user_dir "$username")"
  [ -d "$user_snapshot_dir" ] || return 0
  find "$user_snapshot_dir" -mindepth 1 -maxdepth 1 -type d -printf '%f\n' | LC_ALL=C sort -r
}

latest_snapshot_id() {
  local username="$1"
  snapshot_ids "$username" | head -n1
}

snapshot_list() {
  local username="$1"
  local user_snapshot_dir
  require_ldap_user "$username"
  user_snapshot_dir="$(snapshot_user_dir "$username")"
  install -d -m 700 "$SNAPSHOT_ROOT" "$user_snapshot_dir"

  python3 - "$user_snapshot_dir" "$username" <<'PY'
import json
import time
from pathlib import Path
import sys

snapshot_root = Path(sys.argv[1])
username = sys.argv[2]
snapshots = []

for snapshot_dir in sorted(
    [path for path in snapshot_root.iterdir() if path.is_dir()],
    key=lambda path: path.name,
    reverse=True,
):
    metadata_path = snapshot_dir / "metadata.json"
    payload = {}
    if metadata_path.is_file():
        try:
            payload = json.loads(metadata_path.read_text(encoding="utf-8"))
        except Exception:
            payload = {}
    created_at_epoch = int(payload.get("created_at_epoch") or int(snapshot_dir.stat().st_mtime))
    created_at_display = payload.get("created_at_display") or time.strftime(
        "%Y-%m-%d %H:%M:%S",
        time.localtime(created_at_epoch),
    )
    title = str(payload.get("title") or created_at_display)
    description = str(payload.get("description") or "")
    snapshots.append(
        {
            "id": snapshot_dir.name,
            "created_at_epoch": created_at_epoch,
            "created_at_display": created_at_display,
            "title": title,
            "description": description,
        }
    )

print(json.dumps({"ok": True, "username": username, "snapshots": snapshots}, ensure_ascii=False))
PY
}

snapshot_create() {
  local username="$1"
  local title_text="${2:-}"
  local description_text="${3:-}"
  local group_name user_home upper_dir user_snapshot_dir snapshot_id snapshot_dir created_at_epoch created_at_display title_default
  local base_snapshot_id storage_mode
  require_ldap_user "$username"
  group_name="$(primary_group_name "$username")"
  ensure_workspace_home "$username" "$group_name"
  ensure_rootfs_state "$username"
  user_home="$(workspace_home_dir "$username")"
  upper_dir="$(workspace_rootfs_upper "$username")"
  user_snapshot_dir="$(snapshot_user_dir "$username")"
  install -d -m 700 "$SNAPSHOT_ROOT" "$user_snapshot_dir"

  cleanup_workspace_processes "$username"
  stop_session "$username" || true
  cleanup_workspace_processes "$username"
  reset_runtime_state "$username"
  cleanup_legacy_shared_home "$username"

  snapshot_id="$(generate_snapshot_id "$username")"
  snapshot_dir="${user_snapshot_dir}/${snapshot_id}"
  base_snapshot_id="$(latest_snapshot_id "$username" || true)"
  storage_mode="full"
  if [ -n "${base_snapshot_id}" ] && [ -d "${user_snapshot_dir}/${base_snapshot_id}" ]; then
    storage_mode="incremental"
  fi
  created_at_epoch="$(date +%s)"
  created_at_display="$(date '+%Y-%m-%d %H:%M:%S')"
  title_default="$(snapshot_title_default "$created_at_display")"

  rm -rf "$snapshot_dir"
  install -d -m 700 "$snapshot_dir/rootfs"
  if [ "${storage_mode}" = "incremental" ]; then
    rsync -aHAX --delete --numeric-ids --link-dest="${user_snapshot_dir}/${base_snapshot_id}/home" "${user_home}/" "${snapshot_dir}/home/"
  else
    rsync -aHAX --delete --numeric-ids "${user_home}/" "${snapshot_dir}/home/"
  fi
  if [ -d "$upper_dir" ]; then
    if [ "${storage_mode}" = "incremental" ]; then
      rsync -aHAX --delete --numeric-ids \
        --link-dest="${user_snapshot_dir}/${base_snapshot_id}/rootfs/upper" \
        "${upper_dir}/" "${snapshot_dir}/rootfs/upper/"
    else
      rsync -aHAX --delete --numeric-ids "${upper_dir}/" "${snapshot_dir}/rootfs/upper/"
    fi
    prune_overlay_runtime_artifacts "${snapshot_dir}/rootfs/upper"
  else
    install -d -m 700 "${snapshot_dir}/rootfs/upper"
  fi

  python3 - "$snapshot_dir" "$snapshot_id" "$username" "$created_at_epoch" "$created_at_display" "$title_text" "$description_text" "$title_default" "$storage_mode" "${base_snapshot_id:-}" <<'PY'
import json
import sys
from pathlib import Path

snapshot_dir = Path(sys.argv[1])
snapshot_id = sys.argv[2]
username = sys.argv[3]
created_at_epoch = int(sys.argv[4])
created_at_display = sys.argv[5]
title = sys.argv[6].strip() or sys.argv[8]
description = sys.argv[7].strip()
storage_mode = sys.argv[9]
incremental_base = sys.argv[10]
payload = {
    "id": snapshot_id,
    "username": username,
    "created_at_epoch": created_at_epoch,
    "created_at_display": created_at_display,
    "title": title,
    "description": description,
    "components": ["home", "rootfs/upper"],
    "version": 3,
    "storage_mode": storage_mode,
    "incremental_base": incremental_base or None,
}
(snapshot_dir / "metadata.json").write_text(json.dumps(payload, ensure_ascii=False) + "\n", encoding="utf-8")
PY
  chmod 600 "${snapshot_dir}/metadata.json"

  ensure_session "$username" >/dev/null

  python3 - "$snapshot_id" "$created_at_epoch" "$created_at_display" "$title_text" "$description_text" "$title_default" <<'PY'
import json
import sys

snapshot_id = sys.argv[1]
created_at_epoch = int(sys.argv[2])
created_at_display = sys.argv[3]
title = sys.argv[4].strip() or sys.argv[6]
description = sys.argv[5].strip()
print(json.dumps({
    "ok": True,
    "id": snapshot_id,
    "created_at_epoch": created_at_epoch,
    "created_at_display": created_at_display,
    "title": title,
    "description": description,
    "reconnect_required": True,
}, ensure_ascii=False))
PY
}

snapshot_delete() {
  local username="$1"
  local snapshot_id="$2"
  local deleted_count deleted_newer
  require_ldap_user "$username"
  [ -n "$snapshot_id" ] || die "missing snapshot id"
  [ -d "$(snapshot_user_dir "$username")/${snapshot_id}" ] || die "snapshot does not exist: ${snapshot_id}"

  deleted_count=0
  deleted_newer=0
  while IFS= read -r current_id; do
    [ -n "$current_id" ] || continue
    if [[ "$current_id" == "$snapshot_id" || "$current_id" > "$snapshot_id" ]]; then
      rm -rf "$(snapshot_user_dir "$username")/${current_id}"
      deleted_count=$((deleted_count + 1))
      if [[ "$current_id" > "$snapshot_id" ]]; then
        deleted_newer=$((deleted_newer + 1))
      fi
    fi
  done < <(snapshot_ids "$username")

  python3 - <<EOF
import json
print(json.dumps({
    "ok": True,
    "deleted": ${snapshot_id@Q},
    "deleted_count": int(${deleted_count}),
    "deleted_newer": int(${deleted_newer}),
}, ensure_ascii=False))
EOF
}

snapshot_rollback() {
  local username="$1"
  local snapshot_id="$2"
  local group_name user_home upper_dir work_dir snapshot_dir deleted_newer
  require_ldap_user "$username"
  [ -n "$snapshot_id" ] || die "missing snapshot id"
  group_name="$(primary_group_name "$username")"
  user_home="$(workspace_home_dir "$username")"
  upper_dir="$(workspace_rootfs_upper "$username")"
  work_dir="$(workspace_rootfs_work "$username")"
  snapshot_dir="$(snapshot_user_dir "$username")/${snapshot_id}"
  [ -d "$snapshot_dir" ] || die "snapshot does not exist: ${snapshot_id}"

  stop_session "$username" || true
  cleanup_workspace_processes "$username"
  reset_runtime_state "$username"
  cleanup_legacy_shared_home "$username"
  ensure_workspace_home "$username" "$group_name"
  ensure_rootfs_state "$username"
  sync_home_directory_tree "${snapshot_dir}/home" "$user_home"
  sync_directory_tree "${snapshot_dir}/rootfs/upper" "$upper_dir"
  prune_overlay_runtime_artifacts "$upper_dir"
  rm -rf "$work_dir"
  install -d -m 700 "$work_dir"

  deleted_newer=0
  while IFS= read -r current_id; do
    [ -n "$current_id" ] || continue
    if [[ "$current_id" > "$snapshot_id" ]]; then
      rm -rf "$(snapshot_user_dir "$username")/${current_id}"
      deleted_newer=$((deleted_newer + 1))
    fi
  done < <(snapshot_ids "$username")

  ensure_session "$username" >/dev/null

  python3 - <<EOF
import json
print(json.dumps({
    "ok": True,
    "restored": ${snapshot_id@Q},
    "deleted_newer": int(${deleted_newer}),
    "reconnect_required": True,
}, ensure_ascii=False))
EOF
}

reset_workspace() {
  local username="$1"
  local group_name state_dir user_home upper_dir work_dir user_snapshot_dir
  require_ldap_user "$username"
  group_name="$(primary_group_name "$username")"
  state_dir="$(workspace_state_dir "$username")"
  user_home="$(workspace_home_dir "$username")"
  upper_dir="$(workspace_rootfs_upper "$username")"
  work_dir="$(workspace_rootfs_work "$username")"
  user_snapshot_dir="$(snapshot_user_dir "$username")"

  stop_session "$username" || true
  cleanup_workspace_processes "$username"
  reset_runtime_state "$username"
  cleanup_legacy_shared_home "$username"
  install -d -m 755 "$STATE_ROOT" "$state_dir"
  install -d -m 700 -o "$username" -g "$group_name" "$user_home"
  clear_directory_contents "$user_home"
  rm -rf "$upper_dir" "$work_dir"
  rm -rf "$user_snapshot_dir"

  ensure_session "$username" >/dev/null

  python3 - <<EOF
import json
print(json.dumps({
    "ok": True,
    "username": ${username@Q},
    "snapshots_deleted": True,
    "reconnect_required": True,
}, ensure_ascii=False))
EOF
}

ensure_kasmvnc_profile() {
  local username="$1"
  local group_name="$2"
  local user_home vnc_dir passwd_file passwd_file_session xstartup_file config_file de_selected_file cert_file key_file cert_file_session key_file_session display_num port_num
  load_proxy_credentials
  user_home="$(workspace_home_dir "$username")"
  vnc_dir="${user_home}/.vnc"
  passwd_file="${user_home}/.kasmpasswd"
  passwd_file_session="/home/${username}/.kasmpasswd"
  xstartup_file="${vnc_dir}/xstartup"
  config_file="${vnc_dir}/kasmvnc.yaml"
  de_selected_file="${vnc_dir}/.de-was-selected"
  cert_file="${vnc_dir}/localhost-cert.pem"
  key_file="${vnc_dir}/localhost-key.pem"
  cert_file_session="/home/${username}/.vnc/localhost-cert.pem"
  key_file_session="/home/${username}/.vnc/localhost-key.pem"
  display_num="$(desktop_display "$username")"
  port_num="$(desktop_port "$username")"

  install -d -m 700 -o "$username" -g "$group_name" "$vnc_dir"

  cat >"$config_file" <<EOF
---
desktop:
  resolution:
    width: 1440
    height: 900
  allow_resize: true
  pixel_depth: 24
network:
  protocol: http
  interface: 127.0.0.1
  websocket_port: ${port_num}
  use_ipv4: true
  use_ipv6: false
  ssl:
    pem_certificate: ${cert_file_session}
    pem_key: ${key_file_session}
    require_ssl: false
keyboard:
  raw_keyboard: false
runtime_configuration:
  allow_client_to_override_kasm_server_settings: true
  allow_override_standard_vnc_server_settings: true
data_loss_prevention:
  clipboard:
    allow_mimetypes:
      - chromium/x-web-custom-data
      - text/html
      - image/png
    server_to_client:
      enabled: true
      size: unlimited
      primary_clipboard_enabled: false
    client_to_server:
      enabled: true
      size: unlimited
encoding:
  max_frame_rate: 60
  rect_encoding_mode:
    min_quality: 8
    max_quality: 9
    consider_lossless_quality: 10
  video_encoding_mode:
    enter_video_encoding_mode:
      time_threshold: 30
      area_threshold: 95%
server:
  advanced:
    kasm_password_file: ${passwd_file_session}
EOF
  chown "$username:$group_name" "$config_file"
  chmod 600 "$config_file"

  cat >"$xstartup_file" <<'EOF'
#!/usr/bin/env bash
exec /usr/local/lib/workstation-desktop/workstation-xfce-session.sh
EOF
  chown "$username:$group_name" "$xstartup_file"
  chmod 700 "$xstartup_file"

  touch "$de_selected_file"
  chown "$username:$group_name" "$de_selected_file"
  chmod 600 "$de_selected_file"

  if [ ! -f "$cert_file" ] || [ ! -f "$key_file" ]; then
    umask 077
    openssl req -x509 -nodes -newkey rsa:2048 \
      -keyout "$key_file" \
      -out "$cert_file" \
      -days 3650 \
      -subj "/CN=workstation-desktop-local" >/dev/null 2>&1
    chown "$username:$group_name" "$cert_file" "$key_file"
    chmod 600 "$cert_file" "$key_file"
  fi

  if [ ! -f "$passwd_file" ]; then
    env \
      HOME="$user_home" \
      WORKSTATION_IPLOGIN_DESKTOP_PROXY_USER="${WORKSTATION_IPLOGIN_DESKTOP_PROXY_USER}" \
      WORKSTATION_IPLOGIN_DESKTOP_PROXY_PASSWORD="${WORKSTATION_IPLOGIN_DESKTOP_PROXY_PASSWORD}" \
      WORKSTATION_KASM_PASSWD_FILE="${passwd_file}" \
      runuser -u "$username" -- bash -lc 'printf "%s\n%s\n" "$WORKSTATION_IPLOGIN_DESKTOP_PROXY_PASSWORD" "$WORKSTATION_IPLOGIN_DESKTOP_PROXY_PASSWORD" | vncpasswd -u "$WORKSTATION_IPLOGIN_DESKTOP_PROXY_USER" -w "$WORKSTATION_KASM_PASSWD_FILE" >/dev/null'
    chown "$username:$group_name" "$passwd_file"
    chmod 600 "$passwd_file"
  fi
}

wait_for_backend_ready() {
  local username="$1"
  local port="$2"
  local attempt
  load_proxy_credentials
  for attempt in $(seq 1 60); do
    if ! systemctl is-active --quiet "$(service_name "$username")"; then
      sleep 1
      continue
    fi
    if curl -fsS --max-time 2 --user "${WORKSTATION_IPLOGIN_DESKTOP_PROXY_USER}:${WORKSTATION_IPLOGIN_DESKTOP_PROXY_PASSWORD}" "http://127.0.0.1:${port}/" >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
  done
  systemctl --no-pager -l status "$(service_name "$username")" >&2 || true
  return 1
}

ensure_session() {
  local username="$1"
  local group_name port user_home uid_num upper_dir service active_state
  require_ldap_user "$username"
  [ -d "$ROOTFS_BASE" ] || die "missing rootfs base ${ROOTFS_BASE}; redeploy the workspace stack first"
  group_name="$(primary_group_name "$username")"
  uid_num="$(uid_number "$username")"
  port="$(desktop_port "$username")"
  user_home="$(workspace_home_dir "$username")"
  upper_dir="$(workspace_rootfs_upper "$username")"
  service="$(service_name "$username")"

  ensure_workspace_home "$username" "$group_name"
  ensure_host_login_home "$username" "$group_name"
  ensure_seeded_home "$username" "$group_name"
  migrate_legacy_transfer_dirs "$username" "$group_name"
  sync_desktop_profile "$username" "$group_name"
  sync_mail_bridge_state "$username"
  sync_thunderbird_profile_defaults "$username"
  sync_brave_profile_defaults "$username"
  ensure_rootfs_state "$username"
  prune_overlay_runtime_artifacts "$upper_dir"
  ensure_runtime_dirs "$username" "$group_name"
  ensure_kasmvnc_profile "$username" "$group_name"
  loginctl enable-linger "$username" >/dev/null 2>&1 || true
  systemctl start "user@${uid_num}.service" >/dev/null 2>&1 || true

  systemctl daemon-reload
  systemctl enable "$service" >/dev/null 2>&1 || true
  active_state="$(systemctl show -p ActiveState --value "$service" 2>/dev/null || true)"
  case "$active_state" in
    active|activating|reloading)
      if wait_for_backend_ready "$username" "$port"; then
        queue_wine_runtime_defaults "$username"
        python3 - <<EOF
import json
print(json.dumps({
    "username": ${username@Q},
    "port": ${port},
    "home": ${user_home@Q},
}))
EOF
        return 0
      fi
      ;;
  esac
  systemctl restart "$service"
  wait_for_backend_ready "$username" "$port" || die "desktop session did not start for ${username}"
  queue_wine_runtime_defaults "$username"

  python3 - <<EOF
import json
print(json.dumps({
    "username": ${username@Q},
    "port": ${port},
    "home": ${user_home@Q},
}))
EOF
}

stop_session() {
  local username="$1"
  local service active_state
  service="$(service_name "$username")"
  cleanup_workspace_processes "$username"
  systemctl stop "$service" >/dev/null 2>&1 || true
  for _ in 1 2 3 4 5 6 7 8 9 10; do
    active_state="$(systemctl show -p ActiveState --value "$service" 2>/dev/null || true)"
    case "$active_state" in
      inactive|failed|"")
        break
        ;;
    esac
    sleep 1
  done
  active_state="$(systemctl show -p ActiveState --value "$service" 2>/dev/null || true)"
  if [ "$active_state" != "inactive" ] && [ "$active_state" != "failed" ] && [ -n "$active_state" ]; then
    systemctl kill --signal=KILL "$service" >/dev/null 2>&1 || true
    sleep 1
    systemctl stop "$service" >/dev/null 2>&1 || true
  fi
  systemctl reset-failed "$service" >/dev/null 2>&1 || true
}

session_runner() {
  local username="$1"
  shift
  local pid uid_num gid_num display_num supplementary_groups bus_address
  require_active_session "$username"
  pid="$(service_main_pid "$username")"
  uid_num="$(uid_number "$username")"
  gid_num="$(gid_number "$username")"
  display_num="$(desktop_display "$username")"
  supplementary_groups="$(id -G "$username" | tr ' ' ',')"
  bus_address="$(session_bus_address "$username")"

  [[ "$pid" =~ ^[1-9][0-9]*$ ]] || die "invalid service pid for ${username}"

  nsenter -t "$pid" -m --root="/proc/${pid}/root" --wd="/home/${username}" -- \
    /usr/bin/setpriv --reuid="$uid_num" --regid="$gid_num" --groups="$supplementary_groups" \
    env \
      HOME="/home/${username}" \
      PWD="/home/${username}" \
      USER="${username}" \
      LOGNAME="${username}" \
      SHELL="/usr/local/bin/workstation-user-shell" \
      DISPLAY=":${display_num}" \
      XAUTHORITY="/home/${username}/.Xauthority" \
      XDG_RUNTIME_DIR="/run/user/${uid_num}" \
      DBUS_SESSION_BUS_ADDRESS="${bus_address}" \
      GNOME_KEYRING_CONTROL="/run/user/${uid_num}/keyring" \
      PULSE_SERVER="unix:/run/user/${uid_num}/pulse/native" \
      LANG="ko_KR.UTF-8" \
      LANGUAGE="ko" \
      LC_ALL="ko_KR.UTF-8" \
      "$@"
}

keyring_sync() {
  local username="$1"
  local password
  require_ldap_user "$username"
  require_active_session "$username"
  password="$(cat)"
  [ -n "$password" ] || die "missing keyring password"

  printf '%s' "$password" | session_runner "$username" /bin/sh -lc '
    set -eu
    export DBUS_SESSION_BUS_ADDRESS="${DBUS_SESSION_BUS_ADDRESS:-unix:path=${XDG_RUNTIME_DIR}/bus}"
    export GNOME_KEYRING_CONTROL="${GNOME_KEYRING_CONTROL:-${XDG_RUNTIME_DIR}/keyring}"
    exec gnome-keyring-daemon --unlock --components=pkcs11,secrets,ssh >/dev/null
  '

  python3 - <<EOF
import json
print(json.dumps({
    "ok": True,
    "username": ${username@Q},
}, ensure_ascii=False))
EOF
}

clipboard_runner() {
  local username="$1"
  shift
  session_runner "$username" "$@"
}

clipboard_targets() {
  local username="$1"
  require_ldap_user "$username"
  command -v xclip >/dev/null 2>&1 || die "xclip is not installed"
  clipboard_runner "$username" xclip -selection clipboard -t TARGETS -o || true
}

clipboard_read() {
  local username="$1"
  local mime="$2"
  require_ldap_user "$username"
  command -v xclip >/dev/null 2>&1 || die "xclip is not installed"
  clipboard_runner "$username" xclip -selection clipboard -t "$mime" -o
}

clipboard_set_image() {
  local username="$1"
  local image_path="$2"
  require_ldap_user "$username"
  require_active_session "$username"
  [ -f "$image_path" ] || die "clipboard image does not exist: ${image_path}"
  command -v xclip >/dev/null 2>&1 || die "xclip is not installed"
  [ -x /usr/local/lib/workstation-desktop/workstation-image-clipboard-bridge.py ] || die "clipboard bridge is not installed"

  cat "$image_path" | clipboard_runner "$username" timeout 10s xclip -selection clipboard -t image/png -i
  cat "$image_path" | clipboard_runner "$username" timeout 10s /usr/local/lib/workstation-desktop/workstation-image-clipboard-bridge.py --set-stdin

  python3 - <<'PY'
import json

print(json.dumps({
    "ok": True,
    "mime": "image/png",
    "message": "Image copied into the workspace clipboard.",
}, ensure_ascii=False))
PY
}

clipboard_paste() {
  local username="$1"
  local active_window
  require_ldap_user "$username"
  require_active_session "$username"
  command -v xdotool >/dev/null 2>&1 || die "xdotool is not installed"

  active_window="$(clipboard_runner "$username" timeout 5s xdotool getwindowfocus 2>/dev/null || true)"
  [ -n "$active_window" ] || die "missing active window for ${username}"
  clipboard_runner "$username" timeout 5s xdotool key --window "$active_window" --clearmodifiers ctrl+v

  python3 - <<'PY'
import json

print(json.dumps({
    "ok": True,
    "message": "Paste shortcut sent to the active workspace window.",
}, ensure_ascii=False))
PY
}

clipboard_import() {
  local username="$1"
  shift
  local group_name user_home upload_dir
  require_ldap_user "$username"
  [ "$#" -gt 0 ] || die "clipboard-import requires at least one file"

  group_name="$(primary_group_name "$username")"
  user_home="$(workspace_home_dir "$username")"
  upload_dir="${user_home}/.local/share/workstation-transfer/clipboard"
  install -d -m 700 -o "$username" -g "$group_name" "$upload_dir"

  python3 - "$upload_dir" "$@" <<'PY'
import os
import re
import shutil
import sys
from pathlib import Path

target_dir = Path(sys.argv[1])
saved = []
for index, src_text in enumerate(sys.argv[2:]):
    src = Path(src_text)
    if not src.is_file():
        continue
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", src.name).strip("._") or f"clipboard-{index}"
    dest = target_dir / name
    counter = 1
    while dest.exists():
        stem = Path(name).stem or f"clipboard-{index}"
        suffix = Path(name).suffix
        dest = target_dir / f"{stem}-{counter}{suffix}"
        counter += 1
    shutil.move(str(src), dest)
    saved.append(str(dest))

if not saved:
    raise SystemExit("no files imported")

payload = "\r\n".join(Path(path).resolve().as_uri() for path in saved).encode("utf-8")
sys.stdout.buffer.write(payload)
PY
}

clipboard_import_and_set() {
  local username="$1"
  shift
  local uri_payload
  uri_payload="$(clipboard_import "$username" "$@")"
  printf '%s' "$uri_payload" | clipboard_runner "$username" xclip -selection clipboard -t text/uri-list -i

  python3 - "$uri_payload" <<'PY'
import json
import sys

text = sys.argv[1]
uris = [line.strip() for line in text.splitlines() if line.strip()]
print(json.dumps({
    "ok": True,
    "count": len(uris),
    "uris": uris,
    "message": f"{len(uris)} item(s) copied into the workspace clipboard.",
}, ensure_ascii=False))
PY
}

audio_info() {
  local username="$1"
  local source_name
  require_ldap_user "$username"
  source_name="$(session_runner "$username" /bin/sh -lc 'set -eu; pactl get-default-source | head -n1')"
  [ -n "$source_name" ] || die "missing default pulse source for ${username}"

  python3 - <<EOF
import json

print(json.dumps({
    "ok": True,
    "source": ${source_name@Q},
    "format": "s16le",
    "channels": 2,
    "sample_rate": 48000,
}, ensure_ascii=False))
EOF
}

audio_stream() {
  local username="$1"
  require_ldap_user "$username"
  session_runner "$username" /bin/sh -lc '
    set -eu
    source_name="$(pactl get-default-source | head -n1)"
    [ -n "$source_name" ] || exit 1
    exec parec \
      --raw \
      --latency-msec=10 \
      --format=s16le \
      --channels=2 \
      --rate=48000 \
      --device="$source_name"
  '
}

terminal_shell() {
  local username="$1"
  require_ldap_user "$username"
  session_runner "$username" env TERM="xterm-256color" COLORTERM="truecolor" /usr/local/bin/workstation-user-shell
}

notification_monitor() {
  local username="$1"
  require_ldap_user "$username"
  session_runner "$username" /usr/bin/dbus-monitor --session "interface='org.freedesktop.Notifications',member='Notify'"
}

process_list() {
  local username="$1"
  require_ldap_user "$username"

  python3 - "$username" <<'PY'
import json
import pwd
import subprocess
import sys
import time
from pathlib import Path

username = sys.argv[1]
state_labels = {
    "D": "대기",
    "I": "유휴",
    "R": "실행",
    "S": "절전",
    "T": "정지",
    "Z": "좀비",
}

try:
    user_record = pwd.getpwnam(username)
except KeyError as exc:
    raise SystemExit(str(exc))

result = subprocess.run(
    [
        "ps",
        "--no-headers",
        "--sort",
        "pid",
        "-u",
        username,
        "-o",
        "etimes=",
        "-o",
        "pid=",
        "-o",
        "ppid=",
        "-o",
        "pgid=",
        "-o",
        "stat=",
        "-o",
        "pcpu=",
        "-o",
        "pmem=",
        "-o",
        "comm=",
        "-o",
        "args=",
    ],
    check=True,
    capture_output=True,
    text=True,
    encoding="utf-8",
    errors="replace",
)

items = []
now = int(time.time())
for raw_line in result.stdout.splitlines():
    parts = raw_line.strip().split(None, 8)
    if len(parts) < 8:
        continue
    if len(parts) == 8:
        elapsed_text, pid_text, ppid_text, pgid_text, stat_text, cpu_text, mem_text, comm_text = parts
        args_text = ""
    else:
        elapsed_text, pid_text, ppid_text, pgid_text, stat_text, cpu_text, mem_text, comm_text, args_text = parts
    try:
        pid = int(pid_text.strip())
        ppid = int(ppid_text.strip() or "0")
        pgid = int(pgid_text.strip() or "0")
        elapsed_seconds = int(float(elapsed_text.strip() or "0"))
        cpu_percent = float(cpu_text.strip() or "0")
        memory_percent = float(mem_text.strip() or "0")
    except ValueError:
        continue

    proc_path = Path("/proc") / str(pid)
    try:
        if proc_path.stat().st_uid != user_record.pw_uid:
            continue
    except FileNotFoundError:
        continue

    started_timestamp = max(0, now - elapsed_seconds)
    started_display = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(started_timestamp)) if started_timestamp else ""

    command = args_text.strip() or comm_text.strip() or f"PID {pid}"
    state = (stat_text.strip()[:1] or "?").upper()
    items.append(
        {
            "pid": pid,
            "ppid": ppid,
            "pgid": pgid,
            "state": state,
            "state_label": state_labels.get(state, state),
            "cpu_percent": round(cpu_percent, 1),
            "memory_percent": round(memory_percent, 1),
            "name": comm_text.strip() or command.split(" ", 1)[0],
            "command": command,
            "started_at": started_display,
            "started_timestamp": started_timestamp,
            "elapsed_seconds": elapsed_seconds,
        }
    )

print(json.dumps({"ok": True, "items": items}, ensure_ascii=False))
PY
}

process_kill() {
  local username="$1"
  local pid="$2"
  require_ldap_user "$username"
  [[ "$pid" =~ ^[1-9][0-9]*$ ]] || die "invalid pid"

  python3 - "$username" "$pid" <<'PY'
import json
import os
import pwd
import signal
import sys
from pathlib import Path

username = sys.argv[1]
pid = int(sys.argv[2])
if pid <= 1:
    raise SystemExit("invalid pid")

try:
    user_record = pwd.getpwnam(username)
except KeyError as exc:
    raise SystemExit(str(exc))

proc_path = Path("/proc") / str(pid)
if not proc_path.exists():
    raise SystemExit("process not found")
if proc_path.stat().st_uid != user_record.pw_uid:
    raise SystemExit("process does not belong to user")

os.kill(pid, signal.SIGKILL)

print(
    json.dumps(
        {
            "ok": True,
            "pid": pid,
            "message": "프로세스를 강제 종료했습니다.",
        },
        ensure_ascii=False,
    )
)
PY
}

file_list() {
  local username="$1"
  local requested="${2:-}"
  local user_home
  require_ldap_user "$username"
  user_home="$(workspace_home_dir "$username")"

  python3 - "$user_home" "$requested" <<'PY'
import json
import sys
import time
from pathlib import Path

home = Path(sys.argv[1]).resolve()
requested = (sys.argv[2] or "").strip()
normalized = requested.lstrip("/")
candidate = (home / normalized).resolve()
try:
    relative = candidate.relative_to(home)
except ValueError:
    candidate = home
    relative = Path(".")

if not candidate.exists():
    raise SystemExit("path not found")
if not candidate.is_dir():
    raise SystemExit("path is not a directory")

current = "" if str(relative) == "." else str(relative)
if current:
    parent_path = relative.parent
    parent = "" if str(parent_path) == "." else str(parent_path)
else:
    parent = None

items = []
for child in sorted(candidate.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower())):
    if child.name.startswith("."):
        continue
    stat = child.stat()
    rel = child.relative_to(home)
    items.append(
        {
            "name": child.name,
            "path": str(rel),
            "kind": "dir" if child.is_dir() else "file",
            "size": 0 if child.is_dir() else stat.st_size,
            "mtime": time.strftime("%Y-%m-%d %H:%M", time.localtime(stat.st_mtime)),
        }
    )

print(
    json.dumps(
        {
            "ok": True,
            "current": current,
            "current_display": "/" if not current else f"/{current}",
            "parent": parent,
            "items": items,
        },
        ensure_ascii=False,
    )
)
PY
}

file_upload() {
  local username="$1"
  local requested="${2:-}"
  shift 2
  local group_name user_home
  require_ldap_user "$username"
  [ "$#" -gt 0 ] || die "file-upload requires source files"
  group_name="$(primary_group_name "$username")"
  user_home="$(workspace_home_dir "$username")"

  python3 - "$user_home" "$username" "$group_name" "$requested" "$@" <<'PY'
import grp
import json
import os
import re
import shutil
import sys
from pathlib import Path
import pwd
import unicodedata

home = Path(sys.argv[1]).resolve()
username = sys.argv[2]
group_name = sys.argv[3]
requested = (sys.argv[4] or "").strip()
sources = [Path(item) for item in sys.argv[5:]]

normalized = requested.lstrip("/")
target = (home / normalized).resolve()
try:
    target.relative_to(home)
except ValueError:
    target = home

if not target.exists():
    raise SystemExit("target path not found")
if not target.is_dir():
    raise SystemExit("target path is not a directory")

user_uid = pwd.getpwnam(username).pw_uid
group_gid = grp.getgrnam(group_name).gr_gid

def sanitize_name(raw_name: str, default: str) -> str:
    clean = unicodedata.normalize("NFC", Path(str(raw_name or default).replace("\x00", "")).name)
    clean = clean.replace("/", "_").replace("\\", "_")
    clean = re.sub(r"[\x00-\x1f\x7f]+", "", clean).strip()
    if clean in {"", ".", ".."}:
        return default
    return clean

saved = []
for index, source in enumerate(sources):
    if not source.is_file():
        continue
    name = sanitize_name(source.name, f"upload-{index}.bin")
    destination = target / name
    stem = Path(name).stem or "upload"
    suffix = Path(name).suffix
    counter = 1
    while destination.exists():
        destination = target / f"{stem}-{counter}{suffix}"
        counter += 1
    shutil.move(str(source), destination)
    os.chown(destination, user_uid, group_gid)
    os.chmod(destination, 0o600)
    saved.append(str(destination.relative_to(home)))

if not saved:
    raise SystemExit("no files uploaded")

print(json.dumps({"ok": True, "saved": saved}, ensure_ascii=False))
PY
}

file_export() {
  local username="$1"
  local requested="${2:-}"
  local user_home
  require_ldap_user "$username"
  user_home="$(workspace_home_dir "$username")"

  python3 - "$user_home" "$requested" "$SUDOERS_USER" <<'PY'
import json
import mimetypes
import os
import pwd
import shutil
import sys
import tempfile
from pathlib import Path

home = Path(sys.argv[1]).resolve()
requested = (sys.argv[2] or "").strip()
service_user = sys.argv[3]

normalized = requested.lstrip("/")
target = (home / normalized).resolve()
try:
    target.relative_to(home)
except ValueError:
    target = home

if not target.exists():
    raise SystemExit("target path not found")
if not target.is_file():
    raise SystemExit("target path is not a file")

tmp_dir = Path(tempfile.mkdtemp(prefix="workstation-export-", dir="/tmp"))
destination = tmp_dir / target.name
shutil.copy2(target, destination)

service_pwd = pwd.getpwnam(service_user)
os.chown(tmp_dir, service_pwd.pw_uid, service_pwd.pw_gid)
os.chown(destination, service_pwd.pw_uid, service_pwd.pw_gid)
os.chmod(tmp_dir, 0o700)
os.chmod(destination, 0o600)

print(
    json.dumps(
        {
            "ok": True,
            "path": str(destination),
            "filename": target.name,
            "media_type": mimetypes.guess_type(target.name)[0] or "application/octet-stream",
        },
        ensure_ascii=False,
    )
)
PY
}

sync_profile() {
  local username="$1"
  local group_name
  require_ldap_user "$username"
  group_name="$(primary_group_name "$username")"
  ensure_workspace_home "$username" "$group_name"
  ensure_host_login_home "$username" "$group_name"
  ensure_seeded_home "$username" "$group_name"
  sync_desktop_profile "$username" "$group_name"
  sync_mail_bridge_state "$username"
  sync_thunderbird_profile_defaults "$username"
  sync_brave_profile_defaults "$username"
  ensure_rootfs_state "$username"
  prune_overlay_runtime_artifacts "$(workspace_rootfs_upper "$username")"
  ensure_runtime_dirs "$username" "$group_name"
  ensure_kasmvnc_profile "$username" "$group_name"
  queue_wine_runtime_defaults "$username"
}

sync_all_profiles() {
  local username
  while IFS= read -r username; do
    [ -n "$username" ] || continue
    if ldap-user show "$username" >/dev/null 2>&1; then
      sync_profile "$username"
    fi
  done < <(workspace_users)
}

status_session() {
  local username="$1"
  local port active user_home
  require_ldap_user "$username"
  port="$(desktop_port "$username")"
  user_home="$(workspace_home_dir "$username")"
  if systemctl is-active --quiet "$(service_name "$username")"; then
    active=True
  else
    active=False
  fi
  python3 - <<EOF
import json
print(json.dumps({
    "username": ${username@Q},
    "port": ${port},
    "home": ${user_home@Q},
    "active": ${active},
}))
EOF
}

usage() {
  cat <<'EOF'
Usage:
  workstation-desktop-session ensure <ldap-username>
  workstation-desktop-session sync-profile <ldap-username>
  workstation-desktop-session prewarm-wine <ldap-username>
  workstation-desktop-session sync-all-profiles
  workstation-desktop-session status <ldap-username>
  workstation-desktop-session stop <ldap-username>
  workstation-desktop-session snapshot-list <ldap-username>
  workstation-desktop-session snapshot-create <ldap-username> [title] [description]
  workstation-desktop-session snapshot-delete <ldap-username> <snapshot-id>
  workstation-desktop-session snapshot-rollback <ldap-username> <snapshot-id>
  workstation-desktop-session reset-workspace <ldap-username>
  workstation-desktop-session keyring-sync <ldap-username>
  workstation-desktop-session audio-info <ldap-username>
  workstation-desktop-session audio-stream <ldap-username>
  workstation-desktop-session terminal-shell <ldap-username>
  workstation-desktop-session notification-monitor <ldap-username>
  workstation-desktop-session process-list <ldap-username>
  workstation-desktop-session process-kill <ldap-username> <pid>
  workstation-desktop-session clipboard-targets <ldap-username>
  workstation-desktop-session clipboard-read <ldap-username> <mime>
  workstation-desktop-session clipboard-set-image <ldap-username> <png-file>
  workstation-desktop-session clipboard-paste <ldap-username>
  workstation-desktop-session clipboard-import <ldap-username> <file> [file...]
  workstation-desktop-session file-list <ldap-username> [path]
  workstation-desktop-session file-upload <ldap-username> <path> <file> [file...]
  workstation-desktop-session file-export <ldap-username> <path>
EOF
}

require_root

cmd="${1:-}"
username="${2:-}"

case "$cmd" in
  ensure)
    [ -n "$username" ] || die "missing ldap username"
    with_user_lock "$username" ensure_session "$username"
    ;;
  sync-profile)
    [ -n "$username" ] || die "missing ldap username"
    with_user_lock "$username" sync_profile "$username"
    ;;
  prewarm-wine)
    [ -n "$username" ] || die "missing ldap username"
    with_user_lock "$username" sync_wine_runtime_defaults "$username"
    ;;
  sync-all-profiles)
    sync_all_profiles
    ;;
  status)
    [ -n "$username" ] || die "missing ldap username"
    status_session "$username"
    ;;
  stop)
    [ -n "$username" ] || die "missing ldap username"
    with_user_lock "$username" stop_session "$username"
    ;;
  snapshot-list)
    [ -n "$username" ] || die "missing ldap username"
    snapshot_list "$username"
    ;;
  snapshot-create)
    [ -n "$username" ] || die "missing ldap username"
    with_user_lock "$username" snapshot_create "$username" "${3:-}" "${4:-}"
    ;;
  snapshot-delete)
    [ -n "$username" ] || die "missing ldap username"
    [ -n "${3:-}" ] || die "missing snapshot id"
    with_user_lock "$username" snapshot_delete "$username" "${3:-}"
    ;;
  snapshot-rollback)
    [ -n "$username" ] || die "missing ldap username"
    [ -n "${3:-}" ] || die "missing snapshot id"
    with_user_lock "$username" snapshot_rollback "$username" "${3:-}"
    ;;
  reset-workspace)
    [ -n "$username" ] || die "missing ldap username"
    with_user_lock "$username" reset_workspace "$username"
    ;;
  keyring-sync)
    [ -n "$username" ] || die "missing ldap username"
    keyring_sync "$username"
    ;;
  audio-info)
    [ -n "$username" ] || die "missing ldap username"
    audio_info "$username"
    ;;
  audio-stream)
    [ -n "$username" ] || die "missing ldap username"
    audio_stream "$username"
    ;;
  terminal-shell)
    [ -n "$username" ] || die "missing ldap username"
    terminal_shell "$username"
    ;;
  notification-monitor)
    [ -n "$username" ] || die "missing ldap username"
    notification_monitor "$username"
    ;;
  process-list)
    [ -n "$username" ] || die "missing ldap username"
    process_list "$username"
    ;;
  process-kill)
    [ -n "$username" ] || die "missing ldap username"
    [ -n "${3:-}" ] || die "missing pid"
    process_kill "$username" "${3:-}"
    ;;
  clipboard-targets)
    [ -n "$username" ] || die "missing ldap username"
    clipboard_targets "$username"
    ;;
  clipboard-read)
    [ -n "$username" ] || die "missing ldap username"
    [ -n "${3:-}" ] || die "missing mime type"
    clipboard_read "$username" "${3:-}"
    ;;
  clipboard-set-image)
    [ -n "$username" ] || die "missing ldap username"
    [ -n "${3:-}" ] || die "missing image path"
    clipboard_set_image "$username" "${3:-}"
    ;;
  clipboard-paste)
    [ -n "$username" ] || die "missing ldap username"
    clipboard_paste "$username"
    ;;
  clipboard-import)
    [ -n "$username" ] || die "missing ldap username"
    shift 2
    [ "$#" -gt 0 ] || die "missing source files"
    clipboard_import_and_set "$username" "$@"
    ;;
  file-list)
    [ -n "$username" ] || die "missing ldap username"
    file_list "$username" "${3:-}"
    ;;
  file-upload)
    [ -n "$username" ] || die "missing ldap username"
    target_path="${3-}"
    shift 3
    [ "$#" -gt 0 ] || die "missing source files"
    file_upload "$username" "$target_path" "$@"
    ;;
  file-export)
    [ -n "$username" ] || die "missing ldap username"
    [ -n "${3:-}" ] || die "missing export path"
    file_export "$username" "${3:-}"
    ;;
  *)
    usage
    exit 1
    ;;
esac
