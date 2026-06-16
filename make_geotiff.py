from __future__ import annotations

import argparse
from pathlib import Path

from core import RasterConfig


def default_output_dir() -> Path:
    return Path(__file__).resolve().parent / "output"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate a single-band GeoTIFF from a moisture CSV file."
    )
    parser.add_argument("csv_path", type=Path, help="Path to the input CSV file.")
    parser.add_argument(
        "--boundary-geojson",
        dest="boundary_geojson_path",
        type=Path,
        required=True,
        help="Path to a GeoJSON file containing the farm boundary polygon.",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=default_output_dir(),
        help="Output directory or GeoTIFF file path. Defaults to the package output folder.",
    )
    parser.add_argument(
        "--resolution-m",
        type=float,
        default=10.0,
        help="Approximate raster resolution in meters.",
    )
    parser.add_argument(
        "--max-distance-m",
        type=float,
        default=None,
        help="Optional maximum distance from a sensor point before a pixel is marked NoData.",
    )
    parser.add_argument(
        "--nodata",
        type=int,
        default=255,
        help="NoData byte value to write into the GeoTIFF. Must be 101-255.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    from pipeline import make_geotiff

    config = RasterConfig(
        resolution_m=args.resolution_m,
        max_distance_m=args.max_distance_m,
        nodata_value=args.nodata,
    )
    output_path = make_geotiff(
        args.csv_path, args.boundary_geojson_path, args.output, config
    )
    print(f"GeoTIFF written to: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
