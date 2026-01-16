"""Configuration management for Google OAuth and APIs."""

import os
from pathlib import Path

from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings

# Load environment variables from .env file at project root
load_dotenv(Path(__file__).parent.parent.parent / ".env")


class Settings(BaseSettings):
    """Application settings."""

    # Google Cloud Configuration
    google_client_config: str = Field(
        "credentials/client_secrets.json",
        description="OAuth 2.0 client configuration file",
    )
    google_token_file: str = Field(
        ".gcp-saved-tokens.json", description="Path to store user OAuth tokens"
    )
    oauth_port: int = Field(
        8765,
        description="Port for OAuth callback server",
    )

    # Google API Scopes
    google_scopes: list[str] = Field(
        default=[
            "https://www.googleapis.com/auth/gmail.readonly",
            "https://www.googleapis.com/auth/drive",
            "https://www.googleapis.com/auth/presentations",
        ],
        description="OAuth scopes for Gmail, Drive, and Slides operations",
    )

    # Logging
    log_level: str = Field("INFO", description="Logging level")

    def get_client_config_path(self) -> Path:
        """Get the path to OAuth client configuration."""
        return Path(self.google_client_config)

    def get_token_file_path(self) -> Path:
        """Get the path to the token storage file."""
        return Path(self.google_token_file)


def get_settings() -> Settings:
    """Get application settings."""
    try:
        return Settings()
    except Exception as e:
        raise ValueError(
            f"Configuration error: {e}. "
            f"Please ensure Google OAuth client config and token paths are valid. "
            f"Current working directory: {os.getcwd()}. "
            f"GOOGLE_CLIENT_CONFIG: {os.getenv('GOOGLE_CLIENT_CONFIG')}, "
            f"GOOGLE_TOKEN_FILE: {os.getenv('GOOGLE_TOKEN_FILE')}"
        ) from e
