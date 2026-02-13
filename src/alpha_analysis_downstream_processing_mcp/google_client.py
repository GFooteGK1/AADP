"""Google Client for Gmail and Drive API operations with OAuth."""

from __future__ import annotations

import base64
import logging
from io import BytesIO
from pathlib import Path
from typing import Any

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseUpload

logger = logging.getLogger("[google_client]")


class GoogleClient:
    """Client for interacting with Gmail and Drive APIs using OAuth."""

    def __init__(self, credentials: Credentials) -> None:
        self.credentials = credentials
        self.gmail_service = build("gmail", "v1", credentials=credentials)
        self.drive_service = build("drive", "v3", credentials=credentials)
        self.slides_service = build("slides", "v1", credentials=credentials)
        logger.info(
            "Initialized GoogleClient with Gmail v1, Drive v3, and Slides v1 APIs"
        )

    @classmethod
    def from_oauth_config(
        cls,
        client_config_path: str,
        token_file_path: str,
        oauth_port: int,
        scopes: list[str],
    ) -> GoogleClient:
        """Create client using OAuth flow with provided scopes."""
        credentials: Credentials | None = None
        token_file = Path(token_file_path)

        logger.info("Initializing OAuth flow with scopes: %s", scopes)

        if token_file.exists():
            logger.info("Loading existing credentials from: %s", token_file)
            credentials = Credentials.from_authorized_user_file(str(token_file), scopes)
            if credentials and not credentials.refresh_token:
                logger.warning(
                    "Loaded credentials missing refresh_token; forcing OAuth flow to obtain offline access"
                )
                credentials = None

        if not credentials or not credentials.valid:
            if credentials and credentials.expired and credentials.refresh_token:
                logger.info("Refreshing expired credentials")
                credentials.refresh(Request())
            else:
                logger.info(
                    "Starting OAuth flow - browser window will open (requesting offline access)"
                )
                flow = InstalledAppFlow.from_client_secrets_file(
                    client_config_path, scopes
                )
                credentials = flow.run_local_server(
                    port=oauth_port,
                    access_type="offline",
                    prompt="consent",
                )

            if credentials is None:
                raise RuntimeError("Failed to obtain OAuth credentials")

            with open(token_file, "w") as token:
                token.write(credentials.to_json())
            logger.info("Saved new credentials to: %s", token_file)

        if credentials is None:
            raise RuntimeError("OAuth credentials are None after flow")

        return cls(credentials)

    # ---------- Gmail API Methods ----------

    def get_email_attachments(self, email_id: str) -> list[dict[str, Any]]:
        """
        Get all attachments from an email.

        Args:
            email_id: Gmail message ID

        Returns:
            List of attachment dicts with keys: filename, data (bytes), mimeType
        """
        logger.info("Fetching attachments for email: %s", email_id)

        try:
            message = (
                self.gmail_service.users()
                .messages()
                .get(userId="me", id=email_id)
                .execute()
            )

            attachments: list[dict[str, Any]] = []

            payload = message.get("payload", {})
            parts = payload.get("parts", [])

            def process_parts(parts_list: list[dict[str, Any]]) -> None:
                """Recursively process message parts to find attachments."""
                for part in parts_list:
                    filename = part.get("filename", "")
                    mime_type = part.get("mimeType", "")
                    body = part.get("body", {})
                    attachment_id = body.get("attachmentId")

                    # Check for nested parts (multipart messages)
                    if "parts" in part:
                        process_parts(part["parts"])
                        continue

                    # Skip if no attachment ID (inline content)
                    if not attachment_id:
                        continue

                    if filename:
                        logger.info(
                            "Found attachment: %s (type: %s, id: %s)",
                            filename,
                            mime_type,
                            attachment_id,
                        )

                        # Download the attachment
                        attachment = (
                            self.gmail_service.users()
                            .messages()
                            .attachments()
                            .get(userId="me", messageId=email_id, id=attachment_id)
                            .execute()
                        )

                        data_b64 = attachment.get("data", "")
                        data_bytes = base64.urlsafe_b64decode(data_b64)

                        attachments.append(
                            {
                                "filename": filename,
                                "data": data_bytes,
                                "mimeType": mime_type,
                            }
                        )
                        logger.info(
                            "Downloaded attachment: %s (%d bytes)",
                            filename,
                            len(data_bytes),
                        )

            process_parts(parts)

            logger.info("Found %d attachments for email %s", len(attachments), email_id)
            return attachments

        except HttpError as error:
            logger.error("Failed to get email attachments: %s", error)
            raise RuntimeError(f"Failed to get email attachments: {error}") from error

    # ---------- Drive API Methods ----------

    def create_folder(self, name: str, parent_id: str | None = None) -> dict[str, Any]:
        """
        Create a folder in Google Drive.

        Args:
            name: Folder name
            parent_id: Optional parent folder ID

        Returns:
            Dict with folder metadata including 'id' and 'name'
        """
        if not name.strip():
            raise ValueError("Folder name cannot be empty")

        metadata: dict[str, Any] = {
            "name": name.strip(),
            "mimeType": "application/vnd.google-apps.folder",
        }
        if parent_id:
            metadata["parents"] = [parent_id]

        logger.info(
            "Creating Drive folder: %s (parent: %s)",
            name,
            parent_id or "root",
        )

        try:
            folder = (
                self.drive_service.files()
                .create(
                    body=metadata,
                    fields="id,name,parents,webViewLink",
                    supportsAllDrives=True,
                )
                .execute()
            )
            logger.info(
                "Successfully created folder: %s (id: %s)",
                folder.get("name"),
                folder.get("id"),
            )
            return folder

        except HttpError as error:
            logger.error("Failed to create folder: %s", error)
            raise RuntimeError(f"Failed to create folder: {error}") from error

    def list_folders(self, parent_id: str | None = None) -> list[dict[str, Any]]:
        """
        List direct child folders under a Drive parent folder.

        Args:
            parent_id: Parent folder ID (uses root if not provided)

        Returns:
            List of folder metadata dicts including 'id', 'name', and 'webViewLink'
        """
        parent = parent_id or "root"
        query = (
            f"'{parent}' in parents and "
            "mimeType='application/vnd.google-apps.folder' and "
            "trashed=false"
        )
        logger.info("Listing Drive folders under parent: %s", parent)

        try:
            folders: list[dict[str, Any]] = []
            page_token: str | None = None

            while True:
                response = (
                    self.drive_service.files()
                    .list(
                        q=query,
                        fields="nextPageToken,files(id,name,webViewLink,parents)",
                        supportsAllDrives=True,
                        includeItemsFromAllDrives=True,
                        pageToken=page_token,
                        orderBy="name_natural",
                    )
                    .execute()
                )
                page_folders = response.get("files", [])
                folders.extend(page_folders)
                page_token = response.get("nextPageToken")
                if not page_token:
                    break

            logger.info(
                "Found %d Drive folders under parent %s",
                len(folders),
                parent,
            )
            return folders

        except HttpError as error:
            logger.error("Failed to list Drive folders: %s", error)
            raise RuntimeError(f"Failed to list Drive folders: {error}") from error

    def upload_file(
        self,
        file_name: str,
        file_data: bytes,
        mime_type: str,
        parent_folder_id: str | None = None,
    ) -> dict[str, Any]:
        """
        Upload a file to Google Drive.

        Args:
            file_name: Name for the file in Drive
            file_data: File content as bytes
            mime_type: MIME type of the file
            parent_folder_id: Optional parent folder ID

        Returns:
            Dict with file metadata including 'id', 'name', 'webViewLink'
        """
        logger.info(
            "Uploading file: %s (%d bytes, type: %s)",
            file_name,
            len(file_data),
            mime_type,
        )

        metadata: dict[str, Any] = {"name": file_name}
        if parent_folder_id:
            metadata["parents"] = [parent_folder_id]

        media = MediaIoBaseUpload(
            BytesIO(file_data),
            mimetype=mime_type,
            resumable=True,
        )

        try:
            file = (
                self.drive_service.files()
                .create(
                    body=metadata,
                    media_body=media,
                    fields="id,name,webViewLink,mimeType",
                    supportsAllDrives=True,
                )
                .execute()
            )
            logger.info(
                "Successfully uploaded file: %s (id: %s, link: %s)",
                file.get("name"),
                file.get("id"),
                file.get("webViewLink"),
            )
            return file

        except HttpError as error:
            logger.error("Failed to upload file: %s", error)
            raise RuntimeError(f"Failed to upload file: {error}") from error

    # ---------- Slides API Methods ----------

    def copy_presentation(
        self,
        template_id: str,
        name: str,
        parent_folder_id: str,
    ) -> dict[str, Any]:
        """
        Copy a Google Slides presentation template.

        Args:
            template_id: Template presentation ID
            name: Name for the new presentation
            parent_folder_id: Parent folder ID

        Returns:
            Dict with presentation metadata including 'id' and 'webViewLink'
        """
        logger.info(
            "Copying Slides template: %s (name: %s, parent: %s)",
            template_id,
            name,
            parent_folder_id,
        )

        body: dict[str, Any] = {
            "name": name,
            "parents": [parent_folder_id],
        }

        try:
            presentation = (
                self.drive_service.files()
                .copy(
                    fileId=template_id,
                    body=body,
                    supportsAllDrives=True,
                    fields="id,webViewLink",
                )
                .execute()
            )
            logger.info(
                "Successfully copied presentation: %s (id: %s)",
                name,
                presentation.get("id"),
            )
            return presentation

        except HttpError as error:
            logger.error("Failed to copy presentation: %s", error)
            raise RuntimeError(f"Failed to copy presentation: {error}") from error

    def batch_update_presentation(
        self, presentation_id: str, requests: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """
        Batch update a Google Slides presentation.

        Args:
            presentation_id: Presentation ID
            requests: List of update requests

        Returns:
            Dict with batch update response
        """
        logger.info(
            "Batch updating presentation: %s (%d requests)",
            presentation_id,
            len(requests),
        )

        try:
            response = (
                self.slides_service.presentations()
                .batchUpdate(
                    presentationId=presentation_id,
                    body={"requests": requests},
                )
                .execute()
            )
            logger.info(
                "Successfully updated presentation: %s",
                presentation_id,
            )
            return response

        except HttpError as error:
            logger.error("Failed to update presentation: %s", error)
            raise RuntimeError(f"Failed to update presentation: {error}") from error
