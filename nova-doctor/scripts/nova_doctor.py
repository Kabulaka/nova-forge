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
        timeout=timeout,
        env=environment,
    )


def current_project(cwd: Path) -> tuple[Path | None, Result]:
    try:
        completed = run(["git", "rev-parse", "--show-toplevel"], cwd)
    except (OSError, subprocess.TimeoutExpired) as exc:
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
    except OSError as exc:
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
    except OSError as exc:
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
    documents = sorted(design_root.rglob("*.md")) if design_root.is_dir() else []
    if not documents:
        return Result("PASS", "designs", "no design documents are present (optional)")
    script = suite_root / "nova-development" / "scripts" / "validate_blueprint.py"
    if not script.is_file():
        return Result("FAIL", "designs", f"missing validator: {script}")
    failures: list[str] = []
    for document in documents:
        arguments = [sys.executable, str(script), "--design", str(document)]
        try:
            completed = run(arguments, root)
        except (OSError, subprocess.TimeoutExpired) as exc:
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


def load_review_module(script: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location("nova_doctor_review_support", script)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load Review validator: {script}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def check_audit(root: Path, suite_root: Path) -> Result:
    audit_root = root / ".nova" / "audit"
    if not audit_root.is_dir():
        return Result("PASS", "audit", "audit data is not present (optional)")
    review_script = suite_root / "nova-review" / "scripts" / "nova_review.py"
    if not review_script.is_file():
        return Result("FAIL", "audit", f"missing audit validator: {review_script}")
    try:
        module = load_review_module(review_script)

        def reader(relative: str) -> bytes | None:
            candidate = (root / relative).resolve()
            if not candidate.is_relative_to(root):
                raise ValueError(f"audit reference escapes project root: {relative}")
            return candidate.read_bytes() if candidate.is_file() else None

        index_files = sorted((audit_root / "index").rglob("*.json")) if (audit_root / "index").is_dir() else []
        index_items: set[str] = set()
        for index_file in index_files:
            work_item = index_file.stem
            if work_item in index_items:
                raise ValueError(f"duplicate audit index for {work_item}")
            index_items.add(work_item)
            if module.load_completed_from_reader(root, work_item, reader) is None:
                raise ValueError(f"audit index is incomplete for {work_item}")

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


MARKDOWN_LINK_RE = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")


def markdown_prose(text: str) -> str:
    lines: list[str] = []
    fence: str | None = None
    for line in text.splitlines():
        marker = line.lstrip()[:3]
        if marker in {"```", "~~~"}:
            fence = None if fence == marker else marker if fence is None else fence
            continue
        if fence is None:
            lines.append(re.sub(r"`[^`\n]*`", "", line))
    return "\n".join(lines)


def check_local_links(root: Path) -> Result:
    nova_root = root / ".nova"
    if not nova_root.is_dir():
        return Result("FAIL", "references", "missing .nova directory")
    broken: list[str] = []
    for document in sorted(nova_root.rglob("*.md")):
        try:
            text = document.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            broken.append(f"{document.relative_to(root)}: {exc}")
            continue
        for match in MARKDOWN_LINK_RE.finditer(markdown_prose(text)):
            raw_target = match.group(1).strip()
            if raw_target.startswith("<") and ">" in raw_target:
                raw_target = raw_target[1 : raw_target.index(">")]
            elif " " in raw_target:
                raw_target = raw_target.split(" ", 1)[0]
            if not raw_target or raw_target.startswith("#"):
                continue
            if re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", raw_target):
                continue
            path_text = unquote(raw_target.split("#", 1)[0])
            if not path_text:
                continue
            target = root / path_text.lstrip("/") if path_text.startswith("/.nova/") else document.parent / path_text
            try:
                resolved = target.resolve()
            except OSError as exc:
                broken.append(f"{document.relative_to(root)} -> {raw_target}: {exc}")
                continue
            if not resolved.is_relative_to(root) or not resolved.exists():
                broken.append(f"{document.relative_to(root)} -> {raw_target}")
    if broken:
        details = broken[:DETAIL_LIMIT]
        if len(broken) > DETAIL_LIMIT:
            details.append(f"... {len(broken) - DETAIL_LIMIT} more broken links")
        return Result("FAIL", "references", f"{len(broken)} local Markdown links are broken", tuple(details))
    return Result("PASS", "references", "local Markdown links resolve inside the project")


def diagnose(root: Path, suite_root: Path) -> list[Result]:
    nova_root = root / ".nova"
    results = [
        Result("PASS", "nova-layout", ".nova directory is present")
        if nova_root.is_dir()
        else Result("FAIL", "nova-layout", "missing .nova directory"),
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
        check_designs(root, suite_root),
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
