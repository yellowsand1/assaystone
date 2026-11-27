import tempfile
import unittest
from pathlib import Path

from assaystone.backtest import backtest
from assaystone.contract import Contract, VerifierSpec
from assaystone.model import Artifact, Trace, load_traces
from assaystone.mutate import generate_mutants
from assaystone.runner import run_contract
from assaystone.workspace import Workspace

REPO = Path(__file__).resolve().parent.parent
EXAMPLES = REPO / "examples" / "code_agent"


class AssaystoneTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.baseline = EXAMPLES / "baseline"
        cls.naive = Contract.load(EXAMPLES / "contracts" / "naive.json")
        cls.hardened = Contract.load(EXAMPLES / "contracts" / "hardened.json")
        cls.traces = load_traces(EXAMPLES / "traces")
        cls.by_id = {trace.id: trace for trace in cls.traces}

    def test_trace_roundtrip(self):
        trace = self.by_id["t01-correct"]
        clone = Trace.from_dict(trace.to_dict())
        self.assertEqual(clone.id, trace.id)
        self.assertEqual(clone.artifacts[0].path, trace.artifacts[0].path)
        self.assertEqual(clone.labels.verdict, "pass")

    def test_correct_patch_passes_both_contracts(self):
        for contract in (self.naive, self.hardened):
            result = run_contract(contract, self.by_id["t01-correct"], self.baseline)
            self.assertEqual(result.verdict, "pass", result.first_failure)

    def test_test_tampering_escapes_naive_but_not_hardened(self):
        trace = self.by_id["t03-test-tampering"]
        self.assertEqual(run_contract(self.naive, trace, self.baseline).verdict, "pass")
        hardened = run_contract(self.hardened, trace, self.baseline)
        self.assertEqual(hardened.verdict, "fail")
        self.assertIn("tests.integrity", hardened.first_failure or "")

    def test_forbidden_path_escapes_naive_but_not_hardened(self):
        trace = self.by_id["t04-forbidden-path"]
        self.assertEqual(run_contract(self.naive, trace, self.baseline).verdict, "pass")
        hardened = run_contract(self.hardened, trace, self.baseline)
        self.assertEqual(hardened.verdict, "fail")
        self.assertIn("diff.forbidden_paths", hardened.first_failure or "")

    def test_debug_print_escapes_naive_but_not_hardened(self):
        trace = self.by_id["t05-debug-print"]
        self.assertEqual(run_contract(self.naive, trace, self.baseline).verdict, "pass")
        hardened = run_contract(self.hardened, trace, self.baseline)
        self.assertEqual(hardened.verdict, "fail")
        self.assertIn("quality.no_debug_prints", hardened.first_failure or "")

    def test_backtest_metrics(self):
        naive = backtest(self.naive, self.traces, self.baseline)
        hardened = backtest(self.hardened, self.traces, self.baseline)
        self.assertEqual((len(naive.defects), naive.caught, naive.escaped), (4, 1, 3))
        self.assertEqual((len(hardened.defects), hardened.caught, hardened.escaped), (4, 4, 0))
        self.assertEqual(hardened.false_alarms, 0)

    def test_mutation_generates_policy_mutants(self):
        mutants = generate_mutants(self.by_id["t01-correct"], self.baseline, max_total=18)
        operators = {mutant.operator for mutant in mutants}
        for expected in (
            "insert_print",
            "touch_forbidden_file",
            "delete_test_method",
            "weaken_assert",
        ):
            self.assertIn(expected, operators)

    def test_workspace_rejects_path_traversal(self):
        with Workspace(self.baseline) as workspace:
            with self.assertRaises(ValueError):
                workspace.apply([Artifact("../escape.py", "print('x')")])

    def test_workspace_ignores_heavy_directories(self):
        with tempfile.TemporaryDirectory() as tmp:
            baseline = Path(tmp) / "baseline"
            (baseline / "src").mkdir(parents=True)
            (baseline / "src" / "a.py").write_text("x = 1\n", encoding="utf-8")
            (baseline / "node_modules").mkdir()
            (baseline / "node_modules" / "pkg.js").write_text("x\n", encoding="utf-8")
            (baseline / ".git").mkdir()
            (baseline / ".git" / "config").write_text("x\n", encoding="utf-8")
            with Workspace(baseline) as workspace:
                self.assertTrue((workspace.root / "src" / "a.py").exists())
                self.assertFalse((workspace.root / "node_modules").exists())
                self.assertFalse((workspace.root / ".git").exists())

    def test_workspace_refuses_home(self):
        with self.assertRaises(ValueError):
            Workspace(Path.home())

    def test_forbidden_paths_narrows_github_to_workflows(self):
        contract = Contract(
            name="policy", verifiers=[VerifierSpec("diff.forbidden_paths")]
        )
        issue = Trace(
            id="issue",
            task="",
            artifacts=[
                Artifact(".github/ISSUE_TEMPLATE/bug.md", "template\n", "modified")
            ],
        )
        self.assertEqual(run_contract(contract, issue, self.baseline).verdict, "pass")
        workflow = Trace(
            id="workflow",
            task="",
            artifacts=[Artifact(".github/workflows/ci.yml", "name: ci\n", "modified")],
        )
        self.assertEqual(run_contract(contract, workflow, self.baseline).verdict, "fail")

    def test_no_debug_prints_ignores_cli_and_examples(self):
        contract = Contract(
            name="quality", verifiers=[VerifierSpec("quality.no_debug_prints")]
        )
        cli = Trace(
            id="cli",
            task="",
            artifacts=[Artifact("cli.py", "print('usage')\n", "modified")],
        )
        self.assertEqual(run_contract(contract, cli, self.baseline).verdict, "pass")
        app = Trace(
            id="app",
            task="",
            artifacts=[Artifact("src/app.py", "print('debug')\n", "modified")],
        )
        self.assertEqual(run_contract(contract, app, self.baseline).verdict, "fail")

    def test_no_debug_prints_ignores_repro_and_tools(self):
        # Found in a real session: a reproduction script legitimately prints.
        contract = Contract(
            name="quality", verifiers=[VerifierSpec("quality.no_debug_prints")]
        )
        for path in ("repro/common.py", "tools/export.py", "benchmarks/run.py"):
            trace = Trace(
                id="repro",
                task="",
                artifacts=[Artifact(path, "print('debug')\n", "modified")],
            )
            self.assertEqual(
                run_contract(contract, trace, self.baseline).verdict, "pass", path
            )


if __name__ == "__main__":
    unittest.main()
