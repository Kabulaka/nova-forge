#!/usr/bin/env python3
"""Behavior tests for the read-only current-project Nova doctor."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


TOOL = Path(__file__).with_name("nova_doctor.py")
WORKSPACE = Path(__file__).resolve().parents[3]
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

    def init_repo(self, root: Path) -> None:
        subprocess.run(["git", "init", "-q", str(root)], check=True)
        subprocess.run(
            ["git", "-C", str(root), "config", "user.name", "Nova Doctor Test"],
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(root), "config", "user.email", "doctor@example.invalid"],
            check=True,
        )

    def commit_file(self, root: Path, name: str, content: str, message: str) -> None:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        subprocess.run(["git", "-C", str(root), "add", name], check=True)
        subprocess.run(
            ["git", "-C", str(root), "commit", "-q", "-F", "-"],
            input=message,
            text=True,
            check=True,
        )

    def work_item_message(
        self, work_item: str, change_class: str, schema: int, subject: str
    ) -> str:
        return (
            subject
            + "\n\n"
            + f"Nova-Schema: {schema}\n"
            + f"Work-Item: {work_item}\n"
            + f"Change-Class: {change_class}\n"
            + "Design-Ref: none\n"
            + "Review-Policy: required\n"
            + "Exemption-Rule: none\n"
            + "Validation: doctor fixture (pass)\n"
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
            target = nova / "folder" / "file_(v1).md"
            target.parent.mkdir()
            target.write_text("target\n", encoding="utf-8")
            document = nova / "PROJECT_BLUEPRINT.md"
            document.write_text(
                "````markdown\n"
                "[fenced](missing-fenced.md)\n"
                "````\n"
                "    [indented](missing-indented.md)\n"
                "``[inline](missing-inline.md)``\n"
                "[balanced](folder/file_(v1).md)\n",
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

    def test_nova_symlink_cannot_escape_current_project(self) -> None:
        with (
            tempfile.TemporaryDirectory() as directory,
            tempfile.TemporaryDirectory() as external_directory,
        ):
            root = Path(directory)
            nova = root / ".nova"
            nova.mkdir()
            external = Path(external_directory) / "outside.md"
            external.write_text("EXTERNAL-SECRET\n", encoding="utf-8")
            (nova / "PROJECT_BLUEPRINT.md").symlink_to(external)
            results = DOCTOR.diagnose(root, WORKSPACE)
        self.assertEqual([result.status for result in results], ["FAIL"])
        report = " ".join(
            [result.message for result in results]
            + [detail for result in results for detail in result.details]
        )
        self.assertIn("escapes project root", report)
        self.assertNotIn("EXTERNAL-SECRET", report)

    def test_cli_rejects_another_project_path(self) -> None:
        result = self.run_doctor(WORKSPACE, "--project", "/tmp/other")
        self.assertEqual(result.returncode, 2)
        self.assertIn("unrecognized arguments", result.stderr)

    def test_validator_timeout_is_bounded_failure(self) -> None:
        with mock.patch.object(
            DOCTOR,
            "run",
            side_effect=subprocess.TimeoutExpired(["validator"], 60),
        ):
            result = DOCTOR.validator_result(
                "requirements",
                "requirements validator",
                ["validator", "document.md"],
                WORKSPACE,
            )
        self.assertEqual(result.status, "FAIL")
        self.assertEqual(result.message, "requirements validator timed out")
        self.assertEqual(result.details, ("Run: validator document.md",))

    def test_subprocess_decode_failure_is_bounded(self) -> None:
        completed = DOCTOR.run(
            [sys.executable, "-c", "import os; os.write(1, b'\\xff')"],
            WORKSPACE,
        )
        self.assertEqual(completed.stdout, "\ufffd")

        decode_error = UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid")
        with mock.patch.object(DOCTOR, "run", side_effect=decode_error):
            result = DOCTOR.validator_result(
                "requirements",
                "requirements validator",
                ["validator", "document.md"],
                WORKSPACE,
            )
        self.assertEqual(result.status, "FAIL")
        self.assertEqual(result.message, f"cannot run requirements validator: {decode_error}")
        self.assertEqual(result.details, ("Run: validator document.md",))

    def test_audit_rejects_malformed_feature_record(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            features = root / ".nova" / "audit" / "features"
            features.mkdir(parents=True)
            (features / "2026.jsonl").write_text("{broken json\n", encoding="utf-8")
            result = DOCTOR.check_audit(root, WORKSPACE)
        self.assertEqual(result.status, "FAIL")
        self.assertEqual(result.message, "audit records are inconsistent")
        self.assertTrue(result.details)

    def test_governance_history_rejects_new_pend_after_schema_2(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.init_repo(root)
            self.commit_file(
                root,
                "value.txt",
                "invalid\n",
                self.work_item_message(
                    "PEND-019a1234-5678-7abc-8def-0123456789ab",
                    "feature",
                    2,
                    "feat(delivery): 错误创建旧任务编号",
                ),
            )
            result = DOCTOR.check_governance_history(root, WORKSPACE)
        self.assertEqual(result.status, "FAIL")
        self.assertIn("commit governance violations", result.message)
        self.assertIn("Work-Item does not match", result.details[0])

    def test_governance_history_rejects_fragmented_patch_commits(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.init_repo(root)
            work_item = "PATCH-019a1234-5678-7abc-8def-0123456789ab"
            commit_message = self.work_item_message(
                work_item,
                "patch",
                2,
                "patch(delivery): 调整局部交付行为",
            )
            self.commit_file(root, "value.txt", "one\n", commit_message)
            self.commit_file(root, "value.txt", "two\n", commit_message)
            result = DOCTOR.check_governance_history(root, WORKSPACE)
        self.assertEqual(result.status, "FAIL")
        self.assertIn("allow one implementation result commit", result.details[0])

    def test_governance_history_rejects_schema_1_after_activation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.init_repo(root)
            self.commit_file(
                root,
                "new.txt",
                "schema2\n",
                self.work_item_message(
                    "PATCH-019a1234-5678-7abc-8def-0123456789ab",
                    "patch",
                    2,
                    "patch(delivery): 建立新提交协议",
                ),
            )
            self.commit_file(
                root,
                "legacy.txt",
                "schema1\n",
                self.work_item_message(
                    "MAINT-001",
                    "maintenance",
                    1,
                    "legacy maintenance",
                ),
            )
            result = DOCTOR.check_governance_history(root, WORKSPACE)
        self.assertEqual(result.status, "FAIL")
        self.assertIn("after schema 2 activation", result.details[0])

    def test_governance_history_rejects_schema_2_reuse_of_schema_1_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.init_repo(root)
            work_item = "FIX-019a1234-5678-7abc-8def-0123456789ab"
            self.commit_file(
                root,
                "legacy.txt",
                "legacy\n",
                self.work_item_message(
                    work_item,
                    "adhoc",
                    1,
                    "legacy fix",
                ),
            )
            self.commit_file(
                root,
                "new.txt",
                "new\n",
                self.work_item_message(
                    work_item,
                    "fix",
                    2,
                    "fix(delivery): 恢复既有交付行为",
                ),
            )
            result = DOCTOR.check_governance_history(root, WORKSPACE)
        self.assertEqual(result.status, "FAIL")
        self.assertIn("must not reuse a schema 1 work-item identity", result.details[0])


if __name__ == "__main__":
    unittest.main()
