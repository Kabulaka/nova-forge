#!/usr/bin/env python3
"""Validate a Nova shared capability catalog."""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path, PurePosixPath


HEADERS = ("类型", "能力", "说明", "代码位置", "复用边界")
VERSION_RE = re.compile(r"^>\s*共享能力目录版本[：:]\s*(.+?)\s*$", re.MULTILINE)
PLACEHOLDER_RE = re.compile(r"<[^>]+>")
SEPARATOR_RE = re.compile(r"^:?-{3,}:?$")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--if-present",
        action="store_true",
        help="skip validation only when the canonical catalog does not exist",
    )
    parser.add_argument("path")
    return parser.parse_args()


def table_cells(line: str) -> tuple[str, ...] | None:
    stripped = line.strip()
    if not stripped.startswith("|") or not stripped.endswith("|"):
        return None
    return tuple(cell.strip() for cell in stripped[1:-1].split("|"))


def catalog_rows(text: str) -> tuple[list[tuple[int, tuple[str, ...]]], list[str]]:
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

    rows: list[tuple[int, tuple[str, ...]]] = []
    for line_number, line in enumerate(lines[header_index + 2 :], start=header_index + 3):
        cells = table_cells(line)
        if cells is None:
            if line.strip():
                break
            if rows:
                break
            continue
        if len(cells) != len(HEADERS):
            return [], ["capability row must contain exactly five columns"]
        rows.append((line_number, cells))
    if not rows:
        return [], ["shared capability catalog must contain at least one implemented capability"]
    return rows, []


def catalog_context(path_value: str | os.PathLike[str]) -> tuple[Path, Path, list[str]]:
    raw_path = os.fspath(path_value)
    if not raw_path or "\x00" in raw_path:
        return Path("."), Path("."), ["invalid shared capability catalog path"]
    if raw_path.endswith(("/", "\\")):
        return Path(raw_path), Path("."), [
            "shared capability catalog path must be canonical"
        ]
    if re.search(r"[\\/]{2,}", raw_path):
        return Path(raw_path), Path("."), [
            "shared capability catalog path must be canonical"
        ]
    if any(part in {".", ".."} for part in re.split(r"[\\/]", raw_path)):
        return Path(raw_path), Path("."), [
            "shared capability catalog path must be canonical"
        ]

    path = Path(raw_path)
    if path.parent.name != ".nova" or path.name != "SHARED_CAPABILITIES.md":
        return path, Path("."), [
            "shared capability catalog path must be .nova/SHARED_CAPABILITIES.md"
        ]

    absolute_path = path if path.is_absolute() else Path.cwd() / path
    repo_root = absolute_path.parent.parent
    expected = repo_root / ".nova" / "SHARED_CAPABILITIES.md"
    if absolute_path != expected:
        return path, repo_root, ["shared capability catalog path must be canonical"]
    if absolute_path.parent.is_symlink() or absolute_path.is_symlink():
        return path, repo_root, [
            "shared capability catalog and .nova directory must not be symbolic links"
        ]
    try:
        repo_root.resolve(strict=True)
    except (OSError, RuntimeError, ValueError) as exc:
        return path, repo_root, [f"cannot resolve repository root: {exc}"]
    return absolute_path, repo_root, []


def display_path(value: str) -> str:
    return ascii(value)


def validate(
    path_value: str | os.PathLike[str], *, allow_missing: bool = False
) -> tuple[list[str], bool]:
    errors: list[str] = []
    path, repo_root, context_errors = catalog_context(path_value)
    if context_errors:
        return context_errors, False
    if allow_missing:
        try:
            path.stat()
        except FileNotFoundError:
            if path.parent.is_dir():
                return [], True
            return ["cannot inspect shared capability catalog: parent is not a directory"], False
        except (OSError, RuntimeError, ValueError) as exc:
            return [f"cannot inspect shared capability catalog: {exc}"], False
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        return [f"cannot read shared capability catalog: {exc}"], False

    if VERSION_RE.findall(text) != ["1"]:
        errors.append("shared capability catalog version must be 1")
    if PLACEHOLDER_RE.search(text):
        errors.append("shared capability catalog contains placeholders")

    try:
        repo_root = repo_root.resolve(strict=True)
        path.resolve(strict=True).relative_to(repo_root)
    except (OSError, RuntimeError, ValueError) as exc:
        return errors + [f"cannot resolve shared capability catalog: {exc}"], False

    rows, row_errors = catalog_rows(text)
    errors.extend(row_errors)
    names: set[str] = set()
    for line_number, row in rows:
        _, name, _, location, _ = row
        raw_location = location.strip()
        if raw_location.startswith("`") and raw_location.endswith("`"):
            raw_location = raw_location[1:-1]
        required_values = (*row[:3], raw_location, row[4])
        if any(not value or value == "无" for value in required_values):
            errors.append(f"capability row line {line_number} requires all fields")
        normalized_name = name.casefold()
        if normalized_name in names:
            errors.append(f"duplicate shared capability: {name}")
        names.add(normalized_name)

        invalid_syntax = (
            not raw_location
            or "\x00" in raw_location
            or "\\" in raw_location
            or "//" in raw_location
            or re.match(r"^[A-Za-z]:", raw_location) is not None
        )
        relative = PurePosixPath(raw_location)
        if (
            invalid_syntax
            or relative.is_absolute()
            or not relative.parts
            or any(part in {".", ".."} for part in raw_location.split("/"))
            or relative.parts[0] == ".nova"
            or relative.as_posix() != raw_location
        ):
            errors.append(
                f"capability row line {line_number} has invalid shared capability "
                f"code location: {display_path(location)}"
            )
            continue
        try:
            target = (repo_root / Path(*relative.parts)).resolve(strict=True)
            resolved_relative = target.relative_to(repo_root)
        except FileNotFoundError:
            errors.append(
                f"capability row line {line_number} shared capability code location "
                f"does not exist: {display_path(location)}"
            )
            continue
        except ValueError:
            errors.append(
                f"capability row line {line_number} shared capability code location "
                f"escapes repository: {display_path(location)}"
            )
            continue
        except (OSError, RuntimeError) as exc:
            errors.append(
                f"capability row line {line_number} cannot resolve shared capability "
                f"code location {display_path(location)}: {exc}"
            )
            continue
        if resolved_relative.parts and resolved_relative.parts[0] == ".nova":
            errors.append(
                f"capability row line {line_number} shared capability code location "
                f"resolves into .nova governance data: {display_path(location)}"
            )

    return errors, False


def main() -> int:
    args = parse_args()
    errors, skipped = validate(args.path, allow_missing=args.if_present)
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    if skipped:
        print("OK: shared capability catalog is absent; validation skipped")
        return 0
    print("OK: shared capability catalog is valid")
    return 0


if __name__ == "__main__":
    sys.exit(main())
