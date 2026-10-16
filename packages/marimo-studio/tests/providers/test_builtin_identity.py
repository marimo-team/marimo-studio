"""Validate built-in provider identities and their install requirements."""

from __future__ import annotations

from importlib.metadata import distribution, metadata

import pytest
from packaging.requirements import Requirement

from marimo_studio.view_providers._host import provider_registry
from marimo_studio.view_providers._host.registry import ENTRY_POINT_GROUP

pytestmark = pytest.mark.supported_python


def test_built_in_registration_labels_resolve_canonical_provider_ids() -> None:
    diagnostics = tuple(
        item
        for item in provider_registry().diagnostics()
        if item.distribution == "marimo-studio"
    )

    declared = {
        entry_point.name
        for entry_point in distribution("marimo-studio").entry_points.select(
            group=ENTRY_POINT_GROUP
        )
    }
    assert declared
    assert {item.registration for item in diagnostics} == declared
    for item in diagnostics:
        assert item.provider_key == f"marimo-studio/{item.registration}"


def test_built_in_provider_requirements_name_declared_studio_extras() -> None:
    extras = set(metadata("marimo-studio").get_all("Provides-Extra") or ())
    requirements = [
        Requirement(provider.requirement)
        for provider, _starter in provider_registry().starter_records()
        if provider.distribution == "marimo-studio"
    ]

    assert requirements
    for requirement in requirements:
        assert requirement.name == "marimo-studio"
        assert requirement.extras <= extras, requirement
