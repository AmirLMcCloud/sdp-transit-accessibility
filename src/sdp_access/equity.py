"""Equity analysis: scenario deltas, OLS with HC3 SEs, diagnostics, sensitivity, race-quartile tables."""
from __future__ import annotations

import logging

import geopandas as gpd
import numpy as np
import pandas as pd
import statsmodels.api as sm
import statsmodels.formula.api as smf
from scipy import stats
from statsmodels.stats.diagnostic import het_breuschpagan
from statsmodels.stats.outliers_influence import variance_inflation_factor

log = logging.getLogger(__name__)

RACE_VARS = ["pct_black", "pct_hispanic", "pct_asian"]          # pct_white = reference
CONTROLS = ["pct_poverty", "pct_carfree", "pct_transit", "baseline_min_tt", "log_total_pop"]
IMPUTE_COLS = ["pct_poverty", "pct_carfree", "pct_transit"]


# ------------------------------------------------------------ scenario deltas
def build_delta_frame(bg: gpd.GeoDataFrame, orig: pd.DataFrame, fmp: pd.DataFrame,
                      thresholds: list[int]) -> gpd.GeoDataFrame:
    """Join block groups to original/FMP aggregates and compute FMP − original changes.
    Positive delta_min_tt = longer trip (worse). Negative delta_access_X = fewer schools within X min (worse)."""
    o = orig.add_suffix("_orig").rename(columns={"GEOID_orig": "GEOID"})
    f = fmp.add_suffix("_fmp").rename(columns={"GEOID_fmp": "GEOID"})
    df = bg.merge(o, on="GEOID", how="left", validate="one_to_one").merge(f, on="GEOID", how="left", validate="one_to_one")
    df["baseline_min_tt"] = df["min_tt_orig"]
    df["delta_min_tt"] = df["min_tt_fmp"] - df["min_tt_orig"]
    for t in thresholds:
        df[f"baseline_access_{t}"] = df[f"schools_within_{t}_orig"]
        df[f"delta_access_{t}"] = df[f"schools_within_{t}_fmp"] - df[f"schools_within_{t}_orig"]
    df["any_capped"] = df["capped_orig"].fillna(False).astype(bool) | df["capped_fmp"].fillna(False).astype(bool)
    return df


def flag_study_area(df: gpd.GeoDataFrame, orig_catchments: gpd.GeoDataFrame, catch_id: str,
                    closed_ids: list[str], buffer_m: float, crs_proj: str) -> gpd.GeoDataFrame:
    """study_area=True for block groups within buffer_m of a closed school's original catchment.
    Addresses treatment dilution (one closure vs. ~1,300 block groups)."""
    df = df.copy()
    closed = orig_catchments[orig_catchments[catch_id].astype(str).isin(closed_ids)].to_crs(crs_proj)
    if closed.empty:
        log.warning("No closed-school catchment found; study_area = all block groups")
        df["study_area"] = True
        return df
    zone = closed.geometry.union_all().buffer(buffer_m)
    cents = df.to_crs(crs_proj).geometry.centroid
    df["study_area"] = cents.within(zone).values
    return df


# ------------------------------------------------------------ regression frame
def prepare_regression_frame(df: pd.DataFrame, min_pop: int) -> pd.DataFrame:
    """Filter by population, impute control NaNs with the median (guarded against all-NaN),
    add log_total_pop. Race variables are never imputed — rows missing them are dropped."""
    d = pd.DataFrame(df).copy()
    d = d[d["total_pop"] >= min_pop]
    d = d.dropna(subset=RACE_VARS + ["baseline_min_tt"])
    for c in IMPUTE_COLS:
        n = int(d[c].isna().sum())
        if n == 0:
            continue
        med = d[c].median()
        if np.isnan(med):
            raise ValueError(f"{c} is entirely NaN — cannot impute (check ACS pull)")
        log.info("Imputing %d NaN in %s with median %.3f", n, c, med)
        d[c] = d[c].fillna(med)
    d["log_total_pop"] = np.log(d["total_pop"])
    return d


def make_formula(dv: str, baseline_access: str | None = None) -> str:
    rhs = RACE_VARS + [c for c in CONTROLS]
    if baseline_access:
        rhs = rhs + [baseline_access]
    return f"{dv} ~ " + " + ".join(rhs)


def run_ols(data: pd.DataFrame, formula: str):
    return smf.ols(formula, data=data).fit(cov_type="HC3")


def diagnostics(model, data: pd.DataFrame) -> dict:
    resid = model.resid
    bp = het_breuschpagan(resid, model.model.exog)
    sw = stats.shapiro(resid) if len(resid) <= 5000 else stats.shapiro(resid.sample(5000, random_state=0))
    X = pd.DataFrame(model.model.exog, columns=model.model.exog_names)
    vif = {c: variance_inflation_factor(X.values, i) for i, c in enumerate(X.columns) if c != "Intercept"}
    return {"n": int(model.nobs), "r2": model.rsquared, "adj_r2": model.rsquared_adj,
            "breusch_pagan_p": bp[1], "shapiro_p": sw[1], "vif": vif}


def coef_table(model) -> pd.DataFrame:
    ci = model.conf_int()
    return pd.DataFrame({"coef": model.params, "se": model.bse, "p": model.pvalues,
                         "ci_low": ci[0], "ci_high": ci[1]})


# ------------------------------------------------------------ sensitivity
def sensitivity_table(frame: pd.DataFrame, thresholds: list[int]) -> pd.DataFrame:
    """Race coefficients across outcomes (delta_min_tt + delta_access_X) × samples
    (all / study area / study area excl. capped). Primary robustness exhibit."""
    outcomes = ["delta_min_tt"] + [f"delta_access_{t}" for t in thresholds]
    samples = {"all": frame,
               "study_area": frame[frame["study_area"]],
               "study_area_uncapped": frame[frame["study_area"] & ~frame["any_capped"]]}
    rows = []
    for sname, sdf in samples.items():
        for dv in outcomes:
            sub = sdf.dropna(subset=[dv])
            if len(sub) < len(RACE_VARS + CONTROLS) + 5:
                rows.append({"sample": sname, "outcome": dv, "n": len(sub)}); continue
            if sub[dv].nunique() <= 1:
                rows.append({"sample": sname, "outcome": dv, "n": len(sub), "note": "no variation in DV"}); continue
            t = dv.rsplit("_", 1)[-1]
            ba = f"baseline_access_{t}" if dv.startswith("delta_access_") else None
            m = run_ols(sub, make_formula(dv, ba))
            for r in RACE_VARS:
                rows.append({"sample": sname, "outcome": dv, "n": int(m.nobs), "term": r,
                             "coef": m.params[r], "se": m.bse[r], "p": m.pvalues[r]})
    return pd.DataFrame(rows)


# ------------------------------------------------------------ race quartiles
def race_quartile_table(data: pd.DataFrame, var: str, outcome: str, q: int = 4) -> pd.DataFrame:
    """Mean baseline and outcome by quartile of a race share. Duplicate bin edges are dropped
    (common for sparse groups such as pct_asian), so fewer than q groups may result."""
    d = data.dropna(subset=[var, outcome]).copy()
    if d[var].nunique() < 2:     # constant column: qcut has no valid edges
        d["grp"] = f"All (constant {d[var].iloc[0]:.0%})" if len(d) else "All"
    else:
        _, bins = pd.qcut(d[var], q, retbins=True, duplicates="drop")
        labels = [f"Q{i + 1} ({bins[i]:.0%}–{bins[i + 1]:.0%})" for i in range(len(bins) - 1)]
        d["grp"] = pd.qcut(d[var], q, labels=labels, duplicates="drop")
    return (d.groupby("grp", observed=True)
              .agg(n_bg=("GEOID", "size"), baseline_min_tt=("baseline_min_tt", "mean"),
                   mean_outcome=(outcome, "mean"), total_pop=("total_pop", "sum"))
              .reset_index().rename(columns={"grp": f"{var}_quartile"}))
