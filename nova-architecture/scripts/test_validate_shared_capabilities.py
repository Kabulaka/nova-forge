#!/usr/bin/env python3
"""Tests for validate_shared_capabilities.py."""

from __future__ import annotations

import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path


VALIDATOR = Path(__file__).with_name("validate_shared_capabilities.py")


class SharedCapabilityValidatorTests(unittest.TestCase):
    def make_repo(self, body: str | None = None) -> tuple[tempfile.TemporaryDirectory[str], Path]:
        temp = tempfile.TemporaryDirectory()
        root = Path(temp.name)
        (root / ".nova").mkdir()
        (root / "src/shared").mkdir(parents=True)
        (root / "src/shared/database.py").write_text("# shared database\n", encoding="utf-8")
        catalog = root / ".nova/SHARED_CAPABILITIES.md"
        catalog.write_text(body or self.valid_catalog(), encoding="utf-8")
        return temp, catalog

    @staticmethod
    def valid_catalog() -> str:
        return textwrap.dedent(
            """\
            # Example — 共享能力目录

            > 共享能力目录版本：1
            > 目录定位：仅登记已实现且通过最低验收的共享能力。

            ## 1. 已实现能力

            | 类型 | 能力 | 说明 | 代码位置 | 复用边界 |
            |------|------|------|----------|----------|
            | 数据访问 | SQLite 基础设施 | 统一连接和事务 | `src/shared/database.py` | 模块 Repository 复用，不包含业务查询 |
            """
        )

    def run_validator(
        self, catalog: str | Path, *options: str
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(VALIDATOR), *options, str(catalog)],
            check=False,
            capture_output=True,
            text=True,
        )

    def test_accepts_implemented_capability_with_existing_repo_path(self) -> None:
        temp, catalog = self.make_repo()
        self.addCleanup(temp.cleanup)
        result = self.run_validator(catalog)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("OK: shared capability catalog is valid", result.stdout)

    def test_rejects_missing_code_location(self) -> None:
        temp, catalog = self.make_repo(
            self.valid_catalog().replace("src/shared/database.py", "src/shared/missing.py")
        )
        self.addCleanup(temp.cleanup)
        result = self.run_validator(catalog)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("code location does not exist", result.stdout)

    def test_rejects_duplicate_capability_names(self) -> None:
        body = self.valid_catalog() + (
            "| 后端能力 | SQLite 基础设施 | 另一说明 | `src/shared/database.py` | 另一边界 |\n"
        )
        temp, catalog = self.make_repo(body)
        self.addCleanup(temp.cleanup)
        result = self.run_validator(catalog)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("duplicate shared capability", result.stdout)

    def test_rejects_casefold_duplicate_capability_names(self) -> None:
        body = self.valid_catalog() + (
            "| 后端能力 | sqlite 基础设施 | 另一说明 | `src/shared/database.py` | 另一边界 |\n"
        )
        temp, catalog = self.make_repo(body)
        self.addCleanup(temp.cleanup)
        result = self.run_validator(catalog)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("duplicate shared capability", result.stdout)

    def test_rejects_escape_and_governance_paths(self) -> None:
        for location in ("../outside.py", ".nova/PROJECT_BLUEPRINT.md", "."):
            with self.subTest(location=location):
                temp, catalog = self.make_repo(
                    self.valid_catalog().replace("src/shared/database.py", location)
                )
                self.addCleanup(temp.cleanup)
                result = self.run_validator(catalog)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("invalid shared capability code location", result.stdout)

    def test_rejects_placeholders_and_empty_catalog(self) -> None:
        placeholder = self.valid_catalog().replace("SQLite 基础设施", "<能力>")
        temp, catalog = self.make_repo(placeholder)
        self.addCleanup(temp.cleanup)
        result = self.run_validator(catalog)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("contains placeholders", result.stdout)

        empty = self.valid_catalog().split("| 数据访问", 1)[0]
        temp2, catalog2 = self.make_repo(empty)
        self.addCleanup(temp2.cleanup)
        result2 = self.run_validator(catalog2)
        self.assertNotEqual(result2.returncode, 0)
        self.assertIn("at least one implemented capability", result2.stdout)

    def test_rejects_noncanonical_catalog_path(self) -> None:
        temp, catalog = self.make_repo()
        self.addCleanup(temp.cleanup)
        other = catalog.parent / "CAPABILITIES.md"
        catalog.rename(other)
        result = self.run_validator(other)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("path must be .nova/SHARED_CAPABILITIES.md", result.stdout)

    def test_rejects_catalog_path_alias_and_symbolic_links(self) -> None:
        temp, catalog = self.make_repo()
        self.addCleanup(temp.cleanup)
        alias = f"{catalog.parent}/../.nova/{catalog.name}"
        result = self.run_validator(alias)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("path must be canonical", result.stdout)

        outside = catalog.parent.parent / "outside.md"
        outside.write_text(self.valid_catalog(), encoding="utf-8")
        catalog.unlink()
        catalog.symlink_to(outside)
        result = self.run_validator(catalog)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("must not be symbolic links", result.stdout)

        temp2 = tempfile.TemporaryDirectory()
        self.addCleanup(temp2.cleanup)
        root = Path(temp2.name)
        external_nova = root / "external-nova"
        external_nova.mkdir()
        (external_nova / "SHARED_CAPABILITIES.md").write_text(
            self.valid_catalog(), encoding="utf-8"
        )
        (root / ".nova").symlink_to(external_nova, target_is_directory=True)
        result = self.run_validator(root / ".nova/SHARED_CAPABILITIES.md")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("must not be symbolic links", result.stdout)

    def test_rejects_catalog_path_trailing_separators(self) -> None:
        temp, catalog = self.make_repo()
        self.addCleanup(temp.cleanup)
        for suffix in ("/", "\\"):
            with self.subTest(suffix=suffix):
                result = self.run_validator(f"{catalog}{suffix}")
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("path must be canonical", result.stdout)

    def test_rejects_noncanonical_cross_platform_code_locations(self) -> None:
        locations = (
            r"src\shared\database.py",
            "C:/outside/x.py",
            "//server/share/x.py",
            "src//shared/database.py",
            "src/./shared/database.py",
        )
        for location in locations:
            with self.subTest(location=location):
                temp, catalog = self.make_repo(
                    self.valid_catalog().replace("src/shared/database.py", location)
                )
                self.addCleanup(temp.cleanup)
                result = self.run_validator(catalog)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("invalid shared capability code location", result.stdout)
                self.assertNotIn("Traceback", result.stderr)

    def test_filesystem_path_errors_have_stable_diagnostics(self) -> None:
        temp, catalog = self.make_repo(
            self.valid_catalog().replace("src/shared/database.py", "bad\x00path.py")
        )
        self.addCleanup(temp.cleanup)
        result = self.run_validator(catalog)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("capability row line", result.stdout)
        self.assertIn("invalid shared capability code location", result.stdout)
        self.assertNotIn("Traceback", result.stderr)

        temp2, catalog2 = self.make_repo(
            self.valid_catalog().replace("src/shared/database.py", "loop")
        )
        self.addCleanup(temp2.cleanup)
        (catalog2.parent.parent / "loop").symlink_to("loop")
        result2 = self.run_validator(catalog2)
        self.assertNotEqual(result2.returncode, 0)
        self.assertIn("cannot resolve shared capability code location", result2.stdout)
        self.assertNotIn("Traceback", result2.stderr)

    def test_rejects_invalid_versions_headers_and_empty_fields(self) -> None:
        invalid_bodies = (
            (self.valid_catalog().replace("共享能力目录版本：1", "共享能力目录版本：2"), "version must be 1"),
            (self.valid_catalog() + "> 共享能力目录版本：1\n", "version must be 1"),
            (self.valid_catalog().replace("| 类型 | 能力 |", "| 类别 | 能力 |"), "requires exactly one capability table"),
        )
        for body, diagnostic in invalid_bodies:
            with self.subTest(diagnostic=diagnostic):
                temp, catalog = self.make_repo(body)
                self.addCleanup(temp.cleanup)
                result = self.run_validator(catalog)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(diagnostic, result.stdout)

        for value in (
            "数据访问",
            "SQLite 基础设施",
            "统一连接和事务",
            "src/shared/database.py",
            "模块 Repository 复用，不包含业务查询",
        ):
            with self.subTest(empty_field=value):
                temp, catalog = self.make_repo(self.valid_catalog().replace(value, ""))
                self.addCleanup(temp.cleanup)
                result = self.run_validator(catalog)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("requires all fields", result.stdout)

    def test_optional_orchestration_skips_only_a_missing_canonical_catalog(self) -> None:
        temp, catalog = self.make_repo()
        self.addCleanup(temp.cleanup)
        catalog.unlink()

        direct = self.run_validator(catalog)
        self.assertNotEqual(direct.returncode, 0)
        self.assertIn("cannot read shared capability catalog", direct.stdout)

        optional = self.run_validator(catalog, "--if-present")
        self.assertEqual(optional.returncode, 0, optional.stdout + optional.stderr)
        self.assertIn("catalog is absent; validation skipped", optional.stdout)

        catalog.write_text(
            self.valid_catalog().replace("src/shared/database.py", "missing.py"),
            encoding="utf-8",
        )
        invalid_present = self.run_validator(catalog, "--if-present")
        self.assertNotEqual(invalid_present.returncode, 0)
        self.assertIn("code location does not exist", invalid_present.stdout)


if __name__ == "__main__":
    unittest.main()
