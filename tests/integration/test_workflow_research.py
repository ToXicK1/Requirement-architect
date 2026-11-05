import pytest

from requirements_architect.llm.types import LLMTransientError
from requirements_architect.schemas.research import ResearchReport
from requirements_architect.schemas.state import ClarificationAnswer, Dependency, StageId
from tests.conftest import Script, make_stack, plan, q
from tests.fakes import FakeSearch
from tests.research_helpers import make_service


def factory(repo, gateway):
    return make_service(gateway, repo, providers=[FakeSearch("brave", [])])


async def test_research_runs_after_clarification_and_records_dependencies(tmp_path):
    script = Script(clarify=[plan(q("Q-001", "Which regions?")), plan()])
    async with make_stack(tmp_path, script, research_factory=factory) as st:
        p = await st.repo.create_project("n", "stmt")
        assert (await st.service.start(p.id)).status == "awaiting_clarification"
        assert script.calls["research_plan"] == 0  # research must wait for the answers
        snap = await st.service.resume(
            p.id, [ClarificationAnswer(question_id="Q-001", answer="EU only")]
        )
        assert snap.status == "requirements_complete"
        assert (await st.repo.get_project(p.id)).status == "requirements_complete"
        meta, report = await st.repo.get_latest_output(p.id, StageId.RESEARCH, ResearchReport)
        assert meta.depends_on == [
            Dependency(stage_id=StageId.PROBLEM_UNDERSTANDING, version=1),
            Dependency(stage_id=StageId.CLARIFICATION, version=2),
        ]
        assert report.feasibility_summary == "feasible"
        # the human's answer reaches the research prompts
        assert "EU only" in script.requests[-1].messages[0].content


async def test_research_failure_is_retryable_without_redoing_earlier_stages(tmp_path):
    from requirements_architect.llm.types import LLMTransientError as T

    script = Script(research_plan=[T("down"), {}])
    async with make_stack(tmp_path, script, research_factory=factory) as st:
        p = await st.repo.create_project("n", "stmt")
        with pytest.raises(LLMTransientError):
            await st.service.start(p.id)
        assert (await st.service.snapshot(p.id)).status == "failed"
        assert await st.repo.list_versions(p.id, StageId.RESEARCH) == []
        snap = await st.service.retry(p.id)
        assert snap.status == "requirements_complete"
        assert (script.calls["understand"], script.calls["clarify"]) == (1, 1)
        assert await st.repo.list_versions(p.id, StageId.RESEARCH) == [1]


async def test_without_research_service_workflow_still_ends_ready_for_research(tmp_path):
    async with make_stack(tmp_path, Script()) as st:
        p = await st.repo.create_project("n", "stmt")
        assert (await st.service.start(p.id)).status == "ready_for_research"
        assert script_calls_zero(st.script)


def script_calls_zero(script):
    return script.calls["research_plan"] == 0 and script.calls["research_synthesis"] == 0
