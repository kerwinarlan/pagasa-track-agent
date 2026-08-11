"""Tests for the PAGASA bulletin web scraper."""

from unittest.mock import Mock, patch

import pytest
import requests

from src.scraper import fetch_bulletin_text

MOCK_URL: str = "https://example.com/bulletin.html"

MOCK_HTML: str = """
<html>
  <head><title>Severe Weather Bulletin</title></head>
  <body>
    <h1>Severe Weather Bulletin #1</h1>
    <p>Typhoon "Test" has strengthened.</p>
  </body>
</html>
"""


def make_response(status_code: int, text: str) -> Mock:
    """Return a mock requests response with the given status and body."""
    response = Mock()
    response.status_code = status_code
    response.text = text

    def raise_for_status() -> None:
        if status_code >= 400:
            raise requests.exceptions.HTTPError(
                f"{status_code} Client Error"
            )

    response.raise_for_status.side_effect = raise_for_status
    return response


class TestFetchBulletinText:
    @patch("src.scraper.requests.get")
    def test_successful_fetch_returns_cleaned_text(self, mock_get):
        mock_get.return_value = make_response(200, MOCK_HTML)

        text = fetch_bulletin_text(MOCK_URL)

        mock_get.assert_called_once_with(MOCK_URL)
        assert "Severe Weather Bulletin #1" in text
        assert 'Typhoon "Test" has strengthened.' in text
        assert "<h1>" not in text

    @patch("src.scraper.requests.get")
    def test_404_response_raises_runtime_error(self, mock_get):
        mock_get.return_value = make_response(404, "<html>Not Found</html>")

        with pytest.raises(RuntimeError, match="Failed to fetch"):
            fetch_bulletin_text(MOCK_URL)

    @patch("src.scraper.requests.get")
    def test_connection_error_raises_runtime_error(self, mock_get):
        mock_get.side_effect = requests.exceptions.ConnectionError(
            "connection refused"
        )

        with pytest.raises(RuntimeError, match="Failed to fetch"):
            fetch_bulletin_text(MOCK_URL)
