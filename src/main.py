"""Automated entry point for the PAGASA storm track agent.

The script scrapes the latest Severe Weather Bulletin from the PAGASA
website, resolves it to structured data (deterministic parser first,
LLM fallback), exports the forecast track to GeoJSON, and renders an
interactive storm map.
"""

from __future__ import annotations

from pathlib import Path

from src.extractor import parse_bulletin_text
from src.geojson_exporter import export_to_geojson
from src.map_visualizer import render_map
from src.scraper import NoActiveCycloneError, fetch_bulletin_text

# Placeholder URL until the real PAGASA bulletin endpoint is configured.
PAGASA_BULLETIN_URL: str = (
    "https://www.pagasa.dost.gov.ph/tropical-cyclone/severe-weather-bulletin"
)

_PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent
GEOJSON_OUTPUT_PATH: Path = _PROJECT_ROOT / "data" / "output" / "storm_track.geojson"
HTML_OUTPUT_PATH: Path = _PROJECT_ROOT / "data" / "output" / "storm_map.html"


def main() -> None:
    """Run the full update pipeline: scrape, extract, export, and render."""
    try:
        raw_text = fetch_bulletin_text(PAGASA_BULLETIN_URL)
    except NoActiveCycloneError as exc:
        # A no-bulletin day is a successful run with nothing to publish:
        # keep the last published map, spend no LLM tokens.
        print(f"Nothing to publish: {exc}")
        return
    bulletin = parse_bulletin_text(raw_text)
    export_to_geojson(bulletin, str(GEOJSON_OUTPUT_PATH))
    render_map(str(GEOJSON_OUTPUT_PATH), str(HTML_OUTPUT_PATH))
    print("Update successful!")


if __name__ == "__main__":
    main()
