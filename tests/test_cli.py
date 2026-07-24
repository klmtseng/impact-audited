import contextlib
import io
import json
import shlex
import sys
import tempfile
import unittest
from pathlib import Path

import impact_audited


class AuditCliTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def write(self, relative, content):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def backend(self, stdout="", returncode=0, stderr=""):
        script = self.write(
            "fake_backend.py",
            "import sys\n"
            f"sys.stdout.write({stdout!r})\n"
            f"sys.stderr.write({stderr!r})\n"
            f"raise SystemExit({returncode})\n",
        )
        return (
            f"{shlex.quote(sys.executable)} {shlex.quote(str(script))} "
            "--symbol {sym}"
        )

    def run_json(self, *args):
        output = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(io.StringIO()):
            code = impact_audited.main([*args, "--json"])
        return code, json.loads(output.getvalue())

    def test_python_pass_case(self):
        self.write("target.py", "def audited():\n    return 1\n")
        self.write("caller.py", "from target import audited\nvalue = audited()\n")

        code, result = self.run_json(
            "audited", "--path", str(self.root), "--graph", self.backend("caller.py\n")
        )

        self.assertEqual(code, impact_audited.EXIT_PASS)
        self.assertEqual(result["baseline_caller_count"], 1)
        self.assertEqual(result["graph_caller_count"], 1)
        self.assertEqual(result["missing_callers"], [])
        self.assertEqual(result["final_status"], "PASS")

    def test_python_omission_case(self):
        self.write("target.py", "def audited():\n    return 1\n")
        self.write("caller.py", "from target import audited\naudited()\n")

        code, result = self.run_json(
            "audited", "--path", str(self.root), "--graph", self.backend("target.py\n")
        )

        self.assertEqual(code, impact_audited.EXIT_OMISSION)
        self.assertEqual(result["missing_callers"], ["caller.py"])
        self.assertEqual(result["final_status"], "FAIL")

    def test_typescript_pass_case(self):
        self.write("target.ts", "export function audited(): number { return 1; }\n")
        self.write("caller.ts", "import { audited } from './target';\naudited();\n")

        code, result = self.run_json(
            "audited", "--path", str(self.root), "--graph", self.backend("caller.ts\n")
        )

        self.assertEqual(code, impact_audited.EXIT_PASS)
        self.assertEqual(result["grep_caller_files"], ["caller.ts"])

    def test_typescript_omission_case(self):
        self.write("target.ts", "export function audited(): number { return 1; }\n")
        self.write("caller.ts", "import { audited } from './target';\naudited();\n")

        code, result = self.run_json(
            "audited", "--path", str(self.root), "--graph", self.backend("target.ts\n")
        )

        self.assertEqual(code, impact_audited.EXIT_OMISSION)
        self.assertEqual(result["missing_callers"], ["caller.ts"])

    def test_react_tsx_component_caller(self):
        self.write("Panel.tsx", "export function Panel() { return <section />; }\n")
        self.write(
            "App.tsx",
            "import { Panel } from './Panel';\nexport const App = () => <Panel />;\n",
        )

        code, result = self.run_json(
            "Panel", "--path", str(self.root), "--graph", self.backend("App.tsx\n")
        )

        self.assertEqual(code, impact_audited.EXIT_PASS)
        self.assertEqual(result["grep_caller_files"], ["App.tsx"])

    def test_graph_backend_failure(self):
        self.write("caller.py", "audited()\n")

        code, result = self.run_json(
            "audited",
            "--path",
            str(self.root),
            "--graph",
            self.backend("partial.py\n", returncode=7, stderr="backend exploded\n"),
        )

        self.assertEqual(code, impact_audited.EXIT_BACKEND_FAILURE)
        self.assertEqual(result["error"], "graph_backend_failed")
        self.assertEqual(result["backend_exit_code"], 7)
        self.assertEqual(result["baseline_caller_count"], 1)
        self.assertIsNone(result["graph_caller_count"])
        self.assertEqual(result["final_status"], "FAIL")

    def test_empty_graph_backend_output_is_failure(self):
        code, result = self.run_json(
            "audited", "--path", str(self.root), "--graph", self.backend()
        )

        self.assertEqual(code, impact_audited.EXIT_BACKEND_FAILURE)
        self.assertEqual(result["error"], "graph_backend_failed")

    def test_symbol_substitution_is_shell_quoted(self):
        marker = self.root / "must-not-exist"
        symbol = f"audited; touch {marker}"

        code, _ = self.run_json(
            symbol,
            "--path",
            str(self.root),
            "--graph",
            "printf '%s\\n' {sym}",
        )

        self.assertEqual(code, impact_audited.EXIT_PASS)
        self.assertFalse(marker.exists())

    def test_graph_template_rejects_zero_placeholders(self):
        code, result = self.run_json(
            "audited",
            "--path",
            str(self.root),
            "--graph",
            "printf 'caller.py\n'",
        )

        self.assertEqual(code, impact_audited.EXIT_INVALID_CONFIG)
        self.assertEqual(result["error"], "invalid_configuration")
        self.assertIn("exactly one literal '{sym}'", result["message"])
        self.assertIn("found 0", result["message"])

    def test_graph_template_accepts_exactly_one_placeholder(self):
        self.write("caller.py", "audited()\n")

        code, result = self.run_json(
            "audited",
            "--path",
            str(self.root),
            "--graph",
            self.backend("caller.py\n"),
        )

        self.assertEqual(code, impact_audited.EXIT_PASS)
        self.assertEqual(result["final_status"], "PASS")

    def test_graph_template_rejects_multiple_placeholders(self):
        code, result = self.run_json(
            "audited",
            "--path",
            str(self.root),
            "--graph",
            "printf '%s %s\n' {sym} {sym}",
        )

        self.assertEqual(code, impact_audited.EXIT_INVALID_CONFIG)
        self.assertEqual(result["error"], "invalid_configuration")
        self.assertIn("exactly one literal '{sym}'", result["message"])
        self.assertIn("found 2", result["message"])

    def test_graph_placeholder_human_error_is_clear(self):
        error = io.StringIO()

        with contextlib.redirect_stderr(error):
            code = impact_audited.main(
                [
                    "audited",
                    "--path",
                    str(self.root),
                    "--graph",
                    "printf 'caller.py\n'",
                ]
            )

        self.assertEqual(code, impact_audited.EXIT_INVALID_CONFIG)
        self.assertIn(
            "--graph must contain exactly one literal '{sym}' placeholder (found 0)",
            error.getvalue(),
        )
        self.assertIn("Final: FAIL", error.getvalue())

    def test_invalid_configuration(self):
        code, result = self.run_json(
            "audited", "--path", str(self.root / "does-not-exist")
        )

        self.assertEqual(code, impact_audited.EXIT_INVALID_CONFIG)
        self.assertEqual(result["error"], "invalid_configuration")
        self.assertEqual(result["final_status"], "FAIL")

    def test_argparse_errors_use_invalid_configuration_code(self):
        with self.assertRaises(SystemExit) as raised:
            with contextlib.redirect_stderr(io.StringIO()):
                impact_audited.main([])

        self.assertEqual(raised.exception.code, impact_audited.EXIT_INVALID_CONFIG)

    def test_human_output_has_ci_summary_fields(self):
        self.write("caller.js", "audited();\n")
        output = io.StringIO()

        with contextlib.redirect_stdout(output):
            code = impact_audited.main(
                [
                    "audited",
                    "--path",
                    str(self.root),
                    "--graph",
                    self.backend("caller.js\n"),
                ]
            )

        self.assertEqual(code, impact_audited.EXIT_PASS)
        rendered = output.getvalue()
        self.assertIn("Audited symbol: audited", rendered)
        self.assertIn("Baseline caller count: 1", rendered)
        self.assertIn("Graph caller count: 1", rendered)
        self.assertIn("Missing callers (0): []", rendered)
        self.assertIn("Final: PASS", rendered)

    def test_all_documented_javascript_extensions_are_scanned(self):
        for suffix in (".js", ".jsx", ".mjs", ".cjs"):
            self.write(f"caller{suffix}", "audited();\n")

        callers, _ = impact_audited.baseline_caller_files("audited", self.root)

        self.assertEqual(
            callers,
            {"caller.js", "caller.jsx", "caller.mjs", "caller.cjs"},
        )


if __name__ == "__main__":
    unittest.main()
