#!/usr/bin/env python3
import argparse
import json
import os
import pwd
import grp
import secrets
import subprocess
import sys
from pathlib import Path


HOST_FQDN = os.environ.get("WORKSTATION_PUBLIC_DOMAIN", "example.com")
MAIL_DOMAIN = os.environ.get("WORKSTATION_MAIL_DOMAIN", HOST_FQDN)
BASE_DN = os.environ.get("WORKSTATION_LDAP_BASE_DN", "dc=example,dc=com")
PEOPLE_OU_DN = f"ou=people,{BASE_DN}"
STATE_DIR = Path("/var/lib/workstation-mail/bridge")
STATE_FILE = STATE_DIR / "state.json"
USER_TOKEN_RELATIVE = Path(".local/share/workstation/mail-bridge.json")
PASSWD_FILE = Path("/etc/dovecot/workstation-bridge-passwd")
ALLOW_NETS = "127.0.0.0/8"


def die(message: str) -> "NoReturn":
    print(message, file=sys.stderr)
    raise SystemExit(1)


def run(args: list[str], *, input_text: str | None = None) -> str:
    completed = subprocess.run(
        args,
        input=input_text,
        text=True,
        capture_output=True,
        check=True,
    )
    return completed.stdout


def atomic_write(path: Path, content: str, mode: int, uid: int, gid: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.parent / f".{path.name}.tmp-{os.getpid()}"
    tmp_path.write_text(content, encoding="utf-8")
    os.chmod(tmp_path, mode)
    os.chown(tmp_path, uid, gid)
    tmp_path.replace(path)


def first_value(entry: dict[str, list[str]], key: str) -> str:
    values = entry.get(key) or []
    return values[0] if values else ""


def load_state() -> dict[str, dict]:
    if not STATE_FILE.is_file():
        return {}
    try:
        payload = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        die(f"invalid state file {STATE_FILE}: {exc}")
    if not isinstance(payload, dict):
        die(f"invalid state file {STATE_FILE}: expected object")
    return {str(key): value for key, value in payload.items() if isinstance(value, dict)}


def save_state(state: dict[str, dict]) -> None:
    atomic_write(
        STATE_FILE,
        json.dumps(state, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        0o600,
        0,
        0,
    )


def ldap_people() -> dict[str, dict]:
    output = run(
        [
            "ldapsearch",
            "-Q",
            "-Y",
            "EXTERNAL",
            "-H",
            "ldapi:///",
            "-LLL",
            "-o",
            "ldif-wrap=no",
            "-b",
            PEOPLE_OU_DN,
            f"(mail=*@{MAIL_DOMAIN})",
            "uid",
            "cn",
            "mail",
            "modifyTimestamp",
            "pwdChangedTime",
        ]
    )

    users: dict[str, dict] = {}
    entry: dict[str, list[str]] = {}
    for line in output.splitlines():
        if not line:
            username = first_value(entry, "uid")
            email = first_value(entry, "mail").lower()
            if username and email.endswith(f"@{MAIL_DOMAIN}"):
                users[username] = {
                    "username": username,
                    "full_name": first_value(entry, "cn") or username,
                    "email": email,
                    "pwd_changed_time": first_value(entry, "pwdChangedTime"),
                    "modify_timestamp": first_value(entry, "modifyTimestamp"),
                }
            entry = {}
            continue
        if line.startswith(" ") or ":" not in line:
            continue
        key, value = line.split(":", 1)
        entry.setdefault(key, []).append(value.lstrip())
    if entry:
        username = first_value(entry, "uid")
        email = first_value(entry, "mail").lower()
        if username and email.endswith(f"@{MAIL_DOMAIN}"):
            users[username] = {
                "username": username,
                "full_name": first_value(entry, "cn") or username,
                "email": email,
                "pwd_changed_time": first_value(entry, "pwdChangedTime"),
                "modify_timestamp": first_value(entry, "modifyTimestamp"),
            }
    return users


def marker_for(user: dict) -> str:
    return "|".join(
        [
            user.get("pwd_changed_time", ""),
            user.get("modify_timestamp", ""),
            user.get("email", ""),
            user.get("full_name", ""),
        ]
    )


def password_hash(secret: str) -> str:
    hashed = run(["openssl", "passwd", "-6", "-stdin"], input_text=secret + "\n").strip()
    if not hashed.startswith("$6$"):
        die("unexpected openssl passwd output")
    return "{SHA512-CRYPT}" + hashed


def user_home(username: str) -> Path | None:
    try:
        return Path(pwd.getpwnam(username).pw_dir)
    except KeyError:
        candidate = Path("/home") / username
        return candidate if candidate.is_dir() else None


def write_user_token(user: dict, token: str) -> None:
    home = user_home(user["username"])
    if home is None or not home.is_dir():
        return
    target = home / USER_TOKEN_RELATIVE
    target.parent.mkdir(parents=True, exist_ok=True)
    pwent = pwd.getpwnam(user["username"])
    os.chown(target.parent, pwent.pw_uid, pwent.pw_gid)
    os.chmod(target.parent, 0o700)
    payload = {
        "version": 1,
        "username": user["username"],
        "full_name": user["full_name"],
        "email": user["email"],
        "token": token,
        "host": HOST_FQDN,
        "imap_port": 993,
        "smtp_port": 465,
    }
    atomic_write(
        target,
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        0o600,
        pwent.pw_uid,
        pwent.pw_gid,
    )


def remove_user_token(username: str) -> None:
    home = user_home(username)
    if home is None:
        return
    target = home / USER_TOKEN_RELATIVE
    try:
        target.unlink()
    except FileNotFoundError:
        pass


def render_passwd_lines(state: dict[str, dict], users: dict[str, dict]) -> list[str]:
    lines: list[str] = []
    for username in sorted(users):
        entry = state.get(username)
        if not entry:
            continue
        lines.append(f"{users[username]['email']}:{password_hash(entry['token'])}::::::allow_nets={ALLOW_NETS}")
    return lines


def sync_users(selected_username: str | None) -> None:
    ldap_users = ldap_people()
    state = load_state()

    target_usernames = [selected_username] if selected_username else sorted(ldap_users)
    for username in target_usernames:
        user = ldap_users.get(username)
        if user is None:
            state.pop(username, None)
            remove_user_token(username)
            continue
        marker = marker_for(user)
        token = str(state.get(username, {}).get("token", "")).strip()
        if not token or state.get(username, {}).get("marker") != marker or state.get(username, {}).get("email") != user["email"]:
            token = secrets.token_hex(32)
        state[username] = {
            "email": user["email"],
            "full_name": user["full_name"],
            "marker": marker,
            "token": token,
        }
        write_user_token(user, token)

    if selected_username is None:
        stale_usernames = [username for username in state if username not in ldap_users]
        for username in stale_usernames:
            state.pop(username, None)
            remove_user_token(username)

    save_state(state)
    dovecot_gid = grp.getgrnam("dovecot").gr_gid
    passwd_lines = render_passwd_lines(state, ldap_users)
    atomic_write(
        PASSWD_FILE,
        "\n".join(passwd_lines).rstrip() + ("\n" if passwd_lines else ""),
        0o640,
        0,
        dovecot_gid,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--all", action="store_true")
    group.add_argument("--user")
    return parser.parse_args()


def main() -> int:
    if os.geteuid() != 0:
        die("workstation-mail-bridge-sync must run as root")
    args = parse_args()
    sync_users(args.user if args.user else None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
