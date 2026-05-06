#!/usr/bin/env bash
set -euo pipefail

uid="$(id -u)"
logout_signal="/tmp/workstation-logout-requested-${uid}"

umask 077
: > "${logout_signal}"
chmod 600 "${logout_signal}" 2>/dev/null || true
nohup sh -c "sleep 30; rm -f '${logout_signal}'" >/dev/null 2>&1 &

exec xfce4-session-logout --logout --fast
