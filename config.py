"""Configuration constants and loaders for Power BI MCP Server."""

import functools
import json
import logging
import os
from datetime import timedelta, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_CLIENT_ID = "23d8f6bd-1eb0-4cc2-a08c-7bf525c67bcd"
DEFAULT_TOKEN_CACHE_DIR = "~/.powerbi-mcp"
CONFIG_PATH = Path(__file__).parent / "config.json"
POWER_BI_API = "https://api.powerbi.com/v1.0/myorg"
AZURE_AD_TOKEN_URL = "https://login.microsoftonline.com/common/oauth2/v2.0"
DEVICE_CODE_POLL_INTERVAL = 5  # seconds
DEVICE_CODE_POLL_TIMEOUT = 300  # 5 minutes
REFRESH_POLL_INTERVAL = 30  # 30s between status checks (Enhanced refresh fails fast)
REFRESH_POLL_TIMEOUT = 1800  # 30 min default cap



@functools.cache
def _load_config() -> dict:
    """Load config.json once and cache at module level."""
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, encoding="utf-8") as f:
                cfg = json.load(f)
            logger.info("Loaded config from %s", CONFIG_PATH)
            return cfg
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Failed to load config.json: %s - using defaults", e)
    return {}


def _get_client_id() -> str:
    return _load_config().get("client_id", DEFAULT_CLIENT_ID)


def _get_token_cache_path() -> Path:
    cfg = _load_config()
    cache_dir = Path(os.path.expanduser(cfg.get("token_cache_dir", DEFAULT_TOKEN_CACHE_DIR)))
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir / "token.json"


def _get_pbip_root() -> Path | None:
    cfg = _load_config()
    root = cfg.get("pbip_root")
    if not root:
        return None
    p = Path(os.path.expanduser(root))
    return p if p.exists() else None


# Display timezone for human-readable output (override via config.json)
# Supports integer UTC offset in hours, e.g. 10 for AEST, 8 for CST, -5 for EST
_tz_cfg = _load_config()
_tz_offset = _tz_cfg.get("display_tz_offset", 10)
_tz_label = _tz_cfg.get("display_tz_label", "AEST")
DISPLAY_TZ = timezone(timedelta(hours=_tz_offset))
DISPLAY_TZ_LABEL = f"{_tz_label} (UTC{_tz_offset:+d})"
DISPLAY_TZ_SHORT = _tz_label
