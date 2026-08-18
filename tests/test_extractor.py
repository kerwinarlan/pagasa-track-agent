"""Tests for the bulletin resolver (deterministic first, LLM guarded)."""

from unittest.mock import patch

import pytest

from src.extractor import parse_bulletin_with_source

NAV_JUNK: str = """
PAGASA Toggle navigation GOVPH Home Weather General Weather Daily Weather
Forecast Aviation Marine Climate Astronomy Regional Forecast Products and
Services Information About Us Contact Us Privacy Notice Accessibility
"""


class TestLowConfidenceGuard:
    @patch("src.extractor.get_client")
    def test_junk_text_refuses_llm_fallback(self, mock_get_client):
        """Navigation text must never reach the LLM: tokens and hallucination."""
        with pytest.raises(RuntimeError, match="does not look like a PAGASA bulletin"):
            parse_bulletin_with_source(NAV_JUNK, allow_llm=True)

        mock_get_client.assert_not_called()
