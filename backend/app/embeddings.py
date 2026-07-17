"""The one shared embedding provider for the platform — pulled out of
app/tool_registry/retrieval_tool.py (which used to own a private copy of
this) so SCIL (app/scil/) can reuse the exact same model/dimension instead
of introducing a second embedding provider. 384-dim, matching StudyBuddy's
own EMBEDDING_PROVIDER=local / MiniLM convention (see .env.example).
"""

from functools import lru_cache

EMBEDDING_DIM = 384


@lru_cache
def get_embedder():
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")


def embed_text(text: str) -> list[float]:
    return get_embedder().encode(text, normalize_embeddings=True).tolist()
