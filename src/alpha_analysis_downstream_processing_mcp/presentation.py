"""Google Slides presentation generation for location analysis."""

import logging
import os
from typing import Any

import requests

from .wrike import WRIKE_CUSTOM_FIELDS

logger = logging.getLogger("[presentation]")

# Template configuration
TEMPLATE_PRESENTATION_ID = "1s83QkZ_Gq-lQbUgRJw6gePMj-rqu-rNwZas8JYM56lc"

# Presentation folder configuration - where to create new presentations
PRESENTATION_FOLDER_ID = "1LHiqkN2OapT2g-jNLWVRnOIwHITQ8nYw"

# Template image element IDs (optional). When set, we replace images by ID
# to preserve size/positioning exactly.
MAP_IMAGE_ELEMENT_ID: str | None = "g3b3b46d9223_0_51"
STREET_VIEW_IMAGE_ELEMENT_ID: str | None = "g3b3b46d9223_0_50"

# Enrollment dashboard link location in the template (table cell)
ENROLLMENT_DASHBOARD_TABLE_ID = "g3b3b46d9223_0_49"
ENROLLMENT_DASHBOARD_TABLE_ROW = 1
ENROLLMENT_DASHBOARD_TABLE_COL = 0


def geocode_address(address: str) -> tuple[float, float]:
    """
    Geocode an address to lat/lon using Google Maps Geocoding API.

    Args:
        address: Full address to geocode

    Returns:
        Tuple of (latitude, longitude)

    Raises:
        RuntimeError: If geocoding fails
    """
    api_key = os.getenv("GOOGLE_MAPS_API_KEY", "")
    if not api_key:
        raise RuntimeError("GOOGLE_MAPS_API_KEY is required for geocoding")

    logger.info("Geocoding address: %s", address)

    url = "https://maps.googleapis.com/maps/api/geocode/json"
    params = {"address": address, "key": api_key}

    try:
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()

        if data.get("status") != "OK":
            raise RuntimeError(f"Geocoding failed: {data.get('status')}")

        results = data.get("results", [])
        if not results:
            raise RuntimeError("No geocoding results found")

        location = results[0].get("geometry", {}).get("location", {})
        lat = location.get("lat")
        lon = location.get("lng")

        if lat is None or lon is None:
            raise RuntimeError("Missing lat/lon in geocoding result")

        logger.info("Geocoded address: lat=%s, lon=%s", lat, lon)
        return lat, lon

    except Exception as e:
        logger.error("Geocoding failed: %s", e)
        raise RuntimeError(f"Geocoding failed: {e}") from e


def _format_number(value: float | None) -> str:
    """Format a number with comma separators."""
    if value is None:
        return "N/A"
    return f"{round(value):,}"


def _format_percent(value: float | None) -> str:
    """Format a percentage value."""
    if value is None:
        return "N/A"
    # Handle both 0-1 and 0-100 ranges
    pct = value * 100 if value <= 1.5 else value
    return f"{pct:.1f}%"


def _build_static_map_url(lat: float, lon: float) -> str:
    """Build Google Maps Static API URL."""
    api_key = os.getenv("GOOGLE_MAPS_API_KEY", "")
    return (
        "https://maps.googleapis.com/maps/api/staticmap"
        f"?center={lat},{lon}&zoom=16&size=640x640&maptype=roadmap"
        f"&markers=color:red%7C{lat},{lon}&key={api_key}"
    )


def _build_street_view_url(lat: float, lon: float) -> str:
    """Build Google Maps Street View Static API URL."""
    api_key = os.getenv("GOOGLE_MAPS_API_KEY", "")
    return (
        "https://maps.googleapis.com/maps/api/streetview"
        f"?size=640x640&location={lat},{lon}&fov=80&pitch=0&key={api_key}"
    )


def _build_table_cell_updates(
    *,
    enrollment_score: float | None,
    relative_enrollment_score: float | None,
    enrollment_score_plus: float | None,
    relative_enrollment_score_plus: float | None,
    wealth_score: float | None,
    relative_wealth_score: float | None,
) -> list[dict[str, Any]]:
    """
    Build table cell update requests using text placeholders.

    Template should contain these placeholders in table cells:
    - {{ENROLLMENT_SCORE}}
    - {{RELATIVE_ENROLLMENT_SCORE}}
    - {{ENROLLMENT_SCORE_PLUS}}
    - {{RELATIVE_ENROLLMENT_SCORE_PLUS}}
    - {{WEALTH_SCORE}}
    - {{RELATIVE_WEALTH_SCORE}}
    """
    replacements = [
        ("{{ENROLLMENT_SCORE}}", _format_number(enrollment_score)),
        ("{{RELATIVE_ENROLLMENT_SCORE}}", _format_percent(relative_enrollment_score)),
        ("{{ENROLLMENT_SCORE_PLUS}}", _format_number(enrollment_score_plus)),
        (
            "{{RELATIVE_ENROLLMENT_SCORE_PLUS}}",
            _format_percent(relative_enrollment_score_plus),
        ),
        ("{{WEALTH_SCORE}}", _format_number(wealth_score)),
        ("{{RELATIVE_WEALTH_SCORE}}", _format_percent(relative_wealth_score)),
    ]

    updates: list[dict[str, Any]] = []
    for placeholder, value in replacements:
        updates.append(
            {
                "replaceAllText": {
                    "containsText": {"text": placeholder, "matchCase": True},
                    "replaceText": value,
                }
            }
        )

    return updates


def _build_image_updates(
    *,
    map_url: str,
    street_url: str,
    map_image_id: str | None = None,
    street_image_id: str | None = None,
) -> list[dict[str, Any]]:
    """
    Build image replacement requests using text placeholders.

    Template should contain shapes/text boxes with:
    - {{STREET_VIEW}} - will be replaced with street view image
    - {{MAP_VIEW}} - will be replaced with map image
    """
    requests: list[dict[str, Any]] = []

    if street_image_id:
        requests.append(
            {
                "replaceImage": {
                    "imageObjectId": street_image_id,
                    "url": street_url,
                    "imageReplaceMethod": "CENTER_CROP",
                }
            }
        )
    else:
        logger.warning("Street view image ID not set; skipping image replacement")

    if map_image_id:
        requests.append(
            {
                "replaceImage": {
                    "imageObjectId": map_image_id,
                    "url": map_url,
                    "imageReplaceMethod": "CENTER_CROP",
                }
            }
        )
    else:
        logger.warning("Map image ID not set; skipping image replacement")

    return requests


def build_dashboard_link_updates(
    *,
    link_url: str,
    table_id: str,
    row_index: int,
    col_index: int,
    link_text: str = "Report",
) -> list[dict[str, Any]]:
    """
    Build link update requests for the enrollment dashboard link.

    This replaces the cell text and applies a hyperlink to the configured table cell.
    """
    requests: list[dict[str, Any]] = []

    requests.append(
        {
            "updateTextStyle": {
                "objectId": table_id,
                "cellLocation": {
                    "rowIndex": row_index,
                    "columnIndex": col_index,
                },
                "textRange": {"type": "ALL"},
                "style": {"link": {"url": link_url}},
                "fields": "link",
            }
        }
    )

    return requests


def extract_property_features_from_description(
    description: str,
) -> dict[str, str | None]:
    """
    Extract property features from Wrike description's Real Estate Information section.

    Args:
        description: HTML description from Wrike

    Returns:
        Dict with property feature values
    """
    import re

    result: dict[str, str | None] = {
        "square_footage": None,
        "complete_building": None,
        "move_in_ready": None,
        "current_space_usage": None,
    }

    # Pattern to extract value from: <li><b>Square Footage:</b> VALUE</li>
    # (Wrike may use <b> or <strong>)
    patterns = {
        "square_footage": r"<li><(?:b|strong)>Square Footage:</(?:b|strong)>\s*([^<]+)</li>",
        "complete_building": r"<li><(?:b|strong)>Are we taking the complete building\?:</(?:b|strong)>\s*([^<]+)</li>",
        "move_in_ready": r"<li><(?:b|strong)>Is this move-in ready\?:</(?:b|strong)>\s*([^<]+)</li>",
        "current_space_usage": r"<li><(?:b|strong)>What is the space currently used for\?:</(?:b|strong)>\s*([^<]+)</li>",
    }

    for key, pattern in patterns.items():
        match = re.search(pattern, description, re.IGNORECASE)
        if match:
            value = match.group(1).strip()
            # Skip "Pending" or "N/A" values
            if value and value not in ["Pending", "N/A"]:
                result[key] = value

    return result


def extract_scores_from_wrike_record(record: dict[str, Any]) -> dict[str, float | None]:
    """
    Extract enrollment and wealth scores from Wrike Site Record.

    Args:
        record: Wrike site record with customFields

    Returns:
        Dict with score values
    """
    custom_fields = record.get("customFields", [])
    if not isinstance(custom_fields, list):
        return {
            "enrollment_score": None,
            "relative_enrollment_score": None,
            "enrollment_score_plus": None,
            "relative_enrollment_score_plus": None,
            "wealth_score": None,
            "relative_wealth_score": None,
        }

    score_fields = [
        "enrollment_score",
        "relative_enrollment_score",
        "enrollment_score_plus",
        "relative_enrollment_score_plus",
        "wealth_score",
        "relative_wealth_score",
    ]

    scores: dict[str, float | None] = {field: None for field in score_fields}

    for field in custom_fields:
        if not isinstance(field, dict):
            continue

        field_id = field.get("id")
        field_value = field.get("value")

        # Check each score field
        for field_name in score_fields:
            if field_id == WRIKE_CUSTOM_FIELDS.get(field_name):
                try:
                    scores[field_name] = float(field_value) if field_value else None
                except (ValueError, TypeError):
                    scores[field_name] = None
                break

    return scores


def build_presentation_updates(
    *,
    address: str,
    enrollment_score: float | None,
    relative_enrollment_score: float | None,
    enrollment_score_plus: float | None,
    relative_enrollment_score_plus: float | None,
    wealth_score: float | None,
    relative_wealth_score: float | None,
    square_footage: str | None = None,
    complete_building: str | None = None,
    move_in_ready: str | None = None,
    current_space_usage: str | None = None,
) -> list[dict[str, Any]]:
    """
    Build all presentation update requests.

    Args:
        address: Full address for geocoding and map generation
        enrollment_score: Enrollment Score
        relative_enrollment_score: Relative Enrollment Score (0-1 or 0-100)
        enrollment_score_plus: Enrollment Score+
        relative_enrollment_score_plus: Relative Enrollment Score+ (0-1 or 0-100)
        wealth_score: Wealth Score
        relative_wealth_score: Relative Wealth Score (0-1 or 0-100)
        square_footage: Square footage of the space
        complete_building: Whether taking complete building
        move_in_ready: Whether move-in ready
        current_space_usage: Current usage of the space

    Returns:
        List of batch update requests for Google Slides
    """
    logger.info("Building presentation updates for address: %s", address)

    # Geocode address
    lat, lon = geocode_address(address)

    # Generate map image URLs
    map_url = _build_static_map_url(lat, lon)
    street_url = _build_street_view_url(lat, lon)

    logger.info("Generated map URLs (lat=%s, lon=%s)", lat, lon)

    # Build update requests
    requests: list[dict[str, Any]] = []

    # 1. Replace title with address
    requests.append(
        {
            "replaceAllText": {
                "containsText": {"text": "{{ADDRESS}}", "matchCase": False},
                "replaceText": address,
            }
        }
    )

    # 2. Replace property features section
    property_features = []
    if square_footage:
        property_features.append(f"{square_footage} sqft")
    if complete_building:
        property_features.append(f"Complete building: {complete_building}")
    if move_in_ready:
        property_features.append(f"Move-in ready: {move_in_ready}")
    if current_space_usage:
        property_features.append(f"Current usage: {current_space_usage}")

    property_text = (
        "\n".join(property_features)
        if property_features
        else "No property information available"
    )

    requests.append(
        {
            "replaceAllText": {
                "containsText": {"text": "{{PROPERTY_FEATURES}}", "matchCase": False},
                "replaceText": property_text,
            }
        }
    )

    # 3. Add table updates
    requests += _build_table_cell_updates(
        enrollment_score=enrollment_score,
        relative_enrollment_score=relative_enrollment_score,
        enrollment_score_plus=enrollment_score_plus,
        relative_enrollment_score_plus=relative_enrollment_score_plus,
        wealth_score=wealth_score,
        relative_wealth_score=relative_wealth_score,
    )

    # 4. Add image updates
    logger.info(
        "Building image updates (map_id=%s, street_id=%s)",
        MAP_IMAGE_ELEMENT_ID,
        STREET_VIEW_IMAGE_ELEMENT_ID,
    )
    requests += _build_image_updates(
        map_url=map_url,
        street_url=street_url,
        map_image_id=MAP_IMAGE_ELEMENT_ID,
        street_image_id=STREET_VIEW_IMAGE_ELEMENT_ID,
    )

    logger.info("Built %d update requests", len(requests))
    return requests
