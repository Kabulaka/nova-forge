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


LEGACY_SCHEMA = "1"
SCHEMA = "2"
LEGACY_AUDIT_SCHEMA = "1"
AUDIT_SCHEMA = "2"
TRAILERS = (
    "Nova-Schema",
    "Work-Item",
    "Change-Class",
    "Design-Ref",
    "Review-Policy",
    "Exemption-Rule",
    "Validation",
)
OPTIONAL_TRAILERS = ("Related-Work-Item",)
STANDARD_TRAILERS = TRAILERS + OPTIONAL_TRAILERS
REQUIREMENT_TRAILERS = (
    "Nova-Schema",
    "Commit-Kind",
    "Requirement-Ref",
    "Requirement-Path",
    "Requirement-SHA256",
    "Validation",
)
DELIVERY_PLAN_TRAILERS = (
    "Nova-Schema",
    "Commit-Kind",
    "Requirement-Ref",
    "Requirement-Commit",
    "Requirement-SHA256",
    "Plan-Version",
    "Validation",
)
ARCHITECTURE_TRAILERS = (
    "Nova-Schema",
    "Commit-Kind",
    "Architecture-Ref",
    "Requirement-Ref",
    "Validation",
)
LEGACY_AUDIT_TRAILERS = (
    "Nova-Audit-Schema",
    "Review-Batch",
    "Manifest-SHA256",
    "Validation",
)
AUDIT_TRAILERS = (
    "Nova-Audit-Schema",
    "Review-Batch",
    "Manifest-SHA256",
    "Review-Fix-SHA256",
    "Validation",
)
CHECKPOINT_TRAILERS = frozenset(
    REQUIREMENT_TRAILERS + DELIVERY_PLAN_TRAILERS + ARCHITECTURE_TRAILERS
)
WORK_ITEM_TRAILERS = frozenset(STANDARD_TRAILERS) | {"Review-State"}
AUDIT_MESSAGE_TRAILERS = frozenset(LEGACY_AUDIT_TRAILERS + AUDIT_TRAILERS)
MANAGED_TRAILERS = CHECKPOINT_TRAILERS | WORK_ITEM_TRAILERS | AUDIT_MESSAGE_TRAILERS
LEGACY_WORK_ITEM_PREFIXES = {
    "designed": "PEND",
    "adhoc": "FIX",
    "maintenance": "MAINT",
}
NEW_WORK_ITEM_PREFIXES = {
    "feature": "FEAT",
    "patch": "PATCH",
    "fix": "FIX",
    "maintenance": "MAINT",
}
UUID7_PATTERN = r"[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}"
LEGACY_WORK_ITEM_PATTERNS = {
    change_class: re.compile(rf"^{prefix}-(?:[0-9]+|{UUID7_PATTERN})$")
    for change_class, prefix in LEGACY_WORK_ITEM_PREFIXES.items()
}
NEW_WORK_ITEM_PATTERNS = {
    change_class: re.compile(rf"^{prefix}-{UUID7_PATTERN}$")
    for change_class, prefix in NEW_WORK_ITEM_PREFIXES.items()
}
WORK_ITEM_PATTERNS = {
    **LEGACY_WORK_ITEM_PATTERNS,
    **NEW_WORK_ITEM_PATTERNS,
    "maintenance": re.compile(rf"^MAINT-(?:[0-9]+|{UUID7_PATTERN})$"),
}
ARCHITECTURE_REF_RE = re.compile(rf"^ARCH-{UUID7_PATTERN}$")
DESIGN_REF_RE = re.compile(r"^\.nova/design/[^#\s]+\.md#[A-Za-z0-9][A-Za-z0-9._-]*$")
LEGACY_DESIGN_REF_RE = re.compile(r"^docs/design/[^#\s]+\.md#[A-Za-z0-9][A-Za-z0-9._-]*$")
REQUIREMENT_REF_RE = re.compile(
    r"^REQ-[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}@v[1-9][0-9]*$"
)
REQUIREMENT_LINK_RE = re.compile(
    rf"^\[(?P<ref>REQ-{UUID7_PATTERN}@v[1-9][0-9]*)\]\((?P<path>[^)\s]+\.md)\)$"
)
REQUIREMENT_PATH_RE = re.compile(
    rf"^\.nova/requirements/(?P<key>REQ-{UUID7_PATTERN})_[^/\n]+\.md$"
)
LOWER_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
SUBJECT_RE = re.compile(
    r"^(?P<type>[a-z][a-z0-9-]*)\((?P<scope>[a-z0-9]+(?:-[a-z0-9]+)*)\): (?P<summary>\S.*)$"
)
SUBJECT_SCOPES = {
    "requirements",
    "architecture",
    "delivery",
    "review",
    "doctor",
    "plugin",
    "discovery",
    "release",
}
SUBJECT_TYPES_BY_CLASS = {
    "feature": "feat",
    "patch": "patch",
    "fix": "fix",
    "maintenance": "maint",
}
SUBJECT_TYPES_BY_KIND = {
    "requirement": "req",
    "architecture": "arch",
    "delivery-plan": "plan",
}
REPORT_TITLES = {
    "requirement": "需求完成报告",
    "architecture": "架构完成报告",
    "feature": "FEAT 完成报告",
    "patch": "PATCH 完成报告",
    "fix": "FIX 完成报告",
    "maintenance": "MAINT 完成报告",
    "review": "Review 完成报告",
}
REPORT_SECTIONS = {
    "requirement": (
        "实际结果",
        "未改范围",
        "需求基线",
        "验证与提交",
        "下游路由",
        "遗留与下一步",
    ),
    "architecture": (
        "实际结果",
        "未改范围",
        "差量依据",
        "契约与验证",
        "提交与就绪",
        "遗留与下一步",
    ),
    "feature": (
        "实际结果",
        "未改范围",
        "工作项与分类",
        "验收与测试",
        "文件与提交",
        "Review 状态",
        "文档投影",
        "遗留与下一步",
    ),
    "patch": (
        "实际结果",
        "未改范围",
        "局部调整边界",
        "验收与测试",
        "文件与提交",
        "Review 状态",
        "遗留与下一步",
    ),
    "fix": (
        "实际结果",
        "未改范围",
        "缺陷证据与恢复结果",
        "验收与测试",
        "文件与提交",
        "Review 状态",
        "遗留与下一步",
    ),
    "maintenance": (
        "实际结果",
        "未改范围",
        "维护边界与行为证据",
        "验收与测试",
        "文件与提交",
        "Review 状态",
        "遗留与下一步",
    ),
    "review": (
        "实际结果",
        "未改范围",
        "审查对象",
        "审查轮次与修改",
        "验证",
        "闭环提交与审计",
        "投影更新",
        "遗留与下一步",
    ),
}
REPORT_WORK_ITEM_PATTERNS = {
    "feature": re.compile(rf"FEAT-{UUID7_PATTERN}"),
    "patch": re.compile(rf"PATCH-{UUID7_PATTERN}"),
    "fix": re.compile(rf"FIX-{UUID7_PATTERN}"),
    "maintenance": re.compile(rf"MAINT-{UUID7_PATTERN}"),
}
BOOTSTRAP_REQUIREMENT_REF = "REQ-01a06a50-2732-704d-97d0-7a98b205a4ea@v2"
BOOTSTRAP_CHECKPOINT_WORK_ITEM = "PEND-01a06a50-27d0-7fe5-8d30-ab9de658eaa0"
BOOTSTRAP_WORK_ITEMS = {BOOTSTRAP_CHECKPOINT_WORK_ITEM}
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


def repository_uses_schema_2(repo: Path) -> bool:
    return bool(
        run_git(
            repo,
            "log",
            "-1",
            "--format=%H",
            "--fixed-strings",
            "--grep=Nova-Schema: 2",
        ).strip()
    )


def valid_work_item(value: str) -> bool:
    return any(pattern.fullmatch(value) is not None for pattern in WORK_ITEM_PATTERNS.values())


def feature_work_item(value: str) -> bool:
    return any(
        WORK_ITEM_PATTERNS[change_class].fullmatch(value) is not None
        for change_class in ("designed", "feature")
    )


def new_work_item(change_class: str) -> str:
    prefix = NEW_WORK_ITEM_PREFIXES.get(change_class)
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


def new_requirement_id() -> str:
    """Generate a stable requirement identity without sharing PEND state."""
    timestamp_ms = time.time_ns() // 1_000_000
    value = (
        (timestamp_ms & ((1 << 48) - 1)) << 80
        | 0x7 << 76
        | secrets.randbits(12) << 64
        | 0b10 << 62
        | secrets.randbits(62)
    )
    return f"REQ-{uuid.UUID(int=value)}"


def new_architecture_id() -> str:
    """Generate a stable architecture checkpoint identity."""
    return new_work_item("feature").replace("FEAT-", "ARCH-", 1)


def normalize_nova_path(value: str) -> str:
    """Map pre-.nova persisted paths to their current deterministic location."""
    exact = {
        "PROJECT_BLUEPRINT.md": ".nova/PROJECT_BLUEPRINT.md",
        "PRODUCT_REQUIREMENTS.md": ".nova/PRODUCT_REQUIREMENTS.md",
    }
    if value in exact:
        return exact[value]
    prefixes = {
        "docs/design/": ".nova/design/",
        "docs/audit/": ".nova/audit/",
        "docs/requirements/": ".nova/requirements/",
        "docs/architecture/": ".nova/architecture/",
    }
    for legacy, current in prefixes.items():
        if value.startswith(legacy):
            return current + value[len(legacy):]
    return value


def normalize_design_ref(value: str) -> str:
    if "#" not in value:
        return normalize_nova_path(value)
    path, anchor = value.split("#", 1)
    return f"{normalize_nova_path(path)}#{anchor}"


def blueprint_design_ref(value: str, *, legacy_layout: bool = False) -> str:
    if legacy_layout:
        path, separator, anchor = value.partition("#")
        normalized = normalize_nova_path(path)
        if normalized.startswith(".nova/design/"):
            normalized = "docs/design/" + normalized[len(".nova/design/"):]
        return f"{normalized}{separator}{anchor}"
    normalized = normalize_design_ref(value)
    return normalized[len(".nova/") :] if normalized.startswith(".nova/") else normalized


def nova_path_candidates(value: str) -> tuple[str, ...]:
    normalized = normalize_nova_path(value)
    candidates = [normalized]
    exact = {
        ".nova/PROJECT_BLUEPRINT.md": "PROJECT_BLUEPRINT.md",
        ".nova/PRODUCT_REQUIREMENTS.md": "PRODUCT_REQUIREMENTS.md",
    }
    if normalized in exact:
        candidates.append(exact[normalized])
    else:
        prefixes = {
            ".nova/design/": "docs/design/",
            ".nova/audit/": "docs/audit/",
            ".nova/requirements/": "docs/requirements/",
            ".nova/architecture/": "docs/architecture/",
        }
        for current, legacy in prefixes.items():
            if normalized.startswith(current):
                candidates.append(legacy + normalized[len(current):])
                break
    return tuple(dict.fromkeys(candidates))


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


def validate_subject(text: str, values: dict[str, str]) -> list[str]:
    if values.get("Nova-Schema") != SCHEMA:
        return []
    first_line = text.splitlines()[0] if text.splitlines() else ""
    match = SUBJECT_RE.fullmatch(first_line)
    if match is None:
        return ["subject must match type(scope): 中文结果摘要"]
    scope = match.group("scope")
    if scope not in SUBJECT_SCOPES:
        return [f"subject scope is not allowed: {scope}"]
    summary = match.group("summary")
    if re.search(r"[\u3400-\u9fff]", summary) is None:
        return ["subject summary must contain Chinese result text"]
    if summary.endswith(("。", ".")):
        return ["subject summary must not end with punctuation"]
    expected_type = SUBJECT_TYPES_BY_KIND.get(values.get("Commit-Kind", ""))
    if expected_type is None:
        expected_type = SUBJECT_TYPES_BY_CLASS.get(values.get("Change-Class", ""))
    if expected_type is not None and match.group("type") != expected_type:
        return [f"subject type must be {expected_type} for this commit"]
    return []


def validate_audit_subject(text: str, values: dict[str, str]) -> list[str]:
    if values.get("Nova-Audit-Schema") != AUDIT_SCHEMA:
        return []
    first_line = text.splitlines()[0] if text.splitlines() else ""
    match = SUBJECT_RE.fullmatch(first_line)
    if match is None:
        return ["audit subject must match review(scope): 中文结果摘要"]
    if match.group("type") != "review":
        return ["audit subject type must be review"]
    if match.group("scope") != "review":
        return ["audit subject scope must be review"]
    summary = match.group("summary")
    if re.search(r"[\u3400-\u9fff]", summary) is None:
        return ["audit subject summary must contain Chinese result text"]
    if summary.endswith(("。", ".")):
        return ["audit subject summary must not end with punctuation"]
    return []


def completion_report_template(stage: str) -> str:
    title = REPORT_TITLES.get(stage)
    sections = REPORT_SECTIONS.get(stage)
    if title is None or sections is None:
        raise NovaError(f"unsupported report stage: {stage}")
    blocks = [f"## {title}"]
    for section in sections:
        blocks.extend(("", f"### {section}", "<填写具体事实>"))
    return "\n".join(blocks) + "\n"


def validate_completion_report(stage: str, text: str) -> list[str]:
    title = REPORT_TITLES.get(stage)
    expected_sections = REPORT_SECTIONS.get(stage)
    if title is None or expected_sections is None:
        return [f"unsupported report stage: {stage}"]
    errors: list[str] = []
    if not text.endswith("\n"):
        errors.append("completion report must end with a newline")
    level_two = re.findall(r"^##\s+(.+?)\s*$", text, re.MULTILINE)
    if level_two != [title]:
        errors.append(f"report title must be exactly: {title}")
    headings = list(re.finditer(r"^###\s+(.+?)\s*$", text, re.MULTILINE))
    actual_sections = tuple(match.group(1) for match in headings)
    if actual_sections != expected_sections:
        errors.append(
            "report sections must be exactly: " + " | ".join(expected_sections)
        )
        return errors
    content_by_section: dict[str, str] = {}
    for index, heading in enumerate(headings):
        start = heading.end()
        end = headings[index + 1].start() if index + 1 < len(headings) else len(text)
        content = text[start:end].strip()
        content_by_section[heading.group(1)] = content
        if not content:
            errors.append(f"report section must not be empty: {heading.group(1)}")
        if re.search(r"<[^>\n]+>|\{\{[^}\n]+\}\}|\b(?:TODO|TBD)\b", content, re.IGNORECASE):
            errors.append(f"report section contains a placeholder: {heading.group(1)}")

    actual_result = content_by_section.get("实际结果", "")
    if actual_result in {"无", "不适用"} or re.search(r"[\u3400-\u9fff]", actual_result) is None:
        errors.append("实际结果 must contain a concrete Chinese outcome")
    if not content_by_section.get("未改范围", ""):
        errors.append("未改范围 must explicitly state the untouched boundary")
    final_section = content_by_section.get("遗留与下一步", "")
    if "下一步" not in final_section:
        errors.append("遗留与下一步 must explicitly state 下一步")

    if stage == "requirement":
        baseline = content_by_section.get("需求基线", "")
        if re.search(rf"REQ-{UUID7_PATTERN}@v[1-9][0-9]*", baseline) is None:
            errors.append("需求基线 must contain REQ-<UUIDv7>@vN")
        if "commit" not in content_by_section.get("验证与提交", "").lower():
            errors.append("需求报告 must state the requirement commit result")
    elif stage == "architecture":
        combined = actual_result + "\n" + content_by_section.get("差量依据", "")
        zero_delta_markers = re.findall(
            r"(?:架构(?:差量|结果)?|结论)(?:为|：|:)\s*零差量", combined
        )
        architecture_ids = set(re.findall(rf"ARCH-{UUID7_PATTERN}", combined))
        has_zero_delta = bool(zero_delta_markers)
        if has_zero_delta == (len(architecture_ids) == 1) or len(architecture_ids) > 1:
            errors.append("架构报告 must state exactly one of 零差量 or one ARCH identity")
        if has_zero_delta and not re.search(
            r"(?:未提交|无提交)", content_by_section.get("提交与就绪", "")
        ):
            errors.append("零差量架构报告 must state that no commit was created")
    elif stage in REPORT_WORK_ITEM_PATTERNS:
        identity = content_by_section.get(
            "工作项与分类",
            content_by_section.get(
                "局部调整边界",
                content_by_section.get(
                    "缺陷证据与恢复结果",
                    content_by_section.get("维护边界与行为证据", ""),
                ),
            ),
        )
        if REPORT_WORK_ITEM_PATTERNS[stage].search(identity) is None:
            errors.append(f"{stage} report must contain its canonical work-item identity")
        if re.search(rf"\b{re.escape(stage)}\b", identity, re.IGNORECASE) is None:
            errors.append(f"{stage} report must state Change-Class {stage}")
        review = content_by_section.get("Review 状态", "")
        if re.search(r"\bPASS\b", review, re.IGNORECASE):
            errors.append("delivery report must not claim Review PASS")
        if stage == "fix" and "exempt" in review:
            if "EX-FIX" not in review or "不适用" not in review:
                errors.append("exempt fix report must state EX-FIX and Review round 不适用")
        elif stage == "maintenance" and "exempt" in review:
            if "不适用" not in review:
                errors.append("exempt maintenance report must state Review round 不适用")
        elif not all(value in review for value in ("未 Review", "待Review", "不适用")):
            errors.append(
                "required delivery report must state 未 Review, 待Review, and round 不适用"
            )
    elif stage == "review":
        targets = content_by_section.get("审查对象", "")
        if not re.search(rf"(?:FEAT|PATCH|FIX|MAINT)-{UUID7_PATTERN}|PEND-[A-Za-z0-9._-]+", targets):
            errors.append("Review report must identify every reviewed work item")
        rounds = content_by_section.get("审查轮次与修改", "")
        if re.search(r"第\s*[1-9][0-9]*\s*轮", rounds) is None:
            errors.append("Review report must list findings and changes by round")
        closure = content_by_section.get("闭环提交与审计", "")
        if "commit" not in closure.lower() or "审计" not in closure:
            errors.append("Review report must state the single closure commit and audit")
    return errors


def parse_message(text: str) -> tuple[dict[str, str], list[str]]:
    fields = trailing_fields(text)
    if any(key == "Commit-Kind" for key, _ in fields):
        found: dict[str, list[str]] = defaultdict(list)
        for key, value in fields:
            if key in MANAGED_TRAILERS:
                found[key].append(value)

        errors: list[str] = []
        values: dict[str, str] = {}
        kind_values = found.get("Commit-Kind", [])
        kind = kind_values[0] if len(kind_values) == 1 else ""
        expected = (
            REQUIREMENT_TRAILERS
            if kind == "requirement"
            else DELIVERY_PLAN_TRAILERS
            if kind == "delivery-plan"
            else ARCHITECTURE_TRAILERS
            if kind == "architecture"
            else ("Commit-Kind",)
        )
        for key in expected:
            entries = found.get(key, [])
            if len(entries) != 1:
                errors.append(f"{key} must appear exactly once")
            if entries:
                values[key] = entries[0]
        if kind not in {"requirement", "architecture", "delivery-plan"}:
            errors.append("Commit-Kind must be requirement, architecture, or delivery-plan")
        unexpected_checkpoint = CHECKPOINT_TRAILERS - set(expected)
        if any(found.get(key) for key in unexpected_checkpoint):
            errors.append(f"{kind or 'checkpoint'} commit has incompatible checkpoint trailers")
        forbidden = (
            (WORK_ITEM_TRAILERS - {"Nova-Schema", "Validation"})
            | (AUDIT_MESSAGE_TRAILERS - {"Validation"})
        )
        if any(found.get(key) for key in forbidden):
            errors.append(
                "checkpoint commits must not contain work-item, Review-State, or audit trailers"
            )
        return values, errors

    found: dict[str, list[str]] = defaultdict(list)
    for key, value in fields:
        if key in MANAGED_TRAILERS:
            found[key].append(value)

    errors: list[str] = []
    values: dict[str, str] = {}
    for key in TRAILERS:
        entries = found.get(key, [])
        if len(entries) != 1:
            errors.append(f"{key} must appear exactly once")
        if entries:
            values[key] = entries[0]
    for key in OPTIONAL_TRAILERS:
        entries = found.get(key, [])
        if len(entries) > 1:
            errors.append(f"{key} must appear at most once")
        if entries:
            values[key] = entries[0]
    if found.get("Review-State"):
        errors.append("Review-State is mutable and must not appear in a commit")
    incompatible = (
        (CHECKPOINT_TRAILERS - {"Nova-Schema", "Validation"})
        | (AUDIT_MESSAGE_TRAILERS - {"Validation"})
    )
    if any(found.get(key) for key in incompatible):
        errors.append("work-item commits must not contain checkpoint or audit trailers")
    return values, errors


def parse_audit_message(text: str) -> tuple[dict[str, str], list[str]]:
    found: dict[str, list[str]] = defaultdict(list)
    incompatible_found = False
    for key, value in trailing_fields(text):
        if key in MANAGED_TRAILERS - AUDIT_MESSAGE_TRAILERS - {"Validation"}:
            incompatible_found = True
        if key in AUDIT_MESSAGE_TRAILERS:
            found[key].append(value)

    errors: list[str] = []
    values: dict[str, str] = {}
    schema_values = found.get("Nova-Audit-Schema", [])
    schema = schema_values[0] if len(schema_values) == 1 else ""
    expected = AUDIT_TRAILERS if schema == AUDIT_SCHEMA else LEGACY_AUDIT_TRAILERS
    for key in expected:
        entries = found.get(key, [])
        if len(entries) != 1:
            errors.append(f"{key} must appear exactly once")
        if entries:
            values[key] = entries[0]
    if schema == LEGACY_AUDIT_SCHEMA and found.get("Review-Fix-SHA256"):
        errors.append("schema 1 audit commit must not contain Review-Fix-SHA256")
    if incompatible_found:
        errors.append(
            "audit commits must not contain checkpoint, work-item, or Review-State trailers"
        )
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


def validate_metadata(
    values: dict[str, str],
    diff: str | None = None,
    *,
    allow_legacy_design_ref: bool = False,
    allow_legacy_schema: bool = False,
) -> list[str]:
    errors: list[str] = []
    schema = values.get("Nova-Schema")
    accepted_schemas = {SCHEMA, LEGACY_SCHEMA} if allow_legacy_schema else {SCHEMA}
    if schema not in accepted_schemas:
        errors.append(f"Nova-Schema must be {SCHEMA}")

    change_class = values.get("Change-Class", "")
    work_item = values.get("Work-Item", "")
    class_patterns = (
        LEGACY_WORK_ITEM_PATTERNS
        if schema == LEGACY_SCHEMA
        else NEW_WORK_ITEM_PATTERNS
    )
    pattern = class_patterns.get(change_class)
    if pattern is None:
        allowed = ", ".join(class_patterns)
        errors.append(f"Change-Class must be one of: {allowed}")
    elif not pattern.fullmatch(work_item):
        errors.append(f"Work-Item does not match Change-Class {change_class}")

    related_work_item = values.get("Related-Work-Item")
    if related_work_item is not None:
        if change_class not in {"adhoc", "fix"}:
            errors.append("Related-Work-Item is allowed only for FIX changes")
        if not feature_work_item(related_work_item):
            errors.append("Related-Work-Item must reference a FEAT or legacy PEND work item")
        if related_work_item == work_item:
            errors.append("Related-Work-Item must differ from Work-Item")

    design_ref = values.get("Design-Ref", "")
    if change_class in {"designed", "feature"}:
        valid_design_ref = DESIGN_REF_RE.fullmatch(design_ref) is not None
        if allow_legacy_design_ref and LEGACY_DESIGN_REF_RE.fullmatch(design_ref) is not None:
            valid_design_ref = True
        if not valid_design_ref:
            errors.append("feature changes require .nova/design/*.md#anchor Design-Ref")
    elif design_ref != "none":
        errors.append("patch, fix, and maintenance changes require Design-Ref: none")

    policy = values.get("Review-Policy", "")
    exemption = values.get("Exemption-Rule", "")
    if policy not in {"required", "exempt"}:
        errors.append("Review-Policy must be required or exempt")
    if change_class in {"designed", "adhoc", "feature", "patch"} and policy != "required":
        errors.append(f"{change_class} changes always require Review")
    if policy == "required" and exemption != "none":
        errors.append("required Review must use Exemption-Rule: none")
    if policy == "exempt":
        if change_class == "fix":
            if exemption != "EX-FIX":
                errors.append("exempt fix requires Exemption-Rule: EX-FIX")
        elif change_class == "maintenance":
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
        else:
            errors.append("only fix and maintenance changes may be exempt")

    if re.search(r"\(pass\)\s*$", values.get("Validation", ""), re.IGNORECASE) is None:
        errors.append("Validation must end with (pass)")
    return errors


def validate_requirement_metadata(
    values: dict[str, str],
    diff: str | None,
    repo: Path | None,
    *,
    commit_hash: str | None = None,
    allow_legacy_schema: bool = False,
) -> list[str]:
    errors: list[str] = []
    if values.get("Nova-Schema") != SCHEMA and not (
        allow_legacy_schema and values.get("Nova-Schema") == LEGACY_SCHEMA
    ):
        errors.append(f"Nova-Schema must be {SCHEMA}")
    if values.get("Commit-Kind") != "requirement":
        errors.append("Commit-Kind must be requirement")

    requirement_ref = values.get("Requirement-Ref", "")
    ref_match = REQUIREMENT_REF_RE.fullmatch(requirement_ref)
    if ref_match is None:
        errors.append("Requirement-Ref must be REQ-<UUIDv7>@vN")
    requirement_path = values.get("Requirement-Path", "")
    path_match = REQUIREMENT_PATH_RE.fullmatch(requirement_path)
    if path_match is None:
        errors.append("Requirement-Path must be .nova/requirements/REQ-<UUIDv7>_<name>.md")
    elif ref_match is not None and path_match.group("key") != requirement_ref.split("@", 1)[0]:
        errors.append("Requirement-Path key must match Requirement-Ref")
    expected_sha = values.get("Requirement-SHA256", "")
    if LOWER_SHA256_RE.fullmatch(expected_sha) is None:
        errors.append("Requirement-SHA256 must be 64 lowercase hexadecimal characters")
    if re.search(r"\(pass\)\s*$", values.get("Validation", ""), re.IGNORECASE) is None:
        errors.append("Validation must end with (pass)")

    if diff is None:
        errors.append("requirement commits require the complete staged diff")
    if repo is None:
        errors.append("requirement commits require --repo")
    if errors or diff is None or repo is None:
        return errors

    try:
        if commit_hash is None:
            staged = run_git(repo, "diff", "--cached", "--binary", "--no-ext-diff")
            if diff != staged:
                errors.append("requirement diff must exactly match the repository staged diff")
                return errors
        changes = diff_changes(diff)
        expected_paths = {".nova/PRODUCT_REQUIREMENTS.md", requirement_path}
        if set(diff_paths(diff)) != expected_paths:
            errors.append(
                "requirement commit must contain exactly PRODUCT_REQUIREMENTS.md and Requirement-Path"
            )
            return errors
        if any(old != new for old, new in changes):
            errors.append("requirement commit must not rename paths")
            return errors

        entry_args = (
            ("ls-files", "--stage", "-z", "--")
            if commit_hash is None
            else ("ls-tree", "-z", commit_hash, "--")
        )
        staged_entries = run_git(
            repo, *entry_args, ".nova/PRODUCT_REQUIREMENTS.md", requirement_path
        ).split("\0")
        modes: dict[str, str] = {}
        for entry in staged_entries:
            metadata, separator, path = entry.partition("\t")
            if separator:
                modes[path] = metadata.split(" ", 1)[0]
        if modes != {path: "100644" for path in expected_paths}:
            errors.append("requirement commit paths must be ordinary 100644 Git index files")
            return errors

        if commit_hash is None:
            block_bytes = git_index_blob(repo, requirement_path)
            product_bytes = git_index_blob(repo, ".nova/PRODUCT_REQUIREMENTS.md")
        else:
            block_bytes = run_git_bytes(
                repo, "show", f"{commit_hash}:{requirement_path}", allow_missing=True
            )
            product_bytes = run_git_bytes(
                repo,
                "show",
                f"{commit_hash}:.nova/PRODUCT_REQUIREMENTS.md",
                allow_missing=True,
            )
        if block_bytes is None or product_bytes is None:
            errors.append("requirement commit paths must exist in the Git index")
            return errors
        if hashlib.sha256(block_bytes).hexdigest() != expected_sha:
            errors.append("Requirement-SHA256 does not match the staged requirement block")

        block = block_bytes.decode("utf-8")
        key = requirement_ref.split("@", 1)[0]
        version = requirement_ref.split("@", 1)[1]
        if re.findall(r"^>\s*Requirement-Key[：:]\s*(.+?)\s*$", block, re.MULTILINE) != [key]:
            errors.append("staged requirement block key does not match Requirement-Ref")
        if re.findall(r"^>\s*需求版本[：:]\s*(.+?)\s*$", block, re.MULTILINE) != [version]:
            errors.append("staged requirement block version does not match Requirement-Ref")

        product = product_bytes.decode("utf-8")
        rows = []
        for line in product.splitlines():
            if not line.lstrip().startswith("|"):
                continue
            cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
            if len(cells) == 7 and cells[0] == key:
                rows.append(cells)
        if len(rows) != 1 or rows[0][1] != version:
            errors.append("staged requirement index row does not match Requirement-Ref")

        if commit_hash is None:
            history = run_git(
                repo,
                "log",
                "--format=%H%x1f%B%x1e",
                "--fixed-strings",
                f"--grep=Requirement-Ref: {requirement_ref}",
            )
            for record in history.split("\x1e"):
                if "\x1f" not in record:
                    continue
                _, message = record.strip("\n").split("\x1f", 1)
                metadata, commit_errors = parse_message(message)
                if not commit_errors and metadata.get("Commit-Kind") == "requirement":
                    errors.append(
                        f"Requirement-Ref already has a requirement checkpoint: {requirement_ref}"
                    )
                    break
    except (NovaError, OSError, UnicodeError) as exc:
        errors.append(str(exc))
    return errors


def validate_architecture_metadata(
    values: dict[str, str],
    diff: str | None,
    repo: Path | None,
    *,
    commit_hash: str | None = None,
) -> list[str]:
    errors: list[str] = []
    if values.get("Nova-Schema") != SCHEMA:
        errors.append(f"Nova-Schema must be {SCHEMA}")
    if values.get("Commit-Kind") != "architecture":
        errors.append("Commit-Kind must be architecture")
    architecture_ref = values.get("Architecture-Ref", "")
    if ARCHITECTURE_REF_RE.fullmatch(architecture_ref) is None:
        errors.append("Architecture-Ref must be ARCH-<UUIDv7>")
    requirement_ref = values.get("Requirement-Ref", "")
    if REQUIREMENT_REF_RE.fullmatch(requirement_ref) is None:
        errors.append("Requirement-Ref must be REQ-<UUIDv7>@vN")
    if re.search(r"\(pass\)\s*$", values.get("Validation", ""), re.IGNORECASE) is None:
        errors.append("Validation must end with (pass)")
    if diff is None:
        errors.append("architecture commits require the complete staged diff")
    if repo is None:
        errors.append("architecture commits require --repo")
    if errors or diff is None or repo is None:
        return errors
    try:
        if commit_hash is None:
            staged = run_git(repo, "diff", "--cached", "--binary", "--no-ext-diff")
            if diff != staged:
                return ["architecture diff must exactly match the repository staged diff"]
        paths = set(diff_paths(diff))
        if not paths or not any(path.startswith(".nova/architecture/") for path in paths):
            errors.append("architecture commit must contain an architecture contract path")
        if any(old != new for old, new in diff_changes(diff)):
            errors.append("architecture commit must not rename paths")
        query_requirement(repo, requirement_ref)
        if commit_hash is None:
            history = run_git(
                repo,
                "log",
                "--format=%H%x1f%B%x1e",
                "--fixed-strings",
                f"--grep=Architecture-Ref: {architecture_ref}",
            )
            for record in history.split("\x1e"):
                if "\x1f" not in record:
                    continue
                _, message = record.strip("\n").split("\x1f", 1)
                metadata, commit_errors = parse_message(message)
                if not commit_errors and metadata.get("Commit-Kind") == "architecture":
                    errors.append(
                        f"Architecture-Ref already has an architecture checkpoint: {architecture_ref}"
                    )
                    break
    except (NovaError, OSError, UnicodeError) as exc:
        errors.append(str(exc))
    return errors


DELIVERY_WORK_ITEM_STATES = {
    "planned",
    "active",
    "review_pending",
    "blocked",
    "completed",
    "superseded",
    "cancelled",
}
DELIVERY_MILESTONE_STATES = {"planned", "active", "blocked", "completed"}
DELIVERY_CHANGE_KINDS = {
    "created",
    "added",
    "split",
    "merged",
    "replaced",
    "reordered",
    "dependencies-updated",
    "done-definition-updated",
    "design-bound",
    "activated",
    "milestone-updated",
    "review-submitted",
    "blocked",
    "unblocked",
    "completed",
    "cancelled",
}


def delivery_relative_path(requirement_ref: str) -> str:
    if REQUIREMENT_REF_RE.fullmatch(requirement_ref) is None:
        raise NovaError("Requirement-Ref must be REQ-<UUIDv7>@vN")
    key, version = requirement_ref.split("@", 1)
    return f".nova/delivery/{key}_{version}.json"


def strict_json_object(content: bytes, label: str) -> dict[str, Any]:
    def pairs(values: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in values:
            if key in result:
                raise NovaError(f"{label} contains duplicate key: {key}")
            result[key] = value
        return result

    try:
        value = json.loads(content.decode("utf-8"), object_pairs_hook=pairs)
    except json.JSONDecodeError as exc:
        raise NovaError(f"invalid {label}: {exc}") from exc
    if not isinstance(value, dict):
        raise NovaError(f"{label} must be a JSON object")
    return value


def canonical_delivery_ledger(value: dict[str, Any]) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
        "utf-8"
    )


def product_requirement_row(
    text: str, requirement_ref: str, *, allow_newer_version: bool = False
) -> list[str]:
    key, version = requirement_ref.split("@", 1)
    rows: list[list[str]] = []
    for line in text.splitlines():
        if not line.lstrip().startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) == 7 and cells[0] == key:
            rows.append(cells)
    if len(rows) != 1:
        raise NovaError("product requirements row does not match delivery Requirement-Ref")
    row = rows[0]
    if row[1] == version:
        return row
    if not allow_newer_version:
        raise NovaError("product requirements row does not match delivery Requirement-Ref")
    try:
        current_version = int(row[1].removeprefix("v"))
        ledger_version = int(version.removeprefix("v"))
    except ValueError as exc:
        raise NovaError(
            "product requirements row does not match delivery Requirement-Ref"
        ) from exc
    if current_version <= ledger_version:
        raise NovaError("product requirements row does not match delivery Requirement-Ref")
    return row


def validate_delivery_ledger_data(
    repo: Path,
    ledger: dict[str, Any],
    *,
    blueprint: str,
    product: str,
    verify_evidence: bool = True,
    verify_review_state: bool | None = None,
    evidence_revision: str | None = None,
) -> dict[str, Any]:
    expected_root = {
        "schema",
        "requirement_ref",
        "requirement_checkpoint",
        "plan_version",
        "status",
        "work_items",
        "changes",
    }
    if verify_review_state is None:
        verify_review_state = verify_evidence
    ledger_schema = ledger.get("schema")
    if set(ledger) != expected_root or ledger_schema not in {1, 2}:
        raise NovaError("delivery ledger has missing or unknown root fields")
    requirement_ref = ledger.get("requirement_ref")
    if not isinstance(requirement_ref, str) or REQUIREMENT_REF_RE.fullmatch(requirement_ref) is None:
        raise NovaError("delivery ledger has invalid requirement_ref")
    checkpoint = ledger.get("requirement_checkpoint")
    if not isinstance(checkpoint, dict) or set(checkpoint) != {"commit", "path", "sha256"}:
        raise NovaError("delivery ledger has invalid requirement_checkpoint")
    trusted = query_requirement(repo, requirement_ref, revision=evidence_revision)
    if checkpoint != {key: trusted[key] for key in ("commit", "path", "sha256")}:
        raise NovaError("delivery ledger requirement checkpoint does not match trusted Git history")
    plan_version = ledger.get("plan_version")
    if not isinstance(plan_version, int) or isinstance(plan_version, bool) or plan_version < 1:
        raise NovaError("delivery ledger plan_version must be a positive integer")
    if ledger.get("status") not in {"development", "implemented"}:
        raise NovaError("delivery ledger status must be development or implemented")

    work_items = ledger.get("work_items")
    if not isinstance(work_items, list) or not work_items:
        raise NovaError("delivery ledger work_items must be non-empty")
    by_id: dict[str, dict[str, Any]] = {}
    current: list[dict[str, Any]] = []
    effective: list[dict[str, Any]] = []
    for item in work_items:
        expected_item = {
            "work_item",
            "title",
            "dependencies",
            "done_definition",
            "design_ref",
            "state",
            "blocked_reason",
            "supersedes",
            "change_reason",
            "milestones",
        }
        if not isinstance(item, dict) or set(item) != expected_item:
            raise NovaError("delivery work item has missing or unknown fields")
        work_item = item.get("work_item")
        expected_class = "designed" if ledger_schema == 1 else "feature"
        class_patterns = (
            LEGACY_WORK_ITEM_PATTERNS
            if ledger_schema == 1
            else NEW_WORK_ITEM_PATTERNS
        )
        if not isinstance(work_item, str) or class_patterns[expected_class].fullmatch(work_item) is None:
            expected_prefix = "PEND" if ledger_schema == 1 else "FEAT"
            raise NovaError(f"delivery work item must be a {expected_prefix} identifier")
        if work_item in by_id:
            raise NovaError(f"duplicate delivery work item: {work_item}")
        by_id[work_item] = item
        for field in ("title", "done_definition", "change_reason"):
            if not isinstance(item.get(field), str) or not item[field].strip():
                raise NovaError(f"delivery work item {field} must not be empty: {work_item}")
        dependencies = item.get("dependencies")
        supersedes = item.get("supersedes")
        if (
            not isinstance(dependencies, list)
            or any(not isinstance(value, str) or not valid_work_item(value) for value in dependencies)
            or len(dependencies) != len(set(dependencies))
        ):
            raise NovaError(f"invalid dependencies for {work_item}")
        if (
            not isinstance(supersedes, list)
            or any(not isinstance(value, str) or not valid_work_item(value) for value in supersedes)
            or len(supersedes) != len(set(supersedes))
        ):
            raise NovaError(f"invalid supersedes for {work_item}")
        design_ref = item.get("design_ref")
        state = item.get("state")
        if state not in DELIVERY_WORK_ITEM_STATES:
            raise NovaError(f"invalid state for {work_item}")
        if state != "planned" and (
            not isinstance(design_ref, str) or DESIGN_REF_RE.fullmatch(design_ref) is None
        ):
            raise NovaError(f"non-planned work item requires a design_ref: {work_item}")
        if design_ref is not None and (
            not isinstance(design_ref, str) or DESIGN_REF_RE.fullmatch(design_ref) is None
        ):
            raise NovaError(f"invalid design_ref for {work_item}")
        blocked_reason = item.get("blocked_reason")
        if (state == "blocked") != (isinstance(blocked_reason, str) and bool(blocked_reason.strip())):
            raise NovaError(f"blocked_reason does not match state for {work_item}")
        if state in {"active", "review_pending", "blocked"}:
            current.append(item)
        if state not in {"superseded", "cancelled"}:
            effective.append(item)

        milestones = item.get("milestones")
        if not isinstance(milestones, list) or not milestones:
            raise NovaError(f"work item requires internal milestones: {work_item}")
        seen_milestones: set[str] = set()
        milestone_current = 0
        for milestone in milestones:
            expected_milestone = {
                "id",
                "title",
                "done_definition",
                "state",
                "blocked_reason",
                "evidence",
            }
            if not isinstance(milestone, dict) or set(milestone) != expected_milestone:
                raise NovaError(f"milestone has missing or unknown fields: {work_item}")
            milestone_id = milestone.get("id")
            if not isinstance(milestone_id, str) or re.fullmatch(r"M-0*[1-9][0-9]*", milestone_id) is None:
                raise NovaError(f"invalid milestone id: {work_item}")
            if milestone_id in seen_milestones:
                raise NovaError(f"duplicate milestone id: {work_item}/{milestone_id}")
            seen_milestones.add(milestone_id)
            for field in ("title", "done_definition"):
                if not isinstance(milestone.get(field), str) or not milestone[field].strip():
                    raise NovaError(f"milestone {field} must not be empty: {work_item}/{milestone_id}")
            milestone_state = milestone.get("state")
            if milestone_state not in DELIVERY_MILESTONE_STATES:
                raise NovaError(f"invalid milestone state: {work_item}/{milestone_id}")
            milestone_blocked = milestone.get("blocked_reason")
            if (milestone_state == "blocked") != (
                isinstance(milestone_blocked, str) and bool(milestone_blocked.strip())
            ):
                raise NovaError(f"milestone blocked_reason does not match state: {work_item}/{milestone_id}")
            if milestone_state in {"active", "blocked"}:
                milestone_current += 1
            evidence = milestone.get("evidence")
            if (
                not isinstance(evidence, list)
                or any(not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{40,64}", value) is None for value in evidence)
                or len(evidence) != len(set(evidence))
            ):
                raise NovaError(f"invalid milestone evidence: {work_item}/{milestone_id}")
            if milestone_state == "completed" and not evidence:
                raise NovaError(f"completed milestone requires commit evidence: {work_item}/{milestone_id}")
            if milestone_state != "completed" and evidence:
                raise NovaError(f"only completed milestones may carry evidence: {work_item}/{milestone_id}")
            if verify_evidence:
                for commit_hash in evidence:
                    try:
                        resolved = run_git(repo, "rev-parse", "--verify", f"{commit_hash}^{{commit}}")
                        run_git(
                            repo,
                            "merge-base",
                            "--is-ancestor",
                            resolved.strip(),
                            evidence_revision or "HEAD",
                        )
                        message = run_git(repo, "show", "-s", "--format=%B", resolved.strip())
                        values, errors = parse_message(message)
                    except NovaError as exc:
                        raise NovaError(f"invalid milestone evidence {commit_hash}: {exc}") from exc
                    if errors or values.get("Work-Item") != work_item:
                        raise NovaError(f"milestone evidence does not belong to {work_item}: {commit_hash}")
        if milestone_current > 1:
            raise NovaError(f"work item has multiple current milestones: {work_item}")
        if state == "review_pending" and any(
            milestone["state"] != "completed" for milestone in milestones
        ):
            raise NovaError(f"review_pending work item has incomplete milestones: {work_item}")
        completed_record = (
            load_completed_item(repo, work_item, revision=evidence_revision or "HEAD")
            if verify_review_state
            else None
        )
        if state == "completed" and verify_review_state and completed_record is None:
            raise NovaError(f"completed work item lacks trusted Review PASS: {work_item}")
        if state != "completed" and verify_review_state and completed_record is not None:
            raise NovaError(f"uncompleted work item already has trusted Review PASS: {work_item}")

    if len(current) > 1:
        raise NovaError("delivery ledger may have at most one current work item")
    for work_item, item in by_id.items():
        for dependency in item["dependencies"]:
            if dependency == work_item:
                raise NovaError(f"work item may not depend on itself: {work_item}")
            if dependency in by_id and by_id[dependency]["state"] != "completed":
                if item["state"] != "planned":
                    raise NovaError(f"active work item has incomplete dependency: {work_item}")
            elif (
                dependency not in by_id
                and verify_evidence
                and load_completed_item(
                    repo, dependency, revision=evidence_revision or "HEAD"
                )
                is None
            ):
                raise NovaError(f"external dependency lacks trusted PASS: {dependency}")
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(value: str) -> None:
        if value in visiting:
            raise NovaError("delivery work item dependencies contain a cycle")
        if value in visited or value not in by_id:
            return
        visiting.add(value)
        for dependency in by_id[value]["dependencies"]:
            visit(dependency)
        visiting.remove(value)
        visited.add(value)

    for work_item in by_id:
        visit(work_item)

    changes = ledger.get("changes")
    if not isinstance(changes, list) or len(changes) != plan_version:
        raise NovaError("delivery ledger changes must match plan_version")
    for index, change in enumerate(changes, 1):
        if not isinstance(change, dict) or change.get("plan_version") != index:
            raise NovaError("delivery ledger changes must be sequential")
        if change.get("kind") not in DELIVERY_CHANGE_KINDS:
            raise NovaError("delivery ledger change has invalid kind")
        if not isinstance(change.get("reason"), str) or not change["reason"].strip():
            raise NovaError("delivery ledger change reason must not be empty")

    completed = [item for item in effective if item["state"] == "completed"]
    if ledger["status"] == "implemented":
        if not effective or len(completed) != len(effective) or current:
            raise NovaError("implemented delivery ledger must have all effective work complete")
    elif not effective or len(completed) == len(effective):
        raise NovaError("development delivery ledger must have unfinished effective work")

    expected_blueprint = {
        item["work_item"] for item in effective if item["state"] != "completed"
    }
    actual_blueprint = blueprint_work_items_for_requirement(blueprint, requirement_ref)
    if actual_blueprint != expected_blueprint:
        raise NovaError(
            "delivery ledger and blueprint work items differ; "
            f"expected={sorted(expected_blueprint)}; actual={sorted(actual_blueprint)}"
        )
    row = product_requirement_row(
        product,
        requirement_ref,
        allow_newer_version=ledger["status"] == "implemented",
    )
    if ledger["status"] == "development" and row[2] != "开发中":
        raise NovaError("development delivery ledger requires product state 开发中")
    if ledger["status"] == "implemented":
        current_version = row[1] == requirement_ref.split("@", 1)[1]
        allowed_states = {"已实现", "已更新"} if current_version else {
            "已实现",
            "已更新",
            "开发中",
        }
        if row[2] not in allowed_states:
            raise NovaError("implemented delivery ledger requires implemented product state")
    return ledger


def validate_delivery_plan_metadata(
    values: dict[str, str],
    diff: str | None,
    repo: Path | None,
    *,
    commit_hash: str | None = None,
    allow_legacy_schema: bool = False,
) -> list[str]:
    errors: list[str] = []
    if values.get("Nova-Schema") != SCHEMA and not (
        allow_legacy_schema and values.get("Nova-Schema") == LEGACY_SCHEMA
    ):
        errors.append(f"Nova-Schema must be {SCHEMA}")
    if values.get("Commit-Kind") != "delivery-plan":
        errors.append("Commit-Kind must be delivery-plan")
    requirement_ref = values.get("Requirement-Ref", "")
    if REQUIREMENT_REF_RE.fullmatch(requirement_ref) is None:
        errors.append("Requirement-Ref must be REQ-<UUIDv7>@vN")
    if re.fullmatch(r"[0-9a-f]{40,64}", values.get("Requirement-Commit", "")) is None:
        errors.append("Requirement-Commit must be a Git commit hash")
    if LOWER_SHA256_RE.fullmatch(values.get("Requirement-SHA256", "")) is None:
        errors.append("Requirement-SHA256 must be 64 lowercase hexadecimal characters")
    if re.fullmatch(r"[1-9][0-9]*", values.get("Plan-Version", "")) is None:
        errors.append("Plan-Version must be a positive integer")
    if re.search(r"\(pass\)\s*$", values.get("Validation", ""), re.IGNORECASE) is None:
        errors.append("Validation must end with (pass)")
    if diff is None:
        errors.append("delivery-plan commits require the complete staged diff")
    if repo is None:
        errors.append("delivery-plan commits require --repo")
    if errors or diff is None or repo is None:
        return errors
    try:
        if commit_hash is None:
            staged = run_git(repo, "diff", "--cached", "--binary", "--no-ext-diff")
            if diff != staged:
                return ["delivery-plan diff must exactly match the repository staged diff"]
        ledger_path = delivery_relative_path(requirement_ref)
        paths = set(diff_paths(diff))
        changes = diff_changes(diff)
        if any(old != new for old, new in changes):
            return ["delivery-plan commit must not rename paths"]
        if commit_hash is None:
            ledger_bytes = git_index_blob(repo, ledger_path)
            blueprint_bytes = git_index_blob(repo, ".nova/PROJECT_BLUEPRINT.md")
            product_bytes = git_index_blob(repo, ".nova/PRODUCT_REQUIREMENTS.md")
        else:
            ledger_bytes = run_git_bytes(repo, "show", f"{commit_hash}:{ledger_path}")
            blueprint_bytes = run_git_bytes(repo, "show", f"{commit_hash}:.nova/PROJECT_BLUEPRINT.md")
            product_bytes = run_git_bytes(repo, "show", f"{commit_hash}:.nova/PRODUCT_REQUIREMENTS.md")
        ledger = strict_json_object(ledger_bytes or b"", "delivery ledger")
        if canonical_delivery_ledger(ledger) != ledger_bytes:
            raise NovaError("delivery ledger must use canonical UTF-8 JSON")
        design_paths = {
            item.get("design_ref", "").split("#", 1)[0]
            for item in ledger.get("work_items", [])
            if isinstance(item, dict)
            and isinstance(item.get("design_ref"), str)
            and DESIGN_REF_RE.fullmatch(item["design_ref"]) is not None
        }
        allowed = {
            ledger_path,
            ".nova/PROJECT_BLUEPRINT.md",
            ".nova/PRODUCT_REQUIREMENTS.md",
            *design_paths,
        }
        if ledger_path not in paths or not paths.issubset(allowed):
            return [
                "delivery-plan commit must contain its ledger and only allowed projections or bound designs"
            ]
        for design_path in design_paths:
            content = (
                git_index_blob(repo, design_path)
                if commit_hash is None
                else run_git_bytes(repo, "show", f"{commit_hash}:{design_path}", allow_missing=True)
            )
            if content is None:
                raise NovaError(f"delivery-plan bound design is missing: {design_path}")
        expected_ledger_schema = 1 if values.get("Nova-Schema") == LEGACY_SCHEMA else 2
        if ledger.get("schema") != expected_ledger_schema:
            raise NovaError(
                f"delivery ledger schema must be {expected_ledger_schema} for Nova-Schema {values.get('Nova-Schema')}"
            )
        validate_delivery_ledger_data(
            repo,
            ledger,
            blueprint=(blueprint_bytes or b"").decode("utf-8"),
            product=(product_bytes or b"").decode("utf-8"),
            verify_evidence=True,
            verify_review_state=commit_hash is None,
        )
        checkpoint = ledger["requirement_checkpoint"]
        if values["Requirement-Commit"] != checkpoint["commit"]:
            errors.append("Requirement-Commit does not match delivery ledger")
        if values["Requirement-SHA256"] != checkpoint["sha256"]:
            errors.append("Requirement-SHA256 does not match delivery ledger")
        if values["Plan-Version"] != str(ledger["plan_version"]):
            errors.append("Plan-Version does not match delivery ledger")
        if commit_hash is None:
            history = run_git(
                repo,
                "log",
                "--format=%H%x1f%B%x1e",
                "--fixed-strings",
                f"--grep=Requirement-Ref: {requirement_ref}",
            )
            for record in history.split("\x1e"):
                if "\x1f" not in record:
                    continue
                _, message = record.strip("\n").split("\x1f", 1)
                metadata, commit_errors = parse_message(message)
                if (
                    not commit_errors
                    and metadata.get("Commit-Kind") == "delivery-plan"
                    and metadata.get("Plan-Version") == values["Plan-Version"]
                ):
                    errors.append("Requirement-Ref and Plan-Version already have a delivery-plan commit")
                    break
    except (NovaError, OSError, UnicodeError, json.JSONDecodeError) as exc:
        errors.append(str(exc))
    return errors


def delivery_item_for_commit_boundary(
    repo: Path,
    work_item: str,
    *,
    verify_review_state: bool = True,
    revision: str | None = None,
) -> dict[str, Any]:
    candidates: list[tuple[str, bytes, dict[str, Any]]] = []
    if revision is None:
        delivery_root = safe_repo_path(repo, ".nova/delivery", "delivery directory")
        sources = [
            (str(path.relative_to(repo)), path.read_bytes())
            for path in sorted(delivery_root.glob("REQ-*_v*.json"))
        ]
    else:
        tree_revision = resolve_commit(repo, revision)
        paths = run_git(
            repo,
            "ls-tree",
            "-r",
            "--name-only",
            tree_revision,
            "--",
            ".nova/delivery",
        ).splitlines()
        sources = []
        for relative in sorted(paths):
            if re.fullmatch(r"\.nova/delivery/REQ-.*_v.*\.json", relative) is None:
                continue
            content = git_blob(repo, tree_revision, relative)
            if content is None:
                raise NovaError(f"delivery ledger is absent from Git snapshot: {relative}")
            sources.append((relative, content))
    for relative, content in sources:
        ledger = strict_json_object(content, "delivery ledger")
        if any(item.get("work_item") == work_item for item in ledger.get("work_items", [])):
            candidates.append((relative, content, ledger))
    if len(candidates) != 1:
        raise NovaError(
            "additional FEAT commit requires exactly one delivery ledger with "
            f"pre-registered milestones: {work_item}"
        )
    relative, content, ledger = candidates[0]
    if canonical_delivery_ledger(ledger) != content:
        raise NovaError("delivery ledger must use canonical UTF-8 JSON")
    if revision is None:
        blueprint = safe_repo_path(
            repo, ".nova/PROJECT_BLUEPRINT.md", "blueprint"
        ).read_text(encoding="utf-8")
        product = safe_repo_path(
            repo, ".nova/PRODUCT_REQUIREMENTS.md", "product requirements"
        ).read_text(encoding="utf-8")
    else:
        blueprint_bytes = git_blob(repo, tree_revision, ".nova/PROJECT_BLUEPRINT.md")
        product_bytes = git_blob(repo, tree_revision, ".nova/PRODUCT_REQUIREMENTS.md")
        if blueprint_bytes is None or product_bytes is None:
            raise NovaError(
                "delivery ledger Git snapshot lacks blueprint or product requirements"
            )
        blueprint = blueprint_bytes.decode("utf-8")
        product = product_bytes.decode("utf-8")
    validate_delivery_ledger_data(
        repo,
        ledger,
        blueprint=blueprint,
        product=product,
        verify_evidence=True,
        verify_review_state=verify_review_state,
        evidence_revision=revision,
    )
    return next(item for item in ledger["work_items"] if item["work_item"] == work_item)


def validate_work_item_commit_boundary(
    repo: Path,
    values: dict[str, str],
    *,
    replacing_head: bool = False,
) -> list[str]:
    if values.get("Nova-Schema") != SCHEMA:
        return []
    work_item = values.get("Work-Item", "")
    entries = [
        entry
        for entry in scan_commits(repo, work_item)
        if entry["metadata"].get("Work-Item") == work_item
    ]
    errors = [
        f"invalid existing work-item commit {entry['commit']}: "
        + "; ".join(entry["errors"])
        for entry in entries
        if entry["errors"]
    ]
    if errors:
        return errors

    if replacing_head:
        try:
            head = run_git(repo, "rev-parse", "HEAD").strip()
        except NovaError:
            return ["--amend requires HEAD to be the unreviewed commit being replaced"]
        matches = [entry for entry in entries if entry["commit"] == head]
        if len(matches) != 1:
            return ["--amend requires HEAD to belong to the same Work-Item"]
        previous = matches[0]["metadata"]
        identity = ("Work-Item", "Change-Class", "Design-Ref", "Related-Work-Item")
        if any(previous.get(key) != values.get(key) for key in identity):
            return ["--amend must preserve Work-Item classification and design identity"]
        entries = [entry for entry in entries if entry["commit"] != head]

    if not entries:
        return []
    change_class = values.get("Change-Class")
    if change_class != "feature":
        return [f"{change_class} work items allow one implementation result commit before Review"]
    try:
        item = delivery_item_for_commit_boundary(repo, work_item)
    except (NovaError, OSError, UnicodeError, json.JSONDecodeError) as exc:
        return [str(exc)]
    milestones = item["milestones"]
    completed = [milestone for milestone in milestones if milestone["state"] == "completed"]
    active = [milestone for milestone in milestones if milestone["state"] == "active"]
    if len(milestones) < 2 or len(active) != 1 or item["state"] != "active":
        return [
            "additional FEAT commit requires a distinct active milestone after completed "
            "pre-registered milestones"
        ]
    if any(len(milestone["evidence"]) != 1 for milestone in completed):
        return ["each completed internal milestone must bind exactly one FEAT commit"]
    recorded = [milestone["evidence"][0] for milestone in completed]
    existing = [entry["commit"] for entry in entries]
    if set(recorded) != set(existing) or len(recorded) != len(existing):
        return [
            "existing FEAT commits must exactly match distinct completed milestone evidence"
        ]
    return []


def validate_committed_work_item_boundary(
    repo: Path,
    work_item: str,
    entries: list[dict[str, Any]] | None = None,
    *,
    revision: str | None = None,
) -> list[str]:
    """Recheck result-commit cardinality from immutable Git history."""
    if entries is None:
        entries = [
            entry
            for entry in scan_commits(repo, work_item, revision=revision)
            if entry["metadata"].get("Work-Item") == work_item
        ]
    if not entries:
        return []
    schema_2_entries = [
        entry for entry in entries if entry["metadata"].get("Nova-Schema") == SCHEMA
    ]
    if not schema_2_entries:
        return []
    if len(schema_2_entries) != len(entries):
        return ["schema 2 must not reuse a schema 1 work-item identity"]
    if any(entry["errors"] for entry in entries):
        return [
            f"invalid existing work-item commit {entry['commit']}: "
            + "; ".join(entry["errors"])
            for entry in entries
            if entry["errors"]
        ]
    classes = {entry["metadata"].get("Change-Class") for entry in entries}
    if len(classes) != 1:
        return [f"inconsistent Change-Class across commits for {work_item}"]
    change_class = next(iter(classes))
    if len(entries) == 1:
        return []
    if change_class != "feature":
        return [
            f"{change_class} work items allow one implementation result commit before Review"
        ]
    try:
        item = delivery_item_for_commit_boundary(
            repo,
            work_item,
            verify_review_state=False,
            revision=revision,
        )
    except (NovaError, OSError, UnicodeError, json.JSONDecodeError) as exc:
        return [str(exc)]
    milestones = item["milestones"]
    completed = [milestone for milestone in milestones if milestone["state"] == "completed"]
    if len(milestones) < 2 or len(completed) != len(milestones):
        return [
            "multiple FEAT commits require distinct completed pre-registered milestones"
        ]
    if any(len(milestone["evidence"]) != 1 for milestone in completed):
        return ["each completed internal milestone must bind exactly one FEAT commit"]
    recorded = [milestone["evidence"][0] for milestone in completed]
    committed = [entry["commit"] for entry in entries]
    if set(recorded) != set(committed) or len(recorded) != len(committed):
        return [
            "FEAT commits must exactly match distinct completed milestone evidence"
        ]
    return []


def validate_repository_lifecycle(
    repo: Path, values: dict[str, str], *, replacing_head: bool = False
) -> list[str]:
    errors: list[str] = []
    work_item = values.get("Work-Item", "")
    related_work_item = values.get("Related-Work-Item")
    try:
        if valid_work_item(work_item) and load_completed_item(repo, work_item) is not None:
            errors.append(f"work item already archived: {work_item}")
        if related_work_item is not None:
            if load_completed_item(repo, related_work_item) is None:
                errors.append(
                    f"Related-Work-Item is not a trusted archived FEAT or legacy PEND: {related_work_item}"
                )
        if not errors and valid_work_item(work_item):
            errors.extend(
                validate_work_item_commit_boundary(
                    repo, values, replacing_head=replacing_head
                )
            )
    except (NovaError, OSError, UnicodeError, json.JSONDecodeError) as exc:
        errors.append(str(exc))
    return errors


def validate_message(
    message: str,
    diff: str | None = None,
    repo: Path | None = None,
    *,
    replacing_head: bool = False,
) -> tuple[dict[str, str], list[str]]:
    values, errors = parse_message(message)
    allow_legacy_schema = repo is None or not repository_uses_schema_2(repo)
    if not errors:
        if values.get("Commit-Kind") == "requirement":
            errors.extend(
                validate_requirement_metadata(
                    values, diff, repo, allow_legacy_schema=allow_legacy_schema
                )
            )
        elif values.get("Commit-Kind") == "architecture":
            errors.extend(validate_architecture_metadata(values, diff, repo))
        elif values.get("Commit-Kind") == "delivery-plan":
            errors.extend(
                validate_delivery_plan_metadata(
                    values, diff, repo, allow_legacy_schema=allow_legacy_schema
                )
            )
        else:
            errors.extend(
                validate_metadata(
                    values, diff, allow_legacy_schema=allow_legacy_schema
                )
            )
    if not errors:
        errors.extend(validate_subject(message, values))
    if not errors and repo is not None:
        if values.get("Nova-Schema") != SCHEMA and repository_uses_schema_2(repo):
            errors.append("Nova-Schema 1 is read-only after schema 2 activation")
        elif values.get("Commit-Kind") is None:
            errors.extend(
                validate_repository_lifecycle(
                    repo, values, replacing_head=replacing_head
                )
            )
    return values, errors


def legacy_design_ref_allowed(repo: Path, commit_hash: str, design_ref: str) -> bool:
    legacy_path = design_ref.split("#", 1)[0]
    return (
        LEGACY_DESIGN_REF_RE.fullmatch(design_ref) is not None
        and run_git_bytes(repo, "show", f"{commit_hash}:{legacy_path}", allow_missing=True) is not None
        and run_git_bytes(repo, "show", f"{commit_hash}:.nova/PROJECT_BLUEPRINT.md", allow_missing=True) is None
    )


def validate_committed_message(
    repo: Path, commit_hash: str, message: str, diff: str
) -> tuple[dict[str, str], list[str]]:
    values, errors = parse_message(message)
    if not errors:
        if values.get("Commit-Kind") == "requirement":
            errors.extend(
                validate_requirement_metadata(
                    values,
                    diff,
                    repo,
                    commit_hash=commit_hash,
                    allow_legacy_schema=True,
                )
            )
        elif values.get("Commit-Kind") == "architecture":
            errors.extend(
                validate_architecture_metadata(
                    values, diff, repo, commit_hash=commit_hash
                )
            )
        elif values.get("Commit-Kind") == "delivery-plan":
            errors.extend(
                validate_delivery_plan_metadata(
                    values,
                    diff,
                    repo,
                    commit_hash=commit_hash,
                    allow_legacy_schema=True,
                )
            )
        else:
            errors.extend(
                validate_metadata(
                    values,
                    diff,
                    allow_legacy_design_ref=legacy_design_ref_allowed(
                        repo, commit_hash, values.get("Design-Ref", "")
                    ),
                    allow_legacy_schema=True,
                )
            )
    if not errors:
        errors.extend(validate_subject(message, values))
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
        work_item_keys = {
            "Work-Item",
            "Change-Class",
            "Design-Ref",
            "Review-Policy",
            "Exemption-Rule",
        }
        if "Commit-Kind" in trailer_keys and not trailer_keys.intersection(work_item_keys):
            continue
        is_nova = bool(
            trailer_keys.intersection({"Nova-Schema", "Work-Item", "Change-Class"})
        )
        if not is_nova:
            continue
        if not errors:
            diff = None
            if values.get("Review-Policy") == "exempt":
                diff = run_git(repo, "show", "--format=", "--no-ext-diff", commit_hash)
            design_ref = values.get("Design-Ref", "")
            legacy_allowed = legacy_design_ref_allowed(repo, commit_hash, design_ref)
            errors.extend(
                validate_metadata(
                    values,
                    diff,
                    allow_legacy_design_ref=legacy_allowed,
                    allow_legacy_schema=True,
                )
            )
        commits.append({"commit": commit_hash, "metadata": values, "errors": errors})
    return commits


def feature_index_path(repo: Path, work_item: str) -> Path:
    if not valid_work_item(work_item):
        raise NovaError(f"invalid work item: {work_item}")
    shard = hashlib.sha256(work_item.encode("utf-8")).hexdigest()[:2]
    return repo / ".nova" / "audit" / "index" / shard / f"{work_item}.json"


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
    for candidate in nova_path_candidates(relative):
        value = run_git_bytes(repo, "show", f"{revision}:{candidate}", allow_missing=True)
        if value is not None:
            return value
    return None


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


def review_fix_evidence(
    repo: Path,
    scope: Any,
    *,
    target_revision: str | None = None,
) -> tuple[str, list[str], str]:
    if (
        not isinstance(scope, list)
        or any(
            not isinstance(value, str)
            or not value.startswith("main:")
            or not value.removeprefix("main:")
            for value in scope
        )
        or scope != sorted(set(scope))
    ):
        raise NovaError("review_fix_scope must be a sorted unique main:path list")
    paths = [value.removeprefix("main:") for value in scope]
    for path in paths:
        safe_repo_path(repo, path, "Review fix scope")
    if not paths:
        empty = ""
        return hashlib.sha256(empty.encode("utf-8")).hexdigest(), [], empty
    args = (
        ["diff", "--cached", "--binary", "--no-ext-diff"]
        if target_revision is None
        else [
            "diff",
            f"{target_revision}^",
            target_revision,
            "--binary",
            "--no-ext-diff",
        ]
    )
    if paths:
        args.extend(("--", *paths))
    diff = run_git(repo, *args)
    actual_paths = set(diff_paths(diff))
    if actual_paths != set(paths):
        raise NovaError(
            "Review fix scope does not match its diff paths; "
            f"expected={sorted(paths)}; actual={sorted(actual_paths)}"
        )
    return hashlib.sha256(diff.encode("utf-8")).hexdigest(), paths, diff


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
    if change_class in {"designed", "feature"}:
        design_ref = str(record.get("design_ref", ""))
        if (
            DESIGN_REF_RE.fullmatch(design_ref) is None
            and LEGACY_DESIGN_REF_RE.fullmatch(design_ref) is None
        ) or not package_ids:
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
    schema = record.get("schema") if isinstance(record, dict) else None
    if schema == 2:
        fields.update({"review_fix_sha256", "review_fix_scope", "review_heads"})
    if not isinstance(record, dict) or set(record) != fields:
        raise NovaError(f"invalid Review record fields: {path}")
    reviewed_at = parse_reviewed_at(record.get("reviewed_at"), "reviewed_at")
    batch_id = record.get("batch_id")
    if (
        schema not in {1, 2}
        or not isinstance(batch_id, str)
        or BATCH_ID_RE.fullmatch(batch_id) is None
        or batch_id[3:11] != reviewed_at.strftime("%Y%m%d")
        or record.get("conclusion") != "PASS"
        or not isinstance(record.get("review_round"), int)
        or isinstance(record.get("review_round"), bool)
        or record["review_round"] < 1
        or record["review_round"] > 3
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
    if schema == 2:
        if re.fullmatch(r"[0-9a-f]{64}", str(record.get("review_fix_sha256", ""))) is None:
            raise NovaError(f"invalid Review fix digest: {path}")
        fix_scope = record.get("review_fix_scope")
        if (
            not isinstance(fix_scope, list)
            or any(
                not isinstance(value, str)
                or not value.startswith("main:")
                or not value.removeprefix("main:")
                for value in fix_scope
            )
            or fix_scope != sorted(set(fix_scope))
        ):
            raise NovaError(f"invalid Review fix scope: {path}")
        review_heads = record.get("review_heads")
        if (
            not isinstance(review_heads, dict)
            or "main" not in review_heads
            or any(
                not isinstance(alias, str)
                or REPOSITORY_ALIAS_RE.fullmatch(alias) is None
                or not isinstance(head, str)
                or re.fullmatch(r"[0-9a-f]{40,64}", head) is None
                for alias, head in review_heads.items()
            )
        ):
            raise NovaError(f"invalid Review start heads: {path}")
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
    if schema == 2:
        referenced_aliases = {
            commit_ref["repository"]
            for item in record["items"]
            for commit_ref in item["commits"]
        }
        if not referenced_aliases.issubset(record["review_heads"]):
            raise NovaError(f"Review start heads do not cover all repositories: {path}")
    expected_paths = (
        Path(".nova/audit/reviews") / f"{reviewed_at.year:04d}" / f"{reviewed_at.month:02d}" / f"{batch_id}.yaml",
        Path("docs/audit/reviews") / f"{reviewed_at.year:04d}" / f"{reviewed_at.month:02d}" / f"{batch_id}.yaml",
    )
    if not any(tuple(path.parts[-len(expected.parts) :]) == tuple(expected.parts) for expected in expected_paths):
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

    archive_relative = f".nova/audit/features/{index['feature_year']:04d}.jsonl"
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

    normalized_review_path = normalize_nova_path(index["review_path"])
    review_path = safe_repo_path(repo, normalized_review_path, "review_path")
    expected_review_path = review_path_for_values(repo, completed_at, index["review_batch"])
    if review_path != expected_review_path:
        raise NovaError(f"feature index Review path mismatch for {work_item}")
    review_bytes = reader(normalized_review_path)
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
        related_values: set[str | None] = set()
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
            metadata, errors = parse_message(message)
            if not errors:
                errors.extend(
                    validate_metadata(
                        metadata,
                        diff,
                        allow_legacy_design_ref=legacy_design_ref_allowed(
                            repo, commit_hash, metadata.get("Design-Ref", "")
                        ),
                        allow_legacy_schema=True,
                    )
                )
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
            related_values.add(metadata.get("Related-Work-Item"))
            provided_main.add(commit_hash)
            reviewed_diffs[("main", commit_hash)] = diff

        if len(related_values) > 1:
            raise NovaError(f"inconsistent Related-Work-Item across commits for {work_item}")
        related_work_item = next(iter(related_values), None)

        required_main: set[str] = set()
        history_entries = [
            entry
            for entry in scan_commits(repo, work_item, revision)
            if entry["metadata"].get("Work-Item") == work_item
        ]
        for entry in history_entries:
            metadata = entry["metadata"]
            if entry["errors"]:
                raise NovaError(
                    f"invalid trailers in {entry['commit']}: " + "; ".join(entry["errors"])
                )
            if metadata.get("Related-Work-Item") != related_work_item:
                raise NovaError(
                    f"inconsistent Related-Work-Item across commits for {work_item}"
                )
            if metadata.get("Review-Policy") != "required":
                continue
            if (
                metadata.get("Change-Class"),
                metadata.get("Design-Ref"),
                metadata.get("Related-Work-Item"),
            ) != (
                item["change_class"],
                item["design_ref"],
                related_work_item,
            ):
                raise NovaError(f"inconsistent required commit metadata for {work_item}")
            required_main.add(entry["commit"])
        if (
            related_work_item is not None
            and load_completed_item(repo, related_work_item, revision=revision) is None
        ):
            raise NovaError(
                f"Related-Work-Item is not a trusted archived FEAT or legacy PEND: {related_work_item}"
            )
        if provided_main != required_main:
            raise NovaError(
                f"audit commit coverage mismatch for {work_item}; "
                f"missing={sorted(required_main - provided_main)}; "
                f"extra={sorted(provided_main - required_main)}"
            )
        boundary_errors = validate_committed_work_item_boundary(
            repo, work_item, history_entries, revision=revision
        )
        if boundary_errors:
            raise NovaError(
                f"invalid archived result-commit boundary for {work_item}: "
                + "; ".join(boundary_errors)
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
    legacy_layout = review_relative.startswith("docs/audit/")

    for item in review["items"]:
        if item["change_class"] not in {"designed", "feature"}:
            continue
        blueprint_relative = "PROJECT_BLUEPRINT.md" if legacy_layout else ".nova/PROJECT_BLUEPRINT.md"
        design_relative = item["design_ref"].split("#", 1)[0]
        if not legacy_layout:
            design_relative = normalize_nova_path(design_relative)
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
        requirement_ref = blueprint_requirement_ref(blueprint, item["work_item"])
        if requirement_ref != "无":
            product_relative = ".nova/PRODUCT_REQUIREMENTS.md"
            product = text_updates.get(product_relative)
            if product is None:
                product_bytes = parent_reader(product_relative)
                if product_bytes is None:
                    raise NovaError(
                        f"audit parent lacks product requirements for {item['work_item']}"
                    )
                product = product_bytes.decode("utf-8")
            delivery_relative = delivery_relative_path(requirement_ref)
            delivery_bytes = parent_reader(delivery_relative)
            if delivery_bytes is not None:
                updated_ledger, requirement_complete, implementation_evidence = (
                    update_delivery_ledger_for_pass(
                        delivery_bytes,
                        requirement_ref,
                        item["work_item"],
                        review["batch_id"],
                        review["reviewed_at"],
                    )
                )
                text_updates[delivery_relative] = updated_ledger.decode("utf-8")
                text_updates[product_relative] = (
                    update_product_requirement_status(
                        product,
                        requirement_ref,
                        item["work_item"],
                        blueprint,
                        implementation_evidence,
                    )
                    if requirement_complete
                    else product
                )
            else:
                text_updates[product_relative] = update_product_requirement_status(
                    product, requirement_ref, item["work_item"], blueprint
                )
        text_updates[blueprint_relative] = remove_blueprint_row(
            blueprint, item["work_item"], item["design_ref"], legacy_layout=legacy_layout
        )
        text_updates[design_relative] = complete_design_packages(
            design, item["package_ids"], anchor
        )

    reviewed_at = parse_reviewed_at(review["reviewed_at"], "reviewed_at")
    archive_relative = (
        f"docs/audit/features/{reviewed_at.year:04d}.jsonl"
        if legacy_layout
        else f".nova/audit/features/{reviewed_at.year:04d}.jsonl"
    )
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
        current_index = str(feature_index_path(repo, item["work_item"]).relative_to(repo))
        index_relative = (
            current_index.replace(".nova/audit/", "docs/audit/", 1)
            if legacy_layout
            else current_index
        )
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
        for candidate in nova_path_candidates(relative):
            output = run_git(repo, "ls-files", "--stage", "--", candidate)
            lines = [line for line in output.splitlines() if line]
            if not lines:
                continue
            if len(lines) != 1 or " 0\t" not in lines[0]:
                raise NovaError(f"audit index has unresolved stages for {candidate}")
            return lines[0].split(" ", 1)[0]
        return None
    for candidate in nova_path_candidates(relative):
        output = run_git(repo, "ls-tree", revision, "--", candidate)
        lines = [line for line in output.splitlines() if line]
        if not lines:
            continue
        if len(lines) != 1:
            raise NovaError(f"audit tree has ambiguous path: {candidate}")
        return lines[0].split(" ", 1)[0]
    return None


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
            rf"(?:\.nova/audit|docs/audit)/reviews/[0-9]{{4}}/[0-9]{{2}}/{re.escape(batch_id)}\.yaml",
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
    if str(review["schema"]) != values["Nova-Audit-Schema"]:
        raise NovaError("Nova-Audit-Schema does not match Review record schema")
    if review["batch_id"] != batch_id:
        raise NovaError("Review-Batch does not match Review record")
    if review["manifest_sha256"] != values["Manifest-SHA256"]:
        raise NovaError("Manifest-SHA256 does not match Review record")
    if review["schema"] == 2:
        review_parent = resolve_commit(repo, revision)
        if review["review_heads"].get("main") != review_parent:
            raise NovaError(
                "Review start HEAD does not match the closure commit parent"
            )

    expected_bytes = expected_audit_snapshot(
        repo,
        review,
        review_paths[0],
        lambda path: git_blob(repo, revision, path),
    )
    fix_paths: set[str] = set()
    if review["schema"] == 2:
        computed_fix_digest, normalized_fix_paths, _ = review_fix_evidence(
            repo,
            review["review_fix_scope"],
            target_revision=target_revision,
        )
        fix_paths = set(normalized_fix_paths)
        if computed_fix_digest != review["review_fix_sha256"]:
            raise NovaError("Review fix digest does not match the closure diff")
        if values.get("Review-Fix-SHA256") != computed_fix_digest:
            raise NovaError("Review-Fix-SHA256 does not match Review record")
    expected_changed = set(expected_bytes) | fix_paths
    if changed != expected_changed:
        raise NovaError(
            "audit diff does not exactly match the derived closure paths; "
            f"missing={sorted(expected_changed - changed)}; "
            f"extra={sorted(changed - expected_changed)}"
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
    legacy_layout = review_paths[0].startswith("docs/audit/")
    archive_relative = (
        f"docs/audit/features/{reviewed_at.year:04d}.jsonl"
        if legacy_layout
        else f".nova/audit/features/{reviewed_at.year:04d}.jsonl"
    )
    added_features = added_feature_records(diff, archive_relative)
    expected = set(expected_bytes) | fix_paths
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
        current_index = str(feature_index_path(repo, work_item).relative_to(repo))
        expected.add(
            current_index.replace(".nova/audit/", "docs/audit/", 1)
            if legacy_layout
            else current_index
        )
        if item["change_class"] not in {"designed", "feature"}:
            continue
        designed = True
        design_relative = item["design_ref"].split("#", 1)[0]
        if not legacy_layout:
            design_relative = normalize_nova_path(design_relative)
        expected.add(design_relative)
        design_bytes = reader(design_relative)
        blueprint_relative = "PROJECT_BLUEPRINT.md" if legacy_layout else ".nova/PROJECT_BLUEPRINT.md"
        blueprint_bytes = reader(blueprint_relative)
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
        expected.add("PROJECT_BLUEPRINT.md" if legacy_layout else ".nova/PROJECT_BLUEPRINT.md")
    if changed != expected:
        raise NovaError(
            f"audit diff path mismatch; missing={sorted(expected - changed)}; "
            f"extra={sorted(changed - expected)}"
        )
    for path in changed:
        safe_repo_path(repo, path, "audit diff path")
        if path == archive_relative or path in fix_paths:
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
    revision: str = "HEAD",
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    index_relative = str(feature_index_path(repo, work_item).relative_to(repo))
    commits: list[str] = []
    for candidate in nova_path_candidates(index_relative):
        found = run_git(
            repo, "log", "--follow", "--format=%H", revision, "--", candidate
        ).splitlines()
        commits.extend(value.strip() for value in found if value.strip())
    audit_commit = ""
    values: dict[str, str] = {}
    errors: list[str] = []
    for candidate in dict.fromkeys(commits):
        message = run_git(repo, "show", "-s", "--format=%B", candidate)
        candidate_values, candidate_errors = parse_audit_message(message)
        if (
            not candidate_errors
            and candidate_values.get("Nova-Audit-Schema")
            in {LEGACY_AUDIT_SCHEMA, AUDIT_SCHEMA}
        ):
            audit_commit = candidate
            values = candidate_values
            errors = []
            break
    if not audit_commit:
        return None
    if not errors:
        if values.get("Nova-Audit-Schema") not in {
            LEGACY_AUDIT_SCHEMA,
            AUDIT_SCHEMA,
        }:
            errors.append(
                f"Nova-Audit-Schema must be {LEGACY_AUDIT_SCHEMA} or {AUDIT_SCHEMA}"
            )
        if BATCH_ID_RE.fullmatch(values.get("Review-Batch", "")) is None:
            errors.append("Review-Batch must match NR-YYYYMMDD-<suffix>")
        if re.fullmatch(r"[0-9a-f]{64}", values.get("Manifest-SHA256", "")) is None:
            errors.append("Manifest-SHA256 must be 64 lowercase hexadecimal characters")
        if values.get("Nova-Audit-Schema") == AUDIT_SCHEMA and re.fullmatch(
            r"[0-9a-f]{64}", values.get("Review-Fix-SHA256", "")
        ) is None:
            errors.append("Review-Fix-SHA256 must be 64 lowercase hexadecimal characters")
        if re.search(r"\(pass\)\s*$", values.get("Validation", ""), re.IGNORECASE) is None:
            errors.append("Validation must end with (pass)")
        errors.extend(validate_audit_subject(message, values))
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
    allowed_audit_schemas = (
        {AUDIT_SCHEMA}
        if repository_uses_schema_2(repo)
        else {LEGACY_AUDIT_SCHEMA, AUDIT_SCHEMA}
    )
    if values.get("Nova-Audit-Schema") not in allowed_audit_schemas:
        errors.append(f"Nova-Audit-Schema must be {AUDIT_SCHEMA}")
    batch_id = values.get("Review-Batch", "")
    if BATCH_ID_RE.fullmatch(batch_id) is None:
        errors.append("Review-Batch must match NR-YYYYMMDD-<suffix>")
    digest = values.get("Manifest-SHA256", "")
    if re.fullmatch(r"[0-9a-f]{64}", digest) is None:
        errors.append("Manifest-SHA256 must be 64 lowercase hexadecimal characters")
    if values.get("Nova-Audit-Schema") == AUDIT_SCHEMA and re.fullmatch(
        r"[0-9a-f]{64}", values.get("Review-Fix-SHA256", "")
    ) is None:
        errors.append("Review-Fix-SHA256 must be 64 lowercase hexadecimal characters")
    if re.search(r"\(pass\)\s*$", values.get("Validation", ""), re.IGNORECASE) is None:
        errors.append("Validation must end with (pass)")
    errors.extend(validate_audit_subject(message, values))
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
        index_root = safe_repo_path(repo, ".nova/audit/index", "feature index directory")
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
        if load_completed_item(repo, work_item) is not None:
            raise NovaError(f"work item already archived: {work_item}")
        grouped[work_item].append(entry)

    if mode == "explicit":
        missing = explicit_items - grouped.keys()
        if missing:
            raise NovaError("no unreviewed required commits for: " + ", ".join(sorted(missing)))

    selected: list[dict[str, Any]] = []
    for work_item in sorted(grouped):
        entries = grouped[work_item]
        first = entries[0]["metadata"]
        identity = (
            first.get("Change-Class"),
            first.get("Design-Ref"),
            first.get("Related-Work-Item"),
        )
        if any(
            (
                entry["metadata"].get("Change-Class"),
                entry["metadata"].get("Design-Ref"),
                entry["metadata"].get("Related-Work-Item"),
            )
            != identity
            for entry in entries
        ):
            raise NovaError(f"inconsistent metadata across commits for {work_item}")
        boundary_errors = validate_committed_work_item_boundary(repo, work_item)
        if boundary_errors:
            raise NovaError(
                f"invalid result-commit boundary for {work_item}: "
                + "; ".join(boundary_errors)
            )
        selected_item = {
            "work_item": work_item,
            "change_class": identity[0],
            "design_ref": identity[1],
            "commits": [entry["commit"] for entry in entries],
            "validation": [entry["metadata"].get("Validation") for entry in entries],
        }
        if identity[2] is not None:
            related_work_item = str(identity[2])
            if load_completed_item(repo, related_work_item) is None:
                raise NovaError(
                    "Related-Work-Item is not a trusted archived FEAT or legacy PEND: "
                    f"{related_work_item}"
                )
            selected_item["related_work_item"] = related_work_item
        selected.append(selected_item)
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


def validate_review_heads(
    repositories: dict[str, Path],
    value: Any,
    *,
    existing_batch: bool = False,
    batch_id: str | None = None,
    manifest_sha256: str | None = None,
) -> dict[str, str]:
    if not isinstance(value, dict) or set(value) != set(repositories):
        raise NovaError("review_heads must contain exactly one HEAD for each repository alias")
    normalized: dict[str, str] = {}
    for alias, repository in repositories.items():
        head = value.get(alias)
        if not isinstance(head, str) or re.fullmatch(r"[0-9a-f]{40,64}", head) is None:
            raise NovaError(f"review_heads.{alias} must be a full lowercase commit hash")
        current = run_git(repository, "rev-parse", "HEAD").strip()
        if head == current:
            normalized[alias] = head
            continue
        if not existing_batch or alias != "main":
            raise NovaError(
                f"repository HEAD changed after Review started: {alias}; "
                f"expected={head}; actual={current}"
            )
        parents = run_git(
            repository, "rev-list", "--parents", "-n", "1", current
        ).split()
        if len(parents) != 2 or parents[1] != head:
            raise NovaError(
                "existing Review batch HEAD must be its unique closure commit or "
                f"the Review start HEAD: expected-parent={head}; actual={current}"
            )
        message = run_git(repository, "show", "-s", "--format=%B", current)
        values, errors = parse_audit_message(message)
        if (
            errors
            or values.get("Nova-Audit-Schema") != AUDIT_SCHEMA
            or values.get("Review-Batch") != batch_id
            or values.get("Manifest-SHA256") != manifest_sha256
        ):
            raise NovaError(
                "existing Review batch HEAD is not the matching trusted closure commit"
            )
        raw = run_git(
            repository,
            "log",
            "--format=%H%x1f%B%x1e",
            "--fixed-strings",
            f"--grep=Review-Batch: {batch_id}",
            current,
        )
        matching: list[str] = []
        for record in raw.split("\x1e"):
            record = record.strip("\n")
            if not record or "\x1f" not in record:
                continue
            commit_hash, candidate_message = record.split("\x1f", 1)
            candidate_values, candidate_errors = parse_audit_message(candidate_message)
            if (
                not candidate_errors
                and candidate_values.get("Nova-Audit-Schema") == AUDIT_SCHEMA
                and candidate_values.get("Review-Batch") == batch_id
            ):
                matching.append(commit_hash)
        if matching != [current]:
            raise NovaError(
                "existing Review batch must resolve to exactly one trusted closure commit"
            )
        diff = run_git(
            repository, "show", "--format=", "--binary", "--no-ext-diff", current
        )
        validate_audit_snapshot(
            repository,
            values,
            diff,
            lambda path: git_blob(repository, current, path),
            f"{current}^",
            current,
        )
        normalized[alias] = head
    return normalized


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
    return repo / ".nova" / "audit" / "reviews" / f"{reviewed_at.year:04d}" / f"{reviewed_at.month:02d}" / f"{batch_id}.yaml"


def feature_path(repo: Path, reviewed_at: datetime) -> Path:
    return repo / ".nova" / "audit" / "features" / f"{reviewed_at.year:04d}.jsonl"


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
    record = {
        "schema": manifest["schema"],
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
    if manifest["schema"] == 2:
        record["review_fix_sha256"] = manifest["review_fix_sha256"]
        record["review_fix_scope"] = manifest["review_fix_scope"]
        record["review_heads"] = manifest["review_heads"]
    return record


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
    base_manifest_fields = {
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
    manifest_schema = manifest.get("schema")
    if manifest_schema not in {1, 2}:
        raise NovaError("manifest schema must be 1 or 2")
    if repository_uses_schema_2(repo) and manifest_schema != 2:
        raise NovaError("manifest schema must be 2 after Nova schema 2 activation")
    allowed_manifest_fields = set(base_manifest_fields)
    if manifest_schema == 2:
        allowed_manifest_fields.update(
            {"review_fix_sha256", "review_fix_scope", "review_heads"}
        )
    required_manifest_fields = allowed_manifest_fields - {"repositories"}
    if not required_manifest_fields.issubset(manifest) or not set(manifest).issubset(
        allowed_manifest_fields
    ):
        raise NovaError("manifest has missing or unknown fields")
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
    if (
        not isinstance(manifest.get("review_round"), int)
        or isinstance(manifest["review_round"], bool)
        or not 1 <= manifest["review_round"] <= 3
    ):
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
    if manifest_schema == 2:
        validate_review_heads(
            repositories,
            manifest.get("review_heads"),
            existing_batch=existing_batch,
            batch_id=batch_id,
            manifest_sha256=digest,
        )
    review_fix_paths: list[str] = []
    review_fix_diff = ""
    if manifest_schema == 2:
        expected_fix_digest = manifest.get("review_fix_sha256")
        if re.fullmatch(r"[0-9a-f]{64}", str(expected_fix_digest or "")) is None:
            raise NovaError(
                "review_fix_sha256 must be 64 lowercase hexadecimal characters"
            )
        if existing_batch:
            scope = manifest.get("review_fix_scope")
            if (
                not isinstance(scope, list)
                or any(
                    not isinstance(value, str)
                    or not value.startswith("main:")
                    or not value.removeprefix("main:")
                    for value in scope
                )
                or scope != sorted(set(scope))
            ):
                raise NovaError(
                    "review_fix_scope must be a sorted unique main:path list"
                )
            review_fix_paths = [value.removeprefix("main:") for value in scope]
        else:
            computed_fix_digest, review_fix_paths, review_fix_diff = (
                review_fix_evidence(repo, manifest.get("review_fix_scope"))
            )
            staged = run_git(repo, "diff", "--cached", "--binary", "--no-ext-diff")
            if set(diff_paths(staged)) != set(review_fix_paths):
                raise NovaError(
                    "staged paths before record-pass must exactly match review_fix_scope"
                )
            if computed_fix_digest != expected_fix_digest:
                raise NovaError(
                    "review_fix_sha256 does not match the complete staged Review fixes"
                )

    seen_items: set[str] = set()
    normalized_items: list[dict[str, Any]] = []
    reviewed_diffs: dict[tuple[str, str], str] = {}
    for item in items:
        if not isinstance(item, dict):
            raise NovaError("each manifest item must be an object")
        work_item = item.get("work_item")
        change_class = item.get("change_class")
        class_patterns = (
            LEGACY_WORK_ITEM_PATTERNS if manifest_schema == 1 else WORK_ITEM_PATTERNS
        )
        pattern = class_patterns.get(change_class)
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
        related_values: set[str | None] = set()
        for commit_ref in commit_refs:
            commit_repo = repositories[commit_ref["repository"]]
            commit_hash = commit_ref["commit"]
            message = run_git(commit_repo, "show", "-s", "--format=%B", commit_hash)
            diff = run_git(
                commit_repo, "show", "--format=", "--binary", "--no-ext-diff", commit_hash
            )
            reviewed_diffs[(commit_ref["repository"], commit_hash)] = diff
            metadata, errors = validate_committed_message(
                commit_repo, commit_hash, message, diff
            )
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
            related_values.add(metadata.get("Related-Work-Item"))

        if len(related_values) > 1:
            raise NovaError(f"inconsistent Related-Work-Item across commits for {work_item}")
        related_work_item = next(iter(related_values), None)
        if related_work_item is not None and load_completed_item(repo, related_work_item) is None:
            raise NovaError(
                "Related-Work-Item is not a trusted archived FEAT or legacy PEND: "
                f"{related_work_item}"
            )

        provided_commits = {
            (value["repository"], value["commit"]) for value in commit_refs
        }
        required_commits: set[tuple[str, str]] = set()
        for alias, commit_repo in repositories.items():
            repository_entries: list[dict[str, Any]] = []
            for entry in scan_commits(commit_repo, work_item):
                metadata = entry["metadata"]
                if metadata.get("Work-Item") != work_item:
                    continue
                repository_entries.append(entry)
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
                    metadata.get("Related-Work-Item"),
                ) != (change_class, design_ref, related_work_item):
                    raise NovaError(f"inconsistent required commit metadata for {work_item}")
                required_commits.add((alias, entry["commit"]))
            boundary_errors = validate_committed_work_item_boundary(
                commit_repo, work_item, repository_entries
            )
            if boundary_errors:
                raise NovaError(
                    f"invalid result-commit boundary for {work_item} in {alias}: "
                    + "; ".join(boundary_errors)
                )
        if provided_commits != required_commits:
            missing = sorted(required_commits - provided_commits)
            extra = sorted(provided_commits - required_commits)
            raise NovaError(
                f"manifest commit coverage mismatch for {work_item}; "
                f"missing={missing}; extra={extra}"
            )

        normalized = dict(item)
        normalized["commits"] = commit_refs
        if change_class in {"designed", "feature"}:
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
            if not isinstance(design_ref, str) or (
                DESIGN_REF_RE.fullmatch(design_ref) is None
                and LEGACY_DESIGN_REF_RE.fullmatch(design_ref) is None
            ):
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
            if normalize_design_ref(design_ref) != normalize_design_ref(expected_ref):
                raise NovaError(f"design_ref and design_file mismatch for {work_item}")
            if normalize_nova_path(item["blueprint"]) != ".nova/PROJECT_BLUEPRINT.md":
                raise NovaError(f"blueprint must be .nova/PROJECT_BLUEPRINT.md for {work_item}")
            normalized["blueprint_path"] = safe_repo_path(
                repo, normalize_nova_path(item["blueprint"]), "blueprint"
            )
            normalized["design_path"] = safe_repo_path(
                repo, normalize_nova_path(item["design_file"]), "design_file"
            )
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
                requirement_ref = blueprint_requirement_ref(blueprint, work_item)
                if requirement_ref != "无":
                    product_path = safe_repo_path(
                        repo, ".nova/PRODUCT_REQUIREMENTS.md", "product requirements"
                    )
                    product_bytes = capture_snapshot(snapshots, product_path)
                    if product_bytes is None:
                        raise NovaError(
                            f"product requirements must exist for {work_item} requirement reference"
                        )
                    delivery_path = safe_repo_path(
                        repo, delivery_relative_path(requirement_ref), "delivery ledger"
                    )
                    delivery_bytes = capture_snapshot(snapshots, delivery_path)
                    normalized["delivery_path"] = (
                        delivery_path if delivery_bytes is not None else None
                    )
                    if delivery_bytes is not None:
                        ledger = strict_json_object(delivery_bytes, "delivery ledger")
                        if canonical_delivery_ledger(ledger) != delivery_bytes:
                            raise NovaError("delivery ledger must use canonical UTF-8 JSON")
                        validate_delivery_ledger_data(
                            repo,
                            ledger,
                            blueprint=blueprint,
                            product=product_bytes.decode("utf-8"),
                            verify_evidence=True,
                        )
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
    if manifest_schema == 2:
        reserved_paths = {
            str(output.relative_to(repo)),
            str(archive.relative_to(repo)),
        }
        for item in normalized_items:
            reserved_paths.add(str(feature_index_path(repo, item["work_item"]).relative_to(repo)))
            for field in ("blueprint_path", "design_path", "delivery_path"):
                value = item.get(field)
                if isinstance(value, Path):
                    reserved_paths.add(str(value.relative_to(repo)))
            if item["change_class"] in {"designed", "feature"}:
                reserved_paths.add(".nova/PRODUCT_REQUIREMENTS.md")
        protected_authority = sorted(
            path
            for path in review_fix_paths
            if path in {
                ".nova/PROJECT_BLUEPRINT.md",
                ".nova/PRODUCT_REQUIREMENTS.md",
                ".nova/SHARED_CAPABILITIES.md",
            }
            or path.startswith(
                (
                    ".nova/design/",
                    ".nova/delivery/",
                    ".nova/requirements/",
                    ".nova/architecture/",
                    ".nova/audit/",
                )
            )
        )
        overlap = sorted((set(review_fix_paths) & reserved_paths) | set(protected_authority))
        if overlap:
            raise NovaError(
                "Review fixes must not overlap deterministic closure paths: "
                + ", ".join(overlap)
            )
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
            if item["change_class"] not in {"designed", "feature"}:
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
            if load_completed_item(repo, item["work_item"]) is not None:
                raise NovaError(f"work item already archived: {item['work_item']}")
            index_path = safe_repo_path(
                repo,
                str(feature_index_path(repo, item["work_item"]).relative_to(repo)),
                "feature index",
            )
            if capture_snapshot(snapshots, index_path) is not None:
                raise NovaError(f"work item already archived: {item['work_item']}")
        feature_root = safe_repo_path(
            repo, ".nova/audit/features", "feature archive directory"
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
        "review_fix_paths": review_fix_paths,
        "review_fix_diff": review_fix_diff,
    }


def remove_blueprint_row(
    text: str, work_item: str, design_ref: str, *, legacy_layout: bool = False
) -> str:
    lines = text.splitlines(keepends=True)
    matches = [index for index, line in enumerate(lines) if re.match(rf"^\|\s*{re.escape(work_item)}\s*\|", line)]
    if len(matches) != 1:
        raise NovaError(f"blueprint must contain exactly one row for {work_item}")
    if f"]({blueprint_design_ref(design_ref, legacy_layout=legacy_layout)})" not in lines[matches[0]]:
        raise NovaError(f"blueprint design reference mismatch for {work_item}")
    del lines[matches[0]]
    return "".join(lines)


def blueprint_requirement_ref(text: str, work_item: str) -> str:
    matches = [
        line
        for line in text.splitlines()
        if re.match(rf"^\|\s*{re.escape(work_item)}\s*\|", line)
    ]
    if len(matches) != 1:
        raise NovaError(f"blueprint must contain exactly one row for {work_item}")
    cells = [cell.strip() for cell in matches[0].strip().strip("|").split("|")]
    if len(cells) == 7:
        return "无"
    if len(cells) not in {8, 9}:
        raise NovaError(f"blueprint pending row has invalid columns for {work_item}")
    value = cells[-1]
    link = REQUIREMENT_LINK_RE.fullmatch(value)
    normalized = link.group("ref") if link else value
    if normalized != "无" and REQUIREMENT_REF_RE.fullmatch(normalized) is None:
        raise NovaError(f"invalid requirement reference for {work_item}: {value}")
    return normalized


def blueprint_work_items_for_requirement(text: str, requirement_ref: str) -> set[str]:
    items: set[str] = set()
    for line in text.splitlines():
        if not line.lstrip().startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if (
            len(cells) in {8, 9}
            and feature_work_item(cells[0])
            and blueprint_requirement_ref(line, cells[0]) == requirement_ref
        ):
            items.add(cells[0])
    return items


def update_product_requirement_status(
    text: str,
    requirement_ref: str,
    work_item: str,
    blueprint: str,
    implementation_evidence: list[str] | None = None,
) -> str:
    key, referenced_version_text = requirement_ref.split("@v", 1)
    referenced_version = int(referenced_version_text)
    lines = text.splitlines(keepends=True)
    matches: list[tuple[int, list[str]]] = []
    for index, line in enumerate(lines):
        if not line.lstrip().startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) == 7 and cells[0] == key:
            matches.append((index, cells))
    if len(matches) != 1:
        raise NovaError(f"product requirements index must contain exactly one row for {key}")
    index, cells = matches[0]
    current_match = re.fullmatch(r"v([1-9][0-9]*)", cells[1])
    if current_match is None:
        raise NovaError(f"invalid current requirement version for {key}: {cells[1]}")
    current_version = int(current_match.group(1))
    if referenced_version > current_version:
        raise NovaError(f"reviewed requirement version is newer than current index for {key}")
    if work_item == BOOTSTRAP_CHECKPOINT_WORK_ITEM and implementation_evidence is None:
        if requirement_ref != BOOTSTRAP_REQUIREMENT_REF:
            raise NovaError("bootstrap checkpoint work item has an unexpected Requirement-Ref")
        actual_items = blueprint_work_items_for_requirement(blueprint, requirement_ref)
        if actual_items != BOOTSTRAP_WORK_ITEMS:
            raise NovaError(
                "bootstrap requirement work items do not match the confirmed temporary ledger; "
                f"expected={sorted(BOOTSTRAP_WORK_ITEMS)}; actual={sorted(actual_items)}"
            )
        if cells[2] != "待实现" or cells[5:] != ["无", "无"]:
            raise NovaError(
                "bootstrap requirement must be 待实现 with no implemented version or evidence"
            )
        if referenced_version != current_version:
            raise NovaError("bootstrap checkpoint must reference the current requirement version")
        cells[2] = "开发中"
        ending = "\n" if lines[index].endswith("\n") else ""
        lines[index] = "| " + " | ".join(cells) + " |" + ending
        return "".join(lines)
    implemented_match = re.fullmatch(r"v([1-9][0-9]*)", cells[5])
    implemented_version = int(implemented_match.group(1)) if implemented_match else 0
    if referenced_version >= implemented_version:
        implemented_version = referenced_version
        evidence = implementation_evidence or [work_item]
        if not evidence or any(not feature_work_item(value) for value in evidence):
            raise NovaError("implementation evidence must contain FEAT or legacy PEND work items")
        cells[6] = "、".join(sorted(set(evidence)))
    cells[5] = f"v{implemented_version}"
    cells[2] = "已实现" if implemented_version == current_version else "已更新"
    ending = "\n" if lines[index].endswith("\n") else ""
    lines[index] = "| " + " | ".join(cells) + " |" + ending
    return "".join(lines)


def update_product_requirement_development(text: str, requirement_ref: str) -> str:
    key, version = requirement_ref.split("@", 1)
    lines = text.splitlines(keepends=True)
    matches: list[tuple[int, list[str]]] = []
    for index, line in enumerate(lines):
        if not line.lstrip().startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) == 7 and cells[0] == key:
            matches.append((index, cells))
    if len(matches) != 1:
        raise NovaError(f"product requirements index must contain exactly one row for {key}")
    index, cells = matches[0]
    if cells[1] != version:
        raise NovaError("product requirements version does not match delivery plan")
    if cells[2] not in {"待实现", "已更新", "开发中"}:
        raise NovaError("delivery plan cannot reopen an implemented current requirement")
    if cells[2] == "待实现" and cells[5:] != ["无", "无"]:
        raise NovaError("待实现 requirement must not contain implementation evidence")
    cells[2] = "开发中"
    ending = "\n" if lines[index].endswith("\n") else ""
    lines[index] = "| " + " | ".join(cells) + " |" + ending
    return "".join(lines)


def update_delivery_ledger_for_pass(
    content: bytes,
    requirement_ref: str,
    work_item: str,
    batch_id: str,
    reviewed_at: str,
) -> tuple[bytes, bool, list[str]]:
    ledger = strict_json_object(content, "delivery ledger")
    if ledger.get("requirement_ref") != requirement_ref:
        raise NovaError("delivery ledger Requirement-Ref mismatch during Review close")
    matches = [item for item in ledger.get("work_items", []) if item.get("work_item") == work_item]
    if len(matches) != 1:
        raise NovaError(f"delivery ledger must contain exactly one work item: {work_item}")
    item = matches[0]
    if item.get("state") != "review_pending":
        raise NovaError(f"delivery work item must be review_pending before PASS: {work_item}")
    if any(milestone.get("state") != "completed" for milestone in item.get("milestones", [])):
        raise NovaError(f"delivery work item has incomplete milestones: {work_item}")
    item["state"] = "completed"
    item["blocked_reason"] = None
    ledger["plan_version"] += 1
    ledger["changes"].append(
        {
            "kind": "completed",
            "plan_version": ledger["plan_version"],
            "reason": "trusted Review PASS",
            "review_batch": batch_id,
            "reviewed_at": reviewed_at,
            "work_item": work_item,
        }
    )
    effective = [
        value
        for value in ledger["work_items"]
        if value["state"] not in {"superseded", "cancelled"}
    ]
    complete = bool(effective) and all(value["state"] == "completed" for value in effective)
    ledger["status"] = "implemented" if complete else "development"
    evidence = [value["work_item"] for value in effective if value["state"] == "completed"]
    return canonical_delivery_ledger(ledger), complete, evidence


def milestone_progress(item: dict[str, Any]) -> dict[str, Any]:
    milestones = item["milestones"]
    current = [value for value in milestones if value["state"] in {"active", "blocked"}]
    return {
        "total": len(milestones),
        "completed": len([value for value in milestones if value["state"] == "completed"]),
        "current": current[0] if current else None,
        "remaining": [value for value in milestones if value["state"] == "planned"],
        "blocked": [value for value in milestones if value["state"] == "blocked"],
    }


def query_delivery(
    repo: Path, requirement_ref: str | None = None, work_item: str | None = None
) -> dict[str, Any]:
    if bool(requirement_ref) == bool(work_item):
        raise NovaError("query-delivery requires exactly one of Requirement-Ref or Work-Item")
    delivery_root = safe_repo_path(repo, ".nova/delivery", "delivery directory")
    candidates: list[tuple[Path, dict[str, Any]]] = []
    if requirement_ref:
        path = safe_repo_path(repo, delivery_relative_path(requirement_ref), "delivery ledger")
        if not path.is_file():
            raise NovaError(f"delivery ledger not found: {requirement_ref}")
        candidates.append((path, strict_json_object(path.read_bytes(), "delivery ledger")))
    else:
        if not isinstance(work_item, str) or not valid_work_item(work_item):
            raise NovaError("Work-Item must be a valid FEAT/PATCH/FIX/MAINT or legacy identifier")
        for path in sorted(delivery_root.glob("REQ-*_v*.json")):
            value = strict_json_object(path.read_bytes(), "delivery ledger")
            if any(item.get("work_item") == work_item for item in value.get("work_items", [])):
                candidates.append((path, value))
        if len(candidates) != 1:
            raise NovaError(f"Work-Item must resolve to exactly one delivery ledger: {work_item}")
    path, ledger = candidates[0]
    if canonical_delivery_ledger(ledger) != path.read_bytes():
        raise NovaError("delivery ledger must use canonical UTF-8 JSON")
    blueprint = safe_repo_path(repo, ".nova/PROJECT_BLUEPRINT.md", "blueprint").read_text(
        encoding="utf-8"
    )
    product = safe_repo_path(
        repo, ".nova/PRODUCT_REQUIREMENTS.md", "product requirements"
    ).read_text(encoding="utf-8")
    validate_delivery_ledger_data(
        repo, ledger, blueprint=blueprint, product=product, verify_evidence=True
    )
    effective = [
        item
        for item in ledger["work_items"]
        if item["state"] not in {"superseded", "cancelled"}
    ]
    current = [
        item for item in effective if item["state"] in {"active", "review_pending", "blocked"}
    ]
    current_value = None
    if current:
        current_value = {
            "work_item": current[0]["work_item"],
            "title": current[0]["title"],
            "state": current[0]["state"],
            "milestones": milestone_progress(current[0]),
        }
    return {
        "requirement_ref": ledger["requirement_ref"],
        "requirement_commit": ledger["requirement_checkpoint"]["commit"],
        "plan_version": ledger["plan_version"],
        "status": ledger["status"],
        "total": len(effective),
        "completed": len([item for item in effective if item["state"] == "completed"]),
        "current": current_value,
        "remaining": [
            {"work_item": item["work_item"], "title": item["title"]}
            for item in effective
            if item["state"] == "planned"
        ],
        "blocked": [
            {
                "work_item": item["work_item"],
                "reason": item["blocked_reason"],
            }
            for item in effective
            if item["state"] == "blocked"
        ],
        "evidence": {
            "ledger": str(path.relative_to(repo)),
            "blueprint": ".nova/PROJECT_BLUEPRINT.md",
            "audits": [
                item["work_item"]
                for item in effective
                if item["state"] == "completed"
            ],
        },
    }


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
        if len(cells) not in {7, 8, 9} or not feature_work_item(cells[0]):
            continue
        design_cell = cells[5] if len(cells) == 9 else cells[4]
        links = re.findall(
            r"\[[^]\n]+\]\(((?:design|\.nova/design|docs/design)/[^#\s]+\.md)#[A-Za-z0-9][A-Za-z0-9._-]*\)",
            design_cell,
        )
        normalized_file = normalize_nova_path(design_file)
        if any(normalize_nova_path(link if not link.startswith("design/") else ".nova/" + link) == normalized_file for link in links):
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
        if not feature_work_item(work_item):
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
        if item["change_class"] not in {"designed", "feature"}:
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
        requirement_ref = blueprint_requirement_ref(blueprint, item["work_item"])
        if requirement_ref != "无":
            product_path = safe_repo_path(
                repo, ".nova/PRODUCT_REQUIREMENTS.md", "product requirements"
            )
            product = text_updates.get(product_path)
            if product is None:
                expected[product_path] = validated["snapshots"].get(product_path)
                if expected[product_path] is None:
                    raise NovaError(
                        f"product requirements disappeared before closure: {product_path}"
                    )
                product = expected[product_path].decode("utf-8")
            delivery_path = item.get("delivery_path")
            if delivery_path is not None:
                expected[delivery_path] = validated["snapshots"].get(delivery_path)
                delivery_bytes = expected[delivery_path]
                if delivery_bytes is None:
                    raise NovaError(f"delivery ledger disappeared before closure: {delivery_path}")
                updated_ledger, requirement_complete, implementation_evidence = (
                    update_delivery_ledger_for_pass(
                        delivery_bytes,
                        requirement_ref,
                        item["work_item"],
                        validated["manifest"]["batch_id"],
                        validated["manifest"]["reviewed_at"],
                    )
                )
                text_updates[delivery_path] = updated_ledger.decode("utf-8")
                text_updates[product_path] = (
                    update_product_requirement_status(
                        product,
                        requirement_ref,
                        item["work_item"],
                        blueprint,
                        implementation_evidence,
                    )
                    if requirement_complete
                    else product
                )
            else:
                text_updates[product_path] = update_product_requirement_status(
                    product, requirement_ref, item["work_item"], blueprint
                )
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
        archive_relative = f".nova/audit/features/{year:04d}.jsonl"
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


def query_requirement(
    repo: Path, requirement_ref: str, *, revision: str | None = None
) -> dict[str, str]:
    if REQUIREMENT_REF_RE.fullmatch(requirement_ref) is None:
        raise NovaError("Requirement-Ref must be REQ-<UUIDv7>@vN")
    args = [
        "log",
        "--format=%H%x1f%B%x1e",
        "--fixed-strings",
        f"--grep=Requirement-Ref: {requirement_ref}",
    ]
    if revision is not None:
        args.append(resolve_commit(repo, revision))
    raw = run_git(repo, *args)
    matches: list[dict[str, str]] = []
    for record in raw.split("\x1e"):
        record = record.strip("\n")
        if not record or "\x1f" not in record:
            continue
        commit_hash, message = record.split("\x1f", 1)
        values, parse_errors = parse_message(message)
        if values.get("Commit-Kind") != "requirement" or values.get("Requirement-Ref") != requirement_ref:
            continue
        diff = run_git(repo, "show", "--format=", "--binary", "--no-ext-diff", commit_hash)
        _, errors = validate_committed_message(repo, commit_hash, message, diff)
        errors = parse_errors + [error for error in errors if error not in parse_errors]
        if errors:
            raise NovaError(
                f"invalid requirement checkpoint {commit_hash}: " + "; ".join(errors)
            )
        matches.append(
            {
                "requirement_ref": requirement_ref,
                "commit": commit_hash,
                "path": values["Requirement-Path"],
                "sha256": values["Requirement-SHA256"],
                "validation": values["Validation"],
            }
        )
    if len(matches) != 1:
        raise NovaError(
            f"Requirement-Ref must have exactly one trusted checkpoint; "
            f"found={len(matches)}: {requirement_ref}"
        )
    return matches[0]


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    commands = root.add_subparsers(dest="command", required=True)

    new_id = commands.add_parser("new-id")
    new_id.add_argument(
        "--class", dest="change_class", choices=tuple(NEW_WORK_ITEM_PREFIXES), required=True
    )
    commands.add_parser("new-requirement-id")
    commands.add_parser("new-architecture-id")

    validate = commands.add_parser("validate-message")
    validate.add_argument("--repo", type=Path)
    validate.add_argument("--message-file", type=Path, required=True)
    validate.add_argument("--diff-file", type=Path)
    validate.add_argument(
        "--amend",
        action="store_true",
        help="validate replacing the same unreviewed Work-Item commit at HEAD",
    )

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
    requirement = commands.add_parser("query-requirement")
    requirement.add_argument("--repo", type=Path, required=True)
    requirement.add_argument("--requirement-ref", required=True)
    delivery = commands.add_parser("query-delivery")
    delivery.add_argument("--repo", type=Path, required=True)
    delivery_group = delivery.add_mutually_exclusive_group(required=True)
    delivery_group.add_argument("--requirement-ref")
    delivery_group.add_argument("--work-item")
    report_template = commands.add_parser("report-template")
    report_template.add_argument("--stage", choices=tuple(REPORT_TITLES), required=True)
    validate_report = commands.add_parser("validate-report")
    validate_report.add_argument("--stage", choices=tuple(REPORT_TITLES), required=True)
    validate_report.add_argument("--report-file", type=Path, required=True)
    validate_report.add_argument(
        "--emit-report",
        action="store_true",
        help="write the validated report bytes to stdout instead of a PASS summary",
    )
    return root


def main() -> int:
    args = parser().parse_args()
    try:
        if args.command == "new-id":
            print(new_work_item(args.change_class))
        elif args.command == "new-requirement-id":
            print(new_requirement_id())
        elif args.command == "new-architecture-id":
            print(new_architecture_id())
        elif args.command == "report-template":
            print(completion_report_template(args.stage), end="")
        elif args.command == "validate-report":
            report_bytes = args.report_file.read_bytes()
            report = report_bytes.decode("utf-8")
            errors = validate_completion_report(args.stage, report)
            if errors:
                raise NovaError("; ".join(errors))
            if args.emit_report:
                sys.stdout.buffer.write(report_bytes)
            else:
                print(f"PASS: {args.stage} completion report")
        elif args.command == "validate-message":
            message = args.message_file.read_text(encoding="utf-8")
            diff = args.diff_file.read_text(encoding="utf-8") if args.diff_file else None
            repo = args.repo.resolve() if args.repo else None
            if args.amend and repo is None:
                raise NovaError("--amend requires --repo")
            metadata, errors = validate_message(
                message, diff, repo, replacing_head=args.amend
            )
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
        elif args.command == "query-requirement":
            result = query_requirement(args.repo.resolve(), args.requirement_ref)
            print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        elif args.command == "query-delivery":
            result = query_delivery(
                args.repo.resolve(), args.requirement_ref, args.work_item
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
