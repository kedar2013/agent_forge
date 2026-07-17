from app.tool_registry._templating import UNSET, bind_template


def test_binds_scalar_and_array_values():
    template = {"company_id": "{{company_id}}", "load_id": {"$in": "{{load_ids}}"}}
    bound = bind_template(template, {"company_id": "C0001", "load_ids": [202605, 202606]})
    assert bound == {"company_id": "C0001", "load_id": {"$in": [202605, 202606]}}


def test_omitted_optional_arg_drops_the_key_not_null_matches_nothing():
    template = {"company_id": "{{company_id}}", "gfcid": "{{gfcid}}"}
    bound = bind_template(template, {"company_id": "C0001"})
    assert bound == {"company_id": "C0001"}
    assert "gfcid" not in bound


def test_llm_cannot_inject_new_operators_only_values():
    """The template's shape (keys/operators) is fixed by the tool author;
    a `{{name}}` leaf can only ever be replaced by args[name]'s *value* --
    there is no code path that lets an arg string become a new dict key."""
    template = {"company_name": {"$regex": "{{name_query}}", "$options": "i"}}
    bound = bind_template(template, {"name_query": "$where: 1==1"})
    # The malicious-looking value is bound as a plain regex string, never
    # parsed back into query structure.
    assert bound == {"company_name": {"$regex": "$where: 1==1", "$options": "i"}}


def test_bare_placeholder_resolves_to_unset_sentinel():
    assert bind_template("{{missing}}", {}) is UNSET
