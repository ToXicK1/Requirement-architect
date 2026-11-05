# Development Plan
Phases follow the master instruction (Section 17). Completion = tests pass AND behavior verified.

| Phase | Name | Completion condition |
|---|---|---|
| 1 | Repository foundation | App boots, health endpoints pass, config validated, Alembic wired, Docker files written |
| 2 | LLM infrastructure | Provider abstraction, structured output, retries, cost tracking, tested with fake provider |
| 3 | Core agent | Typed project state, LangGraph workflow, clarification pause/resume, checkpoints |
| 4 | Research | Adapters, SSRF-safe fetcher, evidence registry |
| 5 | Requirements engineering | FR/NFR generation, IDs, traceability |
| 6 | Technical specifications | Architecture, tech, DB/API, security, UI/UX, QA/deploy stages (DONE on scripted LLM; live run blocked on key) |
| 7 | Documentation generation | Markdown tree, PDF, manifest, ZIP (DONE with scripted inputs; audit docs pending Phase 8; diagrams are source only) |
| 8 | Audit engine | Deterministic + LLM validators, bounded remediation |
| 9 | Application interface | Auth, dashboard, approvals, downloads, CLI |
| 10 | Production hardening | Full tests, security scan, backup/recovery docs, deployment verification |

Dependencies: 2 -> 3 -> 4/5 -> 6 -> 7 -> 8 -> 9 -> 10.
