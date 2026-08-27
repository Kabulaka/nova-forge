#!/usr/bin/env python3
"""Run an isolated Codex probe for default commit and manual Review routing."""

from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any


TOOL = Path(__file__).with_name("nova_review.py")
SPEC = importlib.util.spec_from_file_location("nova_review_probe_tool", TOOL)
assert SPEC is not None and SPEC.loader is not None
NOVA_TOOL = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(NOVA_TOOL)

ORDINARY_PROMPT = (
    "这是隔离 Git 行为探针。把 value.txt 从 old 改为 new，并运行足以证明内容为 new 的最低验证。"
    "这是既有契约内的小修复，编号固定为 FIX-001。完成实际操作，不要只解释。"
)
EXPLICIT_REVIEW_PROMPT = (
    "现在明确开始 Review FIX-001，但本探针只验证范围选择：使用 nova-review 的 explicit select 查询候选，"
    "不要启动审查子代理，不要修改文件，不要提交。完成实际查询并报告候选。"
)


class ProbeError(RuntimeError):
    """A failed observable runtime assertion."""


def run(command: list[str], cwd: Path, input_text: str | None = None) -> str:
    result = subprocess.run(
        command,
        cwd=cwd,
        input=input_text,
        check=False,
        capture_output=True,
        text=True,
        timeout=300,
    )
    if result.returncode:
        raise ProbeError(result.stderr.strip() or result.stdout.strip())
    return result.stdout


def event_values(transcript: str, keys: set[str]) -> list[str]:
    values: list[str] = []

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            for key, nested in value.items():
                if key in keys and isinstance(nested, str):
                    values.append(nested)
                visit(nested)
        elif isinstance(value, list):
            for nested in value:
                visit(nested)

    for line in transcript.splitlines():
        try:
            visit(json.loads(line))
        except json.JSONDecodeError:
            continue
    return values


def event_strings(transcript: str) -> list[str]:
    values: list[str] = []

    def visit(value: Any) -> None:
        if isinstance(value, str):
            values.append(value)
        elif isinstance(value, dict):
            for nested in value.values():
                visit(nested)
        elif isinstance(value, list):
            for nested in value:
                visit(nested)

    for line in transcript.splitlines():
        try:
            visit(json.loads(line))
        except json.JSONDecodeError:
            continue
    return values


def review_invocations(transcript: str) -> list[str]:
    forbidden: list[str] = []
    for value in event_strings(transcript):
        lowered = value.lower()
        if (
            "spawn_agent" in lowered
            or "collaboration" in lowered
            or "collab_tool" in lowered
            or ("nova_review.py" in lowered and "select" in lowered)
        ):
            forbidden.append(value)
    return forbidden


def codex_exec(codex: str, repo: Path, prompt: str) -> str:
    return run(
        [
            codex,
            "-a",
            "never",
            "exec",
            "-s",
            "danger-full-access",
            "-C",
            str(repo),
            "--ephemeral",
            "--json",
            "-c",
            'model_reasoning_effort="low"',
            prompt,
        ],
        repo,
    )


def assert_default_commit(repo: Path, transcript: str, baseline: str) -> str:
    head = run(["git", "rev-parse", "HEAD"], repo).strip()
    if head == baseline:
        status = run(["git", "status", "--porcelain"], repo).strip() or "<clean>"
        messages = event_values(transcript, {"text", "message"})[-4:]
        commands = event_values(transcript, {"command"})[-8:]
        raise ProbeError(
            "ordinary implementation did not create a local commit; "
            f"status={status!r}; commands={commands!r}; messages={messages!r}"
        )
    if run(["git", "status", "--porcelain"], repo).strip():
        raise ProbeError("ordinary implementation did not leave a clean worktree")
    if (repo / "value.txt").read_text(encoding="utf-8") != "new\n":
        raise ProbeError("ordinary implementation did not produce the requested result")
    message = run(["git", "show", "-s", "--format=%B", head], repo)
    diff = run(["git", "show", "--format=", "--no-ext-diff", head], repo)
    metadata, errors = NOVA_TOOL.validate_message(message, diff)
    if errors:
        raise ProbeError("ordinary commit has invalid Nova trailers: " + "; ".join(errors))
    if metadata.get("Work-Item") != "FIX-001":
        raise ProbeError("ordinary commit did not preserve FIX-001 identity")
    forbidden = review_invocations(transcript)
    if forbidden:
        raise ProbeError(f"ordinary implementation entered Review: {forbidden}")
    return head


def assert_explicit_selection(repo: Path, transcript: str, expected_head: str) -> None:
    if run(["git", "rev-parse", "HEAD"], repo).strip() != expected_head:
        raise ProbeError("Review selection unexpectedly created a commit")
    if run(["git", "status", "--porcelain"], repo).strip():
        raise ProbeError("Review selection unexpectedly changed the worktree")
    commands = event_values(transcript, {"command"})
    if not any("nova_review.py" in command and "select" in command for command in commands):
        raise ProbeError("explicit Review did not enter nova-review selection")
    if "FIX-001" not in transcript:
        raise ProbeError("explicit Review did not select FIX-001")


def probe(codex: str) -> None:
    with tempfile.TemporaryDirectory(prefix="nova-flow-probe-") as directory:
        repo = Path(directory)
        run(["git", "init", "-q"], repo)
        run(["git", "config", "user.name", "Nova Probe"], repo)
        run(["git", "config", "user.email", "nova-probe@example.invalid"], repo)
        (repo / "value.txt").write_text("old\n", encoding="utf-8")
        run(["git", "add", "value.txt"], repo)
        run(["git", "commit", "-q", "-m", "test: baseline"], repo)
        baseline = run(["git", "rev-parse", "HEAD"], repo).strip()

        ordinary = codex_exec(codex, repo, ORDINARY_PROMPT)
        head = assert_default_commit(repo, ordinary, baseline)

        explicit = codex_exec(codex, repo, EXPLICIT_REVIEW_PROMPT)
        assert_explicit_selection(repo, explicit, head)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--codex", default=shutil.which("codex"))
    args = parser.parse_args()
    if not args.codex:
        print("ERROR: codex executable not found")
        return 1
    try:
        probe(args.codex)
    except (ProbeError, OSError, subprocess.SubprocessError) as exc:
        print(f"ERROR: {exc}")
        return 1
    print("PASS: ordinary implementation committed without Review; explicit Review entered selection")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
