"""Run benchmark problems against a LIVE server and report what happened. Needs a running server
with an LLM configured. Questions are NOT answered: it records where each run pauses.

  python scripts/benchmark.py --url http://127.0.0.1:8000 --user NAME [--only ID ...] [--limit N]
The password is read from the BENCH_PASSWORD environment variable (never an argument)."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import httpx

HERE = Path(__file__).resolve().parent.parent / "benchmarks"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8000")
    ap.add_argument("--user", required=True)
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--timeout", type=int, default=900, help="seconds per problem")
    ap.add_argument("--out", default="benchmark_results.json")
    a = ap.parse_args()
    password = os.environ.get("BENCH_PASSWORD", "")
    if not password:
        print("set BENCH_PASSWORD", file=sys.stderr)
        return 2
    problems = json.loads((HERE / "problems.json").read_text("utf-8"))
    if a.only:
        problems = [p for p in problems if p["id"] in a.only]
    if a.limit:
        problems = problems[: a.limit]
    results = []
    with httpx.Client(base_url=a.url + "/api/v1", timeout=60) as c:
        r = c.post("/auth/login", json={"username": a.user, "password": password})
        r.raise_for_status()
        c.headers["Authorization"] = "Bearer " + r.json()["token"]
        for p in problems:
            t0 = time.time()
            pid = c.post(
                "/projects", json={"name": p["id"], "problem_statement": p["problem_statement"]}
            ).json()["id"]
            c.post(f"/projects/{pid}/start").raise_for_status()
            state, job = "timeout", None
            while time.time() - t0 < a.timeout:
                st = c.get(f"/projects/{pid}/status").json()
                job = st["job"]
                if job and job["state"] != "running":
                    state = st["status"]
                    break
                time.sleep(5)
            row = {
                "id": p["id"],
                "category": p["category"],
                "status": state,
                "seconds": round(time.time() - t0),
                "job_error": job and job.get("error"),
            }
            if state == "specifications_complete":
                c.post(f"/projects/{pid}/audit").raise_for_status()
                while c.get(f"/projects/{pid}/status").json()["job"]["state"] == "running":
                    time.sleep(5)
                rep = c.get(f"/projects/{pid}/audit")
                if rep.status_code == 200:
                    r = rep.json()["report"]
                    row |= {
                        "verdict": r["verdict"],
                        "findings": len(r["findings"]),
                        "llm_review": r["llm_review"],
                    }
            results.append(row)
            print(json.dumps(row), flush=True)
    Path(a.out).write_text(json.dumps(results, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
