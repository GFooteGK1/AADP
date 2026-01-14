## Alpha Analysis Downstream Processing MCP Server

A Model Context Protocol (MCP) server for Alpha analysis downstream processing and automation tasks.

### Tools

- **`process_location(location_id: str, operation: str = "analyze", metadata: dict[str, Any] | None = None)`**:  
  Process a location with various operations. Currently a placeholder for future integrations including:

  - Updating Wrike records
  - Sending email notifications
  - Creating folders/documents
  - Running location analysis

  **Parameters:**

  - `location_id`: Unique identifier for the location
  - `operation`: Type of operation to perform (default: "analyze")
  - `metadata`: Optional metadata for the operation

  **Returns:**

  - `status`: Operation status
  - `location_id`: The processed location ID
  - `operation`: The operation performed
  - `message`: Result message
  - `metadata`: Any metadata passed or generated

### Setup

- **Install dependencies**

```bash
uv sync
```

- **Environment**

Create a `.env` file in the project root for any required API keys or credentials (to be added as integrations are implemented).

- **Run the server**

Add to your MCP client configuration:

```json
{
  "mcpServers": {
    "alpha-analysis-downstream-processing-mcp": {
      "command": "uv",
      "args": ["run", "alpha-analysis-downstream-processing-mcp"],
      "cwd": "/absolute/path/to/alpha-analysis-downstream-processing"
    }
  }
}
```

### Usage example

```python
result = await process_location(
    location_id="LOC-12345",
    operation="analyze",
    metadata={"source": "manual_input"}
)
```

### Development

- **Lint**:

```bash
uv run ruff check .
uv run ruff format .
```

- **Type check**:

```bash
uv run mypy src/
```

### Future Integrations

This server is designed to be extended with:

- Wrike API integration for record updates
- Email/notification services
- File and folder management
- Location analysis and reporting
