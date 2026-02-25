"""MCP server for Alpha analysis downstream processing and automation."""

from __future__ import annotations

from datetime import datetime
import logging
import re
from typing import Any

from dotenv import load_dotenv
from mcp.server import FastMCP

from .config import get_settings
from .email_sender import EmailConfig, LOIEmailData, send_email, send_loi_email
from .google_client import GoogleClient
from .presentation import (
    ENROLLMENT_DASHBOARD_TABLE_COL,
    ENROLLMENT_DASHBOARD_TABLE_ID,
    ENROLLMENT_DASHBOARD_TABLE_ROW,
    PRESENTATION_FOLDER_ID,
    TEMPLATE_PRESENTATION_ID,
    build_dashboard_link_updates,
    build_presentation_updates,
    extract_property_features_from_description,
    extract_scores_from_wrike_record,
    geocode_address,
)
from .utils import (
    download_pdf_from_url,
    extract_enrollment_dashboard_url,
    extract_sir_url_from_description,
)
from .wrike import (
    WRIKE_CUSTOM_FIELDS,
    enrich_custom_fields_with_names,
    extract_address_from_record,
    extract_school_type_from_record,
    find_site_record_by_address,
    get_site_record_by_id,
    resolve_permalink_to_id,
    update_site_record,
    update_site_record_with_location_data,
)

# Load environment variables from the project-root .env if present
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(),  # stderr for MCP protocol compatibility
    ],
)
logger = logging.getLogger(__name__)
logger.info("=" * 80)
logger.info("Alpha Analysis Downstream Processing MCP server starting")

mcp = FastMCP("alpha-analysis-downstream-processing-mcp")


DATE_MM_DD_YYYY_REGEX = re.compile(r"^\d{2}/\d{2}/\d{4}$")


def _is_valid_mm_dd_yyyy(date_str: str) -> bool:
    """Validate date string in strict MM/DD/YYYY format."""
    if not DATE_MM_DD_YYYY_REGEX.fullmatch(date_str):
        return False

    try:
        datetime.strptime(date_str, "%m/%d/%Y")
    except ValueError:
        return False

    return True


@mcp.tool()
async def update_wrike_site_record(
    street_address: str,
    city: str,
    state: str,
    zip_code: str,
    loi_signed_date: str,
    contact_name: str,
    contact_email: str,
    contact_phone: str,
    square_footage: str,
    complete_building: str,
    move_in_ready: str,
    current_space_usage: str,
) -> dict[str, Any]:
    """Update a Wrike Site Record with location data from parsed email.

    This tool:
    - Finds matching Site Record with stage "1. Looking for Sites"
    - Updates overall_site_stage to "2. Evaluating Potential Sites (LOI)"
    - Updates location data (square footage, contact info, property details)

    Args:
        street_address: Street address only (e.g., "123 Main Street")
        city: City name
        state: Two-letter state code
        zip_code: 5-digit zip code
        loi_signed_date: LOI signed date in MM/DD/YYYY format
        contact_name: Full name of site POC
        contact_email: Email address of site POC
        contact_phone: Phone number in (XXX) XXX-XXXX format
        square_footage: Square footage of the space
        complete_building: Whether taking the complete building (yes/no)
        move_in_ready: Whether the space is move-in ready (yes/no)
        current_space_usage: What the space is currently used for

    Returns:
        Dict containing matched record info and update status
    """
    logger.info("Tool called: update_wrike_site_record")
    logger.info(
        "update_wrike_site_record params: street_address=%s, city=%s, state=%s, zip_code=%s, loi_signed_date=%s, "
        "contact_name=%s, contact_email=%s, contact_phone=%s, square_footage=%s, "
        "complete_building=%s, move_in_ready=%s, current_space_usage=%s",
        street_address,
        city,
        state,
        zip_code,
        loi_signed_date,
        contact_name,
        contact_email,
        contact_phone,
        square_footage,
        complete_building,
        move_in_ready,
        current_space_usage,
    )

    # Validate LOI signed date format before making Wrike calls
    logger.info("Validating loi_signed_date format: %s", loi_signed_date)
    if not _is_valid_mm_dd_yyyy(loi_signed_date):
        logger.error(
            "Invalid loi_signed_date format received: %s (expected MM/DD/YYYY)",
            loi_signed_date,
        )
        return {
            "status": "error",
            "error": "Invalid LOI signed date format",
            "field": "loi_signed_date",
            "expected_format": "MM/DD/YYYY",
            "received_value": loi_signed_date,
            "message": "loi_signed_date must match MM/DD/YYYY (for example, 12/25/2026)",
        }

    # Step 1: Construct full address for matching
    full_address = f"{street_address}, {city}, {state} {zip_code}"
    logger.info("Constructed full address: %s", full_address)

    # Step 2: Find matching Site Record in Wrike
    logger.info("Searching for matching Site Record in Wrike...")
    matched_record = find_site_record_by_address(
        address=full_address, stage="1. Looking for Sites"
    )

    if not matched_record:
        logger.error("No matching Site Record found for address: %s", full_address)
        return {
            "status": "error",
            "error": "No matching Site Record found",
            "address": full_address,
            "message": f"Could not find a Site Record matching '{full_address}' with stage '1. Looking for Sites'",
        }

    # Extract matched record details
    record_id = matched_record.get("id")
    record_title = matched_record.get("title")
    record_permalink = matched_record.get("permalink")
    record_description = matched_record.get("description", "")

    if not record_id or not isinstance(record_id, str):
        logger.error("Invalid record_id from matched record: %s", record_id)
        return {
            "status": "error",
            "error": "Invalid record ID",
            "message": "Matched record has invalid or missing ID",
        }

    logger.info(
        "Found matching Site Record: id=%s, title=%s, permalink=%s",
        record_id,
        record_title,
        record_permalink,
    )

    # Step 3: Update Site Record (stage + location data in one API call)
    logger.info("Updating Site Record with stage and location data...")
    update_successful = False

    try:
        update_site_record_with_location_data(
            record_id=record_id,
            loi_signed_date=loi_signed_date,
            square_footage=square_footage,
            complete_building=complete_building,
            move_in_ready=move_in_ready,
            current_space_usage=current_space_usage,
            contact_name=contact_name,
            contact_email=contact_email,
            contact_phone=contact_phone,
        )
        logger.info("Successfully updated Site Record (stage + location data)")
        update_successful = True
    except Exception as e:
        logger.error("Failed to update Site Record: %s", e)
        update_successful = False

    # Step 4: Return result
    result = {
        "status": "success",
        "matched_record": {
            "id": record_id,
            "title": record_title,
            "permalink": record_permalink,
        },
        "update_successful": update_successful,
        "message": f"{'Successfully' if update_successful else 'Failed to'} updated Wrike Site Record for {full_address} (stage + location data).",
    }

    logger.info("update_wrike_site_record result: %s", result)
    return result


@mcp.tool()
async def get_wrike_site_record(
    wrike_record_id: str | None = None,
    wrike_permalink: str | None = None,
) -> dict[str, Any]:
    """Fetch a Wrike Site Record by ID or permalink.

    This tool:
    - Resolves Wrike record (accepts either ID or permalink)
    - Returns full record data including custom fields

    Args:
        wrike_record_id: Wrike Site Record ID (optional if permalink provided)
        wrike_permalink: Wrike permalink URL (optional if record_id provided)

    Returns:
        Dict with site record data
    """
    logger.info("Tool called: get_wrike_site_record")
    logger.info(
        "get_wrike_site_record params: wrike_record_id=%s, wrike_permalink=%s",
        wrike_record_id,
        wrike_permalink,
    )

    # Resolve record ID if permalink is provided
    if not wrike_record_id and not wrike_permalink:
        return {
            "status": "error",
            "error": "Missing parameter",
            "message": "Either wrike_record_id or wrike_permalink must be provided",
        }

    record_id = wrike_record_id

    if wrike_permalink:
        logger.info("Resolving permalink to record ID...")
        try:
            record_id = resolve_permalink_to_id(permalink=wrike_permalink)
            logger.info("Resolved permalink to record ID: %s", record_id)
        except Exception as e:
            logger.error("Failed to resolve permalink: %s", e)
            return {
                "status": "error",
                "error": "Failed to resolve permalink",
                "message": str(e),
            }

    if not record_id:
        return {
            "status": "error",
            "error": "Invalid record ID",
            "message": "Could not determine record ID",
        }

    # Fetch the Site Record
    logger.info("Fetching Wrike Site Record: %s", record_id)
    try:
        site_record = get_site_record_by_id(record_id=record_id)
        logger.info("Successfully fetched Site Record: %s", site_record.get("title"))

        # Enrich custom fields with readable names
        enriched_record = enrich_custom_fields_with_names(site_record)
        logger.info("Enriched custom fields with readable names")

        result = {
            "status": "success",
            "record": enriched_record,
            "message": f"Successfully fetched Site Record: {site_record.get('title')}",
        }

    except Exception as e:
        logger.error("Failed to fetch Wrike Site Record: %s", e)
        result = {
            "status": "error",
            "error": "Failed to fetch Wrike Site Record",
            "message": str(e),
        }

    logger.info("get_wrike_site_record result status: %s", result.get("status"))
    return result


@mcp.tool()
async def send_loi_notification(
    wrike_record_id: str | None = None,
    wrike_permalink: str | None = None,
) -> dict[str, Any]:
    """Send LOI notification email with SIR report attached.

    This tool:
    - Resolves Wrike record (accepts either ID or permalink)
    - Extracts SIR report URL from description
    - Downloads SIR PDF
    - Extracts school type and address
    - Sends email to CDS with SIR attached

    Args:
        wrike_record_id: Wrike Site Record ID (optional if permalink provided)
        wrike_permalink: Wrike permalink URL (optional if record_id provided)

    Returns:
        Dict with email sending status
    """
    logger.info("Tool called: send_loi_notification")
    logger.info(
        "send_loi_notification params: wrike_record_id=%s, wrike_permalink=%s",
        wrike_record_id,
        wrike_permalink,
    )

    # Resolve record ID if permalink is provided
    if not wrike_record_id and not wrike_permalink:
        return {
            "status": "error",
            "error": "Missing parameter",
            "message": "Either wrike_record_id or wrike_permalink must be provided",
        }

    record_id = wrike_record_id

    if wrike_permalink:
        logger.info("Resolving permalink to record ID...")
        try:
            record_id = resolve_permalink_to_id(permalink=wrike_permalink)
            logger.info("Resolved permalink to record ID: %s", record_id)
        except Exception as e:
            logger.error("Failed to resolve permalink: %s", e)
            return {
                "status": "error",
                "error": "Failed to resolve permalink",
                "message": str(e),
            }

    if not record_id:
        return {
            "status": "error",
            "error": "Invalid record ID",
            "message": "Could not determine record ID",
        }

    # Step 1: Get Wrike record
    logger.info("Fetching Wrike Site Record: %s", record_id)
    try:
        site_record = get_site_record_by_id(record_id=record_id)
        record_title = site_record.get("title", "")
        record_description = site_record.get("description", "")
        logger.info("Fetched Site Record: %s", record_title)
    except Exception as e:
        logger.error("Failed to fetch Wrike Site Record: %s", e)
        return {
            "status": "error",
            "error": "Failed to fetch Wrike Site Record",
            "message": str(e),
        }

    # Step 2: Extract address from record
    logger.info("Extracting address from Site Record...")
    full_address = extract_address_from_record(site_record)

    if not full_address:
        logger.warning("Could not extract address from custom fields, using title")
        full_address = record_title

    logger.info("Address: %s", full_address)

    # Step 3: Extract SIR URL
    logger.info("Extracting SIR report URL from description...")
    sir_url = extract_sir_url_from_description(record_description)

    if not sir_url:
        logger.error("No SIR URL found in Site Record description")
        return {
            "status": "error",
            "error": "No SIR URL found",
            "message": "Could not extract SIR report URL from Site Record description",
        }

    # Step 4: Extract school type
    logger.info("Extracting school type from Wrike record...")
    school_type = extract_school_type_from_record(site_record)

    if not school_type:
        logger.warning("School type not found in Wrike record, defaulting to 'micro'")
        school_type = "micro"

    logger.info("School type: %s", school_type)

    # Step 5: Download SIR and send email
    logger.info("Downloading SIR report PDF from: %s", sir_url)
    try:
        sir_pdf = download_pdf_from_url(sir_url)
        logger.info("Successfully downloaded SIR report (%d bytes)", len(sir_pdf))

        # Send email with SIR report attached
        logger.info("Sending LOI email to CDS...")
        email_result = send_loi_email(
            LOIEmailData(
                full_address=full_address,
                school_type=school_type,
                sir_report_pdf=sir_pdf,
                sir_report_filename=f"SIR_{record_id}.pdf",
            )
        )
        email_sent = email_result.get("success", False)
        email_message_id = email_result.get("message_id")
        logger.info("LOI email sent successfully: %s", email_message_id)

        result = {
            "status": "success",
            "email_sent": email_sent,
            "message_id": email_message_id,
            "sir_url": sir_url,
            "message": f"Successfully sent LOI email for {full_address}",
        }

    except Exception as e:
        logger.error("Failed to download SIR or send email: %s", e)
        result = {
            "status": "error",
            "error": "Failed to send email",
            "sir_url": sir_url,
            "message": str(e),
        }

    logger.info("send_loi_notification result: %s", result)
    return result


@mcp.tool()
async def list_drive_folders(
    drive_parent_folder_id: str | None = None,
) -> dict[str, Any]:
    """List direct child folder names under a Google Drive parent folder.

    Args:
        drive_parent_folder_id: Optional parent folder ID (uses root if not provided)

    Returns:
        Dict containing folder names and count
    """
    logger.info("Tool called: list_drive_folders")
    logger.info(
        "list_drive_folders params: drive_parent_folder_id=%s",
        drive_parent_folder_id,
    )

    try:
        settings = get_settings()
        google_client = GoogleClient.from_oauth_config(
            client_config_path=str(settings.get_client_config_path()),
            token_file_path=str(settings.get_token_file_path()),
            oauth_port=settings.oauth_port,
            scopes=settings.google_scopes,
        )
        logger.info("Google client initialized successfully for folder listing")

        folders = google_client.list_folders(parent_id=drive_parent_folder_id)
        folder_names = [
            folder.get("name", "") for folder in folders if folder.get("name")
        ]
        logger.info(
            "list_drive_folders found %d folders under parent %s",
            len(folder_names),
            drive_parent_folder_id or "root",
        )

        result = {
            "status": "success",
            "drive_parent_folder_id": drive_parent_folder_id or "root",
            "folder_count": len(folder_names),
            "folders": folder_names,
            "message": f"Found {len(folder_names)} folders",
        }
    except Exception as e:
        logger.error("Failed to list Drive folders: %s", e)
        result = {
            "status": "error",
            "error": "Failed to list Drive folders",
            "message": str(e),
        }

    logger.info("list_drive_folders result: %s", result)
    return result


@mcp.tool()
async def create_drive_folder_with_attachments(
    email_id: str,
    folder_name: str,
    drive_parent_folder_id: str | None = None,
    wrike_record_id: str | None = None,
) -> dict[str, Any]:
    """Create a Google Drive folder and upload email attachments.

    This tool:
    - Downloads attachments from a Gmail message
    - Creates a folder in Google Drive
    - Uploads all attachments to that folder

    Args:
        email_id: Gmail message ID
        folder_name: Name for the new Drive folder
        drive_parent_folder_id: Optional parent folder ID (uses root if not provided)
        wrike_record_id: Optional Wrike task ID to update the Google Folder field

    Returns:
        Dict with folder info and upload status
    """
    logger.info("Tool called: create_drive_folder_with_attachments")
    logger.info(
        "create_drive_folder_with_attachments params: email_id=%s, folder_name=%s, "
        "drive_parent_folder_id=%s",
        email_id,
        folder_name,
        drive_parent_folder_id,
    )

    drive_folder_created = False
    drive_folder_id = None
    drive_folder_link = None
    attachments_uploaded = 0
    wrike_update_status: dict[str, Any] = {}

    try:
        # Initialize Google client
        settings = get_settings()
        google_client = GoogleClient.from_oauth_config(
            client_config_path=str(settings.get_client_config_path()),
            token_file_path=str(settings.get_token_file_path()),
            oauth_port=settings.oauth_port,
            scopes=settings.google_scopes,
        )
        logger.info("Google client initialized successfully")

        # Get email attachments
        logger.info("Downloading email attachments...")
        attachments = google_client.get_email_attachments(email_id)
        logger.info("Found %d attachments", len(attachments))

        if not attachments:
            logger.warning("No attachments found in email %s", email_id)
            return {
                "status": "error",
                "error": "No attachments found",
                "message": f"Email {email_id} has no attachments",
            }

        # Create folder in Drive
        logger.info(
            "Creating Drive folder: %s (parent: %s)",
            folder_name,
            drive_parent_folder_id or "root",
        )
        folder = google_client.create_folder(
            name=folder_name, parent_id=drive_parent_folder_id
        )
        drive_folder_created = True
        drive_folder_id = folder.get("id")
        drive_folder_link = folder.get("webViewLink")
        logger.info("Created folder: %s (id: %s)", folder_name, drive_folder_id)

        # Upload each attachment to the folder
        uploaded_files: list[dict[str, Any]] = []
        for attachment in attachments:
            filename = attachment["filename"]
            file_data = attachment["data"]
            mime_type = attachment["mimeType"]

            logger.info("Uploading attachment: %s", filename)
            uploaded_file = google_client.upload_file(
                file_name=filename,
                file_data=file_data,
                mime_type=mime_type,
                parent_folder_id=drive_folder_id,
            )
            attachments_uploaded += 1
            uploaded_files.append(
                {
                    "name": uploaded_file.get("name"),
                    "id": uploaded_file.get("id"),
                    "link": uploaded_file.get("webViewLink"),
                }
            )
            logger.info(
                "Uploaded: %s (id: %s)",
                uploaded_file.get("name"),
                uploaded_file.get("id"),
            )

        logger.info(
            "Successfully uploaded %d attachments to folder %s",
            attachments_uploaded,
            drive_folder_id,
        )

        # Optionally update Wrike "Google Folder" custom field
        if wrike_record_id and drive_folder_link:
            try:
                logger.info(
                    "Updating Wrike record %s with Google Folder link", wrike_record_id
                )
                update_site_record(
                    record_id=wrike_record_id,
                    custom_fields=[
                        {
                            "id": WRIKE_CUSTOM_FIELDS["google_folder"],
                            "value": drive_folder_link,
                        }
                    ],
                )
                logger.info("Wrike Google Folder field updated successfully")
                wrike_update_status = {"status": "success"}
            except Exception as wrike_err:
                logger.error(
                    "Failed to update Wrike Google Folder field: %s", wrike_err
                )
                wrike_update_status = {
                    "status": "error",
                    "message": str(wrike_err),
                }
        elif wrike_record_id and not drive_folder_link:
            logger.warning(
                "wrike_record_id provided but drive_folder_link is None; skipping Wrike update"
            )
            wrike_update_status = {
                "status": "skipped",
                "message": "No folder link available to write to Wrike",
            }

        result = {
            "status": "success",
            "folder": {
                "id": drive_folder_id,
                "name": folder_name,
                "link": drive_folder_link,
            },
            "attachments_uploaded": attachments_uploaded,
            "uploaded_files": uploaded_files,
            "wrike_update": wrike_update_status,
            "message": f"Successfully uploaded {attachments_uploaded} attachments to Drive folder '{folder_name}'",
        }

    except Exception as e:
        logger.error(
            "Failed to process email attachments or create Drive folder: %s", e
        )
        result = {
            "status": "error",
            "error": "Failed to create folder or upload attachments",
            "message": str(e),
        }

    logger.info("create_drive_folder_with_attachments result: %s", result)
    return result


@mcp.tool()
async def create_location_presentation(
    wrike_record_id: str | None = None,
    wrike_permalink: str | None = None,
) -> dict[str, Any]:
    """Create a Google Slides presentation for a location from Wrike data.

    This tool:
    - Resolves Wrike record (accepts either ID or permalink)
    - Extracts location data and scores from the record
    - Creates a copy of the presentation template
    - Updates the presentation with enrollment/wealth scores
    - Adds map and street view images

    Args:
        wrike_record_id: Wrike Site Record ID (optional if permalink provided)
        wrike_permalink: Wrike permalink URL (optional if record_id provided)

    Returns:
        Dict with presentation info
    """
    logger.info("Tool called: create_location_presentation")
    logger.info(
        "create_location_presentation params: wrike_record_id=%s, wrike_permalink=%s",
        wrike_record_id,
        wrike_permalink,
    )

    # Resolve record ID if permalink is provided
    if not wrike_record_id and not wrike_permalink:
        return {
            "status": "error",
            "error": "Missing parameter",
            "message": "Either wrike_record_id or wrike_permalink must be provided",
        }

    record_id = wrike_record_id

    if wrike_permalink:
        logger.info("Resolving permalink to record ID...")
        try:
            record_id = resolve_permalink_to_id(permalink=wrike_permalink)
            logger.info("Resolved permalink to record ID: %s", record_id)
        except Exception as e:
            logger.error("Failed to resolve permalink: %s", e)
            return {
                "status": "error",
                "error": "Failed to resolve permalink",
                "message": str(e),
            }

    if not record_id:
        return {
            "status": "error",
            "error": "Invalid record ID",
            "message": "Could not determine record ID",
        }

    # Step 1: Fetch Wrike Site Record
    logger.info("Fetching Wrike Site Record: %s", record_id)
    try:
        site_record = get_site_record_by_id(record_id=record_id)
        record_title = site_record.get("title", "")
        logger.info("Fetched Site Record: %s", record_title)
    except Exception as e:
        logger.error("Failed to fetch Wrike Site Record: %s", e)
        return {
            "status": "error",
            "error": "Failed to fetch Wrike Site Record",
            "message": str(e),
        }

    # Step 2: Extract address
    logger.info("Extracting address from Site Record...")
    address = extract_address_from_record(site_record)

    if not address:
        logger.error("Could not extract address from Site Record")
        return {
            "status": "error",
            "error": "Address not found",
            "message": "Could not extract address from Wrike Site Record",
        }

    logger.info("Address: %s", address)

    # Step 3: Extract scores and property features
    logger.info("Extracting scores from Site Record...")
    scores = extract_scores_from_wrike_record(site_record)
    logger.info("Extracted scores: %s", scores)

    logger.info("Extracting property features from description...")
    record_description = site_record.get("description", "")
    property_features = extract_property_features_from_description(record_description)
    logger.info("Extracted property features: %s", property_features)

    logger.info("Extracting enrollment dashboard URL from description...")
    enrollment_dashboard_url = extract_enrollment_dashboard_url(record_description)
    if enrollment_dashboard_url:
        logger.info("Enrollment dashboard URL: %s", enrollment_dashboard_url)
    else:
        logger.warning("Enrollment dashboard URL not found in description")

    # Step 4: Initialize Google client
    try:
        settings = get_settings()
        google_client = GoogleClient.from_oauth_config(
            client_config_path=str(settings.get_client_config_path()),
            token_file_path=str(settings.get_token_file_path()),
            oauth_port=settings.oauth_port,
            scopes=settings.google_scopes,
        )
        logger.info("Google client initialized successfully")
    except Exception as e:
        logger.error("Failed to initialize Google client: %s", e)
        return {
            "status": "error",
            "error": "Failed to initialize Google client",
            "message": str(e),
        }

    # Step 5: Copy presentation template
    logger.info("Copying presentation template...")
    try:
        presentation_name = f"Alpha Location - {record_title}"
        copied_presentation = google_client.copy_presentation(
            template_id=TEMPLATE_PRESENTATION_ID,
            name=presentation_name,
            parent_folder_id=PRESENTATION_FOLDER_ID,
        )
        presentation_id = copied_presentation.get("id")
        presentation_url = copied_presentation.get("webViewLink")

        if not presentation_id or not isinstance(presentation_id, str):
            raise RuntimeError("Invalid presentation ID returned")

        logger.info(
            "Created presentation: %s (id: %s)",
            presentation_name,
            presentation_id,
        )

        if enrollment_dashboard_url:
            logger.info(
                "Using hardcoded dashboard link location: table_id=%s, r=%s, c=%s",
                ENROLLMENT_DASHBOARD_TABLE_ID,
                ENROLLMENT_DASHBOARD_TABLE_ROW,
                ENROLLMENT_DASHBOARD_TABLE_COL,
            )
    except Exception as e:
        logger.error("Failed to copy presentation: %s", e)
        return {
            "status": "error",
            "error": "Failed to copy presentation",
            "message": str(e),
        }

    # Step 6: Build and apply updates
    logger.info("Updating presentation with data...")
    try:
        update_requests = build_presentation_updates(
            address=address,
            enrollment_score=scores.get("enrollment_score"),
            relative_enrollment_score=scores.get("relative_enrollment_score"),
            enrollment_score_plus=scores.get("enrollment_score_plus"),
            relative_enrollment_score_plus=scores.get("relative_enrollment_score_plus"),
            wealth_score=scores.get("wealth_score"),
            relative_wealth_score=scores.get("relative_wealth_score"),
            square_footage=property_features.get("square_footage"),
            complete_building=property_features.get("complete_building"),
            move_in_ready=property_features.get("move_in_ready"),
            current_space_usage=property_features.get("current_space_usage"),
        )

        if enrollment_dashboard_url:
            logger.info("Adding enrollment dashboard link updates...")
            update_requests += build_dashboard_link_updates(
                link_url=enrollment_dashboard_url,
                table_id=ENROLLMENT_DASHBOARD_TABLE_ID,
                row_index=ENROLLMENT_DASHBOARD_TABLE_ROW,
                col_index=ENROLLMENT_DASHBOARD_TABLE_COL,
            )

        google_client.batch_update_presentation(presentation_id, update_requests)
        logger.info("Successfully updated presentation")

        email_status: dict[str, Any] | None = None
        try:
            logger.info("Sending presentation email to sahil.marwaha@trilogy.com...")
            email_config = EmailConfig(
                to_addresses=["andrew.vincent@trilogy.com"],
                cc_addresses=["sahil.marwaha@trilogy.com"],
                subject=f"Alpha Location Presentation - {address}",
                body_text=(
                    "Your presentation is ready.\n\n"
                    f"Address: {address}\n"
                    f"Presentation: {presentation_url}\n"
                ),
                body_html=(
                    "<p>Your presentation is ready.</p>"
                    f"<p><strong>Address:</strong> {address}</p>"
                    f"<p><strong>Presentation:</strong> "
                    f'<a href="{presentation_url}">{presentation_url}</a></p>'
                ),
            )
            email_status = send_email(email_config)
            logger.info("Presentation email sent: %s", email_status)
        except Exception as e:
            logger.error("Failed to send presentation email: %s", e)
            email_status = {
                "success": False,
                "error": str(e),
            }

        result = {
            "status": "success",
            "presentation": {
                "id": presentation_id,
                "name": presentation_name,
                "url": presentation_url,
            },
            "email": email_status,
            "message": f"Successfully created presentation for {address}",
        }

    except Exception as e:
        logger.error("Failed to update presentation: %s", e)
        result = {
            "status": "error",
            "presentation": {
                "id": presentation_id,
                "url": presentation_url,
            },
            "error": "Failed to update presentation content",
            "message": f"Presentation created but update failed: {e}",
        }

    logger.info("create_location_presentation result: %s", result)
    return result


def main() -> None:
    """Main entry point for the MCP server."""
    logger.info(
        "Starting Alpha Analysis Downstream Processing MCP server (stdio transport)"
    )
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
