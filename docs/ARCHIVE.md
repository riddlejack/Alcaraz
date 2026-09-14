# The research archive

This package is a rebuild of the modelling trunk of a research archive, the repository
in which the science was done between 2026-09-10 and 2026-09-12. The archive is kept
as-is so that every hash its manifests cite stays valid; nothing in it is rewritten.

| | |
|---|---|
| Archive repository | `riddlejack/tennis-research-lab-archive`, currently private; no public archive link is claimed |
| Archive commit the rebuild reads | `0ffd1bd935e4965d4419b5f556d94a95cea20ed3` (2026-09-12) |
| Source tag | not created as of 2026-09-14; the full commit hash above is the binding |
| Accepted ATP run | `experiments/runs/TIER01/attempt_002` (decision D63), manifest `data/manifests/TIER01-run-002.json` |
| Accepted WTA run | `experiments/runs/WTA02/attempt_002` (decisions D61, D62), manifest `data/manifests/WTA02-run-002.json` |
| Elo baseline | `references/CONFIRM2026_elo/`, run `experiments/runs/CONFIRM2026/elo_001` |

## What the link means

Every manifest under `data/manifests/` here is a byte-for-byte copy of the archive's
file of the same name. They bind inputs and outputs by SHA-256, not by git commit, so
they remain valid wherever the bytes are. `docs/EQUIVALENCE.md` records, stage by stage,
that this package reproduces the accepted runs' outputs from the same frozen inputs.

The archive's raw data (`data/raw/`, 11 GB), its working directory (`work/`, 20 GB) and
its run trees (`experiments/runs/`, 5 GB) are not in either repository. The equivalence
tool (`tools/equivalence.py`) needs a local copy of the archive with those directories
present; the reconstruction protocol names the commands.

## What was deliberately left in the archive

Weather (WX*), point-state (PP*), market-residual and teacher experiments (MULTI02/03,
JOINT05, TEACHER*), the HISTORY01/TICK collectors and the Rust crate. `docs/PROCESS.md`
summarises what they found.
