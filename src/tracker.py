"""Stitch sequential bulletins into a storm track and verify forecast skill.

Ingest bulletins in chronological order. The tracker enforces the series
invariants (bulletin number and issue time must advance), compares the
observed displacement between fixes against the movement stated in the
bulletin, and scores the forecast track of each bulletin against the fixes
of later bulletins.

All times are UTC; the current center of a bulletin is analyzed one hour
before its issue time (PAGASA convention, adjustable).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path

from src.schemas.bulletin import Coordinate, ForecastPoint, StormBulletin

EARTH_RADIUS_KM = 6371.0
FORECAST_MATCH_WINDOW = timedelta(hours=3)


def haversine_km(a: Coordinate, b: Coordinate) -> float:
    """Great-circle distance between two coordinates in kilometers."""
    phi1, phi2 = math.radians(a.lat), math.radians(b.lat)
    dphi = math.radians(b.lat - a.lat)
    dlambda = math.radians(b.lon - a.lon)
    h = (
        math.sin(dphi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    )
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(h))


def bearing_deg(a: Coordinate, b: Coordinate) -> float:
    """Initial great-circle bearing from a to b, degrees clockwise from N."""
    phi1, phi2 = math.radians(a.lat), math.radians(b.lat)
    dlambda = math.radians(b.lon - a.lon)
    y = math.sin(dlambda) * math.cos(phi2)
    x = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(dlambda)
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


def _angular_difference(a_deg: float, b_deg: float) -> float:
    return min(abs(a_deg - b_deg), 360.0 - abs(a_deg - b_deg))


@dataclass
class TrackIssue:
    """A soft anomaly found while stitching a bulletin series."""

    bulletin_number: int
    kind: str
    message: str


@dataclass
class StormTracker:
    """Ingests bulletins of one storm and reports track issues."""

    storm_name: str
    analysis_lag: timedelta = timedelta(hours=1)
    bulletins: list[StormBulletin] = field(default_factory=list)
    issues: list[TrackIssue] = field(default_factory=list)
    _pending_forecasts: list[tuple[StormBulletin, ForecastPoint]] = field(default_factory=list)
    _fixes: list[tuple[object, Coordinate]] = field(default_factory=list)
    _forecast_errors_km: list[float] = field(default_factory=list)
    _category_matches: list[bool] = field(default_factory=list)

    def _issue(self, bulletin: StormBulletin, kind: str, message: str) -> None:
        self.issues.append(
            TrackIssue(bulletin_number=bulletin.bulletin_number, kind=kind, message=message)
        )

    def ingest(self, bulletin: StormBulletin) -> None:
        """Add one bulletin; enforce invariants and score its forecasts."""
        if self.bulletins:
            last = self.bulletins[-1]
            if bulletin.bulletin_number <= last.bulletin_number:
                self._issue(
                    bulletin,
                    "non_monotonic_number",
                    f"bulletin #{bulletin.bulletin_number} after #{last.bulletin_number}",
                )
            if bulletin.issued_at <= last.issued_at:
                self._issue(
                    bulletin,
                    "stale_issue_time",
                    f"issued {bulletin.issued_at.isoformat()} at or before #{last.bulletin_number}",
                )
            if bulletin.storm_name != last.storm_name:
                self._issue(
                    bulletin,
                    "storm_name_change",
                    f"storm name changed from {last.storm_name!r} to {bulletin.storm_name!r}",
                )
            if last.inside_par and not bulletin.inside_par:
                self._issue(
                    bulletin,
                    "par_exit",
                    "center has left the Philippine Area of Responsibility",
                )

        # Compare observed displacement against the stated movement.
        self._check_movement(bulletin)

        # Verify this fix against earlier forecasts.
        analysis_time = bulletin.issued_at - self.analysis_lag
        matched: list[tuple[StormBulletin, ForecastPoint]] = []
        for source, forecast in self._pending_forecasts:
            age = abs((forecast.timestamp - analysis_time).total_seconds())
            if age <= FORECAST_MATCH_WINDOW.total_seconds():
                error_km = haversine_km(forecast.position, bulletin.current_position)
                self._forecast_errors_km.append(error_km)
                if source.typhoon_category is not None and forecast.category is not None:
                    self._category_matches.append(
                        forecast.category == source.typhoon_category
                    )
            elif forecast.timestamp < analysis_time - FORECAST_MATCH_WINDOW:
                continue  # expired without a verifying fix
            matched.append((source, forecast))
        self._pending_forecasts = matched

        self._pending_forecasts.extend(
            (bulletin, point) for point in bulletin.forecast_track
        )
        self._fixes.append((analysis_time, bulletin.current_position))
        self.bulletins.append(bulletin)

    def _check_movement(self, bulletin: StormBulletin) -> None:
        if len(self._fixes) < 1:
            return
        analysis_time = bulletin.issued_at - self.analysis_lag
        previous_time, previous_position = self._fixes[-1]
        elapsed_hours = (analysis_time - previous_time).total_seconds() / 3600.0
        if elapsed_hours <= 0:
            return
        distance_km = haversine_km(previous_position, bulletin.current_position)
        observed_speed = distance_km / elapsed_hours
        observed_bearing = bearing_deg(previous_position, bulletin.current_position)

        if bulletin.movement_speed_kmh and observed_speed > 2.0:
            ratio = abs(observed_speed - bulletin.movement_speed_kmh) / bulletin.movement_speed_kmh
            if ratio > 0.4:
                self._issue(
                    bulletin,
                    "speed_mismatch",
                    f"observed {observed_speed:.0f} km/h vs stated "
                    f"{bulletin.movement_speed_kmh:.0f} km/h",
                )
        if bulletin.movement_direction_deg is not None:
            delta = _angular_difference(observed_bearing, bulletin.movement_direction_deg)
            if delta > 45.0:
                self._issue(
                    bulletin,
                    "direction_mismatch",
                    f"observed bearing {observed_bearing:.0f} deg vs stated "
                    f"{bulletin.movement_direction_deg:.0f} deg",
                )

    def report(self) -> dict:
        """Aggregate verification metrics for the ingested series."""
        error_km = self._forecast_errors_km
        return {
            "storm_name": self.storm_name,
            "bulletins": len(self.bulletins),
            "forecast_matches": len(error_km),
            "median_position_error_km": (
                sorted(error_km)[len(error_km) // 2] if error_km else None
            ),
            "category_accuracy": (
                sum(self._category_matches) / len(self._category_matches)
                if self._category_matches
                else None
            ),
            "issue_count": len(self.issues),
            "issues_by_kind": {
                kind: sum(1 for i in self.issues if i.kind == kind)
                for kind in sorted({i.kind for i in self.issues})
            },
        }


def main() -> None:
    """Ingest a storm series from the corpus and print its verification report."""
    import argparse

    from src.extractor import parse_bulletin_with_source

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("storm", help="storm name, for example pepito")
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parent.parent
    corpus_dir = project_root / "data" / "raw" / "corpus"
    paths = sorted(corpus_dir.glob(f"{args.storm}*.txt"))
    if not paths:
        raise SystemExit(f"No corpus files match {args.storm}*")

    tracker: StormTracker | None = None
    for path in paths:
        bulletin, source, result = parse_bulletin_with_source(path.read_text(encoding="utf-8"))
        if tracker is None:
            tracker = StormTracker(storm_name=bulletin.storm_name)
        tracker.ingest(bulletin)
        print(f"#{bulletin.bulletin_number:>2} {path.name:18s} [{source}] "
              f"({bulletin.current_position.lat:.1f}, {bulletin.current_position.lon:.1f})")

    assert tracker is not None
    report = tracker.report()
    print(f"\n{report['storm_name']}: {report['bulletins']} bulletins, "
          f"{report['forecast_matches']} forecast verifications")
    print(f"median forecast position error: "
          f"{report['median_position_error_km']:.0f} km" if report["median_position_error_km"] is not None else "no matches")
    if report["category_accuracy"] is not None:
        print(f"forecast category accuracy: {report['category_accuracy']:.0%}")
    for issue in tracker.issues:
        print(f"  issue #{issue.bulletin_number} [{issue.kind}] {issue.message}")


if __name__ == "__main__":
    main()
