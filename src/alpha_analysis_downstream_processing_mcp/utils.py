"""Utility functions for extracting data and downloading files."""

import logging
import re

import requests

logger = logging.getLogger("[utils]")


def extract_sir_url_from_description(description: str) -> str | None:
    """
    Extract the SIR report URL from a Wrike description.

    Expected format in description:
    <li><b>SIR:</b> <a href="https://...">SIR report</a></li>

    Args:
        description: HTML description from Wrike

    Returns:
        SIR report URL or None if not found
    """
    # Pattern to match SIR report link
    # <li><b>SIR:</b> <a href="URL">...</a></li>
    pattern = r'<li><b>SIR:</b>\s*<a[^>]+href="([^"]+)"'

    match = re.search(pattern, description)
    if match:
        url = match.group(1)
        logger.info("Extracted SIR URL: %s", url)
        return url

    logger.warning("Could not find SIR URL in description")
    return None


def download_pdf_from_url(url: str, timeout: int = 30) -> bytes:
    """
    Download a PDF file from a URL.

    Args:
        url: URL to download from
        timeout: Request timeout in seconds

    Returns:
        PDF file content as bytes

    Raises:
        RuntimeError: If download fails
    """
    logger.info("Downloading PDF from: %s", url)

    try:
        response = requests.get(url, timeout=timeout)
        response.raise_for_status()

        # Verify it's a PDF
        content_type = response.headers.get("Content-Type", "")
        if "pdf" not in content_type.lower():
            logger.warning(
                "Downloaded content may not be PDF. Content-Type: %s", content_type
            )

        logger.info("Successfully downloaded PDF (%d bytes)", len(response.content))
        return response.content

    except requests.RequestException as e:
        logger.error("Failed to download PDF from %s: %s", url, e)
        raise RuntimeError(f"Failed to download PDF: {e}") from e
