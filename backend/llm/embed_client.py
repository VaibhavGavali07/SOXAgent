from __future__ import annotations

import hashlib
import math
import os


class EmbeddingClient:
    def __init__(self) -> None:
        self.enabled = os.getenv("ENABLE_EMBEDDINGS", "true").lower() == "true"
        self.dimensions = 16

    def embed_text(self, text: str) -> list[float]:
        if not self.enabled:
            return []
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        values = []
        for index in range(self.dimensions):
            start = (index * 2) % len(digest)
            chunk = digest[start : start + 2]
            number = int.from_bytes(chunk, "big")
            values.append((number / 65535.0) * 2 - 1)
        return values

    @staticmethod
    def cosine_similarity(left: list[float], right: list[float]) -> float:
        if not left or not right:
            return 0.0
        numerator = sum(a * b for a, b in zip(left, right))
        left_norm = math.sqrt(sum(value * value for value in left))
        right_norm = math.sqrt(sum(value * value for value in right))
        if not left_norm or not right_norm:
            return 0.0
        return numerator / (left_norm * right_norm)

