from __future__ import annotations

import subprocess
from importlib.metadata import version
from itertools import pairwise
from pathlib import Path
from types import SimpleNamespace
from typing import Any, TextIO, cast

import pytest

import marimo_studio._cli.environment as environment_module
from marimo_studio._cli.environment import (
    environment_command,
    run_in_notebook_environment,
)
from marimo_studio._views.api import prepare_view
from marimo_studio._workspace import load_studio
from marimo_studio._workspace.installation import InvokingStudio
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

from ..provider_test_support import (
    ProviderStub,
    candidate,
    install_registry,
)


def test_project_reentry_separates_result_diagnostics_and_process_output(
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
    prepare_view(notebook_path)
    studio = load_studio(notebook_path)
    (studio.root / "uv.lock").write_text("version = 1\n", encoding="utf-8")
    captured: dict[str, Any] = {}
    lines: list[str] = []
    process_lines: list[str] = []

    def run(command: list[str], **kwargs: object) -> SimpleNamespace:
        captured["command"] = command
        child_environment = cast(dict[str, str], kwargs["env"])
        result_channel = Path(child_environment[environment_module._RESULT_CHANNEL_ENV])
        diagnostic_channel = Path(
            child_environment[environment_module._DIAGNOSTIC_CHANNEL_ENV]
        )
        result_channel.write_text('{"schema":1,"ok":false}\n', encoding="utf-8")
        diagnostic_channel.write_text("trusted diagnostic\n", encoding="utf-8")
        stdout = cast(TextIO, kwargs["stdout"])
        stdout.write("uv stdout\n")
        stdout.flush()
        stderr = cast(TextIO, kwargs["stderr"])
        stderr.write("uv stderr\n")
        stderr.flush()
        return SimpleNamespace(returncode=17)

    monkeypatch.setattr(environment_module.shutil, "which", lambda _: "/usr/bin/uv")

    def inline_flags(
        _notebook: Path,
        launch_requirements: tuple[str, ...],
        *,
        compose_project: bool,
        marker_environment: object,
    ) -> list[str]:
        captured["launch_requirements"] = launch_requirements
        captured["compose_project"] = compose_project
        return ["--python", ">=3.10"]

    monkeypatch.setattr(
        environment_module,
        "create_environment_flag_builder",
        lambda: inline_flags,
    )
    monkeypatch.setattr(subprocess, "run", run)

    result = run_in_notebook_environment(
        studio,
        [
            "validate",
            str(studio.notebook),
            "--level",
            "runtime",
            "--json",
        ],
        capture_result=True,
        diagnostic_stream=lambda output: lines.append(output.read()),
        process_stream=lambda output: process_lines.append(output.read()),
    )

    assert result.returncode == 17
    assert result.result == '{"schema":1,"ok":false}\n'
    command = captured["command"]
    assert command[:2] == ["/usr/bin/uv", "run"]
    assert command[command.index("--project") + 1] == str(studio.root)
    assert "--frozen" in command
    assert command[command.index("--") + 1] == "marimo-studio"
    assert command[-5:] == [
        "validate",
        str(studio.notebook),
        "--level",
        "runtime",
        "--json",
    ]
    assert captured["launch_requirements"] == ("marimo-studio==1.2.3",)
    assert captured["compose_project"] is True
    assert "--with-editable" not in command
    assert lines == ["trusted diagnostic\n"]
    assert process_lines == ["uv stdout\n", "uv stderr\n"]


def test_project_config_reentry_carries_every_provider_distribution(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        _deno,
        "deno_availability",
        lambda: ProviderAvailability(True),
    )
    (notebook_path.parent / "pyproject.toml").write_text(
        f"""\
[project]
name = "analysis"
version = "0.0.1"
    dependencies = [
      "marimo-studio=={version("marimo-studio")}",
      "example-suite==1.0.0",
    ]

[tool.marimo-studio]
notebook = "{notebook_path.name}"
default = "dashboard"
""",
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
        "create_environment_flag_builder",
        lambda: inline_flags,
    )

    command = environment_command(load_studio(notebook_path), ["python", "-V"])

    assert captured == {
        "launch_requirements": (
            f"marimo-studio[deno]=={version('marimo-studio')}",
            "example-suite==1.0.0",
        ),
        "compose_project": True,
    }
    source_root = environment_module.package_source_root()
    assert source_root is not None
    assert command[command.index("--with-editable") + 1] == str(source_root)
    assert command[command.index("--") + 1 :] == ["python", "-V"]


def test_installed_wheel_reentry_installs_the_invoking_wheel(
    notebook_path: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepare_view(notebook_path)
    wheel = tmp_path / f"marimo_studio-{version('marimo-studio')}-py3-none-any.whl"
    wheel.write_bytes(b"")
    monkeypatch.setattr(environment_module, "package_source_root", lambda: None)
    monkeypatch.setattr(
        environment_module,
        "invoking_studio",
        lambda: InvokingStudio(version("marimo-studio"), url=wheel.as_uri()),
    )
    monkeypatch.setattr(environment_module.shutil, "which", lambda _: "/usr/bin/uv")
    monkeypatch.setattr(
        environment_module,
        "create_environment_flag_builder",
        lambda: lambda *_args, **_kwargs: [],
    )

    command = environment_command(load_studio(notebook_path), ["python", "-V"])

    assert ["--with", f"marimo-studio @ {wheel.as_uri()}"] in [
        list(pair) for pair in pairwise(command)
    ]
    assert "--with-editable" not in command
    assert command[command.index("--") + 1 :] == ["python", "-V"]
