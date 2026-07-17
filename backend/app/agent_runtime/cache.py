import uuid
from typing import Any


class AgentCache:
    """In-memory cache of built ADK Agent objects.

    Keyed by (agent_id, version). Publishing invalidates every cached
    version for that agent_id, forcing a rebuild from the fresh config
    on the next request instead of rebuilding from Postgres on every call.
    """

    def __init__(self) -> None:
        self._store: dict[tuple[uuid.UUID, int | None], Any] = {}

    def get(self, agent_id: uuid.UUID, version: int | None) -> Any | None:
        return self._store.get((agent_id, version))

    def set(self, agent_id: uuid.UUID, version: int | None, agent: Any) -> None:
        self._store[(agent_id, version)] = agent

    def invalidate(self, agent_id: uuid.UUID) -> None:
        for key in [k for k in self._store if k[0] == agent_id]:
            del self._store[key]

    def clear(self) -> None:
        self._store.clear()


agent_cache = AgentCache()
