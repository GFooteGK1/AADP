#!/bin/sh

# Setup script for Alpha Analysis Downstream Processing MCP Server
echo "Setting up Alpha Analysis Downstream Processing MCP Server..." >&2

# Install dependencies using uv
echo "Installing dependencies..." >&2
uv sync > /dev/null 2>&1

# Install the package in editable mode so the module can be found
echo "Installing alpha_analysis_downstream_processing_mcp package..." >&2
uv pip install -e . > /dev/null 2>&1

echo "Setup complete!" >&2

# Output final JSON configuration to stdout (MANDATORY)
cat << EOF
{
  "command": "uv",
  "args": ["run", "alpha-analysis-downstream-processing-mcp"],
  "env": {},
  "cwd": "$(pwd)"
}
EOF
