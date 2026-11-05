# Current State
- **Phase:** 9 (application interface) implemented and tested; next Phase 10 (production hardening).
- **Completed:** P1-01..05, P2-01..06, P3-01..07, P4-01..07, P5-01..06, P6-01..06, P7-01..09, P8-01..07, P9-01..08, P9-10 (TESTED); P9-09 UI (IMPLEMENTED, not browser-tested).
- **Workflow today:** understand -> clarify -> (pause for answers) -> finish -> research -> requirements -> architecture -> technology -> data_api -> security -> ux -> qa_deploy -> `specifications_complete` (research onward only when a ResearchService is supplied; otherwise ends `ready_for_research`).
- **Known issues / unverified:**
  - `AuditService.run(project_id)` audits the latest specs (deterministic checks + independent LLM review), regenerates auto-fixable design stages within round / stage-run / no-progress limits, saves a versioned report and sets `audit_complete`. Never touches requirements. Verdict is `not_ready` or `ready_for_review`, never approved. Reachable through the API (`POST/GET /api/v1/projects/{id}/audit`, background job); not a graph node. The remediation and review prompts have never run on a real model.
  - `DocumentationService.generate(project_id)` produces `PROJECT_DOCUMENTATION/` (Markdown tree, PDF, manifest.json, openapi.json, traceability.csv, diagrams/*.mmd) plus a ZIP under `OUTPUT_DIR/<project>/vN/`. Reachable through the API (`POST /documents`, then `GET /documents`, `/documents/files/...`, `/documents/download.zip`). Audit documents appear only when a current audit exists; otherwise they are declared pending. PDF diagrams are Mermaid source, not images (ADR-035).
  - Stages 5-10 never run on a real model; Mermaid output not parsed by real Mermaid; OpenAPI only structurally validated; secret scrubber is a heuristic; security output is analysis input, not an audit.
  - Approvals: `ApprovalService` lists spec approval candidates + proposed NFR targets, records append-only fingerprinted decisions (approve / reject / request revision), and the documents show each state. Approving never approves the package as a whole. Revisions regenerate the stage chain; unverified on a real model. Human-owned audit findings have no approval flow yet (P8-08).
  - Requirements stage never run on a real model. Whether models respect the key/objective/citation rules is unknown; build_spec reports violations as issues rather than failing. NFR category gaps and uncited external facts are reported, not auto-remediated (Phase 8).
  - Traceability currently links only objectives and stories; component/entity/endpoint/control/test/task links arrive with Phase 6+. `analyze()` must be called with the extended `required` kinds then.
  - A sandbox reset happened between sessions: always restore from the latest tarball and re-verify.
  - No live network call has ever been made: Brave/GitHub/PyPI/npm/OSV adapters follow public API docs but are tested on mocked HTTP only. Brave's response shape in particular is unconfirmed against the live service.
  - Prompts never run against a real model; research quality is unknown until a key is supplied.
  - 'verified' = quote present in source; it does not prove the claim follows (ADR-015).
  - Reliability list is a small heuristic (ADR-016).
  - SSRF defence is application-level only; production must add network egress restrictions (Phase 10).
  - Docker/compose never built. PostgreSQL unavailable: DB, migrations, checkpointer verified on SQLite only.
  - API + auth exist (scrypt, opaque session tokens, owner-only access, 404 for others). Jobs, rate limits and workflow/approval locks are IN-PROCESS: single worker/instance only (ADR-042/044). Checkpointer is SQLite even with Postgres data (ADR-048). Projects created before Phase 9 have no owner and are not reachable. Registration is off by default; create users with `python -m requirements_architect create-user NAME --password-stdin`. UI is static JS, never opened in a real browser here.
  - Dependency scan done once manually, not in CI.
- **Resume:**
  ```
  cd requirements-architect && python3 -m venv .venv && . .venv/bin/activate
  pip install -e ".[dev]" && pytest -q && ruff check . && mypy src
  ```
- **Last verified results:** pytest 577 passed; ruff + format clean; mypy strict clean (101 files); `alembic check` clean (migration 30bd38d42546).
- **External deps needed:** LLM key (live runs); optional Brave key (web search); optional GitHub token; PostgreSQL/Docker host.
- **Next actions:** Phase 10: verify on PostgreSQL and Docker, dependency/security scan in CI, shared rate-limit store and job queue or a documented single-instance constraint, Postgres checkpointer decision, TLS/proxy guidance (client IP), backup/recovery and residual-risk docs, 20+ benchmark problems, optional Mermaid rendering in the PDF, separate review-gateway configuration, browser/accessibility testing of the UI, a human-owned-finding approval flow.
