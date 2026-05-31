# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-06-01

### Added

- **Authentication**: Azure AD device code flow with token caching and auto-refresh (`pbi_auth`)
- **Workspace discovery**: List workspaces with optional name filter (`pbi_list_workspaces`)
- **Dataset management**: List datasets, aggregate dataset metadata (`pbi_list_datasets`, `pbi_dataset_info`)
- **Refresh management**: Enhanced refresh with table-level control, polling, retry, and timeout (`pbi_refresh_dataset`)
- **Refresh lifecycle**: View history, get execution details, cancel refreshes (`pbi_refresh_manage`)
- **Diagnostics**: One-shot diagnostic reports with root cause classification and error catalog (`pbi_diagnose`)
- **PBIP source lookup**: Locate PBIP source code with fuzzy folder match and TMDL extraction (`pbi_locate_pbip`)
- **DAX queries**: Execute DAX queries with RLS impersonation support (`pbi_execute_query`)
- **Scheduled refresh reporting**: Daily status reports across all datasets in a workspace (`pbi_scheduled_refresh_report`)
- Azure AD App Registration automation script (`setup.ps1`)
