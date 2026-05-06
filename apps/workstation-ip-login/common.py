from __future__ import annotations

import ipaddress
import os
import re
import ssl
from dataclasses import dataclass
from typing import Optional

import redis.asyncio as redis
from ldap3 import Connection, Server, Tls


@dataclass(frozen=True)
class Settings:
    product_title: str
    public_base_url: str
    redis_url: str
    mail_domain: str
    sendmail_path: str
    ldap_host: str
    ldap_port: int
    ldap_base_dn: str
    ldap_people_dn: str
    ldap_ca_cert_file: str
    external_email_store_file: str
    external_email_verification_ttl_seconds: int
    grant_ttl_seconds: int
    session_ttl_seconds: int
    grant_record_ttl_seconds: int
    session_cookie_name: str
    discord_guild_id: int
    discord_channel_id: int
    discord_role_id: int
    discord_token_file: str
    desktop_helper_path: str
    desktop_backend_host: str
    desktop_proxy_user: str
    desktop_proxy_password: str


USER_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


def load_settings() -> Settings:
    public_domain = os.environ.get(
        "WORKSTATION_PUBLIC_DOMAIN",
        os.environ.get("WORKSTATION_IPLOGIN_MAIL_DOMAIN", "example.com"),
    ).strip() or "example.com"
    public_base_url = os.environ.get(
        "WORKSTATION_PUBLIC_BASE_URL",
        f"https://{public_domain}",
    ).strip().rstrip("/") or f"https://{public_domain}"
    ldap_base_dn = os.environ.get("WORKSTATION_IPLOGIN_LDAP_BASE_DN", "dc=example,dc=com")
    return Settings(
        product_title=os.environ.get("WORKSTATION_PRODUCT_TITLE", "korean-linux-web-workstation"),
        public_base_url=public_base_url,
        redis_url=os.environ.get("WORKSTATION_IPLOGIN_REDIS_URL", "redis://127.0.0.1:6379/3"),
        mail_domain=os.environ.get("WORKSTATION_IPLOGIN_MAIL_DOMAIN", public_domain),
        sendmail_path=os.environ.get("WORKSTATION_IPLOGIN_SENDMAIL_PATH", "/usr/sbin/sendmail"),
        ldap_host=os.environ.get("WORKSTATION_IPLOGIN_LDAP_HOST", public_domain),
        ldap_port=int(os.environ.get("WORKSTATION_IPLOGIN_LDAP_PORT", "636")),
        ldap_base_dn=ldap_base_dn,
        ldap_people_dn=os.environ.get(
            "WORKSTATION_IPLOGIN_LDAP_PEOPLE_DN",
            f"ou=people,{ldap_base_dn}",
        ),
        ldap_ca_cert_file=os.environ.get(
            "WORKSTATION_IPLOGIN_LDAP_CA_CERT_FILE",
            "/etc/ssl/certs/ca-certificates.crt",
        ),
        external_email_store_file=os.environ.get(
            "WORKSTATION_IPLOGIN_EXTERNAL_EMAIL_STORE_FILE",
            "/var/lib/workstation-state/workstation-ip-login/external-email-store.json",
        ),
        external_email_verification_ttl_seconds=int(
            os.environ.get("WORKSTATION_IPLOGIN_EXTERNAL_EMAIL_VERIFICATION_TTL_SECONDS", "600")
        ),
        grant_ttl_seconds=int(os.environ.get("WORKSTATION_IPLOGIN_GRANT_TTL_SECONDS", "180")),
        session_ttl_seconds=int(os.environ.get("WORKSTATION_IPLOGIN_SESSION_TTL_SECONDS", "28800")),
        grant_record_ttl_seconds=int(
            os.environ.get("WORKSTATION_IPLOGIN_GRANT_RECORD_TTL_SECONDS", "86400")
        ),
        session_cookie_name=os.environ.get(
            "WORKSTATION_IPLOGIN_SESSION_COOKIE_NAME",
            "workstation_iplogin_session",
        ),
        discord_guild_id=int(os.environ["WORKSTATION_IPLOGIN_DISCORD_GUILD_ID"]),
        discord_channel_id=int(os.environ["WORKSTATION_IPLOGIN_DISCORD_CHANNEL_ID"]),
        discord_role_id=int(os.environ["WORKSTATION_IPLOGIN_DISCORD_ROLE_ID"]),
        discord_token_file=os.environ["WORKSTATION_IPLOGIN_DISCORD_TOKEN_FILE"],
        desktop_helper_path=os.environ.get(
            "WORKSTATION_IPLOGIN_DESKTOP_HELPER",
            "/usr/local/sbin/workstation-desktop-session",
        ),
        desktop_backend_host=os.environ.get("WORKSTATION_IPLOGIN_DESKTOP_BACKEND_HOST", "127.0.0.1"),
        desktop_proxy_user=os.environ["WORKSTATION_IPLOGIN_DESKTOP_PROXY_USER"],
        desktop_proxy_password=os.environ["WORKSTATION_IPLOGIN_DESKTOP_PROXY_PASSWORD"],
    )


def create_redis(settings: Settings) -> redis.Redis:
    return redis.from_url(settings.redis_url, decode_responses=True)


def normalize_ip(value: str | None) -> Optional[str]:
    if not value:
        return None
    candidate = value.strip()
    if "," in candidate:
        candidate = candidate.split(",", 1)[0].strip()
    try:
        return ipaddress.ip_address(candidate).compressed
    except ValueError:
        return None


def normalize_login_id(value: str | None, mail_domain: str) -> Optional[str]:
    if not value:
        return None
    candidate = value.strip().lower()
    if candidate.endswith(f"@{mail_domain}"):
        candidate = candidate[: -(len(mail_domain) + 1)]
    if not USER_RE.fullmatch(candidate):
        return None
    return candidate


def user_dn(username: str, settings: Settings) -> str:
    return f"uid={username},{settings.ldap_people_dn}"


def account_mail_address(username: str, settings: Settings) -> str:
    return f"{username}@{settings.mail_domain}"


def ldap_server(settings: Settings) -> Server:
    tls = Tls(
        ca_certs_file=settings.ldap_ca_cert_file,
        validate=ssl.CERT_REQUIRED,
        version=ssl.PROTOCOL_TLS_CLIENT,
    )
    return Server(
        settings.ldap_host,
        port=settings.ldap_port,
        use_ssl=True,
        tls=tls,
        connect_timeout=5,
    )


def ldap_authenticate(settings: Settings, login_id: str | None, password: str | None) -> Optional[str]:
    username = normalize_login_id(login_id, settings.mail_domain)
    if not username or not password:
        return None

    conn = None
    try:
        conn = Connection(ldap_server(settings), user=user_dn(username, settings), password=password, auto_bind=True)
        return username
    except Exception:
        return None
    finally:
        if conn is not None:
            try:
                conn.unbind()
            except Exception:
                pass


def ldap_change_password(
    settings: Settings,
    login_id: str | None,
    current_password: str | None,
    new_password: str | None,
) -> bool:
    username = normalize_login_id(login_id, settings.mail_domain)
    if not username or not current_password or not new_password:
        return False

    target_dn = user_dn(username, settings)
    conn = None
    try:
        conn = Connection(ldap_server(settings), user=target_dn, password=current_password, auto_bind=True)
        return bool(
            conn.extend.standard.modify_password(
                user=target_dn,
                old_password=current_password,
                new_password=new_password,
            )
        )
    except Exception:
        return False
    finally:
        if conn is not None:
            try:
                conn.unbind()
            except Exception:
                pass


def allow_key(ip_text: str) -> str:
    return f"workstation:iplogin:allow:{ip_text}"


def grant_key(ip_text: str) -> str:
    return f"workstation:iplogin:grant:{ip_text}"


def grant_set_key() -> str:
    return "workstation:iplogin:grants"


def session_key(session_id: str) -> str:
    return f"workstation:iplogin:session:{session_id}"


def requester_label(raw_label: str | None) -> str:
    label = (raw_label or "unknown").replace("\n", " ").replace("\r", " ").strip()
    return label[:120] if label else "unknown"


def active_status_message(ip_text: str, requester_mention: str, requester_name: str, expires_at: int) -> str:
    return "\n".join(
        [
            "Temporary login allowed.",
            f"IP: `{ip_text}`",
            f"Requester: {requester_mention} ({requester_label(requester_name)})",
            f"Countdown: <t:{expires_at}:R>",
            f"Expires: <t:{expires_at}:F>",
        ]
    )


def expired_status_message(ip_text: str, requester_mention: str, requester_name: str, expires_at: int) -> str:
    return "\n".join(
        [
            "Expired.",
            f"IP: `{ip_text}`",
            f"Requester: {requester_mention} ({requester_label(requester_name)})",
            f"Expired: <t:{expires_at}:F>",
        ]
    )
