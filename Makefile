.PHONY: setup lint test reproduce-small reproduce-tier check

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

reproduce-tier:
	$(UV) run tennislab reproduce-small --scenario tier

check: lint test reproduce-small reproduce-tier
