"""Data assembly: ACS block-group demographics + TIGER geometry + input checks."""
from __future__ import annotations

import logging
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import requests

from .config import Config

log = logging.getLogger(__name__)
SENTINEL = -666666666


def pull_acs(year: int, variables: dict, api_key: str, state: str, county: str) -> pd.DataFrame:
    var_str = ",".join(["NAME", *variables])
    resp = requests.get(
        f"https://api.census.gov/data/{year}/acs/acs5",
        params={"get": var_str, "for": "block group:*", "in": f"state:{state} county:{county}", "key": api_key},
        timeout=60,
    )
    resp.raise_for_status()
    data = resp.json()
    df = pd.DataFrame(data[1:], columns=data[0])
    df["GEOID"] = df["state"] + df["county"] + df["tract"] + df["block group"]
    cols = list(variables)
    df[cols] = df[cols].apply(pd.to_numeric, errors="coerce").replace(SENTINEL, np.nan)
    return df.rename(columns=variables)


def safe_div(num: pd.Series, den: pd.Series) -> pd.Series:
    """num/den, NaN (not inf, not epsilon-division) where den is missing or <= 0."""
    num = pd.to_numeric(num, errors="coerce").astype(float)
    den = pd.to_numeric(den, errors="coerce").astype(float)
    return num.where(den > 0) / den.where(den > 0)


def derive_equity_vars(df: pd.DataFrame) -> pd.DataFrame:
    """Proportional equity variables. Poverty proxy = SNAP receipt (B17001 suppressed at BG level)."""
    df = df.copy()
    df["pct_white"] = safe_div(df["white_alone_nonhisp"], df["total_pop"])
    df["pct_black"] = safe_div(df["black_alone_nonhisp"], df["total_pop"])
    df["pct_asian"] = safe_div(df["asian_alone_nonhisp"], df["total_pop"])
    df["pct_hispanic"] = safe_div(df["hispanic_latino"], df["total_pop"])
    df["pct_poverty"] = safe_div(df["snap_recipients"], df["snap_universe"])
    df["hh_no_vehicle"] = df["owner_no_vehicle"] + df["renter_no_vehicle"]
    df["pct_carfree"] = safe_div(df["hh_no_vehicle"], df["tenure_universe"])
    df["pct_transit"] = safe_div(df["commute_transit"], df["commute_universe"])
    age = ["male_5_9", "male_10_14", "male_15_17", "female_5_9", "female_10_14", "female_15_17"]
    df["schoolage_pop"] = df[age].sum(axis=1, min_count=len(age))
    df["pct_schoolage"] = safe_div(df["schoolage_pop"], df["age_universe"])
    pct = [c for c in df.columns if c.startswith("pct_")]
    df[pct] = df[pct].clip(0, 1)
    for c in pct:
        n = int(df[c].isna().sum())
        if n:
            log.warning("ACS suppression: %d NaN in %s", n, c)
    return df


def attach_tiger_geometry(df: pd.DataFrame, year: int, state: str, county: str) -> gpd.GeoDataFrame:
    url = ("https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/"
           f"tigerWMS_ACS{year}/MapServer/8/query")
    resp = requests.get(url, params={
        "where": f"STATE='{state}' AND COUNTY='{county}'", "outFields": "GEOID,AREALAND",
        "f": "geojson", "returnGeometry": "true"}, timeout=120)
    resp.raise_for_status()
    payload = resp.json()
    if "error" in payload:
        raise RuntimeError(f"TIGERweb query failed: {payload['error']}")
    gdf = gpd.GeoDataFrame.from_features(payload["features"], crs="EPSG:4326")
    return gdf.merge(df, on="GEOID", how="left", validate="one_to_one")


def preflight(cfg: Config) -> list[str]:
    """Return a list of missing required inputs (empty = good)."""
    required = {"SEPTA GTFS zip": cfg.gtfs_zip}
    for lvl in cfg.levels:
        for scen in ("original", "fmp"):
            for kind, p in cfg.level(lvl)[scen].items():
                required[f"{lvl}/{scen}/{kind}"] = p
    return [f"{k}: {Path(v)}" for k, v in required.items() if not Path(v).exists()]


def build_blockgroups(cfg: Config) -> gpd.GeoDataFrame:
    acs = pull_acs(cfg.raw["acs"]["year"], cfg.acs_vars, cfg.census_key,
                   cfg.raw["acs"]["state"], cfg.raw["acs"]["county"])
    acs.to_csv(cfg.raw_dir / "acs_raw.csv", index=False)
    gdf = attach_tiger_geometry(derive_equity_vars(acs), cfg.raw["acs"]["year"],
                                cfg.raw["acs"]["state"], cfg.raw["acs"]["county"])
    out = cfg.raw_dir / "philly_blockgroups.gpkg"
    gdf.to_file(out, layer="block_groups", driver="GPKG")
    log.info("Wrote %s (%d block groups)", out, len(gdf))
    return gdf


def stable_ids(gdf: gpd.GeoDataFrame, id_field: str | None, overrides: dict | None = None,
               name_field: str | None = None) -> gpd.GeoDataFrame:
    """Ensure a stable `sid` key. Uses id_field if present, else a rounded-coordinate key
    (identical across scenario layers that share geometry). `overrides` maps a school name
    (matched case-insensitively on name_field) to an id, for rows with placeholder ids."""
    gdf = gdf.copy()
    pts = gdf.to_crs(4326).geometry
    coord = pts.x.round(5).astype(str) + "_" + pts.y.round(5).astype(str)
    if id_field and id_field in gdf.columns:
        raw = gdf[id_field].astype(str).str.strip()
        bad = gdf[id_field].isna() | raw.isin(["", "0", "nan", "None", "<NA>"])
        if bad.any():
            log.warning("%d row(s) have a missing/placeholder %r (rows %s); using coordinate keys for those rows "
                        "(add an id_override if they must match another layer)", int(bad.sum()), id_field,
                        gdf.index[bad].tolist())
        gdf["sid"] = raw.where(~bad, coord)
    else:
        log.warning("id_field %r not in layer; using coordinate keys for all rows", id_field)
        gdf["sid"] = coord
    if overrides and name_field and name_field in gdf.columns:
        names = gdf[name_field].astype(str).str.strip().str.upper()
        for name, new_id in overrides.items():
            m = names == name.strip().upper()
            if m.any():
                gdf.loc[m, "sid"] = str(new_id)
    if gdf["sid"].duplicated().any():
        raise ValueError("School ids are not unique: " + ", ".join(gdf.loc[gdf.sid.duplicated(), "sid"]))
    return gdf


def load_catchments(path, id_field: str) -> gpd.GeoDataFrame:
    """Read a catchment layer; add string key `sid` from id_field (case-insensitive).
    Rows repeating an id are dropped (first kept) and logged — some hosted layers stack
    near-identical copies of the same polygon."""
    gdf = gpd.read_file(path)
    col = {c.lower(): c for c in gdf.columns}.get(id_field.lower())
    if col is None:
        raise KeyError(f"{id_field!r} not in {Path(path).name}; columns: {list(gdf.columns)}")
    gdf["sid"] = gdf[col].astype(str).str.strip()
    n = len(gdf)
    gdf = gdf.drop_duplicates("sid", keep="first").reset_index(drop=True)
    if len(gdf) < n:
        log.warning("%s: dropped %d duplicate catchment rows (kept first per %s)", Path(path).name, n - len(gdf), col)
    return gdf


def closed_school_ids(orig: gpd.GeoDataFrame, fmp: gpd.GeoDataFrame) -> list[str]:
    return sorted(set(orig["sid"]) - set(fmp["sid"]))


# ---------------------------------------------------------------- hosted ArcGIS layers
def fetch_agol_layer(item_id: str, layer: int = 0, page: int = 1000) -> gpd.GeoDataFrame:
    """Download a PUBLIC hosted feature layer by item id via the REST API (no arcgis package, no login)."""
    meta = requests.get(f"https://www.arcgis.com/sharing/rest/content/items/{item_id}",
                        params={"f": "json"}, timeout=60).json()
    if "url" not in meta:
        raise RuntimeError(f"Item {item_id} not found or not public: {meta.get('error', meta)}")
    q = f"{meta['url'].rstrip('/')}/{layer}/query"
    feats, offset = [], 0
    while True:
        r = requests.get(q, params={"where": "1=1", "outFields": "*", "outSR": 4326, "f": "geojson",
                                    "resultOffset": offset, "resultRecordCount": page}, timeout=120).json()
        if "error" in r:
            raise RuntimeError(f"Query failed for {item_id}: {r['error']}")
        batch = r.get("features", [])
        feats += batch
        if len(batch) < page and not r.get("exceededTransferLimit"):
            break
        offset += len(batch)
    if not feats:
        raise RuntimeError(f"Layer {item_id} returned no features")
    return gpd.GeoDataFrame.from_features(feats, crs="EPSG:4326")


def fetch_hosted_inputs(cfg: Config, overwrite: bool = False) -> None:
    for lvl in cfg.levels:
        items = cfg.raw["levels"][lvl].get("agol")
        if not items:
            log.warning("No agol items configured for %s", lvl); continue
        paths = cfg.level(lvl)
        for scen in ("original", "fmp"):
            for kind, item_id in items[scen].items():
                dest = paths[scen][kind]
                if dest.exists() and not overwrite:
                    log.info("exists, skipping: %s", dest.name); continue
                dest.parent.mkdir(parents=True, exist_ok=True)
                gdf = fetch_agol_layer(item_id)
                gdf.to_file(dest)
                log.info("fetched %s/%s/%s -> %s (%d features)", lvl, scen, kind, dest.name, len(gdf))
