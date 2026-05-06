#!/usr/bin/env python3

from __future__ import annotations

import argparse
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path


SOURCE_TEMPLATE = "ja_ott_normal.ott"
KO_TEMPLATE = "ko_ott_normal.ott"
KO_REGION_TEMPLATE = "ko_KR_ott_normal.ott"

XML_REPLACEMENTS = (
    ("Noto Serif CJK JP:ruby", "Noto Serif CJK KR:ruby"),
    ("Noto Sans Mono CJK JP", "Noto Sans Mono CJK KR"),
    ("Noto Sans CJK JP", "Noto Sans CJK KR"),
    ("Noto Serif CJK JP", "Noto Serif CJK KR"),
    ('fo:language="en" fo:country="US"', 'fo:language="ko" fo:country="KR"'),
    ('style:language-asian="ja" style:country-asian="JP"', 'style:language-asian="ko" style:country-asian="KR"'),
)

BINARY_STRING_PATCHES = (
    (b"Default Paragraph Style", "기본 문단 스타일".encode("utf-8")),
    (b"Default Page Style", "기본쪽스타일".encode("utf-8")),
    (b"Welcome to LibreOffice!", "환영합니다!".encode("utf-8")),
    (b"Welcome", "환영".encode("utf-8")),
    (b"User Interface", "사용환경".encode("utf-8")),
    (b"Appearance", "모양".encode("utf-8")),
    (b"You are running %PRODUCTNAME for the first time.", "%PRODUCTNAME 첫 실행입니다.".encode("utf-8")),
    (b"Please take a moment to personalize your settings.", "설정을 잠시 확인해 주세요.".encode("utf-8")),
    (b"You are running version %PRODUCTVERSION of %PRODUCTNAME for the first time. ", "%PRODUCTNAME %PRODUCTVERSION 첫 실행입니다. ".encode("utf-8")),
    (b"~Credits", "기여".encode("utf-8")),
    (b"~Release Notes", "새 기능".encode("utf-8")),
    (b"Do you want to learn what's new?", "새 기능 보기?".encode("utf-8")),
)

STYLE_REPLACEMENTS = (
    (
        '<style:style style:name="Standard" style:family="paragraph"',
        '<style:style style:name="Standard" style:display-name="기본 문단 스타일" style:family="paragraph"',
    ),
    (
        '<style:master-page style:name="Standard" style:page-layout-name="Mpm1"',
        '<style:master-page style:name="Standard" style:display-name="기본 페이지 스타일" style:page-layout-name="Mpm1"',
    ),
    (
        'style:name="First_20_Page" style:display-name="First Page"',
        'style:name="First_20_Page" style:display-name="첫 페이지"',
    ),
    (
        'style:name="Left_20_Page" style:display-name="Left Page"',
        'style:name="Left_20_Page" style:display-name="왼쪽 페이지"',
    ),
    (
        'style:name="Right_20_Page" style:display-name="Right Page"',
        'style:name="Right_20_Page" style:display-name="오른쪽 페이지"',
    ),
    (
        '<style:master-page style:name="Landscape" style:page-layout-name="Mpm5"',
        '<style:master-page style:name="Landscape" style:display-name="가로 방향" style:page-layout-name="Mpm5"',
    ),
)

CUI_PATCHES = (
    (
        'msgctxt "welcomedialog|WelcomeDialog"\nmsgid "What\'s new in %PRODUCTVERSION"\nmsgstr ""',
        'msgctxt "welcomedialog|WelcomeDialog"\nmsgid "What\'s new in %PRODUCTVERSION"\nmsgstr "%PRODUCTVERSION의 새로운 기능"',
    ),
    (
        'msgctxt "welcomedialog|showagain"\nmsgid "Do Show Again"\nmsgstr ""',
        'msgctxt "welcomedialog|showagain"\nmsgid "Do Show Again"\nmsgstr "다시 표시"',
    ),
    (
        'msgctxt "welcomedialog|whatsnewtab"\nmsgid "Welcome"\nmsgstr ""',
        'msgctxt "welcomedialog|whatsnewtab"\nmsgid "Welcome"\nmsgstr "환영"',
    ),
    (
        'msgctxt "welcomedialog|uitab"\nmsgid "User Interface"\nmsgstr ""',
        'msgctxt "welcomedialog|uitab"\nmsgid "User Interface"\nmsgstr "사용자 인터페이스"',
    ),
    (
        'msgctxt "welcomedialog|appearancetab"\nmsgid "Appearance"\nmsgstr ""',
        'msgctxt "welcomedialog|appearancetab"\nmsgid "Appearance"\nmsgstr "모양"',
    ),
)


def copy_xcd(source: Path, target_dir: Path) -> None:
    target_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target_dir / source.name)


def patch_po_entry(po_text: str, replacements: tuple[tuple[str, str], ...]) -> str:
    updated = po_text
    for original, replacement in replacements:
        updated = updated.replace(original, replacement)
    return updated


def rebuild_cui_catalog(cui_mo: Path) -> None:
    po_text = subprocess.run(
        ["msgunfmt", str(cui_mo)],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    patched = patch_po_entry(po_text, CUI_PATCHES)
    if patched == po_text:
        return

    with tempfile.TemporaryDirectory() as tmpdir:
        po_path = Path(tmpdir) / "cui.po"
        mo_path = Path(tmpdir) / "cui.mo"
        po_path.write_text(patched, encoding="utf-8")
        subprocess.run(["msgfmt", "-o", str(mo_path), str(po_path)], check=True)
        shutil.copy2(mo_path, cui_mo)


def patch_binary_strings(binary_path: Path) -> None:
    if not binary_path.is_file():
        return

    original = binary_path.read_bytes()
    patched = original
    for old, new in BINARY_STRING_PATCHES:
        if len(new) > len(old):
            raise ValueError(f"replacement is longer than source string for {old!r}")
        replacement = new + (b"\0" * (len(old) - len(new)))
        patched = patched.replace(old, replacement)

    if patched != original:
        binary_path.write_bytes(patched)


def patch_xml_text(text: str, replacements: tuple[tuple[str, str], ...]) -> str:
    updated = text
    for old, new in replacements:
        updated = updated.replace(old, new)
    return updated


def rebuild_ko_template(template_dir: Path) -> None:
    source = template_dir / SOURCE_TEMPLATE
    target = template_dir / KO_TEMPLATE
    if not source.is_file():
        return

    with zipfile.ZipFile(source, "r") as src:
        members = {name: src.read(name) for name in src.namelist()}

    for xml_name in ("styles.xml", "content.xml"):
        text = members[xml_name].decode("utf-8")
        text = patch_xml_text(text, XML_REPLACEMENTS)
        if xml_name == "styles.xml":
            text = patch_xml_text(text, STYLE_REPLACEMENTS)
        members[xml_name] = text.encode("utf-8")

    with tempfile.NamedTemporaryFile(delete=False) as tmp:
        temp_path = Path(tmp.name)

    try:
        with zipfile.ZipFile(temp_path, "w") as out:
            if "mimetype" in members:
                out.writestr(
                    "mimetype",
                    members["mimetype"],
                    compress_type=zipfile.ZIP_STORED,
                )
            for name, data in members.items():
                if name == "mimetype":
                    continue
                out.writestr(name, data, compress_type=zipfile.ZIP_DEFLATED)
        shutil.move(temp_path, target)
        target.chmod(0o644)
        shutil.copy2(target, template_dir / KO_REGION_TEMPLATE)
        (template_dir / KO_REGION_TEMPLATE).chmod(0o644)
    finally:
        temp_path.unlink(missing_ok=True)


def patch_help_startcenter(install_root: Path) -> None:
    help_path = install_root / "help/ko/text/shared/guide/startcenter.html"
    if not help_path.is_file():
        return

    text = help_path.read_text(encoding="utf-8", errors="ignore")
    replacements = (
        ("Welcome to LibreOffice", "LibreOffice에 오신 것을 환영합니다"),
        ("You see the Start Center", "시작 센터가 표시됩니다"),
        ("Open existing files", "기존 파일 열기"),
        ("Working with Templates", "서식 파일 사용"),
        ("Create:", "만들기:"),
        ("Please support us!", "LibreOffice를 지원해 주세요!"),
    )
    patched = patch_xml_text(text, replacements)
    if patched != text:
        help_path.write_text(patched, encoding="utf-8")


def apply_install_root(install_root: Path, defaults_xcd: Path, writer_xcd: Path) -> None:
    registry_dir = install_root / "share/registry"
    if not registry_dir.is_dir():
        registry_dir = install_root / "share/.registry"
    if not registry_dir.is_dir():
        return

    copy_xcd(defaults_xcd, registry_dir)
    copy_xcd(writer_xcd, registry_dir)

    template_dir = install_root / "share/template/common/l10n"
    if template_dir.is_dir():
        rebuild_ko_template(template_dir)

    cui_mo = install_root / "program/resource/ko/LC_MESSAGES/cui.mo"
    if cui_mo.is_file():
        rebuild_cui_catalog(cui_mo)

    patch_binary_strings(install_root / "program/libswlo.so")
    patch_binary_strings(install_root / "program/libcuilo.so")

    patch_help_startcenter(install_root)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Apply Korean LibreOffice overlays used by workstation.")
    parser.add_argument("--defaults-xcd", required=True)
    parser.add_argument("--writer-xcd", required=True)
    parser.add_argument(
        "--install-root",
        action="append",
        default=[],
        help="LibreOffice install root. May be specified multiple times.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    defaults_xcd = Path(args.defaults_xcd).resolve()
    writer_xcd = Path(args.writer_xcd).resolve()

    install_roots = [Path(path) for path in args.install_root]
    if not install_roots:
        install_roots = [Path("/opt/libreoffice26.2"), Path("/usr/lib/libreoffice")]

    for install_root in install_roots:
        if install_root.exists():
            apply_install_root(install_root, defaults_xcd, writer_xcd)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
