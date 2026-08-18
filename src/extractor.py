"""Resolve raw PAGASA bulletin text into a StormBulletin.

Deterministic-first: the stdlib regex parser in ``src.parser`` handles the
observed 2020-2024 formats. The LLM (DeepSeek via instructor) runs only
when the deterministic parse is incomplete or self-contradictory.

Same input always yields the same output: the deterministic parse is pure,
and a hash cache makes repeated LLM parses free. Disagreements between the
two parsers are logged for review.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any

import instructor
from openai import OpenAI

from src.parser import ParseResult, deterministic_parse
from src.schemas.bulletin import StormBulletin

DEEPSEEK_BASE_URL: str = "https://api.deepseek.com"
DEEPSEEK_MODEL: str = "deepseek-chat"

_client: Any = None
_cache: dict[str, tuple[str, str]] = {}  # text hash -> (bulletin json, source)

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


def _text_hash(raw_text: str) -> str:
    return hashlib.sha256(raw_text.encode("utf-8")).hexdigest()[:16]


def parse_bulletin_with_source(
    raw_text: str, allow_llm: bool = True
) -> tuple[StormBulletin, str, ParseResult]:
    """Parse bulletin text; return (bulletin, source, deterministic result).

    ``source`` is "deterministic" or "llm". An LLM failure raises, since a
    bulletin we cannot parse must not silently vanish.
    """
    result = deterministic_parse(raw_text)
    if result.accepted:
        assert result.bulletin is not None
        return result.bulletin, "deterministic", result

    if not allow_llm:
        raise RuntimeError(
            "Deterministic parse rejected (confidence "
            f"{result.confidence:.2f}): {result.warnings[:3]}"
        )

    if result.confidence < 0.4:
        # The designed LLM fallback is for bulletins with an unusual format
        # (the corpus LPA-dissipation final parses at 0.6). Below 0.4 the
        # input is not a bulletin (navigation junk, empty page); calling the
        # LLM would burn tokens and hallucinate a storm.
        raise RuntimeError(
            "Input does not look like a PAGASA bulletin (confidence "
            f"{result.confidence:.2f}); refusing LLM fallback."
        )

    text_hash = _text_hash(raw_text)
    if text_hash in _cache:
        from pydantic import TypeAdapter

        bulletin = TypeAdapter(StormBulletin).validate_json(_cache[text_hash][0])
        return bulletin, _cache[text_hash][1], result

    bulletin = get_client().chat.completions.create(
        model=DEEPSEEK_MODEL,
        response_model=StormBulletin,
        max_retries=3,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": raw_text},
        ],
    )
    _cache[text_hash] = (bulletin.model_dump_json(), "llm")
    return bulletin, "llm", result


def parse_bulletin_text(raw_text: str) -> StormBulletin:
    """Parse raw PAGASA bulletin text into a structured StormBulletin."""
    bulletin, _source, _result = parse_bulletin_with_source(raw_text)
    return bulletin


def main() -> None:
    """Parse the corpus and report the parse source per file."""
    project_root = Path(__file__).resolve().parent.parent
    corpus_dir = project_root / "data" / "raw" / "corpus"
    for path in sorted(corpus_dir.glob("*.txt")):
        raw_text = path.read_text(encoding="utf-8")
        bulletin, source, result = parse_bulletin_with_source(raw_text)
        if source == "llm" or not result.accepted:
            print(f"{path.name}: {source} conf={result.confidence:.2f}")
            for warning in result.warnings[:4]:
                print(f"    warn: {warning[:110]}")


if __name__ == "__main__":
    main()
