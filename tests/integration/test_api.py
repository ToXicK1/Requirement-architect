import io
import zipfile

from requirements_architect.core.security import RateLimiter
from requirements_architect.schemas.architecture import ArchitectureSpec
from requirements_architect.schemas.common import ApprovalCandidate
from requirements_architect.schemas.state import StageId
from tests.api_helpers import PASSWORD, api, login, wait
from tests.audit_helpers import QA_OK, SECURITY_OK
from tests.conftest import Script as BaseScript
from tests.fakes import FakeSearch
from tests.research_helpers import make_service

V = "/api/v1"


def Script(**kw):
    kw.setdefault("security", [SECURITY_OK])
    kw.setdefault("qa_deploy", [QA_OK])
    return BaseScript(**kw)


def factory(repo, gateway):
    return make_service(gateway, repo, providers=[FakeSearch("brave", [])])


def make(tmp_path, **kw):
    return api(tmp_path, Script(), research_factory=factory, **kw)


async def new_project(client, h, name="Demo"):
    r = await client.post(
        f"{V}/projects", json={"name": name, "problem_statement": "We need a thing."}, headers=h
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def built(client, c, h):
    pid = await new_project(client, h)
    assert (await client.post(f"{V}/projects/{pid}/start", headers=h)).status_code == 202
    await wait(c)
    return pid


# ----------------------------------------------------------------- authentication
async def test_project_routes_require_a_valid_token(tmp_path):
    async with make(tmp_path) as (client, c, _):
        h = await login(client, c)
        pid = await new_project(client, h)
        for method, path in [
            ("get", "/projects"),
            ("post", "/projects"),
            ("get", f"/projects/{pid}"),
            ("get", f"/projects/{pid}/status"),
            ("post", f"/projects/{pid}/start"),
            ("get", f"/projects/{pid}/outputs"),
            ("get", f"/projects/{pid}/approvals"),
            ("get", f"/projects/{pid}/documents"),
            ("get", f"/projects/{pid}/activity"),
            ("get", "/auth/me"),
        ]:
            for headers in ({}, {"Authorization": "Bearer nope"}, {"Authorization": "Basic abc"}):
                r = await getattr(client, method)(V + path, headers=headers)
                assert r.status_code == 401, (method, path, headers)
                assert r.headers["www-authenticate"] == "Bearer"


async def test_login_logout_and_generic_failures(tmp_path):
    async with make(tmp_path) as (client, c, _):
        h = await login(client, c)
        assert (await client.get(f"{V}/auth/me", headers=h)).json()["username"] == "alice"
        bad = await client.post(f"{V}/auth/login", json={"username": "alice", "password": "x" * 14})
        none = await client.post(
            f"{V}/auth/login", json={"username": "ghost", "password": "x" * 14}
        )
        assert bad.status_code == none.status_code == 401 and bad.json() == none.json()
        assert (await client.post(f"{V}/auth/logout", headers=h)).status_code == 204
        assert (await client.get(f"{V}/auth/me", headers=h)).status_code == 401


async def test_login_is_rate_limited(tmp_path):
    async with make(tmp_path) as (client, c, _):
        await c.auth.register("alice", PASSWORD)
        codes = [
            (
                await client.post(
                    f"{V}/auth/login", json={"username": "alice", "password": "wrong-password-1"}
                )
            ).status_code
            for _ in range(7)
        ]
        assert codes[:5] == [401] * 5 and codes[5:] == [429, 429]
        ok = await client.post(f"{V}/auth/login", json={"username": "alice", "password": PASSWORD})
        assert ok.status_code == 429  # even the right password is refused while locked out


async def test_registration_disabled_by_default_and_enabled_by_setting(tmp_path):
    body = {"username": "bob.builder", "password": PASSWORD}
    (tmp_path / "b").mkdir()
    async with make(tmp_path) as (client, _, _):
        assert (await client.post(f"{V}/auth/register", json=body)).status_code == 403
    async with make(tmp_path / "b", registration=True) as (client, _, _):
        assert (await client.post(f"{V}/auth/register", json=body)).status_code == 201
        assert (await client.post(f"{V}/auth/register", json=body)).status_code == 409
        weak = {"username": "carol", "password": "short"}
        assert (await client.post(f"{V}/auth/register", json=weak)).status_code == 422


# ----------------------------------------------------------------- authorization
async def test_other_users_projects_are_invisible(tmp_path):
    async with make(tmp_path) as (client, c, _):
        a = await login(client, c, "alice")
        b = await login(client, c, "bobby")
        pid = await built(client, c, a)
        assert [p["id"] for p in (await client.get(f"{V}/projects", headers=a)).json()] == [pid]
        assert (await client.get(f"{V}/projects", headers=b)).json() == []
        for method, path in [
            ("get", ""),
            ("get", "/status"),
            ("post", "/start"),
            ("post", "/answers"),
            ("post", "/retry"),
            ("get", "/outputs"),
            ("get", "/outputs/stage_05_architecture"),
            ("post", "/audit"),
            ("get", "/audit"),
            ("get", "/approvals"),
            ("post", "/approvals"),
            ("post", "/documents"),
            ("get", "/documents"),
            ("get", "/documents/download.zip"),
            ("get", "/documents/files/README.md"),
            ("get", "/activity"),
        ]:
            r = await getattr(client, method)(f"{V}/projects/{pid}{path}", headers=b)
            missing = await getattr(client, method)(f"{V}/projects/{'0' * 36}{path}", headers=b)
            assert r.status_code == missing.status_code == 404, (method, path, r.status_code)
            assert r.json() == missing.json()  # indistinguishable from "does not exist"


# ----------------------------------------------------------------- workflow
async def test_start_runs_in_background_and_cannot_be_repeated(tmp_path):
    async with make(tmp_path) as (client, c, _):
        h = await login(client, c)
        pid = await new_project(client, h)
        r = await client.post(f"{V}/projects/{pid}/start", headers=h)
        assert r.status_code == 202 and r.json()["kind"] == "workflow"
        await wait(c)
        s = (await client.get(f"{V}/projects/{pid}/status", headers=h)).json()
        assert s["status"] == "specifications_complete" and s["job"]["state"] == "succeeded"
        again = await client.post(f"{V}/projects/{pid}/start", headers=h)
        assert again.status_code == 409


async def test_answers_are_validated_before_a_job_starts(tmp_path):
    async with make(tmp_path) as (client, c, _):
        h = await login(client, c)
        pid = await new_project(client, h)
        body = {"answers": [{"question_id": "Q-001", "answer": "x"}]}
        r = await client.post(f"{V}/projects/{pid}/answers", json=body, headers=h)
        assert r.status_code == 409  # not awaiting answers
        assert c.jobs.get(pid) is None
        bad = await client.post(f"{V}/projects/{pid}/answers", json={"answers": []}, headers=h)
        assert bad.status_code == 422
        extra = await client.post(
            f"{V}/projects/{pid}/answers", json={"answers": body["answers"], "x": 1}, headers=h
        )
        assert extra.status_code == 422


async def test_retry_only_after_failure(tmp_path):
    async with make(tmp_path) as (client, c, _):
        h = await login(client, c)
        pid = await built(client, c, h)
        assert (await client.post(f"{V}/projects/{pid}/retry", headers=h)).status_code == 409


async def test_generation_needs_a_configured_llm(tmp_path):
    async with make(tmp_path, llm=False) as (client, c, _):
        h = await login(client, c)
        pid = await new_project(client, h)
        for path in ("start", "retry", "audit"):
            r = await client.post(f"{V}/projects/{pid}/{path}", headers=h)
            assert r.status_code == 503, path
        status = await client.get(f"{V}/projects/{pid}/status", headers=h)
        assert status.status_code == 200 and status.json()["workflow"] is None


async def test_expensive_operations_are_rate_limited_per_user(tmp_path):
    async with make(tmp_path) as (client, c, _):
        c.expensive = RateLimiter(limit=1, window_seconds=3600)
        h = await login(client, c)
        p1 = await new_project(client, h)
        p2 = await new_project(client, h, "Second")
        assert (await client.post(f"{V}/projects/{p1}/start", headers=h)).status_code == 202
        await wait(c)
        assert (await client.post(f"{V}/projects/{p2}/start", headers=h)).status_code == 429


async def test_one_job_per_project(tmp_path):
    async with make(tmp_path) as (client, c, _):
        h = await login(client, c)
        pid = await built(client, c, h)
        import asyncio

        gate = asyncio.Event()

        async def hold():
            await gate.wait()

        c.jobs.start(pid, "audit", hold)
        r = await client.post(f"{V}/projects/{pid}/documents", headers=h)
        assert r.status_code == 409 and "already running" in r.json()["detail"]
        gate.set()
        await wait(c)


# ----------------------------------------------------------------- outputs, audit, approvals
async def test_outputs_audit_and_activity(tmp_path):
    async with make(tmp_path) as (client, c, _):
        h = await login(client, c)
        pid = await built(client, c, h)
        outs = (await client.get(f"{V}/projects/{pid}/outputs", headers=h)).json()
        assert outs["stage_05_architecture"] == [1]
        one = (
            await client.get(f"{V}/projects/{pid}/outputs/stage_05_architecture", headers=h)
        ).json()
        assert one["version"] == 1 and "components" in one["payload"]
        assert (
            await client.get(
                f"{V}/projects/{pid}/outputs/stage_05_architecture?version=9", headers=h
            )
        ).status_code == 404
        assert (
            await client.get(f"{V}/projects/{pid}/outputs/not_a_stage", headers=h)
        ).status_code == 422
        assert (await client.get(f"{V}/projects/{pid}/audit", headers=h)).status_code == 404
        assert (await client.post(f"{V}/projects/{pid}/audit", headers=h)).status_code == 202
        await wait(c)
        rep = (await client.get(f"{V}/projects/{pid}/audit", headers=h)).json()
        assert rep["report"]["verdict"] in {"not_ready", "ready_for_review"}
        acts = (await client.get(f"{V}/projects/{pid}/activity", headers=h)).json()
        assert {"project.create", "workflow.start", "audit.run"} <= {a["action"] for a in acts}
        assert h["Authorization"].split()[1] not in str(acts)


async def test_approval_decisions_over_http(tmp_path):
    async with make(tmp_path) as (client, c, st):
        h = await login(client, c)
        pid = await built(client, c, h)
        got = await st.repo.get_latest_output(pid, StageId.ARCHITECTURE, ArchitectureSpec)
        got[1].approval_candidates = [
            ApprovalCandidate(
                source_stage=StageId.ARCHITECTURE.value, ref="AD-001", decision="d", reason="r"
            )
        ]
        await st.repo.save_stage_output(pid, StageId.ARCHITECTURE, got[1], got[0].depends_on)
        reqs = (await client.get(f"{V}/projects/{pid}/approvals", headers=h)).json()
        r = reqs[0]
        body = {
            "stage_id": r["stage_id"],
            "ref": r["ref"],
            "fingerprint": "0" * 64,
            "decision": "approve",
        }
        assert (
            await client.post(f"{V}/projects/{pid}/approvals", json=body, headers=h)
        ).status_code == 409
        body["fingerprint"] = r["fingerprint"]
        ok = await client.post(f"{V}/projects/{pid}/approvals", json=body, headers=h)
        assert ok.status_code == 200 and ok.json()["state"] == "approved"
        bad = await client.post(
            f"{V}/projects/{pid}/approvals", json={**body, "decision": "maybe"}, headers=h
        )
        assert bad.status_code == 422


# ----------------------------------------------------------------- documents
async def test_documents_generate_and_download_safely(tmp_path):
    async with make(tmp_path) as (client, c, _):
        h = await login(client, c)
        pid = await built(client, c, h)
        assert (await client.get(f"{V}/projects/{pid}/documents", headers=h)).status_code == 404
        assert (await client.post(f"{V}/projects/{pid}/documents", headers=h)).status_code == 202
        await wait(c)
        assert c.jobs.get(pid).state == "succeeded", c.jobs.get(pid)
        m = (await client.get(f"{V}/projects/{pid}/documents", headers=h)).json()
        paths = [f["path"] for f in m["files"]]
        assert "09_IMPLEMENTATION/CODING_AGENT_INSTRUCTIONS.md" in paths
        one = await client.get(f"{V}/projects/{pid}/documents/files/{paths[0]}", headers=h)
        assert one.status_code == 200 and one.headers["x-content-type-options"] == "nosniff"
        assert one.headers["content-type"].startswith("text/plain")
        pdf = next(p for p in paths if p.endswith(".pdf"))
        pr = await client.get(f"{V}/projects/{pid}/documents/files/{pdf}", headers=h)
        assert pr.content.startswith(b"%PDF") and pr.headers["content-type"] == "application/pdf"
        z = await client.get(f"{V}/projects/{pid}/documents/download.zip", headers=h)
        names = zipfile.ZipFile(io.BytesIO(z.content)).namelist()
        assert z.headers["content-type"] == "application/zip"
        assert all(n.startswith("PROJECT_DOCUMENTATION/") for n in names)
        # path traversal and unlisted files are refused
        for evil in (
            "../../app.db",
            "..%2F..%2Fapp.db",
            "%2e%2e/%2e%2e/x",
            "/etc/passwd",
            "a//b",
            "README.md.tmp",
            "manifest.json/../x",
        ):
            r = await client.get(f"{V}/projects/{pid}/documents/files/{evil}", headers=h)
            assert r.status_code in (404, 422), (evil, r.status_code)
        mf = await client.get(f"{V}/projects/{pid}/documents/files/manifest.json", headers=h)
        assert mf.status_code == 200
        assert (
            await client.get(f"{V}/projects/{pid}/documents?version=99", headers=h)
        ).status_code == 404


async def test_documents_need_complete_specs(tmp_path):
    async with make(tmp_path) as (client, c, _):
        h = await login(client, c)
        pid = await new_project(client, h)
        assert (await client.post(f"{V}/projects/{pid}/documents", headers=h)).status_code == 409


# ----------------------------------------------------------------- hardening
async def test_security_headers_and_no_store(tmp_path):
    async with make(tmp_path) as (client, c, _):
        h = await login(client, c)
        r = await client.get(f"{V}/projects", headers=h)
        assert r.headers["cache-control"] == "no-store"
        assert r.headers["x-frame-options"] == "DENY"
        assert "default-src 'none'" in r.headers["content-security-policy"]
        assert r.headers["referrer-policy"] == "no-referrer"


async def test_oversized_bodies_are_rejected(tmp_path):
    async with make(tmp_path) as (client, c, _):
        h = await login(client, c)
        big = {"name": "x", "problem_statement": "y" * 300_000}
        r = await client.post(f"{V}/projects", json=big, headers=h)
        assert r.status_code == 413 and r.json() == {"error": "request_too_large"}

        async def chunks():  # no Content-Length: streamed
            for _ in range(10):
                yield b"x" * 60_000

        s = await client.post(f"{V}/projects", content=chunks(), headers=h)
        assert s.status_code == 413
        small = {"name": "x", "problem_statement": "y" * 30_000}
        assert (await client.post(f"{V}/projects", json=small, headers=h)).status_code == 422


async def test_project_input_validation(tmp_path):
    async with make(tmp_path) as (client, c, _):
        h = await login(client, c)
        for body in (
            {"name": "", "problem_statement": "long enough text"},
            {"name": "n", "problem_statement": "short"},
            {"name": "n", "problem_statement": "long enough text", "owner_id": "x"},
        ):
            assert (await client.post(f"{V}/projects", json=body, headers=h)).status_code == 422


async def test_revision_request_runs_as_a_job(tmp_path):
    async with make(tmp_path) as (client, c, st):
        h = await login(client, c)
        pid = await built(client, c, h)
        got = await st.repo.get_latest_output(pid, StageId.ARCHITECTURE, ArchitectureSpec)
        got[1].approval_candidates = [
            ApprovalCandidate(
                source_stage=StageId.ARCHITECTURE.value, ref="AD-001", decision="d", reason="r"
            )
        ]
        await st.repo.save_stage_output(pid, StageId.ARCHITECTURE, got[1], got[0].depends_on)
        r = (await client.get(f"{V}/projects/{pid}/approvals", headers=h)).json()[0]
        body = {
            "stage_id": r["stage_id"],
            "ref": "AD-001",
            "fingerprint": r["fingerprint"],
            "decision": "request_revision",
            "note": "",
        }
        # a revision without a note is refused by the service (job fails with a safe message)
        out = await client.post(f"{V}/projects/{pid}/approvals", json=body, headers=h)
        assert out.status_code == 202
        await wait(c)
        assert c.jobs.get(pid).state == "failed" and "note" in c.jobs.get(pid).error
        body["note"] = "use queues"
        assert (
            await client.post(f"{V}/projects/{pid}/approvals", json=body, headers=h)
        ).status_code == 202
        await wait(c)
        assert c.jobs.get(pid).state == "succeeded"
        assert await st.repo.list_versions(pid, StageId.QA_DEPLOY) == [1, 2]


async def test_ui_is_served_with_a_strict_csp_and_no_inline_script(tmp_path):
    async with make(tmp_path) as (client, _, _):
        r = await client.get("/")
        assert r.status_code == 200 and '<script src="/app.js">' in r.text
        assert "<script>" not in r.text and "onclick=" not in r.text
        assert "script-src 'self'" in r.headers["content-security-policy"]
        js = await client.get("/app.js")
        assert js.status_code == 200 and "innerHTML" not in js.text.replace("never innerHTML", "")
        assert (
            await client.get("/health/live")
        ).status_code == 200  # API routes win over the mount


async def test_a_listed_file_replaced_by_a_symlink_out_of_the_package_is_refused(tmp_path):
    async with make(tmp_path) as (client, c, _):
        h = await login(client, c)
        pid = await built(client, c, h)
        await client.post(f"{V}/projects/{pid}/documents", headers=h)
        await wait(c)
        m = (await client.get(f"{V}/projects/{pid}/documents", headers=h)).json()
        rel = next(f["path"] for f in m["files"] if f["path"].endswith(".md"))
        secret = tmp_path / "outside.txt"
        secret.write_text("TOP SECRET")
        target = c.output_dir / pid / f"v{m['package_version']}" / "PROJECT_DOCUMENTATION" / rel
        target.unlink()
        target.symlink_to(secret)
        r = await client.get(f"{V}/projects/{pid}/documents/files/{rel}", headers=h)
        assert r.status_code == 404 and "TOP SECRET" not in r.text


async def test_unlisted_files_on_disk_are_not_served(tmp_path):
    async with make(tmp_path) as (client, c, _):
        h = await login(client, c)
        pid = await built(client, c, h)
        await client.post(f"{V}/projects/{pid}/documents", headers=h)
        await wait(c)
        m = (await client.get(f"{V}/projects/{pid}/documents", headers=h)).json()
        root = c.output_dir / pid / f"v{m['package_version']}" / "PROJECT_DOCUMENTATION"
        (root / "extra.txt").write_text("not in the manifest")
        r = await client.get(f"{V}/projects/{pid}/documents/files/extra.txt", headers=h)
        assert r.status_code == 404
