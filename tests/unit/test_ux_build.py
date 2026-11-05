import pytest
from pydantic import ValidationError

from requirements_architect.agent.stages.dataapi import build_data_api
from requirements_architect.agent.stages.ux import build_ux
from requirements_architect.schemas.dataapi import RawDataApi
from requirements_architect.schemas.ux import RawUx
from tests.design_helpers import make_reqs, raw_endpoint, raw_entity

REQS = make_reqs(2)
API = build_data_api(
    RawDataApi.model_validate({"entities": [raw_entity()], "endpoints": [raw_endpoint()]}), REQS
)

FULL_STATES = [{"state": s, "description": "d"} for s in ("loading", "error", "empty", "populated")]


def screen(key="S1", **kw):
    base = {
        "key": key,
        "name": f"Screen {key}",
        "purpose": "p",
        "states": FULL_STATES,
        "accessibility": ["keyboard navigable"],
        "requirement_ids": ["FR-001"],
        "endpoint_ids": ["EP-001"],
    }
    return base | kw


def build(**kw):
    base = {
        "has_ui": True,
        "personas": [{"name": "Ann", "description": "d"}],
        "screens": [screen()],
    }
    return build_ux(RawUx.model_validate(base | kw), REQS, API)


def codes(spec):
    return [i.code for i in spec.issues]


def test_complete_ui_has_no_issues_and_gets_ids():
    spec = build(
        flows=[
            {
                "key": "FL1",
                "name": "Sign in",
                "actor": "user",
                "steps": ["open", "submit"],
                "requirement_ids": ["FR-001"],
            }
        ]
    )
    assert [s.id for s in spec.screens] == ["SCR-001"] and [f.id for f in spec.flows] == ["FL-001"]
    assert spec.issues == []


def test_api_only_project_drops_invented_screens_and_requires_interface_note():
    spec = build(has_ui=False, screens=[screen()], navigation=["Home"], design_system=["Material"])
    assert spec.screens == [] and spec.navigation == [] and spec.design_system == []
    assert {"SCREENS_FOR_NON_UI_PROJECT", "NO_INTERFACE_SPEC"} <= set(codes(spec))
    ok = build(has_ui=False, screens=[], interface_note="REST API consumed by partner systems.")
    assert ok.issues == [] and ok.interface_note.startswith("REST")


def test_ui_project_without_screens_is_an_error():
    spec = build(screens=[], personas=[])
    errs = [i for i in spec.issues if i.code == "NO_SCREENS"]
    assert errs and errs[0].severity.value == "error" and "NO_PERSONAS" in codes(spec)


def test_every_screen_must_define_loading_error_and_empty_states():
    spec = build(
        screens=[
            screen("S1", states=[{"state": "populated", "description": "d"}], accessibility=[]),
            screen("S2", states=[{"state": "loading", "description": "d"}]),
        ]
    )
    missing = [
        (i.ref, i.message.split()[-2]) for i in spec.issues if i.code == "SCREEN_MISSING_STATE"
    ]
    assert missing == [
        ("SCR-001", "loading"),
        ("SCR-001", "error"),
        ("SCR-001", "empty"),
        ("SCR-002", "error"),
        ("SCR-002", "empty"),
    ]
    assert [i.ref for i in spec.issues if i.code == "SCREEN_NO_ACCESSIBILITY"] == ["SCR-001"]


def test_unknown_requirement_and_endpoint_references_dropped():
    spec = build(
        screens=[screen(requirement_ids=["FR-001", "FR-404"], endpoint_ids=["EP-001", "EP-404"])],
        flows=[
            {"key": "FL1", "name": "n", "actor": "a", "steps": ["s"], "requirement_ids": ["FR-404"]}
        ],
    )
    assert spec.screens[0].requirement_ids == ["FR-001"] and spec.screens[0].endpoint_ids == [
        "EP-001"
    ]
    assert spec.flows[0].requirement_ids == []
    assert codes(spec).count("UNKNOWN_REQUIREMENT") == 2 and "UNKNOWN_ENDPOINT" in codes(spec)


def test_endpoint_references_with_no_api_known():
    spec = build_ux(
        RawUx.model_validate(
            {"has_ui": True, "personas": [{"name": "A", "description": "d"}], "screens": [screen()]}
        ),
        REQS,
        None,
    )
    assert spec.screens[0].endpoint_ids == [] and "UNKNOWN_ENDPOINT" in codes(spec)


def test_raw_schema_rejects_bad_input():
    for bad in (
        {"has_ui": True, "screens": [screen("S1"), screen("S1")]},
        {
            "has_ui": True,
            "flows": [
                {"key": "FL1", "name": "n", "actor": "a", "steps": ["s"]},
                {"key": "FL1", "name": "m", "actor": "a", "steps": ["s"]},
            ],
        },
        {"has_ui": True, "screens": [screen("home")]},
        {"has_ui": True, "screens": [screen(endpoint_ids=["EP1"])]},
        {"has_ui": True, "screens": [screen(states=[{"state": "weird", "description": "d"}])]},
        {"has_ui": True, "flows": [{"key": "FL1", "name": "n", "actor": "a", "steps": []}]},
    ):
        with pytest.raises(ValidationError):
            RawUx.model_validate(bad)
