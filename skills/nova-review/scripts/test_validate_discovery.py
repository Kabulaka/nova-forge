#!/usr/bin/env python3
"""Black-box tests for Nova discovery link validation."""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


TOOL = Path(__file__).with_name("validate_discovery.py")


class DiscoveryTests(unittest.TestCase):
    def fixture(self, root: Path) -> tuple[Path, Path, Path]:
        workspace = root / "workspace"
        codex_home = root / "codex-home"
        claude_home = root / "claude-home"
        (workspace / "codex").mkdir(parents=True)
        (workspace / "codex/AGENTS.global.md").write_text("# global\n", encoding="utf-8")
        (codex_home / "skills").mkdir(parents=True)
        (claude_home / "skills").mkdir(parents=True)
        (codex_home / "AGENTS.md").symlink_to(workspace / "codex/AGENTS.global.md")
        (claude_home / "CLAUDE.md").symlink_to(workspace / "codex/AGENTS.global.md")
        for name in (
            "nova-requirements",
            "nova-architecture",
            "nova-development",
            "nova-doctor",
            "nova-review",
        ):
            (workspace / "skills" / name).mkdir(parents=True)
            (workspace / "skills" / name / "SKILL.md").write_text(
                f"---\nname: {name}\ndescription: test\n---\n",
                encoding="utf-8",
            )
            (codex_home / "skills" / name).symlink_to(workspace / "skills" / name)
            (claude_home / "skills" / name).symlink_to(workspace / "skills" / name)
        return workspace, codex_home, claude_home

    def run_validator(
        self, workspace: Path, codex_home: Path, claude_home: Path | None = None
    ) -> subprocess.CompletedProcess[str]:
        command = [
            sys.executable,
            str(TOOL),
            "--workspace",
            str(workspace),
            "--codex-home",
            str(codex_home),
        ]
        if claude_home is not None:
            command.extend(["--claude-home", str(claude_home)])
        return subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
        )

    def test_exact_links_pass(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace, codex_home, _ = self.fixture(Path(directory))
            result = self.run_validator(workspace, codex_home)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_exact_links_for_both_hosts_pass(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace, codex_home, claude_home = self.fixture(Path(directory))
            result = self.run_validator(workspace, codex_home, claude_home)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_regular_global_file_wrong_target_and_legacy_alias_fail(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace, codex_home, _ = self.fixture(Path(directory))
            (codex_home / "AGENTS.md").unlink()
            (codex_home / "AGENTS.md").write_text("duplicate\n", encoding="utf-8")
            (codex_home / "skills/project-brainstorming").symlink_to(
                workspace / "skills/nova-development"
            )
            result = self.run_validator(workspace, codex_home)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("global AGENTS.md must be a symlink", result.stdout)
            self.assertIn("legacy discovery entry must be absent", result.stdout)
            self.assertIn("exactly one discoverable skill entity", result.stdout)

    def test_duplicate_copy_broken_link_and_frontmatter_mismatch_fail(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace, codex_home, _ = self.fixture(Path(directory))
            duplicate = codex_home / "skills/nova-review-copy"
            duplicate.mkdir()
            (duplicate / "SKILL.md").write_text(
                "---\nname: nova-review\ndescription: duplicate\n---\n",
                encoding="utf-8",
            )
            (codex_home / "skills/broken").symlink_to(workspace / "missing")
            (workspace / "skills/nova-development/SKILL.md").write_text(
                "---\nname: wrong-name\ndescription: wrong\n---\n",
                encoding="utf-8",
            )
            result = self.run_validator(workspace, codex_home)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("nova-review must have exactly one discoverable skill entity, found 2", result.stdout)
            self.assertIn("broken skill discovery entry", result.stdout)
            self.assertIn("skill source frontmatter name mismatch", result.stdout)

    def test_global_and_standard_skill_links_with_wrong_targets_fail(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace, codex_home, _ = self.fixture(Path(directory))
            wrong_global = workspace / "codex/wrong.md"
            wrong_global.write_text("# wrong\n", encoding="utf-8")
            (codex_home / "AGENTS.md").unlink()
            (codex_home / "AGENTS.md").symlink_to(wrong_global)

            wrong_skill = workspace / "wrong-review"
            wrong_skill.mkdir()
            (wrong_skill / "SKILL.md").write_text(
                "---\nname: wrong-review\ndescription: wrong\n---\n",
                encoding="utf-8",
            )
            (codex_home / "skills/nova-review").unlink()
            (codex_home / "skills/nova-review").symlink_to(wrong_skill)

            result = self.run_validator(workspace, codex_home)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("global AGENTS.md resolves to unexpected target", result.stdout)
            self.assertIn("skill discovery entry resolves to unexpected target", result.stdout)

    def test_wrong_claude_global_and_skill_links_fail(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace, codex_home, claude_home = self.fixture(root)
            wrong_global = root / "wrong-claude.md"
            wrong_global.write_text("# wrong\n", encoding="utf-8")
            (claude_home / "CLAUDE.md").unlink()
            (claude_home / "CLAUDE.md").symlink_to(wrong_global)
            (claude_home / "skills/nova-review").unlink()
            (claude_home / "skills/nova-review").symlink_to(
                workspace / "skills/nova-doctor"
            )

            result = self.run_validator(workspace, codex_home, claude_home)

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("global CLAUDE.md resolves to unexpected target", result.stdout)
            self.assertIn("Claude Code skill discovery entry resolves", result.stdout)


if __name__ == "__main__":
    unittest.main()
