"""A team view across several repositories, still one local command."""

import contextlib
import io
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from assaystone import cli, trail
from assaystone.plane import CapabilityManifest, evaluate_gate
from assaystone.portfolio import build_portfolio, load_index, render_portfolio


def make_repo(root: Path, capability: str, command: str):
    (root / ".assaystone").mkdir(parents=True)
    (root / "app.py").write_text("x = 1\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    subprocess.run(
        ["git", "-c", "user.email=a@b.c", "-c", "user.name=t",
         "commit", "-qm", "one"],
        cwd=root,
        check=True,
    )
    data = {
        "capability": capability,
        "owner": "platform",
        "systems": ["git"],
        "data_classes": [],
        "irreversible_actions": [],
        "risk": "medium",
        "lifecycle": "shadow",
        "criteria": [],
        "oracles": [
            {"id": "check", "type": "command", "payload": {"command": [command]}}
        ],
        "policies": {"shadow": {"require": ["check"], "allow_merge": False}},
    }
    path = root / ".assaystone" / "capability.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    manifest = CapabilityManifest.load(path)
    trail.append(
        path.parent / "trail.jsonl",
        evaluate_gate(manifest, "shadow", root),
        actor="ci",
        at="2026-11-25T00:00:00Z",
    )
    return path


class MultiRepoTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.api = self.root / "api"
        self.worker = self.root / "worker"
        make_repo(self.api, "api-svc", "true")
        make_repo(self.worker, "worker-svc", "false")

    def test_several_roots_are_aggregated_with_a_repo_column(self):
        portfolio = build_portfolio([self.api, self.worker])
        self.assertEqual(len(portfolio.entries), 2)
        text = render_portfolio(portfolio)
        self.assertIn("repo", text)
        self.assertIn("api-svc", text)
        self.assertIn("worker-svc", text)
        self.assertEqual(portfolio.critical_count(), 1)

    def test_a_single_root_has_no_repo_column(self):
        text = render_portfolio(build_portfolio(self.api))
        self.assertNotIn("repo  ", text)
        self.assertIn("api-svc", text)

    def test_the_same_root_twice_is_counted_once(self):
        portfolio = build_portfolio([self.api, self.api])
        self.assertEqual(len(portfolio.entries), 1)
        self.assertEqual(len(portfolio.roots), 1)

    def test_an_index_resolves_relative_roots(self):
        index = self.root / "index.json"
        index.write_text(json.dumps({"roots": ["api", "worker"]}),
                         encoding="utf-8")
        roots = load_index(index)
        self.assertEqual([item.name for item in roots], ["api", "worker"])
        portfolio = build_portfolio(roots)
        self.assertEqual(len(portfolio.entries), 2)

    def test_a_bad_index_is_rejected(self):
        index = self.root / "index.json"
        index.write_text("{}", encoding="utf-8")
        with self.assertRaises(ValueError):
            load_index(index)
        index.write_text("{not json", encoding="utf-8")
        with self.assertRaises(ValueError):
            load_index(index)

    def run_cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(["capability", "list", *args])
        return code, out.getvalue(), err.getvalue()

    def test_cli_index_and_strict(self):
        index = self.root / "index.json"
        index.write_text(json.dumps({"roots": ["api", "worker"]}),
                         encoding="utf-8")
        code, out, _ = self.run_cli("--index", str(index))
        self.assertEqual(code, 0)
        self.assertIn("worker-svc", out)
        self.assertNotIn("assaystone-repository", out)

        code, _, _ = self.run_cli("--index", str(index), "--strict")
        self.assertEqual(code, 1)

    def test_cli_repeated_roots(self):
        code, out, _ = self.run_cli(
            "--root", str(self.api), "--root", str(self.worker), "--json"
        )
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertEqual(len(payload["capabilities"]), 2)
        self.assertEqual(payload["critical"], 1)
        self.assertEqual(len(payload["roots"]), 2)

    def test_cli_rejects_a_broken_index(self):
        index = self.root / "index.json"
        index.write_text("{not json", encoding="utf-8")
        code, _, err = self.run_cli("--index", str(index))
        self.assertEqual(code, 2)
        self.assertIn("invalid index", err)


if __name__ == "__main__":
    unittest.main()
