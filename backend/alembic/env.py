import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.config import get_settings
from app.db import Base
from app.models import *  # noqa: F401,F403  (registers all models on Base.metadata)

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

settings = get_settings()
# Note: do NOT use config.set_main_option("sqlalchemy.url", ...) here — the
# password contains a literal "%" (from URL-encoding) which configparser's
# interpolation chokes on. We pass the URL directly to the engine instead.

target_metadata = Base.metadata
DB_SCHEMA = settings.db_schema


def include_name(name, type_, parent_names):
    if type_ == "schema":
        return name == DB_SCHEMA
    return True


def run_migrations_offline() -> None:
    context.configure(
        url=settings.database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        include_name=include_name,
        version_table_schema=DB_SCHEMA,
        include_schemas=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        include_name=include_name,
        version_table_schema=DB_SCHEMA,
        include_schemas=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    connectable = async_engine_from_config(
        {"sqlalchemy.url": settings.database_url},
        prefix="sqlalchemy.",
    )

    async with connectable.begin() as connection:
        await connection.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{DB_SCHEMA}"'))
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
