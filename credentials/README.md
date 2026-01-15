# Credentials Setup (Google APIs)

Place your Google OAuth 2.0 client configuration file here as `client_secrets.json`.

## Required Files

1. **client_secrets.json** - OAuth 2.0 client configuration for user authentication

## Setup Instructions

1. Go to Google Cloud Console (`https://console.cloud.google.com`)
2. Create a new project or select existing one
3. Enable the **Gmail API** and **Google Drive API**
4. Go to "Credentials" → "Create Credentials" → "OAuth 2.0 Client IDs"
5. Choose "Web application" as application type
6. Add your redirect URI to "Authorized redirect URIs"
7. Download the JSON file and save as `client_secrets.json` in this directory

## OAuth Flow

When you first run the server, it will:

1. Use the OAuth credentials from the MCP Hive platform
2. Save your tokens to `.gcp-saved-tokens.json` for future use

Scopes used:

- `https://www.googleapis.com/auth/gmail.readonly` - Read emails and download attachments
- `https://www.googleapis.com/auth/drive` - Create folders and upload files to Google Drive

## Security Note

Credential files (`client_secrets.json`, `.gcp-saved-tokens.json`) are gitignored and should never be committed to version control.
