"""Two domains, one core: a Java change and a refund request."""

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from assaystone.plane import (
    ORACLE_TYPES,
    CapabilityManifest,
    evaluate_gate,
)

REPO = Path(__file__).resolve().parent.parent
CAPABILITIES = REPO / "examples" / "capability"
JAVA = CAPABILITIES / "java_local.json"
SUPPORT = CAPABILITIES / "support.json"


class JavaVerticalTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = CapabilityManifest.load(JAVA)

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name) / "project"
        shutil.copytree(CAPABILITIES / "java_project", self.root)

    def _git_branch(self):
        subprocess.run(["git", "init", "-q"], cwd=self.root, check=True)
        subprocess.run(
            [
                "git",
                "-c",
                "user.email=a@b.c",
                "-c",
                "user.name=t",
                "commit",
                "--allow-empty",
                "-qm",
                "init",
            ],
            cwd=self.root,
            check=True,
        )
        subprocess.run(
            ["git", "checkout", "-q", "-b", "feat/test"], cwd=self.root, check=True
        )

    @unittest.skipUnless(
        shutil.which("javac") and shutil.which("git"), "javac and git are required"
    )
    def test_shadow_passes_and_cannot_merge(self):
        self._git_branch()
        result = evaluate_gate(self.manifest, "shadow", self.root)
        self.assertEqual(result.outcome, "pass", result.reasons)
        self.assertFalse(result.merge_allowed)
        self.assertTrue((self.root / "out" / "com" / "example" / "App.class").exists())

    @unittest.skipUnless(
        shutil.which("javac") and shutil.which("git"), "javac and git are required"
    )
    def test_canary_requires_reviewer_approval(self):
        self._git_branch()
        result = evaluate_gate(self.manifest, "canary", self.root)
        self.assertEqual(result.outcome, "pass", result.reasons)
        self.assertTrue(result.merge_allowed)


class SupportVerticalTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = CapabilityManifest.load(SUPPORT)

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name) / "project"
        shutil.copytree(CAPABILITIES / "support_project", self.root)

    def test_shadow_passes(self):
        result = evaluate_gate(self.manifest, "shadow", self.root)
        self.assertEqual(result.outcome, "pass", result.reasons)
        self.assertFalse(result.merge_allowed)

    def test_canary_passes_with_approval(self):
        result = evaluate_gate(self.manifest, "canary", self.root)
        self.assertEqual(result.outcome, "pass", result.reasons)
        self.assertTrue(result.merge_allowed)

    def test_canary_escalates_without_approval(self):
        (self.root / "approvals.json").unlink()
        result = evaluate_gate(self.manifest, "canary", self.root)
        self.assertEqual(result.outcome, "escalate")
        self.assertFalse(result.merge_allowed)


class AdaptationTest(unittest.TestCase):
    def test_both_domains_use_the_same_primitives(self):
        for path in (JAVA, SUPPORT):
            manifest = CapabilityManifest.load(path)
            for oracle in manifest.oracles:
                self.assertIn(oracle.type, ORACLE_TYPES, oracle.id)
        self.assertTrue((CAPABILITIES / "java.json").exists())
        self.assertTrue((CAPABILITIES / "java_local.json").exists())

    def test_maven_template_is_valid(self):
        manifest = CapabilityManifest.load(CAPABILITIES / "java.json")
        self.assertEqual(manifest.capability, "java-change")
        maven = next(item for item in manifest.oracles if item.id == "compile")
        self.assertEqual(maven.type, "command")
        self.assertIn("mvn", maven.payload["command"])


if __name__ == "__main__":
    unittest.main()
