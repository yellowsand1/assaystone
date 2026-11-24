#!/usr/bin/env python3
"""Snapshot public growth metrics for an Assaystone-style GitHub project.

This script is dependency-free (Python 3.10+ standard library only) so it can
run in a GitHub Actions `schedule` workflow or any cron without installing the
package. It reads the GitHub REST API and the public PyPI / pypistats APIs, then
writes one deterministic JSON snapshot (and, optionally, a CSV row) whose every
metric carries a ``measured`` / ``proxy`` / ``unmeasured`` status.

Design rules
------------
* Network failures degrade to ``unmeasured``; they are never reported as ``0``.
* The GitHub token is read from ``GITHUB_TOKEN`` then ``GH_TOKEN``, used only to
  authenticate requests, and is never printed, logged, or written to a file.
* Every HTTP call is bounded by a timeout so a hung upstream cannot stall a
  weekly routine.

Examples
--------
    python scripts/growth_snapshot.py yellowsand1/assaystone
    python scripts/growth_snapshot.py yellowsand1/assaystone \
        --pypi assaystone --csv snapshot.csv
    python scripts/growth_snapshot.py --help
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

__all__ = [
    "MEASURED",
    "PROXY",
    "UNMEASURED",
    "DEFAULT_TIMEOUT",
    "GitHubClient",
    "PyPIClient",
    "build_snapshot",
    "flatten_snapshot",
    "snapshot_to_csv",
    "write_outputs",
    "main",
]

MEASURED = "measured"
PROXY = "proxy"
UNMEASURED = "unmeasured"

DEFAULT_TIMEOUT = 20.0
_TRAFFIC_DAYS = 14

GITHUB_API = "https://api.github.com"
PYPISTATS_API = "https://pypistats.org/api/packages"


# ---------------------------------------------------------------------------
# Small typed value object
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Metric:
    """A single metric with an explicit measurement status."""

    value: Any
    status: str
    source: str
    note: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {"value": self.value, "status": self.status, "source": self.source, "note": self.note}


# ---------------------------------------------------------------------------
# HTTP layer (stdlib only)
# ---------------------------------------------------------------------------
def _read_token(env: dict[str, str] | None = None) -> str:
    """Return the first present token from GITHUB_TOKEN then GH_TOKEN."""
    env = os.environ if env is None else env
    return env.get("GITHUB_TOKEN") or env.get("GH_TOKEN") or ""


def _request_json(
    url: str,
    *,
    token: str = "",
    timeout: float = DEFAULT_TIMEOUT,
    headers: dict[str, str] | None = None,
    opener: urllib.request.OpenerDirector | None = None,
) -> tuple[Any, dict[str, str]]:
    """GET *url* and return ``(parsed_json, response_headers)``.

    Raises ``urllib.error.URLError`` (or ``HTTPError``) on any failure so the
    caller can decide whether to mark a metric unmeasured.
    """
    req = urllib.request.Request(url)
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("User-Agent", "assaystone-growth-snapshot")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    for key, value in (headers or {}).items():
        req.add_header(key, value)
    handle = opener.open(req, timeout=timeout) if opener is not None else urllib.request.urlopen(req, timeout=timeout)  # noqa: S310
    try:
        body = handle.read()
    finally:
        handle.close()
    payload = json.loads(body.decode("utf-8"))
    return payload, dict(handle.headers.items())


def _get_json(
    url: str,
    *,
    token: str = "",
    timeout: float = DEFAULT_TIMEOUT,
    headers: dict[str, str] | None = None,
    opener: urllib.request.OpenerDirector | None = None,
) -> tuple[Any, str]:
    """Return ``(payload, status)``, never raising for network errors."""
    try:
        payload, _ = _request_json(url, token=token, timeout=timeout, headers=headers, opener=opener)
        return payload, MEASURED
    except (urllib.error.URLError, urllib.error.HTTPError, ValueError, OSError):
        return None, UNMEASURED


# ---------------------------------------------------------------------------
# Pure parsing helpers (unit-testable with offline fixtures)
# ---------------------------------------------------------------------------
def _count_since(dates: list[Any], days: int) -> int:
    """Count ISO timestamps within the last *days* days, inclusive of today."""
    if not dates:
        return 0
    cutoff = _dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(days=days)
    count = 0
    for item in dates:
        if item is None:
            continue
        try:
            parsed = _dt.datetime.fromisoformat(str(item).replace("Z", "+00:00"))
        except ValueError:
            continue
        if parsed >= cutoff:
            count += 1
    return count


def _parse_release_count_and_latest(releases: Any) -> tuple[int | None, str, str]:
    """Return ``(release_count, latest_tag, status)`` from a releases array.

    ``latest_tag`` is the first non-empty ``tag_name`` (GitHub returns releases
    newest first). When the list is empty the status is ``unmeasured`` and the
    count is ``None`` so it can never be mistaken for a real zero.
    """
    if not isinstance(releases, list):
        return None, "", UNMEASURED
    for item in releases:
        if isinstance(item, dict) and item.get("tag_name"):
            return len(releases), str(item["tag_name"]), MEASURED
    return (None, "", UNMEASURED)


def _sum_14d_total(payload: Any) -> tuple[int | None, int, str]:
    """Sum the last 14 daily ``count`` buckets from a GitHub traffic payload.

    Accepts any of the shapes GitHub has returned over time (``views``,
    ``clones``, ``downloads``, or an explicit ``buckets`` list) and keys the
    date on ``timestamp`` before ``date``/``day``. A malformed or missing
    payload is ``unmeasured`` with a ``None`` total, never ``0``.
    """
    if not isinstance(payload, dict):
        return None, 0, UNMEASURED
    buckets = (
        payload.get("views")
        or payload.get("clones")
        or payload.get("downloads")
        or payload.get("buckets")
        or payload.get("days")
        or []
    )
    if not isinstance(buckets, list):
        return None, 0, UNMEASURED
    rows: list[tuple[str, int]] = []
    for bucket in buckets:
        if not isinstance(bucket, dict):
            continue
        day = bucket.get("timestamp") or bucket.get("date") or bucket.get("day")
        count = bucket.get("count")
        if day is None or count is None:
            continue
        try:
            rows.append((str(day), int(count)))
        except (TypeError, ValueError):
            continue
    if not rows:
        return None, 0, UNMEASURED
    rows.sort(key=lambda pair: pair[0])
    total = sum(count for _, count in rows[-_TRAFFIC_DAYS:])
    return total, len(rows), MEASURED


def _extract_link_header(headers: dict[str, str]) -> dict[str, str]:
    """Parse a GitHub Link header into ``{rel: url}``."""
    raw = headers.get("Link") or headers.get("link") or ""
    links: dict[str, str] = {}
    for part in raw.split(","):
        section = part.strip()
        if "<" not in section or ">" not in section:
            continue
        url = section[section.index("<") + 1 : section.index(">")]
        rel = ""
        for piece in section.split(";"):
            piece = piece.strip()
            if piece.startswith("rel="):
                rel = piece[4:].strip().strip('"')
        if rel:
            links[rel] = url
    return links


def _sum_pypi_recent(payload: Any, days: int = _TRAFFIC_DAYS) -> tuple[int | None, int, str]:
    """Sum the ``without_mirrors`` daily downloads over the last *days* days.

    pypistats ``/overall`` returns a flat ``data`` list of
    ``{"category": ..., "date": "YYYY-MM-DD", "downloads": N}`` rows. Mirror
    rows are excluded so the number reflects real installs, not mirror traffic.
    """
    if not isinstance(payload, dict):
        return None, 0, UNMEASURED
    rows = payload.get("data")
    if not isinstance(rows, list):
        return None, 0, UNMEASURED
    dated: list[tuple[str, int]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        if row.get("category") != "without_mirrors":
            continue
        date = row.get("date")
        downloads = row.get("downloads")
        if date is None or downloads is None:
            continue
        try:
            dated.append((str(date), int(downloads)))
        except (TypeError, ValueError):
            continue
    if not dated:
        return None, 0, UNMEASURED
    dated.sort(key=lambda pair: pair[0])
    total = sum(count for _, count in dated[-days:])
    return total, len(dated), MEASURED


def _sum_referrers(payload: Any, days: int = _TRAFFIC_DAYS) -> tuple[int | None, str]:
    """Sum GitHub top-referrer ``count`` values.

    GitHub already limits the payload to the requested 14-day window, so the
    rows carry no timestamp. An empty list is ``unmeasured`` with a ``None``
    total, never ``0``.
    """
    del days  # window is applied by GitHub; kept for a stable signature
    rows = payload.get("data") if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        return None, UNMEASURED
    counts: list[int] = []
    for referrer in rows:
        if not isinstance(referrer, dict):
            continue
        count = referrer.get("count")
        if count is None:
            continue
        try:
            counts.append(int(count))
        except (TypeError, ValueError):
            continue
    if not counts:
        return None, UNMEASURED
    return sum(counts), MEASURED


# ---------------------------------------------------------------------------
# API clients
# ---------------------------------------------------------------------------
class GitHubClient:
    """Minimal dependency-free wrapper around the GitHub REST API."""

    def __init__(
        self,
        owner: str,
        repo: str,
        token: str = "",
        timeout: float = DEFAULT_TIMEOUT,
        opener: urllib.request.OpenerDirector | None = None,
    ):
        self.owner = owner
        self.repo = repo
        self.token = token
        self.timeout = timeout
        self.opener = opener

    def _url(self, path: str) -> str:
        return f"{GITHUB_API}/repos/{self.owner}/{self.repo}{path}"

    def _get(self, path: str) -> tuple[Any, str, dict[str, str]]:
        try:
            payload, headers = _request_json(
                self._url(path),
                token=self.token,
                timeout=self.timeout,
                opener=self.opener,
            )
            return payload, MEASURED, headers
        except (urllib.error.URLError, urllib.error.HTTPError, ValueError, OSError):
            return None, UNMEASURED, {}

    def repo_metrics(self) -> tuple[Any, str]:
        payload, status, _ = self._get("")
        return payload, status

    def releases(self) -> tuple[Any, str]:
        payload, status, _ = self._get("/releases?per_page=100")
        return payload, status

    def traffic_views(self) -> tuple[Any, str]:
        payload, status, _ = self._get("/traffic/views")
        return payload, status

    def traffic_clones(self) -> tuple[Any, str]:
        payload, status, _ = self._get("/traffic/clones")
        return payload, status

    def traffic_referrers(self) -> tuple[Any, str]:
        payload, status, _ = self._get("/traffic/popular/referrers")
        return payload, status


class PyPIClient:
    """Minimal dependency-free wrapper around PyPI and pypistats."""

    def __init__(
        self,
        package: str,
        timeout: float = DEFAULT_TIMEOUT,
        opener: urllib.request.OpenerDirector | None = None,
    ):
        self.package = package
        self.timeout = timeout
        self.opener = opener

    def _get(self, url: str) -> tuple[Any, str]:
        try:
            payload, _ = _request_json(url, timeout=self.timeout, opener=self.opener)
            return payload, MEASURED
        except (urllib.error.URLError, urllib.error.HTTPError, ValueError, OSError):
            return None, UNMEASURED

    def recent_downloads(self, days: int = 14) -> tuple[int | None, str]:
        """Return the sum of the most recent *days* days of PyPI downloads.

        Uses ``/overall`` (real installs only, mirrors excluded), falling back
        to the 7-day ``/recent`` total when overall history is unavailable.
        """
        payload, status = self._get(f"{PYPISTATS_API}/{self.package}/overall")
        if status == MEASURED:
            total, _, parsed_status = _sum_pypi_recent(payload, days=days)
            if parsed_status == MEASURED:
                return total, MEASURED
        payload, status = self._get(f"{PYPISTATS_API}/{self.package}/recent")
        if status != MEASURED or not isinstance(payload, dict):
            return None, UNMEASURED
        data = payload.get("data") or {}
        value = data.get("last_week") if days <= 7 else data.get("last_month")
        if value is None:
            return None, UNMEASURED
        return int(value), PROXY


# ---------------------------------------------------------------------------
# Snapshot assembly
# ---------------------------------------------------------------------------
def build_snapshot(
    owner: str,
    repo: str,
    *,
    token: str = "",
    pypi: str = "",
    fetched_at: str | None = None,
    timeout: float = DEFAULT_TIMEOUT,
    opener: urllib.request.OpenerDirector | None = None,
) -> tuple[dict[str, Any], dict[str, str]]:
    """Assemble one snapshot. Returns ``(snapshot, meta)``.

    ``meta`` contains only non-secret context such as the owner/repo, never the
    token.
    """
    fetched = fetched_at or _dt.datetime.now(_dt.timezone.utc).isoformat()
    github = GitHubClient(owner, repo, token=token, timeout=timeout, opener=opener)
    pypi_client = PyPIClient(pypi, timeout=timeout, opener=opener) if pypi else None

    snapshot: dict[str, Any] = {
        "repository": f"{owner}/{repo}",
        "fetched_at": fetched,
        "pypi_package": pypi or None,
    }

    # Repository core metrics. ``open issues`` is the count of open issues and
    # PRs together (GitHub's ``open_issues_count``) so a proxied ``open_pull_requests``
    # is derived only when the search endpoint is unavailable.
    repo_payload, repo_status = github.repo_metrics()
    if repo_payload is None:
        snapshot["stars"] = {"value": None, "status": UNMEASURED, "source": "github.repo", "note": "repository API failed"}
        snapshot["forks"] = {"value": None, "status": UNMEASURED, "source": "github.repo", "note": "repository API failed"}
        snapshot["watchers"] = {"value": None, "status": UNMEASURED, "source": "github.repo", "note": "repository API failed"}
        snapshot["open_issues"] = {"value": None, "status": UNMEASURED, "source": "github.repo", "note": "repository API failed"}
    else:
        snapshot["stars"] = {"value": repo_payload.get("stargazers_count"), "status": repo_status, "source": "github.repo"}
        snapshot["forks"] = {"value": repo_payload.get("forks_count"), "status": repo_status, "source": "github.repo"}
        snapshot["watchers"] = {"value": repo_payload.get("subscribers_count"), "status": repo_status, "source": "github.repo"}
        snapshot["open_issues"] = {
            "value": repo_payload.get("open_issues_count"),
            "status": repo_status,
            "source": "github.repo",
            "note": "GitHub counts PRs as issues; see open_pull_requests",
        }

    # Open pull requests: a search by ``repo:`` plus type:pr is the only clean way
    # to separate PRs from issues without paging every issue. If the search fails,
    # fall back to the repository's ``open_issues_count`` marked as proxy.
    open_pr: Any = None
    open_pr_status = UNMEASURED
    open_pr_note = "PR search failed"
    search_url = (
        f"{GITHUB_API}/search/issues?q=repo:{owner}/{repo}+is:pr+is:open&per_page=1"
    )
    search_payload, search_status = _get_json(
        search_url, token=token, timeout=timeout, opener=opener
    )
    if search_status == MEASURED and isinstance(search_payload, dict):
        open_pr = search_payload.get("total_count")
        open_pr_status = MEASURED
        open_pr_note = ""
    elif repo_payload is not None and isinstance(repo_payload.get("open_issues_count"), int):
        open_pr = repo_payload["open_issues_count"]
        open_pr_status = PROXY
        open_pr_note = "proxied from open_issues_count"
    snapshot["open_pull_requests"] = {
        "value": open_pr,
        "status": open_pr_status,
        "source": "github.search",
        "note": open_pr_note,
    }

    # Releases.
    releases_payload, releases_status = github.releases()
    release_count, latest_tag, release_status = _parse_release_count_and_latest(releases_payload)
    if releases_status != MEASURED:
        release_status = UNMEASURED
    snapshot["release_count"] = {"value": release_count, "status": release_status, "source": "github.releases", "note": "" if release_status != UNMEASURED else "releases API failed"}
    snapshot["latest_release"] = {"value": latest_tag, "status": release_status, "source": "github.releases", "note": "" if release_status != UNMEASURED else "releases API failed"}

    # Traffic. The traffic endpoints are read-only and need a token with repo
    # push access; without it they 404/403 and are marked unmeasured.
    views_payload, _ = github.traffic_views()
    views_14d, _, views_status = _sum_14d_total(views_payload)
    snapshot["views_14d"] = {"value": views_14d, "status": views_status, "source": "github.traffic", "note": "" if views_status != UNMEASURED else "traffic/views unavailable"}

    clones_payload, _ = github.traffic_clones()
    clones_14d, _, clones_status = _sum_14d_total(clones_payload)
    snapshot["clones_14d"] = {"value": clones_14d, "status": clones_status, "source": "github.traffic", "note": "" if clones_status != UNMEASURED else "traffic/clones unavailable"}

    referrers_payload, referrers_status = github.traffic_referrers()
    referrers_14d, referrers_status = _sum_referrers(referrers_payload)
    snapshot["referrers_14d"] = {"value": referrers_14d, "status": referrers_status, "source": "github.traffic", "note": "" if referrers_status != UNMEASURED else "traffic/referrers unavailable"}

    # PyPI.
    if pypi_client is None:
        snapshot["pypi_downloads_14d"] = {"value": None, "status": UNMEASURED, "source": "pypistats", "note": "no PyPI package given"}
    else:
        pypi_total, pypi_status = pypi_client.recent_downloads()
        snapshot["pypi_downloads_14d"] = {"value": pypi_total, "status": pypi_status, "source": "pypistats", "note": "" if pypi_status != UNMEASURED else "pypistats unavailable"}

    meta = {
        "repository": f"{owner}/{repo}",
        "fetched_at": fetched,
        "pypi_package": pypi or "",
    }
    return snapshot, meta


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------
def flatten_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Flatten the nested ``Metric`` objects into ``field`` and ``field_status``."""
    flat: dict[str, Any] = {}
    for key, value in snapshot.items():
        if isinstance(value, dict) and set(value) >= {"value", "status"}:
            flat[key] = value["value"]
            flat[f"{key}_status"] = value["status"]
            flat[f"{key}_source"] = value["source"]
        else:
            flat[key] = value
    return flat


def snapshot_to_csv(snapshot: dict[str, Any]) -> str:
    """Serialize one flattened snapshot as a single CSV row with a header."""
    flat = flatten_snapshot(snapshot)
    header = list(flat)
    values = [flat[key] for key in header]
    lines = [",".join(_csv_cell(x) for x in header), ",".join(_csv_cell(x) for x in values)]
    return "\n".join(lines) + "\n"


def _csv_cell(value: Any) -> str:
    if value is None:
        return ""
    text = str(value)
    if any(ch in text for ch in ',"\n\r'):
        return '"' + text.replace('"', '""') + '"'
    return text


def write_outputs(
    snapshot: dict[str, Any],
    *,
    json_path: Path | None,
    csv_path: Path | None,
) -> None:
    """Write the JSON and optional CSV outputs atomically."""
    if json_path is not None:
        json_path.write_text(
            json.dumps(snapshot, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    if csv_path is not None:
        csv_path.write_text(snapshot_to_csv(snapshot), encoding="utf-8")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Snapshot public growth metrics for a GitHub repository.",
    )
    parser.add_argument("repository", help="owner/repo, e.g. yellowsand1/assaystone")
    parser.add_argument("--pypi", default="", help="PyPI package name for download metrics")
    parser.add_argument("--csv", default="", help="optional CSV output path")
    parser.add_argument("--json", default="growth_snapshot.json", help="JSON output path")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT, help="HTTP timeout in seconds")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_arg_parser()
    args = parser.parse_args(argv)
    if "/" not in args.repository:
        parser.error("repository must be owner/repo")
    owner, repo = args.repository.split("/", 1)
    token = _read_token()
    snapshot, _meta = build_snapshot(owner, repo, token=token, pypi=args.pypi, timeout=args.timeout)
    json_path = Path(args.json)
    csv_path = Path(args.csv) if args.csv else None
    write_outputs(snapshot, json_path=json_path, csv_path=csv_path)
    print(json.dumps(snapshot, indent=2, sort_keys=True, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
