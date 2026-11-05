# Security notes and residual risks

## Controls in place
- Passwords: scrypt with per-user salt; policy 12-200 characters; generic login failures; constant-work login for unknown users.
- Sessions: random tokens, only SHA-256 stored, server-side revocation, 12h default TTL, bearer header (no cookies, so no CSRF).
- Authorization: every project route checks ownership; others get 404.
- Rate limits: login (per client+user and per client), LLM-spending operations (per user).
- Input: strict request models (unknown fields rejected), 256 KiB body limit (streamed bodies too), problem statement max 20,000 chars.
- Untrusted text: problem statements, research pages, user answers and audit feedback are wrapped as untrusted data in prompts; model output is validated against schemas; code decides ids, scores, gates and approvals; no LLM-generated SQL or shell.
- Output: all text in generated documents is neutralised (no HTML/Markdown structure injection); served as `text/plain` with `nosniff`; only manifest-listed files; containment checks.
- Browser: CSP `default-src 'none'; script-src 'self'`, no inline script, `frame-ancestors 'none'`, `no-store` on API responses; UI renders server data as text only.
- Secrets: scrubber on persisted model output and notes; keys never logged (checked in a production-mode run); `SecretStr` for settings.
- Supply chain: `pip-audit` reported no known vulnerabilities and `bandit` no medium/high findings at the Phase 10 commit (run again before each release; not in CI yet).

## Residual risks (known, accepted for now)
1. **Single instance only.** Jobs, rate limits and locks are in memory; scaling out breaks limits and can run duplicate jobs.
2. **Session token in `sessionStorage`.** Readable by any script on the origin; the CSP and text-only rendering are the defence. A stricter design would use HttpOnly cookies plus CSRF protection.
3. **No account lifecycle.** No password change/reset, no admin UI, no MFA, no per-user disable command, no lockout notification.
4. **No sharing or roles.** Owner-only; old unowned projects are unreachable.
5. **Prompt injection is mitigated, not solved.** A hostile problem statement or fetched page can still steer model output; what is protected is the system (schemas, code-decided gates, no tool use by the model, human approvals). Generated specs from hostile input must still be read by a person.
6. **Heuristic secret scrubbing and compliance-claim detection** miss things.
7. **LLM data exposure.** Problem statements, answers and fetched excerpts are sent to the configured provider; do not use confidential material unless that is acceptable.
8. **SSRF guard is application-level**; add network egress rules.
9. **Same-model audit review** shares blind spots with the generator; use a different review model when it matters.
10. **No audit trail tamper-evidence.** `audit_log` is a normal table.
11. **Backups are unencrypted by default** and the restore drill is partial (see OPERATIONS.md).
12. **UI accessibility** has had basic checks only; no assistive-technology testing.
13. **Not a certification.** Nothing here asserts regulatory compliance; generated documents are drafts for human review.
