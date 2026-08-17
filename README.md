<div align="center">

# 🌪️ PAGASA Track Agent

**Structured storm tracking pipeline**

[![Python](https://img.shields.io/badge/Python%203.9-3776AB?logo=python&logoColor=white)](https://www.python.org)
[![DeepSeek](https://img.shields.io/badge/DeepSeek-4D6BFE?logo=deepseek&logoColor=white)](https://deepseek.com)
[![Pydantic](https://img.shields.io/badge/Pydantic%20v2-E92063?logo=pydantic&logoColor=white)](https://docs.pydantic.dev)
[![Leaflet](https://img.shields.io/badge/Leaflet-199900?logo=leaflet&logoColor=white)](https://leafletjs.com)
[![pytest](https://img.shields.io/badge/pytest-99%20tests-0A9EDC?logo=pytest&logoColor=white)](https://docs.pytest.org)

</div>

PAGASA Track Agent converts raw PAGASA Severe Weather Bulletin text into
structured, validated, and visualizable storm tracking data: parse with a
deterministic regex engine (LLM as fallback), validate with Pydantic v2,
stitch the series into a track, verify forecast skill against later fixes,
export as GeoJSON, and render as an interactive Leaflet map. A golden corpus
of 37 real bulletins (2020-2024) locks the pipeline to ground truth.

---

## Why it exists: bulletins are prose, not data

PAGASA Severe Weather Bulletins are the authoritative source for typhoon
positions in the Philippines - but they arrive as free text, with
coordinates, wind speeds, and signal numbers scattered through prose.
Turning them into track data by hand is slow and error-prone; a single
mistyped coordinate puts a storm outside its own track. This pipeline
automates the whole chain - deterministically first, so the same input
always yields the same output at zero cost, with the LLM demoted to a
fallback for formats the regex engine does not know.

| Problem | Solution | Result |
|---|---|---|
| Bulletins are prose, not data | Deterministic parser (stdlib regex) handles the observed 2020-2024 formats; DeepSeek + Instructor resolves the rest | Structured `StormBulletin` every time |
| LLMs can invent coordinates | Pydantic v2 enforces a Western North Pacific sanity box, enums, and PAGASA intensity thresholds | Track points that are always physically plausible |
| A lone bulletin is not a track | The tracker stitches the series, checks the invariants, and scores each bulletin's forecast against later fixes | A verified storm track with skill metrics |
| Track tables are hard to read | Folium renders an interactive Leaflet map with a scrubbable timeline | Storm movement visible at a glance |

## Architecture

```
┌───────────────┐    ┌───────────────────────────┐    ┌──────────────────┐
│  Raw Text     │───▶│  deterministic_parse      │───▶│  Pydantic v2     │
│  (Bulletin)   │    │  (src/parser.py, stdlib)  │    │  (StormBulletin) │
└───────────────┘    └─────────────┬─────────────┘    └────────┬─────────┘
                                   │ fails (conf < 0.8)        │
                                   ▼                           ▼
                    ┌───────────────────────────┐    ┌──────────────────┐
                    │  DeepSeek + Instructor    │    │  StormTracker     │
                    │  (hash-cached fallback)   │    │  (stitcher +      │
                    └───────────────────────────┘    │   verification)   │
                                                     └────────┬─────────┘
                                                              ▼
┌───────────────┐    ┌──────────────────┐    ┌─────────────────────────┐
│  Leaflet Map  │◀───│  Folium          │◀───│  GeoJSON (RFC 7946)     │
│  (HTML)       │    │  (map_visualizer)│    │  (geojson_exporter)     │
└───────────────┘    └──────────────────┘    └─────────────────────────┘
```

Pipeline stages:

1. **Resolve** - `src/extractor.py` runs the deterministic parser first. It
   never raises: it returns a `ParseResult` with confidence (the fraction of
   5 core fields found) and warnings, accepted at confidence >= 0.8. On
   rejection the DeepSeek + Instructor fallback runs, cached by text hash so
   re-parsing is free and deterministic.
2. **Validate** - `src/schemas/bulletin.py` enforces types, enum values,
   timezone-aware UTC timestamps, category-vs-wind consistency, strictly
   increasing forecast times, and a Western North Pacific sanity box
   (0-50N, 100-170E). PAR membership is a property of the hexagon, not a
   hard constraint: real bulletins place centers outside the PAR.
3. **Stitch and verify** - `src/tracker.py` ingests the series in order,
   flags invariant breaks (non-monotonic number, stale issue time, name
   change, PAR exit), compares observed displacement against stated
   movement, and scores each forecast track against the fixes of later
   bulletins (haversine error within a 3-hour window).
4. **Export** - `src/geojson_exporter.py` converts the bulletin into an
   RFC 7946 FeatureCollection (lon/lat order) with center point, forecast
   points, and a track LineString.
5. **Visualize** - `src/map_visualizer.py` renders the GeoJSON as an
   interactive Leaflet map with a pulsing radar-wave marker, forecast
   markers, an animated storm-track line, and a scrubbable timeline.

## Features

- **Deterministic first** - 36 of 37 corpus bulletins parse without the
  LLM: same input, same output, zero API cost. Forecast valid times are
  resolved from labels (weekday names override misprinted hour counts;
  'Tonight' falls back to the numeric hours), compass prose is canonicalized
  to 16-point abbreviations, and coordinates tolerate wrapped PDF text.
- **Golden corpus** - 37 real bulletins from 2020 (bullet-format),
  2022 (table-format), and 2024, extracted from the archived PAGASA PDFs.
  The parser test asserts exactly one failure: the LPA-dissipation final
  with no wind intensity, which is the designed LLM fallback case.
- **Soft validation** - data anomalies surface as warnings, not failures:
  a TCWS #2 hoisted on a 45 km/h depression (real Pepito data) parses with
  a warning; the tracker's movement and forecast checks are soft issues for
  meteorologist review.
- **Forecast skill verification** - the tracker reports median forecast
  position error and category accuracy per storm series (for example
  Pepito 2020: 19 bulletins, 41 verifications, 126 km median error).
- **GeoJSON support** - RFC 7946-compliant output with correct longitude,
  latitude coordinate order. Includes the current center, every forecast
  position, and a track LineString.
- **Interactive visualizer** - Folium renders a Leaflet HTML map with a
  pulsing radar-wave marker, multi-tiered wind/radar radius rings, orange
  circle markers for forecast positions, and an animated ant-path storm
  track.
- **Tests** - 99 pytest tests cover the schema, the corpus-driven parser,
  the tracker, GeoJSON export, and map rendering.

## Tech Stack

| Component      | Technology                                        |
| -------------- | ------------------------------------------------- |
| Language       | Python 3.9+ (stdlib-only parser)                  |
| Validation     | Pydantic v2 (2.13.4)                              |
| LLM fallback   | Instructor (1.15.4) + OpenAI SDK                 |
| LLM provider   | DeepSeek API (`deepseek-chat`)                    |
| Maps           | Folium (0.20.0) / Leaflet                         |
| Testing        | Pytest (8.4.2)                                    |

## Validation Rules

The `Coordinate` schema enforces a Western North Pacific sanity box:

- Latitude: 0.0 to 50.0 degrees north
- Longitude: 100.0 to 170.0 degrees east

PAR membership (the official hexagon with vertices 5N/115E, 15N/115E,
21N/120E, 25N/120E, 25N/135E, 5N/135E) is exposed as `inside_par` metadata
via ray casting. Real bulletins routinely place centers outside it.

The `StormBulletin` model validator enforces PAGASA intensity thresholds:

| Category              | Max sustained winds (km/h) |
| --------------------- | -------------------------- |
| Tropical Depression   | under 63                   |
| Tropical Storm        | 63-88                      |
| Severe Tropical Storm | 89-117                     |
| Typhoon               | 118-184                    |
| Super Typhoon         | 185 and above              |

## Repository Layout

```
src/
  schemas/bulletin.py     Pydantic v2 models, PAR hexagon, intensity tables
  parser.py               Deterministic stdlib parser (ParseResult)
  extractor.py            Resolver: deterministic first, LLM fallback, hash cache
  tracker.py              Stitcher: invariants + forecast-skill verification
  geojson_exporter.py     RFC 7946 GeoJSON export
  map_visualizer.py       Folium / Leaflet map rendering
  scraper.py              Live PAGASA bulletin fetch
data/
  raw/corpus/             37 archived bulletins (2020-2024), extracted text
  raw/sample_bulletin.txt Legacy synthetic sample
  output/                 Generated GeoJSON and HTML map
tests/                    Pytest suite (99 tests)
```

## Local Setup

### Prerequisites

- Python 3.9 or newer
- A DeepSeek API key (only for LLM fallback; the corpus parses without it)

### Setup

```bash
# 1. Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate

# 2. Install dependencies
pip install pydantic instructor openai folium pytest

# 3. Set your DeepSeek API key
export DEEPSEEK_API_KEY=sk-your-key-here
```

### Parse the corpus deterministically

```bash
python -m pytest tests/test_parser.py -v
```

36 of 37 bulletins must parse without the API; only the LPA-dissipation
final (`auring_24f`) falls back to the LLM.

### Track a storm series

```bash
python -m src.tracker pepito      # 2020 bullet-format series
python -m src.tracker ester       # 2022 table-format series
```

Each prints the verified fixes plus the verification report: median
forecast position error, category accuracy, and every soft issue.

### Export to GeoJSON and render the map

```bash
python -m src.geojson_exporter    # writes data/output/storm_track.geojson
python -m src.map_visualizer      # writes data/output/storm_map.html
```

Run modules with `python -m` (not `python src/extractor.py`) because the
modules import from the `src` package.

## Validation

```bash
python -m pytest tests/    # 99 tests: schema, corpus parser, tracker, GeoJSON export, map rendering
```
