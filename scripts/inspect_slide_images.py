#!/usr/bin/env python3
"""
Inspect a Google Slides presentation and print image element IDs.
"""

from __future__ import annotations

import argparse

from alpha_analysis_downstream_processing_mcp.config import get_settings
from alpha_analysis_downstream_processing_mcp.google_client import GoogleClient


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Inspect slide images and print image element IDs."
    )
    parser.add_argument("--presentation-id", required=True)
    parser.add_argument("--slide-id", default=None)
    args = parser.parse_args()

    settings = get_settings()
    client = GoogleClient.from_oauth_config(
        client_config_path=str(settings.get_client_config_path()),
        token_file_path=str(settings.get_token_file_path()),
        oauth_port=settings.oauth_port,
        scopes=settings.google_scopes,
    )

    presentation = (
        client.slides_service.presentations()
        .get(presentationId=args.presentation_id)
        .execute()
    )

    slides = presentation.get("slides", [])
    for slide in slides:
        slide_id = slide.get("objectId")
        if args.slide_id and slide_id != args.slide_id:
            continue

        for element in slide.get("pageElements", []):
            image = element.get("image")
            if not isinstance(image, dict):
                continue

            element_id = element.get("objectId")
            if not isinstance(element_id, str):
                continue

            content_url = image.get("contentUrl")
            if not isinstance(content_url, str):
                content_url = "unknown"

            print(
                f"SLIDE {slide_id} IMAGE {element_id} contentUrl={content_url}"
            )


if __name__ == "__main__":
    main()
