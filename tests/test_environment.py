from __future__ import annotations

import subprocess
from dataclasses import dataclass
from importlib.metadata import version
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import marimo_studio._workspace.environment as environment_module
from marimo_studio._compat.environment import inline_environment_flags
from marimo_studio._workspace import ensure_view, load_studio
from marimo_studio._workspace.environment import (
    environment_command,
    run_in_notebook_environment,
    should_reenter,
)

from .helpers import notebook_source


@dataclass(frozen=True)
class _Target:
    root: Path
    notebook: Path


def test_notebook_runtime_checks_reenter_the_script_environment(
    notebook_path: Path,
) -> None:
    ensure_view(notebook_path)
    studio = load_studio(notebook_path)

    assert should_reenter(studio, None) is True
    assert should_reenter(studio, False) is False


def test_project_reentry_uses_the_lock_and_relays_stderr(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (notebook_path.parent / "pyproject.toml").write_text(
        f"""\
[project]
name = "analysis"
version = "0.1.0"
dependencies = ["marimo-studio==0.0.1"]

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
        captured["stderr"] = kwargs["stderr"]
        return SimpleNamespace(returncode=17, stderr="native warning\n")

    monkeypatch.setattr(environment_module.shutil, "which", lambda _: "/usr/bin/uv")
    monkeypatch.setattr(
        environment_module,
        "inline_environment_flags",
        lambda *_args, **_kwargs: ["--python", ">=3.11"],
    )
    monkeypatch.setattr(subprocess, "run", run)

    result = run_in_notebook_environment(
        studio,
        ["check", str(studio.root), "--runtime"],
        diagnostic_line=lines.append,
    )

    assert result == 17
    command = captured["command"]
    assert command[:2] == ["/usr/bin/uv", "run"]
    assert command[command.index("--project") + 1] == str(studio.root)
    assert "--frozen" in command
    assert command[command.index("--") + 1] == "marimo-studio"
    assert command[-3:] == ["check", str(studio.root), "--runtime"]
    assert captured["stderr"] == subprocess.PIPE
    assert lines == ["native warning"]


def test_source_checkout_reentry_supersedes_a_stale_notebook_pin(
    tmp_path: Path,
) -> None:
    notebook = tmp_path / "analysis.py"
    notebook.write_text(
        """\
# /// script
# requires-python = ">=3.11"
# dependencies = ["marimo-studio==0.0.0"]
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
            "from importlib.metadata import version; print(version('marimo-studio'))",
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
    assert result.stdout.strip() == version("marimo-studio")


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
version = "0.1.0"
dependencies = ["project-demo"]

[tool.uv.sources]
project-demo = { path = "./project-demo" }
""",
        encoding="utf-8",
    )
    studio = ensure_view(notebook).studio
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


def test_inline_environment_replaces_a_stale_package_requirement(
    tmp_path: Path,
) -> None:
    notebook = tmp_path / "analysis.py"
    notebook.write_text(
        """\
# /// script
# requires-python = ">=3.11"
# dependencies = ["humanize>=4", "marimo-studio==0.0.1"]
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
        "marimo-studio==9.8.7",
        compose_project=False,
    )
    requirements = Path(flags[flags.index("--with-requirements") + 1]).read_text(
        encoding="utf-8"
    )

    assert "humanize>=4" in requirements.splitlines()
    assert "marimo-studio==9.8.7" in requirements.splitlines()
    assert "https://example.test/old.git" not in requirements
    assert flags[flags.index("--index") + 1] == "https://packages.example/simple"
