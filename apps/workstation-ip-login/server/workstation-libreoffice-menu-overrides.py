#!/usr/bin/env python3

from __future__ import annotations

import argparse
import configparser
import re
from pathlib import Path


VERSIONED_ID_RE = re.compile(r"^libreoffice\d[\d.]*-.+\.desktop$")
OBSOLETE_IDS = (
    "startcenter.desktop",
    "writer.desktop",
    "calc.desktop",
    "draw.desktop",
    "impress.desktop",
    "base.desktop",
    "math.desktop",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Maintain managed LibreOffice desktop overrides.")
    parser.add_argument("--system-app-dir", default="/usr/share/applications")
    parser.add_argument("--local-app-dir", default="/usr/local/share/applications")
    parser.add_argument("--template-base", required=True)
    parser.add_argument("--template-math", required=True)
    return parser.parse_args()


def load_desktop(path: Path) -> configparser.ConfigParser:
    parser = configparser.ConfigParser(interpolation=None, strict=False)
    parser.optionxform = str
    parser.read(path, encoding="utf-8")
    return parser


def write_hidden_override(source_path: Path, target_path: Path) -> None:
    source = load_desktop(source_path)
    source_entry = source["Desktop Entry"] if source.has_section("Desktop Entry") else {}
    name = source_entry.get("Name", source_path.stem)
    name_ko = source_entry.get("Name[ko]", name)
    contents = (
        "[Desktop Entry]\n"
        "Version=1.0\n"
        "Type=Application\n"
        f"Name={name}\n"
        f"Name[ko]={name_ko}\n"
        "Hidden=true\n"
        "NoDisplay=true\n"
        "X-Workstation-Managed-LibreOffice-Versioned-Hide=true\n"
    )
    target_path.write_text(contents, encoding="utf-8")


def copy_template(template_path: Path, target_path: Path) -> None:
    target_path.write_text(template_path.read_text(encoding="utf-8"), encoding="utf-8")


def main() -> int:
    args = parse_args()
    system_app_dir = Path(args.system_app_dir)
    local_app_dir = Path(args.local_app_dir)
    template_base = Path(args.template_base)
    template_math = Path(args.template_math)

    local_app_dir.mkdir(parents=True, exist_ok=True)

    expected_hidden_ids: set[str] = set()
    for source_path in sorted(system_app_dir.glob("libreoffice*.desktop")):
        desktop_id = source_path.name
        if not VERSIONED_ID_RE.match(desktop_id):
            continue
        expected_hidden_ids.add(desktop_id)
        write_hidden_override(source_path, local_app_dir / desktop_id)

    for path in sorted(local_app_dir.glob("libreoffice*.desktop")):
        if VERSIONED_ID_RE.match(path.name) and path.name not in expected_hidden_ids:
            path.unlink(missing_ok=True)

    for obsolete_id in OBSOLETE_IDS:
        (local_app_dir / obsolete_id).unlink(missing_ok=True)

    copy_template(template_base, local_app_dir / "libreoffice-base.desktop")
    copy_template(template_math, local_app_dir / "libreoffice-math.desktop")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
