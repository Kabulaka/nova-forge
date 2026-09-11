#!/usr/bin/env python3
"""Run a read-only health check for the current Nova project."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import shlex
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from urllib.parse import unquote


sys.dont_write_bytecode = True

DETAIL_LIMIT = 5
STATUS_RANK = {"PASS": 0, "WARN": 1, "FAIL": 2}


@dataclass(frozen=True)
class Result:
    status: str
    check: str
    message: str
    details: tuple[str, ...] = ()


def run(
    arguments: list[str], cwd: Path, timeout: int = 60
) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    return subprocess.run(
        arguments,
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        env=environment,
    )


def current_project(cwd: Path) -> tuple[Path | None, Result]:
    try:
        completed = run(["git", "rev-parse", "--show-toplevel"], cwd)
    except (OSError, subprocess.TimeoutExpired, UnicodeError) as exc:
        return None, Result("FAIL", "project-root", f"cannot run Git: {exc}")
    if completed.returncode != 0:
        return None, Result(
            "FAIL",
            "project-root",
            "current directory is not inside a Git project",
        )
    root_text = completed.stdout.strip()
    if not root_text:
        return None, Result("FAIL", "project-root", "Git returned an empty project root")
    root = Path(root_text).resolve()
    return root, Result("PASS", "project-root", str(root))


def is_inside_project(root: Path, candidate: Path) -> bool:
    try:
        return candidate.resolve().is_relative_to(root.resolve())
    except (OSError, RuntimeError):
        return False


def nova_boundary(root: Path) -> tuple[Result, bool]:
    nova_root = root / ".nova"
    if not is_inside_project(root, nova_root):
        return Result("FAIL", "nova-layout", ".nova path escapes project root"), False
    if not nova_root.is_dir():
        return Result("FAIL", "nova-layout", "missing .nova directory"), True

    walk_errors: list[str] = []

    def remember_walk_error(exc: OSError) -> None:
        walk_errors.append(str(exc))

    for directory, directories, files in os.walk(
        nova_root, followlinks=False, onerror=remember_walk_error
    ):
        for name in [*directories, *files]:
            candidate = Path(directory) / name
            if not is_inside_project(root, candidate):
                relative = candidate.relative_to(root)
                return (
                    Result(
                        "FAIL",
                        "nova-layout",
                        f"Nova path escapes project root: {relative}",
                    ),
                    False,
                )
    if walk_errors:
        return (
            Result(
                "FAIL",
                "nova-layout",
                "cannot inspect .nova directory",
                tuple(walk_errors[:DETAIL_LIMIT]),
            ),
            False,
        )
    return Result("PASS", "nova-layout", ".nova directory is present"), True


def command_details(completed: subprocess.CompletedProcess[str]) -> tuple[str, ...]:
    lines = []
    for line in (completed.stdout + "\n" + completed.stderr).splitlines():
        stripped = line.strip()
        if stripped.startswith(("ERROR:", "WARNING:")):
            lines.append(stripped)
    if not lines:
        lines = [
            line.strip()
            for line in (completed.stdout + "\n" + completed.stderr).splitlines()
            if line.strip() and line.strip() not in {"PASS", "FAIL"}
        ]
    clipped = lines[:DETAIL_LIMIT]
    if len(lines) > DETAIL_LIMIT:
        clipped.append(f"... {len(lines) - DETAIL_LIMIT} more lines")
    return tuple(clipped)


def validator_result(
    check: str,
    label: str,
    arguments: list[str],
    root: Path,
) -> Result:
    command = shlex.join(arguments)
    try:
        completed = run(arguments, root)
    except subprocess.TimeoutExpired:
        return Result("FAIL", check, f"{label} timed out", (f"Run: {command}",))
    except (OSError, UnicodeError) as exc:
        return Result("FAIL", check, f"cannot run {label}: {exc}", (f"Run: {command}",))
    if completed.returncode == 0:
        return Result("PASS", check, f"{label} passed")
    return Result(
        "FAIL",
        check,
        f"{label} failed",
        command_details(completed) + (f"Run: {command}",),
    )


def migration_changes(output: str) -> bool:
    section: str | None = None
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if line == "Moves:":
            section = "moves"
            continue
        if line == "Reference rewrites:":
            section = "rewrites"
            continue
        if line.startswith("Conflicts:"):
            section = None
            continue
        if section is not None and line and line != "none":
            return True
    return False


def check_migration(root: Path, suite_root: Path) -> Result:
    script = suite_root / "nova-development" / "scripts" / "migrate_nova_layout.py"
    if not script.is_file():
        return Result("FAIL", "migration", f"missing migration detector: {script}")
    arguments = [sys.executable, str(script), "--repo", str(root)]
    try:
        completed = run(arguments, root)
    except subprocess.TimeoutExpired:
        return Result("FAIL", "migration", "migration dry-run timed out")
    except (OSError, UnicodeError) as exc:
        return Result("FAIL", "migration", f"cannot run migration dry-run: {exc}")
    if completed.returncode != 0:
        return Result(
            "FAIL",
            "migration",
            "migration dry-run failed",
            command_details(completed) + (f"Run: {shlex.join(arguments)}",),
        )
    if migration_changes(completed.stdout):
        plan = next(
            (line.strip() for line in completed.stdout.splitlines() if line.startswith("Plan-SHA256:")),
            "migration plan contains changes",
        )
        return Result(
            "WARN",
            "migration",
            "legacy Nova data requires an explicit migration",
            (plan, f"Review only: {shlex.join(arguments)}"),
        )
    return Result("PASS", "migration", "current layout requires no migration")


def optional_validator(
    root: Path,
    suite_root: Path,
    relative_document: str,
    relative_script: str,
    arguments: list[str],
    check: str,
    label: str,
) -> Result:
    document = root / relative_document
    if not is_inside_project(root, document):
        return Result("FAIL", check, f"{relative_document} escapes project root")
    if not document.is_file():
        return Result("PASS", check, f"{label} is not present (optional)")
    script = suite_root / relative_script
    if not script.is_file():
        return Result("FAIL", check, f"missing validator: {script}")
    return validator_result(
        check,
        label,
        [sys.executable, str(script), *arguments, str(document)],
        root,
    )


def check_blueprint(root: Path, suite_root: Path) -> Result:
    document = root / ".nova" / "PROJECT_BLUEPRINT.md"
    if not is_inside_project(root, document):
        return Result("FAIL", "blueprint", ".nova/PROJECT_BLUEPRINT.md escapes project root")
    if not document.is_file():
        return Result("FAIL", "blueprint", "missing .nova/PROJECT_BLUEPRINT.md")
    script = suite_root / "nova-development" / "scripts" / "validate_blueprint.py"
    if not script.is_file():
        return Result("FAIL", "blueprint", f"missing validator: {script}")
    return validator_result(
        "blueprint",
        "project blueprint",
        [sys.executable, str(script), str(document)],
        root,
    )


def check_designs(root: Path, suite_root: Path) -> Result:
    design_root = root / ".nova" / "design"
    if not is_inside_project(root, design_root):
        return Result("FAIL", "designs", ".nova/design escapes project root")
    documents = sorted(design_root.rglob("*.md")) if design_root.is_dir() else []
    if not documents:
        return Result("PASS", "designs", "no design documents are present (optional)")
    script = suite_root / "nova-development" / "scripts" / "validate_blueprint.py"
    if not script.is_file():
        return Result("FAIL", "designs", f"missing validator: {script}")
    failures: list[str] = []
    for document in documents:
        if not is_inside_project(root, document):
            failures.append(f"{document.relative_to(root)}: path escapes project root")
            continue
        arguments = [sys.executable, str(script), "--design", str(document)]
        try:
            completed = run(arguments, root)
        except (OSError, subprocess.TimeoutExpired, UnicodeError) as exc:
            failures.append(f"{document.relative_to(root)}: {exc}")
            continue
        if completed.returncode != 0:
            evidence = command_details(completed)
            failures.append(
                f"{document.relative_to(root)}: {evidence[0] if evidence else 'validation failed'}"
            )
    if failures:
        details = failures[:DETAIL_LIMIT]
        if len(failures) > DETAIL_LIMIT:
            details.append(f"... {len(failures) - DETAIL_LIMIT} more failing designs")
        details.append(
            "Run: "
            + shlex.join([sys.executable, str(script), "--design", "<failing-design>"])
        )
        return Result(
            "FAIL",
            "designs",
            f"{len(failures)} of {len(documents)} design documents failed",
            tuple(details),
        )
    return Result("PASS", "designs", f"{len(documents)} design documents passed")


def check_delivery_ledgers(root: Path, suite_root: Path) -> Result:
    delivery_root = root / ".nova" / "delivery"
    if not is_inside_project(root, delivery_root):
        return Result("FAIL", "delivery", ".nova/delivery escapes project root")
    ledgers = sorted(delivery_root.glob("REQ-*_v*.json")) if delivery_root.is_dir() else []
    if not ledgers:
        return Result("PASS", "delivery", "delivery ledgers are not present (optional)")
    script = suite_root / "nova-review" / "scripts" / "nova_review.py"
    if not script.is_file():
        return Result("FAIL", "delivery", f"missing delivery validator: {script}")
    try:
        module = load_review_module(script)
    except (OSError, RuntimeError) as exc:
        return Result("FAIL", "delivery", f"cannot load delivery validator: {exc}")
    failures: list[str] = []
    for ledger in ledgers:
        if not is_inside_project(root, ledger):
            failures.append(f"{ledger.relative_to(root)}: path escapes project root")
            continue
        try:
            value = json.loads(ledger.read_text(encoding="utf-8"))
            requirement_ref = value.get("requirement_ref") if isinstance(value, dict) else None
            canonical = module.delivery_relative_path(str(requirement_ref or ""))
            if ledger.relative_to(root).as_posix() != canonical:
                failures.append(
                    f"{ledger.relative_to(root)}: non-canonical delivery ledger path; "
                    f"expected {canonical}"
                )
                continue
            arguments = [
                sys.executable,
                str(script),
                "query-delivery",
                "--repo",
                str(root),
                "--requirement-ref",
                str(requirement_ref or ""),
            ]
            completed = run(arguments, root)
        except Exception as exc:  # The Review validator exposes its own NovaError type.
            failures.append(f"{ledger.relative_to(root)}: {exc}")
            continue
        if completed.returncode != 0:
            evidence = command_details(completed)
            failures.append(
                f"{ledger.relative_to(root)}: "
                f"{evidence[0] if evidence else 'validation failed'}"
            )
    if failures:
        details = failures[:DETAIL_LIMIT]
        if len(failures) > DETAIL_LIMIT:
            details.append(f"... {len(failures) - DETAIL_LIMIT} more failing ledgers")
        details.append(
            "Run: "
            + shlex.join(
                [
                    sys.executable,
                    str(script),
                    "query-delivery",
                    "--repo",
                    str(root),
                    "--requirement-ref",
                    "<REQ-...@vN>",
                ]
            )
        )
        return Result(
            "FAIL",
            "delivery",
            f"{len(failures)} of {len(ledgers)} delivery ledgers failed",
            tuple(details),
        )
    return Result("PASS", "delivery", f"{len(ledgers)} delivery ledgers passed")


def load_review_module(script: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location("nova_doctor_review_support", script)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load Review validator: {script}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def git_message_records(root: Path) -> list[tuple[str, str]]:
    completed = run(
        ["git", "log", "--format=%H%x1f%B%x1e"], root
    )
    if completed.returncode != 0:
        raise ValueError(completed.stderr.strip() or "cannot read Git history")
    records: list[tuple[str, str]] = []
    for raw in completed.stdout.split("\x1e"):
        value = raw.strip("\n")
        if not value or "\x1f" not in value:
            continue
        commit_hash, message = value.split("\x1f", 1)
        records.append((commit_hash, message))
    return records


def check_governance_history(root: Path, suite_root: Path) -> Result:
    review_script = suite_root / "nova-review" / "scripts" / "nova_review.py"
    if not review_script.is_file():
        return Result("FAIL", "governance-history", f"missing validator: {review_script}")
    failures: list[str] = []
    work_item_commits: dict[str, list[tuple[str, dict[str, str]]]] = {}
    schema_2_commits: set[str] = set()
    schema_1_commits: list[str] = []
    checked = 0
    try:
        module = load_review_module(review_script)
        for commit_hash, message in git_message_records(root):
            trailer_keys = {key for key, _ in module.trailing_fields(message)}
            if "Nova-Audit-Schema" in trailer_keys:
                checked += 1
                values, errors = module.parse_audit_message(message)
                errors.extend(module.validate_audit_subject(message, values))
                if values.get("Nova-Audit-Schema") not in {
                    module.LEGACY_AUDIT_SCHEMA,
                    module.AUDIT_SCHEMA,
                }:
                    errors.append("unsupported Nova-Audit-Schema")
                if not errors:
                    diff = module.run_git(
                        root,
                        "show",
                        "--format=",
                        "--binary",
                        "--no-ext-diff",
                        commit_hash,
                    )
                    try:
                        module.validate_audit_snapshot(
                            root,
                            values,
                            diff,
                            lambda path, revision=commit_hash: module.git_blob(
                                root, revision, path
                            ),
                            f"{commit_hash}^",
                            commit_hash,
                        )
                    except Exception as exc:
                        errors.append(str(exc))
                if errors:
                    failures.append(f"{commit_hash[:12]} audit: {'; '.join(errors)}")
                continue
            if not trailer_keys.intersection(
                {"Nova-Schema", "Work-Item", "Commit-Kind", "Change-Class"}
            ):
                continue
            checked += 1
            diff = module.run_git(
                root,
                "show",
                "--format=",
                "--binary",
                "--no-ext-diff",
                commit_hash,
            )
            values, errors = module.validate_committed_message(
                root, commit_hash, message, diff
            )
            if errors:
                failures.append(f"{commit_hash[:12]} commit: {'; '.join(errors)}")
                continue
            if values.get("Nova-Schema") == module.SCHEMA:
                schema_2_commits.add(commit_hash)
            elif values.get("Nova-Schema") == module.LEGACY_SCHEMA:
                schema_1_commits.append(commit_hash)
            work_item = values.get("Work-Item")
            if work_item:
                work_item_commits.setdefault(work_item, []).append((commit_hash, values))

        for commit_hash in schema_1_commits:
            ancestors = run(["git", "rev-list", commit_hash], root)
            if ancestors.returncode != 0:
                raise ValueError(
                    ancestors.stderr.strip()
                    or f"cannot inspect ancestors of {commit_hash}"
                )
            if schema_2_commits.intersection(ancestors.stdout.splitlines()):
                failures.append(
                    f"{commit_hash[:12]} commit: Nova-Schema 1 commit appears "
                    "after schema 2 activation"
                )

        for work_item, commits in work_item_commits.items():
            boundary_errors = module.validate_committed_work_item_boundary(
                root,
                work_item,
                [
                    {"commit": commit_hash, "metadata": values, "errors": []}
                    for commit_hash, values in commits
                ],
            )
            if boundary_errors:
                failures.append(f"{work_item}: {'; '.join(boundary_errors)}")
    except (OSError, UnicodeError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        failures.append(str(exc))
    except Exception as exc:  # The Review validator exposes its own NovaError type.
        failures.append(str(exc))

    if failures:
        details = failures[:DETAIL_LIMIT]
        if len(failures) > DETAIL_LIMIT:
            details.append(f"... {len(failures) - DETAIL_LIMIT} more history failures")
        return Result(
            "FAIL",
            "governance-history",
            f"{len(failures)} commit governance violations found",
            tuple(details),
        )
    schema = "schema 2 active" if schema_2_commits else "legacy schema only"
    return Result(
        "PASS",
        "governance-history",
        f"{checked} Nova commits passed ({schema})",
    )


def check_audit(root: Path, suite_root: Path) -> Result:
    boundary, safe_to_read = nova_boundary(root)
    if not safe_to_read:
        return Result("FAIL", "audit", boundary.message, boundary.details)
    audit_root = root / ".nova" / "audit"
    if not is_inside_project(root, audit_root):
        return Result("FAIL", "audit", ".nova/audit escapes project root")
    if not audit_root.is_dir():
        return Result("PASS", "audit", "audit data is not present (optional)")
    review_script = suite_root / "nova-review" / "scripts" / "nova_review.py"
    if not review_script.is_file():
        return Result("FAIL", "audit", f"missing audit validator: {review_script}")
    try:
        module = load_review_module(review_script)
        transaction_guard = getattr(module, "assert_review_transaction_clean", None)
        if transaction_guard is not None:
            transaction_guard(root)

        def reader(relative: str) -> bytes | None:
            candidate = (root / relative).resolve()
            if not is_inside_project(root, candidate):
                raise ValueError(f"audit reference escapes project root: {relative}")
            return candidate.read_bytes() if candidate.is_file() else None

        index_files = sorted((audit_root / "index").rglob("*.json")) if (audit_root / "index").is_dir() else []
        index_items: set[str] = set()
        audit_cache: dict[str, object] = {}
        for index_file in index_files:
            work_item = index_file.stem
            if work_item in index_items:
                raise ValueError(f"duplicate audit index for {work_item}")
            index_items.add(work_item)
            worktree_completed = module.load_completed_from_reader(root, work_item, reader)
            if worktree_completed is None:
                raise ValueError(f"audit index is incomplete for {work_item}")
            committed_completed = module.load_completed_item(
                root, work_item, audit_cache=audit_cache
            )
            if committed_completed is None or committed_completed != worktree_completed:
                raise ValueError(
                    f"audit records are not backed by one trusted closure commit for {work_item}"
                )

        feature_items: set[str] = set()
        for archive in sorted((audit_root / "features").glob("*.jsonl")) if (audit_root / "features").is_dir() else []:
            for number, line in enumerate(archive.read_text(encoding="utf-8").splitlines(), 1):
                if not line.strip():
                    continue
                record = json.loads(line)
                work_item = str(record.get("work_item", "")) if isinstance(record, dict) else ""
                module.validate_feature_record(record, work_item)
                if work_item in feature_items:
                    raise ValueError(f"duplicate feature record for {work_item}")
                feature_items.add(work_item)

        review_items: set[str] = set()
        review_files = sorted((audit_root / "reviews").rglob("*.yaml")) if (audit_root / "reviews").is_dir() else []
        for review_file in review_files:
            record = module.validate_review_record(
                json.loads(review_file.read_text(encoding="utf-8")), review_file
            )
            for item in record["items"]:
                work_item = item["work_item"]
                if work_item in review_items:
                    raise ValueError(f"duplicate Review item for {work_item}")
                review_items.add(work_item)

        if index_items != feature_items or index_items != review_items:
            raise ValueError(
                "audit work-item sets disagree: "
                f"index={len(index_items)}, feature={len(feature_items)}, review={len(review_items)}"
            )
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError, RuntimeError) as exc:
        return Result("FAIL", "audit", "audit records are inconsistent", (str(exc),))
    except Exception as exc:  # The Review validator exposes its own NovaError type.
        return Result("FAIL", "audit", "audit records are inconsistent", (str(exc),))
    return Result("PASS", "audit", f"{len(index_items)} completed work items are consistent")


MARKDOWN_LINK_START_RE = re.compile(r"!?\[[^\]\n]*\]\(")
MARKDOWN_FENCE_RE = re.compile(r" {0,3}(`{3,}|~{3,})")


def without_inline_code(line: str) -> str:
    characters = list(line)
    offset = 0
    while offset < len(line):
        if line[offset] != "`":
            offset += 1
            continue
        end = offset
        while end < len(line) and line[end] == "`":
            end += 1
        delimiter = line[offset:end]
        closing = end
        while True:
            closing = line.find(delimiter, closing)
            if closing < 0:
                offset = end
                break
            before_is_tick = closing > 0 and line[closing - 1] == "`"
            after = closing + len(delimiter)
            after_is_tick = after < len(line) and line[after] == "`"
            if not before_is_tick and not after_is_tick:
                for index in range(offset, after):
                    characters[index] = " "
                offset = after
                break
            closing = after
    return "".join(characters)


def markdown_prose(text: str) -> str:
    lines: list[str] = []
    fence_character: str | None = None
    fence_length = 0
    for line in text.splitlines():
        fence = MARKDOWN_FENCE_RE.match(line)
        if fence_character is not None:
            if (
                fence is not None
                and fence.group(1)[0] == fence_character
                and len(fence.group(1)) >= fence_length
                and not line[fence.end() :].strip()
            ):
                fence_character = None
                fence_length = 0
            continue
        if fence is not None:
            fence_character = fence.group(1)[0]
            fence_length = len(fence.group(1))
            continue
        if line.startswith(("    ", "\t")):
            continue
        lines.append(without_inline_code(line))
    return "\n".join(lines)


def markdown_link_targets(text: str) -> list[str]:
    targets: list[str] = []
    offset = 0
    while match := MARKDOWN_LINK_START_RE.search(text, offset):
        position = match.end()
        if position < len(text) and text[position] == "<":
            end = position + 1
            while end < len(text) and text[end] != ">":
                end += 2 if text[end] == "\\" and end + 1 < len(text) else 1
            if end < len(text):
                targets.append(text[position + 1 : end])
                closing = text.find(")", end + 1)
                offset = closing + 1 if closing >= 0 else end + 1
                continue

        depth = 0
        target_end: int | None = None
        end = position
        while end < len(text):
            character = text[end]
            if character == "\\" and end + 1 < len(text):
                end += 2
                continue
            if character == "(":
                depth += 1
            elif character == ")":
                if depth == 0:
                    target_end = end if target_end is None else target_end
                    break
                depth -= 1
            elif character.isspace() and depth == 0 and target_end is None:
                target_end = end
            end += 1
        if end >= len(text):
            offset = match.end()
            continue
        raw_target = text[position : target_end if target_end is not None else end]
        targets.append(raw_target)
        offset = end + 1
    return targets


def check_local_links(root: Path) -> Result:
    boundary, safe_to_read = nova_boundary(root)
    if not safe_to_read:
        return Result("FAIL", "references", boundary.message, boundary.details)
    nova_root = root / ".nova"
    if not nova_root.is_dir():
        return Result("FAIL", "references", "missing .nova directory")
    broken: list[str] = []
    for document in sorted(nova_root.rglob("*.md")):
        if not is_inside_project(root, document):
            broken.append(f"{document.relative_to(root)}: path escapes project root")
            continue
        try:
            text = document.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            broken.append(f"{document.relative_to(root)}: {exc}")
            continue
        for raw_target in markdown_link_targets(markdown_prose(text)):
            raw_target = raw_target.strip()
            if not raw_target or raw_target.startswith("#"):
                continue
            if re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", raw_target):
                continue
            path_text = unquote(raw_target.split("#", 1)[0])
            path_text = re.sub(r"\\([\\() ])", r"\1", path_text)
            if not path_text:
                continue
            target = root / path_text.lstrip("/") if path_text.startswith("/.nova/") else document.parent / path_text
            try:
                resolved = target.resolve()
            except OSError as exc:
                broken.append(f"{document.relative_to(root)} -> {raw_target}: {exc}")
                continue
            if not is_inside_project(root, resolved) or not resolved.exists():
                broken.append(f"{document.relative_to(root)} -> {raw_target}")
    if broken:
        details = broken[:DETAIL_LIMIT]
        if len(broken) > DETAIL_LIMIT:
            details.append(f"... {len(broken) - DETAIL_LIMIT} more broken links")
        return Result("FAIL", "references", f"{len(broken)} local Markdown links are broken", tuple(details))
    return Result("PASS", "references", "local Markdown links resolve inside the project")


def diagnose(root: Path, suite_root: Path) -> list[Result]:
    layout, safe_to_read = nova_boundary(root)
    if not safe_to_read:
        return [layout]
    results = [
        layout,
        check_migration(root, suite_root),
        check_blueprint(root, suite_root),
        optional_validator(
            root,
            suite_root,
            ".nova/PRODUCT_REQUIREMENTS.md",
            "nova-requirements/scripts/validate_requirements.py",
            ["--index"],
            "requirements",
            "product requirements",
        ),
        optional_validator(
            root,
            suite_root,
            ".nova/architecture/ARCHITECTURE_CONTRACTS.md",
            "nova-architecture/scripts/validate_architecture.py",
            [],
            "architecture",
            "architecture contracts",
        ),
        optional_validator(
            root,
            suite_root,
            ".nova/SHARED_CAPABILITIES.md",
            "nova-architecture/scripts/validate_shared_capabilities.py",
            [],
            "shared-capabilities",
            "shared capability catalog",
        ),
        check_delivery_ledgers(root, suite_root),
        check_designs(root, suite_root),
        check_governance_history(root, suite_root),
        check_audit(root, suite_root),
        check_local_links(root),
    ]
    return results


def print_report(root: Path, results: list[Result]) -> str:
    print(f"Nova Doctor: {root}")
    for result in results:
        print(f"{result.status} {result.check}: {result.message}")
        for detail in result.details:
            print(f"  {detail}")
    overall = max(results, key=lambda result: STATUS_RANK[result.status]).status
    counts = {status: sum(result.status == status for result in results) for status in STATUS_RANK}
    print(
        f"SUMMARY: {overall} "
        f"({counts['PASS']} passed, {counts['WARN']} warnings, {counts['FAIL']} failed)"
    )
    return overall


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    root, root_result = current_project(Path.cwd())
    if root is None:
        print_report(Path.cwd().resolve(), [root_result])
        return 1
    suite_root = Path(__file__).resolve().parents[2]
    results = [root_result, *diagnose(root, suite_root)]
    return 1 if print_report(root, results) == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
