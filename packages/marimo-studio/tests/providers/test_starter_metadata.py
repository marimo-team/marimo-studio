"""Starter presentation metadata and settings at the provider boundary."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import PurePosixPath
from typing import Any

import pytest

from marimo_studio.errors import ConfigurationError
from marimo_studio.view_providers import (
    ProviderStarter,
    SettingChoice,
    StarterSetting,
)
from marimo_studio.view_providers._host.operations.codec import (
    starter_context_from_payload,
    starter_context_payload,
    starters_from_payload,
    starters_payload,
)
from marimo_studio.view_providers._host.starters import (
    resolve_starter_settings,
    validate_starters,
    validate_view_title,
)

from ..provider_test_support import provider_starter_context

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
WEBP = b"RIFF\x00\x00\x00\x00WEBPVP8 " + b"\x00" * 32
ICON = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
    '<path d="M0 0h24v24H0z"/></svg>'
)
PAPER = StarterSetting(
    key="paper",
    label="Paper size",
    help="The page size of the PDF.",
    default="a4",
    choices=(SettingChoice("a4", "A4"), SettingChoice("us-letter", "US Letter")),
)
TOC = StarterSetting(
    key="toc",
    label="Table of contents",
    help="Lists the document's headings.",
    default=False,
)
SUBTITLE = StarterSetting(
    key="subtitle",
    label="Subtitle",
    help="A line under the title.",
    default="",
)


def _starter(**changes: Any) -> ProviderStarter:
    # Validation tests pass values that the record annotations do not allow.
    starter = ProviderStarter(
        "report",
        "Report",
        "A paged report.",
        (PurePosixPath("main.typ"),),
        format="PDF",
        icon=ICON,
        preview=WEBP,
        homepage="https://typst.app",
        settings=(PAPER, TOC, SUBTITLE),
    )
    return replace(starter, **changes)


def test_starter_metadata_and_settings_cross_the_process_boundary() -> None:
    starter = _starter(preview=PNG)

    payload = json.loads(json.dumps(starters_payload((starter,))))

    assert starters_from_payload(payload) == (starter,)
    assert payload[0]["settings"][0] == {
        "key": "paper",
        "label": "Paper size",
        "help": "The page size of the PDF.",
        "kind": "choice",
        "default": "a4",
        "choices": [
            {"value": "a4", "label": "A4"},
            {"value": "us-letter", "label": "US Letter"},
        ],
    }
    assert [setting["kind"] for setting in payload[0]["settings"]] == [
        "choice",
        "boolean",
        "text",
    ]


def test_starter_context_title_and_settings_cross_the_process_boundary(
    tmp_path,
) -> None:
    starter = _starter()
    context = provider_starter_context(
        tmp_path,
        view_name="quarterly-report",
        starter=starter,
        settings={"paper": "us-letter"},
    )

    restored = starter_context_from_payload(
        json.loads(json.dumps(starter_context_payload(context)))
    )

    assert restored.title == "Quarterly Report"
    assert dict(restored.settings) == {
        "paper": "us-letter",
        "toc": False,
        "subtitle": "",
    }


def test_valid_starter_metadata_passes_validation() -> None:
    starter = _starter()

    assert validate_starters("acme/report", (starter,)) == (starter,)


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"preview": b"GIF89a" + b"\x00" * 16}, "PNG, JPEG, or WebP"),
        ({"preview": PNG + b"\x00" * (2 * 1024 * 1024)}, "limits starter"),
        ({"preview": "not bytes"}, "preview to be bytes"),
        ({"icon": "<div></div>"}, "<svg> root"),
        ({"icon": "<svg"}, "SVG markup"),
        (
            {
                "icon": '<!DOCTYPE svg [<!ENTITY a "a">]><svg xmlns="http://www.w3.org/2000/svg"/>'
            },
            "SVG markup",
        ),
        ({"icon": f"<svg>{'x' * 20_000}</svg>"}, "at most"),
        ({"homepage": "http://typst.app"}, "https URL"),
        ({"homepage": "javascript:alert(1)"}, "https URL"),
        ({"format": "x" * 41}, "limits starter"),
        ({"settings": (PAPER, PAPER)}, "setting keys"),
        ({"settings": (replace(PAPER, key="Paper"),)}, "invalid starter setting key"),
        ({"settings": (replace(PAPER, default="legal"),)}, "name one of its choices"),
        ({"settings": (replace(TOC, choices=PAPER.choices),)}, "offer choices"),
        ({"settings": (replace(SUBTITLE, default="two\nlines"),)}, "one-line"),
    ],
)
def test_invalid_starter_metadata_is_a_provider_conformance_error(
    changes: dict[str, object], message: str
) -> None:
    with pytest.raises(ConfigurationError, match=message):
        validate_starters("acme/report", (_starter(**changes),))


def test_requested_settings_replace_defaults() -> None:
    assert dict(resolve_starter_settings(_starter(), {"toc": True})) == {
        "paper": "a4",
        "toc": True,
        "subtitle": "",
    }


@pytest.mark.parametrize(
    ("requested", "message"),
    [
        ({"columns": 2}, "has no setting 'columns'"),
        ({"paper": "legal"}, "does not accept 'legal'"),
        ({"toc": "yes"}, "does not accept 'yes'"),
        ({"subtitle": "two\nlines"}, "does not accept"),
    ],
)
def test_requested_settings_must_fit_the_starter(
    requested: dict[str, object], message: str
) -> None:
    with pytest.raises(ConfigurationError, match=message):
        resolve_starter_settings(_starter(), requested)


@pytest.mark.parametrize("title", ["", "   ", "two\nlines", "x" * 201, 42])
def test_view_titles_are_one_short_line(title: object) -> None:
    with pytest.raises(ConfigurationError, match="title"):
        validate_view_title(title)


def test_view_titles_are_trimmed() -> None:
    assert validate_view_title("  Quarterly report ") == "Quarterly report"
