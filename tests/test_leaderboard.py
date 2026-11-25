"""The leaderboard puts several contracts on one comparable page."""

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from assaystone import cli
from assaystone.leaderboard import LeaderboardError, run_leaderboard

REPO = Path(__file__).resolve().parent.parent
CODE = REPO / "examples" / "code_agent"


def one_entry_manifest(root: Path) -> Path:
    path = root / "leaderboard.json"
    path.write_text(
        json.dumps(
            {
                "name": "test",
                "entries": [
                    {
                        "name": "code/hardened",
                        "contract": str(CODE / "contracts" / "hardened.json"),
                        "traces": str(CODE / "traces"),
                        "baseline": str(CODE / "baseline"),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


class LeaderboardTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.board = run_leaderboard(REPO / "benchmarks" / "leaderboard.json")
        cls.by_name = {entry.name: entry for entry in cls.board.entries}

    def test_builtin_manifest_compares_contracts(self):
        self.assertEqual(len(self.board.entries), 6)
        self.assertTrue(self.by_name["code/hardened"].card.ok)
        self.assertFalse(self.by_name["code/naive"].card.ok)
        self.assertTrue(self.by_name["ops/hardened"].card.ok)
        self.assertFalse(self.by_name["ops/amount-only"].card.ok)
        self.assertTrue(self.by_name["data/hardened"].card.ok)
        self.assertTrue(self.by_name["research/hardened"].card.ok)

    def test_markdown_has_every_entry_and_the_tradeoff(self):
        text = self.board.to_markdown()
        self.assertIn("# Leaderboard: built-in contracts", text)
        for entry in self.board.entries:
            self.assertIn(f"`{entry.name}`", text)
        self.assertIn("NEEDS WORK", text)
        self.assertIn("## How to read this", text)

    def test_json_shape(self):
        data = json.loads(json.dumps(self.board.to_dict()))
        self.assertEqual(len(data["entries"]), 6)
        self.assertEqual(data["entries"][0]["domain"], "code")
        self.assertIn("coverage", data["entries"][0]["card"])

    def test_unknown_contract_is_an_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "leaderboard.json"
            path.write_text(
                json.dumps(
                    {
                        "name": "bad",
                        "entries": [{"name": "bad", "contract": "missing.json"}],
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaises(LeaderboardError):
                run_leaderboard(path)


class LeaderboardCliTest(unittest.TestCase):
    def test_cli_summary_and_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest = one_entry_manifest(Path(tmp))
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = cli.main(
                    ["leaderboard", "--manifest", str(manifest), "--stdout", "summary"]
                )
            self.assertEqual(code, 0)
            self.assertIn("code/hardened", out.getvalue())

            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = cli.main(
                    ["leaderboard", "--manifest", str(manifest), "--stdout", "json"]
                )
            self.assertEqual(code, 0)
            self.assertEqual(len(json.loads(out.getvalue())["entries"]), 1)


if __name__ == "__main__":
    unittest.main()
