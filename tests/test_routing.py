import networkx as nx
import numpy as np
import pandas as pd
import geopandas as gpd
from shapely.geometry import Point
from sdp_access import routing as R


def test_aggregate_matrix_counts_and_cap():
    m = pd.DataFrame({"from_id": ["a", "a", "b", "b"], "to_id": ["s1", "s2", "s1", "s2"],
                      "travel_time": [8.0, 40.0, np.nan, np.nan]})
    out = R.aggregate_matrix_to_blockgroup(m, pd.Series(["a", "b", "c"]), [10, 30, 50], 90).set_index("GEOID")
    assert out.loc["a", "schools_within_10"] == 1 and out.loc["a", "schools_within_50"] == 2
    assert out.loc["b", "capped"] and out.loc["b", "min_tt"] == 90
    assert out.loc["c", "n_reachable"] == 0 and out.loc["c", "capped"]   # BG absent from matrix


def _grid_graph():
    G = nx.MultiDiGraph(crs="EPSG:4326")
    n = 15
    for i in range(n):
        for j in range(n):
            G.add_node(i * n + j, x=-75.2 + i * .001, y=39.95 + j * .001)
    for i in range(n):
        for j in range(n):
            for di, dj in ((1, 0), (0, 1)):
                if i + di < n and j + dj < n:
                    for u, v in ((i * n + j, (i + di) * n + j + dj), ((i + di) * n + j + dj, i * n + j)):
                        G.add_edge(u, v, 0, length=100.0)
    return G


def test_isochrones_nested_and_rings_disjoint():
    s = gpd.GeoDataFrame({"sid": ["s"]}, geometry=[Point(-75.193, 39.957)], crs=4326)
    iso = R.build_isochrones(_grid_graph(), s, [1, 3], 1.4, 25, "EPSG:32618")
    cum = iso[iso.kind == "cumulative"].set_index("minutes").geometry.to_crs(32618)
    ring = iso[iso.kind == "ring"].set_index("minutes").geometry.to_crs(32618)
    assert cum[3].area > cum[1].area and cum[1].within(cum[3].buffer(1))
    assert ring[3].intersection(cum[1]).area < 1.0


def _cfg(tmp_path, zpath):
    from sdp_access.config import load_config
    c = load_config()
    c.raw["paths"]["raw_dir"] = str(tmp_path)
    c.raw["gtfs"]["zip"] = str(zpath)
    return c


def test_prepare_gtfs_layouts(tmp_path):
    import io, zipfile
    from sdp_access.routing import prepare_gtfs
    flat = tmp_path / "flat.zip"
    with zipfile.ZipFile(flat, "w") as z: z.writestr("stop_times.txt", "x")
    assert prepare_gtfs(_cfg(tmp_path, flat)) == [str(flat)]

    inner = io.BytesIO()
    with zipfile.ZipFile(inner, "w") as z: z.writestr("stop_times.txt", "x")
    nested = tmp_path / "nested.zip"
    with zipfile.ZipFile(nested, "w") as z:
        z.writestr("google_bus.zip", inner.getvalue()); z.writestr("google_rail.zip", inner.getvalue())
    out = prepare_gtfs(_cfg(tmp_path, nested))
    assert len(out) == 2 and all(zipfile.ZipFile(p).namelist() == ["stop_times.txt"] for p in out)

    sub = tmp_path / "sub.zip"
    with zipfile.ZipFile(sub, "w") as z: z.writestr("feed/stop_times.txt", "x"); z.writestr("feed/trips.txt", "y")
    out = prepare_gtfs(_cfg(tmp_path, sub))
    assert sorted(zipfile.ZipFile(out[0]).namelist()) == ["stop_times.txt", "trips.txt"]


def _feed(tmp_path, start, end, tue="1"):
    import zipfile
    p = tmp_path / "f.zip"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("calendar.txt", "service_id,monday,tuesday,wednesday,thursday,friday,saturday,sunday,start_date,end_date\n"
                                   f"A,1,{tue},1,1,1,0,0,{start},{end}\n")
        z.writestr("stop_times.txt", "x")
    return p


def test_auto_departure_is_tuesday_inside_feed(tmp_path):
    import datetime as dt
    from sdp_access.routing import resolve_departure
    cfg = _cfg(tmp_path, _feed(tmp_path, "20261101", "20270131"))
    cfg.raw["gtfs"]["departure"] = "auto"
    d, meta = resolve_departure(cfg, [str(tmp_path / "f.zip")])
    assert d.weekday() == 1 and dt.date(2026, 11, 1) <= d.date() <= dt.date(2027, 1, 31) and d.hour == 8


def test_explicit_departure_outside_feed_raises(tmp_path):
    import pytest
    from sdp_access.routing import resolve_departure
    cfg = _cfg(tmp_path, _feed(tmp_path, "20261101", "20270131"))
    cfg.raw["gtfs"]["departure"] = "2026-06-16T08:00:00"
    with pytest.raises(ValueError):
        resolve_departure(cfg, [str(tmp_path / "f.zip")])


def test_auto_departure_avoids_winter_break(tmp_path):
    import datetime as dt
    from sdp_access.routing import resolve_departure
    cfg = _cfg(tmp_path, _feed(tmp_path, "20261101", "20270220"))   # midpoint lands in winter break
    cfg.raw["gtfs"]["departure"] = "auto"
    cfg.raw["gtfs"]["avoid_ranges"] = ["12-20/01-05", "11-22/11-30"]
    d, _ = resolve_departure(cfg, [str(tmp_path / "f.zip")])
    assert d.weekday() == 1
    assert not (dt.date(2026, 12, 20) <= d.date() <= dt.date(2027, 1, 5))
    assert not (dt.date(2026, 11, 22) <= d.date() <= dt.date(2026, 11, 30))
