#!/usr/bin/env python3
"""Tests for the Codex and Claude Code global rule installer."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


TOOL = Path(__file__).with_name("install_global_rules.py")
SPEC = importlib.util.spec_from_file_location("install_global_rules", TOOL)
assert SPEC is not None and SPEC.loader is not None
INSTALLER = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = INSTALLER
SPEC.loader.exec_module(INSTALLER)


class InstallerTests(unittest.TestCase):
    def fixture(self, root: Path) -> tuple[Path, Path, Path]:
        workspace = root / "workspace"
        codex_home = root / "codex-home"
        claude_home = root / "claude-home"
        (workspace / "codex").mkdir(parents=True)
        (workspace / "codex/AGENTS.global.md").write_text(
            "# global\n", encoding="utf-8"
        )
        for name in INSTALLER.SKILL_NAMES:
            (workspace / name).mkdir()
            (workspace / name / "SKILL.md").write_text(
                f"---\nname: {name}\ndescription: test\n---\n",
                encoding="utf-8",
            )
        return workspace, codex_home, claude_home

    def run_installer(
        self, workspace: Path, codex_home: Path, claude_home: Path
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(TOOL),
                "--workspace",
                str(workspace),
                "--codex-home",
                str(codex_home),
                "--claude-home",
                str(claude_home),
            ],
            check=False,
            capture_output=True,
            text=True,
        )

    def assert_installed(
        self, workspace: Path, codex_home: Path, claude_home: Path
    ) -> None:
        source = (workspace / "codex/AGENTS.global.md").resolve()
        self.assertEqual((codex_home / "AGENTS.md").resolve(), source)
        self.assertEqual((claude_home / "CLAUDE.md").resolve(), source)
        for name in INSTALLER.SKILL_NAMES:
            expected = (workspace / name).resolve()
            self.assertEqual((codex_home / "skills" / name).resolve(), expected)
            self.assertEqual((claude_home / "skills" / name).resolve(), expected)

    def test_first_install_links_both_hosts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace, codex_home, claude_home = self.fixture(Path(directory))
            result = self.run_installer(workspace, codex_home, claude_home)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assert_installed(workspace, codex_home, claude_home)

    def test_reinstall_replaces_normal_and_broken_links_without_deleting_sources(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace, codex_home, claude_home = self.fixture(root)
            old_global = root / "old-global.md"
            old_skill = root / "old-skill"
            old_global.write_text("keep\n", encoding="utf-8")
            old_skill.mkdir()
            (old_skill / "marker").write_text("keep\n", encoding="utf-8")
            codex_home.mkdir()
            (codex_home / "skills").mkdir()
            (codex_home / "AGENTS.md").symlink_to(old_global)
            (codex_home / "skills/nova-review").symlink_to(old_skill)
            claude_home.mkdir()
            (claude_home / "CLAUDE.md").symlink_to(root / "missing-global.md")

            result = self.run_installer(workspace, codex_home, claude_home)

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assert_installed(workspace, codex_home, claude_home)
            self.assertEqual(old_global.read_text(encoding="utf-8"), "keep\n")
            self.assertEqual(
                (old_skill / "marker").read_text(encoding="utf-8"), "keep\n"
            )

    def test_regular_file_conflict_causes_zero_link_changes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace, codex_home, claude_home = self.fixture(root)
            old_global = root / "old-global.md"
            old_global.write_text("keep\n", encoding="utf-8")
            codex_home.mkdir()
            (codex_home / "AGENTS.md").symlink_to(old_global)
            claude_home.mkdir()
            (claude_home / "CLAUDE.md").write_text("user rules\n", encoding="utf-8")

            result = self.run_installer(workspace, codex_home, claude_home)

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("refusing to overwrite file", result.stderr)
            self.assertEqual((codex_home / "AGENTS.md").readlink(), old_global)
            self.assertEqual(
                (claude_home / "CLAUDE.md").read_text(encoding="utf-8"),
                "user rules\n",
            )
            self.assertFalse((codex_home / "skills").exists())

    def test_real_directory_conflict_causes_zero_link_changes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace, codex_home, claude_home = self.fixture(root)
            old_global = root / "old-global.md"
            old_global.write_text("keep\n", encoding="utf-8")
            codex_home.mkdir()
            (codex_home / "AGENTS.md").symlink_to(old_global)
            (claude_home / "skills/nova-review").mkdir(parents=True)

            result = self.run_installer(workspace, codex_home, claude_home)

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("refusing to overwrite directory", result.stderr)
            self.assertEqual((codex_home / "AGENTS.md").readlink(), old_global)
            self.assertTrue((claude_home / "skills/nova-review").is_dir())

    def test_unexpected_failure_restores_changed_link(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace, codex_home, claude_home = self.fixture(root)
            old_global = root / "old-global.md"
            old_global.write_text("keep\n", encoding="utf-8")
            codex_home.mkdir()
            (codex_home / "AGENTS.md").symlink_to(old_global)
            failing_target = claude_home / "CLAUDE.md"
            original_symlink_to = Path.symlink_to

            def flaky_symlink_to(
                path: Path, target: Path | str, target_is_directory: bool = False
            ) -> None:
                if path == failing_target:
                    raise OSError("injected failure")
                original_symlink_to(
                    path, target, target_is_directory=target_is_directory
                )

            with mock.patch.object(Path, "symlink_to", flaky_symlink_to):
                with self.assertRaises(INSTALLER.InstallError):
                    INSTALLER.install(workspace, codex_home, claude_home)

            self.assertEqual((codex_home / "AGENTS.md").readlink(), old_global)
            self.assertFalse(failing_target.exists())
            self.assertFalse(failing_target.is_symlink())


if __name__ == "__main__":
    unittest.main()
