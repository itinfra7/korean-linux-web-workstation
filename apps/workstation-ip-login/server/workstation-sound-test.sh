#!/usr/bin/env bash
set -euo pipefail

if [ -z "${PULSE_SERVER:-}" ]; then
  for pulse_socket in "${XDG_RUNTIME_DIR:-}/pulse/native" "${XDG_RUNTIME_DIR:-}"/xpra/pulse-*/pulse/native "${HOME:-}"/.xpra/pulse-*/pulse/native; do
    if [ -S "${pulse_socket}" ]; then
      export PULSE_SERVER="unix:${pulse_socket}"
      break
    fi
  done
fi

run_test() {
  if command -v pactl >/dev/null 2>&1; then
    local module_id=""
    module_id="$(pactl load-module module-sine frequency=440 2>/dev/null || true)"
    if [ -n "${module_id}" ]; then
      sleep 3
      pactl unload-module "${module_id}" >/dev/null 2>&1 || true
      return 0
    fi
  fi
  if command -v speaker-test >/dev/null 2>&1; then
    speaker-test -t sine -f 440 -c 2 -l 1
    return 0
  fi
  printf 'No working audio test command is available.\n' >&2
  return 1
}

run_test
if [ -t 0 ] || [ -t 1 ]; then
  printf '\nPress Enter to close...\n'
  read -r || true
fi
