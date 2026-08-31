#!/usr/bin/env python3
"""Plan or atomically apply the deterministic legacy-to-.nova document migration."""

from __future__ import annotations

import argparse
import hashlib
import os
import posixpath
import re
import stat
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath


ROOT_MAPPINGS = (
    ("PROJECT_BLUEPRINT.md", ".nova/PROJECT_BLUEPRINT.md"),
    ("PRODUCT_REQUIREMENTS.md", ".nova/PRODUCT_REQUIREMENTS.md"),
    ("docs/requirements", ".nova/requirements"),
    ("docs/architecture", ".nova/architecture"),
    ("docs/design", ".nova/design"),
    ("docs/audit", ".nova/audit"),
)
IMMUTABLE_PREFIXES = ("docs/audit/", ".nova/audit/")
DESIGN_PREFIXES = ("docs/design/", ".nova/design/")
ACTIVE_DESIGN_STATES = {"澄清中", "已确认"}
SKILL_SOURCE_PREFIXES = (
    "nova-development/",
    "nova-review/",
    "nova-requirements/",
    "nova-architecture/",
)
TEXT_SUFFIXES = {
    ".c", ".cc", ".conf", ".cpp", ".css", ".go", ".h", ".html", ".ini", ".java",
    ".js", ".json", ".jsx", ".md", ".properties", ".py", ".rb", ".rs", ".sh",
    ".toml", ".ts", ".tsx", ".txt", ".vue", ".xml", ".yaml", ".yml",
}
MAX_TEXT_BYTES = 2 * 1024 * 1024


class MigrationError(RuntimeError):
    pass


@dataclass(frozen=True)
class Move:
    source: str
    target: str
    kind: str
    mode: int
    content_sha256: str


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


def git_files(repo: Path, *args: str) -> set[str]:
    return {
        raw.decode("utf-8")
        for raw in run_git(repo, *args, "-z").stdout.split(b"\0")
        if raw
    }


def file_sha256(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def lexists(path: Path) -> bool:
    try:
        path.lstat()
        return True
    except FileNotFoundError:
        return False


def reject_symlink_parents(repo: Path, target: Path) -> None:
    relative = target.relative_to(repo)
    current = repo
    for part in relative.parts[:-1]:
        current /= part
        try:
            info = current.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode):
            raise MigrationError(f"target parent is a symlink: {current.relative_to(repo)}")
        if not stat.S_ISDIR(info.st_mode):
            raise MigrationError(f"target parent is not a directory: {current.relative_to(repo)}")


def entity_snapshot(path: Path) -> tuple[str, int, str]:
    info = path.lstat()
    mode = stat.S_IMODE(info.st_mode)
    if stat.S_ISLNK(info.st_mode):
        return "symlink", mode, hashlib.sha256(os.readlink(path).encode("utf-8")).hexdigest()
    if stat.S_ISREG(info.st_mode):
        return "file", mode, file_sha256(path)
    if not stat.S_ISDIR(info.st_mode):
        raise MigrationError(f"unsupported migration entity: {path}")
    hasher = hashlib.sha256()
    for current, directories, files in os.walk(path, followlinks=False):
        directories.sort()
        files.sort()
        base = Path(current)
        for name in directories + files:
            child = base / name
            child_info = child.lstat()
            relative = child.relative_to(path).as_posix()
            child_mode = stat.S_IMODE(child_info.st_mode)
            if stat.S_ISLNK(child_info.st_mode):
                kind = "symlink"
                digest = hashlib.sha256(os.readlink(child).encode("utf-8")).hexdigest()
            elif stat.S_ISREG(child_info.st_mode):
                kind = "file"
                digest = file_sha256(child)
            elif stat.S_ISDIR(child_info.st_mode):
                kind = "directory"
                digest = "-"
            else:
                raise MigrationError(f"unsupported migration entity: {child}")
            hasher.update(f"{relative}\0{kind}\0{child_mode:o}\0{digest}\0".encode("utf-8"))
    return "directory", mode, hasher.hexdigest()


def target_for(relative: str, moves: tuple[Move, ...]) -> str:
    for move in moves:
        if relative == move.source:
            return move.target
        prefix = move.source.rstrip("/") + "/"
        if relative.startswith(prefix):
            return move.target.rstrip("/") + "/" + relative[len(prefix):]
    return relative


def immutable_text(relative: str, text: str) -> bool:
    if relative.startswith(IMMUTABLE_PREFIXES + SKILL_SOURCE_PREFIXES):
        return True
    if not relative.startswith(DESIGN_PREFIXES):
        return False
    if not relative.endswith(".md"):
        return True
    states = re.findall(r"^>\s*设计状态[：:]\s*(.+?)\s*$", text, re.MULTILINE)
    return len(states) != 1 or states[0] not in ACTIVE_DESIGN_STATES


def mapped_repo_path(value: str, active_sources: set[str]) -> str | None:
    for old, new in ROOT_MAPPINGS:
        if old not in active_sources:
            continue
        if value == old:
            return new
        prefix = old.rstrip("/") + "/"
        if value.startswith(prefix):
            return new.rstrip("/") + "/" + value[len(prefix):]
    return None


def rewrite_text(relative: str, target_relative: str, text: str, moves: tuple[Move, ...]) -> tuple[str, int]:
    if immutable_text(relative, text):
        return text, 0
    active_sources = {move.source for move in moves}
    replacements = 0

    def rewrite_link(match: re.Match[str]) -> str:
        nonlocal replacements
        destination = match.group(2)
        path_part, separator, anchor = destination.partition("#")
        mapped = mapped_repo_path(path_part, active_sources)
        if mapped is None:
            return match.group(0)
        start = PurePosixPath(target_relative).parent.as_posix() or "."
        rewritten = posixpath.relpath(mapped, start=start)
        replacements += 1
        return f"{match.group(1)}{rewritten}{separator}{anchor}{match.group(3)}"

    text = re.sub(r"(\]\()([^\s)]+)(\))", rewrite_link, text)
    target_parent = PurePosixPath(target_relative).parent.as_posix()
    for old, new in ROOT_MAPPINGS:
        if old not in active_sources or "/" not in old:
            continue
        old_prefix = old.rstrip("/") + "/"
        new_prefix = new.rstrip("/") + "/"
        if target_parent == ".nova":
            new_prefix = new_prefix.removeprefix(".nova/")
        count = text.count(old_prefix)
        if count:
            text = text.replace(old_prefix, new_prefix)
            replacements += count
    if target_parent != ".nova":
        for old, new in ROOT_MAPPINGS[:2]:
            if old not in active_sources:
                continue
            pattern = re.compile(rf"(?<![/A-Za-z0-9_.-]){re.escape(old)}")
            text, count = pattern.subn(new, text)
            replacements += count
    text = text.replace(".nova/.nova/", ".nova/")
    return text, replacements


def plan(repo: Path) -> tuple[tuple[Move, ...], tuple[Rewrite, ...]]:
    tracked = git_files(repo, "ls-files")
    moves: list[Move] = []
    for source, target in ROOT_MAPPINGS:
        source_path = repo / source
        target_path = repo / target
        reject_symlink_parents(repo, target_path)
        try:
            source_path.lstat()
        except FileNotFoundError:
            continue
        try:
            target_path.lstat()
        except FileNotFoundError:
            pass
        else:
            raise MigrationError(f"target conflict: {source} -> {target}")
        kind, mode, digest = entity_snapshot(source_path)
        if kind == "directory":
            untracked: list[str] = []
            for current, directories, files in os.walk(source_path, followlinks=False):
                base = Path(current)
                candidates = [base / name for name in files]
                candidates.extend(base / name for name in directories if (base / name).is_symlink())
                untracked.extend(
                    candidate.relative_to(repo).as_posix()
                    for candidate in candidates
                    if candidate.relative_to(repo).as_posix() not in tracked
                )
            untracked.sort()
            if untracked:
                raise MigrationError("migration source contains untracked files: " + ", ".join(untracked))
        elif source not in tracked:
            raise MigrationError(f"migration source is not tracked: {source}")
        moves.append(Move(source, target, kind, mode, digest))
    move_tuple = tuple(moves)

    listed = git_files(repo, "ls-files", "-co", "--exclude-standard")
    rewrites: list[Rewrite] = []
    for relative in sorted(listed):
        path = repo / relative
        try:
            info = path.lstat()
        except FileNotFoundError:
            continue
        if not stat.S_ISREG(info.st_mode):
            continue
        if info.st_size > MAX_TEXT_BYTES:
            if path.suffix.lower() in TEXT_SUFFIXES or path.name in {"Dockerfile", "Makefile"}:
                raise MigrationError(f"text candidate exceeds {MAX_TEXT_BYTES} bytes: {relative}")
            continue
        before = path.read_bytes()
        try:
            text = before.decode("utf-8")
        except UnicodeDecodeError:
            if any(old.encode("utf-8") in before for old, _ in ROOT_MAPPINGS):
                raise MigrationError(f"reference-bearing file is not UTF-8: {relative}")
            continue
        target_relative = target_for(relative, move_tuple)
        after_text, count = rewrite_text(relative, target_relative, text, move_tuple)
        if count:
            rewrites.append(Rewrite(relative, target_relative, before, after_text.encode("utf-8"), count))
    return move_tuple, tuple(rewrites)


def snapshot_token(moves: tuple[Move, ...], rewrites: tuple[Rewrite, ...]) -> str:
    hasher = hashlib.sha256()
    for move in moves:
        hasher.update(
            f"M\0{move.source}\0{move.target}\0{move.kind}\0{move.mode:o}\0{move.content_sha256}\0".encode()
        )
    for rewrite in rewrites:
        hasher.update(f"R\0{rewrite.source_path}\0{rewrite.target_path}\0".encode())
        hasher.update(hashlib.sha256(rewrite.before).digest())
        hasher.update(hashlib.sha256(rewrite.after).digest())
    return hasher.hexdigest()


def print_plan(moves: tuple[Move, ...], rewrites: tuple[Rewrite, ...]) -> str:
    token = snapshot_token(moves, rewrites)
    print("Nova layout migration dry-run")
    print(f"Plan-SHA256: {token}")
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
    return token


def created_parent_directories(repo: Path, target: Path) -> list[Path]:
    reject_symlink_parents(repo, target)
    missing: list[Path] = []
    current = target.parent
    while current != repo and not current.exists():
        missing.append(current)
        current = current.parent
    target.parent.mkdir(parents=True, exist_ok=True)
    return missing


def validate_documents(repo: Path) -> None:
    skills_root = Path(__file__).resolve().parents[2]
    checks: list[tuple[Path, list[str], str]] = []
    blueprint = repo / ".nova/PROJECT_BLUEPRINT.md"
    if blueprint.is_file() and "蓝图规范版本" in blueprint.read_text(encoding="utf-8"):
        checks.append((skills_root / "nova-development/scripts/validate_blueprint.py", [str(blueprint)], "blueprint"))
    requirements = repo / ".nova/PRODUCT_REQUIREMENTS.md"
    if requirements.is_file() and "需求规范版本" in requirements.read_text(encoding="utf-8"):
        checks.append((skills_root / "nova-requirements/scripts/validate_requirements.py", ["--index", str(requirements)], "requirements"))
    architecture = repo / ".nova/architecture/ARCHITECTURE_CONTRACTS.md"
    if architecture.is_file() and "架构契约版本" in architecture.read_text(encoding="utf-8"):
        checks.append((skills_root / "nova-architecture/scripts/validate_architecture.py", [str(architecture)], "architecture"))
    designs = sorted((repo / ".nova/design").glob("*.md")) if (repo / ".nova/design").is_dir() else ()
    for design in designs:
        if "设计规范版本" in design.read_text(encoding="utf-8"):
            checks.append((skills_root / "nova-development/scripts/validate_blueprint.py", ["--design", str(design)], f"design {design.name}"))
    for script, arguments, label in checks:
        result = subprocess.run([sys.executable, str(script), *arguments], capture_output=True, text=True, check=False)
        if result.returncode:
            detail = (result.stdout + result.stderr).strip().replace("\n", " | ")
            raise MigrationError(f"post-migration {label} validation failed: {detail}")


def apply(repo: Path, moves: tuple[Move, ...], rewrites: tuple[Rewrite, ...]) -> None:
    applied_moves: list[Move] = []
    written: list[Rewrite] = []
    created_dirs: list[Path] = []
    try:
        for move in moves:
            if entity_snapshot(repo / move.source) != (move.kind, move.mode, move.content_sha256):
                raise MigrationError(f"source changed after approved dry-run: {move.source}")
        for move in moves:
            created_dirs.extend(created_parent_directories(repo, repo / move.target))
            run_git(repo, "mv", "--", move.source, move.target)
            applied_moves.append(move)
        for rewrite in rewrites:
            target = repo / rewrite.target_path
            current = target.read_bytes()
            if current != rewrite.before:
                raise MigrationError(f"source changed after approved dry-run: {rewrite.source_path}")
            target.write_bytes(rewrite.after)
            written.append(rewrite)
        for move in moves:
            if lexists(repo / move.source) or not lexists(repo / move.target):
                raise MigrationError(f"post-migration entity check failed: {move.source}")
        validate_documents(repo)
    except Exception as exc:
        rollback_errors: list[str] = []
        for rewrite in reversed(written):
            try:
                (repo / rewrite.target_path).write_bytes(rewrite.before)
            except OSError as rollback_exc:
                rollback_errors.append(f"restore {rewrite.target_path}: {rollback_exc}")
        for move in reversed(applied_moves):
            try:
                if lexists(repo / move.target) and not lexists(repo / move.source):
                    (repo / move.source).parent.mkdir(parents=True, exist_ok=True)
                    run_git(repo, "mv", "--", move.target, move.source)
            except (OSError, MigrationError) as rollback_exc:
                rollback_errors.append(f"reverse {move.target}: {rollback_exc}")
        for directory in sorted(set(created_dirs), key=lambda item: len(item.parts), reverse=True):
            try:
                directory.rmdir()
            except FileNotFoundError:
                pass
            except OSError as rollback_exc:
                rollback_errors.append(f"remove directory {directory.relative_to(repo)}: {rollback_exc}")
        if rollback_errors:
            raise MigrationError(f"migration rollback incomplete after {exc}: " + "; ".join(rollback_errors)) from exc
        raise MigrationError(f"migration rolled back: {exc}") from exc


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--plan-sha256")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        repo = repository_root(args.repo.expanduser().resolve())
        moves, rewrites = plan(repo)
        token = print_plan(moves, rewrites)
        if args.apply:
            if args.plan_sha256 is None:
                raise MigrationError("--apply requires the approved --plan-sha256")
            if args.plan_sha256 != token:
                raise MigrationError(f"approved plan mismatch: expected {args.plan_sha256}, current {token}")
            apply(repo, moves, rewrites)
            print("APPLIED")
        else:
            if args.plan_sha256 is not None:
                raise MigrationError("--plan-sha256 is only valid with --apply")
            print("DRY-RUN ONLY")
        return 0
    except (MigrationError, OSError, UnicodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
