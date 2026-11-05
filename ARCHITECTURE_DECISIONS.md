# Architecture Decision Records
## ADR-001: Modular monolith, FastAPI + SQLAlchemy 2 async
Per master spec. Alternatives (microservices) rejected: unnecessary for v1.
## ADR-002: SQLite (aiosqlite) for tests, PostgreSQL (asyncpg) for production
Sandbox has no PostgreSQL. Production config validator rejects SQLite. PG behavior must be verified separately.
## ADR-003: structlog JSON logging with key-based secret redaction
Redaction is key-name based; free-text secrets in messages are not caught. Residual risk noted.

## ADR-004: Own thin gateway over raw HTTP (httpx) instead of vendor SDKs
Keeps provider-independence, one error taxonomy and full control of retries/timeouts; avoids pulling a vendor SDK into agent logic. Trade-off: we maintain two small adapters and must track API changes. Alternatives: LiteLLM, vendor SDKs.
## ADR-005: Separate `llm` package
Master spec lists package folders as examples of modularity; the gateway is a distinct cross-cutting concern, so it gets its own package rather than living in `core`.
## ADR-006: No built-in model names or prices
Models and prices change; the operator supplies LLM_MODEL and LLM_PRICE_TABLE_JSON. Unpriced calls are reported as unknown, not estimated.
## ADR-007: Fallback only on transient/rate-limit/timeout failures
Permanent errors (auth, bad request) fail fast so misconfiguration is not hidden by silently switching vendors.

## ADR-008: Stage outputs are append-only rows; latest draft is superseded, never overwritten
Satisfies "approved requirements are versioned, not silently overwritten". Unique (project, stage, version) guards concurrent writers. Alternative: JSON blob per project (rejected: no history, lost-update risk).
## ADR-009: Graph state holds plain dicts, not Pydantic objects
Keeps checkpoints serializer-agnostic and resumable across code changes; models are re-validated at node boundaries.
## ADR-010: Interrupt only in a side-effect-free `gate` node; resume payload validated in the service
LangGraph re-runs an interrupted node from its start on resume, so LLM calls must not share a node with interrupt(). Validating before invoking avoids poisoning the checkpoint with a bad resume value.
## ADR-011: LLM re-evaluation bounded by max_rounds; human input unbounded
Prevents endless clarification loops (spec: no uncontrolled loops) without capping legitimate user interaction.
## ADR-012: Model-reused question ids are renumbered rather than dropped (unless same text)
Losing a genuine blocking question is worse than asking one extra.

## ADR-013: SSRF defence = validate + resolve ourselves + connect to the vetted IP
Resolving once and connecting to that exact address (Host header + SNI preserved) closes the DNS-rebinding window between check and use. Every redirect hop is re-validated; any blocked address in a multi-record answer rejects the host. Alternatives: egress firewall only (necessary in production as defence in depth, but not verifiable here), hostname-only denylist (bypassable).
## ADR-014: Registry/search adapters call fixed API hosts through a separate client from the page fetcher
Only the fetcher handles arbitrary URLs, so only it needs SSRF machinery. LLM-supplied package names are strictly validated (fullmatch) before entering URL paths.
## ADR-015: "verified" = quoted text found verbatim in a cited, retrieved source (>=25 chars)
Deterministic and model-proof, but it proves the quote EXISTS, not that it entails the claim. Mitigations: recommendations/assumptions can never be verified; every report carries a disclaimer limitation; Stage 11 audit and human review remain responsible for semantic support. Alternative (LLM-judged entailment) rejected for Stage 3: the judge can be injected through the same sources.
## ADR-016: Source reliability is a hostname heuristic from a small curated list, not a content judgement
Look-alike hosts get no trust. Unlisted hosts are LOW. The list is deliberately short and must be reviewed/extended by maintainers.
## ADR-017: Injection handling = contain + flag, not drop
Retrieved text is delimited, tag-neutralized, invisible-char-stripped and flagged. Flagged sources are kept (security docs legitimately discuss injection). Output is schema-validated and quote-verified, so a successful injection cannot manufacture 'verified' facts. The regex flagger is a heuristic signal, not a boundary.
## ADR-018: Research evidence stored as a versioned stage output (no new tables)
Reuses append-only versioning; full page text is not persisted (hash + 2,000-char excerpt only) to limit storage and copyright exposure.

## ADR-019: Requirements ids, approval state and confirmation flags are assigned by code, never by the model
The model returns local keys (R1..) and may only *propose* NFR targets. `build_spec` assigns FR-/NFR-/US-/OBJ- ids, sets `target_status=proposed|none`, and sets `needs_confirmation`. `user_approved` can only come from `approve_nfr_targets`. Extra fields the model supplies (ids, approval) are ignored by the Raw schemas. Alternative: trust model ids (rejected: collisions, forged approval).
## ADR-020: Problems in model output become `SpecIssue`s; only unresolvable references are dropped
Unknown finding/objective/dependency/story references are removed (they cannot be honoured) and reported. Cycles, uncited external-fact dependencies and missing NFR categories are reported, not "fixed", because repairing them would change requirements. Remediation belongs to the Phase 8 audit engine, which is independent of generation (spec section 6, stage 11).
## ADR-021: Business rules the user did not state are `assumption`, hoisted into spec.assumptions
Honours "do not invent business requirements": inferred rules stay visible, de-duplicated, and flag the requirement `needs_confirmation`.
## ADR-022: Traceability is a pure function over (spec, links, known targets)
Later stages only append links and extend `required`; no schema change needed. CSV export neutralizes leading = + - @ because names are model/user text opened in spreadsheets.
## ADR-023: Requirements node exists only when research is configured
It consumes the persisted research report, so the graph is research -> requirements. Without a ResearchService the workflow still ends at `ready_for_research` (unchanged behaviour; existing tests kept).

## ADR-024: Design stages share one pattern: Raw* model output -> code builder -> versioned spec with SpecIssues
Same "model proposes, code decides" rule as Phase 5. The model returns local keys (C1, T1, E1, EP1, SC1, TH1, FL1, SCR1, TC1); code assigns C-/TECH-/E-/EP-/SC-/TH-/FL-/SCR-/TC- ids, drops references it cannot resolve and reports them as issues. Alternative: trust model ids (rejected: collisions, dangling refs).
## ADR-025: Diagrams and OpenAPI are rendered by code from validated structures
Mermaid text is built by deterministic functions with label sanitization (no model-authored Mermaid). OpenAPI 3.1 is built by code; only a structural validator exists, so we make no claim of full spec validity.
## ADR-026: Technology versions/licenses come only from registry evidence
Status is confirmed/differs/unverified/not_specified; a model-stated version is never presented as verified.
## ADR-027: Security risk and compliance wording are controlled by code
Risk level is computed from likelihood x impact; critical -> error issue, high/critical -> approval candidate. Compliance claims are regex-flagged and a fixed disclaimer is attached. The stage produces analysis input, not an audit or certification.
## ADR-028: Secrets never enter documents
`validation/secrets.scrub` redacts secret-looking text in test data, deployment text, CI steps and env-var purposes and records an error issue. `EnvVar` has no value field, so a value cannot be represented. The scrubber is a heuristic and can miss unusual formats.
## ADR-029: Design nodes are table-driven; the chain ends at `specifications_complete`
`DESIGN_STAGES` lists stage, model, generator and dependencies; each node loads context from persisted outputs (not graph state), records the latest upstream versions as dependencies, and only the last sets the status. Retry resumes at the failed node via the checkpointer; earlier stages are not re-run.

## ADR-030: Documents are rendered by code from persisted specs; the LLM writes no document text
Every document is a deterministic function of stage outputs, so documents cannot contradict the specs and every id in a document exists. Alternative (LLM-written prose): rejected for consistency and injection risk.
## ADR-031: All model/user text passes through `md.text/cell/inline/fence`
These collapse whitespace, neutralize HTML angle brackets and block-start syntax, escape table pipes and lengthen code fences, so a requirement cannot add headings, tables or HTML. The PDF escapes XML again before ReportLab markup.
## ADR-032: Audit documents are declared pending, never faked
REQUIREMENTS_AUDIT.md and FINAL_READINESS_REPORT.md need the Phase 8 audit engine. They are listed in README, manifest and PDF as not generated. The spec forbids empty placeholder documents.
## ADR-033: Package = in-memory file map -> manifest -> staged write -> verify -> atomic rename
`assemble` builds all bytes and a SHA-256 manifest; `write_files` rejects unsafe paths and symlink escapes; the service writes to a staging directory, re-reads and verifies files and the ZIP, and only then renames into `vN`. A failed verification leaves no output and consumes no version number.
## ADR-034: Implementation tasks are derived by code
`build_plan` creates tasks from components, entities, endpoints, controls, screens and test cases, orders them by phase then dependency (cycles reported and broken), and emits `task` trace links. The coding-agent handoff cites only these ids.
## ADR-035: PDF diagrams are Mermaid source, not rendered images (known gap)
A Mermaid renderer needs Chromium/mmdc in the runtime image. Until Phase 10 decides that, the PDF shows diagram source and the ZIP carries `diagrams/*.mmd`.

## ADR-036: The audit re-derives problems from the persisted specs instead of trusting stage builders
Builder issues are passed through (single place to look) but cross-references, traceability, duplicates, cycles, diagram coverage, security gaps, secrets and compliance wording are re-checked on the final stored specs. Duplicated codes are suppressed.
## ADR-037: LLM review is advisory and independent
It sees only rendered specs (never generator prompts/reasoning), cites ids that code verifies (findings citing only nonexistent ids are discarded; uncited 'major' is capped to minor; never blocker), cannot set fixability, and is never used to rewrite specs. A major LLM finding still counts toward the major-findings gate. A separate review gateway can be injected for a different model/provider. Same-model review shares blind spots.
## ADR-038: Remediation regenerates design stages only, and is bounded three ways
Auto-fixable findings belong to architecture..QA stages; requirements and brief issues are always human tasks, so approved requirements are never altered. Regeneration restarts at the earliest affected stage and redoes everything downstream (they consume earlier ids). Limits: remediation rounds, a total stage-run budget, and stop-if-no-improvement. Feedback reaches the model as an untrusted, delimited block appended to the stage prompt.
## ADR-039: The verdict can never be 'approved'
Values are `not_ready` and `ready_for_review`. Gates failing => not_ready. Passing gates only means automated checks passed.
## ADR-040: Audit is a service, not a graph node (for now)
It is idempotent and versioned, so it needs no checkpoint resume. Phase 9 will orchestrate analyze -> audit -> documents behind the API. A stale audit (specs changed afterwards) is excluded from the package rather than shown as current.

## ADR-041: Authentication = scrypt passwords + opaque server-side session tokens
Passwords are hashed with hashlib scrypt (n=2^14, r=8, p=1, per-user salt; no extra dependency). Login always performs one verification (a dummy hash for unknown users) so timing does not reveal usernames, and failures are generic. Tokens are random, returned once, and only their SHA-256 is stored, so a database leak does not yield usable sessions; logout revokes server-side. Bearer tokens in the `Authorization` header (not cookies) make CSRF a non-issue. Registration is off by default (`ALLOW_REGISTRATION`); users are created with the CLI, which reads the password from a prompt or stdin, never from an argument.
## ADR-042: Login and generation are rate limited in-process
Per client+username (5 / 5 min), per client (30 / 5 min), and per user for LLM-spending operations (20 / hour). State is in memory: it resets on restart and is per worker. Behind several workers or instances the effective limit multiplies; a shared store (Redis) or a gateway limit is a Phase 10 item. `X-Forwarded-For` is not trusted, so behind a proxy all clients share the proxy address until the proxy is configured appropriately.
## ADR-043: Project access is owner-only and reported as 404
Every project route resolves the project through one dependency that returns the same 404 for a missing project and for someone else's project, so ids cannot be probed. There is no sharing or role model yet; projects created before Phase 9 have no owner and are inaccessible through the API.
## ADR-044: Long runs are background jobs, one per project
Start/answers/retry/audit/documents/revision return 202 and run as asyncio tasks tracked in memory (state, safe error text). Only our own domain errors expose their message; anything else shows "internal error" and is logged. The job record is lost on restart (results are not: every service persists its own output and status), and a task interrupted by a restart is not resumed automatically except through the workflow's own checkpoint retry. Not suitable for multi-instance deployment without a real queue (Phase 10).
## ADR-045: Approvals are append-only decisions bound to a fingerprint
A request's fingerprint is a hash of stage, ref, decision text, reason and affected ids. A decision counts only while the fingerprint still matches, so a regenerated or changed item is pending again, and a decision made on a stale view is refused (409). Three outcomes: approve, reject (recorded and flagged in the documents), request revision (needs a note; regenerates that stage and everything downstream with the note as untrusted feedback). NFR targets proposed by the system are approved through `approve_nfr_targets`, which saves a NEW requirements version (the earlier one stays as the record). The system makes no recommendation of its own (`recommended` stays empty). Approving items never marks the package itself approved; the status line says so.
## ADR-046: Documents served only from the manifest, as plain text
`/documents/files/{path}` serves a path only if the manifest lists it (or it is `manifest.json`), after the bundle path validator and a resolved-path containment check; Markdown is sent as `text/plain` with `nosniff` so the browser never renders it as HTML. The ZIP and PDF are served as attachments.
## ADR-047: UI is static, dependency-free, and uses `textContent` only
No framework, no inline script or style, strict CSP (`default-src 'none'; script-src 'self'`). All server data is inserted as text nodes. The token lives in `sessionStorage` (wrapped in try/catch), so it is readable by script on the same origin: an XSS would expose it, which is why the CSP and text-only rendering matter. Accessibility has had basic checks only (labels, focus outlines, aria-live), no screen-reader testing.
## ADR-048: The checkpointer stays SQLite for now
LangGraph's Postgres saver is not installed; `CHECKPOINT_PATH` points to a SQLite file even when application data is in PostgreSQL. This is a single-instance limitation and a gap against a fully Postgres production setup; Phase 10 decides between adding the Postgres saver and keeping one instance.
## ADR-049: The API exposes steps; it does not auto-chain analyze -> audit -> documents
Each step is a separate, authorised, rate-limited call so a human can review between them (hybrid approval). A one-click chain would skip those review points.

## ADR-050: PostgreSQL verified by running the same test suite against it
`TEST_DATABASE_URL` switches the shared fixtures to PostgreSQL (schema dropped and recreated per test). All tests except the SQLite-specific migration test pass on PostgreSQL 16; the migration chain itself was verified up/down/up and `alembic check` on PostgreSQL. The checkpointer remains SQLite (ADR-048).
## ADR-051: Forwarded client addresses are opt-in and use the last entry only
`TRUST_FORWARDED_FOR` (default off). The last `X-Forwarded-For` entry is the one appended by the trusted proxy; earlier ones are client-supplied.
## ADR-052: Benchmarks are inputs plus a live runner, not a scored suite
`benchmarks/problems.json` (23 problems incl. vague, contradictory, adversarial, out-of-scope and non-English) and `scripts/benchmark.py` record where live runs end and the audit verdict. There is no automatic quality score: judging a generated package needs a human.
