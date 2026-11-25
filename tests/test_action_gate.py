"""The composite Action's gate summary: outputs, annotations, step summary."""

import contextlib
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parent.parent


def _load():
    spec = importlib.util.spec_from_file_location(
        "action_gate", REPO / "scripts" / "action_gate.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ActionGateTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.report = self.root / "gate.json"
        self.outputs = self.root / "outputs.txt"
        self.summary = self.root / "summary.md"
        self.module = _load()

    def run_gate(self, data):
        self.report.write_text(json.dumps(data), encoding="utf-8")
        env = {
            "GITHUB_OUTPUT": str(self.outputs),
            "GITHUB_STEP_SUMMARY": str(self.summary),
        }
        out = io.StringIO()
        with mock.patch.dict("os.environ", env):
            with contextlib.redirect_stdout(out):
                code = self.module.main(str(self.report))
        return code, out.getvalue()

    def test_pass_sets_outputs_and_summary(self):
        code, out = self.run_gate(
            {
                "outcome": "pass",
                "results": [
                    {
                        "oracle": "compile",
                        "type": "command",
                        "outcome": "pass",
                        "reasons": [],
                    }
                ],
                "gap": [
                    {
                        "criterion": "publish-approved",
                        "severity": "critical",
                    }
                ],
                "reasons": ["shadow requires: compile"],
            }
        )
        self.assertEqual(code, 0)
        text = self.outputs.read_text(encoding="utf-8")
        self.assertIn("verdict=pass", text)
        self.assertIn("findings=0", text)
        self.assertIn("traces=0", text)
        summary = self.summary.read_text(encoding="utf-8")
        self.assertIn("Assaystone gate: pass", summary)
        self.assertIn("publish-approved", summary)
        self.assertIn("::notice::shadow requires", out)

    def test_fail_emits_an_error(self):
        code, out = self.run_gate(
            {
                "outcome": "fail",
                "results": [
                    {
                        "oracle": "parity",
                        "type": "shadow",
                        "outcome": "fail",
                        "reasons": ["json output diverged"],
                    }
                ],
            }
        )
        self.assertEqual(code, 0)
        self.assertIn("findings=1", self.outputs.read_text(encoding="utf-8"))
        self.assertIn("::error::acceptance gate failed", out)

    def test_escalate_emits_a_warning(self):
        _, out = self.run_gate({"outcome": "escalate"})
        self.assertIn("::warning::", out)

    def test_missing_report_escalates(self):
        self.outputs.touch()
        env = {"GITHUB_OUTPUT": str(self.outputs)}
        with mock.patch.dict("os.environ", env):
            self.module.main(str(self.root / "absent.json"))
        self.assertIn(
            "verdict=escalate", self.outputs.read_text(encoding="utf-8")
        )


if __name__ == "__main__":
    unittest.main()
