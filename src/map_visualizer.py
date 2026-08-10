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


def _storm_timeline_html() -> str:
    """Return the timeline slider and cloud layer HTML."""
    return """
<div id="storm-controls" style="position:absolute; left:0; top:0; width:100%; height:100%; z-index:400; pointer-events:none;">
  <canvas id="storm-cloud-layer" width="320" height="320"
          style="position:absolute; left:0; top:0; width:200px; height:200px; pointer-events:none;"></canvas>
  <div id="storm-timeline" style="position:absolute; bottom:14px; left:50%; transform:translateX(-50%); z-index:1000; pointer-events:auto; background:rgba(20,25,40,0.82); border-radius:10px; padding:8px 14px 6px; text-align:center; font-family:sans-serif;">
    <div id="storm-timeline-label" style="color:#fff; font-size:12px; margin-bottom:4px;">0%</div>
    <input id="storm-timeline-slider" type="range" min="0" max="100" value="0"
           style="width:260px; accent-color:#00e5ff; cursor:pointer;"
           aria-label="Storm progression timeline">
    <div style="color:#9fb0c9; font-size:10px; margin-top:2px;">Drag to scrub storm progression</div>
  </div>
</div>
"""


def _storm_timeline_js(
    map_name: str, center: dict[str, Any], track: list[dict[str, Any]] | None
) -> str:
    """Return the scrubbable cloud-animation JavaScript.

    The animation follows the oil-motion continuous-control pattern:
    normalize the slider to a progress value, map it to an integer frame,
    track it with smoothDamp, and render only when the integer frame
    changes. A seeded blob field renders a rotating satellite cloud
    layer whose swirl, size, and opacity develop with storm progress.
    """
    center_json = json.dumps(
        {"lat": center["geometry"]["coordinates"][1],
         "lon": center["geometry"]["coordinates"][0]}
    )
    if track:
        track_coords = [
            [lat, lon]
            for lon, lat in track["geometry"]["coordinates"]
        ]
    else:
        track_coords = []
    track_json = json.dumps(track_coords)
    js = """
(function () {
  function clamp(v, lo, hi) { return Math.min(hi, Math.max(lo, v)); }
  function mulberry32(seed) {
    var a = seed >>> 0;
    return function () {
      a |= 0; a = (a + 0x6D2B79F5) | 0;
      var t = Math.imul(a ^ (a >>> 15), 1 | a);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }
  function smoothDamp(current, target, velocity, smoothTime, maxSpeed, dt) {
    var safeTime = Math.max(0.0001, smoothTime);
    var omega = 2 / safeTime;
    var x = omega * dt;
    var decay = 1 / (1 + x + 0.48 * x * x + 0.235 * x * x * x);
    var originalTarget = target;
    var maxChange = maxSpeed * safeTime;
    var change = clamp(current - target, -maxChange, maxChange);
    var limitedTarget = current - change;
    var temp = (velocity + omega * change) * dt;
    var nextVelocity = (velocity - omega * temp) * decay;
    var nextPosition = limitedTarget + (change + temp) * decay;
    if ((originalTarget - current > 0) === (nextPosition > originalTarget)) {
      nextPosition = originalTarget;
      nextVelocity = 0;
    }
    return [nextPosition, nextVelocity];
  }
  function init() {
    var map = window['__MAP_NAME__'];
    var slider = document.getElementById('storm-timeline-slider');
    var label = document.getElementById('storm-timeline-label');
    var canvas = document.getElementById('storm-cloud-layer');
    if (!map || !slider || !canvas) return;
    map.getContainer().appendChild(document.getElementById('storm-controls'));
    var ctx = canvas.getContext('2d');
    var W = canvas.width, H = canvas.height;
    var CX = W / 2, CY = H / 2;
    var FRAME_COUNT = 24;
    var center = __CENTER__;
    var track = __TRACK__;
    var rand = mulberry32(20241117);
    var BLOBS = [];
    for (var i = 0; i < 44; i++) {
      var r = Math.sqrt(rand()) * W * 0.46;
      var a = rand() * Math.PI * 2;
      BLOBS.push({
        x: CX + Math.cos(a) * r,
        y: CY + Math.sin(a) * r,
        r: 8 + rand() * 16,
        alpha: 0.35 + rand() * 0.45
      });
    }
    function drawFrame(frame) {
      var progress = frame / (FRAME_COUNT - 1);
      var phase = progress * Math.PI * 2;
      var scale = 0.85 + 0.3 * progress;
      var baseAlpha = 0.5 + 0.4 * progress;
      ctx.clearRect(0, 0, W, H);
      for (var i = 0; i < BLOBS.length; i++) {
        var b = BLOBS[i];
        var dx = b.x - CX, dy = b.y - CY;
        var ang = Math.atan2(dy, dx) + phase;
        var rad = Math.hypot(dx, dy) * scale;
        var x = CX + Math.cos(ang) * rad;
        var y = CY + Math.sin(ang) * rad;
        var radius = b.r * (1.1 + 0.5 * progress);
        var g = ctx.createRadialGradient(x, y, 0, x, y, radius);
        g.addColorStop(0, 'rgba(255,255,255,' + (b.alpha * baseAlpha).toFixed(3) + ')');
        g.addColorStop(1, 'rgba(255,255,255,0)');
        ctx.fillStyle = g;
        ctx.beginPath();
        ctx.arc(x, y, radius, 0, Math.PI * 2);
        ctx.fill();
      }
    }
    function interpolateTrack(t) {
      if (track.length === 0) return null;
      if (track.length === 1 || t <= 0) return track[0];
      if (t >= 1) return track[track.length - 1];
      var segs = [], total = 0, i;
      for (i = 1; i < track.length; i++) {
        var d = Math.hypot(track[i][0] - track[i - 1][0], track[i][1] - track[i - 1][1]);
        segs.push(d); total += d;
      }
      var dist = t * total;
      for (i = 0; i < segs.length; i++) {
        if (dist <= segs[i] || i === segs.length - 1) {
          var f = segs[i] === 0 ? 0 : dist / segs[i];
          return [track[i][0] + (track[i + 1][0] - track[i][0]) * f,
                  track[i][1] + (track[i + 1][1] - track[i][1]) * f];
        }
        dist -= segs[i];
      }
      return track[track.length - 1];
    }
    function updateLabel(frame) {
      var progress = frame / (FRAME_COUNT - 1);
      var pct = Math.round(progress * 100);
      var p = interpolateTrack(progress);
      var posText = p ? p[0].toFixed(1) + 'N, ' + p[1].toFixed(1) + 'E' : '';
      label.textContent = pct + '%  ' + posText;
    }
    var position = 0, target = 0, velocity = 0, lastFrame = -1, raf = 0, lastTime = 0;
    var reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    function render() {
      var frame = Math.round(clamp(position, 0, FRAME_COUNT - 1));
      if (frame !== lastFrame) {
        drawFrame(frame);
        updateLabel(frame);
        lastFrame = frame;
      }
    }
    function loop(now) {
      raf = 0;
      var dt = lastTime ? Math.min((now - lastTime) / 1000, 1 / 30) : 1 / 60;
      lastTime = now;
      if (reduced) {
        position = target;
        velocity = 0;
      } else {
        var result = smoothDamp(position, target, velocity, 0.11, FRAME_COUNT * 2, dt);
        position = result[0];
        velocity = result[1];
      }
      render();
      if (Math.abs(target - position) > 0.002 || Math.abs(velocity) > 0.002) {
        raf = requestAnimationFrame(loop);
      }
    }
    function setProgress(p) {
      target = clamp(p, 0, 1) * (FRAME_COUNT - 1);
      if (raf === 0) { lastTime = 0; raf = requestAnimationFrame(loop); }
    }
    slider.addEventListener('input', function () {
      setProgress(slider.value / 100);
    });
    function positionCanvas() {
      var point = map.latLngToContainerPoint([center.lat, center.lon]);
      canvas.style.left = (point.x - 100) + 'px';
      canvas.style.top = (point.y - 100) + 'px';
    }
    map.on('move zoom resize', positionCanvas);
    positionCanvas();
    setProgress(0);
    render();
  }
  setTimeout(init, 0);
})();
"""
    return (
        js.replace("__MAP_NAME__", map_name)
        .replace("__CENTER__", center_json)
        .replace("__TRACK__", track_json)
    )


def _add_timeline(
    map_obj: folium.Map,
    center: dict[str, Any],
    track: dict[str, Any] | None,
) -> None:
    """Inject the timeline slider and scrubbable cloud layer."""
    map_obj.get_root().html.add_child(folium.Element(_storm_timeline_html()))
    map_obj.get_root().script.add_child(
        folium.Element(_storm_timeline_js(map_obj.get_name(), center, track))
    )


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
    _add_timeline(map_obj, center, track)

    map_obj.save(output_html_path)
    return map_obj


def main() -> None:
    """Render the sample storm track to an interactive HTML map."""
    render_map(str(DEFAULT_GEOJSON_PATH), str(DEFAULT_HTML_PATH))
    print(f"Saved storm map to {DEFAULT_HTML_PATH}")


if __name__ == "__main__":
    main()
