from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path, PurePosixPath

from marimo_studio._artifacts.repository import read_published_artifact
from marimo_studio._workspace import load_studio

PROFILES = ("development", "production")


def _run(*arguments: str, cwd: Path) -> None:
    result = subprocess.run(
        arguments,
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(f"{' '.join(arguments)} failed: {detail}")


def _copy_example(repository: Path, temporary: Path) -> Path:
    source = repository / "examples"
    target = temporary / "examples"
    target.mkdir()
    shutil.copy2(source / "nga.py", target / "nga.py")
    shutil.copytree(
        source / "__marimo__" / "studio" / "nga",
        target / "__marimo__" / "studio" / "nga",
        ignore=shutil.ignore_patterns(".artifacts", ".locks", "__pycache__"),
    )
    return target / "nga.py"


def main() -> None:
    repository = Path(__file__).resolve().parent.parent
    executable = Path(sys.executable).with_name("marimo-studio")
    if not executable.is_file():
        located = shutil.which("marimo-studio")
        if located is None:
            raise RuntimeError("marimo-studio is unavailable on PATH")
        executable = Path(located)
    with tempfile.TemporaryDirectory(prefix="marimo-studio-examples-") as directory:
        notebook = _copy_example(repository, Path(directory))
        _run("marimo", "check", str(notebook), cwd=repository)
        studio = load_studio(notebook)
        views = tuple(studio.views)
        if not views:
            raise RuntimeError("The NGA example contains no configured views")
        for view in views:
            for profile in PROFILES:
                _run(
                    str(executable),
                    "view",
                    "build",
                    view,
                    "--target",
                    str(notebook),
                    "--profile",
                    profile,
                    "--json",
                    cwd=repository,
                )
        for view in views:
            for profile in PROFILES:
                artifact = read_published_artifact(studio.views[view], profile)
                if artifact is None:
                    raise RuntimeError(f"{view}/{profile} did not publish an artifact")
                if view == "overview" and (
                    artifact.document != PurePosixPath("index.html")
                    or tuple(item.path for item in artifact.files)
                    != (PurePosixPath("index.html"),)
                ):
                    raise RuntimeError(
                        f"overview/{profile} must publish one HTML document"
                    )


if __name__ == "__main__":
    main()
