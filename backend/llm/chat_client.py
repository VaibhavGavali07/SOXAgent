from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Protocol


class ChatProvider(Protocol):
    provider_name: str
    model_name: str

    def complete_json(self, prompt: str) -> str:
        ...


def normalize_provider_name(value: str | None) -> str:
    normalized = (value or "").strip().lower().replace("-", "_").replace(" ", "_")
    alias_map = {
        "azure": "azure_openai",
        "azureopenai": "azure_openai",
        "azure_openai": "azure_openai",
        "openai": "openai",
        "open_ai": "openai",
        "gemini": "gemini",
        "google_gemini": "gemini",
        "mock": "mock",
    }
    return alias_map.get(normalized, normalized or "mock")


@dataclass
class MockChatProvider:
    provider_name: str = "mock"
    model_name: str = "mock-llm"

    def complete_json(self, prompt: str) -> str:
        return json.dumps({"prompt_received": True, "message": "Mock provider should not be called directly."})


class OpenAIChatProvider:
    provider_name = "openai"

    def __init__(self, model_name: str, api_key: str) -> None:
        from openai import OpenAI

        self.model_name = model_name
        self._client = OpenAI(api_key=api_key)

    def complete_json(self, prompt: str) -> str:
        response = self._client.chat.completions.create(
            model=self.model_name,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
        )
        return response.choices[0].message.content


class AzureOpenAIChatProvider:
    provider_name = "azure_openai"

    def __init__(self, model_name: str, api_key: str, endpoint: str, api_version: str) -> None:
        from openai import AzureOpenAI

        self.model_name = model_name
        self._client = AzureOpenAI(
            api_key=api_key,
            azure_endpoint=endpoint,
            api_version=api_version,
        )

    def complete_json(self, prompt: str) -> str:
        response = self._client.chat.completions.create(
            model=self.model_name,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
        )
        return response.choices[0].message.content


class GeminiChatProvider:
    provider_name = "gemini"

    def __init__(self, model_name: str, api_key: str) -> None:
        from google import genai

        self.model_name = model_name
        self._client = genai.Client(api_key=api_key)

    def complete_json(self, prompt: str) -> str:
        response = self._client.models.generate_content(
            model=self.model_name,
            contents=prompt,
            config={"response_mime_type": "application/json", "temperature": 0},
        )
        return response.text


def build_chat_provider(config: dict | None = None) -> ChatProvider:
    config = config or {}
    explicit_provider = config.get("provider")
    provider = normalize_provider_name(explicit_provider or os.getenv("LLM_PROVIDER") or "mock")
    deployment_name = config.get("deployment_name") or config.get("model")
    mock_llm_enabled = os.getenv("MOCK_LLM", "true").lower() == "true"

    # Respect explicit provider config from DB/UI. Only force mock when no provider
    # was explicitly configured or when provider is explicitly mock.
    if provider == "mock":
        return MockChatProvider(model_name=deployment_name or "mock-llm")
    if mock_llm_enabled and not explicit_provider:
        return MockChatProvider()
    if provider == "openai":
        return OpenAIChatProvider(
            model_name=deployment_name or os.getenv("OPENAI_DEPLOYMENT_NAME") or os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
            api_key=config.get("api_key") or os.getenv("OPENAI_API_KEY", ""),
        )
    if provider == "azure_openai":
        return AzureOpenAIChatProvider(
            model_name=deployment_name or os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME") or os.getenv("AZURE_OPENAI_MODEL", "gpt-4.1-mini"),
            api_key=config.get("api_key") or os.getenv("AZURE_OPENAI_API_KEY", ""),
            endpoint=config.get("endpoint") or os.getenv("AZURE_OPENAI_ENDPOINT", ""),
            api_version=config.get("api_version") or os.getenv("AZURE_OPENAI_API_VERSION", "2024-02-01"),
        )
    if provider == "gemini":
        return GeminiChatProvider(
            model_name=deployment_name or os.getenv("GEMINI_DEPLOYMENT_NAME") or os.getenv("GEMINI_MODEL", "gemini-2.0-flash"),
            api_key=config.get("api_key") or os.getenv("GEMINI_API_KEY", ""),
        )
    return MockChatProvider()
