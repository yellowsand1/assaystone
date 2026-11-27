"""An episode can be reconstructed from git alone: no trace, no instrumentation."""

import contextlib
import io
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from assaystone import cli
from assaystone.episode import EpisodeError, GitEpisode, diff_artifacts, git_root

CONTRACT = {
    "name": "code",
    "test_command": [
        "{python}",
        "-m",
        "unittest",
        "discover",
        "-s",
        "tests",
        "-t",
        ".",
        "-q",
    ],
    "verifiers": [
        {"name": "diff.syntax", "required": True, "params": {}},
        {
            "name": "tests.integrity",
            "required": True,
            "params": {"protected_prefixes": ["tests/"]},
        },
        {"name": "tests.pass", "required": True, "params": {}},
    ],
}


def git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(root), "-c", "user.email=a@b", "-c", "user.name=a", *args],
        check=True,
        capture_output=True,
    )


class Repo:
    def __init__(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "pricing").mkdir()
        (self.root / "tests").mkdir()
        (self.root / ".assaystone").mkdir()
        (self.root / "pricing" / "discounts.py").write_text(
            "def discount(total):\n    return round(total * 0.90, 2)\n"
        )
        (self.root / "tests" / "__init__.py").write_text("")
        (self.root / "tests" / "test_discounts.py").write_text(
            "import unittest\n"
            "from pricing.discounts import discount\n\n"
            "class DiscountTest(unittest.TestCase):\n"
            "    def test_ten_percent(self):\n"
            "        self.assertEqual(discount(100), 90.0)\n\n"
            "    def test_half_cent_rounds(self):\n"
            "        self.assertEqual(discount(9.99), 8.99)\n"
        )
        (self.root / ".assaystone" / "contract.json").write_text(json.dumps(CONTRACT))
        git(self.root, "init", "-q")
        git(self.root, "add", "-A")
        git(self.root, "commit", "-qm", "base")

    def close(self):
        self._tmp.cleanup()

    def delete_a_test(self):
        path = self.root / "tests" / "test_discounts.py"
        text = path.read_text().replace(
            "\n    def test_half_cent_rounds(self):\n"
            "        self.assertEqual(discount(9.99), 8.99)\n",
            "",
        )
        path.write_text(text)

    def fix(self):
        (self.root / "pricing" / "discounts.py").write_text(
            "def discount(total):\n    return round(total * 0.9, 2)\n"
        )


class EpisodeTest(unittest.TestCase):
    def setUp(self):
        self.repo = Repo()

    def tearDown(self):
        self.repo.close()

    def test_git_root_is_found(self):
        self.assertEqual(git_root(self.repo.root), self.repo.root.resolve())

    def test_diff_artifacts_cover_modified_and_untracked(self):
        self.repo.fix()
        (self.repo.root / "NOTES.md").write_text("scratch")
        artifacts, skipped = diff_artifacts(self.repo.root, "HEAD")
        paths = {artifact.path: artifact.change for artifact in artifacts}
        self.assertEqual(paths["pricing/discounts.py"], "modified")
        self.assertEqual(paths["NOTES.md"], "added")
        self.assertEqual(skipped, [])

    def test_episode_is_runtime_sourced_with_provenance(self):
        self.repo.fix()
        with GitEpisode(self.repo.root) as episode:
            self.assertEqual(episode.trace.source, "runtime")
            self.assertTrue(episode.baseline.is_dir())
            self.assertEqual(episode.provenance["kind"], "git_worktree")
            self.assertTrue(episode.provenance["base_sha"])

    def test_no_changes_is_an_explicit_error(self):
        with self.assertRaises(EpisodeError):
            with GitEpisode(self.repo.root):
                pass


class CheckCommandTest(unittest.TestCase):
    def setUp(self):
        self.repo = Repo()

    def tearDown(self):
        self.repo.close()

    def run_check(self, *extra):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cli.main(
                ["check", "--repo", str(self.repo.root), "--base", "HEAD", *extra]
            )
        return code, out.getvalue()

    def test_a_deleted_test_fails_and_the_certificate_records_the_skipped_check(self):
        self.repo.delete_a_test()
        with tempfile.TemporaryDirectory() as certs:
            code, output = self.run_check("--certificate", certs)
            self.assertEqual(code, 1, output)
            self.assertIn("tests.integrity", output)
            files = list(Path(certs).glob("*.certificate.json"))
            self.assertEqual(len(files), 1)
            document = json.loads(files[0].read_text())
        self.assertEqual(document["decision"]["verdict"], "fail")
        self.assertEqual(document["subject"]["provenance"]["kind"], "git_worktree")
        self.assertIn(
            "tests.pass", {item["id"] for item in document["assurance"]["not_run"]}
        )

    def test_a_clean_fix_passes_and_runs_the_suite(self):
        self.repo.fix()
        code, output = self.run_check()
        self.assertEqual(code, 0, output)
        self.assertIn("tests.pass", output)
        self.assertIn("PASS", output)

    def test_json_is_a_certificate(self):
        self.repo.fix()
        code, output = self.run_check("--json")
        self.assertEqual(code, 0, output)
        document = json.loads(output)
        self.assertEqual(document["schema"], "assaystone.certificate/1")
        self.assertEqual(document["decision"]["verdict"], "pass")
        self.assertTrue(document["checks"])


if __name__ == "__main__":
    unittest.main()
