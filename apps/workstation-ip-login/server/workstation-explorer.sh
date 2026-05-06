#!/usr/bin/env bash
set -euo pipefail

target="${HOME:-/}"

case "${1:-computer}" in
  computer)
    target="/"
    ;;
  documents)
    target="${HOME:-/}"
    ;;
  trash)
    target="trash:/"
    ;;
  path)
    shift
    target="${1:-${HOME:-/}}"
    ;;
  *)
    if [ "$#" -gt 0 ]; then
      target="$1"
    fi
    ;;
esac

if command -v thunar >/dev/null 2>&1; then
  exec thunar "$target"
fi

exec xdg-open "$target"
