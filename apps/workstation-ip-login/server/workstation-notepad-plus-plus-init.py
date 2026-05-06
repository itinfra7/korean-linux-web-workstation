#!/usr/bin/env python3

import os
import shutil
import subprocess
import sys
from pathlib import Path


MARKER_NAME = ".workstation-notepad-plus-plus-ready-v1"
DEFAULT_CONFIG_ROOT = Path("/usr/local/share/workstation-desktop/notepad-plus-plus/default")
RELEASE_ROOT = Path("/opt/notepad-plus-plus/current")
HEADLESS_SCREEN = "1024x768x24"
DEFAULT_FILE_SEEDS = {
    "config.xml": DEFAULT_CONFIG_ROOT / "config.xml",
    "langs.xml": RELEASE_ROOT / "langs.model.xml",
    "stylers.xml": RELEASE_ROOT / "stylers.model.xml",
    "nativeLang.xml": RELEASE_ROOT / "localization" / "korean.xml",
}

FONT_REPLACEMENTS = {
    "MS Shell Dlg": "Noto Sans CJK KR",
    "MS Shell Dlg 2": "Noto Sans CJK KR",
    "Malgun Gothic": "Noto Sans CJK KR",
    "Malgun Gothic Semilight": "Noto Sans CJK KR",
    "Gulim": "Noto Sans CJK KR",
    "Dotum": "Noto Sans CJK KR",
    "Batang": "Noto Serif CJK KR",
    "Gungsuh": "Noto Serif CJK KR",
    "GulimChe": "Noto Sans Mono CJK KR",
    "DotumChe": "Noto Sans Mono CJK KR",
}


def fail(message: str, code: int = 1) -> None:
    print(f"workstation-notepad-plus-plus-init: {message}", file=sys.stderr)
    raise SystemExit(code)


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def config_root(prefix: Path) -> Path:
    username = os.environ.get("USER") or os.environ.get("LOGNAME") or Path.home().name
    return prefix / "drive_c" / "users" / username / "AppData" / "Roaming" / "Notepad++"


def copy_if_missing(source: Path, target: Path) -> None:
    if source.is_file() and not target.exists():
        shutil.copy2(source, target)


def headless_command(command: list[str], env: dict[str, str]) -> list[str]:
    if env.get("DISPLAY"):
        return command
    xvfb_run = shutil.which("xvfb-run")
    if xvfb_run:
        return [xvfb_run, "-a", "-s", f"-screen 0 {HEADLESS_SCREEN}", *command]
    return command


def write_font_replacements(env: dict[str, str]) -> None:
    for source_name, target_name in FONT_REPLACEMENTS.items():
        subprocess.run(
            headless_command([
                "wine",
                "reg",
                "add",
                r"HKCU\Software\Wine\Fonts\Replacements",
                "/v",
                source_name,
                "/d",
                target_name,
                "/f",
            ], env),
            env=env,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )


def main() -> int:
    if len(sys.argv) != 2:
        fail("usage: workstation-notepad-plus-plus-init.py <wine-prefix>")

    prefix = Path(sys.argv[1]).expanduser().resolve()
    if not prefix.is_dir():
        fail(f"wine prefix not found: {prefix}")

    notepadpp_config = config_root(prefix)
    ensure_dir(notepadpp_config)
    for target_name, source_path in DEFAULT_FILE_SEEDS.items():
        copy_if_missing(source_path, notepadpp_config / target_name)

    marker = prefix / MARKER_NAME
    if marker.is_file():
        return 0

    env = os.environ.copy()
    env["WINEPREFIX"] = str(prefix)
    env.setdefault("LANG", "ko_KR.UTF-8")
    env.setdefault("LANGUAGE", "ko_KR:ko:en_US:en")
    env.setdefault("LC_ALL", "ko_KR.UTF-8")
    env.setdefault("LC_CTYPE", "ko_KR.UTF-8")

    write_font_replacements(env)
    marker.touch()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
