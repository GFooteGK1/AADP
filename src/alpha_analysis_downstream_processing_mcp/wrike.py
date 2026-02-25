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
    "loi_signed_date": "IEAGN6I6JUAIOUVH",
    "vendor_team": "IEAGN6I6JUAKDCYE",  # Vendor Team (LinkToDatabase)
    "google_folder": "IEAGN6I6JUAIKGJH",  # Google Folder (Text) - Drive folder link
}

# Reverse mapping: ID -> name
WRIKE_CUSTOM_FIELD_NAMES = {v: k for k, v in WRIKE_CUSTOM_FIELDS.items()}

# Required vendor team members to set during downstream processing
# Monica Swannie -> RE5174381
# Shinpei Kuo -> RE5174384
WRIKE_REQUIRED_VENDOR_TEAM_IDS: list[str] = ["RE5174381", "RE5174384"]


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


def enrich_custom_fields_with_names(record: dict[str, Any]) -> dict[str, Any]:
    """
    Enrich custom fields in a Wrike record with human-readable names.

    Args:
        record: Wrike site record

    Returns:
        Record with enriched customFields (adds "name" key to each field)
    """
    custom_fields = record.get("customFields", [])
    if not isinstance(custom_fields, list):
        return record

    enriched_fields = []
    for field in custom_fields:
        if not isinstance(field, dict):
            enriched_fields.append(field)
            continue

        field_id = field.get("id")
        # If no mapping found, use the ID itself as the name
        field_name = WRIKE_CUSTOM_FIELD_NAMES.get(field_id, field_id)

        # Create enriched field with name
        enriched_field = {
            "name": field_name,
            "id": field_id,
            "value": field.get("value"),
        }
        enriched_fields.append(enriched_field)

    # Return modified record
    enriched_record = {**record, "customFields": enriched_fields}
    return enriched_record


def extract_address_from_record(record: dict[str, Any]) -> str | None:
    """
    Extract address from Wrike Site Record.

    Args:
        record: Wrike site record

    Returns:
        Address string or None if not found
    """
    custom_fields = record.get("customFields", [])
    if not isinstance(custom_fields, list):
        return None

    address_field_id = WRIKE_CUSTOM_FIELDS["address"]

    for field in custom_fields:
        if not isinstance(field, dict):
            continue

        if field.get("id") == address_field_id:
            value = field.get("value", "")
            if isinstance(value, str):
                # Strip HTML tags from address field
                # Wrike stores addresses as: <a ...>ADDRESS</a>
                address = re.sub(r"<[^>]+>", "", value).strip()
                return address if address else None

    return None


def extract_school_type_from_record(record: dict[str, Any]) -> str | None:
    """
    Extract and convert school_type from Wrike Site Record.

    Wrike format: "Growth 250", "Microschool 25", "Flagship 1000"
    Internal format: "250", "micro", "1000"

    Args:
        record: Wrike site record

    Returns:
        School type in internal format or None if not found
    """
    custom_fields = record.get("customFields", [])
    if not isinstance(custom_fields, list):
        return None

    school_type_field_id = WRIKE_CUSTOM_FIELDS["school_type"]

    for field in custom_fields:
        if not isinstance(field, dict):
            continue

        if field.get("id") == school_type_field_id:
            value = field.get("value", "")
            if not isinstance(value, str):
                continue

            # Map Wrike format to internal format
            if "Microschool 25" in value or "Micro" in value:
                return "micro"
            elif "Growth 250" in value or value == "250":
                return "250"
            elif "Flagship 1000" in value or value == "1000":
                return "1000"

    return None


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
    required_owner_id: str | None = None,
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

    if required_owner_id:
        logger.info(
            "Filtering Site Records by stage '%s' and ownerId '%s'",
            stage,
            required_owner_id,
        )
    else:
        logger.info("Filtering Site Records by stage '%s' (no owner filter)", stage)

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

            # Require ownerId match before stage filtering (if configured)
            if required_owner_id:
                owner_ids = None
                if isinstance(item.get("project"), dict):
                    owner_ids = item.get("project", {}).get("ownerIds")
                if owner_ids is None:
                    owner_ids = item.get("ownerIds")

                if (
                    not isinstance(owner_ids, list)
                    or required_owner_id not in owner_ids
                ):
                    logger.debug(
                        "Skipping Site Record %s due to missing ownerId '%s' (ownerIds=%s)",
                        item.get("id"),
                        required_owner_id,
                        owner_ids,
                    )
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
  "reasoning": "brief explanation of why this is the best match"
}

If no good match is found, return:
{
  "reasoning": "explanation",
  "matched_id": null
}
Only return a matched_id if you are confident about the match, and there are only minor variations in the address (as mentioned above). It is completely acceptable to return null if you are not confident about the match.
"""

    user_prompt = f"""Target address: {address}

Candidate Site Records:
{json.dumps(candidates, indent=2)}

Which candidate best matches the target address?"""

    logger.info("Calling OpenAI to match address: %s", address)

    response = client.chat.completions.create(
        model="gpt-5.2-2025-12-11",
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
    reasoning: str = result.get("reasoning")

    logger.info(
        "LLM match result: matched_id=%s, reasoning=%s",
        matched_id,
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
    site_records = get_site_records_by_stage(
        stage=stage,
        required_owner_id="KUAUQW6O",  # Greg Foote
    )

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


def resolve_permalink_to_id(*, permalink: str, cfg: WrikeConfig | None = None) -> str:
    """
    Resolve a Wrike permalink to a folder/record ID.

    Args:
        permalink: Wrike permalink (e.g., "https://www.wrike.com/open.htm?id=4348902419")
        cfg: Wrike config (loads from env if not provided)

    Returns:
        Wrike folder/record ID

    Raises:
        WrikeError: If permalink cannot be resolved
    """
    if cfg is None:
        cfg = load_wrike_config()

    url = f"{WRIKE_API_BASE_URL}/folders"

    logger.info("Resolving permalink to record ID: %s", permalink)

    resp = requests.get(
        url,
        headers=_wrike_headers(cfg.access_token),
        params={"permalink": permalink},
        timeout=WRIKE_TIMEOUT_SECONDS,
    )
    _raise_for_wrike_error(resp)

    payload: dict[str, Any] = resp.json()
    data = payload.get("data", [])

    if not data:
        raise WrikeError(f"Could not resolve permalink: {permalink}")

    record = data[0]
    record_id = record.get("id")

    if not isinstance(record_id, str):
        raise WrikeError(f"Invalid record ID from permalink: {permalink}")

    logger.info("Resolved permalink to record ID: %s", record_id)
    return record_id


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
    loi_signed_date: str | None = None,
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

    This function always updates the overall_site_stage to "2. Evaluating Potential Sites (LOI)"
    along with the location data.

    Args:
        record_id: Wrike folder/project ID
        loi_signed_date: LOI signed date in DD/MM/YYYY format
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

    # Always update overall_site_stage to "2. Evaluating Potential Sites (LOI)"
    fields.append(
        {
            "id": WRIKE_CUSTOM_FIELDS["overall_site_stage"],
            "value": "2. Evaluating Potential Sites (LOI)",
        }
    )
    logger.info("Adding overall_site_stage update to custom fields")

    # LOI signed date (date field)
    if loi_signed_date is not None:
        loi_signed_date_clean = loi_signed_date.strip()
        if loi_signed_date_clean:
            fields.append(
                {
                    "id": WRIKE_CUSTOM_FIELDS["loi_signed_date"],
                    "value": loi_signed_date_clean,
                }
            )
            logger.info(
                "Adding loi_signed_date update to custom fields: %s",
                loi_signed_date_clean,
            )
        else:
            logger.warning(
                "Received loi_signed_date but it was empty after trimming; skipping field update"
            )

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

    # Get current record for existing field state and description append
    current_record = get_site_record_by_id(record_id=record_id, cfg=cfg)
    current_description = current_record.get("description", "")

    # Vendor Team (LinkToDatabase): always set to the required two IDs
    vendor_team_value = json.dumps(WRIKE_REQUIRED_VENDOR_TEAM_IDS)
    fields.append(
        {"id": WRIKE_CUSTOM_FIELDS["vendor_team"], "value": vendor_team_value}
    )
    logger.info(
        "Adding vendor_team update to custom fields: ids=%s",
        WRIKE_REQUIRED_VENDOR_TEAM_IDS,
    )

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
