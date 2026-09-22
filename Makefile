.PHONY: setup lint test reproduce-small reproduce-tier check results-figure

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

# The README results figure needs matplotlib, which is deliberately not in the locked
# environment. Render it with the system python3 (tested with matplotlib 3.11).
results-figure:
	python3 tools/render_results_figure.py
