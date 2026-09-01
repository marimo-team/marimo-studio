from __future__ import annotations

from collections.abc import MutableMapping
from pathlib import Path

import pytest

from marimo_studio._views.api import prepare_view
from marimo_studio._workspace import load_studio
from marimo_studio._workspace.config import load_studio_definition
from marimo_studio._workspace.metadata import (
    update_notebook_config,
)
from marimo_studio.errors import ConfigurationError


def test_notebooks_with_the_same_parent_have_independent_presentations(
    notebook_path: Path,
) -> None:
    second = notebook_path.with_name("forecast.py")
    second.write_text(notebook_path.read_text(encoding="utf-8"), encoding="utf-8")

    prepare_view(notebook_path, "dashboard")
    prepare_view(second, "forecast")

    first_studio = load_studio(notebook_path)
    second_studio = load_studio(second)
    assert first_studio.view_root != second_studio.view_root
    assert set(first_studio.views) == {"dashboard"}
    assert set(second_studio.views) == {"forecast"}


def test_directory_discovery_requires_an_explicit_notebook_on_conflict(
    notebook_path: Path,
) -> None:
    inline = notebook_path.with_name("inline.py")
    inline.write_text(notebook_path.read_text(encoding="utf-8"), encoding="utf-8")
    prepare_view(inline)
    (notebook_path.parent / "pyproject.toml").write_text(
        f"""\
[tool.marimo-studio]
notebook = "{notebook_path.name}"
default = "dashboard"
""",
        encoding="utf-8",
    )

    with pytest.raises(ConfigurationError, match="Pass a notebook path"):
        load_studio_definition(notebook_path.parent)

    assert load_studio_definition(inline).notebook == inline


def test_one_notebook_cannot_use_inline_and_project_configuration(
    notebook_path: Path,
) -> None:
    prepare_view(notebook_path)
    pyproject = notebook_path.parent / "pyproject.toml"
    pyproject.write_text(
        f'''\
[tool.marimo-studio]
notebook = "{notebook_path.name}"
default = "dashboard"
''',
        encoding="utf-8",
    )

    for target in (notebook_path, pyproject, notebook_path.parent):
        with pytest.raises(ConfigurationError, match="Keep one configuration source"):
            load_studio_definition(target)


def test_notebook_configuration_controls_presentation_options(
    notebook_path: Path,
) -> None:
    prepare_view(notebook_path)

    def configure(config: MutableMapping[str, object]) -> None:
        config["preserve_session"] = True
        config["show_cell_logs"] = False
        config["runtime"] = "wasm"
        config["runtimes"] = ["server", "wasm"]

    update_notebook_config(notebook_path, configure)
    studio = load_studio(notebook_path)
    assert studio.preserve_session is True
    assert studio.show_cell_logs is False
    assert studio.default_runtime == "wasm"
    assert studio.runtimes == ("server", "wasm")

    def invalidate_session(config: MutableMapping[str, object]) -> None:
        config["preserve_session"] = "yes"

    update_notebook_config(notebook_path, invalidate_session)
    with pytest.raises(ConfigurationError, match="preserve_session must be a boolean"):
        load_studio(notebook_path)

    def invalidate_logs(config: MutableMapping[str, object]) -> None:
        config["preserve_session"] = True
        config["show_cell_logs"] = "no"

    update_notebook_config(notebook_path, invalidate_logs)
    with pytest.raises(ConfigurationError, match="show_cell_logs must be a boolean"):
        load_studio(notebook_path)

    def remove_default(config: MutableMapping[str, object]) -> None:
        config["show_cell_logs"] = False
        config["runtimes"] = ["server"]

    update_notebook_config(notebook_path, remove_default)
    with pytest.raises(ConfigurationError, match="runtime must be present"):
        load_studio(notebook_path)


def test_notebook_configuration_rejects_unknown_fields(
    notebook_path: Path,
) -> None:
    prepare_view(notebook_path)

    def add_unknown(config: MutableMapping[str, object]) -> None:
        config["runtim"] = "server"

    update_notebook_config(notebook_path, add_unknown)

    with pytest.raises(ConfigurationError, match=r"Unsupported.*runtim"):
        load_studio_definition(notebook_path)


def test_project_configuration_rejects_unknown_fields(
    notebook_path: Path,
) -> None:
    pyproject = notebook_path.parent / "pyproject.toml"
    pyproject.write_text(
        f'''\
[tool.marimo-studio]
default = "dashboard"
notebok = "{notebook_path.name}"
''',
        encoding="utf-8",
    )

    with pytest.raises(ConfigurationError, match=r"Unsupported.*notebok"):
        load_studio_definition(pyproject)


def test_cell_bindings_reject_unknown_fields(notebook_path: Path) -> None:
    prepare_view(notebook_path)

    def add_unknown(config: MutableMapping[str, object]) -> None:
        cells = config["cells"]
        assert isinstance(cells, MutableMapping)
        binding = cells["cell-2"]
        assert isinstance(binding, MutableMapping)
        binding["source"] = "stale"

    update_notebook_config(notebook_path, add_unknown)

    with pytest.raises(ConfigurationError, match="Unsupported field 'source'"):
        load_studio_definition(notebook_path)


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("runtime", "browser"),
        ("runtimes", ["server", "browser"]),
    ),
)
def test_configuration_rejects_unsupported_runtime_ids(
    notebook_path: Path,
    field: str,
    value: object,
) -> None:
    prepare_view(notebook_path)

    def configure(config: MutableMapping[str, object]) -> None:
        config[field] = value

    update_notebook_config(notebook_path, configure)

    with pytest.raises(ConfigurationError, match="server, wasm"):
        load_studio_definition(notebook_path)


def test_project_configuration_requires_an_owned_notebook(
    notebook_path: Path,
) -> None:
    project = notebook_path.parent / "project"
    project.mkdir()
    pyproject = project / "pyproject.toml"
    pyproject.write_text(
        f"""\
[tool.marimo-studio]
notebook = "../{notebook_path.name}"
default = "dashboard"
""",
        encoding="utf-8",
    )
    with pytest.raises(ConfigurationError, match="inside the project directory"):
        load_studio_definition(pyproject)
