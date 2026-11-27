"""The version, the changelog, and the release notes must agree.

This exists because they did not. The release-prep edit inserted version headers
by matching a fixed string; once the Unreleased section had content the insert
became a silent no-op, and the changelog skipped eight releases. A product about
evidence should check its own claims.
"""

import re
import unittest
from pathlib import Path

import assaystone
from assaystone import init

REPO = Path(__file__).resolve().parent.parent


class ReleaseConsistencyTest(unittest.TestCase):
    def setUp(self):
        self.version = assaystone.__version__
        self.changelog = (REPO / "CHANGELOG.md").read_text(encoding="utf-8")

    def test_pyproject_version_matches_the_package(self):
        try:
            import tomllib
        except ImportError:  # Python 3.10
            text = (REPO / "pyproject.toml").read_text(encoding="utf-8")
            found = re.search(r'^version = "([^"]+)"', text, re.MULTILINE)
            self.assertIsNotNone(found)
            self.assertEqual(found.group(1), self.version)
            return
        data = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))
        self.assertEqual(data["project"]["version"], self.version)

    def test_changelog_has_a_section_for_the_version(self):
        headings = re.findall(r"^## (\d+\.\d+\.\d+)", self.changelog, re.MULTILINE)
        self.assertIn(
            self.version,
            headings,
            f"CHANGELOG.md has no `## {self.version}` section",
        )

    def test_versions_are_descending_and_complete(self):
        headings = re.findall(r"^## (\d+\.\d+\.\d+)", self.changelog, re.MULTILINE)
        keys = [tuple(int(part) for part in item.split(".")) for item in headings]
        self.assertEqual(keys, sorted(keys, reverse=True), "versions out of order")
        numbers = sorted({item for item in headings}, key=lambda v: tuple(
            int(part) for part in v.split(".")
        ))
        missing = [
            item
            for item in numbers
            if item not in headings
        ]
        self.assertEqual(missing, [])

    def test_release_notes_exist_and_name_the_version(self):
        path = REPO / "docs" / "releases" / f"v{self.version}.md"
        self.assertTrue(path.exists(), f"missing {path.relative_to(REPO)}")
        first = path.read_text(encoding="utf-8").splitlines()[0]
        self.assertIn(self.version, first)

    def test_action_reference_matches_the_version(self):
        self.assertEqual(init.ACTION_REF, f"v{self.version}")

    def test_readme_pins_the_action_to_the_version(self):
        readme = (REPO / "README.md").read_text(encoding="utf-8")
        self.assertIn(f"yellowsand1/assaystone@v{self.version}", readme)
        self.assertIn(f"assaystone=={self.version}", readme)

    def test_there_is_an_unreleased_section(self):
        self.assertIn("## Unreleased", self.changelog)


if __name__ == "__main__":
    unittest.main()
