from collections.abc import AsyncGenerator

from sqlalchemy import MetaData
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import get_settings

settings = get_settings()

# All Agent Forge tables live in their own Postgres schema, separate from
# StudyBuddy's tables in the same database.
metadata = MetaData(schema=settings.db_schema)


class Base(DeclarativeBase):
    metadata = metadata


engine = create_async_engine(
    settings.database_url,
    connect_args={"server_settings": {"search_path": settings.db_schema}},
    pool_pre_ping=True,
)

async_session_factory = async_sessionmaker(engine, expire_on_commit=False)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_factory() as session:
        yield session
