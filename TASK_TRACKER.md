# Task Tracker
Statuses: NOT_STARTED, IN_PROGRESS, BLOCKED, IMPLEMENTED, TESTED, VERIFIED

| ID | Task | Pri | Status | Deps | Notes / Test status |
|---|---|---|---|---|---|
| P1-01 | Repo structure + pyproject | H | TESTED | - | see CURRENT_STATE |
| P1-02 | Settings w/ startup validation | H | TESTED | P1-01 | 5 unit tests |
| P1-03 | Structured logging + redaction | H | TESTED | P1-01 | 1 unit test |
| P1-04 | Async DB layer | H | TESTED | P1-01 | via health tests (SQLite only) |
| P1-05 | Health endpoints | H | TESTED | P1-04 | 3 integration tests |
| P1-06 | Alembic async config | H | IN_PROGRESS | P1-04 | no migrations yet (no models) |
| P1-07 | Dockerfile + compose | M | IMPLEMENTED | P1-01 | NOT built: Docker unavailable in sandbox |
| P1-08 | PostgreSQL verification | H | BLOCKED | P1-04 | no PostgreSQL/Docker in sandbox |
| P2-01 | Provider interface + types/error taxonomy | H | TESTED | P1 | |
| P2-02 | Anthropic + OpenAI-compatible adapters | H | TESTED | P2-01 | httpx.MockTransport only; NOT run against live APIs (no key) |
| P2-03 | Gateway: timeout, bounded retry/backoff, rate limits, fallback, concurrency cap | H | TESTED | P2-01 | 12 unit tests incl. bounded-attempt checks |
| P2-04 | Structured output (JSON schema, fence strip, bounded re-ask) | H | TESTED | P2-03 | |
| P2-05 | Usage + cost tracking (operator price table, unknown = None) | H | TESTED | P2-03 | in-memory only; DB persistence in P3 |
| P2-06 | Config validation + factory | H | TESTED | P2-01 | prod requires LLM config |
| P2-07 | Live provider smoke test | H | BLOCKED | P2-02 | needs real LLM_API_KEY |
| P3-01 | Typed versioned state schemas (+ validators) | H | TESTED | P2 | |
| P3-02 | ORM models + initial Alembic migration | H | TESTED | P3-01 | up/down + `alembic check` on SQLite; PG unverified |
| P3-03 | Repository (append-only versions, answers, usage) | H | TESTED | P3-02 | |
| P3-04 | Versioned prompt files + strict loader + untrusted-text wrapping | H | TESTED | P3-01 | prompts never run against a real model |
| P3-05 | Stage 1 (understanding), Stage 2 (clarification) + id reconciliation | H | TESTED | P3-04 | scripted LLM only |
| P3-06 | LangGraph workflow: pause/resume, bounded rounds, retry | H | TESTED | P3-05 | restart durability verified on SQLite checkpointer |
| P3-07 | Workflow service (validation, per-project lock) | H | TESTED | P3-06 | lock is in-process only |
| P3-08 | Postgres checkpointer | H | BLOCKED | P3-06 | needs PostgreSQL to verify; not installed |
| P3-09 | Live end-to-end run with a real LLM | H | BLOCKED | P3-06,P2-07 | needs LLM key |
| P4-01 | URL validator (scheme/port/userinfo/numeric-host/internal-name/DNS-resolved IP checks) | H | TESTED | P3 | 82 tests; real-resolver test for loopback encodings; 4/4 key mutants killed |
| P4-02 | SafeFetcher (IP pinning+SNI, per-hop redirect revalidation, streaming decoded-size cap, wall-clock timeout, content-type allowlist, no cookies, per-host rate limit) | H | TESTED | P4-01 | 28 tests; 10/11 mutants killed (1 equivalent) |
| P4-03 | Safe extraction + sanitization + injection flagging | H | TESTED | P4-02 | hidden-text, invisible-char, malformed-HTML cases |
| P4-04 | Evidence model + deterministic verification + reliability heuristic | H | TESTED | P3 | model cannot self-verify; see ADR-015 for limits |
| P4-05 | Provider adapters (Brave, GitHub, PyPI, npm, OSV) | H | TESTED | P4-04 | mocked HTTP only; NOT run against live services |
| P4-06 | ResearchService (plan -> search -> fetch -> registries -> synthesize -> verify) | H | TESTED | P4-02..05 | scripted LLM; 16/16 mutants killed |
| P4-07 | Workflow integration (research node, retry) | H | TESTED | P4-06 | |
| P4-08 | Live research run (real search + real LLM) | H | BLOCKED | P4-06,P2-07 | needs LLM key (+ Brave key for web search) |
| P4-09 | Dependency vulnerability scan | M | PARTIAL | - | pip-audit run once: only sandbox `pip` flagged; not yet in CI |
| P5-01 | Requirements schemas (Raw* model layer vs final layer) | H | TESTED | P4 | model cannot supply ids, approval state or needs_confirmation |
| P5-02 | build_spec reconciler (ids, refs, cycles, assumptions, NFR targets) | H | TESTED | P5-01 | 11/11 mutants killed |
| P5-03 | approve_nfr_targets (proposed -> user_approved) | H | TESTED | P5-02 | function only; approval API/UI is Phase 9 |
| P5-04 | Traceability: links, coverage, orphans, dangling, CSV export (+formula-injection guard) | H | TESTED | P5-01 | only objective/story links exist so far |
| P5-05 | requirements prompt v1 + generate_requirements | H | TESTED | P5-02 | scripted LLM only; never run on a real model |
| P5-06 | Workflow node (research -> requirements), retry, deps recorded | H | TESTED | P5-05 | node exists only when a ResearchService is supplied |
| P5-07 | Live requirements run with a real LLM | H | BLOCKED | P5-06,P2-07 | needs LLM key |
| P5-08 | Remediation of NFR-category gaps / uncited facts | M | NOT_STARTED | P8 | issues are reported, not auto-fixed; audit engine owns remediation |
| P6-01 | Architecture stage (components, decisions, patterns, deterministic Mermaid context/component/dataflow diagrams) | H | TESTED | P5 | scripted LLM only; Mermaid text never rendered by a real Mermaid parser |
| P6-02 | Technology stage (registry-verified versions/licenses; no versions from memory) + DB/API stage (entities, endpoints, ER diagram, code-built OpenAPI 3.1) | H | TESTED | P6-01 | OpenAPI checked by a structural validator only, not full spec validation |
| P6-03 | Security stage (STRIDE + AI threats, code-computed risk, compliance-claim guard) + UX stage (personas, flows, screens, states) | H | TESTED | P6-02 | not a security review; disclaimer is fixed text |
| P6-04 | QA/deploy stage (test cases map to real requirement ids, strategy coverage, env vars name-only, secret scrubber) | H | TESTED | P6-03 | scrubber is regex heuristic |
| P6-05 | Full-chain traceability (component/entity/endpoint/control/test links) + approval-candidate collection | H | TESTED | P6-04 | task links arrive with Phase 7 |
| P6-06 | Workflow: research -> requirements -> 6 design nodes -> `specifications_complete` (table-driven nodes, deps recorded, retry resumes at failed stage) | H | TESTED | P6-05 | scripted LLM only |
| P6-07 | Live run of stages 5-10 with a real LLM | H | BLOCKED | P6-06,P2-07 | needs LLM key |
| P6-08 | Cross-stage consistency audit / remediation | M | NOT_STARTED | P8 | issues are reported, not auto-fixed |
