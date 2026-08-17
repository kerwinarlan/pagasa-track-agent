"""Tests for the GeoJSON exporter."""

import json
from datetime import datetime, timezone

import pytest

from src.geojson_exporter import (
    DEFAULT_OUTPUT_PATH,
    bulletin_to_feature_collection,
    export_to_geojson,
)
from src.schemas.bulletin import (
    Coordinate,
    ForecastPoint,
    StormBulletin,
    TyphoonCategory,
    WindSignalNumber,
)


def make_bulletin(with_forecast_track: bool = True) -> StormBulletin:
    """Return a valid bulletin with an optional forecast track."""
    track = (
        [
            ForecastPoint(
                timestamp=datetime(2024, 11, 18, 5, 0, tzinfo=timezone.utc),
                position=Coordinate(lat=15.8, lon=123.6),
            ),
            ForecastPoint(
                timestamp=datetime(2024, 11, 19, 5, 0, tzinfo=timezone.utc),
                position=Coordinate(lat=16.4, lon=122.2),
            ),
        ]
        if with_forecast_track
        else []
    )
    return StormBulletin(
        bulletin_number=15,
        issued_at=datetime(2024, 11, 17, 5, 0, tzinfo=timezone.utc),
        storm_name="SAMPLE",
        signal_number=WindSignalNumber.SIGNAL_4,
        typhoon_category=TyphoonCategory.SUPER_TYPHOON,
        current_position=Coordinate(lat=15.2, lon=124.8),
        movement_speed_kmh=20,
        movement_direction_deg=292.5,
        central_pressure_hpa=915,
        max_sustained_winds_kmh=195,
        forecast_track=track,
    )


class TestBulletinToFeatureCollection:
    def test_returns_feature_collection(self):
        collection = bulletin_to_feature_collection(make_bulletin())
        assert collection["type"] == "FeatureCollection"
        assert isinstance(collection["features"], list)

    def test_current_center_feature(self):
        collection = bulletin_to_feature_collection(make_bulletin())
        center = collection["features"][0]

        assert center["type"] == "Feature"
        assert center["geometry"]["type"] == "Point"
        # RFC 7946 requires [longitude, latitude] order.
        assert center["geometry"]["coordinates"] == [124.8, 15.2]
        assert center["properties"]["storm_name"] == "SAMPLE"
        assert center["properties"]["max_wind_kph"] == 195
        assert center["properties"]["pressure"] == 915

    def test_forecast_point_features(self):
        collection = bulletin_to_feature_collection(make_bulletin())
        forecast_features = collection["features"][1:3]

        assert len(forecast_features) == 2
        assert forecast_features[0]["geometry"]["coordinates"] == [123.6, 15.8]
        assert forecast_features[1]["geometry"]["coordinates"] == [122.2, 16.4]
        assert forecast_features[0]["properties"]["timestamp"] == "2024-11-18T05:00:00+00:00"

    def test_track_linestring_connects_all_points(self):
        collection = bulletin_to_feature_collection(make_bulletin())
        track = collection["features"][3]

        assert track["geometry"]["type"] == "LineString"
        assert track["geometry"]["coordinates"] == [
            [124.8, 15.2],
            [123.6, 15.8],
            [122.2, 16.4],
        ]
        assert track["properties"]["feature"] == "storm_track"

    def test_empty_track_has_no_linestring(self):
        """RFC 7946 forbids 1-position LineStrings."""
        collection = bulletin_to_feature_collection(make_bulletin(with_forecast_track=False))

        assert len(collection["features"]) == 1
        assert collection["features"][0]["geometry"]["type"] == "Point"


class TestExportToGeojson:
    def test_writes_file_and_returns_collection(self, tmp_path):
        output = tmp_path / "storm_track.geojson"
        result = export_to_geojson(make_bulletin(), str(output))

        assert output.exists()
        written = json.loads(output.read_text(encoding="utf-8"))
        assert written == result
        assert written["type"] == "FeatureCollection"

    def test_default_output_directory_created(self, tmp_path, monkeypatch):
        output = tmp_path / "nested" / "dir" / "track.geojson"
        export_to_geojson(make_bulletin(), str(output))
        assert output.exists()

    def test_default_output_path_is_under_data_output(self):
        assert DEFAULT_OUTPUT_PATH.name == "storm_track.geojson"
        assert "output" in DEFAULT_OUTPUT_PATH.parts
