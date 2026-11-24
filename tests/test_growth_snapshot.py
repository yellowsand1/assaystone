"""Offline tests for the dependency-free growth snapshot script.

The script is imported from ``scripts/growth_snapshot.py`` and exercised with a
fixture opener, so no network is touched. Values below are sample fixtures, not
live repository metrics.
"""
from __future__ import annotations

import importlib.util
import json
import sys
import unittest
import urllib.error
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
FIXTURES = REPO / "tests" / "fixtures" / "growth_snapshot"


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "growth_snapshot", REPO / "scripts" / "growth_snapshot.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["growth_snapshot"] = module
    spec.loader.exec_module(module)
    return module


gs = _load_module()


class _Response:
    def __init__(self, path: Path):
        self._path = path
        self.headers = {}

    def read(self) -> bytes:
        return self._path.read_bytes()

    def close(self) -> None:
        pass


class FixtureOpener:
    """Minimal stand-in for ``urllib.request.urlopen`` keyed by URL substring."""

    mapping = {
        "/repos/yellowsand1/assaystone?": None,
        "/repos/yellowsand1/assaystone/releases": "releases.json",
        "/repos/yellowsand1/assaystone/traffic/views": "views.json",
        "/repos/yellowsand1/assaystone/traffic/clones": "clones.json",
        "/repos/yellowsand1/assaystone/traffic/popular/referrers": "referrers.json",
        "/search/issues": "search.json",
        "/api/packages/assaystone/overall": "pypi.json",
    }

    def open(self, req, timeout=gs.DEFAULT_TIMEOUT):
        url = req.full_url
        # The bare repo endpoint has no trailing path.
        if url == f"{gs.GITHUB_API}/repos/yellowsand1/assaystone":
            return _Response(FIXTURES / "repo.json")
        for key, filename in self.mapping.items():
            if key in url:
                return _Response(FIXTURES / filename)
        raise urllib.error.HTTPError(url, 404, "not found", None, None)


class ParsingTests(unittest.TestCase):
    def test_release_count_and_latest(self):
        releases = [{"tag_name": "v0.5.0"}, {"tag_name": "v0.4.1"}]
        self.assertEqual(gs._parse_release_count_and_latest(releases), (2, "v0.5.0", "measured"))
        self.assertEqual(gs._parse_release_count_and_latest([]), (None, "", "unmeasured"))

    def test_sum_14d_total(self):
        payload = {"views": [{"timestamp": "2026-11-23T00:00:00Z", "count": 7}]}
        self.assertEqual(gs._sum_14d_total(payload), (7, 1, "measured"))
        self.assertEqual(gs._sum_14d_total(None), (None, 0, "unmeasured"))

    def test_sum_referrers(self):
        payload = {"data": [{"referrer": "github.com", "count": 5}]}
        self.assertEqual(gs._sum_referrers(payload), (5, "measured"))
        self.assertEqual(gs._sum_referrers({}), (None, "unmeasured"))

    def test_sum_pypi_recent_excludes_mirrors(self):
        payload = {"data": [
            {"category": "without_mirrors", "date": "2026-11-23", "downloads": 10},
            {"category": "with_mirrors", "date": "2026-11-23", "downloads": 999},
        ]}
        self.assertEqual(gs._sum_pypi_recent(payload), (10, 1, "measured"))

    def test_csv_escaping(self):
        self.assertEqual(gs._csv_cell('a,b"c'), '"a,b""c"')
        self.assertEqual(gs._csv_cell(None), "")
        self.assertEqual(gs._csv_cell(7), "7")

    def test_flatten_has_status_for_every_metric(self):
        flat = gs.flatten_snapshot({"stars": {"value": 3, "status": "measured", "source": "github.repo"}})
        self.assertEqual(flat["stars"], 3)
        self.assertEqual(flat["stars_status"], "measured")


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.opener = FixtureOpener()

    def test_build_snapshot_measures_all_fields_offline(self):
        snapshot, meta = gs.build_snapshot(
            "yellowsand1",
            "assaystone",
            token="secret-token-must-not-leak",
            pypi="assaystone",
            fetched_at="2026-11-24T12:00:00+00:00",
            opener=self.opener,
        )
        self.assertEqual(snapshot["stars"]["value"], 42)
        self.assertEqual(snapshot["stars"]["status"], "measured")
        self.assertEqual(snapshot["forks"]["value"], 5)
        self.assertEqual(snapshot["watchers"]["value"], 9)
        self.assertEqual(snapshot["open_issues"]["value"], 4)
        self.assertEqual(snapshot["open_pull_requests"]["value"], 1)
        self.assertEqual(snapshot["open_pull_requests"]["status"], "measured")
        self.assertEqual(snapshot["release_count"]["value"], 2)
        self.assertEqual(snapshot["latest_release"]["value"], "v0.5.0")
        self.assertEqual(snapshot["views_14d"]["value"], 98)  # 14 days x 7
        self.assertEqual(snapshot["clones_14d"]["value"], 42)  # 14 days x 3
        self.assertEqual(snapshot["referrers_14d"]["value"], 7)
        self.assertEqual(snapshot["pypi_downloads_14d"]["value"], 140)  # 14 days x 10
        self.assertEqual(meta["repository"], "yellowsand1/assaystone")
        # The token must never reach the output.
        rendered = json.dumps(snapshot) + json.dumps(meta)
        self.assertNotIn("secret-token-must-not-leak", rendered)

    def test_every_metric_has_a_status(self):
        snapshot, _ = gs.build_snapshot(
            "yellowsand1", "assaystone", pypi="assaystone",
            fetched_at="2026-11-24T12:00:00+00:00", opener=self.opener,
        )
        metric_keys = {
            "stars", "forks", "watchers", "open_issues", "open_pull_requests",
            "release_count", "latest_release", "views_14d", "clones_14d",
            "referrers_14d", "pypi_downloads_14d",
        }
        for key in metric_keys:
            self.assertIn(key, snapshot)
            self.assertIn("status", snapshot[key])
            self.assertIn(snapshot[key]["status"], {"measured", "proxy", "unmeasured"})

    def test_network_failure_degrades_to_unmeasured(self):
        class BrokenOpener:
            def open(self, req, timeout=gs.DEFAULT_TIMEOUT):
                raise urllib.error.URLError("offline")

        snapshot, _ = gs.build_snapshot(
            "yellowsand1", "assaystone", pypi="assaystone",
            fetched_at="2026-11-24T12:00:00+00:00", opener=BrokenOpener(),
        )
        for key in (
            "stars", "forks", "watchers", "open_issues", "open_pull_requests",
            "views_14d", "clones_14d", "referrers_14d", "pypi_downloads_14d",
        ):
            self.assertEqual(snapshot[key]["status"], "unmeasured", key)
            self.assertIsNone(snapshot[key]["value"])
        # release_count and latest_release degrade too, but their value is a
        # placeholder that must not look like a real zero measurement.
        self.assertEqual(snapshot["release_count"]["status"], "unmeasured")
        self.assertEqual(snapshot["latest_release"]["status"], "unmeasured")

    def test_csv_writes_one_row_per_snapshot(self):
        snapshot, _ = gs.build_snapshot(
            "yellowsand1", "assaystone", pypi="assaystone",
            fetched_at="2026-11-24T12:00:00+00:00", opener=self.opener,
        )
        csv_text = gs.snapshot_to_csv(snapshot)
        lines = [line for line in csv_text.splitlines() if line.strip()]
        self.assertEqual(len(lines), 2)  # header + one row
        self.assertIn("stars", lines[0])
        self.assertIn("42", lines[1])


if __name__ == "__main__":
    unittest.main()
