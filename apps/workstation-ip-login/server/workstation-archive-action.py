#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


PEAZIP_BIN = shutil.which("peazip") or "/usr/bin/peazip"
PEAZIP_FLAGS = {
    "extract-here": "-ext2here",
    "extract-folder": "-ext2newfolder",
    "extract-smart": "-ext2folder",
    "compress": "-add2archive",
}


def fail(message: str, exit_code: int = 1) -> int:
    print(message, file=sys.stderr)
    notify("압축 작업 실패", message)
    return exit_code


def notify(summary: str, body: str = "") -> None:
    notify_send = shutil.which("notify-send")
    if not notify_send:
        return
    command = [notify_send, "-u", "normal", summary]
    if body:
      command.append(body)
    subprocess.Popen(
        command,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def ensure_command(path: str, label: str) -> None:
    if Path(path).exists():
        return
    raise FileNotFoundError(f"{label} 실행 파일을 찾을 수 없습니다: {path}")


def collect_paths(arguments: list[str]) -> list[Path]:
    items = [Path(item).expanduser() for item in arguments]
    missing = [str(path) for path in items if not path.exists()]
    if missing:
        raise FileNotFoundError("다음 파일을 찾을 수 없습니다: " + ", ".join(missing))
    return items


def launch_peazip(mode: str, arguments: list[str]) -> int:
    items = collect_paths(arguments)
    command = [PEAZIP_BIN, PEAZIP_FLAGS[mode], *[str(item) for item in items]]
    if os.environ.get("WORKSTATION_ARCHIVE_TEST_ONLY") == "1":
        print(json.dumps(command, ensure_ascii=False))
        return 0
    subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    return 0


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        return fail("usage: workstation-archive-action <extract-here|extract-folder|extract-smart|compress> <path> [path...]")

    mode = argv[1]
    arguments = argv[2:]

    try:
        ensure_command(PEAZIP_BIN, "PeaZip")
        if mode in PEAZIP_FLAGS:
            return launch_peazip(mode, arguments)
        return fail(f"지원하지 않는 동작입니다: {mode}")
    except FileNotFoundError as exc:
        return fail(str(exc))
    except RuntimeError as exc:
        return fail(str(exc))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
