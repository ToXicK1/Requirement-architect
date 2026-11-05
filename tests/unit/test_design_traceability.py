from requirements_architect.agent.stages.architecture import build_architecture
from requirements_architect.agent.stages.dataapi import build_data_api
from requirements_architect.agent.stages.qa_deploy import build_qa
from requirements_architect.agent.stages.security import build_security
from requirements_architect.schemas.architecture import RawArchitecture
from requirements_architect.schemas.dataapi import RawDataApi
from requirements_architect.schemas.qa import RawQaOutput
from requirements_architect.schemas.security import RawSecurityOutput
from requirements_architect.validation.design_traceability import (
    collect_approval_candidates,
    full_report,
)
from requirements_architect.validation.traceability import TraceKind
from tests.design_helpers import (
    make_reqs,
    raw_arch,
    raw_comp,
    raw_endpoint,
    raw_entity,
    raw_security,
)

REQS = make_reqs(2)


def parts(comp_reqs=("FR-001", "FR-002"), tc_reqs=("FR-001", "FR-002", "NFR-001")):
    arch = build_architecture(
        RawArchitecture.model_validate(
            raw_arch(components=[raw_comp("C1", requirement_ids=list(comp_reqs))])
        ),
        REQS,
    )
    api = build_data_api(
        RawDataApi.model_validate({"entities": [raw_entity()], "endpoints": [raw_endpoint()]}),
        REQS,
    )
    sec = build_security(RawSecurityOutput.model_validate(raw_security()), REQS)
    qa = build_qa(
        RawQaOutput.model_validate(
            {
                "test_cases": [
                    {
                        "key": "TC1",
                        "requirement_ids": list(tc_reqs),
                        "scenario": "s",
                        "steps": ["x"],
                        "expected_result": "ok",
                        "priority": "must",
                        "test_type": "unit",
                    }
                ],
                "deployment": {},
            }
        ),
        REQS,
    )
    return arch, api, sec, qa


def test_links_cover_every_design_kind():
    arch, api, sec, qa = parts()
    links, report = full_report(REQS, arch, api, sec, qa)
    kinds = {link.kind for link in links}
    assert {
        TraceKind.COMPONENT,
        TraceKind.ENTITY,
        TraceKind.ENDPOINT,
        TraceKind.CONTROL,
        TraceKind.TEST,
    } <= kinds
    assert report.dangling_links == []


def test_requirement_without_component_or_test_is_uncovered():
    arch, api, sec, qa = parts(comp_reqs=("FR-001",), tc_reqs=("FR-001",))
    _, report = full_report(REQS, arch, api, sec, qa)
    assert {TraceKind.COMPONENT, TraceKind.TEST} <= set(report.uncovered["FR-002"])
    assert not {TraceKind.COMPONENT, TraceKind.TEST} & set(report.uncovered.get("FR-001", []))


def test_missing_stages_make_requirements_uncovered_not_crash():
    _, report = full_report(REQS, None, None, None, None)
    assert TraceKind.TEST in report.uncovered["FR-001"]


def test_approval_candidates_are_gathered_from_all_present_specs():
    arch, api, sec, qa = parts()
    assert collect_approval_candidates(None, None, None, None, None, None) == []
    got = collect_approval_candidates(arch, None, sec, None, api, qa)
    assert len(got) == sum(len(s.approval_candidates) for s in (arch, sec, api, qa))
