# Releasing QueryLens

Maintainer checklist for shipping a version to GitHub Releases and PyPI.
Agents do not push, create releases, or run `gh` (see [AGENTS.md](AGENTS.md));
a human performs the publish steps below.

The browser demo stays on Netlify ([web/README.md](web/README.md)). Publishing
the Python package does not redeploy the site.

## Versioning

- Semantic Versioning (`MAJOR.MINOR.PATCH`), documented in [CHANGELOG.md](CHANGELOG.md).
- Single source of truth: `__version__` in `src/querylens/__init__.py`
  (`pyproject.toml` reads it via Hatch).
- Tag format: `v0.1.0` (leading `v`, matches the existing first release).

## One-time PyPI Trusted Publisher setup

Do this once before the first upload. No long-lived API token is required.

1. Sign in at [pypi.org](https://pypi.org/) (create an account and enable 2FA if needed).
2. Open **Your projects → Publishing** (or create the project via
   **Publishing → Add a new pending publisher** if `querylens` does not exist yet).
3. Add a **Trusted Publisher** with:
   - **PyPI project name:** `querylens`
   - **Owner:** `yagnang-vyas`
   - **Repository:** `query-lens`
   - **Workflow name:** `publish.yml`
   - **Environment name:** `pypi`
4. In the GitHub repo: **Settings → Environments → New environment** named exactly
   `pypi`. Optional but recommended: require a reviewer before deploy, and limit
   the environment to the `main` branch / `v*` tags.
5. Merge the Publish workflow to `main` so `.github/workflows/publish.yml` is on
   the default branch (Trusted Publishing requires that).

## First publish of the existing `v0.1.0` release

`v0.1.0` is already on GitHub Releases. Creating that release again will not
re-fire the workflow, so use a manual run for the debut upload:

1. Finish the Trusted Publisher and `pypi` environment setup above.
2. Confirm `__version__` is still `"0.1.0"` on `main` (or check out the `v0.1.0` tag).
3. GitHub → **Actions → Publish → Run workflow** (`workflow_dispatch`), branch
   `main` (or the tag ref if you prefer).
4. Approve the `pypi` environment if you enabled protection rules.
5. When the job succeeds, verify:
   ```bash
   pip install querylens==0.1.0
   querylens --version
   ```
6. Update the GitHub Release notes for `v0.1.0` if useful (e.g. note that
   `pip install querylens` now works). Do not change the version number.

PyPI versions are immutable: a failed half-upload of `0.1.0` may require a
patch bump (`0.1.1`) for a retry. Prefer fixing Trusted Publisher config before
the first run.

## Every later release

1. **Changelog.** Move items from `[Unreleased]` into a new `## [X.Y.Z] - YYYY-MM-DD`
   section in `CHANGELOG.md`. Add a compare link at the bottom.
2. **Version.** Set `__version__ = "X.Y.Z"` in `src/querylens/__init__.py`.
3. **Checks.** From a clean tree:
   ```bash
   make check
   make dist          # builds dist/ and runs twine check
   ```
4. **Commit** on `main` (Conventional Commits), e.g. `chore: release X.Y.Z`.
5. **Tag and push** (maintainer only):
   ```bash
   git tag -a vX.Y.Z -m "QueryLens X.Y.Z"
   git push origin main
   git push origin vX.Y.Z
   ```
6. **GitHub Release.** Create a release for tag `vX.Y.Z` (GitHub UI or `gh release create`).
   Paste the changelog section. Publishing the release starts the **Publish**
   workflow, which builds and uploads to PyPI via OIDC.
7. **Verify.**
   ```bash
   pip install -U querylens
   querylens --version
   ```
8. **Demo.** Netlify redeploys from `main` on its own; no extra step unless the
   playground needs a content update for the new version.

## Local dry-run (no upload)

```bash
make dist
# inspect dist/querylens-*.tar.gz and dist/querylens-*.whl
# do not run twine upload; CI owns publishing
```

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| Publish job: Trusted Publishing / OIDC error | Pending publisher not saved, wrong workflow name (`publish.yml`), wrong environment name (`pypi`), or workflow not on the default branch |
| `File already exists` on PyPI | That version was already uploaded; bump the version and cut a new tag |
| Wrong version in the wheel | Tag/`__version__` mismatch; fix `__init__.py`, retag if the bad tag was never published |
| Netlify still on an old build | Unrelated to PyPI; check the Netlify deploy for `main` |
