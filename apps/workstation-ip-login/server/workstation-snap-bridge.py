#!/usr/bin/env python3
import json
import os
import selectors
import signal
import socket
import subprocess
import sys
import threading
from pathlib import Path


SOCKET_PATH = Path(os.environ["WORKSTATION_SNAP_BRIDGE_SOCKET"])
LAUNCHERS_DIR = Path(os.environ["WORKSTATION_SNAP_LAUNCHERS_DIR"])
USERNAME = os.environ["WORKSTATION_SNAP_USERNAME"]
USER_HOME = os.environ["WORKSTATION_SNAP_HOME"]
DISPLAY = os.environ["WORKSTATION_SNAP_DISPLAY"]
XAUTHORITY = os.environ["WORKSTATION_SNAP_XAUTHORITY"]
XDG_RUNTIME_DIR = os.environ["WORKSTATION_SNAP_XDG_RUNTIME_DIR"]
PULSE_SERVER = os.environ.get("WORKSTATION_SNAP_PULSE_SERVER", "")
DBUS_SESSION_BUS_ADDRESS = os.environ.get("WORKSTATION_SNAP_DBUS_SESSION_BUS_ADDRESS", f"unix:path={XDG_RUNTIME_DIR}/bus")
TIMEZONE = os.environ.get("WORKSTATION_SNAP_TZ", os.environ.get("TZ", "Asia/Seoul"))
GTK_IM_MODULE = os.environ.get("WORKSTATION_SNAP_GTK_IM_MODULE", "ibus")
QT_IM_MODULE = os.environ.get("WORKSTATION_SNAP_QT_IM_MODULE", "ibus")
XMODIFIERS = os.environ.get("WORKSTATION_SNAP_XMODIFIERS", "@im=ibus")
SDL_IM_MODULE = os.environ.get("WORKSTATION_SNAP_SDL_IM_MODULE", "ibus")
GLFW_IM_MODULE = os.environ.get("WORKSTATION_SNAP_GLFW_IM_MODULE", "ibus")
CLUTTER_IM_MODULE = os.environ.get("WORKSTATION_SNAP_CLUTTER_IM_MODULE", "ibus")
LANG = os.environ.get("LANG", "ko_KR.UTF-8")
LANGUAGE = os.environ.get("LANGUAGE", "ko_KR:ko:en_US:en")
LC_ALL = os.environ.get("LC_ALL", "ko_KR.UTF-8")
PATH_VALUE = os.environ.get("PATH", "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:/snap/bin")
THUNDERBIRD_COMMANDS = {"thunderbird"}
THUNDERBIRD_PROFILE_HELPER = "/usr/local/lib/workstation-desktop/workstation-thunderbird-profile.py"
IM_ENV_KEYS = (
    "IBUS_ADDRESS",
    "GTK_IM_MODULE",
    "QT_IM_MODULE",
    "XMODIFIERS",
    "SDL_IM_MODULE",
    "GLFW_IM_MODULE",
    "CLUTTER_IM_MODULE",
)
PROC_ENV_KEYS = (
    "DISPLAY",
    "XAUTHORITY",
    "XDG_RUNTIME_DIR",
    "PULSE_SERVER",
    "HOME",
    "USER",
    "LOGNAME",
    "LANG",
    "LANGUAGE",
    "LC_ALL",
    "TZ",
    *IM_ENV_KEYS,
)
_IBUS_PROXY_LOCK = threading.Lock()
_IBUS_PROXIES: dict[str, "UnixSocketProxy"] = {}


class UnixSocketProxy:
    def __init__(self, listen_path: Path, target_path: str):
        self.listen_path = listen_path
        self.target_path = target_path
        self._server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._server.setblocking(False)
        self._accept_thread: threading.Thread | None = None
        self._closed = threading.Event()

    def start(self) -> None:
        self.listen_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.listen_path.unlink()
        except FileNotFoundError:
            pass
        self._server.bind(str(self.listen_path))
        os.chmod(self.listen_path, 0o600)
        self._server.listen(16)
        self._accept_thread = threading.Thread(target=self._accept_loop, daemon=True)
        self._accept_thread.start()

    def close(self) -> None:
        if self._closed.is_set():
            return
        self._closed.set()
        try:
            self._server.close()
        except OSError:
            pass
        try:
            self.listen_path.unlink()
        except FileNotFoundError:
            pass

    def _accept_loop(self) -> None:
        while not self._closed.is_set():
            try:
                client, _ = self._server.accept()
            except BlockingIOError:
                self._closed.wait(0.1)
                continue
            except OSError:
                break
            threading.Thread(target=self._handle_client, args=(client,), daemon=True).start()

    def _handle_client(self, client: socket.socket) -> None:
        with client:
            try:
                upstream = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                upstream.connect(self.target_path)
            except OSError:
                return
            with upstream:
                client.setblocking(False)
                upstream.setblocking(False)
                selector = selectors.DefaultSelector()
                selector.register(client, selectors.EVENT_READ, upstream)
                selector.register(upstream, selectors.EVENT_READ, client)
                try:
                    while True:
                        events = selector.select(timeout=1.0)
                        if not events and self._closed.is_set():
                            return
                        for key, _mask in events:
                            source = key.fileobj
                            dest = key.data
                            try:
                                data = source.recv(65536)
                            except BlockingIOError:
                                continue
                            except OSError:
                                return
                            if not data:
                                return
                            try:
                                dest.sendall(data)
                            except OSError:
                                return
                finally:
                    selector.close()


def load_mapping(desktop_id: str) -> dict:
    mapping_path = LAUNCHERS_DIR / f"{desktop_id}.json"
    if not mapping_path.is_file():
        raise FileNotFoundError(f"unknown snap launcher mapping: {desktop_id}")
    return json.loads(mapping_path.read_text(encoding="utf-8"))


def command_for(mapping: dict, action: str | None) -> str:
    if action:
        command = mapping.get("actions", {}).get(action, {}).get("command")
        if command:
            return command
        raise KeyError(f"unknown snap desktop action: {action}")
    command = mapping.get("default", {}).get("command")
    if command:
        return command
    raise KeyError("missing default snap command")


def read_proc_environ(pid: int) -> dict[str, str]:
    try:
        raw = Path(f"/proc/{pid}/environ").read_bytes()
    except OSError:
        return {}
    env = {}
    for entry in raw.split(b"\0"):
        if not entry or b"=" not in entry:
            continue
        key, value = entry.split(b"=", 1)
        try:
            env[key.decode("utf-8")] = value.decode("utf-8")
        except UnicodeDecodeError:
            continue
    return env


def read_proc_cmdline(pid: int) -> str:
    try:
        raw = Path(f"/proc/{pid}/cmdline").read_bytes()
    except OSError:
        return ""
    return raw.replace(b"\0", b" ").decode("utf-8", errors="ignore").strip()


def discover_session_env() -> dict[str, str]:
    current_uid = os.getuid()
    best_env: dict[str, str] = {}
    best_rank = 99
    for proc_dir in Path("/proc").iterdir():
        if not proc_dir.name.isdigit():
            continue
        try:
            if proc_dir.stat().st_uid != current_uid:
                continue
        except OSError:
            continue
        pid = int(proc_dir.name)
        cmdline = read_proc_cmdline(pid)
        if not cmdline:
            continue
        rank = None
        if "xfce4-session" in cmdline:
            rank = 0
        elif "ibus-daemon" in cmdline:
            rank = 1
        elif "dbus-launch" in cmdline:
            rank = 2
        if rank is None:
            continue
        env = read_proc_environ(pid)
        if not env:
            continue
        if env.get("DISPLAY") not in {"", DISPLAY}:
            continue
        if rank < best_rank:
            best_rank = rank
            best_env = env
    return best_env


def ibus_address_from(env: dict[str, str]) -> str:
    base_env = {
        "HOME": env.get("HOME", USER_HOME),
        "USER": env.get("USER", USERNAME),
        "LOGNAME": env.get("LOGNAME", USERNAME),
        "DISPLAY": env.get("DISPLAY", DISPLAY),
        "XAUTHORITY": env.get("XAUTHORITY", XAUTHORITY),
        "XDG_RUNTIME_DIR": env.get("XDG_RUNTIME_DIR", XDG_RUNTIME_DIR),
        "LANG": env.get("LANG", LANG),
        "LANGUAGE": env.get("LANGUAGE", LANGUAGE),
        "LC_ALL": env.get("LC_ALL", LC_ALL),
        "PATH": PATH_VALUE,
    }
    if env.get("DBUS_SESSION_BUS_ADDRESS"):
        base_env["DBUS_SESSION_BUS_ADDRESS"] = env["DBUS_SESSION_BUS_ADDRESS"]
    try:
        result = subprocess.run(
            ["/usr/bin/ibus", "address"],
            env=base_env,
            cwd=base_env["HOME"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            check=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return ""
    return result.stdout.strip()


def unix_path_from_address(address: str) -> str:
    prefix = "unix:path="
    if not address.startswith(prefix):
        return ""
    path_part = address[len(prefix):]
    return path_part.split(",", 1)[0]


def proxy_socket_path_for(command: str) -> Path:
    return Path(XDG_RUNTIME_DIR) / f"snap.{command}" / "workstation-ibus.sock"


def ensure_ibus_proxy(address: str, command: str) -> str:
    target_path = unix_path_from_address(address)
    if not target_path:
        return address
    listen_path = proxy_socket_path_for(command)
    proxy_key = str(listen_path)
    with _IBUS_PROXY_LOCK:
        proxy = _IBUS_PROXIES.get(proxy_key)
        if proxy is not None and proxy.target_path == target_path:
            return f"unix:path={listen_path}"
        if proxy is not None:
            proxy.close()
        proxy = UnixSocketProxy(listen_path, target_path)
        proxy.start()
        _IBUS_PROXIES[proxy_key] = proxy
    return f"unix:path={listen_path}"


def resolve_launch_env() -> dict[str, str]:
    env = {
        "HOME": USER_HOME,
        "USER": USERNAME,
        "LOGNAME": USERNAME,
        "DISPLAY": DISPLAY,
        "XAUTHORITY": XAUTHORITY,
        "XDG_RUNTIME_DIR": XDG_RUNTIME_DIR,
        "PULSE_SERVER": PULSE_SERVER,
        "PATH": PATH_VALUE,
        "LANG": LANG,
        "LANGUAGE": LANGUAGE,
        "LC_ALL": LC_ALL,
        "TZ": TIMEZONE,
        "DBUS_SESSION_BUS_ADDRESS": DBUS_SESSION_BUS_ADDRESS,
        "GTK_IM_MODULE": GTK_IM_MODULE,
        "QT_IM_MODULE": QT_IM_MODULE,
        "XMODIFIERS": XMODIFIERS,
        "SDL_IM_MODULE": SDL_IM_MODULE,
        "GLFW_IM_MODULE": GLFW_IM_MODULE,
        "CLUTTER_IM_MODULE": CLUTTER_IM_MODULE,
    }
    session_env = discover_session_env()
    session_bus = session_env.get("DBUS_SESSION_BUS_ADDRESS", "")
    for key in PROC_ENV_KEYS:
        value = session_env.get(key)
        if value:
            env[key] = value
    probe_env = dict(env)
    if session_bus:
        probe_env["DBUS_SESSION_BUS_ADDRESS"] = session_bus
    ibus_address = session_env.get("IBUS_ADDRESS") or ibus_address_from(probe_env)
    if ibus_address:
        env["IBUS_ADDRESS"] = ibus_address
    return env


def launch_snap(command: str, argv: list[str]) -> None:
    env = resolve_launch_env()
    if env.get("IBUS_ADDRESS"):
        env["IBUS_ADDRESS"] = ensure_ibus_proxy(env["IBUS_ADDRESS"], command)
    runner_env = {
        "HOME": USER_HOME,
        "USER": USERNAME,
        "LOGNAME": USERNAME,
        "XDG_RUNTIME_DIR": XDG_RUNTIME_DIR,
        "DBUS_SESSION_BUS_ADDRESS": DBUS_SESSION_BUS_ADDRESS,
        "PATH": PATH_VALUE,
        "LANG": LANG,
        "LANGUAGE": LANGUAGE,
        "LC_ALL": LC_ALL,
        "TZ": TIMEZONE,
    }
    child_env = [
        f"HOME={env['HOME']}",
        f"USER={env['USER']}",
        f"LOGNAME={env['LOGNAME']}",
        f"DISPLAY={env['DISPLAY']}",
        f"XAUTHORITY={env['XAUTHORITY']}",
        f"XDG_RUNTIME_DIR={env['XDG_RUNTIME_DIR']}",
        f"LANG={env['LANG']}",
        f"LANGUAGE={env['LANGUAGE']}",
        f"LC_ALL={env['LC_ALL']}",
        f"PATH={env['PATH']}",
        f"DBUS_SESSION_BUS_ADDRESS={env['DBUS_SESSION_BUS_ADDRESS']}",
        f"TZ={env['TZ']}",
    ]
    if env.get("PULSE_SERVER"):
        child_env.append(f"PULSE_SERVER={env['PULSE_SERVER']}")
    for key in IM_ENV_KEYS:
        value = env.get(key)
        if value:
            child_env.append(f"{key}={value}")
    command_line = [
        "/usr/bin/systemd-run",
        "--user",
        "--no-block",
        "--quiet",
        "--collect",
        "--service-type=exec",
        *(f"--setenv={item}" for item in child_env),
        f"/snap/bin/{command}",
        *argv,
    ]
    try:
        subprocess.run(
            command_line,
            env=runner_env,
            cwd=USER_HOME,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        stderr_text = (exc.stderr or "").strip()
        if stderr_text:
            raise RuntimeError(stderr_text) from exc
        raise RuntimeError(f"systemd-run failed with exit status {exc.returncode}") from exc


def ensure_snap_profile_defaults(command: str) -> None:
    if command not in THUNDERBIRD_COMMANDS:
        return
    env = resolve_launch_env()
    try:
        subprocess.run(
            ["/usr/bin/python3", THUNDERBIRD_PROFILE_HELPER, "seed-and-sync"],
            env=env,
            cwd=USER_HOME,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        stderr_text = (exc.stderr or "").strip()
        if stderr_text:
            print(f"workstation-snap-bridge: Thunderbird profile preparation warning: {stderr_text}", file=sys.stderr)
            return
        print("workstation-snap-bridge: Thunderbird profile preparation warning: Thunderbird profile preparation failed", file=sys.stderr)
        return


def handle_connection(conn: socket.socket) -> None:
    request = bytearray()
    while True:
        chunk = conn.recv(65536)
        if not chunk:
            break
        request.extend(chunk)
    try:
        payload = json.loads(request.decode("utf-8"))
        desktop_id = str(payload["desktop_id"])
        action = payload.get("action")
        argv = [str(item) for item in payload.get("argv", [])]
        mapping = load_mapping(desktop_id)
        command = command_for(mapping, action)
        ensure_snap_profile_defaults(command)
        launch_snap(command, argv)
        response = {"ok": True}
    except Exception as exc:  # noqa: BLE001
        response = {"ok": False, "error": str(exc)}
    conn.sendall(json.dumps(response, ensure_ascii=False).encode("utf-8"))


def cleanup(*_args) -> None:
    for proxy in list(_IBUS_PROXIES.values()):
        proxy.close()
    _IBUS_PROXIES.clear()
    try:
        SOCKET_PATH.unlink()
    except FileNotFoundError:
        pass
    raise SystemExit(0)


def main() -> int:
    SOCKET_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        SOCKET_PATH.unlink()
    except FileNotFoundError:
        pass

    signal.signal(signal.SIGTERM, cleanup)
    signal.signal(signal.SIGINT, cleanup)

    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
        server.bind(str(SOCKET_PATH))
        os.chmod(SOCKET_PATH, 0o600)
        server.listen(16)
        while True:
            conn, _ = server.accept()
            with conn:
                handle_connection(conn)


if __name__ == "__main__":
    sys.exit(main())
