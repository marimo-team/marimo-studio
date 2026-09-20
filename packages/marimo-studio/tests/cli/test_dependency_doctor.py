from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from marimo_studio._cli import cli


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


def test_dependency_doctor_resolves_provider_umbrella_extras(tmp_path: Path) -> None:
    notebook = tmp_path / "analysis.py"
    notebook.write_text("import marimo\n")
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "analysis"\nversion = "0.1"\n'
        'dependencies = ["marimo-studio[recommended]"]\n'
    )
    view = tmp_path / "__marimo__" / "studio" / "analysis" / "dashboard"
    view.mkdir(parents=True)
    (view / "view.toml").write_text('schema = 1\nprovider = "marimo-studio/react"\n')
    result = CliRunner().invoke(
        cli, ["doctor", "--dependencies", "--target", str(notebook), "--json"]
    )
    assert result.exit_code == 0, result.output
    report = json.loads(result.stdout)
    assert report["ok"]
    assert report["installed"]["deno"]


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
