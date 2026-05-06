#!/usr/bin/env python3

import fcntl
import os
import shutil
import subprocess
import sys
from pathlib import Path


MARKER_NAME = ".workstation-kakaotalk-ready-v1"
LOCK_NAME = ".workstation-kakaotalk-install.lock"
INSTALLER_PATH = Path("/opt/kakaotalk/current/KakaoTalk_Setup.exe")
APP_RELATIVE_PATH = Path("drive_c/Program Files/Kakao/KakaoTalk/KakaoTalk.exe")
HEADLESS_SCREEN = "1024x768x24"
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
    print(f"workstation-kakaotalk-init: {message}", file=sys.stderr)
    raise SystemExit(code)


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


def headless_command(command: list[str], env: dict[str, str]) -> list[str]:
    if env.get("DISPLAY"):
        return command
    xvfb_run = shutil.which("xvfb-run")
    if xvfb_run:
        return [xvfb_run, "-a", "-s", f"-screen 0 {HEADLESS_SCREEN}", *command]
    return command


def main() -> int:
    if len(sys.argv) != 2:
        fail("usage: workstation-kakaotalk-init.py <wine-prefix>")

    prefix = Path(sys.argv[1]).expanduser().resolve()
    if not prefix.is_dir():
        fail(f"wine prefix not found: {prefix}")

    if not INSTALLER_PATH.is_file():
        fail(f"kakaotalk installer not found: {INSTALLER_PATH}")

    marker = prefix / MARKER_NAME
    lock_path = prefix / LOCK_NAME
    app_path = prefix / APP_RELATIVE_PATH

    env = os.environ.copy()
    env["WINEPREFIX"] = str(prefix)
    env.setdefault("LANG", "ko_KR.UTF-8")
    env.setdefault("LANGUAGE", "ko_KR:ko:en_US:en")
    env.setdefault("LC_ALL", "ko_KR.UTF-8")
    env.setdefault("LC_CTYPE", "ko_KR.UTF-8")

    with open(lock_path, "a+", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        if marker.is_file() and app_path.is_file():
            return 0

        write_font_replacements(env)

        if not app_path.is_file():
            subprocess.run(
                headless_command(["wine", str(INSTALLER_PATH), "/S"], env),
                env=env,
                check=True,
                timeout=900,
                cwd="/",
            )

        write_font_replacements(env)

        if not app_path.is_file():
            fail(f"kakaotalk executable not found after install: {app_path}")

        marker.touch()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
