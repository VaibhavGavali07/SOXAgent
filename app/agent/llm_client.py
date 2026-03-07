"""Multi-provider LLM client for the ComplianceEngine.

Supported providers:
  - anthropic   → Claude (Sonnet / Opus / Haiku)
  - openai      → GPT-4o, GPT-4 Turbo, etc.
  - azure_openai → Azure-hosted OpenAI models
  - google      → Gemini 2.0 Flash / Pro, etc.
"""
from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)

_FALLBACK_NOTICE = (
    "[LLM analysis unavailable – no API key configured. "
    "Add your API key on the Connections page to enable AI-powered narrative analysis.]"
)

# Default model per provider
_DEFAULT_MODELS: dict[str, str] = {
    "anthropic":    "claude-sonnet-4-6",
    "openai":       "gpt-4o",
    "azure_openai": "gpt-4o",
    "google":       "gemini-2.0-flash",
}


class LLMClient:
    """Thin wrapper around multiple LLM provider APIs."""

    def __init__(
        self,
        provider: str = "anthropic",
        api_key: str = "",
        model: Optional[str] = None,
        temperature: float = 0.2,
        azure_endpoint: str = "",
        azure_api_version: str = "2024-02-15-preview",
    ):
        self.provider = provider
        self.api_key = api_key
        self.model = model or _DEFAULT_MODELS.get(provider, "claude-sonnet-4-6")
        self.temperature = temperature
        self.azure_endpoint = azure_endpoint
        self.azure_api_version = azure_api_version
        self._client = None

        if api_key:
            self._init_client()

    # ── Initialisation ─────────────────────────────────────────────────────────

    def _init_client(self) -> None:
        try:
            if self.provider == "anthropic":
                import anthropic
                self._client = anthropic.Anthropic(api_key=self.api_key, timeout=90.0)

            elif self.provider == "openai":
                import openai
                self._client = openai.OpenAI(api_key=self.api_key, timeout=90.0)

            elif self.provider == "azure_openai":
                import openai
                self._client = openai.AzureOpenAI(
                    api_key=self.api_key,
                    azure_endpoint=self.azure_endpoint,
                    api_version=self.azure_api_version,
                    timeout=90.0,
                )

            elif self.provider == "google":
                import google.genai as genai
                self._client = genai.Client(api_key=self.api_key)

            else:
                logger.warning("Unknown LLM provider: %s", self.provider)

        except ImportError as exc:
            logger.warning(
                "Package not installed for provider '%s': %s. "
                "Run: pip install %s",
                self.provider,
                exc,
                _pip_hint(self.provider),
            )
        except Exception as exc:
            logger.warning("Failed to initialise %s client: %s", self.provider, exc)

    # ── Public API ─────────────────────────────────────────────────────────────

    def analyze(self, system: str, user: str, max_tokens: int = 1500) -> str:
        """Send a prompt and return the text response."""
        if self._client is None:
            return _FALLBACK_NOTICE

        try:
            if self.provider == "anthropic":
                response = self._client.messages.create(
                    model=self.model,
                    max_tokens=max_tokens,
                    system=system,
                    messages=[{"role": "user", "content": user}],
                )
                return response.content[0].text

            elif self.provider in ("openai", "azure_openai"):
                response = self._client.chat.completions.create(
                    model=self.model,
                    max_completion_tokens=max_tokens,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                )
                return response.choices[0].message.content

            elif self.provider == "google":
                response = self._client.models.generate_content(
                    model=self.model,
                    contents=f"{system}\n\n{user}",
                )
                return response.text

        except Exception as exc:
            logger.error("LLM API call failed (%s): %s", self.provider, exc)
            return f"[LLM analysis failed: {exc}]"

        return _FALLBACK_NOTICE

    def is_available(self) -> bool:
        return self._client is not None

    # ── Factory ────────────────────────────────────────────────────────────────

    @classmethod
    def from_settings(cls, settings: dict[str, str]) -> "LLMClient":
        provider = settings.get("llm_provider", "anthropic")
        model = settings.get("llm_model", "") or None   # empty string → use default
        return cls(
            provider=provider,
            api_key=settings.get("llm_api_key", ""),
            model=model,
            temperature=float(settings.get("llm_temperature", 0.2)),
            azure_endpoint=settings.get("azure_endpoint", ""),
            azure_api_version=settings.get("azure_api_version", "2024-02-15-preview"),
        )


# ── Helpers ────────────────────────────────────────────────────────────────────

def _pip_hint(provider: str) -> str:
    hints = {
        "anthropic":    "anthropic",
        "openai":       "openai",
        "azure_openai": "openai",
        "google":       "google-generativeai",
    }
    return hints.get(provider, "the relevant SDK")
