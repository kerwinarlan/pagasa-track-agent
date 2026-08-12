"""Tests for the map visualizer."""

import json

import pytest

from src.map_visualizer import (
    DEFAULT_HTML_PATH,
    _badge_marker_html,
    _build_cone_envelope,
    _cone_radius_km,
    get_category_badge,
    get_category_color,
    render_map,
)


@pytest.fixture
def storm_geojson(tmp_path) -> str:
    """Write a deterministic storm GeoJSON fixture and return its path."""
    collection = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [124.8, 15.2]},
                "properties": {
                    "storm_name": "SAMPLE",
                    "max_wind_kph": 195.0,
                    "pressure": 915.0,
                    "issued_at": "2024-11-17T05:00:00",
                    "signal_number": 4,
                    "typhoon_category": "Super Typhoon",
                },
            },
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [123.6, 15.8]},
                "properties": {
                    "index": 0,
                    "timestamp": "2024-11-18T05:00:00",
                    "wind_speed_kph": 75,
                },
            },
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [122.2, 16.4]},
                "properties": {
                    "index": 1,
                    "timestamp": "2024-11-19T05:00:00",
                    "wind_speed_kph": 200,
                },
            },
            {
                "type": "Feature",
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[124.8, 15.2], [123.6, 15.8], [122.2, 16.4]],
                },
                "properties": {"storm_name": "SAMPLE", "feature": "storm_track"},
            },
        ],
    }
    path = tmp_path / "storm_track.geojson"
    path.write_text(json.dumps(collection), encoding="utf-8")
    return str(path)


def _load_collection(geojson_path: str) -> dict:
    """Load the fixture GeoJSON collection from disk."""
    with open(geojson_path, encoding="utf-8") as file:
        return json.load(file)


def _point_in_polygon(lat: float, lon: float, polygon: list[list[float]]) -> bool:
    """Return True if (lat, lon) lies inside the [lat, lon] polygon."""
    inside = False
    count = len(polygon)
    previous = count - 1
    for index in range(count):
        lat1, lon1 = polygon[index]
        lat2, lon2 = polygon[previous]
        if (lat1 > lat) != (lat2 > lat):
            x_intersect = (lon2 - lon1) * (lat - lat1) / (lat2 - lat1) + lon1
            if lon < x_intersect:
                inside = not inside
        previous = index
    return inside


def _distance(a: tuple[float, float], b: list[float]) -> float:
    """Return the planar distance between two [lat, lon] points."""
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5


def _distance_to_segment(
    lat: float, lon: float, a: list[float], b: list[float]
) -> float:
    """Return the distance from (lat, lon) to the segment a-b."""
    ax, ay = a[1], a[0]
    bx, by = b[1], b[0]
    dx, dy = bx - ax, by - ay
    length_sq = dx * dx + dy * dy
    if length_sq == 0:
        return _distance((lat, lon), a)
    t = max(0.0, min(1.0, ((lon - ax) * dx + (lat - ay) * dy) / length_sq))
    px, py = ax + t * dx, ay + t * dy
    return ((lon - px) ** 2 + (lat - py) ** 2) ** 0.5


def _point_in_or_on_polygon(
    lat: float, lon: float, polygon: list[list[float]], tolerance: float = 1e-9
) -> bool:
    """Return True if (lat, lon) is inside or on the [lat, lon] polygon."""
    if _point_in_polygon(lat, lon, polygon):
        return True
    count = len(polygon)
    for index in range(count):
        segment_start = polygon[index]
        segment_end = polygon[(index + 1) % count]
        if _distance_to_segment(lat, lon, segment_start, segment_end) <= tolerance:
            return True
    return False


class TestGetCategoryColor:
    @pytest.mark.parametrize(
        "wind_speed_kph, expected",
        [
            (0, "#FFD700"),  # Tropical Depression
            (61, "#FFD700"),  # Upper boundary of Tropical Depression
            (62, "#008000"),  # Lower boundary of Tropical Storm
            (88, "#008000"),  # Upper boundary of Tropical Storm
            (89, "#FFA500"),  # Lower boundary of Severe Tropical Storm
            (117, "#FFA500"),  # Upper boundary of Severe Tropical Storm
            (118, "#FF0000"),  # Lower boundary of Typhoon
            (184, "#FF0000"),  # Upper boundary of Typhoon
            (185, "#800080"),  # Lower boundary of Super Typhoon
            (300, "#800080"),  # Super Typhoon
        ],
    )
    def test_boundaries_map_to_pagasa_colors(self, wind_speed_kph, expected):
        assert get_category_color(wind_speed_kph) == expected


class TestBasemapAndPar:
    def test_uses_cartodb_positron_tiles(self, storm_geojson, tmp_path):
        output = tmp_path / "storm_map.html"
        render_map(storm_geojson, str(output))
        html = output.read_text(encoding="utf-8")

        assert "basemaps.cartocdn.com" in html
        assert "light_all" in html

    def test_par_boundary_is_dashed_gray_polygon(self, storm_geojson, tmp_path):
        output = tmp_path / "storm_map.html"
        render_map(storm_geojson, str(output))
        html = output.read_text(encoding="utf-8")

        assert '"color": "#808080"' in html
        assert '"dashArray": "5, 5"' in html
        assert '"fill": false' in html
        # PAR vertices: 25N 120E, 25N 135E, 5N 135E, 5N 115E, 15N 115E, 21N 120E.
        assert (
            "[[25.0, 120.0], [25.0, 135.0], [5.0, 135.0],"
            " [5.0, 115.0], [15.0, 115.0], [21.0, 120.0]]" in html
        )


class TestConeOfUncertainty:
    def test_cone_polygon_rendered_with_style(self, storm_geojson, tmp_path):
        output = tmp_path / "storm_map.html"
        render_map(storm_geojson, str(output))
        html = output.read_text(encoding="utf-8")

        assert '"color": "#555555"' in html
        assert '"fillColor": "#cccccc"' in html
        assert '"fill": true' in html
        assert '"fillOpacity": 0.3' in html

    def test_envelope_contains_all_waypoints(self, storm_geojson):
        collection = _load_collection(storm_geojson)
        center = collection["features"][0]
        forecast_points = collection["features"][1:-1]
        envelope = _build_cone_envelope(center, forecast_points)

        assert envelope[0] == envelope[-1]  # closed ring
        for feature in [center] + forecast_points:
            lon, lat = feature["geometry"]["coordinates"]
            assert _point_in_or_on_polygon(lat, lon, envelope)

    def test_radius_expands_with_progress(self):
        assert _cone_radius_km(0.0) == pytest.approx(30.0)
        assert _cone_radius_km(0.5) == pytest.approx(140.0)
        assert _cone_radius_km(1.0) == pytest.approx(250.0)


class TestCategoryBadges:
    @pytest.mark.parametrize(
        "wind_speed_kph, expected",
        [
            (0, "D"),  # Tropical Depression
            (61, "D"),  # Upper boundary of Tropical Depression
            (62, "S"),  # Lower boundary of Tropical Storm
            (88, "S"),  # Upper boundary of Tropical Storm
            (89, "🌀"),  # Severe Tropical Storm and above
            (117, "🌀"),
            (118, "🌀"),
            (185, "🌀"),
            (300, "🌀"),
            (None, "?"),  # unknown wind speed
        ],
    )
    def test_badge_for_wind_speed(self, wind_speed_kph, expected):
        assert get_category_badge(wind_speed_kph) == expected

    def test_badge_html_is_black_circle_with_callout(self):
        html = _badge_marker_html("🌀", "2AM 6 Nov")

        assert ">🌀</div>" in html
        assert "2AM 6 Nov" in html
        assert "border-radius:50%" in html
        assert "background:#000" in html

    def test_badges_and_callouts_rendered_on_map(self, storm_geojson, tmp_path):
        output = tmp_path / "storm_map.html"
        render_map(storm_geojson, str(output))
        html = output.read_text(encoding="utf-8")

        # Marker DivIcon html is JSON-escaped inside the map script.
        # 75 km/h -> Tropical Storm 'S'; 200 km/h -> swirl (STS and up).
        assert "\\u003eS\\u003c/div\\u003e" in html
        assert "\\u003e\\ud83c\\udf00\\u003c/div\\u003e" in html
        # Static date/time callouts above the center and forecast markers.
        assert "5AM 17 Nov" in html
        assert "5AM 18 Nov" in html
        assert "5AM 19 Nov" in html


class TestUiOverlay:
    def test_banner_with_storm_name(self, storm_geojson, tmp_path):
        output = tmp_path / "storm_map.html"
        render_map(storm_geojson, str(output))
        html = output.read_text(encoding="utf-8")

        assert "Track and Intensity Forecast of SAMPLE" in html
        assert 'id="pagasa-banner"' in html

    def test_legend_explains_badges_and_colors(self, storm_geojson, tmp_path):
        output = tmp_path / "storm_map.html"
        render_map(storm_geojson, str(output))
        html = output.read_text(encoding="utf-8")

        assert 'id="pagasa-legend"' in html
        assert "Intensity Legend" in html
        for name in (
            "Tropical Depression",
            "Tropical Storm",
            "Severe Tropical Storm",
            "Typhoon",
            "Super Typhoon",
        ):
            assert name in html
        for color in ("#FFD700", "#008000", "#FFA500", "#FF0000", "#800080"):
            assert color in html

    def test_about_button_and_panel(self, storm_geojson, tmp_path):
        output = tmp_path / "storm_map.html"
        render_map(storm_geojson, str(output))
        html = output.read_text(encoding="utf-8")

        assert 'id="pagasa-about-btn"' in html
        assert 'id="pagasa-about"' in html
        assert "PAGASA Track Agent" in html
        assert "not an official forecast" in html


class TestRenderMap:
    def test_creates_html_file(self, storm_geojson, tmp_path):
        output = tmp_path / "storm_map.html"
        render_map(storm_geojson, str(output))
        assert output.exists()
        assert output.stat().st_size > 0

    def test_html_contains_leaflet_map(self, storm_geojson, tmp_path):
        output = tmp_path / "storm_map.html"
        render_map(storm_geojson, str(output))
        html = output.read_text(encoding="utf-8")
        assert "L.map(" in html

    def test_marker_counts(self, storm_geojson, tmp_path):
        output = tmp_path / "storm_map.html"
        render_map(storm_geojson, str(output))
        html = output.read_text(encoding="utf-8")

        assert html.count("L.marker(") == 3  # center + 2 forecast badges
        assert html.count("L.divIcon(") == 3  # PAGASA badges only
        assert html.count("L.circle(") == 0  # radar rings removed
        assert html.count("L.circleMarker(") == 0  # badges replace dots
        assert html.count("L.polygon(") == 2  # PAR boundary + cone
        assert html.count("L.polyline.antPath(") == 1  # storm track

    def test_track_is_animated_ant_path(self, storm_geojson, tmp_path):
        output = tmp_path / "storm_map.html"
        render_map(storm_geojson, str(output))
        html = output.read_text(encoding="utf-8")

        assert "L.polyline.antPath(" in html
        assert '"delay": 1000' in html
        assert '"dashArray": [' in html

    def test_current_center_popup_has_storm_data(self, storm_geojson, tmp_path):
        output = tmp_path / "storm_map.html"
        render_map(storm_geojson, str(output))
        html = output.read_text(encoding="utf-8")

        assert "SAMPLE" in html
        assert "Max winds: 195 km/h" in html
        assert "Pressure: 915 hPa" in html

    def test_map_centered_on_current_position(self, storm_geojson, tmp_path):
        output = tmp_path / "storm_map.html"
        render_map(storm_geojson, str(output))
        html = output.read_text(encoding="utf-8")

        # Folium serializes the center as center: [lat, lon].
        assert "center: [15.2, 124.8]" in html

    def test_center_uses_pagasa_badge(self, storm_geojson, tmp_path):
        output = tmp_path / "storm_map.html"
        render_map(storm_geojson, str(output))
        html = output.read_text(encoding="utf-8")

        # Center is a Super Typhoon (195 km/h) -> swirl badge.
        assert "\\u003e\\ud83c\\udf00\\u003c/div\\u003e" in html
        # Center callout from its issued time.
        assert "5AM 17 Nov" in html

    def test_forecast_markers_use_pagasa_badges(self, storm_geojson, tmp_path):
        output = tmp_path / "storm_map.html"
        render_map(storm_geojson, str(output))
        html = output.read_text(encoding="utf-8")

        # Forecast 75 km/h -> Tropical Storm 'S'; 200 km/h -> swirl.
        assert "\\u003eS\\u003c/div\\u003e" in html
        assert "\\u003e\\ud83c\\udf00\\u003c/div\\u003e" in html

    def test_forecast_popup_shows_wind_speed(self, storm_geojson, tmp_path):
        output = tmp_path / "storm_map.html"
        render_map(storm_geojson, str(output))
        html = output.read_text(encoding="utf-8")

        assert "Forecast #0" in html
        assert "Max winds: 75 km/h" in html
        assert "Forecast #1" in html
        assert "Max winds: 200 km/h" in html

    def test_no_radar_or_cloud_overlay(self, storm_geojson, tmp_path):
        output = tmp_path / "storm_map.html"
        render_map(storm_geojson, str(output))
        html = output.read_text(encoding="utf-8")

        assert "radar-ping" not in html
        assert "storm-cloud-layer" not in html
        assert "storm-timeline-slider" not in html

    def test_satellite_layer_present(self, storm_geojson, tmp_path):
        output = tmp_path / "storm_map.html"
        render_map(storm_geojson, str(output))
        html = output.read_text(encoding="utf-8")

        assert "gibs.earthdata.nasa.gov" in html
        assert "MODIS_Aqua_Brightness_Temp_Band31_Day" in html
        assert "IR Satellite" in html

    def test_layer_control_present(self, storm_geojson, tmp_path):
        output = tmp_path / "storm_map.html"
        render_map(storm_geojson, str(output))
        html = output.read_text(encoding="utf-8")

        assert "L.control.layers(" in html

    def test_missing_features_raises(self, tmp_path):
        empty = tmp_path / "empty.geojson"
        empty.write_text(json.dumps({"type": "FeatureCollection", "features": []}))
        output = tmp_path / "storm_map.html"

        with pytest.raises(ValueError, match="no features"):
            render_map(str(empty), str(output))

    def test_default_html_path_is_under_data_output(self):
        assert DEFAULT_HTML_PATH.name == "storm_map.html"
        assert "output" in DEFAULT_HTML_PATH.parts
