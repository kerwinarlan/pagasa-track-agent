"""Plot PAGASA storm GeoJSON data on an interactive Leaflet map.

The module emulates the official PAGASA Track and Intensity Forecast
layout: a light basemap with the PAR boundary, a mathematically
accurate cone of uncertainty, PAGASA intensity badges (D, S, swirl)
with time callouts along the track, an optional near-real-time IR
satellite layer, and banner and legend overlays. A layer control lets
users toggle between the clean track view and the satellite view.
"""

from __future__ import annotations

import json
import math
from datetime import datetime
from pathlib import Path
from typing import Any

import folium
from folium.plugins import AntPath

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


def _format_number(value: Any) -> str:
    """Format a numeric property for display, trimming trailing .0."""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def get_category_color(wind_speed_kph: int) -> str:
    """Return the PAGASA category color for a wind speed in km/h.

    Categories follow official PAGASA intensity thresholds:
    - Tropical Depression: up to 61 km/h (yellow)
    - Tropical Storm: 62-88 km/h (green)
    - Severe Tropical Storm: 89-117 km/h (orange)
    - Typhoon: 118-184 km/h (red)
    - Super Typhoon: 185 km/h and above (purple)
    """
    if wind_speed_kph <= 61:
        return "#FFD700"
    if wind_speed_kph <= 88:
        return "#008000"
    if wind_speed_kph <= 117:
        return "#FFA500"
    if wind_speed_kph <= 184:
        return "#FF0000"
    return "#800080"


# Legend rows: (badge, wind color, description).
_LEGEND_ENTRIES: list[tuple[str, str, str]] = [
    ("D", "#FFD700", "Tropical Depression (<= 61 km/h)"),
    ("S", "#008000", "Tropical Storm (62-88 km/h)"),
    ("🌀", "#FFA500", "Severe Tropical Storm (89-117 km/h)"),
    ("🌀", "#FF0000", "Typhoon (118-184 km/h)"),
    ("🌀", "#800080", "Super Typhoon (>= 185 km/h)"),
]

# Philippine Area of Responsibility boundary as [lat, lon] vertices.
_PAR_BOUNDARY: list[list[float]] = [
    [25.0, 120.0],
    [25.0, 135.0],
    [5.0, 135.0],
    [5.0, 115.0],
    [15.0, 115.0],
    [21.0, 120.0],
]

# Cone-of-uncertainty geometry. Radii are in kilometers and expand from
# the current position (30 km) up to the farthest forecast (250 km).
_KM_PER_DEGREE: float = 111.19  # approximate km per degree of latitude
_CONE_START_RADIUS_KM: float = 30.0
_CONE_END_RADIUS_KM: float = 250.0
_CONE_CAP_SEGMENTS: int = 24  # segments in the rounded end cap


def _cone_radius_km(progress: float) -> float:
    """Return the cone radius in km at track progress 0..1."""
    return _CONE_START_RADIUS_KM + (
        _CONE_END_RADIUS_KM - _CONE_START_RADIUS_KM
    ) * progress


def get_category_badge(wind_speed_kph: int | None) -> str:
    """Return the PAGASA intensity badge for a wind speed in km/h.

    - 'D' for Tropical Depression (up to 61 km/h)
    - 'S' for Tropical Storm (62-88 km/h)
    - '🌀' for Severe Tropical Storm, Typhoon, and Super Typhoon
    - '?' when the wind speed is unknown
    """
    if wind_speed_kph is None:
        return "?"
    if wind_speed_kph <= 61:
        return "D"
    if wind_speed_kph <= 88:
        return "S"
    return "🌀"


def _format_callout(timestamp: str) -> str:
    """Format an ISO timestamp as a short callout, e.g. '2AM 6 Nov'."""
    try:
        parsed = datetime.fromisoformat(timestamp)
    except (TypeError, ValueError):
        return str(timestamp)
    hour12 = parsed.hour % 12 or 12
    suffix = "AM" if parsed.hour < 12 else "PM"
    return f"{hour12}{suffix} {parsed.day} {parsed.strftime('%b')}"


def _badge_marker_html(badge: str, callout: str) -> str:
    """Return DivIcon HTML: a black circular badge with a time callout."""
    if badge == "🌀":
        size, font_size = 30, 17
    elif len(badge) >= 3:
        size, font_size = 34, 12
    else:
        size, font_size = 24, 15
    return (
        f'<div style="position:relative; width:{size}px; height:{size + 22}px;">'
        f'<div style="position:absolute; top:0; left:50%; transform:translateX(-50%);'
        f' white-space:nowrap; color:#000; font-family:Arial,sans-serif;'
        f' font-size:12px; font-weight:bold;'
        f' text-shadow:0 0 3px #fff, 0 0 3px #fff;">{callout}</div>'
        f'<div style="position:absolute; bottom:0; left:50%; transform:translateX(-50%);'
        f' width:{size}px; height:{size}px; border-radius:50%; background:#000;'
        f' color:#fff; display:flex; align-items:center; justify-content:center;'
        f' font-family:Arial,sans-serif; font-weight:bold;'
        f' font-size:{font_size}px;">{badge}</div>'
        f"</div>"
    )


def _add_par_boundary(map_obj: folium.Map) -> None:
    """Draw the Philippine Area of Responsibility boundary polygon."""
    folium.Polygon(
        locations=_PAR_BOUNDARY,
        color="#808080",
        weight=1.5,
        dash_array="5, 5",
        fill=False,
        tooltip="Philippine Area of Responsibility (PAR)",
    ).add_to(map_obj)


def _build_cone_envelope(
    center: dict[str, Any],
    forecast_points: list[dict[str, Any]],
) -> list[list[float]]:
    """Return a [lat, lon] polygon envelope around the forecast track.

    The envelope is the tangent buffer of the track: each waypoint is
    offset left and right by an expanding radius perpendicular to the
    path, and a rounded semicircular cap closes the polygon around the
    final waypoint.
    """
    features = [center] + forecast_points
    coords = [feature["geometry"]["coordinates"] for feature in features]
    if len(coords) < 2:
        return []

    # Cumulative along-track distance drives the radius interpolation.
    cumulative = [0.0]
    for start, end in zip(coords, coords[1:]):
        cumulative.append(
            cumulative[-1]
            + math.hypot(end[0] - start[0], end[1] - start[1])
        )
    total = cumulative[-1] or 1.0

    left_side: list[list[float]] = []
    right_side: list[list[float]] = []
    count = len(coords)
    for index, (lon, lat) in enumerate(coords):
        if index < count - 1:
            dx = coords[index + 1][0] - lon
            dy = coords[index + 1][1] - lat
        else:
            dx = lon - coords[index - 1][0]
            dy = lat - coords[index - 1][1]
        length = math.hypot(dx, dy)
        px = -dy / length if length else 0.0
        py = dx / length if length else 0.0
        radius = _cone_radius_km(cumulative[index] / total) / _KM_PER_DEGREE
        left_side.append([lat + py * radius, lon + px * radius])
        right_side.append([lat - py * radius, lon - px * radius])

    # Rounded cap around the final waypoint: a semicircle bulging ahead
    # of the track, from the last left offset to the last right offset.
    end_lon, end_lat = coords[-1]
    end_radius = _cone_radius_km(1.0) / _KM_PER_DEGREE
    if count > 1:
        fdx = coords[-1][0] - coords[-2][0]
        fdy = coords[-1][1] - coords[-2][1]
        forward_length = math.hypot(fdx, fdy)
        fdx /= forward_length or 1.0
        fdy /= forward_length or 1.0
    else:
        fdx, fdy = 0.0, 1.0
    cap: list[list[float]] = []
    for step in range(_CONE_CAP_SEGMENTS + 1):
        theta = math.pi / 2 - math.pi * step / _CONE_CAP_SEGMENTS
        cap.append(
            [
                end_lat + end_radius
                * (math.cos(theta) * fdy + math.sin(theta) * py),
                end_lon + end_radius
                * (math.cos(theta) * fdx + math.sin(theta) * px),
            ]
        )

    ring = left_side[:-1] + cap + list(reversed(right_side))[1:]
    ring.append(ring[0])
    return ring


def _add_cone(
    map_obj: folium.Map,
    center: dict[str, Any],
    forecast_points: list[dict[str, Any]],
) -> None:
    """Draw the cone-of-uncertainty envelope around the forecast track."""
    envelope = _build_cone_envelope(center, forecast_points)
    if not envelope:
        return
    folium.Polygon(
        locations=envelope,
        color="#555555",
        weight=1,
        fill=True,
        fill_color="#cccccc",
        fill_opacity=0.3,
        tooltip="Cone of uncertainty",
    ).add_to(map_obj)


def _ui_overlay_html(storm_name: str) -> str:
    """Return the top banner and bottom-left legend overlay HTML."""
    legend_rows = "".join(
        f'<div style="display:flex; align-items:center; gap:6px; margin:3px 0;">'
        f'<span style="width:14px; height:14px; border-radius:50%;'
        f' background:{color}; display:inline-block;"></span>'
        f'<span style="width:22px; height:22px; border-radius:50%; background:#000;'
        f' color:#fff; font-weight:bold; font-size:13px; display:flex;'
        f' align-items:center; justify-content:center;">{badge}</span>'
        f'<span style="color:#222;">{label}</span></div>'
        for badge, color, label in _LEGEND_ENTRIES
    )
    return f"""
<div id="pagasa-ui-overlay">
  <div id="pagasa-banner">Track and Intensity Forecast of {storm_name}</div>
  <div id="pagasa-legend">
    <div style="font-weight:bold; margin-bottom:4px;">Intensity Legend</div>
    {legend_rows}
  </div>
  <button id="pagasa-about-btn" title="About this map">About</button>
  <div id="pagasa-about" hidden>
    <button id="pagasa-about-close" aria-label="Close">&times;</button>
    <h3>About this map</h3>
    <p>Track and intensity forecast of a tropical cyclone, generated by
    <b>PAGASA Track Agent</b>, an automated pipeline that parses official
    PAGASA Severe Weather Bulletins into a structured storm track.</p>
    <p>Source: PAGASA-DOST. This map is for visualization only and is
    not an official forecast.</p>
  </div>
</div>
<style>
  #pagasa-banner {{
    position:absolute; top:12px; left:50%; transform:translateX(-50%);
    background:#000; color:#fff; font-family:Arial,sans-serif;
    font-size:15px; font-weight:bold; padding:8px 18px; border-radius:20px;
    z-index:1000; box-shadow:0 2px 6px rgba(0,0,0,0.4);
  }}
  #pagasa-legend {{
    position:absolute; left:12px; bottom:14px; background:#fff;
    font-family:Arial,sans-serif; font-size:11px; padding:8px 10px;
    border:1px solid #ccc; border-radius:6px; z-index:1000;
    box-shadow:0 2px 6px rgba(0,0,0,0.25);
  }}
  #pagasa-about-btn {{
    position:absolute; top:12px; right:12px; background:#000; color:#fff;
    font-family:Arial,sans-serif; font-size:12px; font-weight:bold;
    padding:6px 14px; border:none; border-radius:14px; cursor:pointer;
    z-index:1000; box-shadow:0 2px 6px rgba(0,0,0,0.4);
  }}
  #pagasa-about {{
    position:absolute; top:46px; right:12px; width:260px; background:#fff;
    font-family:Arial,sans-serif; font-size:12px; line-height:1.5;
    color:#222; padding:14px 16px; border:1px solid #ccc; border-radius:8px;
    z-index:1000; box-shadow:0 2px 8px rgba(0,0,0,0.3);
  }}
  #pagasa-about h3 {{ margin:0 0 8px; font-size:14px; }}
  #pagasa-about p {{ margin:0 0 8px; }}
  #pagasa-about-close {{
    position:absolute; top:6px; right:10px; border:none; background:none;
    font-size:16px; cursor:pointer; color:#888;
  }}
</style>
<script>
  (function () {{
    var btn = document.getElementById("pagasa-about-btn");
    var panel = document.getElementById("pagasa-about");
    btn.addEventListener("click", function () {{
      panel.hidden = !panel.hidden;
    }});
    document.getElementById("pagasa-about-close")
      .addEventListener("click", function () {{ panel.hidden = true; }});
  }})();
</script>
"""


def _add_ui_overlay(map_obj: folium.Map, storm_name: str) -> None:
    """Inject the PAGASA banner and legend overlays."""
    map_obj.get_root().html.add_child(
        folium.Element(_ui_overlay_html(storm_name))
    )


def _add_badge_marker(
    map_obj: folium.Map,
    lat: float,
    lon: float,
    badge: str,
    callout: str,
    popup_html: str,
    tooltip: str,
) -> None:
    """Add a PAGASA DivIcon badge marker with a callout and popup."""
    size = 30 if badge == "🌀" else (34 if len(badge) >= 3 else 24)
    folium.Marker(
        location=[lat, lon],
        popup=folium.Popup(popup_html, max_width=300),
        tooltip=tooltip,
        icon=folium.DivIcon(
            html=_badge_marker_html(badge, callout),
            icon_size=(size, size + 22),
            icon_anchor=(size // 2, 22 + size // 2),
            class_name="",
        ),
    ).add_to(map_obj)


def _add_center_marker(map_obj: folium.Map, feature: dict[str, Any]) -> None:
    """Add the current position with a PAGASA intensity badge."""
    lon, lat = feature["geometry"]["coordinates"]
    props = feature["properties"]
    max_wind_kph = props.get("max_wind_kph")
    wind_speed_kph = int(max_wind_kph) if max_wind_kph is not None else None
    popup_html = (
        f"<b>{props['storm_name']}</b><br>"
        f"Category: {props.get('typhoon_category', 'N/A')}<br>"
        f"Signal: #{props.get('signal_number', 'N/A')}<br>"
        f"Max winds: "
        f"{_format_number(max_wind_kph) if max_wind_kph is not None else 'N/A'}"
        f" km/h<br>"
        f"Pressure: {_format_number(props.get('pressure', 'N/A'))} hPa<br>"
        f"Issued: {props.get('issued_at', 'N/A')}"
    )
    badge = get_category_badge(wind_speed_kph)
    callout = _format_callout(props.get("issued_at", ""))
    _add_badge_marker(
        map_obj,
        lat,
        lon,
        badge,
        callout,
        popup_html,
        tooltip=props["storm_name"],
    )


def _add_forecast_markers(
    map_obj: folium.Map, forecast_points: list[dict[str, Any]]
) -> None:
    """Add PAGASA intensity badges with time callouts at forecast points."""
    for feature in forecast_points:
        lon, lat = feature["geometry"]["coordinates"]
        props = feature["properties"]
        raw_wind = props.get("wind_speed_kph")
        wind_speed_kph = int(raw_wind) if raw_wind is not None else None
        popup_html = (
            f"Forecast #{props.get('index', '?')}<br>"
            f"Time: {props.get('timestamp', 'N/A')}<br>"
            f"Max winds: "
            f"{_format_number(raw_wind) if raw_wind is not None else 'N/A'}"
            f" km/h"
        )
        badge = get_category_badge(wind_speed_kph)
        callout = _format_callout(props.get("timestamp", ""))
        _add_badge_marker(
            map_obj,
            lat,
            lon,
            badge,
            callout,
            popup_html,
            tooltip="Forecast position",
        )


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


# Near-real-time IR satellite imagery from NASA GIBS. The layer uses the
# MODIS Aqua thermal band 31 (brightness temperature), which shows cloud
# tops the way PAGASA's Pic 3 satellite view does. The WMTS date is
# filled in at render time so the map always points at the latest data.
_SATELLITE_TILE_BASE: str = (
    "https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/"
    "MODIS_Aqua_Brightness_Temp_Band31_Day/default"
)


def _satellite_tile_url() -> str:
    """Return the GIBS IR satellite tile URL for the current date."""
    date = datetime.now().strftime("%Y-%m-%d")
    return (
        f"{_SATELLITE_TILE_BASE}/{date}/GoogleMapsCompatible_Level7/"
        "{{z}}/{{y}}/{{x}}.png"
    )


def _add_satellite_layer(map_obj: folium.Map) -> None:
    """Add the optional IR satellite tile layer for the layer control."""
    folium.TileLayer(
        tiles=_satellite_tile_url(),
        name="IR Satellite (MODIS Aqua)",
        attr="Imagery &copy; NASA GIBS",
        min_zoom=4,
        max_zoom=9,
    ).add_to(map_obj)


def render_map(geojson_path: str, output_html_path: str) -> folium.Map:
    """Render the storm GeoJSON to an interactive Leaflet HTML map."""
    collection = _load_geojson(geojson_path)
    center, forecast_points, track = _split_features(collection)

    center_lon, center_lat = center["geometry"]["coordinates"]
    map_obj = folium.Map(
        location=[center_lat, center_lon],
        zoom_start=6,
        tiles="CartoDB positron",
    )

    _add_par_boundary(map_obj)
    _add_cone(map_obj, center, forecast_points)
    _add_track_line(map_obj, track)
    _add_center_marker(map_obj, center)
    _add_forecast_markers(map_obj, forecast_points)
    _add_satellite_layer(map_obj)
    _add_ui_overlay(map_obj, center["properties"]["storm_name"])
    folium.LayerControl().add_to(map_obj)

    map_obj.save(output_html_path)
    return map_obj


def main() -> None:
    """Render the sample storm track to an interactive HTML map."""
    render_map(str(DEFAULT_GEOJSON_PATH), str(DEFAULT_HTML_PATH))
    print(f"Saved storm map to {DEFAULT_HTML_PATH}")


if __name__ == "__main__":
    main()
