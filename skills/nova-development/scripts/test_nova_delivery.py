#!/usr/bin/env python3

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


MODULE_PATH = Path(__file__).with_name("nova_delivery.py")
SPEC = importlib.util.spec_from_file_location("nova_delivery_test", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
DELIVERY = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = DELIVERY
SPEC.loader.exec_module(DELIVERY)
NOVA = DELIVERY.NOVA

REQ = "REQ-019a1234-5678-7abc-8def-0123456789ab@v1"
PEND = "PEND-019a1234-5678-7abc-8def-0123456789ab"
COMMIT = "a" * 40
SHA = "b" * 64
DESIGN = ".nova/design/2026-09-04_example.md#wp-01-example"


def ledger(*, item_state: str = "review_pending", milestone_state: str = "completed") -> dict:
    return {
        "schema": 1,
        "requirement_ref": REQ,
        "requirement_checkpoint": {
            "commit": COMMIT,
            "path": ".nova/requirements/REQ-019a1234-5678-7abc-8def-0123456789ab_example.md",
            "sha256": SHA,
        },
        "plan_version": 1,
        "status": "development",
        "work_items": [
            {
                "work_item": PEND,
                "title": "完整交付能力",
                "dependencies": [],
                "done_definition": "端到端查询返回可信进度",
                "design_ref": DESIGN,
                "state": item_state,
                "blocked_reason": None,
                "supersedes": [],
                "change_reason": "initial-plan",
                "milestones": [
                    {
                        "id": "M-01",
                        "title": "完整实现",
                        "done_definition": "测试通过并提交",
                        "state": milestone_state,
                        "blocked_reason": None,
                        "evidence": [COMMIT] if milestone_state == "completed" else [],
                    }
                ],
            }
        ],
        "changes": [
            {
                "plan_version": 1,
                "kind": "created",
                "work_items": [PEND],
                "reason": "initial-plan",
            }
        ],
    }


def blueprint(*items: str) -> str:
    header = (
        "| 编号 | 优先级 | 来源 | 功能 | 设计依据 | 前置依赖 | 完成定义 | 需求引用 |\n"
        "|------|--------|------|------|----------|----------|----------|----------|\n"
    )
    return header + "".join(
        f"| {item} | P0 | 用户提出 | 完整交付 | [设计](design/2026-09-04_example.md#wp-01-example) | 无 | 完成 | {REQ} |\n"
        for item in items
    )


def product(state: str = "开发中") -> str:
    key, version = REQ.split("@", 1)
    return (
        "| Requirement Key | 版本 | 状态 | 业务模块 | 需求块 | 已实现版本 | 实现依据 |\n"
        "|-----------------|------|------|----------|--------|------------|----------|\n"
        f"| {key} | {version} | {state} | 交付 | [需求](requirements/{key}_example.md) | 无 | 无 |\n"
    )


class DeliveryLedgerTests(unittest.TestCase):
    def test_delivery_plan_trailers_are_a_checkpoint_not_a_work_item(self) -> None:
        message = (
            "plan: create delivery ledger\n\n"
            "Nova-Schema: 1\n"
            "Commit-Kind: delivery-plan\n"
            f"Requirement-Ref: {REQ}\n"
            f"Requirement-Commit: {COMMIT}\n"
            f"Requirement-SHA256: {SHA}\n"
            "Plan-Version: 1\n"
            "Validation: nova-delivery validate (pass)\n"
        )
        values, errors = NOVA.parse_message(message)
        self.assertEqual(errors, [])
        self.assertEqual(values["Commit-Kind"], "delivery-plan")
        self.assertNotIn("Work-Item", values)

    def test_valid_single_task_with_internal_milestone_passes(self) -> None:
        checkpoint = {"commit": COMMIT, "path": ledger()["requirement_checkpoint"]["path"], "sha256": SHA}
        with mock.patch.object(NOVA, "query_requirement", return_value=checkpoint):
            result = NOVA.validate_delivery_ledger_data(
                Path("/tmp/repo"),
                ledger(),
                blueprint=blueprint(PEND),
                product=product(),
                verify_evidence=False,
            )
        self.assertEqual(result["work_items"][0]["milestones"][0]["id"], "M-01")

    def test_blueprint_cannot_reintroduce_step_level_work_items(self) -> None:
        extra = "PEND-019a1234-5678-7abc-8def-1123456789ab"
        checkpoint = {"commit": COMMIT, "path": ledger()["requirement_checkpoint"]["path"], "sha256": SHA}
        with mock.patch.object(NOVA, "query_requirement", return_value=checkpoint):
            with self.assertRaisesRegex(NOVA.NovaError, "ledger and blueprint"):
                NOVA.validate_delivery_ledger_data(
                    Path("/tmp/repo"),
                    ledger(),
                    blueprint=blueprint(PEND, extra),
                    product=product(),
                    verify_evidence=False,
                )

    def test_review_pass_closes_whole_task_not_milestone(self) -> None:
        updated, complete, evidence = NOVA.update_delivery_ledger_for_pass(
            NOVA.canonical_delivery_ledger(ledger()),
            REQ,
            PEND,
            "NR-20260904-example",
            "2026-09-04T12:00:00+08:00",
        )
        value = json.loads(updated)
        self.assertTrue(complete)
        self.assertEqual(evidence, [PEND])
        self.assertEqual(value["status"], "implemented")
        self.assertEqual(value["work_items"][0]["state"], "completed")
        self.assertEqual(value["plan_version"], 2)

    def test_review_pass_rejects_incomplete_internal_milestone(self) -> None:
        value = ledger(item_state="review_pending", milestone_state="active")
        with self.assertRaisesRegex(NOVA.NovaError, "incomplete milestones"):
            NOVA.update_delivery_ledger_for_pass(
                NOVA.canonical_delivery_ledger(value),
                REQ,
                PEND,
                "NR-20260904-example",
                "2026-09-04T12:00:00+08:00",
            )

    def test_completed_historical_ledger_remains_queryable_after_requirement_upgrade(self) -> None:
        value = ledger(item_state="completed")
        value["status"] = "implemented"
        value["plan_version"] = 2
        value["changes"].append(
            {
                "plan_version": 2,
                "kind": "completed",
                "reason": "trusted Review PASS",
            }
        )
        key, _ = REQ.split("@", 1)
        upgraded_product = (
            "| Requirement Key | 版本 | 状态 | 业务模块 | 需求块 | 已实现版本 | 实现依据 |\n"
            "|-----------------|------|------|----------|--------|------------|----------|\n"
            f"| {key} | v2 | 已更新 | 交付 | [需求](requirements/{key}_example.md) | v1 | {PEND} |\n"
        )
        checkpoint = {
            "commit": COMMIT,
            "path": value["requirement_checkpoint"]["path"],
            "sha256": SHA,
        }
        original_validate = NOVA.validate_delivery_ledger_data

        def validate_without_git_evidence(
            repo: Path,
            candidate: dict,
            *,
            blueprint: str,
            product: str,
            **_: object,
        ) -> dict:
            return original_validate(
                repo,
                candidate,
                blueprint=blueprint,
                product=product,
                verify_evidence=False,
                verify_review_state=False,
            )

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            delivery_path = root / NOVA.delivery_relative_path(REQ)
            delivery_path.parent.mkdir(parents=True)
            delivery_path.write_bytes(NOVA.canonical_delivery_ledger(value))
            (root / ".nova/PROJECT_BLUEPRINT.md").write_text(
                blueprint(), encoding="utf-8"
            )
            (root / ".nova/PRODUCT_REQUIREMENTS.md").write_text(
                upgraded_product, encoding="utf-8"
            )
            with (
                mock.patch.object(NOVA, "query_requirement", return_value=checkpoint),
                mock.patch.object(
                    NOVA,
                    "validate_delivery_ledger_data",
                    side_effect=validate_without_git_evidence,
                ),
            ):
                result = NOVA.query_delivery(root, requirement_ref=REQ)
        self.assertEqual(result["requirement_ref"], REQ)
        self.assertEqual(result["status"], "implemented")
        self.assertEqual(result["completed"], 1)

    def test_plan_history_cannot_delete_task_or_milestone(self) -> None:
        previous = ledger(item_state="active", milestone_state="active")
        candidate = json.loads(json.dumps(previous))
        candidate["plan_version"] = 2
        candidate["changes"].append(
            {"plan_version": 2, "kind": "milestone-updated", "reason": "progress"}
        )
        candidate["work_items"][0]["milestones"] = []
        with self.assertRaisesRegex(NOVA.NovaError, "may not delete milestones"):
            DELIVERY.validate_history(previous, candidate)


if __name__ == "__main__":
    unittest.main()
