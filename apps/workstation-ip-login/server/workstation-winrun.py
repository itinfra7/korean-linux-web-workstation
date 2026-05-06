#!/usr/bin/env python3

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


WINE_RUNNER = "/usr/local/bin/workstation-wine-run"
ENV_BIN = "/usr/bin/env"
DOSBOX_BIN = "dosbox-x"
STATE_ROOT_NAME = ".local/share/workstation-windows"
DOSBOX_SET_OPTIONS = (
    "cpu core=dynamic",
    "cpu cycles=max",
    "sdl output=surface",
    "sdl doublescan=false",
    "render frameskip=1",
    "render scaler=none",
    "dos hard drive data rate limit=0",
    "dos floppy drive data rate limit=0",
)
CMD_HINTS = (
    b"setlocal",
    b"endlocal",
    b"%~",
    b"enabledelayedexpansion",
    b"cmdextversion",
    b"errorlevel",
)


def fail(message: str, code: int = 1) -> None:
    print(f"workstation-winrun: {message}", file=sys.stderr)
    raise SystemExit(code)


def state_root() -> Path:
    return Path.home() / STATE_ROOT_NAME


def read_bytes(path: Path, size: int = 4096) -> bytes:
    with path.open("rb") as handle:
        return handle.read(size)


def parse_kind(path: Path) -> str:
    suffix = path.suffix.lower()
    raw = read_bytes(path)

    if suffix == ".msi":
        return "msi"

    if len(raw) >= 64 and raw[:2] == b"MZ":
        pe_offset = int.from_bytes(raw[0x3C:0x40], "little", signed=False)
        try:
            with path.open("rb") as handle:
                handle.seek(pe_offset)
                signature = handle.read(4)
                if signature == b"PE\x00\x00":
                    handle.seek(pe_offset + 24)
                    optional_magic = int.from_bytes(handle.read(2), "little", signed=False)
                    if optional_magic == 0x20B:
                        return "pe64"
                    return "pe32"
                if signature[:2] == b"NE":
                    return "ne16"
                if signature[:2] in {b"LE", b"LX"}:
                    return "pe32"
        except OSError:
            pass
        return "dos_mz"

    if suffix == ".com":
        return "dos_com"
    if suffix in {".bat", ".cmd"}:
        lowered = raw.lower()
        if suffix == ".cmd" or any(token in lowered for token in CMD_HINTS):
            return "batch"
        return "dos_batch"
    if suffix == ".reg":
        return "reg"
    if suffix == ".pif":
        return "dos_com"
    if suffix == ".scr":
        return "pe32"

    return "pe32"


def classify(path: Path) -> dict[str, str]:
    kind = parse_kind(path)
    if kind == "pe64":
        return {"kind": "exe", "engine": "wine", "profile": "modern64"}
    if kind == "pe32":
        return {"kind": "exe", "engine": "wine", "profile": "modern64"}
    if kind in {"ne16", "batch", "reg"}:
        mapped_kind = "exe" if kind in {"pe32", "ne16"} else kind
        return {"kind": mapped_kind, "engine": "wine", "profile": "compat32"}
    if kind == "msi":
        return {"kind": kind, "engine": "wine", "profile": "modern64"}
    if kind in {"dos_mz", "dos_com", "dos_batch"}:
        return {"kind": kind, "engine": "dosbox", "profile": "dosbox"}
    fail(f"unsupported file type: {path}")


def quoted_dos(arg: str) -> str:
    escaped = arg.replace('"', '\\"')
    if any(ch.isspace() for ch in escaped) or not escaped:
        return f'"{escaped}"'
    return escaped


def prepare_dosbox_mount(path: Path) -> tuple[Path, str]:
    launch_root = state_root() / "dosbox" / "mount"
    launch_root.parent.mkdir(parents=True, exist_ok=True)
    if launch_root.is_symlink() or launch_root.exists():
        if launch_root.is_symlink() or launch_root.is_file():
            launch_root.unlink()
        else:
            shutil.rmtree(launch_root)
    launch_root.symlink_to(path.parent)
    return launch_root, path.name


def build_dosbox_command(path: Path, args: list[str], kind: str) -> list[str]:
    mount_root, filename = prepare_dosbox_mount(path)
    command_line = (
        f'call {quoted_dos(filename)} {" ".join(quoted_dos(arg) for arg in args).strip()}'.rstrip()
        if path.suffix.lower() in {".bat", ".cmd"}
        else f'{quoted_dos(filename)} {" ".join(quoted_dos(arg) for arg in args).strip()}'.rstrip()
    )
    command = [
        DOSBOX_BIN,
        "-fastlaunch",
        "-exit",
    ]
    for option in DOSBOX_SET_OPTIONS:
        command.extend(["-set", option])
    command.extend(
        [
            "-c",
            f'mount c "{mount_root}"',
            "-c",
            "c:",
            "-c",
            command_line,
        ]
    )
    return command


def build_wine_command(path: Path, args: list[str], classification: dict[str, str], wait: bool) -> list[str]:
    command: list[str] = []
    if classification["kind"] in {"exe", "msi"}:
        command.extend([ENV_BIN, "WORKSTATION_WINE_ENABLE_MONO=1"])
    command.extend(
        [
            WINE_RUNNER,
            "--profile",
            classification["profile"],
            "--kind",
            classification["kind"],
        ]
    )
    if wait:
        command.append("--wait")
    command.append(str(path))
    command.extend(args)
    return command


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Dispatch DOS and Windows binaries to the workstation runtime.")
    parser.add_argument("--desktop", action="store_true")
    parser.add_argument("--wait", action="store_true")
    parser.add_argument("--classify", action="store_true")
    parser.add_argument("target")
    parser.add_argument("args", nargs=argparse.REMAINDER)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    path = Path(args.target).expanduser().resolve()
    if not path.is_file():
        fail(f"target not found: {path}")
    launch_cwd = str(path.parent)

    classification = classify(path)
    if args.classify:
        print(
            f"engine={classification['engine']} kind={classification['kind']} profile={classification['profile']}",
            flush=True,
        )
        return 0

    if classification["engine"] == "dosbox":
        command = build_dosbox_command(path, args.args, classification["kind"])
        if os.environ.get("WORKSTATION_WINRUN_TEST_ONLY") == "1":
            print(json.dumps({"command": command, "cwd": launch_cwd}, ensure_ascii=False), flush=True)
            return 0
        if args.wait:
            return subprocess.run(command, cwd=launch_cwd).returncode
        subprocess.Popen(command, cwd=launch_cwd, start_new_session=True)
        return 0

    command = build_wine_command(path, args.args, classification, args.wait)
    if os.environ.get("WORKSTATION_WINRUN_TEST_ONLY") == "1":
        print(json.dumps({"command": command, "cwd": launch_cwd}, ensure_ascii=False), flush=True)
        return 0
    if args.wait:
        return subprocess.run(command, cwd=launch_cwd).returncode
    subprocess.Popen(command, cwd=launch_cwd, start_new_session=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
