#!/usr/bin/env python3
"""Black-box tests for Nova commit, selection, and Review archive contracts."""

from __future__ import annotations

import json
import importlib.util
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest import mock


SKILL_ROOT = Path(__file__).resolve().parents[1]
TOOL = SKILL_ROOT / "scripts" / "nova_review.py"
SPEC = importlib.util.spec_from_file_location("nova_review_tool", TOOL)
assert SPEC is not None and SPEC.loader is not None
NOVA_TOOL = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(NOVA_TOOL)


def message(
    work_item: str,
    change_class: str,
    design_ref: str = "none",
    policy: str = "required",
    exemption: str = "none",
    validation: str = "python3 -m unittest (pass)",
) -> str:
    return textwrap.dedent(
        f"""
        test: change {work_item}

        Nova-Schema: 1
        Work-Item: {work_item}
        Change-Class: {change_class}
        Design-Ref: {design_ref}
        Review-Policy: {policy}
        Exemption-Rule: {exemption}
        Validation: {validation}
        """
    ).strip() + "\n"


class NovaReviewTests(unittest.TestCase):
    def run_tool(self, *args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(TOOL), *args],
            cwd=cwd,
            check=False,
            capture_output=True,
            text=True,
        )

    def init_repo(self, root: Path) -> None:
        subprocess.run(["git", "init", "-q", str(root)], check=True)
        subprocess.run(["git", "-C", str(root), "config", "user.name", "Nova Test"], check=True)
        subprocess.run(
            ["git", "-C", str(root), "config", "user.email", "nova@example.invalid"],
            check=True,
        )

    def commit(self, repo: Path, relative: str, content: str, commit_message: str) -> str:
        path = repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        subprocess.run(["git", "-C", str(repo), "add", relative], check=True)
        subprocess.run(
            ["git", "-C", str(repo), "commit", "-q", "-F", "-"],
            input=commit_message,
            text=True,
            check=True,
        )
        return subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

    def validate(self, root: Path, commit_message: str, diff: str | None = None) -> subprocess.CompletedProcess[str]:
        message_path = root / "message.txt"
        message_path.write_text(commit_message, encoding="utf-8")
        args = ["validate-message", "--message-file", str(message_path)]
        if diff is not None:
            diff_path = root / "change.diff"
            diff_path.write_text(diff, encoding="utf-8")
            args.extend(("--diff-file", str(diff_path)))
        return self.run_tool(*args)

    def add_review_evidence(self, repo: Path, manifest: dict[str, object]) -> None:
        repositories = NOVA_TOOL.manifest_repositories(repo, manifest)
        reviewed_diffs: dict[tuple[str, str], str] = {}
        for item in manifest["items"]:
            assert isinstance(item, dict)
            refs = NOVA_TOOL.normalize_commit_refs(
                item["commits"], repositories, str(item["work_item"])
            )
            for ref in refs:
                alias = ref["repository"]
                commit_hash = ref["commit"]
                reviewed_diffs[(alias, commit_hash)] = NOVA_TOOL.run_git(
                    repositories[alias],
                    "show",
                    "--format=",
                    "--binary",
                    "--no-ext-diff",
                    commit_hash,
                )
        digest, scope = NOVA_TOOL.compute_review_evidence(reviewed_diffs)
        manifest["review_round"] = 1
        manifest["review_content_sha256"] = digest
        manifest["review_scope"] = scope

    def commit_audit(self, repo: Path, manifest: dict[str, object]) -> str:
        reviewed_at = NOVA_TOOL.parse_reviewed_at(manifest["reviewed_at"], "reviewed_at")
        batch_id = str(manifest["batch_id"])
        paths = {
            str(
                NOVA_TOOL.review_path_for_values(repo, reviewed_at, batch_id).relative_to(repo)
            ),
            str(NOVA_TOOL.feature_path(repo, reviewed_at).relative_to(repo)),
        }
        for item in manifest["items"]:
            assert isinstance(item, dict)
            paths.add(str(NOVA_TOOL.feature_index_path(repo, item["work_item"]).relative_to(repo)))
            if item["change_class"] == "designed":
                paths.add("PROJECT_BLUEPRINT.md")
                paths.add(str(item["design_file"]))
        subprocess.run(["git", "-C", str(repo), "add", "--", *sorted(paths)], check=True)
        digest = NOVA_TOOL.hashlib.sha256(NOVA_TOOL.canonical_manifest(manifest)).hexdigest()
        audit_message = textwrap.dedent(
            f"""
            audit: record {batch_id}

            Nova-Audit-Schema: 1
            Review-Batch: {batch_id}
            Manifest-SHA256: {digest}
            Validation: nova-review audit validation (pass)
            """
        ).strip() + "\n"
        diff = NOVA_TOOL.run_git(repo, "diff", "--cached", "--binary", "--no-ext-diff")
        _, errors = NOVA_TOOL.validate_audit_message(repo, audit_message, diff)
        self.assertEqual(errors, [])
        subprocess.run(
            ["git", "-C", str(repo), "commit", "-q", "-F", "-"],
            input=audit_message,
            text=True,
            check=True,
        )
        return NOVA_TOOL.run_git(repo, "rev-parse", "HEAD").strip()

    def record_fix_pass(
        self,
        repo: Path,
        work_item: str,
        commit_hash: str,
        suffix: str,
        commit_audit: bool = True,
    ) -> Path:
        manifest = {
            "schema": 1,
            "batch_id": f"NR-20260827-{suffix}",
            "reviewed_at": "2026-08-27T12:00:00+08:00",
            "reviewer": "review-agent",
            "conclusion": "PASS",
            "items": [
                {
                    "work_item": work_item,
                    "change_class": "adhoc",
                    "commits": [commit_hash],
                    "validation": "python3 -m unittest (pass)",
                    "design_ref": "none",
                }
            ],
        }
        self.add_review_evidence(repo, manifest)
        manifest_path = repo / f"review-{suffix}.json"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        result = self.run_tool(
            "record-pass", "--repo", str(repo), "--manifest", str(manifest_path)
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        if commit_audit:
            self.commit_audit(repo, manifest)
        return manifest_path

    def test_valid_classes_and_objective_exemptions(self) -> None:
        doc_diff = textwrap.dedent(
            """
            diff --git a/docs/a.md b/docs/a.md
            --- a/docs/a.md
            +++ b/docs/a.md
            @@ -1 +1 @@
            -old
            +new
            """
        )
        format_diff = textwrap.dedent(
            """
            diff --git a/app.py b/app.py
            --- a/app.py
            +++ b/app.py
            @@ -1 +1 @@
            -value=1
            +value = 1
            """
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cases = (
                (message("PEND-001", "designed", "docs/design/2026-08-27_x.md#wp-01-x"), None),
                (message("FIX-001", "adhoc"), None),
                (message("MAINT-001", "maintenance"), None),
                (message("MAINT-002", "maintenance", policy="exempt", exemption="EX-DOC"), doc_diff),
                (message("MAINT-003", "maintenance", policy="exempt", exemption="EX-FORMAT"), format_diff),
            )
            for commit_message, diff in cases:
                with self.subTest(commit_message=commit_message.splitlines()[0]):
                    result = self.validate(root, commit_message, diff)
                    self.assertEqual(result.returncode, 0, result.stderr)

    def test_ex_doc_rejects_semantic_paths_deletes_renames_and_symlinks(self) -> None:
        cases = {
            "test directory": "diff --git a/tests/readme.md b/tests/readme.md\n--- a/tests/readme.md\n+++ b/tests/readme.md\n@@ -1 +1 @@\n-a\n+b\n",
            "requirements": "diff --git a/requirements-dev.txt b/requirements-dev.txt\n--- a/requirements-dev.txt\n+++ b/requirements-dev.txt\n@@ -1 +1 @@\n-a\n+b\n",
            "delete runtime": "diff --git a/app.py b/app.py\ndeleted file mode 100644\n--- a/app.py\n+++ /dev/null\n@@ -1 +0,0 @@\n-a\n",
            "rename runtime": "diff --git a/app.py b/docs/app.md\nsimilarity index 100%\nrename from app.py\nrename to docs/app.md\n",
            "symlink": "diff --git a/docs/link.md b/docs/link.md\nnew file mode 120000\n--- /dev/null\n+++ b/docs/link.md\n@@ -0,0 +1 @@\n+../../outside\n",
            "gitlink": "diff --git a/docs/vendor.md b/docs/vendor.md\nnew file mode 160000\nindex 0000000..1234567\n--- /dev/null\n+++ b/docs/vendor.md\n@@ -0,0 +1 @@\n+Subproject commit 1234567890123456789012345678901234567890\n",
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            commit_message = message(
                "MAINT-001", "maintenance", policy="exempt", exemption="EX-DOC"
            )
            for label, diff in cases.items():
                with self.subTest(label=label):
                    result = self.validate(root, commit_message, diff)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("EX-DOC permits only", result.stderr)

    def test_ex_format_rejects_rename_even_when_content_change_is_whitespace_only(self) -> None:
        diff = (
            "diff --git a/app.py b/app-renamed.py\n"
            "similarity index 90%\n"
            "rename from app.py\n"
            "rename to app-renamed.py\n"
            "--- a/app.py\n"
            "+++ b/app-renamed.py\n"
            "@@ -1 +1 @@\n"
            "-value=1\n"
            "+value = 1\n"
        )
        with tempfile.TemporaryDirectory() as directory:
            result = self.validate(
                Path(directory),
                message(
                    "MAINT-001",
                    "maintenance",
                    policy="exempt",
                    exemption="EX-FORMAT",
                ),
                diff,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("EX-FORMAT requires", result.stderr)

    def test_body_examples_are_not_trailers_and_failed_validation_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            valid = (
                "test: trailer examples\n\n"
                "Work-Item: PEND-999\n"
                "The line above is documentation, not commit metadata.\n\n"
                + "\n".join(message("FIX-001", "adhoc").splitlines()[2:])
                + "\n"
            )
            accepted = self.validate(root, valid)
            self.assertEqual(accepted.returncode, 0, accepted.stderr)

            rejected = self.validate(
                root, message("FIX-001", "adhoc", validation="tests (fail)")
            )
            self.assertNotEqual(rejected.returncode, 0)
            self.assertIn("Validation must end with (pass)", rejected.stderr)

    def test_invalid_or_ambiguous_metadata_fails_closed(self) -> None:
        code_diff = textwrap.dedent(
            """
            diff --git a/app.py b/app.py
            --- a/app.py
            +++ b/app.py
            @@ -1 +1 @@
            -old
            +new
            """
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cases = (
                message("PEND-001", "designed", "none"),
                message("FIX-001", "adhoc", policy="exempt", exemption="EX-DOC"),
                message("MAINT-001", "maintenance", policy="exempt", exemption="EX-DOC"),
                message("MAINT-002", "maintenance") + "Review-State: PASS\n",
                message("FIX-002", "adhoc").replace("Validation: python3 -m unittest (pass)", "Validation:"),
                message(
                    "MAINT-003",
                    "maintenance",
                    policy="exempt",
                    exemption="EX-REVIEW-RECORD",
                    validation="nova-review record-pass NR-20260827-01 (pass)",
                ),
            )
            for index, commit_message in enumerate(cases):
                with self.subTest(index=index):
                    result = self.validate(root, commit_message, code_diff)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("ERROR:", result.stderr)

    def test_missing_duplicate_and_contradictory_trailers_report_exact_errors(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            missing = message("FIX-001", "adhoc").replace("Validation: python3 -m unittest (pass)\n", "")
            duplicate = message("FIX-001", "adhoc") + "Work-Item: FIX-002\n"
            contradiction = message("PEND-001", "adhoc")
            cases = (
                (missing, "Validation must appear exactly once"),
                (duplicate, "Work-Item must appear exactly once"),
                (contradiction, "Work-Item does not match Change-Class adhoc"),
            )
            for commit_message, expected in cases:
                with self.subTest(expected=expected):
                    result = self.validate(root, commit_message)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn(expected, result.stderr)

    def test_selection_modes_use_ready_ids_and_exclude_reviewed_or_unrelated_commits(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            self.init_repo(repo)
            self.commit(repo, "base.txt", "base\n", "chore: historical unrelated\n")
            self.commit(
                repo,
                "example.txt",
                "example\n",
                "docs: show Nova trailer examples\n\n"
                "Work-Item: FIX-999\n"
                "Change-Class: adhoc\n"
                "These lines are documentation in the message body, not trailers.\n",
            )
            reviewed = self.commit(repo, "one.py", "one\n", message("FIX-001", "adhoc"))
            self.record_fix_pass(repo, "FIX-001", reviewed, "old")
            pending = self.commit(repo, "two.py", "two\n", message("FIX-002", "adhoc"))
            pending_three = self.commit(repo, "three.py", "three\n", message("FIX-003", "adhoc"))
            pending_designed = self.commit(
                repo,
                "feature.py",
                "feature\n",
                message(
                    "PEND-001",
                    "designed",
                    "docs/design/2026-08-27_feature.md#wp-01-feature",
                ),
            )
            pending_maintenance = self.commit(
                repo, "maintenance.txt", "maintained\n", message("MAINT-002", "maintenance")
            )
            self.commit(
                repo,
                "docs/note.md",
                "note\n",
                message(
                    "MAINT-001",
                    "maintenance",
                    policy="exempt",
                    exemption="EX-DOC",
                ),
            )
            current = self.run_tool(
                "select",
                "--repo",
                str(repo),
                "--mode",
                "current",
                "--session-item",
                "FIX-001",
                "--session-item",
                "FIX-002",
                "--session-item",
                "FIX-003",
                "--session-item",
                "PEND-001",
                "--session-item",
                "MAINT-002",
            )
            self.assertEqual(current.returncode, 0, current.stderr)
            current_items = json.loads(current.stdout)
            self.assertEqual(
                [item["work_item"] for item in current_items],
                ["FIX-002", "FIX-003", "MAINT-002", "PEND-001"],
            )
            self.assertEqual(current_items[0]["commits"], [pending])
            self.assertEqual(current_items[1]["commits"], [pending_three])
            self.assertEqual(current_items[2]["commits"], [pending_maintenance])
            self.assertEqual(current_items[3]["commits"], [pending_designed])

            explicit = self.run_tool(
                "select",
                "--repo",
                str(repo),
                "--mode",
                "explicit",
                "--work-item",
                "FIX-001",
                "--work-item",
                "FIX-002",
            )
            self.assertNotEqual(explicit.returncode, 0)
            self.assertIn("no unreviewed required commits for: FIX-001", explicit.stderr)

            explicit = self.run_tool(
                "select", "--repo", str(repo), "--mode", "explicit",
                "--work-item", "FIX-002",
                "--work-item", "FIX-003",
                "--work-item", "PEND-001",
                "--work-item", "MAINT-002",
            )
            self.assertEqual(explicit.returncode, 0, explicit.stderr)
            self.assertEqual(json.loads(explicit.stdout), current_items)

            all_items = self.run_tool("select", "--repo", str(repo), "--mode", "all")
            self.assertEqual(all_items.returncode, 0, all_items.stderr)
            self.assertEqual(
                [item["work_item"] for item in json.loads(all_items.stdout)],
                ["FIX-002", "FIX-003", "MAINT-002", "PEND-001"],
            )

    def designed_documents(self) -> tuple[str, str]:
        blueprint = textwrap.dedent(
            """
            # Blueprint

            ## 6. 待开发功能

            | 编号 | 优先级 | 来源 | 功能 | 设计依据 | 前置依赖 | 完成定义 |
            |------|--------|------|------|----------|----------|----------|
            | PEND-001 | P1 | 用户提出 | Nova | [WP-01](docs/design/2026-08-27_x.md#wp-01-x) | 无 | pass |
            """
        ).lstrip()
        design = textwrap.dedent(
            """
            # Design

            > 设计规范版本：3
            > 设计状态：已确认
            > 演进来源：无
            > 工作包：WP-01、WP-02

            ## 2. 工作包地图

            | 工作包 | 状态 | 交付结果 | 前置依赖 | 设计章节 |
            |--------|------|----------|----------|----------|
            | WP-01 | 待Review | result | 无 | [章节](#wp-01-x) |
            | WP-02 | 待Review | result 2 | WP-01 | [章节](#wp-02-x) |

            ### 2.1 工作项关闭映射

            | 工作项 | 工作包 |
            |--------|--------|
            | PEND-001 | WP-01、WP-02 |

            <a id="wp-01-x"></a>
            ## WP-01 Example

            <a id="wp-02-x"></a>
            ## WP-02 Example
            """
        ).lstrip()
        return blueprint, design

    def test_partial_package_list_cannot_delete_the_blueprint_item(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            self.init_repo(repo)
            blueprint, design = self.designed_documents()
            blueprint_path = repo / "PROJECT_BLUEPRINT.md"
            blueprint_path.write_text(blueprint, encoding="utf-8")
            design_path = repo / "docs/design/2026-08-27_x.md"
            design_path.parent.mkdir(parents=True)
            design_path.write_text(design, encoding="utf-8")
            subprocess.run(
                ["git", "-C", str(repo), "add", "PROJECT_BLUEPRINT.md", "docs/design/2026-08-27_x.md"],
                check=True,
            )
            subprocess.run(
                ["git", "-C", str(repo), "commit", "-q", "-F", "-"],
                input=message(
                    "PEND-001",
                    "designed",
                    "docs/design/2026-08-27_x.md#wp-01-x",
                ),
                text=True,
                check=True,
            )
            commit_hash = subprocess.run(
                ["git", "-C", str(repo), "rev-parse", "HEAD"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            manifest = {
                "schema": 1,
                "batch_id": "NR-20260827-partial",
                "reviewed_at": "2026-08-27T12:00:00+08:00",
                "reviewer": "review-agent",
                "conclusion": "PASS",
                "items": [
                    {
                        "work_item": "PEND-001",
                        "change_class": "designed",
                        "commits": [commit_hash],
                        "validation": "python3 -m unittest (pass)",
                        "design_ref": "docs/design/2026-08-27_x.md#wp-01-x",
                        "blueprint": "PROJECT_BLUEPRINT.md",
                        "design_file": "docs/design/2026-08-27_x.md",
                        "package_ids": ["WP-01"],
                    }
                ],
            }
            self.add_review_evidence(repo, manifest)
            manifest_path = repo / "review.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            for command in ("check-manifest", "record-pass"):
                result = self.run_tool(
                    command, "--repo", str(repo), "--manifest", str(manifest_path)
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("must exactly match the design closure map", result.stderr)

            self.assertEqual(blueprint_path.read_text(encoding="utf-8"), blueprint)
            self.assertEqual(design_path.read_text(encoding="utf-8"), design)
            self.assertFalse((repo / "docs/audit").exists())

    def test_design_without_closure_map_rejects_multiple_ready_packages(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            self.init_repo(repo)
            blueprint, design = self.designed_documents()
            design = design.replace(
                "### 2.1 工作项关闭映射\n\n"
                "| 工作项 | 工作包 |\n"
                "|--------|--------|\n"
                "| PEND-001 | WP-01、WP-02 |\n\n",
                "",
            )
            (repo / "PROJECT_BLUEPRINT.md").write_text(blueprint, encoding="utf-8")
            design_path = repo / "docs/design/2026-08-27_x.md"
            design_path.parent.mkdir(parents=True)
            design_path.write_text(design, encoding="utf-8")
            subprocess.run(
                ["git", "-C", str(repo), "add", "PROJECT_BLUEPRINT.md", str(design_path.relative_to(repo))],
                check=True,
            )
            subprocess.run(
                ["git", "-C", str(repo), "commit", "-q", "-F", "-"],
                input=message(
                    "PEND-001", "designed", "docs/design/2026-08-27_x.md#wp-01-x"
                ),
                text=True,
                check=True,
            )
            commit_hash = NOVA_TOOL.run_git(repo, "rev-parse", "HEAD").strip()
            manifest = {
                "schema": 1,
                "batch_id": "NR-20260827-no-map",
                "reviewed_at": "2026-08-27T12:00:00+08:00",
                "reviewer": "review-agent",
                "conclusion": "PASS",
                "items": [
                    {
                        "work_item": "PEND-001",
                        "change_class": "designed",
                        "commits": [commit_hash],
                        "validation": "tests (pass)",
                        "design_ref": "docs/design/2026-08-27_x.md#wp-01-x",
                        "blueprint": "PROJECT_BLUEPRINT.md",
                        "design_file": "docs/design/2026-08-27_x.md",
                        "package_ids": ["WP-01"],
                    }
                ],
            }
            self.add_review_evidence(repo, manifest)
            manifest_path = repo / "review.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            result = self.run_tool(
                "check-manifest", "--repo", str(repo), "--manifest", str(manifest_path)
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("must contain exactly one linked 待Review package", result.stderr)

    def test_completed_mapping_row_does_not_block_the_next_work_item(self) -> None:
        blueprint = textwrap.dedent(
            """
            | 编号 | 优先级 | 来源 | 功能 | 设计依据 | 前置依赖 | 完成定义 |
            |------|--------|------|------|----------|----------|----------|
            | PEND-002 | P1 | 用户提出 | second | [WP-02](docs/design/2026-08-27_x.md#wp-02-x) | 无 | pass |
            """
        ).lstrip()
        design = textwrap.dedent(
            """
            | 工作包 | 状态 | 交付结果 | 前置依赖 | 设计章节 |
            |--------|------|----------|----------|----------|
            | WP-01 | 已完成 | first | 无 | [章节](#wp-01-x) |
            | WP-02 | 待Review | second | 无 | [章节](#wp-02-x) |

            ### 2.1 工作项关闭映射

            | 工作项 | 工作包 |
            |--------|--------|
            | PEND-001 | WP-01 |
            | PEND-002 | WP-02 |
            """
        ).lstrip()

        self.assertEqual(
            NOVA_TOOL.authoritative_package_ids(
                blueprint,
                design,
                "docs/design/2026-08-27_x.md",
                "PEND-002",
                "wp-02-x",
            ),
            ["WP-02"],
        )

    def test_selection_rejects_malformed_nova_commits_in_scope(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            self.init_repo(repo)
            malformed = message("FIX-001", "adhoc") + "Review-Policy: required\n"
            self.commit(repo, "fix.py", "broken metadata\n", malformed)
            result = self.run_tool(
                "select", "--repo", str(repo), "--mode", "explicit",
                "--work-item", "FIX-001",
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Review-Policy must appear exactly once", result.stderr)

    def test_multi_item_pass_closes_designed_work_and_writes_partitioned_audit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            self.init_repo(repo)
            blueprint, design = self.designed_documents()
            (repo / "PROJECT_BLUEPRINT.md").write_text(blueprint, encoding="utf-8")
            design_path = repo / "docs/design/2026-08-27_x.md"
            design_path.parent.mkdir(parents=True)
            design_path.write_text(design, encoding="utf-8")
            subprocess.run(
                ["git", "-C", str(repo), "add", "PROJECT_BLUEPRINT.md", "docs/design/2026-08-27_x.md"],
                check=True,
            )
            subprocess.run(
                ["git", "-C", str(repo), "commit", "-q", "-F", "-"],
                input=message("PEND-001", "designed", "docs/design/2026-08-27_x.md#wp-01-x"),
                text=True,
                check=True,
            )
            designed_commit = subprocess.run(
                ["git", "-C", str(repo), "rev-parse", "HEAD"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            secondary = repo / "secondary-repo"
            secondary.mkdir()
            self.init_repo(secondary)
            secondary_commit = self.commit(
                secondary,
                "AGENTS.md",
                "linked governance\n",
                message(
                    "PEND-001",
                    "designed",
                    "docs/design/2026-08-27_x.md#wp-01-x",
                ),
            )
            fix_commit = self.commit(repo, "fix.py", "fixed\n", message("FIX-001", "adhoc"))

            manifest = {
                "schema": 1,
                "batch_id": "NR-20260827-01",
                "reviewed_at": "2026-08-27T12:00:00+08:00",
                "reviewer": "review-agent",
                "conclusion": "PASS",
                "repositories": {"main": ".", "codex": "secondary-repo"},
                "items": [
                    {
                        "work_item": "PEND-001",
                        "change_class": "designed",
                        "commits": [
                            {"repository": "main", "commit": designed_commit},
                            {"repository": "codex", "commit": secondary_commit},
                        ],
                        "validation": "python3 -m unittest (pass)",
                        "design_ref": "docs/design/2026-08-27_x.md#wp-01-x",
                        "blueprint": "PROJECT_BLUEPRINT.md",
                        "design_file": "docs/design/2026-08-27_x.md",
                        "package_ids": ["WP-01", "WP-02"],
                    },
                    {
                        "work_item": "FIX-001",
                        "change_class": "adhoc",
                        "commits": [fix_commit],
                        "validation": "python3 -m unittest (pass)",
                        "design_ref": "none",
                    },
                ],
            }
            self.add_review_evidence(repo, manifest)
            manifest_path = repo / "review.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            check = self.run_tool(
                "check-manifest", "--repo", str(repo), "--manifest", str(manifest_path)
            )
            self.assertEqual(check.returncode, 0, check.stderr)
            self.assertFalse((repo / "docs/audit/features/2026.jsonl").exists())
            self.assertIn("PEND-001", (repo / "PROJECT_BLUEPRINT.md").read_text(encoding="utf-8"))
            before_review = design_path.read_text(encoding="utf-8")
            self.assertIn("| WP-01 | 待Review |", before_review)
            self.assertIn("| WP-02 | 待Review |", before_review)

            record = self.run_tool(
                "record-pass", "--repo", str(repo), "--manifest", str(manifest_path)
            )
            self.assertEqual(record.returncode, 0, record.stderr)
            self.assertNotIn("PEND-001", (repo / "PROJECT_BLUEPRINT.md").read_text(encoding="utf-8"))
            closed_design = design_path.read_text(encoding="utf-8")
            self.assertIn("设计状态：已实现", closed_design)
            self.assertIn("| WP-01 | 已完成 |", closed_design)
            self.assertIn("| WP-02 | 已完成 |", closed_design)

            archive_path = repo / "docs/audit/features/2026.jsonl"
            records = [json.loads(line) for line in archive_path.read_text(encoding="utf-8").splitlines()]
            self.assertEqual([entry["work_item"] for entry in records], ["PEND-001", "FIX-001"])
            self.assertEqual(
                [entry["repository"] for entry in records[0]["commits"]],
                ["main", "codex"],
            )
            review_path = repo / "docs/audit/reviews/2026/08/NR-20260827-01.yaml"
            self.assertTrue(review_path.is_file())
            review_record = json.loads(review_path.read_text(encoding="utf-8"))
            self.assertIn(
                "codex",
                [entry["repository"] for entry in review_record["items"][0]["commits"]],
            )
            self.assertNotIn(str(secondary.resolve()), review_path.read_text(encoding="utf-8"))

            again = self.run_tool(
                "record-pass", "--repo", str(repo), "--manifest", str(manifest_path)
            )
            self.assertEqual(again.returncode, 0, again.stderr)
            self.assertTrue(json.loads(again.stdout)["idempotent"])
            self.assertEqual(len(archive_path.read_text(encoding="utf-8").splitlines()), 2)
            self.commit_audit(repo, manifest)

            by_item = self.run_tool(
                "query", "--repo", str(repo), "--work-item", "PEND-001"
            )
            self.assertEqual(by_item.returncode, 0, by_item.stderr)
            self.assertEqual(len(json.loads(by_item.stdout)["features"]), 1)
            with mock.patch.object(
                NOVA_TOOL,
                "validate_audit_snapshot",
                wraps=NOVA_TOOL.validate_audit_snapshot,
            ) as validate_snapshot:
                cached_query = NOVA_TOOL.query(repo, None, 2026, 8)
            self.assertEqual(len(cached_query["features"]), 2)
            self.assertEqual(validate_snapshot.call_count, 1)
            by_month = self.run_tool(
                "query", "--repo", str(repo), "--year", "2026", "--month", "8"
            )
            self.assertEqual(by_month.returncode, 0, by_month.stderr)
            self.assertEqual(
                json.loads(by_month.stdout)["reviews"],
                ["docs/audit/reviews/2026/08/NR-20260827-01.yaml"],
            )

    def test_invalid_manifest_has_no_audit_or_closure_side_effects(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            self.init_repo(repo)
            blueprint, design = self.designed_documents()
            (repo / "PROJECT_BLUEPRINT.md").write_text(blueprint, encoding="utf-8")
            design_path = repo / "docs/design/2026-08-27_x.md"
            design_path.parent.mkdir(parents=True)
            design_path.write_text(design, encoding="utf-8")
            commit_hash = self.commit(repo, "fix.py", "fixed\n", message("FIX-001", "adhoc"))
            manifest = {
                "schema": 1,
                "batch_id": "NR-20260827-bad",
                "reviewed_at": "2026-08-27T12:00:00+08:00",
                "reviewer": "review-agent",
                "conclusion": "REJECT",
                "items": [
                    {
                        "work_item": "FIX-001",
                        "change_class": "adhoc",
                        "commits": [commit_hash],
                        "validation": "tests (pass)",
                        "design_ref": "none",
                    }
                ],
            }
            self.add_review_evidence(repo, manifest)
            manifest_path = repo / "review.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            result = self.run_tool(
                "record-pass", "--repo", str(repo), "--manifest", str(manifest_path)
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual((repo / "PROJECT_BLUEPRINT.md").read_text(encoding="utf-8"), blueprint)
            self.assertEqual(design_path.read_text(encoding="utf-8"), design)
            self.assertFalse((repo / "docs/audit").exists())

    def test_manifest_review_hash_and_scope_must_match_declared_commits(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            self.init_repo(repo)
            commit_hash = self.commit(repo, "fix.py", "fixed\n", message("FIX-001", "adhoc"))
            manifest = {
                "schema": 1,
                "batch_id": "NR-20260827-evidence",
                "reviewed_at": "2026-08-27T12:00:00+08:00",
                "reviewer": "review-agent",
                "conclusion": "PASS",
                "items": [
                    {
                        "work_item": "FIX-001",
                        "change_class": "adhoc",
                        "commits": [commit_hash],
                        "validation": "tests (pass)",
                        "design_ref": "none",
                    }
                ],
            }
            self.add_review_evidence(repo, manifest)
            manifest_path = repo / "review.json"

            valid_hash = manifest["review_content_sha256"]
            manifest["review_content_sha256"] = "0" * 64
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            result = self.run_tool(
                "check-manifest", "--repo", str(repo), "--manifest", str(manifest_path)
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("review_content_sha256 does not match", result.stderr)

            manifest["review_content_sha256"] = valid_hash
            manifest["review_scope"] = ["main:not-the-reviewed-path.py"]
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            result = self.run_tool(
                "check-manifest", "--repo", str(repo), "--manifest", str(manifest_path)
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("review_scope does not match", result.stderr)

    def test_uncommitted_record_edits_cannot_replace_committed_audit_truth(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            self.init_repo(repo)
            commit_hash = self.commit(repo, "fix.py", "fixed\n", message("FIX-001", "adhoc"))
            self.record_fix_pass(repo, "FIX-001", commit_hash, "strict")
            review_path = repo / "docs/audit/reviews/2026/08/NR-20260827-strict.yaml"
            review = json.loads(review_path.read_text(encoding="utf-8"))
            review["items"][0]["commits"][0]["commit"] = "0" * 40
            review_path.write_text(json.dumps(review), encoding="utf-8")
            result = self.run_tool("query", "--repo", str(repo), "--work-item", "FIX-001")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(len(json.loads(result.stdout)["features"]), 1)

            review["items"][0]["commits"][0]["commit"] = commit_hash
            review_path.write_text(json.dumps(review), encoding="utf-8")
            index_path = NOVA_TOOL.feature_index_path(repo, "FIX-001")
            index = json.loads(index_path.read_text(encoding="utf-8"))
            index["review_path"] = "docs/audit/reviews/2026/09/NR-20260827-strict.yaml"
            index_path.write_text(json.dumps(index), encoding="utf-8")
            result = self.run_tool("query", "--repo", str(repo), "--work-item", "FIX-001")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(len(json.loads(result.stdout)["features"]), 1)

    def test_self_consistent_uncommitted_audit_does_not_exclude_pending_commit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            self.init_repo(repo)
            commit_hash = self.commit(repo, "fix.py", "fixed\n", message("FIX-001", "adhoc"))
            self.record_fix_pass(repo, "FIX-001", commit_hash, "uncommitted", commit_audit=False)

            selected = self.run_tool(
                "select", "--repo", str(repo), "--mode", "explicit", "--work-item", "FIX-001"
            )
            self.assertEqual(selected.returncode, 0, selected.stderr)
            self.assertEqual(json.loads(selected.stdout)[0]["commits"], [commit_hash])

    def test_cross_year_duplicate_is_rejected_before_new_archive_write(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            self.init_repo(repo)
            commit_hash = self.commit(repo, "fix.py", "fixed\n", message("FIX-001", "adhoc"))
            old_archive = repo / "docs/audit/features/2025.jsonl"
            old_archive.parent.mkdir(parents=True)
            old_archive.write_text('{"work_item":"FIX-001"}\n', encoding="utf-8")
            manifest_path = repo / "review.json"
            manifest = {
                "schema": 1,
                "batch_id": "NR-20260827-duplicate",
                "reviewed_at": "2026-08-27T12:00:00+08:00",
                "reviewer": "review-agent",
                "conclusion": "PASS",
                "items": [
                    {
                        "work_item": "FIX-001",
                        "change_class": "adhoc",
                        "commits": [commit_hash],
                        "validation": "tests (pass)",
                        "design_ref": "none",
                    }
                ],
            }
            self.add_review_evidence(repo, manifest)
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            result = self.run_tool(
                "record-pass", "--repo", str(repo), "--manifest", str(manifest_path)
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("work item already archived: FIX-001", result.stderr)
            self.assertFalse((repo / "docs/audit/features/2026.jsonl").exists())

    def test_manifest_must_cover_every_required_commit_for_work_item(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            self.init_repo(repo)
            first = self.commit(repo, "fix.py", "one\n", message("FIX-001", "adhoc"))
            self.commit(repo, "fix.py", "two\n", message("FIX-001", "adhoc"))
            manifest_path = repo / "review.json"
            manifest = {
                "schema": 1,
                "batch_id": "NR-20260827-incomplete",
                "reviewed_at": "2026-08-27T12:00:00+08:00",
                "reviewer": "review-agent",
                "conclusion": "PASS",
                "items": [
                    {
                        "work_item": "FIX-001",
                        "change_class": "adhoc",
                        "commits": [first],
                        "validation": "tests (pass)",
                        "design_ref": "none",
                    }
                ],
            }
            self.add_review_evidence(repo, manifest)
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            result = self.run_tool(
                "check-manifest", "--repo", str(repo), "--manifest", str(manifest_path)
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("manifest commit coverage mismatch for FIX-001", result.stderr)
            self.assertFalse((repo / "docs/audit").exists())

    def test_year_and_month_queries_ignore_non_target_malformed_sentinels(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            self.init_repo(repo)
            commit_hash = self.commit(repo, "fix.py", "fixed\n", message("FIX-001", "adhoc"))
            self.record_fix_pass(repo, "FIX-001", commit_hash, "target")
            (repo / "docs/audit/features/2025.jsonl").write_text("not-json\n", encoding="utf-8")
            other_year = repo / "docs/audit/reviews/2025/09/bad.yaml"
            other_year.parent.mkdir(parents=True)
            other_year.write_text("not-json\n", encoding="utf-8")
            by_year = self.run_tool(
                "query", "--repo", str(repo), "--year", "2026"
            )
            self.assertEqual(by_year.returncode, 0, by_year.stderr)
            self.assertEqual(len(json.loads(by_year.stdout)["features"]), 1)

            sentinel = repo / "docs/audit/reviews/2026/09/bad.yaml"
            sentinel.parent.mkdir(parents=True)
            sentinel.write_text("not-json\n", encoding="utf-8")
            result = self.run_tool(
                "query", "--repo", str(repo), "--year", "2026", "--month", "8"
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            value = json.loads(result.stdout)
            self.assertEqual(len(value["features"]), 1)
            self.assertEqual(
                value["reviews"],
                ["docs/audit/reviews/2026/08/NR-20260827-target.yaml"],
            )

    def test_year_query_reads_the_head_annual_archive_once(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            self.init_repo(repo)
            first = self.commit(repo, "one.py", "one\n", message("FIX-001", "adhoc"))
            self.record_fix_pass(repo, "FIX-001", first, "year-one")
            second = self.commit(repo, "two.py", "two\n", message("FIX-002", "adhoc"))
            self.record_fix_pass(repo, "FIX-002", second, "year-two")

            original = NOVA_TOOL.git_blob
            reads: list[tuple[str, str]] = []

            def track(repo_arg: Path, revision: str, relative: str) -> bytes | None:
                reads.append((revision, relative))
                return original(repo_arg, revision, relative)

            with mock.patch.object(NOVA_TOOL, "git_blob", side_effect=track):
                result = NOVA_TOOL.query(repo, None, 2026, None)
            self.assertEqual(len(result["features"]), 2)
            self.assertEqual(
                [
                    entry
                    for entry in reads
                    if entry == ("HEAD", "docs/audit/features/2026.jsonl")
                ],
                [("HEAD", "docs/audit/features/2026.jsonl")],
            )

    def test_generated_audit_commit_message_validates_without_work_item_recursion(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            self.init_repo(repo)
            commit_hash = self.commit(repo, "fix.py", "fixed\n", message("FIX-001", "adhoc"))
            self.record_fix_pass(repo, "FIX-001", commit_hash, "audit", commit_audit=False)
            subprocess.run(
                ["git", "-C", str(repo), "add", "docs/audit"], check=True
            )
            diff = subprocess.run(
                ["git", "-C", str(repo), "diff", "--cached", "--binary", "--no-ext-diff"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout
            review = json.loads(
                (repo / "docs/audit/reviews/2026/08/NR-20260827-audit.yaml").read_text(
                    encoding="utf-8"
                )
            )
            audit_message = textwrap.dedent(
                f"""
                docs(audit): record Nova Review closure

                Nova-Audit-Schema: 1
                Review-Batch: NR-20260827-audit
                Manifest-SHA256: {review['manifest_sha256']}
                Validation: nova-review validate-audit-message (pass)
                """
            ).strip() + "\n"
            message_path = repo / "audit-message.txt"
            diff_path = repo / "audit.diff"
            message_path.write_text(audit_message, encoding="utf-8")
            diff_path.write_text(diff + "\n", encoding="utf-8")
            mismatch = self.run_tool(
                "validate-audit-message",
                "--repo", str(repo),
                "--message-file", str(message_path),
                "--diff-file", str(diff_path),
            )
            self.assertNotEqual(mismatch.returncode, 0)
            self.assertIn("exactly match the repository staged diff", mismatch.stderr)

            review_path = repo / "docs/audit/reviews/2026/08/NR-20260827-audit.yaml"
            review_path.write_text("corrupt worktree copy\n", encoding="utf-8")
            diff_path.write_text(diff, encoding="utf-8")
            result = self.run_tool(
                "validate-audit-message",
                "--repo", str(repo),
                "--message-file", str(message_path),
                "--diff-file", str(diff_path),
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertNotIn("Work-Item", audit_message)

    def test_audit_validation_rejects_noncanonical_bytes_on_an_allowed_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            self.init_repo(repo)
            commit_hash = self.commit(
                repo, "fix.py", "fixed\n", message("FIX-001", "adhoc")
            )
            self.record_fix_pass(
                repo, "FIX-001", commit_hash, "exact", commit_audit=False
            )
            review_path = repo / "docs/audit/reviews/2026/08/NR-20260827-exact.yaml"
            review = json.loads(review_path.read_text(encoding="utf-8"))
            review_path.write_text(
                json.dumps(review, ensure_ascii=False, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            subprocess.run(["git", "-C", str(repo), "add", "docs/audit"], check=True)
            diff = NOVA_TOOL.run_git(
                repo, "diff", "--cached", "--binary", "--no-ext-diff"
            )
            audit_message = textwrap.dedent(
                f"""
                docs(audit): reject noncanonical closure

                Nova-Audit-Schema: 1
                Review-Batch: NR-20260827-exact
                Manifest-SHA256: {review['manifest_sha256']}
                Validation: nova-review validate-audit-message (pass)
                """
            ).strip() + "\n"
            _, errors = NOVA_TOOL.validate_audit_message(repo, audit_message, diff)
            self.assertTrue(
                any("differs from the derived bytes" in error for error in errors),
                errors,
            )

    def test_audit_validation_rederives_authoritative_package_ids(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            self.init_repo(repo)
            blueprint, design = self.designed_documents()
            (repo / "PROJECT_BLUEPRINT.md").write_text(blueprint, encoding="utf-8")
            design_path = repo / "docs/design/2026-08-27_x.md"
            design_path.parent.mkdir(parents=True)
            design_path.write_text(design, encoding="utf-8")
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(repo),
                    "add",
                    "PROJECT_BLUEPRINT.md",
                    "docs/design/2026-08-27_x.md",
                ],
                check=True,
            )
            subprocess.run(
                ["git", "-C", str(repo), "commit", "-q", "-F", "-"],
                input=message(
                    "PEND-001",
                    "designed",
                    "docs/design/2026-08-27_x.md#wp-01-x",
                ),
                text=True,
                check=True,
            )
            commit_hash = NOVA_TOOL.run_git(repo, "rev-parse", "HEAD").strip()
            manifest = {
                "schema": 1,
                "batch_id": "NR-20260827-forged-packages",
                "reviewed_at": "2026-08-27T12:00:00+08:00",
                "reviewer": "review-agent",
                "conclusion": "PASS",
                "items": [
                    {
                        "work_item": "PEND-001",
                        "change_class": "designed",
                        "commits": [commit_hash],
                        "validation": "tests (pass)",
                        "design_ref": "docs/design/2026-08-27_x.md#wp-01-x",
                        "blueprint": "PROJECT_BLUEPRINT.md",
                        "design_file": "docs/design/2026-08-27_x.md",
                        "package_ids": ["WP-01", "WP-02"],
                    }
                ],
            }
            self.add_review_evidence(repo, manifest)
            manifest_path = repo / "review.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            result = self.run_tool(
                "record-pass", "--repo", str(repo), "--manifest", str(manifest_path)
            )
            self.assertEqual(result.returncode, 0, result.stderr)

            review_path = (
                repo
                / "docs/audit/reviews/2026/08/NR-20260827-forged-packages.yaml"
            )
            review = json.loads(review_path.read_text(encoding="utf-8"))
            review["items"][0]["package_ids"] = ["WP-01"]
            review_path.write_text(
                json.dumps(review, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            archive_path = repo / "docs/audit/features/2026.jsonl"
            feature = json.loads(archive_path.read_text(encoding="utf-8"))
            feature["package_ids"] = ["WP-01"]
            archive_path.write_text(
                json.dumps(feature, ensure_ascii=False, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            forged_design = design_path.read_text(encoding="utf-8").replace(
                "设计状态：已实现", "设计状态：已确认"
            ).replace("| WP-02 | 已完成 |", "| WP-02 | 待Review |")
            design_path.write_text(forged_design, encoding="utf-8")
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(repo),
                    "add",
                    "PROJECT_BLUEPRINT.md",
                    "docs/design/2026-08-27_x.md",
                    "docs/audit",
                ],
                check=True,
            )
            diff = NOVA_TOOL.run_git(
                repo, "diff", "--cached", "--binary", "--no-ext-diff"
            )
            audit_message = textwrap.dedent(
                f"""
                docs(audit): reject forged package subset

                Nova-Audit-Schema: 1
                Review-Batch: NR-20260827-forged-packages
                Manifest-SHA256: {review['manifest_sha256']}
                Validation: nova-review validate-audit-message (pass)
                """
            ).strip() + "\n"
            _, errors = NOVA_TOOL.validate_audit_message(repo, audit_message, diff)
            self.assertTrue(
                any("do not match the parent closure map" in error for error in errors),
                errors,
            )

    def test_atomic_writer_rejects_changed_source_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ledger.jsonl"
            path.write_bytes(b"current\n")
            with self.assertRaises(NOVA_TOOL.NovaError):
                NOVA_TOOL.atomic_write_group(
                    Path(directory), {path: (b"stale\n", b"replacement\n")}
                )
            self.assertEqual(path.read_bytes(), b"current\n")

    def test_atomic_writer_rejects_symlink_output_without_escape(self) -> None:
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as outside:
            repo = Path(directory)
            external = Path(outside) / "external.json"
            external.write_bytes(b"outside\n")
            target = repo / "ledger.json"
            target.symlink_to(external)
            with self.assertRaises(NOVA_TOOL.NovaError):
                NOVA_TOOL.atomic_write_group(repo, {target: (None, b"replacement\n")})
            self.assertEqual(external.read_bytes(), b"outside\n")
            self.assertTrue(target.is_symlink())

    def test_record_pass_rejects_symlinked_audit_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as outside:
            repo = Path(directory)
            self.init_repo(repo)
            commit_hash = self.commit(repo, "fix.py", "fixed\n", message("FIX-001", "adhoc"))
            (repo / "docs").mkdir()
            (repo / "docs/audit").symlink_to(Path(outside), target_is_directory=True)
            manifest = {
                "schema": 1,
                "batch_id": "NR-20260827-symlink",
                "reviewed_at": "2026-08-27T12:00:00+08:00",
                "reviewer": "review-agent",
                "conclusion": "PASS",
                "items": [
                    {
                        "work_item": "FIX-001",
                        "change_class": "adhoc",
                        "commits": [commit_hash],
                        "validation": "tests (pass)",
                        "design_ref": "none",
                    }
                ],
            }
            self.add_review_evidence(repo, manifest)
            manifest_path = repo / "review.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            result = self.run_tool(
                "record-pass", "--repo", str(repo), "--manifest", str(manifest_path)
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("must not traverse a symlink", result.stderr)
            self.assertEqual(list(Path(outside).iterdir()), [])

    def test_atomic_writer_detects_last_moment_race_without_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            target = repo / "ledger.json"
            target.write_bytes(b"current\n")
            original = NOVA_TOOL._rename_exchange
            raced = False

            def race(parent_fd: int, left: str, right: str) -> None:
                nonlocal raced
                if not raced:
                    raced = True
                    descriptor = NOVA_TOOL.os.open(
                        right, NOVA_TOOL.os.O_WRONLY | NOVA_TOOL.os.O_TRUNC, dir_fd=parent_fd
                    )
                    try:
                        NOVA_TOOL.os.write(descriptor, b"raced\n")
                    finally:
                        NOVA_TOOL.os.close(descriptor)
                original(parent_fd, left, right)

            with mock.patch.object(NOVA_TOOL, "_rename_exchange", side_effect=race):
                with self.assertRaises(NOVA_TOOL.NovaError):
                    NOVA_TOOL.atomic_write_group(
                        repo, {target: (b"current\n", b"replacement\n")}
                    )
            self.assertEqual(target.read_bytes(), b"raced\n")

    def test_atomic_writer_rechecks_all_validated_snapshots_before_writing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            target = repo / "target.txt"
            watched = repo / "source.txt"
            target.write_bytes(b"old target\n")
            watched.write_bytes(b"changed after validation\n")
            with self.assertRaises(NOVA_TOOL.NovaError):
                NOVA_TOOL.atomic_write_group(
                    repo,
                    {target: (b"old target\n", b"new target\n")},
                    {watched: b"validated source\n"},
                )
            self.assertEqual(target.read_bytes(), b"old target\n")

    def test_atomic_writer_rollback_does_not_overwrite_later_concurrent_content(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            first = repo / "a.txt"
            second = repo / "b.txt"
            first.write_bytes(b"a-old\n")
            second.write_bytes(b"b-old\n")
            original = NOVA_TOOL._rename_exchange
            calls = 0

            def fail_second(parent_fd: int, left: str, right: str) -> None:
                nonlocal calls
                calls += 1
                if calls == 2:
                    first.write_bytes(b"concurrent\n")
                    raise OSError("forced second replacement failure")
                original(parent_fd, left, right)

            with mock.patch.object(NOVA_TOOL, "_rename_exchange", side_effect=fail_second):
                with self.assertRaises(OSError):
                    NOVA_TOOL.atomic_write_group(
                        repo,
                        {
                            first: (b"a-old\n", b"a-new\n"),
                            second: (b"b-old\n", b"b-new\n"),
                        },
                    )
            self.assertEqual(first.read_bytes(), b"concurrent\n")
            self.assertEqual(second.read_bytes(), b"b-old\n")

    def test_atomic_writer_new_file_rollback_moves_before_checking(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            first = repo / "a.txt"
            second = repo / "b.txt"
            second.write_bytes(b"b-old\n")
            original_exchange = NOVA_TOOL._rename_exchange
            original_move = NOVA_TOOL._rename_noreplace
            exchanges = 0
            moved: list[str] = []

            def fail_second(parent_fd: int, left: str, right: str) -> None:
                nonlocal exchanges
                exchanges += 1
                if exchanges == 1:
                    first.write_bytes(b"concurrent\n")
                    raise OSError("forced second replacement failure")
                original_exchange(parent_fd, left, right)

            def track_move(parent_fd: int, left: str, right: str) -> None:
                moved.append(left)
                original_move(parent_fd, left, right)

            with mock.patch.object(
                NOVA_TOOL, "_rename_exchange", side_effect=fail_second
            ), mock.patch.object(
                NOVA_TOOL, "_rename_noreplace", side_effect=track_move
            ):
                with self.assertRaises(OSError):
                    NOVA_TOOL.atomic_write_group(
                        repo,
                        {
                            first: (None, b"a-new\n"),
                            second: (b"b-old\n", b"b-new\n"),
                        },
                    )
            self.assertGreaterEqual(len(moved), 2)
            self.assertEqual(moved[0], "a.txt")
            self.assertEqual(first.read_bytes(), b"concurrent\n")
            self.assertEqual(second.read_bytes(), b"b-old\n")

    def test_atomic_writer_existing_rollback_preserves_still_later_content(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            first = repo / "a.txt"
            second = repo / "b.txt"
            first.write_bytes(b"a-old\n")
            second.write_bytes(b"b-old\n")
            original_exchange = NOVA_TOOL._rename_exchange
            original_move = NOVA_TOOL._rename_noreplace
            exchanges = 0
            moves = 0

            def fail_second(parent_fd: int, left: str, right: str) -> None:
                nonlocal exchanges
                exchanges += 1
                if exchanges == 2:
                    first.write_bytes(b"concurrent-c\n")
                    raise OSError("forced second replacement failure")
                original_exchange(parent_fd, left, right)

            def inject_later(parent_fd: int, left: str, right: str) -> None:
                nonlocal moves
                moves += 1
                if moves == 1:
                    descriptor = NOVA_TOOL.os.open(
                        left,
                        NOVA_TOOL.os.O_WRONLY | NOVA_TOOL.os.O_TRUNC,
                        dir_fd=parent_fd,
                    )
                    try:
                        NOVA_TOOL.os.write(descriptor, b"concurrent-d\n")
                    finally:
                        NOVA_TOOL.os.close(descriptor)
                original_move(parent_fd, left, right)

            with mock.patch.object(
                NOVA_TOOL, "_rename_exchange", side_effect=fail_second
            ), mock.patch.object(
                NOVA_TOOL, "_rename_noreplace", side_effect=inject_later
            ):
                with self.assertRaises(OSError):
                    NOVA_TOOL.atomic_write_group(
                        repo,
                        {
                            first: (b"a-old\n", b"a-new\n"),
                            second: (b"b-old\n", b"b-new\n"),
                        },
                    )
            self.assertEqual(first.read_bytes(), b"concurrent-d\n")
            self.assertEqual(second.read_bytes(), b"b-old\n")
            preserved = list(repo.glob(".a.txt.nova-*-0"))
            self.assertEqual(len(preserved), 1)
            self.assertEqual(preserved[0].read_bytes(), b"concurrent-c\n")

    def test_atomic_writer_cleanup_failure_does_not_rollback_committed_group(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            target = repo / "ledger.txt"
            target.write_bytes(b"old\n")
            with mock.patch.object(
                NOVA_TOOL.os, "unlink", side_effect=OSError("cleanup failed")
            ) as unlink:
                NOVA_TOOL.atomic_write_group(
                    repo, {target: (b"old\n", b"new\n")}
                )
            self.assertGreaterEqual(unlink.call_count, 1)
            self.assertTrue(
                str(unlink.call_args_list[0].args[0]).startswith(".ledger.txt.nova-")
            )
            self.assertEqual(target.read_bytes(), b"new\n")


if __name__ == "__main__":
    unittest.main()
