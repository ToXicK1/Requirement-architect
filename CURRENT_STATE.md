# Current State
- **Phase:** 4 (research) implemented and tested; next Phase 5 (requirements engineering).
- **Completed:** P1-01..05, P2-01..06, P3-01..07, P4-01..07 (TESTED).
- **Workflow today:** understand -> clarify -> (pause for answers) -> finish -> research -> `research_complete` (research node only when a ResearchService is supplied; otherwise ends `ready_for_research`).
- **Known issues / unverified:**
  - No live network call has ever been made: Brave/GitHub/PyPI/npm/OSV adapters follow public API docs but are tested on mocked HTTP only. Brave's response shape in particular is unconfirmed against the live service.
  - Prompts never run against a real model; research quality is unknown until a key is supplied.
  - 'verified' = quote present in source; it does not prove the claim follows (ADR-015).
  - Reliability list is a small heuristic (ADR-016).
  - SSRF defence is application-level only; production must add network egress restrictions (Phase 10).
  - Docker/compose never built. PostgreSQL unavailable: DB, migrations, checkpointer verified on SQLite only.
  - WorkflowService lock is in-process. No HTTP endpoints for workflow, no auth yet (Phase 9).
  - Dependency scan done once manually, not in CI.
- **Resume:**
  ```
  cd requirements-architect && python3 -m venv .venv && . .venv/bin/activate
  pip install -e ".[dev]" && pytest -q && ruff check . && mypy src
  ```
- **Last verified results:** pytest 287 passed; ruff clean; mypy strict clean (41 files); alembic up/down/check OK (SQLite); pip-audit: only sandbox pip.
- **External deps needed:** LLM key (live runs); optional Brave key (web search); optional GitHub token; PostgreSQL/Docker host.
- **Next actions:** Phase 5: Pydantic models + stage for functional requirements (all spec fields) and non-functional requirements (proposed vs user-approved targets labelled separately), stable requirement IDs (FR-001/NFR-001), user stories, acceptance criteria, and a traceability model (requirement -> objective/story/component/entity/endpoint/control/test) with programmatic coverage + orphan detection. Requirements must cite research finding ids where they depend on external facts, and must not invent business rules (route unknowns to assumptions / approval requests).
