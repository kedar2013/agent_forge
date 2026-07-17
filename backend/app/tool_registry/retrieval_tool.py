import os
import re
from typing import Any

import numpy as np
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.embeddings import embed_text as _embed
from app.tool_registry.base import ConfigDrivenTool
from app.tool_registry.serialize import to_json_safe

_engine_cache: dict[str, AsyncEngine] = {}
_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)?$")


def _get_engine(connection_url: str) -> AsyncEngine:
    if connection_url not in _engine_cache:
        _engine_cache[connection_url] = create_async_engine(connection_url, pool_pre_ping=True)
    return _engine_cache[connection_url]


def _assert_safe_identifier(value: str, field_name: str) -> None:
    if not _IDENTIFIER_RE.match(value):
        raise ValueError(f"Unsafe identifier for {field_name}: {value!r}")


def _normalize_state_filter_map(raw: list[str] | dict[str, str]) -> dict[str, str]:
    """`state_filter_columns` accepts either a plain list (state key == column
    name) or a dict mapping state key -> column name, for cases like
    StudyBuddy's own `class_grade` session-state key mapping to a `grade`
    column."""
    if isinstance(raw, dict):
        return raw
    return {key: key for key in raw}


def _parse_vector_literal(text_value: str) -> np.ndarray:
    # pgvector's text representation is "[0.1,0.2,...]"
    return np.array([float(v) for v in text_value.strip("[]").split(",")])


def _cosine_sim(a: np.ndarray, b: np.ndarray) -> float:
    denom = (np.linalg.norm(a) * np.linalg.norm(b)) + 1e-9
    return float(np.dot(a, b) / denom)


def _mmr_select(query_vec: np.ndarray, candidates: list[dict], top_k: int, lam: float = 0.5) -> list[dict]:
    """Maximal Marginal Relevance re-ranking — avoids a top-k dominated by
    near-duplicate passages from one cluster/book, matching StudyBuddy's own
    search_knowledge_base behavior."""
    vecs = [c["_embedding_vec"] for c in candidates]
    relevances = [_cosine_sim(query_vec, v) for v in vecs]

    selected: list[int] = []
    remaining = list(range(len(candidates)))

    while remaining and len(selected) < top_k:
        if not selected:
            best = max(remaining, key=lambda i: relevances[i])
        else:
            def mmr_score(i: int) -> float:
                max_sim = max(_cosine_sim(vecs[i], vecs[j]) for j in selected)
                return lam * relevances[i] - (1 - lam) * max_sim

            best = max(remaining, key=mmr_score)
        selected.append(best)
        remaining.remove(best)

    return [candidates[i] for i in selected]


class RetrievalTool(ConfigDrivenTool):
    """pgvector similarity search over a fixed table/collection.

    `config` shape:
        {
          "connection_env": "DATABASE_URL",
          "table": "public.document_chunks",   # schema-qualified, locked at creation
          "embedding_column": "embedding",
          "text_column": "content",
          "top_k": 5,
          "state_filter_columns": ["grade", "subject", "book_id"],  # optional
          "rerank": "mmr",       # optional, "mmr" or omit for plain top-k
          "mmr_lambda": 0.5
        }

    Table/column names come from the tool's locked config (set once by
    whoever authors the tool row), never from the LLM's runtime arguments —
    only the free-text `query` is LLM-supplied, and it is always sent as a
    bound parameter, never interpolated into the SQL string.

    `state_filter_columns` lets a tool scope results by ADK session state
    (e.g. the student's grade/subject/book_id) rather than LLM-supplied
    args — the model can ask for anything, but it can never widen the scope
    beyond what the session already knows, since these values never come
    from `args`.
    """

    def __init__(self, *, name: str, description: str, input_schema: dict, config: dict) -> None:
        super().__init__(name=name, description=description, input_schema=input_schema)
        table = config["table"]
        embedding_column = config.get("embedding_column", "embedding")
        text_column = config.get("text_column", "content")
        _assert_safe_identifier(table, "table")
        _assert_safe_identifier(embedding_column, "embedding_column")
        _assert_safe_identifier(text_column, "text_column")
        for col in _normalize_state_filter_map(config.get("state_filter_columns", [])).values():
            _assert_safe_identifier(col, "state_filter_columns")
        self._config = config

    async def run_async(self, *, args: dict[str, Any], tool_context) -> Any:
        config = self._config
        connection_url = os.environ[config["connection_env"]]
        engine = _get_engine(connection_url)

        table = config["table"]
        embedding_column = config.get("embedding_column", "embedding")
        text_column = config.get("text_column", "content")
        top_k = config.get("top_k", 5)
        state_filter_map = _normalize_state_filter_map(config.get("state_filter_columns", []))
        use_mmr = config.get("rerank") == "mmr"
        pool_size = max(top_k * 3, 20) if use_mmr else top_k

        embedding = _embed(args["query"])
        embedding_literal = "[" + ",".join(str(v) for v in embedding) + "]"

        params: dict[str, Any] = {"embedding": embedding_literal, "pool_size": pool_size}
        where_clauses = []
        state = getattr(tool_context, "state", {}) or {}
        for state_key, column in state_filter_map.items():
            value = state.get(state_key)
            if value is not None:
                where_clauses.append(f"{column} = :{column}")
                params[column] = value
        where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

        embedding_select = f", {embedding_column}::text AS _embedding_text" if use_mmr else ""

        query = text(
            f"""
            SELECT {text_column} AS content,
                   1 - ({embedding_column} <=> CAST(:embedding AS vector)) AS similarity
                   {embedding_select}
            FROM {table}
            {where_sql}
            ORDER BY {embedding_column} <=> CAST(:embedding AS vector)
            LIMIT :pool_size
            """
        )

        async with engine.connect() as conn:
            result = await conn.execute(query, params)
            candidates = [dict(row._mapping) for row in result.fetchall()]

        if use_mmr and candidates:
            for c in candidates:
                c["_embedding_vec"] = _parse_vector_literal(c.pop("_embedding_text"))
            candidates = _mmr_select(
                np.array(embedding), candidates, top_k, lam=config.get("mmr_lambda", 0.5)
            )
            for c in candidates:
                c.pop("_embedding_vec", None)

        rows = [to_json_safe(c) for c in candidates[:top_k]]
        return {"row_count": len(rows), "rows": rows}
