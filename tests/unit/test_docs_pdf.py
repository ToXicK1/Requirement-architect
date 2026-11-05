import io
import re

from pypdf import PdfReader

from requirements_architect.generators.docs.package import build_package
from requirements_architect.generators.docs.pdf import render_pdf
from tests.design_helpers import make_reqs
from tests.doc_helpers import make_inputs


def render(inp=None):
    inp = inp or make_inputs()
    pkg = build_package(inp)
    return inp, render_pdf(pkg.docs, inp, pkg.pending)


def pages_text(data: bytes) -> list[str]:
    return [p.extract_text() or "" for p in PdfReader(io.BytesIO(data)).pages]


def test_pdf_is_valid_and_has_cover_toc_page_numbers_and_chapters():
    _inp, res = render()
    assert res.data.startswith(b"%PDF") and res.pages >= 5
    pages = pages_text(res.data)
    assert len(pages) == res.pages
    assert "Demo project" in pages[0] and "Approval status" in pages[0] and "DRAFT" in pages[0]
    toc = "\n".join(pages[1:4])
    assert "Table of contents" in toc
    for chapter in (
        "Architecture",
        "Security",
        "Quality Assurance",
        "Implementation",
        "References",
    ):
        assert chapter in toc, chapter
    assert "Page 3" in pages[2] and "v1" in pages[2]
    body = "\n".join(pages)
    for needle in ("System Architecture", "Threat Model", "Coding Agent Instructions", "FR-001"):
        assert needle in body


def test_toc_page_numbers_point_at_real_headings():
    _, res = render()
    reader = PdfReader(io.BytesIO(res.data))
    toc = "\n".join(reader.pages[i].extract_text() for i in range(1, 4))
    m = re.search(r"Threat Model\s*(?:\.\s*)+(\d+)", toc)
    assert m, toc
    page_no = int(m.group(1))
    assert "Threat Model" in reader.pages[page_no - 1].extract_text()


def test_document_metadata_and_no_unfilled_markup():
    _, res = render()
    text = "\n".join(pages_text(res.data))
    assert "**" not in text and "&lt;" not in text and "&amp;" not in text
    assert PdfReader(io.BytesIO(res.data)).metadata.title == "Demo project"


def test_hostile_text_is_rendered_as_text_not_markup():
    reqs = make_reqs(2)
    evil = "<b>bold</b> <font size=99>big</font> <img src=file:///etc/passwd> & more"
    reqs.functional[0].description = evil
    inp = make_inputs(reqs, name=evil)
    _, res = render(inp)
    text = "\n".join(pages_text(res.data))
    assert "<b>bold</b>" in text and "<font size=99>" in text and "file:///etc/passwd" in text


def test_unsupported_characters_are_replaced_and_reported():
    reqs = make_reqs(2)
    reqs.functional[0].description = "cjk \u6f22\u5b57 and café"
    _, res = render(make_inputs(reqs))
    assert any("not supported" in w for w in res.warnings)
    assert "café" in "\n".join(pages_text(res.data))


def test_references_list_sources_when_research_exists():
    from datetime import UTC, datetime

    from requirements_architect.schemas.research import (
        Reliability,
        ResearchReport,
        Source,
        SourceType,
    )

    inp = make_inputs()
    src = Source(
        source_id="S-001",
        url="https://example.org/a",
        title="Example",
        source_type=next(iter(SourceType)),
        retrieved_at=datetime(2026, 1, 1, tzinfo=UTC),
        content_sha256="0" * 64,
        excerpt="e",
        reliability=next(iter(Reliability)),
        reliability_basis="b",
    )
    inp = inp.__class__(**{**inp.__dict__, "research": ResearchReport(sources=[src])})
    _, res = render(inp)
    text = "\n".join(pages_text(res.data))
    assert "S-001" in text and "example.org" in text


def test_not_applicable_documents_are_marked_in_pdf():
    inp = make_inputs(ux={"has_ui": False, "interface_note": "API only service"})
    _, res = render(inp)
    text = "\n".join(pages_text(res.data))
    assert "Not applicable" in text and "API only service" in text


def test_readme_index_is_not_repeated_inside_the_pdf():
    _, res = render()
    text = "\n".join(pages_text(res.data))
    assert "README.md" not in text  # the index is replaced by the table of contents
    assert "REQUIREMENTS_AUDIT.md" in text and "not yet run" in text  # pending docs are disclosed
