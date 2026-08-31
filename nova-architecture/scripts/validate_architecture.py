#!/usr/bin/env python3
"""Validate Nova architecture contract indexes and parallel-readiness gates."""

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


SECTIONS = ("并行开发门禁", "契约索引", "硬依赖")
GATE_HEADERS = ("门禁", "是否需要", "状态", "Review 依据")
INDEX_HEADERS = ("契约类型", "业务范围", "路径", "状态", "所有者")
DEPENDENCY_HEADERS = ("需求块", "依赖需求块", "无法解除的业务原因", "开发顺序")
REQUIRED_GATES = ("共享工程骨架", "数据所有权与契约", "公共 API 契约", "事件契约", "Mock 与测试夹具")
STATUS = {"待确认", "待Review", "已通过", "不适用"}
CONTRACT_TYPES = {"工程骨架", "数据", "API", "事件", "Mock"}
GATE_TYPES = {
    "共享工程骨架": "工程骨架",
    "数据所有权与契约": "数据",
    "公共 API 契约": "API",
    "事件契约": "事件",
    "Mock 与测试夹具": "Mock",
}
PEND_RE = re.compile(r"^PEND-(?:[0-9]+|[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12})$")
PLACEHOLDER_RE = re.compile(r"<(?!/?a\b)[^>\n]+>|\b(?:TODO|TBD)\b|\{\{[^}\n]+\}\}", re.IGNORECASE)
OPENAPI_VERSION_RE = re.compile(r"^3\.(?:0|1)\.\d+$")
ASYNCAPI_VERSION_RE = re.compile(r"^(?:2|3)\.\d+\.\d+$")


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
            if any(not cell for cell in row):
                return rows, [f"empty table cell in {section}"]
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


def validate_foundation_contract(path: Path) -> list[str]:
    text, errors = read(path)
    if text is None:
        return errors
    if sections(text) != ("技术与运行", "目录与依赖"):
        errors.append("foundation contract sections must be exactly: 技术与运行 | 目录与依赖")
    if re.findall(r"^>\s*工程骨架契约版本[：:]\s*(.+?)\s*$", text, re.MULTILINE) != ["1"]:
        errors.append("foundation contract version must be 1")
    for section, headers in (
        ("技术与运行", ("语言", "框架", "运行形态", "持久化", "缓存", "消息", "鉴权", "部署")),
        ("目录与依赖", ("代码区域", "职责", "允许依赖", "禁止依赖")),
    ):
        _, table_errors = table(text, section, headers)
        errors.extend(table_errors)
    return errors


def structured_contract_root(path: Path, key: str) -> str | None:
    text, errors = read(path)
    if text is None or errors:
        return None
    if path.suffix == ".json":
        try:
            value = json.loads(text)
        except json.JSONDecodeError:
            return None
        root = value.get(key) if isinstance(value, dict) else None
        return root.strip() if isinstance(root, str) and root.strip() else None
    match = re.search(rf"(?m)^{re.escape(key)}\s*:\s*['\"]?([^\s'\"]+)", text)
    return match.group(1) if match else None


def structured_contract_version(path: Path) -> str | None:
    text, errors = read(path)
    if text is None or errors:
        return None
    if path.suffix == ".json":
        try:
            value = json.loads(text)
        except json.JSONDecodeError:
            return None
        info = value.get("info") if isinstance(value, dict) else None
        version = info.get("version") if isinstance(info, dict) else None
        return str(version).strip() if isinstance(version, (str, int, float)) else None
    lines = text.splitlines()
    for index, line in enumerate(lines):
        match = re.match(r"^(\s*)info\s*:\s*$", line)
        if not match:
            continue
        indent = len(match.group(1))
        for nested in lines[index + 1 :]:
            if not nested.strip() or nested.lstrip().startswith("#"):
                continue
            nested_indent = len(nested) - len(nested.lstrip())
            if nested_indent <= indent:
                break
            version_match = re.match(r"^\s*version\s*:\s*['\"]?([^\s'\"]+)", nested)
            if version_match:
                return version_match.group(1)
    return None


def validate_mock(path: Path, root: Path, indexed: set[Path]) -> list[str]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return [f"invalid Mock JSON: {exc}"]
    if not isinstance(value, dict):
        return ["Mock must be a JSON object"]
    contract = value.get("_contract")
    version = value.get("_contractVersion")
    if not isinstance(contract, str) or not contract or not isinstance(version, str) or not version:
        return ["Mock requires non-empty _contract and _contractVersion"]
    target = (path.parent / contract).resolve()
    try:
        target.relative_to(root)
    except ValueError:
        return ["Mock contract reference escapes architecture directory"]
    if target not in indexed:
        return ["Mock contract reference must target an indexed contract"]
    actual_version = structured_contract_version(target)
    if actual_version is None:
        return ["Mock target contract must declare info.version"]
    if version != actual_version:
        return [f"Mock contract version mismatch: expected {actual_version}, found {version}"]
    return []


@lru_cache(maxsize=1)
def nova_review_module() -> ModuleType | None:
    tool = Path(__file__).resolve().parents[2] / "nova-review/scripts/nova_review.py"
    if not tool.is_file():
        return None
    try:
        spec = importlib.util.spec_from_file_location("nova_review_architecture_evidence", tool)
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


def trusted_review_pass(nova_root: Path, work_item: str, required_paths: set[Path]) -> bool:
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
    if feature.get("change_class") != "designed":
        return False
    try:
        reviewed_at = module.parse_reviewed_at(feature["completed_at"], "completed_at")
        review_path = module.review_path_for_values(
            repo, reviewed_at, feature["review_batch"]
        )
        review_relative = review_path.relative_to(repo).as_posix()
        review_bytes = module.git_blob(repo, "HEAD", review_relative)
        if review_bytes is None:
            return False
        review = module.validate_review_record(
            json.loads(review_bytes.decode("utf-8")), review_path
        )
    except (module.NovaError, OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError):
        return False
    reviewed_commits = {
        item["commit"]
        for item in feature.get("commits", [])
        if isinstance(item, dict) and item.get("repository") == "main"
    }
    scope = set(review.get("review_scope", []))
    for required in required_paths:
        try:
            relative = required.resolve().relative_to(repo).as_posix()
        except ValueError:
            return False
        if f"main:{relative}" not in scope:
            return False
        dirty = subprocess.run(
            ["git", "-C", str(repo), "diff", "--quiet", "HEAD", "--", relative],
            check=False,
        )
        if dirty.returncode != 0:
            return False
        latest = subprocess.run(
            ["git", "-C", str(repo), "log", "-1", "--format=%H", "--", relative],
            capture_output=True,
            text=True,
            check=False,
        )
        if latest.returncode or latest.stdout.strip() not in reviewed_commits:
            return False
    return True


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
    contracts_by_type: dict[str, list[list[str]]] = {contract_type: [] for contract_type in CONTRACT_TYPES}
    for row in contracts:
        if row[0] not in CONTRACT_TYPES:
            errors.append(f"invalid architecture contract type: {row[0]}")
        else:
            contracts_by_type[row[0]].append(row)
    nova_root = path.parent.parent.resolve()
    for name, needed, state, evidence in gates:
        if needed not in {"是", "否"}:
            errors.append(f"invalid needed value for {name}: {needed}")
        if state not in STATUS:
            errors.append(f"invalid gate status for {name}: {state}")
        if needed == "否" and (state != "不适用" or evidence != "无"):
            errors.append(f"unneeded gate must be 不适用 with 无 evidence: {name}")
        if needed == "是" and state == "不适用":
            errors.append(f"needed gate cannot be 不适用: {name}")
        contract_rows = contracts_by_type.get(GATE_TYPES.get(name, ""), [])
        if needed == "是" and not contract_rows:
            errors.append(f"needed gate has no indexed contract: {name}")
        if needed == "否" and contract_rows:
            errors.append(f"unneeded gate must not have indexed contracts: {name}")
        if contract_rows:
            states = [row[3] for row in contract_rows]
            derived = "待确认" if "待确认" in states else "待Review" if "待Review" in states else "已通过"
            if state != derived:
                errors.append(f"gate state conflicts with indexed contracts: {name}")
        if state in {"待Review", "已通过"}:
            if PEND_RE.fullmatch(evidence) is None:
                errors.append(f"reviewable gate requires PEND Review evidence: {name}")
        elif evidence != "无":
            errors.append(f"unconfirmed gate must use 无 Review evidence: {name}")

    root = path.parent.resolve()
    referenced: set[Path] = set()
    contract_targets: list[tuple[str, str, Path]] = []
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
        contract_targets.append((contract_type, link, target))
    for contract_type, link, target in contract_targets:
        if contract_type == "工程骨架":
            errors.extend(f"{link}: {error}" for error in validate_foundation_contract(target))
        elif contract_type == "数据":
            errors.extend(f"{link}: {error}" for error in validate_data_contract(target))
        elif contract_type == "API":
            root_version = structured_contract_root(target, "openapi")
            if target.suffix not in {".yaml", ".yml", ".json"} or root_version is None or OPENAPI_VERSION_RE.fullmatch(root_version) is None:
                errors.append(f"API contract must contain a supported OpenAPI 3.0.x or 3.1.x root: {link}")
        elif contract_type == "事件":
            root_version = structured_contract_root(target, "asyncapi")
            if target.suffix not in {".yaml", ".yml", ".json"} or root_version is None or ASYNCAPI_VERSION_RE.fullmatch(root_version) is None:
                errors.append(f"event contract must contain a supported AsyncAPI 2.x or 3.x root: {link}")
        elif contract_type == "Mock":
            if target.suffix != ".json":
                errors.append(f"Mock contract must use JSON: {link}")
            else:
                errors.extend(f"{link}: {error}" for error in validate_mock(target, root, referenced))
    for directory in ("foundation", "api", "data", "events", "mocks"):
        candidate = path.parent / directory
        if candidate.is_dir() and not any(file.is_file() for file in candidate.rglob("*")):
            errors.append(f"empty architecture directory is forbidden: {directory}")
        for file in candidate.rglob("*") if candidate.is_dir() else ():
            if file.is_file() and file.resolve() not in referenced:
                errors.append(f"architecture file is not indexed: {file.relative_to(path.parent)}")
    targets_by_type: dict[str, set[Path]] = {contract_type: set() for contract_type in CONTRACT_TYPES}
    for contract_type, _, target in contract_targets:
        targets_by_type[contract_type].add(target)
    for name, needed, state, evidence in gates:
        if state not in {"待Review", "已通过"} or PEND_RE.fullmatch(evidence) is None:
            if ready and needed == "是":
                errors.append(f"parallel development gate is not ready: {name}")
            continue
        required_paths = {path.resolve()} | targets_by_type.get(GATE_TYPES.get(name, ""), set())
        trusted = trusted_review_pass(nova_root, evidence, required_paths)
        if state == "已通过" and not trusted:
            errors.append(f"gate Review evidence is not a trusted PASS covering current contracts: {name}")
        if ready and needed == "是" and not trusted:
            errors.append(f"parallel development gate is not ready: {name}")
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
