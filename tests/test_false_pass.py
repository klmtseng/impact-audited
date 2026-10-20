"""Regression tests for the two v0.2.2 false-PASS holes (fixed in v0.2.3).

1. Text-format backends echo the audited symbol's own definition file. A
   same-file caller must not be counted as covered just because that path
   appears in stdout.
2. Backends that exit 0 with an "ambiguous" / "not found" envelope must be a
   backend failure, not a parsed caller list.

All backends are fake scripts; no GitNexus, no network.
"""

import contextlib
import io
import json
import shlex
import sys
import tempfile
import unittest
from pathlib import Path

import impact_audited

PASS = 0  # literal, so these tests also run against the v0.2.2 module


class FalsePassRegressionTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.tools = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.temp_dir.cleanup()
        self.tools.cleanup()

    def write(self, relative, content):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def backend(self, stdout, returncode=0, stderr=""):
        # Lives outside the audited repo so it never enters the baseline.
        script = Path(self.tools.name) / "fake_backend.py"
        script.write_text(
            "import sys\n"
            f"sys.stdout.write({stdout!r})\n"
            f"sys.stderr.write({stderr!r})\n"
            f"raise SystemExit({returncode})\n",
            encoding="utf-8",
        )
        return f"{shlex.quote(sys.executable)} {shlex.quote(str(script))} {{sym}}"

    def run_json(self, *args):
        output = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(io.StringIO()):
            code = impact_audited.main([*args, "--json"])
        return code, json.loads(output.getvalue())

    def same_file_repo(self):
        # setupConnection is defined AND called in App.tsx (BEAM-P2P shape).
        self.write(
            "App.tsx",
            "export function App() {\n"
            "  const setupConnection = useCallback((c) => { c.open(); }, []);\n"
            "  const initPeer = () => { setupConnection(conn); };\n"
            "  return <div />;\n"
            "}\n",
        )
        self.write("index.tsx", "import { App } from './App';\n")

    # (a) definition-file echo only -> must not PASS
    def test_a_text_backend_echoing_definition_file_is_not_pass(self):
        self.same_file_repo()
        echo = json.dumps(
            {
                "target": {"id": "Const:App.tsx:setupConnection", "filePath": "App.tsx"},
                "impactedCount": 0,
                "byDepth": {},
            }
        )
        code, result = self.run_json(
            "setupConnection", "--path", str(self.root), "--graph", self.backend(echo + "\n")
        )
        self.assertNotEqual(code, PASS)
        self.assertNotEqual(result.get("final_status"), "PASS")
        self.assertEqual(code, impact_audited.EXIT_UNVERIFIED)
        self.assertEqual(result["unverified_callers"], ["App.tsx"])
        self.assertEqual(result["audit_verdict"], "UNVERIFIED")
        self.assertIs(result["audit_pass"], False)

    def test_a_plain_path_echo_is_not_pass(self):
        self.same_file_repo()
        code, result = self.run_json(
            "setupConnection",
            "--path",
            str(self.root),
            "--graph",
            self.backend("Target: setupConnection (App.tsx:2)\nCallers: none\n"),
        )
        self.assertNotEqual(code, PASS)
        self.assertNotEqual(result.get("final_status"), "PASS")

    def test_a_gitnexus_format_target_only_is_omission(self):
        self.same_file_repo()
        echo = json.dumps(
            {
                "target": {"id": "Const:App.tsx:setupConnection", "filePath": "App.tsx"},
                "impactedCount": 0,
                "byDepth": {},
            }
        )
        code, result = self.run_json(
            "setupConnection",
            "--path",
            str(self.root),
            "--graph-format",
            "gitnexus",
            "--graph",
            self.backend(echo),
        )
        self.assertEqual(code, impact_audited.EXIT_OMISSION)
        self.assertEqual(result["missing_callers"], ["App.tsx"])

    # (b) ambiguous / not found with exit 0 -> must not PASS
    def test_b_json_ambiguous_exit_zero_is_not_pass(self):
        self.same_file_repo()
        self.write("other.ts", "export function setupConnection() {}\n")
        ambiguous = json.dumps(
            {
                "status": "ambiguous",
                "message": "Found 2 symbols matching 'setupConnection'.",
                "impactedCount": 0,
                "candidates": [
                    {"uid": "Const:App.tsx:setupConnection", "filePath": "App.tsx"},
                    {"uid": "Function:other.ts:setupConnection", "filePath": "other.ts"},
                ],
            }
        )
        code, result = self.run_json(
            "setupConnection", "--path", str(self.root), "--graph", self.backend(ambiguous)
        )
        self.assertNotEqual(code, PASS)
        self.assertNotEqual(result.get("final_status"), "PASS")
        self.assertEqual(code, impact_audited.EXIT_BACKEND_FAILURE)
        self.assertEqual(result["error"], "graph_backend_failed")

    def test_b_json_not_found_exit_zero_is_not_pass(self):
        # Baseline caller lives in a file the backend lists only as a candidate.
        self.write("lib.py", "def helper():\n    return 1\n")
        self.write("caller.py", "from lib import helper\nhelper()\n")
        not_found = json.dumps(
            {"error": "Target 'helper' not found", "impactedCount": 0, "note": "caller.py"}
        )
        code, result = self.run_json(
            "helper", "--path", str(self.root), "--graph", self.backend(not_found)
        )
        self.assertNotEqual(code, PASS)
        self.assertNotEqual(result.get("final_status"), "PASS")
        self.assertEqual(code, impact_audited.EXIT_BACKEND_FAILURE)

    def test_b_plain_text_ambiguous_exit_zero_is_not_pass(self):
        self.write("lib.py", "def helper():\n    return 1\n")
        self.write("caller.py", "from lib import helper\nhelper()\n")
        code, result = self.run_json(
            "helper",
            "--path",
            str(self.root),
            "--graph",
            self.backend("Symbol 'helper' is ambiguous; candidates:\n  caller.py\n  lib.py\n"),
        )
        self.assertNotEqual(code, PASS)
        self.assertNotEqual(result.get("final_status"), "PASS")
        self.assertEqual(code, impact_audited.EXIT_BACKEND_FAILURE)

    def test_b_custom_fail_pattern_on_stderr(self):
        self.write("lib.py", "def helper():\n    return 1\n")
        self.write("caller.py", "helper()\n")
        code, _ = self.run_json(
            "helper",
            "--path",
            str(self.root),
            "--graph-fail-pattern",
            r"index is stale",
            "--graph",
            self.backend("caller.py\n", stderr="warning: index is stale\n"),
        )
        self.assertEqual(code, impact_audited.EXIT_BACKEND_FAILURE)

    def test_b_default_markers_can_be_disabled(self):
        self.write("lib.py", "def helper():\n    return 1\n")
        self.write("caller.py", "helper()\n")
        code, result = self.run_json(
            "helper",
            "--path",
            str(self.root),
            "--no-default-fail-markers",
            "--graph",
            self.backend("caller.py  # 2 others not found in index\n"),
        )
        self.assertEqual(code, impact_audited.EXIT_PASS)
        self.assertEqual(result["final_status"], "PASS")

    def test_b_marker_inside_path_is_not_a_failure(self):
        self.write("lib.py", "def helper():\n    return 1\n")
        self.write("src/ambiguous.py", "helper()\n")
        code, _ = self.run_json(
            "helper", "--path", str(self.root), "--graph", self.backend("src/ambiguous.py\n")
        )
        self.assertEqual(code, impact_audited.EXIT_PASS)

    def test_b_gitnexus_count_mismatch_is_backend_failure(self):
        self.write("lib.py", "def helper():\n    return 1\n")
        self.write("caller.py", "helper()\n")
        truncated = json.dumps(
            {"impactedCount": 2, "byDepth": {"1": [{"filePath": "caller.py"}]}}
        )
        code, _ = self.run_json(
            "helper",
            "--path",
            str(self.root),
            "--graph-format",
            "gitnexus",
            "--graph",
            self.backend(truncated),
        )
        self.assertEqual(code, impact_audited.EXIT_BACKEND_FAILURE)

    # (c) positive control: backend lists every caller, including same-file
    def test_c_gitnexus_format_listing_same_file_caller_passes(self):
        self.same_file_repo()
        full = json.dumps(
            {
                "target": {"id": "Const:App.tsx:setupConnection", "filePath": "App.tsx"},
                "impactedCount": 1,
                "byDepth": {
                    "1": [{"id": "File:App.tsx", "filePath": "App.tsx", "relationType": "CALLS"}]
                },
            }
        )
        code, result = self.run_json(
            "setupConnection",
            "--path",
            str(self.root),
            "--graph-format",
            "gitnexus",
            "--graph",
            self.backend(full),
        )
        self.assertEqual(code, impact_audited.EXIT_PASS)
        self.assertEqual(result["final_status"], "PASS")
        self.assertEqual(result["unverified_callers"], [])

    def test_c_lines_format_listing_all_callers_passes(self):
        self.same_file_repo()
        self.write("caller.ts", "setupConnection(x);\n")
        code, result = self.run_json(
            "setupConnection",
            "--path",
            str(self.root),
            "--graph-format",
            "lines",
            "--graph",
            self.backend("App.tsx\ncaller.ts\n"),
        )
        self.assertEqual(code, impact_audited.EXIT_PASS)
        self.assertEqual(result["final_status"], "PASS")

    def test_c_text_format_cross_file_callers_still_pass(self):
        self.write("lib.py", "def helper():\n    return 1\n")
        self.write("a.py", "helper()\n")
        self.write("b.py", "x = helper()\n")
        code, result = self.run_json(
            "helper", "--path", str(self.root), "--graph", self.backend("a.py\nb.py\nlib.py\n")
        )
        self.assertEqual(code, impact_audited.EXIT_PASS)
        self.assertEqual(result["final_status"], "PASS")

    def test_lines_format_rejects_non_path_lines(self):
        self.write("lib.py", "def helper():\n    return 1\n")
        self.write("a.py", "helper()\n")
        code, _ = self.run_json(
            "helper",
            "--path",
            str(self.root),
            "--graph-format",
            "lines",
            "--graph",
            self.backend("Callers of helper:\na.py\n"),
        )
        self.assertEqual(code, impact_audited.EXIT_BACKEND_FAILURE)

    def test_omission_takes_precedence_over_unverified(self):
        self.same_file_repo()
        self.write("caller.ts", "setupConnection(x);\n")
        code, result = self.run_json(
            "setupConnection", "--path", str(self.root), "--graph", self.backend("App.tsx\n")
        )
        self.assertEqual(code, impact_audited.EXIT_OMISSION)
        self.assertEqual(result["missing_callers"], ["caller.ts"])
        self.assertEqual(result["unverified_callers"], ["App.tsx"])

    def test_human_output_marks_unverified(self):
        self.same_file_repo()
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = impact_audited.main(
                ["setupConnection", "--path", str(self.root), "--graph", self.backend("App.tsx\n")]
            )
        self.assertEqual(code, impact_audited.EXIT_UNVERIFIED)
        self.assertIn("Unverified callers (1): ['App.tsx']", output.getvalue())
        self.assertIn("Final: FAIL (UNVERIFIED)", output.getvalue())

    def test_format_options_require_graph(self):
        code, result = self.run_json(
            "helper", "--path", str(self.root), "--graph-format", "lines"
        )
        self.assertEqual(code, impact_audited.EXIT_INVALID_CONFIG)
        self.assertEqual(result["error"], "invalid_configuration")

    def test_invalid_fail_pattern_is_config_error(self):
        code, _ = self.run_json(
            "helper",
            "--path",
            str(self.root),
            "--graph-fail-pattern",
            "(",
            "--graph",
            self.backend("x\n"),
        )
        self.assertEqual(code, impact_audited.EXIT_INVALID_CONFIG)


if __name__ == "__main__":
    unittest.main()
