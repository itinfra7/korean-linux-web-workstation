#!/usr/bin/env bash
set -euo pipefail

die() {
  printf 'workstation-snap-launch: %s\n' "$*" >&2
  exit 1
}

action=""
if [ "${1:-}" = "--action" ]; then
  action="${2:-}"
  shift 2
fi

desktop_id="${1:-}"
[ -n "$desktop_id" ] || die "missing desktop id"
shift || true

home_dir="${HOME:-$(getent passwd "$(id -un)" | cut -d: -f6)}"
socket_path="${home_dir}/.local/share/workstation-snap/bridge.sock"
[ -S "$socket_path" ] || die "snap bridge is not available"

python3 - "$socket_path" "$desktop_id" "$action" "$@" <<'PY'
import json
import socket
import sys

socket_path = sys.argv[1]
desktop_id = sys.argv[2]
action = sys.argv[3]
argv = sys.argv[4:]

payload = {
    "desktop_id": desktop_id,
    "argv": argv,
}
if action:
    payload["action"] = action

with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
    client.connect(socket_path)
    client.sendall(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
    client.shutdown(socket.SHUT_WR)
    response = bytearray()
    while True:
      chunk = client.recv(65536)
      if not chunk:
        break
      response.extend(chunk)

if not response:
    print("workstation-snap-launch: empty response from bridge", file=sys.stderr)
    raise SystemExit(1)

reply = json.loads(response.decode("utf-8"))
if not reply.get("ok"):
    print(reply.get("error", "workstation-snap-launch failed"), file=sys.stderr)
    raise SystemExit(1)
PY
