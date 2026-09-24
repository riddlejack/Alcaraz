.PHONY: setup lint test reproduce-small reproduce-tier check results-figure benchmarks numbers

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

# Product benchmark JSONs from the archive result files named in docs/benchmarks/sources.json
# (hash-verified). Needs the research archive: TENNISLAB_ARCHIVE=<archive root>.
benchmarks:
	$(UV) run python tools/build_benchmark_aggregates.py --archive-root "$(TENNISLAB_ARCHIVE)"

# Every number on the README and the benchmark pages must come from a committed JSON
# (docs/numbers.json). Pages with a template in docs/templates are rendered with --render.
numbers:
	$(UV) run python tools/check_readme_numbers.py
