"""The acceptance-plane demo runs end to end without touching the repo."""

import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from assaystone import cli, demo, trail


class PlaneDemoTest(unittest.TestCase):
    def test_demo_shows_pass_fail_approval_and_tamper(self):
        with tempfile.TemporaryDirectory() as tmp:
            text = demo.run_plane(tmp)
            self.assertIn("acceptance plane", text)
            self.assertIn("shadow: pass", text)
            self.assertIn("publish-approved", text)
            self.assertIn("parity:", text)
            self.assertIn("shadow: fail", text)
            self.assertIn("canary without the owner approval:", text)
            self.assertIn("escalate", text)
            self.assertIn("merge_allowed=True", text)
            self.assertIn("production, chained to the canary entry", text)
            self.assertIn("deploy_allowed=True", text)
            self.assertIn("chain broken", text)
            trail_path = Path(tmp) / "plane-demo-trail.jsonl"
            self.assertTrue(trail.verify(trail_path).ok)

    def test_cli_demo_plane(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = cli.main(["demo", "plane", "--output-dir", tmp])
            self.assertEqual(code, 0)
            self.assertIn("acceptance plane", out.getvalue())


if __name__ == "__main__":
    unittest.main()
