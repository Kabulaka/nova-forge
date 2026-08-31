#!/usr/bin/env python3

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("nova_review.py")
SPEC = importlib.util.spec_from_file_location("nova_review_requirement_test", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
NOVA = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = NOVA
SPEC.loader.exec_module(NOVA)

REQ = "REQ-019a1234-5678-7abc-8def-0123456789ab"
PEND = "PEND-019a1234-5678-7abc-8def-0123456789ab"


def product_row(version: str, state: str, implemented: str, evidence: str) -> str:
    return (
        "| Requirement Key | 版本 | 状态 | 业务模块 | 需求块 | 已实现版本 | 实现依据 |\n"
        "|-----------------|------|------|----------|--------|------------|----------|\n"
        f"| {REQ} | {version} | {state} | 订单 | [创建](requirements/{REQ}_创建.md) | {implemented} | {evidence} |\n"
    )


class RequirementStatusTests(unittest.TestCase):
    def test_requirement_id_is_uuid7_and_separate_from_work_items(self) -> None:
        value = NOVA.new_requirement_id()
        self.assertRegex(
            value,
            r"^REQ-[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
        )
        self.assertFalse(NOVA.valid_work_item(value))

    def test_current_version_becomes_implemented(self) -> None:
        updated = NOVA.update_product_requirement_status(
            product_row("v1", "待实现", "无", "无"), f"{REQ}@v1", PEND
        )
        self.assertIn(f"| {REQ} | v1 | 已实现 |", updated)
        self.assertIn(f"| v1 | {PEND} |", updated)

    def test_older_reviewed_version_stays_updated(self) -> None:
        updated = NOVA.update_product_requirement_status(
            product_row("v2", "已更新", "无", "无"), f"{REQ}@v1", PEND
        )
        self.assertIn(f"| {REQ} | v2 | 已更新 |", updated)
        self.assertIn(f"| v1 | {PEND} |", updated)

    def test_blueprint_requirement_ref_is_metadata_only(self) -> None:
        blueprint = (
            "| 编号 | 优先级 | 来源 | 功能 | 设计依据 | 前置依赖 | 完成定义 | 需求引用 |\n"
            "|------|--------|------|------|----------|----------|----------|----------|\n"
            f"| {PEND} | P1 | 用户提出 | 创建 | [WP](design/a.md#wp-01) | 无 | 完成 | {REQ}@v1 |\n"
        )
        self.assertEqual(NOVA.blueprint_requirement_ref(blueprint, PEND), f"{REQ}@v1")


if __name__ == "__main__":
    unittest.main()
