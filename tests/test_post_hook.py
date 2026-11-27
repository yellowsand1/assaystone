"""The PostToolUse hook: check what the action produced, then feed it back."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from assaystone.hooks.claude_code import install_claude_code, run_post_hook

REPO = Path(__file__).resolve().parent.parent


def payload(root: Path, tool: str, args: dict, response=None) -> dict:
    return {
        "hook_event_name": "PostToolUse",
        "session_id": "s1",
        "cwd": str(root),
        "tool_name": tool,
        "tool_input": args,
        "tool_response": response or {},
    }


class PostHookTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / ".assaystone").mkdir()
        (self.root / ".assaystone" / "policy.json").write_text(
            json.dumps({"mode": "block"}), encoding="utf-8"
        )

    def tearDown(self):
        self._tmp.cleanup()

    def test_invalid_python_is_fed_back(self):
        (self.root / "bad.py").write_text("def broken(:\n", encoding="utf-8")
        code, message = run_post_hook(
            payload(self.root, "Write", {"file_path": "bad.py", "content": "def broken(:\n"})
        )
        self.assertEqual(code, 2)
        self.assertIn("syntax error", message)
        record = (self.root / ".assaystone" / "session.jsonl").read_text(encoding="utf-8")
        entry = json.loads(record.splitlines()[0])
        self.assertEqual(entry["phase"], "post")
        self.assertEqual(entry["decision"], "deny")

    def test_valid_python_passes(self):
        (self.root / "ok.py").write_text("def fine():\n    return 1\n", encoding="utf-8")
        code, message = run_post_hook(
            payload(self.root, "Write", {"file_path": "ok.py", "content": "def fine():\n    return 1\n"})
        )
        self.assertEqual((code, message), (0, ""))

    def test_a_secret_in_the_written_content_is_caught(self):
        secret = "AKIAABCDEFGHIJKLMNOP"
        (self.root / "conf.py").write_text(f"KEY = '{secret}'\n", encoding="utf-8")
        code, message = run_post_hook(
            payload(
                self.root,
                "Write",
                {"file_path": "conf.py", "content": f"KEY = '{secret}'\n"},
            )
        )
        self.assertEqual(code, 2)
        self.assertIn("aws_access_key", message)

    def test_warn_mode_reports_without_blocking(self):
        (self.root / ".assaystone" / "policy.json").write_text(
            json.dumps({"mode": "warn"}), encoding="utf-8"
        )
        (self.root / "bad.py").write_text("def broken(:\n", encoding="utf-8")
        code, message = run_post_hook(
            payload(self.root, "Write", {"file_path": "bad.py", "content": "def broken(:\n"})
        )
        self.assertEqual(code, 0)
        self.assertIn("syntax error", message)

    def test_without_a_policy_it_is_passive(self):
        (self.root / ".assaystone" / "policy.json").unlink()
        code, message = run_post_hook(
            payload(self.root, "Write", {"file_path": "bad.py", "content": "def broken(:\n"})
        )
        self.assertEqual((code, message), (0, ""))

    def test_installer_adds_pretooluse_and_posttooluse(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = Path(tmp) / "project" / ".claude" / "settings.local.json"
            target, _ = install_claude_code(settings, mode="block")
            hooks = json.loads(target.read_text(encoding="utf-8"))["hooks"]
            self.assertIn("PreToolUse", hooks)
            self.assertIn("PostToolUse", hooks)
            self.assertIn("claude-code-post", hooks["PostToolUse"][0]["hooks"][0]["command"])

    def test_cli_blocks_with_exit_two(self):
        (self.root / "bad.py").write_text("def broken(:\n", encoding="utf-8")
        proc = subprocess.run(
            [sys.executable, "-m", "assaystone", "hook", "claude-code-post"],
            input=json.dumps(
                payload(self.root, "Write", {"file_path": "bad.py", "content": "def broken(:\n"})
            ),
            cwd=REPO,
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 2, proc.stderr)
        self.assertIn("syntax error", proc.stderr)


if __name__ == "__main__":
    unittest.main()
