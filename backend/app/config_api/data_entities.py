import os
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.logging_hooks import write_audit_log
from app.models.data_entities import DataEntity
from app.principal import Principal, require_role
from app.schemas.data_entities import (
    ConnectionInfo,
    DataEntityCreate,
    DataEntityRead,
    DataEntityUpdate,
    IntrospectRequest,
    IntrospectResponse,
    ListTablesRequest,
    ListTablesResponse,
    TableInfo,
    TestConnectionRequest,
    TestConnectionResponse,
)

router = APIRouter(prefix="/data-entities", tags=["data-entities"])


def _actor(principal: Principal) -> str:
    return principal.email or f"{principal.role} (static token)"


@router.post("", response_model=DataEntityRead, status_code=201)
async def create_data_entity(
    payload: DataEntityCreate,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_role("admin")),
) -> DataEntity:
    existing = await db.scalar(
        select(DataEntity).where(DataEntity.name == payload.name, DataEntity.workspace_id == principal.workspace_id)
    )
    if existing is not None:
        raise HTTPException(status_code=409, detail=f"A data entity named '{payload.name}' already exists")
    entity = DataEntity(**payload.model_dump(exclude={"workspace_id"}), workspace_id=principal.workspace_id)
    db.add(entity)
    await db.flush()
    await write_audit_log(
        db, entity_type="data_entity", entity_id=entity.id, action="create",
        actor=_actor(principal), workspace_id=principal.workspace_id,
    )
    await db.commit()
    await db.refresh(entity)
    return entity


@router.get("", response_model=list[DataEntityRead])
async def list_data_entities(
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_role("admin", "viewer")),
) -> list[DataEntity]:
    result = await db.execute(
        select(DataEntity).where(DataEntity.workspace_id == principal.workspace_id).order_by(DataEntity.created_at.desc())
    )
    return list(result.scalars().all())


def _mysql_database_for(prefix: str) -> str | None:
    return os.environ.get(f"{prefix}_DATABASE") or os.environ.get(f"{prefix}_NAME")


def _mysql_connect(prefix: str):
    import pymysql

    database = _mysql_database_for(prefix)
    if not database:
        raise HTTPException(
            status_code=422, detail=f"{prefix}_DATABASE (or {prefix}_NAME) is not set in the backend's .env"
        )
    try:
        return pymysql.connect(
            host=os.environ.get(f"{prefix}_HOST", "localhost"),
            port=int(os.environ.get(f"{prefix}_PORT", "3306")),
            user=os.environ.get(f"{prefix}_USER", "root"),
            password=os.environ.get(f"{prefix}_PASSWORD", ""),
            database=database,
            cursorclass=pymysql.cursors.DictCursor,
            connect_timeout=5,
        )
    except Exception as exc:  # noqa: BLE001 — connection problems become a readable 422, not a 500
        raise HTTPException(status_code=422, detail=f"Could not connect using {prefix}_*: {exc}")


# NOTE: these literal-path routes must be registered BEFORE the
# /{entity_id} routes below — Starlette matches in registration order, so
# putting them later makes GET /connections parse "connections" as a UUID
# (422) and POST /test-connection a 405. Same trap main.py documents for
# agents_router's /agents/import.


@router.get("/connections", response_model=list[ConnectionInfo])
async def list_connections(
    principal: Principal = Depends(require_role("admin")),
) -> list[ConnectionInfo]:
    """Discovers usable MySQL connections from the backend's own env: any
    `{PREFIX}_HOST` that also has a `{PREFIX}_DATABASE` or `{PREFIX}_NAME`
    sibling. Lets the onboarding wizard offer a picker instead of asking
    admins to blind-type an env prefix they'd have to go read .env for."""
    connections: list[ConnectionInfo] = []
    for key in sorted(os.environ):
        if not key.endswith("_HOST"):
            continue
        prefix = key[: -len("_HOST")]
        database = _mysql_database_for(prefix)
        if not database:
            continue
        connections.append(
            ConnectionInfo(
                prefix=prefix,
                database=database,
                host=os.environ[key],
                port=int(os.environ.get(f"{prefix}_PORT", "3306")),
            )
        )
    return connections


@router.post("/test-connection", response_model=TestConnectionResponse)
async def test_connection(
    payload: TestConnectionRequest,
    principal: Principal = Depends(require_role("admin")),
) -> TestConnectionResponse:
    import asyncio

    prefix = payload.connection_env_prefix

    def _probe() -> TestConnectionResponse:
        conn = _mysql_connect(prefix)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT count(*) AS n FROM information_schema.tables WHERE table_schema = %s",
                    (_mysql_database_for(prefix),),
                )
                n = cur.fetchone()["n"]
        finally:
            conn.close()
        return TestConnectionResponse(ok=True, database=_mysql_database_for(prefix), table_count=n)

    return await asyncio.to_thread(_probe)


@router.post("/list-tables", response_model=ListTablesResponse)
async def list_tables(
    payload: ListTablesRequest,
    principal: Principal = Depends(require_role("admin")),
) -> ListTablesResponse:
    import asyncio

    prefix = payload.connection_env_prefix

    def _query() -> ListTablesResponse:
        conn = _mysql_connect(prefix)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT table_name, table_rows FROM information_schema.tables "
                    "WHERE table_schema = %s ORDER BY table_name",
                    (_mysql_database_for(prefix),),
                )
                tables = [{k.lower(): v for k, v in r.items()} for r in cur.fetchall()]
                cur.execute(
                    "SELECT table_name, count(*) AS n FROM information_schema.columns "
                    "WHERE table_schema = %s GROUP BY table_name",
                    (_mysql_database_for(prefix),),
                )
                count_rows = [{k.lower(): v for k, v in r.items()} for r in cur.fetchall()]
                col_counts = {r["table_name"]: r["n"] for r in count_rows}
        finally:
            conn.close()
        return ListTablesResponse(
            tables=[
                TableInfo(
                    name=t["table_name"],
                    column_count=col_counts.get(t["table_name"], 0),
                    row_estimate=t.get("table_rows") or 0,
                )
                for t in tables
            ]
        )

    return await asyncio.to_thread(_query)


@router.get("/{entity_id}", response_model=DataEntityRead)
async def get_data_entity(
    entity_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_role("admin", "viewer")),
) -> DataEntity:
    entity = await db.get(DataEntity, entity_id)
    if entity is None or entity.workspace_id != principal.workspace_id:
        raise HTTPException(status_code=404, detail="Data entity not found")
    return entity


@router.patch("/{entity_id}", response_model=DataEntityRead)
async def update_data_entity(
    entity_id: uuid.UUID,
    payload: DataEntityUpdate,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_role("admin")),
) -> DataEntity:
    entity = await db.get(DataEntity, entity_id)
    if entity is None or entity.workspace_id != principal.workspace_id:
        raise HTTPException(status_code=404, detail="Data entity not found")
    updates = payload.model_dump(exclude_unset=True)
    for key, value in updates.items():
        setattr(entity, key, value)
    await write_audit_log(
        db, entity_type="data_entity", entity_id=entity.id, action="update",
        actor=_actor(principal), diff=updates, workspace_id=principal.workspace_id,
    )
    await db.commit()
    await db.refresh(entity)
    return entity


@router.delete("/{entity_id}", status_code=204)
async def delete_data_entity(
    entity_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_role("admin")),
) -> None:
    entity = await db.get(DataEntity, entity_id)
    if entity is None or entity.workspace_id != principal.workspace_id:
        raise HTTPException(status_code=404, detail="Data entity not found")
    await write_audit_log(
        db, entity_type="data_entity", entity_id=entity.id, action="delete",
        actor=_actor(principal), workspace_id=principal.workspace_id,
    )
    await db.delete(entity)
    await db.commit()


@router.post("/introspect", response_model=IntrospectResponse)
async def introspect_source(
    payload: IntrospectRequest,
    principal: Principal = Depends(require_role("admin")),
) -> IntrospectResponse:
    """Reads real column names/types from an already-configured connection
    so an admin describes a table's shape by picking, not blind-typing —
    the same `information_schema.columns` source `nl2sql_tool.py`'s
    `DbSchemaTool` already queries for Postgres, generalized here to MySQL
    (and a best-effort document sample for Mongo)."""
    conn_type = payload.connection.get("type")
    if conn_type == "mysql":
        fields, primary_key = await _introspect_mysql(payload.connection, payload.table)
        return IntrospectResponse(fields=fields, primary_key=primary_key)
    if conn_type == "mongo":
        return IntrospectResponse(fields=await _introspect_mongo(payload.connection, payload.table))
    raise HTTPException(status_code=422, detail=f"Unsupported connection type: {conn_type!r}")


async def _introspect_mysql(connection: dict, table: str) -> tuple[list, str | None]:
    import asyncio

    from app.schemas.data_entities import IntrospectedField

    prefix = connection.get("connection_env_prefix")
    if not prefix:
        raise HTTPException(status_code=422, detail="connection.connection_env_prefix is required for mysql")

    def _query() -> tuple[list[IntrospectedField], str | None]:
        conn = _mysql_connect(prefix)
        database = _mysql_database_for(prefix)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT column_name, data_type, column_key FROM information_schema.columns "
                    "WHERE table_schema = %s AND table_name = %s ORDER BY ordinal_position",
                    (database, table),
                )
                rows = cur.fetchall()
        finally:
            conn.close()
        if not rows:
            raise HTTPException(status_code=404, detail=f"Table '{table}' has no columns (does it exist?)")
        # information_schema.columns' result-set casing varies by MySQL
        # server/version regardless of how the SELECT list is written
        # (confirmed: this server returns COLUMN_NAME/DATA_TYPE uppercase
        # even though the query says column_name/data_type) — read
        # case-insensitively rather than assuming one convention.
        normalized = [{k.lower(): v for k, v in r.items()} for r in rows]
        primary_key = next((r["column_name"] for r in normalized if r.get("column_key") == "PRI"), None)
        return [IntrospectedField(name=r["column_name"], type=r["data_type"]) for r in normalized], primary_key

    return await asyncio.to_thread(_query)


async def _introspect_mongo(connection: dict, collection: str) -> list:
    from motor.motor_asyncio import AsyncIOMotorClient

    from app.schemas.data_entities import IntrospectedField

    connection_env = connection.get("connection_env")
    database = connection.get("database")
    if not connection_env or not database:
        raise HTTPException(status_code=422, detail="connection.connection_env and connection.database are required for mongo")
    if connection_env not in os.environ:
        raise HTTPException(status_code=422, detail=f"{connection_env} is not set in the backend's .env")

    client = AsyncIOMotorClient(os.environ[connection_env])
    doc = await client[database][collection].find_one({})
    if doc is None:
        raise HTTPException(status_code=404, detail=f"Collection '{collection}' has no documents to sample")
    fields = []
    for key, value in doc.items():
        if key == "_id":
            continue
        py_type = type(value).__name__
        fields.append(IntrospectedField(name=key, type=py_type))
    return fields
