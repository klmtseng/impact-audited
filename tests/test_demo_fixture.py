import shlex
import subprocess
import sys
import unittest
from pathlib import Path

import impact_audited

REPO = Path(__file__).resolve().parents[1]
FIXTURE = REPO / "examples" / "silent-gap"


class SilentGapFixtureTests(unittest.TestCase):
    def test_fixture_reports_omitted_caller_c(self):
        graph = (
            f"{shlex.quote(sys.executable)} "
            f"{shlex.quote(str(FIXTURE / 'fake_graph.py'))} {{sym}}"
        )
        output = subprocess.run(
            [
                sys.executable,
                str(REPO / "impact_audited.py"),
                "audited",
                "--path",
                str(FIXTURE),
                "--graph",
                graph,
                "--json",
            ],
            cwd=str(REPO),
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(output.returncode, impact_audited.EXIT_OMISSION)
        self.assertIn('"caller_c.py"', output.stdout)
        self.assertIn('"final_status": "FAIL"', output.stdout)

    def test_documented_demo_script_reproduces_expected_fail(self):
        proc = subprocess.run(
            [sys.executable, str(FIXTURE / "run_demo.py")],
            cwd=str(REPO),
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("Demo PASS: expected FAIL reproduced (missing caller_c.py)", proc.stdout)
