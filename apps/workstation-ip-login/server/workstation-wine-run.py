#!/usr/bin/env python3

import argparse
import fcntl
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path


STATE_ROOT_NAME = ".local/share/workstation-windows"
CACHE_ROOT_NAME = ".cache/workstation-windows"
TEMPLATE_ROOT = Path("/usr/local/share/workstation-desktop/wine-prefix-templates")
DEFAULT_DEBUG = "-all"
DEFAULT_OVERRIDES = "winemenubuilder.exe=d"
MONO_DISABLED_OVERRIDES = "winemenubuilder.exe=d;mscoree=d;mshtml=d"
MONO_ROOT = Path("/opt/wine/mono")
MONO_MARKER_NAME = ".workstation-wine-mono-ready"
TEMPLATE_USERNAME_FILE = ".workstation-wine-template-username"
HEADLESS_SCREEN = "1024x768x24"
READY_HOOK_ENV = "WORKSTATION_WINE_READY_HOOK"
TEST_ONLY_ENV = "WORKSTATION_WINE_TEST_ONLY"
MONO_ENABLE_ENV = "WORKSTATION_WINE_ENABLE_MONO"
PROFILE_ARCH = {
    "modern64": "win64",
    "compat32": "win32",
    "kakaotalk32": "win32",
}
KIND_PROFILE = {
    "exe": "modern64",
    "msi": "modern64",
    "batch": "compat32",
    "reg": "compat32",
}
IME_DEFAULTS = {
    "GTK_IM_MODULE": "ibus",
    "QT_IM_MODULE": "ibus",
    "XMODIFIERS": "@im=ibus",
    "SDL_IM_MODULE": "ibus",
    "GLFW_IM_MODULE": "ibus",
    "CLUTTER_IM_MODULE": "ibus",
}


def fail(message: str, code: int = 1) -> None:
    print(f"workstation-wine-run: {message}", file=sys.stderr)
    raise SystemExit(code)


def ensure_dir(path: Path, mode: int = 0o700) -> None:
    path.mkdir(parents=True, exist_ok=True)
    os.chmod(path, mode)


def state_root() -> Path:
    return Path.home() / STATE_ROOT_NAME


def cache_root() -> Path:
    return Path.home() / CACHE_ROOT_NAME


def prefix_root(profile: str) -> Path:
    return state_root() / "prefixes" / profile


def template_root(profile: str) -> Path:
    return TEMPLATE_ROOT / profile


def prefix_ready(prefix: Path) -> bool:
    return (
        (prefix / "system.reg").is_file()
        and (prefix / "user.reg").is_file()
        and (prefix / "drive_c/windows").is_dir()
    )


def pending_prefix(profile: str) -> Path:
    prefix = prefix_root(profile)
    return prefix.with_name(prefix.name + ".tmp")


def mono_marker(prefix: Path) -> Path:
    return prefix / MONO_MARKER_NAME


def template_username_path(prefix: Path) -> Path:
    return prefix / TEMPLATE_USERNAME_FILE


def normalize_prefix(profile: str) -> Path:
    prefix = prefix_root(profile)
    tmp_prefix = pending_prefix(profile)
    if not prefix.exists() and prefix_ready(tmp_prefix):
        tmp_prefix.rename(prefix)
    return prefix


def base_env() -> dict[str, str]:
    env = os.environ.copy()
    env.setdefault("LANG", "ko_KR.UTF-8")
    env.setdefault("LANGUAGE", "ko_KR:ko:en_US:en")
    env.setdefault("LC_ALL", "ko_KR.UTF-8")
    env.setdefault("LC_CTYPE", "ko_KR.UTF-8")
    env.setdefault("TZ", "Asia/Seoul")
    env.setdefault("WINEDEBUG", DEFAULT_DEBUG)
    if mono_enabled():
        env.setdefault("WINEDLLOVERRIDES", DEFAULT_OVERRIDES)
    else:
        env.setdefault("WINEDLLOVERRIDES", MONO_DISABLED_OVERRIDES)
    for key, value in IME_DEFAULTS.items():
        env.setdefault(key, value)
    return env


def runtime_username() -> str:
    return os.environ.get("USER") or os.environ.get("LOGNAME") or Path.home().name


def prefix_env(prefix: Path, arch: str | None = None, *, headless: bool = False) -> dict[str, str]:
    env = base_env()
    env["WINEPREFIX"] = str(prefix)
    if arch:
        env["WINEARCH"] = arch
    if headless:
        for key in ("DISPLAY", "WAYLAND_DISPLAY", "XAUTHORITY"):
            env.pop(key, None)
    return env


def headless_command(command: list[str]) -> list[str]:
    xvfb_run = shutil.which("xvfb-run")
    if xvfb_run:
        return [xvfb_run, "-a", "-s", f"-screen 0 {HEADLESS_SCREEN}", *command]
    return command


def mono_installer() -> Path | None:
    installers = sorted(MONO_ROOT.glob("wine-mono-*-x86.msi"))
    return installers[-1] if installers else None


def mono_enabled() -> bool:
    value = os.environ.get(MONO_ENABLE_ENV, "").strip().lower()
    return value in {"1", "true", "yes", "on"}


def cleanup_install_prompts() -> None:
    uid = str(os.getuid())
    for signal_name in ("-TERM", "-KILL"):
        subprocess.run(
            ["pkill", signal_name, "-u", uid, "-f", r"control\.exe appwiz\.cpl install_mono"],
            check=False,
        )
        subprocess.run(
            ["pkill", signal_name, "-u", uid, "-f", r"control\.exe appwiz\.cpl install_gecko"],
            check=False,
        )
        time.sleep(1)


def stop_wine(env: dict[str, str]) -> None:
    cleanup_install_prompts()
    try:
        subprocess.run(["wineserver", "-k"], env=env, check=False, timeout=15)
    except subprocess.TimeoutExpired:
        pass
    try:
        subprocess.run(["wineserver", "-w"], env=env, check=False, timeout=15)
    except subprocess.TimeoutExpired:
        pass
    uid = str(os.getuid())
    for signal_name in ("-TERM", "-KILL"):
        subprocess.run(["pkill", signal_name, "-u", uid, "-f", "wineboot.exe --init"], check=False)
        subprocess.run(["pkill", signal_name, "-u", uid, "-f", "wineserver"], check=False)
        time.sleep(1)
    try:
        subprocess.run(["wineserver", "-w"], env=env, check=False, timeout=10)
    except subprocess.TimeoutExpired:
        pass
    cleanup_install_prompts()


def ensure_wine_mono(prefix: Path, profile: str) -> None:
    if not mono_enabled():
        return

    marker = mono_marker(prefix)
    if marker.is_file():
        return

    installer = mono_installer()
    if installer is None or not installer.is_file():
        return

    env = prefix_env(prefix, PROFILE_ARCH[profile], headless=True)
    cleanup_install_prompts()
    try:
        installer_output = subprocess.check_output(
            headless_command(["winepath", "-w", str(installer.resolve())]),
            env=env,
            text=True,
            timeout=60,
            stderr=subprocess.STDOUT,
            cwd="/",
        )
        installer_windows_path = next(
            (line.strip() for line in reversed(installer_output.splitlines()) if line.strip()),
            "",
        )
        if not installer_windows_path:
            fail(f"wine mono installer path conversion failed for: {installer}")
        subprocess.run(
            headless_command(["wine", "msiexec", "/i", installer_windows_path, "/qn"]),
            env=env,
            check=True,
            timeout=300,
            cwd="/",
        )
        stop_wine(env)
        marker.touch()
    except subprocess.TimeoutExpired:
        stop_wine(env)
        fail(f"wine mono installation timed out for prefix: {prefix}")
    except subprocess.CalledProcessError:
        stop_wine(env)
        raise
    finally:
        cleanup_install_prompts()


def template_username(prefix: Path) -> str | None:
    metadata = template_username_path(prefix)
    if metadata.is_file():
        value = metadata.read_text(encoding="utf-8", errors="ignore").strip()
        if value:
            return value

    users_root = prefix / "drive_c" / "users"
    if not users_root.is_dir():
        return None

    candidates = sorted(
        entry.name
        for entry in users_root.iterdir()
        if entry.is_dir() and entry.name not in {"Public", "Default", "Default User", "All Users"}
    )
    return candidates[0] if candidates else None


def rewrite_user_links(prefix: Path, source_username: str, target_username: str) -> None:
    if source_username == target_username:
        return

    users_root = prefix / "drive_c" / "users"
    source_dir = users_root / source_username
    target_dir = users_root / target_username
    if source_dir.exists():
        if target_dir.exists():
            shutil.rmtree(target_dir)
        source_dir.rename(target_dir)

    source_home = f"/home/{source_username}"
    target_home = f"/home/{target_username}"

    for path in prefix.rglob("*"):
        if path.is_symlink():
            target = os.readlink(path)
            if source_home in target:
                path.unlink()
                path.symlink_to(target.replace(source_home, target_home))
        elif path.is_file() and path.suffix.lower() in {".reg", ".ini", ".xml", ".txt"}:
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            updated = (
                text.replace(source_home, target_home)
                .replace(f"\\\\users\\\\{source_username}", f"\\\\users\\\\{target_username}")
                .replace(f"\\\\Users\\\\{source_username}", f"\\\\Users\\\\{target_username}")
                .replace(f'"USERNAME"="{source_username}"', f'"USERNAME"="{target_username}"')
            )
            if updated != text:
                path.write_text(updated, encoding="utf-8")


def clone_template_prefix(profile: str, target_prefix: Path) -> bool:
    template = template_root(profile)
    if not prefix_ready(template):
        return False

    shutil.copytree(template, target_prefix, symlinks=True)
    source_username = template_username(template)
    target_username = runtime_username()
    if source_username:
        rewrite_user_links(target_prefix, source_username, target_username)
    template_username_path(target_prefix).unlink(missing_ok=True)
    return prefix_ready(target_prefix)


def ensure_prefix(profile: str) -> Path:
    if profile not in PROFILE_ARCH:
        fail(f"unsupported profile: {profile}")

    prefix = normalize_prefix(profile)
    if prefix_ready(prefix):
        ensure_wine_mono(prefix, profile)
        return prefix

    locks_dir = cache_root() / "locks"
    ensure_dir(locks_dir, 0o700)
    lock_path = locks_dir / f"{profile}.lock"
    with open(lock_path, "a+", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        if prefix_ready(prefix):
            return prefix

        tmp_prefix = pending_prefix(profile)
        shutil.rmtree(tmp_prefix, ignore_errors=True)
        if prefix.exists():
            shutil.rmtree(prefix)

        ensure_dir(prefix.parent, 0o700)
        if clone_template_prefix(profile, tmp_prefix):
            prefix = normalize_prefix(profile)
            ensure_wine_mono(prefix, profile)
            return prefix

        env = prefix_env(tmp_prefix, PROFILE_ARCH[profile], headless=True)

        try:
            cleanup_install_prompts()
            subprocess.run(headless_command(["wineboot", "-u"]), env=env, check=True, timeout=180, cwd="/")
            stop_wine(env)
        except subprocess.TimeoutExpired:
            stop_wine(env)
            if not prefix_ready(tmp_prefix):
                fail(f"wine prefix initialization timed out before becoming ready: {tmp_prefix}")
        except subprocess.CalledProcessError:
            stop_wine(env)
            raise

        prefix = normalize_prefix(profile)
        if not prefix_ready(prefix):
            fail(f"wine prefix initialization did not produce a usable prefix: {tmp_prefix}")
        ensure_wine_mono(prefix, profile)
        return prefix


def wine_env(profile: str) -> dict[str, str]:
    return prefix_env(ensure_prefix(profile))


def run_ready_hook(env: dict[str, str]) -> None:
    hook = env.get(READY_HOOK_ENV)
    if not hook:
        return
    subprocess.run([hook, env["WINEPREFIX"]], env=env, check=True)


def convert_arg(arg: str, env: dict[str, str]) -> str:
    path = Path(arg)
    try:
        if path.exists():
            return subprocess.check_output(
                ["winepath", "-w", str(path.resolve())],
                env=env,
                text=True,
            ).strip()
    except (OSError, subprocess.CalledProcessError):
        return arg
    return arg


def build_command(kind: str, target: Path, trailing_args: list[str], profile: str) -> tuple[list[str], dict[str, str], Path]:
    env = wine_env(profile)
    run_ready_hook(env)
    if not target.exists():
        fail(f"target not found after ready hook: {target}")
    converted_args = [convert_arg(arg, env) for arg in trailing_args]
    launch_cwd = target.parent

    if kind == "msi":
        command = ["wine", "msiexec", "/i", convert_arg(str(target), env), *converted_args]
    elif kind == "batch":
        command = ["wine", "cmd", "/c", convert_arg(str(target), env), *converted_args]
    elif kind == "reg":
        command = ["wine", "regedit", convert_arg(str(target), env), *converted_args]
    else:
        command = ["wine", str(target), *converted_args]

    return command, env, launch_cwd


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a Windows program inside the workstation Wine runtime.")
    parser.add_argument("--kind", choices=sorted(KIND_PROFILE), default="exe")
    parser.add_argument("--profile", choices=sorted(PROFILE_ARCH))
    parser.add_argument("--prepare-profile", action="store_true")
    parser.add_argument("--wait", action="store_true")
    parser.add_argument("target", nargs="?")
    parser.add_argument("args", nargs=argparse.REMAINDER)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    profile = args.profile or KIND_PROFILE[args.kind]

    if args.prepare_profile:
        env = wine_env(profile)
        run_ready_hook(env)
        if os.environ.get(TEST_ONLY_ENV) == "1":
            payload = {
                "prepared": True,
                "profile": profile,
                "prefix": env["WINEPREFIX"],
                "hook": env.get(READY_HOOK_ENV, ""),
            }
            print(json.dumps(payload, ensure_ascii=False), flush=True)
        return 0

    if not args.target:
        fail("missing target")

    target = Path(args.target).expanduser().resolve()
    command, env, launch_cwd = build_command(args.kind, target, args.args, profile)

    if os.environ.get(TEST_ONLY_ENV) == "1":
        payload = {
            "command": command,
            "cwd": str(launch_cwd),
            "env": {
                key: env.get(key, "")
                for key in (
                    "LANG",
                    "LANGUAGE",
                    "LC_ALL",
                    "LC_CTYPE",
                    "GTK_IM_MODULE",
                    "QT_IM_MODULE",
                    "XMODIFIERS",
                    "SDL_IM_MODULE",
                    "GLFW_IM_MODULE",
                    "CLUTTER_IM_MODULE",
                    "IBUS_ADDRESS",
                    "DISPLAY",
                    "WINEPREFIX",
                    READY_HOOK_ENV,
                )
            },
        }
        print(json.dumps(payload, ensure_ascii=False), flush=True)
        return 0

    if args.wait:
        return subprocess.run(command, env=env, cwd=str(launch_cwd)).returncode

    subprocess.Popen(command, env=env, cwd=str(launch_cwd), start_new_session=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
