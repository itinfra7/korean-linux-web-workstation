#!/usr/bin/env python3
from __future__ import annotations

import copy
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


def load_actions(path: Path) -> ET.Element:
    tree = ET.parse(path)
    root = tree.getroot()
    if root.tag != "actions":
        raise ValueError(f"{path} does not contain an <actions> root")
    return root


def normalize(root: ET.Element) -> None:
    for action in root.findall("action"):
        for range_elem in list(action.findall("range")):
            if not (range_elem.text or "").strip():
                action.remove(range_elem)
        command = action.find("command")
        if command is not None and command.text is not None:
            command.text = command.text.strip()


def is_archive_action(action: ET.Element) -> bool:
    command = action.findtext("command") or ""
    return "workstation-archive-action " in command


def action_key(action: ET.Element) -> str:
    return (action.findtext("command") or "").strip()


def merge_actions(canonical_root: ET.Element, target_root: ET.Element) -> bool:
    changed = False
    normalize(canonical_root)
    normalize(target_root)
    removed_archive = False
    for action in list(target_root.findall("action")):
        if is_archive_action(action):
            target_root.remove(action)
            removed_archive = True
    if removed_archive:
        changed = True
    existing_keys = {action_key(action) for action in target_root.findall("action") if action_key(action)}
    for canonical_action in canonical_root.findall("action"):
        key = action_key(canonical_action)
        if not key or key in existing_keys:
            continue
        target_root.append(copy.deepcopy(canonical_action))
        existing_keys.add(key)
        changed = True
    return changed


def write_actions(path: Path, root: ET.Element) -> None:
    tree = ET.ElementTree(root)
    if hasattr(ET, "indent"):
        ET.indent(tree, space="  ")
    path.parent.mkdir(parents=True, exist_ok=True)
    tree.write(path, encoding="utf-8", xml_declaration=True, short_empty_elements=True)


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: workstation-thunar-uca-merge.py <canonical-uca.xml> <target-uca.xml>", file=sys.stderr)
        return 2

    canonical_path = Path(sys.argv[1])
    target_path = Path(sys.argv[2])

    canonical_root = load_actions(canonical_path)
    target_root: ET.Element

    if target_path.exists():
        try:
            target_root = load_actions(target_path)
        except Exception:
            target_root = copy.deepcopy(canonical_root)
            normalize(target_root)
            write_actions(target_path, target_root)
            return 0
        changed = merge_actions(canonical_root, target_root)
        if changed:
            write_actions(target_path, target_root)
        return 0

    target_root = copy.deepcopy(canonical_root)
    normalize(target_root)
    write_actions(target_path, target_root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
