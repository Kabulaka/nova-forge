#!/usr/bin/env python3
"""Install Nova skills and one shared global rule file for Codex and Claude Code."""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from pathlib import Path


SKILL_NAMES = (
    "nova-requirements",
    "nova-architecture",
    "nova-development",
    "nova-doctor",
    "nova-review",
)

LEGACY_SKILL_NAMES = (
    "project-brainstorming",
    "nova-brainstorming",
)


class InstallError(RuntimeError):
    """Raised when installation cannot complete without violating link safety."""


@dataclass(frozen=True)
class LinkSpec:
    source: Path
    target: Path


@dataclass(frozen=True)
class PreviousLink:
    target: Path
    raw_source: str | None
    target_is_directory: bool


def build_link_specs(
    workspace: Path, codex_home: Path, claude_home: Path
) -> list[LinkSpec]:
    workspace = workspace.resolve()
    global_source = workspace / "codex" / "AGENTS.global.md"
    specs = [
        LinkSpec(global_source, codex_home / "AGENTS.md"),
        LinkSpec(global_source, claude_home / "CLAUDE.md"),
    ]
    for name in SKILL_NAMES:
        source = workspace / "skills" / name
        specs.append(LinkSpec(source, codex_home / "skills" / name))
        specs.append(LinkSpec(source, claude_home / "skills" / name))
    return specs


def build_legacy_targets(codex_home: Path, claude_home: Path) -> list[Path]:
    return [
        host_home / "skills" / name
        for host_home in (codex_home, claude_home)
        for name in LEGACY_SKILL_NAMES
    ]


def validate_sources(specs: list[LinkSpec]) -> list[str]:
    errors: list[str] = []
    for spec in specs:
        if spec.source.name == "AGENTS.global.md":
            if not spec.source.is_file():
                errors.append(f"missing global rule source: {spec.source}")
        elif not spec.source.is_dir() or not (spec.source / "SKILL.md").is_file():
            errors.append(f"missing skill source: {spec.source}")
    return list(dict.fromkeys(errors))


def validate_targets(specs: list[LinkSpec], legacy_targets: list[Path]) -> list[str]:
    errors: list[str] = []
    seen: set[Path] = set()
    for spec in specs:
        target = spec.target.absolute()
        if target in seen:
            errors.append(f"duplicate install target: {target}")
        seen.add(target)

        if not target.is_symlink() and target.exists():
            kind = "directory" if target.is_dir() else "file"
            errors.append(f"refusing to overwrite {kind}: {target}")
            continue

        ancestor = target.parent
        while not ancestor.exists() and not ancestor.is_symlink():
            if ancestor == ancestor.parent:
                break
            ancestor = ancestor.parent
        if not ancestor.is_dir():
            errors.append(f"install parent is not a directory: {ancestor}")

    for target in legacy_targets:
        target = target.absolute()
        if target in seen:
            errors.append(f"duplicate install target: {target}")
        seen.add(target)
        if not target.is_symlink() and target.exists():
            kind = "directory" if target.is_dir() else "file"
            errors.append(f"refusing to remove legacy {kind}: {target}")
    return errors


def _create_parents(specs: list[LinkSpec], created: list[Path]) -> None:
    parents = sorted({spec.target.parent for spec in specs}, key=lambda path: len(path.parts))
    for parent in parents:
        missing: list[Path] = []
        cursor = parent
        while not cursor.exists() and not cursor.is_symlink():
            missing.append(cursor)
            cursor = cursor.parent
        for directory in reversed(missing):
            directory.mkdir()
            created.append(directory)


def _rollback(changes: list[PreviousLink], created_dirs: list[Path]) -> list[str]:
    errors: list[str] = []
    for previous in reversed(changes):
        try:
            if previous.target.is_symlink():
                previous.target.unlink()
            elif previous.target.exists():
                errors.append(
                    f"rollback refused to overwrite unexpected path: {previous.target}"
                )
                continue
            if previous.raw_source is not None:
                previous.target.symlink_to(
                    previous.raw_source,
                    target_is_directory=previous.target_is_directory,
                )
        except OSError as exc:
            errors.append(f"rollback failed for {previous.target}: {exc}")

    for directory in reversed(created_dirs):
        try:
            directory.rmdir()
        except FileNotFoundError:
            pass
        except OSError:
            # The directory existed before installation or now contains unrelated data.
            pass
    return errors


def install(workspace: Path, codex_home: Path, claude_home: Path) -> list[LinkSpec]:
    specs = build_link_specs(workspace, codex_home, claude_home)
    legacy_targets = build_legacy_targets(codex_home, claude_home)
    errors = validate_sources(specs) + validate_targets(specs, legacy_targets)
    if errors:
        raise InstallError("\n".join(errors))

    created_dirs: list[Path] = []
    changes: list[PreviousLink] = []
    try:
        _create_parents(specs, created_dirs)
        for target in legacy_targets:
            if target.is_symlink():
                changes.append(
                    PreviousLink(
                        target=target,
                        raw_source=os.readlink(target),
                        target_is_directory=target.is_dir(),
                    )
                )
                target.unlink()
            elif target.exists():
                raise InstallError(f"legacy target changed after preflight: {target}")
        for spec in specs:
            target = spec.target
            if target.is_symlink():
                previous = PreviousLink(
                    target=target,
                    raw_source=os.readlink(target),
                    target_is_directory=target.is_dir(),
                )
            elif target.exists():
                raise InstallError(f"install target changed after preflight: {target}")
            else:
                previous = PreviousLink(
                    target=target,
                    raw_source=None,
                    target_is_directory=False,
                )
            changes.append(previous)
            if target.is_symlink():
                target.unlink()
            target.symlink_to(
                spec.source.resolve(),
                target_is_directory=spec.source.is_dir(),
            )
    except (InstallError, OSError) as exc:
        rollback_errors = _rollback(changes, created_dirs)
        detail = str(exc)
        if rollback_errors:
            detail += "\n" + "\n".join(rollback_errors)
        raise InstallError(detail) from exc
    return specs


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--workspace",
        type=Path,
        default=Path(__file__).resolve().parents[2],
        help="Nova Forge repository root (default: inferred from this script)",
    )
    parser.add_argument(
        "--codex-home",
        type=Path,
        default=Path.home() / ".codex",
        help="Codex user directory (default: ~/.codex)",
    )
    parser.add_argument(
        "--claude-home",
        type=Path,
        default=Path.home() / ".claude",
        help="Claude Code user directory (default: ~/.claude)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        specs = install(args.workspace, args.codex_home, args.claude_home)
    except InstallError as exc:
        for line in str(exc).splitlines():
            print(f"ERROR: {line}", file=sys.stderr)
        print("FAIL", file=sys.stderr)
        return 1

    for spec in specs:
        print(f"LINK: {spec.target} -> {spec.source.resolve()}")
    print("PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
