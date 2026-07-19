"""Publishes one or more agents by name, in-process over the same ASGI/DB
path as `POST /api/agents/{id}/publish` (as the admin static token — same
role a fresh CI checkout or a scripted bootstrap has, no interactive login
needed). Idempotent-ish: an agent already published gets re-published
(a harmless no-op snapshot refresh), never errors on that.

Mainly for scripted environments that need a freshly-seeded agent to have a
real published version before anything that requires one can run against it
— e.g. `scripts/eval_gate.py` (see .github/workflows/eval-gate.yml), which
can only evaluate a PUBLISHED agent's live behavior.

    python scripts/publish_agent.py credit_facility_analyst revenue_returns_analyst
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.db import async_session_factory  # noqa: E402
from app.main import app  # noqa: E402
from app.models.agents import Agent  # noqa: E402


async def publish(agent_names: list[str]) -> bool:
    settings = get_settings()
    all_ok = True
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://publish-agent",
        headers={"Authorization": f"Bearer {settings.agent_forge_api_token}"},
    ) as client:
        for name in agent_names:
            async with async_session_factory() as session:
                agent = await session.scalar(select(Agent).where(Agent.name == name))
            if agent is None:
                print(f"MISS {name}: no agent with this name found")
                all_ok = False
                continue
            resp = await client.post(f"/api/agents/{agent.id}/publish", json={"published_by": "publish_agent.py"})
            if resp.status_code == 200:
                body = resp.json()
                version = (body.get("version") or {}).get("version")
                print(f"OK   {name}: {body['status']} (version {version})")
            else:
                print(f"FAIL {name}: {resp.status_code} {resp.text}")
                all_ok = False
    return all_ok


def main() -> None:
    names = sys.argv[1:]
    if not names:
        print("Usage: python scripts/publish_agent.py <agent_name> [<agent_name> ...]")
        sys.exit(2)
    ok = asyncio.run(publish(names))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
