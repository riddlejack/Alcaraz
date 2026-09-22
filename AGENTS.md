# tennis-lab

## Scope and navigation

This is the rebuilt Python tennis-lab product. The separate Tennis Research Lab directory is the research and provenance archive. Treat archive inputs and frozen historical configurations as immutable, read-only bindings unless a task explicitly grants a bounded archive write. Do not transplant the archive's Rust default or depend on an absolute home path.

Use [the current operating policy](docs/PROCESS.md#current-operating-policy--september-16-2026) for future execution workflow. Resolve acceptance from the relevant decision in docs/DECISIONS.md and the active route or experiment's accepted record; README.md is presentation, not a universal approval register. Use docs/METHODS.md for scientific contracts, docs/PORTING.md for stage work, docs/EQUIVALENCE.md for historical reproduction, and DATA_LICENSES.md for source and redistribution limits. Read only the documents relevant to the task.

## Acceptance boundary

Acceptance is scoped to a named revision, route, population and claim. Resolve it from the relevant decision in docs/DECISIONS.md and its linked evidence; do not treat RB9–RB13 as a blanket list of still-open gates. Later scoped acceptances do not authorize unsupported prospective or comprehensive leak-audit claims. Passing tests or historical reproduction alone is not scientific acceptance.

- **RB9 / RB17:** for a route that uses full_tier, join its tier stages to the synthetic acceptance path and cover the native tier, SR02, sidecar mutations and full-bundle checks applicable to that route. Unsupported WTA tier coverage is not a prerequisite for an ATP-only or WTA-base task; do not claim a missing applicable check passed.
- **RB10:** preserve frozen historical workspace bindings. Put live updates in a separate versioned workspace and manifest-bound configuration with explicit output paths and exposure records.
- **RB11 / RB14 / RB16:** the scoped repair established forecast-only pre-barrier behavior, fold-specific outcome-read receipts, preserved forecast hashes and planted-leak checks for its accepted routes. Apply those requirements to affected new or changed routes and independently reconstruct material changes; do not describe the repair as universally pending or universally comprehensive.
- **RB12:** admit a detector to CI only when its evidence is reconstructable and it fails on its declared planted negative control. Preserve lane ownership and do not import rejected or incomplete gates.
- **RB13:** an event anchor identifies an event; it is not evidence that a result was available. Require an admissible result-date upper bound plus receipt or publication qualification at the cutoff, and quarantine unresolved overlaps.

## Scientific and engineering rules

Preserve chronological information sets; fold-specific label and report barriers; frozen input provenance; neutral player orientation; paired proper-score comparisons on exact matched cohorts; dependence-aware uncertainty; and the distinction between exposed development results and prospective evidence. Keep negative and inconclusive results, source disagreement, limitations, and outcome exposure explicit. Compilation, hashes, passing tests, and local custody do not establish source truth or scientific validity.

Use the pinned `uv` environment and Makefile. `make setup` installs the locked development environment. Use focused validation for bounded repairs and documentation changes. For product code, run `make check` once on the final integrated change; repeat it only when a relevant change or failure invalidates the result. Run a stage or full archive equivalence only when the change affects that computation, with `TENNISLAB_ARCHIVE` read-only, frozen configuration, a separate output directory, and recorded exposure and provenance. Inspect every expected output; a comparator exit code alone is not acceptance. Follow [the current operating policy](docs/PROCESS.md#current-operating-policy--september-16-2026) to distinguish technical repair from scientific change.

Reachability, permission, quality, and redistribution authority are separate source gates. Follow DATA_LICENSES.md and versioned manifests or permission records. Keep restricted raw data and provider payloads out of Git. New collection, accounts, purchases, outreach, publication, or changed traffic scope require owner authority; do not freeze a source as unavailable when new qualified evidence changes its status.

Use the configured capable model directly. Delegate bounded work when capability, independence, or context separation improves the result, with explicit write boundaries and one integrating owner. Record consequential decisions and changed acceptance status in the smallest governing document, backed by evidence.
