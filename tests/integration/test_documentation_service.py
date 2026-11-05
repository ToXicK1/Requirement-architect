import pytest

from requirements_architect.agent.documentation import DocumentationError, DocumentationService
from requirements_architect.generators.docs.bundle import MANIFEST, verify_directory, verify_zip
from requirements_architect.schemas.state import StageId
from tests.conftest import Script, make_stack
from tests.fakes import FakeSearch
from tests.research_helpers import make_service


def factory(repo, gateway):
    return make_service(gateway, repo, providers=[FakeSearch("brave", [])])


async def run_to_specs(st):
    p = await st.repo.create_project("Demo", "We need a thing.")
    await st.service.start(p.id)
    return p


async def test_generates_verified_package_and_records_dependencies(tmp_path):
    async with make_stack(tmp_path, Script(), research_factory=factory) as st:
        p = await run_to_specs(st)
        svc = DocumentationService(st.repo, tmp_path / "out")
        res = await svc.generate(p.id)
        assert res.version == 1 and res.zip_path.exists()
        assert verify_directory(res.directory) == []
        assert verify_zip(res.zip_path.read_bytes()) == []
        assert (res.directory / "PROJECT_DOCUMENTATION.pdf").read_bytes().startswith(b"%PDF")
        assert (await st.repo.get_project(p.id)).status == "documents_complete"
        from requirements_architect.generators.docs.bundle import Manifest

        meta, stored = await st.repo.get_latest_output(p.id, StageId.DOCUMENTATION, Manifest)
        assert stored.package_version == 1
        stages = {d.stage_id for d in meta.depends_on}
        assert {
            StageId.REQUIREMENTS,
            StageId.QA_DEPLOY,
            StageId.SECURITY,
            StageId.RESEARCH,
        } <= stages
        assert (res.directory / MANIFEST).exists()


async def test_second_generation_is_a_new_version_and_keeps_the_first(tmp_path):
    async with make_stack(tmp_path, Script(), research_factory=factory) as st:
        p = await run_to_specs(st)
        svc = DocumentationService(st.repo, tmp_path / "out")
        first = await svc.generate(p.id)
        second = await svc.generate(p.id)
        assert (first.version, second.version) == (1, 2)
        assert first.directory.exists() and second.directory.exists()
        assert await st.repo.list_versions(p.id, StageId.DOCUMENTATION) == [1, 2]


async def test_refuses_before_specifications_are_complete(tmp_path):
    async with make_stack(tmp_path, Script()) as st:  # no research -> workflow ends earlier
        p = await st.repo.create_project("Demo", "stmt")
        await st.service.start(p.id)
        with pytest.raises(DocumentationError, match="specifications must be complete"):
            await DocumentationService(st.repo, tmp_path / "out").generate(p.id)


async def test_rejects_malformed_project_id(tmp_path):
    async with make_stack(tmp_path, Script()) as st:
        with pytest.raises(DocumentationError, match="invalid project id"):
            await DocumentationService(st.repo, tmp_path / "out").generate("../../etc")


async def test_failed_verification_leaves_no_output_and_no_version(tmp_path, monkeypatch):
    import requirements_architect.agent.documentation as mod

    async with make_stack(tmp_path, Script(), research_factory=factory) as st:
        p = await run_to_specs(st)
        monkeypatch.setattr(mod, "verify_directory", lambda root: ["boom"])
        svc = DocumentationService(st.repo, tmp_path / "out")
        with pytest.raises(DocumentationError, match="boom"):
            await svc.generate(p.id)
        assert list((tmp_path / "out" / p.id).iterdir()) == []
        assert await st.repo.list_versions(p.id, StageId.DOCUMENTATION) == []
        assert (await st.repo.get_project(p.id)).status == "specifications_complete"
        monkeypatch.undo()
        assert (await svc.generate(p.id)).version == 1
