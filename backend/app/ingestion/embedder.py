"""
Embedding pipeline using fastembed (local ONNX model, no LLM).

Model: BAAI/bge-small-en-v1.5
  - 384 dimensions
  - ~22MB download, cached locally after first run
  - Strong performance on code and technical text
  - Free, runs entirely on CPU

Design decisions:
  - The embedding model is loaded ONCE at module level (singleton).
    Loading it per-request would add ~2s latency on every embed call.
  - We embed in batches (default 32) to use ONNX parallelism.
  - embed() accepts list[str] and returns list[list[float]] — the same
    interface we'd use with OpenAI embeddings, making provider swap easy.
  - CRITICAL: The LLM is NEVER used for embeddings. This module must
    never import anything from app.models.llm_providers.
"""

from __future__ import annotations

import logging
import os
from typing import Generator

logger = logging.getLogger(__name__)

# Suppress fastembed's verbose HuggingFace symlink warning on Windows
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

_MODEL_NAME = "BAAI/bge-small-en-v1.5"
_EMBEDDING_DIM = 384
_embed_model = None   # Lazy-loaded singleton


def _get_model():
    """Lazy-load the embedding model (downloads ~22MB on first call)."""
    global _embed_model
    if _embed_model is None:
        logger.info(f"Loading embedding model: {_MODEL_NAME}")
        from fastembed import TextEmbedding
        _embed_model = TextEmbedding(model_name=_MODEL_NAME)
        logger.info(f"Embedding model loaded | dim={_EMBEDDING_DIM}")
    return _embed_model


def embed_texts(texts: list[str], batch_size: int = 32) -> list[list[float]]:
    """
    Embed a list of texts and return a list of float vectors.

    Args:
        texts:      List of strings to embed. Empty list returns [].
        batch_size: Number of texts to embed per ONNX inference call.

    Returns:
        List of embedding vectors, same length as input.
    """
    if not texts:
        return []

    model = _get_model()
    embeddings: list[list[float]] = []

    # fastembed.embed() is a generator — materialise in batches
    for batch_start in range(0, len(texts), batch_size):
        batch = texts[batch_start: batch_start + batch_size]
        batch_vecs = list(model.embed(batch))
        embeddings.extend([v.tolist() for v in batch_vecs])

    logger.debug(f"Embedded {len(texts)} texts | dim={_EMBEDDING_DIM}")
    return embeddings


def embed_single(text: str) -> list[float]:
    """Convenience wrapper for embedding a single query string."""
    results = embed_texts([text])
    return results[0] if results else []


def get_embedding_dim() -> int:
    """Return the dimension of the embedding vectors."""
    return _EMBEDDING_DIM


def warmup() -> None:
    """
    Pre-load the model. Call at app startup to avoid first-request latency.
    The model download happens here only once (cached after first run).
    """
    _get_model()
    logger.info("Embedding model warmed up")
