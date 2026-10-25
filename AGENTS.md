# AGENTS.md

Ground rules for anyone, human or AI agent, changing this repository.

1. **Real functionality only.** No stubs, `pass` bodies, `TODO` placeholders, or mocked behaviour
   presented as working.
2. **Fix, don't report.** When a check fails, fix the code. Never weaken a test, skip a test, add
   `# type: ignore` / `# noqa` without a one-line justification comment, or lower the coverage
   threshold.
3. **No invented output.** Any sample output in README.md must be produced by actually running the
   CLI and pasting the result.
4. **Privacy.** Logs can contain personal data and secrets. QueryLens must never print raw query
   text, literal values, or `DETAIL: parameters:` lines. Output contains normalized fingerprints
   only.
5. **Fixtures are synthetic.** Use fake data only (`example.com` emails, obviously fake names and
   values). This is stated in `tests/fixtures/README.md`.
6. **Zero runtime dependencies.** Standard library only at runtime.
7. **Git.** Use Conventional Commits (`feat:`, `test:`, `docs:`, `chore:`, `fix:`, `refactor:`).
   Agents never add a remote, push, force-push, or run any `gh` command; publishing is done by the
   maintainer.
8. **Ambiguity.** If a requirement is ambiguous or contradictory, choose the most conservative
   interpretation and record the decision in `SPEC.md` under "Decisions".

## Workflow

```bash
python -m venv .venv
. .venv/bin/activate
make install
make check      # ruff, ruff format --check, mypy --strict, pytest with >=90% branch coverage
```
