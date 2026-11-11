"""Static interactive map (folium) for GitHub Pages: block-group change in access + schools."""
from __future__ import annotations

from pathlib import Path

import folium
import geopandas as gpd


def build_map(bg: gpd.GeoDataFrame, orig_schools: gpd.GeoDataFrame, closed_ids: list[str],
              value: str, path: Path) -> None:
    bg = bg.to_crs(4326)
    m = folium.Map(location=[39.99, -75.13], zoom_start=11, tiles="cartodbpositron")
    cols = [c for c in ["GEOID", value, "baseline_min_tt", "pct_black", "pct_hispanic", "pct_asian", "pct_white"] if c in bg]
    folium.Choropleth(geo_data=bg[cols + ["geometry"]].to_json(), data=bg[["GEOID", value]].dropna(),
                      columns=["GEOID", value], key_on="feature.properties.GEOID",
                      fill_color="RdBu", fill_opacity=0.7, line_opacity=0.2,
                      legend_name=value).add_to(m)
    folium.GeoJson(bg[cols + ["geometry"]].to_json(), style_function=lambda _: {"fillOpacity": 0, "weight": 0},
                   tooltip=folium.GeoJsonTooltip(fields=cols[:5])).add_to(m)
    for _, r in orig_schools.to_crs(4326).iterrows():
        closed = r["sid"] in closed_ids
        folium.CircleMarker([r.geometry.y, r.geometry.x], radius=6 if closed else 3,
                            color="red" if closed else "#333", fill=True,
                            tooltip=("CLOSED: " if closed else "") + str(r["sid"])).add_to(m)
    path.parent.mkdir(parents=True, exist_ok=True)
    m.save(str(path))
