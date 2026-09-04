"""Verify saved views bootstrap their provider environment from a base install."""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import os
import subprocess
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

import marimo_studio.authoring as studio_authoring
import tomlkit
from marimo_studio._workspace.metadata import read_notebook_metadata
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

_EXTERNAL_DISTRIBUTION = "marimo-studio-e2e-provider"
_NOTEBOOK = """import marimo

app = marimo.App()

@app.cell
def values():
    title = "Provider bootstrap"
    metric = 42
    title
    return metric, title

if __name__ == "__main__":
    app.run()
"""
_STARTERS = (
    ("dashboard", "marimo-studio/react:default"),
    ("web", "marimo-studio-e2e-provider/web:default"),
)


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify provider bootstrap from saved workspace metadata.",
    )
    parser.add_argument("action", choices=("prepare", "verify"))
    parser.add_argument("root", type=Path)
    return parser.parse_args()


def _requirements(notebook: Path) -> dict[str, Requirement]:
    metadata = read_notebook_metadata(notebook) or {}
    dependencies = metadata.get("dependencies", ())
    if not isinstance(dependencies, list) or not all(
        isinstance(value, str) for value in dependencies
    ):
        raise AssertionError("Prepared notebook dependencies are invalid")
    return {
        canonicalize_name(requirement.name): requirement
        for value in dependencies
        if (requirement := Requirement(value))
    }


async def _prepare(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=False)
    notebook = root / "analysis.py"
    notebook.write_text(_NOTEBOOK, encoding="utf-8")
    for view_name, starter_id in _STARTERS:
        workspace = studio_authoring.open_workspace(notebook)
        starters = {starter.id: starter for starter in await workspace.starters()}
        starter = starters.get(starter_id)
        if starter is None or not starter.availability.available:
            raise AssertionError(f"Installed starter is unavailable: {starter_id}")
        await workspace.create_view(view_name, starter=starter)

    requirements = _requirements(notebook)
    studio = requirements[canonicalize_name("marimo-studio")]
    if str(studio.specifier) != f"=={version('marimo-studio')}":
        raise AssertionError(f"Studio dependency is not exact: {studio}")
    if studio.extras != {"deno"}:
        raise AssertionError(f"Deno view did not record its extra: {studio}")
    external = requirements[canonicalize_name(_EXTERNAL_DISTRIBUTION)]
    if str(external.specifier) != f"=={version(_EXTERNAL_DISTRIBUTION)}":
        raise AssertionError(f"External provider dependency is not exact: {external}")
    studio_wheel = Path(os.environ["MARIMO_STUDIO_ACCEPTANCE_STUDIO_WHEEL"])
    provider_wheel = Path(os.environ["MARIMO_STUDIO_ACCEPTANCE_PROVIDER_WHEEL"])
    if not studio_wheel.is_file() or not provider_wheel.is_file():
        raise AssertionError("Provider bootstrap wheel source is unavailable")
    document = tomlkit.document()
    project = tomlkit.table()
    project["name"] = "provider-bootstrap-acceptance"
    project["version"] = "0.0.0"
    project["requires-python"] = ">=3.10,<3.15"
    project["dependencies"] = [str(studio), str(external)]
    document["project"] = project
    tool = tomlkit.table()
    uv = tomlkit.table()
    sources = tomlkit.table()
    for name, path in (
        ("marimo-studio", studio_wheel),
        (_EXTERNAL_DISTRIBUTION, provider_wheel),
    ):
        source = tomlkit.inline_table()
        source["path"] = str(path.resolve())
        sources[name] = source
    uv["sources"] = sources
    age_exclusions = tomlkit.inline_table()
    age_exclusions["marimo-export"] = False
    uv["exclude-newer-package"] = age_exclusions
    tool["uv"] = uv
    document["tool"] = tool
    (root / "pyproject.toml").write_text(tomlkit.dumps(document), encoding="utf-8")


def _assert_optional_providers_absent() -> None:
    if importlib.util.find_spec("deno") is not None:
        raise AssertionError("Base Studio environment contains the Deno package")
    try:
        version(_EXTERNAL_DISTRIBUTION)
    except PackageNotFoundError:
        return
    raise AssertionError("Base Studio environment contains the external provider")


def _run(
    *arguments: str,
    input_text: str | None = None,
) -> dict[str, object]:
    input_bytes = input_text.encode("utf-8") if input_text is not None else None
    completed = subprocess.run(
        ["marimo-studio", *arguments, "--json"],
        check=False,
        capture_output=True,
        input=input_bytes,
        timeout=180,
    )
    stdout = completed.stdout.decode("utf-8")
    stderr = completed.stderr.decode("utf-8")
    if completed.returncode != 0:
        raise AssertionError(
            f"Installed command failed: {' '.join(arguments)}\n{stdout}{stderr}"
        )
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError as error:
        raise AssertionError(
            f"Installed command returned invalid JSON: {stdout!r}"
        ) from error
    if not isinstance(payload, dict):
        raise TypeError("Installed command returned a non-object JSON result")
    return payload


def _verify(root: Path) -> None:
    notebook = root / "analysis.py"
    _assert_optional_providers_absent()
    expected = {
        f"marimo-studio[deno]=={version('marimo-studio')}",
        f"{_EXTERNAL_DISTRIBUTION}==1.0.0",
    }
    created = _run(
        "view",
        "create",
        "appendix",
        "--starter",
        "marimo-studio/vanilla:default",
        "--target",
        str(notebook),
    )
    created_requirements = created.get("launch_requirements")
    if not isinstance(created_requirements, list) or not all(
        isinstance(value, str) for value in created_requirements
    ):
        raise TypeError("View creation returned invalid launch requirements")
    if (
        created.get("view") != "appendix"
        or created.get("provider") != "marimo-studio/vanilla"
        or set(created_requirements) != expected
    ):
        raise AssertionError(f"Unexpected bootstrapped creation result: {created}")
    status = _run("status", "--target", str(notebook))
    launch_requirements = status.get("launch_requirements")
    if not isinstance(launch_requirements, list) or not all(
        isinstance(value, str) for value in launch_requirements
    ):
        raise TypeError("Status returned invalid launch requirements")
    if set(launch_requirements) != expected:
        raise AssertionError(
            f"Unexpected bootstrapped launch requirements: {launch_requirements!r}"
        )
    views = status.get("views")
    if not isinstance(views, list) or not all(isinstance(view, dict) for view in views):
        raise TypeError("Status returned invalid views")
    providers = {view.get("name"): view.get("provider") for view in views}
    if providers != {
        "appendix": "marimo-studio/vanilla",
        "dashboard": "marimo-studio/react",
        "web": "marimo-studio-e2e-provider/web",
    }:
        raise AssertionError(f"Unexpected bootstrapped providers: {providers}")

    inspection = _run(
        "view",
        "inspect",
        "dashboard",
        "--target",
        str(notebook),
    )
    if (
        inspection.get("view") != "dashboard"
        or inspection.get("provider") != "marimo-studio/react"
        or inspection.get("diagnostics") != []
    ):
        raise AssertionError(f"Unexpected Deno inspection result: {inspection}")
    inspection_documents = inspection.get("documents")
    if not isinstance(inspection_documents, list) or "src/App.tsx" not in {
        item.get("path") for item in inspection_documents if isinstance(item, dict)
    }:
        raise AssertionError(f"Deno source documents are unavailable: {inspection}")
    document = _run(
        "view",
        "read",
        "web",
        "src/app.css",
        "--target",
        str(notebook),
    )
    content = document.get("content")
    revision = document.get("revision")
    catalog_generation = document.get("catalog_generation")
    view_generation = document.get("view_generation")
    if (
        document.get("path") != "src/app.css"
        or document.get("access") != "edit"
        or not isinstance(content, str)
        or not content
        or not isinstance(revision, str)
        or not isinstance(catalog_generation, str)
        or not isinstance(view_generation, str)
    ):
        raise AssertionError(f"Unexpected external document result: {document}")
    updated_content = content + "\n"
    written = _run(
        "view",
        "write",
        "web",
        "src/app.css",
        "--expected-revision",
        revision,
        "--catalog-generation",
        catalog_generation,
        "--view-generation",
        view_generation,
        "--from",
        "-",
        "--target",
        str(notebook),
        input_text=updated_content,
    )
    if written.get("content") != updated_content or written.get("revision") == revision:
        raise AssertionError(f"Unexpected external write result: {written}")
    reread = _run(
        "view",
        "read",
        "web",
        "src/app.css",
        "--target",
        str(notebook),
    )
    if reread.get("content") != updated_content or reread.get(
        "revision"
    ) != written.get("revision"):
        raise AssertionError(f"External write was not durable: {reread}")

    validation = _run(
        "validate",
        "--target",
        str(notebook),
        "--level",
        "static",
    )
    if validation.get("ok") is not True:
        raise AssertionError(f"Static validation failed: {validation}")
    build = _run(
        "view",
        "build",
        "dashboard",
        "--target",
        str(notebook),
        "--profile",
        "production",
    )
    if (
        build.get("view") != "dashboard"
        or build.get("profile") != "production"
        or not isinstance(build.get("revision"), str)
    ):
        raise AssertionError(f"Unexpected Deno build result: {build}")
    output = root / "export"
    exported = _run(
        "view",
        "export",
        "web",
        "--target",
        str(notebook),
        "--output",
        str(output),
        "--runtime",
        "wasm",
    )
    entrypoint = exported.get("entrypoint")
    if (
        exported.get("view") != "web"
        or exported.get("runtime") != "wasm"
        or not isinstance(entrypoint, str)
        or not Path(entrypoint).is_file()
    ):
        raise AssertionError(f"Unexpected external export result: {exported}")
    _assert_optional_providers_absent()


def main() -> None:
    args = _arguments()
    root = args.root.resolve()
    if args.action == "prepare":
        asyncio.run(_prepare(root))
    else:
        _verify(root)


if __name__ == "__main__":
    main()
