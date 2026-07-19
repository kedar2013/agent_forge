"""Standalone Temporal worker process for app/durable_workflow/ — runs
ReservationSagaWorkflow and its three activities against a real Temporal
server. Requires the `temporal` extra (`pip install -e ".[temporal]"`) and
TEMPORAL_ENABLED=true + a reachable TEMPORAL_TARGET (`docker compose up -d
temporal` for a local one) in backend/.env.

Run alongside the API server, not instead of it — the API process starts
workflows (see POST /api/reliability/temporal/reservations), this process
is what actually executes them:

    cd backend
    python scripts/run_temporal_worker.py
"""

import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings  # noqa: E402
from app.durable_workflow.client import build_worker, get_temporal_client  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


async def main() -> None:
    settings = get_settings()
    if not settings.temporal_enabled:
        logger.error("TEMPORAL_ENABLED is false — refusing to start a worker with nothing to do. Set it in .env.")
        sys.exit(1)

    client = await get_temporal_client()
    worker = build_worker(client)
    logger.info(
        "Temporal worker started — target=%s namespace=%s task_queue=%s",
        settings.temporal_target,
        settings.temporal_namespace,
        settings.temporal_task_queue,
    )
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
