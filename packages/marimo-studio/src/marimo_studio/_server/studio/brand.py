"""Render Marimo's compact brand mark in the Studio toolbar."""

from __future__ import annotations

from typing import cast

from htpy import Node, img

# Source: apps/web/public/mini-logo.png in the Marimo Cloud repository.
_MARIMO_MARK = (
    "data:image/png;base64,"
    "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"
)


def marimo_mark() -> Node:
    return cast(
        Node,
        img(
            class_="studio-mark",
            src=_MARIMO_MARK,
            alt="",
            aria_hidden="true",
        ),
    )
