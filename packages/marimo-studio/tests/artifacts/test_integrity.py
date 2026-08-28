"""Validate artifact identity, manifests, receipts, and file budgets."""

from __future__ import annotations

import os
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import replace
from importlib.metadata import EntryPoint
from pathlib import Path, PurePosixPath
from typing import Any, cast

import pytest

import marimo_studio._artifacts.inputs as artifact_inputs
import marimo_studio._artifacts.paths as artifact_paths_module
import marimo_studio._artifacts.repository as artifact_repository
import marimo_studio._views.build as build_module
from marimo_studio._artifacts.inputs import project_revision
from marimo_studio._artifacts.limits import (
    ARTIFACT_OUTPUT_BUDGET,
    PROJECT_INPUT_BUDGET,
    FileBudget,
)
from marimo_studio._artifacts.paths import artifact_root
from marimo_studio._artifacts.repository import (
    read_artifact_revision,
    read_build_state,
    read_published_artifact,
)
from marimo_studio._artifacts.retention import lease_published_artifact
from marimo_studio._views.build import publish_view as publish_artifact_lease
from marimo_studio._views.inspection import inspection_request
from marimo_studio._workspace.project_manifest import load_view_project
from marimo_studio.errors import ConfigurationError, ViewProjectError
from marimo_studio.view_providers import (
    BuildProfile,
    BuildRequest,
    BuildResult,
    InspectionRequest,
    ProjectInput,
    ProjectInspection,
    ProviderAvailability,
    ProviderStarter,
    StarterContext,
    ViewProject,
)
from marimo_studio.view_providers._bundled.vanilla import provider as vanilla_provider
from marimo_studio.view_providers._host import provider_registry
from marimo_studio.view_providers._host.registry import (
    ProviderCandidate,
    ProviderRegistry,
)

from ..artifact_test_support import (
    add_provider_outputs as _add_provider_outputs,
)
from ..artifact_test_support import (
    change_document as _change_document,
)
from ..artifact_test_support import (
    manifest_path as _manifest_path,
)
from ..artifact_test_support import (
    profile_path as _profile_path,
)
from ..artifact_test_support import (
    project as _project,
)
from ..artifact_test_support import (
    publish_artifact,
)
from ..artifact_test_support import (
    read_json as _read_json,
)
from ..artifact_test_support import (
    write_json as _write_json,
)


class _EntryPoint:
    def __init__(self, provider: object) -> None:
        self.provider = provider
        self.module = provider.__class__.__module__

    def load(self) -> object:
        return self.provider


class _LeaseCloser:
    def __init__(
        self,
        name: str,
        calls: list[str],
        failure: BaseException | None = None,
    ) -> None:
        self.name = name
        self.calls = calls
        self.failure = failure
        self.closed = False

    def close(self) -> None:
        self.calls.append(self.name)
        self.closed = True
        if self.failure is not None:
            raise self.failure


class _ExternalVanillaProvider:
    def __init__(self) -> None:
        self.info = vanilla_provider.info

    def availability(self, project: ViewProject | None = None) -> ProviderAvailability:
        return vanilla_provider.availability(project)

    def starters(self) -> tuple[ProviderStarter, ...]:
        return ()

    def create(
        self,
        starter: ProviderStarter,
        context: StarterContext,
    ) -> dict[PurePosixPath, bytes]:
        raise ValueError((starter.key, context))

    def inspect(self, request: InspectionRequest) -> ProjectInspection:
        return vanilla_provider.inspect(request)

    def build(self, request: BuildRequest) -> BuildResult:
        return vanilla_provider.build(request)


def _external_registry() -> ProviderRegistry:
    provider = _ExternalVanillaProvider()
    return ProviderRegistry(
        (
            ProviderCandidate(
                registration="third-party-vanilla",
                distribution="third-party-studio",
                version="1.0.0",
                entry_point=cast(EntryPoint, _EntryPoint(provider)),
            ),
        )
    )


def _external_project(tmp_path: Path) -> ViewProject:
    project = _project(tmp_path)
    project.manifest.write_text(
        project.manifest.read_text(encoding="utf-8").replace(
            "marimo-studio/vanilla", "third-party-studio/third-party-vanilla"
        ),
        encoding="utf-8",
    )
    return load_view_project(project.root)


@pytest.mark.parametrize(
    ("budget", "message"),
    (
        (FileBudget(1, 1024 * 1024, 1024 * 1024), "Remove files"),
        (FileBudget(100, 1, 1024 * 1024), "Reduce the file size"),
        (FileBudget(100, 1024 * 1024, 1), "reduce their sizes"),
    ),
)
def test_project_input_budgets_fail_before_provider_build(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    budget: FileBudget,
    message: str,
) -> None:
    project = _project(tmp_path)
    provider = provider_registry().get(project.provider)
    monkeypatch.setattr(artifact_inputs, "PROJECT_INPUT_BUDGET", budget)
    monkeypatch.setattr(
        provider,
        "build",
        lambda _request: pytest.fail("input budgets must fail before provider build"),
    )

    with pytest.raises(ViewProjectError, match=message):
        publish_artifact_lease(project, "development")


def test_project_revision_rejects_a_sparse_input_before_reading_payloads(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _project(tmp_path)
    provider = provider_registry().get(project.provider)
    inspection = provider.inspect(inspection_request(project))
    oversized = project.root / "oversized.bin"
    with oversized.open("wb") as stream:
        stream.truncate(PROJECT_INPUT_BUDGET.max_file_bytes + 1)
    inspection = replace(
        inspection,
        input_scope=(ProjectInput(PurePosixPath("oversized.bin"), "file"),),
    )
    verified_secure_file = artifact_inputs.verified_secure_file

    @contextmanager
    def reject_payload_reads(
        root: Path,
        path: Path,
        label: str,
    ) -> Iterator[tuple[Any, os.stat_result]]:
        with verified_secure_file(root, path, label) as (_stream, state):

            class PayloadTrap:
                def read(self, _size: int = -1) -> bytes:
                    pytest.fail("Oversized input payload must not be read")

            yield cast(Any, PayloadTrap()), state

    monkeypatch.setattr(
        artifact_inputs,
        "verified_secure_file",
        reject_payload_reads,
    )

    with pytest.raises(ConfigurationError, match="Reduce the file size"):
        project_revision(project, inspection, provider.provenance(inspection))


def test_artifact_document_budget_is_checked_before_its_payload_is_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "artifact"
    root.mkdir()
    document = root / "index.html"
    with document.open("wb") as stream:
        stream.truncate(ARTIFACT_OUTPUT_BUDGET.max_file_bytes + 1)
    open_secure_file = artifact_paths_module.open_secure_file

    class PayloadTrap:
        def __init__(self, stream: Any) -> None:
            self.stream = stream

        def fileno(self) -> int:
            return self.stream.fileno()

        def read(self, _size: int = -1) -> bytes:
            pytest.fail("Oversized artifact document payload must not be read")

        def close(self) -> None:
            self.stream.close()

    monkeypatch.setattr(
        artifact_paths_module,
        "open_secure_file",
        lambda owner, path, label: PayloadTrap(open_secure_file(owner, path, label)),
    )

    with pytest.raises(ConfigurationError, match="limit"):
        artifact_repository.validate_document(root, PurePosixPath("index.html"))


@pytest.mark.parametrize(
    ("budget", "message"),
    (
        (FileBudget(1, 1024 * 1024, 1024 * 1024), "Remove files"),
        (FileBudget(100, 1, 1024 * 1024), "Reduce the file size"),
        (FileBudget(100, 1024 * 1024, 1), "reduce their sizes"),
    ),
)
def test_artifact_output_budgets_reject_provider_results(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    budget: FileBudget,
    message: str,
) -> None:
    project = _project(tmp_path)
    _add_provider_outputs(
        monkeypatch,
        project,
        {PurePosixPath("asset.txt"): b"asset"},
    )
    monkeypatch.setattr(
        artifact_paths_module,
        "ARTIFACT_OUTPUT_BUDGET",
        budget,
    )

    with pytest.raises(ViewProjectError, match=message):
        publish_artifact_lease(project, "development")


def test_profiles_share_one_content_only_artifact(tmp_path: Path) -> None:
    project = _project(tmp_path)

    development = publish_artifact(project, "development")
    production = publish_artifact(project, "production")

    assert development.artifact_revision == production.artifact_revision
    assert development.root == production.root
    assert development.profile == "development"
    assert production.profile == "production"
    manifest = _read_json(_manifest_path(development))
    assert set(manifest) == {
        "schema",
        "artifact_revision",
        "document",
        "files",
        "mounts",
    }
    development_state = _read_json(_profile_path(project))
    production_state = _read_json(_profile_path(project, "production"))
    assert development_state["published"]["provider"]["key"] == project.provider
    assert production_state["published"]["artifact_revision"] == (
        development.artifact_revision
    )


def test_artifact_manifest_orders_sibling_and_nested_paths_canonically(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _project(tmp_path)
    _add_provider_outputs(
        monkeypatch,
        project,
        {
            PurePosixPath("a.b"): b"sibling",
            PurePosixPath("a/b"): b"nested",
        },
    )

    with publish_artifact_lease(project, "development") as lease:
        paths = tuple(item.path.as_posix() for item in lease.artifact.files)

    assert paths.index("a.b") < paths.index("a/b")


def test_external_provider_receipt_round_trips_and_leases_prune(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _external_project(tmp_path)
    registry = _external_registry()
    monkeypatch.setattr(build_module, "provider_registry", lambda: registry)
    first_lease = publish_artifact_lease(project, "development")
    first = first_lease.artifact
    assert first.provider.key == project.provider
    receipt = _read_json(_profile_path(project))
    assert receipt["published"]["provider"]["distribution"] == "third-party-studio"
    assert receipt["published"]["provider"]["version"] == "1.0.0"

    monkeypatch.setattr(
        build_module,
        "provider_registry",
        lambda: pytest.fail("published reads must not load provider packages"),
    )
    retained_lease = lease_published_artifact(project, "development")
    assert retained_lease is not None
    assert retained_lease.artifact.provider == first.provider

    monkeypatch.setattr(build_module, "provider_registry", lambda: registry)
    _change_document(project, "external update")
    second_lease = publish_artifact_lease(project, "development")
    first_lease.close()
    assert first.root.parent.is_dir()
    retained_lease.close()
    assert not first.root.parent.exists()
    assert second_lease.artifact.root.parent.is_dir()
    second_lease.close()


def test_project_revision_canonically_includes_project_configuration(
    tmp_path: Path,
) -> None:
    project = _project(tmp_path)
    provider = provider_registry().get(project.provider)
    inspection = provider.inspect(inspection_request(project))
    provenance = provider.provenance(inspection)
    base = project_revision(project, inspection, provenance)
    reordered = replace(
        project,
        options={"theme": "dark", "entrypoint": "index.html"},
    )
    same_options = replace(
        project,
        options={"entrypoint": "index.html", "theme": "dark"},
    )

    assert project_revision(reordered, inspection, provenance) == project_revision(
        same_options, inspection, provenance
    )
    assert (
        project_revision(
            project,
            inspection,
            replace(provenance, version="next-version"),
        )
        != base
    )
    assert project_revision(reordered, inspection, provenance) != base


def test_unsupported_profile_is_rejected_before_artifact_mutation(
    tmp_path: Path,
) -> None:
    project = _project(tmp_path)

    with pytest.raises(ConfigurationError, match="build profile 'preview'"):
        publish_artifact(project, cast(BuildProfile, "preview"))

    assert not artifact_root(project).exists()


def test_live_manifest_is_revalidated_before_artifact_control_creation(
    tmp_path: Path,
) -> None:
    project = _project(tmp_path)
    project.manifest.unlink()

    with pytest.raises(ConfigurationError, match=r"view[.]toml"):
        publish_artifact_lease(project, "development")

    assert not artifact_root(project).exists()


@pytest.mark.parametrize(
    "field,value",
    (
        ("schema", True),
        ("schema", 2),
        ("artifact_revision", "sha256:" + "0" * 64),
    ),
)
def test_artifact_manifest_rejects_corrupt_identity_fields(
    tmp_path: Path,
    field: str,
    value: object,
) -> None:
    project = _project(tmp_path)
    artifact = publish_artifact(project, "development")
    manifest_path = _manifest_path(artifact)
    manifest = _read_json(manifest_path)
    manifest[field] = value
    _write_json(manifest_path, manifest)

    with pytest.raises(ConfigurationError):
        read_artifact_revision(project, artifact.artifact_revision)


def test_artifact_manifest_rejects_duplicate_json_fields(tmp_path: Path) -> None:
    project = _project(tmp_path)
    artifact = publish_artifact(project, "development")
    manifest_path = _manifest_path(artifact)
    source = manifest_path.read_text(encoding="utf-8")
    manifest_path.write_text(
        source.replace("{", '{"schema": 1,', 1),
        encoding="utf-8",
    )

    with pytest.raises(ConfigurationError, match="duplicate field"):
        read_artifact_revision(project, artifact.artifact_revision)


@pytest.mark.parametrize(
    ("mutate", "message"),
    (
        (
            lambda site: site.update(id="INVALID SPACE"),
            "artifact-local identifier",
        ),
        (
            lambda site: site["source"].update(line=0),
            "positive",
        ),
        (
            lambda site: site["source"].update(line=1 << 53),
            "browser-safe",
        ),
        (
            lambda site: site.update(allowedTargets=[]),
            "allowed targets",
        ),
        (
            lambda site: site.update(kind="value", allowedTargets=["report..total"]),
            "dot selection",
        ),
    ),
)
def test_persisted_mounts_use_canonical_validation(
    tmp_path: Path,
    mutate: Callable[[dict[str, Any]], None],
    message: str,
) -> None:
    project = _project(tmp_path)
    artifact = publish_artifact(project, "development")
    manifest_path = _manifest_path(artifact)
    manifest = _read_json(manifest_path)
    mutate(manifest["mounts"][0])
    _write_json(manifest_path, manifest)

    with pytest.raises(ConfigurationError, match=message):
        read_artifact_revision(project, artifact.artifact_revision)


@pytest.mark.parametrize("field", ("sha256", "size"))
def test_artifact_manifest_rejects_corrupt_file_metadata(
    tmp_path: Path,
    field: str,
) -> None:
    project = _project(tmp_path)
    artifact = publish_artifact(project, "development")
    manifest_path = _manifest_path(artifact)
    manifest = _read_json(manifest_path)
    manifest["files"][0][field] = "0" * 64 if field == "sha256" else 9_999
    _write_json(manifest_path, manifest)

    with pytest.raises(ConfigurationError):
        read_artifact_revision(project, artifact.artifact_revision)


def test_artifact_manifest_rejects_unsafe_file_paths(
    tmp_path: Path,
) -> None:
    project = _project(tmp_path)
    artifact = publish_artifact(project, "development")
    manifest_path = _manifest_path(artifact)
    manifest = _read_json(manifest_path)
    manifest["files"][0]["path"] = "../escape.js"
    _write_json(manifest_path, manifest)

    with pytest.raises(ConfigurationError, match="path"):
        read_artifact_revision(project, artifact.artifact_revision)


def test_artifact_read_rejects_missing_and_extra_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _project(tmp_path)
    _add_provider_outputs(
        monkeypatch,
        project,
        {PurePosixPath("asset.txt"): b"asset"},
    )
    artifact = publish_artifact(project, "development")
    missing = artifact.root / artifact.files[-1].path
    content = missing.read_bytes()
    missing.unlink()
    with pytest.raises(ConfigurationError, match="file tree"):
        read_artifact_revision(project, artifact.artifact_revision)

    missing.write_text("restored with different content", encoding="utf-8")
    with pytest.raises(ConfigurationError, match="file tree"):
        read_artifact_revision(project, artifact.artifact_revision)

    missing.write_bytes(content)
    (artifact.root / "extra.js").write_text("extra", encoding="utf-8")
    with pytest.raises(ConfigurationError, match="file tree"):
        read_artifact_revision(project, artifact.artifact_revision)

    (artifact.root / "extra.js").unlink()
    artifact.root.parent.joinpath("untracked.txt").write_text(
        "untracked revision data",
        encoding="utf-8",
    )
    with pytest.raises(ConfigurationError, match="untracked entries"):
        read_artifact_revision(project, artifact.artifact_revision)


@pytest.mark.parametrize(
    "mutate",
    (
        lambda state: state.update(schema=True),
        lambda state: state.update(schema=2),
        lambda state: state.update(extra="field"),
        lambda state: state["published"]["provider"].update(api_version=99),
        lambda state: state["published"]["provider"].update(
            build_fingerprint="invalid"
        ),
        lambda state: state["published"]["provider"].update(extra="field"),
        lambda state: state["published"].update(duration_ms=-1),
        lambda state: state["published"]["diagnostics"].append(
            {
                "code": "published-error",
                "severity": "error",
                "message": "Published evidence cannot contain errors.",
                "hint": "",
                "source": None,
            }
        ),
    ),
)
def test_profile_receipt_rejects_corrupt_publication_evidence(
    tmp_path: Path,
    mutate: Any,
) -> None:
    project = _project(tmp_path)
    publish_artifact(project, "development")
    pointer = _profile_path(project)
    state = _read_json(pointer)
    mutate(state)
    _write_json(pointer, state)

    with pytest.raises(ConfigurationError):
        read_published_artifact(project, "development")


@pytest.mark.parametrize(
    ("mutate", "message"),
    (
        (lambda item: item.update(code="Invalid Code"), "kebab"),
        (lambda item: item.update(severity="fatal"), "severity"),
        (lambda item: item.update(message=""), "message"),
        (lambda item: item.update(hint=" padded "), "hint"),
    ),
)
def test_persisted_build_diagnostics_use_canonical_validation(
    tmp_path: Path,
    mutate: Callable[[dict[str, Any]], None],
    message: str,
) -> None:
    project = _project(tmp_path)
    publish_artifact(project, "development")
    pointer = _profile_path(project)
    state = _read_json(pointer)
    diagnostic = {
        "code": "build-warning",
        "severity": "warning",
        "message": "Build warning",
        "hint": "",
        "source": None,
    }
    mutate(diagnostic)
    state["build"]["diagnostics"] = [diagnostic]
    _write_json(pointer, state)

    with pytest.raises(ConfigurationError, match=message):
        read_build_state(project, "development")
