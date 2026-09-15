"""The obsolete RF harness remains a no-I/O fail-closed compatibility stub."""

import pytest
from tools.campaign_integrity_e import fit_missing_rf

from tennislab.integrity.campaign import CampaignIntegrityError


def test_paused_rf_entry_point_refuses_before_any_input_read(tmp_path):
    with pytest.raises(CampaignIntegrityError, match="RF fits paused by Lane 0"):
        fit_missing_rf(tmp_path / "absent-case", tmp_path / "absent-product")
    assert list(tmp_path.iterdir()) == []
