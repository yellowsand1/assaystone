import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from assaystone.hooks.claude_code import install_claude_code, run_hook

REPO = Path(__file__).resolve().parent.parent
AUDIT = REPO / "examples" / "audit"
TRANSCRIPT = AUDIT / "transcript.jsonl"
BASELINE = AUDIT / "baseline"


class ClaudeCodeHookTest(unittest.TestCase):
    def setUp(self):
        # The hook writes a runtime record next to the work, so never run it in
        # the repository's own fixture directory.
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.baseline = Path(self._tmp.name) / "baseline"
        shutil.copytree(BASELINE, self.baseline)
        # A real session has a pre-session commit and leaves changes on disk.
        subprocess.run(["git", "init", "-q"], cwd=self.baseline, check=True)
        subprocess.run(["git", "add", "-A"], cwd=self.baseline, check=True)
        subprocess.run(
            ["git", "-c", "user.email=a@b.c", "-c", "user.name=t",
             "commit", "-qm", "baseline"],
            cwd=self.baseline,
            check=True,
        )
        test_file = self.baseline / "tests" / "test_discounts.py"
        original = test_file.read_text(encoding="utf-8")
        test_file.write_text(
            original.replace(
                "    def test_round_half_cent(self):\n"
                "        self.assertEqual(apply_discount(1, 50), 0)\n\n",
                "",
            ),
            encoding="utf-8",
        )

    def _payload(self, **overrides):
        payload = {
            "session_id": f"hook-{uuid.uuid4()}",
            "transcript_path": str(TRANSCRIPT),
            "cwd": str(self.baseline),
            "hook_event_name": "Stop",
            "stop_hook_active": False,
        }
        payload.update(overrides)
        return payload

    def test_warn_is_default(self):
        code, message = run_hook(self._payload())
        self.assertEqual(code, 0)
        self.assertIn("tests.integrity", message)

    def test_block_mode(self):
        with patch.dict(os.environ, {"ASSAYSTONE_HOOK_MODE": "block"}, clear=False):
            code, message = run_hook(self._payload())
        self.assertEqual(code, 2)
        self.assertIn("blocked", message)

    def test_stop_hook_active_prevents_loop(self):
        code, message = run_hook(self._payload(stop_hook_active=True))
        self.assertEqual((code, message), (0, ""))

    def test_missing_transcript_fails_open(self):
        code, message = run_hook({"cwd": str(self.baseline)})
        self.assertEqual(code, 0)
        self.assertIn("transcript_path", message)

    def test_warn_dedupes_same_finding(self):
        payload = self._payload()
        first_code, first_message = run_hook(payload)
        second_code, second_message = run_hook(payload)
        self.assertEqual(first_code, 0)
        self.assertIn("tests.integrity", first_message)
        self.assertEqual((second_code, second_message), (0, ""))

    def test_allowlist_filters_finding(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            shutil.copytree(BASELINE, repo)
            (repo / ".assaystone").mkdir(exist_ok=True)
            (repo / ".assaystone" / "hook.json").write_text(
                json.dumps({"ignore": [{"verifier": "tests.integrity"}]}),
                encoding="utf-8",
            )
            code, message = run_hook(self._payload(cwd=str(repo)))
            self.assertEqual((code, message), (0, ""))

    def test_git_working_tree_changes_are_audited(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            (repo / "tests").mkdir(parents=True)
            test_file = repo / "tests" / "test_x.py"
            test_file.write_text("def test_x():\n    assert True\n", encoding="utf-8")
            subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
            subprocess.run(["git", "add", "."], cwd=repo, check=True)
            subprocess.run(
                ["git", "-c", "user.email=a@b.c", "-c", "user.name=t", "commit", "-qm", "init"],
                cwd=repo,
                check=True,
            )
            # Simulate a Bash edit: no Edit/Write tool call in the transcript.
            test_file.write_text("def test_x():\n    assert False\n", encoding="utf-8")
            transcript = Path(tmp) / "session.jsonl"
            session = f"git-hook-{uuid.uuid4()}"
            entry = {
                "type": "assistant",
                "sessionId": session,
                "message": {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "Done."}],
                },
            }
            transcript.write_text(json.dumps(entry) + "\n", encoding="utf-8")
            code, message = run_hook(
                {
                    "session_id": session,
                    "transcript_path": str(transcript),
                    "cwd": str(repo),
                    "stop_hook_active": False,
                }
            )
            self.assertEqual(code, 0)
            self.assertIn("tests.integrity", message)

    def _capability_repo(self, oracle="true"):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        repo = Path(tmp.name) / "repo"
        (repo / ".assaystone").mkdir(parents=True)
        manifest = {
            "capability": "hook-test",
            "owner": "team",
            "systems": [],
            "data_classes": [],
            "irreversible_actions": [],
            "risk": "low",
            "lifecycle": "shadow",
            "criteria": [
                {
                    "id": "ok",
                    "kind": "postcondition",
                    "statement": "it works",
                    "oracle": "ok",
                    "severity": "critical",
                }
            ],
            "oracles": [
                {"id": "ok", "type": "command", "payload": {"command": [oracle]}}
            ],
            "policies": {"shadow": {"require": ["ok"]}},
        }
        (repo / ".assaystone" / "capability.json").write_text(
            json.dumps(manifest), encoding="utf-8"
        )
        (repo / ".assaystone" / "hook.json").write_text(
            json.dumps(
                {
                    "capability": ".assaystone/capability.json",
                    "stage": "shadow",
                }
            ),
            encoding="utf-8",
        )
        return repo

    def test_capability_gate_passes_without_a_transcript(self):
        repo = self._capability_repo()
        code, message = run_hook(
            {"cwd": str(repo), "session_id": f"gate-{uuid.uuid4()}"}
        )
        self.assertEqual((code, message), (0, ""))

    def test_capability_gate_warns_then_blocks(self):
        repo = self._capability_repo(oracle="false")
        payload = {"cwd": str(repo), "session_id": f"gate-{uuid.uuid4()}"}
        code, message = run_hook(payload)
        self.assertEqual(code, 0)
        self.assertIn("-> fail", message)
        with patch.dict(os.environ, {"ASSAYSTONE_HOOK_MODE": "block"}, clear=False):
            code, message = run_hook(payload)
        self.assertEqual(code, 2)
        self.assertIn("blocked", message)

    def test_installer_writes_the_capability_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = Path(tmp) / "project" / ".claude" / "settings.local.json"
            target, changed = install_claude_code(
                settings,
                mode="block",
                manifest=".assaystone/capability.json",
                stage="canary",
            )
            self.assertTrue(changed)
            self.assertTrue(target.exists())
            config = json.loads(
                (Path(tmp) / "project" / ".assaystone" / "hook.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(config["capability"], ".assaystone/capability.json")
            self.assertEqual(config["stage"], "canary")
            text = settings.read_text(encoding="utf-8")
            self.assertIn("ASSAYSTONE_HOOK_MODE=block", text)
            _, changed_again = install_claude_code(
                settings,
                mode="block",
                manifest=".assaystone/capability.json",
                stage="canary",
            )
            self.assertFalse(changed_again)

    def test_cli_hook(self):
        proc = subprocess.run(
            [sys.executable, "-m", "assaystone", "hook", "claude-code"],
            input=json.dumps(self._payload()),
            cwd=REPO,
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("tests.integrity", proc.stdout + proc.stderr)

    def test_install_is_idempotent_and_supports_block(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = Path(tmp) / ".claude" / "settings.local.json"
            target, changed = install_claude_code(settings, mode="warn")
            self.assertTrue(changed)
            data = json.loads(target.read_text(encoding="utf-8"))
            command = data["hooks"]["Stop"][0]["hooks"][0]["command"]
            self.assertEqual(command, "assaystone hook claude-code")

            _, changed_again = install_claude_code(settings, mode="warn")
            self.assertFalse(changed_again)

            target, changed_block = install_claude_code(settings, mode="block")
            self.assertTrue(changed_block)
            data = json.loads(target.read_text(encoding="utf-8"))
            commands = [
                hook["command"]
                for group in data["hooks"]["Stop"]
                for hook in group["hooks"]
            ]
            self.assertIn("ASSAYSTONE_HOOK_MODE=block assaystone hook claude-code", commands)


if __name__ == "__main__":
    unittest.main()
