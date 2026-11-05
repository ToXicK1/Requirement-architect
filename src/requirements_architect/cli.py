"""Command line: create users (registration is off by default) and run the server.

Passwords are never accepted as arguments (they would land in shell history and process lists):
they come from a prompt or from standard input."""

from __future__ import annotations

import argparse
import asyncio
import getpass
import sys
from collections.abc import Sequence
from datetime import timedelta

from requirements_architect.api.auth import AuthService
from requirements_architect.core.config import Settings, get_settings
from requirements_architect.storage.accounts import AccountRepository, UsernameTakenError
from requirements_architect.storage.database import make_engine, make_session_factory


async def create_user(settings: Settings, username: str, password: str) -> str:
    engine = make_engine(settings.database_url)
    try:
        accounts = AccountRepository(make_session_factory(engine))
        auth = AuthService(accounts, session_ttl=timedelta(hours=1))  # the CLI creates no sessions
        user = await auth.register(username, password)
        return user.username
    finally:
        await engine.dispose()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="requirements-architect")
    sub = parser.add_subparsers(dest="cmd", required=True)
    cu = sub.add_parser("create-user", help="create a user account")
    cu.add_argument("username")
    cu.add_argument("--password-stdin", action="store_true", help="read the password from stdin")
    sv = sub.add_parser("serve", help="run the web server")
    sv.add_argument("--host", default="127.0.0.1")
    sv.add_argument("--port", type=int, default=8000)
    args = parser.parse_args(argv)

    if args.cmd == "create-user":
        if args.password_stdin:
            password = sys.stdin.readline().rstrip("\n")
        else:
            password = getpass.getpass("Password: ")
            if getpass.getpass("Repeat password: ") != password:
                print("passwords do not match", file=sys.stderr)
                return 2
        try:
            name = asyncio.run(create_user(get_settings(), args.username, password))
        except UsernameTakenError:
            print("that username is already taken", file=sys.stderr)
            return 1
        except ValueError as exc:
            print(f"invalid: {exc}", file=sys.stderr)
            return 2
        print(f"created user {name}")
        return 0

    import uvicorn

    uvicorn.run("requirements_architect.main:app", host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
