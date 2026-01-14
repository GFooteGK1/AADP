"""MCP server for Alpha analysis downstream processing and automation."""

from __future__ import annotations

import logging
from typing import Any

from dotenv import load_dotenv
from mcp.server import FastMCP

from .wrike import (
    WRIKE_CUSTOM_FIELDS,
    find_site_record_by_address,
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


@mcp.tool()
async def process_location(
    street_address: str,
    city: str,
    state: str,
    zip_code: str,
    contact_name: str,
    contact_email: str,
    contact_phone: str,
    square_footage: str,
    complete_building: str,
    move_in_ready: str,
    current_space_usage: str,
) -> dict[str, Any]:
    """Process a new location from parsed email data.

    This tool processes location information extracted from emails and will:
    - Update Wrike records
    - Send email notifications to CDS
    - Create folders/documents

    Args:
        street_address: Street address only (e.g., "123 Main Street")
        city: City name
        state: Two-letter state code
        zip_code: 5-digit zip code
        contact_name: Full name of site POC
        contact_email: Email address of site POC
        contact_phone: Phone number in (XXX) XXX-XXXX format
        square_footage: Square footage of the space
        complete_building: Whether taking the complete building (yes/no)
        move_in_ready: Whether the space is move-in ready (yes/no)
        current_space_usage: What the space is currently used for

    Returns:
        Dict containing operation results and status
    """
    logger.info("Tool called: process_location")
    logger.info(
        "process_location params: street_address=%s, city=%s, state=%s, zip_code=%s, "
        "contact_name=%s, contact_email=%s, contact_phone=%s, square_footage=%s, "
        "complete_building=%s, move_in_ready=%s, current_space_usage=%s",
        street_address,
        city,
        state,
        zip_code,
        contact_name,
        contact_email,
        contact_phone,
        square_footage,
        complete_building,
        move_in_ready,
        current_space_usage,
    )

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

    # Step 3: Update the overall_site_stage from "1. Looking for Sites" to "2. Evaluating Potential Sites (LOI)"
    logger.info(
        "Updating overall_site_stage to '2. Evaluating Potential Sites (LOI)'..."
    )
    try:
        update_site_record(
            record_id=record_id,
            custom_fields=[
                {
                    "id": WRIKE_CUSTOM_FIELDS["overall_site_stage"],
                    "value": "2. Evaluating Potential Sites (LOI)",
                }
            ],
        )
        logger.info(
            "Successfully updated site stage to '2. Evaluating Potential Sites (LOI)'"
        )
        stage_updated = True
    except Exception as e:
        logger.error("Failed to update site stage: %s", e)
        stage_updated = False

    # Step 4: Update the Site Record with location data (replace "Pending" section)
    logger.info("Updating Site Record with location data...")
    try:
        update_site_record_with_location_data(
            record_id=record_id,
            square_footage=square_footage,
            complete_building=complete_building,
            move_in_ready=move_in_ready,
            current_space_usage=current_space_usage,
            contact_name=contact_name,
            contact_email=contact_email,
            contact_phone=contact_phone,
        )
        logger.info("Successfully updated Site Record with location data")
        location_data_updated = True
    except Exception as e:
        logger.error("Failed to update location data: %s", e)
        location_data_updated = False

    # Step 5: Return final result
    result = {
        "status": "success",
        "matched_record": {
            "id": record_id,
            "title": record_title,
            "permalink": record_permalink,
        },
        "stage_update": {
            "updated": stage_updated,
            "new_stage": (
                "2. Evaluating Potential Sites (LOI)" if stage_updated else None
            ),
        },
        "location_data_update": {
            "updated": location_data_updated,
        },
        "input_data": {
            "address": {
                "street": street_address,
                "city": city,
                "state": state,
                "zip": zip_code,
                "full": full_address,
            },
            "contact": {
                "name": contact_name,
                "email": contact_email,
                "phone": contact_phone,
            },
            "details": {
                "square_footage": square_footage,
                "complete_building": complete_building,
                "move_in_ready": move_in_ready,
                "current_usage": current_space_usage,
            },
        },
        "message": f"Successfully processed location at {full_address}. Stage: {'updated' if stage_updated else 'failed'}. Location data: {'updated' if location_data_updated else 'failed'}.",
    }

    logger.info("process_location result: %s", result)
    return result


def main() -> None:
    """Main entry point for the MCP server."""
    logger.info(
        "Starting Alpha Analysis Downstream Processing MCP server (stdio transport)"
    )
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
