#!/usr/bin/env bash
set -euo pipefail

export TZ="${TZ:-Asia/Seoul}"

apply_xfwm_setting() {
  local path="$1"
  local type="$2"
  local value="$3"
  if xfconf-query -c xfwm4 -p "$path" >/dev/null 2>&1; then
    xfconf-query -c xfwm4 -p "$path" -s "$value" >/dev/null 2>&1 || true
  else
    xfconf-query -c xfwm4 -p "$path" -n -t "$type" -s "$value" >/dev/null 2>&1 || true
  fi
}

apply_xsettings_setting() {
  local path="$1"
  local type="$2"
  local value="$3"
  if xfconf-query -c xsettings -p "$path" >/dev/null 2>&1; then
    xfconf-query -c xsettings -p "$path" -s "$value" >/dev/null 2>&1 || true
  else
    xfconf-query -c xsettings -p "$path" -n -t "$type" -s "$value" >/dev/null 2>&1 || true
  fi
}

apply_desktop_bool() {
  local path="$1"
  local value="$2"
  if xfconf-query -c xfce4-desktop -p "$path" >/dev/null 2>&1; then
    xfconf-query -c xfce4-desktop -p "$path" -s "$value" >/dev/null 2>&1 || true
  else
    xfconf-query -c xfce4-desktop -p "$path" -n -t bool -s "$value" >/dev/null 2>&1 || true
  fi
}

apply_desktop_int() {
  local path="$1"
  local value="$2"
  if xfconf-query -c xfce4-desktop -p "$path" >/dev/null 2>&1; then
    xfconf-query -c xfce4-desktop -p "$path" -s "$value" >/dev/null 2>&1 || true
  else
    xfconf-query -c xfce4-desktop -p "$path" -n -t int -s "$value" >/dev/null 2>&1 || true
  fi
}

apply_desktop_rgba() {
  local path="$1"
  xfconf-query -c xfce4-desktop -p "$path" -r >/dev/null 2>&1 || true
  xfconf-query -c xfce4-desktop -p "$path" -n -a \
    -t double -s 0 \
    -t double -s 0.501961 \
    -t double -s 0.501961 \
    -t double -s 1 >/dev/null 2>&1 || true
}

apply_keyboard_layout_setting() {
  local path="$1"
  local type="$2"
  local value="$3"
  if xfconf-query -c keyboard-layout -p "$path" >/dev/null 2>&1; then
    xfconf-query -c keyboard-layout -p "$path" -s "$value" >/dev/null 2>&1 || true
  else
    xfconf-query -c keyboard-layout -p "$path" -n -t "$type" -s "$value" >/dev/null 2>&1 || true
  fi
}

apply_browser_defaults() {
  local helper_dir helper_file
  helper_dir="${HOME}/.config/xfce4"
  helper_file="${helper_dir}/helpers.rc"

  mkdir -p "${helper_dir}"
  cat >"${helper_file}" <<'EOF'
WebBrowser=brave
Browser=brave
FileManager=thunar
MailReader=thunderbird
TerminalEmulator=xfce4-terminal
EOF

  export BROWSER="${BROWSER:-brave-browser}"

  if command -v xdg-settings >/dev/null 2>&1; then
    for _ in $(seq 1 10); do
      xdg-settings set default-web-browser brave-browser.desktop >/dev/null 2>&1 && break
      sleep 1
    done
  fi

  if command -v xdg-mime >/dev/null 2>&1; then
    xdg-mime default brave-browser.desktop x-scheme-handler/http >/dev/null 2>&1 || true
    xdg-mime default brave-browser.desktop x-scheme-handler/https >/dev/null 2>&1 || true
    xdg-mime default brave-browser.desktop x-scheme-handler/about >/dev/null 2>&1 || true
    xdg-mime default brave-browser.desktop x-scheme-handler/unknown >/dev/null 2>&1 || true
    xdg-mime default brave-browser.desktop text/html >/dev/null 2>&1 || true
    xdg-mime default brave-browser.desktop application/xhtml+xml >/dev/null 2>&1 || true
    xdg-mime default thunar.desktop inode/directory >/dev/null 2>&1 || true
    xdg-mime default thunderbird_thunderbird.desktop x-scheme-handler/mailto >/dev/null 2>&1 || true
    xdg-mime default thunderbird_thunderbird.desktop message/rfc822 >/dev/null 2>&1 || true
    xdg-mime default org.nomacs.ImageLounge.desktop image/png >/dev/null 2>&1 || true
    xdg-mime default org.nomacs.ImageLounge.desktop image/jpeg >/dev/null 2>&1 || true
    xdg-mime default org.nomacs.ImageLounge.desktop image/gif >/dev/null 2>&1 || true
    xdg-mime default org.nomacs.ImageLounge.desktop image/webp >/dev/null 2>&1 || true
    xdg-mime default org.nomacs.ImageLounge.desktop image/bmp >/dev/null 2>&1 || true
    xdg-mime default org.nomacs.ImageLounge.desktop image/tiff >/dev/null 2>&1 || true
  fi
}

apply_ibus_defaults() {
  command -v gsettings >/dev/null 2>&1 || return 0
  for _ in $(seq 1 30); do
    if gsettings writable org.freedesktop.ibus.general preload-engines >/dev/null 2>&1; then
      gsettings set org.freedesktop.ibus.general use-system-keyboard-layout false >/dev/null 2>&1 || true
      gsettings set org.freedesktop.ibus.general preload-engines "['hangul']" >/dev/null 2>&1 || true
      gsettings set org.freedesktop.ibus.general engines-order "['hangul']" >/dev/null 2>&1 || true
      break
    fi
    sleep 1
  done
  if command -v ibus >/dev/null 2>&1; then
    ibus engine hangul >/dev/null 2>&1 || true
  fi
}

apply_keyboard_layout_defaults() {
  for _ in $(seq 1 30); do
    apply_keyboard_layout_setting /Default/XkbDisable bool true
    apply_keyboard_layout_setting /Default/XkbLayout string kr
    apply_keyboard_layout_setting /Default/XkbVariant string kr104
    apply_keyboard_layout_setting /Default/XkbOptions string korean:ralt_hangul,korean:rctrl_hanja
    if xfconf-query -c keyboard-layout -p /Default/XkbDisable >/dev/null 2>&1; then
      break
    fi
    sleep 1
  done
}

trust_desktop_launchers() {
  local desktop_dir="${HOME}/Desktop"
  local file ok checksum
  [ -d "${desktop_dir}" ] || return 0
  command -v gio >/dev/null 2>&1 || return 0
  mkdir -p "${HOME}/.local/share/gvfs-metadata"
  chmod 700 "${HOME}/.local/share/gvfs-metadata" >/dev/null 2>&1 || true
  start_gvfs_metadata

  for _ in $(seq 1 20); do
    ok=1
    for file in "${desktop_dir}"/*.desktop; do
      [ -f "${file}" ] || continue
      chmod 755 "${file}" >/dev/null 2>&1 || true
      checksum="$(sha256sum "${file}" | awk '{print $1}')"
      gio set "${file}" metadata::trusted yes >/dev/null 2>&1 || ok=0
      gio set "${file}" metadata::xfce-exe-checksum "${checksum}" >/dev/null 2>&1 || ok=0
      if ! gio info -a metadata::xfce-exe-checksum "${file}" 2>/dev/null | grep -Fq "${checksum}"; then
        ok=0
      fi
    done
    [ "${ok}" -eq 1 ] && return 0
    sleep 1
  done
}

start_gvfs_metadata() {
  local candidate
  for candidate in gvfsd-metadata /usr/libexec/gvfsd-metadata /usr/lib/gvfs/gvfsd-metadata; do
    if command -v "${candidate}" >/dev/null 2>&1; then
      "${candidate}" >/dev/null 2>&1 &
      return 0
    fi
    if [ -x "${candidate}" ]; then
      "${candidate}" >/dev/null 2>&1 &
      return 0
    fi
  done
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
  find "${HOME}/.local/share/Trash/files" -mindepth 1 -maxdepth 1 -print -quit 2>/dev/null | grep -q .
}

update_trash_launcher_icon() {
  local desktop_file icon_name current_icon
  desktop_file="${HOME}/Desktop/03-workstation-trash.desktop"
  [ -f "${desktop_file}" ] || return 1
  icon_name="user-trash"
  if trash_has_items; then
    icon_name="user-trash-full"
  fi
  current_icon="$(sed -n 's/^Icon=//p' "${desktop_file}" | head -n 1)"
  if [ "${current_icon}" = "${icon_name}" ]; then
    return 1
  fi
  if grep -q '^Icon=' "${desktop_file}"; then
    sed -i "s/^Icon=.*/Icon=${icon_name}/" "${desktop_file}" >/dev/null 2>&1 || return 1
  else
    printf '\nIcon=%s\n' "${icon_name}" >>"${desktop_file}" || return 1
  fi
  return 0
}

start_trash_launcher_monitor() {
  local monitor="/usr/local/lib/workstation-desktop/workstation-trash-icon-monitor.sh"
  [ -x "${monitor}" ] || return 0
  if pgrep -u "$(id -u)" -af '^bash /usr/local/lib/workstation-desktop/workstation-trash-icon-monitor\.sh$' >/dev/null 2>&1; then
    return 0
  fi
  nohup "${monitor}" >/dev/null 2>&1 &
}

launch_desktop_fixups() {
  (
    sleep 2
    trust_desktop_launchers || true
    if update_trash_launcher_icon && command -v xfdesktop >/dev/null 2>&1; then
      xfdesktop --reload >/dev/null 2>&1 || true
    fi
    start_trash_launcher_monitor || true
    if [ -x /usr/local/lib/workstation-desktop/workstation-image-clipboard-bridge.py ]; then
      if ! pgrep -u "$(id -u)" -f 'workstation-image-clipboard-bridge.py' >/dev/null 2>&1; then
        /usr/local/lib/workstation-desktop/workstation-image-clipboard-bridge.py >/dev/null 2>&1 &
      fi
    fi
    if command -v devilspie2 >/dev/null 2>&1 && [ -d /usr/local/share/workstation-desktop/devilspie2 ]; then
      if ! pgrep -u "$(id -u)" -f 'devilspie2 --folder /usr/local/share/workstation-desktop/devilspie2' >/dev/null 2>&1; then
        devilspie2 --folder /usr/local/share/workstation-desktop/devilspie2 >/dev/null 2>&1 &
      fi
    fi
  ) >/dev/null 2>&1 &
}

apply_wallpaper_path() {
  local path="$1"
  local base
  [ -n "$path" ] || return 0
  for monitor in monitor0 monitorVNC-0; do
    for ws in 0 1 2 3; do
      base="/backdrop/screen0/${monitor}/workspace${ws}"
      xfconf-query -c xfce4-desktop -p "${base}/last-image" -n -t string -s "$path" >/dev/null 2>&1 || \
        xfconf-query -c xfce4-desktop -p "${base}/last-image" -s "$path" >/dev/null 2>&1 || true
      apply_desktop_int "${base}/image-style" 2
      apply_desktop_int "${base}/color-style" 1
    done
  done
}

for _ in $(seq 1 30); do
  if xfconf-query -c xsettings -p /Net/ThemeName >/dev/null 2>&1; then
    apply_xsettings_setting /Net/ThemeName string Chicago95
    apply_xsettings_setting /Net/IconThemeName string Chicago95
    apply_xsettings_setting /Gtk/CursorThemeName string "Chicago95 Standard Cursors Black"
    apply_xsettings_setting /Gtk/CursorThemeSize int 16
    apply_xsettings_setting /Gtk/FontName string "UnDotum 10"
    apply_xsettings_setting /Gtk/MonospaceFontName string "D2Coding 10"
    apply_xsettings_setting /Gtk/ToolbarStyle string icons
    apply_xsettings_setting /Gtk/DialogsUseHeader bool false
    break
  fi
  sleep 1
done

for _ in $(seq 1 30); do
  if xfconf-query -c xfwm4 -p /general/theme >/dev/null 2>&1; then
    apply_xfwm_setting /general/theme string Chicago95
    apply_xfwm_setting /general/title_font string "UnDotum Bold 10"
    apply_xfwm_setting /general/use_compositing bool false
    apply_xfwm_setting /general/show_dock_shadow bool false
    apply_xfwm_setting /general/show_frame_shadow bool false
    apply_xfwm_setting /general/show_popup_shadow bool false
    apply_xfwm_setting /general/frame_opacity int 100
    apply_xfwm_setting /general/inactive_opacity int 100
    apply_xfwm_setting /general/move_opacity int 100
    apply_xfwm_setting /general/resize_opacity int 100
    apply_xfwm_setting /general/popup_opacity int 100
    apply_xfwm_setting /general/workspace_count int 1
    break
  fi
  sleep 1
done

for _ in $(seq 1 30); do
  if xfconf-query -c xfce4-desktop -l >/dev/null 2>&1; then
    apply_desktop_int /desktop-icons/style 2
    apply_desktop_bool /desktop-icons/file-icons/show-filesystem false
    apply_desktop_bool /desktop-icons/file-icons/show-home false
    apply_desktop_bool /desktop-icons/file-icons/show-trash false
    apply_desktop_bool /desktop-icons/file-icons/show-removable false
    for monitor in monitor0 monitorVNC-0; do
      for ws in 0 1 2 3; do
        base="/backdrop/screen0/${monitor}/workspace${ws}"
        apply_desktop_int "${base}/color-style" 1
        apply_desktop_int "${base}/image-style" 2
        xfconf-query -c xfce4-desktop -p "${base}/last-image" -n -t string -s "" >/dev/null 2>&1 || \
          xfconf-query -c xfce4-desktop -p "${base}/last-image" -s "" >/dev/null 2>&1 || true
        apply_desktop_rgba "${base}/rgba1"
        apply_desktop_rgba "${base}/rgba2"
      done
    done
    if [ -f /usr/local/share/workstation-desktop/assets/wallpaper.path ]; then
      wallpaper_path="$(sed -n '1p' /usr/local/share/workstation-desktop/assets/wallpaper.path 2>/dev/null || true)"
      apply_wallpaper_path "${wallpaper_path}"
    fi
    break
  fi
  sleep 1
done

if command -v setxkbmap >/dev/null 2>&1; then
  setxkbmap -layout kr -variant kr104 -option korean:ralt_hangul,korean:rctrl_hanja >/dev/null 2>&1 || true
fi
apply_browser_defaults
apply_keyboard_layout_defaults
apply_ibus_defaults

trust_desktop_launchers
update_trash_launcher_icon
launch_desktop_fixups
