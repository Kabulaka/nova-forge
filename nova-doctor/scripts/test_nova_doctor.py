#!/usr/bin/env python3
"""Behavior tests for the read-only current-project Nova doctor."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


TOOL = Path(__file__).with_name("nova_doctor.py")
WORKSPACE = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("nova_doctor_under_test", TOOL)
assert SPEC is not None and SPEC.loader is not None
DOCTOR = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = DOCTOR
SPEC.loader.exec_module(DOCTOR)


class NovaDoctorTests(unittest.TestCase):
    def run_doctor(self, cwd: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(TOOL), *arguments],
            cwd=cwd,
            check=False,
            capture_output=True,
            text=True,
        )

    def test_current_repository_passes(self) -> None:
        before = subprocess.run(
            ["git", "status", "--porcelain=v1"],
            cwd=WORKSPACE,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        result = self.run_doctor(WORKSPACE)
        after = subprocess.run(
            ["git", "status", "--porcelain=v1"],
            cwd=WORKSPACE,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(after, before, "doctor changed the current project")
        self.assertIn(f"Nova Doctor: {WORKSPACE}", result.stdout)
        self.assertIn("PASS blueprint:", result.stdout)
        self.assertIn("PASS audit:", result.stdout)
        self.assertIn("SUMMARY: PASS", result.stdout)

    def test_non_git_directory_fails_without_accepting_another_project(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = self.run_doctor(Path(directory))
        self.assertEqual(result.returncode, 1)
        self.assertIn("FAIL project-root:", result.stdout)
        self.assertIn("SUMMARY: FAIL", result.stdout)

    def test_missing_nova_layout_and_blueprint_fail(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            result = self.run_doctor(root)
        self.assertEqual(result.returncode, 1)
        self.assertIn("FAIL nova-layout: missing .nova directory", result.stdout)
        self.assertIn("FAIL blueprint: missing .nova/PROJECT_BLUEPRINT.md", result.stdout)

    def test_migration_change_detection_distinguishes_empty_plan(self) -> None:
        empty = """Moves:\n  none\nReference rewrites:\n  none\nConflicts: none\n"""
        changed = """Moves:\n  PROJECT_BLUEPRINT.md -> .nova/PROJECT_BLUEPRINT.md\nReference rewrites:\n  none\nConflicts: none\n"""
        self.assertFalse(DOCTOR.migration_changes(empty))
        self.assertTrue(DOCTOR.migration_changes(changed))

    def test_markdown_link_check_ignores_examples_but_rejects_real_breakage(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            nova = root / ".nova"
            nova.mkdir()
            document = nova / "PROJECT_BLUEPRINT.md"
            document.write_text(
                "```markdown\n[example](missing-example.md)\n```\n",
                encoding="utf-8",
            )
            self.assertEqual(DOCTOR.check_local_links(root).status, "PASS")
            document.write_text(
                document.read_text(encoding="utf-8") + "[broken](missing-real.md)\n",
                encoding="utf-8",
            )
            result = DOCTOR.check_local_links(root)
            self.assertEqual(result.status, "FAIL")
            self.assertIn("missing-real.md", result.details[0])

    def test_cli_rejects_another_project_path(self) -> None:
        result = self.run_doctor(WORKSPACE, "--project", "/tmp/other")
        self.assertEqual(result.returncode, 2)
        self.assertIn("unrecognized arguments", result.stderr)


if __name__ == "__main__":
    unittest.main()
