#!/usr/bin/env python3
"""Validate Nova skill discovery and the global Codex AGENTS.md link."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


EXPECTED_SKILLS = ("nova-requirements", "nova-architecture", "nova-development", "nova-review")


def skill_name(path: Path) -> str | None:
    skill_file = path / "SKILL.md"
    if not skill_file.is_file():
        return None
    try:
        text = skill_file.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return None
    if not text.startswith("---\n"):
        return None
    end = text.find("\n---\n", 4)
    if end < 0:
        return None
    matches = re.findall(r"^name:\s*([^\s#]+)\s*$", text[4:end], re.MULTILINE)
    return matches[0] if len(matches) == 1 else None


def validate(workspace: Path, codex_home: Path) -> list[str]:
    workspace = workspace.resolve()
    codex_home = codex_home.resolve()
    errors: list[str] = []
    if (workspace / "AGENTS.md").exists():
        errors.append("workspace root must not contain AGENTS.md; use codex/AGENTS.global.md")

    global_source = workspace / "codex" / "AGENTS.global.md"
    global_link = codex_home / "AGENTS.md"
    if not global_source.is_file():
        errors.append(f"missing global source: {global_source}")
    if not global_link.is_symlink():
        errors.append(f"global AGENTS.md must be a symlink: {global_link}")
    elif global_link.resolve() != global_source.resolve():
        errors.append(f"global AGENTS.md resolves to unexpected target: {global_link.resolve()}")

    skill_home = codex_home / "skills"
    discovered: dict[str, list[Path]] = {}
    if skill_home.is_dir():
        for entry in skill_home.iterdir():
            if entry.is_symlink() and not entry.exists():
                errors.append(f"broken skill discovery entry: {entry}")
                continue
            if not entry.is_dir():
                continue
            name = skill_name(entry)
            if name is not None:
                discovered.setdefault(name, []).append(entry)

    for name in EXPECTED_SKILLS:
        source = workspace / name
        link = skill_home / name
        if not source.is_dir():
            errors.append(f"missing skill source: {source}")
        elif skill_name(source) != name:
            errors.append(f"skill source frontmatter name mismatch: {source}")
        if not link.is_symlink():
            errors.append(f"skill discovery entry must be a symlink: {link}")
        elif not link.exists():
            errors.append(f"skill discovery entry is broken: {link}")
        elif link.resolve() != source.resolve():
            errors.append(f"skill discovery entry resolves to unexpected target: {link.resolve()}")
        matching = discovered.get(name, [])
        if len(matching) != 1:
            errors.append(
                f"{name} must have exactly one discoverable skill entity, found {len(matching)}"
            )
        elif matching[0] != link:
            errors.append(f"{name} discoverable entity must use canonical link: {matching[0]}")

    for legacy_name in ("project-brainstorming", "nova-brainstorming"):
        legacy = skill_home / legacy_name
        if legacy.exists() or legacy.is_symlink():
            errors.append(f"legacy discovery entry must be absent: {legacy}")

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--codex-home", type=Path, required=True)
    args = parser.parse_args()
    errors = validate(args.workspace, args.codex_home)
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        print("FAIL")
        return 1
    print("PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
