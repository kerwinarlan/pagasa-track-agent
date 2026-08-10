"""Tests for the map visualizer."""

import json

import pytest

from src.map_visualizer import DEFAULT_HTML_PATH, render_map


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
                "properties": {"index": 0, "timestamp": "2024-11-18T05:00:00"},
            },
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [122.2, 16.4]},
                "properties": {"index": 1, "timestamp": "2024-11-19T05:00:00"},
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

        assert html.count("L.marker(") == 1  # current center
        assert html.count("L.divIcon(") == 1  # pulsing radar icon
        assert html.count("L.circle(") == 3  # radar radius rings
        assert html.count("L.circleMarker(") == 2  # forecast points
        assert html.count("L.polyline.antPath(") == 1  # storm track

    def test_radar_rings(self, storm_geojson, tmp_path):
        output = tmp_path / "storm_map.html"
        render_map(storm_geojson, str(output))
        html = output.read_text(encoding="utf-8")

        # Eye Wall / Severe Core: 40 km, red, 0.4 fill.
        assert '"radius": 40000' in html
        assert '"color": "#FF0000"' in html
        assert '"fillOpacity": 0.4' in html
        # Storm-Force Winds: 100 km, orange, 0.25 fill.
        assert '"radius": 100000' in html
        assert '"color": "#FF8C00"' in html
        assert '"fillOpacity": 0.25' in html
        # Gale-Force Winds: 200 km, yellow, 0.15 fill.
        assert '"radius": 200000' in html
        assert '"color": "#FFD700"' in html
        assert '"fillOpacity": 0.15' in html

    def test_center_icon_is_pulsing_radar_wave(self, storm_geojson, tmp_path):
        output = tmp_path / "storm_map.html"
        render_map(storm_geojson, str(output))
        html = output.read_text(encoding="utf-8")

        assert "@keyframes radar-ping" in html
        assert "animation: radar-ping 2s ease-out infinite" in html
        assert "00FF88" in html  # radar ring stroke color
        assert html.count("L.divIcon(") == 1

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

    def test_missing_features_raises(self, tmp_path):
        empty = tmp_path / "empty.geojson"
        empty.write_text(json.dumps({"type": "FeatureCollection", "features": []}))
        output = tmp_path / "storm_map.html"

        with pytest.raises(ValueError, match="no features"):
            render_map(str(empty), str(output))

    def test_default_html_path_is_under_data_output(self):
        assert DEFAULT_HTML_PATH.name == "storm_map.html"
        assert "output" in DEFAULT_HTML_PATH.parts


class TestStormTimeline:
    """Tests for the scrubbable timeline and cloud animation layer."""

    @pytest.fixture
    def map_html(self, storm_geojson, tmp_path) -> str:
        output = tmp_path / "storm_map.html"
        render_map(storm_geojson, str(output))
        return output.read_text(encoding="utf-8")

    def test_timeline_slider_present(self, map_html):
        assert 'id="storm-timeline-slider"' in map_html
        assert 'type="range"' in map_html
        assert 'min="0" max="100"' in map_html
        assert 'value="0"' in map_html

    def test_timeline_label_present(self, map_html):
        assert 'id="storm-timeline-label"' in map_html

    def test_cloud_canvas_present(self, map_html):
        assert 'id="storm-cloud-layer"' in map_html
        assert "<canvas" in map_html
        assert 'width="320" height="320"' in map_html

    def test_slider_bound_to_frame_animator(self, map_html):
        # The slider input must drive a progress-to-frame mapping.
        assert "addEventListener('input'" in map_html
        assert "setProgress" in map_html
        assert "FRAME_COUNT" in map_html
        assert "smoothDamp" in map_html
        assert "requestAnimationFrame" in map_html

    def test_cloud_layer_tracks_storm_center(self, map_html):
        # The cloud canvas repositions over the storm center on map moves.
        assert "latLngToContainerPoint" in map_html
        assert "map.on('move zoom resize'" in map_html
        assert "window['map_" in map_html

    def test_reduced_motion_fallback(self, map_html):
        assert "prefers-reduced-motion" in map_html

    def test_track_coordinates_injected_for_progress_label(self, map_html):
        # The label interpolates position along the track as you scrub.
        assert "interpolateTrack" in map_html
        assert "var track = [[15.2, 124.8]" in map_html
        # Cloud layer must center on the storm center (lat/lon).
        assert "var center = {\"lat\": 15.2, \"lon\": 124.8}" in map_html
