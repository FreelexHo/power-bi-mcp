# Power BI MCP Server

An [MCP (Model Context Protocol)](https://modelcontextprotocol.io/) server that lets AI agents manage Power BI workspaces, datasets, and refreshes via natural language.

## Features

### Authentication & Discovery

| Tool | Description |
|---|---|
| `pbi_auth` | Authenticate via Azure AD device code flow (with token caching & auto-refresh) |
| `pbi_list_workspaces` | List accessible workspaces (with optional name filter) |
| `pbi_list_datasets` | List datasets in a workspace |

### Dataset & Refresh Management

| Tool | Description |
|---|---|
| `pbi_dataset_info` | Aggregate dataset metadata + datasources + gateways + refresh schedule + impacted reports + PBIP locate (single call) |
| `pbi_refresh_dataset` | Trigger an Enhanced refresh (supports table-level, polling, retry, timeout) |
| `pbi_refresh_manage` | Refresh lifecycle: view history (`status`), get execution details (`details`), or cancel (`cancel`) |

### Diagnostics & Source Code

| Tool | Description |
|---|---|
| `pbi_diagnose` | One-shot diagnostic report for refresh failures — root cause classification, error catalog, next actions, PBIP source hints |
| `pbi_locate_pbip` | Locate PBIP source code for a dataset (fuzzy folder match + optional table TMDL & M source extraction) |

### Query & Reporting

| Tool | Description |
|---|---|
| `pbi_execute_query` | Execute DAX queries against a dataset (supports RLS impersonation) |
| `pbi_scheduled_refresh_report` | Generate a daily scheduled-refresh status report across all datasets in a workspace (JSON or Markdown table) |

## Architecture

```
server.py            # Entry point — configures logging, runs MCP via stdio
app.py               # FastMCP instance with server instructions
config.py            # Configuration loader (config.json, defaults, constants)
auth.py              # Azure AD device code flow, token caching, HTTP helpers
diagnostics.py       # Refresh error classification, PBIP folder/table locator
error_catalog.py     # Error code catalog + regex patterns for failure classification
tools/               # MCP tool modules (auto-registered via __init__.py)
  ├── auth_tool.py   #   pbi_auth
  ├── workspace.py   #   pbi_list_workspaces, pbi_list_datasets
  ├── dataset.py     #   pbi_dataset_info
  ├── refresh.py     #   pbi_refresh_dataset, pbi_refresh_manage
  ├── diagnose.py    #   pbi_diagnose, pbi_locate_pbip
  ├── query.py       #   pbi_execute_query
  └── report.py      #   pbi_scheduled_refresh_report
setup.ps1            # Azure AD App Registration automation (PowerShell)
config.json          # User-specific config (gitignored)
```

## Quick Start

### 1. Install dependencies

```bash
git clone <repo-url> && cd power-bi-mcp
uv venv && uv sync
```

<details>
<summary>Don't have uv? Use pip instead</summary>

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS/Linux
source .venv/bin/activate

pip install -e .
```

</details>

### 2. Register in your MCP client

Add to your MCP client configuration:

**Cursor / Windsurf / Antigravity IDE** (`mcp.json`):

```json
{
  "mcpServers": {
    "power-bi": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/power-bi-mcp", "server.py"],
      "transport": "stdio"
    }
  }
}
```

### 3. Authenticate (one-time)

Just use the MCP! On first use, the agent will call `pbi_auth` and show you a message like:

```
To sign in, visit https://microsoft.com/devicelogin
and enter the code XXXXXXXX
```

1. Open the link in your browser
2. Enter the code shown
3. Sign in with your Microsoft work account
4. Approve the permissions

That's it. Tokens are cached to `~/.powerbi-mcp/token.json` and auto-refreshed — you won't need to do this again unless you revoke access.

## Configuration

The server works out of the box with a built-in public `client_id`. Create a `config.json` in the project root to customize:

```json
{
    "client_id": "<your-azure-ad-client-id>",
    "token_cache_dir": "~/.powerbi-mcp",
    "pbip_root": "C:/path/to/your/pbip-repo/data/power-bi-report"
}
```

| Key | Default | Description |
|---|---|---|
| `client_id` | Built-in public app | Azure AD App Registration client ID |
| `token_cache_dir` | `~/.powerbi-mcp` | Directory for cached OAuth tokens |
| `pbip_root` | *(none)* | Local PBIP repo root — enables `pbi_locate_pbip` and `pbi_diagnose` source-level hints |

A `setup.ps1` script is included to automate App Registration creation via Azure CLI. See [Advanced Setup](#advanced-setup) below.

## Troubleshooting

### `AADSTS7000218: The request body must contain ... client_assertion`

Your organization may block public client flows. Ask your Azure AD admin to either:
- Allow public client flows on the app registration, **or**
- Create a dedicated App Registration for your team (use `setup.ps1`)

### `AADSTS65001: The user or administrator has not consented`

First-time users in a new Azure AD tenant need to consent to Power BI permissions. If your tenant requires admin consent:
- Ask your admin to grant consent via Azure Portal -> App registrations -> API permissions -> "Grant admin consent"
- Or use `setup.ps1` to create your own App Registration where you are the owner

### `AADSTS50076: MFA required` or `AADSTS50079`

Multi-factor authentication is required by your organization. The device code flow supports MFA — complete the MFA challenge in your browser when prompted.

### `Not authenticated. Call pbi_auth first.`

Token has expired and could not be refreshed. The agent should automatically re-trigger `pbi_auth`. If it doesn't, ask the agent to call `pbi_auth` again.

### Token keeps expiring

By default, tokens are cached at `~/.powerbi-mcp/token.json`. Make sure:
- The directory is writable
- You are not running multiple instances that overwrite each other's tokens

### Refresh details return 403

A 403 on `pbi_refresh_manage action=details` typically indicates insufficient permissions or the refresh record has expired.

## Advanced Setup

For organizations that require their own App Registration:

### Prerequisites
- [Azure CLI](https://aka.ms/installazurecli)
- Azure AD permissions to create App Registrations

### Run setup

```powershell
./setup.ps1
```

This creates an Azure AD App Registration with the correct configuration:

| Setting | Value |
|---|---|
| Sign-in audience | Multi-tenant (any Azure AD directory) |
| Public client flows | Enabled |
| Redirect URI | `https://login.microsoftonline.com/common/oauth2/nativeclient` |
| API Permissions | `Power BI Service`: `Dataset.ReadWrite.All`, `Workspace.Read.All` (Delegated) |

## Tech Stack

- **Python** ≥ 3.10
- **[FastMCP](https://github.com/jlowin/fastmcp)** (`mcp[cli]` ≥ 1.6.0) — MCP server framework, stdio transport
- **[httpx](https://www.python-httpx.org/)** ≥ 0.27.0 — HTTP client for Azure AD & Power BI REST API calls

## License

MIT