"""Azure AD authentication (device code flow) and shared HTTP helpers."""

import json
import logging
import time
from datetime import datetime, timezone

import httpx

from config import (
    AZURE_AD_TOKEN_URL,
    DEVICE_CODE_POLL_INTERVAL,
    DEVICE_CODE_POLL_TIMEOUT,
    POWER_BI_API,
    _get_client_id,
    _get_token_cache_path,
)

logger = logging.getLogger(__name__)


class PowerBIAuth:
    """Handles Azure AD device code flow with token caching."""

    def __init__(self):
        self._client_id = _get_client_id()
        self._scope = "https://analysis.windows.net/powerbi/api/.default offline_access"
        self._token_path = _get_token_cache_path()
        self._access_token: str | None = None
        self._refresh_token: str | None = None
        self._expires_at: float = 0
        self._load_cached_token()

    def _load_cached_token(self):
        if not self._token_path.exists():
            return
        try:
            data = json.loads(self._token_path.read_text(encoding="utf-8"))
            self._access_token = data.get("access_token")
            self._refresh_token = data.get("refresh_token")
            self._expires_at = data.get("expires_at", 0)
            logger.info("Loaded cached token (expires_at=%s)", self._expires_at)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Failed to load cached token: %s", e)

    def _save_token(self, token_response: dict):
        self._access_token = token_response["access_token"]
        self._refresh_token = token_response.get("refresh_token", self._refresh_token)
        expires_in = token_response.get("expires_in", 3600)
        self._expires_at = time.time() + expires_in - 60  # 60s safety margin

        data = {
            "access_token": self._access_token,
            "refresh_token": self._refresh_token,
            "expires_at": self._expires_at,
            "saved_at": datetime.now(timezone.utc).isoformat(),
        }
        self._token_path.parent.mkdir(parents=True, exist_ok=True)
        self._token_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        logger.info("Token cached to %s", self._token_path)

    def _is_token_valid(self) -> bool:
        return self._access_token is not None and time.time() < self._expires_at

    def _refresh_access_token(self) -> bool:
        if not self._refresh_token:
            return False
        try:
            with httpx.Client(timeout=30) as client:
                resp = client.post(
                    f"{AZURE_AD_TOKEN_URL}/token",
                    data={
                        "grant_type": "refresh_token",
                        "client_id": self._client_id,
                        "refresh_token": self._refresh_token,
                        "scope": self._scope,
                    },
                )
                if resp.status_code == 200:
                    self._save_token(resp.json())
                    logger.info("Token refreshed successfully")
                    return True
                logger.warning("Token refresh failed: %s %s", resp.status_code, resp.text)
                return False
        except httpx.HTTPError as e:
            logger.warning("Token refresh error: %s", e)
            return False

    def start_device_code_flow(self) -> dict:
        with httpx.Client(timeout=30) as client:
            resp = client.post(
                f"{AZURE_AD_TOKEN_URL}/devicecode",
                data={"client_id": self._client_id, "scope": self._scope},
            )
            resp.raise_for_status()
            return resp.json()

    def poll_for_token(self, device_code: str) -> dict:
        start = time.time()
        while time.time() - start < DEVICE_CODE_POLL_TIMEOUT:
            time.sleep(DEVICE_CODE_POLL_INTERVAL)
            try:
                with httpx.Client(timeout=30) as client:
                    resp = client.post(
                        f"{AZURE_AD_TOKEN_URL}/token",
                        data={
                            "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                            "client_id": self._client_id,
                            "device_code": device_code,
                        },
                    )
                    body = resp.json()
                    if resp.status_code == 200:
                        self._save_token(body)
                        return {"status": "authenticated", "message": "Token acquired and cached."}
                    error = body.get("error", "")
                    if error == "authorization_pending":
                        continue
                    elif error == "slow_down":
                        time.sleep(5)
                        continue
                    else:
                        return {"status": "error", "error": error, "description": body.get("error_description", "")}
            except httpx.HTTPError as e:
                logger.warning("Poll error: %s", e)
                continue
        return {"status": "timeout", "message": "Device code authentication timed out after 5 minutes."}

    def get_access_token(self) -> str | None:
        if self._is_token_valid():
            return self._access_token
        if self._refresh_access_token():
            return self._access_token
        # Reload from disk - token may have been updated externally
        self._load_cached_token()
        if self._is_token_valid():
            return self._access_token
        if self._refresh_access_token():
            return self._access_token
        return None

    def get_headers(self) -> dict:
        token = self.get_access_token()
        if not token:
            raise RuntimeError("Not authenticated. Call pbi_auth first.")
        return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    def request(self, method: str, url: str, **kwargs) -> httpx.Response:
        """Execute HTTP request with automatic token refresh on 401/403.

        Tries the request once; if the response is 401 or 403, refreshes the
        access token and retries exactly once.  All other status codes are
        returned as-is for the caller to handle.
        """
        timeout = kwargs.pop("timeout", 60)
        headers = self.get_headers()
        with httpx.Client(timeout=timeout) as client:
            resp = getattr(client, method)(url, headers=headers, **kwargs)
            if resp.status_code in (401, 403) and self._refresh_access_token():
                logger.info("Got %d - refreshed token, retrying...", resp.status_code)
                headers = self.get_headers()
                resp = getattr(client, method)(url, headers=headers, **kwargs)
        return resp


# ---------------------------------------------------------------------------
# Singleton & shared HTTP helpers
# ---------------------------------------------------------------------------
auth = PowerBIAuth()


def _get_json(path: str) -> dict:
    """GET an absolute path under POWER_BI_API; returns parsed JSON or raises."""
    resp = auth.request("get", f"{POWER_BI_API}{path}", timeout=30)
    resp.raise_for_status()
    return resp.json()


def _safe_get_json(path: str) -> dict | str:
    """GET with errors swallowed - returns dict on success, error string on failure."""
    try:
        return _get_json(path)
    except httpx.HTTPStatusError as e:
        return {"_error": f"HTTP {e.response.status_code}", "_url": path}
    except Exception as e:
        return {"_error": str(e), "_url": path}
