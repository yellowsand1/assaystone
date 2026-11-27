"""Agents work in task workspaces; the transcript cwd is not always the repo."""

import tempfile
import unittest
from pathlib import Path

from assaystone.replay import (
    artifacts_with_fallback,
    infer_workspace_root,
    replay_tool_calls,
    touched_paths,
)


def make(root: Path, files: dict[str, str]) -> None:
    for relative, content in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


class WorkspaceRootTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        base = Path(self._tmp.name)
        self.baseline = base / "baseline"
        self.workspace = base / "workspace"
        self.baseline.mkdir()
        self.workspace.mkdir()
        (self.workspace / ".git").mkdir()
        make(
            self.baseline,
            {"pyproject.toml": "[project]\n", "src/app.py": "value = 'old'\n"},
        )
        make(
            self.workspace,
            {
                "pyproject.toml": "[project]\n",
                "src/app.py": "value = 'new'\n",
                "tests/test_new.py": "def test_x():\n    assert True\n",
            },
        )
        self.calls = [
            (
                "Write",
                {
                    "file_path": str(self.workspace / "tests/test_new.py"),
                    "content": "def test_x():\n    assert True\n",
                },
            ),
            (
                "Edit",
                {
                    "file_path": str(self.workspace / "src/app.py"),
                    "old_string": "old",
                    "new_string": "new",
                },
            ),
        ]

    def tearDown(self):
        self._tmp.cleanup()

    def test_infers_the_workspace_from_absolute_paths(self):
        self.assertEqual(infer_workspace_root(self.calls, "."), self.workspace.resolve())

    def test_relative_paths_stay_relative(self):
        self.assertEqual(infer_workspace_root([("Edit", {"file_path": "x.py"})], self.baseline),
                         self.baseline.resolve())

    def test_paths_are_mapped_against_the_workspace_root(self):
        touched = touched_paths(self.calls, self.baseline, root=self.workspace)
        self.assertEqual(touched, {"src/app.py", "tests/test_new.py"})

    def test_replay_reads_the_baseline_and_maps_the_workspace(self):
        artifacts = replay_tool_calls(self.calls, self.baseline, root=self.workspace)
        by_path = {artifact.path: artifact.change for artifact in artifacts}
        self.assertEqual(by_path["src/app.py"], "modified")
        self.assertEqual(by_path["tests/test_new.py"], "added")

    def test_fallback_reads_the_workspace_and_keeps_added_status(self):
        partial = replay_tool_calls(
            [self.calls[1]], self.baseline, root=self.workspace
        )
        artifacts = artifacts_with_fallback(
            self.calls,
            self.baseline,
            partial,
            root=self.workspace,
            workspace=self.workspace,
        )
        by_path = {artifact.path: artifact.change for artifact in artifacts}
        self.assertEqual(by_path["tests/test_new.py"], "added")
        self.assertEqual(by_path["src/app.py"], "modified")


if __name__ == "__main__":
    unittest.main()
