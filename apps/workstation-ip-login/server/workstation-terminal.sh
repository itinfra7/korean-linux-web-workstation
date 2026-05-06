#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -eq 0 ]; then
  exec xfce4-terminal --disable-server --working-directory="${PWD:-${HOME:-/}}" --command=/usr/local/bin/workstation-user-shell
fi

exec xfce4-terminal --disable-server "$@"
