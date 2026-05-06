#!/usr/bin/env python3

from __future__ import annotations

import argparse
from pathlib import Path


LANGUAGE_HEADER = "[language]"
LANGUAGE_VALUE = "ko.txt"
TARGET_FILES = ("conf.txt", "conf-lastgood.txt")


def ensure_language_block(text: str) -> str:
    lines = text.splitlines()
    updated = False
    for index, line in enumerate(lines):
        if line.strip() != LANGUAGE_HEADER:
            continue
        next_index = index + 1
        if next_index < len(lines):
            if lines[next_index] != LANGUAGE_VALUE:
                lines[next_index] = LANGUAGE_VALUE
            updated = True
        else:
            lines.append(LANGUAGE_VALUE)
            updated = True
        break

    if not updated:
        if lines and lines[-1] != "":
            lines.append("")
        lines.extend([LANGUAGE_HEADER, LANGUAGE_VALUE])

    result = "\n".join(lines)
    if text.endswith("\n") or not result.endswith("\n"):
        result += "\n"
    return result


def sync_file(seed_path: Path, target_path: Path) -> None:
    if target_path.is_file():
        text = target_path.read_text(encoding="utf-8-sig", errors="ignore")
    else:
        text = seed_path.read_text(encoding="utf-8-sig")
        home_dir = target_path.parent.parent.parent
        text = text.replace("/home/__WORKSTATION_TEMPLATE_USER__", str(home_dir))
    target_path.write_text(ensure_language_block(text), encoding="utf-8-sig")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Ensure the managed PeaZip profile defaults stay Korean.")
    parser.add_argument("--seed", required=True)
    parser.add_argument("--target-dir", required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    seed_path = Path(args.seed).expanduser().resolve()
    target_dir = Path(args.target_dir).expanduser().resolve()
    target_dir.mkdir(parents=True, exist_ok=True)

    for name in TARGET_FILES:
        sync_file(seed_path, target_dir / name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
