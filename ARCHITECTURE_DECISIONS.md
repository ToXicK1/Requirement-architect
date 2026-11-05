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
