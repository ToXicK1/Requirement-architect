# Current State
- **Phase:** 8 (audit engine) implemented and tested; next Phase 9 (application interface).
- **Completed:** P1-01..05, P2-01..06, P3-01..07, P4-01..07, P5-01..06, P6-01..06, P7-01..09, P8-01..07 (TESTED).
- **Workflow today:** understand -> clarify -> (pause for answers) -> finish -> research -> requirements -> architecture -> technology -> data_api -> security -> ux -> qa_deploy -> `specifications_complete` (research onward only when a ResearchService is supplied; otherwise ends `ready_for_research`).
- **Known issues / unverified:**
  - `AuditService.run(project_id)` audits the latest specs (deterministic checks + independent LLM review), regenerates auto-fixable design stages within round / stage-run / no-progress limits, saves a versioned report and sets `audit_complete`. Never touches requirements. Verdict is `not_ready` or `ready_for_review`, never approved. Service only: no endpoint/CLI/graph node yet. The remediation and review prompts have never run on a real model.
  - `DocumentationService.generate(project_id)` produces `PROJECT_DOCUMENTATION/` (Markdown tree, PDF, manifest.json, openapi.json, traceability.csv, diagrams/*.mmd) plus a ZIP under `OUTPUT_DIR/<project>/vN/`. It is a service only: no endpoint/CLI yet (Phase 9). Audit documents appear only when a current audit exists; otherwise they are declared pending. PDF diagrams are Mermaid source, not images (ADR-035).
  - Stages 5-10 never run on a real model; Mermaid output not parsed by real Mermaid; OpenAPI only structurally validated; secret scrubber is a heuristic; security output is analysis input, not an audit.
  - Approval candidates are collected but there is no approval flow yet (Phase 9). Task trace links do not exist yet.
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
- **Last verified results:** pytest 506 passed; ruff + format clean; mypy strict clean (89 files); no migration change.
- **External deps needed:** LLM key (live runs); optional Brave key (web search); optional GitHub token; PostgreSQL/Docker host.
- **Next actions:** Phase 9: FastAPI endpoints (projects, start/resume/retry, answers, stage outputs, audit, documents + downloads), authentication/authorization with per-owner project access, the hybrid human-approval mechanism (approve/reject approval candidates and NFR targets via `approve_nfr_targets`, versioned and audited), CLI, and a minimal web UI. Orchestrate analyze -> audit -> documents behind the API.