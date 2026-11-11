"""Routing: OSMnx walk isochrones + catchment coverage, and r5py walk+transit travel times."""
from __future__ import annotations

import csv
import datetime as dt
import io
import logging
import os
import zipfile
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

from .config import Config

log = logging.getLogger(__name__)


# ---------------------------------------------------------------- OSMnx isochrones
def load_walk_graph(cfg: Config):
    import osmnx as ox
    if cfg.graphml.exists():
        return ox.load_graphml(cfg.graphml)
    G = ox.graph_from_place("Philadelphia, Pennsylvania, USA", network_type="walk")
    cfg.graphml.parent.mkdir(parents=True, exist_ok=True)
    ox.save_graphml(G, cfg.graphml)
    return G


def add_travel_time(G, speed_ms: float):
    for _, _, _, d in G.edges(keys=True, data=True):
        d["travel_time"] = d["length"] / speed_ms
    return G


def build_isochrones(G, schools: gpd.GeoDataFrame, minutes: list[int],
                     speed_ms: float, edge_buffer_m: float, crs_proj: str) -> gpd.GeoDataFrame:
    """Cumulative + donut-ring walk isochrones per school. Output CRS = EPSG:4326."""
    import networkx as nx
    import osmnx as ox
    G = add_travel_time(G, speed_ms)
    pts = schools.to_crs(4326)
    nodes = ox.distance.nearest_nodes(G, pts.geometry.x.values, pts.geometry.y.values)
    rows = []
    for sid, node in zip(schools["sid"], nodes):
        prev = None
        for m in sorted(minutes):
            sub = nx.ego_graph(G, node, radius=m * 60, distance="travel_time")
            if sub.number_of_edges() == 0:   # radius shorter than any edge: fall back to the node itself
                nd = ox.graph_to_gdfs(sub, edges=False).to_crs(crs_proj)
                poly = nd.geometry.buffer(edge_buffer_m).union_all()
            else:
                edges = ox.graph_to_gdfs(sub, nodes=False).to_crs(crs_proj)
                poly = edges.geometry.buffer(edge_buffer_m).union_all()
            ring = poly if prev is None else poly.difference(prev)
            rows.append({"sid": sid, "minutes": m, "geometry": poly, "ring": ring})
            prev = poly
    out = gpd.GeoDataFrame(rows, geometry="geometry", crs=crs_proj)
    ring = gpd.GeoSeries(out["ring"], crs=crs_proj)
    out = out.drop(columns="ring")
    out_ring = out.copy()
    out_ring["geometry"] = ring
    out_ring["kind"], out["kind"] = "ring", "cumulative"
    return pd.concat([out, out_ring], ignore_index=True).pipe(gpd.GeoDataFrame, crs=crs_proj).to_crs(4326)


def catchment_coverage(iso: gpd.GeoDataFrame, catchments: gpd.GeoDataFrame, catch_id: str,
                       blockgroups: gpd.GeoDataFrame, minutes: int, crs_proj: str) -> pd.DataFrame:
    """Per school: % of its catchment area, and % of its catchment's block-group centroids,
    inside the cumulative `minutes` walk isochrone. Ambiguous centroid matches are logged."""
    catch = catchments.assign(sid=catchments[catch_id].astype(str)).to_crs(crs_proj)
    cum = iso[(iso.kind == "cumulative") & (iso.minutes == minutes)].to_crs(crs_proj).set_index("sid")
    cents = gpd.GeoDataFrame(blockgroups[["GEOID"]], geometry=blockgroups.to_crs(crs_proj).centroid, crs=crs_proj)
    j = gpd.sjoin(cents, catch[["sid", "geometry"]], how="inner", predicate="within")
    amb = j.index[j.index.duplicated()].unique()
    if len(amb):
        log.warning("%d block-group centroids matched >1 catchment; keeping first", len(amb))
    j = j[~j.index.duplicated(keep="first")]
    rows = []
    for _, c in catch.iterrows():
        sid = c["sid"]
        if sid not in cum.index:
            rows.append({"sid": sid, "pct_catchment_area": np.nan, "pct_bg_centroids": np.nan}); continue
        iso_geom = cum.loc[sid, "geometry"]
        area = c.geometry.intersection(iso_geom).area / c.geometry.area if c.geometry.area else np.nan
        inside = cents.loc[j.index[j.sid == sid]]
        share = inside.within(iso_geom).mean() if len(inside) else np.nan
        rows.append({"sid": sid, "pct_catchment_area": 100 * area, "pct_bg_centroids": 100 * share})
    return pd.DataFrame(rows).assign(minutes=minutes)


# ---------------------------------------------------------------- r5py
def ensure_java(java_home: str | None = None) -> None:
    """r5py needs JDK 17+. jpype may otherwise pick an old JRE; JAVA_HOME wins."""
    jh = java_home or os.environ.get("JAVA_HOME")
    if not jh:
        raise RuntimeError("JAVA_HOME not set. Install JDK 21 (conda: openjdk=21) and set JAVA_HOME.")
    os.environ["JAVA_HOME"] = jh


def prepare_gtfs(cfg: Config) -> list[str]:
    """Return GTFS zip path(s) r5py can read. Handles three layouts:
      * flat zip (stop_times.txt at the root)        -> used as is
      * zip of zips (e.g. SEPTA google_bus/google_rail) -> inner zips extracted, each used as a feed
      * flat files inside a subfolder                -> rebuilt as a flat zip"""
    z = Path(cfg.gtfs_zip)
    out_dir = cfg.raw_dir / "gtfs_feeds"
    with zipfile.ZipFile(z) as zf:
        names = zf.namelist()
        if "stop_times.txt" in names:
            return [str(z)]
        nested = [n for n in names if n.lower().endswith(".zip")]
        if nested:
            out_dir.mkdir(parents=True, exist_ok=True)
            paths = []
            for n in nested:
                dest = out_dir / Path(n).name
                dest.write_bytes(zf.read(n))
                paths.append(str(dest))
            log.info("GTFS zip contains nested feeds: %s", [Path(p).name for p in paths])
            return paths
        hits = [n for n in names if n.endswith("/stop_times.txt")]
        if hits:
            prefix = hits[0][: -len("stop_times.txt")]
            out_dir.mkdir(parents=True, exist_ok=True)
            dest = out_dir / "flattened_gtfs.zip"
            with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zo:
                for n in names:
                    if n.startswith(prefix) and n.endswith(".txt"):
                        zo.writestr(n[len(prefix):], zf.read(n))
            return [str(dest)]
    raise RuntimeError(f"{z.name} has no GTFS tables (stop_times.txt) and no nested zips; contents: {names[:10]}")


def _read_table(zpath: str, name: str) -> list[dict]:
    with zipfile.ZipFile(zpath) as zf:
        if name not in zf.namelist():
            return []
        return list(csv.DictReader(io.TextIOWrapper(zf.open(name), encoding="utf-8-sig")))


def gtfs_service_info(feeds: list[str]) -> dict:
    """Service range and Tuesday-activity of the loaded feeds (calendar.txt + calendar_dates.txt)."""
    ymd = lambda x: dt.datetime.strptime(x.strip(), "%Y%m%d").date()
    cal, added, removed = [], set(), set()
    for f in feeds:
        for r in _read_table(f, "calendar.txt"):
            cal.append((ymd(r["start_date"]), ymd(r["end_date"]), r["tuesday"].strip() == "1"))
        for r in _read_table(f, "calendar_dates.txt"):
            (added if r["exception_type"].strip() == "1" else removed).add(ymd(r["date"]))
    if not cal and not added:
        raise RuntimeError("GTFS feeds have no calendar.txt/calendar_dates.txt; cannot determine service dates")
    lo = min([c[0] for c in cal] + list(added)); hi = max([c[1] for c in cal] + list(added))
    return {"cal": cal, "added": added, "removed": removed, "start": lo, "end": hi}


def _active(info: dict, d: dt.date) -> bool:
    if d in info["removed"] and d not in info["added"]:
        return False
    return d in info["added"] or any(s <= d <= e and tue for s, e, tue in info["cal"] if d.weekday() == 1)


def resolve_departure(cfg: Config, feeds: list[str]) -> tuple[dt.datetime, dict]:
    """Explicit cfg departure (validated against the feed) or, for "auto", the Tuesday with
    service nearest the middle of the feed's range. Returns (departure, metadata)."""
    info = gtfs_service_info(feeds)
    t = dt.time.fromisoformat(cfg.raw["gtfs"].get("departure_time", "08:00"))
    explicit = cfg.departure
    if explicit is not None:
        if not (info["start"] <= explicit.date() <= info["end"]):
            raise ValueError(f"departure {explicit} is outside the feed's service range "
                             f"{info['start']}–{info['end']}; set gtfs.departure to \"auto\" or a date in range")
        dep = explicit
    else:
        mid = info["start"] + (info["end"] - info["start"]) / 2
        days = [info["start"] + dt.timedelta(days=i) for i in range((info["end"] - info["start"]).days + 1)]
        avoid = cfg.raw["gtfs"].get("avoid_ranges", [])

        def avoided(d: dt.date) -> bool:
            for r in avoid:
                (m1, d1), (m2, d2) = (tuple(int(x) for x in part.split("-")) for part in r.split("/"))
                md = (d.month, d.day)
                if ((m1, d1) <= md <= (m2, d2)) if (m1, d1) <= (m2, d2) else (md >= (m1, d1) or md <= (m2, d2)):
                    return True
            return False

        tues = [d for d in days if d.weekday() == 1 and _active(info, d)]
        clean = [d for d in tues if not avoided(d) and d not in info["added"] and d not in info["removed"]]
        cands = clean or [d for d in tues if not avoided(d)] or tues
        if not clean:
            log.warning("No ordinary school-year Tuesday in the feed; relaxed date filters (check run_metadata.json)")
        cands = sorted(cands, key=lambda d: abs(d - mid))
        if not cands:
            raise RuntimeError("No Tuesday with scheduled service found in the GTFS feed")
        dep = dt.datetime.combine(cands[0], t)
    meta = {"departure": dep.isoformat(), "gtfs_service_start": info["start"].isoformat(),
            "gtfs_service_end": info["end"].isoformat(), "gtfs_files": [Path(f).name for f in feeds],
            "departure_window_min": cfg.raw["gtfs"]["departure_window_min"]}
    log.info("GTFS service %s to %s; departure %s", meta["gtfs_service_start"], meta["gtfs_service_end"], dep)
    return dep, meta


def compute_travel_matrix(cfg: Config, origins: gpd.GeoDataFrame, schools: gpd.GeoDataFrame,
                          feeds: list[str], departure: dt.datetime) -> pd.DataFrame:
    """Walk+SEPTA transit travel time (min) from block-group centroids to each school.
    Returns long df [from_id, to_id, travel_time]; unreachable pairs are NaN."""
    ensure_java()
    import r5py
    net = r5py.TransportNetwork(str(cfg.pbf_path), feeds)
    o = gpd.GeoDataFrame({"id": origins["GEOID"].values}, geometry=origins.to_crs(4326).geometry.representative_point().values, crs=4326)
    d = gpd.GeoDataFrame({"id": schools["sid"].values}, geometry=schools.to_crs(4326).geometry.values, crs=4326)
    ttm = r5py.TravelTimeMatrix(
        net, origins=o, destinations=d, departure=departure,
        departure_time_window=cfg.departure_window,
        transport_modes=[r5py.TransportMode.TRANSIT, r5py.TransportMode.WALK],
        max_time=pd.Timedelta(minutes=cfg.a["max_travel_min"]),
    )
    return pd.DataFrame(ttm)[["from_id", "to_id", "travel_time"]]


def aggregate_matrix_to_blockgroup(matrix: pd.DataFrame, geoids: pd.Series,
                                   thresholds: list[int], max_min: float) -> pd.DataFrame:
    """Collapse origin→school matrix to one row per block group:
       min_tt (NaN if nothing reachable within cap), schools_within_{t}, n_reachable,
       capped (True = nothing reachable within max_min; min_tt then filled with max_min)."""
    g = matrix.groupby("from_id")["travel_time"]
    out = pd.DataFrame({"min_tt": g.min(), "n_reachable": g.apply(lambda s: int(s.notna().sum()))})
    for t in thresholds:
        out[f"schools_within_{t}"] = matrix.assign(ok=matrix.travel_time <= t).groupby("from_id")["ok"].sum()
    out = out.reindex(geoids.values)
    out.index.name = "GEOID"
    out["n_reachable"] = out["n_reachable"].fillna(0).astype(int)
    for t in thresholds:
        out[f"schools_within_{t}"] = out[f"schools_within_{t}"].fillna(0).astype(int)
    out["capped"] = out["min_tt"].isna()
    out["min_tt"] = out["min_tt"].fillna(max_min)
    return out.reset_index()
