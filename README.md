# Who Bears the Travel Burden? Transit Accessibility Under the Philadelphia School Facilities Master Plan

Walk + SEPTA transit accessibility analysis of the School District of Philadelphia (SDP) Facilities Master Plan (FMP), scoped to **high schools** (one closure: Penn Treaty). This portfolio project examines how that change affects the number of high schools reachable by public transit and walking from Philadelphia census block groups, and whether the modeled change varies with neighborhood racial/ethnic composition after accounting for poverty, car-free households, transit use, baseline access, baseline travel time, and population.

The analysis is descriptive and observational. It does not estimate the travel experience of individual students or establish a causal effect of the Facilities Master Plan.

## Key findings

The supplied run contains 1,271 block groups in the full model and 296 in the Penn Treaty study-area model. The study-area model is the primary reported model because a single closure is geographically concentrated and its effect is diluted when averaged across all Philadelphia block groups.

The primary outcome is `delta_access_30`, defined as the FMP scenario minus the original scenario in the number of high schools reachable within 30 minutes. A negative value indicates fewer reachable schools under the FMP scenario.


| Study-area model term (vs. omitted White share) | Coefficient | HC3 SE | p-value | 95% CI |
|---|---:|---:|---:|---:|
| Black share | 0.350 | 0.117 | 0.003 | [0.121, 0.580] |
| Hispanic share | 0.377 | 0.136 | 0.006 | [0.110, 0.644] |
| Asian share | 0.659 | 0.227 | 0.004 | [0.213, 1.104] |


All three race/ethnicity composition terms are positive and statistically significant in the study-area model. Because the outcome is FMP minus original, these positive coefficients indicate a more positive modeled change in the number of schools reachable within 30 minutes as the corresponding neighborhood share increases, conditional on the model covariates. They **do not show a larger loss of 30-minute access** for these groups relative to the omitted White share. The estimates should therefore not be presented as evidence that Black, Hispanic, or Asian neighborhoods bear a greater 30-minute access burden in this model.

The full-city model is less pronounced:

| Full-city model term | Coefficient | HC3 SE | p-value |
|---|---:|---:|---:|
| Black share | 0.169 | 0.022 | <0.001 |
| Hispanic share | 0.043 | 0.039 | 0.273 |
| Asian share | 0.231 | 0.053 | <0.001 |

The study-area model has \(R^2=0.511\) (adjusted \(R^2=0.495\)); the full-city model has \(R^2=0.402\) (adjusted \(R^2=0.398\)). The Breusch–Pagan test is significant in both samples (study area \(p<0.001\); full city \(p<0.001\)), supporting the use of heteroskedasticity-robust HC3 standard errors. VIF values in the study-area model range from 1.06 to 4.14.

Other run-level facts:

- 0.4% of block groups in the model have no school reachable within the travel-time cap.
- The original and FMP access CSVs each contain 1,338 block-group records; the regression dataset/model contains 1,271 observations after the analysis joins and exclusions.
- The average number of schools reachable within 30 minutes is 0.945 in the original scenario and 0.882 in the FMP scenario across the 1,338 access records. This is a descriptive difference of about -0.064 schools per block group, not a population-weighted estimate.

### Sensitivity results

The workbook `outputs/high_equity_tables.xlsx` includes models for `delta_min_tt` and access-count changes at 10, 30, 50, and 70 minutes, plus full-city, study-area, and uncapped study-area samples. The 30-minute study-area race/ethnicity coefficients are positive and significant in the uncapped sample as well (Black 0.350, p=0.003; Hispanic 0.377, p=0.006; Asian 0.659, p=0.006). The `delta_min_tt` study-area coefficients are negative and significant (Black -1.237, p=0.017; Hispanic -1.536, p=0.016; Asian -1.915, p=0.006), which, given `delta_min_tt = FMP - original`, indicates a more negative change in nearest-school travel time associated with those shares. Threshold-specific findings vary; do not generalize the 30-minute result to every threshold.

The quartile worksheets provide descriptive comparisons by block-group race/ethnicity-share quartile. They are not substitutes for the adjusted regression models.

## Method at a glance

```
ACS 5-yr (Census API) ─┐
TIGERweb block groups ─┼─► data ─► block groups + equity vars
                       │
SDP layers (orig/FMP) ─┼─► route ─► OSMnx walk isochrones (5/10/15 min) + catchment coverage
OSM PBF + SEPTA GTFS ──┘            r5py walk+transit travel-time matrix (BG centroid → school)
                                   └► per-BG min travel time, schools reachable ≤ 10/30/50/70 min
                                     (original vs FMP)
                                         │
                               equity ◄──┘ Δ = FMP − original; OLS (HC3 SEs), diagnostics,
                                           sensitivity table, race-quartile tables
                                         ▼
                      map ─► folium HTML (GitHub Pages)     publish_arcgis.py ─► ArcGIS Online
```

**Primary outcome:** `delta_access_30` — change in the number of high schools reachable within 30 min (negative = worse). `delta_min_tt` (change in minutes to nearest school) is reported as a labelled sensitivity, because it does not depend on the access threshold. **Reference group:** White.

**Outcome Caveat:** Coefficients are not necessarily comparisons against White residents alone. Due to the omission of other racial groups, and the Hispanic origin category overlapping with racial categories in a general popuilation classication.

## Reproduce

```bash
conda env create -f environment.yml
conda activate sdp-access
cp .env.example .env            # add CENSUS_API_KEY; set JAVA_HOME if needed
python scripts/download_data.py # OSM PBF + SEPTA GTFS and download manifest
sdp-access fetch                # SDP layers from public ArcGIS Online items
sdp-access all                  # or: fetch | data | route | equity | map
pytest                          # synthetic-data tests; no downloads needed
```

Parameters such as thresholds, walking speed, departure time, study-area buffer, ACS year, and layer names are configured in `config/config.yaml`. The pipeline uses JDK 21 for r5py.

The outputs supplied with this README were generated with a departure time of **Tuesday, December 15, 2026 at 08:00**, using a 60-minute departure window. The recorded SEPTA GTFS service range is **November 1, 2026 through February 20, 2027**. Confirm that the downloaded feed represents school-year service before interpreting the results as typical school-day conditions.

## Outputs

The supplied `outputs.zip` contains:

| File | Contents |
|---|---|
| `high_results.md` | Auto-generated headline model results |
| `high_equity_tables.xlsx` | Coefficients, model diagnostics, VIF, sensitivity models, and race/ethnicity-quartile tables |
| `high_regression_dataset.gpkg` | Block groups with demographics, baseline measures, deltas, and flags |
| `high_access_original.csv`, `high_access_fmp.csv` | Block-group travel-time and reachable-school counts by scenario |
| `high_isochrones_original.gpkg`, `high_isochrones_fmp.gpkg` | Walking isochrones by scenario |
| `high_catchment_coverage_original.csv`, `high_catchment_coverage_fmp.csv` | Catchment area and block-group-centroid coverage summaries |
| `high_schools_original.gpkg`, `high_schools_fmp.gpkg` | School point layers by scenario |
| `run_metadata.json` | Departure time and GTFS service dates |

The supplied archive does **not** contain `docs/high_map.html` or `docs/hero_map.png`; generate/export those with the map step before enabling the README map image or publishing the interactive map.

## Design decisions and interpretation

- **Treatment dilution:** One closure affects a small part of roughly 1,300 block groups. Models are run for all block groups and for a study area consisting of block groups within `study_area_buffer_m` of the closed school's catchment. The study-area model is the primary focused estimate.
- **Unreachable block groups:** These are flagged (`any_capped`). The travel-time cap is used only for the delta calculation, and an uncapped robustness sample is also reported. `max_travel_min` must be at least as large as the largest access threshold.
- **Poverty proxy:** SNAP receipt (ACS table B19058) is used because B17001 poverty estimates are suppressed at block-group level in this workflow.
- **Ambiguous spatial matches:** Centroids on catchment boundaries are logged rather than silently dropped.
- **Catchment versus access:** Catchment coverage is reported separately. The travel-time model measures access to any high school and does not constrain a block group to its assigned catchment school.
- **Model interpretation:** Coefficients describe conditional associations between neighborhood composition and the FMP-minus-original outcome. They are not causal effects, student-level estimates, or proof of individual racial discrimination.

## Limitations

- ACS block-group estimates have margins of error; those MOEs are not propagated into the regression.
- The racial/ethnic composition variables do not form a complete, mutually exclusive population classification. Hispanic origin overlaps racial categories, and omitted groups complicate the interpretation of the omitted White-share term.
- Transit times use one representative Tuesday 08:00 departure (60-minute window), not a full-day distribution. The GTFS feed's season matters; a feed that does not reflect school-year service may misstate typical school commute times.
- Travel time is measured from block-group centroids to school points; within-block-group variation and actual student origins are not modeled.
- FMP scenario layers were digitized/edited manually from the Facilities Master Plan; results depend on that interpretation.
- One closure provides limited statistical power. Treat coefficients as descriptive, not causal.
- The travel-time model measures access to any high school, not enrollment eligibility, assigned-school access, capacity, or actual student choice.
- The Breusch–Pagan diagnostics indicate heteroskedasticity; HC3 standard errors are used, but other model-specification limitations remain.

## Publishing

- **GitHub:** Commit code, configuration, tests, notebook, derived outputs, and `docs/`. Enable GitHub Pages from `/docs` after generating the interactive map.
- **ArcGIS Online:** Install `arcgis`, set `ARCGIS_USERNAME` and `ARCGIS_PASSWORD`, run `python scripts/publish_arcgis.py`, then create a web map comparing original and FMP isochrones and mapping block-group `delta_access_30`. The publishing script requires a live AGOL account and is not validated by the supplied output archive.

## AI Use Disclosure
Generative AI (Claude) was used to assist with rewriting and adapting portions of the project's existing Python scripts to improve compatibility with GitHub hosting and deployment. The original analytical workflow, research objectives, data processing approach, and interpretation of results were developed by the author. AI assistance was limited to code adaptation and compatibility-related adjustments; it was not used to generate the underlying research findings or statistical results. All AI-assisted changes were reviewed by the author.

## License / attribution

Code: MIT (add a `LICENSE`). Data: OpenStreetMap © contributors (ODbL), SEPTA GTFS (SEPTA developer terms), US Census Bureau ACS/TIGER (public domain), SDP layers per district terms. See `DATA.md`.
