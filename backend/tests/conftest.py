import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.config import get_settings
from app.db import async_session_factory
from app.main import app


@pytest_asyncio.fixture
async def client():
    settings = get_settings()
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"Authorization": f"Bearer {settings.agent_forge_api_token}"},
    ) as ac:
        yield ac


@pytest_asyncio.fixture
async def db_session():
    async with async_session_factory() as session:
        yield session


@pytest.fixture
def unique_name():
    def _make(prefix: str) -> str:
        return f"{prefix}_{uuid.uuid4().hex[:8]}"

    return _make


@pytest_asyncio.fixture
async def sql_fixture_table(db_session):
    """A throwaway table in agent_forge for sql_tool tests, dropped afterward."""
    table_name = f"test_fixture_{uuid.uuid4().hex[:8]}"
    await db_session.execute(
        text(f"CREATE TABLE agent_forge.{table_name} (id serial primary key, name text, value int)")
    )
    await db_session.execute(
        text(f"INSERT INTO agent_forge.{table_name} (name, value) VALUES ('alpha', 1), ('beta', 2)")
    )
    await db_session.commit()
    yield table_name
    await db_session.execute(text(f"DROP TABLE IF EXISTS agent_forge.{table_name}"))
    await db_session.commit()
