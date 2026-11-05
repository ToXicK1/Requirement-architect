from dataclasses import replace

from requirements_architect.generators.docs.package import build_package
from requirements_architect.schemas.common import ApprovalCandidate
from tests.doc_helpers import make_inputs


def with_candidate(state=None):
    i = make_inputs()
    arch = i.architecture.model_copy(
        update={
            "approval_candidates": [
                ApprovalCandidate(
                    source_stage="stage_05_architecture", ref="AD-001", decision="d", reason="r"
                )
            ]
        }
    )
    states = {"stage_05_architecture/AD-001": state} if state else {}
    return replace(i, architecture=arch, approval_states=states)


def test_undecided_is_pending():
    i = with_candidate()
    assert i.pending_approvals == 1 and "await human approval" in i.approval_status


def test_approved_is_not_pending_but_package_still_draft():
    i = with_candidate("approved")
    assert i.pending_approvals == 0
    assert "1 item(s) approved" in i.approval_status and i.approval_status.startswith("DRAFT")


def test_rejected_and_revision_counted():
    assert "1 rejected" in with_candidate("rejected").approval_status
    assert "1 sent back" in with_candidate("revision_requested").approval_status


def test_handoff_table_shows_state():
    pkg = build_package(with_candidate("rejected"))
    text = next(d.body for d in pkg.docs if d.path.endswith("CODING_AGENT_INSTRUCTIONS.md"))
    assert "AD-001" in text and "rejected" in text and "NOT approved" in text
