import io
import re
import unittest
from contextlib import redirect_stdout
from pathlib import Path

import impact_audited

REPO = Path(__file__).resolve().parents[1]


class VersionIdentityTests(unittest.TestCase):
    def test_module_version_matches_pyproject(self):
        text = (REPO / "pyproject.toml").read_text(encoding="utf-8")
        match = re.search(r'(?m)^version = "([^"]+)"$', text)
        self.assertIsNotNone(match)
        self.assertEqual(impact_audited.__version__, match.group(1))

    def test_version_flag(self):
        output = io.StringIO()
        with self.assertRaises(SystemExit) as raised, redirect_stdout(output):
            impact_audited.main(["--version"])
        self.assertEqual(raised.exception.code, 0)
        self.assertIn(impact_audited.__version__, output.getvalue())
