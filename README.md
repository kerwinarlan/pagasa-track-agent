# PAGASA Track Agent

Structured Storm Tracking Pipeline

## Overview

PAGASA Track Agent converts raw PAGASA Severe Weather Bulletin text into
structured, validated, and visualizable storm tracking data.

The pipeline parses bulletin text with DeepSeek and Instructor, validates the
result with Pydantic v2, exports it as GeoJSON, and renders it as an
interactive Leaflet map. All coordinates are validated against the Philippine
Area of Responsibility (PAR) bounds: latitude 4N-25N, longitude 116E-127E.

## Architecture

```
┌───────────────┐    ┌───────────────────────────┐    ┌──────────────────┐
│  Raw Text     │───▶│  DeepSeek + Instructor    │───▶│  Pydantic v2     │
│  (Bulletin)   │    │  (deepseek-chat, MD_JSON) │    │  (StormBulletin) │
└───────────────┘    └───────────────────────────┘    └────────┬─────────┘
                                                               │
                                                               ▼
┌───────────────┐    ┌──────────────────┐    ┌─────────────────────────┐
│  Leaflet Map  │◀───│  Folium          │◀───│  GeoJSON (RFC 7946)     │
│  (HTML)       │    │  (map_visualizer)│    │  (geojson_exporter)     │
└───────────────┘    └──────────────────┘    └─────────────────────────┘
```

Pipeline stages:

1. **Extract** - `src/extractor.py` sends the raw bulletin to DeepSeek and uses
   Instructor to coerce the reply into a `StormBulletin` Pydantic model.
   Validation failures trigger automatic re-prompts (`max_retries=3`).
2. **Validate** - `src/schemas/bulletin.py` enforces types, enum values,
   positive physical quantities, and PAR coordinate bounds.
3. **Export** - `src/geojson_exporter.py` converts the bulletin into an
   RFC 7946 FeatureCollection (lon/lat order) with center point, forecast
   points, and a track LineString.
4. **Visualize** - `src/map_visualizer.py` renders the GeoJSON as an
   interactive Leaflet map with radar rings, a pulsing radar-wave marker,
   forecast markers, an animated storm-track line, and a scrubbable
   timeline that drives a satellite cloud animation over the track.

## Features

- **Type validation** - Pydantic v2 schemas with field validators for the
  Philippine Area of Responsibility. Latitude must be within 4N-25N and
  longitude within 116E-127E. Wind-signal and typhoon-category enums reject
  invalid values, and a model validator cross-checks category against the
  PAGASA wind-speed thresholds.
- **Structured extraction** - Instructor wraps the DeepSeek API in
  `MD_JSON` mode, which is the most reliable mode for DeepSeek models.
  Validation errors trigger automatic re-prompts, so the pipeline retries up
  to 3 times before giving up.
- **GeoJSON support** - RFC 7946-compliant output with correct longitude,
  latitude coordinate order. Includes the current center, every forecast
  position, and a track LineString.
- **Interactive visualizer** - Folium renders a Leaflet HTML map with a
  pulsing radar-wave marker, multi-tiered wind/radar radius rings, orange
  circle markers for forecast positions, and an animated ant-path storm
  track. A scrubbable timeline at the bottom drives a satellite cloud
  animation over the storm as you drag from 0% to 100% progression.
- **Tests** - 42 pytest tests cover schemas, extraction flow, GeoJSON
  export, and map rendering.

## Quickstart

### Prerequisites

- Python 3.9 or newer
- A DeepSeek API key

### Setup

```bash
# 1. Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate

# 2. Install dependencies
pip install pydantic instructor openai folium pytest

# Python 3.9 only: instructor's internals use modern union syntax
pip install eval_type_backport

# 3. Set your DeepSeek API key
export DEEPSEEK_API_KEY=sk-your-key-here
```

The repository ships with a sample bulletin at
`data/raw/sample_bulletin.txt` and an existing `.venv` (created with
`python3.9`). If you use `direnv`, the included `.envrc` activates the
virtual environment automatically.

### Run the tests

```bash
python -m pytest tests/
```

### Run the extractor

```bash
python -m src.extractor
```

This parses `data/raw/sample_bulletin.txt` with DeepSeek and prints the
structured `StormBulletin` as pretty JSON. The `DEEPSEEK_API_KEY` variable
must be set.

### Export to GeoJSON

```bash
python -m src.geojson_exporter
```

This extracts the sample bulletin (requires the API key) and writes
`data/output/storm_track.geojson`.

### Render the interactive map

```bash
python -m src.map_visualizer
```

This reads `data/output/storm_track.geojson` and writes
`data/output/storm_map.html`. Open the HTML file in a browser to view the
map. This step does not call the API.

Run modules with `python -m` (not `python src/extractor.py`) because the
modules import from the `src` package.

## Project Structure

```
src/
  schemas/bulletin.py     Pydantic v2 models and PAR validators
  extractor.py            DeepSeek + Instructor structured extraction
  geojson_exporter.py     RFC 7946 GeoJSON export
  map_visualizer.py       Folium / Leaflet map rendering
data/
  raw/sample_bulletin.txt Sample PAGASA bulletin
  output/                 Generated GeoJSON and HTML map
tests/                    Pytest test suite
```

## Tech Stack

| Component      | Technology                                        |
| -------------- | ------------------------------------------------- |
| Language       | Python 3.9+                                       |
| Validation     | Pydantic v2 (2.13.4)                              |
| LLM extraction | Instructor (1.15.4) + OpenAI SDK (2.48.0)         |
| LLM provider   | DeepSeek API (`deepseek-chat`)                    |
| Maps           | Folium (0.20.0) / Leaflet                         |
| Testing        | Pytest (8.4.2)                                    |

## Validation Rules

The `Coordinate` schema rejects any position outside the Philippine Area of
Responsibility:

- Latitude: 4.0 to 25.0 degrees north
- Longitude: 116.0 to 127.0 degrees east

The `StormBulletin` model validator enforces PAGASA intensity thresholds:

| Category              | Max sustained winds (km/h) |
| --------------------- | -------------------------- |
| Tropical Depression   | under 63                   |
| Tropical Storm        | 63-88                      |
| Severe Tropical Storm | 89-117                     |
| Typhoon               | 118-184                    |
| Super Typhoon         | 185 and above              |
