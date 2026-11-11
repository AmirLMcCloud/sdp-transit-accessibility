"""Single entry point:  sdp-access {fetch|data|route|equity|map|all} [--config path]"""
from __future__ import annotations

import argparse
import json
import logging

import geopandas as gpd
import pandas as pd

from . import data as D, equity as E, routing as R, synthesis as S, webmap
from .config import Config, load_config

log = logging.getLogger("sdp_access")


def _bg_path(cfg: Config): return cfg.raw_dir / "philly_blockgroups.gpkg"


def stage_data(cfg: Config) -> None:
    D.build_blockgroups(cfg)


def stage_route(cfg: Config) -> None:
    missing = D.preflight(cfg)
    if missing:
        raise SystemExit("Missing inputs:\n  " + "\n  ".join(missing) + "\nSee DATA.md / scripts/download_data.py")
    bg = gpd.read_file(_bg_path(cfg))
    G = R.load_walk_graph(cfg)
    a = cfg.a
    feeds = R.prepare_gtfs(cfg)
    departure, meta = R.resolve_departure(cfg, feeds)
    (cfg.output_dir / "run_metadata.json").write_text(json.dumps(meta, indent=2))
    for lvl in cfg.levels:
        L = cfg.level(lvl)
        sch = {s: D.stable_ids(gpd.read_file(L[s]["schools"]), L["id_field"], L["id_overrides"], L["id_name_field"]) for s in ("original", "fmp")}
        cat = {s: D.load_catchments(L[s]["catchments"], L["catchment_id_field"]) for s in ("original", "fmp")}
        for s in ("original", "fmp"):
            iso = R.build_isochrones(G, sch[s], a["iso_minutes"], a["walk_speed_ms"], a["edge_buffer_m"], a["projected_crs"])
            iso.to_file(cfg.output_dir / f"{lvl}_isochrones_{s}.gpkg", driver="GPKG")
            cov = pd.concat([R.catchment_coverage(iso, cat[s], "sid", bg, m, a["projected_crs"])
                             for m in a["iso_minutes"]])
            cov.to_csv(cfg.output_dir / f"{lvl}_catchment_coverage_{s}.csv", index=False)
            mat = R.compute_travel_matrix(cfg, bg, sch[s], feeds, departure)
            agg = R.aggregate_matrix_to_blockgroup(mat, bg["GEOID"], a["access_thresholds_min"], a["max_travel_min"])
            agg.to_csv(cfg.output_dir / f"{lvl}_access_{s}.csv", index=False)
            sch[s].to_file(cfg.output_dir / f"{lvl}_schools_{s}.gpkg", driver="GPKG")
        log.info("closed schools (%s): %s", lvl, D.closed_school_ids(sch["original"], sch["fmp"]))


def stage_equity(cfg: Config) -> None:
    a = cfg.a
    th = a["access_thresholds_min"]
    primary = f"delta_access_{a['primary_threshold_min']}"
    bg = gpd.read_file(_bg_path(cfg))
    for lvl in cfg.levels:
        L = cfg.level(lvl)
        orig = pd.read_csv(cfg.output_dir / f"{lvl}_access_original.csv", dtype={"GEOID": str})
        fmp = pd.read_csv(cfg.output_dir / f"{lvl}_access_fmp.csv", dtype={"GEOID": str})
        so = gpd.read_file(cfg.output_dir / f"{lvl}_schools_original.gpkg")
        sf = gpd.read_file(cfg.output_dir / f"{lvl}_schools_fmp.gpkg")
        closed = D.closed_school_ids(so, sf)
        df = E.build_delta_frame(bg, orig, fmp, th)
        df = E.flag_study_area(df, D.load_catchments(L["original"]["catchments"], L["catchment_id_field"]), "sid",
                               closed, a["study_area_buffer_m"], a["projected_crs"])
        reg = E.prepare_regression_frame(df, a["min_pop"])
        tables = {}
        # primary model: change in schools within threshold, study area; delta_min_tt as labelled sensitivity
        for tag, sub in {"all": reg, "study": reg[reg["study_area"]]}.items():
            if sub[primary].nunique() > 1:
                m = E.run_ols(sub, E.make_formula(primary, f"baseline_access_{a['primary_threshold_min']}"))
                tables[f"coef_{tag}"] = E.coef_table(m)
                tables[f"diag_{tag}"] = pd.Series({k: v for k, v in E.diagnostics(m, sub).items() if k != "vif"}).to_frame("value")
                tables[f"vif_{tag}"] = pd.Series(E.diagnostics(m, sub)["vif"]).to_frame("vif")
        sens = E.sensitivity_table(reg, th)
        tables["sensitivity"] = sens
        for v in E.RACE_VARS + ["pct_white"]:
            tables[f"quartile_{v}"] = E.race_quartile_table(reg[reg["study_area"]] if reg["study_area"].any() else reg, v, primary)
        S.export_tables(tables, cfg.output_dir / f"{lvl}_equity_tables.xlsx")
        S.coef_plot(sens, primary, cfg.fig_dir / f"{lvl}_coef_{primary}.png")
        md = S.results_markdown(len(reg), int(reg["study_area"].sum()), float(df["any_capped"].mean()), primary, sens)
        (cfg.output_dir / f"{lvl}_results.md").write_text(md)
        keep = df.drop(columns=[c for c in df.columns if c in ("NAME",)], errors="ignore")
        gpd.GeoDataFrame(keep).to_file(cfg.output_dir / f"{lvl}_regression_dataset.gpkg", driver="GPKG")
        log.info("equity done for %s (n=%d)", lvl, len(reg))


def stage_map(cfg: Config) -> None:
    primary = f"delta_access_{cfg.a['primary_threshold_min']}"
    for lvl in cfg.levels:
        df = gpd.read_file(cfg.output_dir / f"{lvl}_regression_dataset.gpkg")
        so = gpd.read_file(cfg.output_dir / f"{lvl}_schools_original.gpkg")
        sf = gpd.read_file(cfg.output_dir / f"{lvl}_schools_fmp.gpkg")
        webmap.build_map(df, so, D.closed_school_ids(so, sf), primary, cfg.root / "docs" / f"{lvl}_map.html")


def stage_fetch(cfg: Config) -> None:
    D.fetch_hosted_inputs(cfg)


STAGES = {"fetch": stage_fetch, "data": stage_data, "route": stage_route, "equity": stage_equity, "map": stage_map}


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="sdp-access")
    ap.add_argument("stage", choices=[*STAGES, "all"])
    ap.add_argument("--config", default=None)
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    cfg = load_config(args.config)
    cfg.mkdirs()
    for name in (STAGES if args.stage == "all" else [args.stage]):
        log.info("== stage: %s", name)
        STAGES[name](cfg)


if __name__ == "__main__":
    main()
