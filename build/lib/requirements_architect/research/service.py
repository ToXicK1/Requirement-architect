"""Stage 3: research and feasibility.

Pipeline: LLM plans queries -> providers search -> SafeFetcher retrieves -> text is sanitized ->
registries/advisories are read directly -> LLM synthesizes findings -> CODE verifies quotes.
Everything retrieved is untrusted data; failures are recorded as limitations, never hidden.
"""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from urllib.parse import urlsplit, urlunsplit

import structlog
from pydantic import BaseModel

from requirements_architect.agent.prompt_loader import load_prompt, wrap_untrusted
from requirements_architect.llm.gateway import LLMGateway
from requirements_architect.llm.types import LLMRequest, Message
from requirements_architect.research.evidence import classify_source, verify_findings
from requirements_architect.research.extract import extract_document, sanitize_text
from requirements_architect.research.fetcher import FetchedDocument, FetchError, SafeFetcher
from requirements_architect.research.providers import (
    OSVAdvisories,
    PackageRegistry,
    ResearchProviderError,
    SearchHit,
    SearchProvider,
)
from requirements_architect.research.url_safety import UnsafeUrlError
from requirements_architect.schemas.research import (
    PackageFact,
    Reliability,
    ResearchPlan,
    ResearchReport,
    Source,
    SourceType,
    SynthesisOutput,
)
from requirements_architect.schemas.state import (
    ClarificationAnswer,
    Dependency,
    OutputMeta,
    ProjectBrief,
    StageId,
)
from requirements_architect.storage.repository import Repository

log = structlog.get_logger()

_RANK = {Reliability.HIGH: 0, Reliability.MEDIUM: 1, Reliability.LOW: 2}
VERIFICATION_DISCLAIMER = (
    "'verified' means the quoted passage appears verbatim in the cited retrieved source; it does not "
    "establish that the passage fully supports the claim. Review high-impact findings."
)


class ResearchLimits(BaseModel):
    max_queries: int = 6
    max_github_queries: int = 3
    results_per_query: int = 5
    max_fetches: int = 10
    fetch_concurrency: int = 4
    max_packages: int = 10
    excerpt_chars: int = 2000  # per source, both stored and shown to the model
    max_prompt_source_chars: int = 30_000


def _canon(url: str) -> str:
    p = urlsplit(url)
    return urlunsplit((p.scheme.lower(), p.netloc.lower(), p.path.rstrip("/") or "/", p.query, ""))


def _package_text(f: PackageFact) -> str:
    parts = [f"{f.name} ({f.ecosystem}) latest version {f.latest_version or 'unknown'}."]
    if f.license:
        parts.append(f"License: {f.license}.")
    if f.summary:
        parts.append(f"Summary: {f.summary}")
    if f.advisories_checked:
        ids = ", ".join(a.advisory_id for a in f.advisories) or "none"
        parts.append(f"Known advisories for this version (OSV): {ids}.")
    return " ".join(parts)


class ResearchService:
    def __init__(
        self,
        gateway: LLMGateway,
        repo: Repository,
        fetcher: SafeFetcher,
        search_providers: Sequence[SearchProvider] = (),
        registries: Mapping[str, PackageRegistry] | None = None,
        advisories: OSVAdvisories | None = None,
        limits: ResearchLimits | None = None,
    ) -> None:
        self._gateway, self._repo, self._fetcher = gateway, repo, fetcher
        self._providers = list(search_providers)
        self._registries = dict(registries or {})
        self._advisories = advisories
        self._limits = limits or ResearchLimits()

    # ---- helpers -----------------------------------------------------------------------------
    def _ctx(
        self, statement: str, brief: ProjectBrief, answers: Mapping[str, ClarificationAnswer]
    ) -> dict[str, str]:
        ans = "\n".join(f"{a.question_id}: {a.answer}" for a in answers.values()) or "(none)"
        return {
            "problem_statement": wrap_untrusted(statement, "problem_statement"),
            "brief_json": wrap_untrusted(brief.model_dump_json(indent=2), "brief"),
            "answers": wrap_untrusted(ans, "answers"),
        }

    async def _plan(self, project_id: str, ctx: dict[str, str]) -> ResearchPlan:
        prompt = load_prompt("research_plan")
        system, user = prompt.render(
            **ctx,
            max_queries=str(self._limits.max_queries),
            max_github_queries=str(self._limits.max_github_queries),
            max_packages=str(self._limits.max_packages),
        )
        req = LLMRequest(
            system=system,
            messages=[Message(role="user", content=user)],
            prompt_id=prompt.id,
            prompt_version=prompt.version,
            project_id=project_id,
        )
        plan, _ = await self._gateway.complete_structured(req, ResearchPlan)
        return plan

    async def _search(
        self, plan: ResearchPlan, limitations: list[str]
    ) -> tuple[list[SearchHit], list[str]]:
        jobs: list[tuple[SearchProvider, str]] = []
        for prov in self._providers:
            queries = plan.github_queries if prov.name == "github" else plan.queries
            cap = (
                self._limits.max_github_queries
                if prov.name == "github"
                else self._limits.max_queries
            )
            jobs += [(prov, q) for q in queries[:cap]]
        results = await asyncio.gather(
            *(p.search(q, self._limits.results_per_query) for p, q in jobs), return_exceptions=True
        )
        hits: list[SearchHit] = []
        run: list[str] = []
        for (prov, q), res in zip(jobs, results, strict=True):
            if isinstance(res, ResearchProviderError):
                limitations.append(f"search failed ({prov.name}): {res}")
            elif isinstance(res, BaseException):
                raise res  # programming error, not a provider failure
            else:
                hits += res
                run.append(f"{prov.name}: {q}")
        seen: set[str] = set()
        unique: list[SearchHit] = []
        for h in hits:
            key = _canon(h.url)
            if key not in seen:
                seen.add(key)
                unique.append(h)
        unique.sort(key=lambda h: _RANK[classify_source(h.url)[1]])  # stable: authoritative first
        return unique[: self._limits.max_fetches], run

    async def _retrieve(
        self, hits: Sequence[SearchHit], limitations: list[str]
    ) -> list[tuple[Source, str]]:
        sem = asyncio.Semaphore(self._limits.fetch_concurrency)

        async def one(hit: SearchHit) -> tuple[SearchHit, FetchedDocument | Exception]:
            async with sem:
                try:
                    return hit, await self._fetcher.fetch(hit.url)
                except (FetchError, UnsafeUrlError) as exc:
                    return hit, exc

        out: list[tuple[Source, str]] = []
        for hit, res in await asyncio.gather(*(one(h) for h in hits)):
            if isinstance(res, Exception):
                limitations.append(f"could not retrieve {hit.url}: {type(res).__name__}: {res}")
                continue
            doc = res
            ex = extract_document(doc.text, doc.content_type)
            if not ex.text:
                limitations.append(f"no extractable text at {hit.url}")
                continue
            stype, rel, basis = classify_source(doc.final_url)
            title, _ = sanitize_text(ex.title or hit.title, 200)
            source = Source(
                source_id=f"S-{len(out) + 1:03d}",
                url=doc.final_url,
                title=title.replace("\n", " "),
                source_type=stype,
                retrieved_at=doc.retrieved_at,
                content_sha256=doc.sha256,
                excerpt=ex.text[: self._limits.excerpt_chars],
                reliability=rel,
                reliability_basis=basis,
                injection_flags=ex.injection_flags,
            )
            out.append((source, ex.text))
        return out

    async def _packages(self, plan: ResearchPlan, limitations: list[str]) -> list[PackageFact]:
        facts: list[PackageFact] = []
        for ref in plan.packages[: self._limits.max_packages]:
            label = f"{ref.ecosystem}:{sanitize_text(ref.name, 80)[0]}"
            registry = self._registries.get(ref.ecosystem)
            if registry is None:
                limitations.append(f"no registry adapter for {ref.ecosystem}; {label} not checked")
                continue
            try:
                fact = await registry.lookup(ref.name)
            except ResearchProviderError as exc:
                limitations.append(f"package lookup failed for {label}: {exc}")
                continue
            if fact is None:
                limitations.append(
                    f"package not found in registry: {label} (possible hallucinated or misspelled name)"
                )
                continue
            if self._advisories is not None and fact.latest_version:
                try:
                    fact.advisories = await self._advisories.query(ref, fact.latest_version)
                    fact.advisories_checked = True
                except ResearchProviderError as exc:
                    limitations.append(f"advisory lookup failed for {label}: {exc}")
            facts.append(fact)
        return facts

    def _sources_block(self, sources: Sequence[Source]) -> str:
        if not sources:
            return "(no external sources were retrieved)"
        per = max(300, self._limits.max_prompt_source_chars // len(sources))
        blocks = []
        for s in sources:
            body = wrap_untrusted(s.excerpt[:per], "source")
            blocks.append(
                "<source>\n"
                f"id: {s.source_id}\ntype: {s.source_type.value}\nreliability: {s.reliability.value}\n"
                f"injection_suspected: {'yes' if s.injection_flags else 'no'}\n"
                f"url: {wrap_untrusted(s.url, 'source')}\ntitle: {wrap_untrusted(s.title, 'source')}\n"
                f"content:\n{body}\n</source>"
            )
        return "\n\n".join(blocks)

    # ---- entry point -------------------------------------------------------------------------
    async def run(
        self,
        project_id: str,
        problem_statement: str,
        brief: ProjectBrief,
        answers: Mapping[str, ClarificationAnswer],
        depends_on: Sequence[Dependency] = (),
    ) -> tuple[ResearchReport, OutputMeta]:
        limitations: list[str] = []
        ctx = self._ctx(problem_statement, brief, answers)
        configured = bool(self._providers or self._registries)
        if not configured:
            limitations.append(
                "no external research provider is configured; findings are unverified"
            )

        plan = await self._plan(project_id, ctx) if configured else ResearchPlan()
        hits, queries_run = await self._search(plan, limitations) if self._providers else ([], [])
        retrieved = await self._retrieve(hits, limitations)
        packages = await self._packages(plan, limitations)

        sources = [s for s, _ in retrieved]
        texts = {s.source_id: t for s, t in retrieved}
        for fact in packages:  # registry data is first-hand, so it becomes citable evidence
            sid = f"S-{len(sources) + 1:03d}"
            text = _package_text(fact)
            stype, rel, basis = classify_source(fact.registry_url)
            sources.append(
                Source(
                    source_id=sid,
                    url=fact.registry_url,
                    title=f"{fact.name} ({fact.ecosystem}) registry entry",
                    source_type=SourceType.PACKAGE_REGISTRY if stype is SourceType.WEB else stype,
                    retrieved_at=datetime.now(UTC),
                    content_sha256=hashlib.sha256(text.encode()).hexdigest(),
                    excerpt=text[: self._limits.excerpt_chars],
                    reliability=rel,
                    reliability_basis=basis,
                )
            )
            texts[sid] = text

        flagged = [s.source_id for s in sources if s.injection_flags]
        if flagged:
            limitations.append(
                f"possible prompt-injection text detected in {flagged}; treated as data only"
            )
        if configured and not sources:
            limitations.append("external research was configured but returned no usable sources")
        limitations.append(VERIFICATION_DISCLAIMER)

        prompt = load_prompt("research_synthesis")
        system, user = prompt.render(
            **ctx,
            sources=self._sources_block(sources),
            source_note=(
                "external sources were retrieved"
                if sources
                else "NO external sources were retrieved"
            ),
        )
        req = LLMRequest(
            system=system,
            messages=[Message(role="user", content=user)],
            prompt_id=prompt.id,
            prompt_version=prompt.version,
            project_id=project_id,
        )
        synthesis, _ = await self._gateway.complete_structured(req, SynthesisOutput)

        report = ResearchReport(
            sources=sources,
            findings=verify_findings(synthesis.findings, texts),
            packages=packages,
            feasibility_summary=synthesis.feasibility_summary,
            queries_run=queries_run,
            limitations=limitations,
            external_research_available=bool(sources),
        )
        meta = await self._repo.save_stage_output(project_id, StageId.RESEARCH, report, depends_on)
        log.info(
            "research_complete",
            project_id=project_id,
            sources=len(sources),
            findings=len(report.findings),
            limitations=len(limitations),
        )
        return report, meta
