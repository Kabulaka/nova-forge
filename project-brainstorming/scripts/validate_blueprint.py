#!/usr/bin/env python3
"""Validate a version-2 project blueprint or an epic design document."""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path


BLUEPRINT_VERSION = "2"
BLUEPRINT_SECTIONS = (
    "项目定位",
    "技术栈",
    "代码结构",
    "模块架构",
    "跨模块契约",
    "待开发功能",
    "系统架构",
)
BOUNDARY_PARTS = (
    "本期必须实现",
    "明确不做",
    "后续候选",
    "AI 可自行决定",
    "必须再次确认",
)
PENDING_HEADERS = ("编号", "优先级", "功能", "设计依据", "前置依赖", "完成定义")
WORK_PACKAGE_HEADERS = ("工作包", "状态", "前置依赖", "设计章节", "组合验收关系")
DESIGN_STATES = {"澄清中", "已确认", "已实现", "已废弃"}
WORK_PACKAGE_STATES = {"待澄清", "澄清中", "已确认", "开发中", "已完成", "已废弃"}
TASK_ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9._-]*$")
WORK_PACKAGE_ID_RE = re.compile(r"^WP-[A-Za-z0-9._-]+$")
ANCHOR_RE = re.compile(r"<a\s+id=[\"']([A-Za-z0-9][A-Za-z0-9._-]*)[\"']\s*></a>", re.IGNORECASE)
DESIGN_LINK_RE = re.compile(
    r"^\[[^]\n]+\]\((?:<)?([^\s>#]+\.md)#([A-Za-z0-9][A-Za-z0-9._-]*)(?:>)?\)$"
)
PLACEHOLDERS = (
    re.compile(r"<(?!/?a\b)[^>\n]+>", re.IGNORECASE),
    re.compile(r"\{\{[^}\n]+\}\}"),
    re.compile(r"\[(?:TODO|TBD)[^]\n]*\]", re.IGNORECASE),
    re.compile(r"(?:TODO|TBD)\s*:", re.IGNORECASE),
)
FENCE_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
HEADING_RE = re.compile(r"^(#{1,6})[ \t]+(.+?)\s*$")
NUMBERED_HEADING_RE = re.compile(r"^\d+(?:\.\d+)*(?:[.、])?\s+")
TERMINAL_WORK_PACKAGE_STATES = {"已完成", "已废弃"}


@dataclass(frozen=True)
class WorkPackage:
    package_id: str
    heading_index: int
    end_index: int
    anchor: str | None
    state: str | None
    section: str


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


def markdown_structure_lines(text: str) -> tuple[list[str], bool]:
    """Return same-length lines with fenced-code content blanked out."""
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

        closing = re.match(
            rf"^ {{0,3}}{re.escape(fence_character)}{{{fence_length},}}\s*$",
            line,
        )
        if closing:
            fence_character = None
            fence_length = 0
        result.append("")
    return result, fence_character is not None


def heading(line: str) -> tuple[int, str] | None:
    match = HEADING_RE.match(line)
    if not match:
        return None
    title = re.sub(r"\s+#+\s*$", "", match.group(2)).strip()
    return len(match.group(1)), title


def normalized_heading(title: str) -> str:
    return NUMBERED_HEADING_RE.sub("", title).strip()


def heading_entries(lines: list[str]) -> list[tuple[int, int, str]]:
    entries: list[tuple[int, int, str]] = []
    for index, line in enumerate(lines):
        parsed = heading(line)
        if parsed:
            level, title = parsed
            entries.append((index, level, normalized_heading(title)))
    return entries


def common_errors(text: str) -> list[str]:
    errors: list[str] = []
    lines, unbalanced_fence = markdown_structure_lines(text)
    if not text.strip():
        return ["document is empty"]
    first_heading = heading(lines[0]) if lines else None
    if not first_heading or first_heading[0] != 1:
        errors.append("first line must be a level-1 title")
    if unbalanced_fence:
        errors.append("unbalanced fenced code blocks")
    structural_text = "\n".join(lines)
    for pattern in PLACEHOLDERS:
        match = pattern.search(structural_text)
        if match:
            errors.append(f"unresolved placeholder: {match.group(0)}")
            break
    return errors


def markdown_cells(line: str) -> list[str]:
    """Split a Markdown table row without treating escaped pipes as delimiters."""
    source = line.strip()
    if source.startswith("|"):
        source = source[1:]
    if source.endswith("|"):
        slash_count = 0
        index = len(source) - 2
        while index >= 0 and source[index] == "\\":
            slash_count += 1
            index -= 1
        if slash_count % 2 == 0:
            source = source[:-1]

    cells: list[str] = []
    buffer: list[str] = []
    for character in source:
        if character == "|":
            slash_count = 0
            index = len(buffer) - 1
            while index >= 0 and buffer[index] == "\\":
                slash_count += 1
                index -= 1
            if slash_count % 2:
                buffer.pop()
                buffer.append("|")
                continue
            cells.append("".join(buffer).strip())
            buffer = []
            continue
        buffer.append(character)
    cells.append("".join(buffer).strip())
    return cells


def section_table(
    lines: list[str], section_name: str, headers: tuple[str, ...], table_name: str
) -> tuple[list[list[str]], list[str]]:
    errors: list[str] = []
    sections = [
        index
        for index, level, title in heading_entries(lines)
        if level == 2 and title == section_name
    ]
    if not sections:
        return [], [f"missing {table_name} section"]
    if len(sections) > 1:
        errors.append(f"duplicate {table_name} section")
    start = sections[0]
    end = next(
        (
            index
            for index, level, _ in heading_entries(lines)
            if index > start and level == 2
        ),
        len(lines),
    )
    table_lines = [line for line in lines[start + 1 : end] if line.strip().startswith("|")]
    if len(table_lines) < 2:
        return [], errors + [f"{table_name} table is missing"]

    parsed_headers = markdown_cells(table_lines[0])
    if tuple(parsed_headers) != headers:
        errors.append(f"{table_name} table headers must be: " + " | ".join(headers))
    separator = markdown_cells(table_lines[1])
    if len(separator) != len(headers) or not all(
        re.fullmatch(r":?-{3,}:?", cell) for cell in separator
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


def pending_table(lines: list[str]) -> tuple[list[list[str]], list[str]]:
    return section_table(lines, "待开发功能", PENDING_HEADERS, "pending work")


def work_package_map_table(lines: list[str]) -> tuple[list[list[str]], list[str]]:
    return section_table(lines, "工作包地图", WORK_PACKAGE_HEADERS, "work package map")


def within_design_root(blueprint: Path, target: Path) -> bool:
    design_root = (blueprint.parent / "docs" / "design").resolve()
    try:
        target.relative_to(design_root)
        return True
    except ValueError:
        return False


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
    if anchor_lower == package_lower:
        return True
    return (
        anchor_lower.startswith(package_lower)
        and len(anchor_lower) > len(package_lower)
        and anchor_lower[len(package_lower)] in "-._"
    )


def design_work_packages(lines: list[str]) -> list[WorkPackage]:
    starts: list[tuple[int, str]] = []
    entries = heading_entries(lines)
    for index, level, title in entries:
        match = re.fullmatch(r"(WP-[A-Za-z0-9._-]+)\s+\S.*", title)
        if level == 2 and match:
            starts.append((index, match.group(1)))

    packages: list[WorkPackage] = []
    for start, package_id in starts:
        end = next(
            (index for index, level, _ in entries if index > start and level == 2),
            len(lines),
        )
        previous_index = start - 1
        while previous_index >= 0 and not lines[previous_index].strip():
            previous_index -= 1
        anchor_match = (
            ANCHOR_RE.fullmatch(lines[previous_index].strip())
            if previous_index >= 0
            else None
        )
        anchor = anchor_match.group(1) if anchor_match else None
        section = "\n".join(lines[start:end])
        state_match = re.search(r"^-\s*状态[：:]\s*(\S+)\s*$", section, re.MULTILINE)
        state = state_match.group(1) if state_match else None
        packages.append(WorkPackage(package_id, start, end, anchor, state, section))
    return packages


def duplicate_values(values: list[str]) -> set[str]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for value in values:
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    return duplicates


def validate_dependency(
    owner_id: str,
    value: str,
    valid_ids: set[str],
    id_pattern: re.Pattern[str],
    context: str,
) -> list[str]:
    if value in {"无", "待澄清"}:
        return []
    dependencies = re.split(r"\s*[、,，]\s*", value)
    if not dependencies or any(not dependency for dependency in dependencies):
        return [f"invalid {context} dependency for {owner_id}: {value}"]

    errors: list[str] = []
    seen: set[str] = set()
    for dependency in dependencies:
        if not id_pattern.fullmatch(dependency):
            errors.append(f"invalid {context} dependency for {owner_id}: {dependency}")
        elif dependency == owner_id:
            errors.append(f"{context} {owner_id} must not depend on itself")
        elif dependency not in valid_ids:
            errors.append(f"unknown {context} dependency for {owner_id}: {dependency}")
        elif dependency in seen:
            errors.append(f"duplicate {context} dependency for {owner_id}: {dependency}")
        seen.add(dependency)
    return errors


def validate_design_reference(blueprint: Path, value: str) -> list[str]:
    if value == "待澄清":
        return []
    match = DESIGN_LINK_RE.fullmatch(value)
    if not match:
        return [f"design basis must be 待澄清 or one markdown file anchor link: {value}"]

    relative_path, anchor = match.groups()
    target = (blueprint.parent / relative_path).resolve()
    if not within_design_root(blueprint, target):
        return [f"design document must be under docs/design: {relative_path}"]
    if not target.is_file():
        return [f"design document not found: {relative_path}"]
    try:
        target_text = target.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        return [f"cannot read design document {relative_path}: {exc}"]
    lines, _ = markdown_structure_lines(target_text)
    anchors = explicit_anchors(lines)
    if anchor not in anchors:
        return [f"design anchor not found: {relative_path}#{anchor}"]

    packages = design_work_packages(lines)
    duplicate_package_ids = duplicate_values([package.package_id for package in packages])
    if duplicate_package_ids:
        return [
            "design document contains duplicate work package section: "
            + ", ".join(sorted(duplicate_package_ids))
        ]
    matching_packages = [package for package in packages if package.anchor == anchor]
    if len(matching_packages) != 1:
        return [f"design anchor must identify one work package: {relative_path}#{anchor}"]
    package = matching_packages[0]
    if not anchor_matches_package_id(anchor, package.package_id):
        return [
            f"design anchor does not match work package {package.package_id}: "
            f"{relative_path}#{anchor}"
        ]
    if package.state not in WORK_PACKAGE_STATES:
        return [f"design work package has invalid status: {package.package_id}"]
    if package.state in TERMINAL_WORK_PACKAGE_STATES:
        return [
            f"terminal work package must be removed from pending work: "
            f"{relative_path}#{anchor} ({package.state})"
        ]
    return []


def validate_blueprint(path: Path) -> tuple[list[str], list[str]]:
    text, errors = read_document(path)
    warnings: list[str] = []
    if text is None:
        return errors, warnings
    errors.extend(common_errors(text))
    lines, _ = markdown_structure_lines(text)
    structural_text = "\n".join(lines)

    version_match = re.search(
        r"^>\s*蓝图规范版本[：:]\s*([^\s]+)\s*$",
        structural_text,
        re.MULTILINE,
    )
    if not version_match or version_match.group(1) != BLUEPRINT_VERSION:
        found = version_match.group(1) if version_match else "missing"
        errors.append(
            f"blueprint format upgrade required: expected version {BLUEPRINT_VERSION}, found {found}"
        )

    entries = heading_entries(lines)
    positions: list[int] = []
    for required in BLUEPRINT_SECTIONS:
        matches = [
            index
            for index, level, title in entries
            if level == 2 and title == required
        ]
        if not matches:
            errors.append(f"missing level-2 section: {required}")
        else:
            positions.append(matches[0])
            if len(matches) > 1:
                errors.append(f"duplicate level-2 section: {required}")
    if len(positions) == len(BLUEPRINT_SECTIONS) and positions != sorted(positions):
        errors.append("level-2 blueprint sections are out of required order")

    for boundary in BOUNDARY_PARTS:
        if not any(level >= 3 and title == boundary for _, level, title in entries):
            errors.append(f"missing project development boundary category: {boundary}")

    rows, table_errors = pending_table(lines)
    errors.extend(table_errors)
    seen_ids: set[str] = set()
    for cells in rows:
        task_id, priority, feature, design_basis, dependency, completion = cells
        if not TASK_ID_RE.fullmatch(task_id):
            errors.append(f"invalid pending work id: {task_id}")
        elif task_id in seen_ids:
            errors.append(f"duplicate pending work id: {task_id}")
        seen_ids.add(task_id)
        for label, value in (
            ("priority", priority),
            ("feature", feature),
            ("dependency", dependency),
            ("completion definition", completion),
        ):
            if not value:
                errors.append(f"pending work {task_id or '<empty>'} has empty {label}")
        errors.extend(validate_design_reference(path, design_basis))
    valid_task_ids = {
        cells[0] for cells in rows if TASK_ID_RE.fullmatch(cells[0])
    }
    for task_id, _, _, _, dependency, _ in rows:
        if task_id:
            errors.extend(
                validate_dependency(
                    task_id,
                    dependency,
                    valid_task_ids,
                    TASK_ID_RE,
                    "pending work",
                )
            )

    if not re.search(r"必须|不得|shall|must", structural_text, re.IGNORECASE):
        warnings.append("no explicit mandatory project requirement found")
    if not re.search(
        r"失败|错误|超时|取消|恢复|failure|error|timeout|cancel|recovery",
        structural_text,
        re.IGNORECASE,
    ):
        warnings.append("project-level failure or recovery semantics may be missing")
    return errors, warnings


def validate_design(path: Path) -> tuple[list[str], list[str]]:
    text, errors = read_document(path)
    warnings: list[str] = []
    if text is None:
        return errors, warnings
    errors.extend(common_errors(text))
    lines, _ = markdown_structure_lines(text)
    structural_text = "\n".join(lines)

    state_match = re.search(
        r"^>\s*设计状态[：:]\s*(\S+)\s*$", structural_text, re.MULTILINE
    )
    state = state_match.group(1) if state_match else None
    if state not in DESIGN_STATES:
        errors.append(
            "design status must be one of: " + ", ".join(sorted(DESIGN_STATES))
        )
    if not re.search(r"^>\s*关联待办[：:]\s*\S+", structural_text, re.MULTILINE):
        errors.append("missing related pending work metadata")
    reading_match = re.search(
        r"^>\s*必读范围[：:]\s*(.+)$", structural_text, re.MULTILINE
    )
    if not reading_match:
        errors.append("missing required reading metadata")
    else:
        reading_scope = reading_match.group(1)
        for required_term in ("PROJECT_BLUEPRINT.md", "公共上下文", "当前工作包", "直接依赖"):
            if required_term not in reading_scope:
                errors.append(f"required reading metadata missing scope: {required_term}")
        if re.search(r"整份|全文|全部工作包|所有工作包", reading_scope):
            errors.append("required reading metadata must not load the whole epic design")

    entries = heading_entries(lines)
    level_two_requirements = ("公共上下文", "工作包地图", "证据推断", "待确认事项")
    for required in level_two_requirements:
        matches = [
            index
            for index, level, title in entries
            if level == 2 and title == required
        ]
        if not matches:
            errors.append(f"missing design semantic section: {required}")
        elif len(matches) > 1:
            errors.append(f"duplicate design semantic section: {required}")

    public_sections = [
        index
        for index, level, title in entries
        if level == 2 and title == "公共上下文"
    ]
    if public_sections:
        public_start = public_sections[0]
        public_end = next(
            (
                index
                for index, level, _ in entries
                if index > public_start and level == 2
            ),
            len(lines),
        )
        public_titles = {
            title
            for index, level, title in entries
            if public_start < index < public_end and level >= 3
        }
        for label, accepted_titles in (
            ("目标", {"目标", "问题与目标"}),
            ("非目标", {"非目标", "明确非目标"}),
            (
                "共享模型或不变量",
                {
                    "共享模型",
                    "共享领域模型",
                    "共享不变量",
                    "模型与不变量",
                    "共享模型与不变量",
                    "共享领域模型与不变量",
                },
            ),
        ):
            if not public_titles.intersection(accepted_titles):
                errors.append(f"missing design semantic section: {label}")

    anchors = explicit_anchors(lines)
    if len(anchors) != len(set(anchors)):
        errors.append("duplicate explicit anchors found")
    if "shared-context" not in anchors:
        errors.append("missing explicit shared-context anchor")

    packages = design_work_packages(lines)
    if not packages:
        errors.append("design document must contain at least one WP-* section")
    package_ids = [package.package_id for package in packages]
    duplicate_package_ids = duplicate_values(package_ids)
    for package_id in sorted(duplicate_package_ids):
        errors.append(f"duplicate work package section: {package_id}")

    section_statuses: dict[str, str | None] = {}
    package_anchors: dict[str, str] = {}
    required_package_sections = (
        "状态、范围与非目标",
        "前置条件、输入与输出",
        "正常行为、权限与状态",
        "边界、失败与恢复",
        "依赖与影响范围",
        "验收标准",
    )
    for package in packages:
        package_id = package.package_id
        if package.anchor is None or not anchor_matches_package_id(package.anchor, package_id):
            errors.append(f"work package {package_id} needs a matching explicit anchor")
        elif package_id not in package_anchors:
            package_anchors[package_id] = package.anchor

        package_titles = {
            title
            for _, level, title in heading_entries(package.section.splitlines())
            if level == 3
        }
        for required in required_package_sections:
            if required not in package_titles:
                errors.append(f"work package {package_id} missing section: {required}")
        if package_id not in section_statuses:
            section_statuses[package_id] = package.state
        if package.state not in WORK_PACKAGE_STATES:
            errors.append(
                f"work package {package_id} status must be one of: "
                + ", ".join(sorted(WORK_PACKAGE_STATES))
            )

    map_rows, map_errors = work_package_map_table(lines)
    errors.extend(map_errors)
    map_statuses: dict[str, str] = {}
    valid_package_ids = set(package_ids)
    for package_id, package_state, dependency, section_link, combination in map_rows:
        if not WORK_PACKAGE_ID_RE.fullmatch(package_id):
            errors.append(f"invalid work package map id: {package_id}")
        elif package_id in map_statuses:
            errors.append(f"duplicate work package map id: {package_id}")
        if package_state not in WORK_PACKAGE_STATES:
            errors.append(f"invalid work package map status for {package_id}: {package_state}")
        errors.extend(
            validate_dependency(
                package_id,
                dependency,
                valid_package_ids,
                WORK_PACKAGE_ID_RE,
                "work package map",
            )
        )
        if not combination:
            errors.append(f"work package map combination acceptance is empty: {package_id}")
        link_match = re.fullmatch(
            r"\[[^]\n]+\]\(#([A-Za-z0-9][A-Za-z0-9._-]*)\)", section_link
        )
        if not link_match:
            errors.append(f"invalid work package map section link: {package_id}")
        elif link_match.group(1) not in anchors:
            errors.append(f"work package map anchor not found: {package_id}#{link_match.group(1)}")
        elif package_anchors.get(package_id) != link_match.group(1):
            errors.append(f"work package map link must target {package_id} section anchor")
        if package_id not in map_statuses:
            map_statuses[package_id] = package_state
    if set(map_statuses) != set(section_statuses):
        errors.append("work package map ids must exactly match WP-* sections")
    for package_id in set(map_statuses) & set(section_statuses):
        if map_statuses[package_id] != section_statuses[package_id]:
            errors.append(f"work package status mismatch between map and section: {package_id}")

    package_states = [value for value in section_statuses.values() if value is not None]
    has_unconfirmed = any(value in {"待澄清", "澄清中"} for value in package_states)
    all_terminal = bool(package_states) and all(
        value in TERMINAL_WORK_PACKAGE_STATES for value in package_states
    )
    all_deprecated = bool(package_states) and all(
        value == "已废弃" for value in package_states
    )
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
            errors.append(
                "implemented design with only deprecated work packages must be deprecated "
                "and provide a replacement"
            )
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
