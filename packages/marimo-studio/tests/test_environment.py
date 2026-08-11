from __future__ import annotations

import subprocess
from dataclasses import dataclass
from importlib.metadata import version
from pathlib import Path
from types import SimpleNamespace
from typing import Any, TextIO, cast

import pytest

import marimo_studio.environment as environment_module
from marimo_studio._compat.environment import inline_environment_flags
from marimo_studio._workspace import load_studio
from marimo_studio.environment import environment_command, run_in_notebook_environment
from marimo_studio.workspace import ensure_view

from .helpers import notebook_source


@dataclass(frozen=True)
class _Target:
    root: Path
    notebook: Path


def test_project_reentry_uses_the_lock_and_relays_stderr(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (notebook_path.parent / "pyproject.toml").write_text(
        f"""\
[project]
name = "analysis"
version = "0.0.1"
dependencies = ["marimo-studio==1.2.3"]

[tool.marimo-studio]
notebook = "{notebook_path.name}"
default = "dashboard"
""",
        encoding="utf-8",
    )
    ensure_view(notebook_path)
    studio = load_studio(notebook_path)
    (studio.root / "uv.lock").write_text("version = 1\n", encoding="utf-8")
    captured: dict[str, Any] = {}
    lines: list[str] = []

    def run(command: list[str], **kwargs: object) -> SimpleNamespace:
        captured["command"] = command
        stderr = cast(TextIO, kwargs["stderr"])
        stderr.write("native warning\n")
        stderr.flush()
        return SimpleNamespace(returncode=17)

    monkeypatch.setattr(environment_module.shutil, "which", lambda _: "/usr/bin/uv")
    monkeypatch.setattr(environment_module, "package_source_root", lambda: None)

    def inline_flags(
        _notebook: Path,
        package_requirement: str | None,
        *,
        compose_project: bool,
    ) -> list[str]:
        captured["package_requirement"] = package_requirement
        captured["compose_project"] = compose_project
        return ["--python", ">=3.10"]

    monkeypatch.setattr(
        environment_module,
        "create_tooling_adapters",
        lambda: SimpleNamespace(environment=inline_flags),
    )
    monkeypatch.setattr(subprocess, "run", run)

    result = run_in_notebook_environment(
        studio,
        ["check", str(studio.root), "--runtime"],
        diagnostic_stream=lambda output: lines.append(output.read()),
    )

    assert result == 17
    command = captured["command"]
    assert command[:2] == ["/usr/bin/uv", "run"]
    assert command[command.index("--project") + 1] == str(studio.root)
    assert "--frozen" in command
    assert command[command.index("--") + 1] == "marimo-studio"
    assert command[-3:] == ["check", str(studio.root), "--runtime"]
    assert captured["package_requirement"] == "marimo-studio"
    assert captured["compose_project"] is True
    assert lines == ["native warning\n"]


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
    studio = ensure_view(notebook).workspace
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


def test_inline_environment_uses_the_unversioned_package_requirement(
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
        "marimo-studio",
        compose_project=False,
    )
    requirements = Path(flags[flags.index("--with-requirements") + 1]).read_text(
        encoding="utf-8"
    )

    assert set(requirements.splitlines()) == {
        "humanize>=4",
        f"marimo=={version('marimo')}",
        "marimo-studio",
    }
    assert flags[flags.index("--index") + 1] == "https://packages.example/simple"
