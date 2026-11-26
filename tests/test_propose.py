"""Criteria proposed from what the repository already contains."""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from assaystone.plane import CapabilityManifest
from assaystone.propose import Proposal, materialise, propose, scan
from assaystone.scaffold import build_manifest, init_capability

REPO = Path(__file__).resolve().parent.parent


def git(root, *args):
    subprocess.run(
        ["git", "-C", str(root), "-c", "user.email=a@b.c",
         "-c", "user.name=t", *args],
        check=True,
        capture_output=True,
    )


class ScanTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def touch(self, *parts):
        path = self.root.joinpath(*parts)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")
        return path

    def test_an_empty_repository_proposes_nothing(self):
        facts = scan(self.root)
        self.assertEqual(propose(facts), [])

    def test_a_maven_library_proposes_an_api_check(self):
        self.touch("pom.xml")
        self.touch("src/main/java/com/x/A.java")
        facts = scan(self.root, stack="maven")
        self.assertTrue(facts.has_java_sources)
        proposals = propose(facts)
        ids = [item.id for item in proposals]
        self.assertIn("api-unchanged", ids)
        api = next(item for item in proposals if item.id == "api-unchanged")
        self.assertEqual(api.oracle["type"], "command")
        self.assertIn("java_api_diff.py", api.oracle["payload"]["command"][1])
        self.assertIn("downstream", api.why)

    def test_tests_ci_dependencies_and_migrations_are_detected(self):
        self.touch("tests/test_app.py")
        self.touch(".github/workflows/ci.yml")
        self.touch("package.json")
        self.touch("db/migration/V1__a.sql")
        facts = scan(self.root)
        self.assertTrue(facts.has_tests)
        self.assertTrue(facts.has_ci)
        self.assertTrue(facts.has_dependency_manifest)
        self.assertEqual(facts.migration_dirs, ["db/migration"])
        ids = {item.id for item in propose(facts)}
        self.assertEqual(
            ids,
            {"tests-intact", "ci-intact", "deps-unchanged",
             "migrations-reversible"},
        )

    def test_a_python_package_is_detected(self):
        self.touch("mypkg/__init__.py")
        facts = scan(self.root)
        self.assertTrue(facts.has_python_package)


class MaterialiseTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def test_helpers_are_written_once(self):
        proposals = [
            Proposal(
                id="deps-unchanged", kind="invariant", statement="x",
                severity="high",
                oracle={"id": "deps", "type": "command", "payload": {}},
                why="y", helper="deps_diff.py",
            )
        ]
        first = materialise(self.root, proposals)
        self.assertEqual(len(first), 1)
        self.assertTrue(first[0].exists())
        self.assertEqual(materialise(self.root, proposals), [])


class HelperScriptTest(unittest.TestCase):
    """The generated payloads have to work, or the proposal is theatre."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        subprocess.run(["git", "init", "-q"], cwd=self.root, check=True)
        self.proposals = [
            Proposal(
                id=name, kind="invariant", statement=name, severity="high",
                oracle={"id": name, "type": "command", "payload": {}},
                why="test", helper=helper,
            )
            for name, helper in (
                ("deps-unchanged", "deps_diff.py"),
                ("migrations-reversible", "migrations_down.py"),
            )
        ]
        materialise(self.root, self.proposals)

    def run_helper(self, name):
        return subprocess.run(
            [sys.executable, f".assaystone/checks/{name}"],
            cwd=self.root, capture_output=True, text=True,
        )

    def test_dependency_diff_catches_a_new_dependency(self):
        (self.root / "pom.xml").write_text(
            "<project></project>", encoding="utf-8"
        )
        git(self.root, "add", "-A")
        git(self.root, "commit", "-qm", "one")
        self.assertEqual(self.run_helper("deps_diff.py").returncode, 0)
        (self.root / "pom.xml").write_text(
            "<project><dependencies><dependency>"
            "<artifactId>sneaky</artifactId></dependency></dependencies>"
            "</project>",
            encoding="utf-8",
        )
        result = self.run_helper("deps_diff.py")
        self.assertEqual(result.returncode, 1)
        self.assertIn("sneaky", result.stdout)

    def test_migration_down_catches_both_tracked_and_untracked(self):
        (self.root / "db/migration").mkdir(parents=True)
        good = self.root / "db/migration" / "V1__ok.sql"
        good.write_text("-- up\ncreate table t(id int);\n-- down\ndrop table t;\n",
                        encoding="utf-8")
        git(self.root, "add", "-A")
        git(self.root, "commit", "-qm", "one")
        self.assertEqual(self.run_helper("migrations_down.py").returncode, 0)

        (self.root / "db/migration" / "V2__bad.sql").write_text(
            "-- up\ncreate table u(id int);\n", encoding="utf-8"
        )
        result = self.run_helper("migrations_down.py")
        self.assertEqual(result.returncode, 1)
        self.assertIn("V2__bad.sql", result.stdout)


class DraftTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        (self.root / "pom.xml").write_text(
            "<project><packaging>jar</packaging></project>", encoding="utf-8"
        )
        (self.root / "src/main/java/com/x").mkdir(parents=True)
        (self.root / "src/main/java/com/x/A.java").write_text(
            "class A{}", encoding="utf-8"
        )
        (self.root / "src/test/java").mkdir(parents=True)
        (self.root / "db/migration").mkdir(parents=True)
        subprocess.run(["git", "init", "-q"], cwd=self.root, check=True)

    def test_the_draft_gates_the_proposed_criteria(self):
        data, detection = build_manifest(self.root, owner="team")
        criteria = {item["id"]: item for item in data["criteria"]}
        self.assertIn("api-unchanged", criteria)
        self.assertIn("tests-intact", criteria)
        self.assertIn("migrations-reversible", criteria)
        required = set(data["policies"]["shadow"]["require"])
        for item in data["criteria"]:
            self.assertIn(item["oracle"], required)
        CapabilityManifest.from_dict(data)
        self.assertTrue(detection.proposals)

    def test_init_writes_the_helper_scripts(self):
        path, data, detection = init_capability(self.root, owner="team")
        helpers = {Path(item).name for item in detection.helpers}
        self.assertIn("java_api_diff.py", helpers)
        self.assertIn("migrations_down.py", helpers)
        self.assertTrue(
            (self.root / ".assaystone/checks/java_api_diff.py").exists()
        )
        CapabilityManifest.load(path)

    def test_a_repository_with_nothing_gets_no_proposals(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "go.mod").write_text("module x\n", encoding="utf-8")
            data, detection = build_manifest(root, owner="team")
        self.assertEqual(detection.proposals, [])
        self.assertEqual(
            [item["id"] for item in data["criteria"]],
            ["tests"] if any(o["id"] == "tests" for o in data["oracles"]) else [],
        )


if __name__ == "__main__":
    unittest.main()
