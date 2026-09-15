"""Public fail-closed boundary for the retired pre-repair RF harness entry point.

The accepted campaign implementation fits RF members through the manifest-bound
``tennislab.campaign`` graph.  This legacy helper name remains importable only so an
old or partial harness cannot fall through to an unbound fit path.
"""

from pathlib import Path

from tennislab.integrity.campaign import CampaignIntegrityError


def fit_missing_rf(case: Path, product_root: Path) -> None:
    """Refuse the obsolete unbound RF-fit route before reading either argument."""
    del case, product_root
    raise CampaignIntegrityError(
        "RF fits paused by Lane 0; use the reviewed manifest-bound campaign graph"
    )
