#!/usr/bin/env bash
set -euo pipefail

GROUP_NAME="${1:-procadmins}"

if [ "$(id -u)" -ne 0 ]; then
  printf 'workstation-proc-hidepid-apply: must run as root\n' >&2
  exit 1
fi

if ! getent group "${GROUP_NAME}" >/dev/null 2>&1; then
  printf 'workstation-proc-hidepid-apply: missing group %s\n' "${GROUP_NAME}" >&2
  exit 1
fi

PROC_GID="$(getent group "${GROUP_NAME}" | cut -d: -f3)"
CURRENT_OPTS="$(findmnt -no OPTIONS /proc)"

BASE_OPTS="$(
  printf '%s\n' "${CURRENT_OPTS}" \
    | tr ',' '\n' \
    | grep -vE '^(hidepid=|gid=)' \
    | paste -sd, -
)"

if [ -n "${BASE_OPTS}" ]; then
  mount -o "remount,${BASE_OPTS},hidepid=2,gid=${PROC_GID}" /proc
else
  mount -o "remount,hidepid=2,gid=${PROC_GID}" /proc
fi

findmnt -no OPTIONS /proc
