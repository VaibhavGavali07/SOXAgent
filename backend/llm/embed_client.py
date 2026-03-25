"""Semantic embedding client for SOX Agent.

Provider hierarchy (auto-detected from config/env):
  1. OpenAI   text-embedding-3-small  (1536-dim, best quality)
  2. Azure OpenAI embeddings          (1536-dim)
  3. Bag-of-words fallback            (128-dim, no API calls, offline-safe)

The old SHA-256 pseudo-embeddings have been removed — they had no semantic
meaning and made the similar-violations feature useless.
"""
from __future__ import annotations

import logging
import math
import os
from typing import Any

logger = logging.getLogger(__name__)

_FALLBACK_DIMS = 128
_OPENAI_EMBED_MODEL = "text-embedding-3-small"
_OPENAI_EMBED_DIMS = 1536


class EmbeddingClient:
    """Provider-aware embedding client with graceful fallback."""

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.enabled = os.getenv("ENABLE_EMBEDDINGS", "true").lower() == "true"
        self._config = config or {}
        self._provider = self._resolve_provider()
        self.dimensions = _OPENAI_EMBED_DIMS if self._provider in ("openai", "azure_openai") else _FALLBACK_DIMS
        logger.info("EmbeddingClient: provider=%s dims=%d", self._provider, self.dimensions)

    def _resolve_provider(self) -> str:
        if not self.enabled:
            return "disabled"
        explicit = (self._config.get("provider") or "").lower().strip()
        if explicit == "azure_openai" and (self._config.get("api_key") or os.getenv("AZURE_OPENAI_API_KEY")):
            return "azure_openai"
        if explicit == "openai" and (self._config.get("api_key") or os.getenv("OPENAI_API_KEY")):
            return "openai"
        # Auto-detect from available credentials
        if self._config.get("api_key") or os.getenv("OPENAI_API_KEY"):
            return "openai"
        if os.getenv("AZURE_OPENAI_API_KEY") and os.getenv("AZURE_OPENAI_ENDPOINT"):
            return "azure_openai"
        return "fallback"

    # ------------------------------------------------------------------

    def embed_text(self, text: str) -> list[float]:
        if not self.enabled or not text or not text.strip():
            return []
        if self._provider == "openai":
            return self._embed_openai(text)
        if self._provider == "azure_openai":
            return self._embed_azure(text)
        return self._embed_fallback(text)

    def _embed_openai(self, text: str) -> list[float]:
        try:
            from openai import OpenAI
            api_key = self._config.get("api_key") or os.getenv("OPENAI_API_KEY", "")
            client = OpenAI(api_key=api_key)
            response = client.embeddings.create(
                model=_OPENAI_EMBED_MODEL,
                input=text[:8000],
            )
            return response.data[0].embedding
        except Exception as exc:
            logger.warning("OpenAI embedding failed, falling back to local: %s", exc)
            return self._embed_fallback(text)

    def _embed_azure(self, text: str) -> list[float]:
        try:
            from openai import AzureOpenAI
            client = AzureOpenAI(
                api_key=self._config.get("api_key") or os.getenv("AZURE_OPENAI_API_KEY", ""),
                azure_endpoint=self._config.get("endpoint") or os.getenv("AZURE_OPENAI_ENDPOINT", ""),
                api_version=self._config.get("api_version") or os.getenv("AZURE_OPENAI_API_VERSION", "2024-02-01"),
            )
            deploy = self._config.get("embedding_deployment") or "text-embedding-3-small"
            response = client.embeddings.create(model=deploy, input=text[:8000])
            return response.data[0].embedding
        except Exception as exc:
            logger.warning("Azure OpenAI embedding failed, falling back to local: %s", exc)
            return self._embed_fallback(text)

    @staticmethod
    def _embed_fallback(text: str) -> list[float]:
        """Bag-of-words embedding (128-dim).

        Maps each token to a bucket via MD5 and accumulates term frequency.
        Semantically meaningful — tickets sharing words (e.g. 'self-approval',
        'unauthorized') will score high cosine similarity.  Far superior to
        the previous SHA-256 approach which had zero semantic content.
        """
        import hashlib
        tokens = text.lower().split()
        vec = [0.0] * _FALLBACK_DIMS
        for token in tokens:
            h = int(hashlib.md5(token.encode()).hexdigest(), 16)
            vec[h % _FALLBACK_DIMS] += 1.0
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]

    # ------------------------------------------------------------------

    @staticmethod
    def cosine_similarity(left: list[float], right: list[float]) -> float:
        if not left or not right or len(left) != len(right):
            return 0.0
        numerator = sum(a * b for a, b in zip(left, right))
        left_norm = math.sqrt(sum(v * v for v in left))
        right_norm = math.sqrt(sum(v * v for v in right))
        if not left_norm or not right_norm:
            return 0.0
        return numerator / (left_norm * right_norm)
