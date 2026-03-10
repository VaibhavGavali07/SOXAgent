from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

from fastapi.testclient import TestClient


def load_app(tmp_path: Path):
    os.environ["DB_PATH"] = str(tmp_path / "test_agent.db")
    os.environ["MOCK_MODE"] = "true"
    os.environ["MOCK_LLM"] = "true"

    for name in list(sys.modules.keys()):
        if name.startswith("backend"):
            sys.modules.pop(name)

    module = importlib.import_module("backend.main")
    return module.app


def test_llm_test_uses_saved_secret_when_ui_sends_masked_blank(tmp_path: Path):
    app = load_app(tmp_path)
    client = TestClient(app)

    save_resp = client.post(
        "/api/configs",
        json={
            "config_type": "llm",
            "name": "llm-default",
            "data": {
                "provider": "openai",
                "deployment_name": "gpt-4.1-mini",
                "api_key": "saved-secret-key",
            },
        },
    )
    assert save_resp.status_code == 200

    import backend.api.routes_config as routes_config

    class _DummyProvider:
        provider_name = "openai"
        model_name = "gpt-4.1-mini"

        def complete_json(self, prompt: str) -> str:
            return '{"connection":"ok","service":"llm_test"}'

    def _fake_build_chat_provider(config):
        assert config["api_key"] == "saved-secret-key"
        assert config["provider"] == "openai"
        return _DummyProvider()

    original_builder = routes_config.build_chat_provider
    routes_config.build_chat_provider = _fake_build_chat_provider
    try:
        # Simulates UI state after reload where secret fields are masked/blank.
        test_resp = client.post(
            "/api/llm/test",
            json={"provider": "openai", "deployment_name": "gpt-4.1-mini", "api_key": ""},
        )
    finally:
        routes_config.build_chat_provider = original_builder

    assert test_resp.status_code == 200
    body = test_resp.json()
    assert body["ok"] is True
    assert body["provider"] == "openai"
    assert body["deployment_name"] == "gpt-4.1-mini"


def test_explicit_provider_not_overridden_by_mock_env(monkeypatch):
    import backend.llm.chat_client as chat_client

    monkeypatch.setenv("MOCK_LLM", "true")

    class FakeOpenAIProvider:
        provider_name = "openai"

        def __init__(self, model_name: str, api_key: str) -> None:
            self.model_name = model_name
            self.api_key = api_key

        def complete_json(self, prompt: str) -> str:
            return "{}"

    monkeypatch.setattr(chat_client, "OpenAIChatProvider", FakeOpenAIProvider)

    provider = chat_client.build_chat_provider(
        {"provider": "openai", "deployment_name": "gpt-4.1-mini", "api_key": "k"}
    )
    assert provider.provider_name == "openai"
    assert provider.model_name == "gpt-4.1-mini"
