#!/usr/bin/env python3
"""Run an isolated Codex probe for default commit and manual Review routing."""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import shlex
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
    "这是主动局部修改，不是既有契约偏离或缺陷，也不新增能力或公共契约；尚未创建工作项。"
    "完成实际操作，不要只解释。"
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


def completed_command_events(transcript: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for line in transcript.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict) or event.get("type") != "item.completed":
            continue
        item = event.get("item")
        if isinstance(item, dict) and item.get("type") == "command_execution":
            events.append(item)
    return events


def split_command(command: str, *, posix: bool) -> list[str]:
    try:
        tokens = shlex.split(command, posix=posix)
    except ValueError:
        return []
    if not posix:
        tokens = [
            token[1:-1]
            if len(token) >= 2 and token[0] == token[-1] and token[0] in {'"', "'"}
            else token
            for token in tokens
        ]
    return tokens


def executable_name(token: str) -> str:
    return token.replace("\\", "/").rsplit("/", 1)[-1].lower()


def is_python_executable(token: str) -> bool:
    return (
        re.fullmatch(
            r"(?:python(?:\d+(?:\.\d+)*)?|py)(?:\.exe)?",
            executable_name(token),
        )
        is not None
    )


def safe_tokens(tokens: list[str]) -> bool:
    return not any(
        token in {";", "&&", "||", "|", "&"}
        or token.startswith((">", "<"))
        or "\n" in token
        or "\r" in token
        for token in tokens
    )


def has_shell_control_syntax(command: str) -> bool:
    if any(value in command for value in ("\r", "\n", "$(", "`")):
        return True
    quote: str | None = None
    for character in command:
        if quote is not None:
            if character == quote:
                quote = None
            continue
        if character in {'"', "'"}:
            quote = character
        elif character in {";", "|", "&", ">", "<"}:
            return True
    return False


def is_nova_review_invocation(tokens: list[str]) -> bool:
    return (
        len(tokens) >= 3
        and is_python_executable(tokens[0])
        and executable_name(tokens[1]) == "nova_review.py"
        and safe_tokens(tokens)
    )


def command_tokens(command: str) -> list[str]:
    if has_shell_control_syntax(command):
        return []
    outer_variants = [
        tokens
        for tokens in (
            split_command(command, posix=True),
            split_command(command, posix=False),
        )
        if tokens
    ]
    for tokens in outer_variants:
        if is_nova_review_invocation(tokens):
            return tokens
        executable = executable_name(tokens[0])
        wrapper_flags: set[str] | None = None
        if executable in {"bash", "sh", "zsh", "bash.exe", "sh.exe", "zsh.exe"}:
            wrapper_flags = {"-c", "-lc", "-cl"}
        elif executable in {"powershell", "powershell.exe", "pwsh", "pwsh.exe"}:
            wrapper_flags = {"-command", "-c"}
        elif executable in {"cmd", "cmd.exe"}:
            wrapper_flags = {"/c"}
        if wrapper_flags is None:
            continue
        command_indexes = [
            index
            for index, token in enumerate(tokens[1:], start=1)
            if token.lower() in wrapper_flags
        ]
        if len(command_indexes) != 1 or command_indexes[0] + 2 != len(tokens):
            continue
        nested = tokens[command_indexes[0] + 1]
        if has_shell_control_syntax(nested):
            continue
        for posix in (True, False):
            inner = split_command(nested, posix=posix)
            if is_nova_review_invocation(inner):
                return inner
    return []


def nova_review_arguments(command: str) -> list[str]:
    tokens = command_tokens(command)
    if len(tokens) < 3:
        return []
    script = executable_name(tokens[1])
    if not is_python_executable(tokens[0]):
        return []
    if script != "nova_review.py":
        return []
    return tokens[2:]


def command_output(item: dict[str, Any]) -> str | None:
    for key in ("aggregated_output", "stdout"):
        value = item.get(key)
        if isinstance(value, str):
            return value
    return None


def exact_options(arguments: list[str], allowed: set[str]) -> dict[str, str] | None:
    values: dict[str, str] = {}
    index = 0
    while index < len(arguments):
        argument = arguments[index]
        if "=" in argument:
            flag, value = argument.split("=", 1)
            consumed = 1
        else:
            flag = argument
            if index + 1 >= len(arguments):
                return None
            value = arguments[index + 1]
            consumed = 2
        if flag not in allowed or flag in values or not value or value.startswith("--"):
            return None
        values[flag] = value
        index += consumed
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


def generated_patch_work_item(metadata: dict[str, str], transcript: str) -> str:
    work_item = metadata.get("Work-Item", "")
    uuid_part = work_item.removeprefix("PATCH-")
    if (
        not NOVA_TOOL.WORK_ITEM_PATTERNS["patch"].fullmatch(work_item)
        or uuid_part.isdigit()
    ):
        raise ProbeError("ordinary implementation did not create a PATCH UUIDv7 work item")
    successful_generations: list[str] = []
    for item in completed_command_events(transcript):
        if item.get("exit_code") != 0:
            continue
        arguments = nova_review_arguments(str(item.get("command", "")))
        if arguments != ["new-id", "--class", "patch"]:
            continue
        output = command_output(item)
        if output is None:
            continue
        lines = [line.strip() for line in output.splitlines() if line.strip()]
        if len(lines) == 1 and NOVA_TOOL.WORK_ITEM_PATTERNS["patch"].fullmatch(lines[0]):
            successful_generations.append(lines[0])
    if successful_generations != [work_item]:
        raise ProbeError(
            "ordinary implementation did not successfully generate and reuse the committed "
            f"PATCH work item: expected={work_item!r}; generated={successful_generations!r}"
        )
    return work_item


def explicit_review_prompt(work_item: str) -> str:
    return (
        f"现在明确开始 Review {work_item}，但本探针只验证范围选择："
        "使用 nova-review 的 explicit select 查询候选，不要启动审查子代理，不要修改文件，不要提交。"
        "完成实际查询并报告候选。"
    )


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


def assert_default_commit(repo: Path, transcript: str, baseline: str) -> tuple[str, str]:
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
    work_item = generated_patch_work_item(metadata, transcript)
    forbidden = review_invocations(transcript)
    if forbidden:
        raise ProbeError(f"ordinary implementation entered Review: {forbidden}")
    return head, work_item


def assert_explicit_selection(
    repo: Path, transcript: str, expected_head: str, work_item: str
) -> None:
    if run(["git", "rev-parse", "HEAD"], repo).strip() != expected_head:
        raise ProbeError("Review selection unexpectedly created a commit")
    if run(["git", "status", "--porcelain"], repo).strip():
        raise ProbeError("Review selection unexpectedly changed the worktree")
    verified = False
    for item in completed_command_events(transcript):
        if item.get("exit_code") != 0:
            continue
        arguments = nova_review_arguments(str(item.get("command", "")))
        if not arguments or arguments[0] != "select":
            continue
        options = exact_options(arguments[1:], {"--repo", "--mode", "--work-item"})
        if options is None or set(options) != {"--repo", "--mode", "--work-item"}:
            continue
        if options["--mode"] != "explicit" or options["--work-item"] != work_item:
            continue
        output = command_output(item)
        if output is None:
            continue
        try:
            selected = json.loads(output)
        except json.JSONDecodeError:
            continue
        if (
            isinstance(selected, list)
            and len(selected) == 1
            and isinstance(selected[0], dict)
            and selected[0].get("work_item") == work_item
        ):
            verified = True
            break
    if not verified:
        raise ProbeError(
            "explicit Review did not enter nova-review selection or did not successfully "
            f"select exactly {work_item} with explicit mode"
        )


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
        head, work_item = assert_default_commit(repo, ordinary, baseline)

        explicit = codex_exec(codex, repo, explicit_review_prompt(work_item))
        assert_explicit_selection(repo, explicit, head, work_item)


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
