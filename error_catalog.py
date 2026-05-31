"""Error code catalog and regex patterns for refresh failure classification."""

ERROR_CODE_CATALOG: dict[str, tuple[str, str]] = {
    "0xC1450012": (
        "MashupDataAccessError",
        "Power Query data access failed - check M expression, schema drift, or source availability",
    ),
    "0xC112001C": (
        "OperationCancelled",
        "Engine cancelled operation (often cascades from sibling table failure in same transaction)",
    ),
    "0xC11C0006": (
        "TransactionCascade",
        "Cancelled because another table in same transaction failed - check peer table errors",
    ),
    "0xC11C0020": (
        "MemoryEviction",
        "Model evicted from memory during refresh - retry or increase Premium capacity memory",
    ),
    "0xC112001E": (
        "Timeout",
        "Refresh exceeded timeout - reduce data volume, use incremental refresh, or increase timeout",
    ),
    "0xC1450005": ("CapacityThrottle", "Premium capacity throttled - reduce concurrent refreshes or upgrade SKU"),
    "0x0000DEAD": ("ContainerCrash", "Refresh container exited unexpectedly - disable schedule and republish dataset"),
    "0x414700EF": ("EngineActivityId", "Internal engine activity correlator (not a user error)"),
    "0xC14700F0": ("EngineActivityIdTerminal", "Internal engine activity terminal (not a user error)"),
}

# (regex, category, hint) - searched against message text
UNDERLYING_PATTERNS: list[tuple[str, str, str]] = [
    (
        r"column\s+'+'+.*wasn'?t found|column\s+\"\".*wasn'?t found",
        "EmptyColumnReference",
        "Power Query references an empty/missing column name"
        " - inspect Table.SelectColumns / RenameColumns / ExpandTableColumn"
        ' / [""] / Field=""',
    ),
    (
        r"Credentials are required to connect|ModelRefreshFailed_CredentialsNotSpecified",
        "CredentialsNotConfigured",
        "Datasource credentials missing - configure in Power BI Service > Dataset Settings",
    ),
    (
        r"Access to the resource is forbidden|HTTP 403|\bForbidden\b",
        "AccessForbidden",
        "Datasource access denied - verify principal permissions / refresh OAuth token",
    ),
    (
        r"GatewayNotReachable|gateway is offline|gateway.*not.*reachable",
        "GatewayDown",
        "On-premises gateway unreachable - check gatewayStatus and gateway version",
    ),
    (
        r"evicted to free up memory",
        "MemoryEviction",
        "Model evicted during refresh - retry or increase capacity memory",
    ),
    (
        r"Capacity level limit exceeded|Node level limit exceeded|You'?ve exceeded the capacity limit",
        "CapacityThrottle",
        "Premium capacity throttled refresh - reschedule or upgrade SKU",
    ),
    (r"Container exited unexpectedly", "ContainerCrash", "Refresh container crashed - disable schedule and republish"),
    (
        r"The connection either timed out or was lost",
        "ConnectionLost",
        "Network connection to source lost mid-refresh - use Table.Buffer to cache outer join tables",
    ),
    (r"timed out|timeout|timeoutexception", "Timeout", "Operation exceeded time limit"),
    (
        r"Type Mismatch|type mismatch",
        "TypeMismatch",
        "M script type mismatch - check Power Query column types and Power BI Desktop version",
    ),
    (
        r"circular dependency|Circular Dependency",
        "CircularDependency",
        "Calculated table SummarizeColumns may have introduced circular dependency - see MS docs",
    ),
]

SYSTEM_TABLE_PREFIXES = ("LocalDateTable_", "DateTableTemplate_")
