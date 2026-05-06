#!/usr/bin/env python3

import json
import os
import pwd
import shutil
import tempfile
from pathlib import Path
from typing import Any


PREFERENCE_PATCH = {
    "browser": {
        "check_default_browser": False,
    },
    "brave": {
        "widevine_opted_in": True,
        "ask_widevine_install": False,
    },
    "privacy_sandbox": {
        "first_party_sets_enabled": False,
        "m1": {
            "ad_measurement_enabled": False,
            "fledge_enabled": False,
            "topics_enabled": False,
        },
    },
}

LOCAL_STATE_PATCH = {
    "browser": {
        "first_run_finished": True,
        "check_default_browser": False,
    },
    "brave": {
        "enable_search_suggestions_by_default": False,
        "p3a": {
            "enabled": False,
            "notice_acknowledged": True,
        },
        "stats": {
            "first_check_made": True,
        },
    },
}


def ensure_dir(path: Path, mode: int, uid: int, gid: int) -> None:
    path.mkdir(parents=True, exist_ok=True)
    os.chown(path, uid, gid)
    os.chmod(path, mode)


def load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        backup_path = path.with_suffix(path.suffix + ".corrupt")
        shutil.move(path, backup_path)
        return {}
    if isinstance(data, dict):
        return data
    return {}


def merge_dict(target: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    for key, value in patch.items():
        if isinstance(value, dict):
            existing = target.get(key)
            if not isinstance(existing, dict):
                existing = {}
            target[key] = merge_dict(existing, value)
        else:
            target[key] = value
    return target


def atomic_write_json(path: Path, payload: dict[str, Any], uid: int, gid: int) -> None:
    parent = path.parent
    fd, temp_name = tempfile.mkstemp(prefix=path.name + ".", dir=parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
        os.chown(temp_name, uid, gid)
        os.chmod(temp_name, 0o600)
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def ensure_empty_file(path: Path, uid: int, gid: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch(exist_ok=True)
    os.chown(path, uid, gid)
    os.chmod(path, 0o600)


def main() -> int:
    if len(os.sys.argv) != 3:
        raise SystemExit("usage: workstation-brave-profile.py <username> <home-path>")

    username = os.sys.argv[1]
    home_path = Path(os.sys.argv[2]).expanduser().resolve()
    user_info = pwd.getpwnam(username)
    uid = user_info.pw_uid
    gid = user_info.pw_gid

    config_root = home_path / ".config" / "BraveSoftware" / "Brave-Browser"
    profile_root = config_root / "Default"
    widevine_root = config_root / "WidevineCdm"
    local_state_path = config_root / "Local State"
    preferences_path = profile_root / "Preferences"
    first_run_sentinel = config_root / "First Run"

    ensure_dir(home_path / ".config", 0o700, uid, gid)
    ensure_dir(config_root, 0o700, uid, gid)
    ensure_dir(profile_root, 0o700, uid, gid)
    ensure_dir(widevine_root, 0o700, uid, gid)

    local_state = load_json(local_state_path)
    merged_local_state = merge_dict(local_state, LOCAL_STATE_PATCH)
    atomic_write_json(local_state_path, merged_local_state, uid, gid)

    preferences = load_json(preferences_path)
    merged_preferences = merge_dict(preferences, PREFERENCE_PATCH)
    atomic_write_json(preferences_path, merged_preferences, uid, gid)
    ensure_empty_file(first_run_sentinel, uid, gid)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
