#!/usr/bin/env python3

from __future__ import annotations

import argparse
import xml.etree.ElementTree as ET
from pathlib import Path


OOR_NS = "http://openoffice.org/2001/registry"
XS_NS = "http://www.w3.org/2001/XMLSchema"
XSI_NS = "http://www.w3.org/2001/XMLSchema-instance"

ET.register_namespace("oor", OOR_NS)
ET.register_namespace("xs", XS_NS)
ET.register_namespace("xsi", XSI_NS)

ROOT_TAG = f"{{{OOR_NS}}}items"
PATH_ATTR = f"{{{OOR_NS}}}path"
NAME_ATTR = f"{{{OOR_NS}}}name"
OP_ATTR = f"{{{OOR_NS}}}op"


def local_name(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[1]
    return tag


def load_tree(primary_path: Path, fallback_path: Path) -> ET.ElementTree:
    source_path = primary_path if primary_path.is_file() else fallback_path
    if source_path.is_file():
        return ET.ElementTree(ET.fromstring(source_path.read_text(encoding="utf-8", errors="ignore")))
    return ET.ElementTree(ET.Element(ROOT_TAG))


def find_child(element: ET.Element, tag_name: str, attr_name: str | None = None, attr_value: str | None = None) -> ET.Element | None:
    for child in list(element):
        if local_name(child.tag) != tag_name:
            continue
        if attr_name is not None and child.get(attr_name) != attr_value:
            continue
        return child
    return None


def find_children(element: ET.Element, tag_name: str, attr_name: str | None = None, attr_value: str | None = None) -> list[ET.Element]:
    matches: list[ET.Element] = []
    for child in list(element):
        if local_name(child.tag) != tag_name:
            continue
        if attr_name is not None and child.get(attr_name) != attr_value:
            continue
        matches.append(child)
    return matches


def ensure_item_node(root: ET.Element, item_path: str) -> ET.Element:
    items = find_children(root, "item", PATH_ATTR, item_path)
    if not items:
        item = ET.SubElement(root, "item")
        item.set(PATH_ATTR, item_path)
        return item

    item = items[0]
    for extra_item in items[1:]:
        for child in list(extra_item):
            item.append(child)
        root.remove(extra_item)
    return item


def ensure_item(root: ET.Element, item_path: str, prop_name: str, value: str) -> None:
    item = ensure_item_node(root, item_path)

    props = find_children(item, "prop", NAME_ATTR, prop_name)
    prop = props[0] if props else None
    if prop is None:
        prop = ET.SubElement(item, "prop")
        prop.set(NAME_ATTR, prop_name)
    for extra in props[1:]:
        item.remove(extra)

    prop.set(OP_ATTR, "fuse")
    value_nodes = find_children(prop, "value")
    value_node = value_nodes[0] if value_nodes else None
    if value_node is None:
        value_node = ET.SubElement(prop, "value")
    for extra in value_nodes[1:]:
        prop.remove(extra)
    value_node.text = value


def remove_prop(root: ET.Element, item_path: str, prop_name: str) -> None:
    items = find_children(root, "item", PATH_ATTR, item_path)
    if not items:
        return

    keep_item = items[0]
    for extra_item in items[1:]:
        for child in list(extra_item):
            keep_item.append(child)
        root.remove(extra_item)

    for prop in find_children(keep_item, "prop", NAME_ATTR, prop_name):
        keep_item.remove(prop)

    if not list(keep_item):
        root.remove(keep_item)


def ensure_items(root: ET.Element) -> None:
    ensure_item(root, "/org.openoffice.Office.Common/Misc", "FirstRun", "false")
    ensure_item(root, "/org.openoffice.Office.Common/Misc", "LastTipOfTheDayShown", "2147483647")
    ensure_item(root, "/org.openoffice.Office.Common/Misc", "LastTipOfTheDayID", "0")
    ensure_item(root, "/org.openoffice.Office.Common/Misc", "ShowTipOfTheDay", "false")
    ensure_item(root, "/org.openoffice.Setup/L10N", "ooLocale", "ko")
    ensure_item(root, "/org.openoffice.Setup/L10N", "ooSetupSystemLocale", "ko-KR")
    ensure_item(root, "/org.openoffice.Setup/Office", "LastCompatibilityCheckID", "1f77d10d6938fd34972958f64b2bcfa54f8b1ba5")
    ensure_item(root, "/org.openoffice.Setup/Product", "ooSetupLastVersion", "26.2")
    ensure_item(root, "/org.openoffice.Setup/Product", "LastTimeDonateShown", "2147483647")
    ensure_item(root, "/org.openoffice.Setup/Product", "LastTimeGetInvolvedShown", "2147483647")
    ensure_item(root, "/org.openoffice.Office.Linguistic/General", "UILocale", "ko")
    ensure_item(root, "/org.openoffice.Office.Linguistic/General", "DefaultLocale", "ko-KR")
    ensure_item(root, "/org.openoffice.Office.Linguistic/General", "DefaultLocale_CJK", "ko-KR")
    ensure_item(root, "/org.openoffice.Office.Linguistic/General", "DefaultLocale_CTL", "ko-KR")
    ensure_item(root, "/org.openoffice.System/L10N", "Locale", "ko-KR")
    ensure_item(root, "/org.openoffice.System/L10N", "UILocale", "ko")
    ensure_item(root, "/org.openoffice.System/L10N", "SystemLocale", "ko-KR")


def ensure_root(root: ET.Element | None) -> ET.Element:
    if root is not None and local_name(root.tag) == "items":
        return root
    return ET.Element(ROOT_TAG)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Ensure the managed LibreOffice profile defaults stay Korean.")
    parser.add_argument("--seed", required=True)
    parser.add_argument("--target", required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    seed_path = Path(args.seed).expanduser().resolve()
    target_path = Path(args.target).expanduser().resolve()
    target_path.parent.mkdir(parents=True, exist_ok=True)

    tree = load_tree(target_path, seed_path)
    root = ensure_root(tree.getroot())
    tree._setroot(root)
    ensure_items(root)
    ET.indent(tree, space="  ")
    tree.write(target_path, encoding="UTF-8", xml_declaration=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
