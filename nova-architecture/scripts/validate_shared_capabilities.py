#!/usr/bin/env python3
"""Validate a Nova shared capability catalog."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path, PurePosixPath


HEADERS = ("类型", "能力", "说明", "代码位置", "复用边界")
VERSION_RE = re.compile(r"^>\s*共享能力目录版本[：:]\s*(.+?)\s*$", re.MULTILINE)
PLACEHOLDER_RE = re.compile(r"<[^>]+>")
SEPARATOR_RE = re.compile(r"^:?-{3,}:?$")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path)
    return parser.parse_args()


def table_cells(line: str) -> tuple[str, ...] | None:
    stripped = line.strip()
    if not stripped.startswith("|") or not stripped.endswith("|"):
        return None
    return tuple(cell.strip() for cell in stripped[1:-1].split("|"))


def catalog_rows(text: str) -> tuple[list[tuple[str, ...]], list[str]]:
    lines = text.splitlines()
    matches = [index for index, line in enumerate(lines) if table_cells(line) == HEADERS]
    if len(matches) != 1:
        return [], ["shared capability catalog requires exactly one capability table"]

    header_index = matches[0]
    previous = next(
        (line.strip() for line in reversed(lines[:header_index]) if line.strip()),
        "",
    )
    if previous != "## 1. 已实现能力":
        return [], ["capability table must be under: ## 1. 已实现能力"]
    if header_index + 1 >= len(lines):
        return [], ["capability table requires a separator row"]

    separator = table_cells(lines[header_index + 1])
    if separator is None or len(separator) != len(HEADERS) or not all(
        SEPARATOR_RE.fullmatch(cell) for cell in separator
    ):
        return [], ["invalid capability table separator"]

    rows: list[tuple[str, ...]] = []
    for line in lines[header_index + 2 :]:
        cells = table_cells(line)
        if cells is None:
            if line.strip():
                break
            if rows:
                break
            continue
        if len(cells) != len(HEADERS):
            return [], ["capability row must contain exactly five columns"]
        rows.append(cells)
    if not rows:
        return [], ["shared capability catalog must contain at least one implemented capability"]
    return rows, []


def validate(path: Path) -> list[str]:
    errors: list[str] = []
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        return [f"cannot read shared capability catalog: {exc}"]

    if VERSION_RE.findall(text) != ["1"]:
        errors.append("shared capability catalog version must be 1")
    if PLACEHOLDER_RE.search(text):
        errors.append("shared capability catalog contains placeholders")

    try:
        repo_root = path.resolve().parent.parent
        path.resolve().relative_to(repo_root)
    except ValueError:
        return errors + ["shared capability catalog must be inside the repository"]
    if path.parent.name != ".nova" or path.name != "SHARED_CAPABILITIES.md":
        errors.append("shared capability catalog path must be .nova/SHARED_CAPABILITIES.md")

    rows, row_errors = catalog_rows(text)
    errors.extend(row_errors)
    names: set[str] = set()
    for row_number, row in enumerate(rows, start=1):
        _, name, _, location, _ = row
        if any(not value or value == "无" for value in row):
            errors.append(f"capability row {row_number} requires all fields")
        normalized_name = name.casefold()
        if normalized_name in names:
            errors.append(f"duplicate shared capability: {name}")
        names.add(normalized_name)

        raw_location = location.strip("`").strip()
        relative = PurePosixPath(raw_location)
        if (
            not raw_location
            or relative.is_absolute()
            or ".." in relative.parts
            or not relative.parts
            or relative.parts[0] == ".nova"
        ):
            errors.append(f"invalid shared capability code location: {location}")
            continue
        target = (repo_root / Path(*relative.parts)).resolve()
        try:
            target.relative_to(repo_root)
        except ValueError:
            errors.append(f"shared capability code location escapes repository: {location}")
            continue
        if not target.exists():
            errors.append(f"shared capability code location does not exist: {location}")

    return errors


def main() -> int:
    args = parse_args()
    errors = validate(args.path)
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print("OK: shared capability catalog is valid")
    return 0


if __name__ == "__main__":
    sys.exit(main())
