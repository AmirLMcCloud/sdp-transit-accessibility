#!/usr/bin/env python
"""Download large public inputs into data/raw and write a manifest (URL, size, sha256, date).
SDP shapefiles (original/FMP points + catchments) are NOT downloadable here — see DATA.md."""
import datetime as dt, hashlib, json, sys
from pathlib import Path
import requests
from sdp_access.config import load_config

GTFS_URL = "https://github.com/septadev/GTFS/releases/latest/download/gtfs_public.zip"  # SEPTA combined feed; verify in DATA.md


def fetch(url: str, dest: Path) -> dict:
    h = hashlib.sha256()
    with requests.get(url, stream=True, timeout=600) as r:
        r.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk); h.update(chunk)
    return {"url": url, "file": dest.name, "bytes": dest.stat().st_size, "sha256": h.hexdigest(),
            "downloaded": dt.datetime.now(dt.timezone.utc).isoformat()}


def main() -> None:
    cfg = load_config(); cfg.mkdirs()
    man_path = cfg.raw_dir / "manifest.json"
    man = json.loads(man_path.read_text()) if man_path.exists() else {}
    for key, url, dest in [("osm_pbf", cfg.raw["osm"]["pbf_url"], cfg.pbf_path), ("gtfs", GTFS_URL, cfg.gtfs_zip)]:
        if dest.exists():
            print(f"skip (exists): {dest.name}"); continue
        print(f"downloading {key} …"); man[key] = fetch(url, dest)
    man_path.write_text(json.dumps(man, indent=2))
    print("manifest:", man_path, "\nNext: set CENSUS_API_KEY, then `sdp-access all`.")


if __name__ == "__main__":
    sys.exit(main())
