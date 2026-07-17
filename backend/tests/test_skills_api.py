async def test_create_list_get_update_delete_skill(client, unique_name):
    name = unique_name("skill")
    payload = {
        "name": name,
        "instruction_text": "Always answer in bullet points.",
        "few_shot_examples": [{"input": "Explain X", "output": "- point one\n- point two"}],
        "tags": ["formatting"],
    }
    resp = await client.post("/api/skills", json=payload)
    assert resp.status_code == 201, resp.text
    skill = resp.json()
    skill_id = skill["id"]
    assert skill["few_shot_examples"][0]["input"] == "Explain X"
    assert skill["tags"] == ["formatting"]

    resp = await client.get("/api/skills")
    assert any(s["id"] == skill_id for s in resp.json())

    resp = await client.patch(f"/api/skills/{skill_id}", json={"instruction_text": "New instruction"})
    assert resp.status_code == 200
    assert resp.json()["instruction_text"] == "New instruction"

    resp = await client.delete(f"/api/skills/{skill_id}")
    assert resp.status_code == 204

    resp = await client.get(f"/api/skills/{skill_id}")
    assert resp.status_code == 404
