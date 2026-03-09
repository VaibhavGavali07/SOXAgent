"""ServiceNow service - fetches incident tickets via REST API."""
from __future__ import annotations

from typing import Any


# ServiceNow state codes -> human-readable status
_STATE_MAP = {
    "-5": "Pending", "-4": "Pending",
    "1": "Open", "2": "Open", "3": "Open",
    "4": "Closed", "5": "Closed", "6": "Closed",
    "7": "Resolved",
}

# ServiceNow priority codes -> labels
_PRIORITY_MAP = {
    "1": "Critical", "2": "High", "3": "Medium", "4": "Low", "5": "Planning",
}


def _val(field: Any) -> str:
    """Extract display value from a ServiceNow field (may be dict or plain str)."""
    if isinstance(field, dict):
        return field.get("display_value") or field.get("value") or ""
    return str(field) if field else ""


def _map_ticket(raw: dict) -> dict:
    """Normalise a ServiceNow incident record to the internal ticket schema."""
    state_code = _val(raw.get("state", ""))
    status = _STATE_MAP.get(state_code, state_code) if state_code else "Open"

    priority_code = _val(raw.get("priority", ""))
    priority = _PRIORITY_MAP.get(priority_code, priority_code)

    ticket_type = _val(raw.get("type")) or "Incident"

    return {
        "ticket_key": _val(raw.get("number")),
        "title": _val(raw.get("short_description")),
        "status": status,
        "priority": priority,
        "ticket_type": ticket_type,
        "requestor_id": _val(raw.get("caller_id") or raw.get("opened_by")),
        "approver_id": _val(raw.get("approved_by") or raw.get("approval")),
        "implementer_id": _val(raw.get("assigned_to")),
        "documentation_link": _val(raw.get("close_notes") or raw.get("work_notes")),
        "tags": [],
        "_raw_snow": raw,  # preserve original for debugging
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

    def _get_incident_comments(self, token: str, incident_sys_id: str, max_results: int = 100) -> list[dict[str, str]]:
        """Fetch incident comments/work notes with author info from sys_journal_field."""
        if not incident_sys_id:
            return []

        import requests

        headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
        resp = requests.get(
            f"{self.url}/api/now/table/sys_journal_field",
            headers=headers,
            params={
                "sysparm_query": f"element_id={incident_sys_id}^elementINcomments,work_notes",
                "sysparm_fields": "sys_created_by,value,element,sys_created_on",
                "sysparm_limit": max_results,
                "sysparm_display_value": "true",
            },
            timeout=30,
        )
        resp.raise_for_status()
        rows = resp.json().get("result", [])
        comments: list[dict[str, str]] = []
        for row in rows:
            text = _val(row.get("value"))
            if not text:
                continue
            comments.append(
                {
                    "author": _val(row.get("sys_created_by")) or "unknown",
                    "text": text,
                    "type": _val(row.get("element")) or "comment",
                    "created_at": _val(row.get("sys_created_on")),
                }
            )
        return comments

    def get_tickets(self, max_results: int | None = None, page_size: int = 200) -> list[dict[str, Any]]:
        """Return incidents from ServiceNow mapped to the internal ticket schema.

        Fetches in batches until all matching records are read.
        Only closed/resolved incidents are fetched from ServiceNow.

        Returns an empty list when no credentials are configured.
        """
        if self._use_mock:
            return []

        import requests

        page_size = max(1, int(page_size or 200))
        token = self._get_token()
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
        mapped: list[dict[str, Any]] = []
        offset = 0
        remaining = max_results if isinstance(max_results, int) and max_results > 0 else None

        while True:
            limit = page_size if remaining is None else min(page_size, remaining)
            params = {
                "sysparm_limit": limit,
                "sysparm_offset": offset,
                "sysparm_display_value": "true",
                # Incident states: 4/5/6=Closed variants, 7=Resolved
                "sysparm_query": "stateIN4,5,6,7^ORDERBYDESCsys_updated_on",
            }
            resp = requests.get(
                f"{self.url}/api/now/table/incident",
                headers=headers,
                params=params,
                timeout=30,
            )
            resp.raise_for_status()
            results = resp.json().get("result", [])
            if not results:
                break

            for record in results:
                ticket = _map_ticket(record)
                if not ticket["ticket_key"]:
                    continue
                try:
                    ticket["comments"] = self._get_incident_comments(
                        token=token,
                        incident_sys_id=_val(record.get("sys_id")),
                    )
                except Exception:
                    ticket["comments"] = []
                mapped.append(ticket)

            fetched = len(results)
            offset += fetched
            if remaining is not None:
                remaining -= fetched
                if remaining <= 0:
                    break
            if fetched < limit:
                break

        return mapped

    def health_check(self) -> dict:
        if self._use_mock:
            return {"status": "not_configured", "connected": False, "source": "ServiceNow"}
        try:
            token = self._get_token()
            return {"status": "connected", "connected": bool(token), "source": "ServiceNow"}
        except Exception as exc:
            return {"status": "error", "connected": False, "source": "ServiceNow", "error": str(exc)}
