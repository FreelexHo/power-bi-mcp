# Power BI MCP Server

An [MCP (Model Context Protocol)](https://modelcontextprotocol.io/) server that lets AI agents manage Power BI workspaces, datasets, and refreshes via natural language.

For refresh incidents, the server brings dataset context, execution errors, same-workspace report dependencies, and optional local PBIP source hints into one evidence bundle. An agent can use it to propose the next investigation step while leaving fixes and operational decisions to the operator.

[Walk through a simulated refresh diagnosis](#example-diagnose-a-failed-dataset-refresh), or follow [Quick Start](#quick-start) to connect your MCP client.

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
| `pbi_diagnose` | Collect refresh evidence, classify known errors, suggest next actions, and link matching local PBIP source |
| `pbi_locate_pbip` | Locate PBIP source code for a dataset (fuzzy folder match + optional table TMDL & M source extraction) |

### Query & Reporting

| Tool | Description |
|---|---|
| `pbi_execute_query` | Execute DAX queries against a dataset (supports RLS impersonation) |
| `pbi_scheduled_refresh_report` | Generate a daily scheduled-refresh status report across all datasets in a workspace (JSON or Markdown table) |

## Example: diagnose a failed dataset refresh

> **Simulated demonstration — not a real Power BI execution.** All names, IDs, paths, service responses, source code, and agent conclusions below are fictional. The example illustrates the current tool contract; it does not demonstrate a production incident, a successful repair, or measured time savings.

A failed refresh can leave several tables marked as failed. This workflow connects execution messages to a candidate table, matching local source, and reports that may still show stale data, giving the operator a concrete place to investigate.

### 1. Ask the agent

> In "Demo Operations", the "Demo Sales" dataset failed to refresh. Find the likely cause, show which reports in this workspace may be affected, and tell me what to inspect before retrying. Do not change settings or start a refresh.

For this example, assume:

- The MCP server is connected and authentication has completed through `pbi_auth`; the signed-in user can read the workspace, dataset, and refresh details.
- The dataset has a failed Enhanced API refresh with structured `messages` and `objects`.
- Optional source lookup is enabled through [`pbip_root`](#configuration), with a readable local file at `<pbip_root>/Demo Sales/Demo Sales.SemanticModel/definition/tables/fact_sales.tmdl`.

### 2. Resolve the target, then diagnose

The agent discovers the workspace, then lists its datasets and uses the returned IDs. In this simulated discovery, "Demo Operations" maps to `11111111-1111-1111-1111-111111111111` and "Demo Sales" maps to `22222222-2222-2222-2222-222222222222`.

Illustrative MCP tool names and arguments, called in order after reading each discovery result (these are not JSON-RPC envelopes):

```json
[
  {
    "name": "pbi_list_workspaces",
    "arguments": {"filter": "Demo Operations"}
  },
  {
    "name": "pbi_list_datasets",
    "arguments": {"workspace_id": "11111111-1111-1111-1111-111111111111"}
  },
  {
    "name": "pbi_diagnose",
    "arguments": {
      "workspace_id": "11111111-1111-1111-1111-111111111111",
      "dataset_id": "22222222-2222-2222-2222-222222222222",
      "refresh_id": ""
    }
  }
]
```

The interface is `pbi_diagnose(workspace_id: str, dataset_id: str, refresh_id: str = "") -> str`. It returns a JSON-encoded string. With an empty `refresh_id`, it reads the latest **10** refresh records and selects the first record in API response order with `status == "Failed"` and `refreshType == "ViaEnhancedApi"`. This may differ from the most recent scheduled or on-demand failure. To investigate a known incident, pass its `requestId` as `refresh_id`.

### 3. Read the evidence

**Simulated output excerpt:** selected fields from the decoded JSON string are shown below; other metadata, history, and nested fields are omitted for readability. Field names and nesting follow the implementation.

```json
{
  "dataset_summary": {
    "id": "22222222-2222-2222-2222-222222222222",
    "name": "Demo Sales"
  },
  "target_refresh_id": "33333333-3333-3333-3333-333333333333",
  "target_refresh": {
    "status": "Failed",
    "messages": [
      {
        "type": "Error",
        "code": "0xC1450012",
        "message": "Expression.Error: The column '' of the table wasn't found.",
        "location": {"SourceObject": {"Table": "fact_sales", "Partition": "fact_sales"}}
      },
      {
        "type": "Error",
        "code": "0xC11C0006",
        "message": "Cancelled because another table in the same transaction failed.",
        "location": {"SourceObject": {"Table": "dim_date", "Partition": "dim_date"}}
      }
    ],
    "objects": [
      {"table": "fact_sales", "partition": "fact_sales", "status": "Failed"},
      {"table": "dim_date", "partition": "dim_date", "status": "Failed"}
    ]
  },
  "classification": {
    "root_cause_table": "fact_sales",
    "root_cause_partition": "fact_sales",
    "root_cause_column": null,
    "error_code": "0xC1450012",
    "error_category": "MashupDataAccessError",
    "underlying": {
      "pattern": "EmptyColumnReference",
      "snippet": "Expression.Error: The column '' of the table wasn't found."
    },
    "failed_user_tables": ["dim_date", "fact_sales"],
    "next_actions": [
      "Open PBIP and inspect M expression of table 'fact_sales'. Call pbi_locate_pbip with this table name; then grep for empty column refs: Table[\"\"], Field=\"\", PromoteHeaders missing source columns."
    ]
  },
  "impacted_reports": [
    {"id": "44444444-4444-4444-4444-444444444444", "name": "Demo Sales Overview"}
  ],
  "pbip_locate": {
    "status": "found",
    "matches": [
      {
        "match_type": "exact",
        "tables_dir": "/demo/pbip/Demo Sales/Demo Sales.SemanticModel/definition/tables"
      }
    ]
  },
  "root_cause_source": {
    "table_name": "fact_sales",
    "file": "/demo/pbip/Demo Sales/Demo Sales.SemanticModel/definition/tables/fact_sales.tmdl"
  }
}
```

The agent can now follow an inspectable chain:

1. The first `Error` message with `location.SourceObject.Table` identifies `fact_sales` and its partition as the initial investigation candidate.
2. `0xC1450012` maps to `MashupDataAccessError`, and the message matches the catalog's `EmptyColumnReference` pattern. The later `dim_date` cancellation may be a cascade; a failed-table list alone does not prove two independent faults.
3. The PBIP lookup finds a matching folder and table file. Its fictional M partition is shown separately below. When extraction succeeds, `root_cause_source.partition_source_m` contains the extracted TMDL partition body, including `source =`.

**Fictional local TMDL source:**

```text
table fact_sales

    partition fact_sales = m
        mode: import
        source =
            let
                Source = #table({"OrderId", "SalesAmount"}, {{1, 100}}),
                SelectedColumns = Table.SelectColumns(Source, {""})
            in
                SelectedColumns

    annotation PBI_ResultType = Table
```

Here, `Table.SelectColumns` asks for an empty column name, while the fictional source defines only `OrderId` and `SalesAmount`. This corroborates the error pattern and gives the operator a specific expression to inspect. The tool does not choose the intended replacement column.

**Illustrative agent conclusion, not tool output or a verified repair:**

> Start with the `fact_sales` M expression: it selects an empty column name. Confirm the intended column and upstream schema before editing; if the intent is to select `SalesAmount`, replace `{""}` with `{"SalesAmount"}` only after that check. Validate the change in Power Query/Power BI Desktop, confirm the local PBIP version matches the deployed model, then publish and retry through your normal approval process. Review the next refresh result to verify recovery. `dim_date` may have failed as a consequence of the same transaction. The bound "Demo Sales Overview" report in this workspace may still show stale data. This diagnosis has not changed settings or started a refresh.

### 4. Know the limits

| Area | Implemented behavior and required human judgment |
|---|---|
| Refresh selection | Automatic selection covers failed `ViaEnhancedApi` entries in the latest 10 records, not every refresh type or all history. Use `pbi_refresh_manage` with `action="status"` to inspect history and pass an explicit `refresh_id` for the intended incident. An explicit ID does not guarantee rich execution details. |
| Missing evidence | No eligible refresh produces `classification: null` and no `target_refresh`. A failed details request is exposed as `refresh_details_error`, also with no classification. Authentication, history, or network failures can abort the call; missing evidence is not a healthy-state verdict. |
| Error classification | `root_cause_table` is a heuristic: the first eligible error in message order, not a proven causal root. Pattern matching searches all messages and is not necessarily tied to that table. Unknown codes, missing messages, and cascading failures require manual investigation. |
| Local source | Requires an existing, readable `pbip_root`, a matching dataset folder, a `.SemanticModel/definition/tables` directory, and a matching table file. Diagnosis uses the first dataset match; fuzzy matches can be wrong. Source hints may be absent, and M extraction may be `null`. Verify the file and deployed version. |
| Report impact | `impacted_reports` lists reports in the **same workspace** whose `datasetId` matches. It is not a complete cross-workspace dependency or tenant-wide impact analysis. |
| Remediation | This workflow reads evidence and suggests actions. It does not edit M, reset credentials, publish a model, or prove recovery. Refresh/cancel tools are separate capabilities; an operator must decide whether and when to use them. |

Implementation references: [diagnostic tool](tools/diagnose.py), [classification and PBIP lookup](diagnostics.py), [error catalog](error_catalog.py), [dataset/report context](tools/dataset.py), and [refresh history/details](tools/refresh.py).

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
git clone https://github.com/FreelexHo/power-bi-mcp.git && cd power-bi-mcp
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