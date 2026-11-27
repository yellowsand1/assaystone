"""The PreToolUse hook: decide before the action executes."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from assaystone.hooks.claude_code import install_claude_code, run_pre_hook

REPO = Path(__file__).resolve().parent.parent


def payload(root: Path, tool: str, args: dict, session: str = "s1") -> dict:
    return {
        "hook_event_name": "PreToolUse",
        "session_id": session,
        "cwd": str(root),
        "tool_name": tool,
        "tool_input": args,
    }


class PreHookTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / ".assaystone").mkdir()
        (self.root / ".assaystone" / "policy.json").write_text(
            json.dumps(
                {
                    "mode": "block",
                    "deny_paths": [".github/workflows/"],
                    "deny_commands": [r"rm\s+-rf\s+/"],
                }
            )
        )

    def tearDown(self):
        self._tmp.cleanup()

    def test_blocks_a_denied_write_and_records_it(self):
        code, message = run_pre_hook(
            payload(self.root, "Write", {"file_path": ".github/workflows/ci.yml"})
        )
        self.assertEqual(code, 2)
        self.assertIn("denied", message)
        record = self.root / ".assaystone" / "session.jsonl"
        self.assertTrue(record.exists())
        entry = json.loads(record.read_text(encoding="utf-8").splitlines()[0])
        self.assertEqual(entry["decision"], "deny")
        self.assertEqual(entry["tool"], "Write")

    def test_blocks_a_denied_command(self):
        code, message = run_pre_hook(
            payload(self.root, "Bash", {"command": "rm -rf / --no-preserve-root"})
        )
        self.assertEqual(code, 2)
        self.assertIn("deny_commands", message)

    def test_allows_a_benign_write(self):
        code, message = run_pre_hook(payload(self.root, "Write", {"file_path": "src/app.py"}))
        self.assertEqual((code, message), (0, ""))

    def test_warn_mode_reports_without_blocking(self):
        (self.root / ".assaystone" / "policy.json").write_text(
            json.dumps({"mode": "warn", "deny_paths": [".github/"]})
        )
        code, message = run_pre_hook(
            payload(self.root, "Write", {"file_path": ".github/workflows/ci.yml"})
        )
        self.assertEqual(code, 0)
        self.assertIn("denied", message)

    def test_a_missing_policy_is_passive(self):
        (self.root / ".assaystone" / "policy.json").unlink()
        code, message = run_pre_hook(
            payload(self.root, "Write", {"file_path": ".github/workflows/ci.yml"})
        )
        self.assertEqual((code, message), (0, ""))

    def test_env_mode_overrides_the_file(self):
        (self.root / ".assaystone" / "policy.json").write_text(
            json.dumps({"mode": "block", "deny_paths": [".github/"]})
        )
        with patch.dict(os.environ, {"ASSAYSTONE_HOOK_MODE": "warn"}, clear=False):
            code, _ = run_pre_hook(
                payload(self.root, "Write", {"file_path": ".github/workflows/ci.yml"})
            )
        self.assertEqual(code, 0)

    def test_installer_adds_pretooluse_and_a_starter_policy(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = Path(tmp) / "project" / ".claude" / "settings.local.json"
            target, changed = install_claude_code(settings, mode="block")
            self.assertTrue(changed)
            data = json.loads(target.read_text(encoding="utf-8"))
            groups = data["hooks"]["PreToolUse"]
            self.assertEqual(groups[0]["matcher"], "*")
            self.assertIn("claude-code-pre", groups[0]["hooks"][0]["command"])
            policy = Path(tmp) / "project" / ".assaystone" / "policy.json"
            self.assertTrue(policy.exists())
            _, unchanged = install_claude_code(settings, mode="block")
            self.assertFalse(unchanged)

    def test_cli_blocks_with_exit_two(self):
        proc = subprocess.run(
            [sys.executable, "-m", "assaystone", "hook", "claude-code-pre"],
            input=json.dumps(
                payload(self.root, "Write", {"file_path": ".github/workflows/ci.yml"})
            ),
            cwd=REPO,
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 2, proc.stderr)
        self.assertIn("denied", proc.stderr)


if __name__ == "__main__":
    unittest.main()
