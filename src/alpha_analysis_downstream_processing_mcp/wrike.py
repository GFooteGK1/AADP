"""Wrike integration for updating Site Records with location data."""

import json
import logging
import math
import os
import re
from dataclasses import dataclass
from datetime import datetime
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

# US state geographic centroids (latitude, longitude) for proximity calculation
US_STATE_CENTROIDS: dict[str, tuple[float, float]] = {
    "AL": (32.806671, -86.791130),
    "AK": (61.370716, -152.404419),
    "AZ": (33.729759, -111.431221),
    "AR": (34.969704, -92.373123),
    "CA": (36.116203, -119.681564),
    "CO": (39.059811, -105.311104),
    "CT": (41.597782, -72.755371),
    "DE": (39.318523, -75.507141),
    "DC": (38.897438, -77.026817),
    "FL": (27.766279, -81.686783),
    "GA": (33.040619, -83.643074),
    "HI": (21.094318, -157.498337),
    "ID": (44.240459, -114.478828),
    "IL": (40.349457, -88.986137),
    "IN": (39.849426, -86.258278),
    "IA": (42.011539, -93.210526),
    "KS": (38.526600, -96.726486),
    "KY": (37.668140, -84.670067),
    "LA": (31.169960, -91.867805),
    "ME": (44.693947, -69.381927),
    "MD": (39.063946, -76.802101),
    "MA": (42.230171, -71.530106),
    "MI": (43.326618, -84.536095),
    "MN": (45.694454, -93.900192),
    "MS": (32.741646, -89.678696),
    "MO": (38.456085, -92.288368),
    "MT": (46.921925, -110.454353),
    "NE": (41.125370, -98.268082),
    "NV": (38.313515, -117.055374),
    "NH": (43.452492, -71.563896),
    "NJ": (40.298904, -74.521011),
    "NM": (34.840515, -106.248482),
    "NY": (42.165726, -74.948051),
    "NC": (35.630066, -79.806419),
    "ND": (47.528912, -99.784012),
    "OH": (40.388783, -82.764915),
    "OK": (35.565342, -96.928917),
    "OR": (44.572021, -122.070938),
    "PA": (40.590752, -77.209755),
    "RI": (41.680893, -71.511780),
    "SC": (33.856892, -80.945007),
    "SD": (44.299782, -99.438828),
    "TN": (35.747845, -86.692345),
    "TX": (31.054487, -97.563461),
    "UT": (40.150032, -111.862434),
    "VT": (44.045876, -72.710686),
    "VA": (37.769337, -78.169968),
    "WA": (47.400902, -121.490494),
    "WV": (38.491226, -80.954453),
    "WI": (44.268543, -89.616508),
    "WY": (42.755966, -107.302490),
}

# Required vendor team members to set during downstream processing
# Monica Swannie -> RE5174381
# Shinpei Kuo -> RE5174384
WRIKE_REQUIRED_VENDOR_TEAM_IDS: list[str] = ["RE5174381", "RE5174384"]

# P1 Accountable contact pools by school type
# Growth (250) / Flagship (1000): Thomas Barrow, Israe Zizaoui
# Microschool (micro): Devin Bates, Robbie Forrest, Andrea Ewalefo
# JC Fisher: excluded from all assignments (returns [])
_P1_GROWTH_FLAGSHIP_CONTACTS: set[str] = {"KUAWCQTS", "KUAWVGG4"}
_P1_MICROSCHOOL_CONTACTS: set[str] = {"KUAWS3KA", "KUAUVTLM", "KUAWDEOX"}


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
            elif "JC Fisher" in value:
                return "jc_fisher"

    return None


def _haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate great-circle distance in km between two lat/lon points."""
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlon / 2) ** 2
    )
    return R * 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))


def extract_state_from_address(address: str) -> str | None:
    """
    Extract 2-letter US state code from a full address string.

    Handles formats like "123 Main St, Austin, TX 78701" or "Austin, TX".
    """
    address_upper = address.upper().strip()
    # Match ", ST ZIP" or ", ST" at end of string
    match = re.search(r",\s*([A-Z]{2})(?:\s+\d{5}(?:-\d{4})?)?\s*$", address_upper)
    if match:
        state = match.group(1)
        if state in US_STATE_CENTROIDS:
            return state
    return None


def extract_p1_accountable_from_record(record: dict[str, Any]) -> list[str]:
    """Extract P1 Accountable contact IDs from a Wrike record's custom fields."""
    custom_fields = record.get("customFields", [])
    if not isinstance(custom_fields, list):
        return []

    p1_field_id = WRIKE_CUSTOM_FIELDS["p1_accountable"]

    for field in custom_fields:
        if not isinstance(field, dict):
            continue
        if field.get("id") != p1_field_id:
            continue
        value = field.get("value")
        if not value:
            return []
        if isinstance(value, list):
            return [str(v) for v in value if v]
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
                if isinstance(parsed, list):
                    return [str(v) for v in parsed if v]
                if isinstance(parsed, str):
                    return [part.strip() for part in parsed.split(",") if part.strip()]
                return [str(parsed)] if parsed else []
            except (json.JSONDecodeError, ValueError):
                return [part.strip() for part in value.split(",") if part.strip()]

    return []


def _pick_contact_with_fewest_sites(
    candidates: list[str], contact_total_sites: dict[str, int]
) -> str:
    """Pick the contact with the fewest total sites. Break ties alphabetically by ID."""
    return min(candidates, key=lambda cid: (contact_total_sites.get(cid, 0), cid))


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


def get_all_site_records(*, cfg: WrikeConfig | None = None) -> list[dict[str, Any]]:
    """
    Get all Site Records from the Wrike space regardless of stage.

    Used for P1 Accountable assignment logic — we need to see all active work
    across every stage to understand who is working which states.

    Returns:
        List of all Site Records
    """
    if cfg is None:
        cfg = load_wrike_config()

    folder_ids = _get_all_folder_ids(access_token=cfg.access_token)
    logger.info(
        "Fetching all Site Records (any stage) from %d folders", len(folder_ids)
    )

    batch_size = 100
    all_site_records: list[dict[str, Any]] = []

    for i in range(0, len(folder_ids), batch_size):
        batch = folder_ids[i : i + batch_size]
        ids_param = ",".join(batch)

        url = f"{WRIKE_API_BASE_URL}/folders/{ids_param}"

        resp = requests.get(
            url,
            headers=_wrike_headers(cfg.access_token),
            params={"fields": '["customItemTypeId"]'},
            timeout=WRIKE_TIMEOUT_SECONDS,
        )
        _raise_for_wrike_error(resp)

        payload: dict[str, Any] = resp.json()
        data = payload.get("data", [])

        if not isinstance(data, list):
            continue

        for item in data:
            if not isinstance(item, dict):
                continue
            if item.get("customItemTypeId") == WRIKE_SITE_RECORD_TYPE_ID:
                all_site_records.append(item)

    logger.info("Found %d total Site Records across all stages", len(all_site_records))
    return all_site_records


def _eligible_contacts_for_school_type(
    school_type: str | None,
) -> set[str] | None:
    """Return the set of eligible P1 contact IDs for a school type.

    Returns None when ALL contacts (from any pool) are eligible (unknown type).
    Returns an empty set for JC Fisher (no assignment allowed).
    """
    if school_type in ("250", "1000"):
        return _P1_GROWTH_FLAGSHIP_CONTACTS
    if school_type == "micro":
        return _P1_MICROSCHOOL_CONTACTS
    if school_type == "jc_fisher":
        return set()
    # Unknown / None → all pooled contacts are eligible
    return _P1_GROWTH_FLAGSHIP_CONTACTS | _P1_MICROSCHOOL_CONTACTS


def assign_p1_accountable_for_new_site(
    *,
    state: str,
    school_type: str | None = None,
    cfg: WrikeConfig | None = None,
) -> list[str]:
    """
    Determine which P1 Accountable contact to assign to a new site.

    Assignment rules (in priority order):

    1. If one or more P1 Accountable contacts are already working in the target
       state, assign to the one with the fewest total sites overall.

    2. If nobody is working in the target state (new state), find the P1
       Accountable working in the geographically nearest state (by centroid
       distance) and assign to the one with the fewest total sites overall.

    3. If no P1 Accountable exists anywhere, return [].

    Contact pools are restricted by school type:
    - Growth (250) / Flagship (1000): Thomas Barrow, Israe Zizaoui
    - Microschool (micro): Devin Bates, Robbie Forrest, Andrea Ewalefo
    - JC Fisher: excluded from all assignments (returns [])

    Ties in total-site count are broken by contact ID (alphabetical order) so
    the result is always deterministic.

    Args:
        state: Two-letter US state code for the new site (e.g. "TX")
        school_type: Internal school type ("250", "1000", "micro", "jc_fisher")
        cfg: Wrike config (loads from env if not provided)

    Returns:
        List containing the single assigned contact ID, or [] if none found.
    """
    state_upper = state.upper().strip()
    logger.info(
        "Assigning P1 Accountable for state: %s, school_type: %s",
        state_upper,
        school_type,
    )

    # Determine eligible contacts based on school type
    eligible = _eligible_contacts_for_school_type(school_type)
    if eligible is not None and not eligible:
        logger.info(
            "School type '%s' is excluded from P1 assignment; returning []",
            school_type,
        )
        return []

    all_records = get_all_site_records(cfg=cfg)

    # Build lookup tables from existing records that already have a P1 Accountable
    # state_contacts: state code -> set of contact IDs working there
    # contact_total_sites: contact ID -> total site count across all states
    state_contacts: dict[str, set[str]] = {}
    contact_total_sites: dict[str, int] = {}

    for record in all_records:
        contact_ids = extract_p1_accountable_from_record(record)
        if not contact_ids:
            continue

        address = extract_address_from_record(record)
        if not address:
            continue

        record_state = extract_state_from_address(address)
        if not record_state:
            continue

        if record_state not in state_contacts:
            state_contacts[record_state] = set()

        for cid in contact_ids:
            # Only count contacts that are in the eligible pool
            if eligible is not None and cid not in eligible:
                continue
            state_contacts[record_state].add(cid)
            contact_total_sites[cid] = contact_total_sites.get(cid, 0) + 1

    if not contact_total_sites:
        logger.warning(
            "No eligible P1 Accountable found in any existing site record; "
            "skipping assignment (school_type=%s)",
            school_type,
        )
        return []

    # Rule 1: P1 Accountable already working the target state
    if state_upper in state_contacts and state_contacts[state_upper]:
        candidates = list(state_contacts[state_upper])
        assigned = _pick_contact_with_fewest_sites(candidates, contact_total_sites)
        logger.info(
            "P1 assignment (Rule 1 – same state): state=%s, candidates=%s, assigned=%s "
            "(total sites: %d)",
            state_upper,
            candidates,
            assigned,
            contact_total_sites.get(assigned, 0),
        )
        return [assigned]

    # Rule 2: New state — find nearest state with a P1 Accountable
    if state_upper not in US_STATE_CENTROIDS:
        logger.warning(
            "State '%s' not found in US_STATE_CENTROIDS; cannot find nearest",
            state_upper,
        )
        return []

    target_lat, target_lon = US_STATE_CENTROIDS[state_upper]

    nearest_state: str | None = None
    nearest_distance = float("inf")

    for existing_state, contacts in state_contacts.items():
        if not contacts or existing_state not in US_STATE_CENTROIDS:
            continue
        lat, lon = US_STATE_CENTROIDS[existing_state]
        dist = _haversine_distance(target_lat, target_lon, lat, lon)
        if dist < nearest_distance:
            nearest_distance = dist
            nearest_state = existing_state

    if nearest_state is None:
        logger.warning("Could not find any state with a P1 Accountable to fall back to")
        return []

    candidates = list(state_contacts[nearest_state])
    assigned = _pick_contact_with_fewest_sites(candidates, contact_total_sites)
    logger.info(
        "P1 assignment (Rule 2 – nearest state): target=%s, nearest=%s (%.0f km away), "
        "candidates=%s, assigned=%s (total sites: %d)",
        state_upper,
        nearest_state,
        nearest_distance,
        candidates,
        assigned,
        contact_total_sites.get(assigned, 0),
    )
    return [assigned]


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
    responsible_ids: list[str] | None = None,
    cfg: WrikeConfig | None = None,
) -> dict[str, Any]:
    """
    Update a Site Record with new data.

    Note: This field requires explicit permission to be updated. Since the creds are on my account, I added sahil.marwaha@trilogy.com as an editor to this custom field.

    Args:
        record_id: Wrike folder/project ID
        custom_fields: List of custom field updates [{"id": "...", "value": "..."}]
        description: Updated description (optional)
        responsible_ids: Target Wrike user IDs for Site Record default assignee(s).
            Wrike folders/projects do not support ownerIds overwrite directly, so
            this is applied as overwrite semantics via project.ownersAdd/ownersRemove.
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

    current_record_for_noop: dict[str, Any] | None = None
    if responsible_ids is not None:
        target_owner_ids = list(dict.fromkeys(responsible_ids))
        current_record = get_site_record_by_id(record_id=record_id, cfg=cfg)
        current_record_for_noop = current_record
        current_owner_ids = (
            current_record.get("project", {}).get("ownerIds")
            or current_record.get("ownerIds")
            or []
        )
        if not isinstance(current_owner_ids, list):
            current_owner_ids = []

        owners_to_add = [
            oid for oid in target_owner_ids if oid not in current_owner_ids
        ]
        owners_to_remove = [
            oid for oid in current_owner_ids if oid not in target_owner_ids
        ]

        project_updates: dict[str, Any] = {}
        if owners_to_add:
            project_updates["ownersAdd"] = owners_to_add
        if owners_to_remove:
            project_updates["ownersRemove"] = owners_to_remove
        if project_updates:
            body["project"] = project_updates

        logger.info(
            "Overwriting Site Record owners for %s via project owner deltas: current=%s target=%s add=%s remove=%s",
            record_id,
            current_owner_ids,
            target_owner_ids,
            owners_to_add,
            owners_to_remove,
        )

    if not body and current_record_for_noop is not None:
        logger.info(
            "No Site Record update call required for %s; owners already in target state",
            record_id,
        )
        return current_record_for_noop

    if not body:
        raise WrikeError(
            "No updates provided (custom_fields, description, or responsible_ids required)"
        )

    logger.info(
        "Updating site record %s with %d custom fields, responsible_ids=%s",
        record_id,
        len(custom_fields or []),
        responsible_ids,
    )

    def _send_update(update_body: dict[str, Any]) -> dict[str, Any]:
        # Wrike Modify Folder expects form parameters; complex values
        # (arrays/objects) must be JSON-encoded strings.
        request_data: dict[str, str] = {}
        for key, value in update_body.items():
            if isinstance(value, (list, dict)):
                request_data[key] = json.dumps(value)
            elif isinstance(value, bool):
                request_data[key] = "true" if value else "false"
            else:
                request_data[key] = str(value)

        resp = requests.put(
            url,
            headers=_wrike_headers(cfg.access_token),
            data=request_data,
            timeout=WRIKE_TIMEOUT_SECONDS,
        )
        _raise_for_wrike_error(resp)

        payload: dict[str, Any] = resp.json()
        data = payload.get("data", [])
        if not data:
            raise WrikeError(f"Site record update returned no data: {record_id}")
        return data[0]

    updated_record = _send_update(body)
    logger.info("Site record updated: %s", updated_record.get("title"))
    return updated_record


def create_comment(
    *,
    record_id: str,
    text: str,
    cfg: WrikeConfig | None = None,
) -> dict[str, Any]:
    """Post a comment on a Wrike folder/project (Site Record).

    Args:
        record_id: Wrike folder/project ID
        text: Comment text (supports HTML)
        cfg: Wrike config (loads from env if not provided)

    Returns:
        Created comment data from Wrike API
    """
    if cfg is None:
        cfg = load_wrike_config()

    url = f"{WRIKE_API_BASE_URL}/folders/{record_id}/comments"

    resp = requests.post(
        url,
        headers=_wrike_headers(cfg.access_token),
        data={"text": text},
        timeout=WRIKE_TIMEOUT_SECONDS,
    )
    _raise_for_wrike_error(resp)

    payload: dict[str, Any] = resp.json()
    data = payload.get("data", [])
    if not data:
        raise WrikeError(f"Comment creation returned no data for record: {record_id}")

    logger.info("Created comment on record %s", record_id)
    return data[0]


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
    p1_accountable: list[str] | None = None,
    responsible_ids: list[str] | None = None,
    email_body: str | None = None,
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
        p1_accountable: List of Wrike contact IDs to assign as P1 Accountable custom field
        responsible_ids: Target Wrike user IDs for default Site Record Assignee(s)
            (synced to project owners)
        email_body: Full body text of the new site email to append to the description
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

    # LOI signed date (date field) - Wrike expects YYYY-MM-DD
    if loi_signed_date is not None:
        loi_signed_date_clean = loi_signed_date.strip()
        if loi_signed_date_clean:
            loi_signed_date_wrike = loi_signed_date_clean
            try:
                loi_signed_date_wrike = datetime.strptime(
                    loi_signed_date_clean, "%m/%d/%Y"
                ).strftime("%Y-%m-%d")
                logger.info(
                    "Normalized loi_signed_date for Wrike: input=%s output=%s",
                    loi_signed_date_clean,
                    loi_signed_date_wrike,
                )
            except ValueError:
                logger.warning(
                    "Could not normalize loi_signed_date '%s' from MM/DD/YYYY to YYYY-MM-DD; sending raw value",
                    loi_signed_date_clean,
                )
            fields.append(
                {
                    "id": WRIKE_CUSTOM_FIELDS["loi_signed_date"],
                    "value": loi_signed_date_wrike,
                }
            )
            logger.info(
                "Adding loi_signed_date update to custom fields: %s",
                loi_signed_date_wrike,
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
            # Wrike customFields values are safest when sent as strings.
            sq_ft_value_str = (
                str(int(sq_ft_value)) if sq_ft_value.is_integer() else str(sq_ft_value)
            )
            fields.append(
                {"id": WRIKE_CUSTOM_FIELDS["square_footage"], "value": sq_ft_value_str}
            )
            logger.info(
                "Adding square_footage update to custom fields: input=%s normalized=%s",
                square_footage,
                sq_ft_value_str,
            )
        except ValueError:
            logger.warning("Could not parse square_footage: %s", square_footage)

    # Get current record for existing field state and description append
    current_record = get_site_record_by_id(record_id=record_id, cfg=cfg)
    current_description = current_record.get("description", "")

    # School Type: infer from square footage only when not already set on the record
    # Ranges: Micro = 2,500–20,000 | Growth = 20,001–50,000 | Flagship = 50,001–150,000
    existing_school_type = extract_school_type_from_record(current_record)
    if not existing_school_type and square_footage is not None:
        try:
            sq_ft_infer = float(square_footage.replace(",", "").strip())
            inferred_school_type: str
            if sq_ft_infer <= 20000:
                inferred_school_type = "Microschool 25"
            elif sq_ft_infer <= 50000:
                inferred_school_type = "Growth 250"
            else:
                inferred_school_type = "Flagship 1000"

            fields.append(
                {
                    "id": WRIKE_CUSTOM_FIELDS["school_type"],
                    "value": inferred_school_type,
                }
            )
            logger.info(
                "Inferred school_type from square footage (%.0f sq ft): %s",
                sq_ft_infer,
                inferred_school_type,
            )
        except ValueError:
            logger.warning(
                "Could not parse square_footage for school type inference: %s",
                square_footage,
            )

    # Vendor Team (LinkToDatabase): always set to the required two IDs
    vendor_team_value = json.dumps(WRIKE_REQUIRED_VENDOR_TEAM_IDS)
    fields.append(
        {"id": WRIKE_CUSTOM_FIELDS["vendor_team"], "value": vendor_team_value}
    )
    logger.info(
        "Adding vendor_team update to custom fields: ids=%s",
        WRIKE_REQUIRED_VENDOR_TEAM_IDS,
    )

    # P1 Accountable (Contacts): set when an assignment was determined
    if p1_accountable:
        fields.append(
            {
                "id": WRIKE_CUSTOM_FIELDS["p1_accountable"],
                # Contacts custom field expects comma-delimited contact IDs.
                "value": ",".join([cid.strip() for cid in p1_accountable if cid.strip()]),
            }
        )
        logger.info("Adding p1_accountable update to custom fields: %s", p1_accountable)

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

    result = update_site_record(
        record_id=record_id,
        custom_fields=fields if fields else None,
        description=updated_description,
        responsible_ids=responsible_ids if responsible_ids else None,
        cfg=cfg,
    )

    # Post the email body as a comment on the record
    if email_body:
        email_body_html = email_body.replace("\n", "<br />")
        comment_text = (
            "<b>New Site Email Body</b><br />"
            f"<p>{email_body_html}</p>"
        )
        try:
            create_comment(record_id=record_id, text=comment_text, cfg=cfg)
            logger.info("Posted email body as comment on record %s", record_id)
        except Exception as e:
            logger.error("Failed to post email body comment on record %s: %s", record_id, e)

    return result
