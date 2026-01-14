"""Wrike integration for updating Site Records with location data."""

import json
import logging
import os
import re
from dataclasses import dataclass
from typing import Any

import requests
from openai import OpenAI

logger = logging.getLogger("[wrike]")

WRIKE_API_BASE_URL = "https://www.wrike.com/api/v4"
WRIKE_TIMEOUT_SECONDS = 20.0

# Wrike Space ID - Site Records space
WRIKE_SPACE_ID = "IEAGN6I6I5RFSYZI"

# Site Record Custom Item Type
WRIKE_SITE_RECORD_TYPE_ID = "IEAGN6I6PIAEZNHZ"

# Key custom field IDs for Site Record
WRIKE_CUSTOM_FIELDS = {
    # Location fields
    "market": "IEAGN6I6JUAIIP5D",  # Market (DropDown)
    "ahj": "IEAGN6I6JUAJA4RM",  # AHJ - Authority Having Jurisdiction (DropDown)
    "address": "IEAGN6I6JUAIKSH3",  # Address (Text) - full address
    "address_alt": "IEAGN6I6JUAJJ4EV",  # 6. Address (Text) - alternative address field
    "address_county": "IEAGN6I6JUAJNUVF",  # 6.2 Address County (Text)
    # Property fields
    "square_footage": "IEAGN6I6JUAJJ4FC",  # 15.2 Square Footage of Property (Numeric)
    "square_footage_buildings": "IEAGN6I6JUAJJ4FE",  # 15.3 Square Footage of Buildings (Numeric)
    # Score fields - NEW FIELDS (exact names as created)
    "enrollment_score": "IEAGN6I6JUAKGXNV",  # Enrollment Score (Numeric)
    "enrollment_score_plus": "IEAGN6I6JUAKGXNW",  # Enrollment Score+ (Numeric)
    "wealth_score": "IEAGN6I6JUAKGXNX",  # Wealth Score (Numeric)
    "relative_wealth_score": "IEAGN6I6JUAKGXNZ",  # Relative Wealth Score (Percentage)
    # Score fields - Relative scores (Percentage type)
    "relative_enrollment_score": "IEAGN6I6JUAKDM2H",  # Relative Enrollment Score (Percentage)
    "relative_enrollment_score_plus": "IEAGN6I6JUAKGXOL",  # Relative Enrollment Score+ (Percentage)
    # Zoning / K-12 Status
    "zoning": "IEAGN6I6JUAJA4QQ",  # Zoning (DropDown)
    "k12_status": "IEAGN6I6JUAKGXNY",  # K-12 Status (Text) - NEW
    # School
    "school_type": "IEAGN6I6JUAITZSN",  # School Type (DropDown)
    "overall_site_stage": "IEAGN6I6JUAJU2PJ",  # Overall Site Stage (DropDown)
    # Other
    "site_poc": "IEAGN6I6JUAKEKBU",  # Site POC (LinkToDatabase)
    "p1_accountable": "IEAGN6I6JUAJK2MQ",  # P1 Accountable (Contacts)
}


@dataclass(frozen=True)
class WrikeConfig:
    """Wrike API configuration."""

    access_token: str


class WrikeError(RuntimeError):
    """Wrike API error."""

    pass


def load_wrike_config() -> WrikeConfig:
    """Load Wrike configuration from environment variables."""
    access_token = os.getenv("WRIKE_ACCESS_TOKEN", "")

    if not access_token:
        raise WrikeError(
            "Missing WRIKE_ACCESS_TOKEN env var. Add it to .env file or process env."
        )

    logger.info("Wrike config loaded: space_id=%s", WRIKE_SPACE_ID)
    return WrikeConfig(access_token=access_token)


def _wrike_headers(access_token: str) -> dict[str, str]:
    """Build Wrike API request headers."""
    return {
        "Authorization": f"bearer {access_token}",
        "User-Agent": "alpha-analysis-downstream-processing-mcp/1.0",
    }


def _raise_for_wrike_error(resp: requests.Response) -> None:
    """Raise WrikeError if response is not successful."""
    if resp.ok:
        return
    try:
        body = resp.json()
    except Exception:
        body = {"raw": resp.text[:2000]}
    raise WrikeError(f"Wrike API error {resp.status_code}: {body}")


def _get_all_folder_ids(*, access_token: str) -> list[str]:
    """
    Get all folder IDs from the Wrike space.

    Args:
        access_token: Wrike access token

    Returns:
        List of unique folder IDs
    """
    url = f"{WRIKE_API_BASE_URL}/spaces/{WRIKE_SPACE_ID}/folders"

    logger.info("Fetching all folder IDs from space %s", WRIKE_SPACE_ID)

    resp = requests.get(
        url,
        headers=_wrike_headers(access_token),
        timeout=WRIKE_TIMEOUT_SECONDS,
    )
    _raise_for_wrike_error(resp)

    payload: dict[str, Any] = resp.json()

    # Extract folder IDs from data array
    # Expected structure:
    # {
    #   "kind": "folders",
    #   "data": [
    #     {"id": "...", ...},
    #     {"id": "...", ...}
    #   ]
    # }
    folder_ids: list[str] = []
    data = payload.get("data", [])
    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                folder_id = item.get("id")
                if isinstance(folder_id, str):
                    folder_ids.append(folder_id)

    return folder_ids


def get_site_records_by_stage(
    *,
    stage: str = "1. Looking for Sites",
    cfg: WrikeConfig | None = None,
) -> list[dict[str, Any]]:
    """
    Get all Site Records with a specific overall_site_stage value.

    Args:
        stage: The stage value to filter by (default: "1. Looking for Sites")
        cfg: Wrike config (loads from env if not provided)

    Returns:
        List of matching Site Records
    """
    if cfg is None:
        cfg = load_wrike_config()

    # Step 1: Get all folder IDs
    folder_ids = _get_all_folder_ids(access_token=cfg.access_token)

    logger.info("Found %d folder IDs", len(folder_ids))

    # Step 2: Batch query folders (100 at a time per Wrike API limits)
    batch_size = 100
    all_site_records: list[dict[str, Any]] = []

    for i in range(0, len(folder_ids), batch_size):
        batch = folder_ids[i : i + batch_size]
        ids_param = ",".join(batch)

        url = f"{WRIKE_API_BASE_URL}/folders/{ids_param}"

        logger.info(
            "Querying batch %d-%d of %d folders",
            i + 1,
            min(i + batch_size, len(folder_ids)),
            len(folder_ids),
        )

        resp = requests.get(
            url,
            headers=_wrike_headers(cfg.access_token),
            params={"fields": '["customItemTypeId"]'},
            timeout=WRIKE_TIMEOUT_SECONDS,
        )
        _raise_for_wrike_error(resp)

        payload: dict[str, Any] = resp.json()
        data = payload.get("data", [])

        # Expected structure:
        # {
        #   "kind": "folders",
        #   "data": [
        #     {
        #       "id": "...",
        #       "title": "...",
        #       "customItemTypeId": "IEAGN6I6PIAEZNHZ",
        #       "customFields": [
        #         {"id": "IEAGN6I6JUAJU2PJ", "value": "1. Looking for Sites"},
        #         ...
        #       ],
        #       ...
        #     }
        #   ]
        # }

        if not isinstance(data, list):
            continue

        # Filter for Site Records with matching stage
        for item in data:
            if not isinstance(item, dict):
                continue

            # Check if it's a Site Record
            if item.get("customItemTypeId") != WRIKE_SITE_RECORD_TYPE_ID:
                continue

            # Check if overall_site_stage matches
            custom_fields = item.get("customFields")
            if not isinstance(custom_fields, list):
                continue

            stage_field_id = WRIKE_CUSTOM_FIELDS["overall_site_stage"]

            for field in custom_fields:
                if not isinstance(field, dict):
                    continue

                if field.get("id") == stage_field_id:
                    field_value = field.get("value")
                    if isinstance(field_value, str) and field_value == stage:
                        all_site_records.append(item)
                        break

    logger.info("Found %d Site Records with stage '%s'", len(all_site_records), stage)
    return all_site_records


def _match_address_with_llm(
    *, address: str, site_records: list[dict[str, Any]]
) -> dict[str, Any] | None:
    """
    Use LLM to match the provided address to the best Site Record.

    Args:
        address: Address from the email
        site_records: List of Site Records to match against

    Returns:
        Best matching Site Record or None if no match
    """
    if not site_records:
        logger.warning("No site records to match against")
        return None

    # Build a simplified list for the LLM
    # Expected structure of site_records items:
    # {
    #   "id": "...",
    #   "title": "...",
    #   "customFields": [
    #     {"id": "IEAGN6I6JUAIKSH3", "value": "<a ...>ADDRESS</a>"},
    #     ...
    #   ],
    #   ...
    # }
    candidates: list[dict[str, Any]] = []
    for record in site_records:
        if not isinstance(record, dict):
            continue

        record_id = record.get("id")
        title = record.get("title", "")

        # Extract address from custom fields (only use "address" field)
        record_address = ""
        custom_fields = record.get("customFields", [])
        if isinstance(custom_fields, list):
            for field in custom_fields:
                if not isinstance(field, dict):
                    continue

                field_id = field.get("id")
                # Only check the "address" field (not address_alt)
                if field_id == WRIKE_CUSTOM_FIELDS["address"]:
                    value = field.get("value", "")
                    if isinstance(value, str):
                        # Strip HTML tags from address field
                        # Wrike stores addresses as: <a ...>ADDRESS</a>
                        record_address = re.sub(r"<[^>]+>", "", value).strip()
                    break

        candidates.append({"id": record_id, "title": title, "address": record_address})

    # Use OpenAI to match
    openai_api_key = os.getenv("OPENAI_API_KEY")
    if not openai_api_key:
        logger.error("OPENAI_API_KEY not found, cannot perform LLM matching")
        raise WrikeError("OPENAI_API_KEY required for address matching")

    client = OpenAI(api_key=openai_api_key)

    system_prompt = """You are an address matching assistant. Given a target address and a list of candidate Site Records, identify which candidate best matches the target address.

Consider:
- Street number and name
- City, state, zip code
- Approximate matches (e.g., "123 Main St" matches "123 Main Street")
- Abbreviations (e.g., "St" vs "Street", "Rd" vs "Road")

Return ONLY a JSON object with the structure:
{
  "matched_id": "the ID of the best matching record",
  "confidence": "high|medium|low",
  "reasoning": "brief explanation of why this is the best match"
}

If no good match is found, return:
{
  "reasoning": "explanation",
  "confidence": "none",
  "matched_id": null
}"""

    user_prompt = f"""Target address: {address}

Candidate Site Records:
{json.dumps(candidates, indent=2)}

Which candidate best matches the target address?"""

    logger.info("Calling OpenAI to match address: %s", address)

    response = client.chat.completions.create(
        model="gpt-5-mini-2025-08-07",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        response_format={"type": "json_object"},
    )

    result_text = response.choices[0].message.content
    if not result_text:
        logger.error("Empty response from OpenAI")
        return None

    result: dict[str, str | None] = json.loads(result_text)
    matched_id: str | None = result.get("matched_id")
    confidence: str | None = result.get("confidence")
    reasoning: str = result.get("reasoning")

    logger.info(
        "LLM match result: matched_id=%s, confidence=%s, reasoning=%s",
        matched_id,
        confidence,
        reasoning,
    )

    if not matched_id:
        logger.warning("No matching Site Record found by LLM")
        return None

    # Find and return the matching record
    for record in site_records:
        if record.get("id") == matched_id:
            return record

    logger.warning("Matched ID %s not found in site_records", matched_id)
    return None


def find_site_record_by_address(
    *, address: str, stage: str = "1. Looking for Sites"
) -> dict[str, Any] | None:
    """
    Find a Site Record by address using LLM-based matching.

    This function:
    1. Fetches all Site Records with the specified stage
    2. Uses an LLM to match the provided address to the best candidate

    Args:
        address: Address to search for (from email)
        stage: The stage value to filter by (default: "1. Looking for Sites")

    Returns:
        Matched Site Record or None if no match found
    """
    logger.info("Finding site record by address: %s (stage: %s)", address, stage)

    # Get all Site Records with the specified stage
    site_records = get_site_records_by_stage(stage=stage)

    if not site_records:
        logger.warning("No Site Records found with stage '%s'", stage)
        return None

    # Use LLM to match the address
    matched_record = _match_address_with_llm(address=address, site_records=site_records)

    if matched_record:
        logger.info(
            "Found matching Site Record: %s (%s)",
            matched_record.get("title"),
            matched_record.get("id"),
        )
    else:
        logger.warning("No matching Site Record found for address: %s", address)

    return matched_record


def search_site_records_by_address(
    *, address: str, cfg: WrikeConfig | None = None
) -> list[dict[str, Any]]:
    """
    Search for Site Records by address.

    Args:
        address: Full address to search for
        cfg: Wrike config (loads from env if not provided)

    Returns:
        List of matching site records
    """
    if cfg is None:
        cfg = load_wrike_config()

    # Search using Wrike's query API
    # We'll search in the space for folders matching the address
    url = f"{WRIKE_API_BASE_URL}/spaces/{WRIKE_SPACE_ID}/folders"

    logger.info("Searching for site records with address: %s", address)

    resp = requests.get(
        url,
        headers=_wrike_headers(cfg.access_token),
        timeout=WRIKE_TIMEOUT_SECONDS,
    )
    _raise_for_wrike_error(resp)

    payload: dict[str, Any] = resp.json()
    data = payload.get("data", [])

    # Filter for Site Records (by customItemTypeId) and matching address
    matching_records: list[dict[str, Any]] = []
    address_lower = address.lower().strip()

    for item in data:
        if not isinstance(item, dict):
            continue

        # Check if it's a Site Record
        if item.get("customItemTypeId") != WRIKE_SITE_RECORD_TYPE_ID:
            continue

        # Check title or custom fields for address match
        title = item.get("title", "")
        if address_lower in title.lower():
            matching_records.append(item)
            continue

        # Check custom fields
        custom_fields = item.get("customFields", [])
        for field in custom_fields:
            if not isinstance(field, dict):
                continue

            field_id = field.get("id")
            field_value = field.get("value", "")

            # Check address fields
            if field_id in [
                WRIKE_CUSTOM_FIELDS["address"],
                WRIKE_CUSTOM_FIELDS["address_alt"],
            ]:
                if (
                    isinstance(field_value, str)
                    and address_lower in field_value.lower()
                ):
                    matching_records.append(item)
                    break

    logger.info("Found %d matching site records", len(matching_records))
    return matching_records


def get_site_record_by_id(
    *, record_id: str, cfg: WrikeConfig | None = None
) -> dict[str, Any]:
    """
    Get a Site Record by its Wrike ID.

    Args:
        record_id: Wrike folder/project ID
        cfg: Wrike config (loads from env if not provided)

    Returns:
        Site record data
    """
    if cfg is None:
        cfg = load_wrike_config()

    url = f"{WRIKE_API_BASE_URL}/folders/{record_id}"

    logger.info("Fetching site record: %s", record_id)

    resp = requests.get(
        url,
        headers=_wrike_headers(cfg.access_token),
        timeout=WRIKE_TIMEOUT_SECONDS,
    )
    _raise_for_wrike_error(resp)

    payload: dict[str, Any] = resp.json()
    data = payload.get("data", [])

    if not data:
        raise WrikeError(f"Site record not found: {record_id}")

    record = data[0]
    logger.info("Site record fetched: %s", record.get("title"))
    return record


def update_site_record(
    *,
    record_id: str,
    custom_fields: list[dict[str, Any]] | None = None,
    description: str | None = None,
    cfg: WrikeConfig | None = None,
) -> dict[str, Any]:
    """
    Update a Site Record with new data.

    Note: This field requires explicit permission to be updated. Since the creds are on my account, I added sahil.marwaha@trilogy.com as an editor to this custom field.

    Args:
        record_id: Wrike folder/project ID
        custom_fields: List of custom field updates [{"id": "...", "value": "..."}]
        description: Updated description (optional)
        cfg: Wrike config (loads from env if not provided)

    Returns:
        Updated site record data
    """
    if cfg is None:
        cfg = load_wrike_config()

    url = f"{WRIKE_API_BASE_URL}/folders/{record_id}"

    body: dict[str, Any] = {}

    if custom_fields:
        body["customFields"] = custom_fields

    if description is not None:
        body["description"] = description

    if not body:
        raise WrikeError("No updates provided (custom_fields or description required)")

    logger.info(
        "Updating site record %s with %d custom fields",
        record_id,
        len(custom_fields or []),
    )
    # logger.info("Request URL: %s", url)
    # logger.info("Request body: %s", json.dumps(body, indent=2))

    resp = requests.put(
        url,
        headers={
            **_wrike_headers(cfg.access_token),
            "Content-Type": "application/json",
        },
        json=body,
        timeout=WRIKE_TIMEOUT_SECONDS,
    )
    _raise_for_wrike_error(resp)

    payload: dict[str, Any] = resp.json()
    # logger.info("Payload: %s", json.dumps(payload, indent=2))
    data = payload.get("data", [])

    if not data:
        raise WrikeError(f"Site record update returned no data: {record_id}")

    updated_record = data[0]
    logger.info("Site record updated: %s", updated_record.get("title"))
    return updated_record


def update_site_record_with_location_data(
    *,
    record_id: str,
    square_footage: str | None = None,
    complete_building: str | None = None,
    move_in_ready: str | None = None,
    current_space_usage: str | None = None,
    contact_name: str | None = None,
    contact_email: str | None = None,
    contact_phone: str | None = None,
    cfg: WrikeConfig | None = None,
) -> dict[str, Any]:
    """
    Update a Site Record with location data from parsed email.

    Args:
        record_id: Wrike folder/project ID
        square_footage: Square footage of the space
        complete_building: Whether taking the complete building
        move_in_ready: Whether the space is move-in ready
        current_space_usage: What the space is currently used for
        contact_name: Site POC name
        contact_email: Site POC email
        contact_phone: Site POC phone
        cfg: Wrike config (loads from env if not provided)

    Returns:
        Updated site record data
    """
    if cfg is None:
        cfg = load_wrike_config()

    # Build custom fields list
    fields: list[dict[str, Any]] = []

    # Square footage (numeric field)
    if square_footage is not None:
        try:
            # Parse as float, handle common formats
            sq_ft_clean = square_footage.replace(",", "").strip()
            sq_ft_value = float(sq_ft_clean)
            fields.append(
                {"id": WRIKE_CUSTOM_FIELDS["square_footage"], "value": sq_ft_value}
            )
        except ValueError:
            logger.warning("Could not parse square_footage: %s", square_footage)

    # Get current record and append Real Estate section to existing description
    current_record = get_site_record_by_id(record_id=record_id, cfg=cfg)
    current_description = current_record.get("description", "")

    # Build the Real Estate section with actual values
    real_estate_section = (
        "<br /><b>Real Estate Information</b><br /><ul>"
        f"<li><strong>Square Footage:</strong> {square_footage or 'N/A'}</li>"
        f"<li><strong>Are we taking the complete building?:</strong> {complete_building or 'N/A'}</li>"
        f"<li><strong>Is this move-in ready?:</strong> {move_in_ready or 'N/A'}</li>"
        f"<li><strong>What is the space currently used for?:</strong> {current_space_usage or 'N/A'}</li>"
        f"<li><strong>Site POC Name:</strong> {contact_name or 'N/A'}</li>"
        f"<li><strong>Site POC Email:</strong> {contact_email or 'N/A'}</li>"
        f"<li><strong>Site POC Phone Number:</strong> {contact_phone or 'N/A'}</li>"
        "</ul><br />"
    )

    # Append the Real Estate section to existing description
    updated_description = current_description + real_estate_section
    logger.info("Appended Real Estate Information section to description")

    logger.info("Updating site record %s with location data", record_id)

    return update_site_record(
        record_id=record_id,
        custom_fields=fields if fields else None,
        description=updated_description,
        cfg=cfg,
    )
