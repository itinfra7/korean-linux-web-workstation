#!/usr/bin/env python3

import hashlib
import os
import subprocess
import sys
import time
from pathlib import Path

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GdkPixbuf", "2.0")

from gi.repository import Gdk, GdkPixbuf, Gtk  # noqa: E402


PNG_TARGET = "image/png"
RICH_IMAGE_TARGETS = {
    "image/bmp",
    "image/x-bmp",
    "image/x-MS-bmp",
    "image/x-win-bitmap",
    "image/vnd.microsoft.icon",
    "image/x-icon",
}
POLL_SECONDS = 0.6


def xclip_output(*args: str) -> bytes:
    return subprocess.check_output(
        ["xclip", "-selection", "clipboard", *args],
        stderr=subprocess.DEVNULL,
    )


def clipboard_targets() -> set[str]:
    try:
        raw = xclip_output("-t", "TARGETS", "-o")
    except subprocess.CalledProcessError:
        return set()
    return {
        line.strip()
        for line in raw.decode("utf-8", errors="ignore").splitlines()
        if line.strip()
    }


def read_png_clipboard() -> bytes | None:
    try:
        data = xclip_output("-t", PNG_TARGET, "-o")
    except subprocess.CalledProcessError:
        return None
    return data or None


def pixbuf_from_png(data: bytes) -> GdkPixbuf.Pixbuf:
    loader = GdkPixbuf.PixbufLoader.new_with_type("png")
    loader.write(data)
    loader.close()
    pixbuf = loader.get_pixbuf()
    if pixbuf is None:
        raise RuntimeError("clipboard image could not be decoded as PNG")
    return pixbuf


def republish_image(data: bytes) -> None:
    clipboard = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
    clipboard.set_image(pixbuf_from_png(data))
    clipboard.store()
    while Gtk.events_pending():
        Gtk.main_iteration_do(False)


def set_image_from_path(path_text: str) -> int:
    path = Path(path_text)
    if not path.is_file():
        raise FileNotFoundError(path)
    republish_image(path.read_bytes())
    return 0


def set_image_from_stdin() -> int:
    data = sys.stdin.buffer.read()
    if not data:
        raise RuntimeError("missing png data on stdin")
    republish_image(data)
    return 0


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args:
        if len(args) == 2 and args[0] == "--set-file":
            return set_image_from_path(args[1])
        if len(args) == 1 and args[0] == "--set-stdin":
            return set_image_from_stdin()
        raise SystemExit("usage: workstation-image-clipboard-bridge.py [--set-file <png-path> | --set-stdin]")

    if not shutil_which("xclip"):
        return 0

    last_digest = ""
    while True:
        try:
            targets = clipboard_targets()
            if PNG_TARGET not in targets:
                last_digest = ""
                time.sleep(POLL_SECONDS)
                continue

            if RICH_IMAGE_TARGETS & targets:
                data = read_png_clipboard()
                last_digest = hashlib.sha256(data).hexdigest() if data else ""
                time.sleep(POLL_SECONDS)
                continue

            data = read_png_clipboard()
            if not data:
                time.sleep(POLL_SECONDS)
                continue

            digest = hashlib.sha256(data).hexdigest()
            if digest != last_digest:
                republish_image(data)
                last_digest = digest
        except KeyboardInterrupt:
            return 0
        except Exception:
            pass

        time.sleep(POLL_SECONDS)


def shutil_which(name: str) -> str | None:
    paths = os.environ.get("PATH", "").split(os.pathsep)
    for directory in paths:
        candidate = os.path.join(directory, name)
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return None


if __name__ == "__main__":
    raise SystemExit(main())
