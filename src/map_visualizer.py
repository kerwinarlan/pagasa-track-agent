"""Plot PAGASA storm GeoJSON data on an interactive Leaflet map.

The module uses Folium to render markers for the current and forecast
storm positions plus a dashed line for the storm track.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import folium

_PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent
DEFAULT_GEOJSON_PATH: Path = _PROJECT_ROOT / "data" / "output" / "storm_track.geojson"
DEFAULT_HTML_PATH: Path = _PROJECT_ROOT / "data" / "output" / "storm_map.html"


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


def _add_center_marker(map_obj: folium.Map, feature: dict[str, Any]) -> None:
    """Add a marker for the current storm center."""
    lon, lat = feature["geometry"]["coordinates"]
    props = feature["properties"]
    popup_html = (
        f"<b>{props['storm_name']}</b><br>"
        f"Category: {props.get('typhoon_category', 'N/A')}<br>"
        f"Signal: #{props.get('signal_number', 'N/A')}<br>"
        f"Max winds: {props.get('max_wind_kph', 'N/A')} km/h<br>"
        f"Pressure: {props.get('pressure', 'N/A')} hPa<br>"
        f"Issued: {props.get('issued_at', 'N/A')}"
    )
    folium.Marker(
        location=[lat, lon],
        popup=folium.Popup(popup_html, max_width=300),
        tooltip=props["storm_name"],
        icon=folium.Icon(color="red", icon="cloud"),
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
    """Draw the storm track as a dashed polyline."""
    if track is None:
        return
    # GeoJSON coordinates are [lon, lat]; Folium expects [lat, lon].
    coordinates = [
        [lat, lon]
        for lon, lat in track["geometry"]["coordinates"]
    ]
    folium.PolyLine(
        locations=coordinates,
        color="blue",
        weight=3,
        dash_array="5, 5",
        tooltip="Storm track",
    ).add_to(map_obj)


def render_map(geojson_path: str, output_html_path: str) -> folium.Map:
    """Render the storm GeoJSON to an interactive Leaflet HTML map."""
    collection = _load_geojson(geojson_path)
    center, forecast_points, track = _split_features(collection)

    center_lon, center_lat = center["geometry"]["coordinates"]
    map_obj = folium.Map(location=[center_lat, center_lon], zoom_start=6)

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
