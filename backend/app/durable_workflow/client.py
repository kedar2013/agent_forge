"""Temporal client + worker construction — shared by the API trigger
endpoint (reliability_api/router.py, lazy-imports this module only when a
request actually needs it) and scripts/run_temporal_worker.py.
"""

from temporalio.client import Client
from temporalio.worker import Worker

from app.config import get_settings
from app.durable_workflow.activities import confirm_order, release_inventory, reserve_inventory
from app.durable_workflow.workflows import ReservationSagaWorkflow


async def get_temporal_client() -> Client:
    settings = get_settings()
    return await Client.connect(settings.temporal_target, namespace=settings.temporal_namespace)


def build_worker(client: Client) -> Worker:
    settings = get_settings()
    return Worker(
        client,
        task_queue=settings.temporal_task_queue,
        workflows=[ReservationSagaWorkflow],
        activities=[reserve_inventory, confirm_order, release_inventory],
    )
