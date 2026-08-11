"""Fetch PAGASA Severe Weather Bulletins from the web."""

from __future__ import annotations

import requests
from bs4 import BeautifulSoup


def fetch_bulletin_text(url: str) -> str:
    """Fetch the bulletin at ``url`` and return its cleaned raw text.

    Raises:
        RuntimeError: If the HTTP request fails or returns an error status.
    """
    try:
        response = requests.get(url)
        response.raise_for_status()
    except requests.exceptions.RequestException as exc:
        raise RuntimeError(
            f"Failed to fetch bulletin from {url}: {exc}"
        ) from exc

    soup = BeautifulSoup(response.text, "html.parser")
    return soup.get_text(separator="\n", strip=True)
