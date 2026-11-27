import tempfile
import unittest
from pathlib import Path

from assaystone import demo


class DemoTest(unittest.TestCase):
    def test_code_demo(self):
        with tempfile.TemporaryDirectory() as tmp:
            text = demo.run_code(tmp)
            self.assertIn("code/test verifier pack", text)
            self.assertTrue((Path(tmp) / "assaystone-demo-code.md").exists())

    def test_ops_demo(self):
        with tempfile.TemporaryDirectory() as tmp:
            text = demo.run_ops(tmp)
            self.assertIn("runtime gate", text)
            self.assertIn("blocked", text)
            self.assertTrue((Path(tmp) / "assaystone-demo-ops.md").exists())

    def test_audit_demo(self):
        with tempfile.TemporaryDirectory() as tmp:
            text = demo.run_audit(tmp)
            self.assertIn("tests.integrity", text)
            self.assertTrue((Path(tmp) / "assaystone-demo-audit.md").exists())
            self.assertTrue((Path(tmp) / "assaystone-demo-contract.json").exists())

    def test_adversarial_demo_shows_the_trap(self):
        with tempfile.TemporaryDirectory() as tmp:
            text = demo.run_adversarial(tmp)
            self.assertIn("the trap", text)
            self.assertIn("naive", text)
            self.assertIn("tests.harness_integrity", text)
            self.assertTrue(
                (Path(tmp) / "assaystone-demo-adversarial.md").exists()
            )


if __name__ == "__main__":
    unittest.main()
