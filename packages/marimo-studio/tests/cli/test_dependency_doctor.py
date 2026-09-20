from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from marimo_studio._cli import cli
from marimo_studio.errors import ConfigurationError


def test_dependency_doctor_reports_drift_and_missing_runtime_imports(
    tmp_path: Path,
) -> None:
    notebook = tmp_path / "analysis.py"
    notebook.write_text(
        "# /// script\n"
        '# dependencies = ["marimo>=999", "absent-package-for-studio-test"]\n# ///\n'
        "import marimo\nimport absent_module_for_studio_test\n"
        'raise RuntimeError("doctor must not execute notebook code")\n'
    )
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "analysis"\nversion = "0.1"\ndependencies = ["marimo"]\n'
    )
    result = CliRunner().invoke(
        cli, ["doctor", "--dependencies", "--target", str(notebook), "--json"]
    )
    assert result.exit_code == 1, result.output
    report = json.loads(result.stdout)
    assert report["schema"] == 1
    assert not report["ok"]
    assert {item["code"] for item in report["issues"]} == {
        "metadata-drift",
        "missing-distribution",
        "version-mismatch",
        "missing-import",
    }
    assert report["project"] == str(tmp_path / "pyproject.toml")
    assert report["python"]


def test_dependency_doctor_accepts_project_imports_and_inactive_markers(
    tmp_path: Path,
) -> None:
    notebook = tmp_path / "analysis.py"
    notebook.write_text("import marimo\nimport local_analysis\nimport json\n")
    (tmp_path / "local_analysis.py").write_text('raise RuntimeError("do not import")\n')
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "analysis"\nversion = "0.1"\n'
        'dependencies = ["marimo", "absent-package; python_version < \'2\'"]\n'
    )
    result = CliRunner().invoke(
        cli, ["doctor", "--dependencies", "--target", str(notebook), "--json"]
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["ok"]
    assert notebook.read_text() == "import marimo\nimport local_analysis\nimport json\n"


def test_dependency_doctor_checks_configured_provider_requirements(
    notebook_path: Path,
) -> None:
    from marimo_studio._views.api import prepare_view

    prepare_view(notebook_path)
    notebook_path.write_text(
        notebook_path.read_text().replace("marimo-studio==", "marimo-studio>=999.")
    )
    result = CliRunner().invoke(
        cli, ["doctor", "--dependencies", "--target", str(notebook_path), "--json"]
    )
    assert result.exit_code == 1, result.output
    report = json.loads(result.stdout)
    assert any(
        "marimo-studio" in value for value in report["declarations"]["providers"]
    )
    assert any(item["code"] == "version-mismatch" for item in report["issues"])


@pytest.mark.parametrize("configuration", ["invalid", "dual", "removed"])
def test_dependency_doctor_reports_dependencies_when_studio_discovery_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    configuration: str,
) -> None:
    import marimo_studio._workspace.config as config_module

    notebook = tmp_path / "analysis.py"
    notebook.write_text("import absent_module_for_studio_test\n")
    project = tmp_path / "pyproject.toml"
    project.write_text(
        '[project]\nname = "analysis"\nversion = "0.1"\n'
        'dependencies = ["absent-package-for-studio-test"]\n'
        '[tool.marimo-studio]\nnotebook = "analysis.py"\n'
        + (
            "default = 42\n"
            if configuration == "invalid"
            else 'default = "dashboard"\n'
        )
    )
    if configuration == "dual":
        notebook.write_text(
            '# /// script\n# [tool.marimo-studio]\n# default = "dashboard"\n# ///\n'
            + notebook.read_text()
        )
    elif configuration == "removed":

        def missing_snapshot(*_args: object, **_kwargs: object) -> None:
            raise FileNotFoundError(project)

        monkeypatch.setattr(
            config_module, "read_file_snapshot_with_identity", missing_snapshot
        )
    view = tmp_path / "__marimo__" / "studio" / "analysis" / "dashboard"
    view.mkdir(parents=True)
    (view / "view.toml").write_text('schema = 1\nprovider = "marimo-studio/vanilla"\n')

    result = CliRunner().invoke(
        cli, ["doctor", "--dependencies", "--target", str(notebook), "--json"]
    )

    assert result.exit_code == 1, result.output
    report = json.loads(result.stdout)
    assert not report["ok"]
    assert {issue["code"] for issue in report["issues"]} == {
        "workspace-generation-conflict"
        if configuration == "removed"
        else "configuration-error",
        "missing-distribution",
        "missing-import",
        "undeclared-provider",
    }
    assert report["declarations"]["providers"] == ["marimo-studio"]
    assert report["installed"]["absent-package-for-studio-test"] is None
    assert not report["imports"][0]["available"]


def test_dependency_doctor_rejects_unknown_distribution_extras(tmp_path: Path) -> None:
    notebook = tmp_path / "analysis.py"
    notebook.write_text(
        '# /// script\n# dependencies = ["packaging[studio-missing-extra]"]\n# ///\n'
        "import packaging\n"
    )
    result = CliRunner().invoke(
        cli, ["doctor", "--dependencies", "--target", str(notebook), "--json"]
    )
    assert result.exit_code == 1, result.output
    assert {item["code"] for item in json.loads(result.stdout)["issues"]} == {
        "unknown-extra"
    }


def test_dependency_doctor_reports_undefined_marker_environment(tmp_path: Path) -> None:
    notebook = tmp_path / "analysis.py"
    notebook.write_text(
        "# /// script\n# dependencies = [\"packaging; extras == 'test'\"]\n# ///\n"
    )

    result = CliRunner().invoke(
        cli, ["doctor", "--dependencies", "--target", str(notebook), "--json"]
    )

    assert result.exit_code == 1, result.output
    assert isinstance(result.exception, ConfigurationError)
    assert "Invalid dependency: packaging; extras" in str(result.exception)


@pytest.mark.parametrize("dependency", ["broken >= !", 'broken; extras == "test"'])
def test_dependency_doctor_reports_invalid_installed_metadata_and_continues(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, dependency: str
) -> None:
    metadata = tmp_path / "broken_distribution-1.0.dist-info"
    metadata.mkdir()
    (metadata / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: broken-distribution\nVersion: 1.0\n"
        f"Requires-Dist: {dependency}\nRequires-Dist: packaging\n"
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    notebook = tmp_path / "analysis.py"
    notebook.write_text(
        '# /// script\n# dependencies = ["broken-distribution"]\n# ///\n'
    )

    result = CliRunner().invoke(
        cli, ["doctor", "--dependencies", "--target", str(notebook), "--json"]
    )

    assert result.exit_code == 1, result.output
    report = json.loads(result.stdout)
    assert report["installed"]["packaging"]
    assert report["issues"] == [
        {
            "code": "invalid-dependency",
            "message": (
                f"broken-distribution declares an invalid dependency: {dependency}"
            ),
        }
    ]


def test_dependency_doctor_accepts_the_owning_project_package(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    directory = tmp_path / "notebooks"
    directory.mkdir()
    notebook = directory / "analysis.py"
    source = tmp_path / "src" / "analysis_package"
    source.mkdir(parents=True)
    (source / "__init__.py").write_text('raise RuntimeError("do not import")\n')
    monkeypatch.syspath_prepend(str(source.parent))
    notebook.write_text("import analysis_package\n")
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "analysis-project"\nversion = "0.1"\ndependencies = []\n'
    )
    result = CliRunner().invoke(
        cli, ["doctor", "--dependencies", "--target", str(notebook), "--json"]
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["imports"][0]["available"]


@pytest.mark.parametrize("view_root", [None, "views"])
def test_dependency_doctor_resolves_provider_umbrella_extras(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, view_root: str | None
) -> None:
    from marimo_studio.view_providers._host.registry import ProviderRegistry

    from ..provider_test_support import ProviderStub, candidate, install_registry

    metadata = tmp_path / "example_suite-1.0.dist-info"
    metadata.mkdir()
    (metadata / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: example-suite\nVersion: 1.0\n"
        "Provides-Extra: recommended\nProvides-Extra: render\n"
        'Requires-Dist: example-suite[render]; extra == "recommended"\n'
        'Requires-Dist: packaging; extra == "render"\n'
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    install_registry(
        monkeypatch,
        ProviderRegistry(
            (
                candidate(
                    "report",
                    ProviderStub("example-suite/report", "default"),
                    distribution="example-suite",
                ),
            ),
            {"example-suite/report": "example-suite[render]"},
        ),
    )
    notebook = tmp_path / "analysis.py"
    notebook.write_text("import packaging\n")
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "analysis"\nversion = "0.1"\n'
        'dependencies = ["example-suite[recommended]"]\n'
        + (
            '[tool.marimo-studio]\nnotebook = "analysis.py"\n'
            f'default = "dashboard"\nview_root = "{view_root}"\n'
            if view_root is not None
            else ""
        )
    )
    view = tmp_path / (view_root or "__marimo__/studio/analysis") / "dashboard"
    view.mkdir(parents=True)
    (view / "view.toml").write_text('schema = 1\nprovider = "example-suite/report"\n')
    result = CliRunner().invoke(
        cli, ["doctor", "--dependencies", "--target", str(notebook), "--json"]
    )
    assert result.exit_code == 0, result.output
    report = json.loads(result.stdout)
    assert report["ok"]
    assert report["declarations"]["providers"] == ["example-suite[render]"]
    assert report["installed"]["packaging"]


@pytest.mark.deno
def test_dependency_doctor_checks_the_combined_execution_environment(
    tmp_path: Path,
) -> None:
    notebook = tmp_path / "analysis.py"
    notebook.write_text(
        '# /// script\n# dependencies = ["polars"]\n# ///\n'
        "import polars\nimport marimo\n"
    )
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "analysis"\nversion = "0.1"\n'
        'dependencies = ["marimo-studio[deno]"]\n'
    )
    view = tmp_path / "__marimo__" / "studio" / "analysis" / "dashboard"
    view.mkdir(parents=True)
    (view / "view.toml").write_text('schema = 1\nprovider = "marimo-studio/react"\n')
    result = CliRunner().invoke(
        cli, ["doctor", "--dependencies", "--target", str(notebook), "--json"]
    )
    assert result.exit_code == 1, result.output
    assert {issue["code"] for issue in json.loads(result.stdout)["issues"]} == {
        "metadata-drift"
    }


def test_dependency_doctor_rejects_undeclared_packages_in_project_venv(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site_packages = tmp_path / ".venv" / "lib" / "python3.12" / "site-packages"
    site_packages.mkdir(parents=True)
    (site_packages / "accidental_dependency.py").write_text(
        'raise RuntimeError("do not import")\n'
    )
    monkeypatch.syspath_prepend(str(site_packages))
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "analysis"\nversion = "0.1"\ndependencies = []\n'
    )
    notebook = tmp_path / "analysis.py"
    notebook.write_text("import accidental_dependency\n")
    result = CliRunner().invoke(
        cli, ["doctor", "--dependencies", "--target", str(notebook), "--json"]
    )
    assert result.exit_code == 1, result.output
    report = json.loads(result.stdout)
    assert report["imports"][0]["available"]
    assert not report["imports"][0]["local"]
    assert {issue["code"] for issue in report["issues"]} == {"undeclared-import"}
