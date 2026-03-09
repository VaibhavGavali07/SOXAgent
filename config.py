from __future__ import annotations
import os
from pathlib import Path

BASE_DIR = Path(__file__).parent
DATA_DIR = Path.home() / ".itgc_sox_agent"
DATA_DIR.mkdir(parents=True, exist_ok=True)


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "sox-compliance-dev-key-change-in-prod")
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL", f"sqlite:///{DATA_DIR / 'sox_compliance.db'}"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    # SQLite multi-thread safety: allow connections to be used across threads,
    # and wait up to 30 s for write locks instead of failing immediately.
    SQLALCHEMY_ENGINE_OPTIONS = {
        "connect_args": {"timeout": 30, "check_same_thread": False},
    }

    # -- ITGC Control Definitions --------------------------------------------
    CONTROLS: dict[str, dict] = {
        "SELF_APPROVAL": {
            "id": "ITGC-AC-01",
            "name": "Self-Approval Prevention",
            "severity": "High",
            "enabled": True,
            "description": "Requestor and Approver must be different individuals.",
            "framework": "SOX §404",
        },
        "UNAUTHORIZED_APPROVER": {
            "id": "ITGC-AC-02",
            "name": "Unauthorized Approver",
            "severity": "High",
            "enabled": False,
            "description": "Approver must appear on the Authorized Owners list.",
            "framework": "SOX §404",
        },
        "PRIVILEGED_ACCESS": {
            "id": "ITGC-AC-03",
            "name": "Unauthorized Privileged Access Grant",
            "severity": "High",
            "enabled": False,
            "description": "Privileged/admin access granted without proper chain of authorization.",
            "framework": "SOX §404 / NIST AC-6",
        },
        "MISSING_DOCUMENTATION": {
            "id": "ITGC-WF-01",
            "name": "Missing Closure Documentation",
            "severity": "Medium",
            "enabled": True,
            "description": "Closed tickets must have the documentation_link field populated.",
            "framework": "SOX §302",
        },
        "SOD_VIOLATION": {
            "id": "ITGC-SOD-01",
            "name": "Segregation of Duties Violation",
            "severity": "High",
            "enabled": False,
            "description": (
                "A single user must not hold multiple conflicting roles "
                "(Requestor, Approver, Implementer) within one workflow."
            ),
            "framework": "SOX §404 / COBIT APO01.02",
        },
        "UNAUTHORIZED_SOFTWARE": {
            "id": "ITGC-SW-01",
            "name": "Unauthorized Software Installation",
            "severity": "Medium",
            "enabled": True,
            "description": "Software absent from the Approved Software List was detected.",
            "framework": "SOX §404 / CIS Control 2",
        },
        # -- Task 1 gaps -------------------------------------------------------
        "MISSING_APPROVAL": {
            "id": "ITGC-AC-04",
            "name": "Missing Approval",
            "severity": "High",
            "enabled": True,
            "description": "Closed/resolved ticket has no approver assigned.",
            "framework": "SOX §404 / NIST AC-2",
        },
        "INVALID_APPROVAL_TIMESTAMP": {
            "id": "ITGC-AC-05",
            "name": "Invalid Approval Timestamp",
            "severity": "High",
            "enabled": False,
            "description": "Approval timestamp is absent or occurred after ticket closure.",
            "framework": "SOX §302 / NIST AU-3",
        },
    }

    # -- Authorized Approvers (Owners List) -----------------------------------
    AUTHORIZED_APPROVERS: list[str] = [
        "mgr_001",
        "mgr_002",
        "mgr_003",
        "sec_lead_001",
        "it_director_001",
        "compliance_officer_001",
        "john.smith",
        "sarah.jones",
        "admin_lead_01",
    ]

    # -- Approved Software List ------------------------------------------------
    APPROVED_SOFTWARE: list[str] = [
        "Microsoft Office 365",
        "Zoom",
        "Slack",
        "Google Chrome",
        "Visual Studio Code",
        "Python 3.11",
        "Python 3.12",
        "Node.js LTS",
        "Docker Desktop",
        "Git",
        "Postman",
        "Confluence",
        "Jira Software",
        "ServiceNow Agent",
        "McAfee Endpoint Security",
        "CrowdStrike Falcon",
        "Okta Verify",
        "LastPass Enterprise",
        "Microsoft Teams",
        "Windows Defender",
        "7-Zip",
        "Adobe Acrobat Reader",
        "Notepad++",
    ]

