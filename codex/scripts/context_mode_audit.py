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
CONTEXT_TOOL_RE = re.compile(r"(?:mcp__context_mode__)?ctx_(?:batch_execute|execute|execute_file|search)\b")
BROAD_DISCOVERY_RE = re.compile(
    r"ALL_TOOLS\s*\.\s*(?:filter|map)\s*\(|ALL_TOOLS[\s\S]{0,240}?\.includes\s*\("
)
EXACT_DISCOVERY_RE = re.compile(
    r"ALL_TOOLS\s*\.\s*find\s*\([^)]*?\.name\s*={2,3}\s*['\"]([^'\"]+)['\"]"
)
FULL_FILE_CONTENT_RE = re.compile(
    r"(?:text|console\.log|print)\s*\(\s*(?:FILE_CONTENT|file_content)\s*\)"
)


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
        calls: dict[str, tuple[str, int]] = {}
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
                    arguments = _text(payload.get("arguments") or payload.get("input") or "")
                    if isinstance(call_id, str):
                        calls[call_id] = (arguments, line_number)

                    if BROAD_DISCOVERY_RE.search(arguments):
                        report.violations.append(
                            Violation(
                                "BROAD_TOOL_DISCOVERY",
                                str(path),
                                line_number,
                                "ALL_TOOLS must be queried with an exact-name find",
                            )
                        )
                    for target in EXACT_DISCOVERY_RE.findall(arguments):
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
                    if FULL_FILE_CONTENT_RE.search(arguments):
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
                    if not call or not CONTEXT_TOOL_RE.search(call[0]):
                        continue
                    output = _text(payload.get("output") or payload.get("content") or "")
                    output_bytes = len(output.encode("utf-8"))
                    output_lines = output.count("\n") + 1
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
