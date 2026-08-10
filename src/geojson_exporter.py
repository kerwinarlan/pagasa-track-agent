"""Convert StormBulletin objects to GeoJSON (RFC 7946).

GeoJSON always uses [longitude, latitude] coordinate order. Our schema
stores positions as lat/lon, so the exporter swaps the order.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.schemas.bulletin import Coordinate, StormBulletin

_PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent
SAMPLE_BULLETIN_PATH: Path = _PROJECT_ROOT / "data" / "raw" / "sample_bulletin.txt"
DEFAULT_OUTPUT_PATH: Path = _PROJECT_ROOT / "data" / "output" / "storm_track.geojson"


def _point(position: Coordinate) -> dict[str, Any]:
    """Return a GeoJSON Point geometry for a coordinate."""
    return {
        "type": "Point",
        "coordinates": [position.lon, position.lat],
    }


def _current_center_feature(bulletin: StormBulletin) -> dict[str, Any]:
    """Return the GeoJSON feature for the current storm center."""
    return {
        "type": "Feature",
        "geometry": _point(bulletin.current_position),
        "properties": {
            "storm_name": bulletin.storm_name,
            "max_wind_kph": bulletin.max_sustained_winds_kmh,
            "pressure": bulletin.central_pressure_hpa,
            "issued_at": bulletin.issued_at.isoformat(),
            "signal_number": bulletin.signal_number.value,
            "typhoon_category": bulletin.typhoon_category.value,
        },
    }


def _forecast_features(bulletin: StormBulletin) -> list[dict[str, Any]]:
    """Return one GeoJSON Point feature per forecast track position."""
    features = []
    for index, forecast_point in enumerate(bulletin.forecast_track):
        features.append(
            {
                "type": "Feature",
                "geometry": _point(forecast_point.position),
                "properties": {
                    "index": index,
                    "timestamp": forecast_point.timestamp.isoformat(),
                },
            }
        )
    return features


def _track_feature(bulletin: StormBulletin) -> dict[str, Any] | None:
    """Return the LineString feature for the storm track.

    RFC 7946 requires a LineString to have two or more positions, so an
    empty forecast track yields no track feature.
    """
    coordinates = [[bulletin.current_position.lon, bulletin.current_position.lat]]
    coordinates.extend(
        [[point.position.lon, point.position.lat] for point in bulletin.forecast_track]
    )
    if len(coordinates) < 2:
        return None
    return {
        "type": "Feature",
        "geometry": {
            "type": "LineString",
            "coordinates": coordinates,
        },
        "properties": {
            "storm_name": bulletin.storm_name,
            "feature": "storm_track",
        },
    }


def bulletin_to_feature_collection(bulletin: StormBulletin) -> dict[str, Any]:
    """Convert a StormBulletin into an RFC 7946 FeatureCollection."""
    features = [_current_center_feature(bulletin)]
    features.extend(_forecast_features(bulletin))
    track_feature = _track_feature(bulletin)
    if track_feature is not None:
        features.append(track_feature)
    return {
        "type": "FeatureCollection",
        "features": features,
    }


def export_to_geojson(bulletin: StormBulletin, output_path: str) -> dict[str, Any]:
    """Convert the bulletin to GeoJSON and write it to output_path.

    Returns the FeatureCollection that was written.
    """
    collection = bulletin_to_feature_collection(bulletin)
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(collection, indent=2), encoding="utf-8")
    return collection


def main() -> None:
    """Parse the sample bulletin and export it to GeoJSON."""
    from src.extractor import parse_bulletin_text

    raw_text = SAMPLE_BULLETIN_PATH.read_text(encoding="utf-8")
    bulletin = parse_bulletin_text(raw_text)
    export_to_geojson(bulletin, str(DEFAULT_OUTPUT_PATH))
    print(f"Saved storm track to {DEFAULT_OUTPUT_PATH}")


if __name__ == "__main__":
    main()
