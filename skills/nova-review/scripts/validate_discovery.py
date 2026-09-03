#!/usr/bin/env python3
"""Validate Nova skill discovery and Codex/Claude Code global rule links."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


EXPECTED_SKILLS = (
    "nova-requirements",
    "nova-architecture",
    "nova-development",
    "nova-doctor",
    "nova-review",
)


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


def validate_host(
    workspace: Path, host_home: Path, global_filename: str, host_label: str
) -> list[str]:
    errors: list[str] = []
    global_source = workspace / "codex" / "AGENTS.global.md"
    global_link = host_home / global_filename
    if not global_link.is_symlink():
        errors.append(f"global {global_filename} must be a symlink: {global_link}")
    elif global_link.resolve() != global_source.resolve():
        errors.append(
            f"global {global_filename} resolves to unexpected target: "
            f"{global_link.resolve()}"
        )

    skill_home = host_home / "skills"
    discovered: dict[str, list[Path]] = {}
    if skill_home.is_dir():
        for entry in skill_home.iterdir():
            if entry.is_symlink() and not entry.exists():
                errors.append(f"{host_label} broken skill discovery entry: {entry}")
                continue
            if not entry.is_dir():
                continue
            name = skill_name(entry)
            if name is not None:
                discovered.setdefault(name, []).append(entry)

    for name in EXPECTED_SKILLS:
        source = workspace / "skills" / name
        link = skill_home / name
        if not link.is_symlink():
            errors.append(f"{host_label} skill discovery entry must be a symlink: {link}")
        elif not link.exists():
            errors.append(f"{host_label} skill discovery entry is broken: {link}")
        elif link.resolve() != source.resolve():
            errors.append(
                f"{host_label} skill discovery entry resolves to unexpected target: "
                f"{link.resolve()}"
            )
        matching = discovered.get(name, [])
        if len(matching) != 1:
            errors.append(
                f"{host_label} {name} must have exactly one discoverable skill entity, "
                f"found {len(matching)}"
            )
        elif matching[0] != link:
            errors.append(
                f"{host_label} {name} discoverable entity must use canonical link: "
                f"{matching[0]}"
            )

    for legacy_name in ("project-brainstorming", "nova-brainstorming"):
        legacy = skill_home / legacy_name
        if legacy.exists() or legacy.is_symlink():
            errors.append(f"{host_label} legacy discovery entry must be absent: {legacy}")

    return errors


def validate(
    workspace: Path, codex_home: Path, claude_home: Path | None = None
) -> list[str]:
    workspace = workspace.resolve()
    codex_home = codex_home.resolve()
    errors: list[str] = []
    if (workspace / "AGENTS.md").exists():
        errors.append("workspace root must not contain AGENTS.md; use codex/AGENTS.global.md")

    global_source = workspace / "codex" / "AGENTS.global.md"
    if not global_source.is_file():
        errors.append(f"missing global source: {global_source}")

    for name in EXPECTED_SKILLS:
        source = workspace / "skills" / name
        if not source.is_dir():
            errors.append(f"missing skill source: {source}")
        elif skill_name(source) != name:
            errors.append(f"skill source frontmatter name mismatch: {source}")

    errors.extend(validate_host(workspace, codex_home, "AGENTS.md", "Codex"))
    if claude_home is not None:
        errors.extend(
            validate_host(workspace, claude_home.resolve(), "CLAUDE.md", "Claude Code")
        )

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--codex-home", type=Path, required=True)
    parser.add_argument(
        "--claude-home",
        type=Path,
        help="Claude Code user directory; omit for backward-compatible Codex-only validation",
    )
    args = parser.parse_args()
    errors = validate(args.workspace, args.codex_home, args.claude_home)
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        print("FAIL")
        return 1
    print("PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
