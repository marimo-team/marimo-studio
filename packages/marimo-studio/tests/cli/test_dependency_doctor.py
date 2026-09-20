from __future__ import annotations

import json
from pathlib import Path

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
