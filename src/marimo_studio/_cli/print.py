"""Terminal output helpers shared by Studio commands."""

from __future__ import annotations

from typing import Any

import click


def echo(message: Any = "", *, err: bool = False) -> None:
    """Write text through Click's terminal-aware output stream."""
    click.echo(message, err=err)


def green(text: str) -> str:
    return click.style(text, fg="green", bold=True)


def bright_green(text: str) -> str:
    return click.style(text, fg="bright_green", bold=True)


def yellow(text: str) -> str:
    return click.style(text, fg="yellow", bold=True)


def red(text: str) -> str:
    return click.style(text, fg="red", bold=True)


def light_blue(text: str) -> str:
    return click.style(text, fg="bright_cyan", bold=True)
