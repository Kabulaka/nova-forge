#!/usr/bin/env python3
"""Tests for the context-mode JSONL session auditor."""

from __future__ import annotations

import importlib.util
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path


SCRIPT = Path(__file__).with_name("context_mode_audit.py")
SPEC = importlib.util.spec_from_file_location("context_mode_audit", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
AUDIT = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = AUDIT
SPEC.loader.exec_module(AUDIT)


def response_item(payload: dict[str, object]) -> str:
    return json.dumps({"type": "response_item", "payload": payload}, ensure_ascii=False)


def call(call_id: str, code: str) -> str:
    return response_item(
        {
            "type": "function_call",
            "name": "exec",
            "call_id": call_id,
            "arguments": code,
        }
    )


def output(call_id: str, text: str) -> str:
    return response_item(
        {
            "type": "function_call_output",
            "call_id": call_id,
            "output": text,
        }
    )


class ContextModeAuditTests(unittest.TestCase):
    def audit(self, lines: list[str]):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "session.jsonl"
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            before = path.read_bytes()
            report = AUDIT.audit_files([path])
            self.assertEqual(path.read_bytes(), before)
            return report

    def test_exact_single_discovery_and_bounded_output_pass(self) -> None:
        code = (
            'const t=ALL_TOOLS.find(x=>x.name==="mcp__context_mode__ctx_search");'
            'const r=await tools.mcp__context_mode__ctx_search({queries:["root cause"],limit:2});'
        )
        report = self.audit([call("c1", code), output("c1", "evidence\n" * 20)])
        self.assertTrue(report.ok)

    def test_broad_and_repeated_discovery_fail(self) -> None:
        broad = 'text(ALL_TOOLS.filter(x=>x.name.includes("ctx_")));'
        exact = 'text(ALL_TOOLS.find(x=>x.name==="mcp__context_mode__ctx_search"));'
        report = self.audit([call("c1", broad), call("c2", exact), call("c3", exact)])
        self.assertEqual(
            {item.code for item in report.violations},
            {"BROAD_TOOL_DISCOVERY", "REPEATED_TOOL_DISCOVERY"},
        )

    def test_line_and_utf8_byte_limits_fail(self) -> None:
        code = 'await tools.mcp__context_mode__ctx_search({queries:["evidence"],limit:2});'
        report = self.audit(
            [
                call("c1", code),
                output("c1", "x\n" * 41),
                call("c2", code),
                output("c2", "界" * 1366),
            ]
        )
        violations = [item for item in report.violations if item.code == "CONTEXT_OUTPUT_LIMIT"]
        self.assertEqual(len(violations), 2)
        self.assertIn("42 lines", violations[0].detail)
        self.assertIn("4098 bytes", violations[1].detail)

    def test_invalid_json_and_full_file_content_are_reported_without_stopping(self) -> None:
        report = self.audit(
            [
                "{not-json",
                call("c1", "console.log(FILE_CONTENT);"),
                response_item({"type": "message", "role": "assistant", "content": []}),
            ]
        )
        self.assertEqual(
            {item.code for item in report.violations},
            {"INVALID_JSON", "FULL_FILE_CONTENT_OUTPUT"},
        )
        self.assertEqual(report.records, 2)

    def test_cli_expands_directory_and_returns_nonzero_without_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "session.jsonl"
            path.write_text(
                call("c1", 'text(ALL_TOOLS.filter(x=>x.name.includes("ctx_")));') + "\n",
                encoding="utf-8",
            )
            before = path.read_bytes()
            stream = io.StringIO()
            with redirect_stdout(stream):
                exit_code = AUDIT.main([directory])
            self.assertEqual(exit_code, 1)
            self.assertIn("BROAD_TOOL_DISCOVERY", stream.getvalue())
            self.assertEqual(path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
