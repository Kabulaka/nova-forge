#!/usr/bin/env python3
"""Validate a version-3 project blueprint or epic design document."""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path


BLUEPRINT_VERSION = "3"
DESIGN_VERSION = "3"
BLUEPRINT_SECTIONS = (
    "项目定位",
    "技术栈",
    "代码结构",
    "模块架构",
    "跨模块契约",
    "待开发功能",
    "系统架构",
)
FORBIDDEN_BLUEPRINT_HEADINGS = {"非目标", "架构红线", "项目级待确认事项"}
BOUNDARY_VALUES = (
    "本期必须实现",
    "明确不做",
    "后续候选",
    "AI 可自行决定",
    "必须再次确认",
)
PENDING_HEADERS = ("编号", "优先级", "来源", "功能", "设计依据", "前置依赖", "完成定义")
PENDING_SOURCES = {"用户提出", "Review-Defer", "问题诊断", "历史迁移"}
CODE_PLACEMENT_HEADERS = ("代码区域", "职责", "代码落位规则")
MODULE_HEADERS = ("模块", "职责", "对外边界")
GLOBAL_CONTRACT_HEADERS = ("契约", "适用范围", "验证")
BOUNDARY_HEADERS = ("边界", "内容")
LAYER_HEADERS = ("层", "职责", "对应代码结构", "允许依赖")
RESOURCE_HEADERS = ("适用范围", "不变量", "验证")
RECOVERY_HEADERS = ("资源或失败点", "所有者", "恢复与清理")

PROBLEM_HEADERS = ("问题", "成功结果")
SHARED_CONTRACT_HEADERS = ("契约", "已确认约束")
WORK_PACKAGE_HEADERS = ("工作包", "状态", "交付结果", "前置依赖", "设计章节")
PACKAGE_CONTRACT_HEADERS = ("契约", "维度", "已确认约束")
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
TERMINAL_WORK_PACKAGE_STATES = {"已完成", "已废弃"}
REFERENCED_WORK_PACKAGE_STATES = {"已确认", "开发中", "待Review"}

TASK_ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9._-]*$")
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
    parser.add_argument("path", nargs="?", default="PROJECT_BLUEPRINT.md")
    return parser.parse_args()


def read_document(path: Path) -> tuple[str | None, list[str]]:
    if not path.is_file():
        return None, [f"file not found: {path}"]
    try:
        return path.read_text(encoding="utf-8"), []
    except (OSError, UnicodeError) as exc:
        return None, [f"cannot read document: {exc}"]


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
    target_errors, _ = validate_design(target, evolution_stack)
    if target_errors:
        return [f"invalid design evolution source: {error}" for error in target_errors]
    text, read_errors = read_document(target)
    if text is None:
        return [f"invalid design evolution source: {error}" for error in read_errors]
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
    if value in {"无", "待澄清"}:
        return []
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
    design_root = (blueprint.parent / "docs" / "design").resolve()
    try:
        target.relative_to(design_root)
    except ValueError:
        return False
    return True


def validate_design_reference(blueprint: Path, value: str) -> list[str]:
    if value == "待澄清":
        return []
    match = DESIGN_LINK_RE.fullmatch(value)
    if not match:
        return [f"design basis must be 待澄清 or one markdown file anchor link: {value}"]
    relative_path, anchor = match.groups()
    target = (blueprint.parent / relative_path).resolve()
    if not within_design_root(blueprint, target):
        return [f"design basis must stay under docs/design: {relative_path}"]
    design_errors, _ = validate_design(target)
    if design_errors:
        return [f"invalid design document {relative_path}: {error}" for error in design_errors]
    text, errors = read_document(target)
    if text is None:
        return errors
    lines, _ = common_errors(text)
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
        lines, entries, "工作包地图", WORK_PACKAGE_HEADERS, "work package map"
    )
    if table_errors:
        return [f"invalid design document {relative_path}: {error}" for error in table_errors]
    state_by_id = {row[0]: row[1] for row in rows}
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
    if tuple(level_two) != BLUEPRINT_SECTIONS:
        errors.append("blueprint level-2 sections must be exactly: " + " | ".join(BLUEPRINT_SECTIONS))
    for entry in entries:
        if entry.title in FORBIDDEN_BLUEPRINT_HEADINGS:
            errors.append(f"redundant blueprint heading is forbidden in version 3: {entry.title}")

    required_tables = (
        ("代码落位规则", CODE_PLACEMENT_HEADERS, "code placement"),
        ("模块职责", MODULE_HEADERS, "module responsibility"),
        ("全局契约", GLOBAL_CONTRACT_HEADERS, "global contract"),
        ("开发决策边界", BOUNDARY_HEADERS, "development boundary"),
        ("待开发功能", PENDING_HEADERS, "pending work"),
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

    pending_rows = parsed_tables.get("待开发功能", [])
    pending_ids = [row[0] for row in pending_rows]
    valid_pending_ids = set(pending_ids)
    for duplicate in sorted(duplicate_values(pending_ids)):
        errors.append(f"duplicate pending work id: {duplicate}")
    for cells in pending_rows:
        task_id, priority, source, feature, design_basis, dependency, completion = cells
        if not TASK_ID_RE.fullmatch(task_id):
            errors.append(f"invalid pending work id: {task_id}")
        if source not in PENDING_SOURCES:
            errors.append(f"invalid pending work source for {task_id}: {source}")
        for field_name, value in (
            ("priority", priority),
            ("feature", feature),
            ("design basis", design_basis),
            ("dependency", dependency),
            ("completion", completion),
        ):
            if not value:
                errors.append(f"empty {field_name} for pending work {task_id}")
        errors.extend(validate_design_reference(path, design_basis))
    for cells in pending_rows:
        errors.extend(
            validate_dependency(cells[0], cells[5], valid_pending_ids, TASK_ID_RE, "pending work")
        )
    return errors, warnings


def validate_design(
    path: Path, evolution_stack: frozenset[Path] | None = None
) -> tuple[list[str], list[str]]:
    resolved_path = path.resolve()
    stack = frozenset() if evolution_stack is None else evolution_stack
    if resolved_path in stack:
        return [f"design evolution source cycle detected: {path.name}"], []
    next_stack = stack | {resolved_path}
    text, read_errors = read_document(path)
    if text is None:
        return read_errors, []
    lines, errors = common_errors(text)
    errors.extend(validate_design_filename(path))
    warnings: list[str] = []
    entries = heading_entries(lines)
    structural_text = "\n".join(lines)

    if len([entry for entry in entries if entry.level == 1]) != 1:
        errors.append("design must contain exactly one level-1 title")

    version_match = re.search(r"^>\s*设计规范版本[：:]\s*(\S+)\s*$", structural_text, re.MULTILINE)
    if not version_match or version_match.group(1) != DESIGN_VERSION:
        found = version_match.group(1) if version_match else "missing"
        errors.append(f"design format upgrade required: expected version {DESIGN_VERSION}, found {found}")

    state_match = re.search(r"^>\s*设计状态[：:]\s*(\S+)\s*$", structural_text, re.MULTILINE)
    state = state_match.group(1) if state_match else None
    if state not in DESIGN_STATES:
        errors.append("design status must be one of: " + ", ".join(sorted(DESIGN_STATES)))

    evolution_matches = re.findall(
        r"^>\s*演进来源[：:]\s*(.+?)\s*$", structural_text, re.MULTILINE
    )
    if len(evolution_matches) != 1:
        errors.append("design must contain exactly one evolution source metadata line")
    else:
        errors.extend(validate_evolution_source(path, evolution_matches[0], next_stack))

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
        lines, entries, "共享契约", SHARED_CONTRACT_HEADERS, "shared contract"
    )
    errors.extend(table_errors)
    if not shared_rows:
        errors.append("shared contract table must contain at least one row")
    shared_ids = [row[0] for row in shared_rows]
    for contract_id, constraint in shared_rows:
        if not SHARED_CONTRACT_ID_RE.fullmatch(contract_id):
            errors.append(f"invalid shared contract id: {contract_id}")
        if not constraint:
            errors.append(f"empty confirmed constraint for shared contract {contract_id}")

    map_rows, map_errors = table_under_heading(
        lines, entries, "工作包地图", WORK_PACKAGE_HEADERS, "work package map"
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
    anchor_by_id = {package.package_id: package.anchor for package in package_sections}
    for package_id, package_state, deliverable, dependency, section_link in map_rows:
        if not WORK_PACKAGE_ID_RE.fullmatch(package_id):
            errors.append(f"invalid work package id: {package_id}")
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

    if set(map_ids) != set(section_ids):
        errors.append("work package map ids must exactly match WP-* sections")
    if set(metadata_ids) != set(map_ids):
        errors.append("design metadata work package ids must exactly match work package map")

    all_contract_ids = list(shared_ids)
    acceptance_coverage: set[str] = set()
    for package in package_sections:
        contract_rows, contract_errors = table_under_heading(
            lines,
            entries,
            "契约",
            PACKAGE_CONTRACT_HEADERS,
            f"{package.package_id} contract",
            package.start,
            package.end,
        )
        errors.extend(contract_errors)
        contract_ids = [row[0] for row in contract_rows]
        dimensions = [row[1] for row in contract_rows]
        expected_contract = re.compile(rf"^{re.escape(package.package_id)}-C[0-9]+$")
        for contract_id, _, constraint in contract_rows:
            if not expected_contract.fullmatch(contract_id):
                errors.append(f"invalid contract id for {package.package_id}: {contract_id}")
            if not constraint:
                errors.append(f"empty confirmed constraint for contract {contract_id}")
        for duplicate in sorted(duplicate_values(contract_ids)):
            errors.append(f"duplicate contract id: {duplicate}")
        if tuple(dimensions) != CONTRACT_DIMENSIONS:
            errors.append(
                f"{package.package_id} contract dimensions must be exactly: "
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
    known_contract_ids = set(all_contract_ids)
    for contract_id in sorted(acceptance_coverage - known_contract_ids):
        errors.append(f"acceptance references unknown contract: {contract_id}")
    for contract_id in sorted(known_contract_ids - acceptance_coverage):
        errors.append(f"contract lacks acceptance coverage: {contract_id}")

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


def main() -> int:
    args = parse_args()
    path = Path(args.path).expanduser().resolve()
    errors, warnings = validate_design(path) if args.design else validate_blueprint(path)

    print(f"{'Design' if args.design else 'Blueprint'}: {path}")
    for warning in warnings:
        print(f"WARNING: {warning}")
    for error in errors:
        print(f"ERROR: {error}")
    print("PASS" if not errors else "FAIL")
    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
