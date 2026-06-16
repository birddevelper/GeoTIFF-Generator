from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True)
class MoistureReading:
    moisture: float
    latitude: float
    longitude: float
    sampled_at: datetime


@dataclass(frozen=True)
class RasterConfig:
    resolution_m: float = 10.0
    max_distance_m: float | None = None
    nodata_value: int = 255


def _parse_sampled_at(value: str) -> datetime:
    return datetime.fromisoformat(value.strip().replace("Z", "+00:00"))


def read_moisture_csv(csv_path: Path) -> list[MoistureReading]:
    if not csv_path.exists():
        raise FileNotFoundError(f"CSV file does not exist: {csv_path}")

    readings: list[MoistureReading] = []
    with csv_path.open("r", encoding="utf-8", newline="") as file:
        reader = csv.DictReader(file)
        required_columns = {"moisture", "latitude", "longitude", "sampled_at"}
        missing_columns = required_columns.difference(reader.fieldnames or [])
        if missing_columns:
            raise ValueError(f"CSV file is missing required columns: {sorted(missing_columns)}")

        for row in reader:
            moisture_raw = (row.get("moisture") or "").strip()
            latitude_raw = (row.get("latitude") or "").strip()
            longitude_raw = (row.get("longitude") or "").strip()
            sampled_at_raw = (row.get("sampled_at") or "").strip()

            if not moisture_raw or not latitude_raw or not longitude_raw or not sampled_at_raw:
                continue

            readings.append(
                MoistureReading(
                    moisture=float(moisture_raw),
                    latitude=float(latitude_raw),
                    longitude=float(longitude_raw),
                    sampled_at=_parse_sampled_at(sampled_at_raw),
                )
            )

    return readings


def _extract_geojson_geometry(data: object) -> dict:
    if not isinstance(data, dict):
        raise ValueError("Invalid GeoJSON content.")

    geometry_type = data.get("type")
    if geometry_type == "FeatureCollection":
        features = data.get("features") or []
        if not features:
            raise ValueError("GeoJSON FeatureCollection does not contain any features.")
        return _extract_geojson_geometry(features[0])

    if geometry_type == "Feature":
        geometry = data.get("geometry")
        if geometry is None:
            raise ValueError("GeoJSON Feature does not contain a geometry.")
        return geometry

    return data


def load_boundary_geojson(geojson_path: Path):
    if not geojson_path.exists():
        raise FileNotFoundError(f"Boundary GeoJSON file does not exist: {geojson_path}")

    from shapely.geometry import MultiPolygon, Polygon, shape

    with geojson_path.open("r", encoding="utf-8") as file:
        data = json.load(file)

    geometry = _extract_geojson_geometry(data)
    polygon = shape(geometry)

    if polygon.is_empty:
        raise ValueError(f"Boundary GeoJSON is empty: {geojson_path}")

    if isinstance(polygon, MultiPolygon):
        polygon = max(polygon.geoms, key=lambda geom: geom.area)

    if not isinstance(polygon, Polygon):
        raise ValueError("Boundary GeoJSON must describe a Polygon or MultiPolygon.")

    return polygon
