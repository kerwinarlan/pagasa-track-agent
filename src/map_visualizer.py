"""Plot PAGASA storm GeoJSON data on an interactive Leaflet map.

The module uses Folium to render radar rings and a pulsing radar-wave
icon for the storm center, circle markers for forecast positions, and
an animated dashed line for the storm track.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import folium
from folium.plugins import AntPath

_PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent
DEFAULT_GEOJSON_PATH: Path = _PROJECT_ROOT / "data" / "output" / "storm_track.geojson"
DEFAULT_HTML_PATH: Path = _PROJECT_ROOT / "data" / "output" / "storm_map.html"

# Multi-tiered wind/radar radii around the storm center, in meters.
# Each entry is (radius_m, color, fill_opacity, label).
_RADAR_RINGS: list[tuple[float, str, float, str]] = [
    (40000, "#FF0000", 0.4, "Eye Wall / Severe Core"),
    (100000, "#FF8C00", 0.25, "Storm-Force Winds"),
    (200000, "#FFD700", 0.15, "Gale-Force Winds"),
]

# A pulsing radar-wave marker for the storm center. The SVG shows a solid
# dot with four expanding rings that fade out in sequence, like a radar
# ping. The animation is defined inline so the marker works standalone.
_RADAR_ICON_HTML: str = """
<div style="width: 48px; height: 48px;">
  <style>
    @keyframes radar-ping {
      0% { transform: scale(0.3); opacity: 1; }
      100% { transform: scale(1.5); opacity: 0; }
    }
    .radar-ping {
      transform-origin: center;
      transform-box: fill-box;
      animation: radar-ping 2s ease-out infinite;
    }
    .radar-ping-2 { animation-delay: 0.5s; }
    .radar-ping-3 { animation-delay: 1s; }
    .radar-ping-4 { animation-delay: 1.5s; }
  </style>
  <svg viewBox="0 0 48 48" width="48" height="48">
    <circle class="radar-ping" cx="24" cy="24" r="9" fill="none"
            stroke="#00FF88" stroke-width="2"/>
    <circle class="radar-ping radar-ping-2" cx="24" cy="24" r="9"
            fill="none" stroke="#00FF88" stroke-width="2"/>
    <circle class="radar-ping radar-ping-3" cx="24" cy="24" r="9"
            fill="none" stroke="#00FF88" stroke-width="2"/>
    <circle class="radar-ping radar-ping-4" cx="24" cy="24" r="9"
            fill="none" stroke="#00FF88" stroke-width="2"/>
    <circle cx="24" cy="24" r="4.5" fill="#00FF88"/>
  </svg>
</div>
"""


def _load_geojson(geojson_path: str) -> dict[str, Any]:
    """Load and return the GeoJSON FeatureCollection."""
    with open(geojson_path, encoding="utf-8") as file:
        return json.load(file)


def _split_features(
    collection: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any] | None]:
    """Split features into current center, forecast points, and track."""
    features = collection.get("features", [])
    if not features:
        raise ValueError("GeoJSON FeatureCollection contains no features.")
    center = features[0]
    forecast_points = [
        feature
        for feature in features
        if feature["geometry"]["type"] == "Point"
    ][1:]
    track = next(
        (
            feature
            for feature in features
            if feature["geometry"]["type"] == "LineString"
        ),
        None,
    )
    return center, forecast_points, track


def _format_number(value: Any) -> str:
    """Format a numeric property for display, trimming trailing .0."""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _add_radar_rings(
    map_obj: folium.Map, feature: dict[str, Any]
) -> None:
    """Draw wind/radar radius rings around the current storm center."""
    lon, lat = feature["geometry"]["coordinates"]
    for radius, color, fill_opacity, label in _RADAR_RINGS:
        folium.Circle(
            location=[lat, lon],
            radius=radius,
            color=color,
            weight=1,
            fill=True,
            fill_color=color,
            fill_opacity=fill_opacity,
            tooltip=f"{label} ({radius // 1000} km)",
        ).add_to(map_obj)


def _add_center_marker(map_obj: folium.Map, feature: dict[str, Any]) -> None:
    """Add a marker with a pulsing radar-wave icon for the storm center."""
    lon, lat = feature["geometry"]["coordinates"]
    props = feature["properties"]
    popup_html = (
        f"<b>{props['storm_name']}</b><br>"
        f"Category: {props.get('typhoon_category', 'N/A')}<br>"
        f"Signal: #{props.get('signal_number', 'N/A')}<br>"
        f"Max winds: {_format_number(props.get('max_wind_kph', 'N/A'))} km/h<br>"
        f"Pressure: {_format_number(props.get('pressure', 'N/A'))} hPa<br>"
        f"Issued: {props.get('issued_at', 'N/A')}"
    )
    folium.Marker(
        location=[lat, lon],
        popup=folium.Popup(popup_html, max_width=300),
        tooltip=props["storm_name"],
        icon=folium.DivIcon(
            html=_RADAR_ICON_HTML,
            icon_size=(48, 48),
            icon_anchor=(24, 24),
        ),
    ).add_to(map_obj)


def _add_forecast_markers(
    map_obj: folium.Map, forecast_points: list[dict[str, Any]]
) -> None:
    """Add a circle marker for each forecast position."""
    for feature in forecast_points:
        lon, lat = feature["geometry"]["coordinates"]
        props = feature["properties"]
        popup_html = (
            f"Forecast #{props.get('index', '?')}<br>"
            f"Time: {props.get('timestamp', 'N/A')}"
        )
        folium.CircleMarker(
            location=[lat, lon],
            radius=6,
            color="orange",
            fill=True,
            fill_opacity=0.8,
            popup=folium.Popup(popup_html, max_width=300),
            tooltip="Forecast position",
        ).add_to(map_obj)


def _add_track_line(
    map_obj: folium.Map, track: dict[str, Any] | None
) -> None:
    """Draw the storm track as an animated ant path line."""
    if track is None:
        return
    # GeoJSON coordinates are [lon, lat]; Folium expects [lat, lon].
    coordinates = [
        [lat, lon]
        for lon, lat in track["geometry"]["coordinates"]
    ]
    AntPath(
        locations=coordinates,
        delay=1000,
        dash_array=[10, 20],
        color="blue",
        weight=3,
        tooltip="Storm track",
    ).add_to(map_obj)


def render_map(geojson_path: str, output_html_path: str) -> folium.Map:
    """Render the storm GeoJSON to an interactive Leaflet HTML map."""
    collection = _load_geojson(geojson_path)
    center, forecast_points, track = _split_features(collection)

    center_lon, center_lat = center["geometry"]["coordinates"]
    map_obj = folium.Map(location=[center_lat, center_lon], zoom_start=6)

    _add_radar_rings(map_obj, center)
    _add_center_marker(map_obj, center)
    _add_forecast_markers(map_obj, forecast_points)
    _add_track_line(map_obj, track)

    map_obj.save(output_html_path)
    return map_obj


def main() -> None:
    """Render the sample storm track to an interactive HTML map."""
    render_map(str(DEFAULT_GEOJSON_PATH), str(DEFAULT_HTML_PATH))
    print(f"Saved storm map to {DEFAULT_HTML_PATH}")


if __name__ == "__main__":
    main()
