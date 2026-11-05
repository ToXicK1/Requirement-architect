from requirements_architect.agent.approvals import ApprovalError
from requirements_architect.api.jobs import JobRunner
from requirements_architect.api.middleware import BodyLimit


async def test_unexpected_errors_never_expose_their_message():
    runner = JobRunner((ApprovalError,))

    async def boom():
        raise RuntimeError("password=hunter2 in /srv/secret/path")

    async def known():
        raise ApprovalError("a revision needs a note")

    runner.start("p1", "x", boom)
    runner.start("p2", "x", known)
    await runner.drain()
    assert runner.get("p1").state == "failed" and runner.get("p1").error == "internal error"
    assert runner.get("p2").error == "a revision needs a note"


async def _run(declared: bytes):
    called, sent = [], []

    async def app(scope, receive, send):
        called.append(1)
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    async def send(m):
        sent.append(m)

    async def receive():
        return {"type": "http.request", "body": b"x", "more_body": False}

    scope = {"type": "http", "path": "/", "headers": [(b"content-length", declared)]}
    await BodyLimit(app, 1000)(scope, receive, send)
    return called, sent


async def test_declared_oversize_is_rejected_before_the_app_runs():
    called, sent = await _run(b"1000000000")
    assert not called and sent[0]["status"] == 413


async def test_small_requests_pass_through():
    called, sent = await _run(b"1")
    assert called and sent[0]["status"] == 200
