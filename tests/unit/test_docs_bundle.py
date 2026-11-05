import io
import json
import zipfile

import pytest

from requirements_architect.generators.docs.bundle import (
    MANIFEST,
    Manifest,
    assemble,
    build_zip,
    safe_relative,
    verify_directory,
    verify_zip,
    write_files,
)
from requirements_architect.generators.docs.package import build_package
from tests.doc_helpers import make_inputs


@pytest.fixture
def built():
    inp = make_inputs()
    return inp, assemble(build_package(inp), inp, pdf=b"%PDF-fake")


def test_manifest_lists_every_file_with_matching_hashes(built):
    import hashlib

    _, files = built
    manifest = Manifest.model_validate(json.loads(files[MANIFEST]))
    assert {e.path for e in manifest.files} == set(files) - {MANIFEST}
    for e in manifest.files:
        assert hashlib.sha256(files[e.path]).hexdigest() == e.sha256 and e.bytes == len(
            files[e.path]
        )
    assert {e.kind for e in manifest.files} == {"document", "supporting", "pdf"}
    assert manifest.pending_documents and manifest.approval_status.startswith("DRAFT")


def test_assembly_is_deterministic():
    a = make_inputs()
    assert assemble(build_package(a), a) == assemble(build_package(a), a)


def test_write_then_verify_directory_is_clean(built, tmp_path):
    _, files = built
    root = write_files(files, tmp_path)
    assert verify_directory(root) == []
    assert (root / "03_ARCHITECTURE" / "SYSTEM_ARCHITECTURE.md").read_text().startswith("# ")


def test_verify_detects_missing_empty_tampered_and_extra(built, tmp_path):
    _, files = built
    root = write_files(files, tmp_path)
    (root / "README.md").unlink()
    (root / "00_PROJECT_OVERVIEW/GLOSSARY.md").write_text("")
    (root / "traceability.csv").write_text("tampered")
    (root / "extra.txt").write_text("x")
    problems = verify_directory(root)
    assert "missing or unreadable: README.md" in problems
    assert "empty: 00_PROJECT_OVERVIEW/GLOSSARY.md" in problems
    assert "does not match manifest: traceability.csv" in problems
    assert "not in manifest: extra.txt" in problems


def test_verify_reports_missing_manifest(tmp_path):
    assert verify_directory(tmp_path)[0].startswith("manifest unreadable")


@pytest.mark.parametrize(
    "bad", ["../x", "/etc/passwd", "a/../b", "a\\b", "a//b", ".hidden", "a b", "", "x/"]
)
def test_unsafe_paths_are_rejected(bad):
    with pytest.raises(ValueError):
        safe_relative(bad)


def test_write_refuses_traversal(tmp_path):
    with pytest.raises(ValueError):
        write_files({"../escape.txt": b"x"}, tmp_path)
    assert not (tmp_path.parent / "escape.txt").exists()


def test_write_does_not_follow_symlink_out_of_root(tmp_path):
    root = tmp_path / "PROJECT_DOCUMENTATION"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / "link").symlink_to(outside)
    with pytest.raises(ValueError):
        write_files({"link/evil.txt": b"x"}, tmp_path)
    assert not (outside / "evil.txt").exists()


def test_zip_round_trips_and_is_deterministic(built):
    _, files = built
    z1, z2 = build_zip(files), build_zip(files)
    assert z1 == z2
    assert verify_zip(z1) == []
    names = zipfile.ZipFile(io.BytesIO(z1)).namelist()
    assert all(n.startswith("PROJECT_DOCUMENTATION/") for n in names)
    assert "PROJECT_DOCUMENTATION/PROJECT_DOCUMENTATION.pdf" in names


def test_verify_zip_detects_tampering_and_unsafe_entries(built):
    _, files = built
    bad = dict(files)
    bad["traceability.csv"] = b"changed"
    assert "does not match manifest: traceability.csv" in verify_zip(build_zip(bad))
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("../evil", b"x")
        z.writestr("PROJECT_DOCUMENTATION/manifest.json", files[MANIFEST])
    problems = verify_zip(buf.getvalue())
    assert any(p.startswith("unsafe entry") for p in problems)
    assert verify_zip(b"garbage") == ["not a valid zip"]
