#!/usr/bin/env python
"""Publish final outputs to ArcGIS Online as hosted feature layers (ArcGIS API for Python).

Requires `pip install arcgis` and ARCGIS_USERNAME / ARCGIS_PASSWORD in the environment.
Each layer is written to GeoJSON, uploaded, and published. Re-running deletes the previous
item with the same title first, so the script is idempotent. Build the web map (swipe
original vs FMP), popups and StoryMap in the AGOL UI from these layers — see README.
NOTE: not exercised in CI (needs a live AGOL account)."""
import os
import sys
import tempfile
from pathlib import Path

import geopandas as gpd

from sdp_access.config import load_config

LAYERS = {
    "SDP {lvl} - Block groups (access change & demographics)": "{lvl}_regression_dataset.gpkg",
    "SDP {lvl} - Walk isochrones (original)": "{lvl}_isochrones_original.gpkg",
    "SDP {lvl} - Walk isochrones (FMP)": "{lvl}_isochrones_fmp.gpkg",
    "SDP {lvl} - Schools (original)": "{lvl}_schools_original.gpkg",
    "SDP {lvl} - Schools (FMP)": "{lvl}_schools_fmp.gpkg",
}
TAGS = ["SDP", "Philadelphia", "accessibility", "equity", "r5py", "OSMnx"]


def main() -> None:
    from arcgis.gis import GIS
    cfg = load_config()
    gis = GIS("https://www.arcgis.com", os.environ["ARCGIS_USERNAME"], os.environ["ARCGIS_PASSWORD"])
    me = gis.users.me.username
    for lvl in cfg.levels:
        for title_t, file_t in LAYERS.items():
            path, title = cfg.output_dir / file_t.format(lvl=lvl), title_t.format(lvl=lvl.title())
            if not path.exists():
                print("skip (missing):", path.name)
                continue
            gdf = gpd.read_file(path).to_crs(4326)
            for c in gdf.columns.drop("geometry"):
                if gdf[c].dtype == bool:
                    gdf[c] = gdf[c].astype(int)
            for old in gis.content.search(f'title:"{title}" AND owner:{me}'):
                old.delete()
            with tempfile.TemporaryDirectory() as td:
                gj = Path(td) / f"{path.stem}.geojson"
                gdf.to_file(gj, driver="GeoJSON")
                item = gis.content.add({"title": title, "type": "GeoJson", "tags": ",".join(TAGS),
                                        "snippet": "Output of sdp-transit-accessibility"}, data=str(gj))
                layer_item = item.publish()
            print("published:", layer_item.homepage)


if __name__ == "__main__":
    sys.exit(main())
