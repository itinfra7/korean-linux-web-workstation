#!/usr/bin/env python3
import base64
import configparser
import ctypes
import json
import os
import re
import shutil
import subprocess
import sys
import time
import uuid
from ctypes import POINTER, Structure, byref, c_char_p, c_int, c_uint, c_void_p, cast, create_string_buffer, string_at
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote


PROFILE_PREFS = {
    "mail.tabs.drawInTitlebar": True,
    "toolkit.legacyUserProfileCustomizations.stylesheets": True,
    "browser.download.folderList": 2,
    "browser.download.useDownloadDir": True,
}
MAIL_BLOCK_BEGIN = "// workstation-thunderbird-mail-begin"
MAIL_BLOCK_END = "// workstation-thunderbird-mail-end"
MAIL_TOKEN_PATH = Path(".local/share/workstation/mail-bridge.json")
MAIL_HOST = os.environ.get(
    "WORKSTATION_MAIL_HOST",
    os.environ.get("WORKSTATION_PUBLIC_DOMAIN", "example.com"),
)
MAIL_IMAP_PORT = 993
MAIL_SMTP_PORT = 465
MAIL_SOCKET_SSL = 3
MAIL_AUTH_PASSWORD_CLEARTEXT = 3
NSS_LIBRARY_DIR = Path("/snap/thunderbird/current/usr/lib/thunderbird")
NSS_PRELOAD_LIBRARIES = (
    "libnspr4.so",
    "libplds4.so",
    "libplc4.so",
    "libnssutil3.so",
)
PREF_PATTERN = re.compile(r'^\s*user_pref\("(?P<key>[^"]+)",\s*(?P<value>.+)\);\s*$')

CHROME_BLOCK_BEGIN = "/* workstation-thunderbird-ui-begin */"
CHROME_BLOCK_END = "/* workstation-thunderbird-ui-end */"
USER_CHROME_CSS = r"""
:root {
    --workstation-win95-face: #c0c0c0;
    --workstation-win95-light: #ffffff;
    --workstation-win95-midlight: #dfdfdf;
    --workstation-win95-shadow: #808080;
    --workstation-win95-dark: #000000;
    --workstation-win95-title: #000080;
    --workstation-win95-title-text: #ffffff;
}

#messengerWindow #unifiedToolbarContainer {
    min-height: 24px !important;
    height: 24px !important;
    max-height: 24px !important;
    margin: 0 !important;
    padding: 0 !important;
    align-items: stretch !important;
    background: var(--workstation-win95-title) !important;
    border-bottom: 1px solid var(--workstation-win95-dark) !important;
    box-shadow: inset 0 1px 0 #3151c6 !important;
}

#messengerWindow #unifiedToolbar {
    min-height: 24px !important;
    height: 24px !important;
    padding: 0 2px 0 4px !important;
    align-items: stretch !important;
    gap: 1px !important;
    overflow: hidden !important;
    background: transparent !important;
}

#messengerWindow #unifiedToolbar::before {
    content: "Thunderbird";
    display: flex;
    align-items: center;
    margin-right: auto;
    padding: 0 8px 0 2px;
    color: var(--workstation-win95-title-text);
    font: 700 12px "UnDotum";
    text-shadow: none;
}

#messengerWindow #unifiedToolbarContent,
#messengerWindow #notification-popup-box {
    display: none !important;
}

#messengerWindow .titlebar-buttonbox-container {
    flex: 0 0 auto !important;
    align-self: center !important;
    margin: 0 2px 0 0 !important;
    padding: 0 !important;
    -moz-window-dragging: no-drag !important;
}

#messengerWindow .titlebar-buttonbox {
    align-items: center !important;
    gap: 1px !important;
    margin: 0 !important;
    padding: 0 !important;
}

#messengerWindow #button-appmenu,
#messengerWindow .titlebar-button {
    appearance: none !important;
    -moz-appearance: none !important;
    -moz-window-dragging: no-drag !important;
    min-width: 18px !important;
    width: 18px !important;
    min-height: 18px !important;
    height: 18px !important;
    margin: 3px 0 !important;
    padding: 0 !important;
    border-radius: 0 !important;
    color: var(--workstation-win95-dark) !important;
    background: var(--workstation-win95-face) !important;
    background-image: none !important;
    border-top: 1px solid var(--workstation-win95-light) !important;
    border-left: 1px solid var(--workstation-win95-light) !important;
    border-right: 1px solid var(--workstation-win95-shadow) !important;
    border-bottom: 1px solid var(--workstation-win95-shadow) !important;
    box-shadow: inset -1px -1px 0 var(--workstation-win95-dark), inset 1px 1px 0 var(--workstation-win95-midlight) !important;
}

#messengerWindow #button-appmenu {
    list-style-image: var(--icon-settings) !important;
    margin-inline: 0 1px !important;
}

#messengerWindow #button-appmenu .toolbarbutton-text,
#messengerWindow #button-appmenu .toolbarbutton-badge,
#messengerWindow #button-appmenu .toolbarbutton-menu-dropmarker {
    display: none !important;
}

#messengerWindow #button-appmenu > .toolbarbutton-badge-stack,
#messengerWindow .titlebar-button > .toolbarbutton-icon {
    width: 12px !important;
    height: 12px !important;
    min-width: 12px !important;
    min-height: 12px !important;
    margin: 0 !important;
    padding: 0 !important;
}

#messengerWindow #button-appmenu .toolbarbutton-icon,
#messengerWindow .titlebar-button .toolbarbutton-icon {
    fill: var(--workstation-win95-dark) !important;
    stroke: var(--workstation-win95-dark) !important;
}

#messengerWindow #button-appmenu:hover,
#messengerWindow .titlebar-button:hover {
    background: #d4d0c8 !important;
}

#messengerWindow #button-appmenu:is(:active, [open="true"]),
#messengerWindow .titlebar-button:active {
    border-top: 1px solid var(--workstation-win95-shadow) !important;
    border-left: 1px solid var(--workstation-win95-shadow) !important;
    border-right: 1px solid var(--workstation-win95-light) !important;
    border-bottom: 1px solid var(--workstation-win95-light) !important;
    box-shadow: inset 1px 1px 0 var(--workstation-win95-dark), inset -1px -1px 0 var(--workstation-win95-midlight) !important;
}

#messengerWindow .titlebar-spacer {
    display: none !important;
}
""".strip()


@dataclass
class ManagedMailConfig:
    username: str
    full_name: str
    email: str
    token: str


@dataclass
class ManagedMailSlots:
    account: str
    identity: str
    server: str
    smtp: str


class SECItem(Structure):
    _fields_ = [("type", c_uint), ("data", c_void_p), ("len", c_uint)]


class NSSProfileSession:
    _libraries_loaded = False

    def __init__(self, profile_dir: Path):
        self.profile_dir = profile_dir
        self._lib = None

    @classmethod
    def _ensure_loaded(cls) -> None:
        if cls._libraries_loaded:
            return
        for library_name in NSS_PRELOAD_LIBRARIES:
            ctypes.CDLL(str(NSS_LIBRARY_DIR / library_name), mode=ctypes.RTLD_GLOBAL)
        cls._libraries_loaded = True

    def __enter__(self):
        self._ensure_loaded()
        self._lib = ctypes.CDLL(str(NSS_LIBRARY_DIR / "libnss3.so"), mode=ctypes.RTLD_GLOBAL)
        self._lib.NSS_Init.argtypes = [c_char_p]
        self._lib.NSS_Init.restype = c_int
        self._lib.NSS_Shutdown.argtypes = []
        self._lib.NSS_Shutdown.restype = c_int
        self._lib.PK11SDR_Encrypt.argtypes = [POINTER(SECItem), POINTER(SECItem), POINTER(SECItem), c_void_p]
        self._lib.PK11SDR_Encrypt.restype = c_int
        self._lib.PK11SDR_Decrypt.argtypes = [POINTER(SECItem), POINTER(SECItem), c_void_p]
        self._lib.PK11SDR_Decrypt.restype = c_int
        self._lib.SECITEM_FreeItem.argtypes = [POINTER(SECItem), c_int]
        self._lib.SECITEM_FreeItem.restype = None
        if self._lib.NSS_Init(str(self.profile_dir).encode()) != 0:
            raise RuntimeError(f"NSS_Init failed for {self.profile_dir}")
        return self

    def __exit__(self, exc_type, exc, tb):
        if self._lib is not None:
            self._lib.NSS_Shutdown()
        return False

    def encrypt(self, plaintext: str) -> str:
        raw = plaintext.encode("utf-8")
        raw_buffer = create_string_buffer(raw)
        source = SECItem(0, cast(raw_buffer, c_void_p), len(raw))
        key_id = SECItem(0, None, 0)
        result = SECItem()
        if self._lib.PK11SDR_Encrypt(byref(key_id), byref(source), byref(result), None) != 0:
            raise RuntimeError("PK11SDR_Encrypt failed")
        try:
            return base64.b64encode(string_at(result.data, result.len)).decode("ascii")
        finally:
            self._lib.SECITEM_FreeItem(byref(result), 0)

    def decrypt(self, ciphertext: str) -> str:
        raw = base64.b64decode(ciphertext)
        raw_buffer = create_string_buffer(raw)
        source = SECItem(0, cast(raw_buffer, c_void_p), len(raw))
        result = SECItem()
        if self._lib.PK11SDR_Decrypt(byref(source), byref(result), None) != 0:
            raise RuntimeError("PK11SDR_Decrypt failed")
        try:
            return string_at(result.data, result.len).decode("utf-8")
        finally:
            self._lib.SECITEM_FreeItem(byref(result), 0)


def pref_literal(value):
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    escaped = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def pref_line(key, value):
    return f'user_pref("{key}", {pref_literal(value)});'


def merge_managed_block(existing_text: str, begin: str, end: str, body: str) -> str:
    pattern = re.compile(rf"{re.escape(begin)}.*?{re.escape(end)}\n?", re.DOTALL)
    replacement = f"{begin}\n{body.rstrip()}\n{end}\n"
    stripped = pattern.sub("", existing_text).strip()
    if stripped:
        return f"{stripped}\n\n{replacement}"
    return replacement


def profile_root(home: Path) -> Path:
    return home / "snap" / "thunderbird" / "common" / ".thunderbird"


def profile_paths(root: Path) -> list[Path]:
    profiles_ini = root / "profiles.ini"
    if not profiles_ini.is_file():
        return []

    config = configparser.RawConfigParser()
    config.read(profiles_ini, encoding="utf-8")

    resolved_paths: list[Path] = []
    seen: set[Path] = set()
    for section in config.sections():
        if not section.startswith("Profile"):
            continue
        raw_path = config.get(section, "Path", fallback="").strip()
        if not raw_path:
            continue
        is_relative = config.getboolean(section, "IsRelative", fallback=True)
        current = (root / raw_path) if is_relative else Path(raw_path)
        current = current.resolve()
        if current in seen:
            continue
        seen.add(current)
        resolved_paths.append(current)
    return resolved_paths


def profile_prefs_for_home(home: Path) -> dict[str, object]:
    downloads_dir = home / "다운로드"
    return {
        **PROFILE_PREFS,
        "browser.download.dir": str(downloads_dir),
        "browser.download.lastDir": str(downloads_dir),
    }


def write_user_js(home: Path, profile_dir: Path) -> None:
    profile_dir.mkdir(parents=True, exist_ok=True)
    downloads_dir = home / "다운로드"
    downloads_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(downloads_dir, 0o700)
    user_js = profile_dir / "user.js"
    existing_lines: list[str] = []
    if user_js.is_file():
        existing_lines = user_js.read_text(encoding="utf-8", errors="ignore").splitlines()

    effective_prefs = profile_prefs_for_home(home)
    prefixes = tuple(f'user_pref("{key}"' for key in effective_prefs)
    kept_lines = [line for line in existing_lines if not line.lstrip().startswith(prefixes)]
    if kept_lines and kept_lines[-1] != "":
        kept_lines.append("")
    kept_lines.extend(pref_line(key, value) for key, value in effective_prefs.items())

    user_js.write_text("\n".join(kept_lines).rstrip() + "\n", encoding="utf-8")
    os.chmod(user_js, 0o600)


def write_user_chrome(profile_dir: Path) -> None:
    chrome_dir = profile_dir / "chrome"
    chrome_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(chrome_dir, 0o700)

    user_chrome = chrome_dir / "userChrome.css"
    existing_text = ""
    if user_chrome.is_file():
        existing_text = user_chrome.read_text(encoding="utf-8", errors="ignore")

    updated_text = merge_managed_block(
        existing_text,
        CHROME_BLOCK_BEGIN,
        CHROME_BLOCK_END,
        USER_CHROME_CSS,
    )
    user_chrome.write_text(updated_text, encoding="utf-8")
    os.chmod(user_chrome, 0o600)


def parse_pref_value(raw: str):
    raw = raw.strip()
    if raw == "true":
        return True
    if raw == "false":
        return False
    if re.fullmatch(r"-?[0-9]+", raw):
        return int(raw)
    if raw.startswith('"') and raw.endswith('"'):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return raw[1:-1]
    return raw


def parse_pref_map(pref_text: str) -> dict[str, object]:
    values: dict[str, object] = {}
    for line in pref_text.splitlines():
        match = PREF_PATTERN.match(line)
        if not match:
            continue
        values[match.group("key")] = parse_pref_value(match.group("value"))
    return values


def csv_values(raw_value: object) -> list[str]:
    if not isinstance(raw_value, str):
        return []
    return [item for item in (part.strip() for part in raw_value.split(",")) if item]


def unique_preserving_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def allocate_slot(prefix: str, pref_map: dict[str, object]) -> str:
    highest = 0
    pattern = re.compile(rf"^{re.escape(prefix)}(\d+)$")
    for key, value in pref_map.items():
        for candidate in (key, value if isinstance(value, str) else None):
            if not isinstance(candidate, str):
                continue
            match = pattern.match(candidate)
            if match:
                highest = max(highest, int(match.group(1)))
    return f"{prefix}{highest + 1}"


def find_existing_mail_slots(pref_map: dict[str, object], config: ManagedMailConfig) -> ManagedMailSlots | None:
    stored_account = pref_map.get("workstation.mail.managedAccount")
    stored_identity = pref_map.get("workstation.mail.managedIdentity")
    stored_server = pref_map.get("workstation.mail.managedServer")
    stored_smtp = pref_map.get("workstation.mail.managedSmtpServer")
    if all(isinstance(value, str) and value for value in (stored_account, stored_identity, stored_server, stored_smtp)):
        return ManagedMailSlots(stored_account, stored_identity, stored_server, stored_smtp)

    for key, value in pref_map.items():
        if not key.startswith("mail.account.") or not key.endswith(".server") or not isinstance(value, str):
            continue
        account_id = key[len("mail.account.") : -len(".server")]
        server_id = value
        if pref_map.get(f"mail.server.{server_id}.hostname") != MAIL_HOST:
            continue
        if pref_map.get(f"mail.server.{server_id}.type") != "imap":
            continue
        identity_ids = csv_values(pref_map.get(f"mail.account.{account_id}.identities"))
        for identity_id in identity_ids:
            if pref_map.get(f"mail.identity.{identity_id}.useremail") != config.email:
                continue
            smtp_id = pref_map.get(f"mail.identity.{identity_id}.smtpServer")
            if isinstance(smtp_id, str) and smtp_id:
                return ManagedMailSlots(account_id, identity_id, server_id, smtp_id)
            for smtp_key, smtp_value in pref_map.items():
                if not smtp_key.startswith("mail.smtpserver.") or not smtp_key.endswith(".hostname"):
                    continue
                smtp_slot = smtp_key[len("mail.smtpserver.") : -len(".hostname")]
                if smtp_value == MAIL_HOST and pref_map.get(f"mail.smtpserver.{smtp_slot}.username") == config.email:
                    return ManagedMailSlots(account_id, identity_id, server_id, smtp_slot)
            return ManagedMailSlots(account_id, identity_id, server_id, allocate_slot("smtp", pref_map))
    return None


def ensure_mail_slots(pref_map: dict[str, object], config: ManagedMailConfig) -> ManagedMailSlots:
    existing = find_existing_mail_slots(pref_map, config)
    if existing is not None:
        return existing
    return ManagedMailSlots(
        allocate_slot("account", pref_map),
        allocate_slot("id", pref_map),
        allocate_slot("server", pref_map),
        allocate_slot("smtp", pref_map),
    )


def mailbox_uri(config: ManagedMailConfig, folder_name: str) -> str:
    return f"imap://{quote(config.email, safe='')}@{MAIL_HOST}/{quote(folder_name, safe='')}"


def build_managed_mail_prefs(pref_map: dict[str, object], config: ManagedMailConfig) -> dict[str, object]:
    slots = ensure_mail_slots(pref_map, config)
    account_list = unique_preserving_order(csv_values(pref_map.get("mail.accountmanager.accounts")) + [slots.account])
    smtp_list = unique_preserving_order(csv_values(pref_map.get("mail.smtpservers")) + [slots.smtp])
    directory_rel = f"[ProfD]ImapMail/{MAIL_HOST}-{config.username}"

    managed = {
        "workstation.mail.managedAccount": slots.account,
        "workstation.mail.managedIdentity": slots.identity,
        "workstation.mail.managedServer": slots.server,
        "workstation.mail.managedSmtpServer": slots.smtp,
        "workstation.mail.managedEmail": config.email,
        "mail.accountmanager.accounts": ",".join(account_list),
        f"mail.account.{slots.account}.identities": slots.identity,
        f"mail.account.{slots.account}.server": slots.server,
        f"mail.identity.{slots.identity}.fullName": config.full_name,
        f"mail.identity.{slots.identity}.useremail": config.email,
        f"mail.identity.{slots.identity}.valid": True,
        f"mail.identity.{slots.identity}.smtpServer": slots.smtp,
        f"mail.identity.{slots.identity}.draft_folder": mailbox_uri(config, "Drafts"),
        f"mail.identity.{slots.identity}.stationery_folder": mailbox_uri(config, "Templates"),
        f"mail.identity.{slots.identity}.fcc_folder": mailbox_uri(config, "Sent"),
        f"mail.identity.{slots.identity}.archive_folder": mailbox_uri(config, "Archives"),
        f"mail.identity.{slots.identity}.archive_enabled": True,
        f"mail.server.{slots.server}.type": "imap",
        f"mail.server.{slots.server}.hostname": MAIL_HOST,
        f"mail.server.{slots.server}.port": MAIL_IMAP_PORT,
        f"mail.server.{slots.server}.socketType": MAIL_SOCKET_SSL,
        f"mail.server.{slots.server}.authMethod": MAIL_AUTH_PASSWORD_CLEARTEXT,
        f"mail.server.{slots.server}.userName": config.email,
        f"mail.server.{slots.server}.name": config.email,
        f"mail.server.{slots.server}.prettyName": config.email,
        f"mail.server.{slots.server}.directory-rel": directory_rel,
        f"mail.server.{slots.server}.login_at_startup": True,
        f"mail.server.{slots.server}.check_new_mail": True,
        f"mail.server.{slots.server}.download_on_biff": True,
        f"mail.server.{slots.server}.trash_folder_name": "Trash",
        f"mail.server.{slots.server}.spamActionTargetFolder": mailbox_uri(config, "Junk"),
        "mail.smtpservers": ",".join(smtp_list),
        f"mail.smtpserver.{slots.smtp}.hostname": MAIL_HOST,
        f"mail.smtpserver.{slots.smtp}.port": MAIL_SMTP_PORT,
        f"mail.smtpserver.{slots.smtp}.try_ssl": MAIL_SOCKET_SSL,
        f"mail.smtpserver.{slots.smtp}.authMethod": MAIL_AUTH_PASSWORD_CLEARTEXT,
        f"mail.smtpserver.{slots.smtp}.username": config.email,
        f"mail.smtpserver.{slots.smtp}.description": MAIL_HOST,
    }

    default_account = pref_map.get("mail.accountmanager.defaultaccount")
    if not isinstance(default_account, str) or not default_account or default_account == slots.account:
        managed["mail.accountmanager.defaultaccount"] = slots.account

    default_smtp = pref_map.get("mail.smtp.defaultserver")
    if not isinstance(default_smtp, str) or not default_smtp or default_smtp == slots.smtp:
        managed["mail.smtp.defaultserver"] = slots.smtp

    return managed


def write_managed_mail_prefs(profile_dir: Path, config: ManagedMailConfig) -> None:
    prefs_js = profile_dir / "prefs.js"
    existing_text = prefs_js.read_text(encoding="utf-8", errors="ignore") if prefs_js.is_file() else ""
    pref_map = parse_pref_map(existing_text)
    managed_body = "\n".join(
        pref_line(key, value) for key, value in build_managed_mail_prefs(pref_map, config).items()
    )
    prefs_js.write_text(
        merge_managed_block(existing_text, MAIL_BLOCK_BEGIN, MAIL_BLOCK_END, managed_body).rstrip() + "\n",
        encoding="utf-8",
    )
    os.chmod(prefs_js, 0o600)


def empty_logins_payload() -> dict:
    return {
        "logins": [],
        "nextId": 1,
        "potentiallyVulnerablePasswords": [],
        "dismissedBreachAlertsByLoginGUID": {},
        "version": 3,
    }


def warn(message: str) -> None:
    print(f"workstation-thunderbird-profile: {message}", file=sys.stderr)


def load_logins_payload(profile_dir: Path) -> dict:
    logins_path = profile_dir / "logins.json"
    if not logins_path.is_file():
        return empty_logins_payload()
    try:
        payload = json.loads(logins_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return empty_logins_payload()
    if not isinstance(payload, dict):
        return empty_logins_payload()
    payload.setdefault("logins", [])
    payload.setdefault("nextId", 1)
    payload.setdefault("potentiallyVulnerablePasswords", [])
    payload.setdefault("dismissedBreachAlertsByLoginGUID", {})
    payload["version"] = 3
    return payload


def build_login_entry(existing_entry: dict | None, hostname: str, username: str, password: str, nss: NSSProfileSession, next_id: int) -> dict:
    now_ms = int(time.time() * 1000)
    password_changed = True
    if existing_entry is not None:
        try:
            password_changed = nss.decrypt(existing_entry.get("encryptedPassword", "")) != password
        except Exception:
            password_changed = True
    return {
        "id": int(existing_entry.get("id", next_id)) if existing_entry else next_id,
        "hostname": hostname,
        "httpRealm": hostname,
        "formSubmitURL": None,
        "usernameField": "",
        "passwordField": "",
        "encryptedUsername": nss.encrypt(username),
        "encryptedPassword": nss.encrypt(password),
        "guid": existing_entry.get("guid", f"{{{uuid.uuid4()}}}") if existing_entry else f"{{{uuid.uuid4()}}}",
        "encType": 1,
        "timeCreated": int(existing_entry.get("timeCreated", now_ms)) if existing_entry else now_ms,
        "timeLastUsed": int(existing_entry.get("timeLastUsed", now_ms)) if existing_entry else now_ms,
        "timePasswordChanged": int(existing_entry.get("timePasswordChanged", now_ms)) if existing_entry and not password_changed else now_ms,
        "timesUsed": int(existing_entry.get("timesUsed", 1)) if existing_entry else 1,
    }


def write_managed_logins(profile_dir: Path, config: ManagedMailConfig) -> None:
    payload = load_logins_payload(profile_dir)
    raw_logins = payload.get("logins")
    if not isinstance(raw_logins, list):
        raw_logins = []

    imap_hostname = f"imap://{MAIL_HOST}"
    smtp_hostname = f"smtp://{MAIL_HOST}"
    kept_logins: list[dict] = []
    existing_imap = None
    existing_smtp = None

    with NSSProfileSession(profile_dir) as nss:
        for entry in raw_logins:
            if not isinstance(entry, dict):
                continue
            hostname = entry.get("hostname")
            if hostname not in {imap_hostname, smtp_hostname}:
                kept_logins.append(entry)
                continue
            try:
                decrypted_username = nss.decrypt(entry.get("encryptedUsername", ""))
            except Exception:
                kept_logins.append(entry)
                continue
            if decrypted_username != config.email:
                kept_logins.append(entry)
                continue
            if hostname == imap_hostname:
                existing_imap = entry
            else:
                existing_smtp = entry

        used_ids = [int(entry.get("id", 0)) for entry in kept_logins if isinstance(entry.get("id", 0), int)]
        next_id = max(used_ids, default=0) + 1
        imap_entry = build_login_entry(existing_imap, imap_hostname, config.email, config.token, nss, next_id)
        next_id = max(next_id, int(imap_entry["id"]) + 1)
        smtp_entry = build_login_entry(existing_smtp, smtp_hostname, config.email, config.token, nss, next_id)
        payload["logins"] = kept_logins + [imap_entry, smtp_entry]
        payload["nextId"] = max(used_ids + [int(imap_entry["id"]), int(smtp_entry["id"])], default=0) + 1

    logins_path = profile_dir / "logins.json"
    logins_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.chmod(logins_path, 0o600)


def clear_profile_lock_files(profile_dir: Path) -> None:
    for name in (".parentlock", "parent.lock", "lock"):
        try:
            (profile_dir / name).unlink()
        except FileNotFoundError:
            pass


def has_complete_crypto_material(profile_dir: Path) -> bool:
    required = ("key4.db", "cert9.db", "pkcs11.txt")
    for name in required:
        path = profile_dir / name
        if not path.is_file():
            return False
        try:
            if path.stat().st_size <= 0:
                return False
        except FileNotFoundError:
            return False
    return True


def purge_incomplete_crypto_material(profile_dir: Path) -> None:
    clear_profile_lock_files(profile_dir)
    for name in ("key4.db", "cert9.db", "pkcs11.txt"):
        path = profile_dir / name
        try:
            if path.exists() and path.stat().st_size <= 0:
                path.unlink()
        except FileNotFoundError:
            pass


def rotate_broken_crypto_material(profile_dir: Path) -> None:
    stamp = time.strftime("%Y%m%d%H%M%S")
    backup_dir = profile_dir / f"workstation-broken-nss-{stamp}"
    moved = False
    clear_profile_lock_files(profile_dir)
    for name in ("key4.db", "cert9.db", "pkcs11.txt"):
        path = profile_dir / name
        if not path.exists():
            continue
        backup_dir.mkdir(mode=0o700, exist_ok=True)
        shutil.move(str(path), str(backup_dir / name))
        moved = True
    if not moved:
        try:
            backup_dir.rmdir()
        except OSError:
            pass


def ensure_profile_crypto_material(
    home: Path,
    profile_dir: Path,
    force_repair: bool = False,
    aggressive_repair: bool = False,
) -> None:
    if aggressive_repair:
        rotate_broken_crypto_material(profile_dir)
    elif force_repair:
        purge_incomplete_crypto_material(profile_dir)
    if has_complete_crypto_material(profile_dir):
        clear_profile_lock_files(profile_dir)
        return

    env = os.environ.copy()
    env["HOME"] = str(home)
    env.setdefault("LANG", "ko_KR.UTF-8")
    env.setdefault("LANGUAGE", "ko_KR:ko:en_US:en")
    env.setdefault("LC_ALL", "ko_KR.UTF-8")
    env.pop("DISPLAY", None)
    env.pop("XAUTHORITY", None)
    env.pop("WAYLAND_DISPLAY", None)
    clear_profile_lock_files(profile_dir)

    process = subprocess.Popen(
        ["/snap/bin/thunderbird", "--headless", "--profile", str(profile_dir)],
        env=env,
        cwd=home,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if has_complete_crypto_material(profile_dir):
                clear_profile_lock_files(profile_dir)
                return
            if process.poll() is not None:
                break
            time.sleep(0.25)
        if has_complete_crypto_material(profile_dir):
            clear_profile_lock_files(profile_dir)
            return
        raise RuntimeError(f"Thunderbird profile crypto scaffolding did not create complete NSS material in {profile_dir}")
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        clear_profile_lock_files(profile_dir)


def load_managed_mail_config(home: Path) -> ManagedMailConfig | None:
    config_path = home / MAIL_TOKEN_PATH
    if not config_path.is_file():
        return None
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    username = str(payload.get("username", "")).strip()
    full_name = str(payload.get("full_name", "")).strip() or username
    email = str(payload.get("email", "")).strip().lower()
    token = str(payload.get("token", "")).strip()
    if not username or not email or not token:
        return None
    return ManagedMailConfig(username=username, full_name=full_name, email=email, token=token)


def sync_profile_mail(home: Path, profile_dir: Path) -> bool:
    config = load_managed_mail_config(home)
    if config is None:
        return True
    write_managed_mail_prefs(profile_dir, config)
    try:
        ensure_profile_crypto_material(home, profile_dir)
        write_managed_logins(profile_dir, config)
        return True
    except RuntimeError as exc:
        if "NSS_Init failed" not in str(exc) and "PK11SDR_Encrypt failed" not in str(exc):
            warn(f"managed login sync skipped for {profile_dir}: {exc}")
            return False
        try:
            ensure_profile_crypto_material(home, profile_dir, aggressive_repair=True)
            write_managed_logins(profile_dir, config)
            return True
        except Exception as repair_exc:  # noqa: BLE001
            warn(f"managed login sync skipped for {profile_dir} after repair attempt: {repair_exc}")
            return False
    except Exception as exc:  # noqa: BLE001
        warn(f"managed login sync skipped for {profile_dir}: {exc}")
        return False


def sync_existing(home: Path) -> int:
    root = profile_root(home)
    updated = 0
    for current in profile_paths(root):
        try:
            write_user_js(home, current)
            write_user_chrome(current)
            sync_profile_mail(home, current)
            updated += 1
        except Exception as exc:  # noqa: BLE001
            warn(f"profile sync skipped for {current}: {exc}")
    return updated


def seed_profile(home: Path) -> bool:
    root = profile_root(home)
    profiles_ini = root / "profiles.ini"
    if profiles_ini.is_file():
        return False

    root.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["HOME"] = str(home)
    env.setdefault("LANG", "ko_KR.UTF-8")
    env.setdefault("LANGUAGE", "ko_KR:ko:en_US:en")
    env.setdefault("LC_ALL", "ko_KR.UTF-8")
    env.pop("DISPLAY", None)
    env.pop("XAUTHORITY", None)
    env.pop("WAYLAND_DISPLAY", None)

    process = subprocess.Popen(
        ["/snap/bin/thunderbird", "--headless"],
        env=env,
        cwd=home,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if profiles_ini.is_file():
                return True
            if process.poll() is not None:
                break
            time.sleep(0.25)
        if profiles_ini.is_file():
            return True
        raise RuntimeError("Thunderbird profile seeding did not create profiles.ini")
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


def main() -> int:
    action = sys.argv[1] if len(sys.argv) > 1 else ""
    home = Path(os.environ.get("HOME", str(Path.home()))).expanduser().resolve()

    if action == "sync-existing":
        sync_existing(home)
        return 0

    if action == "seed-and-sync":
        seed_profile(home)
        sync_existing(home)
        return 0

    print("usage: workstation-thunderbird-profile.py <sync-existing|seed-and-sync>", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
