#!/usr/bin/env python3
"""Plan or atomically apply the deterministic legacy-to-.nova document migration."""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


ROOT_MAPPINGS = (
    ("PROJECT_BLUEPRINT.md", ".nova/PROJECT_BLUEPRINT.md"),
    ("PRODUCT_REQUIREMENTS.md", ".nova/PRODUCT_REQUIREMENTS.md"),
    ("docs/requirements", ".nova/requirements"),
    ("docs/architecture", ".nova/architecture"),
    ("docs/design", ".nova/design"),
    ("docs/audit", ".nova/audit"),
)
IMMUTABLE_PREFIXES = ("docs/design/", "docs/audit/", ".nova/design/", ".nova/audit/")
SKILL_SOURCE_PREFIXES = (
    "nova-development/",
    "nova-review/",
    "nova-requirements/",
    "nova-architecture/",
)


class MigrationError(RuntimeError):
    pass


@dataclass(frozen=True)
class Move:
    source: str
    target: str


@dataclass(frozen=True)
class Rewrite:
    source_path: str
    target_path: str
    before: bytes
    after: bytes
    replacements: int


def run_git(repo: Path, *args: str, allow_failure: bool = False) -> subprocess.CompletedProcess[bytes]:
    result = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, check=False)
    if result.returncode and not allow_failure:
        message = result.stderr.decode("utf-8", errors="replace").strip()
        raise MigrationError(message or f"git {' '.join(args)} failed")
    return result


def repository_root(path: Path) -> Path:
    result = run_git(path, "rev-parse", "--show-toplevel")
    return Path(result.stdout.decode("utf-8").strip()).resolve()


def tracked(repo: Path, relative: str) -> bool:
    return run_git(repo, "ls-files", "--error-unmatch", "--", relative, allow_failure=True).returncode == 0


def target_for(relative: str, moves: tuple[Move, ...]) -> str:
    for move in moves:
        if relative == move.source:
            return move.target
        prefix = move.source.rstrip("/") + "/"
        if relative.startswith(prefix):
            return move.target.rstrip("/") + "/" + relative[len(prefix):]
    return relative


def rewrite_text(relative: str, text: str, moves: tuple[Move, ...]) -> tuple[str, int]:
    if relative.startswith(IMMUTABLE_PREFIXES + SKILL_SOURCE_PREFIXES):
        return text, 0
    blueprint = relative in ("PROJECT_BLUEPRINT.md", ".nova/PROJECT_BLUEPRINT.md")
    active_sources = {move.source for move in moves}
    replacements = 0
    path_pairs = (
        ("docs/requirements", "docs/requirements/", "requirements/" if blueprint else ".nova/requirements/"),
        ("docs/architecture", "docs/architecture/", "architecture/" if blueprint else ".nova/architecture/"),
        ("docs/design", "docs/design/", "design/" if blueprint else ".nova/design/"),
        ("docs/audit", "docs/audit/", "audit/" if blueprint else ".nova/audit/"),
    )
    for source, old, new in path_pairs:
        if source not in active_sources:
            continue
        count = text.count(old)
        if count:
            text = text.replace(old, new)
            replacements += count
    for old, new in (
        ("PROJECT_BLUEPRINT.md", ".nova/PROJECT_BLUEPRINT.md"),
        ("PRODUCT_REQUIREMENTS.md", ".nova/PRODUCT_REQUIREMENTS.md"),
    ):
        if old not in active_sources:
            continue
        pattern = re.compile(rf"(?<![/A-Za-z0-9_.-]){re.escape(old)}")
        text, count = pattern.subn(new, text)
        replacements += count
    if blueprint:
        text = text.replace(".nova/.nova/", ".nova/")
    return text, replacements


def plan(repo: Path) -> tuple[tuple[Move, ...], tuple[Rewrite, ...]]:
    moves: list[Move] = []
    for source, target in ROOT_MAPPINGS:
        source_path = repo / source
        target_path = repo / target
        if not source_path.exists() and not source_path.is_symlink():
            continue
        if target_path.exists() or target_path.is_symlink():
            raise MigrationError(f"target conflict: {source} -> {target}")
        if source_path.is_dir():
            untracked = [
                file.relative_to(repo).as_posix()
                for file in source_path.rglob("*")
                if (file.is_file() or file.is_symlink()) and not tracked(repo, file.relative_to(repo).as_posix())
            ]
            if untracked:
                raise MigrationError("migration source contains untracked files: " + ", ".join(sorted(untracked)))
        elif not tracked(repo, source):
            raise MigrationError(f"migration source is not tracked: {source}")
        moves.append(Move(source, target))
    move_tuple = tuple(moves)

    listed = run_git(repo, "ls-files", "-co", "--exclude-standard", "-z").stdout.split(b"\0")
    rewrites: list[Rewrite] = []
    for raw in listed:
        if not raw:
            continue
        relative = raw.decode("utf-8")
        path = repo / relative
        if not path.is_file() or relative.startswith(".git/"):
            continue
        before = path.read_bytes()
        try:
            text = before.decode("utf-8")
        except UnicodeDecodeError:
            if any(old.encode("utf-8") in before for old, _ in ROOT_MAPPINGS):
                raise MigrationError(f"reference-bearing file is not UTF-8: {relative}")
            continue
        after_text, count = rewrite_text(relative, text, move_tuple)
        if count:
            rewrites.append(
                Rewrite(relative, target_for(relative, move_tuple), before, after_text.encode("utf-8"), count)
            )
    return move_tuple, tuple(rewrites)


def snapshot_token(moves: tuple[Move, ...], rewrites: tuple[Rewrite, ...]) -> str:
    hasher = hashlib.sha256()
    for move in moves:
        hasher.update(f"M\0{move.source}\0{move.target}\0".encode())
    for rewrite in rewrites:
        hasher.update(f"R\0{rewrite.source_path}\0{rewrite.target_path}\0".encode())
        hasher.update(hashlib.sha256(rewrite.before).digest())
        hasher.update(hashlib.sha256(rewrite.after).digest())
    return hasher.hexdigest()


def print_plan(moves: tuple[Move, ...], rewrites: tuple[Rewrite, ...]) -> None:
    print("Nova layout migration dry-run")
    print(f"Plan-SHA256: {snapshot_token(moves, rewrites)}")
    print("Moves:")
    if not moves:
        print("  none")
    for move in moves:
        print(f"  {move.source} -> {move.target}")
    print("Reference rewrites:")
    if not rewrites:
        print("  none")
    for rewrite in rewrites:
        print(f"  {rewrite.source_path} -> {rewrite.target_path} ({rewrite.replacements})")
    print("Conflicts: none")


def apply(repo: Path, moves: tuple[Move, ...], rewrites: tuple[Rewrite, ...]) -> None:
    if not moves:
        return
    applied_moves: list[Move] = []
    written: list[Rewrite] = []
    try:
        for move in moves:
            (repo / move.target).parent.mkdir(parents=True, exist_ok=True)
            run_git(repo, "mv", "--", move.source, move.target)
            applied_moves.append(move)
        for rewrite in rewrites:
            target = repo / rewrite.target_path
            current = target.read_bytes()
            if current != rewrite.before:
                raise MigrationError(f"source changed after dry-run: {rewrite.source_path}")
            target.write_bytes(rewrite.after)
            written.append(rewrite)
        for move in moves:
            if (repo / move.source).exists() or not (repo / move.target).exists():
                raise MigrationError(f"post-migration entity check failed: {move.source}")
    except Exception as exc:
        for rewrite in reversed(written):
            target = repo / rewrite.target_path
            if target.exists():
                target.write_bytes(rewrite.before)
        for move in reversed(applied_moves):
            if (repo / move.target).exists() and not (repo / move.source).exists():
                (repo / move.source).parent.mkdir(parents=True, exist_ok=True)
                run_git(repo, "mv", "--", move.target, move.source, allow_failure=True)
        raise MigrationError(f"migration rolled back: {exc}") from exc


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        repo = repository_root(args.repo.expanduser().resolve())
        moves, rewrites = plan(repo)
        print_plan(moves, rewrites)
        if args.apply:
            apply(repo, moves, rewrites)
            print("APPLIED")
        else:
            print("DRY-RUN ONLY")
        return 0
    except (MigrationError, OSError, UnicodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
