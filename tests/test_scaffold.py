"""capability init: drafting a manifest from a repository."""

import contextlib
import io
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from assaystone import cli
from assaystone.plane import CapabilityManifest
from assaystone.scaffold import (
    ScaffoldError,
    build_manifest,
    detect,
    init_capability,
    next_steps,
)


class ScaffoldTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def touch(self, *parts):
        path = self.root.joinpath(*parts)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")
        return path

    def test_maven_with_tests(self):
        self.touch("pom.xml")
        self.touch("src/main/java/com/example/App.java")
        self.touch("src/test/java/com/example/AppTest.java")
        data, detection = build_manifest(self.root, owner="platform-team")
        self.assertEqual(detection.stack, "maven")
        ids = [item["id"] for item in data["oracles"]]
        self.assertEqual(ids, ["build", "tests", "artifact"])
        self.assertIn("mvn", data["oracles"][0]["payload"]["command"])
        self.assertIn("target/classes", data["oracles"][2]["payload"]["path"])
        manifest = CapabilityManifest.from_dict(data)
        self.assertEqual(manifest.owner, "platform-team")
        self.assertEqual(manifest.lifecycle, "design")

    def test_maven_without_tests_has_no_test_oracle(self):
        self.touch("pom.xml")
        data, _ = build_manifest(self.root)
        ids = [item["id"] for item in data["oracles"]]
        self.assertNotIn("tests", ids)

    def test_maven_wrapper_is_used(self):
        self.touch("pom.xml")
        self.touch("mvnw")
        data, detection = build_manifest(self.root)
        self.assertEqual(data["oracles"][0]["payload"]["command"][0], "./mvnw")
        self.assertTrue(any("wrapper" in note for note in detection.notes))

    def test_gradle_kotlin_layout(self):
        self.touch("build.gradle.kts")
        self.touch("src/main/kotlin/App.kt")
        data, detection = build_manifest(self.root)
        self.assertEqual(detection.stack, "gradle")
        self.assertEqual(
            data["oracles"][0]["payload"]["command"][-1], "compileKotlin"
        )
        self.assertEqual(
            data["oracles"][1]["payload"]["path"], "build/classes/kotlin/main"
        )

    def test_node_uses_declared_scripts(self):
        (self.root / "package.json").write_text(
            json.dumps({"scripts": {"build": "tsc", "test": "vitest run"}}),
            encoding="utf-8",
        )
        data, detection = build_manifest(self.root)
        self.assertEqual(detection.stack, "node")
        ids = [item["id"] for item in data["oracles"]]
        self.assertEqual(ids, ["build", "tests"])

    def test_node_without_scripts_is_rejected(self):
        (self.root / "package.json").write_text("{}", encoding="utf-8")
        with self.assertRaises(ScaffoldError):
            detect(self.root)

    def test_python_needs_tests(self):
        self.touch("pyproject.toml")
        with self.assertRaises(ScaffoldError):
            detect(self.root)
        self.touch("tests/test_app.py")
        data, detection = build_manifest(self.root)
        self.assertEqual(detection.stack, "python")
        self.assertEqual(data["oracles"][0]["id"], "tests")
        self.assertIn("pytest", data["oracles"][0]["payload"]["command"])

    def test_unknown_repository_is_rejected(self):
        with self.assertRaises(ScaffoldError) as caught:
            detect(self.root)
        self.assertIn("no recognized", str(caught.exception))

    def test_draft_makes_no_unchecked_rollback_claim(self):
        self.touch("pom.xml")
        data, _ = build_manifest(self.root)
        production = data["policies"]["production"]
        self.assertNotIn("rollback_required", production)
        self.assertNotIn("rollback", production)
        self.assertNotIn("approvals", production)
        self.assertTrue(next_steps(data))

    @unittest.skipUnless(shutil.which("git"), "git is required")
    def test_branch_convention_is_detected(self):
        self.touch("pom.xml")
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
            ["git", "checkout", "-q", "-b", "feat/pricing"], cwd=self.root, check=True
        )
        data, _ = build_manifest(self.root)
        branch = next(item for item in data["oracles"] if item["id"] == "branch")
        self.assertEqual(branch["payload"]["expected"], "feat/")

    def test_no_git_means_no_branch_oracle(self):
        self.touch("pom.xml")
        data, _ = build_manifest(self.root)
        self.assertNotIn("branch", [item["id"] for item in data["oracles"]])

    def test_existing_manifest_needs_force(self):
        self.touch("pom.xml")
        target, _, _ = init_capability(self.root)
        with self.assertRaises(ScaffoldError):
            init_capability(self.root)
        _, _, _ = init_capability(self.root, force=True)
        loaded = CapabilityManifest.load(target)
        self.assertEqual(loaded.capability, Path(self.root).name.replace("_", "-"))

    def test_cli_init_json(self):
        self.touch("pom.xml")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cli.main(
                [
                    "capability",
                    "init",
                    "--root",
                    str(self.root),
                    "--owner",
                    "platform-team",
                    "--json",
                ]
            )
        self.assertEqual(code, 0)
        payload = json.loads(out.getvalue())
        self.assertEqual(payload["stack"], "maven")
        self.assertEqual(payload["manifest"]["owner"], "platform-team")
        manifest_path = Path(payload["path"])
        self.assertTrue(manifest_path.exists())
        self.assertEqual(
            CapabilityManifest.load(manifest_path).oracles[0].id, "build"
        )

    def test_cli_init_on_an_unknown_repo_fails(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code = cli.main(
                ["capability", "init", "--root", str(self.root)]
            )
        self.assertEqual(code, 1)
        self.assertIn("no recognized", err.getvalue())


if __name__ == "__main__":
    unittest.main()
