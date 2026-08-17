"""Tracker (stitcher + forecast verification) tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.schemas.bulletin import Coordinate, ForecastPoint, StormBulletin, TyphoonCategory
from src.tracker import StormTracker, bearing_deg, haversine_km


def _bulletin(number, issued, lat, lon, speed=None, direction=None, name="Test"):
    return StormBulletin(
        bulletin_number=number,
        issued_at=issued,
        storm_name=name,
        typhoon_category=TyphoonCategory.TROPICAL_STORM,
        current_position=Coordinate(lat=lat, lon=lon),
        movement_speed_kmh=speed,
        movement_direction_deg=direction,
        max_sustained_winds_kmh=75,
    )


def test_haversine_known_distance():
    """1 degree of latitude is 111.19 km on the great circle."""
    assert haversine_km(Coordinate(lat=15.0, lon=120.0), Coordinate(lat=16.0, lon=120.0)) == pytest.approx(111.19, rel=1e-3)


def test_bearing_due_west():
    # A rhumb line due west at 15N differs slightly from a great circle.
    assert bearing_deg(
        Coordinate(lat=15.0, lon=122.0), Coordinate(lat=15.0, lon=121.0)
    ) == pytest.approx(270.0, abs=0.5)


class TestInvariants:
    def test_monotonic_number_and_time(self):
        tracker = StormTracker("Test")
        t0 = datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc)
        tracker.ingest(_bulletin(1, t0, 15.0, 125.0))
        tracker.ingest(_bulletin(2, t0 + timedelta(hours=6), 15.0, 124.5))
        tracker.ingest(_bulletin(1, t0 + timedelta(hours=12), 15.0, 124.0))  # renumber
        tracker.ingest(_bulletin(4, t0 + timedelta(hours=10), 15.0, 123.5))  # stale
        kinds = [i.kind for i in tracker.issues]
        assert "non_monotonic_number" in kinds
        assert "stale_issue_time" in kinds

    def test_name_change_flags(self):
        tracker = StormTracker("Test")
        t0 = datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc)
        tracker.ingest(_bulletin(1, t0, 15.0, 125.0))
        tracker.ingest(_bulletin(2, t0 + timedelta(hours=6), 15.0, 124.5, name="Other"))
        assert any(i.kind == "storm_name_change" for i in tracker.issues)

    def test_par_exit_flags(self):
        tracker = StormTracker("Test")
        t0 = datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc)
        tracker.ingest(_bulletin(1, t0, 20.0, 122.0))  # inside PAR
        tracker.ingest(_bulletin(2, t0 + timedelta(hours=6), 27.0, 128.0))  # outside
        assert any(i.kind == "par_exit" for i in tracker.issues)


class TestMovementChecks:
    def test_speed_mismatch_flagged(self):
        tracker = StormTracker("Test")
        t0 = datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc)
        tracker.ingest(_bulletin(1, t0, 15.0, 125.0))
        # 111 km west in 6 h = 18.5 km/h; stated 50 km/h -> flagged.
        tracker.ingest(_bulletin(2, t0 + timedelta(hours=6), 15.0, 124.0, speed=50))
        assert any(i.kind == "speed_mismatch" for i in tracker.issues)

    def test_direction_mismatch_flagged(self):
        tracker = StormTracker("Test")
        t0 = datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc)
        tracker.ingest(_bulletin(1, t0, 15.0, 125.0))
        # Actual movement is westward; stated is northward.
        tracker.ingest(_bulletin(2, t0 + timedelta(hours=6), 15.0, 124.0, direction=0))
        assert any(i.kind == "direction_mismatch" for i in tracker.issues)


class TestForecastVerification:
    def test_forecast_verified_against_later_fix(self):
        tracker = StormTracker("Test")
        t0 = datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc)
        first = _bulletin(1, t0, 15.0, 125.0)
        # Forecast: center at (15.0, 122.0) in 12 h.
        first.forecast_track.append(
            ForecastPoint(
                timestamp=t0 + timedelta(hours=12),
                position={"lat": 15.0, "lon": 122.0},
            )
        )
        tracker.ingest(first)
        # 12 h later the center is actually at (15.0, 121.0): 1 degree of
        # longitude at 15N is 107.4 km.
        tracker.ingest(_bulletin(2, t0 + timedelta(hours=12), 15.0, 121.0))
        report = tracker.report()
        assert report["forecast_matches"] == 1
        assert report["median_position_error_km"] == pytest.approx(107.4, abs=1.0)

    def test_expired_forecast_not_counted(self):
        tracker = StormTracker("Test")
        t0 = datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc)
        first = _bulletin(1, t0, 15.0, 125.0)
        first.forecast_track.append(
            ForecastPoint(
                timestamp=t0 + timedelta(hours=12),
                position={"lat": 15.0, "lon": 122.0},
            )
        )
        tracker.ingest(first)
        # Next fix lands before the forecast window; the forecast expires.
        tracker.ingest(_bulletin(2, t0 + timedelta(hours=3), 15.0, 124.7))
        assert tracker.report()["forecast_matches"] == 0
