"""Tests for the Pydantic schemas in src.schemas.bulletin."""

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


class TestCoordinate:
    """Tests for Coordinate PAR bounds validation."""

    def test_valid_coordinate_within_par(self):
        """A coordinate inside the PAR must validate."""
        coord = Coordinate(lat=16.5, lon=123.0)
        assert coord.lat == 16.5
        assert coord.lon == 123.0

    def test_out_of_bounds_latitude_raises(self):
        """A latitude north of the PAR must raise a ValidationError."""
        with pytest.raises(ValidationError, match="Latitude .* outside"):
            Coordinate(lat=30.0, lon=123.0)

    def test_out_of_bounds_longitude_raises(self):
        """A longitude west of the PAR must raise a ValidationError."""
        with pytest.raises(ValidationError, match="Longitude .* outside"):
            Coordinate(lat=16.5, lon=100.0)

    def test_par_boundaries_are_accepted(self):
        """Exact PAR boundary values must validate."""
        coord = Coordinate(lat=4.0, lon=116.0)
        assert coord.lat == 4.0
        assert coord.lon == 116.0


class TestStormBulletin:
    """Tests for full StormBulletin instantiation."""

    def test_valid_full_bulletin_instantiates(self):
        """A complete, consistent bulletin must instantiate successfully."""
        bulletin = StormBulletin(
            bulletin_number=15,
            issued_at=datetime(2024, 11, 17, 5, 0),
            storm_name="SAMPLE",
            signal_number=WindSignalNumber.SIGNAL_4,
            typhoon_category=TyphoonCategory.SUPER_TYPHOON,
            current_position=Coordinate(lat=15.2, lon=124.8),
            movement_speed_kmh=20,
            movement_direction_deg=292.5,
            central_pressure_hpa=915,
            max_sustained_winds_kmh=195,
            forecast_track=[
                ForecastPoint(
                    timestamp=datetime(2024, 11, 18, 5, 0),
                    position=Coordinate(lat=15.8, lon=123.6),
                ),
                ForecastPoint(
                    timestamp=datetime(2024, 11, 19, 5, 0),
                    position=Coordinate(lat=16.4, lon=122.2),
                ),
            ],
        )

        assert bulletin.storm_name == "SAMPLE"
        assert bulletin.bulletin_number == 15
        assert bulletin.signal_number == WindSignalNumber.SIGNAL_4
        assert bulletin.typhoon_category == TyphoonCategory.SUPER_TYPHOON
        assert bulletin.current_position.lat == 15.2
        assert bulletin.current_position.lon == 124.8
        assert bulletin.movement_speed_kmh == 20
        assert bulletin.movement_direction_deg == 292.5
        assert bulletin.central_pressure_hpa == 915
        assert bulletin.max_sustained_winds_kmh == 195
        assert len(bulletin.forecast_track) == 2
        assert bulletin.forecast_track[1].position.lat == 16.4
        assert bulletin.forecast_track[1].position.lon == 122.2

    def test_forecast_track_defaults_to_empty(self):
        """A bulletin without a forecast track must default to an empty list."""
        bulletin = StormBulletin(
            bulletin_number=1,
            issued_at=datetime(2024, 11, 17, 5, 0),
            storm_name="SAMPLE",
            signal_number=WindSignalNumber.SIGNAL_1,
            typhoon_category=TyphoonCategory.TROPICAL_STORM,
            current_position=Coordinate(lat=15.2, lon=124.8),
            movement_speed_kmh=20,
            movement_direction_deg=292.5,
            central_pressure_hpa=995,
            max_sustained_winds_kmh=75,
        )
        assert bulletin.forecast_track == []

    def test_inconsistent_category_and_winds_raises(self):
        """A category that does not match the wind speed must raise."""
        with pytest.raises(ValidationError, match="does not match"):
            StormBulletin(
                bulletin_number=1,
                issued_at=datetime(2024, 11, 17, 5, 0),
                storm_name="SAMPLE",
                signal_number=WindSignalNumber.SIGNAL_1,
                typhoon_category=TyphoonCategory.TYPHOON,
                current_position=Coordinate(lat=15.2, lon=124.8),
                movement_speed_kmh=20,
                movement_direction_deg=292.5,
                central_pressure_hpa=995,
                max_sustained_winds_kmh=75,
            )
