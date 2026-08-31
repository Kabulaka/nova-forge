#!/usr/bin/env python3
"""Validate Nova product requirements indexes and requirement blocks."""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import subprocess
import sys
from functools import lru_cache
from pathlib import Path
from types import ModuleType


REQ_RE = re.compile(r"^REQ-[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")
VERSION_RE = re.compile(r"^v([1-9][0-9]*)$")
PEND_RE = re.compile(r"^PEND-(?:[0-9]+|[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12})$")
INDEX_SECTIONS = ("产品定位", "端到端业务流程", "业务模块", "需求索引", "范围边界")
BLOCK_SECTIONS = ("目标", "参与者与业务流程", "业务规则", "边界与异常", "独立交付边界", "验收")
INDEX_HEADERS = ("Requirement Key", "版本", "状态", "业务模块", "需求块", "已实现版本", "实现依据")
STATUS_VALUES = {"待实现", "已实现", "已更新"}
PLACEHOLDER_RE = re.compile(r"<(?!/?a\b)[^>\n]+>|\b(?:TODO|TBD)\b|\{\{[^}\n]+\}\}", re.IGNORECASE)
RULE_RE = re.compile(r"^R-[A-Za-z0-9][A-Za-z0-9_.-]*$")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--index", type=Path)
    mode.add_argument("--block", type=Path)
    return parser.parse_args()


def read_text(path: Path) -> tuple[str | None, list[str]]:
    try:
        return path.read_text(encoding="utf-8"), []
    except (OSError, UnicodeError) as exc:
        return None, [f"cannot read {path}: {exc}"]


def section_names(text: str) -> tuple[str, ...]:
    result = []
    for line in text.splitlines():
        match = re.match(r"^##\s+(?:[0-9]+(?:\.[0-9]+)*[.、]?\s+)?(.+?)\s*$", line)
        if match:
            result.append(match.group(1))
    return tuple(result)


def metadata(text: str, label: str) -> list[str]:
    return re.findall(rf"^>\s*{re.escape(label)}[：:]\s*(.+?)\s*$", text, re.MULTILINE)


def table_after(text: str, section: str, headers: tuple[str, ...]) -> tuple[list[list[str]], list[str]]:
    lines = text.splitlines()
    heading = next(
        (
            index
            for index, line in enumerate(lines)
            if re.match(rf"^##\s+(?:[0-9]+(?:\.[0-9]+)*[.、]?\s+)?{re.escape(section)}\s*$", line)
        ),
        None,
    )
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
        rows: list[list[str]] = []
        cursor = index + 2
        while cursor < len(lines) and lines[cursor].lstrip().startswith("|"):
            row = [cell.strip() for cell in lines[cursor].strip().strip("|").split("|")]
            if len(row) != len(headers):
                return rows, [f"invalid column count in {section}"]
            if any(not cell for cell in row):
                return rows, [f"empty table cell in {section}"]
            rows.append(row)
            cursor += 1
        return rows, [] if rows else [f"table must contain rows: {section}"]
    return [], [f"missing exact table header in {section}: {' | '.join(headers)}"]


def common_errors(path: Path, text: str, expected_sections: tuple[str, ...]) -> list[str]:
    errors: list[str] = []
    if len(re.findall(r"^#\s+", text, re.MULTILINE)) != 1:
        errors.append("document must contain exactly one level-1 title")
    if section_names(text) != expected_sections:
        errors.append("level-2 sections must be exactly: " + " | ".join(expected_sections))
    if PLACEHOLDER_RE.search(text):
        errors.append("unfinished placeholder found")
    if "```" in text or "~~~" in text:
        errors.append("requirements documents must not contain implementation code fences")
    if not path.is_file():
        errors.append(f"file not found: {path}")
    return errors


def validate_block(path: Path) -> tuple[list[str], dict[str, str]]:
    text, errors = read_text(path)
    if text is None:
        return errors, {}
    errors.extend(common_errors(path, text, BLOCK_SECTIONS))
    fields: dict[str, str] = {}
    for label, key in (
        ("需求块规范版本", "schema"),
        ("Requirement-Key", "key"),
        ("需求版本", "version"),
        ("所属模块", "module"),
    ):
        values = metadata(text, label)
        if len(values) != 1:
            errors.append(f"metadata must contain exactly one {label}")
        else:
            fields[key] = values[0]
    if fields.get("schema") != "1":
        errors.append("requirement block schema version must be 1")
    key = fields.get("key", "")
    if not REQ_RE.fullmatch(key):
        errors.append(f"invalid Requirement-Key: {key or 'missing'}")
    if key and not path.name.startswith(key + "_"):
        errors.append("requirement block filename must start with its Requirement-Key")
    if VERSION_RE.fullmatch(fields.get("version", "")) is None:
        errors.append("requirement version must be v1 or a larger integer")
    tables = (
        ("目标", ("业务问题", "成功结果")),
        ("参与者与业务流程", ("步骤", "参与者", "触发与输入", "业务结果")),
        ("业务规则", ("规则", "唯一定义")),
        ("边界与异常", ("场景", "业务结果或恢复")),
        ("独立交付边界", ("交付结果", "共享业务输入输出", "架构前置", "硬依赖", "明确不做")),
        ("验收", ("覆盖规则", "场景", "预期结果")),
    )
    parsed: dict[str, list[list[str]]] = {}
    for section, headers in tables:
        rows, table_errors = table_after(text, section, headers)
        parsed[section] = rows
        errors.extend(table_errors)
    rule_ids = [row[0] for row in parsed.get("业务规则", [])]
    for rule_id in rule_ids:
        if RULE_RE.fullmatch(rule_id) is None:
            errors.append(f"invalid business rule id: {rule_id or 'empty'}")
    if len(rule_ids) != len(set(rule_ids)):
        errors.append("business rule ids must be unique")
    coverage = {
        token
        for row in parsed.get("验收", [])
        for token in re.split(r"[、,，\s]+", row[0])
        if token
    }
    for rule_id in rule_ids:
        if rule_id not in coverage:
            errors.append(f"business rule lacks acceptance coverage: {rule_id}")
    for rule_id in sorted(coverage - set(rule_ids)):
        errors.append(f"acceptance references unknown business rule: {rule_id}")
    return errors, fields


@lru_cache(maxsize=1)
def nova_review_module() -> ModuleType | None:
    tool = Path(__file__).resolve().parents[2] / "nova-review/scripts/nova_review.py"
    if not tool.is_file():
        return None
    try:
        spec = importlib.util.spec_from_file_location("nova_review_requirements_evidence", tool)
        if spec is None or spec.loader is None:
            return None
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return module
    except (ImportError, OSError):
        return None


def git_repo_for_nova(nova_root: Path) -> Path | None:
    result = subprocess.run(
        ["git", "-C", str(nova_root), "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        return None
    repo = Path(result.stdout.strip()).resolve()
    return repo if (repo / ".nova").resolve() == nova_root.resolve() else None


def trusted_review_pass(
    nova_root: Path, work_item: str, requirement_key: str, implemented_version: str
) -> bool:
    module = nova_review_module()
    repo = git_repo_for_nova(nova_root)
    if module is None or repo is None:
        return False
    try:
        completed = module.load_completed_item(repo, work_item)
    except (module.NovaError, OSError, UnicodeError, json.JSONDecodeError):
        return False
    if completed is None:
        return False
    feature, _ = completed
    design_ref = feature.get("design_ref")
    if feature.get("change_class") != "designed" or not isinstance(design_ref, str):
        return False
    design_path = design_ref.split("#", 1)[0]
    design_bytes = None
    for commit_ref in reversed(feature.get("commits", [])):
        if not isinstance(commit_ref, dict) or commit_ref.get("repository") != "main":
            continue
        commit_hash = commit_ref.get("commit")
        if not isinstance(commit_hash, str):
            continue
        design_bytes = module.run_git_bytes(
            repo, "show", f"{commit_hash}:{design_path}", allow_missing=True
        )
        if design_bytes is not None:
            break
    if design_bytes is None:
        return False
    try:
        design = design_bytes.decode("utf-8")
    except UnicodeError:
        return False
    refs = re.findall(r"^>\s*Requirement-Ref[：:]\s*(.+?)\s*$", design, re.MULTILINE)
    return refs == [f"{requirement_key}@{implemented_version}"]


def validate_index(path: Path) -> list[str]:
    text, errors = read_text(path)
    if text is None:
        return errors
    errors.extend(common_errors(path, text, INDEX_SECTIONS))
    schema = metadata(text, "需求规范版本")
    product_version = metadata(text, "产品版本")
    if schema != ["1"]:
        errors.append("product requirements schema version must be exactly 1")
    if len(product_version) != 1 or VERSION_RE.fullmatch(product_version[0]) is None:
        errors.append("product version must be exactly one vN value")
    parsed_index_tables: dict[str, list[list[str]]] = {}
    for section, headers in (
        ("产品定位", ("对象", "核心问题", "成功结果")),
        ("端到端业务流程", ("步骤", "参与者", "业务输入", "业务结果")),
        ("业务模块", ("业务模块", "职责", "边界")),
        ("范围边界", ("边界", "内容")),
    ):
        section_rows, table_errors = table_after(text, section, headers)
        parsed_index_tables[section] = section_rows
        errors.extend(table_errors)
    modules = [row[0] for row in parsed_index_tables.get("业务模块", [])]
    if len(modules) != len(set(modules)):
        errors.append("business module names must be unique")
    rows, table_errors = table_after(text, "需求索引", INDEX_HEADERS)
    errors.extend(table_errors)
    keys: set[str] = set()
    for row in rows:
        key, version, status, module, link, implemented, evidence = row
        if not REQ_RE.fullmatch(key):
            errors.append(f"invalid requirement key in index: {key}")
            continue
        if key in keys:
            errors.append(f"duplicate requirement key: {key}")
        keys.add(key)
        version_match = VERSION_RE.fullmatch(version)
        if version_match is None:
            errors.append(f"invalid requirement version for {key}: {version}")
        if status not in STATUS_VALUES:
            errors.append(f"invalid requirement status for {key}: {status}")
        if module not in modules:
            errors.append(f"unknown business module for {key}: {module}")
        link_match = re.fullmatch(r"\[[^]\n]+\]\((requirements/(REQ-[^/\s]+\.md))\)", link)
        if link_match is None:
            errors.append(f"invalid requirement block link for {key}")
            continue
        target = (path.parent / link_match.group(1)).resolve()
        root = (path.parent / "requirements").resolve()
        try:
            target.relative_to(root)
        except ValueError:
            errors.append(f"requirement block escapes requirements directory: {key}")
            continue
        block_errors, fields = validate_block(target)
        errors.extend(f"{key}: {error}" for error in block_errors)
        for field, expected in (("key", key), ("version", version), ("module", module)):
            if fields.get(field) and fields[field] != expected:
                errors.append(f"{key}: block {field} does not match index")
        if status == "待实现" and (implemented != "无" or evidence != "无"):
            errors.append(f"{key}: 待实现 requires 无 implemented version and evidence")
        elif status == "已实现":
            if implemented != version or PEND_RE.fullmatch(evidence) is None:
                errors.append(f"{key}: 已实现 requires current implemented version and PEND evidence")
            elif not trusted_review_pass(path.parent, evidence, key, implemented):
                errors.append(f"{key}: implementation evidence is not a trusted Review PASS: {evidence}")
        elif status == "已更新":
            current = int(version_match.group(1)) if version_match else 0
            implemented_match = VERSION_RE.fullmatch(implemented)
            if implemented_match is None or int(implemented_match.group(1)) >= current or PEND_RE.fullmatch(evidence) is None:
                errors.append(f"{key}: 已更新 requires an older implemented version and PEND evidence")
            elif not trusted_review_pass(path.parent, evidence, key, implemented):
                errors.append(f"{key}: implementation evidence is not a trusted Review PASS: {evidence}")
    return errors


def main() -> int:
    args = parse_args()
    path = (args.index or args.block).expanduser().resolve()
    errors = validate_index(path) if args.index else validate_block(path)[0]
    print(f"Requirements: {path}")
    for error in errors:
        print(f"ERROR: {error}")
    print("PASS" if not errors else "FAIL")
    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
