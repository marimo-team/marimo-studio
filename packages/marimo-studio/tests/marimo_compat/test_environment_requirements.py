from __future__ import annotations

from typing import cast

import pytest
from packaging.markers import default_environment
from packaging.version import Version

from marimo_studio._workspace.environment_requirements import (
    allows_source_checkout,
    bootstrap_launch_requirements,
    dependency_constraint,
    effective_dependency_requirement,
)
from marimo_studio.errors import ConfigurationError

pytestmark = pytest.mark.supported_python


def _environment(*, platform: str = "linux") -> dict[str, str]:
    environment = cast(dict[str, str], default_environment())
    environment["sys_platform"] = platform
    return environment


def _constraint(*requirements: str):
    return dependency_constraint(
        {"dependencies": list(requirements)},
        "marimo-studio",
    )


def _resolve(*requirements: str, platform: str = "linux") -> str:
    return effective_dependency_requirement(
        "marimo-studio==1.2.3",
        (_constraint(*requirements),),
        marker_environment=_environment(platform=platform),
    )


def test_inactive_marker_does_not_override_pin_url_or_extras() -> None:
    result = _resolve(
        'marimo-studio[remote] @ https://e.test/s.whl ; sys_platform == "win32"'
    )

    assert result == "marimo-studio==1.2.3"
    assert allows_source_checkout(
        Version("1.2.3"),
        (
            _constraint(
                'marimo-studio @ https://e.test/s.whl ; sys_platform == "win32"'
            ),
        ),
        marker_environment=_environment(),
    )
    inactive_source = dependency_constraint(
        {
            "dependencies": [
                'marimo-studio ; sys_platform == "win32"',
            ],
            "tool": {
                "uv": {
                    "sources": {
                        "marimo-studio": {"path": "./inactive-studio"},
                    },
                },
            },
        },
        "marimo-studio",
    )
    assert allows_source_checkout(
        Version("1.2.3"),
        (inactive_source,),
        marker_environment=_environment(),
    )


@pytest.mark.parametrize(
    ("platform", "expected"),
    (
        ("linux", "marimo-studio[linux]==1.2.3"),
        ("win32", "marimo-studio[windows]==2.0"),
    ),
)
def test_target_selects_one_complementary_marker_branch(
    platform: str,
    expected: str,
) -> None:
    result = _resolve(
        'marimo-studio[linux]==1.2.3 ; sys_platform != "win32"',
        'marimo-studio[windows]==2.0 ; sys_platform == "win32"',
        platform=platform,
    )

    assert result == expected


def test_equivalent_active_exact_pins_merge_extras() -> None:
    assert _resolve(
        "marimo-studio[first]==1.2.3", "marimo-studio[second]==1.2.3.0"
    ) == ("marimo-studio[first,second]==1.2.3")


def test_active_ranges_must_include_the_selected_pin() -> None:
    assert _resolve("marimo-studio>=1", "marimo-studio<2") == "marimo-studio==1.2.3"

    with pytest.raises(ConfigurationError, match="excludes"):
        _resolve("marimo-studio>=2")


def test_active_direct_source_is_marker_free_and_merges_extras() -> None:
    result = _resolve(
        'marimo-studio[source] @ https://e.test/s.whl ; sys_platform == "linux"'
    )

    assert result == "marimo-studio[source] @ https://e.test/s.whl"


def test_active_direct_sources_must_match() -> None:
    with pytest.raises(ConfigurationError, match="conflicting direct sources"):
        _resolve(
            "marimo-studio @ https://example.test/first.whl",
            "marimo-studio @ https://example.test/second.whl",
        )


def test_active_direct_source_and_version_range_are_rejected() -> None:
    with pytest.raises(ConfigurationError, match="direct source and version range"):
        _resolve(
            "marimo-studio @ https://example.test/studio.whl",
            "marimo-studio>=1",
        )


def test_active_direct_source_and_uv_source_are_rejected() -> None:
    constraint = dependency_constraint(
        {
            "dependencies": [
                "marimo-studio @ https://example.test/studio.whl",
            ],
            "tool": {
                "uv": {
                    "sources": {
                        "marimo-studio": {"path": "./studio"},
                    },
                },
            },
        },
        "marimo-studio",
    )

    with pytest.raises(ConfigurationError, match="direct source and uv source"):
        effective_dependency_requirement(
            "marimo-studio==1.2.3",
            (constraint,),
            marker_environment=None,
        )


def test_marker_resolution_requires_a_complete_target_environment() -> None:
    with pytest.raises(ConfigurationError, match="incomplete"):
        effective_dependency_requirement(
            "marimo-studio==1.2.3",
            (_constraint('marimo-studio==2 ; sys_platform == "win32"'),),
            marker_environment={"sys_platform": "linux"},
        )


def test_bootstrap_requirements_follow_saved_provider_identities() -> None:
    requirements = bootstrap_launch_requirements(
        studio_requirement="marimo-studio==1.2.3",
        provider_ids=("marimo-studio/react", "example-suite/report"),
        bundled_requirements={
            "marimo-studio/react": "marimo-studio[deno]",
        },
        notebook_metadata={
            "dependencies": [
                "marimo-studio==1.2.3",
                "example-suite[render]==4.5.6",
            ],
        },
        project_metadata=None,
        marker_environment=None,
    )

    assert requirements == (
        "marimo-studio[deno]==1.2.3",
        "example-suite[render]==4.5.6",
    )


def test_external_provider_requires_an_active_durable_dependency() -> None:
    with pytest.raises(ConfigurationError, match="add it to the notebook or project"):
        bootstrap_launch_requirements(
            studio_requirement="marimo-studio==1.2.3",
            provider_ids=("example-suite/report",),
            bundled_requirements={},
            notebook_metadata={
                "dependencies": ['example-suite==4.5.6 ; sys_platform == "win32"'],
            },
            project_metadata=None,
            marker_environment=_environment(platform="linux"),
        )
