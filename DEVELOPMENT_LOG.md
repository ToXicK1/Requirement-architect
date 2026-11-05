# Development Log
## Session 1 - Phase 1 foundation
- Environment: Python 3.12.3, git 2.43. NO Docker, NO PostgreSQL in sandbox.
- Built: config (startup validation), structlog + redaction, async DB layer, health endpoints, Alembic async wiring, Dockerfile, compose.
- Failures hit & fixed: sh vs bash brace expansion (files not created, recreated); missing greenlet (sqlalchemy[asyncio]); mypy type on log processor; alembic.ini script_location; ruff SIM117.
- Tests: 9 passed (5 config, 1 logging, 3 health). ruff clean, mypy strict clean.
- Remaining: Docker build and PostgreSQL run unverified; no ORM models/migrations yet (Phase 3).

## Session 2 - Phase 2 LLM infrastructure
- Built llm package (types, provider protocol, 2 adapters, gateway, pricing, usage, factory) + config validation.
- Tests: 48 passed total (39 new). ruff + mypy strict clean.
- Failure: one test expected specific timeout type after exhaustion; gateway intentionally raises aggregate error; test corrected (behavior unchanged).
- Not verified: live API calls; prompt version *files* (loader comes with agent stages in P3); usage persistence.

## Session 3 - Phase 3 core agent
- Built: state schemas, ORM + first migration, repository, usage persistence sink, prompt loader + 2 prompts, stages 1-2, LangGraph workflow, WorkflowService.
- Bugs found by tooling/tests: migration was empty (models not imported in env.py) -> fixed + `alembic check` test; mypy caught wrong argument order in service.start(); prompt files missing from wheel risk -> package-data + verified wheel contents.
- Mutation check (5 mutants): 3 killed immediately; 1 revealed a real test gap (supersede status unasserted -> added); 1 revealed dead code (redundant skip-guard -> removed).
- Tests: 75 passed. ruff + mypy strict clean.
- NOT verified: real-LLM behaviour of prompts; PostgreSQL (DB + checkpointer); concurrent multi-process access (lock is per-process).

## Session 4 - Phase 4 research
- Built: url_safety, fetcher, extract, evidence, providers (5 adapters), research service, factory, 2 prompts, workflow research node, config.
- Real bugs found by tests/tools (all fixed): `head` in skip-list swallowed <title>; `$` regex accepted 'pkg\n' (-> fullmatch); npm scoped URL built with replace() hit 'https://' slash; Brave adapter crashed on `"web": []`; min quote length 12 too weak -> 25 (and prompt now asks for full-clause quotes).
- Test-design errors fixed (not product bugs): exact-dict call assertion, provider-limit truncation, 1-char query violating schema, vacuous assertions removed.
- Mutation testing: SSRF/fetcher 10/11 killed (1 equivalent: IPv4-mapped unwrap redundant on py3.12 -> kept as defence in depth); Stage 3 logic 16/16 killed.
- Tests: 287 passed. ruff + mypy strict clean. pip-audit: only sandbox pip flagged.
- NOT verified: any live network call (search, registries, OSV, GitHub); Brave response schema vs live API; real-model prompt quality; production egress controls; PG.

## Session 5 - Phase 5 requirements engineering
- Found on resume: the sandbox had been reset (no repo); restored from the phase4 tarball and RE-VERIFIED before building (287 tests, ruff, mypy all green). Found a stale `build/` copy of the source committed to git -> removed and gitignored.
- Built: requirements schemas, build_spec reconciler, approve_nfr_targets, traceability module + CSV export, versioned prompt, generate_requirements, workflow node.
- Existing tests changed deliberately: research workflow tests now end at `requirements_complete` (was `research_complete`); test Script gained a `requirements` route.
- Tests: 315 passed (28 new). ruff + mypy strict clean. No schema change (alembic untouched).
- Mutation testing: 11/11 killed (finding filter, assumption flagging, cycle detection, NFR status, CSV guard, dangling links, approve validation, dependency metadata, prompt delimiting, orphan stories, uncited-fact flag).
- NOT verified: any real-model output (prompt quality, whether models obey the key/objective/citation rules); NFR category completeness in practice; Postgres; live network.
- Observation (not acted on): a network probe showed pypi.org and registry.npmjs.org reachable (HTTP 200), api.github.com returned 403, example.com DNS failed. A live smoke test of the PyPI/npm adapters may be possible; not attempted this session.

## Session 6 - Phase 6 technical specifications (stages 5-10)
- Built: architecture, technology, DB/API, security, UX, QA/deploy stages (schemas, prompts, builders, generators), Mermaid and OpenAPI generators, secret scrubber, full-chain traceability, table-driven workflow nodes, `specifications_complete` status.
- Existing tests changed deliberately: final status in research/requirements workflow tests is now `specifications_complete`; test Script gained routes and minimal valid defaults for the six new stages.
- Pushed to GitHub (ToXicK1/Requirement-architect, main) after the user installed the Claude GitHub App.
- Tests: 406 passed. ruff, ruff format, mypy strict (63 files) clean. Migration test (`alembic check`) is part of the suite; no schema change.
- Mutation testing: step 1 10/10, step 2 8/8 (+ Mermaid sanitizer mutant), step 4 10/10 killed after two surviving mutants (latest-version dependency, empty redaction marker) exposed weak tests that were then strengthened.
- NOT verified: any real-model output for stages 5-10; Mermaid rendering in a real parser; OpenAPI against a full validator; Postgres; Docker; live network. A standalone `alembic check` on a fresh DB reported "not up to date" until upgraded (expected; the test upgrades first).

## Session 7 - Phase 7 documentation generation
- Built: `generators/docs/*` (md helpers, 11 renderers, task planner, package assembler, bundle/manifest/ZIP, ReportLab PDF), `agent/documentation.py` service, `StageId.DOCUMENTATION`, status `documents_complete`, `output_dir` setting, reportlab dependency (pypdf dev-only).
- No schema change (stage ids are strings); alembic untouched.
- Tests: 466 passed. ruff, ruff format, mypy strict (81 files) clean.
- Mutation testing: 18 mutants; 3 survived first (duplicate-path guard, README skip in PDF, needs-confirmation list) and exposed weak tests -> tests added -> all killed; 2 equivalent survivors (redundant `..` check behind the path regex; ZIP epoch literal equal to the constant).
- Visual check: rendered cover, TOC and body pages to PNG and inspected them.
- NOT verified: a real coding agent consuming CODING_AGENT_INSTRUCTIONS; PDF in other viewers; non-Latin text beyond the font's coverage (unsupported characters become '?' and are reported); Mermaid correctness in a real parser; large projects (hundreds of requirements) for PDF time/size; Docker image has the fonts it needs (Vera ships with ReportLab, DejaVu used if present).
