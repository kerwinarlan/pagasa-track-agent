"""Fetch PAGASA Severe Weather Bulletins from the web."""

from __future__ import annotations

import requests
from bs4 import BeautifulSoup


class NoActiveCycloneError(RuntimeError):
    """Raised when PAGASA reports no active tropical cyclone in the PAR."""


_NO_ACTIVE_MARKERS: tuple[str, ...] = (
    "no active tropical cyclone within the philippine area of responsibility",
    "no active tropical cyclone outside the philippine area of responsibility",
)


def _bulletin_text(soup: BeautifulSoup) -> str:
    """Return the bulletin region text, falling back to the whole page."""
    content = soup.select_one(".article-content")
    root = content if content is not None else soup
    return root.get_text(separator="\n", strip=True)


def fetch_bulletin_text(url: str) -> str:
    """Fetch the bulletin at ``url`` and return its cleaned raw text.

    Returns text from the bulletin region only; site navigation and page
    chrome are dropped so the parser sees the bulletin, not the menu.

    Raises:
        NoActiveCycloneError: PAGASA reports no active tropical cyclone.
        RuntimeError: The HTTP request fails or returns an error status.
    """
    try:
        response = requests.get(url)
        response.raise_for_status()
    except requests.exceptions.RequestException as exc:
        raise RuntimeError(
            f"Failed to fetch bulletin from {url}: {exc}"
        ) from exc

    soup = BeautifulSoup(response.text, "html.parser")
    text = _bulletin_text(soup)
    if any(marker in text.lower() for marker in _NO_ACTIVE_MARKERS):
        raise NoActiveCycloneError(
            "PAGASA reports no active tropical cyclone in the Philippine "
            "Area of Responsibility."
        )
    return text
