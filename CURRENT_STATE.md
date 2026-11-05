# Current State
- **Phase:** 5 (requirements engineering) implemented and tested; next Phase 6 (technical specifications).
- **Completed:** P1-01..05, P2-01..06, P3-01..07, P4-01..07, P5-01..06 (TESTED).
- **Workflow today:** understand -> clarify -> (pause for answers) -> finish -> research -> requirements -> `requirements_complete` (research and requirements nodes only when a ResearchService is supplied; otherwise ends `ready_for_research`).
- **Known issues / unverified:**
  - Requirements stage never run on a real model. Whether models respect the key/objective/citation rules is unknown; build_spec reports violations as issues rather than failing. NFR category gaps and uncited external facts are reported, not auto-remediated (Phase 8).
  - Traceability currently links only objectives and stories; component/entity/endpoint/control/test/task links arrive with Phase 6+. `analyze()` must be called with the extended `required` kinds then.
  - A sandbox reset happened between sessions: always restore from the latest tarball and re-verify.
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
- **Last verified results:** pytest 315 passed; ruff + format clean; mypy strict clean (44 files); no migration change this phase.
- **External deps needed:** LLM key (live runs); optional Brave key (web search); optional GitHub token; PostgreSQL/Docker host.
- **Next actions:** Phase 6: stages 5-10 as Pydantic models + prompts + nodes, each consuming the persisted RequirementsSpec and research report. Start with architecture (components with ids, decisions with rationale/alternatives/trade-offs, Mermaid diagrams validated deterministically), then technology (versions only from research/registry facts, never from memory), DB/API (entities and endpoints with ids), security, UX, QA/deploy (test cases mapped to requirement ids). Each stage must emit trace links so `analyze()` can flag requirements without design/test coverage and orphan components/endpoints/tests. Consider a live smoke test of the PyPI/npm adapters first, since those hosts appeared reachable.