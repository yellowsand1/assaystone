# Release checklist

PyPI versions are immutable. If a release is broken, yank it and publish a patch.

## 1. Version and docs

- [ ] Write `docs/releases/v<version>.md`.
- [ ] Run `make release-prep VERSION=<version>`. It bumps every version reference,
      moves the Unreleased changelog entries under the new version, and fails
      before writing if any edit would not apply.
- [ ] Update the README status line and `CHANGELOG.md`.
- [ ] Add `docs/releases/v<version>.md` with highlights and known limitations.
- [ ] Check the repository URLs in `pyproject.toml`, `README.md`, and
      `assaystone/init.py`.

## 2. Verification

```bash
make test
make demo-audit
make demo
make demo-ops
make demo-plane
make benchmark
```

`make benchmark` fails if verifier recall drops below the committed Failure Zoo
thresholds. Commit the refreshed `docs/failure-zoo.md` or CI will report it stale.

Build and install the wheel in a clean environment:

```bash
rm -rf dist
python3 -m pip install build twine
python3 -m build
python3 -m twine check dist/*
python3 -m venv /tmp/assaystone-release
/tmp/assaystone-release/bin/pip install dist/*.whl pytest
/tmp/assaystone-release/bin/assaystone --version
cd /tmp && /tmp/assaystone-release/bin/assaystone demo audit
```

## 3. Publish

### Trusted publishing (recommended)

1. On PyPI, add a **pending trusted publisher** for project `assaystone`:
   - Owner: `yellowsand1`
   - Repository: `assaystone`
   - Workflow: `release.yml`
   - Environment: `PyPI`
2. In the GitHub repository, create an environment named `PyPI` (no secrets needed).
3. Push a version tag, or run the **release** workflow manually with the tag:
   ```bash
   git tag v0.24.0
   git push origin v0.24.0
   ```
   For a manual run, `tag` is required and must start with `v`. If the version is
   already on PyPI, set `publish_pypi=false` to build and create only the GitHub
   release.
4. `.github/workflows/release.yml` builds, checks, publishes to PyPI, and creates the
   GitHub release from `docs/releases/<tag>.md`.

If a release was created with the wrong tag, delete the GitHub release and the bad
tag, then run the workflow again with the correct tag and `publish_pypi=false`.

For the already-pushed `v0.3.0` tag, add the workflow after configuring the publisher,
then run **Actions → release → Run workflow** with `tag = v0.3.0`.

### Manual fallback

```bash
python3 -m build
python3 -m twine upload dist/*
```

Use `__token__` as the username and a PyPI API token as the password. Never commit the
token.

## 4. Post-release

```bash
python3 -m pip install --upgrade "assaystone==<version>"
assaystone --version
assaystone demo audit
```

- [ ] GitHub Action users can pin `install: assaystone==<version>`.
- [ ] Verify the PyPI page and the GitHub release notes.
- [ ] Announce only if the wheel demo and `pip install` both work.
