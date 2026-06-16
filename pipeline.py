from __future__ import annotations

from pathlib import Path

from core import RasterConfig, load_boundary_geojson, read_moisture_csv
from raster import build_grid, clip_to_boundary, interpolate_moisture, limit_by_distance, write_single_band_geotiff


def default_output_dir() -> Path:
    return Path(__file__).resolve().parent / "output"


def resolve_output_path(csv_path: Path, output_target: Path | None) -> Path:
    if output_target is None:
        return default_output_dir() / f"{csv_path.stem}_moisture.tif"

    if output_target.suffix.lower() in {".tif", ".tiff"}:
        return output_target

    return output_target / f"{csv_path.stem}_moisture.tif"


def make_geotiff(
    csv_path: Path,
    boundary_geojson_path: Path,
    output_target: Path | None = None,
    config: RasterConfig | None = None,
) -> Path:
    job_config = config or RasterConfig()
    readings = read_moisture_csv(csv_path)
    if not readings:
        raise ValueError("No valid moisture readings were found in the CSV file.")

    boundary = load_boundary_geojson(boundary_geojson_path)
    reference_latitude = float(sum(reading.latitude for reading in readings) / len(readings))

    grid = build_grid(boundary.bounds, job_config.resolution_m, reference_latitude)
    interpolated = interpolate_moisture(readings, grid)
    clipped = clip_to_boundary(interpolated, grid, boundary)

    if job_config.max_distance_m is not None:
        clipped = limit_by_distance(readings, clipped, grid, job_config.max_distance_m)

    output_path = resolve_output_path(csv_path, output_target)
    return write_single_band_geotiff(output_path, clipped, grid, job_config.nodata_value)
