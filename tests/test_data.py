import numpy as np
import pandas as pd
import geopandas as gpd
import pytest
from shapely.geometry import Point
from sdp_access import data as D


def test_safe_div_nan_not_inf():
    r = D.safe_div(pd.Series([1, 2, 3]), pd.Series([2, 0, np.nan]))
    assert r.iloc[0] == .5 and r.iloc[1:].isna().all()


def test_derive_equity_vars_shares_bounded():
    df = pd.DataFrame({"total_pop": [100], "white_alone_nonhisp": [50], "black_alone_nonhisp": [30],
                       "asian_alone_nonhisp": [10], "hispanic_latino": [10], "snap_universe": [40],
                       "snap_recipients": [10], "owner_no_vehicle": [2], "renter_no_vehicle": [8],
                       "tenure_universe": [40], "commute_transit": [5], "commute_universe": [50],
                       "male_5_9": [1], "male_10_14": [1], "male_15_17": [1], "female_5_9": [1],
                       "female_10_14": [1], "female_15_17": [1], "age_universe": [100]})
    o = D.derive_equity_vars(df)
    assert o.pct_black[0] == .3 and o.pct_carfree[0] == .25 and o.pct_schoolage[0] == .06
    assert o[[c for c in o if c.startswith("pct_")]].le(1).all().all()


def test_stable_ids_fallback_matches_across_layers():
    a = gpd.GeoDataFrame({"n": [1, 2]}, geometry=[Point(-75.1, 40.0), Point(-75.2, 40.0)], crs=4326)
    b = a.iloc[[0]]
    ia, ib = D.stable_ids(a, "school_id"), D.stable_ids(b, "school_id")
    assert D.closed_school_ids(ia, ib) == [ia.sid.iloc[1]]


def test_stable_ids_duplicate_raises():
    g = gpd.GeoDataFrame({"school_id": ["x", "x"]}, geometry=[Point(0, 0), Point(1, 1)], crs=4326)
    with pytest.raises(ValueError):
        D.stable_ids(g, "school_id")


def test_id_override_fixes_placeholder_and_matches_catchments():
    pts = gpd.GeoDataFrame({"location_i": ["4020", "0"], "school_n_1": ["OVERBROOK HIGH SCHOOL", "PENN TREATY HIGH SCHOOL"]},
                           geometry=[Point(-75.2, 39.97), Point(-75.1, 39.97)], crs=4326)
    out = D.stable_ids(pts, "location_i", {"PENN TREATY HIGH SCHOOL": "5160"}, "school_n_1")
    assert list(out.sid) == ["4020", "5160"]


def test_load_catchments_dedupes_and_is_case_insensitive(tmp_path):
    from shapely.geometry import box
    g = gpd.GeoDataFrame({"HS_ID": ["1", "2", "1"]}, geometry=[box(0, 0, 1, 1), box(1, 0, 2, 1), box(0, 0, 1, 1)], crs=4326)
    f = tmp_path / "c.shp"; g.to_file(f)
    out = D.load_catchments(f, "hs_id")
    assert list(out.sid) == ["1", "2"]


def test_per_row_id_fallback_keeps_other_rows_matching():
    orig = gpd.GeoDataFrame({"location_i": ["4020", None, "0"], "school_n_1": ["A", "PENN TREATY HIGH SCHOOL", "B"]},
                            geometry=[Point(-75.2, 39.97), Point(-75.1, 39.97), Point(-75.0, 39.9)], crs=4326)
    fmp = orig.iloc[[0, 2]]
    o = D.stable_ids(orig, "location_i", {"PENN TREATY HIGH SCHOOL": "5160"}, "school_n_1")
    f = D.stable_ids(fmp, "location_i", {"PENN TREATY HIGH SCHOOL": "5160"}, "school_n_1")
    assert o.sid.iloc[0] == "4020" and o.sid.iloc[1] == "5160"
    assert D.closed_school_ids(o, f) == ["5160"]
