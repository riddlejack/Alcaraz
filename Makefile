.PHONY: setup lint test reproduce-small check

UV ?= uv

setup:
	$(UV) sync --locked --group dev

lint:
	$(UV) run ruff check .
	$(UV) run ruff format --check .

test:
	$(UV) run pytest

reproduce-small:
	$(UV) run tennislab reproduce-small

check: lint test reproduce-small
