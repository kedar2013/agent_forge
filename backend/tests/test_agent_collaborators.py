import uuid

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.auth_users import hash_password, issue_user_token
from app.main import app
from app.models.users import User


async def _make_developer(db_session, unique_name) -> tuple[AsyncClient, str]:
    """A real developer-role user, approved and ready to log in — returns a
    client authenticated as them, plus their email (== _actor(principal) and
    == User.created_by on anything they create)."""
    email = f"{unique_name('dev')}@example.com"
    user = User(
        email=email,
        password_hash=hash_password("irrelevant"),
        role="developer",
        status="approved",
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    token = issue_user_token(str(user.id))
    transport = ASGITransport(app=app)
    client = AsyncClient(transport=transport, base_url="http://test", headers={"Authorization": f"Bearer {token}"})
    return client, email


async def _create_agent_as(dev_client, unique_name, name_prefix="collab_agent"):
    resp = await dev_client.post(
        "/api/agents",
        json={
            "name": unique_name(name_prefix),
            "description": "collaborator test agent",
            "base_instruction": "You are a test agent.",
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def test_non_owner_developer_cannot_modify_agent(db_session, unique_name):
    dev_a, _ = await _make_developer(db_session, unique_name)
    dev_b, _ = await _make_developer(db_session, unique_name)
    try:
        agent = await _create_agent_as(dev_a, unique_name)

        resp = await dev_b.patch(f"/api/agents/{agent['id']}", json={"description": "hijacked"})
        assert resp.status_code == 403
    finally:
        await dev_a.aclose()
        await dev_b.aclose()


async def test_owner_can_add_collaborator_who_can_then_modify(db_session, unique_name):
    dev_a, email_a = await _make_developer(db_session, unique_name)
    dev_b, email_b = await _make_developer(db_session, unique_name)
    try:
        agent = await _create_agent_as(dev_a, unique_name)

        # Still blocked before being added.
        resp = await dev_b.patch(f"/api/agents/{agent['id']}", json={"description": "not yet"})
        assert resp.status_code == 403

        # Owner (dev_a) adds dev_b as a collaborator.
        resp = await dev_a.post(f"/api/agents/{agent['id']}/collaborators", json={"user_email": email_b})
        assert resp.status_code == 204, resp.text

        resp = await dev_a.get(f"/api/agents/{agent['id']}/collaborators")
        assert resp.status_code == 200
        assert [c["user_email"] for c in resp.json()] == [email_b]

        # Now dev_b can modify it.
        resp = await dev_b.patch(f"/api/agents/{agent['id']}", json={"description": "collaborator edit"})
        assert resp.status_code == 200, resp.text
        assert resp.json()["description"] == "collaborator edit"

        # A mere collaborator (not the owner) cannot grant access to a third party.
        dev_c, email_c = await _make_developer(db_session, unique_name)
        try:
            resp = await dev_b.post(f"/api/agents/{agent['id']}/collaborators", json={"user_email": email_c})
            assert resp.status_code == 403
        finally:
            await dev_c.aclose()

        # Owner removes dev_b -- access is revoked again.
        resp = await dev_a.delete(f"/api/agents/{agent['id']}/collaborators/{email_b}")
        assert resp.status_code == 204
        resp = await dev_b.patch(f"/api/agents/{agent['id']}", json={"description": "revoked"})
        assert resp.status_code == 403
    finally:
        await dev_a.aclose()
        await dev_b.aclose()


async def test_add_collaborator_validates_target_user(db_session, unique_name):
    dev_a, _ = await _make_developer(db_session, unique_name)
    try:
        agent = await _create_agent_as(dev_a, unique_name)

        resp = await dev_a.post(
            f"/api/agents/{agent['id']}/collaborators", json={"user_email": "nobody@example.com"}
        )
        assert resp.status_code == 404

        # admin's own client (the shared `client` fixture) has no email --
        # verify a non-developer role is rejected using a viewer account instead.
        viewer_email = f"{unique_name('viewer')}@example.com"
        viewer = User(
            email=viewer_email,
            password_hash=hash_password("irrelevant"),
            role="viewer",
            status="approved",
        )
        db_session.add(viewer)
        await db_session.commit()

        resp = await dev_a.post(
            f"/api/agents/{agent['id']}/collaborators", json={"user_email": viewer_email}
        )
        assert resp.status_code == 422
    finally:
        await dev_a.aclose()
