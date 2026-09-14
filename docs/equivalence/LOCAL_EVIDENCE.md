# Local evidence store

The equivalence records under `docs/equivalence/<run>/` and `docs/ladder.json` are
machine evidence: diff excerpts of stage outputs and the run roots the ladder was built
from. Some of those excerpts quote paths that name the host the run took place on (the
research archive's root, the product repository's root, the interpreter's `site-packages`
directory). A tracked file must not carry a host path (acceptance check 5,
`tests/test_repo_hygiene.py`), and the records must not be silently rewritten either.

## What the tracked files are

The tracked copies listed below are **placeholder representations** of the originals:
byte for byte the same file with only the host-specific prefixes replaced by explicit
semantic placeholders. Every other byte, including every recorded data hash and every
oracle artifact hash, is unchanged.

| Placeholder | Stands for | How the writers derive it |
|---|---|---|
| `<ARCHIVE_ROOT>` | the research archive's root directory | `TENNISLAB_ARCHIVE` |
| `<PRODUCT_ROOT>` | this repository's root | the repository root the tool runs from (the workspace root for the ladder) |
| `<SITE_PACKAGES>` | the interpreter's `site-packages` directory, whole prefix including the root (either environment) | `sysconfig` `purelib`, and the archive's environment at the same relative location under `<ARCHIVE_ROOT>` |

`docs/ladder.json` `run_root` therefore reads `<ARCHIVE_ROOT>/experiments/runs/<run>/run`.

## Where the originals are

The originals were moved, unchanged, to the ignored local store `local/evidence/<same
repository path>` (`local/` is in `.gitignore`). `local/evidence/index.json` is the
machine index: each stored path with the SHA-256 of the original and the concrete prefix
behind each placeholder on the host that produced it. The writers
(`tools/equivalence.py` `compare` and `compare_chain`, `tennislab.evaluation.ladder`)
keep both copies in step: the original to `local/evidence/`, the representation to
`docs/`, through `tennislab.evidence.write_evidence`. The store is per machine; a fresh
clone has the representations only.

## Migrated originals (2026-09-14)

SHA-256 of the original bytes as they stood at commit `f139f05`, before the
representation replaced them.

| Repository path | SHA-256 of the original |
|---|---|
| `docs/equivalence/TIER01_attempt_002/_chain.json` | `986940cdd92c56392ce6aba01cc8f100759681e785685f4698948e9605b71c70` |
| `docs/equivalence/TIER01_attempt_002/features.json` | `c9ffda3e3c0a39a9bcd892344ff999060e7b9bff88e21103d908a0dfd896fa14` |
| `docs/equivalence/TIER01_attempt_002/join.json` | `7a08814719a6bf4e5aad9371b88376b722bd85e6d8280a0f26cfac32b0eb26b3` |
| `docs/equivalence/TIER01_attempt_002/pipeline.json` | `5a480879555c306195c9747182a39e40098cdb9f516ae1f5585337a3f6c75c04` |
| `docs/equivalence/TIER01_attempt_002/preflight.json` | `dc10a4d519f18721651d6ee34a18413b380c6601940368fe4f0921d67c5688c0` |
| `docs/equivalence/TIER01_attempt_002/prepare_panel.json` | `80ae28a0e9c2a6bad335e640166d002e4058890939e9f7d331aa8fb498cdc708` |
| `docs/equivalence/WTA02_attempt_002/_chain.json` | `dc673595c2ad1f6014fc1a7dbba9f3f5dbea6355332f1c89cc4d1036ba9824d3` |
| `docs/equivalence/WTA02_attempt_002/features.json` | `c9c5fcb50d52818911c3b86cc1e53332e185416810260e15acd7b6336cb813ca` |
| `docs/equivalence/WTA02_attempt_002/join.json` | `0a99207db41add94152b7efec1dcec8e299c8e02454343d4a071ec386a37a1c9` |
| `docs/equivalence/WTA02_attempt_002/pipeline.json` | `e68207887537dd23df674f2853be10dc04e28a489511c1726cf4722d65f7047b` |
| `docs/equivalence/WTA02_attempt_002/preflight.json` | `1db6ce65915d327d29b7cfa0aed4fa627f0987af3d45ff0ba52c27a733a06cbc` |
| `docs/ladder.json` | `5abfd12a03caf41c6088524cfa3c386868957117e34cff29d1d600d4f8c0d706` |

Substrings replaced, per file: the archive root, the product root and the
`site-packages` prefix of both environments; nothing else.
