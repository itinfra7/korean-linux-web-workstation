# korean-linux-web-workstation

Korean Linux web workstation with LDAP login, browser-based KasmVNC desktop access, and a Windows 95 style workspace UI.

## Screenshots

## Features

### Login and access

- LDAP password login.
- Discord IP grant gate for browser access.
- Email OTP login for users who registered an external email address.
- Email OTP request limit and expiration controls.
- Session cookie flow with workspace preparation and workspace status polling.
- Logout endpoint and browser session cleanup.

### Browser workspace

- KasmVNC reverse proxy through the web application.
- Windows 95 style VNC sidebar injected into the KasmVNC page.
- Sidebar buttons for fullscreen, browser notifications, terminal, task manager, file transfer, chat, workspace snapshots, and account settings.
- Sidebar button pressed-state synchronization while each panel is open.
- Windows 95 style draggable panel popups, shared active/inactive panel behavior, and shared status toasts near the VNC sidebar.
- Browser notification bridge for workspace GUI notifications.
- Browser notification bridge for unread chat and screenshot messages without exposing message content.
- Browser audio bridge for workspace sound through WebSocket PCM streaming.

### Desktop session

- Per-user XFCE desktop session served through KasmVNC.
- Chicago95 GTK, XFWM, icon, and cursor styling.
- Korean desktop seed with XFCE panel, window manager, desktop, Thunar, MIME, and helper defaults.
- Korean input setup through IBus and IBus Hangul.
- Korean font baseline with Noto CJK, UnDotum, D2Coding, and JoseonGulim webfont assets.
- PulseAudio/PipeWire session setup and sound test helper.
- Per-user runtime, profile, KasmVNC, keyring, and mail state synchronization.
- Wine prewarm service for faster first launch of Wine-backed applications.
- Process visibility hardening helpers for `/proc` policy management.

### VNC sidebar panels

- Terminal panel with persistent xterm.js shell, resize support, and text clipboard key/mouse interaction.
- Task manager panel with current-user process list, command/name/PID/state search, column sorting, live refresh, and SIGKILL confirmation.
- File transfer panel with directory browsing, upload, download, drag-and-drop upload, address bar, and refresh.
- Chat panel with workspace user list, per-user unread badges, text messages, screenshot messages, scrollback pagination, copyable message text, image preview, image open, and image download.
- Workspace snapshot panel with create, list, rollback, delete, and reset actions for the logged-in user workspace.
- Account settings panel with LDAP password change, external email registration, external email change, email verification, and logout.

### Clipboard and files

- Text clipboard bridge between browser and workspace.
- PNG image clipboard bridge from browser into workspace applications.
- Workspace image clipboard polling from the VNC session back to the browser.
- File clipboard import into the workspace.
- File URI clipboard export from workspace selections.
- Safe upload filename normalization and collision handling.

### Chat

- Chat storage in SQLite.
- Chat media storage for workspace screenshots.
- Workspace-only PNG screenshot capture for chat, excluding browser chrome, VNC sidebar, and panel popups.
- LDAP workspace user discovery for chat recipients.
- Test-account filtering for chat user lists.
- Initial message load with older-message pagination.
- Per-peer read markers and unread counts.
- Sidebar unread total badge.
- Per-user unread badges in the chat user list.
- Browser notification on unread chat or screenshot arrival while unread items remain.

### Account and email

- LDAP password change from the account panel.
- External email registration with verification code.
- External email change with LDAP password verification.
- 10-minute verification window for email registration and change.
- Duplicate external email prevention.
- Local mail-domain external email rejection.
- Email-login OTP sent to the registered external email.
- Thunderbird profile synchronization and managed account defaults.
- Mail bridge state synchronization for per-user desktop mail integration.

### Workspace management

- Per-user workspace creation from the repository skel seed.
- Per-user workspace reset.
- Per-user workspace snapshot create/list/delete/rollback.
- Workspace profile synchronization.
- Workspace session status and stop commands.
- Runtime artifact pruning during reset/sync.
- Legacy transfer directory migration.
- Legacy shared-home path cleanup.

### Application and desktop integrations

- LibreOffice Korean defaults, Korean command/menu overrides, and wrapper launchers for Writer, Calc, Impress, Draw, Base, Math, and Start Center.
- LibreOffice duplicate menu suppression through package manager desktop-file override configuration.
- Desktop launchers for terminal, Byobu, My Computer, My Documents, Trash, Notepad++, KakaoTalk, Joplin, Windows runner, and LibreOffice apps.
- Thunar custom actions and MIME defaults.
- Trash icon monitor that keeps the desktop trash launcher trusted and updates empty/full icon state.
- Windows executable handling through Wine wrapper scripts and binfmt entries for common Windows executable extensions.
- Wine-backed Notepad++ wrapper and profile seed.
- Wine-backed KakaoTalk wrapper and initialization helper.
- Joplin launcher wrapper.
- PeaZip profile seed.
- Brave profile defaults.
- Snap launcher bridge with session environment and Korean input propagation.
- Thunderbird Snap integration and managed profile sync.
- GameConqueror wrapper.
- PySolFC music seed.

### Package baseline

- Core services: Redis, nginx, Python, sudo, LDAP tools, SSSD, NSS/PAM SSSD.
- Desktop stack: XFCE, XFCE goodies, Thunar, D-Bus, PulseAudio, PipeWire, IBus, IBus Hangul, Korean fonts.
- Utilities: Byobu, Wine, Winetricks, cabextract, p7zip, zip, unzip, xclip, xsel, ImageMagick, xdotool, wmctrl.
- Office and productivity: LibreOffice, Thunderbird.
- Education, science, and games: GameConqueror, PySolFC, Marble, KTouch, Minuet, Kalzium, GPeriodic, PSPP, Grace, Fityk, Avogadro, GoldenDict, DB Browser for SQLite.

## Management Commands

`workstation-desktop-session` supports:

```text
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
```

Installed wrapper commands:

```text
workstation-archive-action
workstation-byobu
workstation-explorer
workstation-gameconqueror
workstation-joplin
workstation-kakaotalk
workstation-libreoffice
workstation-notepad-plus-plus
workstation-terminal
workstation-user-shell
workstation-wine-run
workstation-winexec
workstation-winrun
```

Desktop runtime helper scripts:

```text
workstation-brave-profile.py
workstation-image-clipboard-bridge.py
workstation-kakaotalk-init.py
workstation-kasmvnc-session.sh
workstation-libreoffice-menu-overrides.py
workstation-libreoffice-profile.py
workstation-libreoffice-registry-patch.py
workstation-mail-bridge-sync.py
workstation-notepad-plus-plus-init.py
workstation-peazip-profile.py
workstation-proc-hidepid-apply.sh
workstation-procadmins-sync.sh
workstation-snap-bridge.py
workstation-snap-launch.sh
workstation-sound-test.sh
workstation-thunar-uca-merge.py
workstation-thunderbird-profile.py
workstation-trash-icon-monitor.sh
workstation-wine-template-build.py
workstation-xfce-inner-session.sh
workstation-xfce-logout.sh
workstation-xfce-poststart.sh
workstation-xfce-session.sh
```

## Layout

- `apps/workstation-ip-login`: application and desktop integration source
- `deploy/env`: environment template
- `deploy/systemd`: service templates
- `deploy/nginx`: reverse proxy template
- `deploy/packages`: package baseline references
- `docs/screenshots`: screenshot placeholders

## Required Configuration

Copy `deploy/env/workstation-ip-login.env.example` to `/etc/workstation-ip-login.env` and replace every placeholder.

Required external services:

- Redis
- LDAP or LDAPS directory
- SMTP/sendmail-compatible local mail transport
- Discord bot token and guild/channel/role IDs
- KasmVNC and XFCE desktop stack

## Install Outline

1. Install OS packages from `deploy/packages/apt-packages.txt`.
2. Install Python dependencies from `apps/workstation-ip-login/requirements.txt` into a virtualenv.
3. Install server scripts from `apps/workstation-ip-login/server` into `/usr/local/bin`, `/usr/local/sbin`, and `/usr/local/lib/workstation-desktop` according to the service templates.
4. Use `deploy/INSTALL_MAP.md` for exact file destinations.
5. Install `deploy/systemd/*.service` and `deploy/nginx/*.conf.example` with local domain values.
6. Enable Redis, nginx, web, Discord bot, and KasmVNC services.

## Third-party Sources

Bundled files:

| Name | Files | Source | License |
| --- | --- | --- | --- |
| xterm.js | `apps/workstation-ip-login/static/vendor/xterm/*` | https://github.com/xtermjs/xterm.js | MIT |
| PySolFC music | `apps/workstation-ip-login/server/skel/.pysolfc/music/*` | https://pysolfc.sourceforge.io/ | GPL, see bundled `.COPYRIGHT` files |
| JoseonGulim webfont | `apps/workstation-ip-login/static/fonts/JoseonGulim.woff` | https://noonnu.cc/en/font_page/415 | Chosun Ilbo font license |
| Default wallpaper assets | `apps/workstation-ip-login/server/assets/workstation-default-wallpaper*.jpg` | bundled project assets | MIT |

Theme and font references:

| Name | Referenced by | Source | License |
| --- | --- | --- | --- |
| Chicago95 GTK, XFWM, icon, and cursor theme | `apps/workstation-ip-login/server/skel/.config/xfce4/xfconf/xfce-perchannel-xml/*` | https://github.com/grassmunk/Chicago95 | GPLv3+ and MIT |
| UnDotum | XFCE `FontName` | https://packages.debian.org/search?keywords=fonts-unfonts-core | GPL |
| D2Coding | XFCE `MonospaceFontName` | https://github.com/naver/d2codingfont | OFL |

Python packages:

| Package | Source | License |
| --- | --- | --- |
| `discord.py` | https://github.com/Rapptz/discord.py | MIT |
| `fastapi` | https://github.com/fastapi/fastapi | MIT |
| `httpx` | https://github.com/encode/httpx | BSD-3-Clause |
| `jinja2` | https://github.com/pallets/jinja | BSD-3-Clause |
| `ldap3` | https://github.com/cannatag/ldap3 | LGPL-3.0 |
| `python-multipart` | https://github.com/Kludex/python-multipart | Apache-2.0 |
| `redis` | https://github.com/redis/redis-py | MIT |
| `uvicorn` | https://github.com/encode/uvicorn | BSD-3-Clause |
| `websockets` | https://github.com/python-websockets/websockets | BSD-3-Clause |

Runtime packages and integrations:

| Package or integration | Source |
| --- | --- |
| Redis server | https://redis.io/ |
| nginx | https://nginx.org/ |
| Python | https://www.python.org/ |
| sudo | https://www.sudo.ws/ |
| OpenLDAP tools | https://www.openldap.org/ |
| SSSD, `libnss-sss`, `libpam-sss` | https://sssd.io/ |
| KasmVNC | https://github.com/kasmtech/KasmVNC |
| XFCE, XFCE goodies, Thunar | https://xfce.org/ |
| D-Bus | https://www.freedesktop.org/wiki/Software/dbus/ |
| PulseAudio | https://www.freedesktop.org/wiki/Software/PulseAudio/ |
| PipeWire | https://pipewire.org/ |
| IBus | https://github.com/ibus/ibus |
| IBus Hangul | https://github.com/libhangul/ibus-hangul |
| Noto CJK fonts | https://github.com/notofonts/noto-cjk |
| Byobu | https://www.byobu.org/ |
| LibreOffice | https://www.libreoffice.org/ |
| Wine | https://www.winehq.org/ |
| Winetricks | https://github.com/Winetricks/winetricks |
| cabextract | https://www.cabextract.org.uk/ |
| p7zip | https://github.com/p7zip-project/p7zip |
| Info-ZIP `zip` and `unzip` | https://infozip.sourceforge.net/ |
| xclip | https://github.com/astrand/xclip |
| xsel | https://github.com/kfish/xsel |
| ImageMagick | https://imagemagick.org/ |
| xdotool | https://github.com/jordansissel/xdotool |
| wmctrl | https://tripie.sweb.cz/utils/wmctrl/ |
| python-ldap | https://www.python-ldap.org/ |
| scanmem / GameConqueror | https://github.com/scanmem/scanmem |
| PySolFC | https://pysolfc.sourceforge.io/ |
| KDE Marble | https://apps.kde.org/marble/ |
| KDE KTouch | https://apps.kde.org/ktouch/ |
| KDE Minuet | https://apps.kde.org/minuet/ |
| KDE Kalzium | https://apps.kde.org/kalzium/ |
| GPeriodic | http://gperiodic.seul.org/ |
| GNU PSPP | https://www.gnu.org/software/pspp/ |
| Grace | https://plasma-gate.weizmann.ac.il/Grace/ |
| Fityk | https://fityk.nieto.pl/ |
| Avogadro | https://avogadro.cc/ |
| GoldenDict | https://github.com/goldendict/goldendict |
| DB Browser for SQLite | https://sqlitebrowser.org/ |
| Thunderbird | https://www.thunderbird.net/ |
| Brave | https://brave.com/ |
| PeaZip | https://peazip.github.io/ |
| Notepad++ | https://notepad-plus-plus.org/ |
| Joplin | https://joplinapp.org/ |
| KakaoTalk | https://www.kakaocorp.com/page/service/service/KakaoTalk |
| Discord developer platform | https://discord.com/developers/docs/intro |

Product names are names of their respective owners.

## License

MIT, by itinfra7 from GitHub.
