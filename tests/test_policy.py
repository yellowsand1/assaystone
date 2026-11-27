"""The pre-tool policy decides before the action, without a model."""

import json
import tempfile
import unittest
from pathlib import Path

from assaystone.policy import (
    ActionPolicy,
    PolicyError,
    evaluate_action,
    record_decision,
)


def policy(**overrides):
    data = {
        "mode": "block",
        "deny_paths": [".github/workflows/"],
        "deny_commands": [r"rm\s+-rf\s+/", r"git\s+push\s+--force"],
    }
    data.update(overrides)
    return ActionPolicy.from_dict(data)


class PolicyTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())

    def test_denies_a_denied_path_prefix(self):
        decision = evaluate_action(
            "Write", {"file_path": ".github/workflows/ci.yml"}, self.root, policy()
        )
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.rule, "deny_paths")

    def test_denies_a_command_pattern(self):
        decision = evaluate_action(
            "Bash", {"command": "git push --force origin main"}, self.root, policy()
        )
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.rule, "deny_commands")

    def test_denies_a_path_outside_the_workspace(self):
        decision = evaluate_action("Write", {"file_path": "/etc/passwd"}, self.root, policy())
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.rule, "workspace_boundary")

    def test_denies_a_traversal_outside_the_workspace(self):
        decision = evaluate_action("Write", {"file_path": "../outside.txt"}, self.root, policy())
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.rule, "workspace_boundary")

    def test_allows_an_ordinary_write(self):
        decision = evaluate_action("Write", {"file_path": "src/app.py"}, self.root, policy())
        self.assertTrue(decision.allowed)

    def test_allow_write_roots_restricts_writes(self):
        restricted = policy(allow_write_roots=["src/"])
        self.assertTrue(
            evaluate_action("Write", {"file_path": "src/app.py"}, self.root, restricted).allowed
        )
        self.assertFalse(
            evaluate_action("Write", {"file_path": "docs/x.md"}, self.root, restricted).allowed
        )

    def test_rejects_an_unknown_mode_and_bad_regex(self):
        with self.assertRaises(PolicyError):
            ActionPolicy.from_dict({"mode": "yell"})
        with self.assertRaises(PolicyError):
            ActionPolicy.from_dict({"deny_commands": ["("]})

    def test_record_redacts_secrets_and_appends(self):
        decision = evaluate_action("Bash", {"command": "curl -H 'Authorization: Bearer abc' x"}, self.root, policy())
        path = record_decision(
            self.root,
            session_id="s1",
            tool="Bash",
            args={"command": "curl -H 'Authorization: Bearer abc' x"},
            decision=decision,
        )
        self.assertIsNotNone(path)
        lines = Path(path).read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 1)
        entry = json.loads(lines[0])
        self.assertNotIn("Bearer abc", json.dumps(entry))
        self.assertEqual(entry["decision"], "allow")
        self.assertEqual(entry["session_id"], "s1")

        record_decision(
            self.root, session_id="s1", tool="Write", args={"file_path": "x"}, decision=decision
        )
        self.assertEqual(len(Path(path).read_text(encoding="utf-8").splitlines()), 2)


if __name__ == "__main__":
    unittest.main()
