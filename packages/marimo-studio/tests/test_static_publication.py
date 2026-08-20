from __future__ import annotations

import json
from pathlib import Path

import pytest
from marimo_export import ExportSpec
from marimo_export.errors import ExecutionError

import marimo_studio._static_delivery as static_delivery_module
from marimo_studio._server.presentation import NotebookPresentation
from marimo_studio._server.studio.view_compiler import compile_export_view
from marimo_studio.export import export_view

from .helpers import configured_export_view


@pytest.fixture(autouse=True)
def isolated_export_repository(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Path:
    repository = tmp_path / "export-repository"
    monkeypatch.setenv("MARIMO_EXPORT_REPOSITORY", str(repository))
    return repository


def test_static_publication_cold_prepare_runs_notebook(
    notebook_path: Path,
    tmp_path: Path,
) -> None:
    configured_export_view(notebook_path)
    marker = tmp_path / "cell-executed"

    publication = static_delivery_module.publication_source().resolve(
        NotebookPresentation(notebook_path).snapshot("dashboard")
    )

    try:
        assert publication.owner is publication.prepared
        assert marker.read_text(encoding="utf-8") == "executed"
        assert publication.prepared.reused is False
        assert publication.prepared.prepared_states
        assert len(publication.prepared.plan.states) == 1
        assert publication.prepared.plan.states[0].aliases == ("baseline",)
        assert publication.path.joinpath("index.json").is_file()
        manifest = publication.manifest("./prepared/")
        prepared_manifest = manifest["prepared"]
        assert isinstance(prepared_manifest, dict)
        assert manifest["schema"] == "marimo-studio.prepared.v1"
        assert prepared_manifest["schema"] == "marimo-export.prepared.v1"
        assert prepared_manifest["export_url"] == "./prepared/"
        assert prepared_manifest["refresh_interval_ms"] == 0
        assert manifest["document_sha256"] == publication.document_sha256
    finally:
        publication.owner.close()


def test_static_publication_exact_reuse_starts_no_notebook_process(
    notebook_path: Path,
    tmp_path: Path,
) -> None:
    configured_export_view(notebook_path)
    marker = tmp_path / "cell-executed"
    snapshot = NotebookPresentation(notebook_path).snapshot("dashboard")
    first = static_delivery_module.publication_source().resolve(snapshot)
    first_identity = first.instance
    first.owner.close()
    marker.unlink()

    second = static_delivery_module.publication_source().resolve(snapshot)

    try:
        assert second.instance == first_identity
        assert second.prepared.reused is True
        assert second.prepared.prepared_states == ()
        assert not marker.exists()
    finally:
        second.owner.close()


def test_css_change_reuses_prepared_export_without_notebook_process(
    notebook_path: Path,
    tmp_path: Path,
) -> None:
    view_root = configured_export_view(notebook_path)
    marker = tmp_path / "cell-executed"
    output = tmp_path / "site"
    export_view(notebook_path, output)
    first_manifest = json.loads(
        output.joinpath("_marimo-studio/views/dashboard/zero-python/current").read_text(
            encoding="utf-8"
        )
    )
    marker.unlink()
    style = view_root / "app.css"
    style.write_text(
        style.read_text(encoding="utf-8") + "\n.dashboard { padding: 1rem; }\n",
        encoding="utf-8",
    )

    export_view(notebook_path, output, force=True)

    second_manifest = json.loads(
        output.joinpath("_marimo-studio/views/dashboard/zero-python/current").read_text(
            encoding="utf-8"
        )
    )
    assert not marker.exists()
    assert (
        second_manifest["prepared"]["instance"]
        == first_manifest["prepared"]["instance"]
    )


def test_notebook_source_change_reprepares_for_the_new_producer(
    notebook_path: Path,
    tmp_path: Path,
) -> None:
    configured_export_view(notebook_path)
    marker = tmp_path / "cell-executed"
    first = static_delivery_module.publication_source().resolve(
        NotebookPresentation(notebook_path).snapshot("dashboard")
    )
    first_producer = first.prepared.plan.producer_sha256
    first.owner.close()
    marker.unlink()
    notebook_path.write_text(
        notebook_path.read_text(encoding="utf-8") + "\n# source revision\n",
        encoding="utf-8",
    )

    second = static_delivery_module.publication_source().resolve(
        NotebookPresentation(notebook_path).snapshot("dashboard")
    )

    try:
        assert marker.read_text(encoding="utf-8") == "executed"
        assert second.prepared.reused is False
        assert second.prepared.plan.producer_sha256 != first_producer
    finally:
        second.owner.close()


def test_static_and_preview_compile_the_saved_export_spec_identically(
    notebook_path: Path,
) -> None:
    view_root = configured_export_view(notebook_path)
    snapshot = NotebookPresentation(notebook_path).snapshot("dashboard")
    baseline = compile_export_view(snapshot)
    saved = baseline.spec.to_value()
    saved["default_state"] = "saved"
    saved["states"] = {"saved": {}}
    view_root.joinpath("export.yaml").write_text(
        json.dumps(saved),
        encoding="utf-8",
    )

    compiled = static_delivery_module._compiled_export_view(snapshot)

    assert compiled.spec.to_value() == saved
    assert compiled.bindings == baseline.bindings


def test_static_compiler_uses_one_baseline_without_repository_observations(
    notebook_path: Path,
) -> None:
    configured_export_view(notebook_path)
    snapshot = NotebookPresentation(notebook_path).snapshot("dashboard")

    compiled = static_delivery_module._compiled_export_view(snapshot)

    assert compiled.spec.default_state == "baseline"
    assert dict(compiled.spec.states) == {"baseline": {}}


def test_static_protection_resolves_the_repository_path_without_opening_it(
    notebook_path: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = tmp_path / "repository"
    monkeypatch.setattr(
        static_delivery_module.ExportRepository,
        "default_path",
        lambda: repository,
    )
    monkeypatch.setattr(
        static_delivery_module.ExportRepository,
        "open",
        lambda: pytest.fail("path resolution must not open the repository"),
    )

    assert (
        static_delivery_module.publication_source().protected_root(notebook_path)
        == repository
    )


def test_static_publication_failure_uses_implicit_repository_ownership(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configured_export_view(notebook_path)
    snapshot = NotebookPresentation(notebook_path).snapshot("dashboard")
    captured: dict[str, object] = {}

    def fail_prepare(*_args: object, **kwargs: object):
        captured["spec"] = kwargs["spec"]
        captured["repository_supplied"] = "repository" in kwargs
        raise ExecutionError("notebook failed")

    monkeypatch.setattr(static_delivery_module, "prepare", fail_prepare)

    with pytest.raises(RuntimeError, match="notebook failed"):
        static_delivery_module.publication_source().resolve(snapshot)

    assert captured["repository_supplied"] is False
    spec = captured["spec"]
    assert isinstance(spec, ExportSpec)
    assert spec.default_state == "baseline"
    assert dict(spec.states) == {"baseline": {}}


def test_static_publication_preserves_verification_failure_when_close_fails(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configured_export_view(notebook_path)
    snapshot = NotebookPresentation(notebook_path).snapshot("dashboard")

    class Prepared:
        def open(self):
            return self

        def verify(self) -> None:
            raise ExecutionError("verification failed")

        def close(self) -> None:
            raise RuntimeError("close failed")

    monkeypatch.setattr(
        static_delivery_module,
        "prepare",
        lambda *_args, **_kwargs: Prepared(),
    )

    with pytest.raises(RuntimeError, match="verification failed") as raised:
        static_delivery_module.publication_source().resolve(snapshot)

    assert isinstance(raised.value.__cause__, ExecutionError)
    assert isinstance(raised.value.__cause__.__cause__, RuntimeError)
    assert str(raised.value.__cause__.__cause__) == "close failed"


def test_static_publication_passes_timeout_to_prepare(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configured_export_view(notebook_path)
    snapshot = NotebookPresentation(notebook_path).snapshot("dashboard")
    captured: dict[str, object] = {}

    def fail_prepare(*_args: object, **kwargs: object):
        captured["timeout"] = kwargs["timeout"]
        captured["repository_supplied"] = "repository" in kwargs
        raise ExecutionError("stop after timeout capture")

    monkeypatch.setattr(static_delivery_module, "prepare", fail_prepare)

    with pytest.raises(RuntimeError, match="stop after timeout capture"):
        static_delivery_module.publication_source().resolve(snapshot, timeout=75.0)

    assert captured["timeout"] == 75.0
    assert captured["repository_supplied"] is False
