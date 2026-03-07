"""JIRA service – fetches access/change tickets via REST API."""
from __future__ import annotations

from typing import Any


class JiraService:
    """Wrapper around JIRA REST API."""

    def __init__(self, url: str = "", username: str = "", api_token: str = ""):
        self.url = url
        self.username = username
        self.api_token = api_token
        self._use_mock = not (url and username and api_token)

    def get_tickets(self, max_results: int = 50) -> list[dict[str, Any]]:
        """Return access/change tickets from JIRA.

        Configure JIRA credentials on the Connections page to enable live data.
        Returns an empty list when no credentials are configured.
        """
        if self._use_mock:
            return []
        # Real implementation:
        # GET /rest/api/3/search?jql=project=...&maxResults=max_results
        raise NotImplementedError("Live JIRA integration not yet configured.")

    def health_check(self) -> dict:
        return {"status": "not_configured" if self._use_mock else "connected",
                "connected": not self._use_mock, "source": "JIRA"}
