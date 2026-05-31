"""pbi_auth tool - device code authentication."""

import json

from app import mcp
from auth import auth


@mcp.tool()
def pbi_auth() -> str:
    """Authenticate to Power BI service.

    Checks for cached token first, attempts refresh if expired,
    falls back to device code flow if needed.

    Returns:
        JSON with authentication status and instructions if user action needed.
    """
    if auth.get_access_token():
        return json.dumps({"status": "already_authenticated", "message": "Valid token available."})

    dc_response = auth.start_device_code_flow()
    user_code = dc_response.get("user_code", "")
    verification_uri = dc_response.get("verification_uri", "")
    message = dc_response.get("message", "")
    device_code = dc_response.get("device_code", "")

    result = auth.poll_for_token(device_code)
    result["user_code"] = user_code
    result["verification_uri"] = verification_uri
    result["initial_message"] = message
    return json.dumps(result, ensure_ascii=False)
