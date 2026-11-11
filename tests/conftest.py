import numpy as np
import pandas as pd
import geopandas as gpd
import pytest
from shapely.geometry import box


@pytest.fixture
def bg_frame():
    """10x10 synthetic block-group grid with demographics (~0.01° cells)."""
    rng = np.random.default_rng(0)
    cells, rows = [], []
    for i in range(10):
        for j in range(10):
            cells.append(box(-75.2 + i * .01, 39.9 + j * .01, -75.19 + i * .01, 39.91 + j * .01))
            pb, ph, pa = rng.uniform(0, .5), rng.uniform(0, .3), rng.uniform(0, .1)
            rows.append({"GEOID": f"4210100{i:02d}{j:02d}0", "total_pop": int(rng.integers(300, 3000)),
                         "pct_black": pb, "pct_hispanic": ph, "pct_asian": pa, "pct_white": 1 - pb - ph - pa,
                         "pct_poverty": rng.uniform(0, .5), "pct_carfree": rng.uniform(0, .6),
                         "pct_transit": rng.uniform(0, .5)})
    return gpd.GeoDataFrame(rows, geometry=cells, crs=4326)


@pytest.fixture
def access_tables(bg_frame):
    rng = np.random.default_rng(1)
    th = [10, 30, 50]
    def mk(shift):
        d = pd.DataFrame({"GEOID": bg_frame.GEOID, "min_tt": rng.uniform(5, 60, len(bg_frame)) + shift,
                          "capped": False, "n_reachable": 5})
        for t in th:
            d[f"schools_within_{t}"] = rng.integers(0, 4, len(bg_frame))
        return d
    o = mk(0)
    f = o.copy()
    f["min_tt"] += rng.uniform(0, 10, len(f))
    for t in th:
        f[f"schools_within_{t}"] = (o[f"schools_within_{t}"] - rng.integers(0, 2, len(f))).clip(lower=0)
    return o, f, th
