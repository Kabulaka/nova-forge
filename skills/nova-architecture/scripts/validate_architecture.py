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
GATE_HEADERS = ("门禁", "是否需要", "状态", "确认依据")
LEGACY_GATE_HEADERS = ("门禁", "是否需要", "状态", "Review 依据")
INDEX_HEADERS = ("契约类型", "业务范围", "路径", "状态", "所有者")
DEPENDENCY_HEADERS = ("需求块", "依赖需求块", "无法解除的业务原因", "开发顺序")
REQUIRED_GATES = ("共享工程骨架", "数据所有权与契约", "公共 API 契约", "事件契约", "Mock 与测试夹具")
STATUS = {"待确认", "已确认", "不适用", "待Review", "已通过"}
CONTRACT_TYPES = {"工程骨架", "数据", "API", "事件", "Mock"}
GATE_TYPES = {
    "共享工程骨架": "工程骨架",
    "数据所有权与契约": "数据",
    "公共 API 契约": "API",
    "事件契约": "事件",
    "Mock 与测试夹具": "Mock",
}
PEND_RE = re.compile(r"^PEND-(?:[0-9]+|[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12})$")
ARCH_RE = re.compile(r"^ARCH-[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")
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


def table_with_lines(
    text: str, section: str, headers: tuple[str, ...]
) -> tuple[list[tuple[list[str], int]], list[str]]:
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
        rows: list[tuple[list[str], int]] = []
        cursor = index + 2
        while cursor < len(lines) and lines[cursor].lstrip().startswith("|"):
            row = [cell.strip() for cell in lines[cursor].strip().strip("|").split("|")]
            if len(row) != len(headers):
                return rows, [f"invalid column count in {section}"]
            if any(not cell for cell in row):
                return rows, [f"empty table cell in {section}"]
            rows.append((row, cursor + 1))
            cursor += 1
        return rows, [] if rows else [f"table must contain rows: {section}"]
    return [], [f"missing exact table header in {section}"]


def table(text: str, section: str, headers: tuple[str, ...]) -> tuple[list[list[str]], list[str]]:
    rows, errors = table_with_lines(text, section, headers)
    return [row for row, _ in rows], errors


def validate_data_contract(path: Path) -> list[str]:
    text, errors = read(path)
    if text is None:
        return errors
    expected = ("所有权", "数据约束", "一致性与并发", "失败与恢复")
    if sections(text) != expected:
        errors.append("data contract sections must be exactly: " + " | ".join(expected))
    versions = re.findall(r"^>\s*数据契约版本[：:]\s*(.+?)\s*$", text, re.MULTILINE)
    if len(versions) != 1 or versions[0] not in {"1", "2"}:
        errors.append("data contract version must be 1 or 2")
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
    versions = re.findall(r"^>\s*工程骨架契约版本[：:]\s*(.+?)\s*$", text, re.MULTILINE)
    if len(versions) != 1 or versions[0] not in {"1", "2"}:
        errors.append("foundation contract version must be 1 or 2")
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
        encoding="utf-8",
        errors="strict",
        check=False,
    )
    if result.returncode:
        return None
    repo = Path(result.stdout.strip()).resolve()
    return repo if (repo / ".nova").resolve() == nova_root.resolve() else None


def trusted_review_item(
    module: ModuleType,
    repo: Path,
    work_item: str,
    cache: dict[str, tuple[dict[str, object], dict[str, object]] | None],
    audit_cache: dict[str, dict[str, tuple[dict[str, object], dict[str, object]]]],
) -> tuple[dict[str, object], dict[str, object]] | None:
    if work_item in cache:
        return cache[work_item]
    try:
        completed = module.load_completed_item(repo, work_item, audit_cache=audit_cache)
    except (module.NovaError, OSError, UnicodeError, json.JSONDecodeError):
        completed = None
    if completed is None or completed[0].get("change_class") != "designed":
        cache[work_item] = None
    else:
        feature, _ = completed
        try:
            reviewed_at = module.parse_reviewed_at(feature["completed_at"], "completed_at")
            review_path = module.review_path_for_values(
                repo, reviewed_at, feature["review_batch"]
            )
            review_relative = review_path.relative_to(repo).as_posix()
            review_bytes = module.git_blob(repo, "HEAD", review_relative)
            if review_bytes is None:
                raise ValueError("missing Review record")
            review = module.validate_review_record(
                json.loads(review_bytes.decode("utf-8")), review_path
            )
        except (
            module.NovaError,
            OSError,
            UnicodeError,
            json.JSONDecodeError,
            KeyError,
            TypeError,
            ValueError,
        ):
            cache[work_item] = None
        else:
            cache[work_item] = (feature, review)
    return cache[work_item]


def trusted_commit_owner(
    module: ModuleType,
    repo: Path,
    commit_hash: str,
    relative: str,
    cache: dict[str, tuple[dict[str, object], dict[str, object]] | None],
    audit_cache: dict[str, dict[str, tuple[dict[str, object], dict[str, object]]]],
) -> str | None:
    try:
        message = module.run_git(repo, "show", "-s", "--format=%B", commit_hash)
        metadata, message_errors = module.parse_message(message)
    except (module.NovaError, OSError, UnicodeError):
        return None
    architecture_ref = metadata.get("Architecture-Ref", "")
    if not message_errors and metadata.get("Commit-Kind") == "architecture":
        try:
            diff = module.run_git(
                repo, "show", "--format=", "--binary", "--no-ext-diff", commit_hash
            )
            _, committed_errors = module.validate_committed_message(
                repo, commit_hash, message, diff
            )
        except (module.NovaError, OSError, UnicodeError):
            return None
        if (
            not committed_errors
            and ARCH_RE.fullmatch(architecture_ref) is not None
            and relative in module.diff_paths(diff)
        ):
            return architecture_ref
        return None
    work_item = metadata.get("Work-Item", "")
    if message_errors or PEND_RE.fullmatch(work_item) is None:
        return None
    completed = trusted_review_item(module, repo, work_item, cache, audit_cache)
    if completed is None:
        return None
    feature, review = completed
    commits = feature.get("commits", [])
    if not isinstance(commits, list) or not any(
        isinstance(commit_ref, dict)
        and commit_ref.get("repository") == "main"
        and commit_ref.get("commit") == commit_hash
        for commit_ref in commits
    ):
        return None
    scope = review.get("review_scope", [])
    if not isinstance(scope, list) or f"main:{relative}" not in scope:
        return None
    return work_item


def blamed_commit(repo: Path, relative: str, line_number: int) -> str | None:
    result = subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "blame",
            "--line-porcelain",
            "-L",
            f"{line_number},{line_number}",
            "--",
            relative,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        return None
    first = result.stdout.partition("\n")[0]
    match = re.match(r"\^?([0-9a-f]{40,64})\s", first)
    if match is None or set(match.group(1)) == {"0"}:
        return None
    return match.group(1)


def trusted_line_owner(
    module: ModuleType,
    repo: Path,
    path: Path,
    line_number: int,
    cache: dict[str, tuple[dict[str, object], dict[str, object]] | None],
    audit_cache: dict[str, dict[str, tuple[dict[str, object], dict[str, object]]]],
) -> str | None:
    try:
        relative = path.resolve().relative_to(repo).as_posix()
    except ValueError:
        return None
    commit_hash = blamed_commit(repo, relative, line_number)
    if commit_hash is None:
        return None
    return trusted_commit_owner(module, repo, commit_hash, relative, cache, audit_cache)


def trusted_file_owner(
    module: ModuleType,
    repo: Path,
    path: Path,
    cache: dict[str, tuple[dict[str, object], dict[str, object]] | None],
    audit_cache: dict[str, dict[str, tuple[dict[str, object], dict[str, object]]]],
) -> str | None:
    try:
        relative = path.resolve().relative_to(repo).as_posix()
    except (ValueError, OSError):
        return None
    head = module.git_blob(repo, "HEAD", relative)
    clean = subprocess.run(
        ["git", "-C", str(repo), "diff", "--quiet", "HEAD", "--", relative],
        check=False,
    )
    if head is None or clean.returncode != 0:
        return None
    result = subprocess.run(
        ["git", "-C", str(repo), "log", "-1", "--format=%H", "--", relative],
        capture_output=True,
        text=True,
        check=False,
    )
    commit_hash = result.stdout.strip() if result.returncode == 0 else ""
    if not re.fullmatch(r"[0-9a-f]{40,64}", commit_hash):
        return None
    return trusted_commit_owner(module, repo, commit_hash, relative, cache, audit_cache)


def trusted_contract_binding(
    module: ModuleType,
    repo: Path,
    index_path: Path,
    line_number: int,
    target: Path,
    cache: dict[str, tuple[dict[str, object], dict[str, object]] | None],
    audit_cache: dict[str, dict[str, tuple[dict[str, object], dict[str, object]]]],
) -> bool:
    """Trust an ARCH-owned index row as confirmation of the target bytes it saw."""
    try:
        index_relative = index_path.resolve().relative_to(repo).as_posix()
        target_relative = target.resolve().relative_to(repo).as_posix()
    except (ValueError, OSError):
        return False
    current = module.git_blob(repo, "HEAD", target_relative)
    clean = subprocess.run(
        ["git", "-C", str(repo), "diff", "--quiet", "HEAD", "--", target_relative],
        check=False,
    )
    if current is None or clean.returncode != 0:
        return False
    commit_hash = blamed_commit(repo, index_relative, line_number)
    if commit_hash is None:
        return False
    owner = trusted_commit_owner(
        module, repo, commit_hash, index_relative, cache, audit_cache
    )
    if owner is None:
        return False
    if ARCH_RE.fullmatch(owner) is not None:
        return module.git_blob(repo, commit_hash, target_relative) == current
    return trusted_file_owner(module, repo, target, cache, audit_cache) is not None


def trusted_index_history(
    module: ModuleType,
    repo: Path,
    path: Path,
    cache: dict[str, tuple[dict[str, object], dict[str, object]] | None],
    audit_cache: dict[str, dict[str, tuple[dict[str, object], dict[str, object]]]],
) -> bool:
    try:
        relative = path.resolve().relative_to(repo).as_posix()
    except (ValueError, OSError):
        return False
    current = module.git_blob(repo, "HEAD", relative)
    clean = subprocess.run(
        ["git", "-C", str(repo), "diff", "--quiet", "HEAD", "--", relative],
        check=False,
    )
    if current is None or clean.returncode != 0:
        return False
    result = subprocess.run(
        ["git", "-C", str(repo), "log", "--follow", "--format=%H", "--", relative],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        return False
    # A schema 2 ARCH checkpoint is an explicit current-byte rebaseline. Changes
    # after that checkpoint must still be owned by another trusted checkpoint.
    untrusted_after_arch = False
    for commit_hash in result.stdout.splitlines():
        owner = trusted_commit_owner(
            module, repo, commit_hash.strip(), relative, cache, audit_cache
        )
        if owner is not None and ARCH_RE.fullmatch(owner) is not None:
            return not untrusted_after_arch
        if owner is None:
            untrusted_after_arch = True

    trusted_baseline = False
    for commit_hash in reversed(result.stdout.splitlines()):
        owner = trusted_commit_owner(
            module, repo, commit_hash.strip(), relative, cache, audit_cache
        )
        if owner is not None:
            trusted_baseline = True
        elif trusted_baseline:
            return False
    return trusted_baseline


def validate(path: Path, ready: bool) -> list[str]:
    text, errors = read(path)
    if text is None:
        return errors
    module = nova_review_module()
    repo = git_repo_for_nova(path.parent.parent)
    if module is not None and repo is not None:
        transaction_guard = getattr(module, "assert_review_transaction_clean", None)
        if transaction_guard is not None:
            try:
                transaction_guard(repo)
            except (module.NovaError, OSError) as exc:
                errors.append(f"unfinished Nova Review transaction: {exc}")
                return errors
    if path.name != "ARCHITECTURE_CONTRACTS.md":
        errors.append("architecture index must be named ARCHITECTURE_CONTRACTS.md")
    if sections(text) != SECTIONS:
        errors.append("level-2 sections must be exactly: " + " | ".join(SECTIONS))
    if PLACEHOLDER_RE.search(text):
        errors.append("unfinished placeholder found")
    versions = re.findall(r"^>\s*架构契约版本[：:]\s*(.+?)\s*$", text, re.MULTILINE)
    if len(versions) != 1 or versions[0] not in {"1", "2"}:
        errors.append("architecture contract version must be 1 or 2")
    blueprint_refs = re.findall(r"^>\s*蓝图引用[：:]\s*(.+?)\s*$", text, re.MULTILINE)
    if blueprint_refs != ["../PROJECT_BLUEPRINT.md"]:
        errors.append("blueprint reference must be ../PROJECT_BLUEPRINT.md")
    elif not (path.parent / blueprint_refs[0]).resolve().is_file():
        errors.append("referenced .nova/PROJECT_BLUEPRINT.md does not exist")

    gate_entries, gate_errors = table_with_lines(text, "并行开发门禁", GATE_HEADERS)
    if gate_errors:
        legacy_gate_entries, legacy_gate_errors = table_with_lines(
            text, "并行开发门禁", LEGACY_GATE_HEADERS
        )
        if not legacy_gate_errors:
            gate_entries, gate_errors = legacy_gate_entries, []
    contract_entries, contract_errors = table_with_lines(text, "契约索引", INDEX_HEADERS)
    dependency_entries, dependency_errors = table_with_lines(text, "硬依赖", DEPENDENCY_HEADERS)
    errors.extend(gate_errors + contract_errors + dependency_errors)
    gates = [row for row, _ in gate_entries]
    contracts = [row for row, _ in contract_entries]
    dependencies = [row for row, _ in dependency_entries]
    gate_names = [row[0] for row in gates]
    if tuple(gate_names) != REQUIRED_GATES:
        errors.append("parallel gates must be exactly: " + " | ".join(REQUIRED_GATES))
    contracts_by_type: dict[str, list[tuple[list[str], int]]] = {
        contract_type: [] for contract_type in CONTRACT_TYPES
    }
    for row, line_number in contract_entries:
        if row[0] not in CONTRACT_TYPES:
            errors.append(f"invalid architecture contract type: {row[0]}")
        else:
            contracts_by_type[row[0]].append((row, line_number))
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
            states = [row[3] for row, _ in contract_rows]
            derived = (
                "待确认"
                if "待确认" in states
                else "待Review"
                if "待Review" in states
                else "已确认"
                if "已确认" in states
                else "已通过"
            )
            if state != derived:
                errors.append(f"gate state conflicts with indexed contracts: {name}")
        if state in {"待Review", "已通过"}:
            if PEND_RE.fullmatch(evidence) is None:
                errors.append(f"legacy reviewable gate requires PEND Review evidence: {name}")
        elif state == "已确认":
            if ARCH_RE.fullmatch(evidence) is None:
                errors.append(f"confirmed gate requires ARCH evidence: {name}")
        elif evidence != "无":
            errors.append(f"unconfirmed gate must use 无 confirmation evidence: {name}")

    root = path.parent.resolve()
    referenced: set[Path] = set()
    contract_targets: list[tuple[str, str, Path, int]] = []
    for (contract_type, scope, link, state, owner), line_number in contract_entries:
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
        contract_targets.append((contract_type, link, target, line_number))
    for contract_type, link, target, _ in contract_targets:
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
                errors.append(
                    "architecture file is not indexed: "
                    + file.relative_to(path.parent).as_posix()
                )
    module = nova_review_module()
    repo = git_repo_for_nova(nova_root)
    review_cache: dict[str, tuple[dict[str, object], dict[str, object]] | None] = {}
    audit_cache: dict[str, dict[str, tuple[dict[str, object], dict[str, object]]]] = {}
    history_required = ready
    if history_required and (
        module is None
        or repo is None
        or not trusted_index_history(
            module, repo, path, review_cache, audit_cache
        )
    ):
        errors.append("architecture index history contains changes outside trusted PASS work items")
    for (name, needed, state, evidence), gate_line in gate_entries:
        evidence_pattern = ARCH_RE if state == "已确认" else PEND_RE
        if state not in {"待Review", "已通过", "已确认"} or evidence_pattern.fullmatch(evidence) is None:
            if ready and needed == "是":
                errors.append(f"parallel development gate is not ready: {name}")
            continue
        contract_type = GATE_TYPES.get(name, "")
        relevant_targets = [
            (target, line_number)
            for indexed_type, _, target, line_number in contract_targets
            if indexed_type == contract_type
        ]
        trusted = module is not None and repo is not None
        if trusted:
            trusted = (
                trusted_line_owner(
                    module, repo, path, gate_line, review_cache, audit_cache
                )
                == evidence
            )
        if trusted:
            trusted = all(
                trusted_contract_binding(
                    module,
                    repo,
                    path,
                    line_number,
                    target,
                    review_cache,
                    audit_cache,
                )
                for target, line_number in relevant_targets
            )
        if ready and state in {"已通过", "已确认"} and not trusted:
            errors.append(f"gate confirmation evidence does not cover current contracts: {name}")
        if ready and needed == "是" and not trusted:
            errors.append(f"parallel development gate is not ready: {name}")
    for (requirement, dependency, reason, order), line_number in dependency_entries:
        if dependency == "无" and (reason != "无" or order != "并行"):
            errors.append(f"dependency-free requirement must be marked 无/并行: {requirement}")
        if dependency != "无" and (reason == "无" or order == "并行"):
            errors.append(f"hard dependency requires a reason and serial order: {requirement}")
        if ready and (
            module is None
            or repo is None
            or trusted_line_owner(
                module, repo, path, line_number, review_cache, audit_cache
            )
            is None
        ):
            errors.append(f"hard dependency row lacks trusted PASS evidence: {requirement}")
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
