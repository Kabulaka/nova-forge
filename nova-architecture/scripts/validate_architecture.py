#!/usr/bin/env python3
"""Validate Nova architecture contract indexes and parallel-readiness gates."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


SECTIONS = ("并行开发门禁", "契约索引", "硬依赖")
GATE_HEADERS = ("门禁", "是否需要", "状态", "Review 依据")
INDEX_HEADERS = ("契约类型", "业务范围", "路径", "状态", "所有者")
DEPENDENCY_HEADERS = ("需求块", "依赖需求块", "无法解除的业务原因", "开发顺序")
REQUIRED_GATES = ("共享工程骨架", "数据所有权与契约", "公共 API 契约", "事件契约", "Mock 与测试夹具")
STATUS = {"待确认", "待Review", "已通过", "不适用"}
PLACEHOLDER_RE = re.compile(r"<(?!/?a\b)[^>\n]+>|\b(?:TODO|TBD)\b|\{\{[^}\n]+\}\}", re.IGNORECASE)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ready", action="store_true", help="require all needed gates to have Review evidence")
    parser.add_argument("path", type=Path)
    return parser.parse_args()


def read(path: Path) -> tuple[str | None, list[str]]:
    try:
        return path.read_text(encoding="utf-8"), []
    except (OSError, UnicodeError) as exc:
        return None, [f"cannot read {path}: {exc}"]


def sections(text: str) -> tuple[str, ...]:
    result = []
    for line in text.splitlines():
        match = re.match(r"^##\s+(?:[0-9]+(?:\.[0-9]+)*[.、]?\s+)?(.+?)\s*$", line)
        if match:
            result.append(match.group(1))
    return tuple(result)


def table(text: str, section: str, headers: tuple[str, ...]) -> tuple[list[list[str]], list[str]]:
    lines = text.splitlines()
    heading = next((i for i, line in enumerate(lines) if re.match(rf"^##\s+(?:[0-9]+[.、]?\s+)?{re.escape(section)}\s*$", line)), None)
    if heading is None:
        return [], [f"missing section: {section}"]
    for index in range(heading + 1, len(lines)):
        if lines[index].startswith("## "):
            break
        if not lines[index].lstrip().startswith("|"):
            continue
        cells = [cell.strip() for cell in lines[index].strip().strip("|").split("|")]
        if tuple(cells) != headers:
            continue
        if index + 1 >= len(lines) or not re.fullmatch(r"\|(?:\s*:?-+:?\s*\|)+", lines[index + 1].strip()):
            return [], [f"invalid table separator in {section}"]
        rows = []
        cursor = index + 2
        while cursor < len(lines) and lines[cursor].lstrip().startswith("|"):
            row = [cell.strip() for cell in lines[cursor].strip().strip("|").split("|")]
            if len(row) != len(headers):
                return rows, [f"invalid column count in {section}"]
            rows.append(row)
            cursor += 1
        return rows, [] if rows else [f"table must contain rows: {section}"]
    return [], [f"missing exact table header in {section}"]


def validate_data_contract(path: Path) -> list[str]:
    text, errors = read(path)
    if text is None:
        return errors
    expected = ("所有权", "数据约束", "一致性与并发", "失败与恢复")
    if sections(text) != expected:
        errors.append("data contract sections must be exactly: " + " | ".join(expected))
    if re.findall(r"^>\s*数据契约版本[：:]\s*(.+?)\s*$", text, re.MULTILINE) != ["1"]:
        errors.append("data contract version must be 1")
    for label in ("Contract-Key", "所有者"):
        if len(re.findall(rf"^>\s*{label}[：:]\s*(.+?)\s*$", text, re.MULTILINE)) != 1:
            errors.append(f"data contract requires exactly one {label}")
    for section, headers in (
        ("所有权", ("数据对象", "权威写入方", "允许读取方", "禁止行为")),
        ("数据约束", ("字段或关系", "类型或范围", "不变量", "兼容规则")),
        ("一致性与并发", ("场景", "原子边界", "并发结果", "幂等规则")),
        ("失败与恢复", ("失败点", "对外结果", "恢复或补偿", "责任方")),
    ):
        _, table_errors = table(text, section, headers)
        errors.extend(table_errors)
    return errors


def validate(path: Path, ready: bool) -> list[str]:
    text, errors = read(path)
    if text is None:
        return errors
    if path.name != "ARCHITECTURE_CONTRACTS.md":
        errors.append("architecture index must be named ARCHITECTURE_CONTRACTS.md")
    if sections(text) != SECTIONS:
        errors.append("level-2 sections must be exactly: " + " | ".join(SECTIONS))
    if PLACEHOLDER_RE.search(text):
        errors.append("unfinished placeholder found")
    if re.findall(r"^>\s*架构契约版本[：:]\s*(.+?)\s*$", text, re.MULTILINE) != ["1"]:
        errors.append("architecture contract version must be 1")
    blueprint_refs = re.findall(r"^>\s*蓝图引用[：:]\s*(.+?)\s*$", text, re.MULTILINE)
    if blueprint_refs != ["../PROJECT_BLUEPRINT.md"]:
        errors.append("blueprint reference must be ../PROJECT_BLUEPRINT.md")
    elif not (path.parent / blueprint_refs[0]).resolve().is_file():
        errors.append("referenced .nova/PROJECT_BLUEPRINT.md does not exist")

    gates, gate_errors = table(text, "并行开发门禁", GATE_HEADERS)
    contracts, contract_errors = table(text, "契约索引", INDEX_HEADERS)
    dependencies, dependency_errors = table(text, "硬依赖", DEPENDENCY_HEADERS)
    errors.extend(gate_errors + contract_errors + dependency_errors)
    gate_names = [row[0] for row in gates]
    if tuple(gate_names) != REQUIRED_GATES:
        errors.append("parallel gates must be exactly: " + " | ".join(REQUIRED_GATES))
    for name, needed, state, evidence in gates:
        if needed not in {"是", "否"}:
            errors.append(f"invalid needed value for {name}: {needed}")
        if state not in STATUS:
            errors.append(f"invalid gate status for {name}: {state}")
        if needed == "否" and (state != "不适用" or evidence != "无"):
            errors.append(f"unneeded gate must be 不适用 with 无 evidence: {name}")
        if needed == "是" and state == "不适用":
            errors.append(f"needed gate cannot be 不适用: {name}")
        if state == "已通过" and evidence == "无":
            errors.append(f"passed gate requires Review evidence: {name}")
        if ready and needed == "是" and (state != "已通过" or evidence == "无"):
            errors.append(f"parallel development gate is not ready: {name}")

    root = path.parent.resolve()
    referenced: set[Path] = set()
    for contract_type, scope, link, state, owner in contracts:
        if state not in STATUS - {"不适用"}:
            errors.append(f"invalid contract status for {scope}: {state}")
        match = re.fullmatch(r"\[[^]\n]+\]\(([^)\s]+)\)", link)
        if match is None:
            errors.append(f"invalid architecture contract link: {link}")
            continue
        target = (path.parent / match.group(1)).resolve()
        try:
            target.relative_to(root)
        except ValueError:
            errors.append(f"architecture contract escapes architecture directory: {link}")
            continue
        if not target.is_file():
            errors.append(f"architecture contract file not found: {link}")
            continue
        referenced.add(target)
        if contract_type == "数据":
            errors.extend(f"{link}: {error}" for error in validate_data_contract(target))
        if contract_type == "API" and target.suffix not in {".yaml", ".yml", ".json"}:
            errors.append(f"API contract must use OpenAPI YAML or JSON: {link}")
        if contract_type == "事件" and target.suffix not in {".yaml", ".yml", ".json"}:
            errors.append(f"event contract must use AsyncAPI YAML or JSON: {link}")
    for directory in ("api", "data", "events", "mocks"):
        candidate = path.parent / directory
        if candidate.is_dir() and not any(file.is_file() for file in candidate.rglob("*")):
            errors.append(f"empty architecture directory is forbidden: {directory}")
        for file in candidate.rglob("*") if candidate.is_dir() else ():
            if file.is_file() and file.resolve() not in referenced:
                errors.append(f"architecture file is not indexed: {file.relative_to(path.parent)}")
    for requirement, dependency, reason, order in dependencies:
        if dependency == "无" and (reason != "无" or order != "并行"):
            errors.append(f"dependency-free requirement must be marked 无/并行: {requirement}")
        if dependency != "无" and (reason == "无" or order == "并行"):
            errors.append(f"hard dependency requires a reason and serial order: {requirement}")
    return errors


def main() -> int:
    args = parse_args()
    path = args.path.expanduser().resolve()
    errors = validate(path, args.ready)
    print(f"Architecture: {path}")
    for error in errors:
        print(f"ERROR: {error}")
    print("PASS" if not errors else "FAIL")
    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
