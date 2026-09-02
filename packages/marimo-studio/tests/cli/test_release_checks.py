"""Protect the release gate through its shell command boundary."""

from __future__ import annotations

import os
import stat
import subprocess
import sys
from hashlib import sha256
from pathlib import Path

import pytest

pytestmark = [
    pytest.mark.skipif(
        os.name == "nt",
        reason="Release shell scripts require a POSIX process environment",
    ),
]

_ROOT = Path(__file__).resolve().parents[4]
_SCRIPT = _ROOT / "scripts" / "require-release-checks.sh"
_COMMIT = "a" * 40
_GH = """#!/bin/sh
workflow="unknown"
branch=""
commit=""
event=""
if [ "$1" != "run" ] || [ "$2" != "list" ]; then exit 90; fi
shift 2
while [ "$#" -gt 0 ]; do
  case "$1" in
    --workflow) shift; workflow="$1" ;;
    --branch) shift; branch="$1" ;;
    --commit) shift; commit="$1" ;;
    --event) shift; event="$1" ;;
    --limit|--json|--jq) shift ;;
    *) exit 91 ;;
  esac
  shift
done
if [ "$branch" != "main" ] ||
  [ "$commit" != "$EXPECTED_COMMIT" ] ||
  [ "$event" != "push" ]; then
  exit 92
fi
printf '%s|%s|%s|%s\n' "$workflow" "$branch" "$commit" "$event" >> "$GH_CALLS"
case "$CHECK_STATE" in
  missing) exit 0 ;;
  pending) printf '123\nin_progress\n\nhttps://example.test/%s\n' "$workflow" ;;
  failed) printf '123\ncompleted\nfailure\nhttps://example.test/%s\n' "$workflow" ;;
  success) printf '123\ncompleted\nsuccess\nhttps://example.test/%s\n' "$workflow" ;;
esac
"""


@pytest.mark.parametrize(
    ("state", "returncode", "message"),
    (
        ("missing", 1, "No CI run found"),
        ("pending", 1, "in_progress/pending"),
        ("failed", 1, "completed/failure"),
        ("success", 0, "Browser acceptance: https://example.test/e2e.yml"),
    ),
)
def test_release_checks_require_successful_runs_for_the_release_commit(
    tmp_path: Path,
    state: str,
    returncode: int,
    message: str,
) -> None:
    binary = tmp_path / "gh"
    calls = tmp_path / "gh-calls"
    binary.write_text(_GH, encoding="utf-8")
    binary.chmod(binary.stat().st_mode | stat.S_IXUSR)

    completed = subprocess.run(
        [_SCRIPT, _COMMIT],
        capture_output=True,
        text=True,
        check=False,
        env={
            **os.environ,
            "CHECK_STATE": state,
            "EXPECTED_COMMIT": _COMMIT,
            "GH_CALLS": str(calls),
            "PATH": f"{tmp_path}{os.pathsep}{os.environ['PATH']}",
        },
    )

    assert completed.returncode == returncode
    assert message in f"{completed.stdout}{completed.stderr}"
    if state == "success":
        assert calls.read_text(encoding="utf-8").splitlines() == [
            f"ci.yml|main|{_COMMIT}|push",
            f"e2e.yml|main|{_COMMIT}|push",
            f"pages.yml|main|{_COMMIT}|push",
        ]


def test_release_checks_reject_an_ambiguous_commit_reference() -> None:
    completed = subprocess.run(
        [_SCRIPT, "main"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 2
    assert "40-character-commit-sha" in completed.stderr


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def _release_workspace(tmp_path: Path, script: str) -> tuple[Path, Path]:
    root = tmp_path / "repo"
    scripts = root / "scripts"
    binaries = root / "bin"
    scripts.mkdir(parents=True)
    binaries.mkdir()
    target = scripts / script
    _write_executable(target, (_ROOT / "scripts" / script).read_text(encoding="utf-8"))
    return target, binaries


def test_pypi_verification_reuses_the_successful_poll_result(tmp_path: Path) -> None:
    script, binaries = _release_workspace(tmp_path, "verify-pypi.sh")
    probe_count = tmp_path / "probe-count"
    calls = tmp_path / "uv-calls"
    _write_executable(
        binaries / "uv",
        """#!/bin/sh
printf '%s\n' "$*" >> "$UV_CALLS"
case "$*" in
  *"python -c "*)
    count=0
    if [ -f "$PROBE_COUNT" ]; then count=$(cat "$PROBE_COUNT"); fi
    count=$((count + 1))
    printf '%s\n' "$count" > "$PROBE_COUNT"
    [ "$count" -eq 1 ] || exit 98
    ;;
esac
""",
    )

    completed = subprocess.run(
        [script],
        capture_output=True,
        text=True,
        check=False,
        cwd=script.parents[1],
        env={
            **os.environ,
            "PATH": f"{binaries}{os.pathsep}{os.environ['PATH']}",
            "PROBE_COUNT": str(probe_count),
            "RELEASE_VERSION": "0.1.0",
            "UV_CALLS": str(calls),
        },
    )

    assert completed.returncode == 0, completed.stderr
    assert probe_count.read_text(encoding="utf-8").strip() == "1"
    commands = calls.read_text(encoding="utf-8").splitlines()
    assert sum("python -c " in command for command in commands) == 1
    assert sum("verify-installed-package.py" in command for command in commands) == 2
    assert sum("marimo-studio[deno]==0.1.0" in command for command in commands) == 1


def test_distribution_checksums_cover_release_artifacts(tmp_path: Path) -> None:
    wheel = tmp_path / "marimo_studio-0.1.0-py3-none-any.whl"
    sdist = tmp_path / "marimo_studio-0.1.0.tar.gz"
    wheel.write_bytes(b"wheel")
    sdist.write_bytes(b"source")

    completed = subprocess.run(
        [sys.executable, _ROOT / "scripts" / "write-dist-checksums.py", tmp_path],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert tmp_path.joinpath("SHA256SUMS").read_text(encoding="utf-8").splitlines() == [
        f"{sha256(wheel.read_bytes()).hexdigest()}  {wheel.name}",
        f"{sha256(sdist.read_bytes()).hexdigest()}  {sdist.name}",
    ]


def test_release_dry_run_checks_the_exact_main_commit_without_tagging(
    tmp_path: Path,
) -> None:
    script, binaries = _release_workspace(tmp_path, "release.sh")
    root = script.parents[1]
    command_log = root / "commands"
    release_notes = root / ".github" / "release-notes" / "v0.1.0.md"
    release_notes.parent.mkdir(parents=True)
    release_notes.write_text("release notes\n", encoding="utf-8")
    _write_executable(
        binaries / "git",
        """#!/bin/sh
printf '%s\n' "$*" >> "$COMMAND_LOG"
case "$*" in
  "branch --show-current") printf 'main\n' ;;
  "status --porcelain") ;;
  "fetch origin main --tags") ;;
  "rev-parse HEAD"|"rev-parse origin/main") printf '%s\n' "$EXPECTED_COMMIT" ;;
  "rev-parse -q --verify refs/tags/v0.1.0") exit 1 ;;
  tag*|push*) exit 93 ;;
  *) exit 94 ;;
esac
""",
    )
    _write_executable(
        binaries / "uv",
        """#!/bin/sh
[ "$*" = "version --package marimo-studio --short" ] || exit 95
printf '0.1.0\n'
""",
    )
    _write_executable(
        binaries / "gh",
        """#!/bin/sh
[ "$*" = "repo view --json url --jq .url" ] || exit 96
printf 'https://example.test/repo\n'
""",
    )
    _write_executable(
        root / "scripts" / "require-release-checks.sh",
        """#!/bin/sh
[ "$1" = "$EXPECTED_COMMIT" ] || exit 97
printf 'CI: https://example.test/ci\nBrowser acceptance: https://example.test/e2e\n'
printf 'Documentation: https://example.test/pages\n'
""",
    )

    completed = subprocess.run(
        [script, "--dry-run"],
        capture_output=True,
        text=True,
        check=False,
        env={
            **os.environ,
            "COMMAND_LOG": str(command_log),
            "EXPECTED_COMMIT": _COMMIT,
            "PATH": f"{binaries}{os.pathsep}{os.environ['PATH']}",
        },
    )

    assert completed.returncode == 0, completed.stderr
    assert f"Commit:  {_COMMIT}" in completed.stdout
    assert "Documentation: https://example.test/pages" in completed.stdout
    assert "Dry run complete" in completed.stdout
    commands = command_log.read_text(encoding="utf-8").splitlines()
    assert "fetch origin main --tags" in commands
    assert not any(command.startswith(("tag ", "push ")) for command in commands)


@pytest.mark.parametrize(
    ("package_version", "tag_type", "tag_commit", "sha", "ancestor", "message"),
    (
        ("0.1.0", "tag", _COMMIT, _COMMIT, "yes", ""),
        ("0.1.1", "tag", _COMMIT, _COMMIT, "yes", "does not match tag"),
        ("0.1.0", "commit", _COMMIT, _COMMIT, "yes", "must be annotated"),
        ("0.1.0", "tag", "b" * 40, _COMMIT, "yes", "does not match tag commit"),
        ("0.1.0", "tag", _COMMIT, _COMMIT, "no", "not on origin/main"),
    ),
)
def test_publish_gate_checks_version_tag_sha_and_main_ancestry(
    tmp_path: Path,
    package_version: str,
    tag_type: str,
    tag_commit: str,
    sha: str,
    ancestor: str,
    message: str,
) -> None:
    script, binaries = _release_workspace(tmp_path, "check-release.sh")
    root = script.parents[1]
    release_checks = root / "release-checks"
    release_notes = root / ".github" / "release-notes" / "v0.1.0.md"
    release_notes.parent.mkdir(parents=True)
    release_notes.write_text("release notes\n", encoding="utf-8")
    _write_executable(
        binaries / "uv",
        """#!/bin/sh
[ "$*" = "version --package marimo-studio --short" ] || exit 95
printf '%s\n' "$PACKAGE_VERSION"
""",
    )
    _write_executable(
        binaries / "git",
        """#!/bin/sh
case "$1 $2" in
  "cat-file -t") printf '%s\n' "$TAG_TYPE" ;;
  "rev-list -n") printf '%s\n' "$TAG_COMMIT" ;;
  "merge-base --is-ancestor")
    if [ "$ANCESTOR" = "yes" ]; then exit 0; fi
    exit 1
    ;;
  *) exit 94 ;;
esac
""",
    )
    _write_executable(
        root / "scripts" / "require-release-checks.sh",
        """#!/bin/sh
printf '%s\n' "$1" > "$RELEASE_CHECKS"
""",
    )

    completed = subprocess.run(
        [script],
        capture_output=True,
        text=True,
        check=False,
        cwd=root,
        env={
            **os.environ,
            "ANCESTOR": ancestor,
            "GITHUB_REF": "refs/tags/v0.1.0",
            "GITHUB_REF_NAME": "v0.1.0",
            "GITHUB_SHA": sha,
            "PACKAGE_VERSION": package_version,
            "PATH": f"{binaries}{os.pathsep}{os.environ['PATH']}",
            "RELEASE_CHECKS": str(release_checks),
            "TAG_COMMIT": tag_commit,
            "TAG_TYPE": tag_type,
        },
    )

    if not message:
        assert completed.returncode == 0, completed.stderr
        assert release_checks.read_text(encoding="utf-8").strip() == _COMMIT
    else:
        assert completed.returncode != 0
        assert message in f"{completed.stdout}{completed.stderr}"
        assert not release_checks.exists()
