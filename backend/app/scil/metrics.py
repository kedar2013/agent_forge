import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.scil import ScilMetrics


async def record(
    session: AsyncSession,
    *,
    agent_id: uuid.UUID,
    request_id: uuid.UUID,
    route: str,
    llm_calls: int,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    retries: int = 0,
    latency_ms: int | None = None,
) -> None:
    session.add(
        ScilMetrics(
            agent_id=agent_id,
            request_id=request_id,
            route=route,
            llm_calls=llm_calls,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            retries=retries,
            latency_ms=latency_ms,
        )
    )
    await session.commit()
