import pytest
from sdp_access.config import load_config
from sdp_access.synthesis import safe_sheet


def test_repo_config_valid():
    cfg = load_config()
    assert cfg.departure is None and cfg.levels == ["high"]
    assert max(cfg.a["access_thresholds_min"]) <= cfg.a["max_travel_min"]


def test_departure_outside_feed_rejected():
    cfg = load_config()
    cfg.raw["gtfs"].update({"departure": "2030-01-01T08:00:00", "feed_valid_from": "2026-06-14", "feed_valid_to": "2026-08-22"})
    with pytest.raises(ValueError):
        cfg.validate()


def test_sheet_name_sanitised():
    assert "/" not in safe_sheet("pct_asian/quartile") and len(safe_sheet("x" * 50)) == 31
