"""The Stop hook can run the contract itself: the pre-final position."""

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from assaystone.hooks.claude_code import run_hook

CONTRACT = {
    "name": "final",
    "verifiers": [
        {"name": "diff.syntax", "required": True, "params": {}},
        {
            "name": "tests.integrity",
            "required": True,
            "params": {"protected_prefixes": ["tests/"]},
        },
    ],
}


class FinalGateTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "pricing").mkdir()
        (self.root / "tests").mkdir()
        (self.root / ".assaystone").mkdir()
        (self.root / "pricing" / "app.py").write_text(
            "def discount(total):\n    return round(total * 0.9, 2)\n", encoding="utf-8"
        )
        (self.root / "tests" / "__init__.py").write_text("", encoding="utf-8")
        (self.root / "tests" / "test_app.py").write_text(
            "import unittest\n"
            "from pricing.app import discount\n\n"
            "class DiscountTest(unittest.TestCase):\n"
            "    def test_ten(self):\n"
            "        self.assertEqual(discount(100), 90.0)\n\n"
            "    def test_rounding(self):\n"
            "        self.assertEqual(discount(9.99), 8.99)\n",
            encoding="utf-8",
        )
        (self.root / ".assaystone" / "contract.json").write_text(
            json.dumps(CONTRACT), encoding="utf-8"
        )
        (self.root / ".assaystone" / "hook.json").write_text(
            json.dumps(
                {
                    "mode": "block",
                    "gate": {"contract": ".assaystone/contract.json", "base": "HEAD"},
                }
            ),
            encoding="utf-8",
        )
        subprocess.run(
            ["git", "-C", str(self.root), "-c", "user.email=a@b", "-c", "user.name=a", "init", "-q"],
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(self.root), "-c", "user.email=a@b", "-c", "user.name=a", "add", "-A"],
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(self.root), "-c", "user.email=a@b", "-c", "user.name=a", "commit", "-qm", "base"],
            check=True,
        )

    def tearDown(self):
        self._tmp.cleanup()

    def stop(self):
        return run_hook(
            {
                "hook_event_name": "Stop",
                "session_id": "s1",
                "cwd": str(self.root),
                "stop_hook_active": False,
            }
        )

    def certificates(self):
        return sorted((self.root / ".assaystone" / "certificates").glob("*.json"))

    def test_a_deleted_test_blocks_the_stop_and_writes_a_certificate(self):
        path = self.root / "tests" / "test_app.py"
        text = path.read_text()
        path.write_text(text[: text.index("    def test_rounding")], encoding="utf-8")
        code, message = self.stop()
        self.assertEqual(code, 2, message)
        self.assertIn("tests.integrity", message)
        files = self.certificates()
        self.assertEqual(len(files), 1)
        document = json.loads(files[0].read_text())
        self.assertEqual(document["decision"]["verdict"], "fail")
        self.assertEqual(document["subject"]["provenance"]["kind"], "git_worktree")

    def test_a_clean_change_is_silent_and_certified(self):
        path = self.root / "pricing" / "app.py"
        path.write_text(path.read_text() + "\n# a careful change\n", encoding="utf-8")
        code, message = self.stop()
        self.assertEqual((code, message), (0, ""))
        self.assertEqual(len(self.certificates()), 1)

    def test_no_changes_is_silent_and_skipped(self):
        code, message = self.stop()
        self.assertEqual(code, 0)
        self.assertIn("nothing to check", message)

    def test_a_broken_contract_fails_open(self):
        (self.root / ".assaystone" / "contract.json").write_text("{", encoding="utf-8")
        code, message = self.stop()
        self.assertEqual(code, 0)
        self.assertIn("not readable", message)


if __name__ == "__main__":
    unittest.main()
