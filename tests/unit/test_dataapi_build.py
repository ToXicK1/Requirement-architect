import pytest
from pydantic import ValidationError

from requirements_architect.agent.stages.dataapi import build_data_api
from requirements_architect.generators.openapi import build_openapi, validate_structure
from requirements_architect.schemas.dataapi import RawDataApi
from tests.design_helpers import make_reqs, raw_endpoint, raw_entity

REQS = make_reqs(2)


def build(entities=(), endpoints=(), **kw):
    raw = RawDataApi.model_validate(
        {"entities": list(entities), "endpoints": list(endpoints), **kw}
    )
    return build_data_api(raw, REQS, "Demo")


def codes(spec):
    return [i.code for i in spec.issues]


def sev(spec, code):
    return {i.severity.value for i in spec.issues if i.code == code}


def test_ids_foreign_keys_and_er_diagram():
    orders = raw_entity(
        "E2",
        "orders",
        fields=[
            {"name": "id", "type": "uuid", "primary_key": True},
            {"name": "user_id", "type": "uuid"},
        ],
        foreign_keys=[{"field": "user_id", "references_entity": "E1"}],
        indexes=[{"fields": ["user_id"]}],
    )
    spec = build([raw_entity("E1", "users"), orders])
    assert [e.id for e in spec.entities] == ["E-001", "E-002"]
    fk = spec.entities[1].foreign_keys[0]
    assert (fk.references_entity, fk.references_field) == ("E-001", "id")
    assert 'orders }o--|| users : "user_id"' in spec.er_diagram
    assert [i for i in spec.issues if i.severity.value == "error"] == []


def test_entity_integrity_errors():
    bad_fk = raw_entity(
        "E2",
        "orders",
        foreign_keys=[
            {"field": "nope", "references_entity": "E1"},
            {"field": "email", "references_entity": "E9"},
            {"field": "email", "references_entity": "E1", "references_field": "missing"},
        ],
        indexes=[{"fields": ["ghost"]}],
    )
    spec = build(
        [
            raw_entity("E1", "users"),
            raw_entity("E3", "users"),  # duplicate table name
            raw_entity(
                "E4",
                "events",
                fields=[{"name": "ts", "type": "timestamp"}, {"name": "ts", "type": "text"}],
            ),
            bad_fk,
        ]
    )
    c = codes(spec)
    for expected in (
        "DUPLICATE_ENTITY",
        "DUPLICATE_FIELD",
        "ENTITY_NO_PRIMARY_KEY",
        "FK_UNKNOWN_FIELD",
        "FK_UNKNOWN_ENTITY",
        "FK_UNKNOWN_TARGET_FIELD",
        "INDEX_UNKNOWN_FIELD",
    ):
        assert expected in c, expected
    assert [e.name for e in spec.entities] == ["users", "events", "orders"]  # duplicate dropped
    orders = spec.entities[2]
    assert orders.foreign_keys == [] and orders.indexes == []
    assert len(spec.entities[1].fields) == 1
    assert sev(spec, "FK_UNKNOWN_ENTITY") == {"error"} and sev(spec, "INDEX_UNKNOWN_FIELD") == {
        "warning"
    }


def test_endpoint_validation_paths_and_duplicates():
    spec = build(
        [raw_entity()],
        [
            raw_endpoint("EP1", path="/users/{id}"),
            raw_endpoint("EP2", path="/users/{user_id}"),  # same shape + method as EP1
            raw_endpoint("EP3", path="users"),
            raw_endpoint("EP4", path="/a/../b"),
            raw_endpoint("EP5", path="/a?x=1"),
            raw_endpoint("EP6", path="/users/{id}", method="DELETE", success_status=204),
        ],
    )
    assert [e.id for e in spec.endpoints] == ["EP-001", "EP-006"]
    c = codes(spec)
    assert c.count("DUPLICATE_ENDPOINT") == 1 and c.count("ENDPOINT_INVALID_PATH") == 3


def test_security_checks():
    spec = build(
        [raw_entity()],
        [
            raw_endpoint("EP1", method="POST", authentication="none", path="/open"),
            raw_endpoint("EP2", authentication="none", path="/health", rate_limit="60/min"),
            raw_endpoint("EP3", authorization="", path="/a", error_responses=[]),
            raw_endpoint("EP4", path="/b", request_schema="Body"),
        ],
    )
    c = codes(spec)
    assert sev(spec, "UNAUTHENTICATED_MUTATION") == {"error"}
    assert [i.ref for i in spec.issues if i.code == "UNAUTHENTICATED_NO_RATE_LIMIT"] == ["EP-001"]
    assert [i.ref for i in spec.issues if i.code == "NO_AUTHORIZATION_RULE"] == ["EP-003"]
    assert [i.ref for i in spec.issues if i.code == "MISSING_AUTH_ERRORS"] == ["EP-003"]
    assert [i.ref for i in spec.issues if i.code == "MISSING_VALIDATION_ERROR"] == ["EP-004"]
    assert "STATUS_METHOD_MISMATCH" not in c


def test_status_method_mismatch():
    spec = build(
        [raw_entity()],
        [
            raw_endpoint("EP1", success_status=201),
            raw_endpoint("EP2", method="DELETE", path="/x", success_status=201),
        ],
    )
    assert [i.ref for i in spec.issues if i.code == "STATUS_METHOD_MISMATCH"] == [
        "EP-001",
        "EP-002",
    ]


def test_references_and_orphans():
    spec = build(
        [raw_entity("E1", requirement_ids=["FR-999"]), raw_entity("E2", "orders")],
        [raw_endpoint("EP1", entity_keys=["E1", "E9"], requirement_ids=[])],
    )
    c = codes(spec)
    assert {"UNKNOWN_REQUIREMENT", "ORPHAN_ENTITY", "UNKNOWN_ENTITY", "ORPHAN_ENDPOINT"} <= set(c)
    assert [i.ref for i in spec.issues if i.code == "ENTITY_NO_ENDPOINT"] == ["E-002"]


def test_no_database_or_api_requires_an_interface_note():
    assert "NO_INTERFACE_DEFINED" in codes(build())
    spec = build(interface_note="A CLI tool; no database and no HTTP API.")
    assert (
        spec.entities == []
        and spec.endpoints == []
        and spec.openapi == {}
        and spec.er_diagram == ""
    )
    assert "NO_INTERFACE_DEFINED" not in codes(spec)


def test_openapi_generated_and_structurally_valid():
    spec = build(
        [raw_entity()],
        [
            raw_endpoint("EP1", path="/users/{id}/orders/{order_id}", authentication="session"),
            raw_endpoint(
                "EP2",
                method="POST",
                path="/login",
                authentication="none",
                rate_limit="5/min",
                success_status=201,
                request_schema="Login",
                error_responses=[{"status": 400, "meaning": "bad"}],
            ),
        ],
    )
    doc = spec.openapi
    assert validate_structure(doc) == []
    op = doc["paths"]["/users/{id}/orders/{order_id}"]["get"]
    assert [p["name"] for p in op["parameters"]] == ["id", "order_id"]
    assert (
        op["security"] == [{"session": []}]
        and doc["components"]["securitySchemes"]["session"]["in"] == "cookie"
    )
    assert (
        doc["paths"]["/login"]["post"]["security"] == []
        and "201" in doc["paths"]["/login"]["post"]["responses"]
    )


def test_openapi_validator_detects_breakage():
    spec = build([raw_entity()], [raw_endpoint("EP1", path="/u/{id}")])
    doc = spec.openapi
    doc["paths"]["/u/{id}"]["get"]["parameters"] = []
    doc["paths"]["/u/{id}"]["get"]["responses"] = {}
    doc["paths"]["/u/{id}"]["get"]["security"] = [{"ghost": []}]
    doc["paths"]["bad"] = {"get": {"responses": {"200": {}}}}
    problems = " | ".join(validate_structure({**doc, "openapi": "2.0"}))
    for needle in (
        "openapi",
        "no responses",
        "path parameters",
        "unknown security scheme",
        "must start with",
    ):
        assert needle in problems, needle
    assert build_openapi("", [])["info"]["title"] == "API"


def test_raw_schema_rejects_bad_input():
    for bad in (
        {"entities": [raw_entity("E1"), raw_entity("E1", "other")]},
        {"entities": [raw_entity("E1", name="Users")]},
        {"entities": [raw_entity("E1", name="drop table;--")]},
        {"endpoints": [raw_endpoint("EP1"), raw_endpoint("EP1", path="/z")]},
        {"endpoints": [raw_endpoint("EP1", method="TRACE")]},
        {"endpoints": [raw_endpoint("EP1", success_status=404)]},
        {"endpoints": [raw_endpoint("EP1", error_responses=[{"status": 200, "meaning": "x"}])]},
    ):
        with pytest.raises(ValidationError):
            RawDataApi.model_validate(bad)
