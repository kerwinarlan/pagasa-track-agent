"""Extract structured storm bulletins from raw PAGASA text with DeepSeek.

The module uses ``instructor`` on top of the OpenAI-compatible DeepSeek
API. The structured output is validated by the Pydantic v2 schema in
``src.schemas.bulletin``.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import instructor
from openai import OpenAI

from src.schemas.bulletin import StormBulletin

DEEPSEEK_BASE_URL: str = "https://api.deepseek.com"
DEEPSEEK_MODEL: str = "deepseek-chat"

_client: Any = None

_SYSTEM_PROMPT: str = (
    "You extract structured data from PAGASA Severe Weather Bulletins. "
    "Return exact values as written in the bulletin. "
    "Convert compass directions (for example 'west-northwestward') to degrees "
    "clockwise from true north (N=0, E=90, S=180, W=270). "
    "Use the PAGASA intensity category that matches the reported maximum "
    "sustained winds, and the wind signal number given in the bulletin. "
    "Include every forecast position with its valid time in the forecast track."
)


def get_client() -> Any:
    """Return a cached instructor-wrapped DeepSeek client."""
    global _client
    if _client is None:
        api_key = os.environ.get("DEEPSEEK_API_KEY")
        if not api_key:
            raise RuntimeError(
                "DEEPSEEK_API_KEY environment variable is not set."
            )
        raw_client = OpenAI(
            base_url=DEEPSEEK_BASE_URL,
            api_key=api_key,
        )
        _client = instructor.from_openai(
            raw_client,
            mode=instructor.Mode.MD_JSON,
        )
    return _client


def parse_bulletin_text(raw_text: str) -> StormBulletin:
    """Parse raw PAGASA bulletin text into a structured StormBulletin."""
    client = get_client()
    return client.chat.completions.create(
        model=DEEPSEEK_MODEL,
        response_model=StormBulletin,
        max_retries=3,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": raw_text},
        ],
    )


def _sample_bulletin_path() -> Path:
    """Return the path to the sample bulletin relative to this file."""
    project_root = Path(__file__).resolve().parent.parent
    return project_root / "data" / "raw" / "sample_bulletin.txt"


def main() -> None:
    """Read the sample bulletin, parse it, and print JSON output."""
    raw_text = _sample_bulletin_path().read_text(encoding="utf-8")
    bulletin = parse_bulletin_text(raw_text)
    print(bulletin.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
