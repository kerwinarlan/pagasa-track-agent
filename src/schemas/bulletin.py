"""Pydantic v2 schemas for PAGASA Severe Weather Bulletins.

All geographic coordinates are validated to lie inside the Philippine
Area of Responsibility (PAR): latitude 4N to 25N and longitude
116E to 127E.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field, field_validator, model_validator

# Philippine Area of Responsibility (PAR) bounds in degrees.
MIN_LATITUDE: float = 4.0
MAX_LATITUDE: float = 25.0
MIN_LONGITUDE: float = 116.0
MAX_LONGITUDE: float = 127.0


class TyphoonCategory(str, Enum):
    """PAGASA tropical cyclone intensity categories."""

    TROPICAL_DEPRESSION = "Tropical Depression"
    TROPICAL_STORM = "Tropical Storm"
    SEVERE_TROPICAL_STORM = "Severe Tropical Storm"
    TYPHOON = "Typhoon"
    SUPER_TYPHOON = "Super Typhoon"


class WindSignalNumber(int, Enum):
    """PAGASA tropical cyclone wind signal (TCWS) number."""

    SIGNAL_1 = 1
    SIGNAL_2 = 2
    SIGNAL_3 = 3
    SIGNAL_4 = 4
    SIGNAL_5 = 5


class Coordinate(BaseModel):
    """A geographic coordinate inside the Philippine Area of Responsibility."""

    lat: float = Field(description="Latitude in degrees north of the equator.")
    lon: float = Field(description="Longitude in degrees east of Greenwich.")

    @field_validator("lat")
    @classmethod
    def latitude_within_par(cls, value: float) -> float:
        """Ensure the latitude is inside the Philippine Area of Responsibility."""
        if not MIN_LATITUDE <= value <= MAX_LATITUDE:
            raise ValueError(
                f"Latitude {value} is outside the Philippine Area of "
                f"Responsibility ({MIN_LATITUDE}N to {MAX_LATITUDE}N)."
            )
        return value

    @field_validator("lon")
    @classmethod
    def longitude_within_par(cls, value: float) -> float:
        """Ensure the longitude is inside the Philippine Area of Responsibility."""
        if not MIN_LONGITUDE <= value <= MAX_LONGITUDE:
            raise ValueError(
                f"Longitude {value} is outside the Philippine Area of "
                f"Responsibility ({MIN_LONGITUDE}E to {MAX_LONGITUDE}E)."
            )
        return value


class ForecastPoint(BaseModel):
    """A timestamped forecast position along the storm track."""

    timestamp: datetime = Field(description="Forecast valid time.")
    position: Coordinate = Field(description="Forecast center position.")


class StormBulletin(BaseModel):
    """A parsed PAGASA Severe Weather Bulletin."""

    bulletin_number: int = Field(
        ge=1, description="Sequential bulletin number for the cyclone."
    )
    issued_at: datetime = Field(description="Bulletin issue timestamp.")
    storm_name: str = Field(
        min_length=1, description="International name of the cyclone."
    )
    signal_number: WindSignalNumber = Field(
        description="Current tropical cyclone wind signal number."
    )
    typhoon_category: TyphoonCategory = Field(
        description="Tropical cyclone intensity category."
    )
    current_position: Coordinate = Field(description="Center of the cyclone.")
    movement_speed_kmh: float = Field(
        gt=0, description="Forward speed of the cyclone in km/h."
    )
    movement_direction_deg: float = Field(
        ge=0,
        lt=360,
        description="Forward direction in degrees clockwise from true north.",
    )
    central_pressure_hpa: float = Field(
        gt=0, description="Central atmospheric pressure in hPa."
    )
    max_sustained_winds_kmh: float = Field(
        gt=0, description="Maximum sustained winds in km/h."
    )
    forecast_track: list[ForecastPoint] = Field(
        default_factory=list,
        description="Timestamped forecast positions along the storm track.",
    )

    @property
    def movement_direction_compass(self) -> str:
        """The movement direction as a 16-point compass bearing."""
        points = [
            "N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
            "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW",
        ]
        index = int(((self.movement_direction_deg % 360) + 11.25) // 22.5) % 16
        return points[index]

    @model_validator(mode="after")
    def category_matches_wind_speed(self) -> "StormBulletin":
        """Ensure the typhoon category matches PAGASA wind thresholds."""
        winds = self.max_sustained_winds_kmh
        expected = TyphoonCategory.SUPER_TYPHOON
        if winds < 185:
            expected = TyphoonCategory.TYPHOON
        if winds < 118:
            expected = TyphoonCategory.SEVERE_TROPICAL_STORM
        if winds < 89:
            expected = TyphoonCategory.TROPICAL_STORM
        if winds < 63:
            expected = TyphoonCategory.TROPICAL_DEPRESSION
        if self.typhoon_category != expected:
            raise ValueError(
                f"Typhoon category {self.typhoon_category.value!r} does not match "
                f"max sustained winds of {winds} km/h (expected "
                f"{expected.value!r})."
            )
        return self


# Backwards-compatible alias for earlier consumers.
SevereWeatherBulletin = StormBulletin
