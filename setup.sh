#!/bin/sh

# Setup script for Alpha Analysis Downstream Processing MCP Server
echo "Setting up Alpha Analysis Downstream Processing MCP Server..." >&2

# Install dependencies using uv
echo "Installing dependencies..." >&2
uv sync > /dev/null 2>&1

# Install the package in editable mode so the module can be found
echo "Installing alpha_analysis_downstream_processing_mcp package..." >&2
uv pip install -e . > /dev/null 2>&1

# Setup OAuth2 configuration if platform variables are available
if [ -n "$API_KEY" ] && [ -n "$API_BASE_URL" ] && [ -n "$HIVE_INSTANCE_ID" ]; then
    echo "Fetching OAuth2 configuration..." >&2
    
    if curl -s -X GET "$API_BASE_URL/api/hive-instances/$HIVE_INSTANCE_ID/oauth2-config" \
        -H "x-api-key: $API_KEY" > oauth_response.json 2>&1; then
        
        # Save credentials in the format expected by our MCP server
        echo "Configuring OAuth2 credentials..." >&2
        
        # Create credentials directory if it doesn't exist
        mkdir -p credentials
        
        # Convert to Google OAuth2 authorized user format
        jq '{
          "client_id": .oauthKeys.client_id,
          "client_secret": .oauthKeys.client_secret,
          "refresh_token": .credentials.refresh_token,
          "token": .credentials.access_token,
          "type": "authorized_user"
        }' oauth_response.json > .gcp-saved-tokens.json
        
        # Create client secrets in Google OAuth format  
        jq '{"web": .oauthKeys}' oauth_response.json > credentials/client_secrets.json

        echo "OAuth2 credentials configured successfully" >&2
        
        rm oauth_response.json
    else
        echo "OAuth2 configuration fetch failed, will use manual setup" >&2
    fi
fi

echo "Setup complete!" >&2

# Output final JSON configuration to stdout (MANDATORY)
cat << EOF
{
  "command": "uv",
  "args": ["run", "alpha-analysis-downstream-processing-mcp"],
  "env": {
    "GOOGLE_CLIENT_CONFIG": "credentials/client_secrets.json",
    "GOOGLE_TOKEN_FILE": ".gcp-saved-tokens.json"
  },
  "cwd": "$(pwd)"
}
EOF
