#!/usr/bin/env python3

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("migrate_nova_layout.py")


def git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


class LayoutMigrationTests(unittest.TestCase):
    def make_repo(self) -> Path:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        repo = Path(temporary.name)
        git(repo, "init", "-q")
        git(repo, "config", "user.name", "Nova Test")
        git(repo, "config", "user.email", "nova@example.invalid")
        (repo / "docs/design").mkdir(parents=True)
        (repo / "PROJECT_BLUEPRINT.md").write_text(
            "[WP](docs/design/example.md#wp-01)\n", encoding="utf-8"
        )
        (repo / "docs/design/example.md").write_text("historical docs/design/ text\n", encoding="utf-8")
        (repo / "tool.py").write_text('PATH = "docs/design/example.md"\n', encoding="utf-8")
        git(repo, "add", ".")
        git(repo, "commit", "-qm", "baseline")
        return repo

    def run_script(self, repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["python3", str(SCRIPT), "--repo", str(repo), *args],
            text=True,
            capture_output=True,
            check=False,
        )

    def test_dry_run_is_zero_write_and_exact(self) -> None:
        repo = self.make_repo()
        before = subprocess.run(["git", "-C", str(repo), "status", "--porcelain"], text=True, capture_output=True, check=True).stdout
        result = self.run_script(repo)
        after = subprocess.run(["git", "-C", str(repo), "status", "--porcelain"], text=True, capture_output=True, check=True).stdout
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(before, after)
        self.assertIn("PROJECT_BLUEPRINT.md -> .nova/PROJECT_BLUEPRINT.md", result.stdout)
        self.assertIn("DRY-RUN ONLY", result.stdout)

    def test_apply_moves_entities_and_preserves_terminal_design_bytes(self) -> None:
        repo = self.make_repo()
        original = (repo / "docs/design/example.md").read_bytes()
        result = self.run_script(repo, "--apply")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((repo / "PROJECT_BLUEPRINT.md").exists())
        self.assertFalse((repo / "docs/design").exists())
        self.assertEqual((repo / ".nova/design/example.md").read_bytes(), original)
        self.assertIn("design/example.md", (repo / ".nova/PROJECT_BLUEPRINT.md").read_text(encoding="utf-8"))
        self.assertIn(".nova/design/example.md", (repo / "tool.py").read_text(encoding="utf-8"))
        second_run = self.run_script(repo)
        self.assertEqual(second_run.returncode, 0, second_run.stderr)
        self.assertIn("Moves:\n  none", second_run.stdout)
        self.assertIn("Reference rewrites:\n  none", second_run.stdout)

    def test_conflict_fails_without_writes(self) -> None:
        repo = self.make_repo()
        (repo / ".nova").mkdir()
        (repo / ".nova/PROJECT_BLUEPRINT.md").write_text("conflict", encoding="utf-8")
        result = self.run_script(repo, "--apply")
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue((repo / "PROJECT_BLUEPRINT.md").exists())
        self.assertEqual((repo / ".nova/PROJECT_BLUEPRINT.md").read_text(), "conflict")


if __name__ == "__main__":
    unittest.main()
