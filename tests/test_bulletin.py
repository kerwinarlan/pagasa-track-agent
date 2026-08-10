"""Tests for the PAGASA Severe Weather Bulletin schema."""

from datetime import datetime

import pytest
from pydantic import ValidationError

from src.schemas.bulletin import (
    Coordinate,
    ForecastPoint,
    StormBulletin,
    TyphoonCategory,
    WindSignalNumber,
)


def make_bulletin(**overrides) -> dict:
    """Return a valid bulletin payload with optional overrides."""
    payload = {
        "bulletin_number": 1,
        "issued_at": datetime(2024, 1, 1, 5, 0),
        "storm_name": "Test",
        "signal_number": WindSignalNumber.SIGNAL_1,
        "typhoon_category": TyphoonCategory.TROPICAL_STORM,
        "current_position": {"lat": 15.0, "lon": 124.0},
        "movement_speed_kmh": 15,
        "movement_direction_deg": 270,
        "central_pressure_hpa": 995,
        "max_sustained_winds_kmh": 75,
        "forecast_track": [],
    }
    payload.update(overrides)
    return payload


class TestCoordinateValidation:
    @pytest.mark.parametrize(
        "lat, lon",
        [
            (4.0, 116.0),  # PAR south-west corner
            (25.0, 127.0),  # PAR north-east corner
            (15.5, 121.5),  # Central Luzon
        ],
    )
    def test_boundary_and_interior_points_accepted(self, lat, lon):
        coord = Coordinate(lat=lat, lon=lon)
        assert coord.lat == lat
        assert coord.lon == lon

    @pytest.mark.parametrize("lat", [3.99, -5.0, 25.01, 90.0])
    def test_latitude_outside_par_rejected(self, lat):
        with pytest.raises(ValidationError, match="Latitude .* outside"):
            Coordinate(lat=lat, lon=124.0)

    @pytest.mark.parametrize("lon", [115.99, 127.01, 180.0, -130.0])
    def test_longitude_outside_par_rejected(self, lon):
        with pytest.raises(ValidationError, match="Longitude .* outside"):
            Coordinate(lat=15.0, lon=lon)


class TestStormBulletin:
    def test_valid_bulletin_accepted(self):
        bulletin = StormBulletin.model_validate(
            make_bulletin(
                signal_number=WindSignalNumber.SIGNAL_4,
                typhoon_category=TyphoonCategory.SUPER_TYPHOON,
                max_sustained_winds_kmh=195,
                central_pressure_hpa=915,
                movement_direction_deg=290,
                forecast_track=[
                    {
                        "timestamp": datetime(2024, 1, 1, 11, 0),
                        "position": {"lat": 15.8, "lon": 123.6},
                    }
                ],
            )
        )
        assert bulletin.storm_name == "Test"
        assert len(bulletin.forecast_track) == 1
        assert bulletin.movement_direction_compass == "WNW"

    def test_forecast_track_position_validated(self):
        with pytest.raises(ValidationError, match="Longitude .* outside"):
            StormBulletin.model_validate(
                make_bulletin(
                    forecast_track=[
                        {
                            "timestamp": datetime(2024, 1, 1, 11, 0),
                            "position": {"lat": 14.0, "lon": 130.0},
                        }
                    ]
                )
            )

    @pytest.mark.parametrize(
        "winds, category",
        [
            (60, TyphoonCategory.TROPICAL_DEPRESSION),
            (75, TyphoonCategory.TROPICAL_STORM),
            (100, TyphoonCategory.SEVERE_TROPICAL_STORM),
            (130, TyphoonCategory.TYPHOON),
            (200, TyphoonCategory.SUPER_TYPHOON),
        ],
    )
    def test_category_matches_wind_thresholds(self, winds, category):
        bulletin = StormBulletin.model_validate(
            make_bulletin(
                typhoon_category=category,
                max_sustained_winds_kmh=winds,
            )
        )
        assert bulletin.typhoon_category == category

    def test_category_mismatch_rejected(self):
        with pytest.raises(ValidationError, match="does not match"):
            StormBulletin.model_validate(
                make_bulletin(
                    typhoon_category=TyphoonCategory.TYPHOON,
                    max_sustained_winds_kmh=75,
                )
            )
