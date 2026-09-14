"""Live update, prospective fixtures and the prospective ledger (Lane D).

Design: ``docs/live/DESIGN.md``. Nothing here touches a historical chain, a frozen config
or the equivalence oracle; every write lands under the live workspace directory named by
``configs/live/live.json`` (``data/live`` by default), inside the declared workspace.
"""
