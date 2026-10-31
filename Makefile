PYTHON ?= python

.PHONY: install lint typecheck test check format dist clean-dist

install:
	$(PYTHON) -m pip install -e ".[dev]"

lint:
	ruff check . && ruff format --check .

typecheck:
	mypy src

test:
	pytest --cov=slowlens --cov-branch --cov-report=term-missing --cov-fail-under=90

check: lint typecheck test

format:
	ruff format . && ruff check --fix .

# Local sdist/wheel dry-run. Publishing is done by CI (see RELEASING.md).
dist: clean-dist
	$(PYTHON) -m pip install -q build twine
	$(PYTHON) -m build
	$(PYTHON) -m twine check dist/*

clean-dist:
	$(PYTHON) -c "import pathlib, shutil; p=pathlib.Path('dist'); shutil.rmtree(p, ignore_errors=True)"
