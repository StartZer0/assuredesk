import math
import re
from collections import defaultdict

from rank_bm25 import BM25Okapi
from sqlalchemy import select

from . import policy
from .db import Chunk, Source


def words(text):
    return re.findall(r"[a-z0-9]+", text.lower())


def retrieve(session, user, book, queries, query_vectors, mode, model_id):
    # Metadata eligibility is resolved BEFORE either branch loads text or scores vectors.
    sources = {src.id: src for src in session.scalars(select(Source)) if policy.eligible(user, src, book)}
    source_ids = list(sources)
    if not source_ids:
        return []
    chunks = list(session.scalars(select(Chunk).where(Chunk.source_id.in_(source_ids))))
    if not chunks:
        return []
    scores = defaultdict(float)
    lexical = BM25Okapi([words(sources[c.source_id].title + " " + c.text) or [""] for c in chunks])
    for query, vector in zip(queries, query_vectors, strict=True):
        if mode != "dense":
            ranked = sorted(
                zip(chunks, lexical.get_scores(words(query)), strict=True),
                key=lambda pair: (-pair[1], pair[0].id),
            )
            for rank, (chunk, score) in enumerate(ranked[:12], 1):
                if score > 0:
                    scores[chunk.id] += 1 / (60 + rank)
        if session.bind.dialect.name == "postgresql":
            rows = list(
                session.scalars(
                    select(Chunk)
                    .where(
                        Chunk.source_id.in_(source_ids),
                        Chunk.embedding_model == model_id,
                        Chunk.embedding.is_not(None),
                    )
                    .order_by(Chunk.embedding.cosine_distance(vector), Chunk.id)
                    .limit(12)
                )
            )
        else:  # Test implementation only; production uses filtered SQL exact vector search.

            def cosine(c):
                a = c.embedding
                return sum(x * y for x, y in zip(a, vector, strict=True)) / (
                    math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in vector)) or 1
                )

            rows = sorted(
                [c for c in chunks if c.embedding is not None and c.embedding_model == model_id],
                key=lambda c: (-cosine(c), c.id),
            )[:12]
        for rank, chunk in enumerate(rows, 1):
            scores[chunk.id] += 1 / (60 + rank)
    ids = sorted(scores, key=lambda k: (-scores[k], k))[:20]
    return ids
