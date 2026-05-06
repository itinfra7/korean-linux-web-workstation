#!/usr/bin/env bash
set -euo pipefail

GROUP_NAME="${1:-procadmins}"
SOURCE_GROUPS=(sudo ldapadmins sudo-superadmins ldapadmins-ldap)

if ! getent group "$GROUP_NAME" >/dev/null 2>&1; then
  printf 'missing proc visibility group: %s\n' "$GROUP_NAME" >&2
  exit 1
fi

mapfile -t MEMBERS < <(
  for source_group in "${SOURCE_GROUPS[@]}"; do
    entry="$(getent group "$source_group" || true)"
    [ -n "$entry" ] || continue
    member_csv="${entry#*:*:*:}"
    [ -n "$member_csv" ] || continue
    IFS=',' read -r -a raw_members <<<"$member_csv"
    for username in "${raw_members[@]}"; do
      [ -n "$username" ] || continue
      getent passwd "$username" >/dev/null 2>&1 || continue
      printf '%s\n' "$username"
    done
  done | sort -u
)

members_csv=""
if [ "${#MEMBERS[@]}" -gt 0 ]; then
  members_csv="$(IFS=,; printf '%s' "${MEMBERS[*]}")"
fi

gpasswd -M "$members_csv" "$GROUP_NAME" >/dev/null
printf 'group=%s\n' "$GROUP_NAME"
printf 'members=%s\n' "$members_csv"
