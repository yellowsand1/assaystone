import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from assaystone.adapters import artifacts_from_git, from_claude_agent, from_langgraph, from_messages
from assaystone.init import init_project
from assaystone.model import Trace
from assaystone.verifiers import REGISTRY, Verifier, load_external_verifiers

REPO = Path(__file__).resolve().parent.parent
EXAMPLES = REPO / "examples" / "code_agent"


class AdapterTest(unittest.TestCase):
    def test_claude_agent_messages(self):
        messages = [
            {"type": "system", "subtype": "init"},
            {
                "type": "assistant",
                "content": [
                    {"type": "text", "text": "I will fix the rounding bug."},
                    {
                        "type": "tool_use",
                        "id": "tool-1",
                        "name": "Edit",
                        "input": {"file_path": "pricing/discounts.py"},
                    },
                ],
            },
            {
                "type": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "tool-1",
                        "content": "file updated",
                        "is_error": False,
                    }
                ],
            },
            {
                "type": "result",
                "result": "Fixed rounding. All tests pass.",
                "is_error": False,
                "session_id": "session-1",
            },
        ]
        trace = from_claude_agent(messages, task="fix rounding")
        self.assertEqual(trace.id, "session-1")
        self.assertEqual(trace.agent, "claude-agent-sdk")
        self.assertEqual(trace.input, "")  # tool results are not prompts
        self.assertEqual(len(trace.steps), 1)
        self.assertEqual(trace.steps[0].tool, "Edit")
        self.assertEqual(trace.steps[0].args["file_path"], "pricing/discounts.py")
        self.assertEqual(trace.steps[0].result, "file updated")
        self.assertTrue(trace.steps[0].ok)
        self.assertEqual(trace.final_message, "Fixed rounding. All tests pass.")
        self.assertEqual(trace.evidence["agent_result"]["session_id"], "session-1")

    def test_openai_style_messages(self):
        messages = [
            {"role": "user", "content": "fix the rounding bug"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call-1",
                        "type": "function",
                        "function": {
                            "name": "edit_file",
                            "arguments": '{"path": "pricing/discounts.py"}',
                        },
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "call-1", "content": "file updated"},
            {"role": "assistant", "content": "Fixed. All tests pass."},
        ]
        trace = from_messages(messages, agent="openai-agents")
        self.assertEqual(trace.input, "fix the rounding bug")
        self.assertEqual(trace.steps[0].tool, "edit_file")
        self.assertEqual(trace.steps[0].args["path"], "pricing/discounts.py")
        self.assertEqual(trace.steps[0].result, "file updated")
        self.assertEqual(trace.final_message, "Fixed. All tests pass.")

    def test_langgraph_state(self):
        state = {
            "messages": [
                {"type": "human", "content": "fix it"},
                {
                    "type": "ai",
                    "content": "",
                    "tool_calls": [
                        {"name": "edit_file", "args": {"path": "x.py"}, "id": "call-1"}
                    ],
                },
                {"type": "tool", "tool_call_id": "call-1", "content": "done"},
                {"type": "ai", "content": "Fixed. All tests pass."},
            ]
        }
        trace = from_langgraph(state)
        self.assertEqual(trace.agent, "langgraph")
        self.assertEqual(trace.input, "fix it")
        self.assertEqual(trace.steps[0].tool, "edit_file")
        self.assertEqual(trace.steps[0].args["path"], "x.py")
        self.assertEqual(trace.steps[0].result, "done")
        self.assertEqual(trace.final_message, "Fixed. All tests pass.")

    def test_artifacts_from_git(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
            (repo / "a.py").write_text("x = 1\n", encoding="utf-8")
            subprocess.run(["git", "add", "."], cwd=repo, check=True)
            subprocess.run(
                ["git", "-c", "user.email=a@b.c", "-c", "user.name=t", "commit", "-qm", "init"],
                cwd=repo,
                check=True,
            )
            (repo / "a.py").write_text("x = 2\n", encoding="utf-8")
            (repo / "b.py").write_text("y = 1\n", encoding="utf-8")
            artifacts = {artifact.path: artifact for artifact in artifacts_from_git(repo)}
            self.assertEqual(artifacts["a.py"].change, "modified")
            self.assertEqual(artifacts["a.py"].content, "x = 2\n")
            self.assertEqual(artifacts["b.py"].change, "added")


class RecordCliTest(unittest.TestCase):
    def test_record_cli(self):
        messages = [
            {
                "type": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "tool-1",
                        "name": "Edit",
                        "input": {"file_path": "pricing/discounts.py"},
                    }
                ],
            },
            {
                "type": "user",
                "content": [
                    {"type": "tool_result", "tool_use_id": "tool-1", "content": "ok"}
                ],
            },
            {"type": "result", "result": "Done.", "session_id": "session-9"},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            transcript = Path(tmp) / "messages.json"
            transcript.write_text(json.dumps(messages), encoding="utf-8")
            output = Path(tmp) / "trace.json"
            proc = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "assaystone",
                    "record",
                    "--transcript",
                    str(transcript),
                    "--out",
                    str(output),
                ],
                cwd=REPO,
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            trace = Trace.load(output)
            self.assertEqual(trace.id, "session-9")
            self.assertEqual(trace.steps[0].tool, "Edit")
            self.assertEqual(trace.final_message, "Done.")


class ExternalVerifierTest(unittest.TestCase):
    def test_entry_point_registers(self):
        class FakeEntryPoint:
            def load(self):
                from assaystone.verifiers import register

                @register
                class ExternalProbe(Verifier):
                    name = "external.probe"
                    layer = "L0"
                    cost_usd = 0.0

                    def check(self, ctx, params):
                        return True, [], []

        with patch("importlib.metadata.entry_points", return_value=[FakeEntryPoint()]):
            load_external_verifiers()
        self.assertIn("external.probe", REGISTRY)


class InitTest(unittest.TestCase):
    def test_init_scaffolds_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "tests").mkdir()
            (root / "tests" / "test_x.py").write_text("def test_x():\n    assert True\n", encoding="utf-8")
            (root / "pyproject.toml").write_text("[project]\nname = 'demo'\n", encoding="utf-8")
            result = init_project(root)
            contract = json.loads(result["contract"].read_text(encoding="utf-8"))
            names = [verifier["name"] for verifier in contract["verifiers"]]
            self.assertIn("tests.pass", names)
            self.assertIn("tests.integrity", names)
            self.assertIn("tests.harness_integrity", names)
            self.assertIn("diff.ci_surface", names)
            self.assertIn("regression", contract["required_defects"])
            self.assertEqual(contract["domain"], "code")
            self.assertIsNone(result["warning"])
            with self.assertRaises(FileExistsError):
                init_project(root)
            with_ci = init_project(root, force=True, ci=True)
            self.assertTrue(with_ci["workflow"].exists())


class PytestPluginTest(unittest.TestCase):
    def _run(self, trace: Path, cwd: str) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        existing = env.get("PYTHONPATH")
        env["PYTHONPATH"] = str(REPO) + (os.pathsep + existing if existing else "")
        env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
        return subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "-q",
                "-p",
                "assaystone.pytest_plugin",
                "--assaystone-contract",
                str(EXAMPLES / "contracts" / "hardened.json"),
                "--assaystone-traces",
                str(trace),
                "--assaystone-baseline",
                str(EXAMPLES / "baseline"),
            ],
            cwd=cwd,
            capture_output=True,
            text=True,
            env=env,
        )

    def test_auto_collected_items(self):
        with tempfile.TemporaryDirectory() as tmp:
            passed = self._run(EXAMPLES / "traces" / "t01-correct.json", tmp)
            self.assertEqual(passed.returncode, 0, passed.stdout + passed.stderr)
            failed = self._run(EXAMPLES / "traces" / "t03-test-tampering.json", tmp)
            self.assertEqual(failed.returncode, 1, failed.stdout + failed.stderr)
            self.assertIn("tests.integrity", failed.stdout + failed.stderr)


if __name__ == "__main__":
    unittest.main()
