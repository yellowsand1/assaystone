"""Do the tests cover the change? Mutation testing over the added lines."""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from assaystone.mutation_check import _is_test_path, cases_for, run_check
from assaystone.oracles import OracleSpec, run_oracle

PROD = '''def rate(region: str) -> int:
    if region == "us":
        return 290
    if region == "eu":
        return 250
    return 250
'''

COVERED_TEST = '''import unittest
from calc import rate


class RateTest(unittest.TestCase):
    def test_us(self):
        self.assertEqual(rate("us"), 290)

    def test_eu(self):
        self.assertEqual(rate("eu"), 250)
'''


def git(root, *args):
    subprocess.run(
        ["git", "-C", str(root), "-c", "user.email=a@b.c",
         "-c", "user.name=t", *args],
        check=True,
        capture_output=True,
    )


class CaseTest(unittest.TestCase):
    def test_tests_are_never_mutated(self):
        for name in ("tests/test_a.py", "test_a.py", "pkg/test_a.py",
                     "src/__tests__/a.py", "pkg/a_test.py", "conftest.py"):
            self.assertTrue(_is_test_path(name), name)
        for name in ("calc.py", "pkg/rate.py", "src/app/main.py"):
            self.assertFalse(_is_test_path(name), name)

    def test_only_the_allowed_lines_are_mutated(self):
        everything = cases_for(PROD, "calc.py", budget=10)
        self.assertTrue(everything)
        rest = cases_for(PROD, "calc.py", budget=10, allowed_lines={1, 2})
        self.assertTrue(rest)
        for case in rest:
            line = int(case.target.rsplit(":", 1)[1])
            self.assertIn(line, {1, 2, 3}, case.description)


class RunTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        (self.root / "calc.py").write_text(PROD, encoding="utf-8")
        (self.root / "test_calc.py").write_text(COVERED_TEST, encoding="utf-8")
        git(self.root, "init", "-q")
        git(self.root, "add", "-A")
        git(self.root, "commit", "-qm", "base")

    def command(self):
        return [sys.executable, "-m", "unittest", "-q", "test_calc.py"]

    def test_a_covered_change_passes(self):
        (self.root / "calc.py").write_text(
            PROD.replace('    if region == "eu":', '    if region == "eu":\n'
                         '        return 250\n    if region == "uk":\n'
                         '        return 250\n    if region == "eu":'),
            encoding="utf-8",
        )
        (self.root / "test_calc.py").write_text(
            COVERED_TEST.replace(
                "    def test_eu(self):",
                '    def test_uk(self):\n        self.assertEqual(rate("uk"), 250)\n\n'
                "    def test_eu(self):",
            ),
            encoding="utf-8",
        )
        git(self.root, "add", "-A")
        git(self.root, "commit", "-qm", "uk")
        check = run_check(self.root, self.command(), against="HEAD~1",
                          threshold=0.5, max_mutants=4)
        self.assertEqual(check.outcome, "pass", check.reasons)

    def test_an_uncovered_change_fails_with_the_survivors(self):
        (self.root / "calc.py").write_text(
            PROD + '\n\ndef surcharge(tier: str) -> int:\n'
                   '    if tier == "gold":\n        return 5\n    return 0\n',
            encoding="utf-8",
        )
        git(self.root, "add", "-A")
        git(self.root, "commit", "-qm", "uncovered")
        check = run_check(self.root, self.command(), against="HEAD~1",
                          threshold=0.5, max_mutants=4)
        self.assertEqual(check.outcome, "fail")
        self.assertIn("do not cover", check.reasons[0])
        self.assertTrue(any("surcharge" in item.case.description
                            for item in check.survivors))

    def test_a_red_baseline_escalates(self):
        (self.root / "calc.py").write_text(
            PROD.replace("return 290", "return 999"), encoding="utf-8"
        )
        git(self.root, "add", "-A")
        git(self.root, "commit", "-qm", "red")
        check = run_check(self.root, self.command(), against="HEAD~1",
                          threshold=0.5, max_mutants=2)
        self.assertEqual(check.outcome, "escalate")
        self.assertIn("does not pass on unmutated code", check.reasons[0])

    def test_a_change_with_no_python_escalates(self):
        (self.root / "notes.txt").write_text("hello\n", encoding="utf-8")
        git(self.root, "add", "-A")
        git(self.root, "commit", "-qm", "notes")
        check = run_check(self.root, self.command(), against="HEAD~1")
        self.assertEqual(check.outcome, "escalate")
        self.assertIn("no changed Python file", check.reasons[0])

    def test_the_oracle_reports_a_score(self):
        (self.root / "calc.py").write_text(
            PROD + '\n\ndef surcharge(tier: str) -> int:\n'
                   '    if tier == "gold":\n        return 5\n    return 0\n',
            encoding="utf-8",
        )
        git(self.root, "add", "-A")
        git(self.root, "commit", "-qm", "uncovered")
        spec = OracleSpec(
            id="mutation",
            type="mutation",
            payload={
                "command": self.command(),
                "against": "HEAD~1",
                "threshold": 0.5,
                "max_mutants": 4,
            },
        )
        result = run_oracle(spec, self.root)
        self.assertEqual(result.outcome, "fail")
        self.assertIn("mutation_score", result.facts)
        self.assertIn("score=", " ".join(result.evidence))


if __name__ == "__main__":
    unittest.main()
