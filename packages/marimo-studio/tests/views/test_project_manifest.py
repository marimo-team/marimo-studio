"""Protect the durable view manifest grammar."""

import os
from pathlib import Path

import pytest

import marimo_studio._workspace.project_manifest as manifest_module
from marimo_studio._views.inspection import inspection_request
from marimo_studio._workspace.project_manifest import load_view_project
from marimo_studio.errors import ConfigurationError


def _manifest(tmp_path: Path, source: str) -> Path:
    root = tmp_path / "dashboard"
    root.mkdir()
    (root / "view.toml").write_text(source, encoding="utf-8")
    return root


def test_manifest_load_preserves_an_unavailable_provider_identity(
    tmp_path: Path,
) -> None:
    root = _manifest(
        tmp_path,
        """schema = 1
provider = "third-party/missing"

[options]
framework_option = "preserved"
""",
    )

    project = load_view_project(root)

    assert project.provider == "third-party/missing"
    assert project.options == {"framework_option": "preserved"}


@pytest.mark.skipif(
    os.name == "nt", reason="symlink creation needs elevated Windows access"
)
def test_manifest_load_keeps_lexical_identity_after_a_root_swap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _manifest(
        tmp_path,
        'schema = 1\nprovider = "marimo-studio/vanilla"\n',
    )
    retired = root.with_name("dashboard-retired")
    external = tmp_path / "external"
    external.mkdir()
    read_toml = manifest_module.read_toml

    def read_then_swap(path: Path) -> dict[str, object]:
        data = read_toml(path)
        root.rename(retired)
        root.symlink_to(external, target_is_directory=True)
        return data

    monkeypatch.setattr(manifest_module, "read_toml", read_then_swap)

    project = load_view_project(root)
    request = inspection_request(project)

    assert project.root == root.absolute()
    assert project.manifest == (root / "view.toml").absolute()
    assert root.absolute() not in request.cache_root.parents
    assert not (external / ".artifacts").exists()


def test_manifest_preserves_nested_json_options(tmp_path: Path) -> None:
    root = _manifest(
        tmp_path,
        """schema = 1
provider = "third-party/json"

[options]
settings = [true, 7, 1.25, "label"]

[options.nested]
enabled = false
thresholds = [0, 0.5]
""",
    )

    assert load_view_project(root).options == {
        "settings": [True, 7, 1.25, "label"],
        "nested": {"enabled": False, "thresholds": [0, 0.5]},
    }


@pytest.mark.parametrize(
    ("source", "message"),
    (
        ('schema = true\nprovider = "third-party/json"\n', "schema must be 1"),
        ("schema = 1\nprovider = 42\n", "provider must be a non-empty string"),
        (
            """schema = 1
provider = "third-party/json"
[options]
settings = [1.0, nan]
""",
            "finite",
        ),
    ),
)
def test_manifest_rejects_invalid_shapes(
    tmp_path: Path,
    source: str,
    message: str,
) -> None:
    root = _manifest(tmp_path, source)

    with pytest.raises(ConfigurationError, match=message):
        load_view_project(root)
