#!/usr/bin/env python3
"""Audit Codex JSONL sessions for bounded context-mode routing violations."""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Sequence


MAX_OUTPUT_BYTES = 4096
MAX_OUTPUT_LINES = 40

CALL_TYPES = {"function_call", "custom_tool_call"}
OUTPUT_TYPES = {"function_call_output", "custom_tool_call_output"}
CONTEXT_TOOL_NAMES = {
    "mcp__context_mode__ctx_batch_execute",
    "mcp__context_mode__ctx_execute",
    "mcp__context_mode__ctx_execute_file",
    "mcp__context_mode__ctx_search",
}
FULL_TOOL_NAME_RE = re.compile(r"[A-Za-z0-9_:-]+\Z")


@dataclass(frozen=True)
class JsToken:
    kind: str
    value: str


@dataclass(frozen=True)
class Violation:
    code: str
    path: str
    line: int
    detail: str


@dataclass
class AuditReport:
    files: int = 0
    records: int = 0
    calls: int = 0
    outputs: int = 0
    violations: list[Violation] | None = None

    def __post_init__(self) -> None:
        if self.violations is None:
            self.violations = []

    @property
    def ok(self) -> bool:
        return not self.violations

    def to_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "files": self.files,
            "records": self.records,
            "calls": self.calls,
            "outputs": self.outputs,
            "violations": [asdict(item) for item in self.violations or []],
        }


def _text(value: object) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _payload_item(record: dict[str, object]) -> tuple[str, dict[str, object]]:
    if record.get("type") != "response_item":
        return "", {}
    payload = record.get("payload")
    if not isinstance(payload, dict):
        return "", {}
    item_type = payload.get("type")
    return (item_type if isinstance(item_type, str) else ""), payload


def _js_tokens(source: str) -> list[JsToken]:
    """Tokenize the small JavaScript subset used by functions.exec cells."""
    tokens: list[JsToken] = []
    index = 0
    while index < len(source):
        char = source[index]
        if char.isspace():
            index += 1
            continue
        if source.startswith("//", index):
            newline = source.find("\n", index + 2)
            index = len(source) if newline == -1 else newline + 1
            continue
        if source.startswith("/*", index):
            end = source.find("*/", index + 2)
            index = len(source) if end == -1 else end + 2
            continue
        if char in "'\"`":
            quote = char
            index += 1
            value: list[str] = []
            while index < len(source):
                current = source[index]
                if current == "\\":
                    if index + 1 >= len(source):
                        index += 1
                        break
                    escaped = source[index + 1]
                    value.append(
                        {"n": "\n", "r": "\r", "t": "\t", "b": "\b", "f": "\f"}.get(
                            escaped, escaped
                        )
                    )
                    index += 2
                    continue
                if current == quote:
                    index += 1
                    break
                value.append(current)
                index += 1
            tokens.append(JsToken("string", "".join(value)))
            continue
        if char.isalpha() or char in "_$":
            end = index + 1
            while end < len(source) and (source[end].isalnum() or source[end] in "_$"):
                end += 1
            tokens.append(JsToken("identifier", source[index:end]))
            index = end
            continue
        operator = next(
            (candidate for candidate in ("===", "!==", "=>", "==", "!=", "&&", "||") if source.startswith(candidate, index)),
            char,
        )
        tokens.append(JsToken("operator", operator))
        index += len(operator)
    return tokens


def _matching_paren(tokens: Sequence[JsToken], open_index: int) -> int | None:
    depth = 0
    for index in range(open_index, len(tokens)):
        if tokens[index].value == "(":
            depth += 1
        elif tokens[index].value == ")":
            depth -= 1
            if depth == 0:
                return index
    return None


def _all_tools_discoveries(source: str) -> tuple[list[str], bool]:
    """Return proven exact targets and whether any ALL_TOOLS use is broad."""
    tokens = _js_tokens(source)
    targets: list[str] = []
    broad = False
    index = 0
    while index < len(tokens):
        if tokens[index] != JsToken("identifier", "ALL_TOOLS"):
            index += 1
            continue
        prefix = tokens[index : index + 4]
        if [token.value for token in prefix] != ["ALL_TOOLS", ".", "find", "("]:
            broad = True
            index += 1
            continue
        close_index = _matching_paren(tokens, index + 3)
        if close_index is None:
            broad = True
            break
        target = _exact_find_target(tokens[index + 4 : close_index])
        if target is not None:
            targets.append(target)
        else:
            broad = True
        index = close_index + 1
    return targets, broad


def _strip_wrapping_parens(tokens: list[JsToken]) -> list[JsToken]:
    while len(tokens) >= 2 and tokens[0].value == "(" and _matching_paren(tokens, 0) == len(tokens) - 1:
        tokens = tokens[1:-1]
    return tokens


def _exact_find_target(predicate: Sequence[JsToken]) -> str | None:
    values = [token.value for token in predicate]
    if values.count("=>") != 1:
        return None
    arrow = values.index("=>")
    parameters = _strip_wrapping_parens(list(predicate[:arrow]))
    body = _strip_wrapping_parens(list(predicate[arrow + 1 :]))

    direct_name: str | None = None
    object_name: str | None = None
    if len(parameters) == 1 and parameters[0].kind == "identifier":
        object_name = parameters[0].value
    elif [token.value for token in parameters] == ["{", "name", "}"]:
        direct_name = "name"
    else:
        return None

    comparison = [token.value for token in body]
    candidate: str | None = None
    if direct_name is not None and len(body) == 3:
        if body[0].value == direct_name and body[1].value in {"==", "==="} and body[2].kind == "string":
            candidate = body[2].value
        elif body[0].kind == "string" and body[1].value in {"==", "==="} and body[2].value == direct_name:
            candidate = body[0].value
    elif object_name is not None:
        member = [object_name, ".", "name"]
        bracket = [object_name, "[", "name", "]"]
        for reference in (member, bracket):
            if comparison[: len(reference)] == reference:
                tail = body[len(reference) :]
                if len(tail) == 2 and tail[0].value in {"==", "==="} and tail[1].kind == "string":
                    candidate = tail[1].value
            if comparison[-len(reference) :] == reference:
                head = body[: -len(reference)]
                if len(head) == 2 and head[0].kind == "string" and head[1].value in {"==", "==="}:
                    candidate = head[0].value
    if candidate is None or FULL_TOOL_NAME_RE.fullmatch(candidate) is None:
        return None
    return candidate


def _is_context_call(call_name: str, arguments: str) -> bool:
    if call_name in CONTEXT_TOOL_NAMES:
        return True
    tokens = _js_tokens(arguments)
    for index in range(len(tokens) - 3):
        if (
            tokens[index].value == "tools"
            and tokens[index + 1].value == "."
            and tokens[index + 2].value in CONTEXT_TOOL_NAMES
            and tokens[index + 3].value == "("
        ):
            return True
    return False


def _forwards_full_file_content(arguments: str, depth: int = 0) -> bool:
    tokens = _js_tokens(arguments)
    for index, token in enumerate(tokens):
        open_index: int | None = None
        if token.value in {"text", "print"} and index + 1 < len(tokens):
            open_index = index + 1 if tokens[index + 1].value == "(" else None
        elif (
            token.value == "console"
            and index + 3 < len(tokens)
            and [item.value for item in tokens[index + 1 : index + 4]] == [".", "log", "("]
        ):
            open_index = index + 3
        if open_index is None:
            continue
        close_index = _matching_paren(tokens, open_index)
        if close_index is None:
            continue
        sink_arguments = tokens[open_index + 1 : close_index]
        if any(
            item.kind == "identifier"
            and item.value in {"FILE_CONTENT", "file_content"}
            and (position + 1 == len(sink_arguments) or sink_arguments[position + 1].value not in {".", "[", "("})
            for position, item in enumerate(sink_arguments)
        ):
            return True
    if depth < 2:
        for token in tokens:
            if (
                token.kind == "string"
                and ("FILE_CONTENT" in token.value or "file_content" in token.value)
                and _forwards_full_file_content(token.value, depth + 1)
            ):
                return True
    return False


def _expand_paths(inputs: Sequence[Path]) -> list[Path]:
    files: set[Path] = set()
    for raw in inputs:
        path = raw.expanduser().resolve()
        if path.is_dir():
            files.update(candidate for candidate in path.rglob("*.jsonl") if candidate.is_file())
        elif path.is_file():
            files.add(path)
        else:
            raise FileNotFoundError(path)
    return sorted(files)


def audit_files(paths: Iterable[Path]) -> AuditReport:
    report = AuditReport()
    for path in paths:
        report.files += 1
        calls: dict[str, tuple[bool, int]] = {}
        discoveries: dict[str, int] = {}

        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for line_number, raw_line in enumerate(handle, 1):
                if not raw_line.strip():
                    continue
                try:
                    record = json.loads(raw_line)
                except json.JSONDecodeError as exc:
                    report.violations.append(
                        Violation("INVALID_JSON", str(path), line_number, exc.msg)
                    )
                    continue
                if not isinstance(record, dict):
                    report.violations.append(
                        Violation("INVALID_RECORD", str(path), line_number, "JSON value is not an object")
                    )
                    continue

                report.records += 1
                item_type, payload = _payload_item(record)
                if item_type in CALL_TYPES:
                    report.calls += 1
                    call_id = payload.get("call_id") or payload.get("id")
                    call_name = payload.get("name") if isinstance(payload.get("name"), str) else ""
                    arguments = _text(payload.get("arguments") or payload.get("input") or "")
                    if isinstance(call_id, str):
                        calls[call_id] = (_is_context_call(call_name, arguments), line_number)

                    exact_targets, broad_discovery = _all_tools_discoveries(arguments)
                    if broad_discovery:
                        report.violations.append(
                            Violation(
                                "BROAD_TOOL_DISCOVERY",
                                str(path),
                                line_number,
                                "ALL_TOOLS must be queried with an exact-name find",
                            )
                        )
                    for target in exact_targets:
                        first_line = discoveries.setdefault(target, line_number)
                        if first_line != line_number:
                            report.violations.append(
                                Violation(
                                    "REPEATED_TOOL_DISCOVERY",
                                    str(path),
                                    line_number,
                                    f"{target} was already discovered at line {first_line}",
                                )
                            )
                    if _forwards_full_file_content(arguments):
                        report.violations.append(
                            Violation(
                                "FULL_FILE_CONTENT_OUTPUT",
                                str(path),
                                line_number,
                                "full file content is forwarded to model context",
                            )
                        )

                elif item_type in OUTPUT_TYPES:
                    report.outputs += 1
                    call_id = payload.get("call_id")
                    call = calls.get(call_id) if isinstance(call_id, str) else None
                    if not call or not call[0]:
                        continue
                    output = _text(payload.get("output") or payload.get("content") or "")
                    output_bytes = len(output.encode("utf-8"))
                    output_lines = len(output.splitlines())
                    if output_bytes > MAX_OUTPUT_BYTES or output_lines > MAX_OUTPUT_LINES:
                        report.violations.append(
                            Violation(
                                "CONTEXT_OUTPUT_LIMIT",
                                str(path),
                                line_number,
                                f"{output_lines} lines, {output_bytes} bytes; "
                                f"limits are {MAX_OUTPUT_LINES} lines and {MAX_OUTPUT_BYTES} bytes",
                            )
                        )
    return report


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="+", type=Path, help="JSONL files or directories")
    parser.add_argument("--json", action="store_true", help="emit a machine-readable report")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        files = _expand_paths(args.paths)
    except FileNotFoundError as exc:
        print(f"ERROR: path does not exist: {exc}", file=sys.stderr)
        return 2
    if not files:
        print("ERROR: no JSONL files found", file=sys.stderr)
        return 2

    report = audit_files(files)
    if args.json:
        print(json.dumps(report.to_dict(), ensure_ascii=False, sort_keys=True))
    else:
        status = "PASS" if report.ok else "FAIL"
        print(
            f"{status}: files={report.files} records={report.records} "
            f"calls={report.calls} outputs={report.outputs} "
            f"violations={len(report.violations or [])}"
        )
        for item in report.violations or []:
            print(f"{item.code} {item.path}:{item.line} {item.detail}")
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
