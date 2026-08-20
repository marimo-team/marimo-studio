from __future__ import annotations

import base64
import importlib.util
import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any
from urllib.error import URLError

import pytest

ROOT = Path(__file__).resolve().parents[3]
VERSION = "0.1.0"
PYPI_SDIST = "https://files.pythonhosted.org/packages/aa/marimo_export-0.1.0.tar.gz"
PYPI_WHEEL = (
    "https://files.pythonhosted.org/packages/bb/marimo_export-0.1.0-py3-none-any.whl"
)
PYPI_SDIST_SHA256 = "a" * 64
PYPI_WHEEL_SHA256 = "b" * 64
NPM_INTEGRITIES = {
    "@marimo-team/marimo-export": "sha512-"
    + base64.b64encode(b"export".ljust(64, b".")).decode("ascii"),
    "@marimo-team/portable-json": "sha512-"
    + base64.b64encode(b"portable-json".ljust(64, b".")).decode("ascii"),
}


def _load_release_dependencies() -> ModuleType:
    path = ROOT / "scripts/check-release-dependencies.py"
    spec = importlib.util.spec_from_file_location("studio_release_dependencies", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


release_dependencies = _load_release_dependencies()


def _write_release_locks(
    root: Path,
    *,
    python_registry: str = "https://pypi.org/simple",
    python_sdist_url: str = PYPI_SDIST,
    npm_integrities: dict[str, str] = NPM_INTEGRITIES,
    npm_tarball: str | None = None,
    npm_export_version: str = VERSION,
    include_export_integrity: bool = True,
) -> None:
    export_integrity = npm_integrities["@marimo-team/marimo-export"]
    portable_integrity = npm_integrities["@marimo-team/portable-json"]
    export_resolution = []
    if include_export_integrity:
        export_resolution.append(f"integrity: {export_integrity}")
    if npm_tarball:
        export_resolution.append(f"tarball: {npm_tarball}")
    export_resolution_text = ", ".join(export_resolution)
    root.joinpath("uv.lock").write_text(
        f'''version = 1

[[package]]
name = "marimo-export"
version = "{VERSION}"
source = {{ registry = "{python_registry}" }}
sdist = {{ url = "{python_sdist_url}", hash = "sha256:{PYPI_SDIST_SHA256}" }}
wheels = [
    {{ url = "{PYPI_WHEEL}", hash = "sha256:{PYPI_WHEEL_SHA256}" }},
]
''',
        encoding="utf-8",
    )
    root.joinpath("pnpm-lock.yaml").write_text(
        f"""lockfileVersion: '9.0'

importers:
  packages/presentation:
    dependencies:
      '@marimo-team/marimo-export':
        specifier: {VERSION}
        version: {npm_export_version}
      '@marimo-team/portable-json':
        specifier: {VERSION}
        version: {VERSION}

packages:
  '@marimo-team/marimo-export@{VERSION}':
    resolution: {{{export_resolution_text}}}

  '@marimo-team/portable-json@{VERSION}':
    resolution: {{integrity: {portable_integrity}}}
""",
        encoding="utf-8",
    )


def _public_metadata() -> dict[str, dict[str, Any]]:
    metadata: dict[str, dict[str, Any]] = {
        f"https://pypi.org/pypi/marimo-export/{VERSION}/json": {
            "info": {"name": "marimo-export", "version": VERSION},
            "urls": [
                {"url": PYPI_SDIST, "digests": {"sha256": PYPI_SDIST_SHA256}},
                {"url": PYPI_WHEEL, "digests": {"sha256": PYPI_WHEEL_SHA256}},
            ],
        }
    }
    for name, integrity in NPM_INTEGRITIES.items():
        encoded = name.replace("@", "%40").replace("/", "%2F")
        basename = name.rsplit("/", maxsplit=1)[-1]
        metadata[f"https://registry.npmjs.org/{encoded}/{VERSION}"] = {
            "name": name,
            "version": VERSION,
            "dist": {
                "integrity": integrity,
                "tarball": (
                    f"https://registry.npmjs.org/{name}/-/{basename}-{VERSION}.tgz"
                ),
            },
        }
    return metadata


def _fetcher(metadata: dict[str, dict[str, Any]]):
    def fetch(url: str, _label: str) -> Any:
        return metadata[url]

    return fetch


def test_release_artifacts_match_canonical_public_metadata(tmp_path: Path) -> None:
    _write_release_locks(tmp_path)
    locks = release_dependencies._release_locks(tmp_path, VERSION)

    release_dependencies._public_versions(
        VERSION,
        locks,
        fetch_json=_fetcher(_public_metadata()),
    )


def test_release_lock_resolves_peer_context_from_the_base_package(
    tmp_path: Path,
) -> None:
    _write_release_locks(
        tmp_path,
        npm_export_version=f"{VERSION}(zod@4.3.6)",
    )

    locks = release_dependencies._release_locks(tmp_path, VERSION)

    assert (
        dict(locks.npm_integrities)["@marimo-team/marimo-export"]
        == (NPM_INTEGRITIES["@marimo-team/marimo-export"])
    )


def test_release_lock_rejects_malformed_peer_context(tmp_path: Path) -> None:
    _write_release_locks(
        tmp_path,
        npm_export_version=f"{VERSION}(zod@4.3.6",
    )

    with pytest.raises(RuntimeError, match="must resolve public"):
        release_dependencies._release_locks(tmp_path, VERSION)


def test_peer_context_requires_the_base_package_integrity(tmp_path: Path) -> None:
    _write_release_locks(
        tmp_path,
        npm_export_version=f"{VERSION}(zod@4.3.6)",
        include_export_integrity=False,
    )

    with pytest.raises(RuntimeError, match="must record the registry integrity"):
        release_dependencies._release_locks(tmp_path, VERSION)


def test_peer_context_integrity_must_match_public_metadata(tmp_path: Path) -> None:
    malicious_integrities = {
        **NPM_INTEGRITIES,
        "@marimo-team/marimo-export": "sha512-"
        + base64.b64encode(b"malicious".ljust(64, b".")).decode("ascii"),
    }
    _write_release_locks(
        tmp_path,
        npm_export_version=f"{VERSION}(zod@4.3.6)",
        npm_integrities=malicious_integrities,
    )
    locks = release_dependencies._release_locks(tmp_path, VERSION)

    with pytest.raises(RuntimeError, match=r"pnpm-lock\.yaml integrity"):
        release_dependencies._public_versions(
            VERSION,
            locks,
            fetch_json=_fetcher(_public_metadata()),
        )


def test_release_lock_rejects_a_noncanonical_python_registry(tmp_path: Path) -> None:
    _write_release_locks(tmp_path, python_registry="https://packages.example/simple")

    with pytest.raises(RuntimeError, match=r"https://pypi\.org/simple"):
        release_dependencies._release_locks(tmp_path, VERSION)


def test_release_lock_rejects_a_noncanonical_python_artifact(tmp_path: Path) -> None:
    _write_release_locks(
        tmp_path,
        python_sdist_url="https://packages.example/marimo_export-0.1.0.tar.gz",
    )

    with pytest.raises(RuntimeError, match=r"files\.pythonhosted\.org"):
        release_dependencies._release_locks(tmp_path, VERSION)


def test_release_lock_rejects_a_noncanonical_npm_tarball(tmp_path: Path) -> None:
    _write_release_locks(
        tmp_path,
        npm_tarball="https://packages.example/marimo-export-0.1.0.tgz",
    )

    with pytest.raises(RuntimeError, match="canonical npm tarball"):
        release_dependencies._release_locks(tmp_path, VERSION)


def test_public_metadata_rejects_a_noncanonical_python_artifact(
    tmp_path: Path,
) -> None:
    _write_release_locks(tmp_path)
    locks = release_dependencies._release_locks(tmp_path, VERSION)
    metadata = _public_metadata()
    metadata[f"https://pypi.org/pypi/marimo-export/{VERSION}/json"]["urls"][0][
        "url"
    ] = "https://packages.example/marimo_export-0.1.0.tar.gz"

    with pytest.raises(RuntimeError, match=r"files\.pythonhosted\.org"):
        release_dependencies._public_versions(
            VERSION,
            locks,
            fetch_json=_fetcher(metadata),
        )


def test_public_metadata_rejects_a_noncanonical_npm_tarball(tmp_path: Path) -> None:
    _write_release_locks(tmp_path)
    locks = release_dependencies._release_locks(tmp_path, VERSION)
    metadata = _public_metadata()
    url = f"https://registry.npmjs.org/%40marimo-team%2Fmarimo-export/{VERSION}"
    metadata[url]["dist"]["tarball"] = (
        "https://packages.example/marimo-export-0.1.0.tgz"
    )

    with pytest.raises(RuntimeError, match="canonical npm tarball"):
        release_dependencies._public_versions(
            VERSION,
            locks,
            fetch_json=_fetcher(metadata),
        )


@pytest.mark.parametrize("ecosystem", ["pypi", "npm"])
def test_public_metadata_must_match_the_locked_digest(
    tmp_path: Path, ecosystem: str
) -> None:
    _write_release_locks(tmp_path)
    locks = release_dependencies._release_locks(tmp_path, VERSION)
    metadata = _public_metadata()
    if ecosystem == "pypi":
        metadata[f"https://pypi.org/pypi/marimo-export/{VERSION}/json"]["urls"][0][
            "digests"
        ]["sha256"] = "c" * 64
        expected = "uv.lock SHA-256"
    else:
        url = f"https://registry.npmjs.org/%40marimo-team%2Fmarimo-export/{VERSION}"
        metadata[url]["dist"]["integrity"] = "sha512-" + base64.b64encode(
            b"different".ljust(64, b".")
        ).decode("ascii")
        expected = "pnpm-lock.yaml integrity"

    with pytest.raises(RuntimeError, match=expected):
        release_dependencies._public_versions(
            VERSION,
            locks,
            fetch_json=_fetcher(metadata),
        )


def test_public_metadata_reports_transient_network_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unavailable(_url: str, *, timeout: int) -> None:
        assert timeout == 20
        raise URLError("temporary DNS failure")

    monkeypatch.setattr(release_dependencies, "urlopen", unavailable)

    with pytest.raises(RuntimeError, match="before dependency installation"):
        release_dependencies._public_json("https://pypi.org/example", "example")


def test_workspace_policy_exempts_exact_coordinated_releases() -> None:
    release_dependencies._workspace_policy(ROOT, VERSION)
    scoped = {
        value
        for value in release_dependencies._workspace_release_age_exclusions(ROOT)
        if value.startswith("@marimo-team/")
    }
    assert scoped == {f"{name}@{VERSION}" for name in NPM_INTEGRITIES}


def _git(root: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", *arguments],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _release_repository(root: Path, *, tag_is_ancestor: bool) -> tuple[str, str]:
    _git(root, "init")
    _git(root, "config", "user.email", "release@example.com")
    _git(root, "config", "user.name", "Studio Release")
    root.joinpath("release.txt").write_text("release\n", encoding="utf-8")
    _git(root, "add", "release.txt")
    _git(root, "commit", "-m", "release")
    tag_commit = _git(root, "rev-parse", "HEAD")
    _git(root, "tag", "-a", "v0.1.0", "-m", "release: 0.1.0")
    if tag_is_ancestor:
        root.joinpath("release.txt").write_text("new main\n", encoding="utf-8")
        _git(root, "add", "release.txt")
        _git(root, "commit", "-m", "advance main")
    main_commit = _git(root, "rev-parse", "HEAD")
    _git(root, "update-ref", "refs/remotes/origin/main", main_commit)
    return tag_commit, main_commit


def _write_command(path: Path, source: str) -> None:
    path.write_text(source, encoding="utf-8")
    path.chmod(0o755)


def _run_release_check(
    root: Path,
    tag_commit: str,
    *,
    ci_run: str,
) -> subprocess.CompletedProcess[str]:
    commands = root / "commands"
    commands.mkdir()
    marker = root / "dependency-check-ran"
    _write_command(
        commands / "uv",
        "#!/bin/sh\nprintf '0.1.0\\n'\n",
    )
    _write_command(
        commands / "python3",
        '#!/bin/sh\nprintf "checked\\n" > "$DEPENDENCY_CHECK_MARKER"\n',
    )
    _write_command(
        commands / "gh",
        '#!/bin/sh\nprintf "%s" "$FAKE_CI_RUN"\n',
    )
    environment = {
        **os.environ,
        "DEPENDENCY_CHECK_MARKER": str(marker),
        "FAKE_CI_RUN": ci_run,
        "GH_TOKEN": "test-token",
        "GITHUB_REF": "refs/tags/v0.1.0",
        "GITHUB_REF_NAME": "v0.1.0",
        "GITHUB_SHA": tag_commit,
        "PATH": f"{commands}{os.pathsep}{os.environ['PATH']}",
    }
    return subprocess.run(
        [str(ROOT / "scripts/check-release.sh")],
        cwd=root,
        env=environment,
        capture_output=True,
        text=True,
    )


def test_publish_preflight_rejects_an_ancestor_tag(tmp_path: Path) -> None:
    tag_commit, main_commit = _release_repository(tmp_path, tag_is_ancestor=True)

    result = _run_release_check(
        tmp_path,
        tag_commit,
        ci_run="completed\nsuccess\nhttps://example.test/ci\n",
    )

    assert result.returncode == 1
    assert f"must point to current origin/main {main_commit}" in result.stderr
    assert not tmp_path.joinpath("dependency-check-ran").exists()


def test_publish_preflight_requires_successful_exact_commit_ci(tmp_path: Path) -> None:
    tag_commit, _main_commit = _release_repository(tmp_path, tag_is_ancestor=False)

    result = _run_release_check(
        tmp_path,
        tag_commit,
        ci_run="completed\nfailure\nhttps://example.test/ci\n",
    )

    assert result.returncode == 1
    assert "Main CI must pass for release commit" in result.stderr
    assert not tmp_path.joinpath("dependency-check-ran").exists()


def test_publish_preflight_checks_dependencies_after_commit_ci(tmp_path: Path) -> None:
    tag_commit, _main_commit = _release_repository(tmp_path, tag_is_ancestor=False)

    result = _run_release_check(
        tmp_path,
        tag_commit,
        ci_run="completed\nsuccess\nhttps://example.test/ci\n",
    )

    assert result.returncode == 0, result.stderr
    assert tmp_path.joinpath("dependency-check-ran").read_text(encoding="utf-8") == (
        "checked\n"
    )


def test_publish_workflow_runs_preflight_before_dependency_installation() -> None:
    workflow = ROOT.joinpath(".github/workflows/publish.yml").read_text(
        encoding="utf-8"
    )
    fetch_index = workflow.index("refs/remotes/origin/main")
    build_index = workflow.index("  build:")
    actions_permission_index = workflow.index("actions: read")
    step_index = workflow.index("- name: Verify release source and dependencies")
    token_index = workflow.index("GH_TOKEN: ${{ github.token }}")
    check_index = workflow.index("./scripts/check-release.sh")
    sync_index = workflow.index("uv sync --locked")

    assert workflow.count("actions: read") == 1
    assert build_index < actions_permission_index < fetch_index
    assert fetch_index < step_index < token_index < check_index < sync_index
