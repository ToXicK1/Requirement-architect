"""Deterministic OpenAPI 3.1 document from structured endpoints, plus a structural validator.

The validator checks the structure this generator relies on; it is NOT a full OpenAPI schema
validation, and nothing here claims the document passes an external validator.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any

from requirements_architect.schemas.dataapi import AuthType, Endpoint

_PARAM = re.compile(r"\{([A-Za-z0-9_]+)\}")
_SCHEMES: dict[AuthType, dict[str, Any]] = {
    AuthType.SESSION: {"type": "apiKey", "in": "cookie", "name": "session"},
    AuthType.BEARER: {"type": "http", "scheme": "bearer"},
    AuthType.API_KEY: {"type": "apiKey", "in": "header", "name": "X-API-Key"},
    AuthType.OAUTH2: {"type": "http", "scheme": "bearer", "description": "OAuth 2.0 access token"},
}


def path_shape(path: str) -> str:
    """Normalize parameter names so /users/{id} and /users/{user_id} collide."""
    return _PARAM.sub("{}", path)


def build_openapi(title: str, endpoints: Sequence[Endpoint]) -> dict[str, Any]:
    paths: dict[str, dict[str, Any]] = {}
    used: set[AuthType] = set()
    for ep in endpoints:
        responses: dict[str, Any] = {str(ep.success_status): {"description": "Success"}}
        for err in ep.error_responses:
            responses[str(err.status)] = {"description": err.meaning}
        op: dict[str, Any] = {
            "operationId": ep.id.replace("-", "_"),
            "summary": ep.purpose,
            "responses": responses,
            "security": [{ep.authentication.value: []}]
            if ep.authentication is not AuthType.NONE
            else [],
        }
        params = [
            {"name": n, "in": "path", "required": True, "schema": {"type": "string"}}
            for n in dict.fromkeys(_PARAM.findall(ep.path))
        ]
        if params:
            op["parameters"] = params
        if ep.authentication is not AuthType.NONE:
            used.add(ep.authentication)
        paths.setdefault(ep.path, {})[ep.method.value.lower()] = op
    doc: dict[str, Any] = {
        "openapi": "3.1.0",
        "info": {"title": title[:100] or "API", "version": "0.1.0"},
        "paths": paths,
    }
    if used:
        doc["components"] = {
            "securitySchemes": {a.value: _SCHEMES[a] for a in sorted(used, key=lambda x: x.value)}
        }
    return doc


def validate_structure(doc: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    if not str(doc.get("openapi", "")).startswith("3."):
        problems.append("missing or unsupported 'openapi' version")
    if not isinstance(doc.get("info"), dict) or not doc["info"].get("title"):
        problems.append("missing info.title")
    schemes = set(doc.get("components", {}).get("securitySchemes", {}))
    for path, item in (doc.get("paths") or {}).items():
        if not path.startswith("/"):
            problems.append(f"path must start with '/': {path}")
        for method, op in item.items():
            where = f"{method.upper()} {path}"
            if not op.get("responses"):
                problems.append(f"{where}: no responses")
            declared = {p["name"] for p in op.get("parameters", []) if p.get("in") == "path"}
            if declared != set(_PARAM.findall(path)):
                problems.append(f"{where}: path parameters not declared exactly")
            for req in op.get("security", []):
                for name in req:
                    if name not in schemes:
                        problems.append(f"{where}: unknown security scheme {name}")
    return problems
