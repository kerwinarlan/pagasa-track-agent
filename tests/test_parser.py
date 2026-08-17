"""Deterministic parser tests, driven by the golden corpus.

The corpus is 37 real PAGASA bulletins extracted from the PDFs archived
in pagasa-parser/bulletin-archive. 36 must parse deterministically; the
one LPA-dissipation final (auring_24f) has no wind intensity and is a
legitimate LLM-fallback case.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.parser import _forecast_time, compass_from_text, deterministic_parse
from src.schemas.bulletin import TyphoonCategory, WindSignalNumber

CORPUS_DIR = Path(__file__).resolve().parent.parent / "data" / "raw" / "corpus"


def _parse(name: str):
    result = deterministic_parse((CORPUS_DIR / name).read_text(encoding="utf-8"))
    assert result.accepted, (name, result.warnings)
    assert result.bulletin is not None
    return result.bulletin


class TestCorpusAcceptance:
    def test_all_but_lpa_final_parse_deterministically(self):
        """36 of 37 bulletins must be accepted without the LLM."""
        failures = []
        for path in sorted(CORPUS_DIR.glob("*.txt")):
            result = deterministic_parse(path.read_text(encoding="utf-8"))
            if not result.accepted:
                failures.append((path.name, result.warnings))
        assert [name for name, _ in failures] == ["auring_24f.txt"], failures

    def test_auring_lpa_final_is_rejected(self):
        """The LPA-dissipation final has no winds; it needs the LLM."""
        result = deterministic_parse(
            (CORPUS_DIR / "auring_24f.txt").read_text(encoding="utf-8")
        )
        assert not result.accepted
        assert result.confidence < 0.8
        assert result.bulletin is None


class TestKnownValues:
    def test_pepito_01_forecast_points(self):
        """2020-era bullets; the mislabeled '96 Hour (Saturday morning)'
        must resolve to +120 h, not collide with the 96 h point."""
        bulletin = _parse("pepito_01.txt")
        stamps = [p.timestamp for p in bulletin.forecast_track]
        assert len(stamps) == 5
        assert all(b > a for a, b in zip(stamps, stamps[1:]))
        assert (stamps[-1] - bulletin.issued_at).total_seconds() == 120 * 3600

    def test_pepito_13_tonight_fallback(self):
        """'(Tonight)' has no weekday; numeric hours must resolve it, and
        the weekday labels shifted by one day must not collide."""
        bulletin = _parse("pepito_13.txt")
        stamps = [p.timestamp for p in bulletin.forecast_track]
        assert all(b > a for a, b in zip(stamps, stamps[1:]))
        assert (stamps[0] - bulletin.issued_at).total_seconds() == 24 * 3600

    def test_carina_14_intensity_and_signal(self):
        """2022+ table era: 130 km/h Typhoon, TCWS #1, pressure parsed."""
        bulletin = _parse("carina_14.txt")
        assert bulletin.storm_name == "Carina"
        assert bulletin.international_name == "GAEMI"
        assert bulletin.max_sustained_winds_kmh == 130
        assert bulletin.typhoon_category is TyphoonCategory.TYPHOON
        assert bulletin.signal_number is WindSignalNumber.SIGNAL_1
        assert bulletin.central_pressure_hpa == 975
        assert len(bulletin.forecast_track) >= 7

    def test_ester_02_single_token_compass(self):
        """'Northwestward at 10 km/h' must yield direction, not None."""
        bulletin = _parse("ester_02.txt")
        assert bulletin.movement_direction_deg == 315.0
        assert bulletin.movement_speed_kmh == 10.0

    def test_quinta_final_outside_par(self):
        """OUTSIDE PAR centers are data, not validation errors."""
        bulletin = _parse("quinta_23f.txt")
        assert bulletin.is_final
        assert not bulletin.inside_par
        assert bulletin.bulletin_number == 23


class TestHelpers:
    def test_compass_from_text_single_token(self):
        assert compass_from_text("Northwestward") == ("NW", "Northwestward")
        assert compass_from_text("North northwestward") == ("NNW", "North northwestward")
        assert compass_from_text("West") == ("W", "West")

    def test_forecast_time_weekday_wins_only_when_later(self):
        # Issued Mon 5:00 AM PHT (realistic PAGASA cycle).
        issued = datetime(2020, 10, 18, 21, 0, tzinfo=timezone.utc)
        # Friday morning = +96 h agrees with the numeric prefix.
        friday = _forecast_time(issued, "96 Hour (Friday morning)", 96)
        assert (friday - issued).total_seconds() == 96 * 3600
        # Saturday is one day further out than the (misprinted) 96 h.
        saturday = _forecast_time(issued, "96 Hour (Saturday morning)", 96)
        assert (saturday - issued).total_seconds() == 120 * 3600
        # A label pointing earlier than the prefix must not win.
        tonight = _forecast_time(issued, "24 Hour (Tonight)", 24)
        assert (tonight - issued).total_seconds() == 24 * 3600
