#!/usr/bin/env python3
"""Validate a versioned project blueprint or epic design document."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path


BLUEPRINT_VERSION = "3"
DESIGN_VERSION = "5"
COMPATIBLE_DESIGN_VERSION = "4"
LEGACY_DESIGN_VERSION = "3"
LEGACY_SNAPSHOT_MANIFEST = ".v3-legacy-snapshots.json"
COMPATIBLE_SNAPSHOT_MANIFEST = ".v4-compatible-snapshots.json"
CONFIRMATION_PENDING = "待确认"
CONFIRMATION_RE = re.compile(r"^用户明确确认@sha256:([0-9a-f]{64})$")
BLUEPRINT_SECTIONS = (
    "项目定位",
    "技术栈",
    "代码结构",
    "模块架构",
    "跨模块契约",
    "交付工作项",
    "系统架构",
)
LEGACY_BLUEPRINT_SECTIONS = BLUEPRINT_SECTIONS[:5] + ("待开发功能",) + BLUEPRINT_SECTIONS[6:]
FORBIDDEN_BLUEPRINT_HEADINGS = {"非目标", "架构红线", "项目级待确认事项"}
BOUNDARY_VALUES = (
    "本期必须实现",
    "明确不做",
    "后续候选",
    "AI 可自行决定",
    "必须再次确认",
)
LEGACY_PENDING_HEADERS = ("编号", "优先级", "来源", "功能", "设计依据", "前置依赖", "完成定义")
COMPATIBLE_PENDING_HEADERS = LEGACY_PENDING_HEADERS + ("需求引用",)
PENDING_HEADERS = ("编号", "状态") + COMPATIBLE_PENDING_HEADERS[1:]
PENDING_SOURCES = {"用户提出", "Review-Defer", "问题诊断", "历史迁移"}
PENDING_STATES = {"待澄清", "待开发", "待Review"}
CODE_PLACEMENT_HEADERS = ("代码区域", "职责", "代码落位规则")
MODULE_HEADERS = ("模块", "职责", "对外边界")
GLOBAL_CONTRACT_HEADERS = ("契约", "适用范围", "验证")
BOUNDARY_HEADERS = ("边界", "内容")
LAYER_HEADERS = ("层", "职责", "对应代码结构", "允许依赖")
RESOURCE_HEADERS = ("适用范围", "不变量", "验证")
RECOVERY_HEADERS = ("资源或失败点", "所有者", "恢复与清理")

PROBLEM_HEADERS = ("问题", "成功结果")
LEGACY_SHARED_CONTRACT_HEADERS = ("契约", "已确认约束")
SHARED_CONTRACT_HEADERS = ("契约", "语义键", "唯一规则")
LEGACY_WORK_PACKAGE_HEADERS = ("工作包", "状态", "交付结果", "前置依赖", "设计章节")
WORK_PACKAGE_HEADERS = ("工作包", "角色", "状态", "交付结果", "前置依赖", "设计章节")
LEGACY_PACKAGE_CONTRACT_HEADERS = ("契约", "维度", "已确认约束")
PACKAGE_CONTRACT_HEADERS = ("契约", "维度", "语义键", "唯一规则")
ACCEPTANCE_HEADERS = ("覆盖契约", "场景", "预期结果")
CLARIFICATION_HEADERS = ("类型", "内容", "来源")
CONTRACT_DIMENSIONS = (
    "交付边界",
    "参与者与权限",
    "触发与输入",
    "结果、状态与不变量",
    "失败与恢复",
    "AI 决策边界",
)
CLARIFICATION_TYPES = {"证据推断", "待确认"}
DESIGN_STATES = {"澄清中", "已确认", "已实现", "已废弃"}
WORK_PACKAGE_STATES = {"待澄清", "澄清中", "已确认", "开发中", "待Review", "已完成", "已废弃"}
WORK_PACKAGE_ROLES = {"能力", "收口"}
TERMINAL_WORK_PACKAGE_STATES = {"已完成", "已废弃"}
REFERENCED_WORK_PACKAGE_STATES = {"已确认", "开发中", "待Review"}

TASK_ID_RE = re.compile(
    r"^(?:FEAT-[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}|PEND-[A-Za-z0-9._-]+)$"
)
LEGACY_TASK_ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9._-]*$")
REQUIREMENT_REF_RE = re.compile(
    r"^REQ-[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}@v[1-9][0-9]*$"
)
REQUIREMENT_LINK_RE = re.compile(
    r"^\[(REQ-[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}@v[1-9][0-9]*)\]\(([^)\s]+\.md)\)$"
)
WORK_PACKAGE_ID_RE = re.compile(r"^WP-[A-Za-z0-9._-]+$")
SHARED_CONTRACT_ID_RE = re.compile(r"^S-[A-Za-z0-9._-]+$")
GLOBAL_CONTRACT_ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9._-]*$")
ANCHOR_RE = re.compile(r"<a\s+id=[\"']([A-Za-z0-9][A-Za-z0-9._-]*)[\"']\s*></a>", re.IGNORECASE)
DESIGN_LINK_RE = re.compile(
    r"^\[[^]\n]+\]\((?:<)?([^\s>#]+\.md)#([A-Za-z0-9][A-Za-z0-9._-]*)(?:>)?\)$"
)
DESIGN_FILENAME_RE = re.compile(
    r"^(?P<created>\d{4}-\d{2}-\d{2})_(?P<name>[^\s/\\]+)\.md$"
)
EVOLUTION_LINK_RE = re.compile(r"^\[[^]\n]+\]\((?:<)?([^\s\\>#]+\.md)(?:>)?\)$")
LOCAL_LINK_RE = re.compile(r"^\[[^]\n]+\]\(#([A-Za-z0-9][A-Za-z0-9._-]*)\)$")
PLACEHOLDERS = (
    re.compile(r"<(?!/?a\b)[^>\n]+>", re.IGNORECASE),
    re.compile(r"\{\{[^}\n]+\}\}"),
    re.compile(r"\[(?:TODO|TBD)[^]\n]*\]", re.IGNORECASE),
    re.compile(r"(?:TODO|TBD)\s*:", re.IGNORECASE),
)
FENCE_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
HEADING_RE = re.compile(r"^(#{1,6})[ \t]+(.+?)\s*$")
NUMBERED_HEADING_RE = re.compile(r"^\d+(?:\.\d+)*(?:[.、])?\s+")


@dataclass(frozen=True)
class Heading:
    index: int
    level: int
    title: str


@dataclass(frozen=True)
class WorkPackageSection:
    package_id: str
    start: int
    end: int
    anchor: str | None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--design", action="store_true", help="validate an epic design document")
    parser.add_argument("path", nargs="?", default=".nova/PROJECT_BLUEPRINT.md")
    return parser.parse_args()


def read_document(path: Path) -> tuple[str | None, list[str]]:
    if not path.is_file():
        return None, [f"file not found: {path}"]
    try:
        return path.read_bytes().decode("utf-8"), []
    except (OSError, UnicodeError) as exc:
        return None, [f"cannot read document: {exc}"]


def git_head_path_candidates(relative_path: str) -> tuple[str, ...]:
    """Resolve current .nova paths against pre-migration immutable Git history."""
    candidates = [relative_path]
    legacy_prefixes = {
        ".nova/design/": "docs/design/",
        ".nova/audit/": "docs/audit/",
        ".nova/requirements/": "docs/requirements/",
        ".nova/architecture/": "docs/architecture/",
    }
    if relative_path == ".nova/PROJECT_BLUEPRINT.md":
        candidates.append("PROJECT_BLUEPRINT.md")
    elif relative_path == ".nova/PRODUCT_REQUIREMENTS.md":
        candidates.append("PRODUCT_REQUIREMENTS.md")
    else:
        for current, legacy in legacy_prefixes.items():
            if relative_path.startswith(current):
                candidates.append(legacy + relative_path[len(current):])
                break
    return tuple(candidates)


def validate_legacy_design_snapshot(path: Path, text_snapshot: str) -> list[str]:
    manifest_path = path.parent / LEGACY_SNAPSHOT_MANIFEST
    manifest_text, read_errors = read_document(manifest_path)
    if manifest_text is None:
        return [
            "terminal legacy design must match a registered Git HEAD snapshot: " + error
            for error in read_errors
        ]
    try:
        manifest = json.loads(manifest_text)
    except json.JSONDecodeError as exc:
        return [f"invalid legacy design snapshot manifest: {exc}"]
    if not isinstance(manifest, dict):
        return ["legacy design snapshot manifest must use schema 1 with a files object"]
    files = manifest.get("files")
    if manifest.get("schema") != 1 or not isinstance(files, dict):
        return ["legacy design snapshot manifest must use schema 1 with a files object"]
    expected = files.get(path.name)
    if not isinstance(expected, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", expected):
        return [
            f"terminal legacy design must match a registered Git HEAD snapshot: {path.name}"
        ]

    content = text_snapshot.encode("utf-8")
    actual = "sha256:" + hashlib.sha256(content).hexdigest()
    if actual != expected:
        return [f"legacy design snapshot content does not match manifest: {path.name}"]

    try:
        root_result = subprocess.run(
            ["git", "-C", str(path.parent), "rev-parse", "--show-toplevel"],
            check=False,
            capture_output=True,
        )
    except OSError as exc:
        return [f"cannot verify legacy design snapshot in Git HEAD: {exc}"]
    if root_result.returncode != 0:
        return [f"legacy design snapshot requires a Git repository: {path.name}"]
    try:
        repository_root = Path(root_result.stdout.decode("utf-8").strip()).resolve()
        relative_path = path.resolve().relative_to(repository_root).as_posix()
    except (UnicodeError, ValueError) as exc:
        return [f"cannot resolve legacy design snapshot in Git repository: {exc}"]

    head_result = None
    try:
        for candidate in git_head_path_candidates(relative_path):
            result = subprocess.run(
                ["git", "-C", str(repository_root), "show", f"HEAD:{candidate}"],
                check=False,
                capture_output=True,
            )
            if result.returncode == 0:
                head_result = result
                break
    except OSError as exc:
        return [f"cannot verify legacy design snapshot in Git HEAD: {exc}"]
    if head_result is None:
        return [f"legacy design snapshot is not present in Git HEAD: {path.name}"]
    if head_result.stdout != content:
        return [f"legacy design snapshot differs from Git HEAD: {path.name}"]
    return []


def validate_compatible_design_snapshot(path: Path, text_snapshot: str) -> list[str]:
    """Allow version 4 only when its semantics match a registered or Git HEAD baseline."""
    manifest_path = path.parent / COMPATIBLE_SNAPSHOT_MANIFEST
    manifest_text, read_errors = read_document(manifest_path)
    expected: str | None = None
    if manifest_text is not None:
        try:
            manifest = json.loads(manifest_text)
        except json.JSONDecodeError as exc:
            return [f"invalid compatible design snapshot manifest: {exc}"]
        if not isinstance(manifest, dict):
            return ["compatible design snapshot manifest must use schema 1 with a files object"]
        files = manifest.get("files")
        if manifest.get("schema") != 1 or not isinstance(files, dict):
            return ["compatible design snapshot manifest must use schema 1 with a files object"]
        expected = files.get(path.name)
        if expected is not None and (
            not isinstance(expected, str)
            or not re.fullmatch(r"sha256:[0-9a-f]{64}", expected)
        ):
            return [f"invalid compatible design semantic baseline: {path.name}"]
    elif manifest_path.exists():
        return [
            "cannot read compatible design snapshot manifest: " + error
            for error in read_errors
        ]

    try:
        root_result = subprocess.run(
            ["git", "-C", str(path.parent), "rev-parse", "--show-toplevel"],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError as exc:
        return [f"cannot verify compatible design baseline in Git HEAD: {exc}"]
    if root_result.returncode != 0:
        return [f"compatible version 4 design requires a Git repository: {path.name}"]
    repository_root = Path(root_result.stdout.strip()).resolve()
    try:
        relative_path = path.resolve().relative_to(repository_root).as_posix()
    except ValueError:
        return [f"compatible version 4 design must stay inside its Git repository: {path.name}"]
    head_result = None
    try:
        for candidate in git_head_path_candidates(relative_path):
            result = subprocess.run(
                ["git", "-C", str(repository_root), "show", f"HEAD:{candidate}"],
                check=False,
                capture_output=True,
            )
            if result.returncode == 0:
                head_result = result
                break
    except OSError as exc:
        return [f"cannot verify compatible design baseline in Git HEAD: {exc}"]
    if head_result is None:
        return [f"compatible version 4 design is not present in Git HEAD: {path.name}"]
    try:
        head_text = head_result.stdout.decode("utf-8")
    except UnicodeError as exc:
        return [f"cannot decode compatible design baseline from Git HEAD: {exc}"]

    head_fingerprint = "sha256:" + design_semantic_fingerprint(
        path, text_snapshot=head_text
    )
    if expected is not None and head_fingerprint != expected:
        return [f"compatible design Git HEAD semantics do not match manifest: {path.name}"]
    baseline_fingerprint = expected or head_fingerprint
    current_fingerprint = "sha256:" + design_semantic_fingerprint(
        path, text_snapshot=text_snapshot
    )
    if current_fingerprint != baseline_fingerprint:
        return [
            f"compatible version 4 design semantics changed; upgrade to version {DESIGN_VERSION}: "
            f"{path.name}"
        ]
    return []


def validate_design_filename(path: Path) -> list[str]:
    match = DESIGN_FILENAME_RE.fullmatch(path.name)
    if not match:
        return [f"design filename must match YYYY-MM-DD_具体名称.md: {path.name}"]
    try:
        date.fromisoformat(match.group("created"))
    except ValueError:
        return [f"design filename date must be a valid calendar date: {match.group('created')}"]
    return []


def validate_evolution_source(
    path: Path, value: str, evolution_stack: frozenset[Path]
) -> list[str]:
    if value == "无":
        return []
    match = EVOLUTION_LINK_RE.fullmatch(value)
    if not match:
        return ["design evolution source must be 无 or one same-directory markdown link"]
    source_path = Path(match.group(1))
    if source_path.is_absolute():
        return ["design evolution source must stay in the same docs/design directory"]
    target = (path.parent / source_path).resolve()
    if target.parent != path.parent.resolve():
        return ["design evolution source must stay in the same docs/design directory"]
    if target == path.resolve():
        return ["design evolution source must not reference itself"]
    filename_errors = validate_design_filename(target)
    if filename_errors:
        return [f"invalid design evolution source: {error}" for error in filename_errors]
    text, read_errors = read_document(target)
    if text is None:
        return [f"invalid design evolution source: {error}" for error in read_errors]
    target_errors, _ = validate_design(target, evolution_stack, text_snapshot=text)
    if target_errors:
        return [f"invalid design evolution source: {error}" for error in target_errors]
    lines, _ = markdown_structure_lines(text)
    structural_text = "\n".join(lines)
    state_match = re.search(r"^>\s*设计状态[：:]\s*(\S+)\s*$", structural_text, re.MULTILINE)
    state = state_match.group(1) if state_match else "missing"
    if state not in {"已实现", "已废弃"}:
        return [f"design evolution source must be terminal, found: {state}"]
    return []


def markdown_structure_lines(text: str) -> tuple[list[str], bool]:
    """Blank fenced-code content while preserving line numbers."""
    result: list[str] = []
    fence_character: str | None = None
    fence_length = 0
    for line in text.splitlines():
        match = FENCE_RE.match(line)
        if fence_character is None:
            if match:
                marker = match.group(1)
                fence_character = marker[0]
                fence_length = len(marker)
                result.append("")
            else:
                result.append(line)
            continue
        if match and not match.group(2).strip():
            marker = match.group(1)
            if marker[0] == fence_character and len(marker) >= fence_length:
                fence_character = None
                fence_length = 0
        result.append("")
    return result, fence_character is None


def heading(line: str) -> tuple[int, str] | None:
    match = HEADING_RE.match(line)
    if not match:
        return None
    return len(match.group(1)), match.group(2).strip()


def normalized_heading(title: str) -> str:
    without_closing = re.sub(r"[ \t]+#+[ \t]*$", "", title.strip())
    return NUMBERED_HEADING_RE.sub("", without_closing).strip()


def heading_entries(lines: list[str]) -> list[Heading]:
    entries: list[Heading] = []
    for index, line in enumerate(lines):
        parsed = heading(line)
        if parsed:
            entries.append(Heading(index, parsed[0], normalized_heading(parsed[1])))
    return entries


def common_errors(text: str) -> tuple[list[str], list[str]]:
    lines, balanced = markdown_structure_lines(text)
    errors: list[str] = []
    if not balanced:
        errors.append("unclosed fenced code block")
    structural_text = "\n".join(lines)
    for pattern in PLACEHOLDERS:
        match = pattern.search(structural_text)
        if match:
            errors.append(f"unfinished placeholder found: {match.group(0)}")
            break
    return lines, errors


def markdown_cells(line: str) -> list[str]:
    stripped = line.strip()
    if not stripped.startswith("|") or not stripped.endswith("|"):
        return []
    cells: list[str] = []
    current: list[str] = []
    escaped = False
    for char in stripped[1:-1]:
        if escaped:
            current.append(char)
            escaped = False
        elif char == "\\":
            current.append(char)
            escaped = True
        elif char == "|":
            cells.append("".join(current).strip())
            current = []
        else:
            current.append(char)
    cells.append("".join(current).strip())
    return cells


def heading_block(entries: list[Heading], selected: Heading, line_count: int) -> tuple[int, int]:
    end = line_count
    for entry in entries:
        if entry.index > selected.index and entry.level <= selected.level:
            end = entry.index
            break
    return selected.index + 1, end


def find_heading(
    entries: list[Heading], title: str, start: int = 0, end: int | None = None
) -> tuple[Heading | None, list[str]]:
    limit = end if end is not None else 10**12
    matches = [entry for entry in entries if start <= entry.index < limit and entry.title == title]
    if not matches:
        return None, [f"missing {title} section"]
    if len(matches) > 1:
        return matches[0], [f"duplicate {title} section"]
    return matches[0], []


def parse_table(
    lines: list[str], start: int, end: int, headers: tuple[str, ...], table_name: str
) -> tuple[list[list[str]], list[str]]:
    table_start: int | None = None
    for index in range(start, end):
        if lines[index].strip().startswith("|"):
            table_start = index
            break
    if table_start is None:
        return [], [f"{table_name} table is missing"]

    table_lines: list[str] = []
    for index in range(table_start, end):
        if not lines[index].strip().startswith("|"):
            break
        table_lines.append(lines[index])
    if len(table_lines) < 2:
        return [], [f"{table_name} table is incomplete"]

    errors: list[str] = []
    parsed_headers = markdown_cells(table_lines[0])
    if tuple(parsed_headers) != headers:
        errors.append(f"{table_name} table headers must be: " + " | ".join(headers))
    separator = markdown_cells(table_lines[1])
    if len(separator) != len(headers) or not all(
        re.fullmatch(r":?-{3,}:?", cell.replace(" ", "")) for cell in separator
    ):
        errors.append(f"{table_name} table separator is invalid")

    rows: list[list[str]] = []
    for line in table_lines[2:]:
        cells = markdown_cells(line)
        if len(cells) != len(headers):
            errors.append(f"{table_name} row must contain {len(headers)} cells: {line}")
            continue
        rows.append(cells)
    return rows, errors


def table_under_heading(
    lines: list[str],
    entries: list[Heading],
    heading_title: str,
    headers: tuple[str, ...],
    table_name: str,
    start: int = 0,
    end: int | None = None,
) -> tuple[list[list[str]], list[str]]:
    selected, errors = find_heading(entries, heading_title, start, end)
    if selected is None:
        return [], errors
    block_start, block_end = heading_block(entries, selected, len(lines))
    if end is not None:
        block_end = min(block_end, end)
    rows, table_errors = parse_table(lines, block_start, block_end, headers, table_name)
    return rows, errors + table_errors


def duplicate_values(values: list[str]) -> set[str]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for value in values:
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    return duplicates


def split_ids(value: str) -> list[str]:
    return [part.strip() for part in re.split(r"[、,，]", value)]


def validate_dependency(
    owner_id: str, value: str, valid_ids: set[str], id_pattern: re.Pattern[str], context: str
) -> list[str]:
    if value == "无":
        return []
    if context == "pending work" and value == "待澄清":
        return []
    if value.startswith("待确认："):
        return [] if value.removeprefix("待确认：").strip() else [
            f"pending {context} dependency must state the concrete question for {owner_id}"
        ]
    if value == "待澄清":
        return [f"ambiguous {context} dependency for {owner_id}: 待澄清"]
    dependencies = split_ids(value)
    if not dependencies:
        return [f"invalid {context} dependency for {owner_id}: {value}"]
    errors: list[str] = []
    seen: set[str] = set()
    for dependency in dependencies:
        if dependency in seen:
            errors.append(f"duplicate {context} dependency for {owner_id}: {dependency}")
        if not id_pattern.fullmatch(dependency):
            errors.append(f"invalid {context} dependency for {owner_id}: {dependency}")
        elif dependency == owner_id:
            errors.append(f"self dependency for {owner_id}")
        elif dependency not in valid_ids:
            errors.append(f"unknown {context} dependency for {owner_id}: {dependency}")
        seen.add(dependency)
    return errors


def validate_work_package_dependency_graph(
    package_ids: list[str], dependency_by_id: dict[str, str], closure_ids: list[str]
) -> list[str]:
    valid_ids = set(package_ids)
    graph = {
        package_id: [
            dependency
            for dependency in split_ids(dependency_by_id.get(package_id, "无"))
            if dependency in valid_ids
        ]
        if dependency_by_id.get(package_id, "无") not in {"无", "待澄清"}
        and not dependency_by_id.get(package_id, "无").startswith("待确认：")
        else []
        for package_id in package_ids
    }
    errors: list[str] = []
    if len(closure_ids) == 1:
        closure_id = closure_ids[0]
        for package_id in package_ids:
            if package_id != closure_id and closure_id in graph[package_id]:
                errors.append(
                    f"capability work package {package_id} must not depend on closure work package {closure_id}"
                )

    visiting: list[str] = []
    visited: set[str] = set()

    def visit(package_id: str) -> list[str] | None:
        if package_id in visiting:
            start = visiting.index(package_id)
            return visiting[start:] + [package_id]
        if package_id in visited:
            return None
        visiting.append(package_id)
        for dependency in graph[package_id]:
            cycle = visit(dependency)
            if cycle:
                return cycle
        visiting.pop()
        visited.add(package_id)
        return None

    for package_id in package_ids:
        cycle = visit(package_id)
        if cycle:
            errors.append(
                "work package dependency graph must be acyclic: " + " -> ".join(cycle)
            )
            break
    return errors


def explicit_anchors(lines: list[str]) -> list[str]:
    anchors: list[str] = []
    for line in lines:
        match = ANCHOR_RE.fullmatch(line.strip())
        if match:
            anchors.append(match.group(1))
    return anchors


def anchor_matches_package_id(anchor: str, package_id: str) -> bool:
    anchor_lower = anchor.lower()
    package_lower = package_id.lower()
    return anchor_lower == package_lower or (
        anchor_lower.startswith(package_lower)
        and len(anchor_lower) > len(package_lower)
        and anchor_lower[len(package_lower)] in "-._"
    )


def work_package_sections(lines: list[str], entries: list[Heading]) -> list[WorkPackageSection]:
    packages: list[WorkPackageSection] = []
    for entry in entries:
        if entry.level != 2:
            continue
        match = re.match(r"^(WP-[A-Za-z0-9._-]+)(?:\s+|$)", entry.title)
        if not match:
            continue
        package_id = match.group(1)
        _, end = heading_block(entries, entry, len(lines))
        anchor = None
        index = entry.index - 1
        while index >= 0 and not lines[index].strip():
            index -= 1
        if index >= 0:
            anchor_match = ANCHOR_RE.fullmatch(lines[index].strip())
            if anchor_match:
                anchor = anchor_match.group(1)
        packages.append(WorkPackageSection(package_id, entry.index, end, anchor))
    return packages


def within_design_root(blueprint: Path, target: Path) -> bool:
    design_root = (blueprint.parent / "design").resolve()
    try:
        target.relative_to(design_root)
    except ValueError:
        return False
    return True


def validate_design_reference(blueprint: Path, value: str) -> list[str]:
    if value.startswith("待澄清：") and value.removeprefix("待澄清：").strip():
        return []
    if value == "待澄清":
        return ["design basis 待澄清 must state the missing decision"]
    match = DESIGN_LINK_RE.fullmatch(value)
    if not match:
        return [f"design basis must state a concrete 待澄清 reason or one markdown file anchor link: {value}"]
    relative_path, anchor = match.groups()
    target = (blueprint.parent / relative_path).resolve()
    if not within_design_root(blueprint, target):
        return [f"design basis must stay under .nova/design: {relative_path}"]
    text, errors = read_document(target)
    if text is None:
        return errors
    design_errors, _ = validate_design(target, text_snapshot=text)
    if design_errors:
        return [f"invalid design document {relative_path}: {error}" for error in design_errors]
    lines, _ = common_errors(text)
    structural_text = "\n".join(lines)
    version_match = re.search(r"^>\s*设计规范版本[：:]\s*(\S+)\s*$", structural_text, re.MULTILINE)
    version = version_match.group(1) if version_match else DESIGN_VERSION
    anchors = explicit_anchors(lines)
    if anchor not in anchors:
        return [f"design anchor not found: {relative_path}#{anchor}"]
    entries = heading_entries(lines)
    packages = work_package_sections(lines, entries)
    matching = [package for package in packages if package.anchor == anchor]
    if len(matching) != 1:
        return [f"design anchor must identify one work package: {relative_path}#{anchor}"]
    package = matching[0]
    if not anchor_matches_package_id(anchor, package.package_id):
        return [f"design anchor does not match work package {package.package_id}: {anchor}"]
    rows, table_errors = table_under_heading(
        lines,
        entries,
        "工作包地图",
        LEGACY_WORK_PACKAGE_HEADERS if version == LEGACY_DESIGN_VERSION else WORK_PACKAGE_HEADERS,
        "work package map",
    )
    if table_errors:
        return [f"invalid design document {relative_path}: {error}" for error in table_errors]
    state_by_id = {row[0]: row[1] if version == LEGACY_DESIGN_VERSION else row[2] for row in rows}
    state = state_by_id.get(package.package_id)
    if state is None:
        return [f"design work package missing from map: {relative_path}#{anchor}"]
    if state in TERMINAL_WORK_PACKAGE_STATES:
        return [f"pending work cannot reference terminal design work package: {relative_path}#{anchor} ({state})"]
    if state not in REFERENCED_WORK_PACKAGE_STATES:
        return [
            "pending work must reference a confirmed, in-development, or pending-review design work package: "
            f"{relative_path}#{anchor} ({state})"
        ]
    return []


def referenced_design_requirement(blueprint: Path, value: str) -> str | None:
    match = DESIGN_LINK_RE.fullmatch(value)
    if match is None:
        return None
    target = (blueprint.parent / match.group(1)).resolve()
    text, _ = read_document(target)
    if text is None:
        return None
    values = re.findall(r"^>\s*Requirement-Ref[：:]\s*(.+?)\s*$", text, re.MULTILINE)
    return values[0] if len(values) == 1 else "无"


def validate_requirement_reference(blueprint: Path, value: str) -> tuple[str | None, list[str]]:
    if value == "无":
        return "无", []
    match = REQUIREMENT_LINK_RE.fullmatch(value)
    if match is None:
        return None, [f"requirement reference must be 无 or a REQ@version markdown link: {value}"]
    requirement_ref, relative_path = match.groups()
    target = (blueprint.parent / relative_path).resolve()
    requirements_root = (blueprint.parent / "requirements").resolve()
    try:
        target.relative_to(requirements_root)
    except ValueError:
        return None, [f"requirement reference must stay under .nova/requirements: {relative_path}"]
    text, errors = read_document(target)
    if text is None:
        return None, errors
    key, version = requirement_ref.split("@", 1)
    keys = re.findall(r"^>\s*Requirement-Key[：:]\s*(.+?)\s*$", text, re.MULTILINE)
    versions = re.findall(r"^>\s*需求版本[：:]\s*(.+?)\s*$", text, re.MULTILINE)
    if keys != [key] or versions != [version]:
        return None, [f"requirement link metadata does not match {requirement_ref}: {relative_path}"]
    return requirement_ref, []


def head_has_legacy_pending_layout(path: Path) -> bool:
    try:
        repo_result = subprocess.run(
            ["git", "-C", str(path.parent), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return False
    repo = Path(repo_result.stdout.strip()).resolve()
    try:
        relative = path.resolve().relative_to(repo).as_posix()
    except ValueError:
        return False
    legacy_header = "| 编号 | 优先级 | 来源 | 功能 | 设计依据 | 前置依赖 | 完成定义 |"
    for candidate in git_head_path_candidates(relative):
        result = subprocess.run(
            ["git", "-C", str(repo), "show", f"HEAD:{candidate}"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0 and legacy_header in result.stdout:
            return True
    return False


def head_pending_ids(path: Path) -> set[str]:
    """Return PEND identities already present in the committed blueprint."""
    try:
        repo_result = subprocess.run(
            ["git", "-C", str(path.parent), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return set()
    repo = Path(repo_result.stdout.strip()).resolve()
    try:
        relative = path.resolve().relative_to(repo).as_posix()
    except ValueError:
        return set()
    for candidate in git_head_path_candidates(relative):
        result = subprocess.run(
            ["git", "-C", str(repo), "show", f"HEAD:{candidate}"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0:
            return set(
                re.findall(r"^\|\s*(PEND-[A-Za-z0-9._-]+)\s*\|", result.stdout, re.MULTILINE)
            )
    return set()


def git_head_matches_document(path: Path, text: str) -> bool:
    try:
        repo_result = subprocess.run(
            ["git", "-C", str(path.parent), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return False
    repo = Path(repo_result.stdout.strip()).resolve()
    try:
        relative = path.resolve().relative_to(repo).as_posix()
    except ValueError:
        return False
    expected = text.encode("utf-8")
    return any(
        subprocess.run(
            ["git", "-C", str(repo), "show", f"HEAD:{candidate}"],
            capture_output=True,
            check=False,
        ).stdout == expected
        for candidate in git_head_path_candidates(relative)
    )


def validate_blueprint(path: Path) -> tuple[list[str], list[str]]:
    text, read_errors = read_document(path)
    if text is None:
        return read_errors, []
    lines, errors = common_errors(text)
    warnings: list[str] = []
    entries = heading_entries(lines)
    structural_text = "\n".join(lines)

    if len([entry for entry in entries if entry.level == 1]) != 1:
        errors.append("blueprint must contain exactly one level-1 title")

    version_match = re.search(r"^>\s*蓝图规范版本[：:]\s*(\S+)\s*$", structural_text, re.MULTILINE)
    if not version_match or version_match.group(1) != BLUEPRINT_VERSION:
        found = version_match.group(1) if version_match else "missing"
        errors.append(f"blueprint format upgrade required: expected version {BLUEPRINT_VERSION}, found {found}")

    level_two = [entry.title for entry in entries if entry.level == 2]
    if tuple(level_two) not in {BLUEPRINT_SECTIONS, LEGACY_BLUEPRINT_SECTIONS}:
        errors.append("blueprint level-2 sections must be exactly: " + " | ".join(BLUEPRINT_SECTIONS))
    for entry in entries:
        if entry.title in FORBIDDEN_BLUEPRINT_HEADINGS:
            errors.append(f"redundant blueprint heading is forbidden in version 3: {entry.title}")

    required_tables = (
        ("代码落位规则", CODE_PLACEMENT_HEADERS, "code placement"),
        ("模块职责", MODULE_HEADERS, "module responsibility"),
        ("全局契约", GLOBAL_CONTRACT_HEADERS, "global contract"),
        ("开发决策边界", BOUNDARY_HEADERS, "development boundary"),
        ("分层与代码映射", LAYER_HEADERS, "layer mapping"),
        ("数据与资源安全", RESOURCE_HEADERS, "data and resource safety"),
        ("运行与恢复", RECOVERY_HEADERS, "runtime recovery"),
    )
    parsed_tables: dict[str, list[list[str]]] = {}
    for section, headers, name in required_tables:
        rows, table_errors = table_under_heading(lines, entries, section, headers, name)
        errors.extend(table_errors)
        parsed_tables[section] = rows
        if section != "待开发功能" and not rows:
            errors.append(f"{name} table must contain at least one row")

    new_pending_layout = "交付工作项" in level_two
    if new_pending_layout:
        pending_rows, pending_errors = table_under_heading(
            lines, entries, "交付工作项", PENDING_HEADERS, "delivery work"
        )
        errors.extend(pending_errors)
    else:
        compatible_rows, compatible_errors = table_under_heading(
            lines, entries, "待开发功能", COMPATIBLE_PENDING_HEADERS, "pending work"
        )
        if not compatible_errors:
            pending_rows = [row[:1] + ["待澄清" if row[4].startswith("待澄清") else "待开发"] + row[1:] for row in compatible_rows]
            warnings.append("pending work table uses legacy heading and has no explicit status")
        else:
            legacy_rows, legacy_errors = table_under_heading(
                lines, entries, "待开发功能", LEGACY_PENDING_HEADERS, "pending work"
            )
            if legacy_errors:
                errors.extend(compatible_errors)
                pending_rows = []
            elif head_has_legacy_pending_layout(path):
                pending_rows = [
                    row[:1]
                    + ["待澄清" if row[4].startswith("待澄清") else "待开发"]
                    + row[1:]
                    + ["无"]
                    for row in legacy_rows
                ]
                warnings.append("pending work table uses legacy layout without 状态 and 需求引用")
            else:
                errors.append(
                    "pending work table requires 状态 and 需求引用; "
                    "legacy layout is allowed only from Git HEAD"
                )
                pending_rows = []
    parsed_tables["交付工作项"] = pending_rows

    contract_ids = [row[0] for row in parsed_tables.get("全局契约", [])]
    for contract_id in contract_ids:
        if not GLOBAL_CONTRACT_ID_RE.fullmatch(contract_id):
            errors.append(f"invalid global contract id: {contract_id}")
    for duplicate in sorted(duplicate_values(contract_ids)):
        errors.append(f"duplicate global contract id: {duplicate}")

    boundary_rows = parsed_tables.get("开发决策边界", [])
    boundary_names = [row[0] for row in boundary_rows]
    if tuple(boundary_names) != BOUNDARY_VALUES:
        errors.append("development boundary rows must be exactly: " + " | ".join(BOUNDARY_VALUES))

    pending_rows = parsed_tables.get("交付工作项", [])
    pending_ids = [row[0] for row in pending_rows]
    valid_pending_ids = set(pending_ids)
    historical_pending = head_pending_ids(path) if new_pending_layout else set()
    pending_id_pattern = TASK_ID_RE if new_pending_layout else LEGACY_TASK_ID_RE
    dependency_context = "delivery work" if new_pending_layout else "pending work"
    for duplicate in sorted(duplicate_values(pending_ids)):
        errors.append(f"duplicate pending work id: {duplicate}")
    for cells in pending_rows:
        task_id, state, priority, source, feature, design_basis, dependency, completion, requirement_ref = cells
        if not pending_id_pattern.fullmatch(task_id):
            errors.append(f"invalid pending work id: {task_id}")
        elif new_pending_layout and task_id.startswith("PEND-") and task_id not in historical_pending:
            errors.append(f"new delivery work must use FEAT, not PEND: {task_id}")
        if state not in PENDING_STATES:
            errors.append(f"invalid delivery work state for {task_id}: {state}")
        if source not in PENDING_SOURCES:
            errors.append(f"invalid pending work source for {task_id}: {source}")
        for field_name, value in (
            ("priority", priority),
            ("feature", feature),
            ("design basis", design_basis),
            ("dependency", dependency),
            ("completion", completion),
            ("requirement reference", requirement_ref),
        ):
            if not value:
                errors.append(f"empty {field_name} for pending work {task_id}")
        design_errors = (
            []
            if not new_pending_layout and design_basis == "待澄清"
            else validate_design_reference(path, design_basis)
        )
        errors.extend(design_errors)
        if (
            new_pending_layout
            and state == "待澄清"
            and not design_basis.startswith("待澄清：")
        ):
            errors.append(f"待澄清 work item must state the missing design decision: {task_id}")
        if state != "待澄清" and design_basis.startswith("待澄清"):
            errors.append(f"{state} work item requires a confirmed design reference: {task_id}")
        if new_pending_layout:
            normalized_requirement, requirement_errors = validate_requirement_reference(
                path, requirement_ref
            )
            errors.extend(requirement_errors)
        else:
            normalized_requirement = requirement_ref
            if requirement_ref != "无" and REQUIREMENT_REF_RE.fullmatch(requirement_ref) is None:
                errors.append(f"invalid requirement reference for {task_id}: {requirement_ref}")
        if not design_errors and not design_basis.startswith("待澄清"):
            design_requirement = referenced_design_requirement(path, design_basis)
            if design_requirement != normalized_requirement:
                errors.append(
                    f"requirement reference does not match design for {task_id}: "
                    f"blueprint={normalized_requirement or 'invalid'}, design={design_requirement or 'missing'}"
                )
    for cells in pending_rows:
        errors.extend(
            validate_dependency(
                cells[0],
                cells[6],
                valid_pending_ids,
                pending_id_pattern,
                dependency_context,
            )
        )
    return errors, warnings


def validate_design(
    path: Path,
    evolution_stack: frozenset[Path] | None = None,
    text_snapshot: str | None = None,
) -> tuple[list[str], list[str]]:
    resolved_path = path.resolve()
    stack = frozenset() if evolution_stack is None else evolution_stack
    if resolved_path in stack:
        return [f"design evolution source cycle detected: {path.name}"], []
    next_stack = stack | {resolved_path}
    if text_snapshot is None:
        text, read_errors = read_document(path)
        if text is None:
            return read_errors, []
    else:
        text = text_snapshot
    lines, errors = common_errors(text)
    errors.extend(validate_design_filename(path))
    warnings: list[str] = []
    entries = heading_entries(lines)
    structural_text = "\n".join(lines)

    if len([entry for entry in entries if entry.level == 1]) != 1:
        errors.append("design must contain exactly one level-1 title")

    version_match = re.search(r"^>\s*设计规范版本[：:]\s*(\S+)\s*$", structural_text, re.MULTILINE)
    version = version_match.group(1) if version_match else None
    if version not in {DESIGN_VERSION, COMPATIBLE_DESIGN_VERSION, LEGACY_DESIGN_VERSION}:
        found = version if version else "missing"
        errors.append(
            f"design format upgrade required: expected version {DESIGN_VERSION}, "
            f"compatible version {COMPATIBLE_DESIGN_VERSION}, or terminal legacy version "
            f"{LEGACY_DESIGN_VERSION}, found {found}"
        )

    state_match = re.search(r"^>\s*设计状态[：:]\s*(\S+)\s*$", structural_text, re.MULTILINE)
    state = state_match.group(1) if state_match else None
    if state not in DESIGN_STATES:
        errors.append("design status must be one of: " + ", ".join(sorted(DESIGN_STATES)))
    if version == LEGACY_DESIGN_VERSION and state not in {"已实现", "已废弃"}:
        errors.append(f"active design must use version {DESIGN_VERSION}")
    if version == LEGACY_DESIGN_VERSION:
        errors.extend(validate_legacy_design_snapshot(path, text))
    elif version == COMPATIBLE_DESIGN_VERSION:
        errors.extend(validate_compatible_design_snapshot(path, text))

    legacy = version == LEGACY_DESIGN_VERSION

    evolution_matches = re.findall(
        r"^>\s*演进来源[：:]\s*(.+?)\s*$", structural_text, re.MULTILINE
    )
    if len(evolution_matches) != 1:
        errors.append("design must contain exactly one evolution source metadata line")
    else:
        errors.extend(validate_evolution_source(path, evolution_matches[0], next_stack))

    requirement_matches = re.findall(
        r"^>\s*Requirement-Ref[：:]\s*(.+?)\s*$", structural_text, re.MULTILINE
    )
    terminal_head_compatibility = (
        version == DESIGN_VERSION
        and state in {"已实现", "已废弃"}
        and not requirement_matches
        and git_head_matches_document(path, text)
    )
    if version == DESIGN_VERSION and len(requirement_matches) != 1 and not terminal_head_compatibility:
        errors.append("version 5 design must contain exactly one Requirement-Ref metadata line")
    elif len(requirement_matches) > 1:
        errors.append("design must contain at most one Requirement-Ref metadata line")
    elif requirement_matches and requirement_matches[0] != "无" and REQUIREMENT_REF_RE.fullmatch(requirement_matches[0]) is None:
        errors.append("Requirement-Ref must be 无 or REQ-<UUIDv7>@vN")

    metadata_match = re.search(r"^>\s*工作包[：:]\s*(.+?)\s*$", structural_text, re.MULTILINE)
    metadata_ids = split_ids(metadata_match.group(1)) if metadata_match else []
    if not metadata_match:
        errors.append("missing design work package metadata")
    for package_id in metadata_ids:
        if not WORK_PACKAGE_ID_RE.fullmatch(package_id):
            errors.append(f"invalid design metadata work package id: {package_id}")
    for duplicate in sorted(duplicate_values(metadata_ids)):
        errors.append(f"duplicate design metadata work package id: {duplicate}")

    level_two = [entry.title for entry in entries if entry.level == 2]
    if not level_two or level_two[0:2] != ["共享约束", "工作包地图"]:
        errors.append("design must start with level-2 sections: 共享约束 | 工作包地图")
    allowed_fixed = {"共享约束", "工作包地图", "澄清暂存"}
    for title in level_two:
        if title in allowed_fixed or WORK_PACKAGE_ID_RE.match(title.split()[0] if title else ""):
            continue
        errors.append(f"unexpected design level-2 section: {title}")
    if level_two.count("共享约束") != 1:
        errors.append("design must contain exactly one shared constraints section")
    if level_two.count("工作包地图") != 1:
        errors.append("design must contain exactly one work package map section")

    anchors = explicit_anchors(lines)
    for duplicate in sorted(duplicate_values(anchors)):
        errors.append(f"duplicate explicit anchor: {duplicate}")
    if "shared-context" not in anchors:
        errors.append("missing explicit shared-context anchor")

    problem_rows, table_errors = table_under_heading(
        lines, entries, "问题与成功结果", PROBLEM_HEADERS, "problem and result"
    )
    errors.extend(table_errors)
    if not problem_rows:
        errors.append("problem and result table must contain at least one row")

    shared_rows, table_errors = table_under_heading(
        lines,
        entries,
        "共享契约",
        LEGACY_SHARED_CONTRACT_HEADERS if legacy else SHARED_CONTRACT_HEADERS,
        "shared contract",
    )
    errors.extend(table_errors)
    if not shared_rows:
        errors.append("shared contract table must contain at least one row")
    shared_ids = [row[0] for row in shared_rows]
    semantic_keys: list[str] = []
    for row in shared_rows:
        contract_id = row[0]
        semantic_key = "" if legacy else row[1]
        constraint = row[1] if legacy else row[2]
        if not SHARED_CONTRACT_ID_RE.fullmatch(contract_id):
            errors.append(f"invalid shared contract id: {contract_id}")
        if not legacy:
            if not semantic_key:
                errors.append(f"empty semantic key for shared contract {contract_id}")
            semantic_keys.append(semantic_key)
        if not constraint:
            errors.append(f"empty confirmed constraint for shared contract {contract_id}")

    map_rows, map_errors = table_under_heading(
        lines,
        entries,
        "工作包地图",
        LEGACY_WORK_PACKAGE_HEADERS if legacy else WORK_PACKAGE_HEADERS,
        "work package map",
    )
    errors.extend(map_errors)
    if not map_rows:
        errors.append("work package map must contain at least one row")

    package_sections = work_package_sections(lines, entries)
    section_ids = [package.package_id for package in package_sections]
    for duplicate in sorted(duplicate_values(section_ids)):
        errors.append(f"duplicate work package section: {duplicate}")
    for package in package_sections:
        if package.anchor is None or not anchor_matches_package_id(package.anchor, package.package_id):
            errors.append(f"work package {package.package_id} needs a matching explicit anchor")

    map_ids = [row[0] for row in map_rows]
    for duplicate in sorted(duplicate_values(map_ids)):
        errors.append(f"duplicate work package map id: {duplicate}")
    valid_package_ids = set(map_ids)
    state_by_id: dict[str, str] = {}
    role_by_id: dict[str, str] = {}
    dependency_by_id: dict[str, str] = {}
    anchor_by_id = {package.package_id: package.anchor for package in package_sections}
    for row in map_rows:
        if legacy:
            package_id, package_state, deliverable, dependency, section_link = row
            role = "能力"
        else:
            package_id, role, package_state, deliverable, dependency, section_link = row
        if not WORK_PACKAGE_ID_RE.fullmatch(package_id):
            errors.append(f"invalid work package id: {package_id}")
        if not legacy and role not in WORK_PACKAGE_ROLES:
            errors.append(f"invalid work package role for {package_id}: {role}")
        if package_state not in WORK_PACKAGE_STATES:
            errors.append(f"invalid work package state for {package_id}: {package_state}")
        if not deliverable:
            errors.append(f"empty deliverable for work package {package_id}")
        errors.extend(
            validate_dependency(package_id, dependency, valid_package_ids, WORK_PACKAGE_ID_RE, "work package")
        )
        link_match = LOCAL_LINK_RE.fullmatch(section_link)
        if not link_match:
            errors.append(f"invalid work package map section link: {package_id}")
        elif link_match.group(1) != anchor_by_id.get(package_id):
            errors.append(f"work package map link must target {package_id} section anchor")
        state_by_id[package_id] = package_state
        role_by_id[package_id] = role
        dependency_by_id[package_id] = dependency

    if set(map_ids) != set(section_ids):
        errors.append("work package map ids must exactly match WP-* sections")
    if set(metadata_ids) != set(map_ids):
        errors.append("design metadata work package ids must exactly match work package map")

    closure_ids = [package_id for package_id in map_ids if role_by_id.get(package_id) == "收口"]
    if not legacy:
        if len(map_ids) == 1 and closure_ids:
            errors.append("single-package design must use the 能力 role, not 收口")
        if len(map_ids) > 1 and len(closure_ids) != 1:
            errors.append("multi-package design must contain exactly one 收口 work package")
        if len(closure_ids) == 1:
            closure_id = closure_ids[0]
            if not (
                state == "澄清中"
                and (
                    dependency_by_id[closure_id] == "待澄清"
                    or dependency_by_id[closure_id].startswith("待确认：")
                )
            ):
                actual_dependencies = set(split_ids(dependency_by_id[closure_id]))
                expected_dependencies = valid_package_ids - {closure_id}
                if actual_dependencies != expected_dependencies:
                    errors.append(
                        f"closure work package {closure_id} must directly depend on every other work package"
                    )
        errors.extend(
            validate_work_package_dependency_graph(map_ids, dependency_by_id, closure_ids)
        )

    all_contract_ids = list(shared_ids)
    acceptance_coverage: set[str] = set()
    contract_owner: dict[str, str] = {}
    acceptance_rows_by_package: dict[str, list[list[str]]] = {}
    for package in package_sections:
        contract_rows, contract_errors = table_under_heading(
            lines,
            entries,
            "契约",
            LEGACY_PACKAGE_CONTRACT_HEADERS if legacy else PACKAGE_CONTRACT_HEADERS,
            f"{package.package_id} contract",
            package.start,
            package.end,
        )
        errors.extend(contract_errors)
        contract_ids = [row[0] for row in contract_rows]
        dimensions = [row[1] for row in contract_rows]
        expected_contract = re.compile(rf"^{re.escape(package.package_id)}-C[0-9]+$")
        for row in contract_rows:
            contract_id = row[0]
            semantic_key = "" if legacy else row[2]
            constraint = row[2] if legacy else row[3]
            if not expected_contract.fullmatch(contract_id):
                errors.append(f"invalid contract id for {package.package_id}: {contract_id}")
            if not legacy:
                if not semantic_key:
                    errors.append(f"empty semantic key for contract {contract_id}")
                semantic_keys.append(semantic_key)
            if not constraint:
                errors.append(f"empty confirmed constraint for contract {contract_id}")
            contract_owner[contract_id] = package.package_id
        for duplicate in sorted(duplicate_values(contract_ids)):
            errors.append(f"duplicate contract id: {duplicate}")
        if legacy:
            if tuple(dimensions) != CONTRACT_DIMENSIONS:
                errors.append(
                    f"{package.package_id} contract dimensions must be exactly: "
                    + " | ".join(CONTRACT_DIMENSIONS)
                )
        else:
            invalid_dimensions = [value for value in dimensions if value not in CONTRACT_DIMENSIONS]
            if invalid_dimensions:
                errors.append(
                    f"{package.package_id} contains invalid contract dimensions: "
                    + " | ".join(invalid_dimensions)
                )
            first_occurrences = tuple(dict.fromkeys(dimensions))
            if first_occurrences != CONTRACT_DIMENSIONS:
                errors.append(
                    f"{package.package_id} contract dimensions must cover in first-occurrence order: "
                    + " | ".join(CONTRACT_DIMENSIONS)
                )
        all_contract_ids.extend(contract_ids)

        acceptance_rows, acceptance_errors = table_under_heading(
            lines,
            entries,
            "验收",
            ACCEPTANCE_HEADERS,
            f"{package.package_id} acceptance",
            package.start,
            package.end,
        )
        errors.extend(acceptance_errors)
        acceptance_rows_by_package[package.package_id] = acceptance_rows
        if not acceptance_rows:
            errors.append(f"{package.package_id} acceptance table must contain at least one row")
        for coverage, scenario, expected in acceptance_rows:
            if not scenario or not expected:
                errors.append(f"empty acceptance scenario or result for {package.package_id}")
            for contract_id in split_ids(coverage):
                if not contract_id:
                    errors.append(f"empty acceptance coverage id for {package.package_id}")
                else:
                    acceptance_coverage.add(contract_id)

    for duplicate in sorted(duplicate_values(all_contract_ids)):
        errors.append(f"duplicate contract id across design: {duplicate}")
    if not legacy:
        for duplicate in sorted(duplicate_values(semantic_keys)):
            errors.append(f"duplicate semantic key across design: {duplicate}")
    known_contract_ids = set(all_contract_ids)
    for contract_id in sorted(acceptance_coverage - known_contract_ids):
        errors.append(f"acceptance references unknown contract: {contract_id}")
    for contract_id in sorted(known_contract_ids - acceptance_coverage):
        errors.append(f"contract lacks acceptance coverage: {contract_id}")

    if not legacy and len(closure_ids) == 1:
        closure_id = closure_ids[0]
        required_packages = valid_package_ids - {closure_id}
        has_combination_acceptance = False
        for coverage, _, _ in acceptance_rows_by_package.get(closure_id, []):
            covered_packages = {
                contract_owner[contract_id]
                for contract_id in split_ids(coverage)
                if contract_id in contract_owner
            }
            if required_packages <= covered_packages:
                has_combination_acceptance = True
                break
        if not has_combination_acceptance:
            errors.append(
                f"closure work package {closure_id} needs one acceptance scenario covering every other work package"
            )

    clarification_headings = [entry for entry in entries if entry.title == "澄清暂存"]
    if state == "澄清中":
        clarification_rows, clarification_errors = table_under_heading(
            lines, entries, "澄清暂存", CLARIFICATION_HEADERS, "clarification staging"
        )
        errors.extend(clarification_errors)
        if not clarification_rows:
            errors.append("clarifying design must contain clarification staging rows")
        if not any(row[0] == "待确认" for row in clarification_rows):
            errors.append("clarifying design must contain at least one pending clarification")
        for row in clarification_rows:
            if row[0] not in CLARIFICATION_TYPES:
                errors.append(f"invalid clarification type: {row[0]}")
    elif clarification_headings:
        errors.append("non-clarifying design must not contain clarification staging")

    if version == DESIGN_VERSION:
        confirmation_matches = re.findall(
            r"^>\s*收敛确认[：:]\s*(.+?)\s*$", structural_text, re.MULTILINE
        )
        if len(confirmation_matches) != 1:
            errors.append(
                "version 5 design must contain exactly one convergence confirmation metadata line"
            )
        else:
            confirmation = confirmation_matches[0]
            if state == "澄清中":
                if confirmation != CONFIRMATION_PENDING:
                    errors.append(
                        "clarifying version 5 design must use convergence confirmation 待确认"
                    )
            else:
                confirmation_match = CONFIRMATION_RE.fullmatch(confirmation)
                if not confirmation_match:
                    errors.append(
                        "confirmed version 5 design must use "
                        "用户明确确认@sha256:<64 lowercase hex>"
                    )
                else:
                    expected_fingerprint = design_semantic_fingerprint(
                        path, text_snapshot=text
                    )
                    if confirmation_match.group(1) != expected_fingerprint:
                        errors.append(
                            "convergence confirmation fingerprint does not match design semantics"
                        )

    package_states = list(state_by_id.values())
    has_unconfirmed = any(value in {"待澄清", "澄清中"} for value in package_states)
    all_terminal = bool(package_states) and all(
        value in TERMINAL_WORK_PACKAGE_STATES for value in package_states
    )
    all_deprecated = bool(package_states) and all(value == "已废弃" for value in package_states)
    if state == "澄清中" and package_states and not has_unconfirmed:
        errors.append("clarifying design must contain an unconfirmed work package")
    elif state == "已确认":
        if has_unconfirmed:
            errors.append("confirmed design contains an unconfirmed work package")
        if all_terminal:
            errors.append("confirmed design with only terminal work packages must be implemented")
    elif state == "已实现":
        if not all_terminal:
            errors.append("implemented design contains an unfinished work package")
        elif all_deprecated:
            errors.append("implemented design with only deprecated work packages must be deprecated")
    elif state == "已废弃":
        if package_states and any(value != "已废弃" for value in package_states):
            errors.append("deprecated design must deprecate every work package")
        replacement = re.search(
            r"^>\s*替代来源[：:]\s*\[[^]\n]+\]\([^)\n]+\)\s*$",
            structural_text,
            re.MULTILINE,
        )
        if not replacement:
            errors.append("deprecated design must provide a linked replacement source")
    return errors, warnings


def design_semantic_fingerprint(path: Path, text_snapshot: str | None = None) -> str:
    """Hash design semantics while excluding lifecycle-only status fields."""
    if text_snapshot is None:
        text, read_errors = read_document(path)
        if text is None:
            raise ValueError(read_errors[0])
    else:
        text = text_snapshot
    lines, _ = common_errors(text)
    entries = heading_entries(lines)
    structural_text = "\n".join(lines)
    version_match = re.search(r"^>\s*设计规范版本[：:]\s*(\S+)\s*$", structural_text, re.MULTILINE)
    version = version_match.group(1) if version_match else ""
    legacy = version == LEGACY_DESIGN_VERSION
    evolution_match = re.search(r"^>\s*演进来源[：:]\s*(.+?)\s*$", structural_text, re.MULTILINE)
    requirement_match = re.search(
        r"^>\s*Requirement-Ref[：:]\s*(.+?)\s*$", structural_text, re.MULTILINE
    )
    metadata_match = re.search(r"^>\s*工作包[：:]\s*(.+?)\s*$", structural_text, re.MULTILINE)

    problem_rows, _ = table_under_heading(
        lines, entries, "问题与成功结果", PROBLEM_HEADERS, "problem and result"
    )
    shared_rows, _ = table_under_heading(
        lines,
        entries,
        "共享契约",
        LEGACY_SHARED_CONTRACT_HEADERS if legacy else SHARED_CONTRACT_HEADERS,
        "shared contract",
    )
    map_rows, _ = table_under_heading(
        lines,
        entries,
        "工作包地图",
        LEGACY_WORK_PACKAGE_HEADERS if legacy else WORK_PACKAGE_HEADERS,
        "work package map",
    )
    semantic_map_rows: list[list[str]] = []
    for row in map_rows:
        if legacy:
            package_id, _, deliverable, dependency, section_link = row
            semantic_map_rows.append([package_id, "能力", deliverable, dependency, section_link])
        else:
            package_id, role, _, deliverable, dependency, section_link = row
            semantic_map_rows.append([package_id, role, deliverable, dependency, section_link])

    package_payload: list[dict[str, object]] = []
    for package in work_package_sections(lines, entries):
        contract_rows, _ = table_under_heading(
            lines,
            entries,
            "契约",
            LEGACY_PACKAGE_CONTRACT_HEADERS if legacy else PACKAGE_CONTRACT_HEADERS,
            f"{package.package_id} contract",
            package.start,
            package.end,
        )
        acceptance_rows, _ = table_under_heading(
            lines,
            entries,
            "验收",
            ACCEPTANCE_HEADERS,
            f"{package.package_id} acceptance",
            package.start,
            package.end,
        )
        package_payload.append(
            {
                "id": package.package_id,
                "anchor": package.anchor,
                "contracts": contract_rows,
                "acceptance": acceptance_rows,
            }
        )

    payload = {
        "version": version,
        "evolution": evolution_match.group(1) if evolution_match else "",
        "packages": split_ids(metadata_match.group(1)) if metadata_match else [],
        "problems": problem_rows,
        "shared_contracts": shared_rows,
        "work_package_map": semantic_map_rows,
        "work_package_semantics": package_payload,
    }
    if requirement_match:
        payload["requirement_ref"] = requirement_match.group(1)
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def validate_design_snapshot(path: Path) -> tuple[list[str], list[str], str | None]:
    text, read_errors = read_document(path)
    if text is None:
        return read_errors, [], None
    errors, warnings = validate_design(path, text_snapshot=text)
    fingerprint = None if errors else design_semantic_fingerprint(path, text_snapshot=text)
    return errors, warnings, fingerprint


def main() -> int:
    args = parse_args()
    path = Path(args.path).expanduser().resolve()
    if args.design:
        errors, warnings, fingerprint = validate_design_snapshot(path)
    else:
        errors, warnings = validate_blueprint(path)
        fingerprint = None

    print(f"{'Design' if args.design else 'Blueprint'}: {path}")
    for warning in warnings:
        print(f"WARNING: {warning}")
    for error in errors:
        print(f"ERROR: {error}")
    if args.design and fingerprint is not None:
        print(f"Semantic-Fingerprint: sha256:{fingerprint}")
    print("PASS" if not errors else "FAIL")
    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
