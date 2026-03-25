from __future__ import annotations

import os
from typing import Any

import requests

from backend.connectors.normalize import normalize_servicenow_ticket

# ServiceNow default state values: 6=Resolved, 7=Closed
_CLOSED_RESOLVED_QUERY = "state=6^ORstate=7"

# Approval states that represent an actual decision (skip informational/pending)
_REAL_APPROVAL_DECISIONS = {"approved", "rejected"}


class ServiceNowConnector:
    def fetch(self, filters: dict[str, Any] | None = None) -> dict[str, list[dict[str, Any]]]:
        filters = filters or {}
        instance_url = (filters.get("instance_url") or os.getenv("SERVICENOW_INSTANCE_URL", "")).rstrip("/")
        if not instance_url:
            raise ValueError(
                "ServiceNow instance_url is required. Please configure the ServiceNow connection in Connections."
            )
        client_id = filters.get("client_id") or os.getenv("SERVICENOW_CLIENT_ID", "")
        client_secret = filters.get("client_secret") or os.getenv("SERVICENOW_CLIENT_SECRET", "")
        table = filters.get("table") or "incident"

        token = self._get_oauth_token(instance_url, client_id, client_secret)
        raw_tickets = self._query_table(instance_url, token, table)

        if not raw_tickets:
            return {"raw_tickets": [], "tickets": [], "software_installs": [], "identity_logs": [], "workflow_logs": []}

        # Collect all sys_ids for batch enrichment
        sys_ids = [r.get("sys_id", "") for r in raw_tickets if r.get("sys_id")]

        # Fetch activity (comments/work notes), approvals, and attachments in batch
        activity_by_sys_id = self._fetch_activity(instance_url, token, sys_ids)
        approvals_by_sys_id = self._fetch_approvals(instance_url, token, sys_ids)
        attachments_by_sys_id = self._fetch_attachments_batch(instance_url, token, sys_ids)

        tickets = [
            normalize_servicenow_ticket(
                self._map_raw_ticket(
                    raw, table, instance_url, activity_by_sys_id, approvals_by_sys_id, attachments_by_sys_id
                ),
                {},
            )
            for raw in raw_tickets
        ]
        return {
            "raw_tickets": raw_tickets,
            "tickets": tickets,
            "software_installs": [],
            "identity_logs": [],
            "workflow_logs": [],
        }

    # ------------------------------------------------------------------ auth

    def _get_oauth_token(self, instance_url: str, client_id: str, client_secret: str) -> str:
        resp = requests.post(
            f"{instance_url}/oauth_token.do",
            data={
                "grant_type": "client_credentials",
                "client_id": client_id,
                "client_secret": client_secret,
            },
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()["access_token"]

    # ------------------------------------------------------------------ main table

    def _query_table(self, instance_url: str, token: str, table: str) -> list[dict[str, Any]]:
        resp = requests.get(
            f"{instance_url}/api/now/table/{table}",
            headers={"Authorization": f"Bearer {token}"},
            params={
                "sysparm_query": _CLOSED_RESOLVED_QUERY,
                "sysparm_display_value": "true",
                "sysparm_exclude_reference_link": "true",
                "sysparm_fields": (
                    "sys_id,number,short_description,description,state,caller_id,requested_for,"
                    "opened_at,sys_updated_on,closed_at,assigned_to,assignment_group,"
                    "priority,category,impact,urgency,approval"
                ),
                "sysparm_limit": 200,
            },
            timeout=60,
        )
        resp.raise_for_status()
        return resp.json().get("result", [])

    # ------------------------------------------------------------------ enrichment

    def _fetch_activity(self, instance_url: str, token: str, sys_ids: list[str]) -> dict[str, list[dict[str, Any]]]:
        if not sys_ids:
            return {}
        id_list = ",".join(sys_ids)
        try:
            resp = requests.get(
                f"{instance_url}/api/now/table/sys_journal_field",
                headers={"Authorization": f"Bearer {token}"},
                params={
                    "sysparm_query": f"element_id IN {id_list}^elementINcomments,work_notes",
                    "sysparm_display_value": "true",
                    "sysparm_exclude_reference_link": "true",
                    "sysparm_fields": "sys_id,element_id,value,sys_created_on,sys_created_by",
                    "sysparm_limit": 1000,
                },
                timeout=30,
            )
            resp.raise_for_status()
        except Exception:
            return {}

        result: dict[str, list[dict[str, Any]]] = {}
        for entry in resp.json().get("result", []):
            eid = entry.get("element_id", "")
            result.setdefault(eid, []).append(entry)
        return result

    def _fetch_approvals(self, instance_url: str, token: str, sys_ids: list[str]) -> dict[str, list[dict[str, Any]]]:
        if not sys_ids:
            return {}
        id_list = ",".join(sys_ids)
        try:
            resp = requests.get(
                f"{instance_url}/api/now/table/sysapproval_approver",
                headers={"Authorization": f"Bearer {token}"},
                params={
                    "sysparm_query": f"document_id IN {id_list}^stateNOT INrequested,not requested",
                    "sysparm_display_value": "true",
                    "sysparm_exclude_reference_link": "true",
                    "sysparm_fields": "sys_id,document_id,approver,state,sys_created_on,comments",
                    "sysparm_limit": 1000,
                },
                timeout=30,
            )
            resp.raise_for_status()
        except Exception:
            return {}

        result: dict[str, list[dict[str, Any]]] = {}
        for entry in resp.json().get("result", []):
            did = entry.get("document_id", "")
            result.setdefault(did, []).append(entry)
        return result

    def _fetch_attachments_batch(
        self, instance_url: str, token: str, sys_ids: list[str]
    ) -> dict[str, list[dict[str, Any]]]:
        """Fetch attachment metadata for all tickets in one API call.

        Returns a dict mapping sys_id → list of attachment metadata dicts.
        Each entry has: sys_id, file_name, content_type, size_bytes, download_link.
        """
        if not sys_ids:
            return {}
        id_list = ",".join(sys_ids)
        try:
            resp = requests.get(
                f"{instance_url}/api/now/attachment",
                headers={"Authorization": f"Bearer {token}"},
                params={
                    "sysparm_query": f"table_sys_id IN {id_list}",
                    "sysparm_fields": "sys_id,file_name,content_type,size_bytes,table_sys_id",
                    "sysparm_limit": 500,
                },
                timeout=30,
            )
            resp.raise_for_status()
        except Exception:
            return {}

        result: dict[str, list[dict[str, Any]]] = {}
        for entry in resp.json().get("result", []):
            tsid = entry.get("table_sys_id", "")
            result.setdefault(tsid, []).append({
                "sys_id": entry.get("sys_id", ""),
                "file_name": entry.get("file_name", ""),
                "content_type": entry.get("content_type", ""),
                "size_bytes": entry.get("size_bytes", 0),
                "download_link": (
                    f"{instance_url}/api/now/attachment/{entry['sys_id']}/file"
                    if entry.get("sys_id") else ""
                ),
            })
        return result

    def download_attachment(self, download_link: str, token: str) -> bytes | None:
        """Download raw bytes for a single attachment. Returns None on failure."""
        if not download_link:
            return None
        try:
            resp = requests.get(
                download_link,
                headers={"Authorization": f"Bearer {token}"},
                timeout=30,
            )
            resp.raise_for_status()
            return resp.content
        except Exception as exc:
            import logging
            logging.getLogger(__name__).warning("download_attachment failed for %s: %s", download_link, exc)
            return None

    # ------------------------------------------------------------------ mapping

    def _map_raw_ticket(
        self,
        raw: dict[str, Any],
        table: str,
        instance_url: str,
        activity_by_sys_id: dict[str, list[dict[str, Any]]],
        approvals_by_sys_id: dict[str, list[dict[str, Any]]],
        attachments_by_sys_id: dict[str, list[dict[str, Any]]] | None = None,
    ) -> dict[str, Any]:
        record_type_map = {
            "incident": "incident",
            "sc_request": "request",
            "change_request": "change",
        }
        sys_id = raw.get("sys_id", "")
        requestor_name = raw.get("caller_id") or raw.get("requested_for") or ""
        assignee = raw.get("assigned_to") or ""

        # Build comments from journal entries
        journal_entries = activity_by_sys_id.get(sys_id, [])
        comments = [
            {
                "id": entry.get("sys_id", f"j_{i}"),
                "author": {"id": "", "name": entry.get("sys_created_by", ""), "email": ""},
                "timestamp": entry.get("sys_created_on", ""),
                "body": (entry.get("value") or "")[:2000],
            }
            for i, entry in enumerate(journal_entries)
            if entry.get("value", "").strip()
        ]

        # Build approvals from sysapproval_approver (real decisions only)
        approval_records = approvals_by_sys_id.get(sys_id, [])
        approval_history = [
            {
                "approver": {"id": "", "name": entry.get("approver", ""), "email": ""},
                "timestamp": entry.get("sys_created_on", ""),
                "type": "approval",
                "decision": entry.get("state", "approved").lower(),
            }
            for entry in approval_records
            if entry.get("state", "").lower() in _REAL_APPROVAL_DECISIONS
        ]

        ticket_url = f"{instance_url}/{table}.do?sys_id={sys_id}" if sys_id else ""

        # Build attachment list — include only entries with a valid sys_id
        raw_attachments = (attachments_by_sys_id or {}).get(sys_id, [])
        attachments = [
            {
                "id": att["sys_id"],
                "name": att["file_name"],
                "url": att["download_link"],
                "content_type": att.get("content_type", ""),
                "size_bytes": att.get("size_bytes", 0),
            }
            for att in raw_attachments
            if att.get("sys_id")
        ]

        return {
            "number": raw.get("number", ""),
            "record_type": record_type_map.get(table, "incident"),
            "short_description": raw.get("short_description", ""),
            "description": raw.get("description", ""),
            "state": raw.get("state", ""),
            "requested_for": {"id": "", "name": requestor_name, "email": ""},
            "approval_history": approval_history,
            "assigned_implementers": (
                [{"id": "", "name": assignee, "email": ""}] if assignee else []
            ),
            "opened_at": raw.get("opened_at", ""),
            "sys_updated_on": raw.get("sys_updated_on", ""),
            "closed_at": raw.get("closed_at") or None,
            "workflow_steps": [],
            "state_transitions": [],
            "activity": comments,
            "attachments": attachments,
            "custom_fields": {
                "risk_hint": self._priority_to_risk(raw.get("priority", "")),
                "category": raw.get("category", ""),
                "impact": raw.get("impact", ""),
                "urgency": raw.get("urgency", ""),
                "assignment_group": raw.get("assignment_group", ""),
                "servicenow_sys_id": sys_id,
                "servicenow_url": ticket_url,
            },
        }

    @staticmethod
    def _priority_to_risk(priority: str) -> str:
        p = priority.lower()
        if "1" in p or "critical" in p:
            return "HIGH"
        if "2" in p or "high" in p:
            return "HIGH"
        if "3" in p or "moderate" in p or "medium" in p:
            return "MEDIUM"
        return "LOW"
