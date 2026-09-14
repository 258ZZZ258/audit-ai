"""Compute pair-specific similarity using the configured production embedding backend."""
import hashlib
import math
from collections import OrderedDict
from threading import RLock
from time import monotonic

from pydantic import BaseModel, ConfigDict, Field

from pipeline.index.embedding_client import Embedding


class CachedEmbeddings:
    """Cache is private to one fixed embedding client/model instance."""

    def __init__(self, client, max_entries=4096, ttl_seconds=900):
        self.client = client
        self.max_entries = max_entries
        self.ttl_seconds = ttl_seconds
        self._entries = OrderedDict()
        self._lock = RLock()

    def embed(self, texts):
        with self._lock:
            now = monotonic()
            for key in [k for k, (deadline, _) in self._entries.items() if deadline <= now]:
                del self._entries[key]
            keys = {text: hashlib.sha256(text.encode()).hexdigest() for text in texts}
            missing = [text for text, key in keys.items() if key not in self._entries]
            fresh = self.client.embed(missing) if missing else []
            if len(fresh) != len(missing):
                raise ValueError("Incomplete embedding response")
            vectors = {key: value[1] for key, value in self._entries.items()}
            dimensions = {len(vector) for vector in vectors.values()}
            for text, embedding in zip(missing, fresh, strict=True):
                vector = embedding.dense
                norm = math.sqrt(sum(x * x for x in vector))
                if not vector or not math.isfinite(norm) or norm == 0:
                    raise ValueError("Invalid embedding")
                dimensions.add(len(vector))
                vectors[keys[text]] = tuple(vector)
            if len(dimensions) > 1:
                self._entries.clear()
                raise ValueError("Embedding model dimension changed")
            # Commit only after validating the entire batch; return independent lists.
            for text in texts:
                key = keys[text]
                if key not in self._entries:
                    self._entries[key] = (monotonic() + self.ttl_seconds, vectors[key])
                self._entries.move_to_end(key)
            while len(self._entries) > self.max_entries:
                self._entries.popitem(last=False)
            return [Embedding(list(vectors[keys[text]]), {}) for text in texts]


class SimilarityPair(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pairId: str = Field(min_length=1, max_length=500)
    issueText: str = Field(min_length=1, max_length=4000)
    recordText: str = Field(min_length=1, max_length=4000)


class SimilarityRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pairs: list[SimilarityPair] = Field(min_length=1, max_length=64)


def score_pairs(request: SimilarityRequest, client) -> dict:
    if len({p.pairId for p in request.pairs}) != len(request.pairs):
        raise ValueError("Duplicate pairId")
    texts = list(dict.fromkeys(t for p in request.pairs for t in (p.issueText, p.recordText)))
    embeddings = client.embed(texts)
    if len(embeddings) != len(texts):
        raise ValueError("Incomplete embedding response")
    vectors = {}
    dimension = None
    for text, embedding in zip(texts, embeddings, strict=True):
        vector = embedding.dense
        if not vector or not all(math.isfinite(x) for x in vector):
            raise ValueError("Invalid embedding")
        dimension = dimension or len(vector)
        norm = math.sqrt(sum(x * x for x in vector))
        if len(vector) != dimension or not math.isfinite(norm) or norm == 0:
            raise ValueError("Invalid embedding dimension or norm")
        vectors[text] = [x / norm for x in vector]
    return {"scores": [{"pairId": p.pairId, "score": max(0.0, min(1.0, sum(
        a * b for a, b in zip(vectors[p.issueText], vectors[p.recordText], strict=True)
    )))} for p in request.pairs]}
