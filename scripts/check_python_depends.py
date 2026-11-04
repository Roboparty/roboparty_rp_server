#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0
# Copyright (C) 2026 RoboParty

"""Check that third-party Python imports are covered by debian/control.

pip and Debian use different package names, so this script keeps an explicit
mapping and verifies that every third-party module imported by the source has a
corresponding Depends/Recommends entry for the roboparty-rp-server package.

Usage:
    python3 scripts/check_python_depends.py          # check (exit 1 on gaps)
    python3 scripts/check_python_depends.py --list   # show the mapping
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "src" / "rp_server"
PACKAGE = "roboparty-rp-server"

# Top-level imported module -> Debian package (without version constraint).
IMPORT_TO_DEB = {
    "fastapi": "python3-fastapi",
    "uvicorn": "python3-uvicorn",
    "websockets": "python3-websockets",
    "google": "python3-protobuf",  # google.protobuf (generated bindings)
    "yaml": "python3-yaml",
    "psutil": "python3-psutil",
    "evdev": "python3-evdev",
    "serial_asyncio": "python3-serial-asyncio",
    "bluetooth": "python3-bluez",
    "cryptography": "python3-cryptography",
    "jwt": "python3-jwt",
}


def imported_modules(root: Path) -> set[str]:
    names: set[str] = set()
    for path in root.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, UnicodeError, SyntaxError) as exc:
            raise SystemExit(f"cannot parse {path}: {exc}")
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names.add(node.module.split(".")[0])
    return names


def stanza(control: str, package: str) -> str:
    for block in re.split(r"\n(?=Package:)", control):
        if re.search(r"^Package:\s*" + re.escape(package) + r"\s*$", block, re.M):
            return block
    raise SystemExit(f"package stanza not found: {package}")


def field_packages(body: str, field: str) -> list[str]:
    match = re.search(rf"^{field}:\s*(.*?)(?=^\S|\Z)", body, re.M | re.S)
    if not match:
        return []
    value = re.sub(r"\s*\n\s*", " ", match.group(1)).strip()
    packages = []
    for item in re.split(r",\s*", value):
        item = item.strip()
        if not item or item.startswith("${"):
            continue
        packages.append(re.split(r"[\s(\[]", item, maxsplit=1)[0])
    return packages


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list", action="store_true", help="print the import -> Debian mapping")
    args = parser.parse_args(argv)

    if args.list:
        for module, deb in sorted(IMPORT_TO_DEB.items()):
            print(f"{module:20s} -> {deb}")
        return 0

    control = (ROOT / "debian" / "control").read_text(encoding="utf-8")
    body = stanza(control, PACKAGE)
    declared = set(field_packages(body, "Depends")) | set(field_packages(body, "Recommends"))

    modules = imported_modules(SOURCE)
    used = {module: IMPORT_TO_DEB[module] for module in modules if module in IMPORT_TO_DEB}
    missing = [(module, deb) for module, deb in sorted(used.items()) if deb not in declared]

    for module, deb in missing:
        print(f"debian/control is missing {deb} (imported as {module})")

    if missing:
        print("FAIL: Python imports are not covered by debian/control")
        return 1
    print(f"OK: {len(used)} third-party imports covered by {PACKAGE} Depends/Recommends")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
