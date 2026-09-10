#!/usr/bin/env python3
"""Validate, apply, and query Nova requirement delivery ledgers."""

from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


REVIEW_TOOL = Path(__file__).resolve().parents[2] / "nova-review/scripts/nova_review.py"
SPEC = importlib.util.spec_from_file_location("nova_delivery_review", REVIEW_TOOL)
assert SPEC is not None and SPEC.loader is not None
NOVA = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = NOVA
SPEC.loader.exec_module(NOVA)


def git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=False,
        capture_output=True,
        text=True,
    )


def load_candidate(path: Path) -> tuple[dict[str, Any], bytes]:
    content = path.read_bytes()
    value = NOVA.strict_json_object(content, "delivery candidate")
    canonical = NOVA.canonical_delivery_ledger(value)
    if content != canonical:
        raise NOVA.NovaError("delivery candidate must use canonical UTF-8 JSON")
    return value, content


def validate_candidate(repo: Path, candidate: dict[str, Any]) -> None:
    blueprint = (repo / ".nova/PROJECT_BLUEPRINT.md").read_text(encoding="utf-8")
    product_path = repo / ".nova/PRODUCT_REQUIREMENTS.md"
    product = product_path.read_text(encoding="utf-8")
    if candidate.get("status") != "development":
        raise NOVA.NovaError("only Review closure may create implemented delivery state")
    product = NOVA.update_product_requirement_development(
        product, candidate.get("requirement_ref", "")
    )
    NOVA.validate_delivery_ledger_data(
        repo,
        candidate,
        blueprint=blueprint,
        product=product,
        verify_evidence=True,
    )


def validate_history(previous: dict[str, Any] | None, candidate: dict[str, Any]) -> None:
    if previous is None:
        if candidate.get("plan_version") != 1:
            raise NOVA.NovaError("initial delivery plan_version must be 1")
        changes = candidate.get("changes", [])
        if len(changes) != 1 or changes[0].get("kind") != "created":
            raise NOVA.NovaError("initial delivery plan must contain one created change")
        return
    if candidate.get("requirement_ref") != previous.get("requirement_ref"):
        raise NOVA.NovaError("delivery plan may not change Requirement-Ref")
    if candidate.get("requirement_checkpoint") != previous.get("requirement_checkpoint"):
        raise NOVA.NovaError("delivery plan may not change requirement checkpoint")
    if candidate.get("plan_version") != previous.get("plan_version", 0) + 1:
        raise NOVA.NovaError("delivery plan_version must increment by one")
    old_changes = previous.get("changes", [])
    if candidate.get("changes", [])[:-1] != old_changes:
        raise NOVA.NovaError("delivery plan changes history must be append-only")
    new_items = {
        item.get("work_item"): item for item in candidate.get("work_items", [])
    }
    for old_item in previous.get("work_items", []):
        work_item = old_item.get("work_item")
        if work_item not in new_items:
            raise NOVA.NovaError(f"delivery plan may not delete work item: {work_item}")
        old_milestones = {value.get("id") for value in old_item.get("milestones", [])}
        new_milestones = {value.get("id") for value in new_items[work_item].get("milestones", [])}
        missing = sorted(old_milestones - new_milestones)
        if missing:
            raise NOVA.NovaError(
                f"delivery plan may not delete milestones from {work_item}: {missing}"
            )


def apply_plan(repo: Path, candidate_path: Path, expected_head: str) -> dict[str, Any]:
    current_head = NOVA.run_git(repo, "rev-parse", "HEAD").strip()
    if current_head != expected_head:
        raise NOVA.NovaError("Git HEAD changed before delivery plan apply")
    if git(repo, "diff", "--cached", "--quiet").returncode != 0:
        raise NOVA.NovaError("delivery plan apply requires an empty Git index")
    candidate, content = load_candidate(candidate_path)
    target = NOVA.safe_repo_path(
        repo,
        NOVA.delivery_relative_path(candidate.get("requirement_ref", "")),
        "delivery ledger",
    )
    previous_bytes = target.read_bytes() if target.exists() else None
    previous = (
        NOVA.strict_json_object(previous_bytes, "previous delivery ledger")
        if previous_bytes is not None
        else None
    )
    validate_history(previous, candidate)
    validate_candidate(repo, candidate)
    product_path = NOVA.safe_repo_path(
        repo, ".nova/PRODUCT_REQUIREMENTS.md", "product requirements"
    )
    product_bytes = product_path.read_bytes()
    updated_product = NOVA.update_product_requirement_development(
        product_bytes.decode("utf-8"), candidate["requirement_ref"]
    ).encode("utf-8")
    snapshots = {target: previous_bytes, product_path: product_bytes}
    updates = {
        target: (previous_bytes, content),
        product_path: (product_bytes, updated_product),
    }
    NOVA.atomic_write_group(repo, updates, snapshots)
    return {
        "requirement_ref": candidate["requirement_ref"],
        "plan_version": candidate["plan_version"],
        "ledger": target.relative_to(repo).as_posix(),
        "product": product_path.relative_to(repo).as_posix(),
        "expected_head": expected_head,
    }


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    commands = root.add_subparsers(dest="command", required=True)
    validate = commands.add_parser("validate")
    validate.add_argument("--repo", type=Path, required=True)
    validate.add_argument("--ledger", type=Path, required=True)
    apply = commands.add_parser("apply-plan")
    apply.add_argument("--repo", type=Path, required=True)
    apply.add_argument("--candidate", type=Path, required=True)
    apply.add_argument("--expected-head", required=True)
    query = commands.add_parser("query")
    query.add_argument("--repo", type=Path, required=True)
    group = query.add_mutually_exclusive_group(required=True)
    group.add_argument("--requirement-ref")
    group.add_argument("--work-item")
    return root


def main() -> int:
    args = parser().parse_args()
    try:
        repo = args.repo.resolve()
        if args.command == "validate":
            candidate, _ = load_candidate(args.ledger.resolve())
            validate_candidate(repo, candidate)
            result = {"status": "PASS", "requirement_ref": candidate["requirement_ref"]}
        elif args.command == "apply-plan":
            result = apply_plan(repo, args.candidate.resolve(), args.expected_head)
        else:
            result = NOVA.query_delivery(repo, args.requirement_ref, args.work_item)
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    except (NOVA.NovaError, OSError, UnicodeError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
