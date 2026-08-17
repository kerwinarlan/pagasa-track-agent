"""Pydantic v2 schemas for PAGASA Severe Weather Bulletins.

Domain rules follow PAGASA's published definitions:

* Intensity categories (as of 23 March 2022, in knots then converted to
  km/h; source: pagasa.dost.gov.ph/information/about-tropical-cyclone):
  Tropical Depression <= 62 km/h (< 34 kt), Tropical Storm 63-88 km/h
  (34-47 kt), Severe Tropical Storm 89-117 km/h (48-63 kt),
  Typhoon 118-184 km/h (64-99 kt), Super Typhoon >= 185 km/h (>= 100 kt).
  The km/h table on the PAGASA page overlaps at 62 and 87-88 due to
  rounding; the knot scale resolves every boundary, and real bulletins
  label 175 km/h as Typhoon and 185 km/h as Super Typhoon.
* The Philippine Area of Responsibility (PAR) is a hexagon, not a box:
  vertices (5N,115E), (15N,115E), (21N,120E), (25N,120E), (25N,135E),
  (5N,135E). PAR membership is metadata: real bulletins routinely place
  forecast points, and even the current center, OUTSIDE PAR (for example
  TCB NR. 25 for JULIAN). Only a wider Western North Pacific sanity box is
  a hard constraint.
* All timestamps are timezone-aware, canonicalized to UTC. PAGASA bulletins
  are issued in Philippine Standard Time (UTC+8).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from enum import Enum

from pydantic import BaseModel, Field, field_validator, model_validator

# Western North Pacific sanity bounds in degrees (hard constraints).
MIN_LATITUDE: float = 0.0
MAX_LATITUDE: float = 50.0
MIN_LONGITUDE: float = 100.0
MAX_LONGITUDE: float = 170.0

# Official PAR hexagon, clockwise from the south-west vertex (PAGASA).
PAR_VERTICES: list[tuple[float, float]] = [
    (5.0, 115.0),
    (15.0, 115.0),
    (21.0, 120.0),
    (25.0, 120.0),
    (25.0, 135.0),
    (5.0, 135.0),
]

# Intensity thresholds in km/h (>= threshold implies the stronger class).
# The first boundary below each category name is its lower bound.
_TYPHOON_CATEGORY_TABLE: list[tuple[float, str]] = [
    (185.0, "Super Typhoon"),
    (118.0, "Typhoon"),
    (89.0, "Severe Tropical Storm"),
    (63.0, "Tropical Storm"),
    (0.0, "Tropical Depression"),
]

# Implied maximum TCWS number from center winds, km/h (PAGASA TCWS scale).
_TCWS_TABLE: list[tuple[float, int]] = [
    (185.0, 5),
    (118.0, 4),
    (89.0, 3),
    (62.0, 2),
    (39.0, 1),
    (0.0, 0),
]

# Rough physical plausibility bands for soft warnings (not hard rejects).
PRESSURE_SANE_MIN: float = 850.0
PRESSURE_SANE_MAX: float = 1060.0
WIND_SANE_MAX: float = 400.0


class TyphoonCategory(str, Enum):
    """PAGASA tropical cyclone intensity categories."""

    TROPICAL_DEPRESSION = "Tropical Depression"
    TROPICAL_STORM = "Tropical Storm"
    SEVERE_TROPICAL_STORM = "Severe Tropical Storm"
    TYPHOON = "Typhoon"
    SUPER_TYPHOON = "Super Typhoon"

    @classmethod
    def from_winds(cls, winds_kmh: float) -> "TyphoonCategory":
        """Return the PAGASA category for a maximum sustained wind speed."""
        for threshold, label in _TYPHOON_CATEGORY_TABLE:
            if winds_kmh >= threshold:
                return cls(label)
        raise ValueError(f"Unreachable: winds {winds_kmh}")

    @classmethod
    def from_label(cls, label: str) -> "TyphoonCategory | None":
        """Map a bulletin label (for example 'STS', 'Super Typhoon') to a category."""
        label = label.strip().upper().replace("-", " ").replace("_", " ")
        aliases = {
            "TD": "Tropical Depression",
            "TROPICAL DEPRESSION": "Tropical Depression",
            "TS": "Tropical Storm",
            "TROPICAL STORM": "Tropical Storm",
            "STS": "Severe Tropical Storm",
            "SEVERE TROPICAL STORM": "Severe Tropical Storm",
            "TY": "Typhoon",
            "TYPHOON": "Typhoon",
            "STY": "Super Typhoon",
            "SUPER TYPHOON": "Super Typhoon",
        }
        label = aliases.get(label, label).upper()
        for category in cls:
            if category.value.upper() == label:
                return category
        return None


class WindSignalNumber(int, Enum):
    """PAGASA tropical cyclone wind signal (TCWS) number."""

    SIGNAL_1 = 1
    SIGNAL_2 = 2
    SIGNAL_3 = 3
    SIGNAL_4 = 4
    SIGNAL_5 = 5


class Coordinate(BaseModel):
    """A geographic coordinate inside the Western North Pacific sanity box."""

    lat: float = Field(description="Latitude in degrees north of the equator.")
    lon: float = Field(description="Longitude in degrees east of Greenwich.")

    @field_validator("lat")
    @classmethod
    def latitude_within_sanity_box(cls, value: float) -> float:
        if not MIN_LATITUDE <= value <= MAX_LATITUDE:
            raise ValueError(
                f"Latitude {value} outside sanity bounds "
                f"({MIN_LATITUDE}N to {MAX_LATITUDE}N)."
            )
        return value

    @field_validator("lon")
    @classmethod
    def longitude_within_sanity_box(cls, value: float) -> float:
        if not MIN_LONGITUDE <= value <= MAX_LONGITUDE:
            raise ValueError(
                f"Longitude {value} outside sanity bounds "
                f"({MIN_LONGITUDE}E to {MAX_LONGITUDE}E)."
            )
        return value

    @property
    def inside_par(self) -> bool:
        """True if this coordinate lies inside the official PAR hexagon."""
        return point_in_polygon(self.lat, self.lon, PAR_VERTICES)

    @property
    def outside_par(self) -> bool:
        """True if this coordinate lies outside the official PAR hexagon."""
        return not self.inside_par


def point_in_polygon(lat: float, lon: float, vertices: list[tuple[float, float]]) -> bool:
    """Ray-casting point-in-polygon test (even-odd rule), no dependencies."""
    inside = False
    j = len(vertices) - 1
    for i, (lat_i, lon_i) in enumerate(vertices):
        lat_j, lon_j = vertices[j]
        if (lat_i > lat) != (lat_j > lat):
            x_cross = (lon_j - lon_i) * (lat - lat_i) / (lat_j - lat_i) + lon_i
            if lon < x_cross:
                inside = not inside
        j = i
    return inside


class ForecastPoint(BaseModel):
    """A timestamped forecast position along the storm track."""

    timestamp: datetime = Field(description="Forecast valid time (UTC).")
    position: Coordinate = Field(description="Forecast center position.")
    max_sustained_winds_kmh: float | None = Field(
        default=None, description="Forecast maximum sustained winds (km/h)."
    )
    category: TyphoonCategory | None = Field(
        default=None, description="Forecast intensity category."
    )
    movement_direction_deg: float | None = Field(
        default=None,
        ge=0,
        lt=360,
        description="Forecast movement direction in degrees from true north.",
    )
    movement_speed_kmh: float | None = Field(
        default=None, description="Forecast movement speed (km/h)."
    )

    @model_validator(mode="after")
    def forecast_category_matches_winds(self) -> "ForecastPoint":
        if (
            self.max_sustained_winds_kmh is not None
            and self.category is not None
            and self.category != TyphoonCategory.from_winds(self.max_sustained_winds_kmh)
        ):
            raise ValueError(
                f"Forecast category {self.category.value!r} does not match "
                f"forecast winds of {self.max_sustained_winds_kmh} km/h."
            )
        return self


class WindSignalArea(BaseModel):
    """The areas under one tropical cyclone wind signal."""

    signal_number: WindSignalNumber = Field(description="TCWS number.")
    areas: list[str] = Field(
        default_factory=list,
        description="Region-area strings (one per column with content).",
    )


class StormBulletin(BaseModel):
    """A parsed PAGASA Severe Weather Bulletin."""

    bulletin_number: int = Field(
        ge=1, description="Sequential bulletin number for the cyclone."
    )
    issued_at: datetime = Field(description="Bulletin issue timestamp (UTC).")
    storm_name: str = Field(
        min_length=1, description="PAGASA local name of the cyclone."
    )
    international_name: str | None = Field(
        default=None, description="International name, when given in parentheses."
    )
    is_final: bool = Field(
        default=False, description="True for the FINAL bulletin of a cyclone."
    )
    typhoon_category: TyphoonCategory = Field(
        description="Tropical cyclone intensity category (validated vs winds)."
    )
    current_position: Coordinate = Field(description="Center of the cyclone.")
    position_description: str | None = Field(
        default=None, description="Reference point text, for example "
        "'270 km West Northwest of Itbayat, Batanes'."
    )
    signal_number: WindSignalNumber | None = Field(
        default=None, description="Highest TCWS number hoisted (legacy single value)."
    )
    wind_signal_areas: list[WindSignalArea] = Field(
        default_factory=list,
        description="Areas under each TCWS number in effect.",
    )
    movement_speed_kmh: float | None = Field(
        default=None,
        gt=0,
        description="Forward speed in km/h; None when 'slowly' or 'almost stationary'.",
    )
    movement_direction_deg: float | None = Field(
        default=None,
        ge=0,
        lt=360,
        description="Forward direction in degrees clockwise from true north.",
    )
    movement_direction_text: str | None = Field(
        default=None, description="Raw movement phrase from the bulletin."
    )
    central_pressure_hpa: float | None = Field(
        default=None, description="Central atmospheric pressure in hPa."
    )
    max_sustained_winds_kmh: float = Field(
        gt=0, description="Maximum sustained winds in km/h."
    )
    gustiness_kmh: float | None = Field(
        default=None, description="Gustiness in km/h when reported."
    )
    forecast_track: list[ForecastPoint] = Field(
        default_factory=list,
        description="Timestamped forecast positions along the storm track.",
    )

    @property
    def hoisted_signal(self) -> WindSignalNumber | None:
        """The highest signal in effect: stored value or max of signal areas."""
        if self.signal_number is not None:
            return self.signal_number
        if not self.wind_signal_areas:
            return None
        return WindSignalNumber(max(a.signal_number.value for a in self.wind_signal_areas))

    @property
    def inside_par(self) -> bool:
        """True if the current center is inside the PAR hexagon."""
        return self.current_position.inside_par

    @property
    def movement_direction_compass(self) -> str | None:
        """The movement direction as a 16-point compass bearing, if known."""
        if self.movement_direction_deg is None:
            return None
        points = [
            "N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
            "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW",
        ]
        index = int(((self.movement_direction_deg % 360) + 11.25) // 22.5) % 16
        return points[index]

    @field_validator("issued_at")
    @classmethod
    def issued_at_must_be_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError(
                "issued_at must be timezone-aware; convert PHT to UTC before parsing."
            )
        return value

    @model_validator(mode="after")
    def category_matches_wind_speed(self) -> "StormBulletin":
        expected = TyphoonCategory.from_winds(self.max_sustained_winds_kmh)
        if self.typhoon_category != expected:
            raise ValueError(
                f"Typhoon category {self.typhoon_category.value!r} does not match "
                f"max sustained winds of {self.max_sustained_winds_kmh} km/h "
                f"(expected {expected.value!r})."
            )
        return self

    @model_validator(mode="after")
    def forecast_timestamps_increase(self) -> "StormBulletin":
        stamps = [p.timestamp for p in self.forecast_track]
        if any(next_ <= prev for prev, next_ in zip(stamps, stamps[1:])):
            raise ValueError("Forecast track timestamps must be strictly increasing.")
        return self

    @model_validator(mode="after")
    def forecast_after_issue_time(self) -> "StormBulletin":
        if any(p.timestamp <= self.issued_at for p in self.forecast_track):
            raise ValueError("Forecast points must be valid after the issue time.")
        return self

    def warnings(self) -> list[str]:
        """Soft physical-consistency notes; informational, never blocking."""
        notes: list[str] = []
        implied = implied_signal(self.max_sustained_winds_kmh)
        hoisted = self.hoisted_signal
        if hoisted is not None and implied is not None and hoisted.value > implied:
            notes.append(
                f"TCWS #{hoisted.value} exceeds the signal implied by center winds "
                f"({self.max_sustained_winds_kmh} km/h implies at most #{implied.value})."
            )
        if self.central_pressure_hpa is not None:
            if not PRESSURE_SANE_MIN <= self.central_pressure_hpa <= PRESSURE_SANE_MAX:
                notes.append(
                    f"Central pressure {self.central_pressure_hpa} hPa is outside the "
                    f"plausible range ({PRESSURE_SANE_MIN}-{PRESSURE_SANE_MAX} hPa)."
                )
            elif self.central_pressure_hpa > 1025 and self.max_sustained_winds_kmh >= 89:
                notes.append(
                    f"High pressure ({self.central_pressure_hpa} hPa) with "
                    f"{self.max_sustained_winds_kmh} km/h winds is unusual."
                )
        if self.max_sustained_winds_kmh > WIND_SANE_MAX:
            notes.append(
                f"Max winds {self.max_sustained_winds_kmh} km/h exceed the plausible "
                f"maximum ({WIND_SANE_MAX} km/h)."
            )
        if self.forecast_track and self.forecast_track[0].position.outside_par:
            notes.append("Forecast track begins outside the PAR.")
        return notes


def implied_signal(winds_kmh: float) -> WindSignalNumber | None:
    """The highest TCWS number implied by center winds (soft guide only)."""
    for threshold, number in _TCWS_TABLE:
        if winds_kmh >= threshold:
            return WindSignalNumber(number) if number else None
    return None


PHT_OFFSET = timedelta(hours=8)


def utc(dt: datetime) -> datetime:
    """Return ``dt`` in UTC, assuming Philippine Standard Time if naive."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc) - PHT_OFFSET
    return dt.astimezone(timezone.utc)


# Backwards-compatible alias for earlier consumers.
SevereWeatherBulletin = StormBulletin
