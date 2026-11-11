# Data sources, vintages and provenance

This document records the inputs used by the school accessibility workflow and the metadata available in the supplied output run. Input retrieval dates and some source-layer identifiers are not present in the output archive; those gaps are identified rather than inferred.

## Input inventory

| Input | Source | Vintage / period | Obtained by | In Git? |
|---|---|---|---|---|
| Demographics and household/transit characteristics (B03002, B19058, B25044, B01001, B08301) | US Census Bureau, ACS 5-year estimates, block-group geography, Philadelphia County (FIPS 42101) | `acs.year` in config; README/config specify 2022 | `sdp-access data` using Census API (`CENSUS_API_KEY`) | No; cached under `data/raw/` |
| Block-group geometry | Census TIGERweb `tigerWMS_ACS{year}`, layer 8 | Matches configured ACS year | `sdp-access data` | No |
| Street network | Geofabrik Pennsylvania OpenStreetMap PBF | Download date and checksum belong in `data/raw/manifest.json`; not included in `outputs.zip` | `scripts/download_data.py` | No |
| Transit schedule | SEPTA combined GTFS (bus and rail; `google_bus.zip`, `google_rail.zip`) | Feed service range in supplied run: 2026-11-01 to 2027-02-20; departure 2026-12-15 08:00 | `scripts/download_data.py` | No |
| Original high-school points and catchments | School District of Philadelphia / Open Data Philly public ArcGIS Online layers | Retrieval date not recorded in supplied outputs | `sdp-access fetch` / manual source-layer workflow | No; source files are relatively large and licensing/source terms should be checked |
| FMP high-school points and catchments | Derived from the SDP Facilities Master Plan; edited/digitized by Amir McCloud | FMP document cited below; digitization based on figures/pages 58–74 | Manual digitization and editing of original layers | Optional if small and redistribution is permitted |

## Required files in `data/inputs/high/` (`sdp-access fetch` downloads them from the public AGOL items listed in `config.yaml`)

- `Original_school.shp` — original high-school points
- `School.shp` — FMP high-school points, with Penn Treaty removed
- `SchoolDist_Catchments_HS_Original.shp` — original high-school catchments
- `SchoolDist_Catchments_HS_Change.shp` — FMP/change catchments

A stable school identifier field (`school_id`) and catchment key (`SCH_ID`) are expected. If `school_id` is absent, the pipeline falls back to rounded-coordinate keys and logs a warning.

## FMP scenario provenance
**Document:** *Accelerating Opportunity: The School District of Philadelphia Facilities Master Plan*, version 1.2.0, dated 2026-11-11. [Source document](https://drive.google.com/file/d/1qTRGHqLl18R9gvpHPCNfMIQYnpdP8tKC/view).

**Scenario represented:** Penn Treaty is removed from the high-school point layer. The FMP catchment boundaries were derived by digitizing figures/pages 58–74 of the plan and editing the original catchment layer. The digitization/editing was performed by Amir McCloud.

Anyone reproducing or reusing this scenario should retain this provenance statement and independently inspect the digitized boundaries against the source plan. The scenario is a manually constructed representation, not an official district GIS release unless separately confirmed by the district.

## Supplied run metadata

The `outputs/run_metadata.json` file records:

| Field | Value |
|---|---|
| Departure date/time | 2026-12-15 08:00 local |
| Departure window | 60 minutes |
| GTFS service start | 2026-11-01 |
| GTFS service end | 2027-02-20 |
| GTFS files | `google_bus.zip`, `google_rail.zip` |

The date is a Tuesday. Confirm that this GTFS feed represents school-year service before describing the result as a typical school-day commute. The output archive does not include the GTFS source files or the download manifest, so its SHA-256 hashes cannot be independently reported from the supplied materials.

## Derived outputs supplied

`outputs.zip` includes:

- `high_access_original.csv` and `high_access_fmp.csv`: block-group travel-time/access measures for the two scenarios
- `high_schools_original.gpkg` and `high_schools_fmp.gpkg`: school point layers
- `high_isochrones_original.gpkg` and `high_isochrones_fmp.gpkg`: walking isochrones
- `high_catchment_coverage_original.csv` and `high_catchment_coverage_fmp.csv`: catchment coverage summaries
- `high_regression_dataset.gpkg`: joined block-group analysis dataset
- `high_equity_tables.xlsx`: model coefficients, diagnostics, VIF, sensitivity results, and race/ethnicity-quartile summaries
- `high_results.md`: generated headline results
- `run_metadata.json`: run-specific GTFS/departure metadata

## Known data caveats

- ACS block-group estimates carry margins of error; MOEs are not propagated into the regression.
- B17001 poverty and B14001 enrollment are suppressed at block-group level in this workflow. SNAP receipt (B19058) is used as a poverty proxy, and the B01001 age 5–17 share is used as an age-related demographic measure.
- Census sentinel value `-666666666` is converted to missing (`NaN`) before derivation.
- The departure date is selected from the GTFS feed's service range. Confirm that the feed represents school-year service.
- The model uses block-group centroids and does not represent within-block-group variation.
- The FMP school/catchment scenario is manually digitized; boundary placement and interpretation introduce potential spatial error.
- Catchment coverage is a separate descriptive measure. The travel-time model estimates access to any high school and does not enforce school assignment by catchment.
- The regression's racial/ethnic variables are not mutually exclusive or exhaustive: Hispanic origin can overlap race categories, and White share is the omitted composition term. Interpret coefficients as conditional associations under this model specification, not simple comparisons between mutually exclusive groups.

## Licences and attribution

- **OpenStreetMap:** © OpenStreetMap contributors, Open Database License (ODbL). Attribute OSM on published maps and comply with ODbL terms.
- **SEPTA GTFS:** SEPTA developer terms apply. Check current terms before redistributing the feed; the feed is not included in the supplied output archive.
- **US Census Bureau ACS/TIGER:** Public-domain federal data.
- **School District of Philadelphia / Open Data Philly:** Follow the terms attached to the source ArcGIS Online items and district data.
- **Derived FMP scenario layers:** Credit the source plan and Amir McCloud's manual digitization/editing. Confirm redistribution rights before publishing the underlying source geometries.

For a reproducible public release, add the exact AGOL item URLs/IDs, retrieval dates, OSM PBF download date/hash, GTFS download date/hash, and the applicable SDP layer terms to this file when those records are available.