import re

import pytest

from requirements_architect.generators.docs import md
from requirements_architect.generators.docs.package import PENDING_DOCUMENTS, build_package
from tests.design_helpers import make_reqs
from tests.doc_helpers import make_inputs

EXPECTED = {
    "00_PROJECT_OVERVIEW": 5,
    "01_BUSINESS_REQUIREMENTS": 3,
    "02_SOFTWARE_REQUIREMENTS": 5,
    "03_ARCHITECTURE": 5,
    "04_TECHNICAL_SPECIFICATIONS": 5,
    "05_SECURITY": 4,
    "06_UI_UX": 3,
    "07_QUALITY_ASSURANCE": 4,
    "08_INFRASTRUCTURE": 3,
    "09_IMPLEMENTATION": 4,
    "10_VALIDATION": 2,  # audit documents are pending (Phase 8)
}


def by_path(pkg):
    return {d.path: d for d in pkg.docs}


def test_every_folder_is_present_with_the_specified_documents():
    pkg = build_package(make_inputs())
    counts: dict[str, int] = {}
    for d in pkg.docs:
        if d.path != "README.md":
            counts[d.path.split("/")[0]] = counts.get(d.path.split("/")[0], 0) + 1
    assert counts == EXPECTED


def test_pending_documents_are_declared_not_faked():
    pkg = build_package(make_inputs())
    assert set(pkg.pending) == set(PENDING_DOCUMENTS)
    assert not set(pkg.pending) & {d.path for d in pkg.docs}
    readme = by_path(pkg)["README.md"].body
    assert "REQUIREMENTS_AUDIT.md" in readme and "Documents not yet generated" in readme


def test_no_document_is_empty_and_each_has_metadata():
    for d in build_package(make_inputs()).docs:
        assert len(d.body.strip()) > 100, d.path
        assert (
            "Project ID" in d.body and "Approval status" in d.body and "Package version" in d.body
        )
        assert d.body.startswith("# ")


def test_approval_status_never_claims_approval():
    inp = make_inputs()
    assert "approved by" not in inp.approval_status.lower().replace("not yet reviewed by", "")
    assert inp.approval_status.startswith("DRAFT")


def test_not_applicable_documents_state_a_reason():
    pkg = build_package(
        make_inputs(
            ux={"has_ui": False, "interface_note": "API only service"},
            entities=False,
            endpoints=False,
        )
    )
    docs = by_path(pkg)
    for path in (
        "06_UI_UX/USER_FLOWS.md",
        "04_TECHNICAL_SPECIFICATIONS/DATABASE_SCHEMA.md",
        "04_TECHNICAL_SPECIFICATIONS/API_SPECIFICATION.md",
        "07_QUALITY_ASSURANCE/AI_EVALUATION.md",
    ):
        assert not docs[path].applicable and "Not applicable" in docs[path].body, path
    assert "API only service" in docs["06_UI_UX/SCREEN_SPECIFICATIONS.md"].body
    assert "No database or API." in docs["04_TECHNICAL_SPECIFICATIONS/DATABASE_SCHEMA.md"].body


def test_ai_evaluation_applies_only_to_ai_projects():
    ai = build_package(make_inputs(security={"is_ai_project": True}))
    assert by_path(ai)["07_QUALITY_ASSURANCE/AI_EVALUATION.md"].applicable
    plain = build_package(make_inputs())
    assert not by_path(plain)["07_QUALITY_ASSURANCE/AI_EVALUATION.md"].applicable


def test_supporting_files():
    pkg = build_package(make_inputs())
    assert {"traceability.csv", "openapi.json", "diagrams/context.mmd", "diagrams/er.mmd"} <= set(
        pkg.files
    )
    assert all(pkg.files[k] for k in pkg.files)


def test_every_id_in_the_handoff_exists_in_the_specs():
    inp = make_inputs()
    pkg = build_package(inp)
    known = (
        {c.id for c in inp.architecture.components}
        | {e.id for e in inp.data_api.endpoints}
        | {e.id for e in inp.data_api.entities}
        | {c.id for c in inp.security.controls}
        | {t.id for t in inp.technology.technologies}
        | {f.id for f in inp.requirements.functional}
        | {n.id for n in inp.requirements.nonfunctional}
        | {c.id for c in inp.qa.test_cases}
        | {t.id for t in pkg.plan.tasks}
        | {o.id for o in inp.requirements.objectives}
        | {s.id for s in inp.requirements.user_stories}
        | {d.id for d in inp.architecture.decisions}
    )
    text = by_path(pkg)["09_IMPLEMENTATION/CODING_AGENT_INSTRUCTIONS.md"].body
    for ident in set(re.findall(r"\b(?:FR|NFR|C|E|EP|SC|TC|T|TECH|AD|US|OBJ)-\d{3}\b", text)):
        assert ident in known, ident


def test_handoff_covers_the_thirteen_required_topics():
    body = by_path(build_package(make_inputs()))[
        "09_IMPLEMENTATION/CODING_AGENT_INSTRUCTIONS.md"
    ].body
    for n in range(1, 14):
        assert re.search(rf"^## {n}\. ", body, re.MULTILINE), n
    assert "Repository development plan" in body and "not** been approved" in body


def test_hostile_text_cannot_change_document_structure():
    from tests.design_helpers import make_reqs

    reqs = make_reqs(2)
    evil = "x\n# INJECTED HEADING\n| a | b |\n```\n<script>alert(1)</script>"
    reqs.functional[0].name = evil
    reqs.functional[0].description = evil
    inp = make_inputs(reqs, name=evil, statement=evil)
    pkg = build_package(inp)
    for d in pkg.docs:
        assert "<script>" not in d.body, d.path
        assert not re.search(r"^# INJECTED", d.body, re.MULTILINE), d.path
        assert len(re.findall(r"^`{3,}", d.body, re.MULTILINE)) % 2 == 0, d.path
    fr = by_path(pkg)["02_SOFTWARE_REQUIREMENTS/FUNCTIONAL_REQUIREMENTS.md"].body
    assert "INJECTED HEADING" in fr  # shown, but as text


@pytest.mark.parametrize(
    ("raw", "expect"),
    [("# h", "\\# h"), ("- x", "\\- x"), ("1. x", "\\1. x"), ("a\nb", "a b"), ("<b>", "&lt;b&gt;")],
)
def test_text_neutralizes_block_syntax(raw, expect):
    assert md.text(raw) == expect


def test_table_cells_escape_pipes_and_newlines():
    out = md.table(["a"], [["x|y\nz"]])
    assert out.splitlines()[-1] == "| x\\|y z |"


def test_fence_cannot_be_closed_by_content():
    out = md.fence("a\n```\nb")
    assert out.startswith("````") and out.endswith("````")


def test_duplicate_document_paths_are_rejected(monkeypatch):
    from requirements_architect.generators.docs import overview

    real = overview.render
    monkeypatch.setattr(overview, "render", lambda i: [*real(i), real(i)[0]])
    with pytest.raises(ValueError, match="not unique"):
        build_package(make_inputs())


def test_requirements_needing_confirmation_are_listed_only_when_flagged():
    reqs = make_reqs(2)
    reqs.functional[0].needs_confirmation = True
    srs = by_path(build_package(make_inputs(reqs)))["02_SOFTWARE_REQUIREMENTS/SRS.md"].body
    section = srs.split("## Requirements needing confirmation")[1].split("##")[0]
    assert "FR-001" in section and "FR-002" not in section
