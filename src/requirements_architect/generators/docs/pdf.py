"""Consolidated PDF built with ReportLab from the generated Markdown (our own restricted
output: headings, tables, bullet/numbered lists, fenced code, bold and inline code)."""

from __future__ import annotations

import html
import io
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    BaseDocTemplate,
    Flowable,
    Frame,
    PageBreak,
    PageTemplate,
    Paragraph,
    Preformatted,
    Spacer,
    Table,
    TableStyle,
)
from reportlab.platypus.tableofcontents import TableOfContents

from requirements_architect.generators.docs.model import Doc, DocInputs

_FOLDER_TITLES = {
    "00": "Project Overview",
    "01": "Business Requirements",
    "02": "Software Requirements",
    "03": "Architecture",
    "04": "Technical Specifications",
    "05": "Security",
    "06": "UI / UX",
    "07": "Quality Assurance",
    "08": "Infrastructure",
    "09": "Implementation",
    "10": "Validation",
}
_DEJAVU = Path("/usr/share/fonts/truetype/dejavu")
_ACCENT = colors.HexColor("#1f3a5f")
_RULE = colors.HexColor("#c9d1dc")
_HEAD_BG = colors.HexColor("#e8edf3")


@dataclass
class PdfResult:
    data: bytes
    warnings: list[str] = field(default_factory=list)
    pages: int = 0


def _register_fonts() -> tuple[str, str, str, Any]:
    """Return (regular, bold, italic, font object for glyph checks)."""
    import reportlab

    vera = Path(reportlab.__file__).parent / "fonts"
    candidates = [
        (
            "RA-Sans",
            _DEJAVU / "DejaVuSans.ttf",
            _DEJAVU / "DejaVuSans-Bold.ttf",
            _DEJAVU / "DejaVuSans-Oblique.ttf",
        ),
        ("RA-Sans", vera / "Vera.ttf", vera / "VeraBd.ttf", vera / "VeraIt.ttf"),
    ]
    for name, reg, bold, ital in candidates:
        if reg.exists() and bold.exists() and ital.exists():
            if name not in pdfmetrics.getRegisteredFontNames():
                pdfmetrics.registerFont(TTFont(name, str(reg)))
                pdfmetrics.registerFont(TTFont(f"{name}-Bold", str(bold)))
                pdfmetrics.registerFont(TTFont(f"{name}-Italic", str(ital)))
                pdfmetrics.registerFontFamily(
                    name,
                    normal=name,
                    bold=f"{name}-Bold",
                    italic=f"{name}-Italic",
                    boldItalic=f"{name}-Bold",
                )
            return name, f"{name}-Bold", f"{name}-Italic", pdfmetrics.getFont(name)
    return "Helvetica", "Helvetica-Bold", "Helvetica-Oblique", pdfmetrics.getFont("Helvetica")


class _Ctx:
    def __init__(self) -> None:
        self.reg, self.bold, self.ital, self.font = _register_fonts()
        self.missing: set[str] = set()
        base = getSampleStyleSheet()
        self.body = ParagraphStyle(
            "body",
            parent=base["BodyText"],
            fontName=self.reg,
            fontSize=9.5,
            leading=13,
            alignment=TA_LEFT,
            spaceAfter=4,
        )
        self.cell = ParagraphStyle(
            "cell", parent=self.body, fontSize=7.5, leading=9.5, spaceAfter=0, wordWrap="CJK"
        )
        self.cellh = ParagraphStyle("cellh", parent=self.cell, fontName=self.bold)
        self.bullet = ParagraphStyle(
            "bullet", parent=self.body, leftIndent=14, bulletIndent=4, spaceAfter=2
        )
        self.code = ParagraphStyle(
            "code", parent=self.body, fontName="Courier", fontSize=7.5, leading=9
        )
        self.h = {
            0: ParagraphStyle(
                "h0",
                parent=self.body,
                fontName=self.bold,
                fontSize=20,
                leading=24,
                textColor=_ACCENT,
                spaceBefore=0,
                spaceAfter=10,
            ),
            1: ParagraphStyle(
                "h1",
                parent=self.body,
                fontName=self.bold,
                fontSize=15,
                leading=19,
                textColor=_ACCENT,
                spaceBefore=12,
                spaceAfter=6,
            ),
            2: ParagraphStyle(
                "h2",
                parent=self.body,
                fontName=self.bold,
                fontSize=12,
                leading=15,
                textColor=_ACCENT,
                spaceBefore=10,
                spaceAfter=4,
            ),
            3: ParagraphStyle(
                "h3",
                parent=self.body,
                fontName=self.bold,
                fontSize=10.5,
                leading=13,
                spaceBefore=8,
                spaceAfter=3,
            ),
            4: ParagraphStyle(
                "h4",
                parent=self.body,
                fontName=self.bold,
                fontSize=9.5,
                leading=12,
                spaceBefore=6,
                spaceAfter=2,
            ),
        }

    def clean(self, s: str) -> str:
        """Replace characters the font cannot draw so output is never silently garbled."""
        out = []
        cmap = getattr(getattr(self.font, "face", None), "charToGlyph", None)
        for ch in s:
            if cmap is not None and ord(ch) > 31 and ord(ch) not in cmap:
                self.missing.add(ch)
                out.append("?")
            elif ord(ch) < 32 and ch not in "\n\t":
                out.append(" ")
            else:
                out.append(ch)
        return "".join(out)

    def inline(self, s: str) -> str:
        """Markdown inline -> ReportLab markup. Everything is XML-escaped first."""
        s = self.clean(html.unescape(s))
        s = re.sub(r"\\([\\`*_{}\[\]()#+\-.!|<>])", lambda m: m.group(1), s)
        s = html.escape(s, quote=False)
        s = re.sub(r"`([^`]+)`", r'<font name="Courier">\1</font>', s)
        s = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", s)
        return s


def _split_row(line: str) -> list[str]:
    cells, cur, esc = [], "", False
    for ch in line.strip().strip("|"):
        if esc:
            cur += "|" if ch == "|" else "\\" + ch
            esc = False
        elif ch == "\\":
            esc = True
        elif ch == "|":
            cells.append(cur.strip())
            cur = ""
        else:
            cur += ch
    cells.append(cur.strip())
    return cells


class _Doc(BaseDocTemplate):
    def __init__(self, buf: io.BytesIO, meta: DocInputs, ctx: _Ctx) -> None:
        super().__init__(
            buf,
            pagesize=A4,
            leftMargin=20 * mm,
            rightMargin=20 * mm,
            topMargin=22 * mm,
            bottomMargin=20 * mm,
            title=meta.project_name,
            author="Requirements Architect",
        )
        self.meta, self.ctx = meta, ctx
        frame = Frame(self.leftMargin, self.bottomMargin, self.width, self.height, id="f")
        self.addPageTemplates(
            [
                PageTemplate(id="cover", frames=[frame], onPage=self._cover),
                PageTemplate(id="body", frames=[frame], onPage=self._page),
            ]
        )

    def _cover(self, canvas: Any, doc: Any) -> None:
        canvas.saveState()
        canvas.setFillColor(_ACCENT)
        canvas.rect(0, A4[1] - 60 * mm, A4[0], 60 * mm, stroke=0, fill=1)
        canvas.restoreState()

    def _page(self, canvas: Any, doc: Any) -> None:
        canvas.saveState()
        canvas.setFont(self.ctx.reg, 8)
        canvas.setFillColor(colors.grey)
        canvas.drawString(
            self.leftMargin,
            12 * mm,
            self.ctx.clean(f"{self.meta.project_name[:60]} - v{self.meta.package_version} - DRAFT"),
        )
        canvas.drawRightString(A4[0] - self.rightMargin, 12 * mm, f"Page {doc.page}")
        canvas.setStrokeColor(_RULE)
        canvas.line(self.leftMargin, 15 * mm, A4[0] - self.rightMargin, 15 * mm)
        canvas.restoreState()

    def afterFlowable(self, flowable: Flowable) -> None:
        level = getattr(flowable, "_toc_level", None)
        if level is not None:
            text = flowable.getPlainText()
            self.notify("TOCEntry", (level, text, self.page))


def _heading(ctx: _Ctx, text: str, level: int, toc: bool = False) -> Paragraph:
    p = Paragraph(ctx.inline(text), ctx.h[min(level, 4)])
    if toc:
        p._toc_level = level - 1
    return p


def _table(ctx: _Ctx, rows: list[list[str]], width: float) -> Table:
    n = max(len(r) for r in rows)
    rows = [r + [""] * (n - len(r)) for r in rows]
    lens = [max(6, min(40, max(len(r[c]) for r in rows[:30]))) for c in range(n)]
    total = sum(lens)
    widths = [width * x / total for x in lens]
    data = [
        [Paragraph(ctx.inline(c), ctx.cellh if ri == 0 else ctx.cell) for c in r]
        for ri, r in enumerate(rows)
    ]
    t = Table(data, colWidths=widths, repeatRows=1)
    t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), _HEAD_BG),
                ("GRID", (0, 0), (-1, -1), 0.4, _RULE),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 3),
                ("RIGHTPADDING", (0, 0), (-1, -1), 3),
                ("TOPPADDING", (0, 0), (-1, -1), 2),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ]
        )
    )
    return t


def markdown_to_flowables(ctx: _Ctx, md_text: str, width: float, shift: int) -> list[Flowable]:
    out: list[Flowable] = []
    lines = md_text.splitlines()
    i = 0
    para: list[str] = []

    def flush() -> None:
        if para:
            out.append(Paragraph(ctx.inline(" ".join(para)), ctx.body))
            para.clear()

    while i < len(lines):
        line = lines[i]
        fence = re.match(r"^(`{3,})(\w*)\s*$", line)
        if fence:
            flush()
            ticks, lang = fence.group(1), fence.group(2)
            body: list[str] = []
            i += 1
            while i < len(lines) and lines[i].strip() != ticks:
                body.append(lines[i])
                i += 1
            if lang == "mermaid":
                out.append(
                    Paragraph(
                        "Diagram source (Mermaid) - render with any Mermaid tool; the source is also provided in diagrams/.",
                        ctx.cell,
                    )
                )
            out.append(
                Preformatted(
                    ctx.clean("\n".join(body)), ctx.code, maxLineLength=110, newLineChars=""
                )
            )
            out.append(Spacer(1, 4))
        elif h := re.match(r"^(#{1,6})\s+(.*)$", line):
            flush()
            out.append(_heading(ctx, h.group(2), len(h.group(1)) + shift))
        elif line.startswith("|") and i + 1 < len(lines) and re.match(r"^\|\s*-{3}", lines[i + 1]):
            flush()
            rows = [_split_row(line)]
            i += 2
            while i < len(lines) and lines[i].startswith("|"):
                rows.append(_split_row(lines[i]))
                i += 1
            out.append(_table(ctx, rows, width))
            out.append(Spacer(1, 6))
            continue
        elif b := re.match(r"^- (.*)$", line):
            flush()
            out.append(Paragraph(ctx.inline(b.group(1)), ctx.bullet, bulletText="•"))
        elif n := re.match(r"^(\d+)\. (.*)$", line):
            flush()
            out.append(Paragraph(ctx.inline(n.group(2)), ctx.bullet, bulletText=f"{n.group(1)}."))
        elif line.startswith(">"):
            flush()
            para.append(line.lstrip("> "))
        elif not line.strip():
            flush()
        else:
            para.append(line.strip())
        i += 1
    flush()
    return out


def _strip_header(body: str) -> str:
    """Drop the per-document title and metadata table (shown once in Document control)."""
    lines = body.splitlines()
    i = 0
    if lines and lines[0].startswith("# "):
        i = 1
        while i < len(lines) and not lines[i].strip():
            i += 1
        while i < len(lines) and lines[i].startswith("|"):
            i += 1
    return "\n".join(lines[i:])


def render_pdf(docs: list[Doc], inp: DocInputs, pending: dict[str, str] | None = None) -> PdfResult:
    ctx = _Ctx()
    buf = io.BytesIO()
    doc = _Doc(buf, inp, ctx)
    w = doc.width
    story: list[Flowable] = []

    # Cover page
    story += [Spacer(1, 62 * mm)]
    cover = ParagraphStyle("cover", parent=ctx.h[0], fontSize=26, leading=31)
    story += [
        Paragraph(ctx.inline(inp.project_name), cover),
        Paragraph("Requirements and Technical Documentation Package", ctx.h[2]),
        Spacer(1, 14 * mm),
    ]
    story.append(
        _table(
            ctx,
            [
                ["Field", "Value"],
                ["Project ID", inp.project_id],
                ["Package version", str(inp.package_version)],
                ["Generated", inp.generated_at.strftime("%Y-%m-%d %H:%M UTC")],
                ["Approval status", inp.approval_status],
            ],
            w * 0.9,
        )
    )
    story += [
        Spacer(1, 10 * mm),
        Paragraph(
            "This is a generated draft. It has not been approved by a human. Items marked proposed, assumption or unverified have not been confirmed.",
            ctx.body,
        ),
    ]
    from reportlab.platypus import NextPageTemplate

    story += [NextPageTemplate("body"), PageBreak()]

    toc = TableOfContents()
    toc.levelStyles = [
        ParagraphStyle("t0", parent=ctx.body, fontName=ctx.bold, leftIndent=0, spaceBefore=5),
        ParagraphStyle("t1", parent=ctx.body, leftIndent=12),
    ]
    story += [Paragraph("Table of contents", ctx.h[0]), toc, PageBreak()]

    story += [_heading(ctx, "Document control", 1, toc=True)]
    story.append(
        _table(
            ctx,
            [
                ["Item", "Value"],
                ["Project", inp.project_name],
                ["Project ID", inp.project_id],
                ["Package version", str(inp.package_version)],
                ["Approval status", inp.approval_status],
                *[[f"Source: {k}", f"version {v}"] for k, v in sorted(inp.source_versions.items())],
            ],
            w,
        )
    )

    if pending:
        story += [Spacer(1, 6), Paragraph("Documents not yet generated", ctx.h[3])]
        story.append(_table(ctx, [["Path", "Reason"], *[[k, v] for k, v in pending.items()]], w))

    current = ""
    for d in docs:
        if d.path == "README.md":
            continue
        folder = d.path.split("/")[0]
        if folder != current:
            current = folder
            story += [
                PageBreak(),
                _heading(
                    ctx, f"{folder[:2]}  {_FOLDER_TITLES.get(folder[:2], folder)}", 1, toc=True
                ),
            ]
        story.append(_heading(ctx, d.title, 2, toc=True))
        if not d.applicable:
            story.append(Paragraph("Not applicable", ctx.h[4]))
        story += markdown_to_flowables(ctx, _strip_header(d.body), w, shift=1)

    story += [PageBreak(), _heading(ctx, "References", 1, toc=True)]
    if inp.research and inp.research.sources:
        rows = [["ID", "Title", "URL", "Retrieved", "Reliability"]] + [
            [
                s.source_id,
                s.title or "-",
                s.url,
                s.retrieved_at.strftime("%Y-%m-%d"),
                s.reliability.value,
            ]
            for s in inp.research.sources
        ]
        story.append(_table(ctx, rows, w))
        story.append(
            Paragraph(
                "Sources are untrusted external content. Reliability is a heuristic.", ctx.body
            )
        )
    else:
        story.append(Paragraph("No external sources were retrieved for this package.", ctx.body))

    doc.multiBuild(story)
    warnings = []
    if ctx.missing:
        warnings.append(
            f"{len(ctx.missing)} distinct character(s) not supported by the PDF font were replaced with '?'"
        )
    if ctx.reg == "Helvetica":
        warnings.append("embedded Unicode font not found; non-Latin text will not render")
    return PdfResult(buf.getvalue(), warnings, doc.page)
