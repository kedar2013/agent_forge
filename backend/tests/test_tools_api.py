async def test_requires_auth():
    from httpx import ASGITransport, AsyncClient

    from app.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/api/tools")
    assert resp.status_code == 401


async def test_create_list_get_update_delete_tool(client, unique_name):
    name = unique_name("tool")
    create_payload = {
        "name": name,
        "tool_type": "http_tool",
        "description": "a test tool",
        "config": {"base_url": "https://example.com", "method": "GET", "path_template": "/x"},
        "input_schema": {"type": "object", "properties": {}},
    }
    resp = await client.post("/api/tools", json=create_payload)
    assert resp.status_code == 201, resp.text
    tool = resp.json()
    tool_id = tool["id"]
    assert tool["name"] == name

    resp = await client.get("/api/tools")
    assert resp.status_code == 200
    assert any(t["id"] == tool_id for t in resp.json())

    resp = await client.get(f"/api/tools/{tool_id}")
    assert resp.status_code == 200
    assert resp.json()["id"] == tool_id

    resp = await client.patch(f"/api/tools/{tool_id}", json={"description": "updated"})
    assert resp.status_code == 200
    assert resp.json()["description"] == "updated"

    resp = await client.delete(f"/api/tools/{tool_id}")
    assert resp.status_code == 204

    resp = await client.get(f"/api/tools/{tool_id}")
    assert resp.status_code == 404


async def test_get_missing_tool_404(client):
    import uuid

    resp = await client.get(f"/api/tools/{uuid.uuid4()}")
    assert resp.status_code == 404
