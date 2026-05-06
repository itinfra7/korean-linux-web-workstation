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

NAME_ATTR = f"{{{OOR_NS}}}name"
OP_ATTR = f"{{{OOR_NS}}}op"


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def find_child(element: ET.Element, tag_name: str, name: str | None = None) -> ET.Element | None:
    for child in list(element):
        if local_name(child.tag) != tag_name:
            continue
        if name is not None and child.get(NAME_ATTR) != name:
            continue
        return child
    return None


def ensure_child(element: ET.Element, tag_name: str, name: str | None = None) -> ET.Element:
    found = find_child(element, tag_name, name)
    if found is not None:
        return found
    child = ET.SubElement(element, tag_name)
    if name is not None:
        child.set(NAME_ATTR, name)
    return child


def ensure_prop(node: ET.Element, prop_name: str, value: str) -> None:
    prop = ensure_child(node, "prop", prop_name)
    prop.set(OP_ATTR, "fuse")
    value_node = None
    for child in list(prop):
        if local_name(child.tag) == "value":
            value_node = child
            break
    if value_node is None:
        value_node = ET.SubElement(prop, "value")
    value_node.text = value


def patch_commands(root: ET.Element, component_name: str) -> bool:
    changed = False
    for comp in list(root):
        if local_name(comp.tag) != "component-data":
            continue
        if comp.get(NAME_ATTR) != component_name:
            continue
        ui = ensure_child(comp, "node", "UserInterface")
        commands = ensure_child(ui, "node", "Commands")
        popups = ensure_child(ui, "node", "Popups")
        if component_name == "WriterCommands":
            numbering = ensure_child(commands, "node", ".uno:NumberingMenu")
            ensure_prop(numbering, "Label", "목록(~L)")
            changed = True

            popup_numbering = ensure_child(popups, "node", ".uno:NumberingMenu")
            ensure_prop(popup_numbering, "Label", "목록(~L)")
            changed = True

            page_dialog = ensure_child(commands, "node", ".uno:PageDialog")
            ensure_prop(page_dialog, "Label", "페이지 스타일(~P)...")
            ensure_prop(page_dialog, "ContextLabel", "페이지 스타일(~P)...")
            changed = True
        elif component_name == "CalcCommands":
            page_dialog = ensure_child(commands, "node", ".uno:PageDialog")
            ensure_prop(page_dialog, "Label", "페이지 스타일(~P)...")
            ensure_prop(page_dialog, "ContextLabel", "페이지 스타일(~P)...")
            changed = True
    return changed


def patch_file(path: Path) -> bool:
    tree = ET.parse(path)
    root = tree.getroot()
    changed = False
    changed |= patch_commands(root, "WriterCommands")
    changed |= patch_commands(root, "CalcCommands")
    if changed:
        ET.indent(tree, space="  ")
        tree.write(path, encoding="UTF-8", xml_declaration=True)
    return changed


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Patch LibreOffice registry command labels for Korean defaults.")
    parser.add_argument("targets", nargs="+")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    for target in args.targets:
        patch_file(Path(target))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
