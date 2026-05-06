from __future__ import annotations

import fcntl
import json
import os
import re
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator


EMAIL_RE = re.compile(
    r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@"
    r"(?:[A-Za-z0-9-]+\.)+[A-Za-z0-9-]{2,63}$"
)


class ExternalEmailError(Exception):
    pass


class InvalidExternalEmailError(ExternalEmailError):
    pass


class DuplicateExternalEmailError(ExternalEmailError):
    pass


@dataclass(frozen=True)
class ExternalEmailRecord:
    username: str
    email: str


def normalize_external_email(value: str | None, blocked_domain: str) -> str:
    candidate = (value or "").strip().lower()
    if not candidate or len(candidate) > 320 or not EMAIL_RE.fullmatch(candidate):
        raise InvalidExternalEmailError("올바른 이메일 주소를 입력하십시오.")
    local_part, domain_part = candidate.rsplit("@", 1)
    if not local_part or not domain_part:
        raise InvalidExternalEmailError("올바른 이메일 주소를 입력하십시오.")
    blocked = blocked_domain.strip().lower()
    if domain_part == blocked:
        raise InvalidExternalEmailError(f"{blocked} 주소는 등록할 수 없습니다.")
    return candidate


def mask_email(value: str | None) -> str:
    if not value or "@" not in value:
        return ""
    local_part, domain_part = value.split("@", 1)
    if len(local_part) <= 2:
        masked_local = f"{local_part[0]}*" if local_part else "*"
    else:
        masked_local = f"{local_part[0]}{'*' * max(1, len(local_part) - 2)}{local_part[-1]}"
    return f"{masked_local}@{domain_part}"


def registered_email(path: str | os.PathLike[str], username: str) -> str | None:
    with _locked_state(Path(path), write=False) as state:
        return state["users"].get(username)


def email_owner(path: str | os.PathLike[str], email: str) -> str | None:
    with _locked_state(Path(path), write=False) as state:
        return state["emails"].get(email)


def set_registered_email(path: str | os.PathLike[str], username: str, email: str) -> ExternalEmailRecord:
    state_path = Path(path)
    with _locked_state(state_path, write=True) as state:
        owner = state["emails"].get(email)
        if owner and owner != username:
            raise DuplicateExternalEmailError("이미 다른 계정에 등록된 이메일입니다.")

        previous = state["users"].get(username)
        if previous and previous != email:
            state["emails"].pop(previous, None)

        state["users"][username] = email
        state["emails"][email] = username
        _write_state(state_path, state)
        return ExternalEmailRecord(username=username, email=email)


@contextmanager
def _locked_state(path: Path, *, write: bool) -> Iterator[dict[str, dict[str, str]]]:
    lock_path = Path(f"{path}.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as lock_handle:
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
        state = _read_state(path)
        try:
            yield state
        finally:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)


def _read_state(path: Path) -> dict[str, dict[str, str]]:
    if not path.exists():
        return {"users": {}, "emails": {}}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"users": {}, "emails": {}}

    users_raw = raw.get("users", {}) if isinstance(raw, dict) else {}
    users: dict[str, str] = {}
    emails: dict[str, str] = {}
    if isinstance(users_raw, dict):
        for username, email in users_raw.items():
            user_text = str(username or "").strip().lower()
            email_text = str(email or "").strip().lower()
            if not user_text or not email_text:
                continue
            if email_text in emails and emails[email_text] != user_text:
                continue
            users[user_text] = email_text
            emails[email_text] = user_text
    return {"users": users, "emails": emails}


def _write_state(path: Path, state: dict[str, dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "users": dict(sorted(state["users"].items())),
        "emails": dict(sorted(state["emails"].items())),
    }
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=str(path.parent),
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        json.dump(payload, handle, ensure_ascii=True, indent=2, sort_keys=True)
        handle.write("\n")
        temp_name = handle.name
    os.replace(temp_name, path)
