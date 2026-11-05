import json

import httpx
import pytest
from pydantic import SecretStr

from requirements_architect.research.providers import (
    BraveSearchProvider,
    GitHubRepoSearch,
    InvalidPackageNameError,
    NpmRegistry,
    OSVAdvisories,
    PyPIRegistry,
    ResearchProviderError,
)
from requirements_architect.schemas.research import PackageRef

KEY = SecretStr("tok-very-secret")


def client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_brave_request_shape_and_mapping():
    seen = {}

    def h(r: httpx.Request):
        seen.update(url=str(r.url), token=r.headers["x-subscription-token"])
        return httpx.Response(
            200,
            json={
                "web": {
                    "results": [
                        {"url": "https://a.example/x", "title": "A", "description": "da"},
                        {"title": "no url"},
                        "junk",
                        {"url": 5},
                    ]
                }
            },
        )

    hits = await BraveSearchProvider(KEY, client(h)).search("fastapi vs flask", 5)
    assert (
        seen["token"] == "tok-very-secret"
        and "q=fastapi" in seen["url"]
        and "count=5" in seen["url"]
    )
    assert [(x.url, x.title, x.snippet, x.provider) for x in hits] == [
        ("https://a.example/x", "A", "da", "brave")
    ]


async def test_github_search_mapping_and_optional_token():
    seen = []

    def h(r: httpx.Request):
        seen.append(r.headers.get("authorization"))
        return httpx.Response(
            200,
            json={
                "items": [
                    {
                        "html_url": "https://github.com/o/r",
                        "full_name": "o/r",
                        "description": "d",
                        "stargazers_count": 7,
                        "license": {"spdx_id": "MIT"},
                    },
                    {
                        "html_url": "https://github.com/o/nolic",
                        "full_name": "o/nolic",
                        "license": None,
                    },
                    {"full_name": "broken"},
                ]
            },
        )

    hits = await GitHubRepoSearch(client(h)).search("q", 10)
    assert seen == [None] and [x.title for x in hits] == ["o/r", "o/nolic"]
    assert "stars=7" in hits[0].snippet and "license=MIT" in hits[0].snippet
    await GitHubRepoSearch(client(h), KEY).search("q", 10)
    assert seen[-1] == "Bearer tok-very-secret"


async def test_pypi_lookup_maps_fields_and_404_is_none():
    def h(r: httpx.Request):
        assert r.url.path == "/pypi/fastapi/json"
        return httpx.Response(
            200, json={"info": {"version": "1.2.3", "license": "MIT", "summary": "web fw"}}
        )

    f = await PyPIRegistry(client(h)).lookup("fastapi")
    assert (f.latest_version, f.license, f.summary) == ("1.2.3", "MIT", "web fw")
    assert f.registry_url == "https://pypi.org/project/fastapi/" and f.advisories_checked is False
    assert (
        await PyPIRegistry(client(lambda r: httpx.Response(404))).lookup("nonexistent-pkg") is None
    )


async def test_npm_lookup_scoped_and_plain():
    paths = []

    def h(r: httpx.Request):
        paths.append(r.url.raw_path.decode())
        return httpx.Response(
            200, json={"dist-tags": {"latest": "4.0.0"}, "license": "ISC", "description": "d"}
        )

    reg = NpmRegistry(client(h))
    assert (await reg.lookup("express")).latest_version == "4.0.0"
    assert (await reg.lookup("@scope/pkg")).name == "@scope/pkg"
    assert paths == ["/express", "/@scope%2Fpkg"]


@pytest.mark.parametrize(
    "name",
    [
        "",
        "../../etc/passwd",
        "a/b",
        "a b",
        "pkg?x=1",
        "pkg#frag",
        "-leading",
        "a" * 200,
        "pkg\n",
        "%2e%2e",
        "http://evil",
        "pkg@1.0",
    ],
)
async def test_pypi_rejects_hostile_names_without_any_request(name):
    def h(r):
        raise AssertionError("no request may be made")

    with pytest.raises(InvalidPackageNameError):
        await PyPIRegistry(client(h)).lookup(name)


@pytest.mark.parametrize(
    "name", ["", "../x", "UPPER", "a b", "@/x", "@scope", "pkg?x", "x" * 300, "@a/b/c", "a\\b"]
)
async def test_npm_rejects_hostile_names_without_any_request(name):
    def h(r):
        raise AssertionError("no request may be made")

    with pytest.raises(InvalidPackageNameError):
        await NpmRegistry(client(h)).lookup(name)


async def test_osv_query_body_and_mapping():
    seen = {}

    def h(r: httpx.Request):
        seen["body"] = json.loads(r.content)
        return httpx.Response(
            200, json={"vulns": [{"id": "GHSA-xxxx", "summary": "bad"}, {"nope": 1}]}
        )

    adv = await OSVAdvisories(client(h)).query(PackageRef(ecosystem="pypi", name="django"), "4.2.0")
    assert seen["body"] == {"package": {"name": "django", "ecosystem": "PyPI"}, "version": "4.2.0"}
    assert [(a.advisory_id, a.summary) for a in adv] == [("GHSA-xxxx", "bad")]
    none = await OSVAdvisories(client(lambda r: httpx.Response(200, json={}))).query(
        PackageRef(ecosystem="npm", name="x"), None
    )
    assert none == []


async def test_osv_rejects_malformed_version():
    with pytest.raises(ResearchProviderError):
        await OSVAdvisories(client(lambda r: httpx.Response(200, json={}))).query(
            PackageRef(ecosystem="pypi", name="x"), "1.0; DROP TABLE"
        )


@pytest.mark.parametrize("status", [401, 403, 429, 500, 503])
async def test_errors_never_leak_secret_or_body(status):
    def h(r):
        return httpx.Response(status, text="BODY tok-very-secret")

    with pytest.raises(ResearchProviderError) as ei:
        await BraveSearchProvider(KEY, client(h)).search("q", 3)
    assert "tok-very-secret" not in str(ei.value) and "BODY" not in str(ei.value)


async def test_network_timeout_and_garbage_are_mapped():
    def boom(r):
        raise httpx.ConnectTimeout("t")

    with pytest.raises(ResearchProviderError, match="timed out"):
        await GitHubRepoSearch(client(boom)).search("q", 3)
    with pytest.raises(ResearchProviderError, match="malformed"):
        await GitHubRepoSearch(client(lambda r: httpx.Response(200, text="<html>"))).search("q", 3)


async def test_unexpected_shapes_yield_empty_not_crash():
    for payload in ([], {"web": []}, {"web": {"results": "x"}}, {"items": "x"}, "null", 5):
        c = client(lambda r, p=payload: httpx.Response(200, content=json.dumps(p).encode()))
        assert await BraveSearchProvider(KEY, c).search("q", 3) == []
        assert await GitHubRepoSearch(c).search("q", 3) == []


async def test_empty_body_is_reported_as_malformed():
    with pytest.raises(ResearchProviderError, match="malformed"):
        await BraveSearchProvider(KEY, client(lambda r: httpx.Response(200))).search("q", 3)
