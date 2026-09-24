"""Regenerate the map geometry served to the browser.

The source is the Natural Earth 1:10m admin-0 countries GeoJSON in
``data/source/countries.geojson`` (14.6 MB). It is converted to TopoJSON with
mapshaper: borders shared by two countries are stored once, and a
topology-preserving Douglas-Peucker pass removes vertices closer than 4 km to
the line (about one to two pixels at the app's maximum zoom, 6), and
neighbouring countries never gap or overlap. Leaflet re-projects and redraws
every border point after each zoom step, so fewer points means faster zooming;
this level keeps every island while cutting the points by about 80%.

A gzip copy is written next to the TopoJSON so the server can send it
pre-compressed without spending CPU per request.

Requires Node.js (``npx`` downloads mapshaper on first use):

    python scripts/build_map_assets.py
"""

from __future__ import annotations

import argparse
import gzip
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data" / "source" / "countries.geojson"
TARGET = ROOT / "public" / "countries.topojson"
MAPSHAPER = "mapshaper@0.6.113"
SIMPLIFY_INTERVAL_METERS = 4000
QUANTIZATION = 100_000


def write_gzip_copy(path: Path) -> Path:
    """Write ``<path>.gz`` deterministically (fixed mtime, so rebuilds are byte-identical)."""
    gzip_path = path.with_name(path.name + ".gz")
    gzip_path.write_bytes(gzip.compress(path.read_bytes(), compresslevel=9, mtime=0))
    return gzip_path


def build(source: Path, target: Path) -> None:
    npx = shutil.which("npx")
    if npx is None:
        raise RuntimeError("npx (Node.js) is required to run mapshaper.")
    subprocess.run(
        [
            npx,
            "--yes",
            MAPSHAPER,
            "-i",
            str(source),
            "name=countries",
            "-simplify",
            "dp",
            f"interval={SIMPLIFY_INTERVAL_METERS}",
            "keep-shapes",
            "-o",
            str(target),
            "format=topojson",
            f"quantization={QUANTIZATION}",
            "force",
        ],
        check=True,
    )
    gzip_path = write_gzip_copy(target)
    print(
        f"{target.name}: {target.stat().st_size:,} bytes "
        f"({gzip_path.stat().st_size:,} gzipped) from {source.stat().st_size:,} bytes"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--source", default=str(SOURCE))
    parser.add_argument("--target", default=str(TARGET))
    args = parser.parse_args()
    build(Path(args.source), Path(args.target))


if __name__ == "__main__":
    main()
