"""Real integration tests for app/durable_workflow/ — against a genuine
local Temporal dev server (temporalio.testing.WorkflowEnvironment.start_local,
which downloads and runs an actual ephemeral Temporal server binary), not a
mock. Skipped automatically if `temporalio` isn't installed (it's an
optional extra — see pyproject.toml's `[project.optional-dependencies].
temporal`) or if starting the local server fails (e.g. no network access
to fetch the server binary in a sandboxed CI runner).
"""

import uuid

import pytest
from sqlalchemy import select

from app.models.reliability_demo import ReliabilityDemoInventory, TemporalReservation

temporalio = pytest.importorskip("temporalio")

from temporalio.testing import WorkflowEnvironment  # noqa: E402
from temporalio.worker import Worker  # noqa: E402

from app.durable_workflow.activities import confirm_order, release_inventory, reserve_inventory  # noqa: E402
from app.durable_workflow.workflows import ReservationSagaInput, ReservationSagaWorkflow  # noqa: E402

_TASK_QUEUE = "test-reliability-queue"


@pytest.fixture(scope="module")
async def temporal_env():
    try:
        env = await WorkflowEnvironment.start_local()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"could not start a local Temporal dev server: {exc}")
    yield env
    await env.shutdown()


async def _seed_inventory(db_session, item: str, available: int) -> None:
    db_session.add(ReliabilityDemoInventory(item=item, available=available))
    await db_session.commit()


async def test_reservation_saga_confirms_successfully(temporal_env, db_session, unique_name):
    item = unique_name("widget")
    await _seed_inventory(db_session, item, available=10)

    async with Worker(
        temporal_env.client,
        task_queue=_TASK_QUEUE,
        workflows=[ReservationSagaWorkflow],
        activities=[reserve_inventory, confirm_order, release_inventory],
    ):
        result = await temporal_env.client.execute_workflow(
            ReservationSagaWorkflow.run,
            ReservationSagaInput(item=item, quantity=3, order_id="order-1"),
            id=f"test-saga-{uuid.uuid4()}",
            task_queue=_TASK_QUEUE,
        )

    assert result.status == "confirmed"

    row = await db_session.get(ReliabilityDemoInventory, item)
    await db_session.refresh(row)
    assert row.available == 7  # 10 - 3, never released since confirm succeeded

    reservation = await db_session.get(TemporalReservation, result.reservation_id)
    assert reservation.status == "confirmed"


async def test_reservation_saga_compensates_on_confirm_failure(temporal_env, db_session, unique_name):
    item = unique_name("widget")
    await _seed_inventory(db_session, item, available=10)

    async with Worker(
        temporal_env.client,
        task_queue=_TASK_QUEUE,
        workflows=[ReservationSagaWorkflow],
        activities=[reserve_inventory, confirm_order, release_inventory],
    ):
        result = await temporal_env.client.execute_workflow(
            ReservationSagaWorkflow.run,
            ReservationSagaInput(item=item, quantity=4, order_id="FORCE_FAIL"),
            id=f"test-saga-{uuid.uuid4()}",
            task_queue=_TASK_QUEUE,
        )

    assert result.status == "compensated"
    assert "declined" in result.detail.lower()

    row = await db_session.get(ReliabilityDemoInventory, item)
    await db_session.refresh(row)
    assert row.available == 10  # reserved 4, then released back -- proves compensation actually fired

    reservation = await db_session.get(TemporalReservation, result.reservation_id)
    assert reservation.status == "released"


async def test_reservation_saga_reports_insufficient_inventory_without_reserving(
    temporal_env, db_session, unique_name
):
    item = unique_name("widget")
    await _seed_inventory(db_session, item, available=2)

    async with Worker(
        temporal_env.client,
        task_queue=_TASK_QUEUE,
        workflows=[ReservationSagaWorkflow],
        activities=[reserve_inventory, confirm_order, release_inventory],
    ):
        result = await temporal_env.client.execute_workflow(
            ReservationSagaWorkflow.run,
            ReservationSagaInput(item=item, quantity=5, order_id="order-2"),
            id=f"test-saga-{uuid.uuid4()}",
            task_queue=_TASK_QUEUE,
        )

    assert result.status == "insufficient_inventory"

    row = await db_session.get(ReliabilityDemoInventory, item)
    await db_session.refresh(row)
    assert row.available == 2  # untouched -- never actually reserved


async def test_reserve_activity_is_idempotent_across_a_retry(temporal_env, db_session, unique_name):
    """Directly exercises the idempotency-key behavior activities.py
    documents: calling reserve_inventory twice with the SAME
    reservation_id (standing in for Temporal retrying an already-succeeded
    activity after e.g. a network blip on the response) must not
    double-decrement inventory."""
    from app.durable_workflow.activities import ReserveInput

    item = unique_name("widget")
    await _seed_inventory(db_session, item, available=10)
    reservation_id = f"idempotency-test-{uuid.uuid4()}"

    async with Worker(
        temporal_env.client,
        task_queue=_TASK_QUEUE,
        workflows=[ReservationSagaWorkflow],
        activities=[reserve_inventory, confirm_order, release_inventory],
    ):
        # Activities are plain async functions once decorated -- callable
        # directly for a focused unit-style check, no workflow needed.
        first = await reserve_inventory(ReserveInput(reservation_id=reservation_id, item=item, quantity=3))
        second = await reserve_inventory(ReserveInput(reservation_id=reservation_id, item=item, quantity=3))

    assert first.reserved is True
    assert second.reserved is True
    assert first.remaining == second.remaining == 7  # only decremented once, not twice
