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

    def test_missing_review_evidence_is_not_ready(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / ".nova"
            shutil.copytree(EXAMPLE_NOVA, target)
            path = target / "architecture/ARCHITECTURE_CONTRACTS.md"
            path.write_text(path.read_text(encoding="utf-8").replace("NR-20260831-architecture-foundation", "无", 1), encoding="utf-8")
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


if __name__ == "__main__":
    unittest.main()
