# Lane D third repair-attempt contract

Status: **frozen before new controls, implementation, or verification against the
rejected second repair `4295df4`**. Every earlier commit, contract, freeze, report and
review world remains evidence. This attempt addresses only the current-version
settlement resolver conflict independently reproduced on ATP and WTA. F2, F3, model
logic, D2 and real-data work are outside its change scope.

## Single invariant

A version can have two earlier trust sources: one or more hash-chained
`fixture_qualified` records and, for the current version, `versions/latest.json`. Resolve
them once, with the same rule for explicit and default settlement:

1. verify the ledger before reading qualification anchors for the requested version;
2. no qualification digest: a matching current pointer digest is an admissible initial
   anchor, so a legitimate unqualified current version continues to work;
3. exactly one qualification digest: it is the prior anchor. A matching current pointer
   may agree, but a conflicting pointer must be refused rather than replace it;
4. more than one distinct qualification digest: refuse as conflicting prior anchors,
   regardless of the current pointer;
5. no qualification and no matching current pointer: refuse as unbound;
6. pass the resolved digest into `load_version` on both explicit and default routes.

The rule is version-ID-specific. A valid update that creates a new current version ID has
no inherited conflict and must still work. A digest proves unchanged bytes since the
relevant trust assignment; it does not prove the initial source, receipt, publication or
custody claim true.

## Public failing controls frozen for this attempt

All controls use the tracked synthetic workspace and public `tennislab.cli.main` path.

- Run valid update then fixture qualification. Keep the qualification ledger and fixture
  bytes unchanged. Edit receipt `finished_utc`, coherently rehash its version-manifest
  binding, and update only the mutable latest pointer to the edited manifest digest.
  Explicit `settle results --version <current-id>` must refuse the pointer/qualification
  conflict.
- Repeat the same setup through default `settle results`; it must apply the identical
  resolver and refuse. A caller-specific explicit-only patch is not acceptable.
- Establish two distinct qualification digests for the same version through public
  fixture commands around the coherent manifest/pointer edit; both explicit and default
  settlement must refuse the conflicting prior anchors.
- Preserve positive public paths: unqualified current explicit/default settlement,
  qualified current settlement when pointer and ledger agree, qualification-bound older
  versions, and a newly updated current version ID. Retain the F2/F3 controls, valid
  numerical equalities and ledger behavior without changing them.

Only resolver precedence/reconciliation and the smallest necessary tests/docs/config
binding may change. No full historical rerun is required for this isolated follow-up;
run affected live tests, shared-writer/hygiene/lint checks and normal synthetic
numerical/ledger controls. Independent acceptance remains external to the builder.
