"""OpenAI embedding adapter. Fails loudly: there is no mock or fallback vector."""
from __future__ import annotations

import os
import time
from typing import Protocol

import openai

# USD per 1M input tokens (OpenAI pricing page, text-embedding-3-small).
PRICE_PER_1M_TOKENS = {"text-embedding-3-small": 0.02, "text-embedding-3-large": 0.13}
DIMENSIONS = {"text-embedding-3-small": 1536, "text-embedding-3-large": 3072}
_TRANSIENT = (openai.RateLimitError, openai.APIConnectionError,
              openai.APITimeoutError, openai.InternalServerError)


class Embedder(Protocol):
    model_name: str
    dimensions: int

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Return one vector per input text, in the same order."""
        ...

    def embed_query(self, question: str) -> list[float]:
        """Return a query vector compatible with the stored document vectors."""
        ...


class OpenAIEmbedder:
    """Batches requests, retries transient errors, and counts billed tokens.

    Raises if the API key is missing or the API keeps failing, so a broken setup
    can never produce a benchmark run on fake vectors.
    """

    def __init__(self, model_name: str, batch_size: int = 100, max_retries: int = 5) -> None:
        if model_name not in DIMENSIONS:
            raise ValueError(f"unknown embedding model {model_name!r}; known: {sorted(DIMENSIONS)}")
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is missing: set it in starter/.env")
        self.model_name = model_name
        self.dimensions = DIMENSIONS[model_name]
        self.batch_size = batch_size
        self.max_retries = max_retries
        self.total_tokens = 0
        self.api_calls = 0
        self._client = openai.OpenAI(api_key=api_key)

    @property
    def cost_usd(self) -> float:
        return self.total_tokens / 1_000_000 * PRICE_PER_1M_TOKENS[self.model_name]

    def _create(self, batch: list[str]) -> list[list[float]]:
        for attempt in range(self.max_retries + 1):
            try:
                resp = self._client.embeddings.create(model=self.model_name, input=batch)
                break
            except _TRANSIENT:
                if attempt == self.max_retries:
                    raise
                time.sleep(min(2 ** attempt, 30))
        self.api_calls += 1
        self.total_tokens += resp.usage.total_tokens
        vectors = [d.embedding for d in sorted(resp.data, key=lambda d: d.index)]
        if len(vectors) != len(batch) or any(len(v) != self.dimensions for v in vectors):
            raise RuntimeError("embedding API returned an unexpected number or size of vectors")
        return vectors

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if any(not t.strip() for t in texts):
            raise ValueError("cannot embed empty text")
        out: list[list[float]] = []
        for i in range(0, len(texts), self.batch_size):
            out.extend(self._create(texts[i:i + self.batch_size]))
        return out

    def embed_query(self, question: str) -> list[float]:
        # text-embedding-3 models use the same space for queries and documents.
        return self.embed_documents([question])[0]
