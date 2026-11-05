"""Turn a Package into files on disk and a ZIP, with a hash manifest and verification."""

from __future__ import annotations

import hashlib
import io
import json
import re
import zipfile
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel

from requirements_architect.generators.docs.model import ROOT, DocInputs
from requirements_architect.generators.docs.package import Package

MANIFEST = "manifest.json"
PDF_NAME = "PROJECT_DOCUMENTATION.pdf"
_SAFE_PATH = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.\-]*(/[A-Za-z0-9_][A-Za-z0-9_.\-]*)*$")
_ZIP_EPOCH = (1980, 1, 1, 0, 0, 0)


class ManifestEntry(BaseModel):
    path: str
    sha256: str
    bytes: int
    kind: str  # document | supporting | pdf
    applicable: bool = True


class Manifest(BaseModel):
    project_id: str
    project_name: str
    package_version: int
    generated_at: datetime
    approval_status: str
    source_versions: dict[str, int]
    files: list[ManifestEntry]
    pending_documents: dict[str, str]
    note: str = (
        "manifest.json is not listed in itself. Hashes are SHA-256 over the stored bytes. "
        "The ZIP stores every listed file under PROJECT_DOCUMENTATION/."
    )


def safe_relative(path: str) -> str:
    """Reject anything that could escape the output directory."""
    if not _SAFE_PATH.match(path) or ".." in path.split("/"):
        raise ValueError(f"unsafe file path: {path!r}")
    return path


def assemble(pkg: Package, inputs: DocInputs, pdf: bytes | None = None) -> dict[str, bytes]:
    """All files of the deliverable (path -> bytes), manifest included."""
    files: dict[str, bytes] = {}
    kinds: dict[str, str] = {}
    applicable: dict[str, bool] = {}
    for d in pkg.docs:
        files[d.path] = d.body.encode("utf-8")
        kinds[d.path] = "document"
        applicable[d.path] = d.applicable
    for path, data in pkg.files.items():
        files[path] = data
        kinds[path] = "supporting"
    if pdf is not None:
        files[PDF_NAME] = pdf
        kinds[PDF_NAME] = "pdf"
    for p in files:
        safe_relative(p)
    manifest = Manifest(
        project_id=inputs.project_id,
        project_name=inputs.project_name,
        package_version=inputs.package_version,
        generated_at=inputs.generated_at,
        approval_status=inputs.approval_status,
        source_versions=inputs.source_versions,
        files=[
            ManifestEntry(
                path=p,
                sha256=hashlib.sha256(files[p]).hexdigest(),
                bytes=len(files[p]),
                kind=kinds[p],
                applicable=applicable.get(p, True),
            )
            for p in sorted(files)
        ],
        pending_documents=pkg.pending,
    )
    files[MANIFEST] = (manifest.model_dump_json(indent=2) + "\n").encode("utf-8")
    return files


def write_files(files: dict[str, bytes], out_dir: Path) -> Path:
    """Write the deliverable under out_dir/PROJECT_DOCUMENTATION. Never writes outside it."""
    root = (out_dir / ROOT).resolve()
    root.mkdir(parents=True, exist_ok=True)
    for rel, data in files.items():
        safe_relative(rel)
        target = (root / rel).resolve()
        if not target.is_relative_to(root):
            raise ValueError(f"path escapes the output directory: {rel!r}")
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(target.name + ".tmp")
        tmp.write_bytes(data)
        tmp.replace(target)
    return root


def verify_directory(root: Path) -> list[str]:
    """Re-read what is on disk and compare with the manifest. Returns problems (empty = ok)."""
    problems: list[str] = []
    mpath = root / MANIFEST
    try:
        manifest = Manifest.model_validate(json.loads(mpath.read_text("utf-8")))
    except (OSError, ValueError) as exc:
        return [f"manifest unreadable: {type(exc).__name__}"]
    listed = {e.path for e in manifest.files}
    for e in manifest.files:
        p = root / e.path
        try:
            data = p.read_bytes()
        except OSError:
            problems.append(f"missing or unreadable: {e.path}")
            continue
        if not data:
            problems.append(f"empty: {e.path}")
        elif len(data) != e.bytes or hashlib.sha256(data).hexdigest() != e.sha256:
            problems.append(f"does not match manifest: {e.path}")
    on_disk = {
        p.relative_to(root).as_posix()
        for p in root.rglob("*")
        if p.is_file() and p.name != MANIFEST
    }
    for extra in sorted(on_disk - listed):
        problems.append(f"not in manifest: {extra}")
    return problems


def build_zip(files: dict[str, bytes]) -> bytes:
    """Deterministic ZIP (fixed timestamps, sorted entries)."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for rel in sorted(files):
            safe_relative(rel)
            info = zipfile.ZipInfo(f"{ROOT}/{rel}", date_time=_ZIP_EPOCH)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            z.writestr(info, files[rel])
    return buf.getvalue()


def verify_zip(data: bytes) -> list[str]:
    """Check a ZIP's entries are safe, non-empty and match its manifest."""
    problems: list[str] = []
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        return ["not a valid zip"]
    with z:
        bad = z.testzip()
        if bad:
            problems.append(f"corrupt entry: {bad}")
        names = z.namelist()
        for n in names:
            if not n.startswith(f"{ROOT}/") or not _SAFE_PATH.match(n):
                problems.append(f"unsafe entry: {n}")
        try:
            manifest = Manifest.model_validate(json.loads(z.read(f"{ROOT}/{MANIFEST}")))
        except (KeyError, ValueError):
            return [*problems, "manifest missing or invalid"]
        for e in manifest.files:
            name = f"{ROOT}/{e.path}"
            if name not in names:
                problems.append(f"missing from zip: {e.path}")
                continue
            body = z.read(name)
            if not body:
                problems.append(f"empty: {e.path}")
            elif hashlib.sha256(body).hexdigest() != e.sha256:
                problems.append(f"does not match manifest: {e.path}")
        listed = {f"{ROOT}/{e.path}" for e in manifest.files} | {f"{ROOT}/{MANIFEST}"}
        problems += [f"not in manifest: {n}" for n in names if n not in listed]
    return problems
