from __future__ import annotations

import subprocess
from dataclasses import dataclass
from importlib.metadata import version
from pathlib import Path
from typing import cast

import pytest
from packaging.markers import default_environment

from marimo_studio._cli.environment import environment_command
from marimo_studio._compat.environment import inline_environment_flags
from marimo_studio._views.api import prepare_view
from marimo_studio._workspace import load_studio
from marimo_studio.errors import ConfigurationError, DependencyError
from marimo_studio.view_providers import ProviderAvailability
from marimo_studio.view_providers._bundled import _deno
from marimo_studio.view_providers._bundled.deno_react import (
    provider as react_provider,
)
from marimo_studio.view_providers._bundled.deno_svelte import (
    provider as svelte_provider,
)
from marimo_studio.view_providers._host.package_policy import (
    BUNDLED_PROVIDER_REQUIREMENTS,
)
from marimo_studio.view_providers._host.registry import ProviderRegistry

from ..helpers import notebook_source
from ..provider_test_support import (
    ProviderStub,
    candidate,
    install_registry,
)


@dataclass(frozen=True)
class _Target:
    root: Path
    notebook: Path


@pytest.mark.native_process
def test_fresh_reentry_installs_react_svelte_and_external_provider_requirements(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        _deno,
        "deno_availability",
        lambda: ProviderAvailability(True),
    )
    package = notebook_path.parent / "example-suite"
    (package / "src" / "example_suite").mkdir(parents=True)
    (package / "pyproject.toml").write_text(
        """\
[project]
name = "example-suite"
version = "1.0.0"

[build-system]
requires = ["uv_build==0.12.2"]
build-backend = "uv_build"
""",
        encoding="utf-8",
    )
    (package / "src" / "example_suite" / "__init__.py").write_text(
        'VALUE = "external-provider"\n',
        encoding="utf-8",
    )
    notebook_path.write_text(
        """\
# /// script
# requires-python = ">=3.10"
# dependencies = ["example-suite"]
#
# [tool.uv.sources]
# example-suite = { path = "./example-suite" }
# ///

"""
        + notebook_path.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    report = ProviderStub("unused/report", "default")
    web = ProviderStub("unused/web", "default")
    install_registry(
        monkeypatch,
        ProviderRegistry(
            (
                candidate("react", react_provider, distribution="marimo-studio"),
                candidate("svelte", svelte_provider, distribution="marimo-studio"),
                candidate("report", report, distribution="example-suite"),
                candidate("web", web, distribution="example-suite"),
            ),
            BUNDLED_PROVIDER_REQUIREMENTS,
        ),
    )
    prepare_view(
        notebook_path,
        "dashboard",
        starter="marimo-studio/react:default",
    )
    prepare_view(
        notebook_path,
        "detail",
        starter="marimo-studio/svelte:default",
    )
    prepare_view(
        notebook_path,
        "slides",
        starter="marimo-studio/react:reveal",
    )
    prepare_view(
        notebook_path,
        "report",
        starter="example-suite/report:default",
    )
    prepare_view(
        notebook_path,
        "web",
        starter="example-suite/web:default",
    )
    install_registry(monkeypatch, ProviderRegistry(()))
    command = environment_command(
        load_studio(notebook_path),
        [
            "python",
            "-c",
            "from importlib.metadata import version; import example_suite; "
            "from marimo_studio.view_providers._bundled.deno_react import "
            "provider as react; "
            "from marimo_studio.view_providers._bundled.deno_svelte import "
            "provider as svelte; "
            "print(':'.join((version('marimo-studio'), version('deno'), "
            "version('example-suite'), example_suite.VALUE, react.info.title, "
            "svelte.info.title)))",
        ],
    )

    result = subprocess.run(
        command,
        cwd=notebook_path.parent,
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == (
        f"{version('marimo-studio')}:2.9.5:1.0.0:external-provider:React:Svelte"
    )
    assert "--isolated" in command
    assert "--no-project" in command


def test_config_only_pyproject_keeps_the_inline_environment_isolated(
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
    (tmp_path / "pyproject.toml").write_text(
        """\
[tool.marimo.runtime]
auto_instantiate = true
""",
        encoding="utf-8",
    )

    command = environment_command(_Target(tmp_path, notebook), ["python", "-V"])

    assert "--project" not in command
    assert "--isolated" in command
    assert "--no-project" in command


def test_config_only_pyproject_bounds_outer_workspace_discovery(
    tmp_path: Path,
) -> None:
    inner = tmp_path / "workspace" / "notebooks"
    inner.mkdir(parents=True)
    notebook = inner / "analysis.py"
    notebook.write_text(
        """\
# /// script
# requires-python = ">=3.10"
# dependencies = ["marimo-studio"]
# ///
""",
        encoding="utf-8",
    )
    (tmp_path / "pyproject.toml").write_text(
        """\
[tool.uv.workspace]
members = []
""",
        encoding="utf-8",
    )
    (inner / "pyproject.toml").write_text(
        """\
[tool.marimo.runtime]
auto_instantiate = true
""",
        encoding="utf-8",
    )

    command = environment_command(_Target(inner, notebook), ["python", "-V"])

    assert "--project" not in command
    assert "--isolated" in command
    assert "--no-project" in command


def test_invalid_nearest_pyproject_blocks_inline_environment(
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
    (tmp_path / "pyproject.toml").write_text(
        """\
[project]
name = "analysis"
dependencies = [
""",
        encoding="utf-8",
    )

    with pytest.raises(DependencyError, match="Invalid project metadata"):
        environment_command(_Target(tmp_path, notebook), ["python", "-V"])


@pytest.mark.native_process
def test_notebook_environment_composes_project_and_pep_723_sources(
    tmp_path: Path,
) -> None:
    project_package = tmp_path / "project-demo"
    (project_package / "src" / "project_demo").mkdir(parents=True)
    (project_package / "pyproject.toml").write_text(
        """\
[project]
name = "project-demo"
version = "1.0.0"
""",
        encoding="utf-8",
    )
    (project_package / "src" / "project_demo" / "__init__.py").write_text(
        'VALUE = "project-source"\n',
        encoding="utf-8",
    )
    notebook_package = tmp_path / "notebook-demo"
    (notebook_package / "src" / "notebook_demo").mkdir(parents=True)
    (notebook_package / "pyproject.toml").write_text(
        """\
[project]
name = "notebook-demo"
version = "1.0.0"
""",
        encoding="utf-8",
    )
    (notebook_package / "src" / "notebook_demo" / "__init__.py").write_text(
        'VALUE = "notebook-source"\n',
        encoding="utf-8",
    )
    notebook_dir = tmp_path / "notebooks"
    notebook_dir.mkdir()
    notebook = notebook_dir / "analysis.py"
    notebook.write_text(
        notebook_source(
            notebook_dir / "executed",
            dependencies=("notebook-demo",),
        ).replace(
            "# ///\nimport marimo",
            "#\n# [tool.uv.sources]\n"
            '# notebook-demo = { path = "../notebook-demo" }\n'
            "# ///\nimport marimo",
        ),
        encoding="utf-8",
    )
    (tmp_path / "pyproject.toml").write_text(
        """\
[project]
name = "analysis"
version = "0.0.1"
dependencies = ["project-demo"]

[tool.uv.sources]
project-demo = { path = "./project-demo" }
""",
        encoding="utf-8",
    )
    studio = prepare_view(notebook).workspace
    assert studio is not None

    command = environment_command(
        studio,
        [
            "python",
            "-c",
            "import notebook_demo, project_demo; "
            "print(f'{project_demo.VALUE}:{notebook_demo.VALUE}')",
        ],
    )
    result = subprocess.run(
        command,
        cwd=notebook_dir,
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "project-source:notebook-source"


def test_inline_environment_preserves_the_notebook_studio_source(
    tmp_path: Path,
) -> None:
    notebook = tmp_path / "analysis.py"
    notebook.write_text(
        """\
# /// script
# requires-python = ">=3.10"
# dependencies = ["humanize>=4", "marimo-studio==1.2.3"]
#
# [tool.uv.sources]
# marimo-studio = { git = "https://example.test/old.git" }
#
# [[tool.uv.index]]
# name = "private"
# url = "https://packages.example/simple"
# ///
""",
        encoding="utf-8",
    )

    flags = inline_environment_flags(
        notebook,
        (f"marimo-studio=={version('marimo-studio')}",),
        compose_project=False,
        marker_environment=None,
    )
    requirements = Path(flags[flags.index("--with-requirements") + 1]).read_text(
        encoding="utf-8"
    )

    assert set(requirements.splitlines()) == {
        "humanize>=4",
        f"marimo=={version('marimo')}",
        "marimo-studio @ git+https://example.test/old.git",
    }
    assert flags[flags.index("--index") + 1] == "https://packages.example/simple"


@pytest.mark.parametrize(
    "launch_requirement",
    (
        "marimo-studio==0.1.0",
        "marimo-studio[deno]==0.1.0",
    ),
)
def test_inline_environment_preserves_exact_pin_and_declared_provider_extras(
    tmp_path: Path,
    launch_requirement: str,
) -> None:
    notebook = tmp_path / "analysis.py"
    notebook.write_text(
        """\
# /// script
# requires-python = ">=3.10"
# dependencies = ["marimo-studio[deno]==1.2.3"]
# ///
""",
        encoding="utf-8",
    )

    flags = inline_environment_flags(
        notebook,
        (launch_requirement,),
        compose_project=False,
        marker_environment=None,
    )
    requirements = Path(flags[flags.index("--with-requirements") + 1]).read_text(
        encoding="utf-8"
    )

    assert "marimo-studio[deno]==1.2.3" in requirements.splitlines()


def test_inline_environment_accepts_equivalent_exact_version_spellings(
    tmp_path: Path,
) -> None:
    notebook = tmp_path / "analysis.py"
    notebook.write_text(
        """\
# /// script
# requires-python = ">=3.10"
# dependencies = ["marimo-studio==1.0", "marimo-studio[deno]==1.0.0"]
# ///
""",
        encoding="utf-8",
    )

    flags = inline_environment_flags(
        notebook,
        (f"marimo-studio=={version('marimo-studio')}",),
        compose_project=False,
        marker_environment=None,
    )
    requirements = Path(flags[flags.index("--with-requirements") + 1]).read_text(
        encoding="utf-8"
    )

    assert "marimo-studio[deno]==1.0" in requirements.splitlines()


def test_inline_environment_pins_each_launch_requirement_in_isolation(
    tmp_path: Path,
) -> None:
    notebook = tmp_path / "analysis.py"
    notebook.write_text(
        """\
# /// script
# requires-python = ">=3.10"
# dependencies = ["marimo-studio[deno]>=0", "example-suite[runtime]>=0"]
# ///
""",
        encoding="utf-8",
    )

    flags = inline_environment_flags(
        notebook,
        (
            "marimo-studio[deno]==0.1.0",
            "example-suite==1.0.0",
        ),
        compose_project=False,
        marker_environment=None,
    )
    requirements = Path(flags[flags.index("--with-requirements") + 1]).read_text(
        encoding="utf-8"
    )

    assert set(requirements.splitlines()) == {
        f"marimo=={version('marimo')}",
        "marimo-studio[deno]==0.1.0",
        "example-suite[runtime]==1.0.0",
    }
    assert "--isolated" in flags
    assert "--no-project" in flags


def test_inline_environment_ignores_a_false_external_provider_source(
    tmp_path: Path,
) -> None:
    notebook = tmp_path / "analysis.py"
    notebook.write_text(
        """\
# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "marimo-studio>=0",
#   "example-suite[runtime] @ git+https://e.test/p.git@v1 ; python_version < '3.0'",
# ]
#
# [tool.uv.sources]
# example-suite = { path = "./inactive-provider" }
# ///
""",
        encoding="utf-8",
    )

    flags = inline_environment_flags(
        notebook,
        (
            "marimo-studio==0.1.0",
            "example-suite[render]==1.0.0",
        ),
        compose_project=False,
        marker_environment=cast(dict[str, str], default_environment()),
    )
    requirements = Path(flags[flags.index("--with-requirements") + 1]).read_text(
        encoding="utf-8"
    )

    assert "example-suite[render]==1.0.0" in requirements.splitlines()
    assert "inactive-provider" not in requirements


def test_inline_environment_ignores_a_false_studio_uv_source(
    tmp_path: Path,
) -> None:
    notebook = tmp_path / "analysis.py"
    notebook.write_text(
        """\
# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "marimo-studio ; sys_platform == 'win32'",
# ]
#
# [tool.uv.sources]
# marimo-studio = { path = "./inactive-studio" }
# ///
""",
        encoding="utf-8",
    )

    flags = inline_environment_flags(
        notebook,
        ("marimo-studio==0.1.0",),
        compose_project=False,
        marker_environment=cast(dict[str, str], default_environment()),
    )
    requirements = Path(flags[flags.index("--with-requirements") + 1]).read_text(
        encoding="utf-8"
    )

    assert "marimo-studio==0.1.0" in requirements.splitlines()
    assert "inactive-studio" not in requirements


def test_inline_environment_rejects_conflicting_external_provider_sources(
    tmp_path: Path,
) -> None:
    notebook = tmp_path / "analysis.py"
    notebook.write_text(
        """\
# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "example-suite @ git+https://example.test/provider.git@v1",
#   "example-suite @ git+https://example.test/provider.git@v2",
# ]
# ///
""",
        encoding="utf-8",
    )

    with pytest.raises(ConfigurationError, match="conflicting direct sources"):
        inline_environment_flags(
            notebook,
            (
                "marimo-studio==0.1.0",
                "example-suite==1.0.0",
            ),
            compose_project=False,
            marker_environment=None,
        )
