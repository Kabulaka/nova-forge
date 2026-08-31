#!/usr/bin/env python3

from __future__ import annotations

import importlib.util
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SCRIPT = Path(__file__).with_name("migrate_nova_layout.py")
SPEC = importlib.util.spec_from_file_location("nova_layout_migration_test", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MIGRATION = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MIGRATION
SPEC.loader.exec_module(MIGRATION)


def git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


class LayoutMigrationTests(unittest.TestCase):
    def make_repo(self) -> tuple[Path, Path]:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        repo = Path(temporary.name) / "repo"
        repo.mkdir()
        external = Path(temporary.name) / "external.txt"
        external.write_text("docs/design/outside.md\n", encoding="utf-8")
        git(repo, "init", "-q")
        git(repo, "config", "user.name", "Nova Test")
        git(repo, "config", "user.email", "nova@example.invalid")
        (repo / "docs/design").mkdir(parents=True)
        (repo / "PROJECT_BLUEPRINT.md").write_text(
            "[需求](PRODUCT_REQUIREMENTS.md)\n[WP](docs/design/active.md#wp-01)\n",
            encoding="utf-8",
        )
        (repo / "PRODUCT_REQUIREMENTS.md").write_text(
            "[蓝图](PROJECT_BLUEPRINT.md)\n", encoding="utf-8"
        )
        (repo / "docs/design/active.md").write_text(
            "> 设计状态：已确认\n> Design-Ref：docs/design/active.md#wp-01\n",
            encoding="utf-8",
        )
        (repo / "docs/design/terminal.md").write_text(
            "> 设计状态：已实现\nhistorical docs/design/ text\n",
            encoding="utf-8",
        )
        (repo / "tool.py").write_text('PATH = "docs/design/active.md"\n', encoding="utf-8")
        (repo / "external-link").symlink_to(external)
        git(repo, "add", ".")
        git(repo, "commit", "-qm", "baseline")
        return repo, external

    def run_script(self, repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["python3", str(SCRIPT), "--repo", str(repo), *args],
            text=True,
            capture_output=True,
            check=False,
        )

    def approved_plan(self, repo: Path) -> tuple[str, subprocess.CompletedProcess[str]]:
        result = self.run_script(repo)
        match = re.search(r"^Plan-SHA256: ([0-9a-f]{64})$", result.stdout, re.MULTILINE)
        self.assertIsNotNone(match, result.stdout + result.stderr)
        return match.group(1), result

    def apply_approved(self, repo: Path, token: str) -> subprocess.CompletedProcess[str]:
        return self.run_script(repo, "--apply", "--plan-sha256", token)

    def test_dry_run_is_zero_write_and_exact(self) -> None:
        repo, _ = self.make_repo()
        before = subprocess.run(["git", "-C", str(repo), "status", "--porcelain"], text=True, capture_output=True, check=True).stdout
        _, result = self.approved_plan(repo)
        after = subprocess.run(["git", "-C", str(repo), "status", "--porcelain"], text=True, capture_output=True, check=True).stdout
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(before, after)
        self.assertIn("PROJECT_BLUEPRINT.md -> .nova/PROJECT_BLUEPRINT.md", result.stdout)
        self.assertIn("DRY-RUN ONLY", result.stdout)

    def test_apply_requires_exact_approved_plan_and_source_snapshot(self) -> None:
        repo, _ = self.make_repo()
        missing = self.run_script(repo, "--apply")
        self.assertNotEqual(missing.returncode, 0)
        token, _ = self.approved_plan(repo)
        blueprint = repo / "PROJECT_BLUEPRINT.md"
        blueprint.write_text(blueprint.read_text(encoding="utf-8") + "changed\n", encoding="utf-8")
        changed = self.apply_approved(repo, token)
        self.assertNotEqual(changed.returncode, 0)
        self.assertIn("approved plan mismatch", changed.stderr)
        self.assertTrue(blueprint.exists())
        self.assertFalse((repo / ".nova").exists())

    def test_mode_change_invalidates_approved_plan(self) -> None:
        repo, _ = self.make_repo()
        token, _ = self.approved_plan(repo)
        os.chmod(repo / "PROJECT_BLUEPRINT.md", 0o600)
        result = self.apply_approved(repo, token)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("approved plan mismatch", result.stderr)

    def test_apply_rewrites_active_docs_preserves_terminal_and_symlink_target(self) -> None:
        repo, external = self.make_repo()
        original_terminal = (repo / "docs/design/terminal.md").read_bytes()
        original_external = external.read_bytes()
        token, _ = self.approved_plan(repo)
        result = self.apply_approved(repo, token)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse((repo / "PROJECT_BLUEPRINT.md").exists())
        self.assertFalse((repo / "docs/design").exists())
        self.assertEqual((repo / ".nova/design/terminal.md").read_bytes(), original_terminal)
        self.assertIn(".nova/design/active.md", (repo / ".nova/design/active.md").read_text(encoding="utf-8"))
        self.assertIn("design/active.md", (repo / ".nova/PROJECT_BLUEPRINT.md").read_text(encoding="utf-8"))
        self.assertIn("[需求](PRODUCT_REQUIREMENTS.md)", (repo / ".nova/PROJECT_BLUEPRINT.md").read_text(encoding="utf-8"))
        self.assertIn("[蓝图](PROJECT_BLUEPRINT.md)", (repo / ".nova/PRODUCT_REQUIREMENTS.md").read_text(encoding="utf-8"))
        self.assertIn(".nova/design/active.md", (repo / "tool.py").read_text(encoding="utf-8"))
        self.assertEqual(external.read_bytes(), original_external)
        second_run = self.run_script(repo)
        self.assertEqual(second_run.returncode, 0, second_run.stderr)
        self.assertIn("Moves:\n  none", second_run.stdout)
        self.assertIn("Reference rewrites:\n  none", second_run.stdout)

    def test_post_validation_failure_rolls_back_and_removes_created_dirs(self) -> None:
        repo, _ = self.make_repo()
        blueprint = repo / "PROJECT_BLUEPRINT.md"
        blueprint.write_text("> 蓝图规范版本：3\ninvalid\n", encoding="utf-8")
        git(repo, "add", "PROJECT_BLUEPRINT.md")
        git(repo, "commit", "-qm", "invalid schema fixture")
        before = blueprint.read_bytes()
        token, _ = self.approved_plan(repo)
        result = self.apply_approved(repo, token)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("migration rolled back", result.stderr)
        self.assertEqual(blueprint.read_bytes(), before)
        self.assertFalse((repo / ".nova").exists())

    def test_conflict_fails_without_writes(self) -> None:
        repo, _ = self.make_repo()
        (repo / ".nova").mkdir()
        (repo / ".nova/PROJECT_BLUEPRINT.md").write_text("conflict", encoding="utf-8")
        result = self.run_script(repo)
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue((repo / "PROJECT_BLUEPRINT.md").exists())
        self.assertEqual((repo / ".nova/PROJECT_BLUEPRINT.md").read_text(), "conflict")

    def test_symlinked_target_parent_is_rejected_without_external_writes(self) -> None:
        repo, _ = self.make_repo()
        outside = repo.parent / "outside-nova"
        outside.mkdir()
        (repo / ".nova").symlink_to(outside, target_is_directory=True)
        result = self.run_script(repo)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("target parent is a symlink", result.stderr)
        self.assertEqual(list(outside.iterdir()), [])

    def test_rollback_failure_reports_actual_residue(self) -> None:
        repo, _ = self.make_repo()
        moves, rewrites = MIGRATION.plan(repo)
        original_run_git = MIGRATION.run_git

        def fail_reverse(target_repo: Path, *args: str, **kwargs: object):
            if args[:2] == ("mv", "--") and str(args[2]).startswith(".nova/"):
                raise MIGRATION.MigrationError("injected reverse failure")
            return original_run_git(target_repo, *args, **kwargs)

        with mock.patch.object(MIGRATION, "validate_documents", side_effect=MIGRATION.MigrationError("injected validation failure")):
            with mock.patch.object(MIGRATION, "run_git", side_effect=fail_reverse):
                with self.assertRaisesRegex(MIGRATION.MigrationError, "rollback incomplete.*reverse"):
                    MIGRATION.apply(repo, moves, rewrites)
        self.assertTrue((repo / ".nova/PROJECT_BLUEPRINT.md").exists())


if __name__ == "__main__":
    unittest.main()
