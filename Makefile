PYTHON ?= python

.PHONY: install lint typecheck test check format

install:
	$(PYTHON) -m pip install -e ".[dev]"

lint:
	ruff check . && ruff format --check .

typecheck:
	mypy src

test:
	pytest --cov=querylens --cov-branch --cov-report=term-missing --cov-fail-under=90

check: lint typecheck test

format:
	ruff format . && ruff check --fix .
