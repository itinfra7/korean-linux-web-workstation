#!/usr/bin/env python3

import argparse
import os
import shutil
import stat
import subprocess
import tempfile
from pathlib import Path


TEMPLATE_ROOT = Path("/usr/local/share/workstation-desktop/wine-prefix-templates")
BUILD_ROOT = Path("/var/lib/workstation-desktop/wine-template-build")
STATE_ROOT_NAME = ".local/share/workstation-windows"
PROFILE_HOOKS = {
    "modern64": "/usr/local/lib/workstation-desktop/workstation-notepad-plus-plus-init.py",
    "kakaotalk32": "/usr/local/lib/workstation-desktop/workstation-kakaotalk-init.py",
}
PROFILES = ("modern64", "compat32", "kakaotalk32")
TEMPLATE_USERNAME_FILE = ".workstation-wine-template-username"


def fail(message: str) -> None:
    raise SystemExit(f"workstation-wine-template-build: {message}")


def run(command: list[str], **kwargs) -> None:
    subprocess.run(command, check=True, **kwargs)


def chmod_tree(path: Path) -> None:
    for target in sorted(path.rglob("*")):
        if target.is_symlink():
            continue
        current = stat.S_IMODE(target.stat().st_mode)
        if target.is_dir():
            target.chmod(0o755)
        elif current & 0o111:
            target.chmod(0o755)
        else:
            target.chmod(0o644)
    path.chmod(0o755)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build root-managed Wine prefix templates for workstation users.")
    parser.add_argument("--bootstrap-user", required=True)
    parser.add_argument("--profile", action="append", choices=PROFILES)
    return parser.parse_args()


def build_profile(profile: str, bootstrap_user: str) -> None:
    build_home = BUILD_ROOT / f"{profile}-{bootstrap_user}"
    run(["rm", "-rf", str(build_home)])
    build_home.mkdir(parents=True, exist_ok=True)

    uid = int(
        subprocess.check_output(["id", "-u", bootstrap_user], text=True).strip()
    )
    gid = int(
        subprocess.check_output(["id", "-g", bootstrap_user], text=True).strip()
    )
    os.chown(build_home, uid, gid)
    build_home.chmod(0o700)

    env_command = [
        "env",
        f"HOME={build_home}",
        f"USER={bootstrap_user}",
        f"LOGNAME={bootstrap_user}",
        "LANG=ko_KR.UTF-8",
        "LANGUAGE=ko_KR:ko:en_US:en",
        "LC_ALL=ko_KR.UTF-8",
        "LC_CTYPE=ko_KR.UTF-8",
    ]
    hook = PROFILE_HOOKS.get(profile)
    if hook:
        env_command.append(f"WORKSTATION_WINE_READY_HOOK={hook}")
    env_command.extend(
        [
            "/usr/bin/python3",
            "/usr/local/bin/workstation-wine-run",
            "--prepare-profile",
            "--profile",
            profile,
        ]
    )

    run(["runuser", "-u", bootstrap_user, "--", *env_command], cwd="/")

    source_prefix = build_home / STATE_ROOT_NAME / "prefixes" / profile
    if not source_prefix.is_dir():
        fail(f"prepared prefix missing after build: {source_prefix}")

    template_tmp = TEMPLATE_ROOT / f"{profile}.tmp"
    template_final = TEMPLATE_ROOT / profile
    run(["rm", "-rf", str(template_tmp), str(template_final)])
    shutil.copytree(source_prefix, template_tmp, symlinks=True)
    (template_tmp / TEMPLATE_USERNAME_FILE).write_text(f"{bootstrap_user}\n", encoding="utf-8")
    chmod_tree(template_tmp)
    template_tmp.rename(template_final)
    run(["rm", "-rf", str(build_home)])


def main() -> int:
    args = parse_args()
    profiles = args.profile or list(PROFILES)

    TEMPLATE_ROOT.mkdir(parents=True, exist_ok=True)
    BUILD_ROOT.mkdir(parents=True, exist_ok=True)
    TEMPLATE_ROOT.chmod(0o755)
    BUILD_ROOT.chmod(0o755)

    for profile in profiles:
        build_profile(profile, args.bootstrap_user)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
