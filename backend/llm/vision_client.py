"""Vision LLM client for extracting approval information from screenshot attachments.

Supports OpenAI gpt-4o-mini (preferred), Azure OpenAI, and Google Gemini.
Falls back gracefully when no vision-capable provider is configured.
"""
from __future__ import annotations

import base64
import json
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

_VISION_PROMPT = """\
You are a SOX compliance auditor analyzing a screenshot attached to a ticket comment.

Extract approval information from this image. Look for:
- Approver name or user ID (who gave the approval)
- Approval text or decision (what was approved / rejected)
- Timestamp of the approval
- Any relevant context about what was being approved

Return ONLY a valid JSON object with exactly this schema:
{
  "approver": "name or user ID of the person who approved, or null if not visible",
  "approval_text": "the approval statement or decision, or null if not visible",
  "timestamp": "when the approval was given (any readable format), or null",
  "approval_status": "approved | rejected | pending | unknown",
  "confidence": 0.0 to 1.0,
  "summary": "one-sentence description of what this screenshot shows"
}

If this is not an approval-related screenshot set confidence to 0.1 and describe what you see.
Do not wrap JSON in markdown fences. Output only the JSON object."""


class VisionClient:
    """Extract structured approval data from screenshot images using a vision LLM.

    Provider resolution order (first available wins):
      1. OpenAI — gpt-4o-mini
      2. Azure OpenAI — vision-capable deployment
      3. Google Gemini — gemini-1.5-flash
      4. None — screenshot analysis disabled
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self._config = config or {}
        self._provider = self._resolve_provider()

    def _resolve_provider(self) -> str:
        provider = (self._config.get("provider") or os.getenv("LLM_PROVIDER", "")).lower()
        if provider == "openai" and (self._config.get("api_key") or os.getenv("OPENAI_API_KEY")):
            return "openai"
        if provider in ("azure", "azure_openai") and (
            self._config.get("api_key") or os.getenv("AZURE_OPENAI_API_KEY")
        ):
            return "azure_openai"
        if provider in ("gemini", "google") and (
            self._config.get("api_key") or os.getenv("GOOGLE_API_KEY")
        ):
            return "gemini"
        # Env-only fallback
        if os.getenv("OPENAI_API_KEY"):
            return "openai"
        if os.getenv("AZURE_OPENAI_API_KEY"):
            return "azure_openai"
        if os.getenv("GOOGLE_API_KEY"):
            return "gemini"
        return "none"

    @property
    def is_available(self) -> bool:
        return self._provider != "none"

    def analyze_image(self, image_bytes: bytes, filename: str = "") -> dict[str, Any] | None:
        """Analyze one image and return extracted approval data.

        Returns a dict with keys:
          approver, approval_text, timestamp, approval_status, confidence, summary

        Returns None when vision is unavailable or the call fails.
        """
        if not self.is_available or not image_bytes:
            return None
        try:
            if self._provider == "openai":
                return self._analyze_openai(image_bytes)
            if self._provider == "azure_openai":
                return self._analyze_azure(image_bytes)
            if self._provider == "gemini":
                return self._analyze_gemini(image_bytes)
        except Exception as exc:
            logger.warning("VisionClient: analysis failed for %r: %s", filename, exc)
        return None

    # ------------------------------------------------------------------
    # Provider implementations
    # ------------------------------------------------------------------

    def _analyze_openai(self, image_bytes: bytes) -> dict[str, Any] | None:
        import openai  # noqa: PLC0415
        api_key = self._config.get("api_key") or os.getenv("OPENAI_API_KEY", "")
        client = openai.OpenAI(api_key=api_key)
        b64, media_type = _encode_image(image_bytes)
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": _VISION_PROMPT},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{media_type};base64,{b64}",
                                "detail": "low",
                            },
                        },
                    ],
                }
            ],
            max_tokens=512,
            temperature=0,
        )
        return _parse_response(response.choices[0].message.content or "")

    def _analyze_azure(self, image_bytes: bytes) -> dict[str, Any] | None:
        import openai  # noqa: PLC0415
        api_key = self._config.get("api_key") or os.getenv("AZURE_OPENAI_API_KEY", "")
        endpoint = self._config.get("endpoint") or os.getenv("AZURE_OPENAI_ENDPOINT", "")
        deployment = (
            self._config.get("vision_deployment")
            or self._config.get("deployment_name", "gpt-4o-mini")
        )
        client = openai.AzureOpenAI(
            api_key=api_key,
            azure_endpoint=endpoint,
            api_version=self._config.get("api_version")
            or os.getenv("AZURE_OPENAI_API_VERSION", "2024-02-01"),
        )
        b64, media_type = _encode_image(image_bytes)
        response = client.chat.completions.create(
            model=deployment,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": _VISION_PROMPT},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{media_type};base64,{b64}",
                                "detail": "low",
                            },
                        },
                    ],
                }
            ],
            max_tokens=512,
            temperature=0,
        )
        return _parse_response(response.choices[0].message.content or "")

    def _analyze_gemini(self, image_bytes: bytes) -> dict[str, Any] | None:
        import google.generativeai as genai  # noqa: PLC0415
        api_key = self._config.get("api_key") or os.getenv("GOOGLE_API_KEY", "")
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel("gemini-1.5-flash")
        _, media_type = _encode_image(image_bytes)
        response = model.generate_content(
            [_VISION_PROMPT, {"mime_type": media_type, "data": image_bytes}]
        )
        return _parse_response(response.text or "")


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

def _encode_image(image_bytes: bytes) -> tuple[str, str]:
    """Return (base64_string, media_type) for an image."""
    b64 = base64.b64encode(image_bytes).decode("utf-8")
    if image_bytes[:4] == b"\x89PNG":
        return b64, "image/png"
    if image_bytes[:2] == b"\xff\xd8":
        return b64, "image/jpeg"
    if image_bytes[:4] == b"GIF8":
        return b64, "image/gif"
    if image_bytes[:4] == b"RIFF" and image_bytes[8:12] == b"WEBP":
        return b64, "image/webp"
    return b64, "image/png"  # safe default


def _parse_response(raw: str) -> dict[str, Any] | None:
    text = raw.strip()
    # Strip accidental markdown fences
    if text.startswith("```"):
        lines = text.split("\n")
        end = -1 if lines[-1].strip() == "```" else len(lines)
        text = "\n".join(lines[1:end])
    try:
        data = json.loads(text)
        return {
            "approver": data.get("approver"),
            "approval_text": data.get("approval_text"),
            "timestamp": data.get("timestamp"),
            "approval_status": data.get("approval_status", "unknown"),
            "confidence": float(data.get("confidence", 0.5)),
            "summary": data.get("summary", ""),
        }
    except (json.JSONDecodeError, ValueError) as exc:
        logger.warning("VisionClient: cannot parse response JSON: %s | snippet: %s", exc, raw[:200])
        return None
