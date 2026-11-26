import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from assaystone.audit import audit_traces, build_audit_contract, load_audit_traces
from assaystone.contract import Contract, VerifierSpec
from assaystone.model import Artifact, Trace
from assaystone.runner import run_contract

REPO = Path(__file__).resolve().parent.parent
AUDIT = REPO / "examples" / "audit"
TRANSCRIPT = AUDIT / "transcript.jsonl"
BASELINE = AUDIT / "baseline"


class AuditTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.traces = load_audit_traces(TRANSCRIPT, baseline=BASELINE)

    def test_transcript_reconstruction(self):
        self.assertEqual(len(self.traces), 1)
        trace = self.traces[0]
        self.assertEqual(trace.id, "audit-demo-session")
        self.assertEqual(
            {artifact.path for artifact in trace.artifacts},
            {"pricing/discounts.py", "tests/test_discounts.py"},
        )
        self.assertEqual(trace.evidence.get("test_exit_code"), 0)
        self.assertEqual(len(trace.steps), 6)
        self.assertEqual(trace.final_message, "Fixed. All tests pass.")

    def test_finds_test_tampering(self):
        contract = build_audit_contract(BASELINE)
        report = audit_traces(contract, self.traces, BASELINE)
        verifiers = {finding.verifier for finding in report.findings}
        self.assertIn("tests.integrity", verifiers)
        self.assertNotIn("tests.pass", [spec.name for spec in contract.verifiers])
        self.assertEqual(report.severity_counts()["high"], 1)
        self.assertEqual(report.exit_code("any"), 1)
        self.assertEqual(report.exit_code("high"), 1)
        self.assertEqual(report.exit_code("none"), 0)
        self.assertEqual(report.clean_count(), 0)

    def test_workspace_mode(self):
        traces = load_audit_traces(TRANSCRIPT, baseline=BASELINE, workspace=True)
        trace = traces[0]
        self.assertEqual(
            {artifact.path for artifact in trace.artifacts},
            {"pricing/discounts.py", "tests/test_discounts.py"},
        )
        # The working tree equals the baseline, so nothing was tampered with:
        # "modified" alone is no longer a finding, only a deleted or weakened
        # test is.
        report = audit_traces(build_audit_contract(BASELINE), traces, BASELINE)
        self.assertNotIn(
            "tests.integrity", {finding.verifier for finding in report.findings}
        )

    def test_partial_replay_falls_back_to_workspace(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "src").mkdir()
            (root / "src" / "a.py").write_text("new = 2\n", encoding="utf-8")
            transcript = root / "session.jsonl"
            entry = {
                "type": "assistant",
                "sessionId": "post-session",
                "message": {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "tool-1",
                            "name": "Edit",
                            "input": {
                                "file_path": "src/a.py",
                                "old_string": "old = 1",
                                "new_string": "new = 2",
                            },
                        }
                    ],
                },
            }
            transcript.write_text(json.dumps(entry) + "\n", encoding="utf-8")
            traces = load_audit_traces(transcript, baseline=root)
            self.assertEqual(len(traces), 1)
            self.assertEqual({a.path for a in traces[0].artifacts}, {"src/a.py"})
            self.assertEqual(traces[0].artifacts[0].content, "new = 2\n")

    def test_audit_step_budget_matches_real_sessions(self):
        contract = build_audit_contract(BASELINE)
        budget = next(spec for spec in contract.verifiers if spec.name == "budget.steps")
        self.assertEqual(budget.params["max_steps"], 5000)

    def test_nested_test_dir_is_protected(self):
        contract = Contract(name="nested", verifiers=[VerifierSpec("tests.integrity")])
        trace = Trace(
            id="nested",
            task="edit a nested test file",
            artifacts=[
                Artifact("demo2/server/tests/v2-api.test.ts", "// changed\n", "modified")
            ],
        )
        result = run_contract(contract, trace, BASELINE)
        self.assertEqual(result.verdict, "fail")
        self.assertIn("tests.integrity", result.first_failure or "")

    def test_cli_json(self):
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "assaystone",
                "audit",
                str(TRANSCRIPT),
                "--baseline",
                str(BASELINE),
                "--json",
            ],
            cwd=REPO,
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 1, proc.stderr)
        data = json.loads(proc.stdout)
        self.assertEqual(data["traces"], 1)
        self.assertEqual(data["summary"]["high"], 1)
        self.assertTrue(
            any(finding["verifier"] == "tests.integrity" for finding in data["findings"])
        )

    def test_record_claude_code_transcript(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "trace.json"
            proc = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "assaystone",
                    "record",
                    "--transcript",
                    str(TRANSCRIPT),
                    "--baseline",
                    str(BASELINE),
                    "--out",
                    str(output),
                ],
                cwd=REPO,
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            trace = Trace.load(output)
            self.assertEqual(len(trace.steps), 6)
            self.assertEqual(
                {artifact.path for artifact in trace.artifacts},
                {"pricing/discounts.py", "tests/test_discounts.py"},
            )

    def test_cli_fail_on_none(self):
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "assaystone",
                "audit",
                str(TRANSCRIPT),
                "--baseline",
                str(BASELINE),
                "--fail-on",
                "none",
            ],
            cwd=REPO,
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)


if __name__ == "__main__":
    unittest.main()
