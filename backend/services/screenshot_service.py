"""Screenshot analysis service for SOX ITGC compliance.

Downloads image attachments from ServiceNow tickets and runs vision LLM
analysis to extract approver identity and approval text.  Results are
injected into the prompt as additional evidence for the ITGC-AC-04
(Missing Approval) and ITGC-AC-01 (Self-Approval) controls.
"""
from __future__ import annotations

import logging
import os
from typing import Any

import requests

from backend.llm.vision_client import VisionClient

logger = logging.getLogger(__name__)

# Only analyse image content types to avoid wasting vision API calls on PDFs etc.
_IMAGE_CONTENT_TYPES = {
    "image/png", "image/jpeg", "image/jpg", "image/gif", "image/webp", "image/bmp",
}
# Max bytes to download per attachment (5 MB) — prevents runaway downloads
_MAX_ATTACHMENT_BYTES = 5 * 1024 * 1024


class ScreenshotService:
    """Download and analyse screenshot attachments from ServiceNow tickets."""

    def __init__(self, sn_config: dict[str, Any], llm_config: dict[str, Any]) -> None:
        self._sn_config = sn_config
        self.vision_client = VisionClient(config=llm_config)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze_ticket_screenshots(self, ticket: dict[str, Any]) -> list[dict[str, Any]]:
        """Return a list of approval-extraction results for image attachments.

        Each result dict has:
          filename, approver, approval_text, timestamp, approval_status,
          confidence, summary

        Returns an empty list when vision is unavailable, there are no image
        attachments, or every download/analysis attempt fails.
        """
        if not self.vision_client.is_available:
            return []

        attachments = ticket.get("attachments") or []
        image_attachments = [
            a for a in attachments
            if _is_image(a.get("content_type", ""), a.get("name", ""))
        ]
        if not image_attachments:
            return []

        token = self._get_token()
        results: list[dict[str, Any]] = []

        for att in image_attachments:
            filename = att.get("name", "attachment")
            url = att.get("url", "")
            if not url:
                continue

            image_bytes = self._download(url, token, filename)
            if not image_bytes:
                continue

            analysis = self.vision_client.analyze_image(image_bytes, filename)
            if analysis:
                results.append({"filename": filename, **analysis})

        return results

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_token(self) -> str:
        """Fetch a fresh OAuth token using the stored ServiceNow config."""
        instance_url = (
            self._sn_config.get("instance_url") or os.getenv("SERVICENOW_INSTANCE_URL", "")
        ).rstrip("/")
        client_id = self._sn_config.get("client_id") or os.getenv("SERVICENOW_CLIENT_ID", "")
        client_secret = (
            self._sn_config.get("client_secret") or os.getenv("SERVICENOW_CLIENT_SECRET", "")
        )
        if not instance_url:
            return ""
        try:
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
            return resp.json().get("access_token", "")
        except Exception as exc:
            logger.warning("ScreenshotService: token fetch failed: %s", exc)
            return ""

    def _download(self, url: str, token: str, filename: str) -> bytes | None:
        """Download attachment bytes, capped at _MAX_ATTACHMENT_BYTES."""
        headers: dict[str, str] = {}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        try:
            resp = requests.get(url, headers=headers, timeout=30, stream=True)
            resp.raise_for_status()
            chunks: list[bytes] = []
            total = 0
            for chunk in resp.iter_content(chunk_size=65536):
                if chunk:
                    total += len(chunk)
                    if total > _MAX_ATTACHMENT_BYTES:
                        logger.warning(
                            "ScreenshotService: attachment %r exceeds size limit, skipping", filename
                        )
                        return None
                    chunks.append(chunk)
            return b"".join(chunks)
        except Exception as exc:
            logger.warning("ScreenshotService: download failed for %r: %s", filename, exc)
            return None


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

def _is_image(content_type: str, filename: str) -> bool:
    """Return True if the attachment looks like a raster image."""
    if content_type.lower() in _IMAGE_CONTENT_TYPES:
        return True
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    return ext in {"png", "jpg", "jpeg", "gif", "webp", "bmp"}
