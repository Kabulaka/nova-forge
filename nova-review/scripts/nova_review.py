#!/usr/bin/env python3
"""Generate IDs, validate Nova commits, select pending work, and record PASS atomically."""

from __future__ import annotations

import argparse
import ctypes
import errno
import fcntl
import hashlib
import json
import os
import re
import secrets
import subprocess
import sys
import time
import uuid
from collections import defaultdict
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterable


SCHEMA = "1"
TRAILERS = (
    "Nova-Schema",
    "Work-Item",
    "Change-Class",
    "Design-Ref",
    "Review-Policy",
    "Exemption-Rule",
    "Validation",
)
AUDIT_TRAILERS = (
    "Nova-Audit-Schema",
    "Review-Batch",
    "Manifest-SHA256",
    "Validation",
)
WORK_ITEM_PREFIXES = {
    "designed": "PEND",
    "adhoc": "FIX",
    "maintenance": "MAINT",
}
UUID7_PATTERN = r"[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}"
WORK_ITEM_PATTERNS = {
    change_class: re.compile(rf"^{prefix}-(?:[0-9]+|{UUID7_PATTERN})$")
    for change_class, prefix in WORK_ITEM_PREFIXES.items()
}
DESIGN_REF_RE = re.compile(r"^docs/design/[^#\s]+\.md#[A-Za-z0-9][A-Za-z0-9._-]*$")
BATCH_ID_RE = re.compile(r"^NR-[0-9]{8}-[A-Za-z0-9._-]+$")
REPOSITORY_ALIAS_RE = re.compile(r"^[A-Za-z][A-Za-z0-9._-]*$")
DOC_SUFFIXES = {".md", ".txt", ".rst"}
DOC_FORBIDDEN_PARTS = {"test", "tests", "fixture", "fixtures", "scripts", "config"}
DOC_FORBIDDEN_NAMES = {"requirements.txt", "constraints.txt"}
MAP_ROW_RE = re.compile(
    r"^(?P<prefix>\|\s*(?P<id>WP-[A-Za-z0-9._-]+)\s*\|\s*"
    r"(?:(?:能力|收口)\s*\|\s*)?)"
    r"(?P<state>待澄清|澄清中|已确认|开发中|待Review|已完成|已废弃)"
    r"(?P<suffix>\s*\|.*)$"
)
WORK_ITEM_MAP_HEADER = ("工作项", "工作包")
TERMINAL_STATES = {"已完成", "已废弃"}
RENAME_EXCHANGE = 2
RENAME_NOREPLACE = 1
AT_FDCWD = -100


class NovaError(ValueError):
    """A deterministic contract error."""


def run_git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode:
        raise NovaError(result.stderr.strip() or result.stdout.strip() or "git command failed")
    return result.stdout


def run_git_bytes(repo: Path, *args: str, allow_missing: bool = False) -> bytes | None:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=False,
        capture_output=True,
    )
    if result.returncode:
        if allow_missing:
            return None
        message = result.stderr.decode("utf-8", errors="replace").strip()
        if not message:
            message = result.stdout.decode("utf-8", errors="replace").strip()
        raise NovaError(message or "git command failed")
    return result.stdout


def valid_work_item(value: str) -> bool:
    return any(pattern.fullmatch(value) is not None for pattern in WORK_ITEM_PATTERNS.values())


def new_work_item(change_class: str) -> str:
    prefix = WORK_ITEM_PREFIXES.get(change_class)
    if prefix is None:
        raise NovaError(f"unsupported Change-Class: {change_class}")
    timestamp_ms = time.time_ns() // 1_000_000
    value = (
        (timestamp_ms & ((1 << 48) - 1)) << 80
        | 0x7 << 76
        | secrets.randbits(12) << 64
        | 0b10 << 62
        | secrets.randbits(62)
    )
    return f"{prefix}-{uuid.UUID(int=value)}"


def trailing_fields(text: str) -> list[tuple[str, str]]:
    lines = text.rstrip().splitlines()
    fields: list[tuple[str, str]] = []
    for line in reversed(lines):
        match = re.fullmatch(r"([A-Za-z][A-Za-z0-9-]+):[ \t]*(.*?)\s*", line)
        if match is None:
            break
        fields.append((match.group(1), match.group(2)))
    fields.reverse()
    return fields


def parse_message(text: str) -> tuple[dict[str, str], list[str]]:
    found: dict[str, list[str]] = defaultdict(list)
    for key, value in trailing_fields(text):
        if key in TRAILERS or key == "Review-State":
            found[key].append(value)

    errors: list[str] = []
    values: dict[str, str] = {}
    for key in TRAILERS:
        entries = found.get(key, [])
        if len(entries) != 1:
            errors.append(f"{key} must appear exactly once")
        if entries:
            values[key] = entries[0]
    if found.get("Review-State"):
        errors.append("Review-State is mutable and must not appear in a commit")
    return values, errors


def parse_audit_message(text: str) -> tuple[dict[str, str], list[str]]:
    found: dict[str, list[str]] = defaultdict(list)
    standard_found = False
    for key, value in trailing_fields(text):
        if key in set(TRAILERS) - {"Validation"} or key == "Review-State":
            standard_found = True
        if key in AUDIT_TRAILERS:
            found[key].append(value)

    errors: list[str] = []
    values: dict[str, str] = {}
    for key in AUDIT_TRAILERS:
        entries = found.get(key, [])
        if len(entries) != 1:
            errors.append(f"{key} must appear exactly once")
        if entries:
            values[key] = entries[0]
    if standard_found:
        errors.append("audit commits must not contain work-item or Review-State trailers")
    return values, errors


def decode_git_path(value: str) -> str:
    """Decode escapes after the dedicated tokenizer removes outer Git C quotes."""
    decoded = bytearray()
    escapes = {
        "a": 0x07,
        "b": 0x08,
        "t": 0x09,
        "n": 0x0A,
        "v": 0x0B,
        "f": 0x0C,
        "r": 0x0D,
        "\\": 0x5C,
        '"': 0x22,
    }
    index = 0
    while index < len(value):
        character = value[index]
        if character != "\\":
            decoded.extend(character.encode("utf-8"))
            index += 1
            continue
        if index + 1 >= len(value):
            raise NovaError(f"invalid trailing escape in Git path: {value}")
        escaped = value[index + 1]
        octal = value[index + 1 : index + 4]
        if len(octal) == 3 and all(character in "01234567" for character in octal):
            decoded.append(int(octal, 8))
            index += 4
            continue
        if escaped not in escapes:
            raise NovaError(f"invalid escape in Git path: {value}")
        decoded.append(escapes[escaped])
        index += 2
    try:
        return decoded.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise NovaError(f"Git path is not valid UTF-8: {value}") from exc


def git_diff_header_paths(line: str) -> tuple[str, str]:
    payload = line.removeprefix("diff --git ")
    values: list[str] = []
    index = 0
    while len(values) < 2:
        if values:
            if index >= len(payload) or payload[index] != " ":
                raise NovaError(f"invalid diff header: {line}")
            while index < len(payload) and payload[index] == " ":
                index += 1
        if index >= len(payload):
            raise NovaError(f"invalid diff header: {line}")
        if payload[index] != '"':
            end = index
            while end < len(payload) and payload[end] != " ":
                end += 1
            values.append(payload[index:end])
            index = end
            continue
        index += 1
        raw: list[str] = []
        while index < len(payload):
            character = payload[index]
            if character == '"':
                index += 1
                break
            if character == "\\":
                if index + 1 >= len(payload):
                    raise NovaError(f"invalid diff header: {line}")
                raw.extend((character, payload[index + 1]))
                index += 2
                continue
            raw.append(character)
            index += 1
        else:
            raise NovaError(f"invalid diff header: {line}")
        values.append("".join(raw))
    if index != len(payload):
        raise NovaError(f"invalid diff header: {line}")
    return decode_git_path(values[0]), decode_git_path(values[1])


def diff_changes(diff: str) -> list[tuple[str, str]]:
    changes: list[tuple[str, str]] = []
    for line in diff.splitlines():
        if not line.startswith("diff --git "):
            continue
        old_path, new_path = git_diff_header_paths(line)
        if old_path.startswith("a/"):
            old_path = old_path[2:]
        if new_path.startswith("b/"):
            new_path = new_path[2:]
        changes.append((old_path, new_path))
    return changes


def diff_paths(diff: str) -> list[str]:
    return sorted({path for change in diff_changes(diff) for path in change if path != "/dev/null"})


def unsafe_exemption_mode(diff: str) -> bool:
    return re.search(
        r"^(?:old mode|new mode|new file mode|deleted file mode) (?:120000|160000)$"
        r"|^index [0-9a-f]+\.\.[0-9a-f]+ (?:120000|160000)$",
        diff,
        re.MULTILINE,
    ) is not None


def documentation_only_diff(diff: str) -> bool:
    changes = diff_changes(diff)
    if not changes or "GIT binary patch" in diff or unsafe_exemption_mode(diff):
        return False
    for old_path, new_path in changes:
        for value in (old_path, new_path):
            if value == "/dev/null":
                continue
            path = Path(value)
            lowered = {part.lower() for part in path.parts}
            if (
                path.suffix.lower() not in DOC_SUFFIXES
                or path.name.lower() in DOC_FORBIDDEN_NAMES
                or (
                    path.name.lower().startswith("requirements")
                    and path.suffix.lower() == ".txt"
                )
                or lowered & DOC_FORBIDDEN_PARTS
            ):
                return False
    return True


def whitespace_only_diff(diff: str) -> bool:
    changes = diff_changes(diff)
    if (
        not changes
        or unsafe_exemption_mode(diff)
        or "GIT binary patch" in diff
        or any(old != new or old == "/dev/null" for old, new in changes)
        or re.search(
            r"^(?:rename from|rename to|similarity index|new file mode|deleted file mode|old mode|new mode) ",
            diff,
            re.MULTILINE,
        )
    ):
        return False
    files: list[tuple[list[str], list[str]]] = []
    removed: list[str] | None = None
    added: list[str] | None = None
    for line in diff.splitlines():
        if line.startswith("diff --git "):
            if removed is not None and added is not None:
                files.append((removed, added))
            removed, added = [], []
        elif removed is not None and line.startswith("-") and not line.startswith("---"):
            removed.append(line[1:])
        elif added is not None and line.startswith("+") and not line.startswith("+++"):
            added.append(line[1:])
    if removed is not None and added is not None:
        files.append((removed, added))
    if not files or not any(old or new for old, new in files):
        return False
    normalize = lambda lines: re.sub(r"\s+", "", "".join(lines))
    return all(bool(old) and bool(new) and normalize(old) == normalize(new) for old, new in files)


def validate_metadata(values: dict[str, str], diff: str | None = None) -> list[str]:
    errors: list[str] = []
    if values.get("Nova-Schema") != SCHEMA:
        errors.append(f"Nova-Schema must be {SCHEMA}")

    change_class = values.get("Change-Class", "")
    work_item = values.get("Work-Item", "")
    pattern = WORK_ITEM_PATTERNS.get(change_class)
    if pattern is None:
        errors.append("Change-Class must be designed, adhoc, or maintenance")
    elif not pattern.fullmatch(work_item):
        errors.append(f"Work-Item does not match Change-Class {change_class}")

    design_ref = values.get("Design-Ref", "")
    if change_class == "designed":
        if not DESIGN_REF_RE.fullmatch(design_ref):
            errors.append("designed changes require docs/design/*.md#anchor Design-Ref")
    elif design_ref != "none":
        errors.append("adhoc and maintenance changes require Design-Ref: none")

    policy = values.get("Review-Policy", "")
    exemption = values.get("Exemption-Rule", "")
    if policy not in {"required", "exempt"}:
        errors.append("Review-Policy must be required or exempt")
    if change_class in {"designed", "adhoc"} and policy != "required":
        errors.append(f"{change_class} changes always require Review")
    if policy == "required" and exemption != "none":
        errors.append("required Review must use Exemption-Rule: none")
    if policy == "exempt":
        if change_class != "maintenance":
            errors.append("only maintenance changes may be exempt")
        if exemption not in {"EX-DOC", "EX-FORMAT"}:
            errors.append("exempt maintenance requires an allowed EX-* rule")
        if diff is None:
            errors.append("exempt maintenance requires a complete diff")
        elif exemption == "EX-DOC":
            if not documentation_only_diff(diff):
                errors.append(
                    "EX-DOC permits only non-runtime documentation paths on both diff sides"
                )
        elif exemption == "EX-FORMAT" and not whitespace_only_diff(diff):
            errors.append("EX-FORMAT requires a whitespace-only complete diff")

    if re.search(r"\(pass\)\s*$", values.get("Validation", ""), re.IGNORECASE) is None:
        errors.append("Validation must end with (pass)")
    return errors


def validate_message(message: str, diff: str | None = None) -> tuple[dict[str, str], list[str]]:
    values, errors = parse_message(message)
    if not errors:
        errors.extend(validate_metadata(values, diff))
    return values, errors


def scan_commits(
    repo: Path, work_item: str | None = None, revision: str | None = None
) -> list[dict[str, Any]]:
    args = ["log", "--format=%H%x1f%B%x1e"]
    if revision:
        args.append(revision)
    if work_item:
        args.extend(("--fixed-strings", f"--grep=Work-Item: {work_item}"))
    raw = run_git(repo, *args)
    commits: list[dict[str, Any]] = []
    for record in raw.split("\x1e"):
        record = record.strip("\n")
        if not record or "\x1f" not in record:
            continue
        commit_hash, message = record.split("\x1f", 1)
        values, errors = parse_message(message)
        trailer_keys = {key for key, _ in trailing_fields(message)}
        is_nova = bool(
            trailer_keys.intersection({"Nova-Schema", "Work-Item", "Change-Class"})
        )
        if not is_nova:
            continue
        if not errors:
            diff = None
            if values.get("Review-Policy") == "exempt":
                diff = run_git(repo, "show", "--format=", "--no-ext-diff", commit_hash)
            errors.extend(validate_metadata(values, diff))
        commits.append({"commit": commit_hash, "metadata": values, "errors": errors})
    return commits


def feature_index_path(repo: Path, work_item: str) -> Path:
    if not valid_work_item(work_item):
        raise NovaError(f"invalid work item: {work_item}")
    shard = hashlib.sha256(work_item.encode("utf-8")).hexdigest()[:2]
    return repo / "docs" / "audit" / "index" / shard / f"{work_item}.json"


def read_json_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise NovaError(f"invalid {label} {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise NovaError(f"invalid {label} {path}: expected object")
    return value


def read_json_bytes(content: bytes, path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(content.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise NovaError(f"invalid {label} {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise NovaError(f"invalid {label} {path}: expected object")
    return value


def capture_snapshot(snapshots: dict[Path, bytes | None], path: Path) -> bytes | None:
    if path not in snapshots:
        try:
            snapshots[path] = path.read_bytes()
        except FileNotFoundError:
            snapshots[path] = None
    return snapshots[path]


def git_blob(repo: Path, revision: str, relative: str) -> bytes | None:
    if relative.startswith("/") or ".." in Path(relative).parts:
        raise NovaError(f"invalid Git blob path: {relative}")
    return run_git_bytes(
        repo,
        "show",
        f"{revision}:{relative}",
        allow_missing=True,
    )


def compute_review_evidence(
    reviewed_diffs: dict[tuple[str, str], str]
) -> tuple[str, list[str]]:
    hasher = hashlib.sha256()
    scope: set[str] = set()
    for (alias, commit_hash), diff in sorted(reviewed_diffs.items()):
        hasher.update(alias.encode("utf-8") + b"\0")
        hasher.update(commit_hash.encode("ascii") + b"\0")
        hasher.update(diff.encode("utf-8"))
        hasher.update(b"\0")
        scope.update(f"{alias}:{path}" for path in diff_paths(diff))
    return hasher.hexdigest(), sorted(scope)


def valid_commit_ref(value: Any) -> bool:
    return (
        isinstance(value, dict)
        and set(value) == {"repository", "commit"}
        and isinstance(value["repository"], str)
        and REPOSITORY_ALIAS_RE.fullmatch(value["repository"]) is not None
        and isinstance(value["commit"], str)
        and re.fullmatch(r"[0-9a-f]{40,64}", value["commit"]) is not None
    )


def parse_reviewed_at(value: Any, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise NovaError(f"{label} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise NovaError(f"{label} must include a timezone")
    return parsed


def validate_feature_record(record: Any, work_item: str) -> dict[str, Any]:
    fields = {
        "schema",
        "work_item",
        "change_class",
        "design_ref",
        "package_ids",
        "commits",
        "validation",
        "review_batch",
        "completed_at",
    }
    if not isinstance(record, dict) or set(record) != fields:
        raise NovaError(f"invalid feature record fields for {work_item}")
    change_class = record.get("change_class")
    pattern = WORK_ITEM_PATTERNS.get(change_class)
    package_ids = record.get("package_ids")
    if (
        record.get("schema") != 1
        or record.get("work_item") != work_item
        or pattern is None
        or pattern.fullmatch(work_item) is None
        or not isinstance(record.get("validation"), str)
        or not record["validation"].strip()
        or not isinstance(record.get("review_batch"), str)
        or BATCH_ID_RE.fullmatch(record["review_batch"]) is None
        or not isinstance(record.get("commits"), list)
        or not record["commits"]
        or not all(valid_commit_ref(value) for value in record["commits"])
        or len({(value["repository"], value["commit"]) for value in record["commits"]})
        != len(record["commits"])
        or not isinstance(package_ids, list)
        or any(
            not isinstance(value, str)
            or re.fullmatch(r"WP-[A-Za-z0-9._-]+", value) is None
            for value in package_ids
        )
        or len(package_ids) != len(set(package_ids))
    ):
        raise NovaError(f"invalid feature record values for {work_item}")
    if change_class == "designed":
        if not DESIGN_REF_RE.fullmatch(str(record.get("design_ref", ""))) or not package_ids:
            raise NovaError(f"invalid designed feature record for {work_item}")
    elif record.get("design_ref") != "none" or package_ids:
        raise NovaError(f"invalid non-designed feature record for {work_item}")
    completed_at = parse_reviewed_at(record.get("completed_at"), "completed_at")
    if record["review_batch"][3:11] != completed_at.strftime("%Y%m%d"):
        raise NovaError(f"feature batch date mismatch for {work_item}")
    return record


def validate_review_record(record: Any, path: Path) -> dict[str, Any]:
    fields = {
        "schema",
        "batch_id",
        "reviewed_at",
        "reviewer",
        "conclusion",
        "review_round",
        "review_content_sha256",
        "review_scope",
        "manifest_sha256",
        "items",
    }
    if not isinstance(record, dict) or set(record) != fields:
        raise NovaError(f"invalid Review record fields: {path}")
    reviewed_at = parse_reviewed_at(record.get("reviewed_at"), "reviewed_at")
    batch_id = record.get("batch_id")
    if (
        record.get("schema") != 1
        or not isinstance(batch_id, str)
        or BATCH_ID_RE.fullmatch(batch_id) is None
        or batch_id[3:11] != reviewed_at.strftime("%Y%m%d")
        or record.get("conclusion") != "PASS"
        or not isinstance(record.get("review_round"), int)
        or not 1 <= record["review_round"] <= 3
        or re.fullmatch(
            r"[0-9a-f]{64}", str(record.get("review_content_sha256", ""))
        )
        is None
        or not isinstance(record.get("review_scope"), list)
        or not record["review_scope"]
        or any(not isinstance(value, str) or not value for value in record["review_scope"])
        or record["review_scope"] != sorted(set(record["review_scope"]))
        or not isinstance(record.get("reviewer"), str)
        or not record["reviewer"].strip()
        or re.fullmatch(r"[0-9a-f]{64}", str(record.get("manifest_sha256", ""))) is None
        or not isinstance(record.get("items"), list)
        or not record["items"]
    ):
        raise NovaError(f"invalid Review record values: {path}")
    seen: set[str] = set()
    item_fields = {
        "work_item",
        "change_class",
        "design_ref",
        "package_ids",
        "validation",
        "commits",
    }
    for item in record["items"]:
        if not isinstance(item, dict) or set(item) != item_fields:
            raise NovaError(f"invalid Review item fields: {path}")
        feature_shape = {
            "schema": 1,
            **item,
            "review_batch": batch_id,
            "completed_at": record["reviewed_at"],
        }
        validate_feature_record(feature_shape, str(item.get("work_item", "")))
        if item["work_item"] in seen:
            raise NovaError(f"duplicate Review item: {item['work_item']}")
        seen.add(item["work_item"])
    expected_path = Path("docs/audit/reviews") / f"{reviewed_at.year:04d}" / f"{reviewed_at.month:02d}" / f"{batch_id}.yaml"
    if tuple(path.parts[-len(expected_path.parts) :]) != tuple(expected_path.parts):
        raise NovaError(f"Review record path does not match its timestamp and batch: {path}")
    return record


def git_index_blob(repo: Path, relative: str) -> bytes | None:
    if relative.startswith("/") or ".." in Path(relative).parts:
        raise NovaError(f"invalid Git index path: {relative}")
    return run_git_bytes(repo, "show", f":{relative}", allow_missing=True)


def load_completed_from_reader(
    repo: Path,
    work_item: str,
    reader: Callable[[str], bytes | None],
    feature_override: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    index_relative = str(feature_index_path(repo, work_item).relative_to(repo))
    index_path = safe_repo_path(repo, index_relative, "feature index")
    index_bytes = reader(index_relative)
    if index_bytes is None:
        return None
    index = read_json_bytes(index_bytes, index_path, "feature index")
    if set(index) != {"schema", "work_item", "feature_year", "review_path", "review_batch"}:
        raise NovaError(f"invalid feature index fields for {work_item}")
    if (
        index.get("schema") != 1
        or index.get("work_item") != work_item
        or not isinstance(index.get("feature_year"), int)
        or not isinstance(index.get("review_path"), str)
        or not isinstance(index.get("review_batch"), str)
    ):
        raise NovaError(f"invalid feature index values for {work_item}")

    archive_relative = f"docs/audit/features/{index['feature_year']:04d}.jsonl"
    archive = safe_repo_path(repo, archive_relative, "feature archive")
    if feature_override is None:
        feature_matches: list[dict[str, Any]] = []
        archive_bytes = reader(archive_relative)
        if archive_bytes is None:
            raise NovaError(f"feature archive is missing for {work_item}")
        try:
            lines = archive_bytes.decode("utf-8").splitlines()
        except UnicodeError as exc:
            raise NovaError(f"invalid feature archive {archive}: {exc}") from exc
        for line in lines:
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise NovaError(f"invalid feature archive {archive}: {exc}") from exc
            if isinstance(record, dict) and record.get("work_item") == work_item:
                feature_matches.append(record)
        if len(feature_matches) != 1:
            raise NovaError(f"feature archive must contain exactly one record for {work_item}")
        feature = validate_feature_record(feature_matches[0], work_item)
    else:
        feature = validate_feature_record(feature_override, work_item)
    completed_at = parse_reviewed_at(feature["completed_at"], "completed_at")
    if completed_at.year != index["feature_year"]:
        raise NovaError(f"feature index year mismatch for {work_item}")
    if feature["review_batch"] != index["review_batch"]:
        raise NovaError(f"feature index batch mismatch for {work_item}")

    review_path = safe_repo_path(repo, index["review_path"], "review_path")
    expected_review_path = review_path_for_values(repo, completed_at, index["review_batch"])
    if review_path != expected_review_path:
        raise NovaError(f"feature index Review path mismatch for {work_item}")
    review_bytes = reader(index["review_path"])
    if review_bytes is None:
        raise NovaError(f"Review record is missing for {work_item}")
    review = validate_review_record(
        read_json_bytes(review_bytes, review_path, "Review record"), review_path
    )
    if review["batch_id"] != index["review_batch"] or review["reviewed_at"] != feature["completed_at"]:
        raise NovaError(f"feature and Review batch metadata disagree for {work_item}")
    review_items = [item for item in review["items"] if isinstance(item, dict) and item.get("work_item") == work_item]
    if len(review_items) != 1:
        raise NovaError(f"Review record must contain exactly one item for {work_item}")
    review_item = review_items[0]
    expected_feature = {
        "schema": 1,
        **review_item,
        "review_batch": review["batch_id"],
        "completed_at": review["reviewed_at"],
    }
    if feature != expected_feature:
        raise NovaError(f"feature and Review records disagree for {work_item}")
    return feature, review_item


def added_feature_records(diff: str, archive_relative: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    in_archive = False
    for line in diff.splitlines():
        if line.startswith("diff --git "):
            changes = diff_changes(line)
            in_archive = bool(changes and archive_relative in changes[0])
            continue
        if not in_archive or not line.startswith("+") or line.startswith("+++"):
            continue
        try:
            value = json.loads(line[1:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            records.append(value)
    return records


def validate_recorded_commits(
    repo: Path,
    review: dict[str, Any],
    revision: str,
) -> None:
    reviewed_diffs: dict[tuple[str, str], str] = {}
    has_external = False
    for item in review["items"]:
        work_item = item["work_item"]
        provided_main: set[str] = set()
        for commit_ref in item["commits"]:
            alias = commit_ref["repository"]
            if alias != "main":
                has_external = True
                continue
            commit_hash = resolve_commit(repo, commit_ref["commit"])
            if commit_hash != commit_ref["commit"]:
                raise NovaError(f"non-canonical reviewed commit for {work_item}")
            message = run_git(repo, "show", "-s", "--format=%B", commit_hash)
            diff = run_git(repo, "show", "--format=", "--binary", "--no-ext-diff", commit_hash)
            metadata, errors = validate_message(message, diff)
            if errors:
                raise NovaError(f"invalid reviewed commit {commit_hash}: " + "; ".join(errors))
            expected = (work_item, item["change_class"], item["design_ref"], "required")
            actual = (
                metadata.get("Work-Item"),
                metadata.get("Change-Class"),
                metadata.get("Design-Ref"),
                metadata.get("Review-Policy"),
            )
            if actual != expected:
                raise NovaError(f"reviewed commit metadata mismatch for {commit_hash}")
            provided_main.add(commit_hash)
            reviewed_diffs[("main", commit_hash)] = diff

        required_main: set[str] = set()
        for entry in scan_commits(repo, work_item, revision):
            metadata = entry["metadata"]
            if metadata.get("Work-Item") != work_item:
                continue
            if entry["errors"]:
                raise NovaError(
                    f"invalid trailers in {entry['commit']}: " + "; ".join(entry["errors"])
                )
            if metadata.get("Review-Policy") != "required":
                continue
            if (metadata.get("Change-Class"), metadata.get("Design-Ref")) != (
                item["change_class"],
                item["design_ref"],
            ):
                raise NovaError(f"inconsistent required commit metadata for {work_item}")
            required_main.add(entry["commit"])
        if provided_main != required_main:
            raise NovaError(
                f"audit commit coverage mismatch for {work_item}; "
                f"missing={sorted(required_main - provided_main)}; "
                f"extra={sorted(provided_main - required_main)}"
            )

    _, main_scope = compute_review_evidence(reviewed_diffs)
    recorded_main_scope = sorted(
        value for value in review["review_scope"] if value.startswith("main:")
    )
    if recorded_main_scope != main_scope:
        raise NovaError("Review scope does not match the committed main-repository diffs")
    if not has_external:
        digest, scope = compute_review_evidence(reviewed_diffs)
        if review["review_content_sha256"] != digest or review["review_scope"] != scope:
            raise NovaError("Review content evidence does not match the committed diffs")


def expected_audit_snapshot(
    repo: Path,
    review: dict[str, Any],
    review_relative: str,
    parent_reader: Callable[[str], bytes | None],
) -> dict[str, bytes]:
    """Derive the only valid closure bytes from the audit commit's parent."""
    text_updates: dict[str, str] = {}

    for item in review["items"]:
        if item["change_class"] != "designed":
            continue
        blueprint_relative = "PROJECT_BLUEPRINT.md"
        design_relative = item["design_ref"].split("#", 1)[0]
        blueprint = text_updates.get(blueprint_relative)
        if blueprint is None:
            blueprint_bytes = parent_reader(blueprint_relative)
            if blueprint_bytes is None:
                raise NovaError(f"audit parent lacks blueprint for {item['work_item']}")
            blueprint = blueprint_bytes.decode("utf-8")
        design = text_updates.get(design_relative)
        if design is None:
            design_bytes = parent_reader(design_relative)
            if design_bytes is None:
                raise NovaError(f"audit parent lacks design for {item['work_item']}")
            design = design_bytes.decode("utf-8")
        anchor = item["design_ref"].split("#", 1)[1]
        authoritative = authoritative_package_ids(
            blueprint,
            design,
            design_relative,
            item["work_item"],
            anchor,
        )
        if item["package_ids"] != authoritative:
            raise NovaError(
                f"audit package_ids do not match the parent closure map for "
                f"{item['work_item']}; expected={authoritative}; "
                f"actual={item['package_ids']}"
            )
        text_updates[blueprint_relative] = remove_blueprint_row(
            blueprint, item["work_item"], item["design_ref"]
        )
        text_updates[design_relative] = complete_design_packages(
            design, item["package_ids"], anchor
        )

    reviewed_at = parse_reviewed_at(review["reviewed_at"], "reviewed_at")
    archive_relative = f"docs/audit/features/{reviewed_at.year:04d}.jsonl"
    archive_bytes = parent_reader(archive_relative)
    archive = archive_bytes.decode("utf-8") if archive_bytes is not None else ""
    records = [
        json.dumps(
            feature_record(item, review["batch_id"], review["reviewed_at"]),
            ensure_ascii=False,
            sort_keys=True,
        )
        for item in review["items"]
    ]
    text_updates[archive_relative] = (
        archive
        + ("" if not archive or archive.endswith("\n") else "\n")
        + "\n".join(records)
        + "\n"
    )

    if parent_reader(review_relative) is not None:
        raise NovaError("Review record already existed in the audit parent")
    text_updates[review_relative] = (
        json.dumps(review, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    )
    for item in review["items"]:
        index_relative = str(feature_index_path(repo, item["work_item"]).relative_to(repo))
        if parent_reader(index_relative) is not None:
            raise NovaError(f"feature index already existed in audit parent: {item['work_item']}")
        index = {
            "schema": 1,
            "work_item": item["work_item"],
            "feature_year": reviewed_at.year,
            "review_path": review_relative,
            "review_batch": review["batch_id"],
        }
        text_updates[index_relative] = (
            json.dumps(index, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        )
    return {path: content.encode("utf-8") for path, content in text_updates.items()}


def git_path_mode(repo: Path, revision: str | None, relative: str) -> str | None:
    if revision is None:
        output = run_git(repo, "ls-files", "--stage", "--", relative)
        lines = [line for line in output.splitlines() if line]
        if not lines:
            return None
        if len(lines) != 1 or " 0\t" not in lines[0]:
            raise NovaError(f"audit index has unresolved stages for {relative}")
        return lines[0].split(" ", 1)[0]
    output = run_git(repo, "ls-tree", revision, "--", relative)
    lines = [line for line in output.splitlines() if line]
    if not lines:
        return None
    if len(lines) != 1:
        raise NovaError(f"audit tree has ambiguous path: {relative}")
    return lines[0].split(" ", 1)[0]


def validate_audit_snapshot(
    repo: Path,
    values: dict[str, str],
    diff: str,
    reader: Callable[[str], bytes | None],
    revision: str,
    target_revision: str | None = None,
) -> dict[str, tuple[dict[str, Any], dict[str, Any]]]:
    changed = set(diff_paths(diff))
    batch_id = values["Review-Batch"]
    review_paths = sorted(
        path
        for path in changed
        if re.fullmatch(
            rf"docs/audit/reviews/[0-9]{{4}}/[0-9]{{2}}/{re.escape(batch_id)}\.yaml",
            path,
        )
    )
    if len(review_paths) != 1:
        raise NovaError("audit diff must contain exactly one matching Review record")
    review_path = safe_repo_path(repo, review_paths[0], "Review record")
    review_bytes = reader(review_paths[0])
    if review_bytes is None:
        raise NovaError("matching Review record is absent from the validated Git snapshot")
    review = validate_review_record(
        read_json_bytes(review_bytes, review_path, "Review record"), review_path
    )
    if review["batch_id"] != batch_id:
        raise NovaError("Review-Batch does not match Review record")
    if review["manifest_sha256"] != values["Manifest-SHA256"]:
        raise NovaError("Manifest-SHA256 does not match Review record")

    expected_bytes = expected_audit_snapshot(
        repo,
        review,
        review_paths[0],
        lambda path: git_blob(repo, revision, path),
    )
    if changed != set(expected_bytes):
        raise NovaError(
            "audit diff does not exactly match the derived closure paths; "
            f"missing={sorted(set(expected_bytes) - changed)}; "
            f"extra={sorted(changed - set(expected_bytes))}"
        )
    for relative, content in expected_bytes.items():
        if reader(relative) != content:
            raise NovaError(f"audit closure output differs from the derived bytes: {relative}")
        parent_mode = git_path_mode(repo, revision, relative)
        target_mode = git_path_mode(repo, target_revision, relative)
        expected_mode = parent_mode if parent_mode is not None else "100644"
        if target_mode != expected_mode:
            raise NovaError(
                f"audit closure mode differs from the derived transition: {relative}"
            )

    reviewed_at = parse_reviewed_at(review["reviewed_at"], "reviewed_at")
    archive_relative = f"docs/audit/features/{reviewed_at.year:04d}.jsonl"
    added_features = added_feature_records(diff, archive_relative)
    expected = {
        review_paths[0],
        archive_relative,
    }
    designed = False
    completed_items: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
    for item in review["items"]:
        work_item = item["work_item"]
        feature_matches = [
            value for value in added_features if value.get("work_item") == work_item
        ]
        if len(feature_matches) != 1:
            raise NovaError(
                f"audit diff must add exactly one feature record for {work_item}"
            )
        completed = load_completed_from_reader(
            repo, work_item, reader, feature_matches[0]
        )
        if completed is None or completed[1] != item:
            raise NovaError(f"audit records are incomplete for {work_item}")
        completed_items[work_item] = completed
        expected.add(str(feature_index_path(repo, work_item).relative_to(repo)))
        if item["change_class"] != "designed":
            continue
        designed = True
        design_relative = item["design_ref"].split("#", 1)[0]
        expected.add(design_relative)
        design_bytes = reader(design_relative)
        blueprint_bytes = reader("PROJECT_BLUEPRINT.md")
        if design_bytes is None or blueprint_bytes is None:
            raise NovaError(f"closed design documents are missing for {work_item}")
        blueprint = blueprint_bytes.decode("utf-8")
        if re.search(rf"^\|\s*{re.escape(work_item)}\s*\|", blueprint, re.MULTILINE):
            raise NovaError(f"audit snapshot still contains blueprint row for {work_item}")
        design = design_bytes.decode("utf-8")
        for package_id in item["package_ids"]:
            if design_package_state(design, package_id) != "已完成":
                raise NovaError(f"audit snapshot package is not complete: {package_id}")
    if designed:
        expected.add("PROJECT_BLUEPRINT.md")
    if changed != expected:
        raise NovaError(
            f"audit diff path mismatch; missing={sorted(expected - changed)}; "
            f"extra={sorted(changed - expected)}"
        )
    for path in changed:
        safe_repo_path(repo, path, "audit diff path")
        if path == archive_relative:
            continue
        if reader(path) is None:
            raise NovaError(f"audit snapshot lacks changed path: {path}")
    validate_recorded_commits(repo, review, revision)
    return completed_items


def load_completed_item(
    repo: Path,
    work_item: str,
    expected_feature: dict[str, Any] | None = None,
    audit_cache: dict[
        str, dict[str, tuple[dict[str, Any], dict[str, Any]]]
    ] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    index_relative = str(feature_index_path(repo, work_item).relative_to(repo))
    commits = run_git(repo, "log", "-1", "--format=%H", "--", index_relative).splitlines()
    if not commits:
        return None
    audit_commit = commits[0].strip()
    if not audit_commit:
        return None
    message = run_git(repo, "show", "-s", "--format=%B", audit_commit)
    values, errors = parse_audit_message(message)
    if not errors:
        if values.get("Nova-Audit-Schema") != SCHEMA:
            errors.append(f"Nova-Audit-Schema must be {SCHEMA}")
        if BATCH_ID_RE.fullmatch(values.get("Review-Batch", "")) is None:
            errors.append("Review-Batch must match NR-YYYYMMDD-<suffix>")
        if re.fullmatch(r"[0-9a-f]{64}", values.get("Manifest-SHA256", "")) is None:
            errors.append("Manifest-SHA256 must be 64 lowercase hexadecimal characters")
        if re.search(r"\(pass\)\s*$", values.get("Validation", ""), re.IGNORECASE) is None:
            errors.append("Validation must end with (pass)")
    if errors:
        raise NovaError(f"invalid audit commit {audit_commit}: " + "; ".join(errors))
    completed_items = audit_cache.get(audit_commit) if audit_cache is not None else None
    if completed_items is None:
        diff = run_git(repo, "show", "--format=", "--binary", "--no-ext-diff", audit_commit)
        reader = lambda path: git_blob(repo, audit_commit, path)
        completed_items = validate_audit_snapshot(
            repo, values, diff, reader, f"{audit_commit}^", audit_commit
        )
        if audit_cache is not None:
            audit_cache[audit_commit] = completed_items
    completed = completed_items.get(work_item)
    if completed is None:
        raise NovaError(f"audit commit lacks indexed work item: {work_item}")
    if expected_feature is not None and completed[0] != expected_feature:
        raise NovaError(f"year archive and audit commit disagree for {work_item}")
    return completed


def validate_audit_message(
    repo: Path, message: str, diff: str
) -> tuple[dict[str, str], list[str]]:
    values, errors = parse_audit_message(message)
    if errors:
        return values, errors
    if values.get("Nova-Audit-Schema") != SCHEMA:
        errors.append(f"Nova-Audit-Schema must be {SCHEMA}")
    batch_id = values.get("Review-Batch", "")
    if BATCH_ID_RE.fullmatch(batch_id) is None:
        errors.append("Review-Batch must match NR-YYYYMMDD-<suffix>")
    digest = values.get("Manifest-SHA256", "")
    if re.fullmatch(r"[0-9a-f]{64}", digest) is None:
        errors.append("Manifest-SHA256 must be 64 lowercase hexadecimal characters")
    if re.search(r"\(pass\)\s*$", values.get("Validation", ""), re.IGNORECASE) is None:
        errors.append("Validation must end with (pass)")
    staged = run_git(repo, "diff", "--cached", "--binary", "--no-ext-diff")
    if diff != staged:
        errors.append("audit diff must exactly match the repository staged diff")
        return values, errors
    if errors:
        return values, errors
    try:
        validate_audit_snapshot(repo, values, diff, lambda path: git_index_blob(repo, path), "HEAD")
    except (NovaError, OSError, UnicodeError, json.JSONDecodeError) as exc:
        errors.append(str(exc))
    return values, errors


def reviewed_commits(repo: Path, work_items: set[str] | None = None) -> set[str]:
    if work_items is None:
        index_root = safe_repo_path(repo, "docs/audit/index", "feature index directory")
        work_items = {path.stem for path in index_root.glob("[0-9a-f][0-9a-f]/*.json")}
    result: set[str] = set()
    for work_item in work_items:
        completed = load_completed_item(repo, work_item)
        if completed is None:
            continue
        feature, _ = completed
        result.update(
            ref["commit"] for ref in feature["commits"] if ref["repository"] == "main"
        )
    return result


def select_pending(
    repo: Path,
    mode: str,
    session_items: set[str],
    explicit_items: set[str],
) -> list[dict[str, Any]]:
    if mode == "current" and not session_items:
        raise NovaError("current mode requires at least one --session-item")
    if mode == "explicit" and not explicit_items:
        raise NovaError("explicit mode requires at least one --work-item")

    target_items = session_items if mode == "current" else explicit_items if mode == "explicit" else None
    reviewed = reviewed_commits(repo, target_items)
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    if target_items is None:
        commits = scan_commits(repo)
    else:
        commits = []
        seen_commits: set[str] = set()
        for target in sorted(target_items):
            for entry in scan_commits(repo, target):
                if entry["commit"] not in seen_commits:
                    seen_commits.add(entry["commit"])
                    commits.append(entry)
    for entry in reversed(commits):
        metadata = entry["metadata"]
        work_item = metadata.get("Work-Item", "")
        if mode == "current" and work_item not in session_items:
            continue
        if mode == "explicit" and work_item not in explicit_items:
            continue
        if entry["errors"]:
            raise NovaError(
                f"invalid trailers in {entry['commit']}: " + "; ".join(entry["errors"])
            )
        if entry["commit"] in reviewed or metadata.get("Review-Policy") != "required":
            continue
        grouped[work_item].append(entry)

    if mode == "explicit":
        missing = explicit_items - grouped.keys()
        if missing:
            raise NovaError("no unreviewed required commits for: " + ", ".join(sorted(missing)))

    selected: list[dict[str, Any]] = []
    for work_item in sorted(grouped):
        entries = grouped[work_item]
        first = entries[0]["metadata"]
        identity = (first.get("Change-Class"), first.get("Design-Ref"))
        if any(
            (entry["metadata"].get("Change-Class"), entry["metadata"].get("Design-Ref"))
            != identity
            for entry in entries
        ):
            raise NovaError(f"inconsistent metadata across commits for {work_item}")
        selected.append(
            {
                "work_item": work_item,
                "change_class": identity[0],
                "design_ref": identity[1],
                "commits": [entry["commit"] for entry in entries],
                "validation": [entry["metadata"].get("Validation") for entry in entries],
            }
        )
    return selected


def canonical_manifest(manifest: dict[str, Any]) -> bytes:
    return json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )


def reject_symlink_components(repo: Path, candidate: Path, field: str) -> None:
    repo = repo.resolve()
    try:
        relative = candidate.absolute().relative_to(repo)
    except ValueError as exc:
        raise NovaError(f"{field} must stay inside repository") from exc
    current = repo
    for part in relative.parts:
        current = current / part
        try:
            mode = os.lstat(current).st_mode
        except FileNotFoundError:
            continue
        if os.path.islink(current):
            raise NovaError(f"{field} must not traverse a symlink: {current}")
        if current != candidate and not os.path.isdir(current):
            raise NovaError(f"{field} parent is not a directory: {current}")


def safe_repo_path(repo: Path, value: str, field: str) -> Path:
    candidate = Path(os.path.abspath(repo / value))
    try:
        candidate.relative_to(repo.resolve())
    except ValueError as exc:
        raise NovaError(f"{field} must stay inside repository") from exc
    reject_symlink_components(repo, candidate, field)
    return candidate


def resolve_commit(repo: Path, value: str) -> str:
    if not isinstance(value, str) or not value:
        raise NovaError("commit must be a non-empty string")
    return run_git(
        repo, "rev-parse", "--verify", "--end-of-options", f"{value}^{{commit}}"
    ).strip()


def manifest_repositories(primary_repo: Path, manifest: dict[str, Any]) -> dict[str, Path]:
    configured = manifest.get("repositories", {"main": "."})
    if not isinstance(configured, dict) or not configured:
        raise NovaError("repositories must be a non-empty object")
    repositories: dict[str, Path] = {}
    for alias, location in configured.items():
        if not isinstance(alias, str) or not REPOSITORY_ALIAS_RE.fullmatch(alias):
            raise NovaError(f"invalid repository alias: {alias}")
        if not isinstance(location, str) or not location:
            raise NovaError(f"repository path must not be empty: {alias}")
        path = Path(location)
        if not path.is_absolute():
            path = primary_repo / path
        path = path.resolve()
        top_level = Path(run_git(path, "rev-parse", "--show-toplevel").strip()).resolve()
        if top_level != path:
            raise NovaError(f"repository alias must target a Git root: {alias}")
        repositories[alias] = path
    if repositories.get("main") != primary_repo.resolve():
        raise NovaError("repositories.main must target the primary repository")
    return repositories


def normalize_commit_refs(
    values: Any, repositories: dict[str, Path], work_item: str
) -> list[dict[str, str]]:
    if not isinstance(values, list) or not values:
        raise NovaError(f"commits must be non-empty for {work_item}")
    normalized: list[dict[str, str]] = []
    for value in values:
        if isinstance(value, str):
            alias, commit_value = "main", value
        elif isinstance(value, dict) and set(value) == {"repository", "commit"}:
            alias, commit_value = value["repository"], value["commit"]
        else:
            raise NovaError(f"invalid commit reference for {work_item}")
        if alias not in repositories:
            raise NovaError(f"unknown repository alias for {work_item}: {alias}")
        full_hash = resolve_commit(repositories[alias], commit_value)
        normalized.append({"repository": alias, "commit": full_hash})
    identities = {(value["repository"], value["commit"]) for value in normalized}
    if len(identities) != len(normalized):
        raise NovaError(f"duplicate commit for {work_item}")
    return normalized


def load_manifest(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise NovaError(f"cannot read manifest: {exc}") from exc
    if not isinstance(value, dict):
        raise NovaError("manifest must be a JSON object")
    return value


def review_path_for_values(repo: Path, reviewed_at: datetime, batch_id: str) -> Path:
    return repo / "docs" / "audit" / "reviews" / f"{reviewed_at.year:04d}" / f"{reviewed_at.month:02d}" / f"{batch_id}.yaml"


def feature_path(repo: Path, reviewed_at: datetime) -> Path:
    return repo / "docs" / "audit" / "features" / f"{reviewed_at.year:04d}.jsonl"


def feature_record(item: dict[str, Any], batch_id: str, completed_at: str) -> dict[str, Any]:
    return {
        "schema": 1,
        "work_item": item["work_item"],
        "change_class": item["change_class"],
        "design_ref": item["design_ref"],
        "package_ids": item.get("package_ids", []),
        "commits": item["commits"],
        "validation": item["validation"],
        "review_batch": batch_id,
        "completed_at": completed_at,
    }


def review_record_data(
    manifest: dict[str, Any], digest: str, items: list[dict[str, Any]]
) -> dict[str, Any]:
    return {
        "schema": 1,
        "batch_id": manifest["batch_id"],
        "reviewed_at": manifest["reviewed_at"],
        "reviewer": manifest["reviewer"],
        "conclusion": "PASS",
        "review_round": manifest["review_round"],
        "review_content_sha256": manifest["review_content_sha256"],
        "review_scope": manifest["review_scope"],
        "manifest_sha256": digest,
        "items": [
            {
                "work_item": item["work_item"],
                "change_class": item["change_class"],
                "design_ref": item["design_ref"],
                "package_ids": item.get("package_ids", []),
                "validation": item["validation"],
                "commits": item["commits"],
            }
            for item in items
        ],
    }


def feature_index_record(
    repo: Path, item: dict[str, Any], reviewed_at: datetime, batch_id: str, output: Path
) -> dict[str, Any]:
    return {
        "schema": 1,
        "work_item": item["work_item"],
        "feature_year": reviewed_at.year,
        "review_path": str(output.relative_to(repo)),
        "review_batch": batch_id,
    }


def validate_manifest(repo: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    allowed_manifest_fields = {
        "schema",
        "batch_id",
        "reviewed_at",
        "reviewer",
        "conclusion",
        "review_round",
        "review_content_sha256",
        "review_scope",
        "repositories",
        "items",
    }
    required_manifest_fields = allowed_manifest_fields - {"repositories"}
    if not required_manifest_fields.issubset(manifest) or not set(manifest).issubset(
        allowed_manifest_fields
    ):
        raise NovaError("manifest has missing or unknown fields")
    if manifest.get("schema") != 1:
        raise NovaError("manifest schema must be 1")
    batch_id = manifest.get("batch_id")
    if not isinstance(batch_id, str) or not BATCH_ID_RE.fullmatch(batch_id):
        raise NovaError("batch_id must match NR-YYYYMMDD-<suffix>")
    reviewed_at = parse_reviewed_at(manifest.get("reviewed_at"), "reviewed_at")
    if batch_id[3:11] != reviewed_at.strftime("%Y%m%d"):
        raise NovaError("batch_id date must match reviewed_at")
    if not isinstance(manifest.get("reviewer"), str) or not manifest["reviewer"].strip():
        raise NovaError("reviewer must not be empty")
    if manifest.get("conclusion") != "PASS":
        raise NovaError("record-pass accepts only conclusion PASS")
    if not isinstance(manifest.get("review_round"), int) or not 1 <= manifest["review_round"] <= 3:
        raise NovaError("review_round must be an integer from 1 to 3")
    if re.fullmatch(r"[0-9a-f]{64}", str(manifest.get("review_content_sha256", ""))) is None:
        raise NovaError("review_content_sha256 must be 64 lowercase hexadecimal characters")
    if (
        not isinstance(manifest.get("review_scope"), list)
        or not manifest["review_scope"]
        or any(not isinstance(value, str) or not value for value in manifest["review_scope"])
        or manifest["review_scope"] != sorted(set(manifest["review_scope"]))
    ):
        raise NovaError("review_scope must be a sorted unique non-empty string list")
    items = manifest.get("items")
    if not isinstance(items, list) or not items:
        raise NovaError("manifest items must be a non-empty list")
    repositories = manifest_repositories(repo, manifest)
    snapshots: dict[Path, bytes | None] = {}

    digest = hashlib.sha256(canonical_manifest(manifest)).hexdigest()
    output = safe_repo_path(
        repo,
        str(review_path_for_values(repo, reviewed_at, batch_id).relative_to(repo)),
        "review output",
    )
    output_snapshot = capture_snapshot(snapshots, output)
    existing_batch = output_snapshot is not None

    seen_items: set[str] = set()
    normalized_items: list[dict[str, Any]] = []
    reviewed_diffs: dict[tuple[str, str], str] = {}
    for item in items:
        if not isinstance(item, dict):
            raise NovaError("each manifest item must be an object")
        work_item = item.get("work_item")
        change_class = item.get("change_class")
        pattern = WORK_ITEM_PATTERNS.get(change_class)
        if not isinstance(work_item, str) or pattern is None or not pattern.fullmatch(work_item):
            raise NovaError(f"invalid work item/class combination: {work_item}/{change_class}")
        if work_item in seen_items:
            raise NovaError(f"duplicate work item in manifest: {work_item}")
        seen_items.add(work_item)
        validation = item.get("validation")
        if not isinstance(validation, str) or re.search(
            r"\(pass\)\s*$", validation, re.IGNORECASE
        ) is None:
            raise NovaError(f"validation must end with (pass) for {work_item}")
        commit_refs = normalize_commit_refs(item.get("commits"), repositories, work_item)

        design_ref = item.get("design_ref")
        for commit_ref in commit_refs:
            commit_repo = repositories[commit_ref["repository"]]
            commit_hash = commit_ref["commit"]
            message = run_git(commit_repo, "show", "-s", "--format=%B", commit_hash)
            diff = run_git(
                commit_repo, "show", "--format=", "--binary", "--no-ext-diff", commit_hash
            )
            reviewed_diffs[(commit_ref["repository"], commit_hash)] = diff
            metadata, errors = validate_message(message, diff)
            if errors:
                raise NovaError(f"invalid commit {commit_hash}: " + "; ".join(errors))
            expected = (work_item, change_class, design_ref)
            actual = (
                metadata.get("Work-Item"),
                metadata.get("Change-Class"),
                metadata.get("Design-Ref"),
            )
            if actual != expected:
                raise NovaError(f"commit metadata mismatch for {commit_hash}")
            if metadata.get("Review-Policy") != "required":
                raise NovaError(f"manifest commit does not require Review: {commit_hash}")

        provided_commits = {
            (value["repository"], value["commit"]) for value in commit_refs
        }
        required_commits: set[tuple[str, str]] = set()
        for alias, commit_repo in repositories.items():
            for entry in scan_commits(commit_repo, work_item):
                metadata = entry["metadata"]
                if metadata.get("Work-Item") != work_item:
                    continue
                if entry["errors"]:
                    raise NovaError(
                        f"invalid trailers in {entry['commit']}: "
                        + "; ".join(entry["errors"])
                    )
                if metadata.get("Review-Policy") != "required":
                    continue
                if (
                    metadata.get("Change-Class"),
                    metadata.get("Design-Ref"),
                ) != (change_class, design_ref):
                    raise NovaError(f"inconsistent required commit metadata for {work_item}")
                required_commits.add((alias, entry["commit"]))
        if provided_commits != required_commits:
            missing = sorted(required_commits - provided_commits)
            extra = sorted(provided_commits - required_commits)
            raise NovaError(
                f"manifest commit coverage mismatch for {work_item}; "
                f"missing={missing}; extra={extra}"
            )

        normalized = dict(item)
        normalized["commits"] = commit_refs
        if change_class == "designed":
            expected_fields = {
                "work_item",
                "change_class",
                "commits",
                "validation",
                "design_ref",
                "blueprint",
                "design_file",
                "package_ids",
            }
            if set(item) != expected_fields:
                raise NovaError(f"designed item has missing or unknown fields: {work_item}")
            if not isinstance(design_ref, str) or not DESIGN_REF_RE.fullmatch(design_ref):
                raise NovaError(f"invalid design_ref for {work_item}")
            for field in ("blueprint", "design_file"):
                if not isinstance(item.get(field), str) or not item[field]:
                    raise NovaError(f"{field} is required for {work_item}")
            package_ids = item.get("package_ids")
            if (
                not isinstance(package_ids, list)
                or not package_ids
                or any(
                    not isinstance(value, str)
                    or re.fullmatch(r"WP-[A-Za-z0-9._-]+", value) is None
                    for value in package_ids
                )
                or len(package_ids) != len(set(package_ids))
            ):
                raise NovaError(f"package_ids must contain unique WP-* values for {work_item}")
            expected_ref = f"{item['design_file']}#{design_ref.split('#', 1)[1]}"
            if design_ref != expected_ref:
                raise NovaError(f"design_ref and design_file mismatch for {work_item}")
            if item["blueprint"] != "PROJECT_BLUEPRINT.md":
                raise NovaError(f"blueprint must be PROJECT_BLUEPRINT.md for {work_item}")
            normalized["blueprint_path"] = safe_repo_path(repo, item["blueprint"], "blueprint")
            normalized["design_path"] = safe_repo_path(repo, item["design_file"], "design_file")
            if existing_batch:
                # The first successful close already removed the blueprint row. The
                # immutable Review/feature records below are the authority for an
                # idempotent replay, while package state is checked after loading them.
                normalized["package_ids"] = package_ids
            else:
                blueprint_bytes = capture_snapshot(snapshots, normalized["blueprint_path"])
                design_bytes = capture_snapshot(snapshots, normalized["design_path"])
                if blueprint_bytes is None or design_bytes is None:
                    raise NovaError(f"blueprint and design must exist for {work_item}")
                blueprint = blueprint_bytes.decode("utf-8")
                design = design_bytes.decode("utf-8")
                authoritative = authoritative_package_ids(
                    blueprint,
                    design,
                    item["design_file"],
                    work_item,
                    design_ref.split("#", 1)[1],
                )
                if package_ids != authoritative:
                    raise NovaError(
                        f"package_ids must exactly match the design closure map for {work_item}; "
                        f"expected={authoritative}; actual={package_ids}"
                    )
                normalized["package_ids"] = authoritative
        else:
            expected_fields = {
                "work_item",
                "change_class",
                "commits",
                "validation",
                "design_ref",
            }
            if set(item) != expected_fields:
                raise NovaError(f"{change_class} item has missing or unknown fields: {work_item}")
            if design_ref != "none":
                raise NovaError(f"{change_class} requires design_ref none")
            normalized["package_ids"] = []
        normalized_items.append(normalized)

    computed_digest, computed_scope = compute_review_evidence(reviewed_diffs)
    if manifest["review_content_sha256"] != computed_digest:
        raise NovaError("review_content_sha256 does not match the complete commit diffs")
    if manifest["review_scope"] != computed_scope:
        raise NovaError(
            "review_scope does not match the complete commit diff paths; "
            f"expected={computed_scope}; actual={manifest['review_scope']}"
        )

    archive = safe_repo_path(
        repo,
        str(feature_path(repo, reviewed_at).relative_to(repo)),
        "feature archive",
    )
    capture_snapshot(snapshots, archive)
    expected_review = review_record_data(manifest, digest, normalized_items)

    if existing_batch:
        assert output_snapshot is not None
        if validate_review_record(
            read_json_bytes(output_snapshot, output, "Review record"), output
        ) != expected_review:
            raise NovaError("batch_id already exists with different or invalid content")
        def snapshot_reader(relative: str) -> bytes | None:
            path = safe_repo_path(repo, relative, "idempotent audit record")
            return capture_snapshot(snapshots, path)

        for item in normalized_items:
            completed = load_completed_from_reader(repo, item["work_item"], snapshot_reader)
            expected_feature = feature_record(
                item, batch_id, manifest["reviewed_at"]
            )
            if completed is None or completed[0] != expected_feature:
                raise NovaError(
                    f"existing Review batch lacks matching feature record for {item['work_item']}"
                )
            if item["change_class"] != "designed":
                continue
            blueprint_bytes = capture_snapshot(snapshots, item["blueprint_path"])
            design_bytes = capture_snapshot(snapshots, item["design_path"])
            if blueprint_bytes is None or design_bytes is None:
                raise NovaError(f"idempotent closure documents are missing: {item['work_item']}")
            blueprint = blueprint_bytes.decode("utf-8")
            if re.search(rf"^\|\s*{re.escape(item['work_item'])}\s*\|", blueprint, re.MULTILINE):
                raise NovaError(f"idempotent closure still has blueprint row for {item['work_item']}")
            design = design_bytes.decode("utf-8")
            for package_id in item["package_ids"]:
                if design_package_state(design, package_id) != "已完成":
                    raise NovaError(
                        f"idempotent closure package is not complete: {package_id}"
                    )
    else:
        for item in normalized_items:
            index_path = safe_repo_path(
                repo,
                str(feature_index_path(repo, item["work_item"]).relative_to(repo)),
                "feature index",
            )
            if capture_snapshot(snapshots, index_path) is not None:
                raise NovaError(f"work item already archived: {item['work_item']}")
        feature_root = safe_repo_path(
            repo, "docs/audit/features", "feature archive directory"
        )
        for historical in feature_root.glob("[0-9][0-9][0-9][0-9].jsonl"):
            reject_symlink_components(repo, historical, "historical feature archive")
            historical_bytes = capture_snapshot(snapshots, historical)
            assert historical_bytes is not None
            for line in historical_bytes.decode("utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise NovaError(f"invalid feature archive {historical}: {exc}") from exc
                if isinstance(record, dict) and record.get("work_item") in seen_items:
                    raise NovaError(f"work item already archived: {record.get('work_item')}")

    return {
        "manifest": manifest,
        "reviewed_at": reviewed_at,
        "digest": digest,
        "review_path": output,
        "feature_path": archive,
        "review_record": expected_review,
        "idempotent": existing_batch,
        "items": normalized_items,
        "snapshots": snapshots,
    }


def remove_blueprint_row(text: str, work_item: str, design_ref: str) -> str:
    lines = text.splitlines(keepends=True)
    matches = [index for index, line in enumerate(lines) if re.match(rf"^\|\s*{re.escape(work_item)}\s*\|", line)]
    if len(matches) != 1:
        raise NovaError(f"blueprint must contain exactly one row for {work_item}")
    if f"]({design_ref})" not in lines[matches[0]]:
        raise NovaError(f"blueprint design reference mismatch for {work_item}")
    del lines[matches[0]]
    return "".join(lines)


def design_package_state(text: str, package_id: str) -> str | None:
    matches = [
        match.group("state")
        for line in text.splitlines()
        if (match := MAP_ROW_RE.match(line)) and match.group("id") == package_id
    ]
    return matches[0] if len(matches) == 1 else None


def blueprint_items_for_design(text: str, design_file: str) -> set[str]:
    items: set[str] = set()
    for line in text.splitlines():
        if not line.lstrip().startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) != 7 or WORK_ITEM_PATTERNS["designed"].fullmatch(cells[0]) is None:
            continue
        links = re.findall(
            r"\[[^]\n]+\]\((docs/design/[^#\s]+\.md)#[A-Za-z0-9][A-Za-z0-9._-]*\)",
            cells[4],
        )
        if design_file in links:
            items.add(cells[0])
    return items


def parse_work_item_package_map(text: str) -> dict[str, list[str]]:
    lines = text.splitlines()
    headers = [
        index
        for index, line in enumerate(lines)
        if tuple(cell.strip() for cell in line.strip().strip("|").split("|"))
        == WORK_ITEM_MAP_HEADER
    ]
    if not headers:
        return {}
    if len(headers) != 1:
        raise NovaError("design must contain at most one work item closure map")
    header = headers[0]
    if header + 1 >= len(lines) or re.fullmatch(
        r"\|\s*-+\s*\|\s*-+\s*\|", lines[header + 1]
    ) is None:
        raise NovaError("invalid work item closure map separator")
    mapping: dict[str, list[str]] = {}
    owner: dict[str, str] = {}
    for line in lines[header + 2 :]:
        if not line.lstrip().startswith("|"):
            break
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) != 2:
            raise NovaError("invalid work item closure map row")
        work_item, raw_packages = cells
        if WORK_ITEM_PATTERNS["designed"].fullmatch(work_item) is None:
            raise NovaError(f"invalid closure map work item: {work_item}")
        if work_item in mapping:
            raise NovaError(f"duplicate closure map work item: {work_item}")
        package_ids = [
            value.strip() for value in re.split(r"[、,，]", raw_packages) if value.strip()
        ]
        if (
            not package_ids
            or len(package_ids) != len(set(package_ids))
            or any(re.fullmatch(r"WP-[A-Za-z0-9._-]+", value) is None for value in package_ids)
        ):
            raise NovaError(f"invalid closure map package list for {work_item}")
        for package_id in package_ids:
            if package_id in owner:
                raise NovaError(
                    f"design package {package_id} belongs to multiple work items: "
                    f"{owner[package_id]}, {work_item}"
                )
            owner[package_id] = work_item
        mapping[work_item] = package_ids
    if not mapping:
        raise NovaError("work item closure map must contain at least one row")
    return mapping


def authoritative_package_ids(
    blueprint: str,
    design: str,
    design_file: str,
    work_item: str,
    linked_anchor: str,
) -> list[str]:
    package_rows: dict[str, tuple[str, str]] = {}
    for line in design.splitlines():
        match = MAP_ROW_RE.match(line)
        if not match:
            continue
        package_id = match.group("id")
        if package_id in package_rows:
            raise NovaError(f"duplicate design package row: {package_id}")
        package_rows[package_id] = (match.group("state"), line)
    linked = [
        package_id
        for package_id, (_, line) in package_rows.items()
        if f"](#{linked_anchor})" in line
    ]
    if len(linked) != 1:
        raise NovaError("Design-Ref anchor must identify exactly one design package")

    mapping = parse_work_item_package_map(design)
    blueprint_items = blueprint_items_for_design(blueprint, design_file)
    if mapping:
        unknown = sorted(
            package_id
            for package_ids in mapping.values()
            for package_id in package_ids
            if package_id not in package_rows
        )
        if unknown:
            raise NovaError(f"closure map contains unknown design packages: {unknown}")
        active_mapping = {
            mapped_item
            for mapped_item, package_ids in mapping.items()
            if any(package_rows[package_id][0] != "已完成" for package_id in package_ids)
        }
        if active_mapping != blueprint_items:
            raise NovaError(
                "active closure map work items must exactly match blueprint items for design; "
                f"map={sorted(active_mapping)}; blueprint={sorted(blueprint_items)}"
            )
        mapped = {package_id for package_ids in mapping.values() for package_id in package_ids}
        unmapped_ready = sorted(
            package_id
            for package_id, (state, _) in package_rows.items()
            if state == "待Review" and package_id not in mapped
        )
        if unmapped_ready:
            raise NovaError(f"待Review design packages lack closure mapping: {unmapped_ready}")
        if work_item not in mapping:
            raise NovaError(f"closure map lacks work item: {work_item}")
        result = mapping[work_item]
    else:
        if blueprint_items != {work_item}:
            raise NovaError("multiple blueprint items sharing one design require a closure map")
        ready_packages = sorted(
            package_id
            for package_id, (state, _) in package_rows.items()
            if state == "待Review"
        )
        if ready_packages != linked:
            raise NovaError(
                "a design without a closure map must contain exactly one linked 待Review package"
            )
        result = linked
    if linked[0] not in result:
        raise NovaError("Design-Ref package must belong to the work item closure set")
    return result


def complete_design_packages(text: str, package_ids: list[str], linked_anchor: str) -> str:
    lines = text.splitlines(keepends=True)
    matches: dict[str, int] = {}
    states: dict[str, str] = {}
    linked_package: str | None = None
    for index, line in enumerate(lines):
        match = MAP_ROW_RE.match(line.rstrip("\n"))
        if not match:
            continue
        package_id = match.group("id")
        if package_id in states:
            raise NovaError(f"duplicate design package row: {package_id}")
        states[package_id] = match.group("state")
        matches[package_id] = index
        if f"](#{linked_anchor})" in line:
            linked_package = package_id
    if linked_package not in package_ids:
        raise NovaError("Design-Ref anchor must identify one package selected for closure")
    for package_id in package_ids:
        if package_id not in matches or states.get(package_id) != "待Review":
            raise NovaError(f"design package {package_id} must appear once in state 待Review")
        index = matches[package_id]
        newline = "\n" if lines[index].endswith("\n") else ""
        match = MAP_ROW_RE.match(lines[index].rstrip("\n"))
        assert match is not None
        lines[index] = match.group("prefix") + "已完成" + match.group("suffix") + newline
        states[package_id] = "已完成"
    result = "".join(lines)
    if states and all(value in TERMINAL_STATES for value in states.values()):
        result, count = re.subn(
            r"^>\s*设计状态[：:]\s*已确认\s*$",
            "> 设计状态：已实现",
            result,
            count=1,
            flags=re.MULTILINE,
        )
        if count != 1:
            raise NovaError("terminal design must have state 已确认 before closure")
    return result


def yaml_review(validated: dict[str, Any]) -> str:
    # JSON is valid YAML 1.2 and gives the stdlib a strict, deterministic parser.
    return json.dumps(
        validated["review_record"], ensure_ascii=False, indent=2, sort_keys=True
    ) + "\n"


def build_updates(
    repo: Path, validated: dict[str, Any]
) -> dict[Path, tuple[bytes | None, bytes]]:
    if validated["idempotent"]:
        return {}
    text_updates: dict[Path, str] = {}
    expected: dict[Path, bytes | None] = {}
    for item in validated["items"]:
        if item["change_class"] != "designed":
            continue
        blueprint_path = item["blueprint_path"]
        design_path = item["design_path"]
        blueprint = text_updates.get(blueprint_path)
        if blueprint is None:
            expected[blueprint_path] = validated["snapshots"][blueprint_path]
            if expected[blueprint_path] is None:
                raise NovaError(f"blueprint disappeared before closure: {blueprint_path}")
            blueprint = expected[blueprint_path].decode("utf-8")
        design = text_updates.get(design_path)
        if design is None:
            expected[design_path] = validated["snapshots"][design_path]
            if expected[design_path] is None:
                raise NovaError(f"design disappeared before closure: {design_path}")
            design = expected[design_path].decode("utf-8")
        anchor = item["design_ref"].split("#", 1)[1]
        text_updates[blueprint_path] = remove_blueprint_row(
            blueprint, item["work_item"], item["design_ref"]
        )
        text_updates[design_path] = complete_design_packages(
            design, item["package_ids"], anchor
        )

    reviewed_at = validated["reviewed_at"]
    archive_path = validated["feature_path"]
    expected[archive_path] = validated["snapshots"][archive_path]
    archive = expected[archive_path].decode("utf-8") if expected[archive_path] is not None else ""
    records: list[str] = []
    for item in validated["items"]:
        record = feature_record(
            item,
            validated["manifest"]["batch_id"],
            validated["manifest"]["reviewed_at"],
        )
        records.append(json.dumps(record, ensure_ascii=False, sort_keys=True))
        index_path = safe_repo_path(
            repo,
            str(feature_index_path(repo, item["work_item"]).relative_to(repo)),
            "feature index",
        )
        expected[index_path] = validated["snapshots"][index_path]
        if expected[index_path] is not None:
            raise NovaError(f"feature index appeared before closure: {index_path}")
        text_updates[index_path] = (
            json.dumps(
                feature_index_record(
                    repo,
                    item,
                    reviewed_at,
                    validated["manifest"]["batch_id"],
                    validated["review_path"],
                ),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n"
        )
    text_updates[archive_path] = archive + ("" if not archive or archive.endswith("\n") else "\n") + "\n".join(records) + "\n"
    expected[validated["review_path"]] = validated["snapshots"][validated["review_path"]]
    if expected[validated["review_path"]] is not None:
        raise NovaError("Review record appeared before closure")
    text_updates[validated["review_path"]] = yaml_review(validated)
    return {
        path: (expected[path], content.encode("utf-8"))
        for path, content in text_updates.items()
    }


def _open_secure_parent(
    repo: Path, path: Path, created_directories: list[Path]
) -> tuple[int, str]:
    try:
        relative = path.relative_to(repo)
    except ValueError as exc:
        raise NovaError(f"output path escapes repository: {path}") from exc
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    descriptor = os.open(repo, flags)
    current = repo
    try:
        for part in relative.parent.parts:
            current = current / part
            try:
                child = os.open(part, flags, dir_fd=descriptor)
            except FileNotFoundError:
                try:
                    os.mkdir(part, mode=0o755, dir_fd=descriptor)
                    created_directories.append(current)
                except FileExistsError:
                    pass
                child = os.open(part, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        return descriptor, relative.name
    except Exception:
        os.close(descriptor)
        raise


def _read_at(parent_fd: int, name: str) -> bytes | None:
    try:
        descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=parent_fd)
    except FileNotFoundError:
        return None
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            raise NovaError(f"refusing symlink output: {name}") from exc
        raise
    try:
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def _read_repo_path(repo: Path, path: Path) -> bytes | None:
    try:
        relative = path.relative_to(repo)
    except ValueError as exc:
        raise NovaError(f"snapshot path escapes repository: {path}") from exc
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    descriptor = os.open(repo, flags)
    try:
        for part in relative.parent.parts:
            try:
                child = os.open(part, flags, dir_fd=descriptor)
            except FileNotFoundError:
                return None
            os.close(descriptor)
            descriptor = child
        return _read_at(descriptor, relative.name)
    finally:
        os.close(descriptor)


def _rename_exchange(parent_fd: int, left: str, right: str) -> None:
    libc = ctypes.CDLL(None, use_errno=True)
    renameat2 = getattr(libc, "renameat2", None)
    if renameat2 is None:
        raise NovaError("atomic conditional replacement requires renameat2")
    result = renameat2(
        ctypes.c_int(parent_fd),
        ctypes.c_char_p(os.fsencode(left)),
        ctypes.c_int(parent_fd),
        ctypes.c_char_p(os.fsencode(right)),
        ctypes.c_uint(RENAME_EXCHANGE),
    )
    if result != 0:
        code = ctypes.get_errno()
        raise OSError(code, os.strerror(code), right)


def _rename_noreplace(parent_fd: int, left: str, right: str) -> None:
    libc = ctypes.CDLL(None, use_errno=True)
    renameat2 = getattr(libc, "renameat2", None)
    if renameat2 is None:
        raise NovaError("atomic conditional move requires renameat2")
    result = renameat2(
        ctypes.c_int(parent_fd),
        ctypes.c_char_p(os.fsencode(left)),
        ctypes.c_int(parent_fd),
        ctypes.c_char_p(os.fsencode(right)),
        ctypes.c_uint(RENAME_NOREPLACE),
    )
    if result != 0:
        code = ctypes.get_errno()
        raise OSError(code, os.strerror(code), right)


def _write_temp_at(parent_fd: int, target_name: str, content: bytes, sequence: int) -> str:
    temp_name = f".{target_name}.nova-{os.getpid()}-{sequence}"
    descriptor = os.open(
        temp_name,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
        0o600,
        dir_fd=parent_fd,
    )
    try:
        view = memoryview(content)
        while view:
            written = os.write(descriptor, view)
            view = view[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    return temp_name


def atomic_write_group(
    repo: Path,
    updates: dict[Path, tuple[bytes | None, bytes]],
    watched: dict[Path, bytes | None] | None = None,
) -> None:
    entries: list[dict[str, Any]] = []
    completed: list[dict[str, Any]] = []
    created_directories: list[Path] = []
    committed = False
    try:
        for path, expected in sorted((watched or {}).items(), key=lambda value: str(value[0])):
            if _read_repo_path(repo, path) != expected:
                raise NovaError(f"validated source changed before Review closure: {path}")
        for sequence, (path, (expected, content)) in enumerate(
            sorted(updates.items(), key=lambda value: str(value[0]))
        ):
            parent_fd, name = _open_secure_parent(repo, path, created_directories)
            try:
                current = _read_at(parent_fd, name)
                if current != expected:
                    raise NovaError(f"source changed during Review closure: {path}")
                temp_name = _write_temp_at(parent_fd, name, content, sequence)
                entries.append(
                    {
                        "path": path,
                        "parent_fd": parent_fd,
                        "name": name,
                        "temp": temp_name,
                        "expected": expected,
                    }
                )
            except Exception:
                os.close(parent_fd)
                raise

        for path, expected in sorted((watched or {}).items(), key=lambda value: str(value[0])):
            if _read_repo_path(repo, path) != expected:
                raise NovaError(f"validated source changed immediately before Review closure: {path}")
        for entry in entries:
            current = _read_at(entry["parent_fd"], entry["name"])
            if current != entry["expected"]:
                raise NovaError(
                    f"source changed immediately before Review closure: {entry['path']}"
                )
            if entry["expected"] is None:
                try:
                    os.link(
                        entry["temp"],
                        entry["name"],
                        src_dir_fd=entry["parent_fd"],
                        dst_dir_fd=entry["parent_fd"],
                        follow_symlinks=False,
                    )
                except FileExistsError as exc:
                    raise NovaError(f"source appeared during Review closure: {entry['path']}") from exc
                entry["action"] = "new"
            else:
                _rename_exchange(entry["parent_fd"], entry["temp"], entry["name"])
                entry["action"] = "exchange"
                if _read_at(entry["parent_fd"], entry["temp"]) != entry["expected"]:
                    _rename_exchange(entry["parent_fd"], entry["temp"], entry["name"])
                    entry.pop("action", None)
                    raise NovaError(f"source raced Review closure: {entry['path']}")
            completed.append(entry)
        for parent_fd in {entry["parent_fd"] for entry in entries}:
            os.fsync(parent_fd)
        committed = True
        for entry in entries:
            try:
                os.unlink(entry["temp"], dir_fd=entry["parent_fd"])
                os.fsync(entry["parent_fd"])
            except OSError:
                pass
    except Exception:
        for entry in reversed(completed):
            if entry.get("action") == "exchange":
                # The first exchange atomically displaces the current target. If
                # those displaced bytes are not ours, move the parent candidate to
                # an independent backup and restore with NOREPLACE. A still-later
                # target owner wins; unknown displaced bytes bypass generic cleanup.
                try:
                    _rename_exchange(entry["parent_fd"], entry["temp"], entry["name"])
                except FileNotFoundError:
                    continue
                if _read_at(entry["parent_fd"], entry["temp"]) != updates[entry["path"]][1]:
                    backup_name = f"{entry['temp']}.target"
                    try:
                        _rename_noreplace(
                            entry["parent_fd"], entry["name"], backup_name
                        )
                    except FileNotFoundError:
                        entry["preserve_temp"] = True
                        continue
                    backup = _read_at(entry["parent_fd"], backup_name)
                    if backup == entry["expected"]:
                        remove_backup = False
                        try:
                            _rename_noreplace(
                                entry["parent_fd"], entry["temp"], entry["name"]
                            )
                        except FileExistsError:
                            entry["preserve_temp"] = True
                            remove_backup = True
                        except OSError:
                            entry["preserve_temp"] = True
                            try:
                                _rename_noreplace(
                                    entry["parent_fd"], backup_name, entry["name"]
                                )
                            except OSError:
                                entry["rollback"] = backup_name
                        else:
                            remove_backup = True
                        if remove_backup:
                            try:
                                os.unlink(backup_name, dir_fd=entry["parent_fd"])
                            except OSError:
                                pass
                    else:
                        entry["preserve_temp"] = True
                        try:
                            _rename_noreplace(
                                entry["parent_fd"], backup_name, entry["name"]
                            )
                        except FileExistsError:
                            entry["rollback"] = backup_name
            elif entry.get("action") == "new":
                rollback_name = f"{entry['temp']}.rollback"
                try:
                    _rename_noreplace(entry["parent_fd"], entry["name"], rollback_name)
                except FileNotFoundError:
                    continue
                moved = _read_at(entry["parent_fd"], rollback_name)
                if moved == updates[entry["path"]][1]:
                    os.unlink(rollback_name, dir_fd=entry["parent_fd"])
                else:
                    try:
                        _rename_noreplace(
                            entry["parent_fd"], rollback_name, entry["name"]
                        )
                    except FileExistsError:
                        # A still-later writer owns the target. Keep the displaced
                        # unknown content under its unique rollback name rather
                        # than deleting it or overwriting the newer target.
                        entry["rollback"] = rollback_name
        for entry in entries:
            if entry.get("preserve_temp"):
                continue
            try:
                os.unlink(entry["temp"], dir_fd=entry["parent_fd"])
            except FileNotFoundError:
                pass
        raise
    finally:
        for entry in entries:
            os.close(entry["parent_fd"])
        if not committed:
            for directory in reversed(created_directories):
                try:
                    directory.rmdir()
                except (FileNotFoundError, OSError):
                    pass


@contextmanager
def review_lock(repo: Path, timeout_seconds: float = 5.0) -> Iterable[None]:
    git_directory = Path(run_git(repo, "rev-parse", "--absolute-git-dir").strip())
    lock_path = git_directory / "nova-review.lock"
    with lock_path.open("a+", encoding="utf-8") as handle:
        deadline = time.monotonic() + timeout_seconds
        while True:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise NovaError("timed out waiting for Nova Review closure lock")
                time.sleep(0.05)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def query(repo: Path, work_item: str | None, year: int | None, month: int | None) -> dict[str, Any]:
    commits: list[dict[str, Any]] = []
    if work_item:
        if not valid_work_item(work_item):
            raise NovaError(f"invalid work item: {work_item}")
        commits = [
            entry
            for entry in scan_commits(repo, work_item)
            if entry["metadata"].get("Work-Item") == work_item
        ]

    features: list[dict[str, Any]] = []
    reviews: list[str] = []
    if work_item:
        completed = load_completed_item(repo, work_item)
        if completed is not None:
            feature, _ = completed
            completed_at = datetime.fromisoformat(feature["completed_at"])
            if (year is None or completed_at.year == year) and (
                month is None or completed_at.month == month
            ):
                features.append(feature)
                reviews.append(
                    str(
                        review_path_for_values(
                            repo, completed_at, feature["review_batch"]
                        ).relative_to(repo)
                    )
                )
    else:
        assert year is not None
        audit_cache: dict[
            str, dict[str, tuple[dict[str, Any], dict[str, Any]]]
        ] = {}
        archive_relative = f"docs/audit/features/{year:04d}.jsonl"
        archive = safe_repo_path(repo, archive_relative, "feature archive")
        archive_bytes = git_blob(repo, "HEAD", archive_relative)
        if archive_bytes is not None:
            try:
                archive_lines = archive_bytes.decode("utf-8").splitlines()
            except UnicodeError as exc:
                raise NovaError(f"invalid feature archive {archive}: {exc}") from exc
            for line in archive_lines:
                if line.strip():
                    value = json.loads(line)
                    work_item_value = value.get("work_item") if isinstance(value, dict) else ""
                    feature = validate_feature_record(value, str(work_item_value))
                    completed_at = parse_reviewed_at(feature["completed_at"], "completed_at")
                    if month is not None and completed_at.month != month:
                        continue
                    completed = load_completed_item(
                        repo,
                        feature["work_item"],
                        expected_feature=feature,
                        audit_cache=audit_cache,
                    )
                    if completed is None or completed[0] != feature:
                        raise NovaError(
                            f"feature archive lacks matching index and Review: {feature['work_item']}"
                        )
                    features.append(feature)
                    reviews.append(
                        str(
                            review_path_for_values(
                                repo, completed_at, feature["review_batch"]
                            ).relative_to(repo)
                        )
                    )
    return {
        "work_item": work_item,
        "commits": commits,
        "features": features,
        "reviews": sorted(set(reviews)),
    }


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    commands = root.add_subparsers(dest="command", required=True)

    new_id = commands.add_parser("new-id")
    new_id.add_argument(
        "--class", dest="change_class", choices=tuple(WORK_ITEM_PREFIXES), required=True
    )

    validate = commands.add_parser("validate-message")
    validate.add_argument("--message-file", type=Path, required=True)
    validate.add_argument("--diff-file", type=Path)

    validate_audit = commands.add_parser("validate-audit-message")
    validate_audit.add_argument("--repo", type=Path, required=True)
    validate_audit.add_argument("--message-file", type=Path, required=True)
    validate_audit.add_argument("--diff-file", type=Path, required=True)

    select = commands.add_parser("select")
    select.add_argument("--repo", type=Path, required=True)
    select.add_argument("--mode", choices=("current", "explicit", "all"), required=True)
    select.add_argument("--session-item", action="append", default=[])
    select.add_argument("--work-item", action="append", default=[])

    for name in ("check-manifest", "record-pass"):
        command = commands.add_parser(name)
        command.add_argument("--repo", type=Path, required=True)
        command.add_argument("--manifest", type=Path, required=True)

    find = commands.add_parser("query")
    find.add_argument("--repo", type=Path, required=True)
    find.add_argument("--work-item")
    find.add_argument("--year", type=int)
    find.add_argument("--month", type=int)
    return root


def main() -> int:
    args = parser().parse_args()
    try:
        if args.command == "new-id":
            print(new_work_item(args.change_class))
        elif args.command == "validate-message":
            message = args.message_file.read_text(encoding="utf-8")
            diff = args.diff_file.read_text(encoding="utf-8") if args.diff_file else None
            metadata, errors = validate_message(message, diff)
            if errors:
                raise NovaError("; ".join(errors))
            print(json.dumps(metadata, ensure_ascii=False, sort_keys=True))
        elif args.command == "validate-audit-message":
            message = args.message_file.read_text(encoding="utf-8")
            diff = args.diff_file.read_text(encoding="utf-8")
            metadata, errors = validate_audit_message(args.repo.resolve(), message, diff)
            if errors:
                raise NovaError("; ".join(errors))
            print(json.dumps(metadata, ensure_ascii=False, sort_keys=True))
        elif args.command == "select":
            result = select_pending(
                args.repo.resolve(), args.mode, set(args.session_item), set(args.work_item)
            )
            print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        elif args.command in {"check-manifest", "record-pass"}:
            repo = args.repo.resolve()
            manifest = load_manifest(args.manifest)
            if args.command == "record-pass":
                with review_lock(repo):
                    validated = validate_manifest(repo, manifest)
                    updates = build_updates(repo, validated)
                    if updates:
                        atomic_write_group(repo, updates, validated["snapshots"])
            else:
                validated = validate_manifest(repo, manifest)
                build_updates(repo, validated)
            print(
                json.dumps(
                    {
                        "batch_id": manifest["batch_id"],
                        "idempotent": validated["idempotent"],
                        "items": [item["work_item"] for item in validated["items"]],
                        "status": "PASS",
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )
        elif args.command == "query":
            if args.month and not args.year:
                raise NovaError("--month requires --year")
            if args.month is not None and not 1 <= args.month <= 12:
                raise NovaError("--month must be between 1 and 12")
            if not args.work_item and not args.year:
                raise NovaError("query requires --work-item or --year")
            print(
                json.dumps(
                    query(args.repo.resolve(), args.work_item, args.year, args.month),
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
            )
        return 0
    except (NovaError, OSError, UnicodeError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
