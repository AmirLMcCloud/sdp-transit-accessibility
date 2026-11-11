"""Config loading. One YAML file, resolved relative to the repo root; no hardcoded paths."""
from __future__ import annotations

import datetime as dt
import os
from dataclasses import dataclass
from pathlib import Path

import yaml

try:  # optional .env support
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None


def find_root(start: Path | None = None) -> Path:
    """Repo root = nearest parent containing config/config.yaml (or $SDP_ROOT)."""
    if os.environ.get("SDP_ROOT"):
        return Path(os.environ["SDP_ROOT"]).resolve()
    p = (start or Path.cwd()).resolve()
    for cand in [p, *p.parents]:
        if (cand / "config" / "config.yaml").exists():
            return cand
    raise FileNotFoundError("config/config.yaml not found; run from the repo or set SDP_ROOT")


@dataclass
class Config:
    root: Path
    raw: dict

    # ---- paths
    def _p(self, rel: str) -> Path:
        return (self.root / rel).resolve()

    @property
    def data_dir(self) -> Path: return self._p(self.raw["paths"]["data_dir"])
    @property
    def raw_dir(self) -> Path: return self._p(self.raw["paths"]["raw_dir"])
    @property
    def output_dir(self) -> Path: return self._p(self.raw["paths"]["output_dir"])
    @property
    def fig_dir(self) -> Path: return self._p(self.raw["paths"]["figure_dir"])
    @property
    def gtfs_zip(self) -> Path: return self._p(self.raw["gtfs"]["zip"])
    @property
    def pbf_path(self) -> Path: return self._p(self.raw["osm"]["pbf_path"])
    @property
    def graphml(self) -> Path: return self._p(self.raw["osm"]["walk_graph"])

    # ---- parameters
    @property
    def a(self) -> dict: return self.raw["analysis"]
    @property
    def departure(self) -> dt.datetime | None:
        """Explicit departure, or None when set to "auto" (resolved from the feed at run time)."""
        d = str(self.raw["gtfs"]["departure"])
        return None if d.lower() == "auto" else dt.datetime.fromisoformat(d)
    @property
    def departure_window(self) -> dt.timedelta: return dt.timedelta(minutes=self.raw["gtfs"]["departure_window_min"])
    @property
    def levels(self) -> list[str]: return list(self.raw["levels"]["active"])
    @property
    def acs_vars(self) -> dict: return dict(self.raw["acs_vars"])
    @property
    def census_key(self) -> str:
        key = os.environ.get("CENSUS_API_KEY", "")
        if not key:
            raise RuntimeError("Set CENSUS_API_KEY (see .env.example).")
        return key

    def level(self, name: str) -> dict:
        lv = self.raw["levels"][name]
        out = {"id_field": lv.get("id_field"), "catchment_id_field": lv.get("catchment_id_field"),
               "id_name_field": lv.get("id_name_field"), "id_overrides": lv.get("id_overrides") or {}}
        for scen in ("original", "fmp"):
            out[scen] = {k: self.data_dir / name / v for k, v in lv[scen].items()}
        return out

    def validate(self) -> None:
        d, g = self.departure, self.raw["gtfs"]
        if d is not None and "feed_valid_from" in g and "feed_valid_to" in g:
            lo = dt.datetime.fromisoformat(g["feed_valid_from"])
            hi = dt.datetime.fromisoformat(g["feed_valid_to"]) + dt.timedelta(days=1)
            if not lo <= d < hi:
                raise ValueError(f"departure {d} outside GTFS feed validity {lo.date()}–{hi.date()}")
        if max(self.a["access_thresholds_min"]) > self.a["max_travel_min"]:
            raise ValueError("max_travel_min must be >= the largest access threshold, "
                             "otherwise those thresholds silently equal the cap")
        if self.a["primary_threshold_min"] not in self.a["access_thresholds_min"]:
            raise ValueError("primary_threshold_min must be one of access_thresholds_min")

    def mkdirs(self) -> None:
        for d in (self.raw_dir, self.output_dir, self.fig_dir):
            d.mkdir(parents=True, exist_ok=True)


def load_config(path: str | Path | None = None) -> Config:
    root = find_root()
    if load_dotenv:
        load_dotenv(root / ".env")
    path = Path(path) if path else root / "config" / "config.yaml"
    cfg = Config(root=root, raw=yaml.safe_load(path.read_text()))
    cfg.validate()
    return cfg
