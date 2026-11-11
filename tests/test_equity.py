import numpy as np
import pytest
from sdp_access import equity as E


def _frame(bg_frame, access_tables):
    o, f, th = access_tables
    df = E.build_delta_frame(bg_frame, o, f, th)
    df["study_area"] = np.arange(len(df)) < 60
    return df, th


def test_delta_is_fmp_minus_original(bg_frame, access_tables):
    df, th = _frame(bg_frame, access_tables)
    o, f, _ = access_tables
    assert len(df) == len(bg_frame)
    np.testing.assert_allclose(df.delta_min_tt, f.min_tt.values - o.min_tt.values)
    np.testing.assert_array_equal(df.delta_access_30, f.schools_within_30.values - o.schools_within_30.values)
    assert df.GEOID.is_unique and df.GEOID.str.len().eq(12).all()


def test_regression_frame_has_no_nans(bg_frame, access_tables):
    df, _ = _frame(bg_frame, access_tables)
    df.loc[3, "pct_poverty"] = np.nan
    reg = E.prepare_regression_frame(df, 100)
    assert reg[E.RACE_VARS + E.CONTROLS].notna().all().all()


def test_all_nan_control_raises(bg_frame, access_tables):
    df, _ = _frame(bg_frame, access_tables)
    df["pct_transit"] = np.nan
    with pytest.raises(ValueError):
        E.prepare_regression_frame(df, 100)


def test_ols_recovers_planted_effect(bg_frame, access_tables):
    df, _ = _frame(bg_frame, access_tables)
    df["delta_min_tt"] = 20 * df.pct_black + np.random.default_rng(2).normal(0, .5, len(df))
    reg = E.prepare_regression_frame(df, 100)
    m = E.run_ols(reg, E.make_formula("delta_min_tt"))
    assert m.params["pct_black"] == pytest.approx(20, abs=3) and m.pvalues["pct_black"] < .01
    assert set(E.diagnostics(m, reg)) >= {"breusch_pagan_p", "vif", "n"}


def test_sensitivity_differs_across_outcomes(bg_frame, access_tables):
    df, th = _frame(bg_frame, access_tables)
    reg = E.prepare_regression_frame(df, 100)
    s = E.sensitivity_table(reg, th).dropna(subset=["term"])
    assert set(s.outcome) == {"delta_min_tt", *[f"delta_access_{t}" for t in th]}
    # DVs built from different thresholds must not collapse to identical estimates
    c = s[(s["sample"] == "all") & (s.term == "pct_black")].set_index("outcome").coef
    assert c.nunique() == len(c)


def test_quartiles_handle_duplicate_edges(bg_frame):
    d = bg_frame.assign(pct_asian=0.0, baseline_min_tt=10.0, delta_access_30=-1)
    t = E.race_quartile_table(d, "pct_asian", "delta_access_30")
    assert len(t) >= 1 and t.n_bg.sum() == len(d)
