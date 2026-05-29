#!/usr/bin/env pwsh
<#
.SYNOPSIS
    One-time setup for Power BI MCP Server.
    Creates an Azure AD App Registration and generates config.json.
.NOTES
    Requires Azure CLI (az): https://aka.ms/installazurecli
#>

$ErrorActionPreference = "Stop"
$scriptDir = $PSScriptRoot

# ── Pre-checks ────────────────────────────────────────────────────────────────
if (-not (Get-Command az -ErrorAction SilentlyContinue)) {
    Write-Error "Azure CLI (az) not found. Install from https://aka.ms/installazurecli"
    exit 1
}

$account = az account show 2>$null | ConvertFrom-Json
if (-not $account) {
    Write-Host "Not logged in to Azure CLI. Running 'az login'..." -ForegroundColor Yellow
    az login | Out-Null
    $account = az account show | ConvertFrom-Json
}
Write-Host "Logged in as: $($account.user.name) | Tenant: $($account.tenantId)" -ForegroundColor Cyan

# ── Create App Registration ───────────────────────────────────────────────────
Write-Host "`nCreating Azure AD App Registration..." -ForegroundColor Green

$app = az ad app create `
    --display-name "Power BI MCP" `
    --sign-in-audience "AzureADMultipleOrgs" `
    --public-client-redirect-uris "https://login.microsoftonline.com/common/oauth2/nativeclient" `
    --is-fallback-public-client true `
    | ConvertFrom-Json

$clientId = $app.appId
Write-Host "App Registration created: $clientId"

# ── Add Power BI API Permissions ──────────────────────────────────────────────
$pbiResourceId = "00000009-0000-0000-c000-000000000000"

Write-Host "`nConfiguring Power BI API permissions..." -ForegroundColor Green

# Ensure Power BI service principal exists in tenant
$pbiSp = az ad sp show --id $pbiResourceId 2>$null | ConvertFrom-Json
if (-not $pbiSp) {
    Write-Host "  Creating Power BI service principal in tenant..."
    az ad sp create --id $pbiResourceId | Out-Null
    $pbiSp = az ad sp show --id $pbiResourceId | ConvertFrom-Json
}

# Discover delegated permission GUIDs
$scopes = $pbiSp.oauth2PermissionScopes
$datasetRW = ($scopes | Where-Object { $_.value -eq "Dataset.ReadWrite.All" }).id
$workspaceR = ($scopes | Where-Object { $_.value -eq "Workspace.Read.All" }).id

if ($datasetRW -and $workspaceR) {
    az ad app permission add `
        --id $clientId `
        --api $pbiResourceId `
        --api-permissions "$datasetRW=Scope" "$workspaceR=Scope" `
        | Out-Null
    Write-Host "  Added: Dataset.ReadWrite.All (delegated)"
    Write-Host "  Added: Workspace.Read.All (delegated)"
    Write-Host "  Note: User consent will be prompted on first login." -ForegroundColor Yellow
} else {
    Write-Warning "Could not discover Power BI permission IDs."
    Write-Warning "Available scopes:"
    $scopes | ForEach-Object { Write-Host "    $($_.value)" }
    Write-Warning "Add Dataset.ReadWrite.All and Workspace.Read.All manually in Azure Portal."
}

# ── Generate config.json ─────────────────────────────────────────────────────
$configPath = Join-Path $scriptDir "config.json"
@{
    client_id       = $clientId
    token_cache_dir = "~/.powerbi-mcp"
} | ConvertTo-Json | Set-Content -Path $configPath -Encoding UTF8

Write-Host "`nconfig.json written to: $configPath" -ForegroundColor Green

# ── Summary ───────────────────────────────────────────────────────────────────
Write-Host "`n$('=' * 50)" -ForegroundColor Cyan
Write-Host "Setup complete!" -ForegroundColor Green
Write-Host "  Client ID : $clientId"
Write-Host "  Config    : $configPath"
Write-Host ""
Write-Host "Next steps:" -ForegroundColor Cyan
Write-Host "  1. Install dependencies:  uv venv && uv sync"
Write-Host "  2. Register this MCP server in your AI client"
Write-Host "  3. On first use, authenticate via device code flow"
Write-Host "$('=' * 50)" -ForegroundColor Cyan
