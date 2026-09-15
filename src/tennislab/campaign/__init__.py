"""Frozen Lane E campaign mechanics.

The package is intentionally separate from the historical chain.  It consumes
manifest-bound raw forecasts, emits S0--S3 forecasts before a hash barrier, and scores
them only in the explicit post-barrier report command.
"""

from tennislab.campaign.members import MEMBER_IDS, MemberSpec, member_specs

__all__ = ["MEMBER_IDS", "MemberSpec", "member_specs"]
