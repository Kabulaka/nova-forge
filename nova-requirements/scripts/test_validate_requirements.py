#!/usr/bin/env python3

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = ROOT / "scripts/validate_requirements.py"
EXAMPLE = ROOT / "references/examples/equipment-rental/.nova"


class RequirementsValidatorTests(unittest.TestCase):
    def run_validator(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["python3", str(VALIDATOR), *args],
            text=True,
            capture_output=True,
            check=False,
        )

    def test_complete_example_passes(self) -> None:
        result = self.run_validator("--index", str(EXAMPLE / "PRODUCT_REQUIREMENTS.md"))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("PASS", result.stdout)

    def test_block_passes_independently(self) -> None:
        block = next((EXAMPLE / "requirements").glob("REQ-*.md"))
        result = self.run_validator("--block", str(block))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_inconsistent_implemented_state_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / ".nova"
            target.mkdir()
            (target / "requirements").mkdir()
            source_block = next((EXAMPLE / "requirements").glob("REQ-*.md"))
            (target / "requirements" / source_block.name).write_bytes(source_block.read_bytes())
            text = (EXAMPLE / "PRODUCT_REQUIREMENTS.md").read_text(encoding="utf-8")
            text = text.replace("| v1 | 待实现 |", "| v1 | 已实现 |")
            (target / "PRODUCT_REQUIREMENTS.md").write_text(text, encoding="utf-8")
            result = self.run_validator("--index", str(target / "PRODUCT_REQUIREMENTS.md"))
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("已实现 requires", result.stdout)


if __name__ == "__main__":
    unittest.main()
