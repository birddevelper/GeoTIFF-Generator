from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from osgeo import gdal, osr
from scipy.spatial import cKDTree

from core import MoistureReading


def meters_per_degree(latitude: float) -> tuple[float, float]:
    latitude_radians = math.radians(latitude)
    meters_per_degree_latitude = (
        111132.92
        - 559.82 * math.cos(2 * latitude_radians)
        + 1.175 * math.cos(4 * latitude_radians)
        - 0.0023 * math.cos(6 * latitude_radians)
    )
    meters_per_degree_longitude = (
        111412.84 * math.cos(latitude_radians)
        - 93.5 * math.cos(3 * latitude_radians)
        + 0.118 * math.cos(5 * latitude_radians)
    )
    return meters_per_degree_latitude, meters_per_degree_longitude


def to_metric_xy(
    longitudes: np.ndarray,
    latitudes: np.ndarray,
    reference_latitude: float,
) -> tuple[np.ndarray, np.ndarray]:
    meters_lat, meters_lon = meters_per_degree(reference_latitude)
    x_coords = np.asarray(longitudes, dtype=np.float64) * meters_lon
    y_coords = np.asarray(latitudes, dtype=np.float64) * meters_lat
    return x_coords, y_coords


def degree_steps_for_resolution(resolution_m: float, reference_latitude: float) -> tuple[float, float]:
    meters_lat, meters_lon = meters_per_degree(reference_latitude)
    lon_step = resolution_m / meters_lon
    lat_step = resolution_m / meters_lat
    return lon_step, lat_step


@dataclass(frozen=True)
class GridSpec:
    width: int
    height: int
    lon_step: float
    lat_step: float
    geotransform: tuple[float, float, float, float, float, float]
    lon_grid: np.ndarray
    lat_grid: np.ndarray
    reference_latitude: float


def build_grid(
    bounds: tuple[float, float, float, float],
    resolution_m: float,
    reference_latitude: float,
) -> GridSpec:
    min_lon, min_lat, max_lon, max_lat = bounds
    lon_step, lat_step = degree_steps_for_resolution(resolution_m, reference_latitude)

    width = max(1, int(math.ceil((max_lon - min_lon) / lon_step)))
    height = max(1, int(math.ceil((max_lat - min_lat) / lat_step)))

    lon_centers = min_lon + (np.arange(width) + 0.5) * lon_step
    lat_centers = max_lat - (np.arange(height) + 0.5) * lat_step
    lon_grid, lat_grid = np.meshgrid(lon_centers, lat_centers)
    geotransform = (min_lon, lon_step, 0.0, max_lat, 0.0, -lat_step)

    return GridSpec(
        width=width,
        height=height,
        lon_step=lon_step,
        lat_step=lat_step,
        geotransform=geotransform,
        lon_grid=lon_grid,
        lat_grid=lat_grid,
        reference_latitude=reference_latitude,
    )


def interpolate_moisture(
    readings: list[MoistureReading],
    grid: GridSpec,
    *,
    neighbors: int = 12,
    power: float = 2.0,
    smoothing: float = 1e-9,
) -> np.ndarray:
    longitudes = np.array([reading.longitude for reading in readings], dtype=np.float64)
    latitudes = np.array([reading.latitude for reading in readings], dtype=np.float64)
    moisture = np.array([reading.moisture for reading in readings], dtype=np.float64)

    point_x, point_y = to_metric_xy(longitudes, latitudes, grid.reference_latitude)
    grid_x, grid_y = to_metric_xy(grid.lon_grid.ravel(), grid.lat_grid.ravel(), grid.reference_latitude)

    query_points = np.column_stack([grid_x, grid_y])
    sample_points = np.column_stack([point_x, point_y])
    tree = cKDTree(sample_points)

    k = min(max(1, neighbors), len(readings))
    distances, indices = tree.query(query_points, k=k)
    distances = np.asarray(distances, dtype=np.float64)
    indices = np.asarray(indices)

    if k == 1:
        surface = moisture[indices]
        return surface.reshape(grid.lon_grid.shape).astype(np.float32)

    exact_matches = distances <= smoothing
    weights = 1.0 / np.power(distances + smoothing, power)
    weighted_moisture = moisture[indices] * weights
    weighted_sum = weighted_moisture.sum(axis=1)
    weight_total = weights.sum(axis=1)
    surface = np.divide(
        weighted_sum,
        weight_total,
        out=np.zeros_like(weighted_sum),
        where=weight_total > 0,
    )

    if np.any(exact_matches):
        exact_rows = np.where(np.any(exact_matches, axis=1))[0]
        exact_cols = np.argmax(exact_matches[exact_rows], axis=1)
        surface[exact_rows] = moisture[indices[exact_rows, exact_cols]]

    return surface.reshape(grid.lon_grid.shape).astype(np.float32)


def clip_to_boundary(grid_values: np.ndarray, grid: GridSpec, boundary_polygon) -> np.ndarray:
    from shapely import contains_xy

    mask = contains_xy(boundary_polygon, grid.lon_grid, grid.lat_grid)
    clipped = np.array(grid_values, copy=True)
    clipped[~mask] = np.nan
    return clipped


def limit_by_distance(
    readings: list[MoistureReading],
    grid_values: np.ndarray,
    grid: GridSpec,
    max_distance_m: float,
) -> np.ndarray:
    point_lons = np.array([reading.longitude for reading in readings], dtype=np.float64)
    point_lats = np.array([reading.latitude for reading in readings], dtype=np.float64)
    point_x, point_y = to_metric_xy(point_lons, point_lats, grid.reference_latitude)

    grid_x, grid_y = to_metric_xy(grid.lon_grid.ravel(), grid.lat_grid.ravel(), grid.reference_latitude)
    tree = cKDTree(np.column_stack([point_x, point_y]))
    distances, _ = tree.query(np.column_stack([grid_x, grid_y]))

    limited = np.array(grid_values, copy=True).ravel()
    limited[distances > max_distance_m] = np.nan
    return limited.reshape(grid_values.shape)


def write_single_band_geotiff(
    output_path: Path,
    grid_values: np.ndarray,
    grid: GridSpec,
    nodata_value: int,
) -> Path:
    if not 101 <= nodata_value <= 255:
        raise ValueError("UInt8 GeoTIFF NoData value must be between 101 and 255.")

    output_path.parent.mkdir(parents=True, exist_ok=True)

    driver = gdal.GetDriverByName("GTiff")
    dataset = driver.Create(
        str(output_path),
        grid.width,
        grid.height,
        1,
        gdal.GDT_Byte,
        options=["COMPRESS=LZW"],
    )
    if dataset is None:
        raise RuntimeError(f"Could not create GeoTIFF at {output_path}")

    dataset.SetGeoTransform(grid.geotransform)
    spatial_reference = osr.SpatialReference()
    spatial_reference.ImportFromEPSG(4326)
    dataset.SetProjection(spatial_reference.ExportToWkt())

    band = dataset.GetRasterBand(1)
    band.SetNoDataValue(nodata_value)

    percent_values = np.where(
        np.isfinite(grid_values),
        np.rint(np.clip(grid_values * 100.0, 0.0, 100.0)),
        nodata_value,
    ).astype(np.uint8)
    band.WriteRaster(
        0,
        0,
        grid.width,
        grid.height,
        percent_values.tobytes(order="C"),
        buf_xsize=grid.width,
        buf_ysize=grid.height,
        buf_type=gdal.GDT_Byte,
    )
    band.FlushCache()

    dataset.FlushCache()
    dataset = None
    return output_path
