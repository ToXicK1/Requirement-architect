import pytest

from requirements_architect.llm.types import LLMTransientError
from requirements_architect.schemas.qa import QaSpec
from requirements_architect.schemas.state import StageId
from requirements_architect.schemas.technology import TechnologySpec
from tests.conftest import MINIMAL_QA, MINIMAL_TECH, Script, make_stack
from tests.fakes import FakeSearch
from tests.research_helpers import make_service

DESIGN = [
    StageId.ARCHITECTURE,
    StageId.TECHNOLOGY,
    StageId.DATA_API,
    StageId.SECURITY,
    StageId.UX,
    StageId.QA_DEPLOY,
]


def factory(repo, gateway):
    return make_service(gateway, repo, providers=[FakeSearch("brave", [])])


async def test_chain_persists_every_stage_with_dependencies(tmp_path):
    script = Script()
    async with make_stack(tmp_path, script, research_factory=factory) as st:
        p = await st.repo.create_project("n", "stmt")
        snap = await st.service.start(p.id)
        assert snap.status == "specifications_complete"
        for stage in DESIGN:
            assert await st.repo.list_versions(p.id, stage) == [1], stage
        meta, _ = await st.repo.get_latest_output(p.id, StageId.QA_DEPLOY, QaSpec)
        assert {d.stage_id for d in meta.depends_on} >= {
            StageId.REQUIREMENTS,
            StageId.SECURITY,
            StageId.UX,
        }
        assert all(d.version == 1 for d in meta.depends_on)
        for key in ("architecture", "technology", "data_api", "security", "ux", "qa_deploy"):
            assert script.calls[key] == 1


async def test_later_stage_failure_is_retryable_without_redoing_earlier_stages(tmp_path):
    script = Script(technology=[LLMTransientError("down"), MINIMAL_TECH])
    async with make_stack(tmp_path, script, research_factory=factory) as st:
        p = await st.repo.create_project("n", "stmt")
        with pytest.raises(LLMTransientError):
            await st.service.start(p.id)
        assert (await st.service.snapshot(p.id)).status == "failed"
        assert await st.repo.list_versions(p.id, StageId.ARCHITECTURE) == [1]
        assert await st.repo.list_versions(p.id, StageId.TECHNOLOGY) == []
        assert (await st.service.retry(p.id)).status == "specifications_complete"
        assert (script.calls["requirements"], script.calls["architecture"]) == (1, 1)
        assert await st.repo.list_versions(p.id, StageId.TECHNOLOGY) == [1]
        assert await st.repo.get_latest_output(p.id, StageId.TECHNOLOGY, TechnologySpec)


async def test_qa_issues_are_kept_not_hidden(tmp_path):
    bad = MINIMAL_QA | {
        "test_cases": [MINIMAL_QA["test_cases"][0] | {"test_data": ["password = hunter2hunter2"]}]
    }
    async with make_stack(tmp_path, Script(qa_deploy=[bad]), research_factory=factory) as st:
        p = await st.repo.create_project("n", "stmt")
        assert (await st.service.start(p.id)).status == "specifications_complete"
        _, qa = await st.repo.get_latest_output(p.id, StageId.QA_DEPLOY, QaSpec)
        assert "SECRET_IN_TEST_DATA" in [i.code for i in qa.issues]
        assert "hunter2hunter2" not in qa.model_dump_json()


async def test_dependency_records_the_latest_upstream_version(tmp_path):
    from requirements_architect.agent.design_nodes import DESIGN_STAGES, make_design_node
    from requirements_architect.schemas.security import SecuritySpec
    from requirements_architect.schemas.state import ProjectBrief

    async with make_stack(tmp_path, Script(), research_factory=factory) as st:
        p = await st.repo.create_project("n", "stmt")
        await st.service.start(p.id)
        _, sec = await st.repo.get_latest_output(p.id, StageId.SECURITY, SecuritySpec)
        await st.repo.save_stage_output(p.id, StageId.SECURITY, sec)  # security v2
        qa_stage = next(s for s in DESIGN_STAGES if s.stage_id is StageId.QA_DEPLOY)
        brief = await st.repo.get_latest_output(p.id, StageId.PROBLEM_UNDERSTANDING, ProjectBrief)
        state = {"project_id": p.id, "brief": brief[1].model_dump()}
        await make_design_node(st.gateway, st.repo, qa_stage, last=False)(state)
        meta, _ = await st.repo.get_latest_output(p.id, StageId.QA_DEPLOY, QaSpec)
        assert meta.version == 2
        deps = {d.stage_id: d.version for d in meta.depends_on}
        assert deps[StageId.SECURITY] == 2 and deps[StageId.UX] == 1
