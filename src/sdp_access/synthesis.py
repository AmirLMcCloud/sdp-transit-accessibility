"""Outputs for write-up and portfolio: Excel tables, coefficient figure, results markdown."""
from __future__ import annotations

import re
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

from .equity import RACE_VARS


def safe_sheet(name: str) -> str:
    return re.sub(r"[\\/*?:\[\]]", "", name)[:31]


def export_tables(tables: dict[str, pd.DataFrame], path: Path) -> None:
    with pd.ExcelWriter(path, engine="openpyxl") as xw:
        for name, df in tables.items():
            df.to_excel(xw, sheet_name=safe_sheet(name), index=not isinstance(df.index, pd.RangeIndex))


def coef_plot(sens: pd.DataFrame, outcome: str, path: Path, sample: str = "study_area") -> None:
    d = sens[(sens["outcome"] == outcome) & (sens["sample"] == sample) & sens.get("term", pd.Series(dtype=object)).isin(RACE_VARS)]
    if d.empty:
        return
    fig, ax = plt.subplots(figsize=(6, 3))
    ax.errorbar(d["coef"], range(len(d)), xerr=1.96 * d["se"], fmt="o", capsize=3)
    ax.axvline(0, color="grey", lw=0.8)
    ax.set_yticks(range(len(d)), [t.replace("pct_", "% ").title() for t in d["term"]])
    ax.set_title(f"{outcome} — race coefficients (ref: White), {sample.replace('_', ' ')}")
    fig.tight_layout(); fig.savefig(path, dpi=200); plt.close(fig)


def results_markdown(n_bg: int, n_study: int, pct_capped: float, primary: str, sens: pd.DataFrame) -> str:
    d = sens[(sens["outcome"] == primary) & (sens["sample"] == "study_area") & sens.get("term", pd.Series(dtype=object)).isin(RACE_VARS)]
    lines = [f"* Block groups in model: **{n_bg}** (study area: **{n_study}**)",
             f"* Share with no school reachable inside the cap: **{pct_capped:.1%}**",
             f"* Primary outcome: `{primary}` (study-area sample)", "",
             "| Group (vs White) | coef | SE | p |", "|---|---|---|---|"]
    for _, r in d.iterrows():
        lines.append(f"| {r['term'].replace('pct_', '').title()} | {r['coef']:.3f} | {r['se']:.3f} | {r['p']:.3f} |")
    return "\n".join(lines)
