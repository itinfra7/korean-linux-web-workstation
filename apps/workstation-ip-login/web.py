from __future__ import annotations

import asyncio
import base64
import contextlib
import dataclasses
import errno
import fcntl
import hashlib
import json
import logging
import os
import pty
import pwd
import re
import secrets
import shutil
import signal
import stat
import struct
import subprocess
import tempfile
import termios
import time
import unicodedata
from email.message import EmailMessage
from http.cookies import SimpleCookie
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote, urlparse

import httpx
import websockets
from fastapi import FastAPI, Form, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.background import BackgroundTask

from chat_store import (
    append_chat_media_message,
    append_chat_message,
    chat_media_record,
    chat_unread_summary,
    fetch_chat_messages,
    init_chat_store,
    list_chat_peer_summaries,
    mark_chat_peer_read,
)
from common import (
    account_mail_address,
    allow_key,
    create_redis,
    ldap_change_password,
    ldap_authenticate,
    load_settings,
    normalize_ip,
    normalize_login_id,
    session_key,
)
from external_email import (
    DuplicateExternalEmailError,
    email_owner,
    mask_email,
    normalize_external_email,
    registered_email,
    set_registered_email,
)


BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
settings = load_settings()
templates.env.globals["product_title"] = settings.product_title
templates.env.globals["public_base_url"] = settings.public_base_url
templates.env.globals["mail_domain"] = settings.mail_domain
WORKSPACE_CSS_ASSET = BASE_DIR / "static" / "kasmvnc" / "workspace.css"
WORKSPACE_JS_ASSET = BASE_DIR / "static" / "kasmvnc" / "workspace.js"
TERMINAL_FRAME_CSS_ASSET = BASE_DIR / "static" / "kasmvnc" / "terminal-frame.css"
TERMINAL_FRAME_JS_ASSET = BASE_DIR / "static" / "kasmvnc" / "terminal-frame.js"
WORKSPACE_CSS_URL = f"/static/kasmvnc/workspace.css?v={int(WORKSPACE_CSS_ASSET.stat().st_mtime)}"
WORKSPACE_JS_URL = f"/static/kasmvnc/workspace.js?v={int(WORKSPACE_JS_ASSET.stat().st_mtime)}"
TERMINAL_FRAME_CSS_URL = f"/static/kasmvnc/terminal-frame.css?v={int(TERMINAL_FRAME_CSS_ASSET.stat().st_mtime)}"
TERMINAL_FRAME_JS_URL = f"/static/kasmvnc/terminal-frame.js?v={int(TERMINAL_FRAME_JS_ASSET.stat().st_mtime)}"

app = FastAPI()
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
logger = logging.getLogger("workstation_iplogin.web")


def public_root_url() -> str:
    return settings.public_base_url.rstrip("/") + "/"

HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
}

DESKTOP_READY_TIMEOUT_SECONDS = 1.5
DESKTOP_READY_RETRIES = 3
DESKTOP_READY_RETRY_DELAY_SECONDS = 0.35
DESKTOP_RECENT_START_GRACE_SECONDS = 20
DESKTOP_RECENT_START_WAIT_SECONDS = 12
TERMINAL_DEFAULT_COLS = 100
TERMINAL_DEFAULT_ROWS = 30
TERMINAL_PTY_READ_SIZE = 8192
EXTERNAL_EMAIL_CODE_DIGITS = 6
EMAIL_LOGIN_BROWSER_COOKIE_NAME = "workstation_iplogin_email_browser"
EMAIL_LOGIN_BROWSER_COOKIE_RE = re.compile(r"^[A-Za-z0-9_-]{20,128}$")
EMAIL_LOGIN_TTL_SECONDS = 600
EMAIL_LOGIN_REQUEST_LIMIT = 5
EMAIL_LOGIN_REQUEST_WINDOW_SECONDS = 600
EMAIL_LOGIN_RESEND_COOLDOWN_SECONDS = 30
EMAIL_LOGIN_VERIFY_ATTEMPT_LIMIT = 5
WORKSPACE_USERS_ROOT = Path(os.environ.get("WORKSTATION_DESKTOP_USERS_ROOT", "/var/lib/workstation-desktop/users"))
CHAT_STORE_FILE = Path(os.environ.get("WORKSTATION_IPLOGIN_CHAT_STORE_FILE", "/var/lib/workstation-state/workstation-ip-login/chat.sqlite3"))
CHAT_MEDIA_ROOT = Path(os.environ.get("WORKSTATION_IPLOGIN_CHAT_MEDIA_ROOT", "/var/lib/workstation-state/workstation-ip-login/chat-media"))
CHAT_PAGE_SIZE = 30
CHAT_MESSAGE_MAX_CHARS = 4000
CHAT_PERSON_UID_MIN = 50000
CHAT_IMAGE_MAX_BYTES = 25 * 1024 * 1024
CHAT_SCREENSHOT_PREVIEW_TEXT = "[스크린샷]"
CHAT_MEDIA_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{16,128}$")
TEST_ACCOUNT_TERMS = ("test", "smoke", "dummy", "sample", "qa")
DESKTOP_LOGOUT_SIGNAL_NAME = "workstation-logout-requested"
NOTIFICATION_STREAM_KEEPALIVE_SECONDS = 15
NOTIFICATION_STREAM_QUEUE_SIZE = 64
NOTIFICATION_BRIDGE_RESTART_DELAY_SECONDS = 1.5


@dataclasses.dataclass
class WorkspaceNotificationBridge:
    username: str
    subscribers: set[asyncio.Queue[dict[str, Any]]] = dataclasses.field(default_factory=set)
    task: asyncio.Task[None] | None = None


@app.on_event("startup")
async def startup() -> None:
    app.state.redis = create_redis(settings)
    app.state.desktop_tasks = {}
    app.state.clipboard_cache = {}
    app.state.clipboard_last = {}
    app.state.notification_bridges = {}
    app.state.notification_bridge_lock = asyncio.Lock()
    await asyncio.to_thread(init_chat_store, CHAT_STORE_FILE)
    await asyncio.to_thread(CHAT_MEDIA_ROOT.mkdir, parents=True, exist_ok=True)


@app.on_event("shutdown")
async def shutdown() -> None:
    for bridge in list(getattr(app.state, "notification_bridges", {}).values()):
        task = getattr(bridge, "task", None)
        if task:
          task.cancel()
    for bridge in list(getattr(app.state, "notification_bridges", {}).values()):
        task = getattr(bridge, "task", None)
        if task:
            with contextlib.suppress(asyncio.CancelledError):
                await task
    await app.state.redis.aclose()


def normalized_client_ip(header_ip: str | None, socket_ip: str | None) -> str:
    real_ip = normalize_ip(header_ip)
    if real_ip:
        return real_ip
    peer_ip = normalize_ip(socket_ip)
    return peer_ip or "unknown"


def client_ip(request: Request) -> str:
    return normalized_client_ip(
        request.headers.get("x-real-ip"),
        request.client.host if request.client else None,
    )


def websocket_client_ip(websocket: WebSocket) -> str:
    return normalized_client_ip(
        websocket.headers.get("x-real-ip"),
        websocket.client.host if websocket.client else None,
    )


def desktop_logout_signal_target(username: str | None) -> tuple[Path, int] | None:
    normalized_username = str(username or "").strip().lower()
    if not normalized_username:
        return None
    try:
        pwent = pwd.getpwnam(normalized_username)
    except KeyError:
        return None
    return Path(f"/tmp/{DESKTOP_LOGOUT_SIGNAL_NAME}-{pwent.pw_uid}"), pwent.pw_uid


def desktop_logout_requested(username: str | None) -> bool:
    target = desktop_logout_signal_target(username)
    if not target:
        return False
    logout_signal, expected_uid = target
    try:
        signal_stat = logout_signal.stat(follow_symlinks=False)
    except FileNotFoundError:
        return False
    except PermissionError:
        return False
    return stat.S_ISREG(signal_stat.st_mode) and signal_stat.st_uid == expected_uid


async def invalidate_sessions_for_username(username: str | None) -> int:
    normalized_username = str(username or "").strip().lower()
    if not normalized_username:
        return 0

    keys_to_delete: list[str] = []
    async for key in app.state.redis.scan_iter(match="workstation:iplogin:session:*", count=100):
        stored_username = str(await app.state.redis.hget(key, "username") or "").strip().lower()
        if stored_username == normalized_username:
            keys_to_delete.append(key)

    if not keys_to_delete:
        return 0

    await app.state.redis.delete(*keys_to_delete)
    return len(keys_to_delete)


async def session_from_values(session_id: str | None, request_ip: str) -> dict | None:
    if not session_id:
        return None
    session_data = await app.state.redis.hgetall(session_key(session_id))
    if not session_data:
        return None
    if session_data.get("ip") != request_ip:
        return None
    if desktop_logout_requested(session_data.get("username")):
        await invalidate_sessions_for_username(session_data.get("username"))
        return None
    await app.state.redis.expire(session_key(session_id), settings.session_ttl_seconds)
    session_data["session_id"] = session_id
    return session_data


async def current_session(request: Request) -> dict | None:
    return await session_from_values(
        request.cookies.get(settings.session_cookie_name),
        client_ip(request),
    )


async def current_websocket_session(websocket: WebSocket) -> dict | None:
    session_id = websocket.cookies.get(settings.session_cookie_name)
    if not session_id:
        raw_cookie = websocket.headers.get("cookie", "")
        if raw_cookie:
            jar = SimpleCookie()
            try:
                jar.load(raw_cookie)
            except Exception:
                jar = SimpleCookie()
            morsel = jar.get(settings.session_cookie_name)
            if morsel is not None:
                session_id = morsel.value
    return await session_from_values(session_id, websocket_client_ip(websocket))


def email_login_pending_key(browser_token: str) -> str:
    return f"workstation:iplogin:email-login:pending:{browser_token}"


def email_login_rate_key(browser_token: str) -> str:
    return f"workstation:iplogin:email-login:rate:{browser_token}"


def resolve_email_login_browser_token(request: Request) -> tuple[str, bool]:
    cookie_value = str(request.cookies.get(EMAIL_LOGIN_BROWSER_COOKIE_NAME) or "").strip()
    if EMAIL_LOGIN_BROWSER_COOKIE_RE.fullmatch(cookie_value):
        return cookie_value, False
    return secrets.token_urlsafe(24), True


def set_email_login_browser_cookie(response: Response, browser_token: str) -> None:
    response.set_cookie(
        EMAIL_LOGIN_BROWSER_COOKIE_NAME,
        browser_token,
        max_age=31536000,
        httponly=True,
        secure=True,
        samesite="lax",
        path="/",
    )


def set_login_session_cookie(response: Response, session_id: str) -> None:
    response.set_cookie(
        settings.session_cookie_name,
        session_id,
        max_age=settings.session_ttl_seconds,
        httponly=True,
        secure=True,
        samesite="lax",
        path="/",
    )


async def clear_pending_email_login(browser_token: str) -> None:
    await app.state.redis.delete(email_login_pending_key(browser_token))


async def email_login_request_count(browser_token: str) -> tuple[int, int]:
    key = email_login_rate_key(browser_token)
    count = await app.state.redis.incr(key)
    if count == 1:
        await app.state.redis.expire(key, EMAIL_LOGIN_REQUEST_WINDOW_SECONDS)
    ttl = await app.state.redis.ttl(key)
    return count, max(ttl, 0)


def send_login_email_verification_message(
    *,
    sender_email: str,
    target_email: str,
    code: str,
    ttl_seconds: int,
) -> None:
    message = EmailMessage()
    message["From"] = sender_email
    message["To"] = target_email
    message["Reply-To"] = sender_email
    message["Subject"] = f"[{settings.mail_domain}] 로그인 인증 번호"
    message.set_content(
        "\n".join(
            [
                f"{settings.product_title} 로그인 인증 안내입니다.",
                "",
                f"LDAP 계정 이메일: {sender_email}",
                f"인증 번호: {code}",
                f"유효 시간: {max(1, ttl_seconds // 60)}분",
                "",
                "이 요청을 본인이 하지 않았다면 이 메일을 무시하십시오.",
            ]
        )
    )
    subprocess.run(
        [settings.sendmail_path, "-t", "-oi", "-f", sender_email],
        input=message.as_bytes(),
        capture_output=True,
        check=True,
    )


def normalize_email_login_code(value: str | None) -> str:
    return re.sub(r"\D+", "", str(value or ""))[:EXTERNAL_EMAIL_CODE_DIGITS]


async def websocket_session_diagnostics(websocket: WebSocket) -> dict[str, str]:
    client = websocket_client_ip(websocket)
    cookie_header = websocket.headers.get("cookie", "")
    session_id = websocket.cookies.get(settings.session_cookie_name)

    if not session_id and cookie_header:
        jar = SimpleCookie()
        try:
            jar.load(cookie_header)
        except Exception:
            jar = SimpleCookie()
        morsel = jar.get(settings.session_cookie_name)
        if morsel is not None:
            session_id = morsel.value

    if not session_id:
        return {
            "reason": "missing_session_cookie",
            "client_ip": client,
            "cookie_header_present": str(bool(cookie_header)),
        }

    stored = await app.state.redis.hgetall(session_key(session_id))
    if not stored:
        return {
            "reason": "missing_session_record",
            "client_ip": client,
            "cookie_header_present": str(bool(cookie_header)),
        }

    if stored.get("ip") != client:
        return {
            "reason": "ip_mismatch",
            "client_ip": client,
            "stored_ip": stored.get("ip", ""),
            "username": stored.get("username", ""),
        }

    return {
        "reason": "unknown_rejection",
        "client_ip": client,
        "username": stored.get("username", ""),
    }


def render_page(
    request: Request,
    *,
    error: str | None = None,
    login_id: str = "",
    session_data: dict | None = None,
) -> HTMLResponse:
    response = templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "request": request,
            "error": error,
            "login_id": login_id,
            "client_ip": client_ip(request),
            "session_data": session_data,
            "email_login_ttl_seconds": EMAIL_LOGIN_TTL_SECONDS,
            "email_login_ttl_minutes": max(1, EMAIL_LOGIN_TTL_SECONDS // 60),
            "email_login_request_limit": EMAIL_LOGIN_REQUEST_LIMIT,
            "email_login_request_window_seconds": EMAIL_LOGIN_REQUEST_WINDOW_SECONDS,
            "email_login_request_window_minutes": max(1, EMAIL_LOGIN_REQUEST_WINDOW_SECONDS // 60),
            "email_login_resend_cooldown_seconds": EMAIL_LOGIN_RESEND_COOLDOWN_SECONDS,
        },
    )
    browser_token, issued = resolve_email_login_browser_token(request)
    if issued:
        set_email_login_browser_cookie(response, browser_token)
    if request.cookies.get(settings.session_cookie_name) and not session_data:
        response.delete_cookie(settings.session_cookie_name, path="/")
    return response


def render_prepare_page(request: Request, session_data: dict) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="prepare.html",
        context={
            "request": request,
            "client_ip": client_ip(request),
            "session_data": session_data,
        },
    )


def render_terminal_frame_page(request: Request, session_data: dict) -> HTMLResponse:
    response = templates.TemplateResponse(
        request=request,
        name="terminal-frame.html",
        context={
            "request": request,
            "session_data": session_data,
            "terminal_frame_css_url": TERMINAL_FRAME_CSS_URL,
            "terminal_frame_js_url": TERMINAL_FRAME_JS_URL,
        },
    )
    response.headers["Cross-Origin-Embedder-Policy"] = "require-corp"
    response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
    response.headers["Cross-Origin-Resource-Policy"] = "same-origin"
    return response


async def delayed_failure(request: Request, started: float, login_id: str) -> HTMLResponse:
    remaining = 0.9 - (time.monotonic() - started)
    if remaining > 0:
        await asyncio.sleep(remaining)
    return render_page(request, error="미안합니다.", login_id=login_id)


async def process_login_attempt(request: Request, login_id: str, password: str) -> tuple[bool, str | None]:
    ip_text = client_ip(request)
    if ip_text == "unknown":
        return False, None
    if not await app.state.redis.exists(allow_key(ip_text)):
        return False, None
    username = await asyncio.to_thread(ldap_authenticate, settings, login_id, password)
    if not username:
        return False, None
    return True, username


async def verify_session_password(username: str, password: str) -> bool:
    if not password:
        return False
    matched = await asyncio.to_thread(ldap_authenticate, settings, username, password)
    return matched == username


def external_email_pending_key(username: str) -> str:
    return f"workstation:iplogin:external-email:pending:{username}"


def external_email_pending_email_key(email: str) -> str:
    return f"workstation:iplogin:external-email:pending-email:{email}"


def generate_external_email_code() -> str:
    return f"{secrets.randbelow(10 ** EXTERNAL_EMAIL_CODE_DIGITS):0{EXTERNAL_EMAIL_CODE_DIGITS}d}"


async def clear_pending_external_email(username: str) -> None:
    key = external_email_pending_key(username)
    pending = await app.state.redis.hgetall(key)
    pending_email = str(pending.get("email", "")).strip().lower()
    if pending_email:
        await app.state.redis.delete(external_email_pending_email_key(pending_email))
    await app.state.redis.delete(key)


def send_external_email_verification_message(
    *,
    sender_email: str,
    target_email: str,
    code: str,
    ttl_seconds: int,
) -> None:
    message = EmailMessage()
    message["From"] = sender_email
    message["To"] = target_email
    message["Reply-To"] = sender_email
    message["Subject"] = f"[{settings.mail_domain}] 외부 이메일 인증 번호"
    message.set_content(
        "\n".join(
            [
                f"{settings.product_title} 외부 이메일 인증 안내입니다.",
                "",
                f"LDAP 계정 이메일: {sender_email}",
                f"대상 외부 이메일: {target_email}",
                f"인증 번호: {code}",
                f"유효 시간: {max(1, ttl_seconds // 60)}분",
                "",
                "이 요청을 본인이 하지 않았다면 이 메일을 무시하십시오.",
            ]
        )
    )
    subprocess.run(
        [settings.sendmail_path, "-t", "-oi", "-f", sender_email],
        input=message.as_bytes(),
        capture_output=True,
        check=True,
    )


async def current_registered_external_email(username: str) -> str | None:
    return await asyncio.to_thread(
        registered_email,
        settings.external_email_store_file,
        username,
    )


async def external_email_payload(username: str) -> dict[str, Any]:
    current_email = await current_registered_external_email(username)
    pending = await app.state.redis.hgetall(external_email_pending_key(username))
    pending_email = str(pending.get("email", "")).strip().lower()
    pending_ttl = await app.state.redis.ttl(external_email_pending_key(username))
    pending_active = bool(pending_email and pending_ttl > 0)
    return {
        "ok": True,
        "registered": bool(current_email),
        "registered_email": current_email or "",
        "can_register": not current_email,
        "can_change": bool(current_email),
        "pending": pending_active,
        "pending_email": pending_email if pending_active else "",
        "pending_email_masked": mask_email(pending_email) if pending_active else "",
        "pending_expires_in_seconds": pending_ttl if pending_active else 0,
    }


async def create_login_session(ip_text: str, username: str) -> str:
    session_id = secrets.token_urlsafe(32)
    await app.state.redis.hset(
        session_key(session_id),
        mapping={
            "username": username,
            "ip": ip_text,
            "created_at": str(int(time.time())),
        },
    )
    await app.state.redis.expire(session_key(session_id), settings.session_ttl_seconds)
    return session_id


def parse_optional_positive_int(raw_value: str | None) -> int | None:
    value = str(raw_value or "").strip()
    if not value:
        return None
    if not value.isdigit():
        return None
    parsed = int(value)
    return parsed if parsed > 0 else None


def chat_message_text(raw_value: str | None) -> str:
    text = str(raw_value or "").replace("\r\n", "\n").replace("\r", "\n")
    text = text.strip()
    if len(text) > CHAT_MESSAGE_MAX_CHARS:
        text = text[:CHAT_MESSAGE_MAX_CHARS].rstrip()
    return text


def parse_png_dimensions(raw_bytes: bytes) -> tuple[int, int]:
    if len(raw_bytes) < 24:
        raise ValueError("png payload too small")
    if raw_bytes[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("not a png file")
    if raw_bytes[12:16] != b"IHDR":
        raise ValueError("png ihdr chunk missing")
    width = int.from_bytes(raw_bytes[16:20], "big")
    height = int.from_bytes(raw_bytes[20:24], "big")
    if width <= 0 or height <= 0:
        raise ValueError("invalid png dimensions")
    return width, height


def is_test_workspace_account(username: str, gecos: str) -> bool:
    normalized_username = str(username or "").strip().lower()
    normalized_gecos = str(gecos or "").strip().lower()
    if any(term in normalized_username for term in TEST_ACCOUNT_TERMS):
        return True
    return any(re.search(rf"\b{re.escape(term)}\b", normalized_gecos) for term in TEST_ACCOUNT_TERMS)


def workspace_chat_candidates(current_username: str) -> list[dict[str, str]]:
    normalized_current = str(current_username or "").strip().lower()
    root = WORKSPACE_USERS_ROOT
    if not root.is_dir():
        return []

    peers: list[dict[str, str]] = []
    for child in sorted(root.iterdir(), key=lambda path: path.name.lower()):
        if not child.is_dir():
            continue
        username = child.name.strip().lower()
        if not username or username == normalized_current:
            continue
        if normalize_login_id(username, settings.mail_domain) != username:
            continue
        if not (child / "home").is_dir():
            continue
        try:
            pwent = pwd.getpwnam(username)
        except KeyError:
            continue
        if pwent.pw_uid < CHAT_PERSON_UID_MIN:
            continue
        if Path(pwent.pw_dir) != Path("/home") / username:
            continue
        if not pwent.pw_shell or pwent.pw_shell in {"/usr/sbin/nologin", "/usr/bin/false", "/bin/false"}:
            continue
        if is_test_workspace_account(username, pwent.pw_gecos):
            continue
        peers.append(
            {
                "username": username,
                "display_name": username,
            }
        )
    return peers


def workspace_chat_users_payload(current_username: str) -> list[dict[str, Any]]:
    peers = workspace_chat_candidates(current_username)
    peer_names = [peer["username"] for peer in peers]
    summaries = list_chat_peer_summaries(CHAT_STORE_FILE, current_username, peer_names)
    unread = chat_unread_summary(CHAT_STORE_FILE, current_username, peer_names)
    unread_peers = unread.get("peers", {})
    items: list[dict[str, Any]] = []
    for peer in peers:
        summary = summaries.get(peer["username"], {})
        peer_unread = unread_peers.get(peer["username"], {})
        last_message_body = str(summary.get("last_message_body", "") or "")
        items.append(
            {
                "username": peer["username"],
                "display_name": peer["display_name"],
                "last_message_id": int(summary.get("last_message_id", 0) or 0),
                "last_message_created_at_display": str(summary.get("last_message_created_at_display", "") or ""),
                "last_message_preview": last_message_body[:72],
                "unread_count": int(peer_unread.get("unread_count", 0) or 0),
                "latest_unread_id": int(peer_unread.get("latest_unread_id", 0) or 0),
            }
        )
    items.sort(key=lambda item: (-int(item["last_message_id"]), str(item["username"])))
    return items


def workspace_chat_unread_payload(current_username: str) -> dict[str, Any]:
    peers = workspace_chat_candidates(current_username)
    return chat_unread_summary(CHAT_STORE_FILE, current_username, [peer["username"] for peer in peers])


def workspace_chat_peer_allowed(current_username: str, peer_username: str) -> bool:
    normalized_peer = str(peer_username or "").strip().lower()
    return any(item["username"] == normalized_peer for item in workspace_chat_candidates(current_username))


def chat_message_payload(item: dict[str, Any], current_username: str) -> dict[str, Any]:
    sender = str(item.get("sender", "") or "").strip().lower()
    recipient = str(item.get("recipient", "") or "").strip().lower()
    message_type = str(item.get("message_type", "") or "text").strip().lower() or "text"
    media_token = str(item.get("media_token", "") or "").strip()
    body = str(item.get("body", "") or "")
    return {
        "id": int(item.get("id", 0) or 0),
        "sender": sender,
        "recipient": recipient,
        "body": body,
        "message_type": message_type,
        "preview_text": CHAT_SCREENSHOT_PREVIEW_TEXT if message_type == "image" else body,
        "media_token": media_token,
        "media_mime": str(item.get("media_mime", "") or ""),
        "media_filename": str(item.get("media_filename", "") or ""),
        "media_width": int(item.get("media_width", 0) or 0),
        "media_height": int(item.get("media_height", 0) or 0),
        "media_size": int(item.get("media_size", 0) or 0),
        "media_url": f"/api/workspace/chat/media/{media_token}" if message_type == "image" and media_token else "",
        "created_at_epoch": int(item.get("created_at_epoch", 0) or 0),
        "created_at_display": str(item.get("created_at_display", "") or ""),
        "is_self": sender == str(current_username or "").strip().lower(),
        "display_name": sender or recipient,
    }


def run_desktop_helper(username: str) -> dict:
    result = subprocess.run(
        ["sudo", "-n", settings.desktop_helper_path, "ensure", username],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)
    return {
        "username": payload["username"],
        "port": int(payload["port"]),
        "home": payload.get("home", ""),
    }


def run_desktop_secret_command(*args: str, password: str, timeout: float | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["sudo", "-n", settings.desktop_helper_path, *args],
        check=True,
        capture_output=True,
        text=True,
        timeout=timeout,
        input=password,
    )


def run_desktop_command(*args: str, text: bool = True, timeout: float | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["sudo", "-n", settings.desktop_helper_path, *args],
        check=True,
        capture_output=True,
        text=text,
        timeout=timeout,
    )


async def clear_session_desktop_state(session_data: dict) -> None:
    session_id = session_data["session_id"]
    clear_desktop_task(session_id)
    await app.state.redis.hdel(
        session_key(session_id),
        "desktop_port",
        "desktop_home",
        "desktop_ready_at",
        "desktop_error",
        "desktop_error_at",
    )
    session_data.pop("desktop_port", None)
    session_data.pop("desktop_home", None)
    session_data.pop("desktop_ready_at", None)
    session_data.pop("desktop_error", None)
    session_data.pop("desktop_error_at", None)


async def set_session_desktop_state(session_data: dict, username: str | None = None) -> dict[str, Any]:
    resolved_username = username or session_data["username"]
    result = await asyncio.to_thread(run_desktop_command, "status", resolved_username)
    payload = json.loads(result.stdout)
    if not payload.get("active"):
        raise RuntimeError(f"desktop backend not active for {resolved_username}")

    ready_at = str(int(time.time()))
    await app.state.redis.hset(
        session_key(session_data["session_id"]),
        mapping={
            "desktop_port": str(payload["port"]),
            "desktop_home": payload.get("home", ""),
            "desktop_ready_at": ready_at,
        },
    )
    await app.state.redis.hdel(
        session_key(session_data["session_id"]),
        "desktop_error",
        "desktop_error_at",
    )
    session_data["desktop_port"] = str(payload["port"])
    session_data["desktop_home"] = payload.get("home", "")
    session_data["desktop_ready_at"] = ready_at
    session_data.pop("desktop_error", None)
    session_data.pop("desktop_error_at", None)
    return payload


def run_audio_metadata(username: str) -> dict[str, Any]:
    result = run_desktop_command("audio-info", username)
    payload = json.loads(result.stdout)
    return {
        "source": str(payload.get("source") or ""),
        "format": str(payload.get("format") or "s16le"),
        "channels": int(payload.get("channels") or 2),
        "sample_rate": int(payload.get("sample_rate") or 48000),
    }


def desktop_backend_payload(session_data: dict, port: int) -> dict[str, Any]:
    return {
        "username": session_data["username"],
        "port": port,
        "home": session_data.get("desktop_home", ""),
    }


def desktop_recently_started(session_data: dict, grace_seconds: int = DESKTOP_RECENT_START_GRACE_SECONDS) -> bool:
    started_at = session_data.get("desktop_ready_at", "")
    if not started_at.isdigit():
        return False
    return (time.time() - int(started_at)) < grace_seconds


def clipboard_entry_token(username: str, kind: str, payload: bytes) -> str:
    digest = hashlib.sha256(payload).hexdigest()
    return f"{username}:{kind}:{digest}"


def clipboard_cache_put(token: str, entry: dict[str, Any]) -> None:
    app.state.clipboard_cache[token] = entry
    if len(app.state.clipboard_cache) > 64:
        for stale in list(app.state.clipboard_cache.keys())[:-64]:
            app.state.clipboard_cache.pop(stale, None)


def clipboard_cache_get(token: str, username: str) -> dict[str, Any] | None:
    entry = app.state.clipboard_cache.get(token)
    if not entry or entry.get("username") != username:
        return None
    return entry


def parse_file_uris(raw: bytes, home: str) -> tuple[list[str], list[Path]]:
    text = raw.decode("utf-8", errors="ignore").replace("\r\n", "\n")
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if lines and lines[0] in {"copy", "cut"}:
        lines = lines[1:]

    uris: list[str] = []
    paths: list[Path] = []
    home_path = Path(home).resolve()
    for item in lines:
        parsed = urlparse(item)
        if parsed.scheme != "file":
            continue
        candidate = Path(unquote(parsed.path)).resolve()
        if not candidate.exists():
            continue
        try:
            candidate.relative_to(home_path)
        except ValueError:
            continue
        uris.append(candidate.as_uri())
        paths.append(candidate)
    return uris, paths


def user_home_path(session_data: dict[str, Any]) -> Path:
    return Path(session_data.get("desktop_home") or f"/home/{session_data['username']}").resolve()


def sanitize_upload_name(name: str, default: str = "upload.bin") -> str:
    clean = unicodedata.normalize("NFC", Path(str(name or default).replace("\x00", "")).name)
    clean = clean.replace("/", "_").replace("\\", "_")
    clean = re.sub(r"[\x00-\x1f\x7f]+", "", clean).strip()
    if clean in {"", ".", ".."}:
        return default
    return clean


def content_disposition_attachment(filename: str) -> str:
    clean = sanitize_upload_name(filename, default="download")
    suffix = Path(clean).suffix
    stem = Path(clean).stem or clean
    fallback_stem = re.sub(r"[^A-Za-z0-9._-]+", "_", stem).strip("._-") or "download"
    if not re.search(r"[A-Za-z]", fallback_stem):
        fallback_stem = f"download-{fallback_stem}".strip("-")
    fallback = f"{fallback_stem}{suffix}"
    encoded = quote(clean, safe="")
    return f"attachment; filename=\"{fallback}\"; filename*=UTF-8''{encoded}"


async def write_upload_to_path(upload: Any, destination: Path, chunk_size: int = 1024 * 1024) -> None:
    with destination.open("wb") as handle:
        while True:
            chunk = await upload.read(chunk_size)
            if not chunk:
                break
            handle.write(chunk)
    close = getattr(upload, "close", None)
    if callable(close):
        maybe_coro = close()
        if asyncio.iscoroutine(maybe_coro):
            await maybe_coro


def workspace_path_target(home_path: Path, requested: str) -> tuple[str, str | None, str, Path]:
    requested = (requested or "").strip()
    normalized = requested.lstrip("/")
    candidate = (home_path / normalized).resolve()
    try:
        relative = candidate.relative_to(home_path)
    except ValueError:
        candidate = home_path
        relative = Path(".")

    current = "" if str(relative) == "." else str(relative)
    parent: str | None
    if current:
        parent_path = relative.parent
        parent = "" if str(parent_path) == "." else str(parent_path)
    else:
        parent = None
    current_display = "/" if not current else f"/{current}"
    return current, parent, current_display, candidate


def workspace_unique_path(directory: Path, filename: str) -> Path:
    target = directory / filename
    stem = Path(filename).stem or "upload"
    suffix = Path(filename).suffix
    counter = 1
    while target.exists():
        target = directory / f"{stem}-{counter}{suffix}"
        counter += 1
    return target


def workspace_listing(home_path: Path, requested: str) -> dict[str, Any]:
    current, parent, current_display, target = workspace_path_target(home_path, requested)
    if not target.exists():
        raise FileNotFoundError("path not found")
    if not target.is_dir():
        raise NotADirectoryError("path is not a directory")

    items: list[dict[str, Any]] = []
    for child in sorted(target.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower())):
        if child.name.startswith("."):
            continue
        child_rel = child.relative_to(home_path)
        stat = child.stat()
        items.append(
            {
                "name": child.name,
                "path": str(child_rel),
                "kind": "dir" if child.is_dir() else "file",
                "size": 0 if child.is_dir() else stat.st_size,
                "mtime": time.strftime("%Y-%m-%d %H:%M", time.localtime(stat.st_mtime)),
            }
        )

    return {
        "ok": True,
        "current": current,
        "current_display": current_display,
        "parent": parent,
        "items": items,
    }


def snapshot_rich_clipboard(username: str, home: str, session_id: str) -> dict[str, Any]:
    try:
        targets_result = run_desktop_command("clipboard-targets", username, text=False)
    except subprocess.CalledProcessError:
        return {"ok": True, "changed": False, "kind": "none"}

    targets = {
        line.strip()
        for line in targets_result.stdout.decode("utf-8", errors="ignore").splitlines()
        if line.strip()
    }

    if "image/png" in targets:
        data = run_desktop_command("clipboard-read", username, "image/png", text=False).stdout
        token = clipboard_entry_token(username, "image", data)
        changed = token != app.state.clipboard_last.get(session_id)
        clipboard_cache_put(
            token,
            {
                "username": username,
                "kind": "image",
                "mime": "image/png",
                "data": data,
            },
        )
        app.state.clipboard_last[session_id] = token
        return {
            "ok": True,
            "changed": changed,
            "kind": "image",
            "mime": "image/png",
            "token": token,
        }

    for mime in ("x-special/gnome-copied-files", "text/uri-list"):
        if mime not in targets:
            continue
        raw = run_desktop_command("clipboard-read", username, mime, text=False).stdout
        uris, paths = parse_file_uris(raw, home)
        if not uris:
            continue
        token = clipboard_entry_token(username, "files", "\n".join(uris).encode("utf-8"))
        changed = token != app.state.clipboard_last.get(session_id)
        clipboard_cache_put(
            token,
            {
                "username": username,
                "kind": "files",
                "mime": mime,
                "paths": paths,
                "uris": uris,
                "names": [path.name for path in paths],
                "text": "\n".join(uris),
            },
        )
        app.state.clipboard_last[session_id] = token
        return {
            "ok": True,
            "changed": changed,
            "kind": "files",
            "mime": mime,
            "token": token,
            "uris": uris,
            "names": [path.name for path in paths],
            "text": "\n".join(uris),
        }

    return {"ok": True, "changed": False, "kind": "none"}


async def ensure_desktop_backend(session_data: dict) -> dict:
    session_id = session_data["session_id"]
    current_task = app.state.desktop_tasks.get(session_id)
    if current_task and not current_task.done():
        await current_task
        refreshed = await session_from_values(session_id, session_data.get("ip", ""))
        if refreshed:
            session_data.update(refreshed)
        ready_backend = await cached_desktop_backend(session_data)
        if ready_backend:
            return ready_backend

    port_text = session_data.get("desktop_port")
    if port_text and port_text.isdigit():
        port = int(port_text)
        if await desktop_backend_ready(port):
            return desktop_backend_payload(session_data, port)
        if desktop_recently_started(session_data):
            deadline = time.monotonic() + DESKTOP_RECENT_START_WAIT_SECONDS
            while time.monotonic() < deadline:
                if await desktop_backend_ready(port):
                    return desktop_backend_payload(session_data, port)
                await asyncio.sleep(0.5)

    backend = await asyncio.to_thread(run_desktop_helper, session_data["username"])
    await app.state.redis.hset(
        session_key(session_data["session_id"]),
        mapping={
            "desktop_port": str(backend["port"]),
            "desktop_home": backend["home"],
            "desktop_ready_at": str(int(time.time())),
        },
    )
    session_data["desktop_port"] = str(backend["port"])
    session_data["desktop_home"] = backend["home"]
    return backend


async def desktop_backend_ready(port: int, timeout: float = 0.8) -> bool:
    for attempt in range(DESKTOP_READY_RETRIES):
        try:
            async with httpx.AsyncClient(timeout=max(timeout, DESKTOP_READY_TIMEOUT_SECONDS), follow_redirects=False) as client:
                response = await client.get(
                    f"http://{settings.desktop_backend_host}:{port}/",
                    headers={
                        "Authorization": desktop_proxy_authorization(),
                        "X-Forwarded-Proto": "https",
                    },
                )
            if response.status_code < 500:
                return True
        except Exception:
            pass
        if attempt + 1 < DESKTOP_READY_RETRIES:
            await asyncio.sleep(DESKTOP_READY_RETRY_DELAY_SECONDS)
    return False


async def cached_desktop_backend(session_data: dict) -> dict[str, Any] | None:
    port_text = session_data.get("desktop_port")
    if not port_text or not port_text.isdigit():
        return None
    port = int(port_text)
    if not await desktop_backend_ready(port):
        return None
    return desktop_backend_payload(session_data, port)


def clear_desktop_task(session_id: str) -> None:
    app.state.desktop_tasks.pop(session_id, None)


async def background_start_desktop(session_id: str, username: str, login_password: str | None = None) -> None:
    try:
        backend = await asyncio.to_thread(run_desktop_helper, username)
        if login_password:
            try:
                await asyncio.to_thread(
                    run_desktop_secret_command,
                    "keyring-sync",
                    username,
                    password=login_password,
                    timeout=20,
                )
            except Exception:
                logger.exception("workspace keyring sync failed after backend start for %s", username)
        await app.state.redis.hset(
            session_key(session_id),
            mapping={
                "desktop_port": str(backend["port"]),
                "desktop_home": backend.get("home", ""),
                "desktop_ready_at": str(int(time.time())),
            },
        )
        await app.state.redis.hdel(
            session_key(session_id),
            "desktop_error",
            "desktop_error_at",
        )
    except Exception:
        logger.exception("desktop backend start failed for %s", username)
        await app.state.redis.hset(
            session_key(session_id),
            mapping={
                "desktop_error": "1",
                "desktop_error_at": str(int(time.time())),
            },
        )
        raise
    finally:
        clear_desktop_task(session_id)


async def schedule_desktop_backend(session_data: dict, login_password: str | None = None) -> None:
    session_id = session_data["session_id"]
    if await cached_desktop_backend(session_data):
        return
    current_task = app.state.desktop_tasks.get(session_id)
    if current_task and not current_task.done():
        return
    if session_data.get("desktop_port") and desktop_recently_started(session_data):
        return
    await app.state.redis.hdel(
        session_key(session_id),
        "desktop_error",
        "desktop_error_at",
    )
    task = asyncio.create_task(background_start_desktop(session_id, session_data["username"], login_password))
    app.state.desktop_tasks[session_id] = task


def workspace_target(port: int, path: str, query: str) -> str:
    cleaned = path.lstrip("/")
    target = f"http://{settings.desktop_backend_host}:{port}/"
    if cleaned:
        target = f"{target}{cleaned}"
    if query:
        target = f"{target}?{query}"
    return target


def websocket_target(port: int, path: str, query: str) -> str:
    cleaned = path.lstrip("/")
    target = f"ws://{settings.desktop_backend_host}:{port}/"
    if cleaned:
        target = f"{target}{cleaned}"
    if query:
        target = f"{target}?{query}"
    return target


def desktop_proxy_authorization() -> str:
    token = base64.b64encode(
        f"{settings.desktop_proxy_user}:{settings.desktop_proxy_password}".encode("utf-8")
    ).decode("ascii")
    return f"Basic {token}"


def coerce_terminal_size(value: Any, fallback: int, minimum: int, maximum: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return fallback
    return max(minimum, min(maximum, number))


def set_pty_size(fd: int, cols: int, rows: int) -> None:
    packed = struct.pack(
        "HHHH",
        coerce_terminal_size(rows, TERMINAL_DEFAULT_ROWS, 2, 500),
        coerce_terminal_size(cols, TERMINAL_DEFAULT_COLS, 10, 500),
        0,
        0,
    )
    fcntl.ioctl(fd, termios.TIOCSWINSZ, packed)


def read_pty_chunk(fd: int, size: int = TERMINAL_PTY_READ_SIZE) -> bytes:
    try:
        return os.read(fd, size)
    except OSError as exc:
        if exc.errno in {errno.EIO, errno.EBADF}:
            return b""
        raise


async def wait_for_pty_chunk(fd: int) -> bytes:
    loop = asyncio.get_running_loop()
    future: asyncio.Future[bytes] = loop.create_future()

    def on_ready() -> None:
        if future.done():
            return
        try:
            future.set_result(read_pty_chunk(fd))
        except Exception as exc:
            future.set_exception(exc)

    loop.add_reader(fd, on_ready)
    try:
        return await future
    finally:
        with contextlib.suppress(Exception):
            loop.remove_reader(fd)


def spawn_terminal_process(username: str, cols: int, rows: int) -> tuple[subprocess.Popen[bytes], int]:
    master_fd, slave_fd = pty.openpty()
    try:
        set_pty_size(slave_fd, cols, rows)

        def prepare_child() -> None:
            os.setsid()
            fcntl.ioctl(slave_fd, termios.TIOCSCTTY, 0)

        process = subprocess.Popen(
            ["sudo", "-n", settings.desktop_helper_path, "terminal-shell", username],
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=slave_fd,
            preexec_fn=prepare_child,
            close_fds=True,
        )
    except Exception:
        os.close(master_fd)
        os.close(slave_fd)
        raise

    os.close(slave_fd)
    return process, master_fd


def signal_process_group(pid: int, sig: int) -> None:
    with contextlib.suppress(ProcessLookupError):
        os.killpg(pid, sig)


async def drain_subprocess_logs(stream: asyncio.StreamReader | None, label: str) -> None:
    if stream is None:
        return
    while True:
        line = await stream.readline()
        if not line:
            return
        message = line.decode("utf-8", errors="replace").strip()
        if message:
            logger.warning("%s: %s", label, message)


def notification_monitor_command(username: str) -> list[str]:
    return ["sudo", "-n", settings.desktop_helper_path, "notification-monitor", username]


def decode_dbus_monitor_string(line: str) -> str | None:
    match = re.match(r'^string "(.*)"$', line.strip())
    if not match:
        return None
    raw = match.group(1)
    try:
        return json.loads(f'"{raw}"')
    except json.JSONDecodeError:
        return raw.replace(r"\"", '"').replace(r"\\", "\\")


def is_dbus_monitor_block_header(line: str) -> bool:
    return bool(line) and not line.startswith(" ")


def parse_notification_monitor_block(lines: list[str]) -> dict[str, Any] | None:
    if not lines:
        return None
    header = lines[0].strip()
    if "interface=org.freedesktop.Notifications" not in header or "member=Notify" not in header:
        return None
    strings: list[str] = []
    saw_top_level_array = False
    expire_timeout = -1
    for raw_line in lines:
        line = raw_line.strip()
        if line.startswith("array ["):
            saw_top_level_array = True
            continue
        if not saw_top_level_array and line.startswith("string "):
            value = decode_dbus_monitor_string(line)
            if value is not None:
                strings.append(value)
            continue
        if line.startswith("int32 "):
            try:
                expire_timeout = int(line.split(None, 1)[1].strip())
            except (IndexError, ValueError):
                expire_timeout = -1

    app_name = strings[0].strip() if len(strings) > 0 else ""
    app_icon = strings[1].strip() if len(strings) > 1 else ""
    summary = strings[2].strip() if len(strings) > 2 else ""
    body = strings[3].strip() if len(strings) > 3 else ""
    if not any((summary, body)):
        return None
    return {
        "app_name": app_name,
        "app_icon": app_icon,
        "summary": summary,
        "body": body,
        "expire_timeout": expire_timeout,
        "created_at_display": time.strftime("%Y-%m-%d-%H:%M:%S", time.localtime()),
        "tag": hashlib.sha256(
            "\x1f".join(
                [
                    app_name,
                    app_icon,
                    summary,
                    body,
                    str(expire_timeout),
                    str(time.time_ns()),
                ]
            ).encode("utf-8", errors="ignore")
        ).hexdigest()[:24],
    }


def publish_workspace_notification(bridge: WorkspaceNotificationBridge, payload: dict[str, Any]) -> None:
    for queue in tuple(bridge.subscribers):
        if queue.full():
            with contextlib.suppress(asyncio.QueueEmpty):
                queue.get_nowait()
        with contextlib.suppress(asyncio.QueueFull):
            queue.put_nowait(payload)


async def terminate_async_process(process: asyncio.subprocess.Process | None, *, label: str) -> None:
    if process is None or process.returncode is not None:
        return
    with contextlib.suppress(ProcessLookupError):
        process.terminate()
    try:
        await asyncio.wait_for(process.wait(), timeout=2)
        return
    except (asyncio.TimeoutError, ProcessLookupError):
        pass
    with contextlib.suppress(ProcessLookupError):
        process.kill()
    with contextlib.suppress(asyncio.TimeoutError, ProcessLookupError):
        await asyncio.wait_for(process.wait(), timeout=2)


async def run_workspace_notification_bridge(bridge: WorkspaceNotificationBridge) -> None:
    process: asyncio.subprocess.Process | None = None
    stderr_task: asyncio.Task[None] | None = None
    try:
        while bridge.subscribers:
            try:
                process = await asyncio.create_subprocess_exec(
                    *notification_monitor_command(bridge.username),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
            except Exception:
                logger.exception("workspace notification monitor start failed for %s", bridge.username)
                if not bridge.subscribers:
                    break
                await asyncio.sleep(NOTIFICATION_BRIDGE_RESTART_DELAY_SECONDS)
                continue

            stderr_task = asyncio.create_task(
                drain_subprocess_logs(process.stderr, f"workspace-notification-monitor[{bridge.username}]")
            )
            current_block: list[str] = []
            try:
                assert process.stdout is not None
                while bridge.subscribers:
                    raw_line = await process.stdout.readline()
                    if not raw_line:
                        break
                    line = raw_line.decode("utf-8", errors="replace").rstrip("\r\n")
                    if is_dbus_monitor_block_header(line):
                        payload = parse_notification_monitor_block(current_block)
                        if payload:
                            publish_workspace_notification(bridge, payload)
                        current_block = [line]
                        continue
                    if current_block:
                        current_block.append(line)
                        if line.strip().startswith("int32 "):
                            payload = parse_notification_monitor_block(current_block)
                            if payload:
                                publish_workspace_notification(bridge, payload)
                                current_block = []

                payload = parse_notification_monitor_block(current_block)
                if payload:
                    publish_workspace_notification(bridge, payload)
            finally:
                await terminate_async_process(process, label=f"workspace-notification-monitor[{bridge.username}]")
                process = None
                if stderr_task:
                    stderr_task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await stderr_task
                    stderr_task = None

            if bridge.subscribers:
                await asyncio.sleep(NOTIFICATION_BRIDGE_RESTART_DELAY_SECONDS)
    except asyncio.CancelledError:
        raise
    finally:
        if stderr_task:
            stderr_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await stderr_task
        await terminate_async_process(process, label=f"workspace-notification-monitor[{bridge.username}]")
        async with app.state.notification_bridge_lock:
            current = app.state.notification_bridges.get(bridge.username)
            if current is bridge and not bridge.subscribers:
                app.state.notification_bridges.pop(bridge.username, None)


async def register_workspace_notification_client(username: str) -> asyncio.Queue[dict[str, Any]]:
    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=NOTIFICATION_STREAM_QUEUE_SIZE)
    async with app.state.notification_bridge_lock:
        bridge = app.state.notification_bridges.get(username)
        if bridge is None:
            bridge = WorkspaceNotificationBridge(username=username)
            app.state.notification_bridges[username] = bridge
        bridge.subscribers.add(queue)
        if bridge.task is None or bridge.task.done():
            bridge.task = asyncio.create_task(run_workspace_notification_bridge(bridge))
    return queue


async def unregister_workspace_notification_client(username: str, queue: asyncio.Queue[dict[str, Any]]) -> None:
    bridge: WorkspaceNotificationBridge | None = None
    task: asyncio.Task[None] | None = None
    async with app.state.notification_bridge_lock:
        bridge = app.state.notification_bridges.get(username)
        if bridge is None:
            return
        bridge.subscribers.discard(queue)
        if not bridge.subscribers:
            task = bridge.task
            bridge.task = None
            app.state.notification_bridges.pop(username, None)
    if task:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


def forwarded_request_headers(request: Request) -> dict[str, str]:
    headers: dict[str, str] = {}
    for key, value in request.headers.items():
        lower = key.lower()
        if lower in HOP_BY_HOP_HEADERS or lower in {"host", "cookie", "content-length", "accept-encoding"}:
            continue
        headers[key] = value
    headers["X-Real-IP"] = client_ip(request)
    headers["X-Forwarded-Proto"] = "https"
    headers["X-Forwarded-For"] = request.headers.get("x-forwarded-for", client_ip(request))
    headers["Authorization"] = desktop_proxy_authorization()
    # Keep upstream responses uncompressed so header and body semantics stay aligned
    # after httpx reads and re-emits the content through FastAPI.
    headers["Accept-Encoding"] = "identity"
    return headers


def forwarded_response_headers(headers: httpx.Headers) -> dict[str, str]:
    proxied: dict[str, str] = {}
    for key, value in headers.items():
        lower = key.lower()
        if lower in HOP_BY_HOP_HEADERS or lower in {"content-length", "content-encoding"}:
            continue
        if lower == "location" and value.startswith("/"):
            proxied[key] = f"/workspace{value}"
            continue
        proxied[key] = value
    return proxied


def inject_workspace_overrides(content: bytes, headers: httpx.Headers) -> bytes:
    content_type = headers.get("content-type", "").lower()
    if "text/html" not in content_type:
        return content
    try:
        document = content.decode("utf-8")
    except UnicodeDecodeError:
        return content
    if "/static/kasmvnc/workspace.css" not in document and "</head>" in document:
        document = document.replace(
            "</head>",
            f'  <link rel="stylesheet" href="{WORKSPACE_CSS_URL}">\n</head>',
            1,
        )
    if "/static/kasmvnc/workspace.js" not in document and "</body>" in document:
        document = document.replace(
            "</body>",
            f'  <script src="{WORKSPACE_JS_URL}"></script>\n</body>',
            1,
        )
    return document.encode("utf-8")


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    return render_page(request, session_data=await current_session(request))


@app.get("/workspace-terminal-frame", response_class=HTMLResponse)
async def workspace_terminal_frame(request: Request) -> HTMLResponse:
    session_data = await current_session(request)
    if not session_data:
        return HTMLResponse("세션이 만료되었습니다.", status_code=403)
    return render_terminal_frame_page(request, session_data)


@app.get("/api/workspace/notifications/stream")
async def workspace_notifications_stream(request: Request) -> Response:
    session_data = await current_session(request)
    if not session_data:
        return PlainTextResponse("세션이 만료되었습니다.", status_code=403)

    await ensure_desktop_backend(session_data)
    queue = await register_workspace_notification_client(session_data["username"])

    async def event_stream() -> Any:
        try:
            yield "event: ready\ndata: {}\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    payload = await asyncio.wait_for(queue.get(), timeout=NOTIFICATION_STREAM_KEEPALIVE_SECONDS)
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
                    continue
                yield f"event: notification\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
        finally:
            await unregister_workspace_notification_client(session_data["username"], queue)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-store",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/login", response_class=HTMLResponse)
async def login(
    request: Request,
    login_id: str = Form(""),
    password: str = Form(""),
) -> Response:
    started = time.monotonic()
    ok, username = await process_login_attempt(request, login_id, password)
    if not ok or not username:
        return await delayed_failure(request, started, login_id)

    session_id = await create_login_session(client_ip(request), username)
    await schedule_desktop_backend(
        {
            "session_id": session_id,
            "username": username,
            "ip": client_ip(request),
        },
        login_password=password,
    )

    response = RedirectResponse("/workspace/", status_code=303)
    set_login_session_cookie(response, session_id)
    return response


@app.post("/api/login")
async def api_login(
    request: Request,
    login_id: str = Form(""),
    password: str = Form(""),
) -> JSONResponse:
    ok, username = await process_login_attempt(request, login_id, password)
    if not ok or not username:
        return JSONResponse({"ok": False, "message": "미안합니다."}, status_code=200)

    session_id = await create_login_session(client_ip(request), username)
    await schedule_desktop_backend(
        {
            "session_id": session_id,
            "username": username,
            "ip": client_ip(request),
        },
        login_password=password,
    )
    response = JSONResponse(
        {
            "ok": True,
            "message": "환영합니다.",
            "redirect": "/workspace/prepare",
        },
        status_code=200,
    )
    set_login_session_cookie(response, session_id)
    return response


@app.post("/api/login/email/request")
async def api_login_email_request(
    request: Request,
    login_id: str = Form(""),
) -> JSONResponse:
    browser_token, issued = resolve_email_login_browser_token(request)
    failure = JSONResponse({"ok": False, "message": "미안합니다."}, status_code=200)
    if issued:
        set_email_login_browser_cookie(failure, browser_token)

    ip_text = client_ip(request)
    if ip_text == "unknown":
        return failure

    count, _ttl = await email_login_request_count(browser_token)
    if count > EMAIL_LOGIN_REQUEST_LIMIT:
        return failure

    username = normalize_login_id(login_id, settings.mail_domain)
    if not username:
        return failure

    target_email = await current_registered_external_email(username)
    if not target_email:
        return failure

    pending_key = email_login_pending_key(browser_token)
    pending = await app.state.redis.hgetall(pending_key)
    requested_at = str(pending.get("requested_at", "")).strip()
    if requested_at.isdigit():
        elapsed = int(time.time()) - int(requested_at)
        if elapsed < EMAIL_LOGIN_RESEND_COOLDOWN_SECONDS:
            return failure

    sender_email = account_mail_address(username, settings)
    code = generate_external_email_code()
    await app.state.redis.hset(
        pending_key,
        mapping={
            "username": username,
            "email": target_email,
            "code": code,
            "ip": ip_text,
            "requested_at": str(int(time.time())),
            "attempts": "0",
        },
    )
    await app.state.redis.expire(pending_key, EMAIL_LOGIN_TTL_SECONDS)

    try:
        await asyncio.to_thread(
            send_login_email_verification_message,
            sender_email=sender_email,
            target_email=target_email,
            code=code,
            ttl_seconds=EMAIL_LOGIN_TTL_SECONDS,
        )
    except Exception:
        logger.exception("login email otp send failed for %s", username)
        await clear_pending_email_login(browser_token)
        return failure

    response = JSONResponse(
        {
            "ok": True,
            "message": "인증 번호를 보냈습니다.",
            "username": username,
            "expires_in_seconds": EMAIL_LOGIN_TTL_SECONDS,
            "resend_available_in_seconds": EMAIL_LOGIN_RESEND_COOLDOWN_SECONDS,
        },
        status_code=200,
    )
    if issued:
        set_email_login_browser_cookie(response, browser_token)
    return response


@app.post("/api/login/email/verify")
async def api_login_email_verify(
    request: Request,
    code: str = Form(""),
) -> JSONResponse:
    browser_token, issued = resolve_email_login_browser_token(request)
    failure = JSONResponse({"ok": False, "message": "미안합니다."}, status_code=200)
    if issued:
        set_email_login_browser_cookie(failure, browser_token)

    ip_text = client_ip(request)
    if ip_text == "unknown":
        return failure

    pending_key = email_login_pending_key(browser_token)
    pending = await app.state.redis.hgetall(pending_key)
    pending_ttl = await app.state.redis.ttl(pending_key)
    if not pending or pending_ttl <= 0:
        await clear_pending_email_login(browser_token)
        return failure

    username = str(pending.get("username", "")).strip().lower()
    expected_code = str(pending.get("code", "")).strip()
    pending_ip = str(pending.get("ip", "")).strip()
    submitted_code = normalize_email_login_code(code)
    if not username or not expected_code or pending_ip != ip_text:
        await clear_pending_email_login(browser_token)
        return failure

    if submitted_code != expected_code:
        attempts = await app.state.redis.hincrby(pending_key, "attempts", 1)
        if attempts >= EMAIL_LOGIN_VERIFY_ATTEMPT_LIMIT:
            await clear_pending_email_login(browser_token)
        return failure

    session_id = await create_login_session(ip_text, username)
    await schedule_desktop_backend(
        {
            "session_id": session_id,
            "username": username,
            "ip": ip_text,
        },
        login_password=None,
    )
    await clear_pending_email_login(browser_token)

    response = JSONResponse(
        {
            "ok": True,
            "message": "환영합니다.",
            "redirect": "/workspace/prepare",
        },
        status_code=200,
    )
    set_login_session_cookie(response, session_id)
    if issued:
        set_email_login_browser_cookie(response, browser_token)
    return response


@app.post("/logout")
async def logout(request: Request) -> RedirectResponse:
    session_id = request.cookies.get(settings.session_cookie_name)
    if session_id:
        await app.state.redis.delete(session_key(session_id))
    response = RedirectResponse(public_root_url(), status_code=303)
    response.delete_cookie(settings.session_cookie_name, path="/")
    return response


@app.get("/workspace", response_class=RedirectResponse)
async def workspace_slash() -> RedirectResponse:
    return RedirectResponse("/workspace/", status_code=307)


@app.get("/workspace/prepare", response_class=HTMLResponse)
async def workspace_prepare(request: Request) -> Response:
    session_data = await current_session(request)
    if not session_data:
        return RedirectResponse("/", status_code=303)
    await schedule_desktop_backend(session_data)
    return render_prepare_page(request, session_data)


@app.get("/api/workspace-status")
async def workspace_status(request: Request) -> JSONResponse:
    session_data = await current_session(request)
    if not session_data:
        return JSONResponse(
            {"ok": False, "status": "unauthorized", "message": "미안합니다.", "redirect": "/"},
            status_code=401,
        )

    ready_backend = await cached_desktop_backend(session_data)
    if ready_backend:
        if session_data.get("desktop_error") == "1":
            await app.state.redis.hdel(
                session_key(session_data["session_id"]),
                "desktop_error",
                "desktop_error_at",
            )
            session_data.pop("desktop_error", None)
            session_data.pop("desktop_error_at", None)
        return JSONResponse(
            {"ok": True, "status": "ready", "redirect": "/workspace/"},
            status_code=200,
        )

    if session_data.get("desktop_error") == "1":
        return JSONResponse(
            {"ok": False, "status": "failed", "message": "미안합니다.", "redirect": "/"},
            status_code=503,
        )

    await schedule_desktop_backend(session_data)
    return JSONResponse({"ok": True, "status": "starting"}, status_code=200)


@app.get("/api/workspace/chat/users")
async def workspace_chat_users(request: Request) -> JSONResponse:
    session_data = await current_session(request)
    if not session_data:
        return JSONResponse({"ok": False, "message": "미안합니다."}, status_code=401)

    try:
        users = await asyncio.to_thread(workspace_chat_users_payload, session_data["username"])
        unread = await asyncio.to_thread(workspace_chat_unread_payload, session_data["username"])
    except Exception:
        logger.exception("workspace chat user list failed for %s", session_data["username"])
        return JSONResponse({"ok": False, "message": "미안합니다."}, status_code=500)
    return JSONResponse(
        {
            "ok": True,
            "users": users,
            "total_unread": int(unread.get("total_unread", 0) or 0),
            "latest_unread_id": int(unread.get("latest_unread_id", 0) or 0),
            "unread_peers": unread.get("peers", {}),
        },
        headers={"Cache-Control": "no-store"},
    )


@app.get("/api/workspace/chat/unread")
async def workspace_chat_unread(request: Request) -> JSONResponse:
    session_data = await current_session(request)
    if not session_data:
        return JSONResponse({"ok": False, "message": "미안합니다."}, status_code=401)

    try:
        unread = await asyncio.to_thread(workspace_chat_unread_payload, session_data["username"])
    except Exception:
        logger.exception("workspace chat unread summary failed for %s", session_data["username"])
        return JSONResponse({"ok": False, "message": "미안합니다."}, status_code=500)
    return JSONResponse(
        {
            "ok": True,
            "total_unread": int(unread.get("total_unread", 0) or 0),
            "latest_unread_id": int(unread.get("latest_unread_id", 0) or 0),
            "peers": unread.get("peers", {}),
        },
        headers={"Cache-Control": "no-store"},
    )


@app.get("/api/workspace/chat/messages")
async def workspace_chat_messages(request: Request) -> JSONResponse:
    session_data = await current_session(request)
    if not session_data:
        return JSONResponse({"ok": False, "message": "미안합니다."}, status_code=401)

    peer_username = normalize_login_id(request.query_params.get("peer"), settings.mail_domain)
    if not peer_username:
        return JSONResponse({"ok": False, "message": "미안합니다."}, status_code=400)
    if not await asyncio.to_thread(workspace_chat_peer_allowed, session_data["username"], peer_username):
        return JSONResponse({"ok": False, "message": "미안합니다."}, status_code=404)

    before_id = parse_optional_positive_int(request.query_params.get("before_id"))
    after_id = parse_optional_positive_int(request.query_params.get("after_id"))
    limit = parse_optional_positive_int(request.query_params.get("limit")) or CHAT_PAGE_SIZE
    if before_id is not None and after_id is not None:
        return JSONResponse({"ok": False, "message": "미안합니다."}, status_code=400)

    try:
        payload = await asyncio.to_thread(
            fetch_chat_messages,
            CHAT_STORE_FILE,
            session_data["username"],
            peer_username,
            before_id=before_id,
            after_id=after_id,
            limit=limit,
        )
    except Exception:
        logger.exception("workspace chat message list failed for %s -> %s", session_data["username"], peer_username)
        return JSONResponse({"ok": False, "message": "미안합니다."}, status_code=500)

    return JSONResponse(
        {
            "ok": True,
            "peer": peer_username,
            "messages": [chat_message_payload(item, session_data["username"]) for item in payload.get("messages", [])],
            "has_more": bool(payload.get("has_more")),
        },
        headers={"Cache-Control": "no-store"},
    )


@app.post("/api/workspace/chat/read")
async def workspace_chat_read(request: Request) -> JSONResponse:
    session_data = await current_session(request)
    if not session_data:
        return JSONResponse({"ok": False, "message": "미안합니다."}, status_code=401)

    form = await request.form()
    peer_username = normalize_login_id(form.get("peer"), settings.mail_domain)
    if not peer_username:
        return JSONResponse({"ok": False, "message": "미안합니다."}, status_code=400)
    if not await asyncio.to_thread(workspace_chat_peer_allowed, session_data["username"], peer_username):
        return JSONResponse({"ok": False, "message": "미안합니다."}, status_code=404)

    try:
        read = await asyncio.to_thread(mark_chat_peer_read, CHAT_STORE_FILE, session_data["username"], peer_username)
        unread = await asyncio.to_thread(workspace_chat_unread_payload, session_data["username"])
    except Exception:
        logger.exception("workspace chat read marker failed for %s -> %s", session_data["username"], peer_username)
        return JSONResponse({"ok": False, "message": "미안합니다."}, status_code=500)

    return JSONResponse(
        {
            "ok": True,
            "peer": peer_username,
            "last_read_message_id": int(read.get("last_read_message_id", 0) or 0),
            "total_unread": int(unread.get("total_unread", 0) or 0),
            "latest_unread_id": int(unread.get("latest_unread_id", 0) or 0),
            "peers": unread.get("peers", {}),
        },
        headers={"Cache-Control": "no-store"},
    )


@app.post("/api/workspace/chat/messages/send")
async def workspace_chat_send(request: Request) -> JSONResponse:
    session_data = await current_session(request)
    if not session_data:
        return JSONResponse({"ok": False, "message": "미안합니다."}, status_code=401)

    form = await request.form()
    peer_username = normalize_login_id(form.get("peer"), settings.mail_domain)
    message_text = chat_message_text(form.get("body"))
    if not peer_username or not message_text:
        return JSONResponse({"ok": False, "message": "미안합니다."}, status_code=400)
    if not await asyncio.to_thread(workspace_chat_peer_allowed, session_data["username"], peer_username):
        return JSONResponse({"ok": False, "message": "미안합니다."}, status_code=404)

    try:
        item = await asyncio.to_thread(
            append_chat_message,
            CHAT_STORE_FILE,
            session_data["username"],
            peer_username,
            message_text,
        )
    except Exception:
        logger.exception("workspace chat send failed for %s -> %s", session_data["username"], peer_username)
        return JSONResponse({"ok": False, "message": "미안합니다."}, status_code=500)

    return JSONResponse(
        {
            "ok": True,
            "message": "메시지를 보냈습니다.",
            "item": chat_message_payload(item, session_data["username"]),
        },
        headers={"Cache-Control": "no-store"},
    )


@app.post("/api/workspace/chat/messages/screenshot")
async def workspace_chat_send_screenshot(request: Request) -> JSONResponse:
    session_data = await current_session(request)
    if not session_data:
        return JSONResponse({"ok": False, "message": "미안합니다."}, status_code=401)

    form = await request.form()
    peer_username = normalize_login_id(form.get("peer"), settings.mail_domain)
    image = form.get("image")
    if not peer_username or image is None:
        return JSONResponse({"ok": False, "message": "미안합니다."}, status_code=400)
    if not await asyncio.to_thread(workspace_chat_peer_allowed, session_data["username"], peer_username):
        return JSONResponse({"ok": False, "message": "미안합니다."}, status_code=404)

    image_read = getattr(image, "read", None)
    if not callable(image_read):
        return JSONResponse({"ok": False, "message": "미안합니다."}, status_code=400)

    final_path: Path | None = None
    try:
        raw_bytes = await image.read()
        if not raw_bytes or len(raw_bytes) > CHAT_IMAGE_MAX_BYTES:
            return JSONResponse({"ok": False, "message": "미안합니다."}, status_code=400)

        width, height = parse_png_dimensions(raw_bytes)
        media_token = secrets.token_urlsafe(24)
        if not CHAT_MEDIA_TOKEN_RE.fullmatch(media_token):
            raise RuntimeError("generated chat media token failed validation")

        filename = f"workspace-{time.strftime('%Y%m%d-%H%M%S', time.localtime())}.png"
        temp_path = CHAT_MEDIA_ROOT / f".{media_token}.tmp"
        final_path = CHAT_MEDIA_ROOT / f"{media_token}.png"
        temp_path.write_bytes(raw_bytes)
        temp_path.replace(final_path)

        item = await asyncio.to_thread(
            append_chat_media_message,
            CHAT_STORE_FILE,
            session_data["username"],
            peer_username,
            media_token=media_token,
            media_mime="image/png",
            media_filename=filename,
            media_width=width,
            media_height=height,
            media_size=len(raw_bytes),
        )
    except ValueError:
        if final_path is not None:
            final_path.unlink(missing_ok=True)
        return JSONResponse({"ok": False, "message": "미안합니다."}, status_code=400)
    except Exception:
        if final_path is not None:
            final_path.unlink(missing_ok=True)
        logger.exception("workspace chat screenshot send failed for %s -> %s", session_data["username"], peer_username)
        return JSONResponse({"ok": False, "message": "미안합니다."}, status_code=500)
    finally:
        image_close = getattr(image, "close", None)
        if callable(image_close):
            maybe_coro = image_close()
            if asyncio.iscoroutine(maybe_coro):
                await maybe_coro

    return JSONResponse(
        {
            "ok": True,
            "message": "스크린샷을 보냈습니다.",
            "item": chat_message_payload(item, session_data["username"]),
        },
        headers={"Cache-Control": "no-store"},
    )


@app.get("/api/workspace/chat/media/{token}")
async def workspace_chat_media(request: Request, token: str) -> Response:
    session_data = await current_session(request)
    if not session_data:
        return JSONResponse({"ok": False, "message": "미안합니다."}, status_code=401)

    media_token = str(token or "").strip()
    if not CHAT_MEDIA_TOKEN_RE.fullmatch(media_token):
        return JSONResponse({"ok": False, "message": "미안합니다."}, status_code=404)

    item = await asyncio.to_thread(chat_media_record, CHAT_STORE_FILE, media_token)
    if not item or str(item.get("message_type", "") or "") != "image":
        return JSONResponse({"ok": False, "message": "미안합니다."}, status_code=404)

    username = str(session_data["username"] or "").strip().lower()
    sender = str(item.get("sender", "") or "").strip().lower()
    recipient = str(item.get("recipient", "") or "").strip().lower()
    if username not in {sender, recipient}:
        return JSONResponse({"ok": False, "message": "미안합니다."}, status_code=404)

    media_path = CHAT_MEDIA_ROOT / f"{media_token}.png"
    if not media_path.is_file():
        return JSONResponse({"ok": False, "message": "미안합니다."}, status_code=404)

    headers = {"Cache-Control": "no-store"}
    if request.query_params.get("download") in {"1", "true", "yes"}:
        headers["Content-Disposition"] = content_disposition_attachment(
            str(item.get("media_filename", "") or "workspace-screenshot.png")
        )
    return FileResponse(
        media_path,
        media_type=str(item.get("media_mime", "") or "image/png"),
        headers=headers,
    )


@app.get("/api/workspace/processes")
async def workspace_processes(request: Request) -> JSONResponse:
    session_data = await current_session(request)
    if not session_data:
        return JSONResponse({"ok": False, "message": "미안합니다."}, status_code=401)

    try:
        result = await asyncio.to_thread(
            run_desktop_command,
            "process-list",
            session_data["username"],
        )
        payload = json.loads(result.stdout)
    except subprocess.CalledProcessError:
        return JSONResponse({"ok": False, "message": "미안합니다."}, status_code=400)
    except Exception:
        logger.exception("workspace process list failed for %s", session_data["username"])
        return JSONResponse({"ok": False, "message": "미안합니다."}, status_code=500)
    return JSONResponse(payload, headers={"Cache-Control": "no-store"})


@app.post("/api/workspace/processes/kill")
async def workspace_process_kill(request: Request) -> JSONResponse:
    session_data = await current_session(request)
    if not session_data:
        return JSONResponse({"ok": False, "message": "미안합니다."}, status_code=401)

    form = await request.form()
    pid = parse_optional_positive_int(str(form.get("pid", "")))
    if pid is None:
        return JSONResponse({"ok": False, "message": "미안합니다."}, status_code=400)

    try:
        result = await asyncio.to_thread(
            run_desktop_command,
            "process-kill",
            session_data["username"],
            str(pid),
        )
        payload = json.loads(result.stdout)
        payload.setdefault("message", "프로세스를 강제 종료했습니다.")
    except subprocess.CalledProcessError:
        return JSONResponse({"ok": False, "message": "미안합니다."}, status_code=400)
    except Exception:
        logger.exception("workspace process kill failed for %s pid=%s", session_data["username"], pid)
        return JSONResponse({"ok": False, "message": "미안합니다."}, status_code=500)
    return JSONResponse(payload, headers={"Cache-Control": "no-store"})


@app.get("/api/workspace/snapshots")
async def workspace_snapshots(request: Request) -> JSONResponse:
    session_data = await current_session(request)
    if not session_data:
        return JSONResponse({"ok": False, "message": "미안합니다."}, status_code=401)

    try:
        result = await asyncio.to_thread(
            run_desktop_command,
            "snapshot-list",
            session_data["username"],
        )
        payload = json.loads(result.stdout)
    except subprocess.CalledProcessError:
        return JSONResponse({"ok": False, "message": "미안합니다."}, status_code=400)
    except Exception:
        logger.exception("workspace snapshot list failed for %s", session_data["username"])
        return JSONResponse({"ok": False, "message": "미안합니다."}, status_code=500)
    return JSONResponse(payload, headers={"Cache-Control": "no-store"})


@app.post("/api/workspace/snapshots/create")
async def workspace_snapshot_create(request: Request) -> JSONResponse:
    session_data = await current_session(request)
    if not session_data:
        return JSONResponse({"ok": False, "message": "미안합니다."}, status_code=401)

    form = await request.form()
    title = str(form.get("title", "")).strip()
    description = str(form.get("description", "")).strip()

    try:
        result = await asyncio.to_thread(
            run_desktop_command,
            "snapshot-create",
            session_data["username"],
            title,
            description,
        )
        payload = json.loads(result.stdout)
        payload.setdefault("message", "스냅샷을 만들었습니다.")
        payload.setdefault("redirect", "/workspace/prepare")
        await set_session_desktop_state(session_data, session_data["username"])
    except subprocess.CalledProcessError:
        return JSONResponse({"ok": False, "message": "미안합니다."}, status_code=400)
    except Exception:
        logger.exception("workspace snapshot create failed for %s", session_data["username"])
        return JSONResponse({"ok": False, "message": "미안합니다."}, status_code=500)
    return JSONResponse(payload, headers={"Cache-Control": "no-store"})


@app.post("/api/workspace/snapshots/delete")
async def workspace_snapshot_delete(request: Request) -> JSONResponse:
    session_data = await current_session(request)
    if not session_data:
        return JSONResponse({"ok": False, "message": "미안합니다."}, status_code=401)

    form = await request.form()
    snapshot_id = str(form.get("snapshot_id", "")).strip()
    password = str(form.get("password", ""))
    if not snapshot_id:
        return JSONResponse({"ok": False, "message": "미안합니다."}, status_code=400)
    if not await verify_session_password(session_data["username"], password):
        return JSONResponse({"ok": False, "message": "미안합니다."}, status_code=200)

    try:
        result = await asyncio.to_thread(
            run_desktop_command,
            "snapshot-delete",
            session_data["username"],
            snapshot_id,
        )
        payload = json.loads(result.stdout)
        payload.setdefault("message", "스냅샷을 삭제했습니다.")
    except subprocess.CalledProcessError:
        return JSONResponse({"ok": False, "message": "미안합니다."}, status_code=400)
    except Exception:
        logger.exception("workspace snapshot delete failed for %s", session_data["username"])
        return JSONResponse({"ok": False, "message": "미안합니다."}, status_code=500)
    return JSONResponse(payload, headers={"Cache-Control": "no-store"})


@app.post("/api/workspace/snapshots/rollback")
async def workspace_snapshot_rollback(request: Request) -> JSONResponse:
    session_data = await current_session(request)
    if not session_data:
        return JSONResponse({"ok": False, "message": "미안합니다."}, status_code=401)

    form = await request.form()
    snapshot_id = str(form.get("snapshot_id", "")).strip()
    password = str(form.get("password", ""))
    if not snapshot_id:
        return JSONResponse({"ok": False, "message": "미안합니다."}, status_code=400)
    if not await verify_session_password(session_data["username"], password):
        return JSONResponse({"ok": False, "message": "미안합니다."}, status_code=200)

    try:
        result = await asyncio.to_thread(
            run_desktop_command,
            "snapshot-rollback",
            session_data["username"],
            snapshot_id,
        )
        payload = json.loads(result.stdout)
        payload.setdefault("message", "선택한 스냅샷으로 되돌리는 중입니다.")
        payload.setdefault("redirect", "/workspace/prepare")
        await set_session_desktop_state(session_data, session_data["username"])
        try:
            await asyncio.to_thread(
                run_desktop_secret_command,
                "keyring-sync",
                session_data["username"],
                password=password,
                timeout=20,
            )
        except Exception:
            logger.exception("workspace keyring sync failed after rollback for %s", session_data["username"])
    except subprocess.CalledProcessError:
        return JSONResponse({"ok": False, "message": "미안합니다."}, status_code=400)
    except Exception:
        logger.exception("workspace snapshot rollback failed for %s", session_data["username"])
        return JSONResponse({"ok": False, "message": "미안합니다."}, status_code=500)
    return JSONResponse(payload, headers={"Cache-Control": "no-store"})


@app.post("/api/workspace/reset")
async def workspace_reset(request: Request) -> JSONResponse:
    session_data = await current_session(request)
    if not session_data:
        return JSONResponse({"ok": False, "message": "미안합니다."}, status_code=401)

    form = await request.form()
    password = str(form.get("password", ""))
    if not await verify_session_password(session_data["username"], password):
        return JSONResponse({"ok": False, "message": "미안합니다."}, status_code=200)

    try:
        result = await asyncio.to_thread(
            run_desktop_command,
            "reset-workspace",
            session_data["username"],
        )
        payload = json.loads(result.stdout)
        payload.setdefault("message", "작업공간을 초기화하는 중입니다.")
        payload.setdefault("redirect", "/workspace/prepare")
        await set_session_desktop_state(session_data, session_data["username"])
        try:
            await asyncio.to_thread(
                run_desktop_secret_command,
                "keyring-sync",
                session_data["username"],
                password=password,
                timeout=20,
            )
        except Exception:
            logger.exception("workspace keyring sync failed after reset for %s", session_data["username"])
    except subprocess.CalledProcessError:
        return JSONResponse({"ok": False, "message": "미안합니다."}, status_code=400)
    except Exception:
        logger.exception("workspace reset failed for %s", session_data["username"])
        return JSONResponse({"ok": False, "message": "미안합니다."}, status_code=500)
    return JSONResponse(payload, headers={"Cache-Control": "no-store"})


@app.post("/api/workspace/account/password")
async def workspace_account_password_change(request: Request) -> JSONResponse:
    session_data = await current_session(request)
    if not session_data:
        return JSONResponse({"ok": False, "message": "미안합니다."}, status_code=401)

    form = await request.form()
    current_password = str(form.get("current_password", ""))
    new_password = str(form.get("new_password", ""))
    confirm_password = str(form.get("confirm_password", ""))
    if not current_password or not new_password or not confirm_password:
        return JSONResponse({"ok": False, "message": "모든 항목을 입력하십시오."}, status_code=400)
    if new_password != confirm_password:
        return JSONResponse({"ok": False, "message": "새 비밀번호 확인이 일치하지 않습니다."}, status_code=400)
    if current_password == new_password:
        return JSONResponse({"ok": False, "message": "새 비밀번호를 현재 비밀번호와 다르게 입력하십시오."}, status_code=400)
    if not await verify_session_password(session_data["username"], current_password):
        return JSONResponse({"ok": False, "message": "현재 비밀번호가 올바르지 않습니다."}, status_code=200)

    changed = await asyncio.to_thread(
        ldap_change_password,
        settings,
        session_data["username"],
        current_password,
        new_password,
    )
    if not changed:
        return JSONResponse({"ok": False, "message": "비밀번호를 변경하지 못했습니다."}, status_code=400)

    try:
        await asyncio.to_thread(
            run_desktop_secret_command,
            "keyring-sync",
            session_data["username"],
            password=new_password,
            timeout=20,
        )
    except Exception:
        logger.exception("workspace keyring sync failed after password change for %s", session_data["username"])

    return JSONResponse(
        {
            "ok": True,
            "message": "비밀번호를 변경했습니다.",
        },
        headers={"Cache-Control": "no-store"},
    )


@app.get("/api/workspace/account/email")
async def workspace_account_email(request: Request) -> JSONResponse:
    session_data = await current_session(request)
    if not session_data:
        return JSONResponse({"ok": False, "message": "미안합니다."}, status_code=401)

    payload = await external_email_payload(session_data["username"])
    return JSONResponse(payload, headers={"Cache-Control": "no-store"})


@app.post("/api/workspace/account/email/request")
async def workspace_account_email_request(request: Request) -> JSONResponse:
    session_data = await current_session(request)
    if not session_data:
        return JSONResponse({"ok": False, "message": "미안합니다."}, status_code=401)

    form = await request.form()
    mode = str(form.get("mode", "")).strip().lower()
    candidate_raw = str(form.get("email", ""))
    current_password = str(form.get("current_password", ""))
    if mode not in {"register", "change"}:
        return JSONResponse({"ok": False, "message": "미안합니다."}, status_code=400)

    try:
        candidate_email = normalize_external_email(candidate_raw, settings.mail_domain)
    except Exception as exc:
        return JSONResponse({"ok": False, "message": str(exc)}, status_code=400)

    current_email = await current_registered_external_email(session_data["username"])
    if mode == "register" and current_email:
        return JSONResponse(
            {"ok": False, "message": "이미 등록된 외부 이메일이 있습니다. 이메일 변경을 사용하십시오."},
            status_code=400,
        )
    if mode == "change" and not current_email:
        return JSONResponse({"ok": False, "message": "등록된 외부 이메일이 없습니다."}, status_code=400)
    if current_email and candidate_email == current_email:
        return JSONResponse({"ok": False, "message": "현재 등록된 이메일과 다른 주소를 입력하십시오."}, status_code=400)
    if mode == "change" and not await verify_session_password(session_data["username"], current_password):
        return JSONResponse({"ok": False, "message": "현재 LDAP 비밀번호가 올바르지 않습니다."}, status_code=200)

    existing_owner = await asyncio.to_thread(
        email_owner,
        settings.external_email_store_file,
        candidate_email,
    )
    if existing_owner and existing_owner != session_data["username"]:
        return JSONResponse({"ok": False, "message": "이미 다른 계정에 등록된 이메일입니다."}, status_code=400)

    pending_owner = await app.state.redis.get(external_email_pending_email_key(candidate_email))
    if pending_owner and pending_owner != session_data["username"]:
        return JSONResponse({"ok": False, "message": "다른 계정에서 인증 중인 이메일입니다."}, status_code=400)

    await clear_pending_external_email(session_data["username"])

    verification_code = generate_external_email_code()
    sender_email = account_mail_address(session_data["username"], settings)
    pending_key = external_email_pending_key(session_data["username"])
    pending_email_key = external_email_pending_email_key(candidate_email)
    ttl_seconds = settings.external_email_verification_ttl_seconds
    requested_at = str(int(time.time()))

    await app.state.redis.hset(
        pending_key,
        mapping={
            "email": candidate_email,
            "code": verification_code,
            "mode": mode,
            "requested_at": requested_at,
            "sender_email": sender_email,
        },
    )
    await app.state.redis.expire(pending_key, ttl_seconds)
    await app.state.redis.set(pending_email_key, session_data["username"], ex=ttl_seconds)

    try:
        await asyncio.to_thread(
            send_external_email_verification_message,
            sender_email=sender_email,
            target_email=candidate_email,
            code=verification_code,
            ttl_seconds=ttl_seconds,
        )
    except subprocess.CalledProcessError:
        await clear_pending_external_email(session_data["username"])
        logger.exception("external email verification send failed for %s", session_data["username"])
        return JSONResponse({"ok": False, "message": "인증 메일을 보내지 못했습니다."}, status_code=500)
    except Exception:
        await clear_pending_external_email(session_data["username"])
        logger.exception("external email verification request failed for %s", session_data["username"])
        return JSONResponse({"ok": False, "message": "인증 메일을 보내지 못했습니다."}, status_code=500)

    return JSONResponse(
        {
            "ok": True,
            "message": "인증 메일을 보냈습니다.",
            "masked_email": mask_email(candidate_email),
            "expires_in_seconds": ttl_seconds,
            "mode": mode,
        },
        headers={"Cache-Control": "no-store"},
    )


@app.post("/api/workspace/account/email/verify")
async def workspace_account_email_verify(request: Request) -> JSONResponse:
    session_data = await current_session(request)
    if not session_data:
        return JSONResponse({"ok": False, "message": "미안합니다."}, status_code=401)

    form = await request.form()
    code = re.sub(r"\s+", "", str(form.get("code", "")))
    if not code:
        return JSONResponse({"ok": False, "message": "인증 번호를 입력하십시오."}, status_code=400)
    if not re.fullmatch(rf"\d{{{EXTERNAL_EMAIL_CODE_DIGITS}}}", code):
        return JSONResponse({"ok": False, "message": "인증 번호는 6자리 숫자여야 합니다."}, status_code=400)

    pending_key = external_email_pending_key(session_data["username"])
    pending = await app.state.redis.hgetall(pending_key)
    pending_email = str(pending.get("email", "")).strip().lower()
    pending_code = str(pending.get("code", "")).strip()
    if not pending_email or not pending_code:
        return JSONResponse({"ok": False, "message": "진행 중인 이메일 인증이 없습니다."}, status_code=400)
    if not secrets.compare_digest(code, pending_code):
        return JSONResponse({"ok": False, "message": "인증 번호가 올바르지 않습니다."}, status_code=200)

    try:
        record = await asyncio.to_thread(
            set_registered_email,
            settings.external_email_store_file,
            session_data["username"],
            pending_email,
        )
    except DuplicateExternalEmailError as exc:
        await clear_pending_external_email(session_data["username"])
        return JSONResponse({"ok": False, "message": str(exc)}, status_code=400)
    except Exception:
        logger.exception("external email verify failed for %s", session_data["username"])
        return JSONResponse({"ok": False, "message": "외부 이메일을 등록하지 못했습니다."}, status_code=500)

    await clear_pending_external_email(session_data["username"])
    payload = await external_email_payload(session_data["username"])
    payload.update(
        {
            "message": "외부 이메일을 등록했습니다.",
            "registered_email": record.email,
        }
    )
    return JSONResponse(payload, headers={"Cache-Control": "no-store"})


@app.get("/api/files/list")
async def files_list(request: Request, path: str = "") -> JSONResponse:
    session_data = await current_session(request)
    if not session_data:
        return JSONResponse({"ok": False, "message": "미안합니다."}, status_code=401)

    try:
        result = await asyncio.to_thread(
            run_desktop_command,
            "file-list",
            session_data["username"],
            path,
        )
        payload = json.loads(result.stdout)
    except subprocess.CalledProcessError:
        return JSONResponse({"ok": False, "message": "미안합니다."}, status_code=404)
    except Exception:
        logger.exception("file list failed for %s", session_data["username"])
        return JSONResponse({"ok": False, "message": "미안합니다."}, status_code=500)
    return JSONResponse(payload, headers={"Cache-Control": "no-store"})


@app.post("/api/files/upload")
async def files_upload(request: Request) -> JSONResponse:
    session_data = await current_session(request)
    if not session_data:
        return JSONResponse({"ok": False, "message": "미안합니다."}, status_code=401)

    form = await request.form()
    requested_path = str(form.get("path", ""))
    files = [item for item in form.getlist("files") if hasattr(item, "filename")]
    if not files:
        return JSONResponse({"ok": False, "message": "미안합니다."}, status_code=400)

    temp_dir = Path(tempfile.mkdtemp(prefix="workstation-files-upload-", dir="/tmp"))
    temp_paths: list[Path] = []
    try:
        for index, upload in enumerate(files):
            filename = sanitize_upload_name(getattr(upload, "filename", "") or f"upload-{index}.bin")
            destination = temp_dir / filename
            await write_upload_to_path(upload, destination)
            temp_paths.append(destination)

        result = await asyncio.to_thread(
            run_desktop_command,
            "file-upload",
            session_data["username"],
            requested_path,
            *[str(path) for path in temp_paths],
        )
        payload = json.loads(result.stdout)
    except subprocess.CalledProcessError:
        return JSONResponse({"ok": False, "message": "미안합니다."}, status_code=400)
    except Exception:
        logger.exception("file upload failed for %s", session_data["username"])
        return JSONResponse({"ok": False, "message": "미안합니다."}, status_code=500)
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

    return JSONResponse(payload, headers={"Cache-Control": "no-store"})


@app.get("/api/files/download")
async def files_download(request: Request, path: str = "") -> Response:
    session_data = await current_session(request)
    if not session_data:
        return JSONResponse({"ok": False, "message": "미안합니다."}, status_code=401)

    try:
        result = await asyncio.to_thread(
            run_desktop_command,
            "file-export",
            session_data["username"],
            path,
        )
        payload = json.loads(result.stdout)
    except subprocess.CalledProcessError:
        return JSONResponse({"ok": False, "message": "미안합니다."}, status_code=404)
    except Exception:
        logger.exception("file export failed for %s", session_data["username"])
        return JSONResponse({"ok": False, "message": "미안합니다."}, status_code=500)

    return FileResponse(
        payload["path"],
        filename=payload["filename"],
        media_type=payload.get("media_type") or "application/octet-stream",
        background=BackgroundTask(lambda: shutil.rmtree(str(Path(payload["path"]).parent), ignore_errors=True)),
        headers={
            "Cache-Control": "no-store",
            "Content-Disposition": content_disposition_attachment(payload["filename"]),
        },
    )


@app.post("/api/clipboard/upload")
async def clipboard_upload(request: Request) -> JSONResponse:
    session_data = await current_session(request)
    if not session_data:
        return JSONResponse({"ok": False, "message": "미안합니다."}, status_code=401)

    backend = await cached_desktop_backend(session_data)
    if not backend:
        return JSONResponse({"ok": False, "message": "미안합니다."}, status_code=409)

    form = await request.form()
    files = [item for item in form.values() if hasattr(item, "filename")]
    if not files:
        return JSONResponse({"ok": False, "message": "미안합니다."}, status_code=400)

    temp_dir = Path(tempfile.mkdtemp(prefix="workstation-clipboard-", dir="/tmp"))
    temp_paths: list[Path] = []
    try:
        for index, upload in enumerate(files):
            filename = Path(getattr(upload, "filename", "") or f"clipboard-{index}").name
            target = temp_dir / (filename or f"clipboard-{index}")
            await write_upload_to_path(upload, target)
            temp_paths.append(target)

        result = await asyncio.to_thread(
            run_desktop_command,
            "clipboard-import",
            session_data["username"],
            *[str(path) for path in temp_paths],
        )
        payload = json.loads(result.stdout)
        return JSONResponse(payload, status_code=200)
    except Exception:
        logger.exception("clipboard upload failed for %s", session_data["username"])
        return JSONResponse({"ok": False, "message": "미안합니다."}, status_code=500)
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


@app.post("/api/clipboard/image-paste")
async def clipboard_image_paste(request: Request) -> JSONResponse:
    session_data = await current_session(request)
    if not session_data:
        return JSONResponse({"ok": False, "message": "미안합니다."}, status_code=401)

    backend = await cached_desktop_backend(session_data)
    if not backend:
        return JSONResponse({"ok": False, "message": "미안합니다."}, status_code=409)

    form = await request.form()
    image = next((item for item in form.values() if hasattr(item, "filename")), None)
    if image is None:
        return JSONResponse({"ok": False, "message": "미안합니다."}, status_code=400)

    temp_dir = Path(tempfile.mkdtemp(prefix="workstation-clipboard-image-", dir="/tmp"))
    image_path = temp_dir / "clipboard-image.png"
    try:
        await write_upload_to_path(image, image_path)
        data = image_path.read_bytes()
        if not data.startswith(b"\x89PNG\r\n\x1a\n"):
            return JSONResponse({"ok": False, "message": "미안합니다."}, status_code=400)

        await asyncio.to_thread(
            run_desktop_command,
            "clipboard-set-image",
            session_data["username"],
            str(image_path),
            timeout=15,
        )
        await asyncio.to_thread(
            run_desktop_command,
            "clipboard-paste",
            session_data["username"],
            timeout=10,
        )

        token = clipboard_entry_token(session_data["username"], "image", data)
        clipboard_cache_put(
            token,
            {
                "username": session_data["username"],
                "kind": "image",
                "mime": "image/png",
                "data": data,
            },
        )
        app.state.clipboard_last[session_data["session_id"]] = token
        return JSONResponse(
            {
                "ok": True,
                "kind": "image",
                "mime": "image/png",
                "token": token,
                "message": "Image pasted into the workspace clipboard.",
            },
            status_code=200,
            headers={"Cache-Control": "no-store"},
        )
    except subprocess.CalledProcessError:
        return JSONResponse({"ok": False, "message": "미안합니다."}, status_code=400)
    except subprocess.TimeoutExpired:
        logger.warning("clipboard image paste timed out for %s", session_data["username"])
        return JSONResponse({"ok": False, "message": "미안합니다."}, status_code=504)
    except Exception:
        logger.exception("clipboard image paste failed for %s", session_data["username"])
        return JSONResponse({"ok": False, "message": "미안합니다."}, status_code=500)
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


@app.get("/api/clipboard/poll")
async def clipboard_poll(request: Request) -> JSONResponse:
    session_data = await current_session(request)
    if not session_data:
        return JSONResponse({"ok": False, "message": "미안합니다."}, status_code=401)

    backend = await cached_desktop_backend(session_data)
    if not backend:
        return JSONResponse({"ok": True, "changed": False, "kind": "none"}, headers={"Cache-Control": "no-store"})

    payload = await asyncio.to_thread(
        snapshot_rich_clipboard,
        session_data["username"],
        session_data.get("desktop_home") or f"/home/{session_data['username']}",
        session_data["session_id"],
    )
    return JSONResponse(payload, headers={"Cache-Control": "no-store"})


@app.get("/api/clipboard/item/{token}")
async def clipboard_item(request: Request, token: str) -> Response:
    session_data = await current_session(request)
    if not session_data:
        return JSONResponse({"ok": False, "message": "미안합니다."}, status_code=401)
    entry = clipboard_cache_get(token, session_data["username"])
    if not entry or entry.get("kind") != "image":
        return JSONResponse({"ok": False, "message": "미안합니다."}, status_code=404)
    return Response(
        content=entry["data"],
        media_type=entry.get("mime", "image/png"),
        headers={"Cache-Control": "no-store"},
    )


@app.get("/api/clipboard/file/{token}/{index}")
async def clipboard_file(request: Request, token: str, index: int) -> Response:
    session_data = await current_session(request)
    if not session_data:
        return JSONResponse({"ok": False, "message": "미안합니다."}, status_code=401)
    entry = clipboard_cache_get(token, session_data["username"])
    if not entry or entry.get("kind") != "files":
        return JSONResponse({"ok": False, "message": "미안합니다."}, status_code=404)
    paths = entry.get("paths") or []
    if index < 0 or index >= len(paths):
        return JSONResponse({"ok": False, "message": "미안합니다."}, status_code=404)
    path = paths[index]
    return FileResponse(
        path,
        filename=path.name,
        headers={"Cache-Control": "no-store"},
    )


@app.api_route("/workspace/{path:path}", methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
async def workspace_http_proxy(request: Request, path: str = "") -> Response:
    session_data = await current_session(request)
    if not session_data:
        return RedirectResponse("/", status_code=303)

    backend = await cached_desktop_backend(session_data)
    if not backend:
        await schedule_desktop_backend(session_data)
        return RedirectResponse("/workspace/prepare", status_code=303)
    target = workspace_target(backend["port"], path, request.url.query)
    body = await request.body()

    try:
        async with httpx.AsyncClient(timeout=90, follow_redirects=False) as client:
            upstream = await client.request(
                request.method,
                target,
                headers=forwarded_request_headers(request),
                content=body,
            )
    except httpx.ConnectError:
        await schedule_desktop_backend(session_data)
        return RedirectResponse("/workspace/prepare", status_code=303)

    response_content = b"" if request.method == "HEAD" else inject_workspace_overrides(upstream.content, upstream.headers)

    return Response(
        content=response_content,
        status_code=upstream.status_code,
        headers=forwarded_response_headers(upstream.headers),
    )


@app.websocket("/api/workspace-terminal-ws")
async def workspace_terminal_websocket(websocket: WebSocket) -> None:
    session_data = await current_websocket_session(websocket)
    if not session_data:
        details = await websocket_session_diagnostics(websocket)
        logger.warning("workspace terminal websocket rejected: %s", json.dumps(details, sort_keys=True))
        await websocket.close(code=4403)
        return

    process: subprocess.Popen[bytes] | None = None
    master_fd: int | None = None
    input_task: asyncio.Task[None] | None = None
    output_task: asyncio.Task[None] | None = None
    wait_task: asyncio.Task[int] | None = None

    try:
        await ensure_desktop_backend(session_data)
        process, master_fd = await asyncio.to_thread(
            spawn_terminal_process,
            session_data["username"],
            TERMINAL_DEFAULT_COLS,
            TERMINAL_DEFAULT_ROWS,
        )
        await websocket.accept()

        async def input_loop() -> None:
            assert process is not None
            assert master_fd is not None
            while True:
                try:
                    message = await websocket.receive()
                except WebSocketDisconnect:
                    return
                if message["type"] == "websocket.disconnect":
                    return
                raw_text = message.get("text")
                if raw_text is None:
                    continue
                try:
                    payload = json.loads(raw_text)
                except json.JSONDecodeError:
                    continue
                if not isinstance(payload, dict):
                    continue
                action = str(payload.get("type") or "")
                if action == "input":
                    data = payload.get("data")
                    if not isinstance(data, str) or not data:
                        continue
                    try:
                        os.write(master_fd, data.encode("utf-8", errors="ignore"))
                    except OSError:
                        return
                    continue
                if action == "resize":
                    cols = coerce_terminal_size(payload.get("cols"), TERMINAL_DEFAULT_COLS, 10, 500)
                    rows = coerce_terminal_size(payload.get("rows"), TERMINAL_DEFAULT_ROWS, 2, 500)
                    await asyncio.to_thread(set_pty_size, master_fd, cols, rows)
                    signal_process_group(process.pid, signal.SIGWINCH)

        async def output_loop() -> None:
            assert master_fd is not None
            while True:
                chunk = await wait_for_pty_chunk(master_fd)
                if not chunk:
                    return
                await websocket.send_bytes(chunk)

        input_task = asyncio.create_task(input_loop())
        output_task = asyncio.create_task(output_loop())
        wait_task = asyncio.create_task(asyncio.to_thread(process.wait))
        done, pending = await asyncio.wait(
            {input_task, output_task, wait_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()
        for task in done:
            with contextlib.suppress(asyncio.CancelledError, WebSocketDisconnect):
                await task
    except Exception:
        logger.exception("workspace terminal websocket failed for %s", session_data.get("username", "unknown"))
    finally:
        for task in (input_task, output_task, wait_task):
            if not task:
                continue
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, WebSocketDisconnect):
                await task

        if process and process.poll() is None:
            signal_process_group(process.pid, signal.SIGHUP)
            try:
                await asyncio.to_thread(process.wait, 2)
            except subprocess.TimeoutExpired:
                signal_process_group(process.pid, signal.SIGTERM)
                try:
                    await asyncio.to_thread(process.wait, 2)
                except subprocess.TimeoutExpired:
                    signal_process_group(process.pid, signal.SIGKILL)
                    with contextlib.suppress(subprocess.TimeoutExpired):
                        await asyncio.to_thread(process.wait, 2)

        if master_fd is not None:
            with contextlib.suppress(OSError):
                os.close(master_fd)

        if websocket.client_state.name == "CONNECTED":
            with contextlib.suppress(Exception):
                await websocket.close(code=1000)


@app.websocket("/api/workspace-audio-ws")
async def workspace_audio_websocket(websocket: WebSocket) -> None:
    session_data = await current_websocket_session(websocket)
    if not session_data:
        details = await websocket_session_diagnostics(websocket)
        logger.warning("workspace audio websocket rejected: %s", json.dumps(details, sort_keys=True))
        await websocket.close(code=4403)
        return

    process: asyncio.subprocess.Process | None = None
    stderr_task: asyncio.Task[None] | None = None
    receive_task: asyncio.Task[None] | None = None

    try:
        await ensure_desktop_backend(session_data)
        metadata = await asyncio.to_thread(run_audio_metadata, session_data["username"])
        process = await asyncio.create_subprocess_exec(
            "sudo",
            "-n",
            settings.desktop_helper_path,
            "audio-stream",
            session_data["username"],
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stderr_task = asyncio.create_task(
            drain_subprocess_logs(process.stderr, f"workspace audio stderr [{session_data['username']}]")
        )

        await websocket.accept()
        await websocket.send_text(
            json.dumps(
                {
                    "type": "config",
                    "source": metadata["source"],
                    "format": metadata["format"],
                    "channels": metadata["channels"],
                    "sampleRate": metadata["sample_rate"],
                }
            )
        )

        async def receive_loop() -> None:
            while True:
                message = await websocket.receive()
                if message["type"] == "websocket.disconnect":
                    return

        receive_task = asyncio.create_task(receive_loop())

        assert process.stdout is not None
        while True:
            chunk = await process.stdout.read(8192)
            if not chunk:
                break
            await websocket.send_bytes(chunk)
    except Exception:
        logger.exception("workspace audio websocket failed for %s", session_data.get("username", "unknown"))
    finally:
        if receive_task:
            receive_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await receive_task

        if process and process.returncode is None:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=2)
            except asyncio.TimeoutError:
                process.kill()
                with contextlib.suppress(asyncio.TimeoutError):
                    await asyncio.wait_for(process.wait(), timeout=2)

        if stderr_task:
            stderr_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await stderr_task

        if websocket.client_state.name == "CONNECTED":
            with contextlib.suppress(Exception):
                await websocket.close(code=1000)


async def proxy_workspace_websocket(websocket: WebSocket, path: str = "") -> None:
    session_data = await current_websocket_session(websocket)
    if not session_data:
        details = await websocket_session_diagnostics(websocket)
        logger.warning("workspace websocket rejected: %s", json.dumps(details, sort_keys=True))
        await websocket.close(code=4403)
        return

    backend = await ensure_desktop_backend(session_data)
    target = websocket_target(backend["port"], path, websocket.url.query)
    requested_subprotocols = list(websocket.scope.get("subprotocols") or [])

    try:
        async with websockets.connect(
            target,
            extra_headers={
                "Authorization": desktop_proxy_authorization(),
                "X-Real-IP": websocket_client_ip(websocket),
                "X-Forwarded-Proto": "https",
                "Origin": websocket.headers.get("origin", settings.public_base_url.rstrip("/")),
                "User-Agent": websocket.headers.get("user-agent", ""),
            },
            subprotocols=requested_subprotocols or None,
            max_size=None,
            ping_interval=None,
            ping_timeout=None,
            close_timeout=5,
        ) as upstream:
            await websocket.accept(subprotocol=upstream.subprotocol)

            async def client_to_upstream() -> None:
                while True:
                    message = await websocket.receive()
                    if message["type"] == "websocket.disconnect":
                        await upstream.close()
                        return
                    if message.get("bytes") is not None:
                        await upstream.send(message["bytes"])
                    elif message.get("text") is not None:
                        await upstream.send(message["text"])

            async def upstream_to_client() -> None:
                async for message in upstream:
                    if isinstance(message, bytes):
                        await websocket.send_bytes(message)
                    else:
                        await websocket.send_text(message)

            await asyncio.gather(client_to_upstream(), upstream_to_client())
    except Exception:
        if websocket.client_state.name == "CONNECTED":
            await websocket.close(code=1011)


@app.websocket("/workspace/{path:path}")
async def workspace_websocket_proxy(websocket: WebSocket, path: str = "") -> None:
    await proxy_workspace_websocket(websocket, path)


@app.websocket("/websockify")
async def root_websockify_proxy(websocket: WebSocket) -> None:
    await proxy_workspace_websocket(websocket, "websockify")


@app.get("/healthz", response_class=PlainTextResponse)
async def healthz() -> str:
    return "ok"
