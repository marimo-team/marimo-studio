"""Validate built-in provider identities and their install requirements."""

from __future__ import annotations

from importlib.metadata import metadata

import pytest
from packaging.requirements import Requirement

from marimo_studio.view_providers._host import provider_registry

pytestmark = pytest.mark.supported_python


def test_built_in_registration_labels_resolve_canonical_provider_ids() -> None:
    diagnostics = tuple(
        item
        for item in provider_registry().diagnostics()
        if item.distribution == "marimo-studio"
    )

    assert diagnostics
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
