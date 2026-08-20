from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest
from marimo._server.session_manager import SessionManager

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

import marimo_studio._compat.layout as layout_module
import marimo_studio._composition as composition_module
import marimo_studio._delivery.assets as assets_module
import marimo_studio._validation.static as checks_module
from marimo_studio._compat.notebook import load_static_notebook
from marimo_studio._compat.patch import ReversiblePatch
from marimo_studio._compat.runtime_probe import probe_runtime_in_worker
from marimo_studio._composition import create_browser_runtime_projector
from marimo_studio._validation.static import check_studio
from marimo_studio._views.api import prepare_view
from marimo_studio._workspace import load_studio
from marimo_studio.errors._internal import CompatibilityError

from ..helpers import empty_notebook_source

pytestmark = pytest.mark.supported_python


def test_pinned_release_matches_the_private_symbols() -> None:
    layout_module.clear_release_cache()

    version = layout_module.assert_pinned_release()

    assert version == layout_module.MARIMO_VERSION


def test_python_projects_pin_the_supported_marimo_release() -> None:
    root = Path(__file__).parents[4]
    with (root / "pyproject.toml").open("rb") as stream:
        workspace = tomllib.load(stream)
    with (root / "packages/marimo-studio/pyproject.toml").open("rb") as stream:
        package = tomllib.load(stream)

    version = layout_module.MARIMO_VERSION
    assert f"marimo[recommended]=={version}" in workspace["dependency-groups"]["dev"]
    assert f"marimo=={version}" in package["project"]["dependencies"]


def test_same_version_source_drift_fails_with_the_observed_fingerprint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def changed(self: object, file_key: object) -> None:
        del self, file_key

    monkeypatch.setattr(SessionManager, "get_session_by_file_key", changed)
    layout_module.clear_release_cache()

    with pytest.raises(CompatibilityError) as raised:
        layout_module.assert_pinned_release()

    message = str(raised.value)
    assert "server-context" in message
    assert "get_session_by_file_key" in message
    assert "fingerprint" in message
    assert layout_module.MARIMO_VERSION in message


def test_private_signature_drift_fails_before_adapter_construction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def changed(self: object) -> None:
        del self

    monkeypatch.setattr(SessionManager, "get_session", changed)
    layout_module.clear_release_cache()

    with pytest.raises(CompatibilityError, match="parameters"):
        layout_module.assert_pinned_release()


def test_kernel_root_validates_the_release_before_construction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    constructed = False

    def construct(_: None) -> object:
        nonlocal constructed
        constructed = True
        return object()

    layout_module.clear_release_cache()
    monkeypatch.setattr(layout_module, "version", lambda _name: "0.23.15")
    monkeypatch.setattr(composition_module, "_construct_kernel_lifespan", construct)

    with pytest.raises(CompatibilityError, match="installed version"):
        composition_module.kernel_lifespan(None)
    assert constructed is False
    layout_module.clear_release_cache()


@pytest.mark.parametrize("field", ["version", "commit", "patchSha256"])
def test_browser_projector_rejects_release_drift(
    monkeypatch: pytest.MonkeyPatch,
    field: str,
) -> None:
    observed = {
        "version": layout_module.MARIMO_VERSION,
        "commit": layout_module.MARIMO_RELEASE_COMMIT,
        "patchSha256": layout_module.MARIMO_FRONTEND_PATCH_SHA256,
    }
    observed[field] = "different"
    monkeypatch.setattr(
        assets_module,
        "_runtime_marimo_metadata",
        lambda: observed,
    )

    with pytest.raises(CompatibilityError, match="browser runtime"):
        create_browser_runtime_projector()


def test_browser_projector_owns_runtime_data_and_instance_identity(
    notebook_path: Path,
) -> None:
    projector = create_browser_runtime_projector()
    source = empty_notebook_source()
    first = projector.project(
        notebook_path,
        source,
    )
    repeated = projector.project(
        notebook_path,
        source,
    )
    source_changed = projector.project(
        notebook_path,
        source + "# source revision\n",
    )

    assert first.runtime_data() == {
        "code": first.code,
        "filename": "notebook.py",
        "version": layout_module.MARIMO_VERSION,
        "executionCells": [cell.to_dict() for cell in first.execution_cells],
        "bootstrapCellId": first.bootstrap_cell_id,
    }
    assert len(first.execution_cells) == 1
    assert first.execution_cells[0].runtime_id == first.bootstrap_cell_id
    assert first.commit == layout_module.MARIMO_RELEASE_COMMIT
    assert repeated.instance == first.instance
    assert source_changed.instance != first.instance


def test_browser_execution_catalog_preserves_saved_notebook_cells(
    notebook_path: Path,
) -> None:
    projection = create_browser_runtime_projector().project(
        notebook_path,
        notebook_path.read_text(encoding="utf-8"),
    )
    static = load_static_notebook(notebook_path)
    catalog = {cell.runtime_id: cell.code for cell in projection.execution_cells}

    assert {
        cell.runtime_id: cell.code for cell in static.cells
    }.items() <= catalog.items()
    assert projection.bootstrap_cell_id not in {
        cell.runtime_id for cell in static.cells
    }
    assert "_studio_projection_bridge_ready" in catalog[projection.bootstrap_cell_id]


def test_browser_projection_bootstrap_executes_in_the_native_kernel(
    notebook_path: Path,
    tmp_path: Path,
) -> None:
    projection = create_browser_runtime_projector().project(
        notebook_path,
        empty_notebook_source(),
    )
    projected = tmp_path / "projected.py"
    projected.write_text(projection.code, encoding="utf-8")

    runtime = asyncio.run(
        probe_runtime_in_worker(
            projected,
            cell_ids=(projection.bootstrap_cell_id,),
            variables=(),
            timeout=10,
            show_tracebacks=True,
        )
    )

    bootstrap = runtime.cells[projection.bootstrap_cell_id]
    assert bootstrap.status == "idle"
    assert bootstrap.errors == ()


def test_check_reports_the_validated_release_identity(notebook_path: Path) -> None:
    prepare_view(notebook_path)

    result = next(
        item
        for item in check_studio(load_studio(notebook_path)).checks
        if item.name == "compatibility"
    )

    assert result.status == "pass"
    assert result.details is not None
    assert result.details["validation"] == "pass"
    assert result.details["adapterFamily"] == "private"
    expected = {
        "version": layout_module.MARIMO_VERSION,
        "commit": layout_module.MARIMO_RELEASE_COMMIT,
    }
    assert result.details["requiredRelease"] == expected
    assert result.details["marimo"] == expected
    assert result.details["browser"] == expected


def test_check_reports_the_required_release_when_validation_fails(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepare_view(notebook_path)

    def fail_validation() -> object:
        raise CompatibilityError("release mismatch")

    monkeypatch.setattr(
        checks_module,
        "create_browser_runtime_projector",
        fail_validation,
    )

    result = check_studio(load_studio(notebook_path)).checks[0]

    assert result.status == "fail"
    assert result.details is not None
    assert result.details["validation"] == "fail"
    assert result.details["requiredRelease"] == {
        "version": layout_module.MARIMO_VERSION,
        "commit": layout_module.MARIMO_RELEASE_COMMIT,
    }
    assert result.details["marimo"] is None
    assert result.details["browser"] is None
    assert result.details["adapterFamily"] == "private"


def test_reversible_patch_rejects_a_conflict_and_retries_close() -> None:
    class Target:
        @staticmethod
        def method() -> str:
            return "native"

    original = Target.method
    patch = ReversiblePatch(
        "test-capability",
        Target,
        "method",
        lambda native: lambda: f"studio:{native()}",
    )
    handle = patch.open()
    replacement = Target.method
    type.__setattr__(Target, "method", staticmethod(lambda: "foreign"))

    with pytest.raises(CompatibilityError, match="before Studio could restore"):
        handle.close()

    Target.method = replacement
    handle.close()
    assert Target.method is original


def test_adapter_setup_preserves_rollback_failure_as_its_cause() -> None:
    setup_error = RuntimeError("adapter setup failed")
    cleanup_error = RuntimeError("adapter cleanup failed")

    class Handle:
        def close(self) -> None:
            raise cleanup_error

    class FirstInstaller:
        def open(self) -> Handle:
            return Handle()

    class FailingInstaller:
        def open(self) -> Handle:
            raise setup_error

    lifecycle = composition_module._PrivateAdapterLifecycle(
        (FirstInstaller(), FailingInstaller())
    )

    with pytest.raises(RuntimeError, match="adapter setup failed") as raised:
        lifecycle.open()

    assert raised.value is setup_error
    assert raised.value.__cause__ is cleanup_error
