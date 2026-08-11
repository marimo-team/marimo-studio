from __future__ import annotations

import sys
from pathlib import Path

import pytest
from marimo._server.session_manager import SessionManager

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

import marimo_studio._assets as assets_module
import marimo_studio._compat.layout as layout_module
import marimo_studio._composition as composition_module
import marimo_studio.checks as checks_module
from marimo_studio._compat.patch import ReversiblePatch
from marimo_studio._composition import create_browser_runtime_projector
from marimo_studio._workspace import load_studio
from marimo_studio.checks import check_studio
from marimo_studio.errors import CompatibilityError
from marimo_studio.values import parse_value_reference
from marimo_studio.workspace import ensure_view

from .helpers import empty_notebook_source


def test_pinned_release_matches_the_private_symbols() -> None:
    layout_module.clear_release_cache()

    version = layout_module.assert_pinned_release()

    assert version == layout_module.MARIMO_VERSION


def test_python_projects_pin_the_supported_marimo_release() -> None:
    root = Path(__file__).parents[3]
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


@pytest.mark.parametrize("field", ["version", "commit"])
def test_browser_projector_rejects_release_drift(
    monkeypatch: pytest.MonkeyPatch,
    field: str,
) -> None:
    observed = {
        "version": layout_module.MARIMO_VERSION,
        "commit": layout_module.MARIMO_RELEASE_COMMIT,
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
        values={"value": parse_value_reference("value")},
        outputs={},
    )
    selectors_changed = projector.project(
        notebook_path,
        source,
        values={},
        outputs={"output": parse_value_reference("output")},
    )
    source_changed = projector.project(
        notebook_path,
        source + "# source revision\n",
        values={},
        outputs={},
    )

    assert first.runtime_data() == {
        "code": first.code,
        "filename": "notebook.py",
        "version": layout_module.MARIMO_VERSION,
        "valueSpecs": {"value": ("value", ())},
        "outputSpecs": {},
    }
    assert first.commit == layout_module.MARIMO_RELEASE_COMMIT
    assert selectors_changed.instance == first.instance
    assert source_changed.instance != first.instance


def test_check_reports_the_validated_release_identity(notebook_path: Path) -> None:
    ensure_view(notebook_path)

    result = next(
        item
        for item in check_studio(load_studio(notebook_path))
        if item.name == "compatibility"
    )

    assert result.status == "pass"
    assert result.details is not None
    assert set(result.details) == {
        "validation",
        "studio",
        "requiredRelease",
        "marimo",
        "browser",
        "adapterFamily",
    }
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
    ensure_view(notebook_path)

    def fail_validation() -> object:
        raise CompatibilityError("release mismatch")

    monkeypatch.setattr(
        checks_module,
        "create_browser_runtime_projector",
        fail_validation,
    )

    result = check_studio(load_studio(notebook_path))[0]

    assert result.status == "fail"
    assert result.details is not None
    assert set(result.details) == {
        "validation",
        "studio",
        "requiredRelease",
        "marimo",
        "browser",
        "adapterFamily",
    }
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
