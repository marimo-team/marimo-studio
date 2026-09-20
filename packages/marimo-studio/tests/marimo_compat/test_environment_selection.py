from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from importlib.metadata import version
from itertools import pairwise
from pathlib import Path

import pytest
from packaging.requirements import Requirement

import marimo_studio._cli.environment as environment_module
from marimo_studio._cli.environment import (
    environment_command,
    provider_bootstrap_required,
)
from marimo_studio._compat.browser_notebook import browser_notebook_source
from marimo_studio._workspace.metadata import read_notebook_metadata
from marimo_studio.errors import ConfigurationError


@dataclass(frozen=True)
class _Target:
    root: Path
    notebook: Path


@pytest.mark.parametrize("fixture", ("lazy.py", "notebook.py"))
def test_main_e2e_fixtures_bootstrap_their_saved_external_provider(
    tmp_path: Path,
    fixture: str,
) -> None:
    repository = Path(__file__).resolve().parents[4]
    source_notebook = repository / "apps" / "e2e" / "fixtures" / fixture
    source_metadata = read_notebook_metadata(source_notebook)
    assert source_metadata is not None
    source_path = source_metadata["tool"]["uv"]["sources"][
        "marimo-studio-e2e-provider"
    ]["path"]
    assert isinstance(source_path, str)
    source_provider = (
        repository / "apps" / "e2e" / "fixtures-provider" / "provider"
    ).resolve()
    assert (source_notebook.parent / source_path).resolve() == source_provider
    workspace = tmp_path / "workspace"
    shutil.copytree(repository / "apps" / "e2e" / "fixtures", workspace)
    expected = workspace.parent / "fixtures-provider" / "provider"
    shutil.copytree(
        repository / "apps" / "e2e" / "fixtures-provider" / "provider",
        expected,
    )
    notebook = workspace / fixture
    metadata = read_notebook_metadata(notebook)
    assert metadata is not None
    dependencies = metadata.get("dependencies")
    assert isinstance(dependencies, list)
    external = [
        Requirement(value)
        for value in dependencies
        if isinstance(value, str)
        and Requirement(value).name == "marimo-studio-e2e-provider"
    ]

    assert len(external) == 1
    assert str(external[0].specifier) == "==1.0.0"
    config = metadata["tool"]["marimo-studio"]
    assert list(config["provider_dependencies"]) == [
        "marimo-studio-e2e-provider==1.0.0"
    ]
    target = _Target(notebook.parent, notebook)
    assert provider_bootstrap_required(target)
    command = environment_command(target, ["python", "-V"])
    requirements = [value for flag, value in pairwise(command) if flag == "--with"]
    prepared = [Requirement(value) for value in requirements]
    provider = next(
        requirement
        for requirement in prepared
        if requirement.name == "marimo-studio-e2e-provider"
    )
    assert provider.url in {str(expected.resolve()), expected.resolve().as_uri()}
    configured_source = metadata["tool"]["uv"]["sources"]["marimo-studio-e2e-provider"][
        "path"
    ]
    assert isinstance(configured_source, str)
    assert (notebook.parent / configured_source).resolve() == expected.resolve()
    browser_notebook = tmp_path / fixture
    browser_notebook.write_text(
        browser_notebook_source(notebook, notebook.read_text(encoding="utf-8")),
        encoding="utf-8",
    )
    browser_metadata = read_notebook_metadata(browser_notebook)
    assert browser_metadata is not None
    assert "marimo-studio-e2e-provider" not in {
        Requirement(value).name
        for value in browser_metadata.get("dependencies", ())
        if isinstance(value, str)
    }


@pytest.mark.parametrize(
    (
        "project_requirement",
        "source_declaration",
        "expected_requirement",
        "uses_source_checkout",
    ),
    (
        (
            "marimo-studio>=0",
            "",
            f"marimo-studio=={version('marimo-studio')}",
            True,
        ),
        (
            f"marimo-studio=={version('marimo-studio')}",
            "",
            f"marimo-studio=={version('marimo-studio')}",
            True,
        ),
        (
            "marimo-studio==999.0.0",
            "",
            "marimo-studio==999.0.0",
            False,
        ),
        (
            "marimo-studio>=0",
            """
[tool.uv.sources]
marimo-studio = { path = "./declared-studio" }
""",
            "marimo-studio>=0",
            False,
        ),
    ),
)
def test_project_requirement_selects_the_studio_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    project_requirement: str,
    source_declaration: str,
    expected_requirement: str,
    uses_source_checkout: bool,
) -> None:
    notebook = tmp_path / "analysis.py"
    notebook.write_text("import marimo\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        f"""\
[project]
name = "analysis"
version = "0.0.1"
dependencies = ["{project_requirement}"]
{source_declaration}
""",
        encoding="utf-8",
    )
    source_root = tmp_path / "invoking-studio"
    source_root.mkdir()
    captured: dict[str, object] = {}

    def inline_flags(
        _notebook: Path,
        launch_requirements: tuple[str, ...],
        *,
        compose_project: bool,
        marker_environment: object,
    ) -> list[str]:
        captured["launch_requirements"] = launch_requirements
        captured["compose_project"] = compose_project
        return []

    monkeypatch.setattr(environment_module.shutil, "which", lambda _: "/usr/bin/uv")
    monkeypatch.setattr(
        environment_module,
        "package_source_root",
        lambda: source_root,
    )
    monkeypatch.setattr(
        environment_module,
        "create_environment_flag_builder",
        lambda: inline_flags,
    )

    command = environment_command(_Target(tmp_path, notebook), ["python", "-V"])

    assert captured == {
        "launch_requirements": (expected_requirement,),
        "compose_project": True,
    }
    if uses_source_checkout:
        assert command[command.index("--with-editable") + 1] == str(source_root)
    else:
        assert "--with-editable" not in command


def test_inactive_project_source_cannot_replace_the_invoking_studio(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    notebook = tmp_path / "analysis.py"
    notebook.write_text("import marimo\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        """\
[project]
name = "analysis"
version = "0.0.1"
dependencies = ["marimo-studio ; python_version < '3.0'"]

[tool.uv.sources]
marimo-studio = { path = "./inactive-studio" }
""",
        encoding="utf-8",
    )
    source_root = tmp_path / "invoking-studio"
    source_root.mkdir()

    def inline_flags(
        _notebook: Path,
        _launch_requirements: tuple[str, ...],
        *,
        compose_project: bool,
        marker_environment: object,
    ) -> list[str]:
        assert compose_project
        assert marker_environment is not None
        return []

    monkeypatch.setattr(environment_module.shutil, "which", lambda _: "/usr/bin/uv")
    monkeypatch.setattr(
        environment_module,
        "package_source_root",
        lambda: source_root,
    )
    monkeypatch.setattr(
        environment_module,
        "create_environment_flag_builder",
        lambda: inline_flags,
    )

    command = environment_command(_Target(tmp_path, notebook), ["python", "-V"])

    assert "--no-sources-package" in command
    index = command.index("--no-sources-package")
    assert command[index + 1] == "marimo-studio"
    assert command[command.index("--with-editable") + 1] == str(source_root)


@pytest.mark.supported_python
def test_provider_bootstrap_follows_only_an_active_declared_source(
    tmp_path: Path,
) -> None:
    notebook = tmp_path / "analysis.py"
    notebook.write_text(
        f"""\
# /// script
# requires-python = ">=3.10"
# dependencies = ["marimo-studio=={version("marimo-studio")}"]
#
# [tool.uv.sources]
# marimo-studio = {{ path = "./declared-studio" }}
# ///
""",
        encoding="utf-8",
    )
    target = _Target(tmp_path, notebook)

    assert provider_bootstrap_required(target)

    notebook.write_text(
        f"""\
# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "marimo-studio=={version("marimo-studio")} ; python_version < '3.0'",
# ]
#
# [tool.uv.sources]
# marimo-studio = {{ path = "./declared-studio" }}
# ///
""",
        encoding="utf-8",
    )

    assert not provider_bootstrap_required(target)


@pytest.mark.supported_python
def test_marker_bootstrap_rejects_a_different_target_python(
    tmp_path: Path,
) -> None:
    notebook = tmp_path / "analysis.py"
    notebook.write_text(
        """\
# /// script
# requires-python = ">=99"
# dependencies = [
#   "marimo-studio ; python_version >= '3.0'",
# ]
# ///
""",
        encoding="utf-8",
    )

    with pytest.raises(ConfigurationError, match="different target Python"):
        environment_command(_Target(tmp_path, notebook), ["python", "-V"])


@pytest.mark.supported_python
def test_installed_external_extra_requires_bootstrap() -> None:
    assert not environment_module._installed_requirement_satisfies(
        f"packaging[provider]=={version('packaging')}"
    )


@pytest.mark.deno
def test_installed_deno_extra_checks_its_exact_dependency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    studio_version = version("marimo-studio")
    assert environment_module._installed_requirement_satisfies(
        f"marimo-studio[deno]=={studio_version}"
    )
    installed_version = environment_module.version

    def mismatched_deno(distribution: str) -> str:
        if distribution == "deno":
            return "0"
        return installed_version(distribution)

    monkeypatch.setattr(environment_module, "version", mismatched_deno)

    assert not environment_module._installed_requirement_satisfies(
        f"marimo-studio[deno]=={studio_version}"
    )


def test_project_and_notebook_reject_conflicting_exact_studio_versions(
    tmp_path: Path,
) -> None:
    notebook = tmp_path / "analysis.py"
    notebook.write_text(
        f"""\
# /// script
# requires-python = ">=3.10"
# dependencies = ["marimo-studio=={version("marimo-studio")}"]
# ///
""",
        encoding="utf-8",
    )
    (tmp_path / "pyproject.toml").write_text(
        """\
[project]
name = "analysis"
version = "0.0.1"
dependencies = ["marimo-studio==999.0.0"]
""",
        encoding="utf-8",
    )

    with pytest.raises(ConfigurationError, match="conflicting exact"):
        environment_command(_Target(tmp_path, notebook), ["python", "-V"])


@pytest.mark.native_process
def test_source_checkout_reentry_uses_local_package_for_unversioned_requirement(
    tmp_path: Path,
) -> None:
    notebook = tmp_path / "analysis.py"
    notebook.write_text(
        """\
# /// script
# requires-python = ">=3.10"
# dependencies = ["marimo-studio"]
# ///
""",
        encoding="utf-8",
    )
    target = _Target(tmp_path, notebook)
    command = environment_command(
        target,
        [
            "python",
            "-c",
            "from pathlib import Path; import marimo_studio; "
            "print(Path(marimo_studio.__file__).resolve())",
        ],
    )

    result = subprocess.run(
        command,
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )

    assert result.returncode == 0, result.stderr
    source_root = environment_module.package_source_root()
    assert source_root is not None
    assert Path(result.stdout.strip()).is_relative_to(source_root)
    assert command[command.index("--with-editable") + 1] == str(source_root)


@pytest.mark.parametrize(
    ("requirement", "uses_source_checkout"),
    (
        ("marimo-studio", True),
        (f"marimo-studio=={version('marimo-studio')}", True),
        ("marimo-studio==999.0.0", False),
    ),
)
def test_source_checkout_respects_the_declared_exact_studio_version(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    requirement: str,
    uses_source_checkout: bool,
) -> None:
    notebook = tmp_path / "analysis.py"
    notebook.write_text(
        f"""\
# /// script
# requires-python = ">=3.10"
# dependencies = ["{requirement}"]
# ///
""",
        encoding="utf-8",
    )
    source_root = tmp_path / "studio-source"
    source_root.mkdir()
    monkeypatch.setattr(
        environment_module,
        "package_source_root",
        lambda: source_root,
    )

    command = environment_command(_Target(tmp_path, notebook), ["python", "-V"])

    if uses_source_checkout:
        assert command[command.index("--with-editable") + 1] == str(source_root)
    else:
        assert "--with-editable" not in command
        requirements = [value for flag, value in pairwise(command) if flag == "--with"]
        assert "marimo-studio==999.0.0" in requirements


def test_notebook_source_claim_omits_the_invoking_checkout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    notebook = tmp_path / "analysis.py"
    notebook.write_text(
        """\
# /// script
# requires-python = ">=3.10"
# dependencies = ["marimo-studio>=0"]
#
# [tool.uv.sources]
# marimo-studio = { path = "./declared-studio" }
# ///
""",
        encoding="utf-8",
    )
    invoking_source = tmp_path / "invoking-studio"
    invoking_source.mkdir()
    declared_source = tmp_path / "declared-studio"
    declared_source.mkdir()
    monkeypatch.setattr(
        environment_module,
        "package_source_root",
        lambda: invoking_source,
    )

    command = environment_command(_Target(tmp_path, notebook), ["python", "-V"])

    assert "--with-editable" not in command
    requirements = [value for flag, value in pairwise(command) if flag == "--with"]
    assert f"marimo-studio @ {declared_source}" in requirements
