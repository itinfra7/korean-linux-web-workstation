# Install Map

Use this map when packaging or writing an installer.

## Application

- `apps/workstation-ip-login` -> `/opt/korean-linux-web-workstation/apps/workstation-ip-login`
- Python virtualenv -> `/opt/korean-linux-web-workstation/.venv`
- `deploy/env/workstation-ip-login.env.example` -> `/etc/workstation-ip-login.env`

## Privileged Helper

- `apps/workstation-ip-login/server/workstation-desktop-session.sh` -> `/usr/local/sbin/workstation-desktop-session`
- `apps/workstation-ip-login/server/workstation-ip-login-desktop.sudoers` -> `/etc/sudoers.d/workstation-ip-login-desktop`

## Desktop Runtime Scripts

Install executable scripts from `apps/workstation-ip-login/server` to `/usr/local/lib/workstation-desktop`, except wrappers that are launched directly from desktop files.

Install these wrappers to `/usr/local/bin`:

- `workstation-archive-action.py` as `workstation-archive-action`
- `workstation-byobu.sh` as `workstation-byobu`
- `workstation-explorer.sh` as `workstation-explorer`
- `workstation-gameconqueror-wrapper.sh` as `workstation-gameconqueror`
- `workstation-joplin`
- `workstation-kakaotalk`
- `workstation-libreoffice.sh` as `workstation-libreoffice`
- `workstation-notepad-plus-plus`
- `workstation-terminal.sh` as `workstation-terminal`
- `workstation-user-shell.sh` as `workstation-user-shell`
- `workstation-wine-run.py` as `workstation-wine-run`
- `workstation-winexec.sh` as `workstation-winexec`
- `workstation-winrun.py` as `workstation-winrun`

## Desktop Seed And Assets

- `apps/workstation-ip-login/server/skel` -> `/usr/local/share/workstation-desktop/skel`
- `apps/workstation-ip-login/server/applications` -> `/usr/local/share/workstation-desktop/applications`
- `apps/workstation-ip-login/server/assets` -> `/usr/local/share/workstation-desktop/assets`
- `apps/workstation-ip-login/server/libreoffice` -> `/usr/local/share/workstation-desktop/libreoffice`
- `apps/workstation-ip-login/server/mime` -> `/usr/local/share/mime/packages`
- `apps/workstation-ip-login/server/notepad-plus-plus` -> `/usr/local/share/workstation-desktop/notepad-plus-plus`
- `apps/workstation-ip-login/server/devilspie2` -> `/usr/local/share/workstation-desktop/devilspie2`

## Services

- `deploy/systemd/workstation-ip-login-web.service` -> `/etc/systemd/system/workstation-ip-login-web.service`
- `deploy/systemd/workstation-ip-login-discord-bot.service` -> `/etc/systemd/system/workstation-ip-login-discord-bot.service`
- `deploy/systemd/workstation-kasmvnc@.service` -> `/etc/systemd/system/workstation-kasmvnc@.service`
- `apps/workstation-ip-login/server/workstation-wine-prewarm@.service` -> `/etc/systemd/system/workstation-wine-prewarm@.service`

## Web Proxy

- `deploy/nginx/korean-linux-web-workstation.conf.example` -> `/etc/nginx/sites-available/<PUBLIC_DOMAIN>`
