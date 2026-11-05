import pytest

from requirements_architect.schemas.state import (
    ClarificationAnswer,
    Dependency,
    OutputStatus,
    ProjectBrief,
    StageId,
)
from requirements_architect.storage.repository import NotFoundError
from tests.conftest import Script, make_stack


def brief(text: str) -> ProjectBrief:
    return ProjectBrief(actual_problem=text, proposed_solution="s")


async def test_versions_append_and_supersede(tmp_path):
    async with make_stack(tmp_path, Script()) as st:
        p = await st.repo.create_project("n", "stmt")
        s = StageId.PROBLEM_UNDERSTANDING
        m1 = await st.repo.save_stage_output(p.id, s, brief("one"))
        m2 = await st.repo.save_stage_output(
            p.id, s, brief("two"), [Dependency(stage_id=s, version=1)]
        )
        assert (m1.version, m2.version) == (1, 2)
        assert await st.repo.list_versions(p.id, s) == [1, 2]  # nothing overwritten or deleted
        meta, latest = await st.repo.get_latest_output(p.id, s, ProjectBrief)
        assert latest.actual_problem == "two" and meta.status is OutputStatus.DRAFT
        assert meta.depends_on == [Dependency(stage_id=s, version=1)]
        from sqlalchemy import select

        from requirements_architect.storage.models import StageOutput

        async with st.repo._factory() as sess:
            rows = await sess.scalars(select(StageOutput).where(StageOutput.project_id == p.id))
            statuses = {r.version: r.status for r in rows}
        assert statuses == {1: "superseded", 2: "draft"}


async def test_projects_are_isolated(tmp_path):
    async with make_stack(tmp_path, Script()) as st:
        a = await st.repo.create_project("a", "x")
        b = await st.repo.create_project("b", "y")
        s = StageId.PROBLEM_UNDERSTANDING
        await st.repo.save_stage_output(a.id, s, brief("A"))
        assert await st.repo.get_latest_output(b.id, s, ProjectBrief) is None
        await st.repo.save_answers(a.id, [ClarificationAnswer(question_id="Q-001", answer="yes")])
        assert await st.repo.get_answers(b.id) == {}


async def test_answers_upsert_and_missing_project(tmp_path):
    async with make_stack(tmp_path, Script()) as st:
        p = await st.repo.create_project("n", "x")
        await st.repo.save_answers(p.id, [ClarificationAnswer(question_id="Q-001", answer="a")])
        await st.repo.save_answers(
            p.id,
            [ClarificationAnswer(question_id="Q-001", answer="b", accepted_recommendation=True)],
        )
        got = (await st.repo.get_answers(p.id))["Q-001"]
        assert got.answer == "b" and got.accepted_recommendation is True
        with pytest.raises(NotFoundError):
            await st.repo.get_project("does-not-exist")
