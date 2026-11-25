# Growth snapshot

A dependency-free (stdlib-only) weekly metric snapshot for Assaystone's public
adoption. It reads the GitHub REST API and pypistats, then writes one
deterministic JSON snapshot (and, optionally, a CSV row) whose every metric
carries a `measured` / `proxy` / `unmeasured` status.

> No metric is invented. A network failure, a missing token, or an unavailable
> endpoint degrades that field to `unmeasured` with a `null` value — it is never
> reported as `0`.

## Run it

```bash
# One-off snapshot, printed to stdout and written to growth_snapshot.json
python scripts/growth_snapshot.py yellowsand1/assaystone --pypi assaystone

# Also append a CSV row
python scripts/growth_snapshot.py yellowsand1/assaystone \
    --pypi assaystone --csv snapshot.csv

# Via the Makefile
make growth-snapshot
```

Only the standard library is used, so the script runs on Python 3.10+ with no
install step. GitHub metrics come from `api.github.com/repos/<owner>/<repo>`;
PyPI downloads come from `pypistats.org/api/packages/<pkg>/overall` (real
installs only, mirrors excluded).

## Weekly routine

The GitHub traffic endpoints (`/traffic/views`, `/traffic/clones`,
`/traffic/popular/referrers`) require a token with push access to the
repository. Without one they return 403/404 and are recorded as `unmeasured`,
which keeps the snapshot honest instead of guessing zero.

Add a repository secret named `GH_TOKEN` holding a fine-grained token with
`Repository access → <repo>` and `Contents: Read-only`, then add a scheduled
workflow (e.g. `.github/workflows/growth-snapshot.yml`):

```yaml
name: growth-snapshot

on:
  schedule:
    - cron: "0 9 * * 1"   # Mondays at 09:00 UTC
  workflow_dispatch:

jobs:
  snapshot:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - name: Snapshot public metrics
        env:
          GH_TOKEN: ${{ secrets.GH_TOKEN }}
        run: python scripts/growth_snapshot.py yellowsand1/assaystone --pypi assaystone --csv snapshot.csv
      - name: Upload the snapshot as an artifact
        uses: actions/upload-artifact@v4
        with:
          name: growth-snapshot
          path: |
            growth_snapshot.json
            snapshot.csv
```

The token is read from `GH_TOKEN` (or `GITHUB_TOKEN`), used only to
authenticate the request, and never printed, logged, or written to a file.
Never commit a token.

## Output fields

| field | source | status when degraded |
|---|---|---|
| `stars` | GitHub repo | `unmeasured` (repo API failed) |
| `forks` | GitHub repo | `unmeasured` |
| `watchers` | GitHub repo (`subscribers_count`) | `unmeasured` |
| `open_issues` | GitHub repo (`open_issues_count`) | `unmeasured` |
| `open_pull_requests` | GitHub search (`is:pr is:open`) | `proxy` from `open_issues_count` when search fails |
| `release_count` | GitHub releases | `unmeasured` |
| `latest_release` | GitHub releases (first tag, newest first) | `unmeasured` |
| `views_14d` | GitHub traffic | `unmeasured` without a push-access token |
| `clones_14d` | GitHub traffic | `unmeasured` without a push-access token |
| `referrers_14d` | GitHub traffic | `unmeasured` without a push-access token |
| `pypi_downloads_14d` | pypistats `without_mirrors` | `unmeasured`; `proxy` from the 7-day total when daily history is unavailable |

`open_issues` is GitHub's combined issue+PR count; the `open_pull_requests`
field is the clean PR-only number and should be preferred when comparing the
two.

## Output shape

Every metric is an object with `value`, `status`, `source`, and `note`. The CSV
flattens it into `<field>`, `<field>_status`, and `<field>_source` columns so a
run is one row:

```json
{
  "repository": "yellowsand1/assaystone",
  "fetched_at": "2026-11-24T05:49:21+00:00",
  "pypi_package": "assaystone",
  "stars": {"value": 2, "status": "measured", "source": "github.repo", "note": ""},
  "views_14d": {"value": null, "status": "unmeasured", "source": "github.traffic", "note": "traffic/views unavailable"}
}
```

## Tests

Offline unit tests run against committed fixtures (no network) and cover the
parsers, the full snapshot assembly, the unmeasured degradation path, and CSV
escaping:

```bash
make test          # unittest discovery
make pytest        # pytest collection and suite
make lint          # ruff over assaystone, tests, and scripts
```
