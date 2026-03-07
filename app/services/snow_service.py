"""ServiceNow service – fetches incidents and service requests via REST API."""
from __future__ import annotations

from typing import Any


# ServiceNow state codes → human-readable status
_STATE_MAP = {
    "-5": "Pending", "-4": "Pending",
    "1":  "Open",    "2": "Open",    "3": "Open",
    "4":  "Closed",  "5": "Closed",  "6": "Closed",
    "7":  "Resolved",
}

# ServiceNow priority codes → labels
_PRIORITY_MAP = {
    "1": "Critical", "2": "High", "3": "Medium", "4": "Low", "5": "Planning",
}


def _val(field: Any) -> str:
    """Extract display value from a ServiceNow field (may be dict or plain str)."""
    if isinstance(field, dict):
        return field.get("display_value") or field.get("value") or ""
    return str(field) if field else ""


def _map_ticket(raw: dict) -> dict:
    """Normalise a ServiceNow change_request record to the internal ticket schema."""
    state_code = _val(raw.get("state", ""))
    status = _STATE_MAP.get(state_code, state_code) if state_code else "Open"

    priority_code = _val(raw.get("priority", ""))
    priority = _PRIORITY_MAP.get(priority_code, priority_code)

    # Determine ticket type from chg_model or type field
    ticket_type = _val(raw.get("type") or raw.get("chg_model") or "") or "Change Request"

    return {
        "ticket_key":         _val(raw.get("number")),
        "title":              _val(raw.get("short_description")),
        "status":             status,
        "priority":           priority,
        "ticket_type":        ticket_type,
        "requestor_id":       _val(raw.get("requested_by") or raw.get("opened_by")),
        "approver_id":        _val(raw.get("approved_by") or raw.get("approval")),
        "implementer_id":     _val(raw.get("assigned_to")),
        "documentation_link": _val(raw.get("close_notes") or raw.get("work_notes")),
        "tags":               [],
        "_raw_snow":          raw,  # preserve original for debugging
    }


class ServiceNowService:
    """Wrapper around ServiceNow REST API using OAuth 2.0 client credentials."""

    def __init__(
        self,
        url: str = "",
        client_id: str = "",
        client_secret: str = "",
        client_name: str = "",
    ):
        self.url = url.rstrip("/")
        self.client_id = client_id
        self.client_secret = client_secret
        self.client_name = client_name
        self._use_mock = not (url and client_id and client_secret)

    def _get_token(self) -> str:
        """Obtain an OAuth 2.0 access token via client credentials grant."""
        import requests
        resp = requests.post(
            f"{self.url}/oauth_token.do",
            data={
                "grant_type": "client_credentials",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
            },
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()["access_token"]

    def get_tickets(self, max_results: int = 50) -> list[dict[str, Any]]:
        """Return change requests from ServiceNow mapped to the internal ticket schema.

        Returns an empty list when no credentials are configured.
        """
        if self._use_mock:
            return []
        import requests
        token = self._get_token()
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
        resp = requests.get(
            f"{self.url}/api/now/table/change_request",
            headers=headers,
            params={"sysparm_limit": max_results, "sysparm_display_value": "true"},
            timeout=30,
        )
        resp.raise_for_status()
        results = resp.json().get("result", [])
        # Map to internal schema and skip any records without a ticket number
        mapped = []
        for r in results:
            ticket = _map_ticket(r)
            if ticket["ticket_key"]:
                mapped.append(ticket)
        return mapped

    def health_check(self) -> dict:
        if self._use_mock:
            return {"status": "not_configured", "connected": False, "source": "ServiceNow"}
        try:
            token = self._get_token()
            return {"status": "connected", "connected": bool(token), "source": "ServiceNow"}
        except Exception as exc:
            return {"status": "error", "connected": False, "source": "ServiceNow", "error": str(exc)}
