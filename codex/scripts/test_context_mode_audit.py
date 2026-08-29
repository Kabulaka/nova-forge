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
        broad = 'text(ALL_TOOLS.find(x=>/^mcp__context_mode__ctx_/.test(x.name)));'
        exact = 'text(ALL_TOOLS.find(({name})=>name==="mcp__context_mode__ctx_search"));'
        report = self.audit([call("c1", broad), call("c2", exact), call("c3", exact)])
        self.assertEqual(
            {item.code for item in report.violations},
            {"BROAD_TOOL_DISCOVERY", "REPEATED_TOOL_DISCOVERY"},
        )

    def test_find_callback_binding_must_match_and_bracket_name_is_exact(self) -> None:
        unrelated = (
            'text(ALL_TOOLS.find(x=>y.name==="mcp__context_mode__ctx_search"));'
        )
        bracket = (
            'text(ALL_TOOLS.find(x=>x["name"]==="mcp__context_mode__ctx_search"));'
        )
        report = self.audit([call("c1", unrelated), call("c2", bracket)])
        self.assertEqual(
            [item.code for item in report.violations],
            ["BROAD_TOOL_DISCOVERY"],
        )

    def test_exact_line_and_byte_boundaries_pass(self) -> None:
        code = 'await tools.mcp__context_mode__ctx_search({queries:["evidence"],limit:2});'
        report = self.audit(
            [
                call("c1", code),
                output("c1", "x\n" * 40),
                call("c2", code),
                output("c2", "x" * 4096),
            ]
        )
        self.assertTrue(report.ok)

    def test_line_and_byte_limits_fail_above_boundary(self) -> None:
        code = 'await tools.mcp__context_mode__ctx_search({queries:["evidence"],limit:2});'
        report = self.audit(
            [
                call("c1", code),
                output("c1", "x\n" * 41),
                call("c2", code),
                output("c2", "x" * 4097),
            ]
        )
        violations = [item for item in report.violations if item.code == "CONTEXT_OUTPUT_LIMIT"]
        self.assertEqual(len(violations), 2)
        self.assertIn("41 lines", violations[0].detail)
        self.assertIn("4097 bytes", violations[1].detail)

    def test_non_context_command_mentioning_tool_name_does_not_limit_output(self) -> None:
        code = 'await tools.exec_command({cmd:"rg -n ctx_search docs"});'
        report = self.audit([call("c1", code), output("c1", "x\n" * 41)])
        self.assertTrue(report.ok)

    def test_invalid_json_and_full_file_content_are_reported_without_stopping(self) -> None:
        report = self.audit(
            [
                "{not-json",
                call("c1", "text({body: FILE_CONTENT});"),
                response_item({"type": "message", "role": "assistant", "content": []}),
            ]
        )
        self.assertEqual(
            {item.code for item in report.violations},
            {"INVALID_JSON", "FULL_FILE_CONTENT_OUTPUT"},
        )
        self.assertEqual(report.records, 2)

    def test_embedded_context_code_forwarding_full_file_is_reported(self) -> None:
        code = (
            'await tools.mcp__context_mode__ctx_execute_file({'
            'path:"sample.log",language:"javascript",'
            'code:"console.log(FILE_CONTENT)"});'
        )
        report = self.audit([call("c1", code)])
        self.assertEqual(
            [item.code for item in report.violations],
            ["FULL_FILE_CONTENT_OUTPUT"],
        )

    def test_escaped_embedded_full_file_fails_but_derived_summary_passes(self) -> None:
        escaped = (
            'await tools.mcp__context_mode__ctx_execute_file({'
            'path:"sample.log",language:"javascript",'
            'code:"console.log(\\\"prefix\\\", FILE_CONTENT)"});'
        )
        summary = "console.log(FILE_CONTENT.split('\\n').length);"
        report = self.audit([call("c1", escaped), call("c2", summary)])
        self.assertEqual(
            [item.code for item in report.violations],
            ["FULL_FILE_CONTENT_OUTPUT"],
        )

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
