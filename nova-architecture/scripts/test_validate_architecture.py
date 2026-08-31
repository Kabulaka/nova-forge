#!/usr/bin/env python3

from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = ROOT / "scripts/validate_architecture.py"
EXAMPLE_NOVA = ROOT / "references/examples/order-platform/.nova"


class ArchitectureValidatorTests(unittest.TestCase):
    def run_validator(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(["python3", str(VALIDATOR), *args], text=True, capture_output=True, check=False)

    def test_complete_parallel_example_is_ready(self) -> None:
        path = EXAMPLE_NOVA / "architecture/ARCHITECTURE_CONTRACTS.md"
        result = self.run_validator("--ready", str(path))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_pending_document_becomes_ready_from_immutable_audit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / ".nova"
            shutil.copytree(EXAMPLE_NOVA, target)
            path = target / "architecture/ARCHITECTURE_CONTRACTS.md"
            path.write_text(path.read_text(encoding="utf-8").replace("已通过", "待Review"), encoding="utf-8")
            result = self.run_validator("--ready", str(path))
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_missing_review_evidence_is_not_ready(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / ".nova"
            shutil.copytree(EXAMPLE_NOVA, target)
            path = target / "architecture/ARCHITECTURE_CONTRACTS.md"
            path.write_text(path.read_text(encoding="utf-8").replace("PEND-100", "无", 1), encoding="utf-8")
            result = self.run_validator("--ready", str(path))
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Review evidence", result.stdout)

    def test_unindexed_architecture_file_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / ".nova"
            shutil.copytree(EXAMPLE_NOVA, target)
            extra = target / "architecture/data/extra.md"
            extra.write_text("extra", encoding="utf-8")
            result = self.run_validator(str(target / "architecture/ARCHITECTURE_CONTRACTS.md"))
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("not indexed", result.stdout)

    def test_needed_gate_requires_matching_indexed_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / ".nova"
            shutil.copytree(EXAMPLE_NOVA, target)
            path = target / "architecture/ARCHITECTURE_CONTRACTS.md"
            text = path.read_text(encoding="utf-8")
            text = "\n".join(line for line in text.splitlines() if "[订单响应夹具]" not in line) + "\n"
            path.write_text(text, encoding="utf-8")
            result = self.run_validator("--ready", str(path))
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("needed gate has no indexed contract: Mock", result.stdout)

    def test_forged_review_evidence_and_state_conflict_fail(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / ".nova"
            shutil.copytree(EXAMPLE_NOVA, target)
            path = target / "architecture/ARCHITECTURE_CONTRACTS.md"
            text = path.read_text(encoding="utf-8").replace("PEND-100", "PEND-999")
            text = text.replace("[OpenAPI](api/openapi.yaml) | 已通过", "[OpenAPI](api/openapi.yaml) | 待Review")
            path.write_text(text, encoding="utf-8")
            result = self.run_validator("--ready", str(path))
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("not a trusted PASS", result.stdout)
            self.assertIn("gate state conflicts", result.stdout)

    def test_invalid_openapi_and_mock_contract_fail(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / ".nova"
            shutil.copytree(EXAMPLE_NOVA, target)
            api = target / "architecture/api/openapi.yaml"
            api.write_text(api.read_text(encoding="utf-8").replace("openapi:", "swagger:"), encoding="utf-8")
            mock = target / "architecture/mocks/order-created.json"
            mock.write_text('{"payload": {}}\n', encoding="utf-8")
            result = self.run_validator(str(target / "architecture/ARCHITECTURE_CONTRACTS.md"))
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("valid OpenAPI root", result.stdout)
            self.assertIn("_contract and _contractVersion", result.stdout)

    def test_invalid_asyncapi_and_incomplete_foundation_fail(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / ".nova"
            shutil.copytree(EXAMPLE_NOVA, target)
            index = target / "architecture/ARCHITECTURE_CONTRACTS.md"
            text = index.read_text(encoding="utf-8").replace(
                "| 事件契约 | 否 | 不适用 | 无 |", "| 事件契约 | 是 | 已通过 | PEND-100 |"
            ).replace(
                "| Mock | 订单 API |",
                "| 事件 | 订单 | [订单事件](events/order.yaml) | 已通过 | 订单模块 |\n| Mock | 订单 API |",
            )
            index.write_text(text, encoding="utf-8")
            event = target / "architecture/events/order.yaml"
            event.parent.mkdir()
            event.write_text("name: not-asyncapi\n", encoding="utf-8")
            foundation = target / "architecture/foundation/project-skeleton.md"
            foundation.write_text(
                foundation.read_text(encoding="utf-8").replace("| Python 3.13 | FastAPI |", "| Python 3.13 |  |"),
                encoding="utf-8",
            )
            result = self.run_validator("--ready", str(index))
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("valid AsyncAPI root", result.stdout)
            self.assertIn("empty table cell in 技术与运行", result.stdout)


if __name__ == "__main__":
    unittest.main()
