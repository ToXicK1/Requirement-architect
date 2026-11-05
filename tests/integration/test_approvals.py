import pytest

from requirements_architect.agent.approvals import (
    ApprovalError,
    ApprovalService,
    ApprovalState,
    Decision,
)
from requirements_architect.schemas.architecture import ArchitectureSpec
from requirements_architect.schemas.common import ApprovalCandidate
from requirements_architect.schemas.requirements import (
    NfrCategory,
    NonFunctionalRequirement,
    RequirementsSpec,
    TargetStatus,
)
from requirements_architect.schemas.state import StageId
from requirements_architect.storage.approvals import ApprovalRepository
from tests.audit_helpers import QA_OK, SECURITY_OK
from tests.conftest import Script as BaseScript
from tests.conftest import make_stack
from tests.fakes import FakeSearch
from tests.research_helpers import make_service


def Script(**kw):
    kw.setdefault("security", [SECURITY_OK])
    kw.setdefault("qa_deploy", [QA_OK])
    return BaseScript(**kw)


def factory(repo, gateway):
    return make_service(gateway, repo, providers=[FakeSearch("brave", [])])


async def setup(st):
    p = await st.repo.create_project("Demo", "We need a thing.")
    await st.service.start(p.id)
    got = await st.repo.get_latest_output(p.id, StageId.ARCHITECTURE, ArchitectureSpec)
    arch = got[1]
    arch.approval_candidates = [
        ApprovalCandidate(
            source_stage=StageId.ARCHITECTURE.value,
            ref="AD-001",
            decision="Use a modular monolith",
            reason="irreversible",
        )
    ]
    await st.repo.save_stage_output(p.id, StageId.ARCHITECTURE, arch, got[0].depends_on)
    rq = await st.repo.get_latest_output(p.id, StageId.REQUIREMENTS, RequirementsSpec)
    spec = rq[1]
    nfr = NonFunctionalRequirement(
        id="NFR-001",
        category=NfrCategory.PERFORMANCE,
        statement="Pages respond quickly",
        target="p95 < 300ms",
        target_status=TargetStatus.PROPOSED,
        measurement_method="load test",
        rationale="r",
        finding_ids=[],
    )
    spec.nonfunctional = [nfr]
    await st.repo.save_stage_output(p.id, StageId.REQUIREMENTS, spec, rq[0].depends_on)
    return p, nfr.id


def svc(st):
    return ApprovalService(st.repo, ApprovalRepository(st.repo._factory), st.gateway)


async def test_requests_cover_candidates_and_proposed_targets_and_start_pending(tmp_path):
    async with make_stack(tmp_path, Script(), research_factory=factory) as st:
        p, nfr_id = await setup(st)
        reqs = await svc(st).list(p.id)
        by = {r.ref: r for r in reqs}
        assert by["AD-001"].state is ApprovalState.PENDING and by["AD-001"].recommended is None
        assert by[nfr_id].kind == "nfr_target" and by[nfr_id].state is ApprovalState.PENDING
        assert by["AD-001"].affected_documents


async def test_approve_records_actor_and_survives_reload(tmp_path):
    async with make_stack(tmp_path, Script(), research_factory=factory) as st:
        p, _ = await setup(st)
        s = svc(st)
        req = next(r for r in await s.list(p.id) if r.ref == "AD-001")
        out = await s.decide(
            p.id, req.stage_id, "AD-001", req.fingerprint, Decision.APPROVE, "ok", "u1"
        )
        assert out.state is ApprovalState.APPROVED and out.decided_by == "u1"
        again = next(r for r in await svc(st).list(p.id) if r.ref == "AD-001")
        assert again.state is ApprovalState.APPROVED and again.note == "ok"


async def test_changed_decision_asks_again(tmp_path):
    async with make_stack(tmp_path, Script(), research_factory=factory) as st:
        p, _ = await setup(st)
        s = svc(st)
        req = next(r for r in await s.list(p.id) if r.ref == "AD-001")
        await s.decide(p.id, req.stage_id, "AD-001", req.fingerprint, Decision.APPROVE, "", "u1")
        got = await st.repo.get_latest_output(p.id, StageId.ARCHITECTURE, ArchitectureSpec)
        arch = got[1]
        arch.approval_candidates[0].decision = "Use microservices"
        await st.repo.save_stage_output(p.id, StageId.ARCHITECTURE, arch, got[0].depends_on)
        now = next(r for r in await s.list(p.id) if r.ref == "AD-001")
        assert now.state is ApprovalState.PENDING and now.fingerprint != req.fingerprint
        with pytest.raises(ApprovalError, match="changed"):
            await s.decide(
                p.id, req.stage_id, "AD-001", req.fingerprint, Decision.APPROVE, "", "u1"
            )


async def test_reject_is_recorded_and_not_approved(tmp_path):
    async with make_stack(tmp_path, Script(), research_factory=factory) as st:
        p, _ = await setup(st)
        s = svc(st)
        req = next(r for r in await s.list(p.id) if r.ref == "AD-001")
        out = await s.decide(
            p.id, req.stage_id, "AD-001", req.fingerprint, Decision.REJECT, "no", "u1"
        )
        assert out.state is ApprovalState.REJECTED
        assert (await s.states(p.id))[(StageId.ARCHITECTURE.value, "AD-001")] == "rejected"


async def test_approving_a_target_saves_a_new_requirements_version(tmp_path):
    async with make_stack(tmp_path, Script(), research_factory=factory) as st:
        p, nfr_id = await setup(st)
        s = svc(st)
        before = await st.repo.list_versions(p.id, StageId.REQUIREMENTS)
        req = next(r for r in await s.list(p.id) if r.ref == nfr_id)
        out = await s.decide(
            p.id, req.stage_id, nfr_id, req.fingerprint, Decision.APPROVE, "", "u1"
        )
        assert out.state is ApprovalState.APPROVED
        after = await st.repo.list_versions(p.id, StageId.REQUIREMENTS)
        assert after == [*before, before[-1] + 1]
        _, latest = await st.repo.get_latest_output(p.id, StageId.REQUIREMENTS, RequirementsSpec)
        assert (
            next(n for n in latest.nonfunctional if n.id == nfr_id).target_status
            is TargetStatus.USER_APPROVED
        )


async def test_revision_needs_a_note_and_regenerates_chain_with_feedback(tmp_path):
    script = Script()
    async with make_stack(tmp_path, script, research_factory=factory) as st:
        p, _ = await setup(st)
        s = svc(st)
        req = next(r for r in await s.list(p.id) if r.ref == "AD-001")
        with pytest.raises(ApprovalError, match="note"):
            await s.decide(
                p.id, req.stage_id, "AD-001", req.fingerprint, Decision.REQUEST_REVISION, " ", "u1"
            )
        before = dict(script.calls)
        await s.decide(
            p.id,
            req.stage_id,
            "AD-001",
            req.fingerprint,
            Decision.REQUEST_REVISION,
            "Prefer queues",
            "u1",
        )
        for k in ("architecture", "technology", "data_api", "security", "ux", "qa_deploy"):
            assert script.calls[k] == before[k] + 1
        fb = [r for r in script.requests if "Prefer queues" in r.messages[0].content]
        assert len(fb) == 1 and "audit_feedback" in fb[0].messages[0].content


async def test_revision_without_gateway_is_refused_and_unknown_request_rejected(tmp_path):
    async with make_stack(tmp_path, Script(), research_factory=factory) as st:
        p, _ = await setup(st)
        s = ApprovalService(st.repo, ApprovalRepository(st.repo._factory))
        req = next(r for r in await s.list(p.id) if r.ref == "AD-001")
        with pytest.raises(ApprovalError, match="gateway"):
            await s.decide(
                p.id, req.stage_id, "AD-001", req.fingerprint, Decision.REQUEST_REVISION, "x", "u1"
            )
        with pytest.raises(ApprovalError, match="no such"):
            await s.decide(p.id, StageId.UX, "NOPE", "f", Decision.APPROVE, "", "u1")


async def test_notes_are_scrubbed_of_secrets(tmp_path):
    async with make_stack(tmp_path, Script(), research_factory=factory) as st:
        p, _ = await setup(st)
        s = svc(st)
        req = next(r for r in await s.list(p.id) if r.ref == "AD-001")
        out = await s.decide(
            p.id,
            req.stage_id,
            "AD-001",
            req.fingerprint,
            Decision.APPROVE,
            "key sk-ant-api03-" + "A" * 40,
            "u1",
        )
        assert "AAAA" not in out.note


async def test_the_latest_decision_wins(tmp_path):
    async with make_stack(tmp_path, Script(), research_factory=factory) as st:
        p, _ = await setup(st)
        s = svc(st)
        req = next(r for r in await s.list(p.id) if r.ref == "AD-001")
        await s.decide(p.id, req.stage_id, "AD-001", req.fingerprint, Decision.APPROVE, "", "u1")
        await s.decide(
            p.id, req.stage_id, "AD-001", req.fingerprint, Decision.REJECT, "changed mind", "u2"
        )
        now = next(r for r in await s.list(p.id) if r.ref == "AD-001")
        assert now.state is ApprovalState.REJECTED and now.decided_by == "u2"
