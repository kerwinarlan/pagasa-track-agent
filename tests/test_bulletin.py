"""Tests for the PAGASA Severe Weather Bulletin schema."""

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from src.schemas.bulletin import (
    Coordinate,
    ForecastPoint,
    StormBulletin,
    TyphoonCategory,
    WindSignalNumber,
    implied_signal,
)


def make_bulletin(**overrides) -> dict:
    """Return a valid bulletin payload with optional overrides."""
    payload = {
        "bulletin_number": 1,
        "issued_at": datetime(2024, 1, 1, 5, 0, tzinfo=timezone.utc),
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

    def test_inside_par_uses_hexagon(self):
        """inside_par must be true only inside the PAR hexagon."""
        assert Coordinate(lat=14.0, lon=121.0).inside_par  # Luzon interior
        assert not Coordinate(lat=25.01, lon=127.0).inside_par  # north of PAR
        assert not Coordinate(lat=15.0, lon=114.5).inside_par  # west of PAR
        assert Coordinate(lat=15.0, lon=134.0).inside_par  # eastern band

    @pytest.mark.parametrize("lat", [-0.01, -5.0, 50.01, 90.0])
    def test_latitude_outside_sanity_box_rejected(self, lat):
        with pytest.raises(ValidationError, match="Latitude .* outside"):
            Coordinate(lat=lat, lon=124.0)

    @pytest.mark.parametrize("lon", [99.99, 170.01, 180.0, -130.0])
    def test_longitude_outside_sanity_box_rejected(self, lon):
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
                        "timestamp": datetime(2024, 1, 1, 11, 0, tzinfo=timezone.utc),
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
                            "timestamp": datetime(2024, 1, 1, 11, 0, tzinfo=timezone.utc),
                            "position": {"lat": 14.0, "lon": 171.0},
                        }
                    ]
                )
            )

    def test_forecast_timestamps_must_increase(self):
        with pytest.raises(ValidationError, match="strictly increasing"):
            StormBulletin.model_validate(
                make_bulletin(
                    forecast_track=[
                        {
                            "timestamp": datetime(2024, 1, 1, 11, 0, tzinfo=timezone.utc),
                            "position": {"lat": 15.0, "lon": 123.0},
                        },
                        {
                            "timestamp": datetime(2024, 1, 1, 9, 0, tzinfo=timezone.utc),
                            "position": {"lat": 15.2, "lon": 122.5},
                        },
                    ]
                )
            )

    def test_forecast_after_issue_time(self):
        with pytest.raises(ValidationError, match="after the issue time"):
            StormBulletin.model_validate(
                make_bulletin(
                    forecast_track=[
                        {
                            "timestamp": datetime(2024, 1, 1, 2, 0, tzinfo=timezone.utc),
                            "position": {"lat": 15.0, "lon": 123.0},
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


class TestCategoryAndSignal:
    def test_from_label_short_and_long(self):
        assert TyphoonCategory.from_label("TY") is TyphoonCategory.TYPHOON
        assert TyphoonCategory.from_label("Super Typhoon") is TyphoonCategory.SUPER_TYPHOON
        assert TyphoonCategory.from_label("garbage") is None

    def test_from_winds_boundaries(self):
        assert TyphoonCategory.from_winds(62) is TyphoonCategory.TROPICAL_DEPRESSION
        assert TyphoonCategory.from_winds(63) is TyphoonCategory.TROPICAL_STORM
        assert TyphoonCategory.from_winds(89) is TyphoonCategory.SEVERE_TROPICAL_STORM
        assert TyphoonCategory.from_winds(118) is TyphoonCategory.TYPHOON
        assert TyphoonCategory.from_winds(185) is TyphoonCategory.SUPER_TYPHOON

    def test_implied_signal_table(self):
        assert implied_signal(60) == WindSignalNumber.SIGNAL_1
        assert implied_signal(75) == WindSignalNumber.SIGNAL_2
        assert implied_signal(90) == WindSignalNumber.SIGNAL_3
        assert implied_signal(120) == WindSignalNumber.SIGNAL_4
        assert implied_signal(190) == WindSignalNumber.SIGNAL_5

    def test_timestamps_are_utc(self):
        bulletin = StormBulletin.model_validate(
            make_bulletin(issued_at=datetime(2024, 1, 1, 5, 0, tzinfo=timezone.utc))
        )
        assert bulletin.issued_at.tzinfo is not None
        assert bulletin.issued_at.utcoffset().total_seconds() == 0
