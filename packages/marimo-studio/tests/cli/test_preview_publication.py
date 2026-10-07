"""Protect preview publication through its shell command boundary."""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from packaging.version import Version

pytestmark = [
    pytest.mark.skipif(
        os.name == "nt",
        reason="Publication shell scripts require a POSIX process environment",
    ),
]

_ROOT = Path(__file__).resolve().parents[4]
_COMMIT = "a" * 40
_REPOSITORY = "marimo-team/marimo-studio"
_DOWNLOADS = f"https://github.com/{_REPOSITORY}/releases/download/preview"

# Keeps the preview release as JSON so tests can inspect what a reader of the
# GitHub release would see.
_GH = """#!{python}
import json
import os
import sys
from pathlib import Path

state = Path(os.environ["GH_STATE"])
release_path = state / "release.json"
comments_path = state / "comments.json"
args = sys.argv[1:]
repository = f"repos/{{os.environ['GH_REPO']}}"
pulls = f"{{repository}}/commits/{commit}/pulls"
comments_api = f"{{repository}}/issues/{{os.environ['MERGED_PULL']}}/comments"


def release():
    return json.loads(release_path.read_text())


def save(data):
    release_path.write_text(json.dumps(data))


def options(values):
    parsed = {{}}
    while values:
        flag = values.pop(0)
        parsed[flag] = True if flag in ("--prerelease", "--yes") else values.pop(0)
    return parsed


match args:
    case ["release", "view", "preview"]:
        sys.exit(0 if release_path.exists() else 1)
    case ["release", "view", "preview", "--json", "assets", "--jq", ".assets[].name"]:
        print("\\n".join(release()["assets"]))
    case ["release", "create", "preview", *rest]:
        parsed = options(rest)
        save(
            {{
                "assets": [],
                "notes": parsed["--notes"],
                "prerelease": parsed.get("--prerelease", False),
                "target": parsed["--target"],
                "title": parsed["--title"],
            }}
        )
    case ["release", "upload", "preview", path]:
        data = release()
        name = Path(path).name
        if name in data["assets"]:
            sys.exit(1)
        data["assets"].append(name)
        save(data)
    case ["release", "edit", "preview", "--notes-file", path]:
        data = release()
        data["notes"] = Path(path).read_text()
        save(data)
    case ["release", "delete-asset", "preview", name, "--yes"]:
        data = release()
        data["assets"].remove(name)
        save(data)
    case ["api", path, "--jq", _] if path == pulls:
        print(os.environ["MERGED_PULL"])
    case ["api", "--paginate", path, "--jq", ".[].body"] if path == comments_api:
        if comments_path.exists():
            for comment in json.loads(comments_path.read_text()):
                print(comment["body"])
    case ["pr", "comment", pull, "--body", body]:
        comments = []
        if comments_path.exists():
            comments = json.loads(comments_path.read_text())
        comments.append({{"pull": pull, "body": body}})
        comments_path.write_text(json.dumps(comments))
    case _:
        sys.exit(90)
"""


class _PreviewRelease:
    def __init__(self, root: Path, assets: list[str] | None = None) -> None:
        self.root = root
        self.state = root / "github"
        self.state.mkdir()
        binaries = root / "bin"
        binaries.mkdir()
        gh = binaries / "gh"
        gh.write_text(
            _GH.format(python=sys.executable, commit=_COMMIT), encoding="utf-8"
        )
        gh.chmod(gh.stat().st_mode | stat.S_IXUSR)
        self.path = f"{binaries}{os.pathsep}{os.environ['PATH']}"
        if assets is not None:
            self._write(
                {
                    "assets": assets,
                    "notes": "",
                    "prerelease": True,
                    "target": _COMMIT,
                    "title": "Preview builds",
                }
            )

    def publish(self, name: str) -> subprocess.CompletedProcess[str]:
        wheel = self.root / "dist" / name
        wheel.parent.mkdir(exist_ok=True)
        wheel.write_bytes(b"wheel")
        return subprocess.run(
            [_ROOT / "scripts" / "publish-preview.sh", wheel, _COMMIT],
            capture_output=True,
            text=True,
            check=False,
            env={
                **os.environ,
                "GH_REPO": _REPOSITORY,
                "GH_STATE": str(self.state),
                "GITHUB_SERVER_URL": "https://github.com",
                "MERGED_PULL": "42",
                "PATH": self.path,
            },
        )

    def release(self) -> dict[str, Any]:
        return json.loads((self.state / "release.json").read_text(encoding="utf-8"))

    def comments(self) -> list[dict[str, str]]:
        path = self.state / "comments.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else []

    def _write(self, release: dict[str, Any]) -> None:
        (self.state / "release.json").write_text(json.dumps(release), encoding="utf-8")


def _wheel(version: str) -> str:
    return f"marimo_studio-{version}-py3-none-any.whl"


def test_first_preview_creates_the_release_and_announces_the_wheel(
    tmp_path: Path,
) -> None:
    github = _PreviewRelease(tmp_path)

    completed = github.publish(_wheel("0.2.4.dev14"))

    assert completed.returncode == 0, completed.stderr
    release = github.release()
    url = f"{_DOWNLOADS}/{_wheel('0.2.4.dev14')}"
    assert release["prerelease"] is True
    assert release["target"] == _COMMIT
    assert release["assets"] == [_wheel("0.2.4.dev14")]
    assert f'uv tool install "marimo-studio @ {url}"' in release["notes"]
    assert f'# dependencies = ["marimo-studio @ {url}"]' in release["notes"]
    [comment] = github.comments()
    assert comment["pull"] == "42"
    assert f'uv tool install "marimo-studio @ {url}"' in comment["body"]


def test_preview_notes_describe_the_newest_wheel(tmp_path: Path) -> None:
    github = _PreviewRelease(tmp_path)

    assert github.publish(_wheel("0.2.4.dev15")).returncode == 0
    completed = github.publish(_wheel("0.2.4.dev9"))

    assert completed.returncode == 0, completed.stderr
    release = github.release()
    assert sorted(release["assets"]) == [_wheel("0.2.4.dev15"), _wheel("0.2.4.dev9")]
    assert f"{_DOWNLOADS}/{_wheel('0.2.4.dev15')}" in release["notes"]
    assert _wheel("0.2.4.dev9") not in release["notes"]


def test_preview_release_keeps_the_newest_thirty_wheels(tmp_path: Path) -> None:
    github = _PreviewRelease(
        tmp_path,
        assets=[_wheel(f"0.2.4.dev{number}") for number in range(1, 31)],
    )

    completed = github.publish(_wheel("0.2.4.dev31"))

    assert completed.returncode == 0, completed.stderr
    assets = github.release()["assets"]
    assert len(assets) == 30
    assert _wheel("0.2.4.dev1") not in assets
    assert _wheel("0.2.4.dev31") in assets


def test_republishing_a_preview_keeps_one_wheel_and_one_announcement(
    tmp_path: Path,
) -> None:
    github = _PreviewRelease(tmp_path)

    assert github.publish(_wheel("0.2.4.dev14")).returncode == 0
    completed = github.publish(_wheel("0.2.4.dev14"))

    assert completed.returncode == 0, completed.stderr
    assert github.release()["assets"] == [_wheel("0.2.4.dev14")]
    assert len(github.comments()) == 1


def test_rerun_announces_an_uploaded_wheel_the_pull_request_missed(
    tmp_path: Path,
) -> None:
    github = _PreviewRelease(tmp_path, assets=[_wheel("0.2.4.dev14")])

    completed = github.publish(_wheel("0.2.4.dev14"))

    assert completed.returncode == 0, completed.stderr
    assert github.release()["assets"] == [_wheel("0.2.4.dev14")]
    [comment] = github.comments()
    assert f"{_DOWNLOADS}/{_wheel('0.2.4.dev14')}" in comment["body"]


def test_preview_publication_rejects_release_wheels(tmp_path: Path) -> None:
    github = _PreviewRelease(tmp_path)

    completed = github.publish(_wheel("0.2.4"))

    assert completed.returncode == 1
    assert "Expected a marimo-studio preview wheel" in completed.stderr
    assert not (github.state / "release.json").exists()


def _git(repository: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        capture_output=True,
        text=True,
        check=True,
        cwd=repository,
        env={
            **os.environ,
            "GIT_AUTHOR_EMAIL": "studio@example.test",
            "GIT_AUTHOR_NAME": "Studio",
            "GIT_COMMITTER_EMAIL": "studio@example.test",
            "GIT_COMMITTER_NAME": "Studio",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
        },
    )
    return completed.stdout.strip()


def _commit(repository: Path) -> str:
    _git(repository, "commit", "--allow-empty", "--message", "change")
    return _git(repository, "rev-parse", "HEAD")


def _preview_version(repository: Path, commit: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [_ROOT / "scripts" / "preview-version.sh", commit],
        capture_output=True,
        text=True,
        check=False,
        cwd=repository,
    )


def test_preview_versions_increase_across_releases(tmp_path: Path) -> None:
    _git(tmp_path, "init", "--quiet")
    released = _commit(tmp_path)
    _git(tmp_path, "tag", "--annotate", "v0.2.3", "--message", "release", released)
    first = _commit(tmp_path)
    candidate = _commit(tmp_path)
    before_tag = _preview_version(tmp_path, candidate).stdout.strip()
    _git(tmp_path, "tag", "--annotate", "v0.2.4", "--message", "release", candidate)
    after_release = _commit(tmp_path)

    versions = [
        _preview_version(tmp_path, first).stdout.strip(),
        before_tag,
        _preview_version(tmp_path, candidate).stdout.strip(),
        _preview_version(tmp_path, after_release).stdout.strip(),
    ]

    assert versions == ["0.2.4.dev1", "0.2.4.dev2", "0.2.4.dev2", "0.2.5.dev1"]
    assert Version(versions[1]) < Version("0.2.4") < Version(versions[3])


def test_preview_version_counts_from_the_previous_final_release(
    tmp_path: Path,
) -> None:
    _git(tmp_path, "init", "--quiet")
    released = _commit(tmp_path)
    _git(tmp_path, "tag", "--annotate", "v0.2.3", "--message", "release", released)
    candidate = _commit(tmp_path)
    _git(tmp_path, "tag", "--annotate", "v0.2.4-rc1", "--message", "rc", candidate)
    commit = _commit(tmp_path)

    completed = _preview_version(tmp_path, commit)

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "0.2.4.dev2"


def test_preview_version_requires_a_previous_release(tmp_path: Path) -> None:
    _git(tmp_path, "init", "--quiet")
    _commit(tmp_path)
    commit = _commit(tmp_path)

    completed = _preview_version(tmp_path, commit)

    assert completed.returncode == 1
    assert "No vX.Y.Z release tag precedes" in completed.stderr
